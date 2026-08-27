"""事件日历适配器 — 未来 N 天财报/IPO/制裁/央行事件。

数据源优先级（WS0 验证结论）：
1. 手工 json（data/event_calendar.json）— 确定性基底，人工维护未来事件
2. yfinance earnings_dates — 美股未来财报日（本地可能被 Yahoo 限频，生产环境可用）

akshare 业绩预告/快报为「已披露」语义（非未来），故不进「未来事件日历」，
留给 WS2 事件脉冲做暴雷识别。akshare「预约披露时间」接口（stock_yysj_em）
当前有解析 bug，列为二期增强。

契约（见 get_future_events）：status 三态区分「有数据 / 源可用但无事件 / 源不可用」，
落实验收标准「无数据时明确报数据缺失而非假全零」。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

_VALID_TYPES = {"earnings", "ipo", "rate_sanction", "central_bank"}
_VALID_RISK = {"high", "med", "low"}

_MANUAL_PATH = Path(__file__).parent.parent / "data" / "event_calendar.json"

# 核心美股财报标的（LDS 算力链案例相关），后续应从 config.WATCHLIST 提取
_US_EARNINGS_SYMBOLS = ["NVDA", "TSM", "MU", "AVGO", "AMD", "ANET", "COHR"]


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _manual_available() -> bool:
    return _MANUAL_PATH.exists()


def _load_manual_events() -> list[dict]:
    if not _MANUAL_PATH.exists():
        return []
    try:
        data = json.loads(_MANUAL_PATH.read_text(encoding="utf-8"))
        return data.get("events", []) if isinstance(data, dict) else []
    except Exception as exc:  # noqa: BLE001 - 手工文件损坏时降级为空
        logger.warning("[event_calendar] 手工日历读取失败: %s", exc)
        return []


def _fetch_us_earnings(days: int) -> list[dict]:
    """美股未来财报日（yfinance earnings_dates）。限频/失败时静默降级。"""
    import time
    import yfinance as yf

    today = datetime.now().date()
    horizon = today + timedelta(days=days)
    events: list[dict] = []
    for i, sym in enumerate(_US_EARNINGS_SYMBOLS):
        if i > 0:
            time.sleep(1)
        try:
            ed = yf.Ticker(sym).get_earnings_dates(limit=4)
            if ed is None or ed.empty:
                continue
            for idx in ed.index:
                d = getattr(idx, "date", None)
                d = d() if callable(d) else d
                if d is None or not (today <= d <= horizon):
                    continue
                events.append({
                    "date": d.strftime("%Y-%m-%d"),
                    "symbol": sym,
                    "type": "earnings",
                    "title": f"{sym} 财报",
                    "risk_level": "high",
                })
        except Exception as exc:  # noqa: BLE001 - 限频/网络抖动逐标的降级
            logger.warning("[event_calendar] %s 财报日获取失败: %s", sym, exc)
    return events


def _filter_window(events: list[dict], days: int) -> list[dict]:
    """仅保留 [今天, 今天+days] 窗口内的事件。"""
    today = datetime.now().date()
    horizon = today + timedelta(days=days)
    kept: list[dict] = []
    for ev in events:
        try:
            d = datetime.strptime(str(ev.get("date", "")), "%Y-%m-%d").date()
        except ValueError:
            continue
        if today <= d <= horizon:
            kept.append(ev)
    return kept


def _dedupe_and_validate(events: list[dict]) -> list[dict]:
    """去重（date+symbol+type）并校验字段/枚举合法性。"""
    seen: set[tuple] = set()
    valid: list[dict] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") not in _VALID_TYPES or ev.get("risk_level") not in _VALID_RISK:
            continue
        if not all(k in ev for k in ("date", "symbol", "type", "title", "risk_level")):
            continue
        key = (ev["date"], ev["symbol"], ev["type"])
        if key not in seen:
            seen.add(key)
            valid.append(ev)
    return valid


def get_future_events(days: int = 7) -> dict:
    """获取未来 N 天事件日历。

    Returns:
        {
            "status": "ok" | "empty" | "missing",
            "events": [{"date", "symbol", "type", "title", "risk_level"}, ...],
            "source": str,    # 实际生效的数据源，如 "manual_json" / "manual_json+yfinance" / "none"
            "data_age": str,  # 数据抓取日期（降级 json 时尤其重要）
        }
    """
    events: list[dict] = []
    sources: list[str] = []

    if _manual_available():
        events.extend(_load_manual_events())
        sources.append("manual_json")

    try:
        us_events = _fetch_us_earnings(days)
        if us_events:
            events.extend(us_events)
            sources.append("yfinance")
    except Exception as exc:  # noqa: BLE001 - yfinance 整体失败降级
        logger.warning("[event_calendar] yfinance 源失败: %s", exc)

    valid = _dedupe_and_validate(_filter_window(events, days))

    if valid:
        status = "ok"
    elif sources:
        status = "empty"
    else:
        status = "missing"

    return {
        "status": status,
        "events": valid,
        "source": "+".join(sources) if sources else "none",
        "data_age": _today_str(),
    }
