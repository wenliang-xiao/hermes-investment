"""
trading/models.py — 模拟交易数据模型

PaperAccount: 资金账户总览
Position: 单只标的持仓
Order: 单笔委托
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    """单只标的持仓"""
    symbol: str                     # 标的代码
    name: str = ""                  # 标的名称
    total_quantity: int = 0        # 总持仓(含T日买入)
    available_quantity: int = 0    # 可用持仓(T+1解锁后)
    frozen_quantity: int = 0       # 冻结持仓(卖出委托占用)
    cost_price: float = 0.0        # 加权平均成本
    current_price: float = 0.0     # 当前市价
    buy_date: str = ""             # 最近买入日(YYYY-MM-DD)
    peak_price: float = 0.0        # 持仓期间最高价
    entry_score: float = 0.0       # 建仓时评分

    @property
    def market_value(self) -> float:
        return self.current_price * self.total_quantity

    @property
    def total_cost(self) -> float:
        return self.cost_price * self.total_quantity

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.cost_price) * self.total_quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        if self.cost_price > 0:
            return (self.current_price - self.cost_price) / self.cost_price * 100
        return 0.0

    @property
    def drawdown_from_peak(self) -> float:
        if self.peak_price > 0:
            return (self.current_price - self.peak_price) / self.peak_price * 100
        return 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "total_quantity": self.total_quantity,
            "available_quantity": self.available_quantity,
            "frozen_quantity": self.frozen_quantity,
            "cost_price": round(self.cost_price, 4),
            "current_price": round(self.current_price, 4),
            "market_value": round(self.market_value, 2),
            "total_cost": round(self.total_cost, 2),
            "unrealized_pnl": round(self.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(self.unrealized_pnl_pct, 2),
            "drawdown_from_peak": round(self.drawdown_from_peak, 2),
            "buy_date": self.buy_date,
            "peak_price": round(self.peak_price, 4),
            "entry_score": round(self.entry_score, 2) if self.entry_score else None,
        }


@dataclass
class Order:
    """单笔委托 — 含完整费用明细"""
    order_id: str
    symbol: str
    direction: str                 # "buy" / "sell"
    order_type: str = "market"     # "market" / "limit"
    price: float = 0.0             # 委托价(限价单) / 提交时市价(市价单)
    quantity: int = 0              # 委托数量
    filled_quantity: int = 0       # 已成交数量
    filled_price: float = 0.0      # 成交均价
    status: str = "pending"        # "pending"/"partial"/"filled"/"cancelled"/"rejected"
    commission: float = 0.0        # 佣金
    stamp_tax: float = 0.0         # 印花税
    transfer_fee: float = 0.0      # 过户费
    slippage_cost: float = 0.0     # 滑点成本
    reason: str = ""               # 交易理由
    reject_reason: str = ""        # 拒绝原因
    created_at: str = ""
    filled_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @property
    def total_cost(self) -> float:
        """全部费用合计"""
        return self.commission + self.stamp_tax + self.transfer_fee + self.slippage_cost

    @property
    def turnover(self) -> float:
        """成交金额"""
        return self.filled_price * self.filled_quantity

    @property
    def is_buy(self) -> bool:
        return self.direction == "buy"

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "direction": self.direction,
            "order_type": self.order_type,
            "price": round(self.price, 4),
            "quantity": self.quantity,
            "filled_quantity": self.filled_quantity,
            "filled_price": round(self.filled_price, 4),
            "status": self.status,
            "commission": round(self.commission, 2),
            "stamp_tax": round(self.stamp_tax, 2),
            "transfer_fee": round(self.transfer_fee, 2),
            "slippage_cost": round(self.slippage_cost, 2),
            "total_cost": round(self.total_cost, 2),
            "reason": self.reason,
            "reject_reason": self.reject_reason,
            "created_at": self.created_at,
            "filled_at": self.filled_at,
        }


@dataclass
class PaperAccount:
    """模拟账户总览"""
    account_id: str
    initial_cash: float        # 初始资金
    available_cash: float = 0.0  # 可用资金(含卖出所得)
    frozen_cash: float = 0.0     # 冻结资金(买入委托占用)
    positions: dict = field(default_factory=dict)      # symbol -> Position
    pending_orders: list = field(default_factory=list)  # list of Order
    order_history: list = field(default_factory=list)   # 已完成的历史委托
    realized_pnl: float = 0.0    # 累计已实现盈亏
    snapshots: list = field(default_factory=list)       # 每日快照列表

    def __post_init__(self):
        if self.available_cash == 0.0:
            self.available_cash = self.initial_cash
        if not self.positions:
            self.positions = {}

    @property
    def cash(self) -> float:
        """总现金 = 可用 + 冻结"""
        return self.available_cash + self.frozen_cash

    @property
    def position_value(self) -> float:
        """持仓总市值"""
        return sum(p.market_value for p in self.positions.values())

    @property
    def total_equity(self) -> float:
        """总权益 = 现金 + 持仓市值"""
        return self.cash + self.position_value

    @property
    def total_pnl(self) -> float:
        """总盈亏 = 已实现 + 未实现"""
        unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        return self.realized_pnl + unrealized

    @property
    def return_pct(self) -> float:
        """总收益率(%)"""
        if self.initial_cash > 0:
            return self.total_pnl / self.initial_cash * 100
        return 0.0

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "initial_cash": self.initial_cash,
            "available_cash": round(self.available_cash, 2),
            "frozen_cash": round(self.frozen_cash, 2),
            "total_cash": round(self.cash, 2),
            "position_value": round(self.position_value, 2),
            "total_equity": round(self.total_equity, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "total_pnl": round(self.total_pnl, 2),
            "return_pct": round(self.return_pct, 2),
            "position_count": len(self.positions),
            "pending_order_count": len(self.pending_orders),
            "positions": {sym: p.to_dict() for sym, p in self.positions.items()},
            "pending_orders": [o.to_dict() for o in self.pending_orders],
        }
