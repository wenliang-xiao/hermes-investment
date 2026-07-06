#!/usr/bin/env python3
"""
回测 CLI — 使用 evaluator_fixed 对指定策略运行回测并保存到 data/backtest/

用法:
    python3 scripts/run_backtest.py faceji --from 2020-01-01 --to 2025-12-31
    python3 scripts/run_backtest.py silverquant --walk-forward --cycles 3
    python3 scripts/run_backtest.py --list
"""
import sys, os, argparse, json, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date


def do_list():
    """列出已有回测结果"""
    from analysis.backtest_storage import list_results
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
    from evaluator_fixed import evaluate_strategy

    strategy = args.strategy
    print(f"🚀 运行回测: {strategy}")
    print(f"   日期: {args.from_date} → {args.to_date}")
    print(f"   Walk-Forward: {'是' if args.walk_forward else '否'} ({args.cycles} cycles)")

    result = evaluate_strategy(
        strategy_name=strategy,
        walk_forward=args.walk_forward,
        cycles=args.cycles,
    )

    if result is None:
        print("❌ 回测失败")
        return

    print(f"\n✅ 回测完成!")
    print(f"   Sortino: {result.get('avg_sortino', '?'):.4f}")
    print(f"   收益率: {result.get('avg_return_pct', '?'):.2f}%")

    # 转换为标准 schema 并保存
    from analysis.backtest_storage import save_result
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
        "cycles": result.get("cycle_details", []) if args.walk_forward else [],
        "aggregate": {
            "avg_sortino": round(result.get("avg_sortino", result.get("score", 0)), 4),
            "avg_return_pct": result.get("avg_return_pct", result.get("total_return_pct", 0)),
            "avg_max_dd_pct": result.get("avg_max_drawdown_pct", result.get("max_drawdown_pct", 0)),
            "total_trades": result.get("total_trades", result.get("trade_count", 0)),
            "total_symbols_traded": result.get("stocks_with_data", 0),
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
