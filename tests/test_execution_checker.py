"""Tests for ExecutionChecker — 建仓6查 + TrailStop"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.execution_checker import ExecutionChecker


class TestBuildChecklist:
    def test_all_passed(self):
        """优秀标的 → 建仓6查全过"""
        checker = ExecutionChecker()
        score = {
            "composite": 0.72,
            "scores": {"quality": 0.82, "momentum": 0.65, "value": 0.30},
        }
        macro = {"dual_gate": {"macro": "绿", "trend": "黄"}, "quadrant": "扩张期"}
        result = checker.check("600519", score_data=score, macro_state=macro)
        assert result["symbol"] == "600519"
        assert "build_checklist" in result
        cl = result["build_checklist"]
        assert "dual_gate_open" in cl
        assert "macro_ok" in cl
        assert "technical_ok" in cl
        assert "quality_gate" in cl
        assert cl["dual_gate_open"]["status"] is True
        assert cl["macro_ok"]["status"] is True

    def test_weak_stock_blocked(self):
        """弱标的 → 大部分检查不通过"""
        checker = ExecutionChecker()
        score = {"composite": 0.35, "scores": {"quality": 0.30, "momentum": 0.25}}
        macro = {"dual_gate": {"macro": "红", "trend": "红"}, "quadrant": "衰退期"}
        result = checker.check("000001", score_data=score, macro_state=macro)
        cl = result["build_checklist"]
        assert cl["dual_gate_open"]["status"] is False
        assert cl["macro_ok"]["status"] is False
        assert result["action"] == "WAIT"

    def test_no_score_data(self):
        """无评分 → 应该用默认值"""
        checker = ExecutionChecker()
        result = checker.check("600000", score_data=None, macro_state=None)
        assert result["action"] in ("BUY", "WAIT")
        assert "build_checklist" in result


class TestTrailStop:
    def test_profit_high_bucket(self):
        """盈利≥30% → 峰值×0.88"""
        pos = {"entry_price": 100, "current_price": 140, "quantity": 100}
        pos["_peak_price"] = 150
        checker = ExecutionChecker()
        result = checker.check("TEST", position=pos)
        trail = result["trail_stop"]
        assert trail["bucket"] == "盈利≥30%"
        assert trail["stop_price"] == round(150 * 0.88, 2)
        assert trail["status"] == "warning"  # distance=5.7% < 8% warning threshold

    def test_profit_med_bucket(self):
        """盈利10-30% → 峰值×0.85"""
        pos = {"entry_price": 100, "current_price": 120, "quantity": 100}
        pos["_peak_price"] = 125
        checker = ExecutionChecker()
        result = checker.check("TEST", position=pos)
        trail = result["trail_stop"]
        assert trail["bucket"] == "盈利10-30%"
        assert trail["status"] == "safe"

    def test_triggered(self):
        """当前价≤止损价 → triggered"""
        pos = {"entry_price": 100, "current_price": 82, "quantity": 100}
        pos["_peak_price"] = 100
        checker = ExecutionChecker()
        result = checker.check("TEST", position=pos)
        trail = result["trail_stop"]
        assert trail["status"] == "triggered"
        assert result["action"] == "SELL"
        assert result["action_confidence"] >= 0.85

    def test_warning(self):
        """距离止损<8% → warning"""
        pos = {"entry_price": 100, "current_price": 95, "quantity": 100}
        pos["_peak_price"] = 100
        checker = ExecutionChecker()
        result = checker.check("TEST", position=pos)
        trail = result["trail_stop"]
        # 亏损→成本×0.92=92, 当前95, 距离=(95-92)/95=3.1% < 8% → warning
        assert trail["status"] in ("warning", "critical")

    def test_no_position(self):
        """无持仓 → 不应有trail_stop"""
        checker = ExecutionChecker()
        result = checker.check("TEST", score_data={"composite": 0.5, "scores": {}})
        assert "trail_stop" not in result
        assert "build_checklist" in result


class TestRebalance:
    def test_calc_rebalance(self):
        checker = ExecutionChecker()
        target = {"A股": 25, "ETF": 20, "债券": 10, "黄金": 15, "商品": 10}
        actual = {"A股": 22, "ETF": 18, "债券": 12, "黄金": 15, "商品": 13}
        result = checker.calc_rebalance(target, actual)
        assert "deviations" in result
        assert "days_to_month_end" in result
        assert len(result["deviations"]) == 5
        # A股偏离=25-22=3%
        a_dev = [d for d in result["deviations"] if d["asset"] == "A股"][0]
        assert a_dev["diff"] == 3.0
        assert a_dev["target"] == 25
        assert a_dev["actual"] == 22
