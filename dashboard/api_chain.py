"""
产业链证据 API — 链定位 + Nick四问 + 机构流向
"""
from fastapi import APIRouter, HTTPException
from dashboard.shared import get_name
from research.chain_evidence import (
    get_chain_position, get_chain_map, get_nick_four, get_institutional_flow,
)

router = APIRouter(tags=["chain"])


@router.get("/api/v2/chain/map")
async def api_chain_map():
    """产业链地图 — 所有链条+利润池+Perez阶段"""
    return {"status": "ok", "chains": get_chain_map()}


@router.get("/api/v2/chain/position/{symbol}")
async def api_chain_position(symbol: str):
    """标的产业链定位 — 利润池位置+Perez阶段"""
    pos = get_chain_position(symbol)
    return {"status": "ok" if pos.get("chain") else "no_chain", "position": pos}


@router.get("/api/v2/chain/nick-four/{symbol}")
async def api_nick_four(symbol: str):
    """Nick四问 — Q1(时机)/Q2(公司)/Q3(价格)/Q4(错误)"""
    name = get_name(symbol)
    result = get_nick_four(symbol, name)
    if result.get("error"):
        return {"status": "error", "message": result["error"]}
    result["symbol"] = symbol
    result["name"] = name
    return {"status": "ok", "nick_four": result}


@router.get("/api/v2/chain/institutional-flow")
async def api_institutional_flow(chain: str = ""):
    """机构/散户流向 — 各产业链的机构配置观点"""
    flows = get_institutional_flow(chain if chain else "")
    return {"status": "ok", "flows": flows}
