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

# 并发安全 (2026-09-02 统一): baostock C 层全局单例, 多线程并发调用会共享句柄炸掉
# → 所有 C 层调用(login/query/next)必须串行化。
# 注意: data_layer.py 也有自己的 _BS_LOCK/_bs_login/_bs_logout — 若各自持锁则同一进程
# 内 C 层句柄并发无保护 → 协议流错乱 ("Error -3 decompressing" / 接收数据异常)。
# 因此这里**延迟复用 data_layer 的锁与 logout**, 保证全进程单锁单会话。
_BS_LOCK: "threading.RLock | None" = None

def _shared_lock():
    """统一到 data_layer 的全局锁 (进程内单锁, C 层句柄串行化)"""
    global _BS_LOCK
    if _BS_LOCK is None:
        from data.data_layer import _BS_LOCK as dl_lock
        _BS_LOCK = dl_lock
    return _BS_LOCK


def _shared_logout():
    """统一到 data_layer 的连接重置 (close socket 打断挂死 recv + 防协议污染)"""
    try:
        from data.data_layer import _bs_logout
        _bs_logout(force_close=True)
    except Exception as e:
        logger.warning(f"[baostock] 统一 logout 失败: {e}")

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
    """获取全局持久 baostock 会话 (进程内仅 login 一次, 与 data_layer 共享状态)。

    2026-09-02: 会话状态必须与 data_layer._bs_logged_in 同步 —
    超时后 _shared_logout() 会置 data_layer._bs_logged_in=False, 若本地仍缓存旧模块
    则下次调用不会重新 login → 连接已关但继续用 → 全部失败。
    """
    global _BS_MODULE
    if _BS_MODULE is not None:
        try:
            from data.data_layer import _bs_logged_in as dl_logged_in
            if dl_logged_in:
                return _BS_MODULE
        except Exception:
            return _BS_MODULE  # data_layer 不可用, 用本地缓存
    import baostock as bs
    from data.data_layer import _bs_login as dl_login
    dl_login()  # 统一走 data_layer 登录 (持共享锁 + 更新 _bs_logged_in)
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


def _bs_iter_results(rs, timeout: float = 15):
    """安全迭代 baostock 结果集 — worker 线程里 rs.next() 也可能挂死。

    用守护线程 + future.wait 实现线程级超时; 超时返回已读部分(可能为空)并重置连接。
    主线程场景直接迭代 (SIGALRM 由外层守护)。
    """
    if threading.current_thread() is threading.main_thread():
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        return rows

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
    rows: list = []
    def _drain():
        while rs.next():
            rows.append(rs.get_row_data())

    executor = ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(_drain)
    try:
        fut.result(timeout=timeout)
    except FutureTimeout:
        logger.warning(f"[baostock] 结果集读取超时(>{timeout:.0f}s) — 返回已读 {len(rows)} 行并重置连接")
        _shared_logout()  # close socket 打断挂死 recv + 防协议污染
    finally:
        executor.shutdown(wait=False)
    return rows


def _bs_login(bs):
    """带超时的 baostock 登录 (挂死时抛 BSTimeoutError)"""
    with _shared_lock(), _timeout_guard(BS_LOGIN_TIMEOUT):
        lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return lg


def _bs_query(bs, bs_code: str, fields: str, start_date: str, end_date: str):
    """带超时的 baostock 历史查询 (挂死时抛 BSTimeoutError)

    线程安全修复 (2026-09-02): SIGALRM 仅主线程可用; worker 线程里的 C 层 recv
    挂死无法被 SIGALRM 打断。这里用守护线程 + future.wait(timeout) 实现线程级超时:
    超时则放弃该查询(返回 None), 由调用方降级 akshare。
    """
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

    def _do_query():
        # 注意: _BS_LOCK 由外层 get_history_a 持有; 这里只执行 C 层调用
        return bs.query_history_k_data_plus(
            bs_code, fields,
            start_date=start_date, end_date=end_date,
            frequency="d", adjustflag="2"  # 前复权
        )

    # 主线程: SIGALRM 守护原逻辑
    if threading.current_thread() is threading.main_thread():
        with _timeout_guard(BS_CALL_TIMEOUT):
            return bs.query_history_k_data_plus(
                bs_code, fields,
                start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="2"
            )

    # worker 线程: 守护线程 + future timeout
    executor = ThreadPoolExecutor(max_workers=1)
    fut = executor.submit(_do_query)
    try:
        return fut.result(timeout=BS_CALL_TIMEOUT)
    except FutureTimeout:
        logger.warning(f"[baostock] {bs_code} worker线程查询超时(>{BS_CALL_TIMEOUT:.0f}s) — 放弃并重置连接")
        _shared_logout()  # close socket 打断挂死 recv + 防协议污染
        return None
    finally:
        executor.shutdown(wait=False)


def _bs_login_old():
    import baostock as bs
    lg = bs.login()
    if lg.error_code != "0":
        raise RuntimeError(f"baostock login failed: {lg.error_msg}")
    return bs


def _a_code(symbol: str) -> str:
    """Convert 6-digit code to baostock format (sh/sz.xxxxxx)

    交易所代码段 (2026-09 修正 16/15 归属):
      sz(深): 000/001/002/003 主板, 300/301 创业板, 159 深ETF, 15/16 深基金/LOF
      sh(沪): 600/601/603/605 主板, 688 科创板, 51/52/56/58 沪ETF, 50 沪LOF
    顺序注意: 更长前缀(如 159/688)必须在前匹配, 避免被短前缀截胡。
    """
    if symbol.startswith(("159", "688")):
        # 159深ETF → sz; 688科创板 → sh
        return f"sz.{symbol}" if symbol.startswith("159") else f"sh.{symbol}"
    if symbol.startswith(("00", "30", "15", "16", "301")):
        # 00 深主板, 30/301 创业板, 15/16 深基金/LOF
        return f"sz.{symbol}"
    if symbol.startswith(("60", "68", "51", "52", "56", "58", "50")):
        # 60 沪主板, 68 科创, 51/52/56/58 沪ETF, 50 沪LOF
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
    """baostock 主路径（带超时 + 持久会话）

    2026-09-02 重构: 锁只保护 C 层调用(query+读取), akshare fallback 一律在锁外 —
    akshare 是独立网络栈, 若在锁内挂死 = 锁永持 = 整批死锁。
    """
    import pandas as pd
    lock = _shared_lock()
    bs = _bs_session()  # 进程内仅 login 一次 (login 内部已持锁)
    bs_code = _a_code(symbol)

    fields = "date,open,high,low,close,volume,amount,peTTM,pctChg"

    from datetime import datetime, timedelta
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=int(days * 1.4))).strftime("%Y-%m-%d")

    rs = None
    rows = []
    with lock:  # 仅保护 C 层调用 (query + rs.next() 读取)
        rs = _bs_query(bs, bs_code, fields, start_date, end_date)
        if rs is None:
            logger.warning(f"[baostock] {symbol} 查询超时放弃 → 锁外降级 akshare")
        elif rs.error_code != "0":
            rs = None
        else:
            # 安全读取 (worker线程有守护超时; 主线程 SIGALRM)
            rows = _bs_iter_results(rs, timeout=BS_CALL_TIMEOUT)

    if rs is None:
        # worker线程超时放弃 → 降级 akshare (锁外)
        return _fallback_akshare_etf(symbol)

    if not rows:
        # baostock没数据 → AKShare ETF 历史 (锁外)
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
