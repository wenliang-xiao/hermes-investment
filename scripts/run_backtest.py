#!/usr/bin/env python3
"""
回测 CLI — 使用 evaluator_fixed 对指定策略运行回测并保存到 data/backtest/

用法:
    python3 scripts/run_backtest.py faceji --from 2020-01-01 --to 2025-12-31
    python3 scripts/run_backtest.py silverquant --walk-forward --cycles 3
    python3 scripts/run_backtest.py --list
"""
import sys, os, argparse, json, uuid
_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
try:
    from dotenv import load_dotenv
    _env_path = os.environ.get("HERMES_ENV", os.path.join(os.path.dirname(_PROJECT_DIR), ".env"))
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except Exception:
    pass

from datetime import datetime, date


def do_list():
    """列出已有回测结果"""
    from engine.backtest_storage import list_results
    results = list_results()
    if not results:
        print("📭 暂无回测结果")
        return
    print(f"📊 共 {len(results)} 条回测结果:\n")
    print(f"{'策略':<15} {'run_id':<30} {'日期范围':<25} {'Sortino':<8} {'收益率':<8} {'交易数':<6}")
    print("-" * 95)
    for r in results:
        dr = r.get("date_range", {})
        dr_str = f"{dr.get('from','?')} → {dr.get('to','?')}"
        sortino = f"{r.get('avg_sortino','?'):.2f}" if isinstance(r.get('avg_sortino'), (int,float)) else "?"
        ret = f"{r.get('avg_return_pct','?'):.1f}%" if isinstance(r.get('avg_return_pct'), (int,float)) else "?"
        print(f"{r.get('strategy','?'):<15} {r.get('run_id','?'):<30} {dr_str:<25} {sortino:<8} {ret:<8} {r.get('total_trades','?'):<6}")


def do_run(args):
    """运行回测并保存"""
    from engine.evaluator_fixed import evaluate_strategy

    strategy = args.strategy
    print(f"🚀 运行回测: {strategy}")
    print(f"   日期: {args.from_date} → {args.to_date}")
    print(f"   Walk-Forward: {'是' if args.walk_forward else '否'} ({args.cycles} cycles)")

    result = evaluate_strategy(
        strategy_name=strategy,
        walk_forward=args.walk_forward,
        cycles=args.cycles,
    )

    if result is None or (isinstance(result, dict) and "error" in result):
        print(f"❌ 回测失败: {result.get('error','未知错误') if isinstance(result, dict) else '无结果'}")
        return

    # 兼容 BacktestResult 和旧 dict 格式
    from engine.backtest_types import BacktestResult
    if isinstance(result, BacktestResult):
        br = result
        avg_sortino = br.sortino_ratio if not args.walk_forward else br.extra.get("avg_sortino", 0)
        avg_return = br.total_return_pct if not args.walk_forward else br.extra.get("avg_return_pct", 0)
        avg_mdd = br.max_drawdown_pct if not args.walk_forward else br.extra.get("avg_max_drawdown_pct", 0)
        total_trades = br.trade_count if not args.walk_forward else br.extra.get("total_trades", 0)
        stocks_data = br.extra.get("stocks_with_data", 0)
        cycle_details = br.extra.get("cycle_details", [])
        sortino_raw = br.sortino_ratio
        score_raw = br.sortino_ratio
    else:
        avg_sortino = result.get("avg_sortino", result.get("score", 0))
        avg_return = result.get("avg_return_pct", result.get("total_return_pct", 0))
        avg_mdd = result.get("avg_max_drawdown_pct", result.get("max_drawdown_pct", 0))
        total_trades = result.get("total_trades", result.get("trade_count", 0))
        stocks_data = result.get("stocks_with_data", 0)
        cycle_details = result.get("cycle_details", [])
        sortino_raw = result.get("sortino_ratio") or result.get("score", 0)
        score_raw = result.get("score", 0)

    print(f"\n✅ 回测完成!")
    print(f"   Sortino: {avg_sortino:.4f}" if isinstance(avg_sortino, (int, float)) else f"   Sortino: {avg_sortino}")
    print(f"   收益率: {avg_return:.2f}%" if isinstance(avg_return, (int, float)) else f"   收益率: {avg_return}")

    # 转换为标准 schema 并保存
    from engine.backtest_storage import save_result
    standard = {
        "meta": {
            "strategy": strategy,
            "symbols": [],
            "date_range": {"from": args.from_date, "to": args.to_date},
            "days": 0,
            "walk_forward_cycles": args.cycles if args.walk_forward else 0,
            "run_id": f"bt_{strategy}_{date.today().strftime('%Y%m%d')}_{uuid.uuid4().hex[:4]}",
            "generated_at": datetime.now().isoformat(),
        },
        "cycles": cycle_details if args.walk_forward else [],
        "aggregate": {
            "avg_sortino": round(avg_sortino, 4) if isinstance(avg_sortino, (int, float)) else 0,
            "avg_return_pct": avg_return,
            "avg_max_dd_pct": avg_mdd,
            "total_trades": total_trades,
            "total_symbols_traded": stocks_data,
        },
        "cost_model": {"commission_rate": 0.00015, "stamp_tax_rate": 0.001},
    }
    path = save_result(strategy, standard)
    print(f"   💾 已保存: {path}")


def main():
    parser = argparse.ArgumentParser(description="面基回测系统 CLI")
    parser.add_argument("strategy", nargs="?", choices=["faceji", "silverquant", "tradingagents"],
                        help="策略名称")
    parser.add_argument("--from", dest="from_date", default="2020-01-01",
                        help="起始日期 (默认 2020-01-01)")
    parser.add_argument("--to", dest="to_date", default="2025-12-31",
                        help="结束日期 (默认 2025-12-31)")
    parser.add_argument("--walk-forward", action="store_true", help="启用 Walk-Forward")
    parser.add_argument("--cycles", type=int, default=3, help="Walk-Forward 轮数")
    parser.add_argument("--list", action="store_true", help="列出已有结果")
    parser.add_argument("--save", action="store_true", default=True,
                        help="保存结果到 data/backtest/ (默认: true)")

    args = parser.parse_args()

    if args.list:
        do_list()
    elif args.strategy:
        do_run(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
