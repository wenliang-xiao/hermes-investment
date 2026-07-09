"""Tests for LayerStatus — 六层聚合器"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.layer_status import LayerStatus


class TestLayerStatus:
    def test_l1_macro(self):
        ls = LayerStatus()
        macro = {"dual_gate": {"macro": "绿", "trend": "黄"}, "quadrant": "扩张期", "trend_temp": "温"}
        result = ls._l1_macro(macro)
        assert result["dual_gate"]["macro"] == "绿"
        assert result["quadrant"] == "扩张期"

    def test_l1_default(self):
        ls = LayerStatus()
        result = ls._l1_macro(None)
        assert result["dual_gate"]["macro"] == "?"
        assert result["quadrant"] == "未知"

    def test_l5_normal(self):
        ls = LayerStatus()
        pos = [{"market_value": 1000, "entry_price": 10, "current_price": 12}]
        result = ls._l5_risk(pos)
        assert result["status"] == "normal"
        assert result["triggered_stops"] == 0

    def test_l5_warning(self):
        ls = LayerStatus()
        pos = [{"market_value": 800, "entry_price": 10, "current_price": 9.1}]
        result = ls._l5_risk(pos)
        assert result["status"] in ("normal", "warning")

    def test_l6_discipline(self):
        ls = LayerStatus(weekly_trade_limit=3)
        result = ls._l6_discipline(["trade1", "trade2"])
        assert result["weekly_trades"] == 2
        assert result["over_limit"] is False

    def test_l6_over_limit(self):
        ls = LayerStatus(weekly_trade_limit=3)
        result = ls._l6_discipline(["t1", "t2", "t3", "t4"])
        assert result["over_limit"] is True

    def test_get_all(self):
        ls = LayerStatus()
        result = ls.get_all()
        assert "l1_macro" in result
        assert "l5_risk" in result
        assert "l6_discipline" in result
        assert result["l5_risk"]["status"] == "normal"
