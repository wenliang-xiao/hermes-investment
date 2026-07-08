#!/usr/bin/env python3
"""
scripts/run_etf_discovery.py — ETF 动态发现日度运行脚本

从全量 A股 ETF 市场中扫描，应用多因子评分，输出动态 ETF 池。

用法:
    python3 scripts/run_etf_discovery.py
    python3 scripts/run_etf_discovery.py --top-n 20 --per-category 3
    python3 scripts/run_etf_discovery.py --output data/etf_discovery_daily.json
"""

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _SCRIPT_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

try:
    from dotenv import load_dotenv
    _env_path = os.environ.get("HERMES_ENV", str(_PROJECT_DIR.parent / ".env"))
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except Exception:
    pass


def main():
    import argparse
    from datetime import datetime

    parser = argparse.ArgumentParser(
        description="ETF 动态发现扫描器 — 全市场扫描 + 多因子评分",
    )
    parser.add_argument("--top-n", "-n", type=int, default=30,
                        help="最终输出数量 (默认: 30)")
    parser.add_argument("--per-category", "-c", type=int, default=5,
                        help="每个类别最大数量 (默认: 5)")
    parser.add_argument("--output", "-o", type=str,
                        default=str(_PROJECT_DIR / "data" / "etf_discovery.json"),
                        help="输出 JSON 路径")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="静默模式")
    args = parser.parse_args()

    print("=" * 60)
    print("  ETF 动态发现 · 日度扫描")
    print(f"  启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  TOP-N: {args.top_n} | 每类最多: {args.per_category}")
    print(f"  输出路径: {args.output}")
    print("=" * 60)
    print()

    from etf.discovery import EtfDiscoveryScanner

    scanner = EtfDiscoveryScanner(
        top_n_per_category=args.per_category,
        total_output=args.top_n,
    )
    result = scanner.scan(verbose=not args.quiet)

    if "error" in result:
        print(f"\n[ERROR] 扫描失败: {result['error']}")
        sys.exit(1)

    output_path = Path(args.output)
    scanner.save(output_path)

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"  扫描结果摘要")
    print(f"  扫描日期: {result['scan_date']}")
    print(f"  有效ETF: {result['total_scanned']}")
    print(f"  市场情绪: {result['market_regime']}")
    if result.get("safe_haven_recommended"):
        print(f"  ⚠️  推荐切换安全港: {result.get('safe_haven_symbol')}")
    print()

    print(f"  TOP 10 推荐:")
    for e in result.get("top_picks", [])[:10]:
        print(f"    {e['rank']:2d}. [{e['category']:12s}] {e['name']:16s} ({e['symbol']}) "
              f"综合:{e['composite_score']:.3f} 动量:{e['momentum']:+.2f}% "
              f"趋势:{e.get('trend_signal','-')}")

    print(f"\n  类别分布: {result.get('category_stats', {})}")
    print(f"  完整输出: {output_path}")
    print(f"{'='*60}")

    return result


if __name__ == "__main__":
    main()
