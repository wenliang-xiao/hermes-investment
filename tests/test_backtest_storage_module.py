"""Tests for analysis/backtest_storage — persistence layer."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from analysis.backtest_storage import (
    save_result, list_results, load_result, delete_result,
    BACKTEST_DIR,
)

SAMPLE = {
    "meta": {
        "strategy": "faceji",
        "symbols": ["300502", "688008"],
        "date_range": {"from": "2020-01-01", "to": "2025-12-31"},
        "days": 1260,
        "walk_forward_cycles": 3,
        "run_id": "wf_faceji_test001",
        "generated_at": "2026-07-06T21:00:00",
    },
    "cycles": [],
    "aggregate": {
        "avg_sortino": 2.3,
        "avg_return_pct": 14.1,
        "avg_max_dd_pct": -9.2,
        "total_trades": 120,
        "total_symbols_traded": 15,
    },
    "cost_model": {"commission_rate": 0.00015},
}


class TestBacktestStorage:
    def test_save_creates_file(self):
        """保存后文件存在"""
        path = save_result("faceji", SAMPLE)
        assert os.path.exists(path)

    def test_save_and_load_roundtrip(self):
        """保存→加载→内容一致"""
        path = save_result("faceji", SAMPLE)
        loaded = load_result("wf_faceji_test001")
        assert loaded is not None
        assert loaded["meta"]["strategy"] == "faceji"
        assert loaded["aggregate"]["avg_sortino"] == 2.3

    def test_list_results(self):
        """list_results 返回保存的结果摘要"""
        save_result("silverquant", SAMPLE | {"meta": {**SAMPLE["meta"],
                    "strategy": "silverquant", "run_id": "wf_sq_test001"}})
        results = list_results()
        assert len(results) >= 1
        all_sq = [r for r in results if r["strategy"] == "silverquant"]
        assert len(all_sq) >= 1

    def test_list_results_filtered(self):
        """按策略筛选"""
        sq_results = list_results(strategy="silverquant")
        assert all(r["strategy"] == "silverquant" for r in sq_results)

    def test_delete(self):
        """删除后文件不存在"""
        save_result("faceji", SAMPLE | {"meta": {**SAMPLE["meta"],
                    "run_id": "wf_faceji_del"}})
        assert delete_result("wf_faceji_del") is True
        assert load_result("wf_faceji_del") is None

    def test_auto_id_generation(self):
        """不传 run_id 时自动生成"""
        result = {"meta": {"strategy": "faceji", "symbols": [], "date_range": {},
                  "days": 0}, "cycles": [], "aggregate": {}, "cost_model": {}}
        path = save_result("faceji", result)
        assert "bt_faceji_" in os.path.basename(path)
        assert path.endswith(".json")

    def test_load_nonexistent(self):
        """不存在的 run_id 返回 None"""
        assert load_result("nonexistent_12345") is None

    def test_list_empty_cleanup(self):
        """测试结束后清理测试文件"""
        for r in list_results():
            rid = r.get("run_id") or ""
            if "test001" in rid or "wf_sq_test001" in rid:
                delete_result(rid)
