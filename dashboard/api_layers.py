"""
六层指标 API — /api/v2/layers/status, layers/macro, layers/allocation
"""
import json, os
from datetime import datetime, date, timedelta
from fastapi import APIRouter
from pathlib import Path

router = APIRouter(tags=["layers"])

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@router.get("/api/v2/layers/status")
async def layers_status():
    """L1-L6 六层聚合状态"""
    from engine.layer_status import LayerStatus

    ls = LayerStatus()
    macro = _load_macro()
    positions = _load_all_positions()
    pool = _load_pool()
    trades = _load_trades()

    result = ls.get_all(
        macro_state=macro,
        positions=positions,
        pool_data=pool,
        trades_this_week=trades,
    )
    return {"status": "ok", "layers": result}


@router.get("/api/v2/layers/macro")
async def layers_macro():
    """L1 宏观详情"""
    from engine.layer_status import LayerStatus
    ls = LayerStatus()
    macro = _load_macro()
    return {"status": "ok", "l1_macro": ls._l1_macro(macro)}


@router.get("/api/v2/layers/allocation")
async def layers_allocation():
    """L2 配置详情"""
    from engine.layer_status import LayerStatus
    ls = LayerStatus()
    positions = _load_all_positions()
    return {"status": "ok", "l2_allocation": ls._l2_allocation(positions)}


def _load_macro() -> dict:
    path = DATA / "macro_engine_cache.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


def _load_all_positions() -> list:
    path = DATA / "strategy_states.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        pos_list = []
        for sname, sinfo in data.items():
            if isinstance(sinfo, dict):
                for sym, ps in sinfo.get("positions", {}).items():
                    if isinstance(ps, dict):
                        pos_list.append({
                            "symbol": ps.get("symbol", sym),
                            "entry_price": ps.get("entry_price", 0),
                            "current_price": ps.get("current_price", 0),
                            "quantity": ps.get("quantity", 0),
                            "market_value": ps.get("current_price", 0) * ps.get("quantity", 0),
                        })
        return pos_list
    except (json.JSONDecodeError, KeyError):
        return []


def _load_pool() -> dict:
    """读取三层票池 (watch/monitor/deep) — 候选=发现+盯住层, 链=按标的目标签去重"""
    from dashboard.shared import _guess_chain

    score_map = _load_score_map()
    today_str = date.today().strftime("%Y-%m-%d")
    items_all = []
    candidates = []
    for tier in ("watch", "monitor", "deep"):
        path = DATA / "pool" / f"{tier}.json"
        if not path.exists():
            continue
        try:
            with open(path) as f:
                raw = f.read().strip()
                items = json.loads(raw) if raw else []
        except (json.JSONDecodeError, OSError):
            continue
        if tier in ("watch", "monitor"):
            candidates.extend(items)
        items_all.extend(items)

    new_today = sum(
        1 for it in items_all
        if str(it.get("date_added", ""))[:10] == today_str
    )
    chains = sorted({
        _guess_chain(it.get("symbol", ""), score_map)
        for it in items_all if it.get("symbol")
    } - {"其他"})
    return {"candidates": candidates, "new_today": new_today, "active_chains": chains}


def _load_score_map() -> dict:
    """从 scan_snapshot_latest.json 构建 symbol → 评分条目 (供链条推断)"""
    path = DATA / "scan_snapshot_latest.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return {r.get("symbol", ""): r for r in data.get("results", []) if r.get("symbol")}
    except (json.JSONDecodeError, KeyError):
        return {}


def _load_trades() -> dict:
    """读取本周交易 → {strategy: count} (按 ISO 周划分, 从 trade_history 拍平)"""
    path = DATA / "trading_signals.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}

    # 本周一 (ISO 周起点)
    today = date.today()
    monday = today - timedelta(days=today.weekday())

    counts: dict = {}
    th = data.get("trade_history", {})
    if isinstance(th, dict):
        for sname, txns in th.items():
            for t in (txns or []):
                tdate = str(t.get("date", ""))[:10]
                if not tdate:
                    continue
                try:
                    d = datetime.strptime(tdate, "%Y-%m-%d").date()
                except ValueError:
                    continue
                if d >= monday:
                    counts[sname] = counts.get(sname, 0) + 1
    return counts
