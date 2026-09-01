"""netvalue 中间点快照价修复 + 归一化测试 (2026-08-31)

背景 (api_portfolio.py):
1. 逐日重建净值时中间点用 entry_price(成本价) 计算持仓市值 → 浮盈不随市价变化。
   修复: _build_price_snapshot_map 预构建 {symbol: {date: close}} 快照价,
   中间点用当日快照价 mark-to-market (无行情降级成本价)。
2. P2: 净值统一归一化到首日=1.0 (相对收益曲线, 与沪深300基准同尺度可叠加)。

注意: 末点被 total_value 校准是 P0-6 设计; 用 3 天序列让目标日成为中间点。
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture
def signals_3day(tmp_path):
    """1 策略 3 天: 08-13 买入600519@1500(100股), 08-14 买入002594@100(50股), 08-15 买入300750@200(10股)。"""
    data = {
        "date": "2026-08-15",
        "portfolios": {
            "faceji": {
                "label": "面基", "cash": 843000.0, "capital": 1000000.0,
                "total_value": 850000.0, "total_invested": 157000.0,
                "total_return": -15.0,
            }
        },
        "positions": {"faceji": {}},
        "trade_history": {
            "faceji": [
                {"date": "2026-08-13", "symbol": "600519", "action": "买入",
                 "price": 1500.0, "quantity": 100, "pnl": 0},
                {"date": "2026-08-14", "symbol": "002594", "action": "买入",
                 "price": 100.0, "quantity": 50, "pnl": 0},
                {"date": "2026-08-15", "symbol": "300750", "action": "买入",
                 "price": 200.0, "quantity": 10, "pnl": 0},
            ]
        },
    }
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "trading_signals.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _stub_history(price_map: dict[str, dict[str, float]]):
    """替换 data_router.get_history — {symbol: {date: close}} → dates/closes"""
    import data.data_router as dr

    def _get_history(symbol, days=1200):
        if symbol not in price_map:
            return None
        m = price_map[symbol]
        dates = sorted(m.keys())
        closes = [m[d] for d in dates]
        return {"dates": dates, "close": closes}

    dr.get_history = _get_history


class TestNetvalueSnapshotPrice:
    def test_midpoint_uses_snapshot_price_not_cost(self, monkeypatch, signals_3day):
        """08-14 中间点: 600519 市值用快照价 1700 (非成本 1500), 归一化后仍反映+20k浮盈"""
        import dashboard.api_portfolio as ap
        monkeypatch.setattr(ap, "ROOT", signals_3day)

        _stub_history({
            "600519": {"2026-08-13": 1500.0, "2026-08-14": 1700.0},
            "002594": {"2026-08-14": 100.0},
            # 基准 stub: sh.000300 无行情 → 基准跳过 (避免真实网络)
        })

        r = ap.api_v2_portfolio_netvalue()
        assert "error" not in r, r.get("error")
        s = r["series"][0]
        labels, values = s["labels"], s["values"]
        assert "2026-08-13" in labels and "2026-08-14" in labels
        d13 = labels.index("2026-08-13")
        d14 = labels.index("2026-08-14")
        # 归一化到首日=1.0
        assert values[d13] == pytest.approx(1.0, abs=1e-4), f"08-13 首日应=1.0, 实得{values[d13]}"
        # 08-14 (中间点): (100×1700 + 50×100 + 1000000)/1,150,000 = 1.02174
        assert values[d14] == pytest.approx(1_175_000 / 1_150_000, abs=1e-4), f"实得{values[d14]}"

    def test_missing_symbol_falls_back_to_cost(self, monkeypatch, signals_3day):
        """002594 无行情 → 中间点 08-14 用成本价, 不崩溃"""
        import dashboard.api_portfolio as ap
        monkeypatch.setattr(ap, "ROOT", signals_3day)

        _stub_history({
            "600519": {"2026-08-13": 1500.0, "2026-08-14": 1550.0},
        })

        r = ap.api_v2_portfolio_netvalue()
        s = r["series"][0]
        labels, values = s["labels"], s["values"]
        d14 = labels.index("2026-08-14")
        # 08-14: (100×1550 + 50×100 + 1000000)/1,150,000 = 1.00870
        assert values[d14] == pytest.approx(1_160_000 / 1_150_000, abs=1e-4), f"实得{values[d14]}"

    def test_snapshot_map_only_covers_traded_symbols(self, monkeypatch):
        """_build_price_snapshot_map 只拉 trade_history 出现过的 symbol"""
        import dashboard.api_portfolio as ap
        import data.data_router as dr
        called = []
        orig = dr.get_history

        def _spy(symbol, days=1200):
            called.append(symbol)
            return {"dates": ["2026-08-13"], "close": [1500.0]}

        dr.get_history = _spy
        try:
            m = ap._build_price_snapshot_map({
                "faceji": [{"date": "2026-08-13", "symbol": "600519"}],
            })
            assert "600519" in m
            assert len(called) == 1 and called[0] == "600519", f"只应拉出现过的, 实拉{called}"
            m2 = ap._build_price_snapshot_map({"faceji": []})
            assert m2 == {}
        finally:
            dr.get_history = orig

    def test_benchmark_series_appended_when_hs300_available(self, monkeypatch, signals_3day):
        """沪深300行情可得 → 追加 benchmark series (归一化 1.0 起点, flag 标记)"""
        import dashboard.api_portfolio as ap
        monkeypatch.setattr(ap, "ROOT", signals_3day)

        # 行情: 策略标的 + 基准 sh.000300 (3 天映射)
        _stub_history({
            "600519": {"2026-08-13": 1500.0, "2026-08-14": 1500.0},
            "002594": {"2026-08-14": 100.0},
        })
        import data.data_router as dr
        orig = dr.get_history
        stub = dr.get_history

        def _get_history(symbol, days=1200):
            if symbol == "sh.000300":
                return {"dates": ["2026-08-13", "2026-08-14", "2026-08-15"],
                        "close": [4000.0, 4100.0, 4020.0]}
            return stub(symbol, days)

        dr.get_history = _get_history
        try:
            r = ap.api_v2_portfolio_netvalue()
        finally:
            dr.get_history = orig

        bm_series = [s for s in r["series"] if s.get("benchmark")]
        assert len(bm_series) == 1, f"应有基准 series, 实得{[s['name'] for s in r['series']]}"
        bm = bm_series[0]
        assert bm["name"] == "沪深300"
        assert bm["values"][0] == pytest.approx(1.0, abs=1e-4)
        assert bm["values"][-1] == pytest.approx(4020.0 / 4000.0, abs=1e-4)
        assert bm["total_return"] == pytest.approx((4020.0 / 4000.0 - 1) * 100, abs=0.1)