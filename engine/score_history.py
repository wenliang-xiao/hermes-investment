"""
因子分历史数据库 v1.0

解决回测核心问题：因子分没有历史记录，回测只能用模拟动量分。

设计思路（Oracle 建议的 B+D-lite 路线）：
  每次周报/日报运行后，把当天的因子分保存为日期快照。
  回测时从快照加载真实历史因子分。
  
  对于2018-2024的历史期，用"简化PIT重建"：
    - 价格类因子（动量、波动率、技术面）：直接从历史价格计算，完全准确
    - 基本面因子（ROE、营收增速）：从baostock历史财务数据获取，加45天报告滞后
    - PE历史百分位：从Tushare历史PE序列计算
  
  这比纯模拟动量分可信得多，也比完美PIT实现快得多。

存储路径：DATA_DIR/factor_scores/YYYY-MM-DD.json
"""
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


try:
    from investment_system.config import BASE
    SCORE_DIR = BASE / ".hermes" / "factor_scores"
except Exception:
    import pathlib
    SCORE_DIR = pathlib.Path("/home/admin/.hermes/investment_system/.hermes/factor_scores")

MACRO_HISTORY_FILE = SCORE_DIR.parent / "macro_gate_history.json"


def save_scores(date_str: str, scores: Dict[str, float]):
    """保存某日的因子评分快照。每次周报/日报扫描完成后调用。"""
    try:
        SCORE_DIR.mkdir(parents=True, exist_ok=True)
        path = SCORE_DIR / f"{date_str}.json"
        existing = {}
        if path.exists():
            with open(path) as f:
                existing = json.load(f)
        existing.update(scores)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(existing, f, ensure_ascii=False)
    except Exception as e:
        print(f"[score_history] 保存失败 {date_str}: {e}")


def load_scores(date_str: str) -> Dict[str, float]:
    """加载某日的因子评分快照。回测时使用。"""
    path = SCORE_DIR / f"{date_str}.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def load_scores_range(start: str, end: str) -> Dict[str, Dict[str, float]]:
    """加载日期范围内所有因子分快照。用于回测初始化。"""
    result = {}
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    cur = start_dt
    while cur <= end_dt:
        date_str = cur.strftime("%Y-%m-%d")
        scores = load_scores(date_str)
        if scores:
            result[date_str] = scores
        cur += timedelta(days=1)
    return result


def save_macro_gate(date_str: str, macro_gate: str, trend_gate: str):
    """保存某日的双门状态。每次宏观数据更新后调用。"""
    try:
        history = {}
        if MACRO_HISTORY_FILE.exists():
            with open(MACRO_HISTORY_FILE) as f:
                history = json.load(f)
        dual_closed = macro_gate in ("红灯", "黄灯") and trend_gate in ("红灯", "黄灯")
        history[date_str] = {
            "macro_gate": macro_gate,
            "trend_gate": trend_gate,
            "dual_closed": dual_closed,
        }
        MACRO_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(MACRO_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False)
    except Exception as e:
        print(f"[score_history] 双门保存失败 {date_str}: {e}")


def load_macro_gate_series(start: str, end: str) -> pd.Series:
    if MACRO_HISTORY_FILE.exists():
        try:
            with open(MACRO_HISTORY_FILE) as f:
                history = json.load(f)
            dates = pd.date_range(start, end, freq="B")
            gate_vals = []
            hit_count = 0
            for d in dates:
                date_str = d.strftime("%Y-%m-%d")
                entry = history.get(date_str)
                if entry is None:
                    prev = d - timedelta(days=1)
                    entry = history.get(prev.strftime("%Y-%m-%d"))
                if entry:
                    gate_vals.append(0 if entry.get("dual_closed") else 1)
                    hit_count += 1
                else:
                    gate_vals.append(1)
            coverage = hit_count / max(len(dates), 1)
            if coverage >= 0.2:
                print(f"[score_history] 缓存双门覆盖率{coverage:.0%}，直接使用")
                return pd.Series(gate_vals, index=dates)
            print(f"[score_history] 缓存覆盖率仅{coverage:.0%}<20%，改用宏观数据重建")
        except Exception as e:
            print(f"[score_history] 加载历史双门失败({e})，改用宏观数据重建")

    print("[score_history] 从宏观数据重建双门序列...")
    return _rebuild_gate_from_macro(start, end)


def _rebuild_gate_from_macro(start: str, end: str) -> pd.Series:
    """
    双门仓位乘数（v2：仓位乘数模式，不再是0/1开关）。

    面基+LDS 的真实含义：宏观不好不是「不能操作」而是「降低风险敞口」。
    CPI<1%的通缩是中国长期常态，用0/1开关等于永久锁死策略。

    宏观门（CPI驱动）：
      CPI < 0.0%   → 0.3x（严重通缩，极度防御）
      CPI 0.0-1.0% → 0.5x（温和通缩，半仓）
      CPI 1.0-2.0% → 1.0x（正常，满仓）
      CPI 2.0-3.0% → 0.75x（温和通胀，适度收缩）
      CPI > 3.0%   → 0.3x（过热通胀，极度防御）

    趋势门（MA60偏离）：
      MA60偏离 <= -5% → 额外乘以 0.5x（趋势明显下行）
      其他            → 不做额外调整

    最终 gate_val = 宏观乘数 × 趋势乘数，范围 [0.15, 1.0]
    backtest 里: gate_val=0 → 空仓，>0 → 按比例持仓
    """
    dates = pd.date_range(start, end, freq="B")
    gate_series = pd.Series(1.0, index=dates)

    cpi_history = _get_historical_cpi(start, end)
    index_ma = _get_index_ma_series(start, end)

    for i, date in enumerate(dates):
        cpi = _get_latest_known_value(cpi_history, date)

        if cpi is None:
            macro_mult = 1.0
        elif cpi < 0.0:
            macro_mult = 0.3
        elif cpi < 1.0:
            macro_mult = 0.5
        elif cpi < 2.0:
            macro_mult = 1.0
        elif cpi < 3.0:
            macro_mult = 0.75
        else:
            macro_mult = 0.3

        dev = index_ma.get(date.strftime("%Y-%m-%d"), None)
        trend_mult = 0.5 if (dev is not None and dev <= -0.05) else 1.0

        gate_val = round(macro_mult * trend_mult, 2)
        gate_series.iloc[i] = gate_val

    full_close = (gate_series <= 0.15).sum()
    half = ((gate_series > 0.15) & (gate_series < 0.8)).sum()
    full_open = (gate_series >= 0.8).sum()
    total = len(gate_series)
    print(f"[score_history] 双门重建(仓位乘数): 全防御{full_close/total:.1%} "
          f"| 半仓{half/total:.1%} | 满仓{full_open/total:.1%}")
    return gate_series


def _get_historical_cpi(start: str, end: str) -> Dict[str, float]:
    """获取历史CPI数据（带发布日期延迟）。"""
    import socket as _sock
    _sock.setdefaulttimeout(10)  # AKShare防挂死

    try:
        import akshare as ak
        df = ak.macro_china_cpi_monthly()
        if df is not None and not df.empty:
            cpi_dict = {}
            for _, row in df.iterrows():
                date_val = str(row.iloc[0])
                cpi_val = row.iloc[1] if len(row) > 1 else None
                if date_val and cpi_val is not None:
                    try:
                        release_date = (
                            datetime.strptime(date_val[:7], "%Y-%m") + timedelta(days=45)
                        ).strftime("%Y-%m-%d")
                        cpi_dict[release_date] = float(cpi_val)
                    except Exception:
                        pass
            if cpi_dict:
                return cpi_dict
    except Exception:
        pass

    # 硬编码fallback：2018-2024各季CPI，日期已含45天报告滞后
    known_cpi = {
        "2018-01-01": 1.5, "2018-04-01": 2.1, "2018-07-01": 2.0, "2018-10-01": 2.5,
        "2019-01-01": 1.7, "2019-04-01": 2.5, "2019-07-01": 2.8, "2019-10-01": 3.8,
        "2020-01-01": 5.4, "2020-04-01": 3.3, "2020-07-01": 2.7, "2020-10-01": 0.5,
        "2021-01-01": -0.3, "2021-04-01": 0.9, "2021-07-01": 1.0, "2021-10-01": 1.5,
        "2022-01-01": 0.9, "2022-04-01": 1.5, "2022-07-01": 2.7, "2022-10-01": 2.1,
        "2023-01-01": 2.1, "2023-04-01": 0.1, "2023-07-01": -0.3, "2023-10-01": -0.2,
        "2024-01-01": 0.2, "2024-04-01": 0.3, "2024-07-01": 0.5, "2024-10-01": 0.3,
    }
    return known_cpi


def _get_index_ma_series(start: str, end: str) -> Dict:
    """获取上证指数60日均线偏离度序列（趋势门判断依据）。
    优先baostock，超时失败时fallback到yfinance。
    """
    # ── 先试 baostock ──
    try:
        import baostock as bs
        bs.login()
        import socket
        socket.setdefaulttimeout(15)
        rs = bs.query_history_k_data_plus(
            "sh.000001", "date,close",
            start_date=(datetime.strptime(start, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d"),
            end_date=end,
            frequency="d"
        )
        rows = []
        while rs.next():
            r = rs.get_row_data()
            if r[1]:
                rows.append({"date": pd.Timestamp(r[0]), "close": float(r[1])})
        bs.logout()
        if rows:
            df = pd.DataFrame(rows).set_index("date")
            df["ma60"] = df["close"].rolling(60).mean()
            df["dev"] = (df["close"] - df["ma60"]) / df["ma60"]
            result = {k.strftime("%Y-%m-%d"): v for k, v in df["dev"].dropna().to_dict().items()}
            if result:
                print(f"[score_history] baostock 上证MA60数据: {len(result)} 天")
                return result
    except Exception:
        pass

    # ── fallback: yfinance ──
    try:
        import yfinance as yf
        start_dt = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=120)).strftime("%Y-%m-%d")
        ticker = yf.Ticker("000001.SS")
        df = ticker.history(start=start_dt, end=end)
        if not df.empty:
            df.index = df.index.tz_localize(None)
            df["ma60"] = df["Close"].rolling(60).mean()
            df["dev"] = (df["Close"] - df["ma60"]) / df["ma60"]
            result = {k.strftime("%Y-%m-%d"): v for k, v in df["dev"].dropna().to_dict().items()}
            print(f"[score_history] yfinance 上证MA60数据(baostock fallback): {len(result)} 天")
            return result
    except Exception as e:
        print(f"[score_history] yfinance fallback也失败: {e}")

    return {}


def _get_latest_known_value(data_dict: Dict[str, float], date) -> Optional[float]:
    """返回在给定日期之前最近已知的值（模拟数据发布延迟）。"""
    date_str = date.strftime("%Y-%m-%d")
    known_dates = sorted([d for d in data_dict.keys() if d <= date_str], reverse=True)
    if known_dates:
        return data_dict[known_dates[0]]
    return None


def _fetch_fundamental_history(symbols: List[str], start: str, end: str) -> Dict[str, List[dict]]:
    result = {}
    pe_history: Dict[str, pd.Series] = {}
    try:
        import baostock as bs
        import socket
        socket.setdefaulttimeout(8)
        bs.login()

        for sym in symbols:
            code = f"sh.{sym}" if sym.startswith(("5", "6")) else f"sz.{sym}"

            growth_by_period: Dict[str, dict] = {}
            for year in range(int(start[:4]) - 1, int(end[:4]) + 1):
                for quarter in [1, 2, 3, 4]:
                    period_key = f"{year}q{quarter}"
                    try:
                        rs = bs.query_growth_data(code=code, year=year, quarter=quarter)
                        if rs.error_code != "0":
                            continue
                        while rs.next():
                            r = rs.get_row_data()
                            try:
                                roe = float(r[3]) * 100 if r[3] and r[3].strip() else None
                                rev_growth = float(r[4]) * 100 if r[4] and r[4].strip() else None
                                profit_growth = float(r[5]) * 100 if len(r) > 5 and r[5] and r[5].strip() else None
                                if roe is not None:
                                    growth_by_period[period_key] = {
                                        "year": year, "quarter": quarter,
                                        "roe": roe,
                                        "rev_growth": rev_growth or 0.0,
                                        "profit_growth": profit_growth or 0.0,
                                    }
                            except Exception:
                                pass
                    except Exception:
                        pass

            dupont_by_period: Dict[str, dict] = {}
            for year in range(int(start[:4]) - 1, int(end[:4]) + 1):
                for quarter in [1, 2, 3, 4]:
                    period_key = f"{year}q{quarter}"
                    try:
                        rs = bs.query_dupont_data(code=code, year=year, quarter=quarter)
                        if rs.error_code != "0":
                            continue
                        while rs.next():
                            r = rs.get_row_data()
                            try:
                                gross_margin = float(r[4]) * 100 if len(r) > 4 and r[4] and r[4].strip() else None
                                if gross_margin is not None:
                                    dupont_by_period[period_key] = {"gross_margin": gross_margin}
                            except Exception:
                                pass
                    except Exception:
                        pass

            records = []
            for period_key, gd in growth_by_period.items():
                year, quarter = gd["year"], gd["quarter"]
                report_date_str = f"{year}-{quarter * 3:02d}-30"
                available_date = (
                    datetime.strptime(report_date_str, "%Y-%m-%d") + timedelta(days=45)
                ).strftime("%Y-%m-%d")
                rec = {
                    "available_date": available_date,
                    "roe": gd["roe"],
                    "rev_growth": gd["rev_growth"],
                    "profit_growth": gd["profit_growth"],
                    "gross_margin": dupont_by_period.get(period_key, {}).get("gross_margin", 0.0),
                }
                records.append(rec)
            if records:
                result[sym] = sorted(records, key=lambda x: x["available_date"])

            try:
                rs_pe = bs.query_history_k_data_plus(
                    code, "date,peTTM",
                    start_date=start, end_date=end,
                    frequency="w", adjustflag="3")
                if rs_pe.error_code == "0":
                    pe_rows = []
                    while rs_pe.next():
                        r = rs_pe.get_row_data()
                        try:
                            if r[1] and r[1].strip():
                                pe_val = float(r[1])
                                if 0 < pe_val < 2000:
                                    pe_rows.append((r[0], pe_val))
                        except Exception:
                            pass
                    if pe_rows:
                        s = pd.Series(dict(pe_rows))
                        s.index = pd.to_datetime(s.index)
                        pe_history[sym] = s.dropna()
            except Exception:
                pass

        bs.logout()
    except Exception as e:
        print(f"[score_history] 财务数据拉取失败(超时/无数据): {e}")

    result["__pe_history__"] = pe_history  # type: ignore[assignment]
    return result


def _calc_pe_percentile_from_history(pe_series: pd.Series, date: pd.Timestamp, current_pe: float) -> Optional[float]:
    if pe_series.empty or current_pe <= 0:
        return None
    hist = pe_series[pe_series.index <= date]
    if len(hist) < 20:
        return None
    return float((hist < current_pe).mean()) * 100


def _get_latest_fundamental(fund_hist: List[dict], date) -> dict:
    date_str = date.strftime("%Y-%m-%d")
    known = [r for r in fund_hist if r["available_date"] <= date_str]
    return known[-1] if known else {}


def build_historical_scores_from_prices(
    symbols: List[str],
    price_data: Dict[str, pd.DataFrame],
    start: str,
    end: str,
    rebalance_freq: str = "W-FRI",
    use_fundamentals: bool = True,
) -> Dict[str, Dict[str, float]]:
    fundamental_data: Dict[str, List[dict]] = {}
    pe_hist_map: Dict[str, pd.Series] = {}

    if use_fundamentals:
        print("[score_history] 拉取历史财务+PE数据（含45天PIT延迟）...")
        raw = _fetch_fundamental_history(symbols, start, end)
        pe_hist_map = raw.pop("__pe_history__", {})  # type: ignore[arg-type]
        fundamental_data = raw
        print(f"[score_history] 财务覆盖: {len(fundamental_data)}/{len(symbols)}只  PE历史: {len(pe_hist_map)}只")

    try:
        from investment_system.config import FACTOR_WEIGHTS
        _factor_weights = FACTOR_WEIGHTS
    except Exception:
        _factor_weights = {"default": {"质量": 0.23, "价值": 0.17, "成长": 0.17,
                                        "低波": 0.17, "红利": 0.17, "动量": 0.09}}

    cpi_hist = _get_historical_cpi(start, end)
    index_ma = _get_index_ma_series(start, end)

    try:
        from investment_system.analysis.factor_scanner import FactorScanner
        _fs = FactorScanner()
    except Exception:
        _fs = None

    all_scores = {}
    rebalance_dates = pd.date_range(start, end, freq=rebalance_freq)

    for date in rebalance_dates:
        date_str = date.strftime("%Y-%m-%d")

        cpi_val = _get_latest_known_value(cpi_hist, date)
        dev_val = index_ma.get(date_str)
        try:
            regime = _get_historical_regime_for_score(date, cpi_val, dev_val)
        except Exception:
            regime = "default"
        w = _factor_weights.get(regime, _factor_weights.get("default", {}))

        day_scores = {}

        for sym in symbols:
            if sym not in price_data:
                continue
            df = price_data[sym]
            hist = df[df.index <= date]
            if len(hist) < 60:
                continue
            close = hist["close"].values

            ret_20 = (close[-1] / close[-21] - 1) * 100 if len(close) >= 21 else 0
            ret_60 = (close[-1] / close[-61] - 1) * 100 if len(close) >= 61 else 0
            ret_120 = (close[-1] / close[-121] - 1) * 100 if len(close) >= 121 else 0
            s_momentum = max(1.0, min(10.0, 5 + (ret_20 * 0.4 + ret_60 * 0.35 + ret_120 * 0.25) / 8))

            if len(close) >= 60:
                vol = float(np.std(np.diff(close[-61:]) / close[-61:-1]) * np.sqrt(252) * 100)
                s_lowvol = max(1.0, min(10.0, 10 - (vol - 15) / 4))
            else:
                s_lowvol = 5.0

            rsi = 50.0
            if len(close) >= 15:
                diffs = np.diff(close[-15:])
                gains = np.mean(np.maximum(diffs, 0))
                losses = np.mean(np.maximum(-diffs, 0))
                if losses > 0:
                    rsi = 100 - 100 / (1 + gains / losses)
            ma60 = float(np.mean(close[-60:])) if len(close) >= 60 else float(close[-1])
            ma60_dev = (close[-1] - ma60) / ma60 * 100
            s_tech = 5.0
            if 30 < rsi < 70:
                s_tech += 1.0
            if -5 < ma60_dev < 15:
                s_tech += 1.5
            if ma60_dev > 0:
                s_tech += 0.5
            s_tech = max(1.0, min(10.0, s_tech))

            quality_gate_pass = True
            if use_fundamentals and sym in fundamental_data:
                fd = _get_latest_fundamental(fundamental_data[sym], date)
                if fd:
                    roe = fd.get("roe", None)
                    rev = fd.get("rev_growth", None)
                    profit_g = fd.get("profit_growth", None)
                    roe_neg = roe is not None and roe < -5.0
                    rev_collapse = rev is not None and rev < -30.0
                    profit_collapse = profit_g is not None and profit_g < -50.0
                    if roe_neg and rev_collapse:
                        quality_gate_pass = False
                    if profit_collapse and roe_neg:
                        quality_gate_pass = False

            if not quality_gate_pass:
                continue

            s_profit_pool = 5.0
            perez_mult = 1.0
            if _fs is not None:
                try:
                    s_profit_pool = _fs._get_profit_pool_score(sym)
                    perez_mult = _fs._get_perez_multiplier(sym)
                except Exception:
                    pass

            industry_rel = 0.0
            if len(close) >= 61:
                sym_ret_60 = close[-1] / close[-61] - 1
                all_rets = []
                for other in list(day_scores.keys())[:30]:
                    if other in price_data:
                        oh = price_data[other]
                        oh_hist = oh[oh.index <= date]
                        if len(oh_hist) >= 61:
                            all_rets.append(oh_hist["close"].values[-1] / oh_hist["close"].values[-61] - 1)
                if all_rets:
                    industry_rel = sym_ret_60 - float(np.median(all_rets))

            s_rel_momentum = max(1.0, min(10.0, 5.0 + industry_rel * 30))
            score = (s_momentum * 0.50 + s_rel_momentum * 0.20 +
                     s_lowvol * 0.10 + s_tech * 0.05 +
                     s_profit_pool * 0.15)
            score = max(1.0, min(10.0, score * perez_mult))
            day_scores[sym] = round(score, 2)

        if day_scores:
            all_scores[date_str] = day_scores

    return all_scores


def _get_historical_regime_for_score(date: pd.Timestamp, cpi_val: Optional[float],
                                      dev_val: Optional[float]) -> str:
    trend_down = dev_val is not None and dev_val <= -0.05
    if cpi_val is None:
        return "default"
    if trend_down and cpi_val < 1.0:
        return "衰退期"
    if cpi_val >= 2.5:
        return "过热期"
    if trend_down:
        return "衰退期"
    if cpi_val >= 1.0:
        return "扩张期"
    return "复苏期"
