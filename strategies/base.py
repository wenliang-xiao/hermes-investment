"""
strategies/base.py — 纯数据类型定义

所有策略共享的类型定义。纯数据，无行为，无IO。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


Action = Literal["BUY", "SELL", "HOLD"]
Priority = Literal["HIGH", "MED", "LOW"]


@dataclass
class Signal:
    """交易信号 —— 纯数据"""
    symbol: str
    action: Action
    price: float
    reason: str = ""
    priority: Priority = "MED"
    size_pct: float | None = None   # BUY时建议仓位占比(%)
    pnl_pct: float | None = None    # SELL时浮动盈亏(%)
    score: float | None = None      # 生成该信号的评分
    name: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "action": self.action,
            "price": round(self.price, 2) if self.price else 0,
            "reason": self.reason,
            "priority": self.priority,
            "size_pct": self.size_pct,
            "pnl_pct": round(self.pnl_pct, 2) if self.pnl_pct else None,
            "score": round(self.score, 1) if self.score else None,
        }


@dataclass
class PositionData:
    """持仓快照 —— 只读，纯数据"""
    symbol: str
    entry_price: float
    quantity: int
    entry_date: str = ""
    peak: float | None = None
    current_price: float | None = None

    @property
    def pnl_pct(self) -> float:
        cp = self.current_price or self.entry_price
        return (cp - self.entry_price) / self.entry_price * 100

    @property
    def drawdown_from_peak(self) -> float:
        if self.peak and self.current_price:
            return (self.current_price - self.peak) / self.peak * 100
        return 0.0


@dataclass
class FacejiConfig:
    """面基策略参数"""
    entry_threshold: float = 5.0
    exit_threshold: float = 4.5        # ScoreDropSeller
    max_positions: int = 8
    max_candidates: int = 5
    hard_stop_loss_pct: float = -8.0    # HardSeller
    trailing_stop_pct: float = -12.0   # FallSeller
    kelly_odds: float = 2.0
    kelly_fraction: float = 0.5         # 半凯利
    max_position_pct: float = 0.08      # 单笔上限8%
    ma_trend_boost_threshold: float = 5.5  # 评分高于此免除MA趋势过滤


@dataclass
class SilverQuantConfig:
    """SilverQuant策略参数"""
    entry_threshold: float = 5.0
    max_positions: int = 8
    max_candidates: int = 5
    slot_amount: float = 30000.0
    hard_stop_loss_pct: float = -8.0
    trailing_stop_pct: float = -12.0
    score_drop_threshold: float = 4.5
    ma_sell_pnl_exemption: float = -5.0  # MA死叉且亏损超过此值时不卖


@dataclass
class TradingAgentsConfig:
    """TradingAgents策略参数"""
    max_positions: int = 6
    max_candidates: int = 3
    debate_entry_threshold: float = 5.5
    debate_force_sell: float = 4.0
    debate_weak_sell: float = 5.0
    kelly_odds: float = 1.8
    kelly_fraction: float = 0.5
    max_position_pct: float = 0.12
    hard_stop_loss_pct: float = -8.0
