"""
cache_historical.py — 批量拉取并缓存全量日线历史

只拉取 baostock 可获取的标的（A股、部分LOF/ETF）。
港股/美股/期货/Yahoo 类用 data_layer 中各自的数据源处理。
缓存到 data/cache/{symbol}_{days}d.pkl 供 evaluator_fixed 和回测使用。
"""
import sys, os, pickle, time, json
from pathlib import Path

_ROOT = Path(__file__).parent.parent  # scripts/../ = project root
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT.parent))  # for investment_system package import

from data.data_layer import get_stock_daily
from domain import WATCHLIST
import functools
print = functools.partial(print, flush=True)

# A股标的（baostock可获取的6位代码）
A_SHARES = [
    "300502", "300308", "688256", "688008", "688012",
    "688041", "688120", "002371", "603501", "688017",
    "300124", "002747", "002472", "300750", "601012",
    "600760", "002179", "603259", "300760", "600519",
    "000858", "600887", "600036", "601318", "600030",
    "600900", "601985", "601899", "600028", "601877",
    "688390", "159985",
]

DAYS = [120, 250]
cache_dir = _ROOT / "data" / "cache"
cache_dir.mkdir(parents=True, exist_ok=True)

summary = {d: {} for d in DAYS}
total_size = 0

for days in DAYS:
    print(f"\n📦 拉取 {days}天...")
    for sym in A_SHARES:
        name = WATCHLIST.get(sym, {}).get("name", sym)
        cp = cache_dir / f"{sym}_{days}d.pkl"
        if cp.exists():
            sz = os.path.getsize(cp)
            total_size += sz
            summary[days][sym] = f"✓cache({sz//1024}KB)"
            print(f"  {sym:>8} {name:<8} ✅ 缓存 ({sz//1024}KB)")
            continue
        df = get_stock_daily(sym, days=days + 30)
        if df is None or len(df) < 30:
            summary[days][sym] = f"✗数据不足({len(df) if df is not None else 0})"
            print(f"  {sym:>8} {name:<8} ❌ {len(df) if df is not None else 0}天")
            continue
        # trim to exact days
        if len(df) > days:
            df = df.iloc[-days:]
        try:
            with open(cp, "wb") as f:
                pickle.dump(df, f)
            sz = os.path.getsize(cp)
            total_size += sz
            summary[days][sym] = f"✓{len(df)}d({sz//1024}KB)"
            print(f"  {sym:>8} {name:<8} ✅ {len(df)}天 ({sz//1024}KB)")
        except Exception as e:
            summary[days][sym] = f"✗{e}"
            print(f"  {sym:>8} {name:<8} ❌ {e}")
        time.sleep(1.2)

total_files = len([f for f in cache_dir.iterdir() if f.suffix == ".pkl"])
print(f"\n✅ 全量缓存完成")
print(f"   缓存目录: {cache_dir}")
for d in DAYS:
    good = sum(1 for v in summary[d].values() if v.startswith("✓"))
    print(f"   {d}天: {good}/{len(A_SHARES)} 成功")
print(f"   总大小: {total_size/1024/1024:.1f} MB")
print(f"   文件数: {total_files}")