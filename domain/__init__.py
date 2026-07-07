"""
domain 包 — 投资领域配置 (re-export from config)

⚠️ 本文件原包含 881 行与 config.py 重复的配置数据，已于 2026-07-07 统一为 re-export。
   config.py 是唯一的配置事实源 (single source of truth)。
   历史问题：双重维护导致 CPI_STRATEGY_MAP 缺键、INDUSTRY_CHAINS 缺物理AI链。

参考: docs/review/architecture-review-2026-07-07.md P1-4 节
"""
from config import (
    MACRO_THRESHOLDS,
    FACTOR_WEIGHTS,
    CHAIN_ECONOMICS_WEIGHTS,
    PROFIT_POOL_SCORES,
    CPI_STRATEGY_MAP,
    TREND_TEMP,
    FX_PAIRS,
    BOND_MARKETS,
    GLOBAL_INDICES,
    HK_WATCHLIST,
    US_WATCHLIST,
    A_SHARE_ETF_WATCHLIST,
    REAL_ESTATE_WATCHLIST,
    COMMODITIES,
    MACRO_SECTOR_ROTATION,
    NEWS_SOURCES,
    RISK_PARAMS,
    LDS_STOCK_FILTERS,
    WATCHLIST,
    OPPORTUNITY_THEMES,
    INDUSTRY_CHAINS,
    DOMESTIC_SUB_THEMES,
    NORTHBOUND_CONFIG,
    CACHE_TTL,
)

from config import get_domestic_sub_score

__all__ = [
    "MACRO_THRESHOLDS",
    "FACTOR_WEIGHTS",
    "CHAIN_ECONOMICS_WEIGHTS",
    "PROFIT_POOL_SCORES",
    "CPI_STRATEGY_MAP",
    "TREND_TEMP",
    "FX_PAIRS",
    "BOND_MARKETS",
    "GLOBAL_INDICES",
    "HK_WATCHLIST",
    "US_WATCHLIST",
    "A_SHARE_ETF_WATCHLIST",
    "REAL_ESTATE_WATCHLIST",
    "COMMODITIES",
    "MACRO_SECTOR_ROTATION",
    "NEWS_SOURCES",
    "RISK_PARAMS",
    "LDS_STOCK_FILTERS",
    "WATCHLIST",
    "OPPORTUNITY_THEMES",
    "INDUSTRY_CHAINS",
    "DOMESTIC_SUB_THEMES",
    "NORTHBOUND_CONFIG",
    "CACHE_TTL",
    "get_domestic_sub_score",
]
