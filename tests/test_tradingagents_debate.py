"""TradingAgents 辩论制逻辑修复测试 (2026-09-01)

锁定 bug 修复:
  1. 死叉/RSI超买(看空信号)应「降低」辩论分(原逻辑 bear=sc-bp 反向)
  2. 看空信号应能影响最终分(原逻辑 bear恒≤neut, 看空分支永不触发)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from strategies.tradingagents import _debate_score
from strategies.base import TradingAgentsConfig


@pytest.fixture
def cfg():
    return TradingAgentsConfig()


def test_debate_no_bear_signal_equals_bull(cfg):
    """无看空信号时, 辩论分 = bull = 评分×0.5 + 技术×0.5。"""
    final = _debate_score(6.0, {"total_tech_score": 6.0, "rsi": 50, "macd_signal": "⚪"}, cfg)
    assert final == pytest.approx(6.0)


def test_debate_death_cross_lowers_score(cfg):
    """死叉(看空信号)必须降低辩论分, 而非升高或不变。"""
    no_signal = _debate_score(6.0, {"total_tech_score": 6.0, "rsi": 50, "macd_signal": "⚪"}, cfg)
    death_cross = _debate_score(6.0, {"total_tech_score": 6.0, "rsi": 50, "macd_signal": "死叉"}, cfg)
    assert death_cross < no_signal, f"死叉应降低辩论分, got {death_cross} vs {no_signal}"


def test_debate_rsi_overbought_lowers_score(cfg):
    """RSI>70(超买看空)必须降低辩论分。"""
    normal = _debate_score(6.0, {"total_tech_score": 6.0, "rsi": 50, "macd_signal": "⚪"}, cfg)
    overbought = _debate_score(6.0, {"total_tech_score": 6.0, "rsi": 75, "macd_signal": "⚪"}, cfg)
    assert overbought < normal, f"RSI超买应降低辩论分, got {overbought} vs {normal}"


def test_debate_bear_can_dominate(cfg):
    """强看空(死叉+RSI超买)时辩论分应跌破强卖阈值(4.0), 使看空分支可触发。"""
    final = _debate_score(5.0, {"total_tech_score": 5.0, "rsi": 80, "macd_signal": "死叉"}, cfg)
    assert final < 4.0, f"强看空应使辩论分 <4.0(强卖阈值), got {final}"


def test_debate_range_clamped(cfg):
    """辩论分始终在 [0,10] 内。"""
    low = _debate_score(1.0, {"total_tech_score": 1.0, "rsi": 90, "macd_signal": "死叉"}, cfg)
    high = _debate_score(9.0, {"total_tech_score": 9.0, "rsi": 40, "macd_signal": "金叉"}, cfg)
    assert 0.0 <= low <= 10.0
    assert 0.0 <= high <= 10.0
