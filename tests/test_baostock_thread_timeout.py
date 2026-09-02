"""测试 baostock worker 线程挂死守护 (2026-09-02)。

背景: score_batch 线程池 (max_workers=3) 里 SIGALRM 超时守护失效,
baostock C 层 recv 挂死 → 整批永久阻塞 → cron 被 1800s/5400s 超时杀。

覆盖:
1. _bs_query 在 worker 线程对挂死的 query 返回 None (而非永久阻塞)
2. _bs_iter_results 对挂死的 rs.next() 返回已读部分 (而非永久阻塞)
3. 主线程路径不受影响 (走 SIGALRM 原逻辑)
"""
import sys
import os
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytestmark = pytest.mark.timeout(60)  # 覆盖全局 10s: 本测试需等待 BS_CALL_TIMEOUT=15s 超时


class _HangingRs:
    """模拟 baostock 挂死结果集: query 永久阻塞 / next() 永久阻塞"""
    def __init__(self, hang_on="query"):
        self.hang_on = hang_on
        self.error_code = "0"
        self._count = 0

    def query_history_k_data_plus(self, *a, **kw):
        if self.hang_on == "query":
            time.sleep(60)  # 模拟 C 层 recv 挂死
        return self

    def next(self):
        if self.hang_on == "next":
            time.sleep(60)  # 模拟读取挂死
        if self._count < 2:
            self._count += 1
            return True
        return False

    def get_row_data(self):
        return [f"r{self._count}", "1", "2", "3", "4", "5", "6", "7"]


def _run_in_worker(fn, budget: float = 20):
    """在非主线程执行 fn, 返回结果 (超时则抛异常)"""
    result = {}

    def _target():
        result["val"] = fn()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join(timeout=budget)
    assert not t.is_alive(), "worker 线程未在超时内返回 → 挂死未修复"
    return result["val"]


def test_bs_query_worker_thread_timeout_returns_none():
    """worker 线程: 挂死 query 应在 BS_CALL_TIMEOUT 内返回 None"""
    from data.sources.baostock_source import _bs_query

    bs = _HangingRs(hang_on="query")

    def _call():
        return _bs_query(bs, "sh.600000", "f", "2026-01-01", "2026-09-01")

    start = time.time()
    result = _run_in_worker(_call)
    elapsed = time.time() - start

    assert result is None
    assert elapsed < 19, f"应为快速降级, 实际 {elapsed:.1f}s"


def test_bs_iter_results_worker_thread_timeout_partial():
    """worker 线程: 挂死 rs.next() 应返回已读部分"""
    from data.sources.baostock_source import _bs_iter_results

    rs = _HangingRs(hang_on="next")  # 第一行就挂

    start = time.time()
    rows = _run_in_worker(lambda: _bs_iter_results(rs, timeout=1))
    elapsed = time.time() - start

    assert isinstance(rows, list)
    assert elapsed < 19, f"应快速返回部分行, 实际 {elapsed:.1f}s"


def test_bs_iter_results_worker_thread_normal():
    """worker 线程: 正常结果集完整读取 (不误伤)"""
    from data.sources.baostock_source import _bs_iter_results

    rs = _HangingRs(hang_on="none")

    rows = _run_in_worker(lambda: _bs_iter_results(rs, timeout=5))
    assert len(rows) == 2


def test_bs_query_main_thread_keeps_sigalrm():
    """主线程: _bs_query 仍走 SIGALRM 原逻辑 (快速返回)"""
    from data.sources.baostock_source import _bs_query

    class _OkRs:
        error_code = "0"
        def query_history_k_data_plus(self, *a, **kw):
            return self

    bs = _OkRs()
    # 主线程直接调用不应抛错
    result = _bs_query(bs, "sh.600000", "f", "2026-01-01", "2026-09-01")
    assert result is bs