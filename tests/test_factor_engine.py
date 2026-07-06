"""Tests for analysis/factor_engine — initialization and edge cases."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from analysis.factor_engine import FactorEngine


class TestFactorEngineInit:
    def test_engine_creates(self):
        """引擎初始化不报错"""
        try:
            engine = FactorEngine()
            assert engine is not None
            assert hasattr(engine, "score_batch")
            assert hasattr(engine, "score_symbol")
        except ImportError as e:
            # 缺少数据依赖（baostock等）时跳过
            pytest.skip(f"Missing dependency: {e}")

    def test_engine_empty_batch(self):
        """空列表评分 → 空结果"""
        try:
            engine = FactorEngine()
            results = engine.score_batch([])
            assert results == []
        except ImportError:
            pytest.skip("Missing dependency")
