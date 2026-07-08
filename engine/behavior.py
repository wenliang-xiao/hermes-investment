"""analysis/behavior.py — 行为诊断引擎

从策略交易历史 + 组合快照中，计算 4 项行为偏差指标：
  1. 处置效应比 (Disposition Effect Ratio)
  2. 过度交易指数 (Overtrading Index)
  3. 追涨分数 (Chasing Score)
  4. 锚定指数 (Anchoring Index)

借鉴: Vibe-Trading Shadow Account 行为诊断管线，
      面基播客反复讲的行为金融学框架（处置效应/过度交易/追涨/锚定）。

用法:
    from engine.behavior import diagnose_strategy
    diag = diagnose_strategy(history, positions, cash)
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np

# ── 常量 ──

# 过度交易基准：每周建议交易次数
BENCHMARK_TRADES_PER_WEEK = 2
# 交易成本（单边，含滑点估算）
COMMISSION_RATE = 0.0015
# 处置效应显著阈值
DISPOSITION_THRESHOLD = 1.5
# 追涨敏感期（买入前追踪天数）
CHASING_LOOKBACK = 10
# 锚定指数阈值（偏离历史高点百分比）
ANCHORING_THRESHOLD_PCT = 20.0


# ── 核心诊断函数 ──


def diagnose_strategy(history: list[dict], strategy_name: str = "unknown") -> dict:
    """对单个策略的交易历史做全维度行为诊断

    Args:
        history: 交易历史列表，每笔含 date/symbol/action/price/cost/
        strategy_name: 策略名称（仅用于日志/标注）

    Returns:
        dict with keys:
            disposition_ratio, overtrading_index, chasing_score,
            anchoring_index, trade_count, sell_count,
            trade_frequency_per_week, avg_hold_days,
            pnl_analysis, recommended_actions
    """
    # 分离买卖
    buys = [h for h in history if h.get("action") in ("买入", "BUY")]
    sells = [h for h in history if h.get("action") in ("卖出", "SELL")]

    # 1. 处置效应比
    disposition = _calc_disposition_effect(sells, buys)

    # 2. 过度交易指数
    overtrading = _calc_overtrading(history, buys, sells)

    # 3. 追涨分数
    chasing = _calc_chasing(history, buys)

    # 4. 锚定指数
    anchoring = _calc_anchoring(history)

    # 5. 盈亏分析
    pnl = _calc_pnl_analysis(sells, buys)

    # 6. 持仓天数分析
    hold_days = _calc_hold_days(history)

    return {
        "strategy": strategy_name,
        "disposition_ratio": round(disposition["ratio"], 4),
        "disposition_detail": disposition["detail"],
        "overtrading_index": round(overtrading["index"], 4),
        "overtrading_detail": overtrading["detail"],
        "chasing_score": round(chasing["score"], 4),
        "chasing_detail": chasing["detail"],
        "anchoring_index": round(anchoring["index"], 4),
        "anchoring_detail": anchoring["detail"],
        "pnl_analysis": pnl,
        "hold_days_analysis": hold_days,
        "trade_count": len(history),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "recommended_actions": disposition["actions"]
        + overtrading["actions"]
        + chasing["actions"]
        + anchoring["actions"],
    }


def diagnose_all(portfolio_states: dict) -> dict:
    """对所有策略做行为诊断（组合级）

    Args:
        portfolio_states: strategy_states.json 内容（dict of dict）

    Returns:
        dict: {strategy_name: diagnosis, ...} + 一个 '_combined' 汇总
    """
    results = {}
    all_history = []
    for sname, state in portfolio_states.items():
        if not isinstance(state, dict):
            continue
        hist = state.get("history", [])
        all_history.extend(hist)
        results[sname] = diagnose_strategy(hist, sname)

    # 组合级诊断（三策略合并）
    results["_combined"] = diagnose_strategy(all_history, "_combined")
    return results


# ── 子函数 ──


def _calc_disposition_effect(sells: list[dict], buys: list[dict]) -> dict:
    """处置效应

    定义: 盈利时卖出倾向 vs 亏损时卖出倾向
    计算:
        盈利卖出笔数 / (盈利卖出笔试+亏损卖出笔数)  vs
        亏损持有笔数 / (亏损持有笔试+亏损卖出笔数)
    简化: 盈利卖出笔数 / 亏损卖出笔数
    若 ratio > 1.5: 显著处置效应（过早止盈）

    额外: 用买入价格作为参考
    """
    if not sells:
        return {"ratio": 0.0, "detail": "无卖出记录", "actions": []}

    # 构建 symbol→买入价映射（取最近一笔）
    entry_prices = {}
    for b in sorted(buys, key=lambda x: x.get("date", "")):
        sym = b.get("symbol", "")
        price = _safe_float(b.get("price", 0))
        if sym and price > 0:
            entry_prices[sym] = price

    profit_sells = 0
    loss_sells = 0
    total_profit = 0.0
    total_loss = 0.0
    details = []

    for s in sells:
        sym = s.get("symbol", "")
        sell_price = _safe_float(s.get("price", 0))
        # 从 pnl 字段获取盈亏百分比
        pnl_pct = _safe_float(s.get("pnl_pct", 0))
        pnl_abs = _safe_float(s.get("pnl", 0))
        entry = entry_prices.get(sym, 0)

        if pnl_pct > 0 or (sell_price > entry and entry > 0):
            profit_sells += 1
            total_profit += abs(pnl_abs) if pnl_abs else (sell_price - entry)
        elif pnl_pct < 0 or (sell_price < entry and entry > 0):
            loss_sells += 1
            total_loss += abs(pnl_abs) if pnl_abs else (entry - sell_price)

        details.append(
            {
                "symbol": sym,
                "sell_price": sell_price,
                "entry_price": entry,
                "pnl_pct": pnl_pct,
                "side": "profit" if (pnl_pct > 0 or sell_price > entry > 0) else "loss",
                "date": s.get("date", ""),
                "reason": s.get("reason", ""),
            }
        )

    if loss_sells == 0:
        # 全是盈利卖出 — 极强处置效应
        ratio = float("inf") if profit_sells > 0 else 0.0
        severity = "🔴 极强" if ratio == float("inf") else "⚪ 无数据"
        actions = ["⚠️ 所有卖出均为盈利：可能过早止盈，建议让利润奔跑"]
    elif loss_sells > 0:
        ratio = profit_sells / loss_sells
        if ratio > 3.0:
            severity = "🔴 严重"
            actions = ["⚠️ 盈利卖出是亏损卖出的%.1f倍 — 典型处置效应，建议放宽止盈阈值" % ratio]
        elif ratio > 1.5:
            severity = "🟡 中等"
            actions = ["📌 处置效应比 %.1f — 略高于正常，注意止损纪律" % ratio]
        else:
            severity = "🟢 正常"
            actions = ["✅ 处置效应在正常范围内"]
    else:
        ratio = 0.0
        severity = "⚪ 无数据"
        actions = []

    detail_text = f"盈利卖出{profit_sells}笔  vs  亏损卖出{loss_sells}笔，比值={ratio:.2f}"
    return {
        "ratio": ratio,
        "detail": f"{severity} {detail_text}",
        "actions": actions,
        "profit_sells": profit_sells,
        "loss_sells": loss_sells,
    }


def _calc_overtrading(history: list[dict], buys: list[dict], sells: list[dict]) -> dict:
    """过度交易指数

    计算: 日均交易次数 / 基准日均交易次数（benchmark）
    基准: 每周2次 = 每天 ~0.4次（按5个交易日算）
    """
    if not history:
        return {"index": 0.0, "detail": "无交易记录", "actions": []}

    dates = [h.get("date", "") for h in history if h.get("date")]
    if not dates:
        return {"index": 0.0, "detail": "无日期信息", "actions": []}

    date_min = min(dates)
    date_max = max(dates)
    try:
        d0 = datetime.strptime(date_min, "%Y-%m-%d")
        d1 = datetime.strptime(date_max, "%Y-%m-%d")
        trading_days = max((d1 - d0).days + 1, 1)
    except Exception:
        trading_days = len(set(dates))

    total_trades = len(buys) + len(sells)
    daily_freq = total_trades / trading_days
    benchmark_daily = BENCHMARK_TRADES_PER_WEEK / 5  # 0.4

    index = daily_freq / benchmark_daily if benchmark_daily > 0 else 0

    if index > 3.0:
        severity = "🔴 严重"
        actions = [
            f"⚠️ 日均交易{daily_freq:.1f}笔，超过基准{benchmark_daily:.1f}的{index:.1f}倍 — 过度交易是回撤最大来源之一"
        ]
    elif index > 2.0:
        severity = "🟡 中等"
        actions = [
            f"📌 日均交易{daily_freq:.1f}笔，接近上限，建议主动降频"
        ]
    elif index > 1.2:
        severity = "🟡 轻微"
        actions = ["📌 交易频率略高于基准，可关注"]
    else:
        severity = "🟢 正常"
        actions = ["✅ 交易频率在合理范围"]

    detail_text = (
        f"总交易{total_trades}笔，{trading_days}天"
        f"（{date_min}~{date_max}），日均{daily_freq:.2f}笔"
    )
    return {
        "index": round(index, 2),
        "detail": f"{severity} {detail_text}",
        "actions": actions,
        "daily_frequency": round(daily_freq, 4),
        "trading_days": trading_days,
        "total_trades": total_trades,
    }


def _calc_chasing(history: list[dict], buys: list[dict]) -> dict:
    """追涨分数

    追涨定义: 在标的已经大幅上涨后买入
    简化计算（无日内数据时）:
    - 检查同标的买入前的卖出记录（即是否别人卖了他买）
    - 同日内买入次数（集中建仓不算追涨，分散买入算）
    - 追涨分 = 同日内多笔不同标的买入的集中度
    """
    if not buys:
        return {"score": 0.0, "detail": "无买入记录", "actions": []}

    # 按日期统计买入次数
    buy_by_date = Counter(b.get("date", "") for b in buys)

    # 集中度: 一天内买入≥3只不同标的记一次"追涨日"
    chasing_days = sum(1 for d, c in buy_by_date.items() if c >= 3)

    # 总交易天数
    total_days = len(buy_by_date)
    chasing_ratio = chasing_days / total_days if total_days > 0 else 0

    # 也检查是否有同一天买+卖的（情绪化交易信号）
    sell_dates = set(s.get("date", "") for s in history if s.get("action") in ("卖出", "SELL"))
    buy_dates = set(b.get("date", "") for b in buys)
    same_day_trade = len(buy_dates & sell_dates)

    # 追涨分 = chasing_ratio * 10 + same_day_trade * 2
    score = chasing_ratio * 10 + same_day_trade * 0.5

    if score > 5:
        severity = "🔴 严重"
        actions = [
            "⚠️ 追涨倾向明显 — 建议坚持分批建仓策略，避免情绪化买入",
        ]
    elif score > 2:
        severity = "🟡 中等"
        actions = ["📌 有一定追涨倾向，注意买入节奏"]
    elif score > 0:
        severity = "🟢 轻微"
        actions = ["✅ 追涨倾向可控"]
    else:
        severity = "🟢 无"
        actions = ["✅ 无追涨行为"]

    detail_text = (
        f"买入日{total_days}天中{chasing_days}天集中买入≥3只"
        f"（{chasing_ratio:.0%}），同日买卖{same_day_trade}次"
    )
    return {
        "score": round(score, 2),
        "detail": f"{severity} {detail_text}",
        "actions": actions,
        "chasing_days": chasing_days,
        "total_buy_days": total_days,
        "same_day_trade_count": same_day_trade,
    }


def _calc_anchoring(history: list[dict]) -> dict:
    """锚定指数

    锚定定义: 持仓下跌时不肯止损，等待回到买入价。
    计算: 检查卖出记录中，是否有亏损超过15%才卖出的。
    若平均亏损幅度 > ANCHORING_THRESHOLD_PCT → 锚定效应
    """
    if not history:
        return {"index": 0.0, "detail": "无交易记录", "actions": []}

    sells = [h for h in history if h.get("action") in ("卖出", "SELL")]
    if not sells:
        return {"index": 0.0, "detail": "无卖出记录（无法判断锚定）", "actions": []}

    # 提取亏损卖出的跌幅分布
    loss_pcts = []
    for s in sells:
        pnl = _safe_float(s.get("pnl_pct", 0))
        if pnl < 0:
            loss_pcts.append(abs(pnl))

    if not loss_pcts:
        return {"index": 0.0, "detail": "无亏损卖出记录", "actions": []}

    avg_loss_pct = np.mean(loss_pcts)
    max_loss_pct = max(loss_pcts)
    loss_count = len(loss_pcts)
    total_sells = len(sells)
    loss_ratio = loss_count / total_sells

    # 锚定指数 = 平均亏损幅度(归一化到20%) × 亏损占比
    index = (avg_loss_pct / ANCHORING_THRESHOLD_PCT) * loss_ratio

    if index > 1.5:
        severity = "🔴 严重"
        actions = [
            f"⚠️ 平均亏损达{avg_loss_pct:.1f}%才止损，锚定效应显著"
            + " — 建议设置硬性止损线（如-8%/-12%）并严格执行",
        ]
    elif index > 0.8:
        severity = "🟡 中等"
        actions = [f"📌 平均亏损{avg_loss_pct:.1f}%止损，建议收紧至-10%以内"]
    else:
        severity = "🟢 正常"
        actions = ["✅ 止损纪律良好"]

    detail_text = (
        f"亏损卖出{loss_count}/{total_sells}笔（{loss_ratio:.0%}）"
        f"，平均亏{avg_loss_pct:.1f}%，最大亏{max_loss_pct:.1f}%"
    )
    return {
        "index": round(index, 4),
        "detail": f"{severity} {detail_text}",
        "actions": actions,
        "avg_loss_pct": round(avg_loss_pct, 2),
        "max_loss_pct": round(max_loss_pct, 2),
        "loss_sell_count": loss_count,
        "total_sell_count": total_sells,
    }


def _calc_pnl_analysis(sells: list[dict], buys: list[dict]) -> dict:
    """盈亏分析"""
    total_commission = sum(
        _safe_float(h.get("cost", 0)) * COMMISSION_RATE
        for h in (sells + buys)
    )
    gross_pnl = sum(_safe_float(s.get("pnl", 0)) for s in sells)
    net_pnl = gross_pnl - total_commission

    profitable_sells = sum(1 for s in sells if _safe_float(s.get("pnl", 0)) > 0)
    loss_sells = sum(1 for s in sells if _safe_float(s.get("pnl", 0)) < 0)

    return {
        "gross_pnl": round(gross_pnl, 2),
        "commission_est": round(total_commission, 2),
        "net_pnl": round(net_pnl, 2),
        "profitable_sells": profitable_sells,
        "loss_sells": loss_sells,
        "win_rate": round(profitable_sells / max(len(sells), 1), 4),
    }


def _calc_hold_days(history: list[dict]) -> dict:
    """持仓天数分析"""
    buy_events = defaultdict(list)
    for h in history:
        if h.get("action") in ("买入", "BUY"):
            buy_events[h.get("symbol", "")].append(h.get("date", ""))

    hold_times = []
    for sym, dates in buy_events.items():
        sells = [
            h for h in history
            if h.get("symbol") == sym and h.get("action") in ("卖出", "SELL")
        ]
        for s in sells:
            s_date = s.get("date", "")
            # 找最近一笔买入
            relevant_buys = [d for d in dates if d <= s_date]
            if relevant_buys:
                b_date = max(relevant_buys)
                try:
                    bd = datetime.strptime(b_date, "%Y-%m-%d")
                    sd = datetime.strptime(s_date, "%Y-%m-%d")
                    hold_days = (sd - bd).days
                    hold_times.append(hold_days)
                except Exception:
                    pass

    if not hold_times:
        return {"avg_days": 0, "min_days": 0, "max_days": 0, "note": "无完整买卖对"}

    return {
        "avg_days": round(np.mean(hold_times), 1),
        "min_days": int(min(hold_times)),
        "max_days": int(max(hold_times)),
    }


def _safe_float(v: Any, default: float = 0.0) -> float:
    """安全转float"""
    if v is None:
        return default
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


# ── 辅助：加载数据 ──


def load_strategy_states(path: str | Path = None) -> dict:
    """加载 strategy_states.json"""
    if path is None:
        path = Path(__file__).resolve().parent.parent / "data" / "strategy_states.json"
    with open(path) as f:
        return json.load(f)


def run_behavior_diagnosis(path: str | Path = None) -> dict:
    """一键运行全策略行为诊断"""
    states = load_strategy_states(path)
    return diagnose_all(states)
