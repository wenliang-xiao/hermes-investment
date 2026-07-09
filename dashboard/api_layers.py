"""
六层指标 API — /api/v2/layers/status, layers/macro, layers/allocation
"""
import json, os
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
    path = DATA / "pool" / "deep_layer.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            candidates = json.load(f)
        return {"candidates": candidates, "new_today": 0, "active_chains": []}
    except (json.JSONDecodeError, KeyError):
        return {}


def _load_trades() -> list:
    path = DATA / "trading_signals.json"
    if not path.exists():
        return []
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("trade_history", [])
    except (json.JSONDecodeError, KeyError):
        return []
