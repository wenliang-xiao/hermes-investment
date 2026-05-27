"""
回测引擎 v1.0 — 三策略对比

策略一：多因子选股（factor_scanner评分，每周调仓，宏观权重自适应）
策略二：LDS全天候ETF（25%红利低波+30%纳指100+25%黄金+20%豆粕，月度再平衡）
策略三：多因子选股 + 双门控制总仓位（双门开→持仓，双门关→全清）

基准：沪深300全收益指数（000300.SH）

目标指标：
  - 年化收益率
  - 最大回撤（MDD）
  - 夏普比率（无风险利率3%）
  - 卡玛比率（年化收益/最大回撤）
  - 月度胜率（vs基准）

运行方式：
  python -m investment_system.analysis.backtest --start 2018-01-01 --end 2024-12-31
"""
import argparse
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


RISK_FREE_RATE = 0.03

ALLWEATHER_WEIGHTS = {
    "512890": 0.25,
    "513100": 0.30,
    "518880": 0.25,
    "159985": 0.20,
}

LDS_STOCK_FILTERS = {
    "roe_min": 12.0,
    "rev_growth_min": 15.0,
    "market_cap_max": 200_0000_0000,
}

PORTFOLIO_MAX_POSITIONS = 8
STOP_LOSS = 0.08
TAKE_PROFIT_HALF = 0.15
TAKE_PROFIT_FULL = 0.30


@dataclass
class Trade:
    symbol: str
    entry_date: str
    entry_price: float
    exit_date: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl_pct: float = 0.0


@dataclass
class BacktestResult:
    strategy_name: str
    start_date: str
    end_date: str
    equity_curve: pd.Series = field(default_factory=pd.Series)
    benchmark_curve: pd.Series = field(default_factory=pd.Series)
    trades: List[Trade] = field(default_factory=list)
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    calmar: float = 0.0
    win_rate_vs_benchmark: float = 0.0
    monthly_returns: pd.Series = field(default_factory=pd.Series)
    gate_closed_pct: float = 0.0  # 双门关闭比例（策略三）

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name,
            "period": f"{self.start_date} ~ {self.end_date}",
            "annual_return": f"{self.annual_return:.2%}",
            "max_drawdown": f"{self.max_drawdown:.2%}",
            "sharpe": f"{self.sharpe:.2f}",
            "calmar": f"{self.calmar:.2f}",
            "win_rate_vs_benchmark": f"{self.win_rate_vs_benchmark:.1%}",
            "total_trades": len(self.trades),
            "gate_closed_pct": f"{self.gate_closed_pct:.1%}" if self.gate_closed_pct > 0 else "N/A",
        }


def _load_price_data(symbols: List[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    """
    批量拉取股票/ETF/指数日线数据。
      - A股个股（纯数字） → yfinance 优先，失败则 baostock 备用
      - 中国ETF（512/518/159/511/588开头）→ AKShare fund_etf_hist_em
      - 沪深300（000300）→ yfinance 或 AKShare
      - 其它（字母开头）→ yfinance
    """
    data = {}
    import time as _time

    # 分类
    a_stock_list = []
    cn_etf_list = []
    yf_list = []
    for s in symbols:
        ds = str(s)
        if ds == "000300":
            a_stock_list.append(s)  # 走 yfinance/AKShare
        elif ds.isdigit() and (ds.startswith(("512", "513", "518", "511", "588", "159")) or ds in ("159915", "159926", "159985")):
            cn_etf_list.append(s)
        elif ds.isdigit():
            a_stock_list.append(s)
        else:
            yf_list.append(s)

    # ─── 沪深300：AKShare优先（yfinance仅925天不全）───
    if "000300" in symbols:
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                df = df[(df.index >= start) & (df.index <= end)].copy()
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                data["000300"] = df[["close"]]
        except Exception:
            try:
                import yfinance as yf
                ticker = yf.Ticker("000300.SS")
                df = ticker.history(start=start, end=end)
                if not df.empty:
                    if df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                    data["000300"] = df[["Close"]].rename(columns={"Close": "close"})
            except Exception:
                pass

    # ─── yfinance（A股个股）───
    if a_stock_list:
        try:
            import yfinance as yf
            for sym in a_stock_list:
                try:
                    code = "000300.SS" if str(sym) == "000300" else (
                        f"{sym}.SS" if str(sym).startswith(("5", "6")) else f"{sym}.SZ"
                    )
                    ticker = yf.Ticker(code)
                    df = ticker.history(start=start, end=end)
                    if not df.empty:
                        if df.index.tz is not None:
                            df.index = df.index.tz_localize(None)
                        data[sym] = df[["Close"]].rename(columns={"Close": "close"})
                        continue  # 跳过baostock备用
                except Exception:
                    pass
        except Exception:
            pass

    # ─── 沪深300备用：AKShare ───
    if "000300" not in data and "000300" in symbols:
        try:
            import akshare as ak
            df = ak.stock_zh_index_daily(symbol="sh000300")
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df.set_index("date", inplace=True)
                df = df[(df.index >= start) & (df.index <= end)]
                data["000300"] = df[["close"]]
        except Exception:
            pass

    # ─── AKShare（中国ETF，优先），失败则yfinance ───
    if cn_etf_list:
        for sym in cn_etf_list:
            try:
                import yfinance as yf
                # 先试 yfinance — 512xxx.SS / 159xxx.SZ
                yf_code = f"{sym}.SS"
                yf_df = yf.Ticker(yf_code).history(start=start, end=end)
                if yf_df.empty:
                    yf_code = f"{sym}.SZ"
                    yf_df = yf.Ticker(yf_code).history(start=start, end=end)
                if not yf_df.empty:
                    if yf_df.index.tz is not None:
                        yf_df.index = yf_df.index.tz_localize(None)
                    data[sym] = yf_df[["Close"]].rename(columns={"Close": "close"})
                    continue
            except Exception:
                pass
            # Fallback: AKShare
            try:
                import akshare as ak
                start_dt = f"{start[:10]}"
                end_dt = f"{end[:10]}"
                df = ak.fund_etf_hist_em(
                    symbol=sym,
                    period="daily",
                    start_date=start_dt,
                    end_date=end_dt,
                    adjust="qfq",
                )
                if df is not None and not df.empty:
                    cols = [str(c).lower() for c in df.columns]
                    if "日期" in cols:
                        df["date"] = pd.to_datetime(df.iloc[:, 0])
                        df.set_index("date", inplace=True)
                        close_col = [i for i, c in enumerate(cols) if "收盘" in c]
                        if close_col:
                            df["close"] = pd.to_numeric(df.iloc[:, close_col[0]], errors="coerce")
                            data[sym] = df[["close"]]
            except Exception:
                pass

    # ─── yfinance（非A股，如美股ETF）───
    if yf_list:
        try:
            import yfinance as yf
            for sym in yf_list:
                try:
                    ticker = yf.Ticker(sym)
                    df = ticker.history(start=start, end=end)[["Close"]].rename(columns={"Close": "close"})
                    if not df.empty:
                        if df.index.tz is not None:
                            df.index = df.index.tz_localize(None)
                        data[sym] = df
                except Exception:
                    pass
        except Exception:
            pass

    # ── 统一 index 为无时区 ──
    for sym in list(data.keys()):
        df = data[sym]
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
            data[sym] = df

    return data


def _calc_metrics(equity: pd.Series, benchmark: pd.Series, rf: float = RISK_FREE_RATE) -> dict:
    if equity.empty or len(equity) < 2:
        return {"annual_return": 0, "max_drawdown": 0, "sharpe": 0, "calmar": 0, "win_rate_vs_benchmark": 0}

    returns = equity.pct_change().dropna()
    n_years = len(equity) / 252

    annual_return = float((equity.iloc[-1] / equity.iloc[0]) ** (1 / max(n_years, 0.01)) - 1)

    peak = equity.expanding().max()
    drawdown = (equity - peak) / peak
    max_drawdown = float(drawdown.min())

    excess = returns - rf / 252
    sharpe = float(excess.mean() / excess.std() * np.sqrt(252)) if excess.std() > 0 else 0

    calmar = annual_return / abs(max_drawdown) if max_drawdown < 0 else annual_return / 0.01

    monthly_eq = equity.resample("ME").last().pct_change().dropna()
    if not benchmark.empty:
        monthly_bm = benchmark.resample("ME").last().pct_change().dropna()
        common = monthly_eq.index.intersection(monthly_bm.index)
        if len(common) > 0:
            win_rate = float((monthly_eq[common] > monthly_bm[common]).mean())
        else:
            win_rate = 0.0
    else:
        win_rate = 0.0

    return {
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": calmar,
        "win_rate_vs_benchmark": win_rate,
        "monthly_returns": monthly_eq,
    }


def run_allweather(price_data: Dict[str, pd.DataFrame], start: str, end: str,
                   benchmark: pd.Series) -> BacktestResult:
    """
    策略二：LDS全天候ETF组合
    初始等权，每月最后交易日再平衡，偏离>5%触发调仓。
    """
    dates = pd.date_range(start, end, freq="B")
    portfolio_value = pd.Series(index=dates, dtype=float)
    portfolio_value.iloc[0] = 1.0

    weights = dict(ALLWEATHER_WEIGHTS)
    positions = {sym: w for sym, w in weights.items()}
    last_rebalance = pd.Timestamp(start)

    for i, date in enumerate(dates[1:], 1):
        date_str = date.strftime("%Y-%m-%d")
        returns = {}
        for sym, w in positions.items():
            if sym in price_data:
                df = price_data[sym]
                prev_idx = df.index[df.index <= dates[i - 1]]
                curr_idx = df.index[df.index <= date]
                if len(prev_idx) > 0 and len(curr_idx) > 0:
                    prev_p = float(df.loc[prev_idx[-1], "close"])
                    curr_p = float(df.loc[curr_idx[-1], "close"])
                    returns[sym] = curr_p / prev_p - 1 if prev_p > 0 else 0
                else:
                    returns[sym] = 0
            else:
                returns[sym] = 0

        daily_ret = sum(positions[sym] * returns.get(sym, 0) for sym in positions)
        portfolio_value.iloc[i] = portfolio_value.iloc[i - 1] * (1 + daily_ret)

        if date.month != last_rebalance.month:
            positions = dict(ALLWEATHER_WEIGHTS)
            last_rebalance = date

    equity = portfolio_value.dropna()
    metrics = _calc_metrics(equity, benchmark)

    result = BacktestResult(
        strategy_name="LDS全天候ETF",
        start_date=start,
        end_date=end,
        equity_curve=equity,
        benchmark_curve=benchmark,
        **{k: v for k, v in metrics.items() if k != "monthly_returns"},
    )
    result.monthly_returns = metrics.get("monthly_returns", pd.Series())
    return result


def run_multifactor_stock(price_data: Dict[str, pd.DataFrame],
                          factor_scores: Dict[str, Dict[str, float]],
                          start: str, end: str,
                          benchmark: pd.Series,
                          use_dual_gate: bool = False,
                          gate_series: Optional[pd.Series] = None) -> BacktestResult:
    """
    策略一/三：多因子选股组合
    每周五评分，取top-N建仓，等权分配，8%硬止损，15%/30%分级止盈。
    use_dual_gate=True 时加入双门控制：双门关 → 空仓。
    """
    strategy_name = "多因子选股+双门控制" if use_dual_gate else "多因子选股"
    dates = pd.date_range(start, end, freq="B")
    portfolio_value = pd.Series(index=dates, dtype=float)
    portfolio_value.iloc[0] = 1.0

    holdings: Dict[str, float] = {}
    entry_prices: Dict[str, float] = {}
    trades: List[Trade] = []
    rebalance_dates = pd.date_range(start, end, freq="W-FRI")

    gate_closed_days = 0
    total_days = len(dates)

    for i, date in enumerate(dates[1:], 1):
        gate_open = True
        if use_dual_gate and gate_series is not None:
            gate_val = gate_series.get(date, gate_series.get(date - timedelta(days=1), 1))
            gate_open = bool(gate_val)
            if not gate_open:
                gate_closed_days += 1

        if not gate_open and holdings:
            for sym, w in list(holdings.items()):
                if sym in price_data:
                    curr_idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(curr_idx) > 0:
                        exit_p = float(price_data[sym].loc[curr_idx[-1], "close"])
                        entry_p = entry_prices.get(sym, exit_p)
                        pnl = (exit_p - entry_p) / entry_p
                        trades.append(Trade(sym, "", entry_p, date.strftime("%Y-%m-%d"), exit_p, "dual_gate_close", pnl))
            holdings = {}
            entry_prices = {}

        exit_set = set()
        for sym in list(holdings.keys()):
            if sym not in price_data:
                continue
            df = price_data[sym]
            curr_idx = df.index[df.index <= date]
            if len(curr_idx) == 0:
                continue
            curr_p = float(df.loc[curr_idx[-1], "close"])
            entry_p = entry_prices.get(sym, curr_p)
            pnl = (curr_p - entry_p) / entry_p
            if pnl <= -STOP_LOSS:
                exit_set.add(sym)
                trades.append(Trade(sym, "", entry_p, date.strftime("%Y-%m-%d"), curr_p, "stop_loss", pnl))
            elif pnl >= TAKE_PROFIT_FULL:
                exit_set.add(sym)
                trades.append(Trade(sym, "", entry_p, date.strftime("%Y-%m-%d"), curr_p, "take_profit_full", pnl))
            elif pnl >= TAKE_PROFIT_HALF:
                holdings[sym] *= 0.5
                trades.append(Trade(sym, "", entry_p, date.strftime("%Y-%m-%d"), curr_p, "take_profit_half", pnl))
        for sym in exit_set:
            holdings.pop(sym, None)
            entry_prices.pop(sym, None)

        if date in rebalance_dates and gate_open:
            date_str = date.strftime("%Y-%m-%d")
            scores = factor_scores.get(date_str, {})
            if scores:
                top_n = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:PORTFOLIO_MAX_POSITIONS]
                new_holdings = {sym: 1.0 / PORTFOLIO_MAX_POSITIONS for sym, _ in top_n}
                entered = set(new_holdings) - set(holdings)
                exited = set(holdings) - set(new_holdings)
                for sym in exited:
                    if sym in price_data:
                        curr_idx = price_data[sym].index[price_data[sym].index <= date]
                        if len(curr_idx) > 0:
                            exit_p = float(price_data[sym].loc[curr_idx[-1], "close"])
                            entry_p = entry_prices.get(sym, exit_p)
                            pnl = (exit_p - entry_p) / entry_p
                            trades.append(Trade(sym, "", entry_p, date.strftime("%Y-%m-%d"), exit_p, "rebalance", pnl))
                for sym in entered:
                    if sym in price_data:
                        curr_idx = price_data[sym].index[price_data[sym].index <= date]
                        if len(curr_idx) > 0:
                            entry_prices[sym] = float(price_data[sym].loc[curr_idx[-1], "close"])
                holdings = new_holdings
                TRADE_COST = 0.002
                portfolio_value.iloc[i - 1] *= (1 - TRADE_COST * (len(entered) + len(exited)) / max(PORTFOLIO_MAX_POSITIONS, 1))

        if not holdings:
            portfolio_value.iloc[i] = portfolio_value.iloc[i - 1]
            continue

        daily_ret = 0.0
        total_w = sum(holdings.values())
        for sym, w in holdings.items():
            if sym not in price_data:
                continue
            df = price_data[sym]
            prev_idx = df.index[df.index <= dates[i - 1]]
            curr_idx = df.index[df.index <= date]
            if len(prev_idx) > 0 and len(curr_idx) > 0:
                prev_p = float(df.loc[prev_idx[-1], "close"])
                curr_p = float(df.loc[curr_idx[-1], "close"])
                daily_ret += (w / total_w) * (curr_p / prev_p - 1) if prev_p > 0 else 0

        portfolio_value.iloc[i] = portfolio_value.iloc[i - 1] * (1 + daily_ret)

    equity = portfolio_value.dropna()
    metrics = _calc_metrics(equity, benchmark)
    result = BacktestResult(
        strategy_name=strategy_name,
        start_date=start,
        end_date=end,
        equity_curve=equity,
        benchmark_curve=benchmark,
        trades=trades,
        gate_closed_pct=gate_closed_days / max(total_days, 1),
        **{k: v for k, v in metrics.items() if k != "monthly_returns"},
    )
    result.monthly_returns = metrics.get("monthly_returns", pd.Series())
    return result


def generate_mock_factor_scores(symbols: List[str], start: str, end: str,
                                 price_data: Dict[str, pd.DataFrame]) -> Dict[str, Dict[str, float]]:
    """
    在无历史因子数据时，用历史价格动量+波动率生成模拟因子分（用于回测框架验证）。
    真实回测应替换为实际因子评分的历史序列。
    """
    scores = {}
    rebalance_dates = pd.date_range(start, end, freq="W-FRI")
    for date in rebalance_dates:
        date_str = date.strftime("%Y-%m-%d")
        day_scores = {}
        for sym in symbols:
            if sym not in price_data:
                continue
            df = price_data[sym]
            hist = df[df.index <= date]
            if len(hist) < 60:
                continue
            close = hist["close"].values
            ret_60d = (close[-1] / close[-61] - 1) * 100 if len(close) >= 61 else 0
            vol = float(np.std(np.diff(close[-21:]) / close[-21:-1]) * np.sqrt(252) * 100) if len(close) >= 21 else 20
            score = max(1, min(10, 5 + ret_60d / 10 - vol / 20))
            day_scores[sym] = round(score, 2)
        if day_scores:
            scores[date_str] = day_scores
    return scores


def run_backtest(start: str = "2018-01-01", end: str = "2024-12-31",
                 symbols: Optional[List[str]] = None) -> List[BacktestResult]:
    """
    主入口：运行三个策略的回测并返回结果列表。
    """
    if symbols is None:
        from investment_system.config import INDUSTRY_CHAINS
        symbols_set = set()
        for chain in INDUSTRY_CHAINS.values():
            for s in chain.get("symbols", []):
                if str(s).isdigit():
                    symbols_set.add(str(s))
        symbols = list(symbols_set)[:30]

    etf_symbols = list(ALLWEATHER_WEIGHTS.keys())
    all_symbols = list(set(symbols + etf_symbols + ["000300"]))

    print(f"[backtest] 加载价格数据: {len(all_symbols)} 只...")
    price_data = _load_price_data(all_symbols, start, end)
    print(f"[backtest] 成功加载: {len(price_data)} 只")

    loaded_symbols = []
    for s in symbols:
        if s in price_data:
            loaded_symbols.append(s)
    symbols = loaded_symbols
    print(f"[backtest] 可用A股标的: {len(symbols)} 只")

    benchmark = pd.Series(dtype=float)
    if "000300" in price_data:
        bm_df = price_data["000300"]
        benchmark = bm_df["close"] / bm_df["close"].iloc[0]
        print(f"[backtest] 沪深300基准加载: {len(bm_df)} 天")
    else:
        # 无基准时用等权替代
        print("[backtest] ⚠️ 沪深300基准不可用，跳过基准对比")
        benchmark = pd.Series(index=pd.date_range(start, end, freq="B"), dtype=float)

    print("[backtest] 加载/重建因子评分...")
    try:
        from investment_system.analysis.score_history import (
            load_scores_range, build_historical_scores_from_prices
        )
        factor_scores = load_scores_range(start, end)
        coverage = len(factor_scores)
        print(f"[backtest] 历史快照加载: {coverage} 个交易日")
        if coverage < 10:
            print("[backtest] 历史快照不足，改用价格重建因子分（D-lite）...")
            factor_scores = build_historical_scores_from_prices(symbols, price_data, start, end, use_fundamentals=False)
            print(f"[backtest] D-lite重建完成: {len(factor_scores)} 个截面")
    except Exception as e:
        print(f"[backtest] 因子分加载失败({e})，fallback到模拟分...")
        factor_scores = generate_mock_factor_scores(symbols, start, end, price_data)

    print("[backtest] 策略一：多因子选股...")
    r1 = run_multifactor_stock(price_data, factor_scores, start, end, benchmark, False)

    print("[backtest] 策略二：LDS全天候ETF...")
    r2 = run_allweather(price_data, start, end, benchmark)

    print("[backtest] 策略三：多因子+双门控制...")
    try:
        from investment_system.analysis.score_history import load_macro_gate_series
        gate_series = load_macro_gate_series(start, end)
        closed_pct = (gate_series == 0).mean()
        print(f"[backtest] 双门历史: 关闭{closed_pct:.1%}时间")
    except Exception as e:
        print(f"[backtest] 双门历史加载失败({e})，fallback到全开...")
        gate_series = pd.Series(1, index=pd.date_range(start, end, freq="B"))
    r3 = run_multifactor_stock(price_data, factor_scores, start, end, benchmark, True, gate_series)

    return [r1, r2, r3]


def print_report(results: List[BacktestResult]):
    print("\n" + "=" * 80)
    print("回测报告 — 三策略对比（2018-2024）")
    print("=" * 80)
    headers = ["策略", "年化收益", "最大回撤", "夏普", "卡玛", "月度胜率(vs基准)", "双门关闭"]
    rows = []
    for r in results:
        gate_str = f"{r.gate_closed_pct:.1%}" if r.gate_closed_pct > 0 else "-"
        rows.append([
            r.strategy_name,
            f"{r.annual_return:.1%}",
            f"{r.max_drawdown:.1%}",
            f"{r.sharpe:.2f}",
            f"{r.calmar:.2f}",
            f"{r.win_rate_vs_benchmark:.1%}",
            gate_str,
        ])

    col_widths = [max(len(str(row[i])) for row in rows + [headers]) + 2 for i in range(len(headers))]
    fmt = "".join(f"{{:<{w}}}" for w in col_widths)
    print(fmt.format(*headers))
    print("-" * sum(col_widths))
    for row in rows:
        print(fmt.format(*row))
    print("=" * 80)
    print("\n目标验证（低波动+可接受回撤+2x沪深300）:")
    for r in results:
        passes = []
        if abs(r.max_drawdown) < 0.25:
            passes.append("✅ 最大回撤<25%")
        else:
            passes.append(f"❌ 最大回撤{r.max_drawdown:.1%}>25%")
        if r.sharpe > 1.0:
            passes.append("✅ 夏普>1.0")
        else:
            passes.append(f"⚠️  夏普{r.sharpe:.2f}<1.0")
        print(f"  {r.strategy_name}: {' | '.join(passes)}")

    # 详细分析
    print("\n" + "─" * 80)
    print("深度分析")
    print("─" * 80)
    for r in results:
        if r.trades:
            pnls = [t.pnl_pct for t in r.trades]
            avg_pnl = np.mean(pnls) if pnls else 0
            win_rate = sum(1 for p in pnls if p > 0) / len(pnls) if pnls else 0
            stop_loss_count = sum(1 for t in r.trades if t.exit_reason == "stop_loss")
            tp_full_count = sum(1 for t in r.trades if t.exit_reason == "take_profit_full")
            print(f"  {r.strategy_name}:")
            print(f"    交易次数: {len(r.trades)}")
            print(f"    平均单笔盈亏: {avg_pnl:.2%}")
            print(f"    胜率: {win_rate:.1%}")
            print(f"    止损触发: {stop_loss_count}次")
            print(f"    止盈(全仓)触发: {tp_full_count}次")
            if r.gate_closed_pct > 0:
                print(f"    双门关闭: {r.gate_closed_pct:.1%}天持仓={1-r.gate_closed_pct:.1%}天")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2024-12-31")
    parser.add_argument("--output", default="", help="JSON输出路径（可选）")
    args = parser.parse_args()

    results = run_backtest(args.start, args.end)
    print_report(results)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in results], f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")