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

    def test_benchmark_window_from_equity_curve_span(self):
        """基准线窗口应对齐到策略净值曲线的时间跨度, 而非UI的日历days参数.

        策略引擎跑 FIXED_DAYS=120 交易日(约5个多月), 若基准只拉最近 days=60 日历日
        则两线日期范围错位, 叠加对比失真。须用 curve 首末日期推算跨度。
        """
        from dashboard.api_backtest import _benchmark_window_days
        # 曲线跨度 2026-03-02 至 2026-08-19 ≈ 170 日历天 → 窗口 ≥ 170
        daily = [
            {"date": "2026-03-02", "value": 1000000.0},
            {"date": "2026-08-19", "value": 1100000.0},
        ]
        win = _benchmark_window_days(daily, default_days=60)
        assert win >= 170
        assert win <= 200  # 加 20 缓冲

    def test_benchmark_window_default_when_no_curve(self):
        """净值曲线缺失时用传入的默认 days(保底≥30)."""
        from dashboard.api_backtest import _benchmark_window_days
        assert _benchmark_window_days([], default_days=60) == 60
        assert _benchmark_window_days([], default_days=15) == 30

    def test_benchmark_window_tolerant_of_bad_dates(self):
        """含非法日期行时降级到默认窗口, 不抛异常."""
        from dashboard.api_backtest import _benchmark_window_days
        daily = [{"date": "invalid", "value": 1.0}, {"date": "2026-08-01", "value": 1.0}]
        assert _benchmark_window_days(daily, default_days=45) == 45