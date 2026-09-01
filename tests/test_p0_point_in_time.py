"""P0-1 时点评分 — 财务 point-in-time (2026-09-01)

financial_report_available_date: 报告期 → A股法定披露截止日映射。
这是消除"用未来财报回测过去"前视偏差的数据层基础。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_financial_report_available_date_mapping():
    from domain.financial_calendar import financial_report_available_date as f
    assert f("2024Q1") == "2024-04-30"  # 一季报 4/30
    assert f("2024Q2") == "2024-08-31"  # 半年报 8/31
    assert f("2024Q3") == "2024-10-31"  # 三季报 10/31
    assert f("2024Q4") == "2025-04-30"  # 年报次年 4/30


def test_financial_report_available_date_parse_failure():
    from domain.financial_calendar import financial_report_available_date as f
    assert f("bad") == "bad"  # 无法解析时原样返回, 不崩


def test_financial_history_asof_filter_logic():
    """as_of 过滤逻辑: 只保留「披露截止日 <= as_of」的财报。"""
    from domain.financial_calendar import financial_report_available_date as f
    periods = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    as_of = "2024-06-01"
    # 2024Q1(4/30) 已披露可见; 2024Q2(8/31)/Q3/Q4 尚未披露
    visible = [p for p in periods if f(p) <= as_of]
    assert visible == ["2024Q1"], f"as_of={as_of} 应只见 Q1, got {visible}"


def test_financial_history_asof_year_end():
    """年末视角: 年报(次年4/30)尚未披露, 只见当年 Q1/Q2/Q3。"""
    from domain.financial_calendar import financial_report_available_date as f
    periods = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    as_of = "2024-12-31"
    visible = [p for p in periods if f(p) <= as_of]
    assert visible == ["2024Q1", "2024Q2", "2024Q3"], f"got {visible}"
