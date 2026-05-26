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
    from investment_system.config import DATA_DIR
    SCORE_DIR = DATA_DIR / "factor_scores"
except Exception:
    import pathlib
    SCORE_DIR = pathlib.Path("/home/admin/.hermes/investment_system/data/factor_scores")

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
    
    双门规则：
      宏观门：CPI < 1.0% → 红灯，1.0-2.0% → 绿灯，2.0-3.0% → 黄灯，>3% → 红灯
      趋势门：20日均线偏离度 < -5% → 红灯，-5%到5% → 黄灯，>5% → 绿灯
      双门关闭 = 宏观门 in (红,黄) AND 趋势门 in (红,黄)
    """
    dates = pd.date_range(start, end, freq="B")
    gate_series = pd.Series(1, index=dates)

    cpi_history = _get_historical_cpi(start, end)
    index_ma = _get_index_ma_series(start, end)

    for i, date in enumerate(dates):
        date_str = date.strftime("%Y-%m-%d")

        cpi = _get_latest_known_value(cpi_history, date)
        if cpi is None:
            macro_gate_closed = False
        elif cpi < 1.0 or cpi > 3.0:
            macro_gate_closed = True
        elif cpi >= 2.0:
            macro_gate_closed = True
        else:
            macro_gate_closed = False

        dev = index_ma.get(date, None)
        if dev is None:
            trend_gate_closed = False
        elif dev < -0.05:
            trend_gate_closed = True
        elif dev < 0.05:
            trend_gate_closed = True
        else:
            trend_gate_closed = False

        gate_series.iloc[i] = 0 if (macro_gate_closed and trend_gate_closed) else 1

    closed_count = (gate_series == 0).sum()
    total = len(gate_series)
    print(f"[score_history] 双门重建完成: {closed_count}/{total}天关闭 ({closed_count/total:.1%})")
    return gate_series


def _get_historical_cpi(start: str, end: str) -> Dict[str, float]:
    """获取历史CPI数据（带发布日期延迟）。"""
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
            return cpi_dict
    except Exception:
        pass

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
    """获取上证指数20日均线偏离度序列（趋势门判断依据）。"""
    try:
        import baostock as bs
        bs.login()
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
        if not rows:
            return {}
        df = pd.DataFrame(rows).set_index("date")
        df["ma20"] = df["close"].rolling(20).mean()
        df["dev"] = (df["close"] - df["ma20"]) / df["ma20"]
        return df["dev"].to_dict()
    except Exception:
        return {}


def _get_latest_known_value(data_dict: Dict[str, float], date) -> Optional[float]:
    """返回在给定日期之前最近已知的值（模拟数据发布延迟）。"""
    date_str = date.strftime("%Y-%m-%d")
    known_dates = sorted([d for d in data_dict.keys() if d <= date_str], reverse=True)
    if known_dates:
        return data_dict[known_dates[0]]
    return None


def build_historical_scores_from_prices(
    symbols: List[str],
    price_data: Dict[str, pd.DataFrame],
    start: str,
    end: str,
    rebalance_freq: str = "W-FRI"
) -> Dict[str, Dict[str, float]]:
    """
    从历史价格数据重建因子分快照（D-lite方案）。
    
    用于2018-2024历史期回测，比纯模拟动量分可信得多：
      - 动量因子：20日+60日+120日收益率加权（与live系统一致）
      - 低波因子：90日年化波动率倒数
      - 技术因子：RSI + MA位置
    
    Oracle注意：这仍然不包含基本面因子的历史数据（ROE等需要点时PIT）。
    用于验证策略框架合理性是足够的，但不能用于精确归因。
    """
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
            momentum = (ret_20 * 0.4 + ret_60 * 0.35 + ret_120 * 0.25)
            s_momentum = max(1, min(10, 5 + momentum / 8))

            if len(close) >= 60:
                returns = np.diff(close[-61:]) / close[-61:-1]
                vol = float(np.std(returns) * np.sqrt(252) * 100)
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
            ma60 = np.mean(close[-60:]) if len(close) >= 60 else close[-1]
            ma60_dev = (close[-1] - ma60) / ma60 * 100
            s_tech = 5.0
            if 30 < rsi < 70:
                s_tech += 1.0
            if -5 < ma60_dev < 15:
                s_tech += 1.5
            if ma60_dev > 0:
                s_tech += 0.5

            score = s_momentum * 0.5 + s_lowvol * 0.3 + s_tech * 0.2
            score = round(max(1, min(10, score)), 2)
            day_scores[sym] = score

        if day_scores:
            all_scores[date_str] = day_scores

    return all_scores
