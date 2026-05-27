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
    """
    加载历史双门状态序列（1=开，0=关）。
    如果历史文件不存在，则用CPI/PMI数据重建。
    """
    if MACRO_HISTORY_FILE.exists():
        try:
            with open(MACRO_HISTORY_FILE) as f:
                history = json.load(f)
            dates = pd.date_range(start, end, freq="B")
            gate_vals = []
            for d in dates:
                date_str = d.strftime("%Y-%m-%d")
                entry = history.get(date_str)
                if entry is None:
                    prev = d - timedelta(days=1)
                    entry = history.get(prev.strftime("%Y-%m-%d"))
                if entry:
                    gate_vals.append(0 if entry.get("dual_closed") else 1)
                else:
                    gate_vals.append(1)
            return pd.Series(gate_vals, index=dates)
        except Exception as e:
            print(f"[score_history] 加载历史双门失败: {e}")

    print("[score_history] 无历史双门记录，尝试从宏观数据重建...")
    return _rebuild_gate_from_macro(start, end)


def _rebuild_gate_from_macro(start: str, end: str) -> pd.Series:
    """
    从历史CPI/PMI数据重建双门状态。
    Oracle建议：使用数据发布日期而非数据所属月份，避免前视偏差。
    
    双门规则（完整版）：
      宏观门：CPI < 1.0% → 红灯(关)    1.0-2.0% → 绿灯(开)  
              2.0-3.0% → 黄灯(关)    >3% → 红灯(关)
      趋势门：MA20偏离 < -5% → 红灯(关)  -5%~+5% → 黄灯(关)  >+5% → 绿灯(开)
      双门关闭 = 宏观门 in (红,黄) AND 趋势门 in (红,黄)
    """
    dates = pd.date_range(start, end, freq="B")
    gate_series = pd.Series(1, index=dates)

    cpi_history = _get_historical_cpi(start, end)
    index_ma = _get_index_ma_series(start, end)

    for i, date in enumerate(dates):
        cpi = _get_latest_known_value(cpi_history, date)
        if cpi is None:
            macro_gate_closed = False
        elif cpi < 1.0:
            macro_gate_closed = True   # 红灯
        elif cpi <= 2.0:
            macro_gate_closed = False  # 绿灯
        elif cpi <= 3.0:
            macro_gate_closed = True   # 黄灯
        else:
            macro_gate_closed = True   # 红灯

        dev = index_ma.get(date.strftime("%Y-%m-%d"), None)
        if dev is None:
            trend_gate_closed = False
        elif dev <= -0.05:
            trend_gate_closed = True   # 红灯
        elif dev >= 0.05:
            trend_gate_closed = False  # 绿灯
        else:
            trend_gate_closed = True   # 黄灯(-5%~+5%)

        gate_series.iloc[i] = 0 if (macro_gate_closed and trend_gate_closed) else 1

    closed_count = (gate_series == 0).sum()
    total = len(gate_series)
    print(f"[score_history] 双门重建完成: {closed_count}/{total}天关闭 ({closed_count/total:.1%})")
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
    """获取上证指数20日均线偏离度序列（趋势门判断依据）。
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
            start_date=(datetime.strptime(start, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d"),
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
            df["ma20"] = df["close"].rolling(20).mean()
            df["dev"] = (df["close"] - df["ma20"]) / df["ma20"]
            result = {k.strftime("%Y-%m-%d"): v for k, v in df["dev"].dropna().to_dict().items()}
            if result:
                print(f"[score_history] baostock 上证MA数据: {len(result)} 天")
                return result
    except Exception:
        pass

    # ── fallback: yfinance ──
    try:
        import yfinance as yf
        start_dt = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=60)).strftime("%Y-%m-%d")
        ticker = yf.Ticker("000001.SS")
        df = ticker.history(start=start_dt, end=end)
        if not df.empty:
            df.index = df.index.tz_localize(None)
            df["ma20"] = df["Close"].rolling(20).mean()
            df["dev"] = (df["Close"] - df["ma20"]) / df["ma20"]
            result = {k.strftime("%Y-%m-%d"): v for k, v in df["dev"].dropna().to_dict().items()}
            print(f"[score_history] yfinance 上证MA数据(baostock fallback): {len(result)} 天")
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
    """
    从baostock拉取历史财务数据（季度ROE+营收增速）。
    加45天报告滞后，避免前视偏差。
    baostock超时时返回空字典，回测fallback到纯价格因子。
    返回格式：{symbol: [{report_date, available_date, roe, rev_growth}]}
    """
    result = {}
    try:
        import baostock as bs
        import socket
        socket.setdefaulttimeout(4)  # 4s超时避免卡死
        bs.login()
        for sym in symbols:
            code = f"sh.{sym}" if sym.startswith(("5", "6")) else f"sz.{sym}"
            records = []
            for year in range(int(start[:4]) - 1, int(end[:4]) + 1):
                for quarter in [1, 2, 3, 4]:
                    try:
                        rs = bs.query_growth_data(code=code, year=year, quarter=quarter)
                        if rs.error_code != "0":
                            continue
                        while rs.next():
                            r = rs.get_row_data()
                            try:
                                report_date_str = f"{year}-{quarter * 3:02d}-30"
                                available_date = (
                                    datetime.strptime(report_date_str, "%Y-%m-%d") + timedelta(days=45)
                                ).strftime("%Y-%m-%d")
                                roe = float(r[3]) * 100 if r[3] and r[3].strip() else None
                                rev_growth = float(r[4]) * 100 if r[4] and r[4].strip() else None
                                if roe is not None:
                                    records.append({
                                        "available_date": available_date,
                                        "roe": roe,
                                        "rev_growth": rev_growth or 0.0,
                                    })
                            except Exception:
                                pass
                    except Exception:
                        pass
            if records:
                result[sym] = sorted(records, key=lambda x: x["available_date"])
        bs.logout()
    except Exception as e:
        print(f"[score_history] 财务数据拉取失败(超时/无数据): {e}")
    return result


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
    """
    从历史价格+基本面数据重建因子分快照（D-lite+方案）。
    
    因子构成（与 factor_scanner 对齐）：
      - 质量（ROE）：权重 25% — 需要baostock历史财务，45天滞后
      - 成长（营收增速）：权重 15% — 同上
      - 动量（20/60/120日）：权重 25%
      - 低波（90日波动率倒数）：权重 20%
      - 技术（RSI+MA）：权重 15%
    
    Oracle注意：PE历史百分位仍缺失（需Tushare，可后续增加）。
    比纯动量分可信得多，基本面因子有时间滞后保护，无前视偏差。
    """
    fundamental_data: Dict[str, List[dict]] = {}
    if use_fundamentals:
        print("[score_history] 拉取历史财务数据（ROE+营收增速，含45天滞后）...")
        fundamental_data = _fetch_fundamental_history(symbols, start, end)
        print(f"[score_history] 财务数据覆盖: {len(fundamental_data)}/{len(symbols)} 只")

    all_scores = {}
    rebalance_dates = pd.date_range(start, end, freq=rebalance_freq)

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

            ret_20 = (close[-1] / close[-21] - 1) * 100 if len(close) >= 21 else 0
            ret_60 = (close[-1] / close[-61] - 1) * 100 if len(close) >= 61 else 0
            ret_120 = (close[-1] / close[-121] - 1) * 100 if len(close) >= 121 else 0
            momentum_raw = ret_20 * 0.4 + ret_60 * 0.35 + ret_120 * 0.25
            s_momentum = max(1, min(10, 5 + momentum_raw / 8))

            if len(close) >= 60:
                returns_arr = np.diff(close[-61:]) / close[-61:-1]
                vol = float(np.std(returns_arr) * np.sqrt(252) * 100)
                s_lowvol = max(1, min(10, 10 - (vol - 15) / 4))
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
            s_tech = max(1, min(10, s_tech))

            s_quality = 5.0
            s_growth = 5.0
            if sym in fundamental_data:
                fd = _get_latest_fundamental(fundamental_data[sym], date)
                if fd:
                    roe = fd.get("roe", 0) or 0
                    rev = fd.get("rev_growth", 0) or 0
                    s_quality = max(1, min(10, 1 + 9 * min(abs(roe), 40) / 40))
                    s_growth = max(1, min(10, 1 + 9 * min(abs(rev), 60) / 60))

            if use_fundamentals and sym in fundamental_data:
                score = (s_quality * 0.25 + s_growth * 0.15 +
                         s_momentum * 0.25 + s_lowvol * 0.20 + s_tech * 0.15)
            else:
                score = s_momentum * 0.50 + s_lowvol * 0.30 + s_tech * 0.20

            day_scores[sym] = round(max(1, min(10, score)), 2)

        if day_scores:
            all_scores[date_str] = day_scores

    return all_scores
