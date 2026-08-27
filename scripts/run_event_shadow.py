"""
每日影子运行 — 记录事件避险脉冲 + 建议 + 实际持仓快照，累积证据判断避险是否有效。

方法论：事件驱动不可历史回测（Bayes 在线更新），故影子前向验证。
每日追加一条 {脉冲, 建议, 实际持仓快照} 到 data/shadow_event_history.json，
累积 1-3 个月后离线分析「避险建议是否跑赢实际持仓」。
"""
import sys, os, json, functools
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

import logging

from engine.event_calendar import get_future_events
from engine.event_risk_engine import calc_event_risk, build_event_advice, build_shadow_entry, get_market_moves

logger = logging.getLogger(__name__)

HISTORY_FILE = os.path.join(_PROJECT_DIR, "data", "shadow_event_history.json")


def load_history() -> list:
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            pass
    return []


def save_history(entries: list):
    with open(HISTORY_FILE, "w") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


def _load_actual_snapshot() -> dict:
    try:
        from output.shadow_account import get_shadow_summary, load_shadow

        summary = get_shadow_summary()
        book = load_shadow()
        return {
            "total_value": summary.get("total_value"),
            "position_count": summary.get("count", 0),
            "realized_pnl": book.get("realized_pnl", 0),
        }
    except Exception as exc:  # noqa: BLE001 - 本地缺 investment_system 包时降级为缺失标记
        logger.warning("[event_shadow] shadow_account 读取失败（数据缺失）: %s", exc)
        return {"total_value": None, "position_count": 0, "realized_pnl": 0}


def run_shadow() -> dict:
    """执行一次影子运行，返回本次记录条目。"""
    date_str = datetime.now().strftime("%Y-%m-%d")

    calendar = get_future_events(days=7)
    market_moves = get_market_moves()
    event_risk = calc_event_risk(calendar, market_moves, hours=48)
    advice = build_event_advice(event_risk)

    actual_snapshot = _load_actual_snapshot()

    entry = build_shadow_entry(date_str, event_risk, advice, actual_snapshot)

    history = load_history()
    history.append(entry)
    save_history(history)
    return entry


if __name__ == "__main__":
    print = functools.partial(print, flush=True)
    entry = run_shadow()
    print(json.dumps(entry, ensure_ascii=False, indent=2))
