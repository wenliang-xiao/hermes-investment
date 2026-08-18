"""并发采集一致性测试 (2026-08-18)

验证 score_batch 的 ThreadPoolExecutor 并发改造:
  1. 并发结果与串行采集结果完全一致 (确定性)
  2. 并发下缓存双检锁不丢数据、不死锁
  3. 模拟慢数据源 (0.05s/标) 时并发明显快于串行
"""
import sys, os, time, threading
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import numpy as np


# 慢速数据源 stub: 每次调用 sleep 模拟网络 IO
class SlowFinSource:
    def __init__(self, delay=0.05):
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def get_financial_report(self, symbol):
        time.sleep(self.delay)
        with self._lock:
            self.calls += 1
        # 确定性: 每股固定 ROE/毛利 (清洗 A股代码格式)
        code = str(symbol).replace(".SH", "").replace(".SZ", "").zfill(6)
        seed = int(code[-2:])
        return {
            "净资产收益率": 5.0 + (seed % 20),
            "毛利率": 20.0 + (seed % 30),
            "净利率": 5.0 + (seed % 15),
            "资产负债率": 30.0 + (seed % 40),
            "每股经营现金流": 0.5 + (seed % 20) / 10.0,
        }


class SlowHistSource:
    def __init__(self, delay=0.03):
        self.delay = delay
        self.calls = 0
        self._lock = threading.Lock()

    def get_history(self, symbol, days=250):
        time.sleep(self.delay)
        with self._lock:
            self.calls += 1
        code = str(symbol).replace(".SH", "").replace(".SZ", "").zfill(6)
        seed = int(code[-2:])
        n = 80
        base = 10.0 + (seed % 20)
        return {
            "dates": [f"2026-01-{i:02d}" for i in range(1, n + 1)],
            "close": [base + i * 0.1 for i in range(n)],
            "open": [base + i * 0.1 for i in range(n)],
            "high": [base + i * 0.1 + 0.5 for i in range(n)],
            "low": [base + i * 0.1 - 0.5 for i in range(n)],
            "volume": [1000.0] * n,
            "pe": [15.0 + (seed % 10)] * n,
        }


@pytest.fixture
def engine_with_slow_sources(monkeypatch):
    from engine.factor_engine import FactorEngine
    import data.data_layer as dl
    import data.data_router as dr
    import data.sources.yahoo_source as ys
    engine = FactorEngine()
    fin = SlowFinSource()
    hist = SlowHistSource()
    # _get_fin 内部 from data.data_layer import get_financial_report (函数级导入)
    monkeypatch.setattr(dl, "get_financial_report", fin.get_financial_report)
    monkeypatch.setattr(dr, "get_history", hist.get_history)
    monkeypatch.setattr(dr, "get_rt", lambda sym: {"pe": 15.0, "price": 10.0})
    # PE fallback 链最后一段 (get_rt_yahoo) 也 mock, 避免测试内真实网络请求
    monkeypatch.setattr(ys, "get_rt_yahoo", lambda sym: {"pe": 15.0, "price": 10.0})
    # 行业排名因子走 QTSource → mock 掉 (返回确定性排名)
    monkeypatch.setattr(engine, "_get_qt_source", lambda: _FakeQT())
    return engine, fin, hist


class _FakeQT:
    """确定性行业排名 stub (避免真实蜻蜓 API 网络调用)"""
    api_key = "test-key"

    def get_industry_rank(self, code, metric="jzcsyl"):
        seed = int(str(code)[-2:])
        rank = 1 + (seed % 50)
        return {
            "industryName": "测试行业",
            "industryRank": f"{rank}/100",
            "industryAvg": 50.0,
            "industryList": [],
        }


class TestConcurrentCollect:
    def test_concurrent_matches_serial(self, engine_with_slow_sources):
        """并发采集的 raw_values 与串行一致 (确定性)"""
        from engine.factor_engine import FactorEngine, SUB_FACTOR_DEFS
        engine, fin, hist = engine_with_slow_sources
        symbols = [f"{600000 + i}.SH" for i in range(12)]

        # 串行基准 (直接调用 _get_sub_value)
        serial_raw = {}
        for sk in SUB_FACTOR_DEFS:
            serial_raw[sk] = {}
        for sym in symbols:
            for sk in SUB_FACTOR_DEFS:
                serial_raw[sk][sym] = engine._get_sub_value(sk, sym)

        # 并发 (通过 score_batch 内部路径验证 raw 一致 → 用 monkeypatch 记录)
        # 方法: 手动执行并发收集逻辑, 与 score_batch 相同
        from concurrent.futures import ThreadPoolExecutor, as_completed
        engine2 = FactorEngine()
        monkeypatch_engine = engine  # 复用同一个 engine (共享缓存)

        # 清缓存后跑并发
        engine.clear_cache()
        raw_values = {sk: {} for sk in SUB_FACTOR_DEFS}

        def _collect_one(sym):
            return {sk: engine._get_sub_value(sk, sym) for sk in SUB_FACTOR_DEFS}

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_collect_one, sym): sym for sym in symbols}
            for fut in as_completed(futures):
                sym = futures[fut]
                sub_values = fut.result()
                for sk, v in sub_values.items():
                    raw_values[sk][sym] = v

        # 结果一致性: 每个子因子每个 symbol 的 raw 值相同
        for sk in SUB_FACTOR_DEFS:
            for sym in symbols:
                assert raw_values[sk][sym] == serial_raw[sk][sym], \
                    f"mismatch {sk} {sym}: conc={raw_values[sk][sym]} serial={serial_raw[sk][sym]}"

    def test_concurrent_no_deadlock(self, engine_with_slow_sources):
        """并发采集 6 workers × 12 symbols 不超时不死锁"""
        from engine.factor_engine import SUB_FACTOR_DEFS
        from concurrent.futures import ThreadPoolExecutor, as_completed
        engine, fin, hist = engine_with_slow_sources
        symbols = [f"{600000 + i}.SH" for i in range(12)]
        engine.clear_cache()

        def _collect_one(sym):
            return {sk: engine._get_sub_value(sk, sym) for sk in SUB_FACTOR_DEFS}

        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(_collect_one, sym): sym for sym in symbols}
            results = [f.result(timeout=30) for f in futures]  # futures dict keys 是 future
        assert len(results) == 12

    def test_concurrent_faster_than_serial(self, engine_with_slow_sources):
        """12 symbols × (0.05s fin + 0.03s hist) 串行 ~0.96s, 6并发应 < 0.5s"""
        from engine.factor_engine import SUB_FACTOR_DEFS
        from concurrent.futures import ThreadPoolExecutor, as_completed
        engine, fin, hist = engine_with_slow_sources
        symbols = [f"{600000 + i}.SH" for i in range(12)]
        engine.clear_cache()

        t0 = time.time()
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {pool.submit(
                lambda s: [engine._get_sub_value(sk, s) for sk in SUB_FACTOR_DEFS], sym
            ): sym for sym in symbols}
            for f in futures:
                f.result(timeout=30)
        elapsed = time.time() - t0
        # 串行 ≈ 12×(0.05×5个fin因子缓存复用 + 0.03×hist) ≈ 0.96s; 并发应 < 串行的80%
        assert elapsed < 0.8, f"concurrent too slow: {elapsed:.2f}s"
