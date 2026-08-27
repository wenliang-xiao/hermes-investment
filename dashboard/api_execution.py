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

    # 执行决策只关心: 今日有信号的标的 + 当前持仓 (避免全评分池刷屏)
    focus = set(positions.keys())
    try:
        sig_path = DATA / "trading_signals.json"
        if sig_path.exists():
            with open(sig_path) as f:
                ts = json.load(f)
            for s in ts.get("all_signals", []):
                if s.get("symbol"):
                    focus.add(s["symbol"])
    except (json.JSONDecodeError, KeyError, OSError):
        pass
    scores = {sym: info for sym, info in scores.items() if sym in focus}

    # 宏观状态 → 双门/象限检查有真实数据
    macro_state = {}
    try:
        mp = DATA / "macro_engine_cache.json"
        if mp.exists():
            with open(mp) as f:
                macro_state = json.load(f)
    except (json.JSONDecodeError, KeyError, OSError):
        pass

    # 今日已卖出(止损)的标的 → 禁止当日反手 (信号自洽硬规则)
    sold_today = set()
    try:
        ts_path = DATA / "trading_signals.json"
        if ts_path.exists():
            with open(ts_path) as f:
                _ts = json.load(f)
            _today = _ts.get("date", "")
            for _sname, _txns in (_ts.get("trade_history", {}) or {}).items():
                for _t in (_txns or []):
                    if str(_t.get("date", ""))[:10] == _today and str(_t.get("action", "")).startswith(("卖", "SELL")):
                        sold_today.add(_t.get("symbol"))
    except (json.JSONDecodeError, KeyError, OSError):
        pass

    checker = ExecutionChecker()
    builder = EvidenceBuilder()

    board = {"buy": [], "sell": [], "hold": [], "wait": [], "excluded": []}

    for sid, info in scores.items():
        sym = info.get("symbol", sid)
        position = positions.get(sym) if positions else None

        # 合成数据质量 → 证据链[数据层] 从 missing → ok
        item = dict(info)
        dq = _synthesize_data_quality(item)
        item["data_quality"] = dq
        item["composite"] = info.get("composite_v4", info.get("composite", 0))

        # 执行检查 (score_data 传完整评分条目: composite/scores/factor_breakdown/data_quality)
        exec_res = checker.check(
            symbol=sym,
            score_data=item,
            macro_state=macro_state,
            position=position,
        )

        # 证据包
        packet = builder.build(
            symbol=sym,
            score_data=item,
            position=position,
        )

        entry = {
            "symbol": sym,
            "name": info.get("name", sym),
            "action": exec_res.get("action", "HOLD"),
            "action_confidence": exec_res.get("action_confidence", 0.5),
            "action_reason": exec_res.get("action_reason", ""),
            "composite": item.get("composite", 0),
            "scores": info.get("scores", {}),
            "factor_breakdown": info.get("factor_breakdown", {}),
            "data_quality": dq,
            "evidence": packet.to_dict(),
        }

        if exec_res.get("build_checklist"):
            entry["build_checklist"] = exec_res["build_checklist"]
        if exec_res.get("trail_stop"):
            entry["trail_stop"] = exec_res["trail_stop"]

        action = str(exec_res.get("action", "HOLD")).lower()

        # 今日已止损标的 → 禁止反手买入 (信号自洽)
        if sym in sold_today and action == "buy":
            entry["action"] = "EXCLUDED"
            entry["action_reason"] = "⚠️ 今日已止损, 禁止当日反手"
            board["excluded"].append(entry)
            continue

        if action in board:
            board[action].append(entry)
        else:
            board["hold"].append(entry)

    return {"status": "ok", "macro": {
        "quadrant": macro_state.get("quadrant"),
        "dual_gate": (macro_state.get("dual_gate") or {}),
    }, "board": board}


def _synthesize_data_quality(info: dict) -> dict:
    """合成数据质量: 价格有效性 + 因子完整度 + 快照新鲜度 (供证据链[数据层])"""
    price = info.get("price", 0) or 0
    fb = info.get("factor_breakdown", {}) or {}
    n = len(fb)
    price_ok = price > 0
    if n >= 20 and price_ok:
        grade = "A"
    elif n >= 10 and price_ok:
        grade = "B"
    else:
        grade = "D"
    return {
        "grade": grade,
        "price_valid": price_ok,
        "price": price,
        "factor_count": n,
        "factor_completeness": round(min(1.0, n / 25), 2),
        "snapshot": "scan_snapshot_latest",
        "note": f"价格{'有效' if price_ok else '无效'}, 子因子{n}项, 综合质量{grade}",
    }


@router.get("/api/v2/execution/build-checklist/{symbol}")
async def build_checklist(symbol: str):
    """单个标的的建仓6查"""
    from engine.execution_checker import ExecutionChecker
    checker = ExecutionChecker()
    scores = _load_trading_signals()
    item = scores.get(symbol, {})
    result = checker.check(symbol, score_data=item)
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
    """构建 symbol → 评分条目 映射 (供执行决策区按标的检查)

    来源: scan_snapshot_latest.json.results — 每个标的含 composite_v4/scores/factor_breakdown
    (trading_signals.json.portfolios 是策略组合摘要, 无标的评分, 不能当评分源)
    """
    path = DATA / "scan_snapshot_latest.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}
    score_map = {}
    for r in data.get("results", []):
        sym = r.get("symbol", "")
        if not sym:
            continue
        item = dict(r)
        item["composite"] = r.get("composite_v4", r.get("composite", 0))
        score_map[sym] = item
    return score_map


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
                for sym, ps in sinfo.get("positions", {}).items():
                    if isinstance(ps, dict) and ps.get("current_price", 0) > 0:
                        item = dict(ps)
                        item["symbol"] = item.get("symbol", sym)
                        pos[sym] = item
        return pos
    except (json.JSONDecodeError, KeyError):
        return {}


@router.get("/api/v2/execution/event-risk")
async def event_risk():
    """事件风险指示灯数据 — 读 shadow_event_history.json 最新一条影子记录。

    不实时计算（避免每次刷新触发 yfinance 网络调用），只读 WS4 影子脚本
    每日累积的最新记录。无数据时明确报缺失而非假全零。
    """
    path = DATA / "shadow_event_history.json"
    if not path.exists():
        return {"status": "missing", "message": "无影子记录，请运行 run_event_shadow.py"}
    try:
        with open(path) as f:
            history = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"status": "missing", "message": "影子记录读取失败"}
    if not history or not isinstance(history, list):
        return {"status": "empty", "message": "影子记录为空"}
    return {"status": "ok", "event_risk": history[-1]}