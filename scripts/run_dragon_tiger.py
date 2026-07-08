#!/usr/bin/env python3
"""
龙虎榜每日采集脚本
==================
用法:
  python3 scripts/run_dragon_tiger.py             # 默认采集最近一日
  python3 scripts/run_dragon_tiger.py --date 20260707  # 指定日期
  python3 scripts/run_dragon_tiger.py --no-seats  # 跳过席位明细(快模式)

输出: data/dragon_tiger.json
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    date = None
    skip_seats = False

    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--date" and i + 1 < len(args):
            date = args[i + 1]
        elif arg == "--no-seats":
            skip_seats = True

    print("🐉 龙虎榜数据采集 v1.0")
    print("=" * 60)

    target_date = date or datetime.now().strftime("%Y-%m-%d")
    print(f"📅 目标日期: {target_date}")
    if skip_seats:
        print("⚡ 快速模式: 跳过席位明细")

    from research.dragon_tiger import build_full_report

    if skip_seats:
        from research.dragon_tiger import fetch_daily_dragon_tiger, analyze_top_stocks
        from research.dragon_tiger import compute_institution_vs_retail, find_watchlist_overlap
        records = fetch_daily_dragon_tiger(date=date)
        top = analyze_top_stocks(records, limit=10)
        inst_vs_retail = compute_institution_vs_retail(records)
        overlap = find_watchlist_overlap(records)

        report = {
            "date": records[0]["date"] if records else target_date,
            "top_stocks": top,
            "famous_seats": {"active_celebrities": [], "total_famous_buy": 0, "total_famous_sell": 0},
            "institution_vs_retail": inst_vs_retail,
            "watchlist_overlap": overlap,
            "all_records": records,
            "total_records": len(records),
            "cache_timestamp": datetime.now().isoformat(),
            "status": "ok" if records else "empty",
        }

        import json
        cache_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  "data", "dragon_tiger.json")
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    else:
        report = build_full_report(date=date)

    print(f"\n📊 采集结果:")
    print(f"  上榜总数: {report.get('total_records', 0)} 只")
    print(f"  Top10净买入: {len(report.get('top_stocks', []))} 只")
    print(f"  活跃游资: {len(report.get('famous_seats', {}).get('active_celebrities', []))} 位")
    print(f"  WATCHLIST交集: {len(report.get('watchlist_overlap', []))} 只")
    print(f"  缓存时间: {report.get('cache_timestamp', '')}")
    print(f"  状态: {report.get('status', 'unknown')}")
    print(f"\n  ✅ 数据已缓存到 data/dragon_tiger.json")


if __name__ == "__main__":
    main()
