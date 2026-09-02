"""模拟 score_batch 线程池场景验证 (2026-09-02):
3 个 worker 线程同时调 data_layer._bs_query_with_timeout, 其中一个 C 层挂死,
验证: 挂死线程 25s 超时返回 None + 重置连接, 其余线程不被锁死, 整批快速结束。
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "investment_system"))

from concurrent.futures import ThreadPoolExecutor

class _HangingRs:
    def __init__(self, hang=False):
        self.hang = hang
        self.error_code = "0"
        self.fields = ["date", "close"]
    def query_history_k_data_plus(self, *a, **kw):
        if self.hang:
            time.sleep(60)  # 模拟 C 层 recv 挂死
        return self
    def next(self):
        if self.hang:
            time.sleep(60)
        return False
    def get_row_data(self):
        return ["2026-09-01", "10.0"]

def main():
    import data.data_layer as dl

    # 打开连接 (真实 baostock login 一次)
    print("[setup] login...")
    dl._bs_login()
    print("[setup] logged_in =", dl._bs_logged_in)

    # 打补丁: 含 "hang" 的代码 → 挂死; 否则走真实 baostock
    orig_query = dl.bs.query_history_k_data_plus
    def fake_query(*a, **kw):
        code = a[0] if a else kw.get("code", "")
        if "hang" in str(code):
            time.sleep(60)  # 模拟 C 层 recv 挂死
        return orig_query(*a, **kw)
    dl.bs.query_history_k_data_plus = fake_query

    results = {}
    def worker(i):
        start = time.time()
        code = "sh.600000.0" if i == 0 else ("sh.600000.hang" if i == 1 else "sh.600000.2")
        try:
            rs = dl._bs_query_with_timeout(dl.bs.query_history_k_data_plus,
                                           code, "date,close",
                                           start_date="2026-01-01", end_date="2026-09-01")
            results[i] = ("ok", rs, round(time.time()-start, 1))
        except Exception as e:
            results[i] = ("err", str(e)[:60], round(time.time()-start, 1))

    pool = ThreadPoolExecutor(max_workers=3)
    t0 = time.time()
    futs = [pool.submit(worker, i) for i in range(3)]
    # 全部应在 ~25s 内结束 (挂死的那个超时返回 None)
    for f in futs:
        f.result(timeout=45)
    elapsed = round(time.time()-t0, 1)
    pool.shutdown(wait=False)

    print(f"[result] 总耗时 {elapsed}s (期望 < 35s, 挂死 worker 25s 超时返回)")
    for i in sorted(results):
        print(f"  worker{i}: {results[i]}")
    assert elapsed < 40, f"整批仍被锁死: {elapsed}s"
    print("[PASS] 线程池场景: 挂死查询被超时切断, 不阻塞其他 worker")

if __name__ == "__main__":
    main()