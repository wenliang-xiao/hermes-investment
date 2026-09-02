"""东财资金流数据源测试 (2026-09-02)

锁定: 板块资金流(board_fund_flow) + 个股资金流(fund_flow_minute)的字段解析。
依据 a-stock-data 实测: 东财 push2 是百度 PAE 失效后的零鉴权替代。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def test_em_secid():
    from data.sources.eastmoney_source import _em_secid
    assert _em_secid("600519") == "1.600519"  # 沪市
    assert _em_secid("300750") == "0.300750"  # 深市
    assert _em_secid("688256") == "1.688256"  # 科创板(沪)


def test_board_fund_flow_parsing(monkeypatch):
    """板块资金流字段解析: f12=代码/f14=名称/f62=主力净额/f184=占比/f66=超大单。"""
    import data.sources.eastmoney_source as src
    payload = {
        "data": {
            "total": 2,
            "diff": [
                {"f12": "BK0475", "f14": "国防军工", "f3": 1.31, "f62": 2744000000.0,
                 "f184": 4.86, "f204": "长城军工", "f66": 100000000.0,
                 "f72": 50000000.0, "f78": 30000000.0, "f84": 20000000.0},
                {"f12": "BK0476", "f14": "电网设备", "f3": 0.49, "f62": 1482000000.0,
                 "f184": 4.17, "f204": "远东股份"},
            ],
        }
    }
    monkeypatch.setattr(src, "_em_get", lambda *a, **k: FakeResp(payload))
    d = src.get_board_fund_flow("industry", "today", 5)
    assert d["total"] == 2
    assert d["rows"][0]["name"] == "国防军工"
    assert d["rows"][0]["main_net"] == 2744000000.0
    assert d["rows"][0]["super_large_net"] == 100000000.0
    assert d["rows"][0]["leader"] == "长城军工"


def test_stock_fund_flow_minute_parsing(monkeypatch):
    """个股资金流字段解析: klines 逗号分隔 → main_net/small_net/mid_net/large_net/super_net。"""
    import data.sources.eastmoney_source as src
    payload = {
        "data": {
            "klines": [
                "2026-09-02 09:31,1000000.0,200000.0,300000.0,400000.0,500000.0",
                "2026-09-02 09:32,-500000.0,-100000.0,-150000.0,-200000.0,-300000.0",
            ],
        }
    }
    monkeypatch.setattr(src, "_em_get", lambda *a, **k: FakeResp(payload))
    rows = src.get_stock_fund_flow_minute("600519")
    assert len(rows) == 2
    assert rows[0]["main_net"] == 1000000.0
    assert rows[1]["super_net"] == -300000.0


def test_stock_fund_flow_today_sum(monkeypatch):
    """当日主力净流入 = 分钟级 main_net 累计。"""
    import data.sources.eastmoney_source as src
    monkeypatch.setattr(src, "get_stock_fund_flow_minute",
                        lambda code: [{"main_net": 100.0}, {"main_net": -40.0}])
    assert src.get_stock_fund_flow_today("600519") == 60.0
