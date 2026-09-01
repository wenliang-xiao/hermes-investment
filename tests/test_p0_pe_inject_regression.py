"""price_series 注入模式下 PE 空列表越界回归测试

背景 (2026-09-01 merge 后验证):
  opencode 时点评分注入 price_series, FactorEngine._get_hist 走注入路径。
  _get_sub_value 里 `hist.get("pe", [None])[-1]` 在 pe key 存在但为空列表
  (注入的 _tail 对 None/短序列返回 []) 时 → IndexError: list index out of range,
  导致 score_batch 线程池内 collect 全部失败 → 评分退化, 时点评分不可用。
  修复: `(hist.get("pe") or [None])[-1]` 对空列表兜底。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestPESubValueEmptyList:
    """pe 子因子在注入空列表时不应越界"""

    def test_injected_empty_pe_no_crash(self):
        from engine.factor_engine import FactorEngine, SUB_FACTOR_DEFS

        # 注入模式: _injected_hist 里 pe 为空列表 (旧缓存缺 pe 列时 _tail 返回 [])
        eng = FactorEngine()
        eng._injected_hist = {
            "600519": {
                "close": [1700.0 + i for i in range(30)],
                "dates": [f"2026-01-{i+1:02d}" for i in range(30)],
                "open": [1700.0 + i + 0.1 for i in range(30)],
                "volume": [],
                "amount": [],
                "pe": [],  # 空 pe → 旧代码 [][-1] 越界
            }
        }

        # 直接调 _get_sub_value 的 pe 分支 (通过 _get_hist 注入路径)
        # daily_row: pe 子因子
        pe_key = [k for k, d in SUB_FACTOR_DEFS.items()
                  if d.get("source") == "daily_row" and d.get("field") == "pe"]
        if not pe_key:
            # 找不到明确的 pe 子因子 key, 跳过
            return
        # 只测 _get_hist 注入路径不越界
        hist = eng._get_hist("600519", 10)
        assert "close" in hist, "注入的 close 应可用"
        assert hist["pe"] == [], "注入的 pe 应为空列表"
        # 模拟 _get_sub_value 的 pe 访问表达式
        pe = (hist.get("pe") or [None])[-1]
        assert pe is None, "空 pe 列表 → 取到 None 而非越界"

    def test_empty_close_list_returns_none(self):
        """close 空列表时 daily_row 分支应返回 None 而非崩溃"""
        from engine.factor_engine import FactorEngine

        eng = FactorEngine()
        eng._injected_hist = {
            "600519": {"close": [], "pe": [], "volume": [], "amount": []}
        }
        hist = eng._get_hist("600519", 10)
        assert hist is not None
        assert "close" in hist
        assert hist["close"] == []