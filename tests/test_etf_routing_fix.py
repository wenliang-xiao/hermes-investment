"""测试 data_router 场内 ETF 路由修复 (2026-09-02)。

覆盖:
1. _detect_source 对场内 ETF 代码段返回 akshare_etf (不走 baostock)
2. A股/指数/港股路由不受影响
3. get_history_etf 新浪源主路径可用 (stub 网络)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.mark.parametrize(
    "code,expected",
    [
        ("159667", "akshare_etf"),   # 深市ETF
        ("510300", "akshare_etf"),   # 沪市ETF
        ("159915", "akshare_etf"),   # 深市创业板ETF
        ("513100", "akshare_etf"),   # 沪市跨境ETF
        ("588000", "akshare_etf"),   # 沪市科创50ETF
        ("520123", "akshare_etf"),   # 沪市LOF
        ("530123", "akshare_etf"),   # 沪市跨境ETF
        ("600900", "baostock"),      # A股沪市
        ("300750", "baostock"),      # A股深市创业板
        ("000001", "baostock"),      # A股深市主板
        ("0700.HK", "tencent"),     # 港股（腾讯源, 2026-08 替代 yfinance）
        ("sh.000300", "baostock"),   # 指数
    ],
)
def test_detect_source_etf_routing(code, expected):
    from data.data_router import _detect_source
    assert _detect_source(code) == expected


def test_a_code_159_priority():
    """159 开头深市 ETF 必须 sz. 前缀 (不能被 '15' 抢先成 sh.)"""
    from data.sources.baostock_source import _a_code
    assert _a_code("159667") == "sz.159667"
    assert _a_code("510300") == "sh.510300"
    assert _a_code("600900") == "sh.600900"
    assert _a_code("300750") == "sz.300750"


def test_get_history_etf_sina_main(monkeypatch):
    """get_history_etf 新浪源主路径返回结构化数据"""
    import pandas as pd

    fake_df = pd.DataFrame({
        "date": ["2026-08-28", "2026-08-31", "2026-09-01"],
        "open": [1.0, 1.1, 1.2],
        "high": [1.2, 1.3, 1.4],
        "low": [0.9, 1.0, 1.1],
        "close": [1.1, 1.2, 1.3],
        "volume": [100, 200, 300],
    })

    import akshare as ak
    monkeypatch.setattr(ak, "fund_etf_hist_sina", lambda symbol: fake_df)

    from data.sources.akshare_source import get_history_etf
    result = get_history_etf("159667", days=3)
    assert result is not None
    assert result["close"][-1] == 1.3
    assert result["symbol"] == "159667"
    assert len(result["dates"]) == 3


def test_get_history_etf_sina_fallback_em(monkeypatch):
    """新浪源异常时降级东财源"""
    import pandas as pd

    fake_df = pd.DataFrame({
        "日期": ["2026-08-31", "2026-09-01"],
        "开盘": [1.0, 1.1],
        "收盘": [1.2, 1.3],
        "成交量": [100, 200],
    })

    import akshare as ak
    monkeypatch.setattr(ak, "fund_etf_hist_sina", lambda symbol: (_ for _ in ()).throw(RuntimeError("sina down")))
    monkeypatch.setattr(ak, "fund_etf_hist_em", lambda **kw: fake_df)

    from data.sources.akshare_source import get_history_etf
    result = get_history_etf("510300", days=2)
    assert result is not None
    assert result["close"][-1] == 1.3