"""
analysis/cost_model.py — 独立成本模型

从 OSkhQuant 标准借鉴的 A 股真实交易成本计算。
支持按流通市值分级滑点。

用法:
    from engine.cost_model import calc_trade_cost, estimate_slippage_tier

    cost = calc_trade_cost(price=100, qty=1000, direction='buy', symbol='300502')
    # => {"slippage": X, "commission": Y, "stamp_tax": 0, ...}
"""
from __future__ import annotations

# ── A股交易费率 ──
COMMISSION_RATE = 0.00015      # 佣金万1.5
MIN_COMMISSION = 5.0           # 最低佣金5元
STAMP_TAX_RATE = 0.001         # 千1印花税(仅卖出)
TRANSFER_FEE_RATE = 0.00002    # 万0.2过户费(双向)
FLOW_FEE = 0.1                 # 每笔0.1元规费

# 滑点分级（按日均成交额）
SLIPPAGE_TIERS = [
    {"name": "L1-巨量", "min_adv": 50e8, "slippage": 0.0002},    # >50亿  (万分之2)
    {"name": "L2-大市", "min_adv": 10e8, "slippage": 0.0005},    # >10亿  (万分之5)
    {"name": "L3-中等", "min_adv": 5e8, "slippage": 0.001},      # >5亿   (千1)
    {"name": "L4-小盘", "min_adv": 1e8, "slippage": 0.003},      # >1亿   (千3)
    {"name": "L5-微盘", "min_adv": 0, "slippage": 0.01},          # <1亿   (1%)
]

# 内存缓存 {symbol -> tier_name} 避免重复查询
_adv_cache: dict[str, str | None] = {}


def estimate_slippage_tier(symbol: str) -> str:
    """估算某标的的滑点等级

    通过缓存的历史成交额数据判断。
    """
    if symbol in _adv_cache:
        return _adv_cache[symbol] or "L4-小盘"

    try:
        # 尝试从缓存的中位数成交额判断
        import pickle, os
        from pathlib import Path
        cache_dir = Path(__file__).parent.parent / "data" / "cache"
        # 找包含该symbol的成交额缓存
        for f in cache_dir.glob(f"*{symbol}*"):
            try:
                with open(f, "rb") as fh:
                    data = pickle.load(fh)
                if isinstance(data, dict) and "amount" in data:
                    amounts = [a for a in data["amount"] if a and a > 0]
                    if amounts:
                        import statistics
                        median_adv = statistics.median(amounts)
                        for tier in SLIPPAGE_TIERS:
                            if median_adv >= tier["min_adv"]:
                                _adv_cache[symbol] = tier["name"]
                                return tier["name"]
            except Exception:
                continue
    except Exception:
        pass

    # 默认中等
    _adv_cache[symbol] = None
    return "L4-小盘"


def get_slippage_rate(symbol: str) -> float:
    """获取某标的的滑点率"""
    tier_name = estimate_slippage_tier(symbol)
    for tier in SLIPPAGE_TIERS:
        if tier["name"] == tier_name:
            return tier["slippage"]
    return 0.003  # default


def calc_trade_cost(
    price: float,
    qty: int,
    direction: str,
    symbol: str = "",
    *,
    override_slippage: float | None = None,
) -> dict:
    """计算单笔交易成本

    Args:
        price: 成交价格
        qty: 成交数量
        direction: 'buy' 或 'sell'
        symbol: 标的代码（用于滑点分级）
        override_slippage: 强制指定滑点率（覆盖自动分级）

    Returns:
        {
            "slippage": float,       # 滑点成本(元)
            "commission": float,     # 佣金(元)
            "stamp_tax": float,      # 印花税(元, 仅卖出)
            "transfer_fee": float,   # 过户费(元)
            "flow_fee": float,       # 规费(元)
            "total": float,          # 总成本(元)
            "total_rate": float,     # 总成本率(占成交额)
            "slippage_rate": float,  # 滑点率
        }
    """
    turnover = price * qty
    is_sell = direction.lower() == "sell"

    # 佣金
    commission = max(turnover * COMMISSION_RATE, MIN_COMMISSION)

    # 印花税（仅卖出）
    stamp_tax = turnover * STAMP_TAX_RATE if is_sell else 0.0

    # 过户费（双向）
    transfer_fee = turnover * TRANSFER_FEE_RATE

    # 规费（固定）
    flow_fee = FLOW_FEE

    # 滑点
    if override_slippage is not None:
        slippage_rate = override_slippage
    else:
        slippage_rate = get_slippage_rate(symbol) if symbol else 0.003
    slippage = turnover * slippage_rate

    total = slippage + commission + stamp_tax + transfer_fee + flow_fee
    total_rate = total / turnover if turnover > 0 else 0

    return {
        "slippage": round(slippage, 2),
        "commission": round(commission, 2),
        "stamp_tax": round(stamp_tax, 2),
        "transfer_fee": round(transfer_fee, 2),
        "flow_fee": round(flow_fee, 2),
        "total": round(total, 2),
        "total_rate": round(total_rate, 6),
        "slippage_rate": slippage_rate,
    }


def calc_adjusted_price(
    price: float, qty: int, direction: str, symbol: str = "",
) -> tuple[float, dict]:
    """计算调整后的成交价格和成本明细

    Returns:
        (adjusted_price, cost_detail)
        买入: adjusted_price = price + slippage_per_share + other_costs_per_share
        卖出: adjusted_price = price - slippage_per_share - other_costs_per_share
    """
    cost = calc_trade_cost(price, qty, direction, symbol)
    total_cost = cost["total"]
    cost_per_share = total_cost / qty if qty > 0 else 0

    if direction.lower() == "sell":
        adjusted_price = price - cost_per_share
    else:
        adjusted_price = price + cost_per_share

    return round(adjusted_price, 4), cost
