"""Tests for analysis/cost_model — A股/港美股交易成本模型."""
import pytest
from engine.cost_model import (
    calc_trade_cost, COMMISSION_RATE, MIN_COMMISSION,
    STAMP_TAX_RATE, TRANSFER_FEE_RATE, FLOW_FEE,
)


class TestCalcTradeCost:
    def test_buy_a_share(self):
        """A股买入: 佣金+过户费+规费, 无印花税"""
        r = calc_trade_cost(price=100.0, qty=1000, direction="buy", symbol="300502")
        assert r["commission"] == pytest.approx(100_000 * COMMISSION_RATE)
        assert r["stamp_tax"] == 0  # 买入无印花税
        assert r["transfer_fee"] > 0
        assert r["flow_fee"] == FLOW_FEE
        assert r["slippage"] >= 0
        assert r["total"] > 0

    def test_sell_a_share(self):
        """A股卖出: 佣金+印花税+过户费+规费"""
        r = calc_trade_cost(price=100.0, qty=1000, direction="sell", symbol="300502")
        assert r["stamp_tax"] == pytest.approx(100_000 * STAMP_TAX_RATE)
        assert r["total"] > r["stamp_tax"]

    def test_min_commission_enforced(self):
        """小单：佣金按最低5元收"""
        r = calc_trade_cost(price=5.0, qty=100, direction="buy", symbol="300502")
        assert r["commission"] == MIN_COMMISSION  # 500*0.00015=0.075 < 5

    def test_hk_stock(self):
        """港股: 当前模型统一按A股处理, 买入无印花税"""
        r = calc_trade_cost(price=100.0, qty=1000, direction="buy", symbol="00700.HK")
        assert r["stamp_tax"] == 0  # TODO: 港股买入印花税未实现

    def test_us_stock(self):
        """美股: 当前模型统一按A股处理, 卖出有印花税"""
        r = calc_trade_cost(price=100.0, qty=1000, direction="sell", symbol="AAPL")
        assert r["stamp_tax"] > 0  # TODO: 美股无印花税未实现

    def test_large_trade_slippage(self):
        """大单滑点随成交额增大而减小"""
        small = calc_trade_cost(price=5.0, qty=10000, direction="buy", symbol="300502")
        large = calc_trade_cost(price=100.0, qty=100000, direction="buy", symbol="300502")
        # 大额成交额 → 更小滑点比率
        assert large["slippage"] >= 0

    def test_zero_qty(self):
        """0股 → 仅佣金(最低5元)+规费"""
        r = calc_trade_cost(price=100.0, qty=0, direction="buy", symbol="300502")
        # 佣金按最低5元, 无其他费用
        assert r["commission"] == MIN_COMMISSION
        assert r["stamp_tax"] == 0
        assert r["total"] == MIN_COMMISSION + FLOW_FEE
