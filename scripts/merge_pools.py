#!/usr/bin/env python3
"""
合并A股+港美股池子到统一的三层票池
"""
import json, os, sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from engine.factor_engine import PoolManager

def main():
    pm = PoolManager()

    # 读取A股结果
    a_path = os.path.join(_PROJECT_DIR, "data/factor_daily.json")
    hk_us_path = os.path.join(_PROJECT_DIR, "data/factor_daily_hk_us.json")

    a_results = []
    hk_us_results = []

    if os.path.exists(a_path):
        with open(a_path) as f:
            a_data = json.load(f)
        a_results = a_data.get("top_results", [])
        print(f"A股: {len(a_results)} 只评分")

    if os.path.exists(hk_us_path):
        with open(hk_us_path) as f:
            hk_data = json.load(f)
        hk_us_results = hk_data.get("top_results", [])
        print(f"港美股: {len(hk_us_results)} 只评分")

    # 合并为统一格式 (factor_engine.score_batch 输出格式)
    combined = []
    seen = set()

    for r in a_results + hk_us_results:
        sym = r["symbol"]
        if sym in seen:
            continue
        seen.add(sym)
        combined.append({
            "symbol": sym,
            "composite": r["composite"],
            "scores": r.get("scores", {}),
            "factor_breakdown": r.get("factor_breakdown", {}),
            "macro_state": r.get("macro_state", "扩张期"),
        })

    # 按评分降序
    combined.sort(key=lambda x: x["composite"], reverse=True)
    print(f"合并后: {len(combined)} 只 (A股{len(a_results)}+港美股{len(hk_us_results)})")

    # 更新PoolManager
    pools = pm.update_pools(combined)

    # 输出摘要
    print(f"Watch={len(pools['watch'])} | Monitor={len(pools['monitor'])} | Deep={len(pools['deep'])}")
    print("\n前10名:")
    for i, r in enumerate(combined[:10]):
        print(f"  {i+1:>2}. {r['symbol']:<10} {r['composite']:.4f}")

if __name__ == "__main__":
    main()