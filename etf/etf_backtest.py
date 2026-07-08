"""
analysis/etf_backtest.py — ETF 回测引擎

对任意配置策略（FixedMix/RiskParity/GridRebalance/TrendFollowing）
运行日频再平衡回测，输出组合级指标。

用法:
    from etf.etf_backtest import run_etf_backtest
    from etf.allocation_strategies import FixedMix

    strat = FixedMix({"SPY": 0.6, "TLT": 0.4})
    result = run_etf_backtest(strat, {"SPY": prices1, "TLT": prices2})
"""
from __future__ import annotations

import math
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Callable


# ── 默认成本参数（ETF 费率低）──
COMMISSION_RATE = 0.0001       # 万1
SLIPPAGE = 0.0003              # 万分之3（ETF流动性好）
TRADING_DAYS = 252
INITIAL_CASH = 1_000_000.0


def run_etf_backtest(
    strategy,
    price_data: dict[str, list[float]],
    strategy_name: str = "",
    rebalance_freq: int = 1,   # 每日再平衡（1天）
    cost_mode: str = "simple",
) -> dict:
    """运行 ETF 组合回测

    Args:
        strategy: AllocationStrategy 实例
        price_data: {symbol: [close_prices]}
        strategy_name: 策略名（用于输出）
        rebalance_freq: 再平衡频率（天）
        cost_mode: "simple"（单边0.1%）或 "detailed"

    Returns:
        dict with metrics
    """
    # 转换为 DataFrame
    df = pd.DataFrame(price_data)
    df = df.dropna(how="all")

    if df.empty or len(df.columns) < 2:
        return {"error": "数据不足，至少需要2个标的"}

    n_days = len(df)
    symbols = list(df.columns)

    # ── 逐日模拟 ──
    cash = INITIAL_CASH
    holdings: dict[str, float] = {s: 0.0 for s in symbols}  # 持仓市值
    equity_curve: list[float] = []
    trades: list[dict] = []
    trade_count = 0
    win_count = 0
    last_rebalance_prices: dict[str, float] = {}

    for day_idx in range(n_days):
        daily_prices: dict[str, float] = {}
        for s in symbols:
            v = df.iloc[day_idx][s]
            if pd.notna(v):
                daily_prices[s] = float(v)

        if not daily_prices:
            if equity_curve:
                equity_curve.append(equity_curve[-1])
            else:
                equity_curve.append(INITIAL_CASH)
            continue

        # 刷新持仓市值
        position_value = 0.0
        for s in symbols:
            if s in daily_prices:
                holdings[s] = daily_prices[s] * (holdings.get(s, 0) / (last_rebalance_prices.get(s, 1) or 1))
                position_value += holdings[s]

        total_value = cash + position_value

        # 判断是否再平衡
        should_rebalance = (day_idx % rebalance_freq == 0 and day_idx > 0) or day_idx == 0

        if should_rebalance:
            # 计算目标权重
            target_weights = strategy.compute(df, day_idx)

            # 卖出：先变现所有
            sell_proceeds = 0.0
            for s in symbols:
                if s in daily_prices and holdings.get(s, 0) > 0:
                    qty = holdings[s] / daily_prices[s]
                    proceeds = qty * daily_prices[s]
                    cost = proceeds * (COMMISSION_RATE + SLIPPAGE)
                    net_proceeds = proceeds - cost
                    sell_proceeds += net_proceeds
                    holdings[s] = 0.0

            cash = cash + sell_proceeds

            # 买入
            buy_cost = 0.0
            new_holdings: dict[str, float] = {}
            for s in symbols:
                if s in daily_prices and s in target_weights:
                    target_cash = cash * target_weights[s]
                    if target_cash <= 0:
                        new_holdings[s] = 0.0
                        continue
                    qty = target_cash / daily_prices[s]
                    cost = target_cash * (COMMISSION_RATE + SLIPPAGE)
                    buy_cost += cost
                    net_investment = target_cash - cost
                    new_holdings[s] = net_investment
                    last_rebalance_prices[s] = daily_prices[s]
                    if target_cash > 0:
                        trade_count += 1

            cash = cash - sum(new_holdings.values())
            holdings = new_holdings

        # 记录净值
        position_value = sum(holdings.values())
        total_value = cash + position_value
        equity_curve.append(total_value)

    # ── 计算指标 ──
    if len(equity_curve) < 5:
        return {"error": "净值曲线太短"}

    equity = pd.Series(equity_curve)
    final_value = equity.iloc[-1]

    total_return = final_value / INITIAL_CASH - 1.0
    annualized_return = (1.0 + total_return) ** (TRADING_DAYS / n_days) - 1.0 if n_days > 0 else 0.0

    daily_returns = equity.pct_change().dropna()
    std = float(daily_returns.std())
    sharpe = float(daily_returns.mean()) / std * math.sqrt(TRADING_DAYS) if std > 0 else 0.0

    downside = daily_returns[daily_returns < 0]
    dstd = float(downside.std())
    sortino = float(daily_returns.mean()) / dstd * math.sqrt(TRADING_DAYS) if dstd > 0 else 0.0

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown = float(-drawdown.min())

    return {
        "strategy": strategy_name or strategy.name,
        "type": "etf",
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(annualized_return * 100, 2),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "final_value": round(final_value, 2),
        "total_days": n_days,
        "num_assets": len(symbols),
        "rebalance_freq": rebalance_freq,
    }


def run_etf_walk_forward(
    strategy,
    price_data: dict[str, list[float]],
    strategy_name: str = "",
    train_days: int = 252,
    test_days: int = 63,
    cycles: int = 3,
) -> dict:
    """ETF Walk-Forward 评估"""
    if len(price_data) < 2:
        return {"error": "至少需要2个ETF标的"}

    min_days = min(len(p) for p in price_data.values())
    if min_days < train_days + test_days * cycles:
        return {"error": f"数据不足: {min_days}天, 需要至少{train_days + test_days * cycles}天"}

    cycle_results = []
    for cycle in range(cycles):
        test_start = train_days + cycle * test_days
        test_end = test_start + test_days
        if test_end > min_days:
            break

        # 提取 test 窗口数据
        test_data: dict[str, list[float]] = {}
        for sym, prices in price_data.items():
            test_data[sym] = prices[:test_end]

        result = run_etf_backtest(strategy, test_data,
                                   f"{strategy_name or strategy.name}_W{cycle+1}")
        if "error" not in result:
            cycle_results.append(result)

    if not cycle_results:
        return {"error": "无有效 cycle"}

    import numpy as np
    returns = [r["total_return_pct"] for r in cycle_results]
    sortinos = [r["sortino_ratio"] for r in cycle_results]
    dds = [r["max_drawdown_pct"] for r in cycle_results]

    return {
        "strategy": strategy_name or strategy.name,
        "mode": "walk_forward",
        "cycles": len(cycle_results),
        "avg_return_pct": round(np.mean(returns), 2),
        "avg_sortino": round(np.mean(sortinos), 4),
        "avg_max_drawdown_pct": round(np.mean(dds), 2),
        "min_sortino": round(min(sortinos), 4),
        "max_sortino": round(max(sortinos), 4),
        "cycle_details": cycle_results,
    }


def compare_all_etf_strategies(price_data: dict[str, list[float]]) -> dict[str, dict]:
    """比较所有内置 ETF 策略

    返回 {策略名: 结果}
    """
    from etf.allocation_strategies import FixedMix, RiskParity, GridRebalance, TrendFollowing

    results = {}

    # 1. 固定 60/40
    if "SPY" in price_data and "TLT" in price_data:
        s1 = FixedMix({"SPY": 0.6, "TLT": 0.4}, name="Fixed_60_40")
        results["fixed_60_40"] = run_etf_backtest(s1, price_data, "Fixed 60/40")

    # 2. 固定 50/50
    if "SPY" in price_data and "TLT" in price_data:
        s2 = FixedMix({"SPY": 0.5, "TLT": 0.5}, name="Fixed_50_50")
        results["fixed_50_50"] = run_etf_backtest(s2, price_data, "Fixed 50/50")

    # 3. 风险平价
    symbols = [s for s in price_data.keys()]
    if len(symbols) >= 2:
        s3 = RiskParity(symbols, name="RiskParity")
        results["risk_parity"] = run_etf_backtest(s3, price_data, "Risk Parity")

    # 4. 网格再平衡
    if "SPY" in price_data and "TLT" in price_data:
        s4 = GridRebalance({"SPY": 0.6, "TLT": 0.4}, tolerance=0.05, name="GridRebalance")
        results["grid_rebalance"] = run_etf_backtest(s4, price_data, "Grid 5%")

    # 5. 趋势跟踪
    risk_assets = [s for s in ["SPY", "QQQ"] if s in price_data]
    if risk_assets and "TLT" in price_data:
        s5 = TrendFollowing(risk_assets, safe_asset="TLT", name="TrendFollow")
        results["trend_follow"] = run_etf_backtest(s5, price_data, "Trend Follow")

    return results
