"""tests/test_behavior.py — 行为诊断引擎测试

TDD: RED → GREEN → REFACTOR
"""
import sys, json, os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.behavior import (
    diagnose_strategy,
    diagnose_all,
    _calc_disposition_effect,
    _calc_overtrading,
    _calc_chasing,
    _calc_anchoring,
    _calc_pnl_analysis,
)


# ── Fixtures ──


def _make_trade(date: str, symbol: str, action: str, price: float,
                pnl_pct: float = 0, pnl: float = 0, cost: float = 0,
                reason: str = "") -> dict:
    return {
        "date": date,
        "symbol": symbol,
        "action": action,
        "price": price,
        "pnl_pct": pnl_pct,
        "pnl": pnl,
        "cost": cost,
        "reason": reason,
    }


# ── 1. 处置效应 ──


def test_disposition_effect_high():
    """强处置效应：大量盈利卖出 vs 少量亏损卖出"""
    sells = [
        _make_trade("2026-07-01", "A", "卖出", 110, pnl_pct=10, pnl=100),
        _make_trade("2026-07-01", "B", "卖出", 120, pnl_pct=20, pnl=200),
        _make_trade("2026-07-01", "C", "卖出", 105, pnl_pct=5, pnl=50),
        _make_trade("2026-07-02", "D", "卖出", 95, pnl_pct=-5, pnl=-50),
    ]
    buys = [
        _make_trade("2026-06-01", "A", "买入", 100),
        _make_trade("2026-06-01", "B", "买入", 100),
        _make_trade("2026-06-01", "C", "买入", 100),
        _make_trade("2026-06-01", "D", "买入", 100),
    ]
    result = _calc_disposition_effect(sells, buys)
    # 3 profit / 1 loss = 3.0 > 1.5 → 显著
    assert result["ratio"] >= 2.0, f"Expected high disposition ratio, got {result['ratio']}"
    assert result["profit_sells"] == 3
    assert result["loss_sells"] == 1


def test_disposition_effect_normal():
    """正常处置效应：约一半盈利一半亏损卖出"""
    sells = [
        _make_trade("2026-07-01", "A", "卖出", 110, pnl_pct=10, pnl=100),
        _make_trade("2026-07-01", "B", "卖出", 90, pnl_pct=-10, pnl=-100),
    ]
    buys = [
        _make_trade("2026-06-01", "A", "买入", 100),
        _make_trade("2026-06-01", "B", "买入", 100),
    ]
    result = _calc_disposition_effect(sells, buys)
    # 1 profit / 1 loss = 1.0 → 正常
    assert result["ratio"] <= 1.5, f"Expected normal disposition, got {result['ratio']}"


def test_disposition_effect_no_sells():
    """无卖出记录时返回 0"""
    result = _calc_disposition_effect([], [])
    assert result["ratio"] == 0.0


# ── 2. 过度交易指数 ──


def test_overtrading_high():
    """高过度交易指数：30天20笔 = 日均0.67，基准0.4 → 1.67倍"""
    history = [
        _make_trade(f"2026-06-{d:02d}", "A", "买入", 100)
        for d in range(1, 21)
    ]
    result = _calc_overtrading(history, history, [])
    # 20 trades / 20 days = 1.0/day / 0.4 = 2.5
    assert result["index"] > 1.5, f"Expected high overtrading, got {result['index']}"


def test_overtrading_normal():
    """正常频率：10天2笔"""
    history = [
        _make_trade("2026-06-01", "A", "买入", 100),
        _make_trade("2026-06-10", "B", "买入", 100),
    ]
    result = _calc_overtrading(history, history, [])
    # 2 trades / 10 days = 0.2/day / 0.4 = 0.5
    assert result["index"] < 1.0


def test_overtrading_empty():
    """空历史返回 0"""
    result = _calc_overtrading([], [], [])
    assert result["index"] == 0.0


# ── 3. 追涨分数 ──


def test_chasing_high():
    """高追涨：一天买入4只不同标的"""
    buys = [
        _make_trade("2026-07-01", "A", "买入", 100),
        _make_trade("2026-07-01", "B", "买入", 100),
        _make_trade("2026-07-01", "C", "买入", 100),
        _make_trade("2026-07-01", "D", "买入", 100),
    ]
    result = _calc_chasing(buys + [], buys)
    # 1 chasing day out of 1 = 100% → score ~10
    assert result["score"] >= 5.0, f"Expected high chasing, got {result['score']}"


def test_chasing_normal():
    """正常：分散日买入"""
    buys = [
        _make_trade("2026-07-01", "A", "买入", 100),
        _make_trade("2026-07-02", "B", "买入", 100),
        _make_trade("2026-07-05", "C", "买入", 100),
    ]
    result = _calc_chasing(buys + [], buys)
    # 0 chasing days out of 3 = 0%
    assert result["score"] < 2.0


def test_chasing_empty():
    """无买入返回 0"""
    result = _calc_chasing([], [])
    assert result["score"] == 0.0


# ── 4. 锚定指数 ──


def test_anchoring_high():
    """高锚定：亏损卖出平均亏25%"""
    sells = [
        _make_trade("2026-07-01", "A", "卖出", 100, pnl_pct=-25, pnl=-2500),
        _make_trade("2026-07-01", "B", "卖出", 100, pnl_pct=-30, pnl=-3000),
    ]
    result = _calc_anchoring(sells)
    # avg_loss = 27.5% / 20% * (2/2) = 1.375
    assert result["index"] > 0.8, f"Expected high anchoring, got {result['index']}"
    assert result["avg_loss_pct"] >= 20.0


def test_anchoring_normal():
    """正常锚定：及时止损"""
    sells = [
        _make_trade("2026-07-01", "A", "卖出", 100, pnl_pct=-5, pnl=-500),
        _make_trade("2026-07-01", "B", "卖出", 100, pnl_pct=-3, pnl=-300),
    ]
    result = _calc_anchoring(sells)
    assert result["index"] < 0.8


def test_anchoring_empty():
    """空数据返回 0"""
    result = _calc_anchoring([])
    assert result["index"] == 0.0


# ── 5. 集成测试 ──


def test_diagnose_strategy_full():
    """全流程：一个策略的完整诊断"""
    history = [
        _make_trade("2026-06-24", "A", "买入", 100, cost=10000),
        _make_trade("2026-06-25", "B", "买入", 200, cost=20000),
        _make_trade("2026-06-26", "A", "卖出", 120, pnl=2000, pnl_pct=20, cost=10000),
        _make_trade("2026-06-27", "C", "买入", 50, cost=5000),
        _make_trade("2026-06-28", "B", "卖出", 180, pnl=-2000, pnl_pct=-10, cost=20000),
    ]
    result = diagnose_strategy(history, "test_strategy")
    assert result["strategy"] == "test_strategy"
    assert result["trade_count"] == 5
    assert result["buy_count"] == 3
    assert result["sell_count"] == 2
    assert "disposition_ratio" in result
    assert "overtrading_index" in result
    assert "chasing_score" in result
    assert "anchoring_index" in result
    assert "recommended_actions" in result
    assert len(result["recommended_actions"]) > 0


def test_diagnose_all():
    """诊断所有策略"""
    states = {
        "faceji": {"history": [
            _make_trade("2026-06-24", "A", "买入", 100),
            _make_trade("2026-06-26", "A", "卖出", 120, pnl_pct=20),
        ]},
        "silverquant": {"history": [
            _make_trade("2026-06-24", "B", "买入", 200),
            _make_trade("2026-06-28", "B", "卖出", 180, pnl_pct=-10),
        ]},
    }
    results = diagnose_all(states)
    assert "faceji" in results
    assert "silverquant" in results
    assert "_combined" in results


def test_real_data():
    """用真实 strategy_states.json 数据验证"""
    path = Path(__file__).resolve().parent.parent / "data" / "strategy_states.json"
    if not path.exists():
        return  # skip if no real data
    from engine.behavior import load_strategy_states
    states = load_strategy_states(path)
    results = diagnose_all(states)
    assert len(results) >= 3  # faceji, silverquant, tradingagents + _combined
    for sname in ["faceji", "silverquant", "tradingagents", "_combined"]:
        assert sname in results, f"Missing {sname}"
        r = results[sname]
        assert "disposition_ratio" in r
        assert "overtrading_index" in r
        assert "chasing_score" in r
        assert "anchoring_index" in r
