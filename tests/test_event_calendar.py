"""Tests for event_calendar — 未来事件日历适配器契约。

覆盖：返回契约、status 三态（ok/empty/missing）、字段与枚举校验、窗口过滤、去重。
全部 mock 掉网络与文件，快速且不依赖真实数据源。
"""
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import engine.event_calendar as ec

VALID_TYPES = {"earnings", "ipo", "rate_sanction", "central_bank"}
VALID_RISK = {"high", "med", "low"}


def future_event(days_ahead: int = 1, **kw) -> dict:
    """构造一个落在 [今天, 今天+days] 窗口内的事件。"""
    d = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
    ev = {"date": d, "symbol": "NVDA", "type": "earnings",
          "title": "NVDA 财报", "risk_level": "high"}
    ev.update(kw)
    return ev


@pytest.fixture
def no_network(monkeypatch):
    """隔离 yfinance 网络调用，返回空（无美股财报事件）。"""
    monkeypatch.setattr(ec, "_fetch_us_earnings", lambda days: [])


def set_manual(monkeypatch, available: bool, events):
    """控制手工 json 源：available=False 表示文件不存在（源不可用）。"""
    monkeypatch.setattr(ec, "_manual_available", lambda: available)
    monkeypatch.setattr(ec, "_load_manual_events", lambda: events)


class TestContractShape:
    def test_returns_dict_with_required_keys(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event()])
        result = ec.get_future_events(days=7)
        assert isinstance(result, dict)
        for key in ("status", "events", "source", "data_age"):
            assert key in result, f"缺少字段 {key}"

    def test_events_is_list(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event()])
        assert isinstance(ec.get_future_events(days=7)["events"], list)


class TestStatusEnum:
    def test_ok_when_events_exist(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event()])
        assert ec.get_future_events(days=7)["status"] == "ok"

    def test_empty_when_source_available_but_no_events(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [])  # 源在但窗口内无事件
        result = ec.get_future_events(days=7)
        assert result["status"] == "empty"
        assert result["events"] == []
        assert "manual_json" in result["source"]

    def test_missing_when_all_sources_unavailable(self, no_network, monkeypatch):
        set_manual(monkeypatch, False, [])  # 源不存在 + yfinance 空
        result = ec.get_future_events(days=7)
        assert result["status"] == "missing"
        assert result["source"] == "none"

    def test_missing_marked_with_clue(self, no_network, monkeypatch):
        set_manual(monkeypatch, False, [])
        result = ec.get_future_events(days=7)
        assert result["data_age"] or result["source"]


class TestEventFields:
    def test_each_event_has_required_fields(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event()])
        for ev in ec.get_future_events(days=7)["events"]:
            for key in ("date", "symbol", "type", "title", "risk_level"):
                assert key in ev, f"event 缺少字段 {key}: {ev}"

    def test_type_is_valid_enum(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event(type="ipo")])
        for ev in ec.get_future_events(days=7)["events"]:
            assert ev["type"] in VALID_TYPES

    def test_risk_level_is_valid_enum(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event(risk_level="med")])
        for ev in ec.get_future_events(days=7)["events"]:
            assert ev["risk_level"] in VALID_RISK


class TestWindowFilter:
    def test_past_event_filtered_out(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event(days_ahead=-3)])
        result = ec.get_future_events(days=7)
        assert result["status"] == "empty"  # 过期事件被过滤，源仍在
        assert result["events"] == []

    def test_future_event_within_window_kept(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event(days_ahead=3)])
        result = ec.get_future_events(days=7)
        assert result["status"] == "ok"
        assert len(result["events"]) == 1

    def test_event_beyond_window_filtered_out(self, no_network, monkeypatch):
        set_manual(monkeypatch, True, [future_event(days_ahead=30)])
        result = ec.get_future_events(days=7)
        assert result["events"] == []


class TestDedupe:
    def test_duplicate_events_deduped(self, no_network, monkeypatch):
        ev = future_event()
        set_manual(monkeypatch, True, [ev, dict(ev)])
        result = ec.get_future_events(days=7)
        assert len(result["events"]) == 1
