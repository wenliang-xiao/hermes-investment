"""幸存者偏差补池 — build_universe_with_delisted 单元测试"""
import sys
import os
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_delisted(monkeypatch, delisted_list):
    fake = types.ModuleType("data.data_layer")
    fake.get_delisted_stocks = lambda: delisted_list
    monkeypatch.setitem(sys.modules, "data.data_layer", fake)


def test_build_universe_merges_delisted(monkeypatch):
    from engine import evaluator_fixed as ev
    _mock_delisted(monkeypatch, [
        {"code": "000001", "name": "退市A", "out_date": "2024-01-01"},
        {"code": "000002", "name": "退市B", "out_date": "2023-01-01"},
    ])
    base = ["600519", "300750"]
    result = ev.build_universe_with_delisted(base, delisted_limit=10)
    assert result[:2] == base, "基准池应在最前"
    assert "000001" in result and "000002" in result, "退市股应被纳入"
    assert len(result) == 4


def test_build_universe_sorted_by_out_date_desc(monkeypatch):
    from engine import evaluator_fixed as ev
    _mock_delisted(monkeypatch, [
        {"code": "000001", "name": "早退", "out_date": "2020-01-01"},
        {"code": "000002", "name": "晚退", "out_date": "2025-01-01"},
        {"code": "000003", "name": "中退", "out_date": "2023-01-01"},
    ])
    result = ev.build_universe_with_delisted(["600519"], delisted_limit=10)
    assert result[1] == "000002", f"最近退市应优先, got {result}"


def test_build_universe_respects_limit(monkeypatch):
    from engine import evaluator_fixed as ev
    _mock_delisted(monkeypatch, [
        {"code": f"00000{i}", "name": f"退{i}", "out_date": f"2024-0{i}-01"}
        for i in range(1, 6)
    ])
    result = ev.build_universe_with_delisted(["600519"], delisted_limit=2)
    assert len(result) == 3, f"基准1 + 退市2 = 3, got {len(result)}"


def test_build_universe_dedupes(monkeypatch):
    from engine import evaluator_fixed as ev
    _mock_delisted(monkeypatch, [
        {"code": "600519", "name": "重复", "out_date": "2024-01-01"},
    ])
    result = ev.build_universe_with_delisted(["600519"], delisted_limit=10)
    assert result == ["600519"], "重复 code 应去重"


def test_build_universe_fallback_when_fetch_fails(monkeypatch):
    from engine import evaluator_fixed as ev
    fake = types.ModuleType("data.data_layer")
    fake.get_delisted_stocks = lambda: (_ for _ in ()).throw(RuntimeError("baostock down"))
    monkeypatch.setitem(sys.modules, "data.data_layer", fake)
    result = ev.build_universe_with_delisted(["600519"], delisted_limit=10)
    assert result == ["600519"], "拉取失败时应退回基准池"
