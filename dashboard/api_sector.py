"""板块反转层 API — 板块级/时序级信号 (与个股截面打分互补)

数据源: data/sector_reversal.json (scripts/run_sector_reversal.py 生成)
"""
import json
import os
import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from dashboard.shared import ROOT

router = APIRouter()

_PATH = ROOT / "data" / "sector_reversal.json"


@router.get("/api/v2/sector_reversal")
def api_sector_reversal():
    """全部板块的时序状态 + 跨市场传导缺口。"""
    if not _PATH.exists():
        return JSONResponse({"error": "sector_reversal.json 未生成",
                             "hint": "python3 scripts/run_sector_reversal.py"},
                            status_code=404)
    with open(_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    payload["age_hours"] = round((time.time() - os.path.getmtime(_PATH)) / 3600, 1)
    payload["stale"] = payload["age_hours"] > 96
    return payload


@router.get("/api/v2/sector_reversal/rank")
def api_sector_reversal_rank():
    """按反转证据强度排序的精简榜 (前端表格用)。"""
    if not _PATH.exists():
        return JSONResponse({"error": "sector_reversal.json 未生成"}, status_code=404)
    with open(_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    rows = sorted(payload.get("sectors", []), key=lambda x: x.get("score", 0), reverse=True)
    return {
        "date": payload.get("date"),
        "age_hours": round((time.time() - os.path.getmtime(_PATH)) / 3600, 1),
        "rows": [{
            "key": s["key"], "name": s["name"], "symbol": s["symbol"], "market": s["market"],
            "stage": s["stage"], "score": s["score"],
            "ret_1d": s.get("ret_1d"), "ret_5d": s.get("ret_5d"), "ret_20d": s.get("ret_20d"),
            "dd_60d": s.get("dd_60d"), "rs_5d": s.get("rs_5d"),
            "reversal_fired": (s.get("reversal") or {}).get("fired", False),
            "reversal_reason": (s.get("reversal") or {}).get("reason", ""),
        } for s in rows],
        "transmission": payload.get("transmission", []),
        "method": payload.get("method", {}),
    }
