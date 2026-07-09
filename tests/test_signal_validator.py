"""Tests for SignalValidator — 信号历史验证"""
import sys, os, json, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.signal_validator import SignalValidator, HISTORY_FILE


class TestSignalValidator:
    def setup_method(self):
        # 用临时文件避免污染真数据
        self.backup = HISTORY_FILE.read_bytes() if HISTORY_FILE.exists() else None

    def teardown_method(self):
        if self.backup:
            HISTORY_FILE.write_bytes(self.backup)
        elif HISTORY_FILE.exists():
            HISTORY_FILE.unlink()

    def test_record_and_validate(self):
        v = SignalValidator()
        cnt = v.record_signal("2026-07-01", "300502", "BUY", 0.72)
        assert cnt == 1
        result = v.validate()
        assert result["total_signals"] == 1
        assert result["pending"] == 1  # not verified yet

    def test_aggregate_empty(self):
        v = SignalValidator()
        agg = v.aggregate()
        assert agg["total_verified"] == 0
        assert agg["overall_accuracy"] is None

    def test_aggregate_with_verified(self):
        v = SignalValidator()
        v.record_signal("2026-07-01", "300502", "BUY", 0.72, "faceji")
        v.record_signal("2026-07-01", "000001", "SELL", 0.23, "silverquant")

        # 手动添加验证结果
        records = v.history["records"]
        records[0]["verified"] = True
        records[0]["correct"] = True
        records[1]["verified"] = True
        records[1]["correct"] = False

        agg = v.aggregate()
        assert agg["total_verified"] == 2
        assert agg["overall_accuracy"] == 0.5
        assert agg["by_score_band"]["high"]["accuracy"] == 1.0
        assert agg["by_score_band"]["low"]["accuracy"] == 0.0
