"""Regression tests for evaluator_fixed — baseline & import validation."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class TestEvaluatorFixedImport:
    def test_module_imports(self):
        """evaluator_fixed 模块可安全导入"""
        import engine.evaluator_fixed as ev
        assert hasattr(ev, "FIXED_UNIVERSE")
        assert len(ev.FIXED_UNIVERSE) >= 19

    def test_baseline_exists(self):
        """基线文件存在且可读"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "eval_cache", "baseline.json")
        if not os.path.exists(path):
            pytest.skip("No baseline file (CI)")
        import json
        with open(path) as f:
            baseline = json.load(f)
        assert "faceji" in baseline
        assert "sortino_ratio" in baseline["faceji"]

    def test_universe_has_valid_symbols(self):
        """FIXED_UNIVERSE 全部是6位数字（A股代码格式）"""
        import engine.evaluator_fixed as ev
        for entry in ev.FIXED_UNIVERSE:
            sym = entry["symbol"] if isinstance(entry, dict) else entry
            assert len(sym) == 6 and sym.isdigit(), f"{sym} 不是A股代码格式"
