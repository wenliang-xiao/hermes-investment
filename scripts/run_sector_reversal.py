#!/usr/bin/env python3
"""板块反转层日更 — 11 个 LDS 板块 + 科创50/创业板/费半 的时序反转扫描

用法:
    python3 scripts/run_sector_reversal.py            # 扫描并落盘
    python3 scripts/run_sector_reversal.py --print     # 扫描并打印摘要

产物: data/sector_reversal.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from engine.sector_reversal_engine import (  # noqa: E402
    analyze_sector,
    lead_lag,
    pct_return,
    save_snapshot,
    transmission_gap,
    METHOD,
    STAGE_REVERSAL,
    STAGE_BASING,
    STAGE_FALLING,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("sector_reversal")

# 板块 → (代理标的, 显示名, 市场)
PROXIES: dict[str, tuple[str, str, str]] = {
    "科技":     ("515000", "科技ETF", "A"),
    "半导体":   ("512480", "半导体ETF", "A"),
    "AI算力":   ("515070", "人工智能ETF", "A"),
    "新能源":   ("515030", "新能源车ETF", "A"),
    "军工":     ("512660", "军工ETF", "A"),
    "医药":     ("512010", "医药ETF", "A"),
    "消费":     ("159928", "消费ETF", "A"),
    "金融":     ("512800", "银行ETF", "A"),
    "能源":     ("159930", "能源ETF", "A"),
    "地产基建": ("512200", "房地产ETF", "A"),
    "汽车":     ("516110", "汽车ETF", "A"),
    # 用户关心的宽基/海外导航标的 (不属 LDS 11 板块, 单独列)
    "科创50":   ("588000", "科创50ETF", "A"),
    "创业板":   ("159915", "创业板ETF", "A"),
    "费城半导体": ("SOXX", "费城半导体ETF", "US"),
}

BENCHMARK_A = "510300"   # 沪深300ETF
BENCHMARK_US = "^IXIC"   # 纳斯达克

# 跨市场传导对: (leader, follower)
TRANSMISSION_PAIRS = [("SOXX", "512480"), ("^IXIC", "515070"), ("SOXX", "588000")]


def _fetch(symbol: str, days: int = 130) -> dict | None:
    """带重试的单标的日线拉取。返回 {dates, close, volume}。"""
    from data.data_router import get_history
    for attempt in range(2):
        try:
            d = get_history(symbol, days)
            if d and d.get("close"):
                return {"dates": list(d.get("dates") or []),
                        "close": [float(x) for x in d["close"]],
                        "volume": [float(x) for x in (d.get("volume") or [0] * len(d["close"]))]}
        except Exception as e:  # noqa: BLE001 - 数据源异常需降级, 不中断全扫
            logger.warning("fetch %s attempt%d failed: %s", symbol, attempt + 1, str(e)[:80])
        time.sleep(1.5)
    return None


def run(days: int = 130) -> dict:
    series: dict[str, dict] = {}

    # 基准先取 — 失败会导致全部相对强度为空, 必须优先且有更多重试
    for _ in range(5):
        s = _fetch(BENCHMARK_A, days)
        if s:
            series[BENCHMARK_A] = s
            break
        time.sleep(3)
    if BENCHMARK_A not in series:
        logger.error("基准 %s 多次拉取失败", BENCHMARK_A)

    # 美股基准 (费半等海外标的的相对强度基准)
    series[BENCHMARK_US] = _fetch(BENCHMARK_US, days) or {}

    for key, (sym, _name, _mkt) in PROXIES.items():
        s = _fetch(sym, days)
        if s:
            series[sym] = s
        else:
            logger.error("板块 %s 代理 %s 数据缺失, 跳过", key, sym)
        time.sleep(0.6)

    bench_a = series.get(BENCHMARK_A, {}).get("close") or []
    bench_us = series.get(BENCHMARK_US, {}).get("close") or []
    if not bench_a:
        logger.error("基准 %s 缺失, 相对强度将为空", BENCHMARK_A)

    sectors: list[dict] = []
    for key, (sym, name, mkt) in PROXIES.items():
        s = series.get(sym)
        if not s:
            continue
        bench = bench_us if mkt == "US" else (bench_a if mkt == "A" else bench_a)
        sectors.append(analyze_sector(
            key=key, name=name, symbol=sym, market=mkt,
            close=s["close"], volume=s["volume"], bench_close=bench,
            dates=s["dates"],
        ))

    # ─── 跨市场传导 ───
    transmission: list[dict] = []
    for leader_sym, follower_sym in TRANSMISSION_PAIRS:
        ls, fs = series.get(leader_sym), series.get(follower_sym)
        if not ls or not fs:
            continue
        ll = lead_lag(ls["close"], fs["close"], max_lag=5)
        l5 = pct_return(ls["close"], 5)
        f5 = pct_return(fs["close"], 5)
        if l5 is None or f5 is None:
            continue
        gap = transmission_gap(l5, f5)
        transmission.append({
            "leader": leader_sym,
            "follower": follower_sym,
            "leader_5d": l5,
            "follower_5d": f5,
            "lag": ll["lag"],
            "corr": ll["corr"],
            "gap_pp": gap["gap_pp"],
            "leader_ahead": gap["leader_ahead"],
            "read": (f"领先标的5日{l5:+.2f}% vs 跟随标的{f5:+.2f}%, "
                     f"缺口{gap['gap_pp']:+.2f}pp, 历史领先{ll['lag']}日(corr={ll['corr']})"),
        })
    transmission.sort(key=lambda x: abs(x["gap_pp"]), reverse=True)

    # ─── 摘要 ───
    def _sorted(stage: str) -> list[dict]:
        return sorted([s for s in sectors if s["stage"] == stage],
                      key=lambda x: x["score"], reverse=True)

    summary = {
        "reversal": [{"key": s["key"], "name": s["name"], "score": s["score"],
                      "ret_5d": s["ret_5d"], "dd_60d": s["dd_60d"],
                      "reason": s["reversal"]["reason"]} for s in _sorted(STAGE_REVERSAL)],
        "basing": [{"key": s["key"], "score": s["score"], "rs_5d": s["rs_5d"]} for s in _sorted(STAGE_BASING)],
        "falling": [{"key": s["key"], "score": s["score"], "ret_5d": s["ret_5d"]} for s in _sorted(STAGE_FALLING)],
        "gap_top": transmission[0] if transmission else None,
        "score_rank": [{"key": s["key"], "score": s["score"], "stage": s["stage"]}
                       for s in sorted(sectors, key=lambda x: x["score"], reverse=True)],
    }

    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "benchmark_a": BENCHMARK_A,
        "benchmark_us": BENCHMARK_US,
        "sectors": sectors,
        "transmission": transmission,
        "summary": summary,
        "method": METHOD,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--print", dest="do_print", action="store_true")
    args = ap.parse_args()

    payload = run()
    path = save_snapshot(payload)
    print(f"\n✅ 板块反转扫描完成 → {path} ({len(payload['sectors'])} 个板块)\n")

    if args.do_print:
        print(f"{'板块':<10}{'阶段':<10}{'评分':>6}{'5日%':>8}{'20日%':>8}{'回撤%':>8}{'RS5':>8}  反转")
        print("─" * 78)
        for s in sorted(payload["sectors"], key=lambda x: x["score"], reverse=True):
            rv = "✅" if s["reversal"]["fired"] else " "
            print(f"{s['key']:<10}{s['stage']:<10}{s['score']:>6.1f}"
                  f"{(s['ret_5d'] or 0):>8.2f}{(s['ret_20d'] or 0):>8.2f}"
                  f"{(s['dd_60d'] or 0):>8.2f}{(s['rs_5d'] or 0):>8.2f}  {rv} {s['reversal']['reason'][:28]}")
        print("\n跨市场传导:")
        for t in payload["transmission"]:
            print(f"  {t['leader']} → {t['follower']}: {t['read']}")


if __name__ == "__main__":
    main()
