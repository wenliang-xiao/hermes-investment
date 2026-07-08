"""
trading/rules.py — A 股交易规则

- T+1: 当日买入次日才能卖出
- 涨跌停: 主板±10%、创业板/科创板±20%、ST±5%
- 最小单位: 买入100股整数倍, 卖出可零股
- 板块识别: 通过代码前缀判断
"""
from __future__ import annotations
from datetime import date, datetime
from trading.models import Position


# ═══════════════════════════════════════════
# 板块识别
# ═══════════════════════════════════════════

ST_PREFIXES = ("ST", "*ST", "SST", "S*ST")


def get_board(symbol: str) -> str:
    """识别标的所属板块

    Returns:
        "main"    — 主板 (60xxxx/00xxxx)
        "chinext" — 创业板 (30xxxx)
        "star"    — 科创板 (688xxx)
        "st"      — ST 股
        "other"   — 非 A 股(港股/美股/ETF 等)
    """
    sym = str(symbol).strip()

    # 过滤非 A 股
    if "." in sym or not sym.isdigit() or len(sym) != 6:
        return "other"

    # ST 检测（通过代码匹配，实际需配合数据源确认）
    # 这里只做代码前缀判断

    if sym.startswith("300"):
        return "chinext"
    if sym.startswith("688"):
        return "star"
    if sym.startswith(("60", "00")):
        return "main"
    # 4 开头一般不存在 A 股
    return "other"


def get_price_limit_range(symbol: str, prev_close: float = 0.0) -> tuple:
    """获取涨跌停价格范围

    Args:
        symbol: 标的代码
        prev_close: 前收盘价(元)。若为 0 则只返回百分比限制

    Returns:
        (lower, upper, limit_pct)
        lower: 跌停价 (prev_close * (1 - limit_pct))
        upper: 涨停价 (prev_close * (1 + limit_pct))
        limit_pct: 涨跌幅限制(小数形式)
    """
    board = get_board(symbol)

    # 涨跌幅限制
    limit_map = {
        "main":    0.10,
        "chinext": 0.20,
        "star":    0.20,
        "other":   99.0,    # 非 A 股无涨跌停
    }

    # ST 检测: 通过 symbol 本身判断(假如带 ST 前缀)
    # 实际调用时需外部配合数据源
    sym_upper = str(symbol).upper()
    is_st = any(sym_upper.startswith(p) for p in ST_PREFIXES)
    if is_st:
        limit_pct = 0.05
    else:
        limit_pct = limit_map.get(board, 0.10)

    if prev_close <= 0:
        return (-limit_pct, limit_pct, limit_pct)  # 返回百分比

    lower = round(prev_close * (1 - limit_pct), 4)
    upper = round(prev_close * (1 + limit_pct), 4)
    return (lower, upper, limit_pct)


def check_price_limit(symbol: str, price: float, prev_close: float) -> tuple:
    """检查价格是否在涨跌停范围内

    Returns:
        (is_valid, message)
    """
    lower, upper, limit_pct = get_price_limit_range(symbol, prev_close)

    if limit_pct >= 1.0:
        # 非 A 股，不检查涨跌停
        return (True, "")

    if price < lower:
        return (False, f"{symbol}: {price} 低于跌停价 {lower:.2f} (-{limit_pct*100:.0f}%)")
    if price > upper:
        return (False, f"{symbol}: {price} 高于涨停价 {upper:.2f} (+{limit_pct*100:.0f}%)")
    return (True, "")


# ═══════════════════════════════════════════
# T+1 规则
# ═══════════════════════════════════════════


def check_t1(position: Position | None, today: str | None = None) -> tuple:
    """检查 T+1 卖出限制

    规则: T 日买入的股票，T+1 日才能卖出。
    position.available_quantity 表示已解锁的可卖数量。

    Args:
        position: 持仓对象(None 表示无持仓)
        today: 今日日期(YYYY-MM-DD)

    Returns:
        (is_unlocked, message)
        is_unlocked: True 表示有可卖持仓
    """
    if position is None:
        return (False, "无该标持仓")

    if position.total_quantity <= 0:
        return (False, "持仓数量为 0")

    if position.available_quantity > 0:
        return (True, f"可卖出 {position.available_quantity} 股")

    # 今日买入的全部冻结 → T+1 未解锁
    buy_date = position.buy_date or "未知"
    return (False, f"T+1 未解锁(买入日 {buy_date}), 可用 0/{position.total_quantity} 股")


def unlock_t1_positions(account, today: str):
    """每日开市前解锁 T+1 持仓

    规则: 上日买入的持仓在今天解锁为 available。
    调用时机: 每天 match_orders() 之后 / update_prices() 之前
    """
    if isinstance(today, date):
        today = today.strftime("%Y-%m-%d")

    for sym, pos in account.positions.items():
        if pos.buy_date and pos.buy_date != today:
            # 非今日买入 → 全部解锁
            pos.available_quantity = pos.total_quantity
            pos.frozen_quantity = 0
        elif pos.buy_date == today:
            # 今日买入 → 保持冻结
            pos.available_quantity = 0
            pos.frozen_quantity = 0  # 非卖出冻结，是 T+1 锁定
            # 注: 今日买入 frozen_quantity 由上笔卖出委托设置
        else:
            # 无 buy_date → 视为已解锁
            pos.available_quantity = pos.total_quantity
            pos.frozen_quantity = 0


# ═══════════════════════════════════════════
# 最小交易单位
# ═══════════════════════════════════════════

MIN_LOT = 100  # A 股最小买入单位（1 手）


def check_min_units(direction: str, quantity: int) -> tuple:
    """检查最小交易单位

    - 买入: 必须是 100 的整数倍
    - 卖出: 任意数量（含零股）

    Returns:
        (is_valid, message)
    """
    direction = str(direction).lower()
    qty = int(quantity)

    if qty <= 0:
        return (False, "委托数量必须 > 0")

    if direction == "buy":
        if qty % MIN_LOT != 0:
            return (False, f"买入必须是 {MIN_LOT} 股的整数倍, 当前 {qty}")
        return (True, "")

    if direction == "sell":
        return (True, "")

    return (False, f"未知方向: {direction}")


def round_down_lot(amount: int) -> int:
    """向下取整到整手"""
    return (amount // MIN_LOT) * MIN_LOT


def round_up_lot(amount: int) -> int:
    """向上取整到整手"""
    return ((amount + MIN_LOT - 1) // MIN_LOT) * MIN_LOT
