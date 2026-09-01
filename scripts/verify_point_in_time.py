#!/usr/bin/env python3
"""P0-1 数据级验证 — use_point_in_time=True vs False 前视消除对比

opencode 转达: 时点评分全链路已合入 main (d39281c→760cb7e)。
核心开关 run_backtest(use_point_in_time=True) 默认关闭保持向后兼容,
需在开发机器跑一次 True vs False 对比, 验证前视消除后 CAGR 降幅。

本脚本: 预加载真实行情 → 同参数跑两种模式 → 输出对比指标。
单线程 (规避 baostock 多线程 login 冲突)。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import engine.evaluator_fixed as ef
from engine.evaluator_fixed import FIXED_UNIVERSE, preload_all_data, load_dates_map
from strategies.faceji import decide as faceji_decide

DAYS = 120


def result_summary(r):
    if isinstance(r, dict) and "error" in r:
        return {"error": r["error"]}
    return {
        "total_return_pct": round(r.total_return_pct, 2),
        "annualized_pct": round(r.annualized_return_pct, 2),
        "sharpe": round(r.sharpe_ratio, 3),
        "max_drawdown_pct": round(r.max_drawdown_pct, 2),
        "win_rate_pct": round(r.win_rate_pct, 1),
        "trade_count": r.trade_count,
        "scoring_mode": getattr(r, "scoring_mode", "?"),
    }


def main():
    print(f"预加载 {DAYS} 天行情 (FIXED_UNIVERSE {len(FIXED_UNIVERSE)} 只)...", flush=True)
    t0 = time.time()
    # 单线程预加载全部价格
    price_data = preload_all_data(days=DAYS)
    dates_map = load_dates_map(days=DAYS)
    print(f"预加载完成: {len(price_data)} 只, 耗时 {time.time()-t0:.1f}s", flush=True)
    if not price_data:
        print("ERROR: 无行情数据"); return

    # True vs False
    for mode in (False, True):
        t1 = time.time()
        print(f"\n=== use_point_in_time={mode} ===", flush=True)
        try:
            r = ef.run_backtest(price_data, faceji_decide, "faceji",
                                dates_map=dates_map, use_point_in_time=mode)
            s = result_summary(r)
            print(f"耗时 {time.time()-t1:.1f}s")
            for k, v in s.items():
                print(f"  {k}: {v}")
        except Exception as e:
            import traceback
            print(f"FAILED ({time.time()-t1:.1f}s): {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()