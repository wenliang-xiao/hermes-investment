"""Walk-Forward 对比 — API 透传 + 响应保留 cycle_details 契约测试."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestWalkForwardAPI:
    def test_custom_endpoint_accepts_walk_forward_param(self):
        """API 端点签名接受 walk_forward/cycles/test_days 参数."""
        from dashboard import api_backtest
        import inspect
        sig = inspect.signature(api_backtest.api_v2_backtest_custom)
        assert "walk_forward" in sig.parameters
        assert sig.parameters["walk_forward"].default is False
        assert "cycles" in sig.parameters
        assert "test_days" in sig.parameters

    def test_wf_result_helper_keeps_cycle_details(self):
        """_backtest_result_to_frontend 保留 extra.cycle_details 供前端展示周期表."""
        from dashboard.api_backtest import _backtest_result_to_frontend
        br = type("BR", (), {
            "strategy_name": "faceji", "final_value": 1_100_000.0,
            "initial_cash": 1_000_000.0, "trade_count": 23,
            "total_return_pct": 10.0, "win_rate_pct": 50.0,
            "max_drawdown_pct": 5.0, "sharpe_ratio": 1.5,
            "sortino_ratio": 1.2, "calmar_ratio": 2.0,
            "equity_curve": [{"date": "2026-01-01", "value": 1_000_000.0}],
            "trades": [],
        })()
        # 手动挂 extra
        br.extra = {"mode": "walk_forward",
                    "cycle_details": [{"cycle": 1, "return_pct": 8.0, "test_days": 63},
                                      {"cycle": 2, "return_pct": -3.0, "test_days": 63}]}
        out = _backtest_result_to_frontend(br, "faceji (面基)")
        assert out["extra"]["cycle_details"][0]["cycle"] == 1
        assert out["extra"]["mode"] == "walk_forward"

    def test_wf_result_no_cycle_details_safe(self):
        """非 WF 结果(无 cycle_details) 不崩溃."""
        from dashboard.api_backtest import _backtest_result_to_frontend
        br = type("BR", (), {
            "strategy_name": "faceji", "final_value": 1_100_000.0,
            "initial_cash": 1_000_000.0, "trade_count": 23,
            "total_return_pct": 10.0, "win_rate_pct": 50.0,
            "max_drawdown_pct": 5.0, "sharpe_ratio": 1.5,
            "sortino_ratio": 1.2, "calmar_ratio": 2.0,
            "equity_curve": [], "trades": [],
        })()
        br.extra = {}
        out = _backtest_result_to_frontend(br, "faceji (面基)")
        assert out["extra"] == {}