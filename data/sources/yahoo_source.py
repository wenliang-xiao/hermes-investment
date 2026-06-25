"""
data/sources/yahoo_source.py — 港美股/指数数据源

包装 yfinance，提供港美股+指数+美ETF的历史和实时数据。
"""
from __future__ import annotations

def get_history_yahoo(symbol: str, days: int = 1200):
    """拉取港美股/ETF/指数历史日线"""
    import yfinance as yf
    import pandas as pd
    import numpy as np
    from datetime import datetime, timedelta

    # Calculate period
    period_days = int(days * 1.5)
    start = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end)
        if df is None or df.empty:
            return None

        # Normalize columns
        df = df.rename(columns={
            "Open": "open", "High": "high", "Low": "low",
            "Close": "close", "Volume": "volume",
        })

        dates = [d.strftime("%Y-%m-%d") for d in df.index.tolist()]
        result = {
            "symbol": symbol,
            "dates": dates,
            "open": df["open"].tolist(),
            "high": df["high"].tolist(),
            "low": df["low"].tolist(),
            "close": df["close"].tolist(),
            "volume": df["volume"].tolist(),
        }

        # Optional: amount = close * volume approximation
        amounts = [c * v for c, v in zip(result["close"], result["volume"])]
        result["amount"] = amounts
        result["pct_chg"] = [0.0] * len(dates)  # calculated on demand

        return result
    except Exception as e:
        print(f"  yfinance error for {symbol}: {e}")
        return None


def get_rt_yahoo(symbol: str):
    """获取港美股实时行情"""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.info or {}
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose", 0)
        prev_close = info.get("previousClose", price)
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
        volume = info.get("volume") or info.get("regularMarketVolume", 0)

        return {
            "symbol": symbol,
            "name": info.get("shortName") or info.get("longName") or symbol,
            "price": price,
            "change_pct": round(change_pct, 2),
            "volume": volume,
            "source": "yfinance",
        }
    except Exception:
        return None
