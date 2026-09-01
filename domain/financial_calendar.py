"""A股财务日历 — 报告期到法定披露截止日的映射。

point-in-time 财务的基础规则：回测到某日，只能看到「披露截止日 <= 该日」的财报。
此模块零第三方依赖，便于在测试中快速 import（避免 data_layer 的重依赖加载）。
"""


def financial_report_available_date(period: str) -> str:
    """报告期 → 财报法定披露截止日(A股): Q1→4/30, Q2→8/31, Q3→10/31, Q4→次年4/30.

    period 形如 "2024Q3"。比「报告期末+45/90天」更贴合 A 股真实可见时点。
    无法解析时原样返回(不崩)。
    """
    try:
        year = int(period[:4])
        q = int(period[5])
    except (ValueError, IndexError):
        return period
    if q == 1:
        return f"{year}-04-30"
    if q == 2:
        return f"{year}-08-31"
    if q == 3:
        return f"{year}-10-31"
    if q == 4:
        return f"{year + 1}-04-30"
    return period
