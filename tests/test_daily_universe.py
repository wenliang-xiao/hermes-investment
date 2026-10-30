"""日报选股宇宙 (v4 全池 + 板块配额) 单测

覆盖旧 bug: run_daily.py:399 MAX_SCAN=18 且按宏观象限硬分配 → 半导体名额为 0,
TOP10 连续多日同一批票。新实现必须保证: 全池不截断 + 每板块有代表 + 口径唯一。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from engine.daily_universe import (
    apply_quotes,
    build_daily_universe,
    parse_qt_response,
    is_a_share,
    load_v4_pool,
    market_of,
    sector_leaders,
    SCORE_SCALE,
)


def _rows():
    return [
        {"symbol": "600519", "name": "600519", "sector": "消费", "score": 6.0, "composite": 0.60},
        {"symbol": "000858", "name": "000858", "sector": "消费", "score": 5.8, "composite": 0.58},
        {"symbol": "600036", "name": "600036", "sector": "金融", "score": 6.1, "composite": 0.61},
        {"symbol": "000001", "name": "000001", "sector": "金融", "score": 5.9, "composite": 0.59},
        {"symbol": "688981", "name": "688981", "sector": "半导体", "score": 4.5, "composite": 0.45},
        {"symbol": "002371", "name": "002371", "sector": "半导体", "score": 5.0, "composite": 0.50},
        {"symbol": "688012", "name": "688012", "sector": "半导体", "score": 5.3, "composite": 0.53},
        {"symbol": "300124", "name": "300124", "sector": "科技", "score": 5.7, "composite": 0.57},
    ]


# ─── 基础判定 ───
def test_is_a_share():
    assert is_a_share("600519") is True
    assert is_a_share("688981") is True
    assert is_a_share("0700.HK") is False
    assert is_a_share("NVDA") is False
    assert is_a_share("") is False


def test_market_of():
    assert market_of("600519") == "A"
    assert market_of("0700.HK") == "HK"
    assert market_of("NVDA") == "US"


# ─── 载入 ───
def test_load_v4_pool_parses_and_scales(tmp_path):
    p = tmp_path / "factor_daily.json"
    p.write_text(json.dumps({
        "date": "2026-10-30",
        "top_results": [
            {"symbol": "688981", "composite": 0.4452},
            {"symbol": "0941.HK", "composite": 0.6408},
        ],
    }), encoding="utf-8")
    rows = load_v4_pool(str(p))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "0941.HK"          # 按分数降序
    assert rows[0]["score"] == pytest.approx(6.41, abs=0.01)
    assert rows[0]["market"] == "HK"
    assert rows[1]["score"] == pytest.approx(0.4452 * SCORE_SCALE, abs=0.01)
    assert rows[1]["source"] == "factor_v4"


def test_load_v4_pool_missing_file():
    assert load_v4_pool("/nonexistent/x.json") == []


# ─── 板块代表榜 (核心修复: 旧实现半导体名额=0) ───
def test_sector_leaders_one_per_sector():
    leaders = sector_leaders(_rows(), per_sector=1)
    assert len(leaders) == 4
    assert {r["sector"] for r in leaders} == {"消费", "金融", "半导体", "科技"}
    assert leaders[0]["symbol"] == "600036", "代表榜按分数降序"
    assert any(r["sector"] == "半导体" for r in leaders), "半导体必须有代表"


def test_sector_leaders_per_sector_three():
    """每板块取前 3 → 覆盖全部板块, 无重复"""
    leaders = sector_leaders(_rows(), per_sector=3)
    assert len({r["symbol"] for r in leaders}) == len(leaders)
    assert len([r for r in leaders if r["sector"] == "半导体"]) == 3


# ─── 行情补充 ───
def _qt_line(name: str, sym: str, price: float, chg: float, pe: str = "") -> str:
    """构造一条腾讯 qt.gtimg 返回行 (50 字段, 关键位: [1]名 [2]代码 [3]价 [32]涨幅 [39]PE)"""
    f = ["0"] * 50
    f[0], f[1], f[2], f[3] = "1", name, sym, f"{price}"
    f[32], f[39] = f"{chg}", pe
    return 'v_' + sym + '="' + "~".join(f) + '"'


def test_parse_qt_response_strips_inner_space():
    """腾讯把"五 粮 液"带空格, 必须清洗"""
    q = parse_qt_response(_qt_line("五 粮 液", "000858", 74.62, 3.24, "15.1"))
    assert q["000858"]["name"] == "五粮液"
    assert q["000858"]["price"] == pytest.approx(74.62)
    assert q["000858"]["change_pct"] == pytest.approx(3.24)
    assert q["000858"]["pe"] == pytest.approx(15.1)


def test_parse_qt_response_skips_garbage():
    assert parse_qt_response("") == {}
    assert parse_qt_response('v_sh600519="";') == {}
    assert parse_qt_response(_qt_line("x", "600519", 0.0, 0.0)) == {}, "价格为0的行丢弃"


def test_apply_quotes_fills_fields():
    rows = _rows()[:2]
    quotes = {"600519": {"name": "贵州茅台", "price": 1500.0, "change_pct": 1.5, "pe": 22.0}}
    out = apply_quotes(rows, quotes)
    assert out[0]["name"] == "贵州茅台"
    assert out[0]["price"] == 1500.0
    assert out[0]["change_pct"] == 1.5
    assert out[1]["name"] == "000858", "补不到的行保留裸代码, 不能变成 None"


# ─── 入口 ───
def test_build_daily_universe_missing_returns_signal(tmp_path):
    rows, status = build_daily_universe(path=str(tmp_path / "none.json"))
    assert rows == [] and status == "missing"


def test_build_daily_universe_end_to_end(tmp_path):
    p = tmp_path / "factor_daily.json"
    p.write_text(json.dumps({
        "date": "2026-10-30",
        "top_results": [{"symbol": r["symbol"], "composite": r["composite"],
                         "scores": {"value": 0.4}} for r in _rows()],
    }), encoding="utf-8")
    rows, status = build_daily_universe(quote_fn=None, path=str(p), with_quotes=False)
    assert status == "complete"
    assert len(rows) == 8, "全池不截断"
    assert rows[0]["symbol"] == "600036", "主榜保持纯分数排序"
    assert {r["sector"] for r in rows} == {"消费", "金融", "半导体", "科技"}
    assert all(r["source"] == "factor_v4" for r in rows)


def test_filter_market():
    """主榜只放 A 股, 港美股不能混进来抢 TOP10"""
    from engine.daily_universe import filter_market
    rows = _rows() + [
        {"symbol": "0941.HK", "name": "中国移动", "sector": "其他", "score": 6.41, "market": "HK"},
    ]
    a = filter_market(rows, "A")
    assert all(r["symbol"] != "0941.HK" for r in a)
    assert filter_market(rows, "HK")[0]["symbol"] == "0941.HK"


def test_round_robin_universe_covers_every_sector():
    """旧实现把板块并集截前 80 只 → 地产基建/汽车整块丢失; 轮转必须每板块都有名额"""
    from engine.daily_universe import round_robin_universe
    sections = {
        "消费": [f"60000{i}" for i in range(1, 21)],
        "金融": [f"60100{i}" for i in range(1, 16)],
        "汽车": [f"60110{i}" for i in range(1, 9)],
        "地产基建": [f"60120{i}" for i in range(1, 12)],
        "半导体": [f"68800{i}" for i in range(1, 16)],
    }
    core = [f"30000{i}" for i in range(1, 41)]
    uni = round_robin_universe(sections, core, limit=40)
    assert len(uni) == 40
    assert len(set(uni)) == 40
    for sec in ("汽车", "地产基建", "半导体"):
        assert any(x in uni for x in sections[sec]), f"{sec} 必须进入扫描宇宙"


def test_round_robin_respects_limit_and_is_deterministic():
    from engine.daily_universe import round_robin_universe
    sections = {"A": ["600001", "600002", "600003"], "B": ["600004", "600005"]}
    a = round_robin_universe(sections, core=[], limit=4)
    b = round_robin_universe(sections, core=[], limit=4)
    assert a == b and len(a) == 4
