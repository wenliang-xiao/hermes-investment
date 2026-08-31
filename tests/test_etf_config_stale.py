"""ETF 过期检测 — timestamp 距今 >7 天判定为 stale 需要重算

ETF-专项 2026-08-31:
  旧实现: 静态读取 etf_portfolio.json, 60 天前的配置默默展示, 无过期感知。
  新实现: is_etf_config_stale() 判定过期, API 层据此自动重算或回退。
  本测试锁定判定逻辑 (时间注入, 不触真实行情)。
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from dashboard.api_etf import is_etf_config_stale

NOW = datetime(2026, 8, 31, 12, 0, 0)


def _cfg(days_ago: int | None) -> dict:
    """构造 etf_portfolio.json 样式的配置 dict"""
    ts = (NOW - timedelta(days=days_ago)).isoformat() if days_ago is not None else ""
    return {"timestamp": ts, "combined": []}


class TestEtfConfigStale:
    """过期判定核心"""

    def test_fresh_within_7_days_not_stale(self):
        assert is_etf_config_stale(_cfg(days_ago=1), now=NOW) is False

    def test_exactly_7_days_not_stale(self):
        # 边界: 7 天整 → 不 stale (age > 7 才触发)
        assert is_etf_config_stale(_cfg(days_ago=7), now=NOW) is False

    def test_over_7_days_stale(self):
        assert is_etf_config_stale(_cfg(days_ago=8), now=NOW) is True

    def test_sixty_days_stale(self):
        # 真实场景: 当前文件 2026-07-02, 距 2026-08-31 = 60 天
        assert is_etf_config_stale(_cfg(days_ago=60), now=NOW) is True

    def test_missing_timestamp_stale(self):
        assert is_etf_config_stale(_cfg(days_ago=None), now=NOW) is True

    def test_bad_timestamp_stale(self):
        assert is_etf_config_stale({"timestamp": "not-a-date"}, now=NOW) is True

    def test_utc_z_suffix_normalized(self):
        # Z 后缀 (UTC) → 归一化后判定
        ts = (NOW - timedelta(days=3)).isoformat() + "Z"
        assert is_etf_config_stale({"timestamp": ts}, now=NOW) is False

    def test_naive_tzinfo_normalized(self):
        # 带时区偏移 → 剥离时区后判定
        ts = (NOW - timedelta(days=2)).isoformat() + "+08:00"
        assert is_etf_config_stale({"timestamp": ts}, now=NOW) is False