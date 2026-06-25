"""
data/sources/akshare_source.py — AKShare 数据源

东财实时行情 + 期货历史 + 新浪交叉验证。
"""
from __future__ import annotations
import pandas as pd
import numpy as np


def get_rt_em(symbol: str):
    """东财实时行情 (AKShare stock_zh_a_spot_em) — 带新浪回退"""
    try:
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            return get_rt_sina(symbol)

        code_col = [c for c in df.columns if "代码" in c or "code" in c.lower()]
        if not code_col:
            return get_rt_sina(symbol)
        row = df[df[code_col[0]].astype(str) == symbol]
        if row.empty:
            return get_rt_sina(symbol)
        row = row.iloc[0]

        price = float(row.get("最新价", 0)) if "最新价" in row else 0
        prev = float(row.get("昨收", price)) if "昨收" in row else price
        change_pct = ((price - prev) / prev * 100) if prev else 0

        return {
            "symbol": symbol,
            "name": str(row.get("名称", "")),
            "price": price,
            "change_pct": round(change_pct, 2),
            "volume": float(row.get("成交量", 0)),
            "amount": float(row.get("成交额", 0)),
            "turnover_rate": float(row.get("换手率", 0)),
            "pe": float(row.get("市盈率-动态", 0)) if row.get("市盈率-动态") else None,
            "source": "eastmoney",
        }
    except Exception as e:
        print(f"  EastMoney RT error for {symbol}: {e}")
        return None


def get_rt_sina(symbol: str):
    """新浪实时行情（用于交叉验证）

    新浪返回格式: "var hq_str_sh603259=\"药明康德,106.310,...
    """
    try:
        import requests
        prefix = "sh" if symbol.startswith(("60", "68")) else "sz"
        url = f"https://hq.sinajs.cn/list={prefix}{symbol}"
        headers = {"Referer": "https://finance.sina.com.cn"}
        r = requests.get(url, headers=headers, timeout=5)
        text = r.text

        # Parse: var hq_str_sh603259="name,open,prev_close,current,high,low,...
        if '"' not in text:
            return None
        data = text.split('"')[1].split(",")
        if len(data) < 4:
            return None

        name = data[0]
        price = float(data[3]) if data[3] else 0
        prev = float(data[2]) if len(data) > 2 and data[2] else price
        change_pct = ((price - prev) / prev * 100) if prev else 0

        return {
            "symbol": symbol,
            "name": name,
            "price": price,
            "change_pct": round(change_pct, 2),
            "source": "sina",
        }
    except Exception:
        return None


def get_history_futures(symbol: str, days: int = 1200):
    """期货历史日线 via AKShare"""
    try:
        import akshare as ak
        # Map symbol to AKShare futures symbol
        futures_map = {
            "CL=F": "CL",
            "GC=F": "GC",
            "HG=F": "HG",
        }
        fm = futures_map.get(symbol)
        if not fm:
            return None

        df = ak.futures_foreign_hist(symbol=fm)
        if df is None or df.empty:
            return None

        dates = df["date"].tolist()
        if not dates:
            return None

        result = {
            "symbol": symbol,
            "dates": [str(d) for d in dates],
            "open": [float(v) if v else 0 for v in df.get("open", [0] * len(dates))],
            "high": [float(v) if v else 0 for v in df.get("high", [0] * len(dates))],
            "low": [float(v) if v else 0 for v in df.get("low", [0] * len(dates))],
            "close": [float(v) if v else 0 for v in df.get("close", [0] * len(dates))],
            "volume": [float(v) if v else 0 for v in df.get("volume", [0] * len(dates))],
            "amount": [0] * len(dates),
        }
        return result
    except Exception as e:
        print(f"  futures history error for {symbol}: {e}")
        return None


def get_rt_futures(symbol: str):
    """期货实时行情"""
    try:
        import akshare as ak
        # Map symbol to AKShare futures symbol
        futures_map = {
            "CL=F": "CL",
            "GC=F": "GC",
            "HG=F": "HG",
        }
        fm = futures_map.get(symbol)
        if not fm:
            return None

        from datetime import datetime, timedelta
        df = ak.futures_foreign_hist(
            symbol=fm,
        )
        if df is None or df.empty:
            return None

        last = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else last
        change_pct = ((float(last.get("close", 0)) - float(prev.get("close", 0))) / float(prev.get("close", 0)) * 100) if float(prev.get("close", 0)) else 0

        return {
            "symbol": symbol,
            "name": fm,
            "price": float(last.get("close", 0)),
            "change_pct": round(change_pct, 2),
            "volume": float(last.get("volume", 0)),
            "source": "akshare",
        }
    except Exception:
        return None


def get_history_etf(symbol: str, days: int = 1200):
    """ETF历史日线 via AKShare fund_etf_hist_em（东财ETF行情）"""
    try:
        import akshare as ak
        from datetime import datetime, timedelta
        end = datetime.now()
        start = end - timedelta(days=int(days * 1.5))

        df = ak.fund_etf_hist_em(
            symbol=symbol,
            period="daily",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
            adjust="qfq",
        )
        if df is None or df.empty:
            return None

        dates = df.get("日期", [])
        if dates is None or len(dates) == 0:
            return None

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
    except Exception as e:
        print(f"  ETF history error for {symbol}: {e}")
        return None
