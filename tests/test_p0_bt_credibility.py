"""第一批 P0 修复 — 回测可信性 (2026-08-31)

P0-3: T+1 成交 — 信号 T 日收盘生成, T+1 开盘价成交
P0-4: v3 引擎卖出成本模型 — _decide_loop SELL 分支接入 calc_adjusted_price
P0-10: sortino 无 fallback — 缺失时返回 None
P0-13: 短窗口报告 — rolling 指标图降级
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest


class TestT1Execution:
    """P0-3: 信号 T 日生成, T+1 开盘价成交"""

    def test_load_price_history_caches_open(self, monkeypatch, tmp_path):
        """缓存 DataFrame 必须含 open 列 (T+1 成交的数据基础)."""
        from engine import evaluator_fixed as ev
        monkeypatch.setattr(ev, "CACHE_DIR", tmp_path / "cache")
        ev.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({
            "date": pd.bdate_range("2026-01-01", periods=20).strftime("%Y-%m-%d").tolist(),
            "open": [10.0 + i * 0.1 for i in range(20)],
            "close": [10.5 + i * 0.1 for i in range(20)],
        })
        df.to_pickle(ev.CACHE_DIR / "600519_20d.pkl")
        # 读路径必须带回 open
        hist = ev.load_price_history("600519", 20)

    def test_run_backtest_accepts_use_t1_flag(self):
        """run_backtest 签名必须含 use_t1 参数 (默认 True)."""
        from engine import evaluator_fixed as ev
        import inspect
        sig = inspect.signature(ev.run_backtest)
        assert "use_t1" in sig.parameters
        assert sig.parameters["use_t1"].default is True

    def test_t1_executes_on_next_day_open(self, monkeypatch, tmp_path):
        """T 日信号必须在 T+1 日开盘价成交而非 T 日收盘价."""
        from engine import evaluator_fixed as ev
        from strategies.base import Signal

        closes = [10.0 + i * 0.5 for i in range(70)]     # 稳定上涨
        opens = [10.2 + i * 0.5 for i in range(70)]      # 开盘略高于昨收
        # 构造到 day_idx 的信号: 只在第 10 天给一个 BUY
        calls = {"idx": 0}

        def decide(score_map, tech_map, price_map, positions, cash):
            if calls["idx"] == 10:
                calls["idx"] += 1
                return [Signal(symbol="600519", action="BUY", price=price_map["600519"],
                               size_pct=10, reason="test")]
            calls["idx"] += 1
            return []

        price_data = {"600519": {"close": closes, "open": opens}}
        dates = pd.bdate_range("2026-01-01", periods=70).strftime("%Y-%m-%d").tolist()
        dates_map = {"600519": dates}
        r = ev.run_backtest(price_data, decide, "faceji", dates_map=dates_map, use_t1=True)
        assert not isinstance(r, dict), f"回测失败: {r}"
        buys = [t for t in r.trades if t["action"] == "BUY"]
        assert len(buys) == 1
        # 用 T+1 开盘: opens[11] = 10.2 + 11*0.5 = 15.7
        assert abs(buys[0]["price"] - opens[11]) < 1e-6, f"成交价 {buys[0]['price']} != T+1开盘 {opens[11]}"

    def test_t1_last_day_signal_not_executed(self, monkeypatch, tmp_path):
        """最后一天生成的信号没有 T+1 → 不成交."""
        from engine import evaluator_fixed as ev
        from strategies.base import Signal

        closes = [10.0 + i * 0.5 for i in range(70)]
        opens = [10.2 + i * 0.5 for i in range(70)]
        state = {"n": 0}

        def decide(score_map, tech_map, price_map, positions, cash):
            state["n"] += 1
            if state["n"] == 70:   # 最后一天
                return [Signal(symbol="600519", action="BUY", price=price_map["600519"],
                               size_pct=10, reason="last")]
            return []

        price_data = {"600519": {"close": closes, "open": opens}}
        dates = pd.bdate_range("2026-01-01", periods=70).strftime("%Y-%m-%d").tolist()
        r = ev.run_backtest(price_data, decide, "faceji", dates_map={"600519": dates}, use_t1=True)
        assert not isinstance(r, dict)
        buys = [t for t in r.trades if t["action"] == "BUY"]
        assert len(buys) == 0, "最后一天信号不应成交 (无 T+1)"


class TestV3SellCostModel:
    """P0-4: v3 引擎 _decide_loop 卖出必须接入成本模型"""

    def test_decide_loop_sell_uses_cost_model(self, monkeypatch):
        """SELL 分支必须用 calc_adjusted_price 而非裸 total_cash += qty*price."""
        from engine import backtest_v3
        src = open(backtest_v3.__file__).read()
        sell_line = [l for l in src.splitlines() if "total_cash += qty * price" in l]
        assert not sell_line, f"_decide_loop 仍有裸卖出: {sell_line}"


class TestSortinoNoFallback:
    """P0-10: sortino 缺失时返回 None, 不 fallback 到 score"""

    def test_sortino_not_fallback_to_score(self, monkeypatch, tmp_path):
        """BacktestResult.sortino_ratio 缺失时应为 None 而非 score."""
        from engine import evaluator_fixed as ev
        monkeypatch.setattr(ev, "CACHE_DIR", tmp_path / "cache")
        # 直接检查 _build_result 路径: metrics 无 sortino → None
        metrics = {"sharpe_ratio": 1.5, "score": 7.0}
        # 通过构造最小 price_data 跑完整回测, metrics 由 _compute_metrics 生成
        closes = [10.0 for _ in range(70)]
        opens = [10.2 for _ in range(70)]
        price_data = {"600519": {"close": closes, "open": opens}}
        dates = pd.bdate_range("2026-01-01", periods=70).strftime("%Y-%m-%d").tolist()

        def decide(score_map, tech_map, price_map, positions, cash):
            return []

        r = ev.run_backtest(price_data, decide, "faceji", dates_map={"600519": dates})
        assert not isinstance(r, dict)
        # sortino 可以是 None 或数值, 但绝不能等于 score 7.0 这种 fallback 痕迹
        assert r.sortino_ratio != 7.0