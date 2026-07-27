"""
面基交易系统 — 扫描计划构建器

提供 build_daily_scan_plan() 供 run_weekly.py 调用。
原实现已归档至 _archive/，这里保留一个轻量版本保证兼容。
"""
import sys, os

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_DIR)

try:
    from investment_system import config as cfg
    WATCHLIST = cfg.WATCHLIST
except Exception:
    WATCHLIST = {}

def build_daily_scan_plan():
    """
    构建每日扫描计划。
    返回包含 research_universe、buy_universe_codes 等字段的 dict。
    """
    codes = list(WATCHLIST.keys())
    return {
        "research_universe": codes,
        "buy_universe_codes": codes,
        "total": len(codes),
    }
