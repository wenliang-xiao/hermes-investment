"""
strategies/base.py — 纯数据类型定义

所有策略共享的类型定义。纯数据，无行为，无IO。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

try:
    from investment_system import config as _config   # 已 pip install 的包形态
except ImportError:
    import config as _config                          # 本地源码形态

_DISC = getattr(_config, "TRADING_DISCIPLINE", {}) or {}
_RISK = getattr(_config, "RISK_PARAMS", {}) or {}

# 四档 trailing stop 默认值（与 config.TRADING_DISCIPLINE 保持一致）
_DEFAULT_TIERS = [
    {"min_pnl": 0.30, "threshold_pct": -12.0, "label": "T3"},
    {"min_pnl": 0.10, "threshold_pct": -15.0, "label": "T2"},
    {"min_pnl": None, "threshold_pct": -20.0, "label": "T1"},
]
TRAILING_MIN_HOLD_DAYS = int(_DISC.get("trailing_stop_min_hold_days", 10))


def trailing_stop_threshold(pnl_pct: float) -> tuple[float, str]:
    """按四档规则返回 (峰值回撤阈值%, 档位标签)。

    pnl_pct 为浮盈百分比（如 12.5 表示 +12.5%）。
    规则见 docs/STRATEGY.md §5.4 / config.TRADING_DISCIPLINE。
    """
    ratio = (pnl_pct or 0) / 100.0
    for tier in (_DISC.get("trailing_stop_tiers") or _DEFAULT_TIERS):
        min_pnl = tier.get("min_pnl")
        if min_pnl is None or ratio >= float(min_pnl):
            return float(tier.get("threshold_pct")), str(tier.get("label", ""))
    return -20.0, "T1"


def hold_days(entry_date: str) -> int | None:
    """持仓天数；日期缺失/不可解析时返回 None（调用方不得据此放宽风控）。"""
    if not entry_date:
        return None
    try:
        return (datetime.now() - datetime.strptime(str(entry_date)[:10], "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return None


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


_LIMITS = _DISC.get("strategy_limits", {}) or {}
_FJ = _LIMITS.get("faceji", {}) or {}
_SQ = _LIMITS.get("silverquant", {}) or {}
_TA = _LIMITS.get("tradingagents", {}) or {}
_STOP_LOSS_PCT = -abs(float(_RISK.get("stop_loss_pct", 0.08))) * 100
_MAX_TOTAL_POSITIONS = int(_RISK.get("max_total_positions", 8))


@dataclass
class FacejiConfig:
    """面基策略参数（默认值来自 config.TRADING_DISCIPLINE / RISK_PARAMS，ADR-0005）"""
    entry_threshold: float = 5.0
    exit_threshold: float = 4.5        # ScoreDropSeller
    max_positions: int = int(_FJ.get("max_positions", _MAX_TOTAL_POSITIONS))
    max_candidates: int = int(_FJ.get("max_candidates", 5))
    hard_stop_loss_pct: float = _STOP_LOSS_PCT    # HardSeller（ATR 自适应以此为底限）
    kelly_odds: float = 2.0
    kelly_fraction: float = 0.5         # 半凯利
    max_position_pct: float = float(_FJ.get("max_position_pct", _RISK.get("max_single_position", 0.12)))
    ma_trend_boost_threshold: float = 5.5  # 评分高于此免除MA趋势过滤


@dataclass
class SilverQuantConfig:
    """SilverQuant策略参数（默认值来自 config，ADR-0005）"""
    entry_threshold: float = 5.0
    max_positions: int = int(_SQ.get("max_positions", _MAX_TOTAL_POSITIONS))
    max_candidates: int = int(_SQ.get("max_candidates", 5))
    slot_amount: float = float(_DISC.get("silverquant_slot_amount", 30000.0))
    hard_stop_loss_pct: float = _STOP_LOSS_PCT
    score_drop_threshold: float = 4.5
    ma_sell_pnl_exemption: float = -5.0  # MA死叉且亏损超过此值时不卖


@dataclass
class TradingAgentsConfig:
    """TradingAgents策略参数（默认值来自 config，ADR-0005）"""
    max_positions: int = int(_TA.get("max_positions", 6))
    max_candidates: int = int(_TA.get("max_candidates", 3))
    debate_entry_threshold: float = 5.5
    debate_force_sell: float = 4.0
    debate_weak_sell: float = 5.0
    kelly_odds: float = 1.8
    kelly_fraction: float = 0.5
    max_position_pct: float = float(_TA.get("max_position_pct", _RISK.get("max_single_position", 0.12)))
    hard_stop_loss_pct: float = _STOP_LOSS_PCT
