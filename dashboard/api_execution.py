"""
执行决策区 API — execution/board + build-checklist + trail-stop
"""
import json, os
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pathlib import Path
from typing import Optional

router = APIRouter(tags=["execution"])

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


@router.get("/api/v2/execution/board")
async def execution_board():
    """
    执行决策区核心数据 — 所有信号聚合 + 建仓检查 + TrailStop 状态

    返回: {actions: [BUY, SELL, HOLD, WAIT], stocks: [...]}
    """
    from engine.execution_checker import ExecutionChecker
    from engine.evidence_builder import EvidenceBuilder

    # 加载评分数据
    scores = _load_trading_signals()
    if not scores:
        return {"status": "empty", "message": "无评分数据,请确保 run_trading.py 已运行"}

    # 加载持仓
    positions = _load_positions()

    checker = ExecutionChecker()
    builder = EvidenceBuilder()

    board = {"buy": [], "sell": [], "hold": [], "wait": []}

    for sid, info in scores.items():
        sym = info.get("symbol", sid)
        position = positions.get(sym) if positions else None

        # 执行检查
        exec_res = checker.check(
            symbol=sym,
            score_data=info.get("scores", {}),
            position=position,
        )

        # 证据包
        packet = builder.build(
            symbol=sym,
            score_data=info.get("scores", {}),
            position=position,
        )

        entry = {
            "symbol": sym,
            "action": exec_res.get("action", "HOLD"),
            "action_confidence": exec_res.get("action_confidence", 0.5),
            "action_reason": exec_res.get("action_reason", ""),
            "composite": info.get("scores", {}).get("composite", 0),
            "evidence": packet.to_dict(),
        }

        if exec_res.get("build_checklist"):
            entry["build_checklist"] = exec_res["build_checklist"]
        if exec_res.get("trail_stop"):
            entry["trail_stop"] = exec_res["trail_stop"]

        action = exec_res.get("action", "HOLD")
        if action in board:
            board[action].append(entry)
        else:
            board["hold"].append(entry)

    return {"status": "ok", "board": board}


@router.get("/api/v2/execution/build-checklist/{symbol}")
async def build_checklist(symbol: str):
    """单个标的的建仓6查"""
    from engine.execution_checker import ExecutionChecker
    checker = ExecutionChecker()
    scores = _load_trading_signals()
    item = scores.get(symbol, {})
    score_data = item.get("scores", {})
    result = checker.check(symbol, score_data=score_data)
    return {"symbol": symbol, "build_checklist": result.get("build_checklist", {})}


@router.get("/api/v2/execution/trail-stop/{symbol}")
async def trail_stop(symbol: str):
    """单个持仓的TrailStop状态"""
    from engine.execution_checker import ExecutionChecker
    positions = _load_positions()
    position = positions.get(symbol) if positions else None
    if not position:
        return {"status": "not_position", "message": f"{symbol} 不在持仓中"}
    checker = ExecutionChecker()
    result = checker.check(symbol, position=position)
    return {"symbol": symbol, "trail_stop": result.get("trail_stop", {})}


def _load_trading_signals() -> dict:
    path = DATA / "trading_signals.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return data.get("portfolios", {})
    except (json.JSONDecodeError, KeyError):
        return {}


def _load_positions() -> dict:
    path = DATA / "strategy_states.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        pos = {}
        for sname, sinfo in data.items():
            if isinstance(sinfo, dict):
                for ps in sinfo.get("positions", {}).values():
                    if isinstance(ps, dict) and ps.get("symbol"):
                        pos[ps["symbol"]] = ps
        return pos
    except (json.JSONDecodeError, KeyError):
        return {}