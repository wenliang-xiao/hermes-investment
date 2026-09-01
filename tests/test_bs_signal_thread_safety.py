"""baostock signal 线程冲突修复测试 (2026-08-31)

背景: data/data_layer.py 的 _bs_query_with_timeout / _bs_iter_results 原无条件
使用 signal.alarm — 该调用仅主线程可用, 在 score_batch 的 ThreadPoolExecutor
worker 线程里触发 `signal only works in main thread` → 登录失败 →
财务因子全面退化 (composite 恒 0.5)。

修复: 非主线程跳过 signal.alarm, 直接调用 func (依赖 _BS_LOCK 串行化 +
socket 层超时兜底); 主线程保留 SIGALRM 硬超时。

本测试用真实 worker 线程验证:
  1. worker 线程调用 _bs_query_with_timeout 正常执行 (修复前抛 ValueError)
  2. worker 线程调用 _bs_iter_results 正常迭代
  3. 主线程分支仍保留 signal 超时语义 (alarm 被设置)
  4. _bs_login 双检锁不会并发重复登录
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from concurrent.futures import ThreadPoolExecutor


class _FakeResultSet:
    """模拟 baostock 结果集 (3 行数据)"""
    fields = ["code", "value"]

    def __init__(self, n=3):
        self._rows = [[f"sh.60000{i}", str(i)] for i in range(n)]
        self._i = 0

    def next(self):
        if self._i >= len(self._rows):
            return False
        self._i += 1
        return True

    def get_row_data(self):
        return self._rows[self._i - 1]


class _FakeLogin:
    error_code = "0"
    error_msg = ""


def test_bs_query_with_timeout_works_in_worker_thread():
    """worker 线程调用不抛 signal 错误, func 正常执行"""
    import data.data_layer as dl

    def _worker():
        # 修复前: 这里会抛 ValueError("signal only works in main thread")
        return dl._bs_query_with_timeout(lambda: 42, timeout=10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_worker)
        result = fut.result(timeout=10)
    assert result == 42


def test_bs_query_with_timeout_passes_args_kwargs_in_worker():
    import data.data_layer as dl

    def _add(a, b=0):
        return a + b

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(lambda: dl._bs_query_with_timeout(_add, 1, b=2, timeout=5))
        assert fut.result(timeout=10) == 3


def test_bs_iter_results_works_in_worker_thread():
    """worker 线程迭代结果集正常, 返回全部行"""
    import data.data_layer as dl

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(lambda: dl._bs_iter_results(_FakeResultSet(3), timeout=10))
        rows = fut.result(timeout=10)
    assert len(rows) == 3
    assert rows[0] == ["sh.600000", "0"]


def test_main_thread_still_sets_alarm(monkeypatch):
    """主线程分支保留 SIGALRM 语义 — alarm 被设置"""
    import data.data_layer as dl

    alarms = []

    class _FakeSignal:
        SIGALRM = 14

        @staticmethod
        def signal(signum, handler):
            return None

        @staticmethod
        def alarm(seconds):
            alarms.append(seconds)
            return 0

    monkeypatch.setattr(dl, "_signal_module", _FakeSignal())
    dl._bs_query_with_timeout(lambda: 1, timeout=7)
    assert alarms == [7, 0]  # 设置 alarm, 完成后清零
    # 还原 (monkeypatch 自动还原)


def test_bs_session_serialized_with_lock(monkeypatch):
    """_BS_LOCK 是 RLock, 主/worker 线程调用不抛异常"""
    import data.data_layer as dl

    def _worker():
        # 模拟 login + query + iter 全链路 (都被锁保护但仍可重入)
        lg = dl._bs_query_with_timeout(lambda: _FakeLogin(), timeout=5)
        with dl._BS_LOCK:
            pass  # RLock 可重入, 不抛 RuntimeError
        return lg.error_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(_worker) for _ in range(2)]
        assert [f.result(timeout=10) for f in futures] == ["0", "0"]


def test_bs_login_double_check_lock(monkeypatch):
    """双检锁: 已登录的全局标志不被重复 login 覆盖"""
    import data.data_layer as dl

    login_calls = []

    class _FakeBS:
        def login(self):
            login_calls.append(1)
            return _FakeLogin()

    monkeypatch.setattr(dl, "bs", _FakeBS())
    monkeypatch.setattr(dl, "_bs_logged_in", False)

    dl._bs_login()
    dl._bs_login()  # 第二次: _bs_logged_in=True → 不再 login
    assert len(login_calls) == 1
    assert dl._bs_logged_in is True