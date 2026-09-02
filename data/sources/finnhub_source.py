"""data/sources/finnhub_source.py — 美股数据源 (Finnhub 实时报价 + 历史 K 线)

架构: yfinance(免费兜底) + Finnhub(实时报价, 免费 60 次/分钟, 需 key)。
Finnhub 优先(实时、免费层慷慨), yfinance 兜底(零鉴权、美股历史最全)。

Finnhub 免费层: 60 次/分钟, 实时报价 + 新闻 + 基本面指标。
Key: 环境变量 FINNHUB_API_KEY。
"""
from __future__ import annotations

import os
import time
import datetime


def _api_key() -> str:
    return os.environ.get("FINNHUB_API_KEY", "")


def get_rt_finnhub(symbol: str):
    """美股实时报价 (Finnhub quote 端点)。symbol 如 AAPL。

    返回 {symbol, name, price, change_pct, high, low, open, prev_close}。
    无 key / 请求失败返回 None (由上层降级 yfinance)。
    """
    key = _api_key()
    if not key:
        return None
    import requests
    url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={key}"
    try:
        r = requests.get(url, timeout=5)
        d = r.json()
    except Exception:
        return None
    c = d.get("c")  # current price
    if not c:
        return None
    return {
        "symbol": symbol,
        "name": symbol,
        "price": float(c),
        "change_pct": round(float(d.get("dp", 0) or 0), 2),
        "high": float(d.get("h", 0) or 0),
        "low": float(d.get("l", 0) or 0),
        "open": float(d.get("o", 0) or 0),
        "prev_close": float(d.get("pc", 0) or 0),
        "source": "finnhub",
    }


def get_history_finnhub(symbol: str, days: int = 600):
    """美股历史日线 (Finnhub candle 端点)。symbol 如 AAPL。

    返回 {symbol, dates, open, high, low, close, volume}。
    无 key / 请求失败返回 None (由上层降级 yfinance)。
    """
    key = _api_key()
    if not key:
        return None
    import requests
    to = int(time.time())
    from_ = to - days * 86400
    url = (f"https://finnhub.io/api/v1/stock/candle?symbol={symbol}"
           f"&resolution=D&from={from_}&to={to}&token={key}")
    try:
        r = requests.get(url, timeout=10)
        d = r.json()
    except Exception:
        return None
    if d.get("s") != "ok" or not d.get("c"):
        return None
    dates = [datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d") for t in d["t"]]
    return {
        "symbol": symbol,
        "dates": dates,
        "open": d["o"],
        "high": d["h"],
        "low": d["l"],
        "close": d["c"],
        "volume": d["v"],
    }
