"""test_etf_portfolio_action.py — ETF 组合信号 action 正确性

验证子组合 (timing/rp) 与合并视图 (combined) 的 action 信号一致，
且 action 基于真实价格权重偏离计算，而非硬编码 HOLD。

背景 (ETF-专项 2026-08-31):
  _build_output() 中 timing_out / rp_out 的 action 曾被硬编码为 "HOLD"，
  只有 combined 部分重新计算 action → 择时/非择时两个子组合表格信号永远为 HOLD，失去意义。
  本测试锁定: 子组合的 action 必须由 _determine_action(当前权重, 目标权重) 推导。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import pytest

from etf.etf_portfolio import EtfPortfolioBuilder, _determine_action


class TestDetermineAction:
    """_determine_action 阈值判断"""

    def test_buy_when_target_above_current_beyond_threshold(self):
        assert _determine_action(0.10, 0.20, 0.02) == "BUY"

    def test_sell_when_target_below_current_beyond_threshold(self):
        assert _determine_action(0.30, 0.20, 0.02) == "SELL"

    def test_hold_within_threshold(self):
        assert _determine_action(0.19, 0.20, 0.02) == "HOLD"


class TestActionPropagation:
    """子组合 action 必须与 combined 一致 (相同推导逻辑)"""

    def _stub_builder(self) -> EtfPortfolioBuilder:
        """构造 builder，注入 fake price_df 与 weights，绕过真实行情依赖"""
        b = EtfPortfolioBuilder()
        # 造 80 天价格: 510300 上涨(触发BUY倾向), 511010 平稳, 518880 上涨,
        # 159985 下跌(触发SELL倾向), 512480 平稳, 513100 上涨
        dates = pd.date_range("2026-01-01", periods=80, freq="B")
        import numpy as np
        price_data = {}
        base = {"510300": 4.0, "511010": 100.0, "512480": 1.5, "518880": 5.0, "513100": 4.5, "159985": 1.2}
        trend = {"510300": 1.005, "511010": 1.0, "512480": 1.0, "518880": 1.004, "513100": 1.006, "159985": 0.996}
        for sym, b0 in base.items():
            vals = [b0]
            for _ in range(79):
                vals.append(vals[-1] * trend[sym])
            price_data[sym] = vals
        b.price_df = pd.DataFrame(price_data, index=dates)
        b._latest_idx = len(b.price_df) - 1
        # 注入权重: timing 给 510300 较大权重, rp 用 4 支
        b._timing_weights = {"510300": 0.5, "511010": 0.1, "512480": 0.1, "518880": 0.1, "513100": 0.2}
        b._rp_weights = {"510300": 0.3, "511010": 0.3, "518880": 0.2, "159985": 0.2}
        return b

    def test_subportfolio_actions_derived_not_hardcoded(self):
        b = self._stub_builder()
        out = b._build_output()
        timing_symbols = out["timing_portfolio"]["symbols"]
        rp_symbols = out["non_timing_portfolio"]["symbols"]
        combined = out["combined"]

        # 子组合 action 不能全部是 HOLD (至少出现一个非 HOLD)
        timing_actions = {e["etf_symbol"]: e["action"] for e in timing_symbols}
        rp_actions = {e["etf_symbol"]: e["action"] for e in rp_symbols}
        combined_actions = {e["etf_symbol"]: e["action"] for e in combined}

        assert any(a != "HOLD" for a in timing_actions.values()), "timing 子组合信号全为 HOLD — 未从价格推导"
        assert any(a != "HOLD" for a in rp_actions.values()), "rp 子组合信号全为 HOLD — 未从价格推导"

        # 重叠标的: 子组合 action 必须与 combined 一致 (same derivation)
        for sym in set(timing_actions) & set(combined_actions):
            assert timing_actions[sym] == combined_actions[sym], \
                f"timing vs combined action 不一致: {sym}"
        for sym in set(rp_actions) & set(combined_actions):
            assert rp_actions[sym] == combined_actions[sym], \
                f"rp vs combined action 不一致: {sym}"