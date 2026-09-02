"""腾讯港股数据源测试 (2026-09-02)

锁定: get_history_hk(ifzq 字段顺序 [date,open,close,high,low,volume]) +
get_rt_hk(qt.gtimg 港股字段 [3]=价/[32]=涨跌幅/[39]=PE)。
港股字段布局与 A 股不同, 单独校准。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeResp:
    def __init__(self, content_bytes, text=""):
        self.content = content_bytes
        self.text = text

    def json(self):
        import json
        return json.loads(self.content.decode("utf-8"))


def test_get_history_hk_field_order(monkeypatch):
    """ifzq K线字段顺序是 [date, open, close, high, low, volume](close 在第3位)。"""
    import data.sources.akshare_source as src
    import json
    payload = {"data": {"hk00700": {"qfqday": [
        ["2026-09-01", "440.0", "439.0", "442.0", "438.0", "20000000.0"],
        ["2026-09-02", "439.0", "438.2", "441.4", "435.0", "21341328.0"],
    ]}}}
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp(
        json.dumps(payload).encode("utf-8")))
    r = src.get_history_hk("0700.HK")
    assert r["close"][-1] == 438.2, "close 在第3位"
    assert r["high"][-1] == 441.4, "high 在第4位"
    assert r["low"][-1] == 435.0, "low 在第5位"
    assert r["open"][-1] == 439.0, "open 在第2位"
    assert r["volume"][-1] == 21341328.0


def test_get_rt_hk_fields(monkeypatch):
    """港股快照字段: [3]=现价 [32]=涨跌幅% [39]=PE。"""
    import data.sources.akshare_source as src
    fields = [""] * 60
    fields[1] = "腾讯控股"
    fields[3] = "438.200"
    fields[6] = "21341328.0"
    fields[32] = "-0.72"
    fields[37] = "9336637626.700"
    fields[39] = "16.02"
    raw = 'v_hk00700="' + "~".join(fields) + '~"'
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp(
        raw.encode("gbk")))
    r = src.get_rt_hk("0700.HK")
    assert r["price"] == 438.2
    assert r["change_pct"] == -0.72
    assert r["pe"] == 16.02
    assert r["volume"] == 21341328.0


def test_router_hk_routes_to_tencent():
    """data_router 的 .HK 应路由到 tencent(而非 yfinance)。"""
    from data import data_router
    assert data_router._detect_source("0700.HK") == "tencent"
