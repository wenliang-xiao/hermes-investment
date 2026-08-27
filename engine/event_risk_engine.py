"""事件风险脉冲 + 决策建议 + 影子记录。

核心规则（calc_event_risk / build_event_advice / build_shadow_entry）为纯函数，
行情异动获取（get_market_moves）为 IO 层，本地限频时静默降级。
阈值按飞书评审共识保守取值（Trellis 修订第六、七节）。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

GOLD_1D_THRESHOLD = 2.0
GOLD_5D_THRESHOLD = 5.0
NASDAQ_1D_THRESHOLD = -3.0
A_CHAIN_1D_THRESHOLD = -2.0

# 光模块龙头，NVDA 算力链 A股映射代表（跨市场共振的 A股侧标的）
_A_CHAIN_SYMBOL = "300308"

_LEVEL_TO_ADJUST = {"none": 0.0, "moderate": 0.3, "high": 0.6, "extreme": 1.0}


def _event_in_window(date_str: str, hours: int) -> bool:
    try:
        d = datetime.strptime(str(date_str), "%Y-%m-%d").date()
    except ValueError:
        return False
    today = datetime.now().date()
    horizon = today + timedelta(hours=hours)
    return today <= d <= horizon


def calc_event_risk(calendar: dict, market_moves: dict | None = None, hours: int = 48) -> dict:
    """计算事件避险脉冲。

    Args:
        calendar: event_calendar.get_future_events() 的返回 dict。
        market_moves: 避险异动 dict，如 {"gold_1d_pct", "gold_5d_pct",
            "nasdaq_1d_pct", "a_chain_1d_pct"}。
        hours: 事件窗口（小时），默认 48。

    Returns:
        {"level", "triggered_by", "risk_adjust", "captions"}
    """
    market_moves = market_moves or {}
    strong: list[str] = []
    weak: list[str] = []

    for ev in calendar.get("events", []):
        if not _event_in_window(ev.get("date", ""), hours):
            continue
        title = ev.get("title", ev.get("symbol", "事件"))
        if ev.get("risk_level") == "high":
            strong.append(f"未来{hours}h内 {title}")
        elif ev.get("risk_level") == "med":
            weak.append(f"未来{hours}h内 {title}")

    gold_1d = market_moves.get("gold_1d_pct")
    gold_5d = market_moves.get("gold_5d_pct")
    if gold_1d is not None and gold_1d > GOLD_1D_THRESHOLD:
        strong.append(f"黄金单日急拉 {gold_1d}%>{GOLD_1D_THRESHOLD}%")
    elif gold_5d is not None and gold_5d > GOLD_5D_THRESHOLD:
        strong.append(f"黄金5日累计 {gold_5d}%>{GOLD_5D_THRESHOLD}%")

    nasdaq_1d = market_moves.get("nasdaq_1d_pct")
    a_chain_1d = market_moves.get("a_chain_1d_pct")
    if (nasdaq_1d is not None and a_chain_1d is not None
            and nasdaq_1d < NASDAQ_1D_THRESHOLD and a_chain_1d < A_CHAIN_1D_THRESHOLD):
        strong.append(f"跨市场共振：纳指 {nasdaq_1d}% + A股映射链 {a_chain_1d}%")

    if len(strong) >= 2:
        level = "extreme"
    elif len(strong) == 1:
        level = "high"
    elif weak:
        level = "moderate"
    else:
        level = "none"

    triggered_by = strong + weak
    return {
        "level": level,
        "triggered_by": triggered_by,
        "risk_adjust": _LEVEL_TO_ADJUST[level],
        "captions": "；".join(triggered_by) if triggered_by else "无事件避险信号",
    }


_LEVEL_TO_ADVICE = {
    "extreme": {"action": "清仓建议", "position_adjust": 0.0, "block_buy": True, "havens": ["黄金ETF", "白银"]},
    "high": {"action": "降仓建议", "position_adjust": 0.3, "block_buy": True, "havens": ["黄金ETF"]},
    "moderate": {"action": "控制仓位", "position_adjust": 0.6, "block_buy": False, "havens": []},
    "none": {"action": "维持", "position_adjust": 1.0, "block_buy": False, "havens": []},
}


def build_event_advice(event_risk: dict) -> dict:
    """把事件风险脉冲转成决策层建议（不接实盘，仅产出建议动作）。

    Args:
        event_risk: calc_event_risk() 的返回 dict。

    Returns:
        {"action", "position_adjust", "block_buy", "havens", "level", "triggered_by"}
    """
    level = event_risk.get("level", "none")
    base = _LEVEL_TO_ADVICE.get(level, _LEVEL_TO_ADVICE["none"])
    return {
        "action": base["action"],
        "position_adjust": base["position_adjust"],
        "block_buy": base["block_buy"],
        "havens": list(base["havens"]),
        "level": level,
        "triggered_by": event_risk.get("triggered_by", []),
    }


def build_shadow_entry(date_str: str, event_risk: dict, advice: dict, actual_snapshot: dict) -> dict:
    """组装一条影子运行记录条目（每日记录脉冲 + 建议 + 实际持仓快照）。

    hedged_pnl = actual_realized_pnl × position_adjust，为线性简化假设
    （假设盈亏随仓位比例缩减，避险资产损益未计入），供累积后对比
    「避险版 vs 实际」损益。

    Args:
        date_str: 日期字符串 "YYYY-MM-DD"。
        event_risk: calc_event_risk() 的返回 dict。
        advice: build_event_advice() 的返回 dict。
        actual_snapshot: 实际持仓快照 {"total_value", "position_count", "realized_pnl"}。

    Returns:
        影子记录条目 dict。
    """
    actual_pnl = actual_snapshot.get("realized_pnl", 0)
    position_adjust = advice.get("position_adjust", 1.0)
    return {
        "date": date_str,
        "level": event_risk.get("level"),
        "triggered_by": event_risk.get("triggered_by", []),
        "action": advice.get("action"),
        "position_adjust": position_adjust,
        "havens": advice.get("havens", []),
        "actual_total_value": actual_snapshot.get("total_value"),
        "actual_position_count": actual_snapshot.get("position_count", 0),
        "actual_realized_pnl": actual_pnl,
        "hedged_pnl": round(actual_pnl * position_adjust, 2),
    }


def _pct_change(closes: list, lookback: int) -> float | None:
    """从收盘价序列算 lookback 日涨跌幅（%）。数据不足或前值为 0 返回 None。"""
    if len(closes) < lookback + 1:
        return None
    prev = closes[-lookback - 1]
    curr = closes[-1]
    if not prev:
        return None
    return (curr - prev) / prev * 100


def get_market_moves() -> dict:
    """获取避险异动（黄金单日/5日、纳指单日、A股映射链单日涨跌幅%）。限频/失败静默降级为空 dict。"""
    import yfinance as yf

    moves: dict = {}
    try:
        df = yf.Ticker("GC=F").history(period="1mo")
        if df is not None and not df.empty:
            closes = df["Close"].tolist()
            gold_1d = _pct_change(closes, 1)
            gold_5d = _pct_change(closes, 5)
            if gold_1d is not None:
                moves["gold_1d_pct"] = round(gold_1d, 2)
            if gold_5d is not None:
                moves["gold_5d_pct"] = round(gold_5d, 2)
    except Exception as exc:  # noqa: BLE001 - 限频降级
        logger.warning("[event_risk] 黄金异动获取失败: %s", exc)

    try:
        df = yf.Ticker("^IXIC").history(period="5d")
        if df is not None and not df.empty:
            nasdaq_1d = _pct_change(df["Close"].tolist(), 1)
            if nasdaq_1d is not None:
                moves["nasdaq_1d_pct"] = round(nasdaq_1d, 2)
    except Exception as exc:  # noqa: BLE001 - 限频降级
        logger.warning("[event_risk] 纳指异动获取失败: %s", exc)

    try:
        from data.sources.akshare_source import get_rt_em

        rt = get_rt_em(_A_CHAIN_SYMBOL)
        if rt and rt.get("change_pct") is not None:
            moves["a_chain_1d_pct"] = round(rt["change_pct"], 2)
    except Exception as exc:  # noqa: BLE001 - 行情源降级
        logger.warning("[event_risk] A股映射链异动获取失败: %s", exc)

    return moves


def load_latest_event_risk(path=None) -> dict | None:
    """读 shadow_event_history.json 最新一条影子记录，无记录或非当天返回 None。"""
    import json
    import os
    from pathlib import Path

    if path is None:
        path = Path(__file__).parent.parent / "data" / "shadow_event_history.json"
    if not os.path.exists(path):
        logger.warning("[event_risk] 影子记录不存在: %s（run_event_shadow.py 未运行，事件拦截不生效）", path)
        return None
    try:
        with open(path) as f:
            history = json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("[event_risk] 影子记录读取失败: %s", path)
        return None
    if not history or not isinstance(history, list):
        return None
    latest = history[-1]
    if latest.get("date") != datetime.now().strftime("%Y-%m-%d"):
        logger.warning("[event_risk] 影子记录非当天(%s)，事件拦截不生效", latest.get("date"))
        return None
    return latest


def event_blocks_buy(event_risk: dict | None) -> bool:
    """事件风险是否禁用 BUY（level ≥ high）。"""
    if not event_risk:
        return False
    return event_risk.get("level") in ("high", "extreme")
