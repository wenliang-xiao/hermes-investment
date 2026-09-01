"""
backtest_types.py — 统一回测结果数据结构

所有回测引擎( evaluator_fixed.py / analysis/backtest.py / _archive/backtest_v2.py )
统一输出 BacktestResult，Dashboard 回测面板依赖此格式。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date as DateType
from typing import Optional


@dataclass
class BacktestResult:
    """统一的回测结果

    净值曲线 + 风险指标 + 交易记录 + 基准对比。
    """

    strategy_name: str

    # 回测时间范围
    start_date: str  # "YYYY-MM-DD"
    end_date: str    # "YYYY-MM-DD"

    # 资金与终值
    initial_cash: float
    final_value: float

    # 收益指标
    total_return_pct: float
    annualized_return_pct: float

    # 风险调整指标
    sharpe_ratio: float
    sortino_ratio: Optional[float]  # None = 数据不足未计算（不 fallback 到 score）
    max_drawdown_pct: float
    calmar_ratio: float

    # 交易统计
    win_rate_pct: float
    trade_count: int

    # 序列数据
    equity_curve: list[dict] = field(default_factory=list)
    # ^ [{date: "YYYY-MM-DD", value: float}]

    trades: list[dict] = field(default_factory=list)
    # ^ [{date: "YYYY-MM-DD", symbol, action, price, qty, pnl, reason}]

    benchmark: Optional[list[dict]] = None
    # ^ [{date: "YYYY-MM-DD", value: float}] — 沪深300基准，暂无则为 None

    # 额外元信息
    extra: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        """转为 JSON 兼容 dict（用于 API 返回）"""
        result = asdict(self)
        # 清理 None 基准
        if result.get("benchmark") is None:
            result["benchmark"] = []
        # 评分模式从 extra 提升到顶层 (API/前端直接可读)
        result["scoring_mode"] = self.scoring_mode
        return result

    @property
    def scoring_mode(self) -> str:
        """评分模式: point_in_time / fixed_score (从 extra 映射, 直接可读)"""
        return self.extra.get("scoring_mode", "fixed_score")

    @classmethod
    def from_evaluator_dict(
        cls,
        raw: dict,
        strategy_name: str = "",
        start_date: str = "",
        end_date: str = "",
        equity_curve: list[dict] | None = None,
        trades: list[dict] | None = None,
    ) -> "BacktestResult":
        """从 evaluator_fixed._compute_metrics() 的 dict 构造 BacktestResult

        用于向后兼容旧的 dict 输出格式。
        """
        annualized = raw.get("annualized_return_pct", 0.0)
        mdd = raw.get("max_drawdown_pct", 0.0)
        calmar = annualized / mdd if mdd > 0 else 0.0

        return cls(
            strategy_name=raw.get("strategy", strategy_name),
            start_date=start_date,
            end_date=end_date,
            initial_cash=raw.get("initial_cash", 1_000_000.0),
            final_value=raw.get("final_value", 1_000_000.0),
            total_return_pct=raw.get("total_return_pct", 0.0),
            annualized_return_pct=annualized,
            sharpe_ratio=raw.get("sharpe_ratio", 0.0),
            sortino_ratio=raw.get("sortino_ratio"),
            max_drawdown_pct=mdd,
            calmar_ratio=round(calmar, 4),
            win_rate_pct=raw.get("win_rate_pct", 0.0),
            trade_count=raw.get("trade_count", 0),
            equity_curve=equity_curve or [],
            trades=trades or [],
            benchmark=None,
            extra={
                "total_days": raw.get("total_days", 0),
                "universe_size": raw.get("universe_size", 0),
                "stocks_with_data": raw.get("stocks_with_data", 0),
                **raw.get("extra", {}),
            },
        )
