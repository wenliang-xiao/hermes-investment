"""
trading/ — 专业 PaperTradingEngine 模拟交易引擎

支持 A 股 T+1、涨跌停、真实费用模型、每日快照持久化。
独立于 analysis/trading_engine.py，可桥接现有数据。
"""
from trading.models import PaperAccount, Position, Order
from trading.rules import (
    check_t1, check_price_limit, check_min_units,
    get_price_limit_range, get_board,
)
from trading.cost import calc_buy_cost, calc_sell_cost
from trading.engine import PaperTradingEngine
from trading.bridge import from_trading_signals

__all__ = [
    "PaperAccount", "Position", "Order",
    "check_t1", "check_price_limit", "check_min_units",
    "get_price_limit_range", "get_board",
    "calc_buy_cost", "calc_sell_cost",
    "PaperTradingEngine",
    "from_trading_signals",
]
