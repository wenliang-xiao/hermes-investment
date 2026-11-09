"""标的显示名解析回归 — 面板不允许出现 "688012 688012" 这种代码重复。

背景: 因子快照 factor_daily/scan_snapshot 的 name 字段曾被写成 symbol 本身,
前端 `${s.symbol} ${s.name}` 就渲染成 "688012 688012"。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.api_execution import _display_name
from engine.factor_engine import _stock_name


def test_display_name_falls_back_to_local_map():
    # 快照里 name 就是代码 → 必须解析成中文名
    assert _display_name("688012", "688012") == "中微公司"


def test_display_name_keeps_real_name():
    assert _display_name("中微公司", "688012") == "中微公司"


def test_display_name_unknown_code_returns_symbol():
    # 未知代码不抛异常, 回落代码本身
    assert _display_name(None, "999999") == "999999"


def test_stock_name_matches_display_name():
    assert _stock_name("688012") == "中微公司"
    assert _stock_name("999999") == "999999"
