"""
data/sources/baostock_source.py — A股日线数据源

包装 baostock，提供 A 股+ETF 的历史日线。
"""
from __future__ import annotations
from pathlib import Path
import sys, os, json
from datetime import datetime

_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def _bs_login():
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return bs

def _a_code(symbol: str) -> str:
    """Convert 6-digit code to baostock format (sh/sz.xxxxxx)"""
    if symbol.startswith(("60", "68", "51", "15", "16")):
        return f"sh.{symbol}"
    elif symbol.startswith(("00", "30", "159")):
        return f"sz.{symbol}"
    return symbol

def get_history_a(symbol: str, days: int = 1200):
    """拉取 A 股/ETF 历史日线 (支持 baostock + AKShare fallback)"""
    import baostock as bs
    import pandas as pd
    bs_code = _a_code(symbol)

    # Query fields
    fields = "date,open,high,low,close,volume,amount,peTTM,pctChg"

    # Calculate start date
    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    # Estimate ~1.3x trading days for calendar days
    start_date = (datetime.now() - timedelta(days=int(days * 1.4))).strftime("%Y-%m-%d")

    # Login
    lg = bs.login()
    if lg.error_code != "0":
        return None

    rs = bs.query_history_k_data_plus(
        bs_code, fields,
        start_date=start_date, end_date=end_date,
        frequency="d", adjustflag="2"  # 前复权
    )
    bs.logout()

    if rs.error_code != "0":
        return None

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    if not rows:
        # baostock没数据 → 试试AKShare ETF历史
        bs.logout()
        try:
            import akshare as ak
            df = ak.fund_etf_hist_em(symbol=symbol, period="daily", start_date="20180101", end_date=datetime.now().strftime("%Y%m%d"), adjust="qfq")
            if df is not None and not df.empty:
                dates = df["日期"].tolist() if "日期" in df.columns else []
                if dates:
                    result = {
                        "symbol": symbol,
                        "dates": [str(d) for d in dates],
                        "open": [float(v) if v else 0 for v in df.get("开盘", [0]*len(dates))],
                        "high": [float(v) if v else 0 for v in df.get("最高", [0]*len(dates))],
                        "low": [float(v) if v else 0 for v in df.get("最低", [0]*len(dates))],
                        "close": [float(v) if v else 0 for v in df.get("收盘", [0]*len(dates))],
                        "volume": [float(v) if v else 0 for v in df.get("成交量", [0]*len(dates))],
                        "amount": [float(v) if v else 0 for v in df.get("成交额", [0]*len(dates))],
                    }
                    return result
        except Exception:
            pass
        return None

    # Build result dict with numpy arrays
    import numpy as np
    dates, opens, highs, lows, closes, volumes, amounts, pes, pcts = [], [], [], [], [], [], [], [], []
    for r in rows:
        try:
            dates.append(str(r[0]))
            opens.append(float(r[1]))
            highs.append(float(r[2]))
            lows.append(float(r[3]))
            closes.append(float(r[4]))
            volumes.append(float(r[5]) if r[5] else 0)
            amounts.append(float(r[6]) if r[6] else 0)
            pes.append(float(r[7]) if r[7] else None)
            pcts.append(float(r[8]) if r[8] else 0)
        except (ValueError, IndexError):
            continue

    return {
        "symbol": symbol,
        "dates": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "amount": amounts,
        "pe": pes,
        "pct_chg": pcts,
    }
