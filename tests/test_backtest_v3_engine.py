"""backtest_v3 引擎修复 — WS-A(真正周期) / WS-B(xalpha真引擎) / WS-C(对比) 契约测试.

针对用户指出的三大缺陷:
1. days 参数不生效 → evaluate_strategy 永远 FIXED_DAYS=120
2. 日期标签是自然日而非交易日 → 报告日期错位
3. xalpha 引擎没真正用于回测(只有适配层)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import pytest


class TestDaysControlsWindow:
    def test_evaluate_strategy_accepts_days_param(self):
        """evaluate_strategy 签名含 days 参数(默认 None → FIXED_DAYS)."""
        from engine import evaluator_fixed
        import inspect
        sig = inspect.signature(evaluator_fixed.evaluate_strategy)
        assert "days" in sig.parameters

    def test_run_backtest_v3_passes_days_to_engine(self, monkeypatch):
        """run_backtest_v3(days=250) 必须把 days 传给 evaluate_strategy."""
        from engine import backtest_v3
        captured = {}

        class FakeResult:
            strategy_name = "faceji"
            initial_cash = 1_000_000
            total_return_pct = 10.0
            annualized_return_pct = 20.0
            sharpe_ratio = 1.5
            sortino_ratio = 1.2
            max_drawdown_pct = 5.0
            calmar_ratio = 2.0
            win_rate_pct = 50.0
            trade_count = 10
            equity_curve = [
                {"date": f"2026-{m:02d}-01", "value": 1_000_000 + i * 1000}
                for i, m in enumerate(range(1, 110))
            ]
            trades = [{"symbol": "600519", "action": "BUY", "price": 100}]
            extra = {}

        def fake_evaluate(strategy_name, walk_forward=False, cycles=3,
                         train_days=252, test_days=63, custom_symbols=None,
                         days=None, **kw):
            captured["days"] = days
            captured["symbols"] = custom_symbols
            return FakeResult()

        monkeypatch.setattr("engine.evaluator_fixed.evaluate_strategy", fake_evaluate)
        monkeypatch.setattr(backtest_v3, "generate_report",
                            lambda *a, **k: {"run_id": "x", "report_path": "/tmp/x.html",
                                             "metrics": {}, "meta": {}})
        monkeypatch.setattr(backtest_v3, "_fetch_benchmark_nav",
                            lambda days=120: None)
        r = backtest_v3.run_backtest_v3(
            "faceji", days=250, custom_symbols=["600519", "000858"])
        assert captured["days"] == 250
        assert captured["symbols"] == ["600519", "000858"]


class TestRealTradingDates:
    def test_load_dates_map_keeps_dates(self, monkeypatch, tmp_path):
        """load_dates_map 返回每标真实日期序列(与价格对齐)."""
        from engine import evaluator_fixed
        df = pd.DataFrame({
            "date": pd.bdate_range("2026-01-01", periods=20),
            "close": [10 + i * 0.1 for i in range(20)],
        })
        import engine.evaluator_fixed as ev
        # 隔离 CACHE_DIR 到 tmp
        monkeypatch.setattr(ev, "CACHE_DIR", tmp_path / "cache")
        ev.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_file = ev.CACHE_DIR / "600519_20d.pkl"
        df.to_pickle(cache_file)
        dates_map = ev.load_dates_map(days=20, custom_symbols=["600519"])
        assert "600519" in dates_map
        assert len(dates_map["600519"]) == 20
        # 全是工作日
        from datetime import date as _date
        for ds in dates_map["600519"]:
            assert _date.fromisoformat(ds).weekday() < 5


class TestXalphaEngineRealUse:
    def test_xalpha_mul_nav_no_negative(self):
        """xalpha mul 引擎跑多标的 buyandhold → NAV 全为正, 长度合理."""
        import xalpha.policy as pol
        import xalpha.backtest as bt
        from engine.backtest_v3 import AStockInfo, _closes_to_df

        n = 60
        def mk_df(base):
            return pd.DataFrame({
                "date": pd.bdate_range("2026-01-01", periods=n),
                "close": [base + i * 0.05 for i in range(n)],
                "open": [base + i * 0.05 for i in range(n)],
                "high": [base + i * 0.05 + 0.1 for i in range(n)],
                "low": [base + i * 0.05 - 0.1 for i in range(n)],
                "volume": [1000] * n,
            })

        trade_objs = []
        for code, base in [("600519", 100.0), ("000858", 50.0), ("600036", 20.0)]:
            info = AStockInfo(code, code, mk_df(base), enforce_lot=True)
            start = str(info.price["date"].iloc[0].date())
            end = str(info.price["date"].iloc[-1].date())
            cp = pol.buyandhold(info, start, end, totmoney=100000)
            tr = bt.trade(info, cp.status)
            trade_objs.append(tr)

        m = bt.mul(*trade_objs)
        dates = sorted(set().union(*[set(t.price["date"]) for t in trade_objs]))
        nav = [sum(t.briefdailyreport(d).get("currentvalue", 0) for t in trade_objs)
               for d in dates]
        assert len(nav) >= n - 2
        assert min(nav) > 0

    def test_build_status_multi_symbol(self):
        """build_status 支持多标的 → 返回多列 DataFrame(每标的一列), 供 mul 逐标的消费."""
        from engine.backtest_v3 import build_status_from_decisions
        decisions = [
            {"date": "2026-01-01", "symbol": "600519", "action": "BUY", "amount": 50000},
            {"date": "2026-01-02", "symbol": "000858", "action": "BUY", "amount": 30000},
            {"date": "2026-01-05", "symbol": "600519", "action": "SELL", "shares": 100},
        ]
        price_map = {"600519": 100.0, "000858": 50.0}
        st = build_status_from_decisions(decisions, price_map)
        assert "600519" in st.columns
        assert "000858" in st.columns  # 多标的全部保留
        # 600519: +50000, -100(份额, shuhui契约)
        vals = st["600519"].dropna().tolist()
        assert 50000 in vals
        assert -100 in vals


class TestCompareReport:
    def test_generate_compare_report_multi_strategy(self, tmp_path, monkeypatch):
        """多策略对比报告: 3 条 NAV → 1 份 HTML 含指标表."""
        import numpy as np
        from engine import backtest_v3
        from engine.backtest_v3 import clear_reports, generate_compare_report
        monkeypatch.setattr(backtest_v3, "REPORT_ROOT", tmp_path / "reports")
        import quantstats as qs
        navs = {}
        for name, seed in [("faceji", 1), ("silverquant", 2), ("tradingagents", 3)]:
            rng = np.random.default_rng(seed)
            nav = pd.Series(1_000_000 * (1 + np.cumsum(rng.normal(0.001, 0.01, 80))),
                            index=pd.date_range("2026-01-01", periods=80, freq="B"),
                            name=name)
            navs[name] = nav
        res = generate_compare_report(navs, None, params={"days": 80},
                                      run_id="cmp_test")
        assert res["run_id"] == "cmp_test"
        report = (tmp_path / "reports" / "cmp_test" / "report.html")
        assert report.exists()
        html = report.read_text(encoding="utf-8")
        assert "faceji" in html and "silverquant" in html and "tradingagents" in html
        assert "Sharpe" in html and "MaxDD" in html
        assert "data:image/png;base64" in html  # 净值对比图内嵌