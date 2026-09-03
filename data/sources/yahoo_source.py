"""
data/sources/yahoo_source.py — 港美股/指数数据源

包装 yfinance，提供港美股+指数+美ETF的历史和实时数据。

可靠性说明（2026-08-13 加固）：
  yfinance/Yahoo 的 origin 后端经常返回瞬时的 Cloudflare 5xx（502 Bad Gateway /
  429 Too Many Requests / 503）。这些是瞬态错误，重试即可恢复，但若不重试会直接
  打到上层 cron 导致整批失败。本模块所有 yfinance 调用统一走 `_with_retry`，
  采用指数退避 + 抖动（backoff）自动重试，只在多次重试均失败后才向上抛。
"""
from __future__ import annotations

import time
import random
import logging

logger = logging.getLogger(__name__)

# 瞬态 HTTP 状态码：这些都应该重试
_TRANSIENT_STATUS = {429, 500, 502, 503, 504}

_YA_DEFAULT_RETRIES = 4
_YA_BASE_DELAY = 2.0          # 秒，首次退避基准
_YA_MAX_DELAY = 30.0          # 最大退避上限


def _is_transient_error(exc: BaseException) -> bool:
    """判断异常是否为可重试的瞬态错误（Cloudflare 5xx / 限频 / 网络抖动）。"""
    if type(exc).__name__ == "YFRateLimitError":
        return True
    if type(exc).__name__ == "YFOptionalParamError":
        return False
    txt = str(exc).lower()
    if any(errm in txt for errm in ("502", "503", "504", "500")):
        return True
    if "429" in txt or "rate limit" in txt or "too many requests" in txt:
        return True
    if "bad gateway" in txt or "cloudflare" in txt or "origin" in txt:
        return True
    # 网络层瞬态错误
    if any(errm in txt for errm in ("timed out", "timeout", "connection reset",
                                    "connection refused", "temporarily unavailable")):
        return True
    return False


def _with_retry(fn, retries: int = _YA_DEFAULT_RETRIES,
                base_delay: float = _YA_BASE_DELAY,
                max_delay: float = _YA_MAX_DELAY):
    """指数退避 + 抖动重试包装器。

    Args:
        fn: 无参可调用对象（yfinance 调用闭包）。
        retries: 总尝试次数（含首次）。默认 4 次。
        base_delay: 首次退避基础秒数。
        max_delay: 退避上限秒数。
    Returns:
        fn() 的返回值；若重试耗尽则重新抛出最后一次异常。
    """
    attempt = 0
    last_exc = None
    while attempt < retries:
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - 需要捕获所有潜在瞬态错误
            attempt += 1
            last_exc = exc
            if not _is_transient_error(exc):
                raise
            if attempt >= retries:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1))) * \
                (0.7 + 0.6 * random.random())   # 抖动 ±30%
            logger.warning(
                f"[yahoo] 瞬态错误({exc}) 重试 {attempt}/{retries}, sleep={delay:.1f}s")
            time.sleep(delay)
    raise last_exc


def get_history_yahoo(symbol: str, days: int = 1200):
    """拉取港美股/ETF/指数历史日线（带 502/429/5xx 自动重试）。"""
    import yfinance as yf

    from datetime import datetime, timedelta

    period_days = int(days * 1.5)
    start = (datetime.now() - timedelta(days=period_days)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")

    def _fetch():
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start, end=end)
        return df

    try:
        df = _with_retry(_fetch)
    except Exception as e:
        logger.error(f"  yfinance history error for {symbol} (retries exhausted): {e}")
        return None

    if df is None or df.empty:
        return None

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
    amounts = [c * v for c, v in zip(result["close"], result["volume"])]
    result["amount"] = amounts
    result["pct_chg"] = [0.0] * len(dates)

    return result


def get_rt_yahoo(symbol: str):
    """获取港美股实时行情（带 502/429/5xx 自动重试）。"""
    import yfinance as yf

    def _fetch():
        ticker = yf.Ticker(symbol)
        return ticker.info or {}

    try:
        info = _with_retry(_fetch)
    except Exception as e:
        logger.error(f"  yfinance rt error for {symbol} (retries exhausted): {e}")
        return None

    price = info.get("currentPrice") or info.get("regularMarketPrice") or \
        info.get("previousClose", 0)
    prev_close = info.get("previousClose", price)
    change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
    volume = info.get("volume") or info.get("regularMarketVolume", 0)
    pe = info.get("trailingPE") or info.get("forwardPE") or info.get("peRatio")

    return {
        "symbol": symbol,
        "name": info.get("shortName") or info.get("longName") or symbol,
        "price": price,
        "change_pct": round(change_pct, 2),
        "volume": volume,
        "pe": pe,
        "source": "yfinance",
    }
