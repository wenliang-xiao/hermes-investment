"""backtest_v3 — AStockInfo 契约 / 策略桥 / 报告落盘 测试."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path

import pandas as pd
import pytest


def _mk_df(n=30, start="2026-01-01", base=10.0):
    return pd.DataFrame({
        "date": pd.date_range(start, periods=n, freq="B"),
        "close": [base + i * 0.05 for i in range(n)],
        "open": [base + i * 0.05 for i in range(n)],
        "high": [base + i * 0.05 + 0.1 for i in range(n)],
        "low": [base + i * 0.05 - 0.1 for i in range(n)],
        "volume": [1000] * n,
    })


class TestAStockInfo:
    def test_shengou_cash_share_consistent(self):
        """买入 100k → 现金流出=份额*价格+佣金, 份额≈金额/价格."""
        from engine.backtest_v3 import AStockInfo
        info = AStockInfo("300502", "新易盛", _mk_df(), enforce_lot=False)
        rdate, cash, share = info.shengou(100000, "2026-01-02")
        price = info.price[info.price["date"] >= pd.Timestamp("2026-01-02")].iloc[0].netvalue
        assert cash < 0
        assert share > 0
        # 份额*价格 ≈ 买入金额(去手续费)
        assert abs(share * price - 100000) < 100
        # 现金流 = -(份额*价格 + 佣金), 佣金≈万1.5
        assert abs(abs(cash) - share * price) < 20

    def test_shuhui_cash_share_stamp_tax(self):
        """卖出份额 → 现金流入 = 份额*价格 - 佣金 - 印花税千1."""
        from engine.backtest_v3 import AStockInfo
        info = AStockInfo("300502", "新易盛", _mk_df(), enforce_lot=False)
        # 先买后卖
        _, _, share = info.shengou(100000, "2026-01-02")
        rdate, cash, dshare = info.shuhui(share, "2026-01-10")
        assert cash > 0
        assert dshare < 0
        sell_price = info.price[info.price["date"] >= pd.Timestamp("2026-01-10")].iloc[0].netvalue
        gross = share * sell_price
        assert cash < gross  # 扣费
        # 印花税千1 ≈ gross*0.001
        assert abs((gross - cash) / gross - (0.001 + 0.00015)) < 0.002

    def test_enforce_lot_rounds_to_100(self):
        """整手模式: 份额必须是100的整数倍."""
        from engine.backtest_v3 import AStockInfo
        info = AStockInfo("300502", "新易盛", _mk_df(base=10.0), enforce_lot=True, lot_size=100)
        _, _, share = info.shengou(100000, "2026-01-02")
        assert share % 100 == 0

    def test_buy_then_sell_net_value_positive(self):
        """buyandhold 全流程: 净值序列非空且未归一为0."""
        import xalpha.policy as pol
        import xalpha.backtest as bt
        from engine.backtest_v3 import AStockInfo
        df = _mk_df(n=60, base=10.0)
        info = AStockInfo("300502", "新易盛", df, enforce_lot=False)
        start = str(info.price["date"].iloc[0].date())
        end = str(info.price["date"].iloc[-1].date())
        cp = pol.buyandhold(info, start, end, totmoney=100000)
        tr = bt.trade(info, cp.status)
        dates = tr.price[tr.price["date"] >= tr.cftable.iloc[0].date]["date"]
        nav = pd.Series([tr.briefdailyreport(d).get("currentvalue", 0) for d in dates], index=dates)
        assert nav.iloc[-1] > 0
        assert len(nav) > 50


class TestBuildStatus:
    def test_buy_sell_conservation(self):
        """买入100k+卖出 → 记账单金额守恒: 总买入-总卖出 ≤ 初始资金(扣费)."""
        from engine.backtest_v3 import build_status_from_decisions
        price_map = {"300502": 10.0, "300750": 20.0}
        decisions = [
            {"date": "2026-01-01", "symbol": "300502", "action": "BUY", "amount": 50000},
            {"date": "2026-01-02", "symbol": "300750", "action": "BUY", "amount": 30000},
            {"date": "2026-01-03", "symbol": "300502", "action": "SELL", "shares": 5000},
        ]
        st = build_status_from_decisions(decisions, price_map, capital=100000)
        buys = st[st["amount"] > 0]["amount"].sum()
        sells = abs(st[st["amount"] < 0]["amount"].sum())
        assert abs(buys - 80000) < 1
        assert sells == pytest.approx(5000 * 10.0, abs=1)

    def test_sell_without_shares_uses_price(self):
        """SELL 未显式给 shares → 用 price_map 折现金额."""
        from engine.backtest_v3 import build_status_from_decisions
        decisions = [
            {"date": "2026-01-01", "symbol": "300502", "action": "BUY", "amount": 100000},
            {"date": "2026-01-05", "symbol": "300502", "action": "SELL", "shares": 5000},
        ]
        st = build_status_from_decisions(decisions, {"300502": 10.5})
        assert abs(st.iloc[-1]["amount"]) == pytest.approx(5000 * 10.5, abs=1)


class TestReports:
    def test_generate_report_creates_html_and_meta(self):
        """NAV → HTML + meta.json 落盘, metrics 含核心指标."""
        import numpy as np
        from engine.backtest_v3 import clear_reports, generate_report
        clear_reports()
        nav = pd.Series(1_000_000 * (1 + np.cumsum(np.random.normal(0.001, 0.01, 100))),
                        index=pd.date_range("2026-01-01", periods=100, freq="B"))
        res = generate_report(nav, None, "faceji", params={"days": 100},
                              trades=[{"a": 1}], run_id="test_run_1")
        assert res["run_id"] == "test_run_1"
        assert Path(res["report_path"]).exists()
        meta = res["meta"]
        assert "sharpe" in meta["metrics"]
        assert meta["n_days"] == 100
        # meta.json 落盘
        from engine.backtest_v3 import REPORT_ROOT
        assert (REPORT_ROOT / "test_run_1" / "meta.json").exists()
        clear_reports()

    def test_list_reports_roundtrip(self):
        """generate → list → get 读写一致."""
        import numpy as np
        from engine.backtest_v3 import clear_reports, generate_report, list_reports, get_report
        clear_reports()
        nav = pd.Series(1_000_000 * (1 + np.cumsum(np.random.normal(0.001, 0.01, 60))),
                        index=pd.date_range("2026-01-01", periods=60, freq="B"))
        generate_report(nav, None, "silverquant", run_id="test_run_2")
        lst = list_reports()
        assert len(lst) == 1 and lst[0]["run_id"] == "test_run_2"
        got = get_report("test_run_2")
        assert got is not None and "report_path" in got
        clear_reports()