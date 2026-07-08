"""
中美脱钩·比较优势发现引擎 v1.0
================================
基于技术/产业域比较优势分析，识别在中美脱钩背景下
具有结构性优势的中国标的。

方法论:
  1. 按产业链卡位划分15+技术/产业域
  2. 每个域评估中美各自的竞争优势（产能/技术/政策）
  3. 从优势方提取受益标的：中国领导者(best) > 中国潜力 > 供应链间接受益
  4. 按置信度+角色权重排序输出发现列表

数据源: data/decoupling_map.json
"""

import json
import os
import sys
from typing import Optional

# Path setup for dual-mode imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# ── 置信度 → 基础分映射 ──
CONFIDENCE_SCORE = {
    "high": 0.90,
    "medium": 0.70,
    "low": 0.50,
}

# ── 角色 → 权重系数 ──
ROLE_WEIGHT = {
    "china_leaders": 0.95,          # 中国在该域全球领先 → 直接受益
    "china_potential": 0.80,        # 中国在追赶期 → 潜在受益
    "china_beneficiaries": 0.75,    # 供应链间接受益
}


def _load_map() -> dict:
    """加载比较优势地图"""
    map_path = os.path.join(_PROJECT_DIR, "data", "decoupling_map.json")
    with open(map_path, "r") as f:
        return json.load(f)


def get_comparative_advantage_map() -> dict:
    """
    返回完整的比较优势地图（含所有域定义）。

    用于 Dashboard API 展示和深度分析。
    """
    return _load_map()


def get_discovered_stocks(
    watchlist_symbols: Optional[set] = None,
    min_confidence: str = "low",
) -> list[dict]:
    """
    基于比较优势地图发现具有结构性优势的标的。

    Args:
        watchlist_symbols: 已知 WATCHLIST 的符号集合，用于名称富化。
                           如果为 None，只使用 stock_names 兜底。
        min_confidence: 最低置信度过滤 ("high"/"medium"/"low")

    Returns:
        [{symbol, domain, reason, catalyst, advantage_score, confidence,
          role, name, risk_factors}, ...]
        按 advantage_score 降序排列，去重（同一symbol取最高分）。
    """
    data = _load_map()
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    min_level = confidence_order.get(min_confidence, 2)

    # 加载名称映射
    try:
        from data.stock_names import get_name as _stock_get_name
    except ImportError:
        def _stock_get_name(code: str) -> str:
            return code

    seen: dict[str, dict] = {}  # symbol → best entry

    for dm in data.get("domains", []):
        domain = dm["domain"]
        confidence = dm.get("confidence", "medium")

        # 置信度过滤
        if confidence_order.get(confidence, 2) > min_level:
            continue

        base_score = CONFIDENCE_SCORE.get(confidence, 0.50)
        reason = dm.get("reason", "")
        catalyst = dm.get("catalyst", "")
        risk_factors = dm.get("risk_factors", [])

        for role, weight in ROLE_WEIGHT.items():
            symbols = dm.get(role, [])
            if not symbols:
                continue

            advantage_score = round(base_score * weight, 4)

            for sym in symbols:
                # 去重：同一symbol取最高 advantage_score
                if sym in seen and seen[sym]["advantage_score"] >= advantage_score:
                    continue

                seen[sym] = {
                    "symbol": sym,
                    "domain": domain,
                    "reason": reason,
                    "catalyst": catalyst,
                    "advantage_score": advantage_score,
                    "confidence": confidence,
                    "role": role,
                    "name": _stock_get_name(sym),
                    "risk_factors": risk_factors,
                }

    # 按 advantage_score 降序排列
    result = sorted(seen.values(), key=lambda x: x["advantage_score"], reverse=True)

    # 富化名称（如果传了 watchlist）
    if watchlist_symbols is not None:
        for item in result:
            sym = item["symbol"]
            if sym in watchlist_symbols:
                wl_entry = watchlist_symbols[sym]
                if isinstance(wl_entry, dict):
                    if not item.get("name") or item["name"] == sym:
                        item["name"] = wl_entry.get("name", sym)
                    item["chain"] = wl_entry.get("chain", "")
                    item["tier"] = wl_entry.get("tier", "")

    return result


def get_domain_summary() -> list[dict]:
    """
    返回每个技术域的摘要信息 — 用于飞书报告/Dashboard总览。

    Returns:
        [{domain, advantage, leader_count, top_symbols, confidence}, ...]
    """
    data = _load_map()
    summary = []

    for dm in data.get("domains", []):
        domain = dm["domain"]
        confidence = dm.get("confidence", "medium")

        # 判断优势方
        if dm.get("china_advantage"):
            advantage = "China"
            leaders = dm.get("china_leaders", [])
        elif dm.get("us_advantage"):
            advantage = "US"
            leaders = dm.get("us_leaders", [])
        else:
            advantage = "Mixed"
            leaders = (dm.get("china_leaders", [])
                       + dm.get("china_potential", [])
                       + dm.get("china_beneficiaries", []))

        summary.append({
            "domain": domain,
            "advantage": advantage,
            "leader_count": len(leaders),
            "top_symbols": leaders[:3],
            "confidence": confidence,
            "catalyst": dm.get("catalyst", ""),
        })

    return summary


def get_stocks_by_domain(symbol: str) -> list[dict]:
    """
    查询某个标的在哪些技术域有比较优势。

    Returns:
        [{domain, advantage, role, score, ...}]
    """
    data = _load_map()
    matches = []

    for dm in data.get("domains", []):
        domain = dm["domain"]
        confidence = dm.get("confidence", "medium")
        base_score = CONFIDENCE_SCORE.get(confidence, 0.50)

        for role, weight in ROLE_WEIGHT.items():
            if symbol in dm.get(role, []):
                matches.append({
                    "domain": domain,
                    "advantage": "China" if dm.get("china_advantage")
                    else "US" if dm.get("us_advantage") else "Mixed",
                    "role": role,
                    "score": round(base_score * weight, 4),
                    "confidence": confidence,
                })

    return sorted(matches, key=lambda x: x["score"], reverse=True)


# ── CLI quick test ──
if __name__ == "__main__":
    stocks = get_discovered_stocks()
    print(f"\n{'='*70}")
    print(f"中美脱钩·比较优势发现 | 共 {len(stocks)} 只标的")
    print(f"{'='*70}")
    for i, s in enumerate(stocks[:20], 1):
        role_label = {
            "china_leaders": "🏆领导者",
            "china_potential": "🔬追赶期",
            "china_beneficiaries": "🔗受益方",
        }.get(s["role"], s["role"])
        print(f"{i:2d}. {s['symbol']:<10s} {s['name']:<10s} "
              f"score={s['advantage_score']:.3f} {role_label} "
              f"domain={s['domain']}")
