"""
data/sources/baostock_source.py — A股日线数据源

包装 baostock，提供 A 股+ETF 的历史日线。

P0 加固 (2026-08-18):
  - baostock 服务器偶发静默挂死 (TCP ESTABLISHED 但永不返回数据, Recv-Q=0)
  - 修复前: cron 每日 8:00/17:30 卡死在 bs.login()/query_history_k_data_plus()
    → 模拟盘数据永远停滞 (current_price=entry_price, pnl=0)
  - 修复: 每次 C 层调用外挂 SIGALRM 进程级硬超时, 超时抛 TimeoutError
    → 调用方降级 akshare ETF 历史, 保证 run_trading 永不卡死
"""
from __future__ import annotations
from pathlib import Path
import sys, os, json, signal, time, logging, threading
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# 并发安全 (2026-08-18): baostock C 层全局单例, 多线程并发调用会共享句柄炸掉
# → 所有 C 层调用(login/query/next)必须串行化
_BS_LOCK = threading.RLock()

_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# P0: baostock 单次 C 层调用硬超时 (秒)
BS_CALL_TIMEOUT = 15
BS_LOGIN_TIMEOUT = 10


class BSTimeoutError(TimeoutError):
    """baostock C 层调用挂死超时"""


# P0性能: baostock login 是网络握手(1-2s), 每次调用都 login+logout 浪费
# 52标×2次=104次握手=3-4分钟纯开销 → 模块级持久会话(进程内仅login一次)
_BS_MODULE = None  # 已 login 的 baostock 模块引用


def _bs_session() -> "module":
    """获取模块级持久 baostock 会话 (进程内仅 login 一次)"""
    global _BS_MODULE
    if _BS_MODULE is not None:
        return _BS_MODULE
    import baostock as bs
    _bs_login(bs)
    _BS_MODULE = bs
    return bs


@contextmanager
def _timeout_guard(seconds: float):
    """SIGALRM 超时守护上下文 — baostock C 层 socket recv 挂死时强制中断。

    已验证: SIGALRM 可打断 C 层阻塞 recv (114.94.20.42:10030 挂死场景 5s 内中断)。
    并发安全 (2026-08-18): SIGALRM 仅主线程可用 — worker 线程跳过 (依赖 _BS_LOCK 串行化
    + requests/socket 层超时兜底; 且 C 层调用已被 _BS_LOCK 保护, 不会并行进入)。
    """
    if seconds <= 0 or threading.current_thread() is not threading.main_thread():
        yield
        return

    def _handler(signum, frame):
        raise BSTimeoutError(f"baostock C 层调用超时(>{seconds:.0f}s) — 服务器静默挂死")

    old = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _bs_login(bs):
    """带超时的 baostock 登录 (挂死时抛 BSTimeoutError)"""
    with _BS_LOCK, _timeout_guard(BS_LOGIN_TIMEOUT):
        lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return lg


def _bs_query(bs, bs_code: str, fields: str, start_date: str, end_date: str):
    """带超时的 baostock 历史查询 (挂死时抛 BSTimeoutError)"""
    with _BS_LOCK, _timeout_guard(BS_CALL_TIMEOUT):
        rs = bs.query_history_k_data_plus(
            bs_code, fields,
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"  # 前复权
        )
    return rs


def _bs_login_old():
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return bs


def _a_code(symbol: str) -> str:
    """Convert 6-digit code to baostock format (sh/sz.xxxxxx)"""
    # 注意顺序: "159" 必须在 "15" 之前匹配 (深市 ETF 159xxx → sz.)
    if symbol.startswith(("159", "00", "30")):
        return f"sz.{symbol}"
    elif symbol.startswith(("60", "68", "51", "15", "16")):
        return f"sh.{symbol}"
    return symbol


def _fallback_akshare_etf(symbol: str):
    """AKShare ETF 历史降级 (baostock 无数据或挂死时)"""
    import akshare as ak
    from datetime import datetime as _dt
    df = ak.fund_etf_hist_em(symbol=symbol, period="daily",
                              start_date="20180101",
                              end_date=_dt.now().strftime("%Y%m%d"),
                              adjust="qfq")
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


def get_history_a(symbol: str, days: int = 1200):
    """拉取 A 股/ETF 历史日线 (baostock + 超时防护 + AKShare fallback)

    P0 加固: 任一步骤挂死(服务器静默)时由 SIGALRM 强制中断,
    返回 None → 调用方走降级/缓存, 保证主流程永不卡死。
    """
    try:
        return _get_history_a_bs(symbol, days)
    except BSTimeoutError as e:
        logger.warning(f"[baostock] {symbol} 挂死超时: {e} → 降级 akshare")
        try:
            return _fallback_akshare_etf(symbol)
        except Exception as fe:
            logger.warning(f"[baostock] {symbol} akshare 降级失败: {fe}")
            return None
    except Exception as e:
        logger.warning(f"[baostock] {symbol} 获取失败: {e} → 降级 akshare")
        try:
            return _fallback_akshare_etf(symbol)
        except Exception:
            return None


def _get_history_a_bs(symbol: str, days: int = 1200):
    """baostock 主路径（带超时 + 持久会话）"""
    import pandas as pd
    with _BS_LOCK:  # 保护 query + rs.next() 读取全流程 (C 层共享句柄)
        bs = _bs_session()  # 进程内仅 login 一次
        bs_code = _a_code(symbol)

        fields = "date,open,high,low,close,volume,amount,peTTM,pctChg"

        from datetime import datetime, timedelta
        end_date = datetime.now().strftime("%Y-%m-%d")
        start_date = (datetime.now() - timedelta(days=int(days * 1.4))).strftime("%Y-%m-%d")

        # Query (超时守护) — 持久会话不再每次 login/logout
        rs = _bs_query(bs, bs_code, fields, start_date, end_date)

        if rs.error_code != "0":
            return None

        rows = []
        while rs.next():
            rows.append(rs.get_row_data())

    if not rows:
        # baostock没数据 → AKShare ETF 历史
        return _fallback_akshare_etf(symbol)

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
