#!/usr/bin/env python3
"""
面基因子日扫 — 新引擎入口脚本
==================================
每日扫描: 因子引擎 → PoolManager → 输出 JSON

用法:
    python3 scripts/run_factor_daily.py [--symbols A,B,C] [--output data/factor_daily.json]

对比旧版 (run_trading.py):
  - 旧版: 31只 + baostock + 6因子固定评分 (factor_scanner.py) + TradingEngine
  - 新版: 全核心池 + 19子因子截面分位 + IC权重 + PoolManager三层票池
"""

import sys, os, json, logging
from datetime import date

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
try:
    from dotenv import load_dotenv
    _env_path = os.environ.get("HERMES_ENV", os.path.join(os.path.dirname(_PROJECT_DIR), ".env"))
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except Exception:
    pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def main():
    import argparse
    from engine.factor_engine import FactorEngine, PoolManager

    parser = argparse.ArgumentParser(description="面基因子日扫")
    parser.add_argument("--symbols", help="标的列表,逗号分隔", default="")
    parser.add_argument("--output", default="data/factor_daily.json",
                        help="输出路径")
    parser.add_argument("--top-n", type=int, default=30, help="输出前N只")
    parser.add_argument("--macro-state", default="扩张期", help="宏观状态")
    args = parser.parse_args()

    # 标的池
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        # 默认: 核心池 + LDS全板块
        try:
            from domain.stock_universe import ALL_CORE_STOCKS, LDS_SECTORS
            all_symbols = set()
            for sec_syms in LDS_SECTORS.values():
                for s in sec_syms:
                    if len(str(s)) == 6:
                        all_symbols.add(str(s))
            # 核心池优先
            symbols = [str(s) for s in ALL_CORE_STOCKS if len(str(s)) == 6]
            # 补上全板块
            for s in all_symbols:
                if s not in symbols:
                    symbols.append(s)
        except ImportError:
            symbols = ["300502", "688041", "688008", "002371", "603259",
                       "688256", "600519", "000858", "300750", "002594",
                       "000333", "002415", "000651", "002304", "600585"]

    logger.info(f"[factor_daily] 扫描池: {len(symbols)} 只标的, macro={args.macro_state}")

    # 因子引擎批量评分
    engine = FactorEngine()
    scored = engine.score_batch(symbols, macro_state=args.macro_state)

    # 输出TOP N
    top_n = scored[:args.top_n]

    # 更新PoolManager
    pm = PoolManager()
    pools = pm.update_pools(scored)

    # 组装输出
    output = {
        "date": date.today().isoformat(),
        "macro_state": args.macro_state,
        "total_scored": len(scored),
        "top_n": args.top_n,
        "weights_used": scored[0]["weights_used"] if scored else {},
        "pools": {
            "watch_count": len(pools["watch"]),
            "monitor_count": len(pools["monitor"]),
            "deep_count": len(pools["deep"]),
        },
        "top_results": [
            {
                "rank": i + 1,
                "symbol": r["symbol"],
                "composite": r["composite"],
                "scores": r["scores"],
                "macro_state": r["macro_state"],
            }
            for i, r in enumerate(top_n)
        ],
    }

    # 保存
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    logger.info(f"[factor_daily] 输出到 {args.output} ({len(scored)} 只, top={args.top_n})")

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"📊 面基因子日扫 | {output['date']} | {len(scored)}只 | macro={args.macro_state}")
    print(f"{'='*60}")
    print(f"{'排名':<4} {'代码':<8} {'综合分':<8} {'质量':<7} {'价值':<7} {'成长':<7} {'动量':<7}")
    print(f"{'-'*55}")
    for r in output["top_results"][:10]:
        s = r["scores"]
        print(f"{r['rank']:<4} {r['symbol']:<8} {r['composite']:<8.4f} "
              f"{s.get('quality',0):<7.3f} {s.get('value',0):<7.3f} "
              f"{s.get('growth',0):<7.3f} {s.get('momentum',0):<7.3f}")
    print()
    print(f"三层票池: Watch={output['pools']['watch_count']} | "
          f"Monitor={output['pools']['monitor_count']} | "
          f"Deep={output['pools']['deep_count']}")


if __name__ == "__main__":
    main()
