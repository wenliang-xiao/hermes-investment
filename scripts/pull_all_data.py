"""
scripts/pull_all_data.py — 全量数据拉取（PR1 核心）

拉取所有84只标的 × 5年日线，缓存到 data/cache/。
支持增量更新（已有缓存的跳过）。
"""
import sys, os, time, json
from pathlib import Path

# Add project to path
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT.parent))
sys.path.insert(0, os.path.join(str(_ROOT.parent), "investment_system"))

import functools
print = functools.partial(print, flush=True)

# Import domain (WATCHLIST) and data router
from investment_system import domain
from data.data_router import get_history, _detect_source, get_cache_info

# Configuration
DAYS = 1200  # ~5 years of trading days
RATE_LIMIT = 1.2  # seconds between API calls (baostock rate limit)
CACHE_DIR = _ROOT / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def stock_type(sym):
    if sym.endswith('.HK'): return "港股"
    if sym.startswith('^') or sym in ('DXY','CNY=X'): return "指数"
    if '=' in sym: return "期货"
    if sym.isdigit() and len(sym)==6:
        if sym.startswith(('51','15','16','159')): return "ETF"
        return "A股"
    return "美股"


def already_cached(symbol, days=None):
    """Check if data already cached"""
    cache_key = f"get_history_{symbol}_{days or DAYS}"
    cache_path = CACHE_DIR / f"{cache_key}.pkl"
    return cache_path.exists()


def main():
    symbols = sorted(domain.WATCHLIST.keys())
    total = len(symbols)
    print(f"📊 开始全量数据拉取: {total} 只标的 × {DAYS}天")
    print(f"   缓存目录: {CACHE_DIR}")
    print()

    # Separate by source for progress tracking
    by_source = {"baostock": [], "yfinance": [], "akshare_futures": []}
    for sym in symbols:
        src = _detect_source(sym)
        by_source[src].append(sym)

    for src, syms in by_source.items():
        print(f"  {src}: {len(syms)} 只")

    baostock_total = len(by_source["baostock"])
    yfinance_total = len(by_source["yfinance"])

    success = 0
    skipped = 0
    failed = 0

    # Phase 1: baostock (A股 + ETF)
    print(f"\n{'='*50}")
    print(f"Phase 1: baostock ({baostock_total} 只)")
    print(f"{'='*50}")
    for i, sym in enumerate(by_source["baostock"]):
        if already_cached(sym, 1200):
            print(f"  [{i+1}/{baostock_total}] {sym} ⏭️ 已缓存")
            skipped += 1
            continue

        print(f"  [{i+1}/{baostock_total}] {sym} {stock_type(sym)}...", end="")
        try:
            df = get_history(sym, 1200)
            if df and len(df.get("dates", [])) > 60:
                print(f" ✅ {len(df['dates'])}天")
                success += 1
            else:
                print(f" ⚠️ 数据不足({len(df.get('dates',[]))}天)")
                failed += 1
        except Exception as e:
            print(f" ❌ {e}")
            failed += 1
        time.sleep(RATE_LIMIT)

    # Phase 2: yfinance (港美股 + ETF)
    print(f"\n{'='*50}")
    print(f"Phase 2: yfinance ({yfinance_total} 只)")
    print(f"{'='*50}")
    for i, sym in enumerate(by_source["yfinance"]):
        if already_cached(sym, 1200):
            print(f"  [{i+1}/{yfinance_total}] {sym} ⏭️ 已缓存")
            skipped += 1
            continue

        print(f"  [{i+1}/{yfinance_total}] {sym} {stock_type(sym)}...", end="")
        try:
            df = get_history(sym, 1200)
            if df and len(df.get("dates", [])) > 60:
                print(f" ✅ {len(df['dates'])}天")
                success += 1
            else:
                print(f" ⚠️ 数据不足({len(df.get('dates',[]))}天)")
                failed += 1
        except Exception as e:
            print(f" ❌ {e}")
            failed += 1
        # yfinance rate limit
        time.sleep(0.5)

    # Phase 3: futures (AKShare)
    futures_syms = by_source.get("akshare_futures", [])
    if futures_syms:
        print(f"\n{'='*50}")
        print(f"Phase 3: futures ({len(futures_syms)} 只)")
        print(f"{'='*50}")
        for i, sym in enumerate(futures_syms):
            if already_cached(sym, 1200):
                print(f"  [{i+1}/{len(futures_syms)}] {sym} ⏭️ 已缓存")
                skipped += 1
                continue
            print(f"  [{i+1}/{len(futures_syms)}] {sym} {stock_type(sym)}...", end="")
            try:
                df = get_history(sym, 1200)
                if df and len(df.get("dates", [])) > 60:
                    print(f" ✅ {len(df['dates'])}天")
                    success += 1
                else:
                    print(f" ⚠️ 数据不足")
                    failed += 1
            except Exception as e:
                print(f" ❌ {e}")
                failed += 1
            time.sleep(1)

    print(f"\n{'='*50}")
    print(f"✅ 完成! 成功={success} 已缓存={skipped} 失败={failed}")
    print(f"缓存: {get_cache_info()}")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
