"""ATR 自适应止损测试 (2026-09-01)

锁定: 高波动股止损更宽(2×ATR%), 低波动股保底 -8%。
修复前: 固定 -8% 在半导体高波动股上频繁止损(胜率0%)。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from strategies.faceji import decide as faceji_decide
from strategies.base import PositionData, FacejiConfig


def _mk_positions(entry, current):
    return {"600519": PositionData(symbol="600519", entry_price=entry,
                                   quantity=100, current_price=current)}


def test_compute_technicals_returns_atr_pct():
    from engine.evaluator_fixed import compute_technicals
    closes = [100.0 + (i % 3) * 2 for i in range(60)]  # 有波动的序列
    te = compute_technicals(closes, 102.0)
    assert "atr_pct" in te, "compute_technicals 应返回 atr_pct"


def test_high_vol_atr_stop_wider():
    """高波动股(atr_pct=10): 止损阈值 -20%, 浮亏 -10% 不触发(修复前固定 -8% 会触发)。"""
    positions = _mk_positions(100.0, 90.0)  # 浮亏 -10% (避开 FallSeller -12%)
    tech_map = {"600519": {"atr_pct": 10.0, "ma20_dev": -1.0, "ma60_dev": -2.0,
                           "macd_signal": "⚪", "rsi": 50}}
    price_map = {"600519": 90.0}
    score_map = {"600519": 6.0}
    signals = faceji_decide(score_map, tech_map, price_map, positions,
                            cash=100000, config=FacejiConfig())
    sells = [s for s in signals if s.action == "SELL"]
    assert not sells, f"高波动股 -10% 不应触发止损(阈值 -20%), got {[s.reason for s in sells]}"


def test_low_vol_atr_stop_floor():
    """低波动股(atr_pct=2): 止损阈值保底 -8%, 浮亏 -9% 触发。"""
    positions = _mk_positions(100.0, 91.0)  # 浮亏 -9%
    tech_map = {"600519": {"atr_pct": 2.0, "ma20_dev": -1.0, "ma60_dev": -2.0,
                           "macd_signal": "⚪", "rsi": 50}}
    price_map = {"600519": 91.0}
    score_map = {"600519": 6.0}
    signals = faceji_decide(score_map, tech_map, price_map, positions,
                            cash=100000, config=FacejiConfig())
    sells = [s for s in signals if s.action == "SELL"]
    assert sells, "低波动股 -9% 应触发止损(保底 -8%)"
