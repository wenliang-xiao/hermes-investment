#!/usr/bin/env python3
"""
Merge 4 batch factor_daily files into factor_daily.json, run merge_pools,
and generate scan_snapshot_YYYY-MM-DD.json.

Usage: python3 scripts/merge_batches_today.py
"""
import json, os, sys
from datetime import date

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def main():
    today = date.today().isoformat()
    batch_files = [
        os.path.join(_PROJECT_DIR, f"data/factor_daily_batch{i}.json")
        for i in range(1, 5)
    ]
    hk_us_file = os.path.join(_PROJECT_DIR, "data/factor_daily_batch5.json")

    # 1. Merge all batch results
    all_results = []
    seen_symbols = set()

    for bf in batch_files:
        if not os.path.exists(bf):
            print(f"⚠️  Missing: {bf}")
            continue
        with open(bf) as f:
            data = json.load(f)
        for r in data.get("top_results", []):
            sym = r["symbol"]
            if sym not in seen_symbols:
                seen_symbols.add(sym)
                all_results.append(r)
        print(f"  {os.path.basename(bf)}: {data.get('total_scored', 0)} scored, "
              f"{len(data.get('top_results', []))} top")

    # Also merge HK/US batch5 if exists
    if os.path.exists(hk_us_file):
        with open(hk_us_file) as f:
            hk_data = json.load(f)
        for r in hk_data.get("top_results", []):
            sym = r["symbol"]
            if sym not in seen_symbols:
                seen_symbols.add(sym)
                all_results.append(r)
        print(f"  {os.path.basename(hk_us_file)}: {hk_data.get('total_scored', 0)} scored, "
              f"{len(hk_data.get('top_results', []))} top")

    # Sort by rank
    all_results.sort(key=lambda x: x.get("rank", 999))

    # 2. Write merged factor_daily.json
    merged = {
        "date": today,
        "macro_state": "扩张期",
        "total_scored": len(all_results),
        "top_n": len(all_results),
        "top_results": all_results,
    }
    out_path = os.path.join(_PROJECT_DIR, "data/factor_daily.json")
    with open(out_path, "w") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"\n✅ Merged {len(all_results)} stocks -> data/factor_daily.json")

    # 3. Run merge_pools
    print("\n--- Running merge_pools.py ---")
    sys.path.insert(0, _PROJECT_DIR)
    from engine.factor_engine import PoolManager

    pm = PoolManager()
    combined = []
    for r in all_results:
        combined.append({
            "symbol": r["symbol"],
            "composite": r["composite"],
            "scores": r.get("scores", {}),
            "factor_breakdown": r.get("factor_breakdown", {}),
            "macro_state": r.get("macro_state", "扩张期"),
        })
    combined.sort(key=lambda x: x["composite"], reverse=True)
    pools = pm.update_pools(combined)
    print(f"  Pools: Watch={len(pools['watch'])} | Monitor={len(pools['monitor'])} | Deep={len(pools['deep'])}")

    # Top 10
    print("  Top 10:")
    for i, r in enumerate(combined[:10]):
        print(f"    {i+1:>2}. {r['symbol']:<10} {r['composite']:.4f}")

    # 4. Generate scan snapshot
    print("\n--- Generating scan snapshot ---")
    snap_results = []
    snap_seen = set()
    for r in all_results:
        sym = r["symbol"]
        if sym not in snap_seen:
            snap_seen.add(sym)
            snap_results.append({
                "symbol": sym,
                "composite": r.get("composite", 0),
                "scores": r.get("scores", {}),
                "macro_state": r.get("macro_state", "扩张期"),
            })
    snap_results.sort(key=lambda x: x["composite"], reverse=True)

    snap = {
        "date": today,
        "engine": "factor_engine_v4",
        "count": len(snap_results),
        "results": snap_results,
        "pools": {
            "watch_count": len(pools["watch"]),
            "monitor_count": len(pools["monitor"]),
            "deep_count": len(pools["deep"]),
        },
    }

    snap_dir = os.path.join(_PROJECT_DIR, "data/scan_snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    snap_path = os.path.join(snap_dir, f"scan_snapshot_{today}.json")
    with open(snap_path, "w") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)

    latest_path = os.path.join(_PROJECT_DIR, "data/scan_snapshot_latest.json")
    with open(latest_path, "w") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)

    print(f"  Snapshot: {snap_path} ({snap['count']} stocks)")
    print(f"  Latest:   {latest_path}")

    # 5. Log date
    log_path = os.path.join(_PROJECT_DIR, "data/scan_snapshot_days.log")
    with open(log_path, "a") as f:
        f.write(f"{today}\n")
    print(f"\n✅ Logged date: {today} -> scan_snapshot_days.log")

    # 6. Cumulative count
    snapshots = sorted([
        f for f in os.listdir(snap_dir)
        if f.startswith("scan_snapshot_20") and f.endswith(".json")
    ])
    print(f"📊 Total snapshots: {len(snapshots)} days (need 60+ for backtest)")


if __name__ == "__main__":
    main()
