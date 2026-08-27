"""胜率口径测试 — 胜率应基于已平仓(卖出)交易数, 而非含买入的全部交易数."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestWinRate:
    def _p(self, win_count, trade_count, closed_count, equity=None):
        from engine.evaluator_fixed import _compute_metrics
        eq = equity or [1_000_000.0, 1_010_000.0, 1_005_000.0, 1_020_000.0]
        return _compute_metrics(eq, [], trade_count, win_count,
                                "test", {}, {}, len(eq),
                                closed_count=closed_count)

    def test_win_rate_uses_closed_count_not_buys(self):
        """买入104次+卖出98次(48盈) → 胜率应=48/98≈49%, 而非48/202≈24%."""
        m = self._p(win_count=48, trade_count=202, closed_count=98)
        assert m["win_rate_pct"] == pytest.approx(48 / 98 * 100, abs=0.1)

    def test_win_rate_zero_when_no_closed(self):
        """无平仓交易 → 胜率0, 不除零."""
        m = self._p(win_count=0, trade_count=14, closed_count=0)
        assert m["win_rate_pct"] == 0.0

    def test_win_rate_closed_count_defaults_to_trade_count(self):
        """未传 closed_count 时向后兼容: 用 trade_count (旧行为)."""
        m = self._p(win_count=5, trade_count=20, closed_count=None)
        assert m["win_rate_pct"] == pytest.approx(5 / 20 * 100, abs=0.1)