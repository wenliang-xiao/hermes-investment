"""未成交观点库 API"""
import json
from collections import Counter

from fastapi import APIRouter
from dashboard.shared import ROOT

router = APIRouter()


def _load_insights():
    """读取 insights.json，文件不存在/解析失败时返回空结构。"""
    path = ROOT / "data" / "insights.json"
    if not path.exists():
        return {"updated": "", "insights": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"updated": "", "insights": []}


@router.get("/api/v2/insights")
def api_v2_insights():
    """返回 insights.json 全量。"""
    data = _load_insights()
    insights = data.get("insights", []) or []
    return {
        "updated": data.get("updated", ""),
        "count": len(insights),
        "insights": insights,
    }


@router.get("/api/v2/insights/summary")
def api_v2_insights_summary():
    """统计: 被信号最多却没成交的标的 Top + 按 not_executed_reason 分布。"""
    data = _load_insights()
    insights = data.get("insights", []) or []

    # 按 标的(symbol) 统计未成交观点数
    by_symbol = Counter()
    sym_name = {}
    for it in insights:
        sym = it.get("symbol") or "?"
        by_symbol[sym] += 1
        sym_name[sym] = it.get("name") or sym

    top_symbols = [
        {"symbol": s, "name": sym_name[s], "count": c}
        for s, c in by_symbol.most_common(10)
    ]

    # 按 not_executed_reason 分布
    by_reason = Counter()
    for it in insights:
        reason = it.get("not_executed_reason") or "未知"
        by_reason[reason] += 1

    reason_dist = [
        {"reason": r, "count": c}
        for r, c in by_reason.most_common()
    ]

    # 按策略分布
    by_strategy = Counter()
    for it in insights:
        strat = it.get("strategy") or "unknown"
        by_strategy[strat] += 1

    return {
        "updated": data.get("updated", ""),
        "total": len(insights),
        "top_unexecuted_symbols": top_symbols,
        "reason_distribution": reason_dist,
        "strategy_distribution": [
            {"strategy": s, "count": c}
            for s, c in by_strategy.most_common()
        ],
    }
