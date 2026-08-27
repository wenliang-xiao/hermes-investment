"""Tests for event_risk_engine — 事件避险脉冲规则引擎契约。

契约：calc_event_risk(calendar, market_moves, hours) 输出
{level ∈ none/moderate/high/extreme, triggered_by, risk_adjust, captions}。
纯规则 + 可读 triggered_by（透明原则），阈值按共识保守取值。
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import engine.event_risk_engine as ere


def future_event(days_ahead: int = 1, risk_level: str = "high", **kw) -> dict:
    d = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    ev = {"date": d, "symbol": "NVDA", "type": "earnings",
          "title": "NVDA 财报", "risk_level": risk_level}
    ev.update(kw)
    return ev


def calendar(events=None, status: str = "ok") -> dict:
    return {"status": status, "events": events or [], "source": "manual_json",
            "data_age": "2026-08-27"}


class TestOutputShape:
    def test_returns_dict_with_required_keys(self):
        result = ere.calc_event_risk(calendar())
        for key in ("level", "triggered_by", "risk_adjust", "captions"):
            assert key in result, f"缺少字段 {key}"

    def test_level_is_valid_enum(self):
        assert ere.calc_event_risk(calendar())["level"] in (
            "none", "moderate", "high", "extreme")


class TestNoSignal:
    def test_no_event_no_move_is_none(self):
        result = ere.calc_event_risk(calendar(), market_moves={})
        assert result["level"] == "none"
        assert result["triggered_by"] == []


class TestEventTrigger:
    def test_high_event_within_48h(self):
        result = ere.calc_event_risk(calendar([future_event(risk_level="high")]))
        assert result["level"] in ("high", "extreme")
        assert result["triggered_by"], "应给出可读触发原因"

    def test_med_event_is_moderate(self):
        result = ere.calc_event_risk(calendar([future_event(risk_level="med")]))
        assert result["level"] == "moderate"

    def test_event_beyond_48h_not_triggered(self):
        result = ere.calc_event_risk(
            calendar([future_event(days_ahead=3, risk_level="high")]), hours=48)
        assert result["level"] == "none"  # 3 天后事件超出 48h 窗口


class TestMarketMoveTrigger:
    def test_gold_1d_spike(self):
        result = ere.calc_event_risk(calendar(), market_moves={"gold_1d_pct": 2.5})
        assert result["level"] in ("high", "extreme")
        assert any("黄金" in t for t in result["triggered_by"])

    def test_gold_5d_spike(self):
        result = ere.calc_event_risk(calendar(), market_moves={"gold_5d_pct": 5.5})
        assert result["level"] in ("high", "extreme")

    def test_gold_mild_move_not_triggered(self):
        result = ere.calc_event_risk(calendar(), market_moves={"gold_1d_pct": 1.0})
        assert result["level"] == "none"  # 1% < 2% 阈值，不触发


class TestCrossMarketResonance:
    def test_nasdaq_and_a_chain_both_drop(self):
        result = ere.calc_event_risk(
            calendar(), market_moves={"nasdaq_1d_pct": -3.5, "a_chain_1d_pct": -2.5})
        assert result["level"] in ("high", "extreme")
        assert any("共振" in t for t in result["triggered_by"])

    def test_nasdaq_drop_alone_not_triggered(self):
        result = ere.calc_event_risk(calendar(), market_moves={"nasdaq_1d_pct": -3.5})
        assert result["level"] == "none"  # 纳指单独跌不足成共振


class TestExtreme:
    def test_multiple_strong_triggers_is_extreme(self):
        result = ere.calc_event_risk(
            calendar([future_event(risk_level="high")]),
            market_moves={"gold_1d_pct": 2.5, "nasdaq_1d_pct": -3.5, "a_chain_1d_pct": -2.5})
        assert result["level"] == "extreme"

    def test_risk_adjust_higher_for_extreme_than_none(self):
        none = ere.calc_event_risk(calendar())
        extreme = ere.calc_event_risk(
            calendar([future_event(risk_level="high")]),
            market_moves={"gold_1d_pct": 2.5})
        assert extreme["risk_adjust"] > none["risk_adjust"]


class TestBuildEventAdvice:
    """事件脉冲 → 决策层建议（不接实盘，只产出建议动作）。"""

    def _advice(self, level):
        return ere.build_event_advice({"level": level, "triggered_by": ["x"]})

    def test_returns_required_keys(self):
        for key in ("action", "position_adjust", "block_buy", "havens", "level", "triggered_by"):
            assert key in self._advice("none"), f"缺少字段 {key}"

    def test_extreme_suggests_clear(self):
        a = self._advice("extreme")
        assert a["action"] == "清仓建议"
        assert a["position_adjust"] == 0.0
        assert a["block_buy"] is True

    def test_high_suggests_cut_to_0_3_and_block_buy(self):
        a = self._advice("high")
        assert a["action"] == "降仓建议"
        assert a["position_adjust"] == 0.3
        assert a["block_buy"] is True

    def test_moderate_controls_position_no_block(self):
        a = self._advice("moderate")
        assert a["action"] == "控制仓位"
        assert a["block_buy"] is False

    def test_none_keeps_position(self):
        a = self._advice("none")
        assert a["action"] == "维持"
        assert a["position_adjust"] == 1.0
        assert a["block_buy"] is False

    def test_havens_only_for_extreme_and_high(self):
        assert self._advice("extreme")["havens"]
        assert self._advice("high")["havens"]
        assert self._advice("moderate")["havens"] == []
        assert self._advice("none")["havens"] == []

    def test_triggered_by_passthrough(self):
        a = ere.build_event_advice({"level": "high", "triggered_by": ["黄金急拉", "NVDA财报"]})
        assert a["triggered_by"] == ["黄金急拉", "NVDA财报"]


class TestBuildShadowEntry:
    """影子运行记录条目（每日记录事件脉冲 + 建议 + 实际持仓快照）。"""

    def test_returns_required_keys(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "high", "triggered_by": ["x"]},
            {"action": "降仓建议", "position_adjust": 0.3, "havens": ["黄金ETF"]},
            {"total_value": 1000000, "position_count": 5, "realized_pnl": 1200})
        for key in ("date", "level", "triggered_by", "action", "position_adjust",
                    "havens", "actual_total_value", "actual_position_count", "actual_realized_pnl",
                    "hedged_pnl"):
            assert key in entry, f"缺少字段 {key}"

    def test_fields_passthrough(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "extreme", "triggered_by": ["a", "b"]},
            {"action": "清仓建议", "position_adjust": 0.0, "havens": ["黄金ETF", "白银"]},
            {"total_value": 1000000, "position_count": 5, "realized_pnl": 1200})
        assert entry["date"] == "2026-08-27"
        assert entry["level"] == "extreme"
        assert entry["triggered_by"] == ["a", "b"]
        assert entry["action"] == "清仓建议"
        assert entry["position_adjust"] == 0.0

    def test_actual_snapshot_mapped(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "none", "triggered_by": []},
            {"action": "维持", "position_adjust": 1.0, "havens": []},
            {"total_value": 950000, "position_count": 3, "realized_pnl": -500})
        assert entry["actual_total_value"] == 950000
        assert entry["actual_position_count"] == 3
        assert entry["actual_realized_pnl"] == -500

    def test_havens_and_triggered_by_are_lists(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "high", "triggered_by": ["x"]},
            {"action": "降仓建议", "position_adjust": 0.3, "havens": ["黄金ETF"]},
            {"total_value": 1, "position_count": 0, "realized_pnl": 0})
        assert isinstance(entry["havens"], list)
        assert isinstance(entry["triggered_by"], list)

    def test_hedged_pnl_scaled_by_position_adjust(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "high", "triggered_by": []},
            {"action": "降仓建议", "position_adjust": 0.3, "havens": []},
            {"total_value": 1, "position_count": 0, "realized_pnl": -500})
        assert entry["hedged_pnl"] == -150.0

    def test_hedged_pnl_equals_actual_when_none(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "none", "triggered_by": []},
            {"action": "维持", "position_adjust": 1.0, "havens": []},
            {"total_value": 1, "position_count": 0, "realized_pnl": -500})
        assert entry["hedged_pnl"] == -500.0

    def test_hedged_pnl_zero_when_extreme(self):
        entry = ere.build_shadow_entry(
            "2026-08-27", {"level": "extreme", "triggered_by": []},
            {"action": "清仓建议", "position_adjust": 0.0, "havens": []},
            {"total_value": 1, "position_count": 0, "realized_pnl": -500})
        assert entry["hedged_pnl"] == 0.0


class TestPctChange:
    def test_1d(self):
        assert ere._pct_change([100, 110], 1) == 10.0

    def test_5d(self):
        assert ere._pct_change([100, 102, 104, 106, 108, 110], 5) == 10.0

    def test_insufficient_data(self):
        assert ere._pct_change([100], 1) is None

    def test_zero_prev(self):
        assert ere._pct_change([0, 110], 1) is None


class TestGetMarketMoves:
    @pytest.fixture
    def mock_sources(self, monkeypatch):
        """mock yfinance（黄金/纳指）与腾讯行情（A股映射链），隔离网络。"""
        import yfinance as yf
        import pandas as pd

        class FakeTicker:
            def __init__(self, sym):
                self.sym = sym

            def history(self, period):
                return pd.DataFrame({"Close": [100, 102, 104, 106, 108, 110]},
                                    index=pd.date_range("2026-08-20", periods=6))

        monkeypatch.setattr(yf, "Ticker", FakeTicker)
        import data.sources.akshare_source as aks
        monkeypatch.setattr(aks, "get_rt_em", lambda sym: {"symbol": sym, "change_pct": -2.5})

    def test_returns_all_moves(self, mock_sources):
        moves = ere.get_market_moves()
        assert moves["gold_5d_pct"] == 10.0
        assert "gold_1d_pct" in moves
        assert "nasdaq_1d_pct" in moves
        assert moves["a_chain_1d_pct"] == -2.5

    def test_failure_returns_empty(self, monkeypatch):
        import yfinance as yf
        import data.sources.akshare_source as aks

        def boom(sym):
            raise RuntimeError("rate limited")

        monkeypatch.setattr(yf, "Ticker", boom)
        monkeypatch.setattr(aks, "get_rt_em", boom)
        assert ere.get_market_moves() == {}


class TestEventBlocksBuy:
    def test_high_blocks(self):
        assert ere.event_blocks_buy({"level": "high"}) is True

    def test_extreme_blocks(self):
        assert ere.event_blocks_buy({"level": "extreme"}) is True

    def test_moderate_not_block(self):
        assert ere.event_blocks_buy({"level": "moderate"}) is False

    def test_none_not_block(self):
        assert ere.event_blocks_buy({"level": "none"}) is False

    def test_missing_not_block(self):
        assert ere.event_blocks_buy(None) is False


class TestLoadLatestEventRisk:
    def test_returns_latest(self, tmp_path):
        import json

        p = tmp_path / "history.json"
        p.write_text(json.dumps([{"date": "a"}, {"date": "b"}]))
        assert ere.load_latest_event_risk(str(p)) == {"date": "b"}

    def test_missing_file_returns_none(self, tmp_path):
        assert ere.load_latest_event_risk(str(tmp_path / "none.json")) is None

    def test_empty_list_returns_none(self, tmp_path):
        import json

        p = tmp_path / "history.json"
        p.write_text(json.dumps([]))
        assert ere.load_latest_event_risk(str(p)) is None
