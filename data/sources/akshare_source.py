"""data/sources/akshare_source.py — A股实时行情 + 历史数据源

实时行情: **腾讯财经 API** (qt.gtimg.cn) — 比东财/Sina 快10倍且更稳定
历史数据: AKShare 标准接口 (期货/ETF/日线)

注意: EastMoney push2delay 和 Sina API 从本服务器不可达（Connection refused / timeout），
因此替换为腾讯 API。腾讯格式支持 A 股（sh/sz 前缀）和港股（hk 前缀）。
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import time

# ── 60s 内存缓存 ──
_rt_cache: dict[str, tuple[float, dict]] = {}


def _cached(symbol: str, fetcher, ttl: int = 60):
    now = time.time()
    cached = _rt_cache.get(symbol)
    if cached and (now - cached[0]) < ttl:
        return cached[1]
    result = fetcher(symbol)
    if result and result.get("price", 0) > 0:
        _rt_cache[symbol] = (now, result)
    return result


def get_rt_em(symbol: str):
    """A股实时行情 — 腾讯财经 API (主源)"""
    def _fetch(sym):
        try:
            import requests
            prefix = "sh" if sym.startswith(("60", "68")) else "sz"
            url = f"https://qt.gtimg.cn/q={prefix}{sym}"
            r = requests.get(url, timeout=5)
            text = r.text
            if '"' not in text:
                return None
            data = text.split('"')[1].split("~")
            if len(data) < 40:
                return None
            price = float(data[3]) if data[3] else 0
            if price <= 0:
                return None
            # volume 单位: 沪深主板/创业板是"手"(×100转股), 科创板(688/689)直接是"股"
            vol_raw = float(data[6]) if data[6] else 0
            volume = vol_raw if sym.startswith(("688", "689")) else vol_raw * 100
            return {
                "symbol": sym,
                "name": str(data[1]),
                "price": price,
                "change_pct": round(float(data[32]) if data[32] else 0, 2),
                "change": float(data[31]) if data[31] else 0,
                "volume": volume,
                "amount": float(data[37]) if data[37] else 0,
                "turnover_rate": float(data[38]) if data[38] else None,
                "pe": float(data[39]) if data[39] else None,
                "pb": float(data[46]) if data[46] else None,
                "source": "tencent",
            }
        except Exception as e:
            print(f"  Tencent RT error for {sym}: {e}")
            return None
    return _cached(symbol, _fetch)


def get_rt_sina(symbol: str):
    """新浪实时行情（降级备用）"""
    def _fetch(sym):
        try:
            import requests
            prefix = "sh" if sym.startswith(("60", "68")) else "sz"
            url = f"https://hq.sinajs.cn/list={prefix}{sym}"
            headers = {"Referer": "https://finance.sina.com.cn"}
            r = requests.get(url, headers=headers, timeout=3)
            text = r.text
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
                "symbol": sym,
                "name": name,
                "price": price,
                "change_pct": round(change_pct, 2),
                "volume": float(data[8]) if len(data) > 8 and data[8] else 0,
                "amount": float(data[9]) if len(data) > 9 and data[9] else 0,
                "source": "sina",
            }
        except Exception as e:
            print(f"  Sina RT error for {sym}: {e}")
            return None
    return _cached(symbol, _fetch)


def get_rt_futures(symbol: str):
    """期货实时行情 (AKShare)"""
    def _fetch(sym):
        try:
            import akshare as ak
            df = ak.futures_zh_minute_sina(sym)
            if df is not None and not df.empty:
                return {
                    "symbol": sym,
                    "price": float(df.iloc[-1]["close"]),
                }
        except Exception:
            pass
        return None
    return _cached(symbol, _fetch, ttl=120)


def get_history_futures(symbol: str, days: int = 600):
    """期货历史日线 (AKShare)"""
    try:
        import akshare as ak
        df = ak.futures_hist_em(symbol, period="daily", days=days)
        if df is None or df.empty:
            return None
        dates = df["日期"].tolist() if "日期" in df.columns else []
        if not dates:
            return None
        return {
            "symbol": symbol,
            "dates": [str(d) for d in dates],
            "open": [float(v) if v else 0 for v in df.get("开盘", [0] * len(dates))],
            "high": [float(v) if v else 0 for v in df.get("最高", [0] * len(dates))],
            "low": [float(v) if v else 0 for v in df.get("最低", [0] * len(dates))],
            "close": [float(v) if v else 0 for v in df.get("收盘", [0] * len(dates))],
            "volume": [float(v) if v else 0 for v in df.get("成交量", [0] * len(dates))],
        }
    except Exception:
        return None


def get_history_etf(symbol: str, days: int = 600):
    """ETF历史 (AKShare)

    主用新浪源 fund_etf_hist_sina (需 sh/sz 前缀, 快且稳)。
    东财 fund_etf_hist_em 作为 fallback (2026-09 起东财 hist 接口常被 RemoteDisconnected 限流)。
    """
    import akshare as ak
    from datetime import datetime, timedelta

    # 加交易所前缀 (新浪要求 sh510300 / sz159915)
    if symbol.isdigit() and len(symbol) == 6:
        if symbol.startswith(("159", "00", "30")):
            prefixed = f"sz{symbol}"
        else:
            prefixed = f"sh{symbol}"
    else:
        prefixed = symbol

    # 1) 新浪源主路径
    try:
        df = ak.fund_etf_hist_sina(symbol=prefixed)
        if df is not None and not df.empty and "date" in df.columns and "close" in df.columns:
            df = df.tail(days)
            dates = df["date"].tolist()
            if dates:
                return {
                    "symbol": symbol,
                    "dates": [str(d) for d in dates],
                    "open": [float(v) if v else 0 for v in df.get("open", [0] * len(dates))],
                    "high": [float(v) if v else 0 for v in df.get("high", [0] * len(dates))],
                    "low": [float(v) if v else 0 for v in df.get("low", [0] * len(dates))],
                    "close": [float(v) if v else 0 for v in df.get("close", [0] * len(dates))],
                    "volume": [float(v) if v else 0 for v in df.get("volume", [0] * len(dates))],
                }
    except Exception:
        pass

    # 2) 东财源 fallback
    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
    try:
        df = ak.fund_etf_hist_em(
            symbol=symbol, period="daily",
            start_date=start, end_date=end, adjust="qfq"
        )
        if df is None or df.empty:
            return None
        dates = df["日期"].tolist() if "日期" in df.columns else []
        if not dates:
            return None
        return {
            "symbol": symbol,
            "dates": [str(d) for d in dates],
            "open": [float(v) if v else 0 for v in df.get("开盘", [0] * len(dates))],
            "high": [float(v) if v else 0 for v in df.get("最高", [0] * len(dates))],
            "low": [float(v) if v else 0 for v in df.get("最低", [0] * len(dates))],
            "close": [float(v) if v else 0 for v in df.get("收盘", [0] * len(dates))],
            "volume": [float(v) if v else 0 for v in df.get("成交量", [0] * len(dates))],
            "amount": [float(v) if v else 0 for v in df.get("成交额", [0] * len(dates))],
        }
    except Exception:
        return None

def get_history_hk(symbol: str, days: int = 600):
    """港股历史日线(腾讯 ifzq, 零鉴权)。symbol 如 0700.HK。

    返回 {symbol, dates, open, close, high, low, volume}。
    注意 ifzq 字段顺序是 [date, open, close, high, low, volume](close 在第3位)。
    """
    import requests
    code = symbol.replace(".HK", "").zfill(5)
    url = (f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
           f"?param=hk{code},day,,,{days},qfq")
    try:
        r = requests.get(url, timeout=10)
        d = r.json()
        node = (d.get("data") or {}).get(f"hk{code}") or {}
        klines = node.get("qfqday") or node.get("day") or []
    except Exception:
        return None
    if not klines:
        return None

    dates, opens, closes, highs, lows, volumes = [], [], [], [], [], []
    for k in klines:
        if len(k) < 6:
            continue
        dates.append(str(k[0]))
        opens.append(float(k[1]))
        closes.append(float(k[2]))
        highs.append(float(k[3]))
        lows.append(float(k[4]))
        volumes.append(float(k[5]))
    return {"symbol": symbol, "dates": dates, "open": opens, "close": closes,
            "high": highs, "low": lows, "volume": volumes}


def get_rt_hk(symbol: str):
    """港股实时快照(腾讯 qt.gtimg, 零鉴权)。symbol 如 0700.HK。

    港股字段布局与 A 股不同: [3]=现价 [32]=涨跌幅% [39]=PE, [6]=成交量(股)。
    """
    import requests
    code = symbol.replace(".HK", "").zfill(5)
    url = f"https://qt.gtimg.cn/q=hk{code}"
    try:
        r = requests.get(url, timeout=5)
        text = r.content.decode("gbk", errors="replace")
    except Exception:
        return None
    data = text.split('"')[1].split("~") if '"' in text else []
    if len(data) < 40:
        return None
    price = float(data[3]) if data[3] else 0
    if price <= 0:
        return None
    return {
        "symbol": symbol,
        "name": str(data[1]),
        "price": price,
        "change_pct": round(float(data[32]) if data[32] else 0, 2),
        "volume": float(data[6]) if data[6] else 0,
        "amount": float(data[37]) if data[37] else 0,
        "pe": float(data[39]) if data[39] else None,
        "source": "tencent",
    }
