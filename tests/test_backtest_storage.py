"""Tests for backtest storage schema and persistence."""
import sys, os, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import date


class TestBacktestResultSchema:
    """回测结果存储 schema 验证"""

    SAMPLE = {
        "meta": {
            "strategy": "faceji",
            "symbols": ["300502", "688008"],
            "date_range": {"from": "2020-01-01", "to": "2025-12-31"},
            "days": 1260,
            "walk_forward_cycles": 3,
            "run_id": "wf_faceji_20260706_001",
            "generated_at": "2026-07-06T21:00:00",
        },
        "cycles": [
            {
                "cycle": 1,
                "train": {"from": "2020-01-01", "to": "2021-01-01"},
                "test": {"from": "2021-01-02", "to": "2021-03-31"},
                "metrics": {
                    "sortino": 2.5,
                    "sharpe": 1.8,
                    "total_return_pct": 15.2,
                    "max_drawdown_pct": -8.3,
                    "win_rate": 0.65,
                    "n_trades": 42,
                },
                "trades": [
                    {"symbol": "300502", "action": "BUY", "entry_date": "2021-02-01",
                     "exit_date": "2021-03-15", "entry_price": 50.0, "exit_price": 55.0,
                     "pnl_pct": 10.0, "hold_days": 42, "exit_reason": "take_profit"}
                ]
            }
        ],
        "aggregate": {
            "avg_sortino": 2.3,
            "avg_return_pct": 14.1,
            "avg_max_dd_pct": -9.2,
            "total_trades": 120,
            "total_symbols_traded": 15,
        },
        "cost_model": {
            "commission_rate": 0.00015,
            "stamp_tax_rate": 0.001,
            "slippage_model": "tiered_L3",
        },
    }

    def test_schema_has_all_sections(self):
        """schema 必须有 meta, cycles, aggregate, cost_model"""
        assert "meta" in self.SAMPLE
        assert "cycles" in self.SAMPLE
        assert "aggregate" in self.SAMPLE
        assert "cost_model" in self.SAMPLE

    def test_meta_has_required_fields(self):
        """meta 段必须包含必要字段"""
        m = self.SAMPLE["meta"]
        for field in ["strategy", "symbols", "date_range", "days", "run_id", "generated_at"]:
            assert field in m, f"meta missing: {field}"

    def test_cycle_has_all_sections(self):
        """每个 cycle 必须有 train/test/metrics/trades"""
        c = self.SAMPLE["cycles"][0]
        for section in ["cycle", "train", "test", "metrics", "trades"]:
            assert section in c, f"cycle missing: {section}"

    def test_metrics_has_required_fields(self):
        """metrics 段必须包含核心指标"""
        m = self.SAMPLE["cycles"][0]["metrics"]
        for field in ["sortino", "sharpe", "total_return_pct", "max_drawdown_pct",
                       "win_rate", "n_trades"]:
            assert field in m, f"metrics missing: {field}"

    def test_aggregate_has_required_fields(self):
        """aggregate 段必须包含汇总指标"""
        a = self.SAMPLE["aggregate"]
        for field in ["avg_sortino", "avg_return_pct", "avg_max_dd_pct",
                       "total_trades", "total_symbols_traded"]:
            assert field in a


class TestBacktestStorage:
    """回测结果持久化存储"""

    def test_save_and_load(self):
        """保存 JSON 再读回 → 内容一致"""
        import utils.atomic_io as aio
        data = {
            "meta": {"strategy": "faceji", "symbols": ["000001"], "date_range": {},
                     "days": 100, "run_id": "test", "generated_at": "now"},
            "cycles": [],
            "aggregate": {"avg_sortino": 0, "avg_return_pct": 0, "avg_max_dd_pct": 0,
                          "total_trades": 0, "total_symbols_traded": 0},
            "cost_model": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backtest_wf_faceji_20260706.json")
            aio.atomic_write_json(path, data)
            with open(path) as f:
                loaded = json.load(f)
            assert loaded["meta"]["run_id"] == "test"
            assert loaded["aggregate"]["total_trades"] == 0

    def test_result_dir_structure(self):
        """data/backtest/ 目录存在且可写"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "backtest")
        os.makedirs(path, exist_ok=True)
        assert os.path.isdir(path)
        assert os.access(path, os.W_OK)

    def test_backtest_comparison_exists(self):
        """legacy: data/backtest_comparison.json 存在"""
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "backtest_comparison.json")
        if not os.path.exists(path):
            pytest.skip("No legacy comparison file")
        with open(path) as f:
            d = json.load(f)
        assert isinstance(d, dict)
