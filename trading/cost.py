"""
trading/cost.py — A 股真实交易费用模型 (2026 年费率标准)

费用构成:
  佣金:     万 2.5 (双向), 最低 5 元
  印花税:   千 0.5 (仅卖出方)
  过户费:   十万分之 1 (双向)
  滑点模拟: 买入 +bp, 卖出 -bp (按价格分层)

返回结构统一为 dict，直接可用于 Order.dataclass 赋值。
"""
from __future__ import annotations

# ── 2026 年 A 股费率常量 ──
COMMISSION_RATE = 0.00025         # 万 2.5 佣金
MIN_COMMISSION = 5.0              # 最低佣金 5 元
STAMP_TAX_RATE = 0.0005           # 千 0.5 印花税 (仅卖出)
TRANSFER_FEE_RATE = 0.00001       # 十万分之 1 过户费 (双向)

# ── 滑点分层 (按价格区间) ──
# 高价股流动性差，滑点更小(bp)；低价股滑点更大
SLIPPAGE_TIERS = [
    {"min_price": 100,  "bps_buy": 8,   "bps_sell": 8},    # 高价 >100: 8bp
    {"min_price": 30,   "bps_buy": 10,  "bps_sell": 10},   # 中价 30-100: 10bp
    {"min_price": 10,   "bps_buy": 15,  "bps_sell": 15},   # 中低价 10-30: 15bp
    {"min_price": 0,    "bps_buy": 30,  "bps_sell": 30},   # 低价 <10: 30bp
]

# 默认滑点 (按要求的简化版 ±0.1%)
DEFAULT_SLIPPAGE_BPS = 10   # 买入 +10bp, 卖出 -10bp


def _get_slippage_bps(price: float, direction: str) -> float:
    """按价格区间获取滑点 bps 数"""
    for tier in SLIPPAGE_TIERS:
        if price >= tier["min_price"]:
            return tier["bps_buy"] if direction == "buy" else tier["bps_sell"]
    return DEFAULT_SLIPPAGE_BPS


def calc_buy_cost(price: float, quantity: int) -> dict:
    """计算买入总成本

    Args:
        price: 买入委托价
        quantity: 买入股数

    Returns:
        {
            commission:   float,    # 佣金
            stamp_tax:    0.0,      # 印花税(买入为0)
            transfer_fee: float,    # 过户费
            slippage_cost:float,    # 滑点成本(元)
            slippage_bps:  int,     # 滑点 bps
            adjusted_price:float,   # 调整后成交价(含滑点)
            total_cost:    float,   # 总费用
            actual_payment:float,   # 实际支付金额
        }
    """
    turnover = price * quantity

    # 佣金(双向, 最低 5 元)
    commission = max(turnover * COMMISSION_RATE, MIN_COMMISSION)

    # 买入无印花税
    stamp_tax = 0.0

    # 过户费(双向)
    transfer_fee = turnover * TRANSFER_FEE_RATE

    # 滑点(买入价上浮)
    slippage_bps = _get_slippage_bps(price, "buy")
    slippage_rate = slippage_bps / 10000.0
    slippage_cost = turnover * slippage_rate
    adjusted_price = price * (1 + slippage_rate)

    total_cost = commission + stamp_tax + transfer_fee + slippage_cost
    actual_payment = turnover + total_cost

    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "slippage_cost": round(slippage_cost, 2),
        "slippage_bps": slippage_bps,
        "adjusted_price": round(adjusted_price, 4),
        "total_cost": round(total_cost, 2),
        "actual_payment": round(actual_payment, 2),
    }


def calc_sell_cost(price: float, quantity: int) -> dict:
    """计算卖出总成本

    Args:
        price: 卖出委托价
        quantity: 卖出股数

    Returns:
        {
            commission:    float,    # 佣金
            stamp_tax:     float,    # 印花税
            transfer_fee:  float,    # 过户费
            slippage_cost: float,    # 滑点成本(元)
            slippage_bps:  int,      # 滑点 bps
            adjusted_price:float,    # 调整后成交价(含滑点)
            total_cost:    float,    # 总费用
            net_proceeds:  float,    # 实际到手金额
        }
    """
    turnover = price * quantity

    # 佣金(双向, 最低 5 元)
    commission = max(turnover * COMMISSION_RATE, MIN_COMMISSION)

    # 印花税(仅卖出)
    stamp_tax = turnover * STAMP_TAX_RATE

    # 过户费(双向)
    transfer_fee = turnover * TRANSFER_FEE_RATE

    # 滑点(卖出价下浮)
    slippage_bps = _get_slippage_bps(price, "sell")
    slippage_rate = slippage_bps / 10000.0
    slippage_cost = turnover * slippage_rate
    adjusted_price = price * (1 - slippage_rate)

    total_cost = commission + stamp_tax + transfer_fee + slippage_cost
    net_proceeds = turnover - total_cost

    return {
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "slippage_cost": round(slippage_cost, 2),
        "slippage_bps": slippage_bps,
        "adjusted_price": round(adjusted_price, 4),
        "total_cost": round(total_cost, 2),
        "net_proceeds": round(net_proceeds, 2),
    }
