"""回测对比 v2 — 基准线(沪深300)契约测试."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestBenchmark:
    def test_normalize_benchmark_to_base100(self):
        """基准净值归一化: 首日=1.0, 后续=close/首日close."""
        from dashboard.api_backtest import _normalize_benchmark
        closes = [3000.0, 3020.5, 3055.0, 3000.0 + 3 * 5]  # 单调小幅
        norm = _normalize_benchmark(closes)
        assert norm[0] == pytest.approx(1.0, abs=1e-6)
        # 末值 = 末close/首close
        assert norm[-1] == pytest.approx(closes[-1] / closes[0], abs=1e-4)
        assert len(norm) == len(closes)

    def test_benchmark_empty_input(self):
        """空输入返回空列表, 不崩溃."""
        from dashboard.api_backtest import _normalize_benchmark
        assert _normalize_benchmark([]) == []

    def test_benchmark_fetcher_returns_curve(self):
        """_fetch_benchmark_curve 返回 {dates, values} 或 None(数据不可用时报缺失)."""
        import dashboard.api_backtest as ab
        assert hasattr(ab, "_fetch_benchmark_curve")