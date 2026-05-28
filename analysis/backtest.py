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

# ═══ 策略四：跨资产配置参数 ═══
# 宏观象限→各类资产权重（面基框架：货币信用四象限驱动配置）
# 复苏期：宽货币·紧信用 → 债券+A股双高
# 扩张期：宽货币·宽信用 → 股票(美股+A股)高配
# 过热期：紧货币·宽信用 → 商品最强，A股最低
# 衰退期：紧货币·紧信用 → 债券最高，商品最低
STRATEGY4_QUADRANT_WEIGHTS = {
    "复苏期":  {"a_share": 0.30, "stock_etf": 0.15, "bond_etf": 0.20, "commodity_etf": 0.10, "us_stock": 0.15, "hk_stock": 0.10},
    "扩张期":  {"a_share": 0.25, "stock_etf": 0.20, "bond_etf": 0.10, "commodity_etf": 0.15, "us_stock": 0.20, "hk_stock": 0.10},
    "过热期":  {"a_share": 0.15, "stock_etf": 0.10, "bond_etf": 0.10, "commodity_etf": 0.30, "us_stock": 0.20, "hk_stock": 0.15},
    "衰退期":  {"a_share": 0.20, "stock_etf": 0.10, "bond_etf": 0.30, "commodity_etf": 0.10, "us_stock": 0.15, "hk_stock": 0.15},
    "default": {"a_share": 0.25, "stock_etf": 0.15, "bond_etf": 0.15, "commodity_etf": 0.15, "us_stock": 0.15, "hk_stock": 0.15},
}

# ETF池分类（按资产类别）
STOCK_ETF_POOL = ["512890", "513100", "512480", "512660"]
BOND_ETF_POOL = ["511260"]    # 国开债ETF（债券久期替代）
COMMODITY_ETF_POOL = ["518880", "159985"]

# ETF多因子评分权重（用户确认：动量40%+低波20%+流动性15%+跟踪误差10%+宏观拟合度15%）
ETF_FACTOR_WEIGHTS = {
    "momentum": 0.40,
    "low_vol": 0.20,
    "liquidity": 0.15,
    "tracking_error": 0.10,
    "macro_fit": 0.15,
}

ALL_ETF_POOL = list(set(STOCK_ETF_POOL + BOND_ETF_POOL + COMMODITY_ETF_POOL))

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
    chain: str = ""
    score: float = 0.0
    holding_days: int = 0

    def holding_period(self) -> int:
        if self.entry_date and self.exit_date:
            try:
                from datetime import datetime
                d = (datetime.strptime(self.exit_date, "%Y-%m-%d") -
                     datetime.strptime(self.entry_date, "%Y-%m-%d")).days
                return max(0, d)
            except Exception:
                pass
        return self.holding_days

    def exit_reason_cn(self) -> str:
        mapping = {
            "stop_loss": "🔴止损(-8%)",
            "take_profit_full": "🟢止盈(+30%)",
            "take_profit_half": "🟡减半仓(+15%)",
            "rebalance": "🔄换仓(周度再平衡)",
            "dual_gate_close": "🚪双门关闭(空仓)",
        }
        return mapping.get(self.exit_reason, self.exit_reason)


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
    yearly_returns: Dict[int, float] = field(default_factory=dict)
    drawdown_series: pd.Series = field(default_factory=pd.Series)
    gate_closed_pct: float = 0.0

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
            "yearly_returns": {str(y): f"{r:.1%}" for y, r in self.yearly_returns.items()},
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

    yearly_eq = equity.resample("YE").last()
    yearly_returns = {}
    for i in range(1, len(yearly_eq)):
        year = yearly_eq.index[i].year
        yr = float(yearly_eq.iloc[i] / yearly_eq.iloc[i - 1] - 1)
        yearly_returns[year] = yr
    if len(yearly_eq) >= 1:
        first_year = yearly_eq.index[0].year
        if first_year not in yearly_returns:
            yr0 = float(yearly_eq.iloc[0] / equity.iloc[0] - 1)
            yearly_returns[first_year] = yr0

    drawdown_series = (equity - equity.expanding().max()) / equity.expanding().max()

    return {
        "annual_return": annual_return,
        "max_drawdown": max_drawdown,
        "sharpe": sharpe,
        "calmar": calmar,
        "win_rate_vs_benchmark": win_rate,
        "monthly_returns": monthly_eq,
        "yearly_returns": yearly_returns,
        "drawdown_series": drawdown_series,
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

    exclude = {"monthly_returns", "yearly_returns", "drawdown_series"}
    result = BacktestResult(
        strategy_name="LDS全天候ETF",
        start_date=start,
        end_date=end,
        equity_curve=equity,
        benchmark_curve=benchmark,
        **{k: v for k, v in metrics.items() if k not in exclude},
    )
    result.monthly_returns = metrics.get("monthly_returns", pd.Series())
    result.yearly_returns = metrics.get("yearly_returns", {})
    result.drawdown_series = metrics.get("drawdown_series", pd.Series())
    return result


MACRO_REGIME_WEIGHTS = {
    "扩张期": {"stock": 0.40, "broad_etf": 0.25, "gold": 0.15, "bond": 0.10, "commodity": 0.10},
    "过热期": {"stock": 0.20, "broad_etf": 0.15, "gold": 0.25, "bond": 0.10, "commodity": 0.30},
    "衰退期": {"stock": 0.10, "broad_etf": 0.10, "gold": 0.30, "bond": 0.40, "commodity": 0.10},
    "复苏期": {"stock": 0.35, "broad_etf": 0.30, "gold": 0.15, "bond": 0.15, "commodity": 0.05},
    "default": {"stock": 0.30, "broad_etf": 0.25, "gold": 0.20, "bond": 0.15, "commodity": 0.10},
}

STRATEGY4_ETF_MAP = {
    "broad_etf": "513100",
    "gold":      "518880",
    "bond":      "511260",
    "commodity": "159985",
}


def _get_regime_for_date(date: pd.Timestamp, cpi_history: dict, index_ma: dict) -> str:
    date_str = date.strftime("%Y-%m-%d")
    cpi = None
    for d in sorted(cpi_history.keys(), reverse=True):
        if d <= date_str:
            cpi = cpi_history[d]
            break
    dev = index_ma.get(date_str)
    if dev is None:
        for d in sorted(index_ma.keys(), reverse=True):
            if d <= date_str:
                dev = index_ma[d]
                break
    trend_down = dev is not None and dev <= -0.05
    if cpi is None:
        return "default"
    if cpi >= 2.0 and not trend_down:
        return "过热期" if cpi >= 3.0 else "扩张期"
    if cpi < 1.0 and trend_down:
        return "衰退期"
    if trend_down:
        return "衰退期"
    if cpi < 1.0:
        return "复苏期"
    return "扩张期"


def _relaxed_gate_val(cpi_val: Optional[float], dev: Optional[float]) -> float:
    if cpi_val is None:
        macro_mult = 1.0
    elif cpi_val < 0.0:
        macro_mult = 0.5
    elif cpi_val < 1.0:
        macro_mult = 0.8
    elif cpi_val < 2.0:
        macro_mult = 1.0
    elif cpi_val < 3.0:
        macro_mult = 0.85
    else:
        macro_mult = 0.4
    trend_mult = 0.6 if (dev is not None and dev <= -0.05) else 1.0
    return round(macro_mult * trend_mult, 2)


def run_macro_driven_allweather(
    price_data: Dict[str, pd.DataFrame],
    factor_scores: Dict[str, Dict[str, float]],
    start: str, end: str,
    benchmark: pd.Series,
    stock_symbols: List[str],
) -> BacktestResult:
    from investment_system.analysis.score_history import (
        _get_historical_cpi, _get_index_ma_series, _get_latest_known_value
    )
    dates = pd.date_range(start, end, freq="B")
    portfolio_value = pd.Series(index=dates, dtype=float)
    portfolio_value.iloc[0] = 1.0

    cpi_history = _get_historical_cpi(start, end)
    index_ma = _get_index_ma_series(start, end)

    rebalance_dates = pd.date_range(start, end, freq="4W-FRI")
    last_regime = "default"
    stock_holdings: Dict[str, float] = {}
    stock_entry: Dict[str, float] = {}
    stock_peak: Dict[str, float] = {}
    trades: List[Trade] = []

    for i, date in enumerate(dates[1:], 1):
        date_str = date.strftime("%Y-%m-%d")
        cpi_val = _get_latest_known_value(cpi_history, date)
        dev_val = index_ma.get(date_str)
        if dev_val is None:
            for d in sorted(index_ma.keys(), reverse=True):
                if d <= date_str:
                    dev_val = index_ma[d]
                    break
        gate_val = _relaxed_gate_val(cpi_val, dev_val)

        if date in rebalance_dates:
            last_regime = _get_regime_for_date(date, cpi_history, index_ma)
            regime_w = MACRO_REGIME_WEIGHTS.get(last_regime, MACRO_REGIME_WEIGHTS["default"])
            stock_target = regime_w["stock"] * gate_val

            date_scores = factor_scores.get(date_str, {})
            valid = {s: date_scores[s] for s in stock_symbols if s in date_scores and s in price_data}
            top_stocks = sorted(valid.items(), key=lambda x: x[1], reverse=True)[:5]
            new_stock_syms = {s for s, _ in top_stocks}

            for sym in list(stock_holdings.keys()):
                if sym not in new_stock_syms and sym in price_data:
                    idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(idx) > 0:
                        exit_p = float(price_data[sym].loc[idx[-1], "close"])
                        entry_p = stock_entry.get(sym, exit_p)
                        trades.append(Trade(sym, stock_entry.get(sym + "_date", ""), entry_p,
                                            date_str, exit_p, "rebalance",
                                            (exit_p - entry_p) / entry_p if entry_p > 0 else 0))
            for sym in new_stock_syms:
                if sym not in stock_holdings and sym in price_data:
                    idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(idx) > 0:
                        ep = float(price_data[sym].loc[idx[-1], "close"])
                        stock_entry[sym] = ep
                        stock_entry[sym + "_date"] = date_str
                        stock_peak[sym] = ep
            stock_holdings = {s: stock_target / max(len(top_stocks), 1) for s, _ in top_stocks}

        exit_set = set()
        for sym in list(stock_holdings.keys()):
            if sym not in price_data:
                continue
            idx = price_data[sym].index[price_data[sym].index <= date]
            if not len(idx):
                continue
            curr_p = float(price_data[sym].loc[idx[-1], "close"])
            entry_p = stock_entry.get(sym, curr_p)
            pnl = (curr_p - entry_p) / entry_p
            stock_peak[sym] = max(stock_peak.get(sym, curr_p), curr_p)
            dd = (curr_p - stock_peak[sym]) / stock_peak[sym] if stock_peak[sym] > 0 else 0
            if pnl <= -STOP_LOSS:
                exit_set.add(sym)
                trades.append(Trade(sym, stock_entry.get(sym + "_date", ""), entry_p,
                                    date_str, curr_p, "stop_loss", pnl))
            elif pnl >= 0.15 and dd <= -0.20:
                exit_set.add(sym)
                trades.append(Trade(sym, stock_entry.get(sym + "_date", ""), entry_p,
                                    date_str, curr_p, "trend_stop", pnl))
        for sym in exit_set:
            stock_holdings.pop(sym, None)
            stock_entry.pop(sym, None)
            stock_peak.pop(sym, None)

        regime_w = MACRO_REGIME_WEIGHTS.get(last_regime, MACRO_REGIME_WEIGHTS["default"])
        daily_ret = 0.0
        stock_total_w = sum(stock_holdings.values())
        if stock_total_w > 0:
            for sym, w in stock_holdings.items():
                if sym not in price_data:
                    continue
                df = price_data[sym]
                pi = df.index[df.index <= dates[i - 1]]
                ci = df.index[df.index <= date]
                if len(pi) > 0 and len(ci) > 0:
                    pp = float(df.loc[pi[-1], "close"])
                    cp = float(df.loc[ci[-1], "close"])
                    daily_ret += (w / stock_total_w) * regime_w["stock"] * (cp / pp - 1) if pp > 0 else 0

        for asset_class, sym in STRATEGY4_ETF_MAP.items():
            class_w = regime_w.get(asset_class, 0) * gate_val
            if sym not in price_data or class_w <= 0:
                continue
            df = price_data[sym]
            pi = df.index[df.index <= dates[i - 1]]
            ci = df.index[df.index <= date]
            if len(pi) > 0 and len(ci) > 0:
                pp = float(df.loc[pi[-1], "close"])
                cp = float(df.loc[ci[-1], "close"])
                daily_ret += class_w * (cp / pp - 1) if pp > 0 else 0

        portfolio_value.iloc[i] = portfolio_value.iloc[i - 1] * (1 + daily_ret)

    equity = portfolio_value.dropna()
    metrics = _calc_metrics(equity, benchmark)
    exclude = {"monthly_returns", "yearly_returns", "drawdown_series"}
    result = BacktestResult(
        strategy_name="策略四：宏观驱动全天候+双门",
        start_date=start,
        end_date=end,
        equity_curve=equity,
        benchmark_curve=benchmark,
        trades=trades,
        **{k: v for k, v in metrics.items() if k not in exclude},
    )
    result.monthly_returns = metrics.get("monthly_returns", pd.Series())
    result.yearly_returns = metrics.get("yearly_returns", {})
    result.drawdown_series = metrics.get("drawdown_series", pd.Series())
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
    entry_dates: Dict[str, str] = {}
    peak_prices: Dict[str, float] = {}
    trades: List[Trade] = []
    rebalance_dates = pd.date_range(start, end, freq="4W-FRI")
    REPLACEMENT_THRESHOLD = 0.15

    gate_closed_days = 0
    total_days = len(dates)

    for i, date in enumerate(dates[1:], 1):
        gate_val = 1.0
        if use_dual_gate and gate_series is not None:
            gate_val = float(gate_series.get(date, gate_series.get(date - timedelta(days=1), 1.0)))
        gate_open = gate_val > 0
        if gate_val < 0.8:
            gate_closed_days += 1

        if not gate_open and holdings:
            for sym, w in list(holdings.items()):
                if sym in price_data:
                    curr_idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(curr_idx) > 0:
                        exit_p = float(price_data[sym].loc[curr_idx[-1], "close"])
                        entry_p = entry_prices.get(sym, exit_p)
                        pnl = (exit_p - entry_p) / entry_p
                        entry_d = entry_dates.get(sym, "")
                        trades.append(Trade(sym, entry_d, entry_p, date.strftime("%Y-%m-%d"), exit_p, "dual_gate_close", pnl))
            holdings = {}
            entry_prices = {}
            entry_dates = {}

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
            entry_d = entry_dates.get(sym, "")

            peak_prices[sym] = max(peak_prices.get(sym, curr_p), curr_p)
            peak_p = peak_prices[sym]
            dd_from_peak = (curr_p - peak_p) / peak_p if peak_p > 0 else 0

            early_loss = pnl <= -STOP_LOSS

            is_winner = pnl >= 0.15
            trend_stop_triggered = is_winner and dd_from_peak <= -0.20

            if early_loss:
                exit_set.add(sym)
                trades.append(Trade(sym, entry_d, entry_p, date.strftime("%Y-%m-%d"), curr_p, "stop_loss", pnl))
            elif trend_stop_triggered:
                exit_set.add(sym)
                trades.append(Trade(sym, entry_d, entry_p, date.strftime("%Y-%m-%d"), curr_p, "trend_stop", pnl))
        for sym in exit_set:
            holdings.pop(sym, None)
            entry_prices.pop(sym, None)
            peak_prices.pop(sym, None)

        if date in rebalance_dates and gate_open:
            date_str = date.strftime("%Y-%m-%d")
            scores = factor_scores.get(date_str, {})
            if scores:
                def _right_side_ok(sym):
                    if sym not in price_data:
                        return False
                    df = price_data[sym]
                    hist = df[df.index <= date]
                    if len(hist) < 60:
                        return True
                    close = hist["close"].values
                    ma20 = float(np.mean(close[-20:])) if len(close) >= 20 else close[-1]
                    ma60 = float(np.mean(close[-60:]))
                    return close[-1] > ma60 and ma20 > ma60

                qualified = {sym: sc for sym, sc in scores.items() if _right_side_ok(sym)}
                if not qualified:
                    qualified = scores

                top_candidates = sorted(qualified.items(), key=lambda x: x[1], reverse=True)
                held_scores = {sym: scores.get(sym, 0.0) for sym in holdings}
                final_top = []
                held_remaining = set(holdings.keys())
                for sym, sc in top_candidates:
                    if sym in holdings:
                        final_top.append((sym, sc))
                        held_remaining.discard(sym)
                    else:
                        if held_remaining:
                            weakest_held = min(held_remaining, key=lambda s: held_scores.get(s, 0))
                            if sc > held_scores.get(weakest_held, 0) * (1 + REPLACEMENT_THRESHOLD):
                                final_top.append((sym, sc))
                                held_remaining.discard(weakest_held)
                        else:
                            final_top.append((sym, sc))
                    if len(final_top) >= PORTFOLIO_MAX_POSITIONS:
                        break
                if not final_top:
                    final_top = top_candidates[:PORTFOLIO_MAX_POSITIONS]
                top_n = final_top[:PORTFOLIO_MAX_POSITIONS]
                new_holdings = {sym: 1.0 / PORTFOLIO_MAX_POSITIONS for sym, _ in top_n}
                entered = set(new_holdings) - set(holdings)
                exited = set(holdings) - set(new_holdings)
                sym_chain = {}
                sym_score = {sym: sc for sym, sc in top_n}
                try:
                    from investment_system.config import INDUSTRY_CHAINS
                    for chain_name, chain_data in INDUSTRY_CHAINS.items():
                        for s in chain_data.get("symbols", []):
                            if str(s) not in sym_chain:
                                sym_chain[str(s)] = chain_name
                except Exception:
                    pass

                for sym in exited:
                    if sym in price_data:
                        curr_idx = price_data[sym].index[price_data[sym].index <= date]
                        if len(curr_idx) > 0:
                            exit_p = float(price_data[sym].loc[curr_idx[-1], "close"])
                            entry_p = entry_prices.get(sym, exit_p)
                            pnl = (exit_p - entry_p) / entry_p
                            entry_d = entry_dates.get(sym, "")
                            t = Trade(sym, entry_d, entry_p, date.strftime("%Y-%m-%d"),
                                      exit_p, "rebalance", pnl,
                                      chain=sym_chain.get(sym, ""),
                                      score=sym_score.get(sym, 0.0))
                            trades.append(t)
                for sym in entered:
                    if sym in price_data:
                        curr_idx = price_data[sym].index[price_data[sym].index <= date]
                        if len(curr_idx) > 0:
                            ep = float(price_data[sym].loc[curr_idx[-1], "close"])
                            entry_prices[sym] = ep
                            entry_dates[sym] = date.strftime("%Y-%m-%d")
                            peak_prices[sym] = ep
                for sym in exited:
                    peak_prices.pop(sym, None)
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

        portfolio_value.iloc[i] = portfolio_value.iloc[i - 1] * (1 + daily_ret * gate_val)

    equity = portfolio_value.dropna()
    metrics = _calc_metrics(equity, benchmark)
    exclude = {"monthly_returns", "yearly_returns", "drawdown_series"}
    result = BacktestResult(
        strategy_name=strategy_name,
        start_date=start,
        end_date=end,
        equity_curve=equity,
        benchmark_curve=benchmark,
        trades=trades,
        gate_closed_pct=gate_closed_days / max(total_days, 1),
        **{k: v for k, v in metrics.items() if k not in exclude},
    )
    result.monthly_returns = metrics.get("monthly_returns", pd.Series())
    result.yearly_returns = metrics.get("yearly_returns", {})
    result.drawdown_series = metrics.get("drawdown_series", pd.Series())
    return result


def _score_etf_pool(pool: List[str], price_data: Dict[str, pd.DataFrame],
                     date: pd.Timestamp) -> Dict[str, float]:
    """ETF多因子评分：动量40%+低波20%+流动性15%+跟踪误差10%+宏观拟合度15%"""
    scores = {}
    for sym in pool:
        if sym not in price_data:
            scores[sym] = 5.0  # 无数据则中位数
            continue
        df = price_data[sym]
        hist = df[df.index <= date]
        if len(hist) < 20:
            scores[sym] = 5.0
            continue
        close = hist["close"].values

        # 动量(60日)
        mom_60d = (close[-1] / close[max(0, len(close)-61)] - 1) * 100 if len(close) >= 61 else 0
        mom_score = max(0, min(10, 5 + mom_60d / 8))

        # 低波(20日波动率倒数)
        rets = np.diff(close[-21:]) / close[-21:-1] if len(close) >= 21 else [0.005] * 20
        vol_20d = float(np.std(rets) * np.sqrt(252) * 100)
        vol_score = max(1, min(10, 10 - vol_20d / 4))

        # 流动性(用数据可用天数/总天数 ≈ 交易活跃度代理)
        total_days = len(hist)
        data_gap_ratio = total_days / max((date - hist.index[0]).days, 1)
        liq_score = max(3, min(10, 5 + data_gap_ratio * 5))

        # 跟踪误差(固定中位数，后续可细化)
        te_score = 5.0

        # 宏观拟合度(固定中位数，后续可用CPI相关性细化)
        mf_score = 5.0

        total = (mom_score * ETF_FACTOR_WEIGHTS["momentum"] +
                 vol_score * ETF_FACTOR_WEIGHTS["low_vol"] +
                 liq_score * ETF_FACTOR_WEIGHTS["liquidity"] +
                 te_score * ETF_FACTOR_WEIGHTS["tracking_error"] +
                 mf_score * ETF_FACTOR_WEIGHTS["macro_fit"])
        scores[sym] = round(total, 2)

    return scores


def _get_historical_regime(date: pd.Timestamp, cpi_dict: Dict[str, float],
                            pmi_dict: Dict[str, float]) -> str:
    """用CPI + PMI推算历史宏观象限"""
    # 找最近的CPI（延迟45天）
    cpi_val = 1.5
    for d_str in sorted(cpi_dict.keys(), reverse=True):
        if date >= pd.Timestamp(d_str):
            cpi_val = cpi_dict[d_str]
            break
    # 找最近的PMI
    pmi_val = 50.0
    for d_str in sorted(pmi_dict.keys(), reverse=True):
        if date >= pd.Timestamp(d_str):
            pmi_val = pmi_dict[d_str]
            break

    if pmi_val < 48:
        return "衰退期" if cpi_val < 1.0 else "复苏期"
    elif cpi_val < 1.0:
        return "复苏期"
    elif cpi_val < 2.5:
        return "扩张期"
    else:
        return "过热期"


def run_strategy4(price_data: Dict[str, pd.DataFrame],
                  factor_scores: Dict[str, Dict[str, float]],
                  stock_symbols: List[str],
                  start: str, end: str,
                  benchmark: pd.Series,
                  gate_series: Optional[pd.Series] = None) -> BacktestResult:
    """
    策略四：宏观象限驱动的跨资产配置 + 多因子链内选股 + 双门乘数控制

    流程：
    1. 宏观象限→各类资产权重
    2. 各类资产池内多因子评分→排序选股
    3. 宏观权重×选股权重→最终配置
    4. 双门v2连续乘数×总仓位
    """
    strategy_name = "策略四：宏观驱动跨资产配置+双门"
    dates = pd.date_range(start, end, freq="B")
    portfolio_value = pd.Series(index=dates, dtype=float)
    portfolio_value.iloc[0] = 1.0
    rebalance_dates = pd.date_range(start, end, freq="4W-FRI")

    # 准备宏观数据
    try:
        from investment_system.analysis.score_history import _get_historical_cpi
        cpi_dict = _get_historical_cpi(start, end)
    except Exception:
        cpi_dict = {}
    # PMI数据（简化版：从CPI字典反向推理或使用默认值）
    pmi_dict = {}

    holdings: Dict[str, float] = {}
    entry_prices: Dict[str, float] = {}
    entry_dates: Dict[str, str] = {}
    trades: List[Trade] = []
    gate_closed_days = 0
    total_days = len(dates)

    for i, date in enumerate(dates[1:], 1):
        gate_val = 1.0
        if gate_series is not None:
            gate_val = float(gate_series.get(date, gate_series.get(date - timedelta(days=1), 1.0)))
        if gate_val < 0.8:
            gate_closed_days += 1

        # 仓位乘数为0时清仓
        if gate_val <= 0 and holdings:
            for sym, w in list(holdings.items()):
                if sym in price_data:
                    curr_idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(curr_idx) > 0:
                        exit_p = float(price_data[sym].loc[curr_idx[-1], "close"])
                        entry_p = entry_prices.get(sym, exit_p)
                        pnl = (exit_p - entry_p) / entry_p
                        trades.append(Trade(
                            sym, entry_dates.get(sym, ""), entry_p,
                            date.strftime("%Y-%m-%d"), exit_p, "dual_gate_close", pnl
                        ))
            holdings = {}
            entry_prices = {}
            entry_dates = {}
            portfolio_value.iloc[i] = portfolio_value.iloc[i - 1]
            continue

        # 月度再平衡：重配所有资产
        if date in rebalance_dates and gate_val > 0:
            regime = _get_historical_regime(date, cpi_dict, pmi_dict)
            weights = STRATEGY4_QUADRANT_WEIGHTS.get(regime, STRATEGY4_QUADRANT_WEIGHTS["default"])

            # ── ① A股链内选股 ──
            date_str = date.strftime("%Y-%m-%d")
            scores = factor_scores.get(date_str, {})
            # 筛选可用标的
            if scores:
                qualified = {}
                for sym, sc in scores.items():
                    if sym in stock_symbols and sym in price_data:
                        right_side = True
                        df_hist = price_data[sym][price_data[sym].index <= date]
                        if len(df_hist) >= 60:
                            c = df_hist["close"].values
                            ma60 = float(np.mean(c[-60:]))
                            ma20 = float(np.mean(c[-20:]))
                            if c[-1] <= ma60 or ma20 <= ma60:
                                right_side = False
                        if right_side:
                            qualified[sym] = sc
                if not qualified:
                    qualified = {sym: sc for sym, sc in scores.items()
                                 if sym in stock_symbols and sym in price_data}
                top_stocks = sorted(qualified.items(), key=lambda x: x[1], reverse=True)[:8]
            else:
                top_stocks = []

            # ── ② ETF多因子评分 ──
            stk_etf_scores = _score_etf_pool(STOCK_ETF_POOL, price_data, date)
            bnd_etf_scores = _score_etf_pool(BOND_ETF_POOL, price_data, date)
            cmd_etf_scores = _score_etf_pool(COMMODITY_ETF_POOL, price_data, date)

            # 美股/港股（从WATCHLIST加载）
            us_symbols = [k for k in stock_symbols if not str(k).isdigit() and not str(k).endswith(".HK")]
            hk_symbols = [k for k in stock_symbols if str(k).endswith(".HK")]

            # ── ③ 构建组合 ──
            new_holdings: Dict[str, float] = {}
            asset_weight = weights.get("a_share", 0.25)
            if top_stocks:
                per_stock = asset_weight / len(top_stocks)
                for sym, _ in top_stocks:
                    new_holdings[sym] = per_stock

            # 股票ETF
            etf_w = weights.get("stock_etf", 0.15)
            if stk_etf_scores:
                total_sc = sum(stk_etf_scores.values())
                if total_sc > 0:
                    for sym, sc in stk_etf_scores.items():
                        new_holdings[sym] = etf_w * (sc / total_sc)

            # 债券ETF
            bnd_w = weights.get("bond_etf", 0.15)
            if bnd_etf_scores:
                total_sc = sum(bnd_etf_scores.values())
                if total_sc > 0:
                    for sym, sc in bnd_etf_scores.items():
                        new_holdings[sym] = bnd_w * (sc / total_sc)

            # 商品ETF
            cmd_w = weights.get("commodity_etf", 0.15)
            if cmd_etf_scores:
                total_sc = sum(cmd_etf_scores.values())
                if total_sc > 0:
                    for sym, sc in cmd_etf_scores.items():
                        new_holdings[sym] = cmd_w * (sc / total_sc)

            # 美股（等权）
            us_w = weights.get("us_stock", 0.15)
            if us_symbols:
                per_us = us_w / len(us_symbols)
                for sym in us_symbols:
                    new_holdings[sym] = per_us

            # 港股（等权）
            hk_w = weights.get("hk_stock", 0.10)
            if hk_symbols:
                per_hk = hk_w / len(hk_symbols)
                for sym in hk_symbols:
                    new_holdings[sym] = per_hk

            # 记录交易
            exited = set(holdings) - set(new_holdings)
            entered = set(new_holdings) - set(holdings)
            for sym in exited:
                if sym in price_data:
                    curr_idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(curr_idx) > 0:
                        exit_p = float(price_data[sym].loc[curr_idx[-1], "close"])
                        entry_p = entry_prices.get(sym, exit_p)
                        pnl = (exit_p - entry_p) / entry_p
                        trades.append(Trade(
                            sym, entry_dates.get(sym, ""), entry_p,
                            date.strftime("%Y-%m-%d"), exit_p, "rebalance", pnl
                        ))
            for sym in entered:
                if sym in price_data:
                    curr_idx = price_data[sym].index[price_data[sym].index <= date]
                    if len(curr_idx) > 0:
                        entry_prices[sym] = float(price_data[sym].loc[curr_idx[-1], "close"])
                        entry_dates[sym] = date.strftime("%Y-%m-%d")
            for sym in exited:
                entry_prices.pop(sym, None)
                entry_dates.pop(sym, None)

            holdings = new_holdings

            # 交易摩擦
            churn = (len(entered) + len(exited)) / max(len(holdings) + len(exited), 1)
            portfolio_value.iloc[i - 1] *= (1 - 0.002 * churn)

        # 每日净值更新
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

        portfolio_value.iloc[i] = portfolio_value.iloc[i - 1] * (1 + daily_ret * gate_val)

    equity = portfolio_value.dropna()
    metrics = _calc_metrics(equity, benchmark)
    exclude = {"monthly_returns", "yearly_returns", "drawdown_series"}
    result = BacktestResult(
        strategy_name=strategy_name,
        start_date=start,
        end_date=end,
        equity_curve=equity,
        benchmark_curve=benchmark,
        trades=trades,
        gate_closed_pct=gate_closed_days / max(total_days, 1),
        **{k: v for k, v in metrics.items() if k not in exclude},
    )
    result.monthly_returns = metrics.get("monthly_returns", pd.Series())
    result.yearly_returns = metrics.get("yearly_returns", {})
    result.drawdown_series = metrics.get("drawdown_series", pd.Series())
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


def run_backtest(start: str = "2018-01-01", end: Optional[str] = None,
                 symbols: Optional[List[str]] = None) -> List[BacktestResult]:
    """
    主入口：运行三个策略的回测并返回结果列表。
    end=None 时自动使用 baostock 最新交易日（动态截止），保证研报和回测数据同源。
    """
    if end is None:
        try:
            import baostock as bs
            bs.login()
            rs = bs.query_trade_dates(start_date="2024-01-01", end_date="2030-12-31")
            last_trade = "2024-12-31"
            while rs.next():
                r = rs.get_row_data()
                if r[1] == "1":
                    last_trade = r[0]
            bs.logout()
            end = last_trade
            print(f"[backtest] end_date 自动设为 baostock 最新交易日: {end}")
        except Exception:
            end = datetime.now().strftime("%Y-%m-%d")
            print(f"[backtest] end_date fallback 到今天: {end}")
    if symbols is None:
        from investment_system.config import WATCHLIST, INDUSTRY_CHAINS
        chain_symbols_set = set()
        for chain in INDUSTRY_CHAINS.values():
            for s in chain.get("symbols", []):
                if str(s).isdigit():
                    chain_symbols_set.add(str(s))
        symbols = [k for k in WATCHLIST.keys()
                   if str(k).isdigit() and str(k) in chain_symbols_set]
        print(f"[backtest] 多因子选股池: WATCHLIST∩链内 = {len(symbols)}只"
              f" (WATCHLIST共{sum(1 for k in WATCHLIST if str(k).isdigit())}只A股,"
              f" 链内共{len(chain_symbols_set)}只)")
        if not symbols:
            symbols = [str(s) for s in chain_symbols_set][:60]
            print(f"[backtest] fallback 链内A股: {len(symbols)} 只")

    etf_symbols = list(ALLWEATHER_WEIGHTS.keys()) + list(STRATEGY4_ETF_MAP.values())
    all_symbols = list(set(symbols + etf_symbols + ALL_ETF_POOL + ["000300"]))

    # 策略四需要完整WATCHLIST（含美股/港股）
    all_watchlist = symbols.copy()
    try:
        from investment_system.config import WATCHLIST
        all_watchlist = [str(k) for k in WATCHLIST.keys()]
        us_hk = [k for k in WATCHLIST.keys() if any(c in str(k) for c in ["NVDA", "TSLA", "TSM", "GOOGL", "MSFT", "AMZN", "INTC", "VST", "CEG", "EQIX", "DLR", ".HK"])]
        all_symbols = list(set(all_symbols + us_hk))
    except Exception:
        pass

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
        closed_pct = (gate_series < 0.8).mean()
        avg_mult = gate_series.mean()
        print(f"[backtest] 双门历史: 非满仓{closed_pct:.1%}时间, 平均仓位乘数{avg_mult:.2f}")
    except Exception as e:
        print(f"[backtest] 双门历史加载失败({e})，fallback到全开...")
        gate_series = pd.Series(1, index=pd.date_range(start, end, freq="B"))
    r3 = run_multifactor_stock(price_data, factor_scores, start, end, benchmark, True, gate_series)

    print("[backtest] 策略四：宏观驱动跨资产配置+双门...")
    r4 = run_strategy4(price_data, factor_scores, all_watchlist, start, end, benchmark, gate_series)

    return [r1, r2, r3, r4]


def print_report(results: List[BacktestResult]):
    print("\n" + "=" * 80)
    print("回测报告 — 四策略对比（2018-2024）")
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
            tp_full_count = sum(1 for t in r.trades if t.exit_reason == "take_profit_full")
            trend_stop_count = sum(1 for t in r.trades if t.exit_reason == "trend_stop")
            rebalance_count = sum(1 for t in r.trades if t.exit_reason == "rebalance")
            print(f"    止盈(全仓)触发: {tp_full_count}次")
            print(f"    趋势止损触发: {trend_stop_count}次")
            rebalance_pnls = [t.pnl_pct for t in r.trades if t.exit_reason == "rebalance"]
            if rebalance_pnls:
                rb_wr = sum(1 for p in rebalance_pnls if p > 0) / len(rebalance_pnls)
                print(f"    换仓次数: {rebalance_count}次 | 换仓胜率: {rb_wr:.1%} | 换仓均盈: {np.mean(rebalance_pnls):+.1%}")
            holding_days = [t.holding_period() for t in r.trades if t.holding_period() > 0]
            if holding_days:
                print(f"    平均持仓天数: {np.mean(holding_days):.0f}天 | 中位数: {np.median(holding_days):.0f}天")
            n_years = max((pd.Timestamp(r.end_date) - pd.Timestamp(r.start_date)).days / 365, 1)
            turnover = len([t for t in r.trades if t.exit_reason not in ("dual_gate_close",)]) / (8 * n_years)
            print(f"    年化换手率: {turnover:.1f}x")
            if r.gate_closed_pct > 0:
                print(f"    双门非满仓: {r.gate_closed_pct:.1%}天")


def generate_investor_report(results: List[BacktestResult], output_path: str = "") -> str:
    """
    三层完整投资者报告：
    Layer 1: 组合概览（净值曲线、年度盈亏、回撤时段）
    Layer 2: 每笔交易记录（买了什么、何时买、何时卖、原因、盈亏）
    Layer 3: 选股逻辑（为什么选这只、在哪条链、得分多少）
    """
    lines = []
    SEP = "=" * 90

    lines.append(SEP)
    lines.append("  面基三源融合投资系统 · 完整回测报告（投资者版）")
    lines.append(SEP)

    for r in results:
        lines.append(f"\n{'━'*90}")
        lines.append(f"  策略：{r.strategy_name}  |  区间：{r.start_date} ~ {r.end_date}")
        lines.append(f"{'━'*90}")

        lines.append("\n【一、组合总览】")
        lines.append(f"  年化收益：{r.annual_return:+.1%}  |  最大回撤：{r.max_drawdown:.1%}  |  夏普：{r.sharpe:.2f}  |  卡玛：{r.calmar:.2f}")
        lines.append(f"  月度胜率（vs沪深300）：{r.win_rate_vs_benchmark:.1%}")
        if r.gate_closed_pct > 0:
            lines.append(f"  双门非满仓：{r.gate_closed_pct:.1%}时间（满仓=gate≥0.8x）")

        if r.yearly_returns:
            lines.append("\n【二、逐年盈亏】")
            bm_yearly = {}
            if not r.benchmark_curve.empty:
                bm_yr = r.benchmark_curve.resample("YE").last()
                for i in range(1, len(bm_yr)):
                    y = bm_yr.index[i].year
                    bm_yearly[y] = float(bm_yr.iloc[i] / bm_yr.iloc[i-1] - 1)

            header = f"  {'年份':<6} {'策略收益':>10} {'基准(沪深300)':>14} {'超额':>8} {'判定':>6}"
            lines.append(header)
            lines.append("  " + "-" * 50)
            for year in sorted(r.yearly_returns.keys()):
                ret = r.yearly_returns[year]
                bm = bm_yearly.get(year, None)
                bm_str = f"{bm:+.1%}" if bm is not None else "  N/A  "
                alpha = f"{ret - bm:+.1%}" if bm is not None else "  N/A"
                flag = "✅" if ret > 0 else "❌"
                lines.append(f"  {year:<6} {ret:>+10.1%} {bm_str:>14} {alpha:>8} {flag:>6}")

        if not r.drawdown_series.empty:
            lines.append("\n【三、最大回撤时段】")
            dd = r.drawdown_series
            min_dd = dd.min()
            if min_dd < -0.05:
                min_idx = dd.idxmin()
                peak_before = dd[:min_idx]
                peak_date = peak_before[peak_before == 0].index[-1] if (peak_before == 0).any() else dd.index[0]
                recovery = dd[min_idx:]
                recovery_dates = recovery[recovery >= -0.01].index
                rec_date = recovery_dates[0] if len(recovery_dates) > 0 else "未恢复"
                lines.append(f"  最大回撤 {min_dd:.1%}：从 {peak_date.strftime('%Y-%m-%d')} 开始，"
                              f"谷底 {min_idx.strftime('%Y-%m-%d')}，"
                              f"恢复于 {rec_date.strftime('%Y-%m-%d') if hasattr(rec_date, 'strftime') else rec_date}")

                dd_pcts = [-0.05, -0.10, -0.15, -0.20]
                for threshold in dd_pcts:
                    periods = []
                    in_dd = False
                    start_d = None
                    for d, v in dd.items():
                        if v <= threshold and not in_dd:
                            in_dd = True
                            start_d = d
                        elif v > threshold and in_dd:
                            in_dd = False
                            periods.append((start_d, d))
                    if in_dd:
                        periods.append((start_d, dd.index[-1]))
                    if periods:
                        dur = sum((e - s).days for s, e in periods)
                        lines.append(f"  回撤>{abs(threshold):.0%} 共 {len(periods)} 次，累计 {dur} 天")

        if r.trades:
            lines.append(f"\n【四、逐笔交易记录】（共{len(r.trades)}笔）")
            lines.append(f"  {'入场日':>12} {'出场日':>12} {'代码':>10} {'产业链':<18} {'入场价':>8} {'出场价':>8} {'盈亏':>8} {'持仓天':>6} {'原因'}")
            lines.append("  " + "-" * 110)

            sorted_trades = sorted(r.trades, key=lambda t: t.entry_date or "")
            for t in sorted_trades:
                hold = t.holding_period()
                pnl_str = f"{t.pnl_pct:+.1%}"
                flag = "🟢" if t.pnl_pct > 0 else "🔴"
                chain_short = (t.chain[:16] + "..") if len(t.chain) > 16 else t.chain
                lines.append(
                    f"  {t.entry_date or '?':>12} {t.exit_date or '?':>12} {t.symbol:>10} "
                    f"{chain_short:<18} {t.entry_price:>8.2f} {t.exit_price or 0:>8.2f} "
                    f"{flag}{pnl_str:>7} {hold:>6}天  {t.exit_reason_cn()}"
                )

            lines.append(f"\n【五、按退出原因统计】")
            from collections import Counter
            reason_counts = Counter(t.exit_reason for t in r.trades)
            reason_pnl: Dict[str, List[float]] = {}
            for t in r.trades:
                reason_pnl.setdefault(t.exit_reason, []).append(t.pnl_pct)
            for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
                pnls = reason_pnl[reason]
                avg = np.mean(pnls)
                win = sum(1 for p in pnls if p > 0) / len(pnls)
                cn = {"stop_loss":"止损","take_profit_full":"止盈(全)","take_profit_half":"止盈(半)",
                      "rebalance":"换仓","dual_gate_close":"双门关闭"}.get(reason, reason)
                lines.append(f"  {cn:<12} {count:>5}次  平均盈亏 {avg:+.1%}  胜率 {win:.0%}")

            lines.append(f"\n【六、产业链分布】")
            chain_data: Dict[str, List[float]] = {}
            for t in r.trades:
                if t.chain:
                    chain_data.setdefault(t.chain, []).append(t.pnl_pct)
            for chain, pnls in sorted(chain_data.items(), key=lambda x: -len(x[1])):
                avg = np.mean(pnls)
                win = sum(1 for p in pnls if p > 0) / len(pnls)
                lines.append(f"  {chain:<22} {len(pnls):>4}笔  平均盈亏 {avg:+.1%}  胜率 {win:.0%}")

            top_wins = sorted(r.trades, key=lambda t: t.pnl_pct, reverse=True)[:5]
            top_loss = sorted(r.trades, key=lambda t: t.pnl_pct)[:5]
            lines.append(f"\n【七、最佳5笔 vs 最差5笔】")
            lines.append("  最佳:")
            for t in top_wins:
                lines.append(f"    {t.symbol} {t.entry_date}→{t.exit_date}  {t.pnl_pct:+.1%}  [{t.chain}]")
            lines.append("  最差:")
            for t in top_loss:
                lines.append(f"    {t.symbol} {t.entry_date}→{t.exit_date}  {t.pnl_pct:+.1%}  [{t.chain}]  {t.exit_reason_cn()}")

    report_text = "\n".join(lines)

    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_text)
        print(f"[investor_report] 完整报告已保存: {output_path}")

    return report_text


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default=None, help="截止日期（默认自动取baostock最新交易日）")
    parser.add_argument("--output", default="", help="JSON输出路径（可选）")
    parser.add_argument("--investor-report", default="", help="投资者完整报告输出路径（.txt）")
    args = parser.parse_args()

    results = run_backtest(args.start, args.end)
    print_report(results)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump([r.to_dict() for r in results], f, ensure_ascii=False, indent=2)
        print(f"\n结果已保存到: {args.output}")

    investor_path = getattr(args, "investor_report", "")
    if investor_path:
        generate_investor_report(results, investor_path)
    else:
        print("\n" + "─"*50)
        print("提示：加 --investor-report /tmp/report.txt 生成完整投资者报告（含逐笔交易）")
        print("─"*50)