"""
手动交易记录器
用户执行交易后，用此脚本记录到 shadow_account 和 trade_log

用法：
  python3 scripts/manual_trade.py --strategy faceji --action BUY --symbol 603259 --price 92.21 --size 0.03
  python3 scripts/manual_trade.py --strategy silverquant --action SELL --symbol 300502 --price 580 --pnl -230

或交互式：
  python3 scripts/manual_trade.py
"""
import sys, os, json, argparse
from datetime import date, datetime

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)

from analysis.trading_engine import TradingEngine
from domain import WATCHLIST


def get_name(sym):
    info = WATCHLIST.get(sym, {})
    if isinstance(info, dict):
        return info.get("name", sym)
    return str(info)


def record(strategy, action, symbol, price, size_pct=None, pnl_pct=None, reason=""):
    """记录一笔手动交易"""
    engine = TradingEngine()

    # 构建信号
    signal = {
        "id": f"MANUAL-{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "strategy": strategy,
        "action": action,
        "symbol": symbol,
        "name": get_name(symbol),
        "price": price,
        "size_pct": size_pct,
        "pnl_pct": pnl_pct,
        "reason": reason or f"手动{action}",
        "priority": "HIGH",
        "manual": True,
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 在engine中执行（更新内部状态）
    ok, msg = engine.execute_signal(signal)
    if ok:
        print(f"✅ 记录成功")
        print(f"   {strategy} {action} {symbol}({get_name(symbol)}) @{price}")
        if size_pct:
            print(f"   仓位: {size_pct:.1f}%")
        if pnl_pct is not None:
            print(f"   盈亏: {pnl_pct:+.2f}%")
        return signal
    else:
        print(f"❌ 记录失败: {msg}")
        return None


def interactive():
    """交互式录入"""
    print("📋 手动交易记录器")
    print("─" * 40)
    strategy = input("策略 (faceji/silverquant/tradingagents): ").strip()
    action = input("操作 (BUY/SELL): ").strip().upper()
    symbol = input("标的代码: ").strip()
    price_str = input("成交价格: ").strip()
    price = float(price_str) if price_str else 0

    size_pct = None
    pnl_pct = None
    if action == "BUY":
        size_str = input("仓位占比% (如3.0): ").strip()
        size_pct = float(size_str) if size_str else None
    else:
        pnl_str = input("盈亏% (如-2.3): ").strip()
        pnl_pct = float(pnl_str) if pnl_str else None

    reason = input("原因 (可选): ").strip()
    record(strategy, action, symbol, price, size_pct, pnl_pct, reason)


def main():
    parser = argparse.ArgumentParser(description="手动交易记录")
    parser.add_argument("--strategy", choices=["faceji", "silverquant", "tradingagents"], help="策略名")
    parser.add_argument("--action", choices=["BUY", "SELL"], help="操作")
    parser.add_argument("--symbol", type=str, help="标的代码")
    parser.add_argument("--price", type=float, help="成交价格")
    parser.add_argument("--size", type=float, help="仓位占比 (BUY用)")
    parser.add_argument("--pnl", type=float, help="盈亏% (SELL用)")
    parser.add_argument("--reason", type=str, default="", help="原因")

    args = parser.parse_args()

    if args.strategy and args.action and args.symbol and args.price:
        record(args.strategy, args.action, args.symbol, args.price,
               args.size, args.pnl, args.reason)
    else:
        interactive()


if __name__ == "__main__":
    main()
