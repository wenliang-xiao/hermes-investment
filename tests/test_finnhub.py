"""Finnhub 美股数据源测试 (2026-09-02)

锁定: quote(c=价/dp=涨跌幅) + candle(c/h/l/o/v/t) 字段解析;
无 key 时返回 None(降级 yfinance)。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_rt_quote_fields(monkeypatch):
    """quote 端点: c=当前价 dp=涨跌幅% h/l/o=高低开 pc=昨收。"""
    import data.sources.finnhub_source as src
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp({
        "c": 230.5, "d": -1.2, "dp": -0.52, "h": 233.0, "l": 229.0,
        "o": 232.0, "pc": 231.7, "t": 1700000000,
    }))
    r = src.get_rt_finnhub("AAPL")
    assert r["price"] == 230.5
    assert r["change_pct"] == -0.52
    assert r["high"] == 233.0
    assert r["prev_close"] == 231.7


def test_history_candle_fields(monkeypatch):
    """candle 端点: c/h/l/o/v/t 数组, s=ok 状态。"""
    import data.sources.finnhub_source as src
    monkeypatch.setenv("FINNHUB_API_KEY", "test_key")
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp({
        "c": [100.0, 101.0], "h": [101.0, 102.0], "l": [99.0, 100.0],
        "o": [99.5, 100.5], "v": [1000000, 1100000],
        "t": [1700000000, 1700086400], "s": "ok",
    }))
    r = src.get_history_finnhub("AAPL", days=600)
    assert r["close"] == [100.0, 101.0]
    assert r["high"] == [101.0, 102.0]
    assert len(r["dates"]) == 2


def test_no_key_returns_none(monkeypatch):
    """无 FINNHUB_API_KEY 时返回 None(由上层降级 yfinance)。"""
    import data.sources.finnhub_source as src
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert src.get_rt_finnhub("AAPL") is None
    assert src.get_history_finnhub("AAPL") is None
