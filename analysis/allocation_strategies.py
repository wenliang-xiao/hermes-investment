"""
analysis/allocation_strategies.py — ETF 资产配置策略

多种配置模型实现，供 etf_backtest 调用。

策略:
1. FixedMix — 固定比例 (60/40, 50/50)
2. RiskParity — 风险平价 (波动率倒数×协方差)
3. GridRebalance — 网格再平衡 (±5%偏离触发)
4. TrendFollowing — 趋势跟踪 (MA20/MA60)

用法:
    from analysis.allocation_strategies import FixedMix, RiskParity

    strat = FixedMix({"SPY": 0.6, "TLT": 0.4})
    weights = strat.compute(price_data)  # 每日权重
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Callable


class AllocationStrategy:
    """资产配置策略基类"""

    def __init__(self, name: str):
        self.name = name

    def compute(self, price_df: pd.DataFrame, date_idx: int) -> dict[str, float]:
        """返回 {symbol: weight} 权重映射，总和=1.0"""
        raise NotImplementedError


class FixedMix(AllocationStrategy):
    """固定比例配置

    最简单的基准策略。例: 60% SPY + 40% TLT
    """

    def __init__(self, weights: dict[str, float], name: str = ""):
        super().__init__(name or f"Fixed_{'_'.join(weights.keys())}")
        # 归一化
        total = sum(weights.values())
        self.target_weights = {k: v / total for k, v in weights.items()}

    def compute(self, price_df: pd.DataFrame, date_idx: int) -> dict[str, float]:
        return dict(self.target_weights)


class RiskParity(AllocationStrategy):
    """风险平价配置

    使用 rolling 60 天窗口计算波动率倒数作为权重。
    可选的协方差调整版本。
    """

    def __init__(self, symbols: list[str], window: int = 60,
                 use_covariance: bool = False, name: str = "RiskParity"):
        super().__init__(name)
        self.symbols = symbols
        self.window = window
        self.use_covariance = use_covariance

    def compute(self, price_df: pd.DataFrame, date_idx: int) -> dict[str, float]:
        if date_idx < self.window + 5:
            # 数据不足：等权
            return {s: 1.0 / len(self.symbols) for s in self.symbols}

        # 取 window 天的收益率
        prices = {}
        for s in self.symbols:
            if s in price_df.columns:
                col = price_df[s].dropna().iloc[:date_idx + 1]
                if len(col) > self.window:
                    prices[s] = col.iloc[-self.window:]

        if len(prices) < 2:
            return {s: 1.0 / len(self.symbols) for s in self.symbols}

        ret_df = pd.DataFrame(prices).pct_change().dropna()

        if ret_df.empty or len(ret_df) < 5:
            return {s: 1.0 / len(self.symbols) for s in self.symbols}

        if self.use_covariance:
            # 协方差风险平价: 权重与 marginal risk contribution 成反比
            cov = ret_df.cov()
            inv_vol = 1.0 / np.sqrt(np.diag(cov))
            weights = inv_vol / inv_vol.sum()
        else:
            # 简单波动率倒数
            vols = ret_df.std()
            inv_vol = 1.0 / vols.replace(0, np.nan)
            weights = inv_vol / inv_vol.sum()

        return {s: float(weights.get(s, 0)) for s in self.symbols}


class GridRebalance(AllocationStrategy):
    """网格再平衡

    固定目标比例，偏离超过 tolerance 时触发再平衡。
    """

    def __init__(self, target_weights: dict[str, float],
                 tolerance: float = 0.05, name: str = "GridRebalance"):
        super().__init__(name)
        total = sum(target_weights.values())
        self.target = {k: v / total for k, v in target_weights.items()}
        self.tolerance = tolerance
        self.last_rebalance_idx = -1

    def compute(self, price_df: pd.DataFrame, date_idx: int) -> dict[str, float]:
        if date_idx == 0:
            self.last_rebalance_idx = 0
            return dict(self.target)

        # 计算当前实际权重
        current_values = {}
        total_value = 0
        for s in self.target:
            if s in price_df.columns and date_idx < len(price_df[s].dropna()):
                val = float(price_df[s].iloc[date_idx])
                current_values[s] = val
                total_value += val

        if total_value <= 0:
            return dict(self.target)

        # 检查偏离
        max_deviation = 0
        for s in self.target:
            actual_w = current_values.get(s, 0) / total_value
            deviation = abs(actual_w - self.target[s])
            max_deviation = max(max_deviation, deviation)

        if max_deviation > self.tolerance and date_idx - self.last_rebalance_idx > 5:
            self.last_rebalance_idx = date_idx
            return dict(self.target)

        # 保持当前权重
        return {s: current_values.get(s, 0) / total_value if total_value > 0 else self.target[s]
                for s in self.target}


class TrendFollowing(AllocationStrategy):
    """趋势跟踪配置

    快线(MA20) > 慢线(MA60) → 持有
    快线 < 慢线 → 转向国债/现金
    支持多个标的组合。
    """

    def __init__(self, risk_assets: list[str], safe_asset: str = "TLT",
                 fast_ma: int = 20, slow_ma: int = 60,
                 name: str = "TrendFollowing"):
        super().__init__(name)
        self.risk_assets = risk_assets
        self.safe_asset = safe_asset
        self.fast_ma = fast_ma
        self.slow_ma = slow_ma

    def compute(self, price_df: pd.DataFrame, date_idx: int) -> dict[str, float]:
        n_risk = len(self.risk_assets)
        if n_risk == 0:
            return {self.safe_asset: 1.0}

        weights: dict[str, float] = {}
        risk_weight = 0

        for s in self.risk_assets:
            if s not in price_df.columns:
                continue
            col = price_df[s].dropna()
            if date_idx < self.slow_ma or len(col) <= date_idx:
                weights[s] = 0
                continue

            prices = col.iloc[:date_idx + 1].values
            if len(prices) < self.slow_ma:
                weights[s] = 0
                continue

            fast_ma = np.mean(prices[-self.fast_ma:]) if len(prices) >= self.fast_ma else np.mean(prices)
            slow_ma = np.mean(prices[-self.slow_ma:]) if len(prices) >= self.slow_ma else np.mean(prices)

            if fast_ma > slow_ma:
                weights[s] = 1.0 / n_risk  # 等权分配
                risk_weight += weights[s]
            else:
                weights[s] = 0

        # 剩余给安全资产
        remaining = 1.0 - risk_weight
        weights[self.safe_asset] = max(0, remaining)

        return weights
