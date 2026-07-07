"""
data/data_router.py — 统一数据路由

从 xalpha._get_daily() 借鉴的 prefix-based dispatch 模式。
自动识别代码前缀/后缀，分发到正确的数据源。

用法:
    from data.data_router import get_history, get_rt

路由规则:
    .HK 结尾       → yfinance (港股)
    ^ 开头          → yfinance (指数/美债收益率)
    CL=/GC=/HG=    → AKShare (期货)
    全数字(6位)    → baostock (A股+ETF，含51/15/16/159开头)
    已知短代码     → yfinance (美股/美ETF)
    其他           → yfinance (默认)
"""
from __future__ import annotations
from pathlib import Path
import pickle, time, os
from functools import wraps
from typing import Optional

_DATA_DIR = Path(__file__).parent.parent / "data" / "cache"
_DATA_DIR.mkdir(parents=True, exist_ok=True)


# ── cachedio: 透明数据缓存装饰器 (从 xalpha.cachedio 借鉴) ──
def cachedio(ttl_hours: int = 24):
    """缓存装饰器：缓存函数返回结果到本地 pickle 文件。

    缓存键: {func_name}_{arg_hash}.pkl
    用法:
        @cachedio(ttl_hours=48)
        def fetch_data(symbol, days):
            ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key from function name and args
            key_parts = [func.__name__] + [str(a) for a in args] + [f"{k}={v}" for k, v in sorted(kwargs.items())]
            cache_name = "_".join(key_parts).replace(".", "_").replace("=", "_")[:200]
            cache_path = _DATA_DIR / f"{cache_name}.pkl"

            # Check cache
            if cache_path.exists():
                age = time.time() - cache_path.stat().st_mtime
                if age < ttl_hours * 3600:
                    with open(cache_path, "rb") as f:
                        return pickle.load(f)

            # Fetch
            result = func(*args, **kwargs)
            if result is not None and not (isinstance(result, (list, dict)) and len(result) == 0):
                with open(cache_path, "wb") as f:
                    pickle.dump(result, f)
            return result
        return wrapper
    return decorator


# ── 符号映射（yfinance 兼容） ──
_SYMBOL_MAP = {
    "BRK.B": "BRK-B",      # yfinance uses hyphen, not dot
    "DXY": "DX-Y.NYB",     # ICE US Dollar Index
}

def _resolve_symbol(symbol: str) -> str:
    return _SYMBOL_MAP.get(symbol, symbol)


# ── 数据源探测 ──
def _detect_source(symbol: str) -> str:
    """自动识别代码对应的数据源

    Returns: "baostock" | "yfinance" | "akshare_futures"
    """
    # 港股
    if symbol.endswith(".HK"):
        return "yfinance"

    # 指数/美债收益率
    if symbol.startswith("^") or symbol in ("DXY",):
        return "yfinance"

    # 期货 (AKShare) — 但排除 FX 汇率
    if "=" in symbol and "CNY" not in symbol and "USD" not in symbol:
        return "akshare_futures"

    # A股 (6位数字，含ETF — baostock 统一获取 A股+ETF)
    if symbol.isdigit() and len(symbol) == 6:
        return "baostock"

    # 已知美股/美ETF短代码
    us_known = {
        "AMD","AMZN","ANET","AVGO","BRK.B","COHR","COST","GEV",
        "GOOGL","JPM","LLY","META","MSFT","MU","NVDA","TSM","VST","XOM",
        "GDX","GLD","IEF","SLV","TIP","TLT","XLP","XLU",
    }
    if symbol in us_known:
        return "yfinance"

    # 默认 yfinance
    return "yfinance"


# ── 核心函数 ──

@cachedio(ttl_hours=720)  # 30天缓存
def get_history(symbol: str, days: int = 1200) -> Optional[dict]:
    """获取历史日线数据

    Args:
        symbol: 代码 (如 "300502", "0700.HK", "NVDA")
        days: 需要的数据天数

    Returns:
        dict with keys: dates, open, high, low, close, volume
        或 None (数据不可得)
    """
    symbol = _resolve_symbol(symbol)
    source = _detect_source(symbol)
    if source == "baostock":
        from data.sources.baostock_source import get_history_a
        return get_history_a(symbol, days)
    elif source == "yfinance":
        from data.sources.yahoo_source import get_history_yahoo
        return get_history_yahoo(symbol, days)
    elif source == "akshare_futures":
        from data.sources.akshare_source import get_history_futures
        return get_history_futures(symbol, days)
    return None


def get_rt(symbol: str) -> Optional[dict]:
    """获取实时行情

    Returns dict:
        symbol, name, price, change_pct, volume, amount, turnover_rate, pe
    """
    symbol = _resolve_symbol(symbol)
    source = _detect_source(symbol)
    if source == "baostock":
        # A股用东财实时
        from data.sources.akshare_source import get_rt_em
        return get_rt_em(symbol)
    elif source == "yfinance":
        from data.sources.yahoo_source import get_rt_yahoo
        return get_rt_yahoo(symbol)
    elif source == "akshare_futures":
        from data.sources.akshare_source import get_rt_futures
        return get_rt_futures(symbol)
    return None


def get_rt_safe(symbol: str) -> Optional[dict]:
    """带双源交叉验证的实时行情 (参考 xalpha get_rt double_check)

    A股: 东财 primary + 新浪 secondary, 偏差 >0.5% 报错
    港美股: yfinance primary (无交叉)
    """
    r1 = get_rt(symbol)
    if r1 is None:
        return None

    source = _detect_source(symbol)
    if source == "baostock":
        try:
            from data.sources.akshare_source import get_rt_sina
            r2 = get_rt_sina(symbol)
            if r2 and abs(r1["price"] / r2["price"] - 1) > 0.005:
                print(f"WARN: price mismatch for {symbol}: {r1['price']} vs {r2['price']}")
        except Exception:
            pass

    return r1


def get_cache_info() -> dict:
    """返回缓存统计信息"""
    files = list(_DATA_DIR.glob("*.pkl"))
    total_bytes = sum(f.stat().st_size for f in files)
    return {
        "cache_dir": str(_DATA_DIR),
        "file_count": len(files),
        "total_size_mb": round(total_bytes / 1024 / 1024, 2),
    }
