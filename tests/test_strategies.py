"""
Tests for strategies/ pure decision functions + factor_engine helpers.
Each strategy is a pure function: input dicts → output Signal list.
No IO, no state mutation — easy to unit test.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from strategies.base import Signal, PositionData, FacejiConfig, SilverQuantConfig, TradingAgentsConfig
from strategies import faceji, silverquant, tradingagents
from engine.factor_engine import score_to_signal, convert_v3_to_v4, convert_v4_to_v3


# ═══════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════

def make_tech(ma20=5, ma60=2, rsi=50, macd="⚪中性", tech_score=5.0):
    return {"ma20_dev": ma20, "ma60_dev": ma60, "rsi": rsi,
            "macd_signal": macd, "total_tech_score": tech_score}


# ═══════════════════════════════════════════════
# factor_engine helpers
# ═══════════════════════════════════════════════

class TestScoreToSignal:
    def test_strong_buy(self):
        """≥0.63 → 强买入"""
        name, label = score_to_signal(0.65)
        assert name == "STRONGBUY"
        assert "买入" in label

    def test_buy(self):
        """0.48-0.63 → 买入"""
        name, label = score_to_signal(0.50)
        assert name == "BUY"

    def test_hold(self):
        """0.35-0.48 → 持有"""
        name, label = score_to_signal(0.40)
        assert name == "HOLD"

    def test_sell(self):
        """0.25-0.35 → 卖出"""
        name, label = score_to_signal(0.30)
        assert name == "SELL"

    def test_strong_sell(self):
        """<0.25 → 强卖出"""
        name, label = score_to_signal(0.20)
        assert name == "STRONGSELL"

    def test_custom_thresholds(self):
        name, _ = score_to_signal(0.50, threshold_buy=0.60, threshold_sell=0.40)
        assert name == "HOLD"


class TestScoreConversion:
    def test_v3_to_v4_neutral(self):
        """5.0 → 0.444..."""
        assert convert_v3_to_v4(5.0) == pytest.approx(0.4444, rel=0.01)

    def test_v3_to_v4_max(self):
        assert convert_v3_to_v4(10.0) == 1.0

    def test_v3_to_v4_min(self):
        assert convert_v3_to_v4(1.0) == 0.0

    def test_v4_to_v3_roundtrip(self):
        for v3 in [1.0, 3.5, 5.0, 7.2, 10.0]:
            v4 = convert_v3_to_v4(v3)
            back = convert_v4_to_v3(v4)
            assert back == pytest.approx(v3, rel=0.01), f"roundtrip {v3} → {v4} → {back}"


# ═══════════════════════════════════════════════
# Faceji Strategy
# ═══════════════════════════════════════════════

class TestFacejiDecide:
    def test_empty_inputs(self):
        """空输入 → 空信号"""
        signals = faceji.decide({}, {}, {}, {}, 100000)
        assert signals == []

    def test_no_positions_buy_candidate(self):
        """评分≥5.0 + MA趋势ok → 买入信号"""
        signals = faceji.decide(
            {"000001": 6.0},
            {"000001": make_tech(ma20=5, ma60=2)},  # ma20 > ma60 ✓
            {"000001": 10.0},
            {}, 100000
        )
        assert len(signals) == 1
        assert signals[0].action == "BUY"
        assert signals[0].symbol == "000001"

    def test_low_score_no_buy(self):
        """评分<5.0 → 无买入"""
        signals = faceji.decide(
            {"000001": 4.0},
            {"000001": make_tech()},
            {"000001": 10.0},
            {}, 100000
        )
        buy_signals = [s for s in signals if s.action == "BUY"]
        assert len(buy_signals) == 0

    def test_ma_trend_filter(self):
        """ma60 > ma20 且评分<5.5 → 不建仓"""
        signals = faceji.decide(
            {"000001": 5.2},
            {"000001": make_tech(ma20=1, ma60=5)},  # ma60 > ma20 → 趋势向下
            {"000001": 10.0},
            {}, 100000
        )
        buy_signals = [s for s in signals if s.action == "BUY"]
        assert len(buy_signals) == 0

    def test_hard_stop_loss(self):
        """持仓亏损≤-8% → 硬止损"""
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = faceji.decide(
            {}, {}, {"000001": 90.0},  # -10%
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert len(sells) == 1
        assert "止损" in sells[0].reason or "硬止损" in sells[0].reason

    def test_trailing_stop(self):
        """峰值回落-12% → FallSeller"""
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=120)}
        signals = faceji.decide(
            {}, {}, {"000001": 105},  # -12.5% from peak
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert len(sells) >= 1

    def test_score_drop_sell(self):
        """评分<4.5 → 卖出"""
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = faceji.decide(
            {"000001": 4.0}, {}, {"000001": 100},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert len(sells) >= 1

    def test_kelly_sizing(self):
        """Kelly仓位不超过单笔上限"""
        signals = faceji.decide(
            {"000001": 8.0},
            {"000001": make_tech(ma20=5, ma60=2)},
            {"000001": 100.0},
            {}, 1000000
        )
        assert len(signals) == 1
        sp = signals[0].size_pct
        assert sp is None or sp <= 8.0  # FacejiConfig.max_position_pct = 0.08


# ═══════════════════════════════════════════════
# SilverQuant Strategy
# ═══════════════════════════════════════════════

class TestSilverQuantDecide:
    def test_empty(self):
        assert silverquant.decide({}, {}, {}, {}, 100000) == []

    def test_buy_on_score(self):
        """评分≥5.0 → 买入"""
        signals = silverquant.decide(
            {"000001": 6.0}, {}, {"000001": 10.0},
            {}, 100000
        )
        buys = [s for s in signals if s.action == "BUY"]
        assert len(buys) == 1

    def test_score_too_low(self):
        """评分<5.0 → 不买入"""
        signals = silverquant.decide(
            {"000001": 4.0}, {}, {"000001": 10.0},
            {}, 100000
        )
        buys = [s for s in signals if s.action == "BUY"]
        assert len(buys) == 0

    def test_hard_seller(self):
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = silverquant.decide(
            {}, {}, {"000001": 90},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert any("HardSeller" in s.reason for s in sells)

    def test_trailing_seller(self):
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=120)}
        signals = silverquant.decide(
            {}, {}, {"000001": 105},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert any("FallSeller" in s.reason for s in sells)

    def test_ma_seller(self):
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = silverquant.decide(
            {"000001": 5.0},
            {"000001": make_tech(ma20=1, ma60=5)},  # 死叉
            {"000001": 100},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert any("MASeller" in s.reason for s in sells)

    def test_score_drop(self):
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = silverquant.decide(
            {"000001": 4.0},
            {"000001": make_tech()},
            {"000001": 100},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert any("ScoreDrop" in s.reason for s in sells)


# ═══════════════════════════════════════════════
# TradingAgents Strategy
# ═══════════════════════════════════════════════

class TestTradingAgentsDecide:
    def test_empty(self):
        assert tradingagents.decide({}, {}, {}, {}, 100000) == []

    def test_buy_on_debate(self):
        """辩论分≥5.5 → 买入"""
        signals = tradingagents.decide(
            {"000001": 7.0},
            {"000001": make_tech()},
            {"000001": 10.0},
            {}, 100000
        )
        buys = [s for s in signals if s.action == "BUY"]
        assert len(buys) == 1
        assert "辩论" in buys[0].reason

    def test_low_debate_no_buy(self):
        signals = tradingagents.decide(
            {"000001": 4.0},
            {"000001": make_tech()},
            {"000001": 10.0},
            {}, 100000
        )
        buys = [s for s in signals if s.action == "BUY"]
        assert len(buys) == 0

    def test_force_sell_low_debate(self):
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100)}
        signals = tradingagents.decide(
            {"000001": 3.0},
            {"000001": make_tech()},
            {"000001": 100},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert len(sells) >= 1

    def test_hard_stop(self):
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = tradingagents.decide(
            {"000001": 6.0},
            {"000001": make_tech()},
            {"000001": 90},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert len(sells) >= 1
        assert "止损" in sells[0].reason

    def test_weak_sell(self):
        """辩论分<5.0+亏损 → 卖出"""
        pos = {"000001": PositionData("000001", entry_price=100, quantity=100, peak=100)}
        signals = tradingagents.decide(
            {"000001": 4.5},
            {"000001": make_tech()},
            {"000001": 95},
            pos, 100000
        )
        sells = [s for s in signals if s.action == "SELL"]
        assert any("亏损" in s.reason for s in sells)

    def test_top3_candidates(self):
        """最多取前3候选"""
        score_map = {f"00000{i}": 8.0 for i in range(1, 10)}
        tech_map = {f"00000{i}": make_tech() for i in range(1, 10)}
        price_map = {f"00000{i}": 100.0 for i in range(1, 10)}
        signals = tradingagents.decide(score_map, tech_map, price_map, {}, 1000000)
        buys = [s for s in signals if s.action == "BUY"]
        assert len(buys) <= 3


# ═══════════════════════════════════════════════
# Signal dataclass
# ═══════════════════════════════════════════════

class TestSignalDataclass:
    def test_to_dict(self):
        s = Signal("000001", "BUY", price=100.0, reason="test", priority="HIGH")
        d = s.to_dict()
        assert d["action"] == "BUY"
        assert d["symbol"] == "000001"
        assert d["priority"] == "HIGH"

    def test_position_data_pnl(self):
        p = PositionData("000001", entry_price=100, quantity=100, current_price=110)
        assert p.pnl_pct == pytest.approx(10.0)

    def test_position_data_drawdown(self):
        p = PositionData("000001", entry_price=100, quantity=100, peak=120, current_price=100)
        assert p.drawdown_from_peak == pytest.approx(-16.67, rel=0.01)
