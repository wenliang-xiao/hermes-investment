"""get_financial_history 数据正确性修复测试 (2026-08-31)

背景 (data/data_layer.py):
1. _field(rs, name) 对同一 baostock 结果集连续调用两次 (gpMargin+npMargin),
   baostock 结果集是**一次性游标** → 第二次必然拿不到 → net_margin 恒 None。
   修复: _row_dict(rs) 一次取整行 dict, 字段按名读 (含 _to_float 处理 0.0/NaN)。
2. baostock liabilityToAsset **报告期单位漂移** (2025Q3=0.001281, 2026Q2=0.151931)
   → 固定乘数错。修复: 用 assetToEquity 恒等式 负债率=1-1/assetToEquity。
3. query_cash_flow_data 只返回财务比率 (无绝对现金流) → ocf/fcf 保持 None 合法降级。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


class _FakeRS:
    """模拟 baostock 结果集 — 一次性游标 (next 后不可重放)"""
    def __init__(self, fields, rows):
        self.fields = fields
        self._rows = rows
        self._i = 0

    @property
    def error_code(self):
        return "0"

    def next(self):
        if self._i >= len(self._rows):
            return False
        self._i += 1
        return True

    def get_row_data(self):
        return self._rows[self._i - 1]


def _fake_query(results_by_year_q):
    """构造 bs.query_* 的 mock — 按 (year, quarter) 返回对应的 FakeRS"""
    def _query(code, year, quarter=None, **kw):
        return results_by_year_q.get((year, quarter))
    return _query


class TestFinancialHistoryFields:
    def test_net_margin_not_lost_by_cursor_consumption(self, monkeypatch):
        """同一结果集取 gm+nm 两个字段, 两者都应取到 (修复前 nm 恒 None)"""
        import data.data_layer as dl
        # profit_data 结果只有 1 行 (baostock 惯例)
        fields = ["code", "pubDate", "statDate", "roeAvg", "npMargin", "gpMargin",
                  "netProfit", "epsTTM", "MBRevenue", "totalShare", "liqaShare"]
        row = ["sh.600519", "2026-08-15", "2026-06-30", "0.179543", "0.507516",
               "0.895552", "46033330566.78", "65.14", "92278072083.21", "12.5e8", "12.5e8"]
        rs_profit = _FakeRS(fields, [row])
        # 直接测 _row_dict 核心语义: 一次取整行, 字段按名读
        from data.data_layer import get_financial_history
        monkeypatch.setattr(dl, "_bs_login", lambda: None)

        # 构造 4 个接口的返回 (dupont/profit/balance/growth/cash_flow)
        rs_d = _FakeRS(["code", "dupontROE"], [["sh.600519", "0.179543"]])
        rs_p = _FakeRS(fields, [row])
        rs_b = _FakeRS(["code", "liabilityToAsset", "assetToEquity"],
                       [["sh.600519", "0.151931", "1.179150"]])
        rs_g = _FakeRS(["code", "YOYNI"], [["sh.600519", "-0.0203"]])
        rs_cf = _FakeRS(["code", "CFOToOR"], [["sh.600519", "0.297359"]])

        calls = {}

        def _bs_query_with_timeout(func, *args, timeout=25, **kwargs):
            year = kwargs.get("year"); quarter = kwargs.get("quarter")
            fname = func.__name__
            calls.setdefault(fname, []).append((year, quarter))
            if fname == "query_dupont_data":
                return rs_d
            if fname == "query_profit_data":
                return rs_p
            if fname == "query_balance_data":
                return rs_b
            if fname == "query_growth_data":
                return rs_g
            if fname == "query_cash_flow_data":
                return rs_cf
            return _FakeRS(["code"], [])

        monkeypatch.setattr(dl, "_bs_query_with_timeout", _bs_query_with_timeout)
        monkeypatch.setattr(dl, "_bs_code", lambda s: "sh." + s)

        hist = get_financial_history("600519", quarters=1)

        assert len(hist) == 1
        h = hist[0]
        assert h["net_margin"] == pytest.approx(50.75, abs=0.05), f"net_margin应取到50.75, 实得{h['net_margin']}"
        assert h["gross_margin"] == pytest.approx(89.56, abs=0.05)
        assert h["roe"] == pytest.approx(17.95, abs=0.05)

    def test_debt_ratio_uses_asset_to_equity_identity(self, monkeypatch):
        """debt_ratio 用 1-1/assetToEquity 计算 (免疫 liabilityToAsset 单位漂移)"""
        import data.data_layer as dl
        monkeypatch.setattr(dl, "_bs_login", lambda: None)
        dl._FIN_CACHE.clear()  # 清缓存避免跨测试污染
        from data.data_layer import get_financial_history

        rs_d = _FakeRS(["code", "dupontROE"], [["sh.600519", "0.179543"]])
        rs_p = _FakeRS(["code", "npMargin"], [["sh.600519", "0.507516"]])
        rs_b = _FakeRS(["code", "liabilityToAsset", "assetToEquity"],
                       [["sh.600519", "0.001281", "1.146904"]])  # 2025Q3 漂移单位
        rs_g = _FakeRS(["code", "YOYNI"], [["sh.600519", "-0.02"]])
        rs_cf = _FakeRS(["code", "CFOToOR"], [["sh.600519", "0.29"]])

        def _bs_query_with_timeout(func, *args, timeout=25, **kwargs):
            fname = func.__name__
            if fname == "query_dupont_data":
                return rs_d
            if fname == "query_profit_data":
                return rs_p
            if fname == "query_balance_data":
                return rs_b
            if fname == "query_growth_data":
                return rs_g
            return rs_cf

        monkeypatch.setattr(dl, "_bs_query_with_timeout", _bs_query_with_timeout)
        monkeypatch.setattr(dl, "_bs_code", lambda s: "sh." + s)

        hist = get_financial_history("600519", quarters=1)
        h = hist[0]
        # 漂移单位下 liabilityToAsset=0.001281 ×100=0.13% 错误; assetToEquity 反推=12.81%
        assert h["debt_ratio"] == pytest.approx(12.81, abs=0.1), f"实得{h['debt_ratio']}"

    def test_ocf_fcf_none_when_cash_flow_ratios_only(self, monkeypatch):
        """query_cash_flow_data 只给比率 → ocf/fcf None 合法降级 (不崩溃)"""
        import data.data_layer as dl
        monkeypatch.setattr(dl, "_bs_login", lambda: None)
        dl._FIN_CACHE.clear()  # 清缓存避免跨测试污染
        from data.data_layer import get_financial_history

        rs_d = _FakeRS(["code", "dupontROE"], [["sh.600519", "0.179543"]])
        rs_p = _FakeRS(["code", "npMargin"], [["sh.600519", "0.507516"]])
        rs_b = _FakeRS(["code", "assetToEquity"], [["sh.600519", "1.179150"]])
        rs_g = _FakeRS(["code", "YOYNI"], [["sh.600519", "-0.02"]])
        rs_cf = _FakeRS(["code", "CFOToOR", "CFOToNP"], [["sh.600519", "0.29", "0.57"]])

        def _bs_query_with_timeout(func, *args, timeout=25, **kwargs):
            fname = func.__name__
            if fname == "query_dupont_data":
                return rs_d
            if fname == "query_profit_data":
                return rs_p
            if fname == "query_balance_data":
                return rs_b
            if fname == "query_growth_data":
                return rs_g
            return rs_cf

        monkeypatch.setattr(dl, "_bs_query_with_timeout", _bs_query_with_timeout)
        monkeypatch.setattr(dl, "_bs_code", lambda s: "sh." + s)

        hist = get_financial_history("600519", quarters=1)
        h = hist[0]
        assert h["ocf"] is None
        assert h["fcf"] is None
        # 其他字段不受影响
        assert h["net_margin"] == pytest.approx(50.75, abs=0.05)
        assert h["debt_ratio"] == pytest.approx(15.19, abs=0.1)

    def test_to_float_handles_zero_and_nan(self):
        """_to_float: 0.0 是有效值 (旧实现 if v: 把 0.0 当 falsy 丢字段)"""
        import data.data_layer as dl
        dl._FIN_CACHE.clear()  # 清缓存避免跨测试污染
        from data.data_layer import get_financial_history
        # _to_float 是闭包内部函数, 通过行为验证: 构造 roe=0 的行不应被丢弃
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(dl, "_bs_login", lambda: None)

        rs_d = _FakeRS(["code", "dupontROE"], [["sh.600519", "0.0"]])
        rs_p = _FakeRS(["code", "npMargin", "gpMargin"], [["sh.600519", "0.1", "0.2"]])
        rs_b = _FakeRS(["code", "assetToEquity"], [["sh.600519", "1.18"]])
        rs_g = _FakeRS(["code", "YOYNI"], [["sh.600519", "0.03"]])
        rs_cf = _FakeRS(["code", "CFOToOR"], [["sh.600519", "0.2"]])

        def _bs_query_with_timeout(func, *args, timeout=25, **kwargs):
            fname = func.__name__
            return {"query_dupont_data": rs_d, "query_profit_data": rs_p,
                    "query_balance_data": rs_b, "query_growth_data": rs_g,
                    "query_cash_flow_data": rs_cf}.get(fname, _FakeRS(["code"], []))

        monkeypatch.setattr(dl, "_bs_query_with_timeout", _bs_query_with_timeout)
        monkeypatch.setattr(dl, "_bs_code", lambda s: "sh." + s)
        hist = get_financial_history("600519", quarters=1)
        monkeypatch.undo()
        assert len(hist) == 1
        assert hist[0]["roe"] == pytest.approx(0.0, abs=1e-9)  # 0.0 保留而非 None