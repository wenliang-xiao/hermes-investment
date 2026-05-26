"""
动态选股宇宙构建器 v1.0

每日从 A 股全市场（5000+只）动态筛选两个候选池：
  research_universe : ~200只龙头，理解产业链景气（不用来直接买）
  buy_universe      : ~200-400只中小市值，多因子评分后找低估好票

数据源：AKShare stock_zh_a_spot_em（东方财富全市场实时行情）
筛选速度：全市场快照 <1分钟，因子评分后续在 factor_scanner 里完成
"""
import logging
import pandas as pd
from datetime import datetime
from investment_system.data.data_source_layer import get_a_share_universe_snapshot, build_candidate_universe, DataResult
from investment_system import config

logger = logging.getLogger(__name__)


RESEARCH_SECTORS = {
    "AI算力": ["300502", "301489", "002463", "688256", "603501", "688668"],
    "半导体设备": ["688012", "688041", "688328", "688536", "688120", "300604"],
    "存储/HBM": ["603986", "688110", "002156", "688008"],
    "机器人": ["300665", "300825", "300274", "002017", "688160"],
    "工业软件": ["688111", "688568", "688188"],
    "新能源": ["300750", "601012", "688599", "002129"],
    "医药CXO": ["300760", "603259", "000661", "688029"],
    "军工": ["600760", "002179", "600391", "688186"],
    "消费龙头": ["600519", "000858", "600887"],
    "金融": ["600036", "601318", "601688"],
}

_RESEARCH_UNIVERSE_CACHE: list = []
_RESEARCH_CACHE_TIME: float = 0
_RESEARCH_TTL = 3600

_BUY_UNIVERSE_CACHE: DataResult = None
_BUY_CACHE_TIME: float = 0
_BUY_TTL = 1800


def get_research_universe() -> list:
    """
    研究宇宙：覆盖各链龙头，理解产业链温度
    返回股票代码列表
    """
    import time
    global _RESEARCH_UNIVERSE_CACHE, _RESEARCH_CACHE_TIME
    if _RESEARCH_UNIVERSE_CACHE and (time.time() - _RESEARCH_CACHE_TIME) < _RESEARCH_TTL:
        return _RESEARCH_UNIVERSE_CACHE

    codes = []
    seen = set()
    for sector_codes in RESEARCH_SECTORS.values():
        for code in sector_codes:
            if code not in seen:
                seen.add(code)
                codes.append(code)

    from investment_system import config as cfg
    for chain_info in cfg.INDUSTRY_CHAINS.values():
        for code in chain_info.get("symbols", []):
            if len(code) == 6 and code.isdigit() and code not in seen:
                seen.add(code)
                codes.append(code)

    _RESEARCH_UNIVERSE_CACHE = codes
    _RESEARCH_CACHE_TIME = time.time()
    logger.info("[Universe] 研究宇宙: %d 只龙头", len(codes))
    return codes


def get_buy_universe(
    min_mktcap_yi: float = 30,
    max_mktcap_yi: float = 200,
    min_turnover_pct: float = 1.5,
    min_amount_wan: float = 3000,
) -> DataResult:
    """
    买入候选池：全市场动态筛选，按低估度排序
    返回 DataResult，data 是 DataFrame
    """
    import time
    global _BUY_UNIVERSE_CACHE, _BUY_CACHE_TIME
    if _BUY_UNIVERSE_CACHE and _BUY_UNIVERSE_CACHE.ok and (time.time() - _BUY_CACHE_TIME) < _BUY_TTL:
        return _BUY_UNIVERSE_CACHE

    result = build_candidate_universe(
        min_mktcap_yi=min_mktcap_yi,
        max_mktcap_yi=max_mktcap_yi,
        min_turnover_pct=min_turnover_pct,
        min_amount_wan=min_amount_wan,
    )

    if result.ok and result.data is not None:
        result = _apply_value_trap_filter(result)

    _BUY_UNIVERSE_CACHE = result
    _BUY_CACHE_TIME = time.time()
    return result


def _apply_value_trap_filter(result: DataResult) -> DataResult:
    """
    价值陷阱过滤：PE折价 + 基本面没坏 + 流动性达标
    在快照层面能做的基础过滤（深度财务指标在 factor_scanner 层完成）
    """
    df = result.data.copy()
    before = len(df)

    sector_pe_medians = _compute_sector_pe_median(df)
    df["sector_pe_median"] = df["code"].apply(
        lambda c: sector_pe_medians.get(_guess_sector(c), 25.0)
    )
    df["pe_discount_pct"] = (df["sector_pe_median"] - df["pe_ttm"]) / df["sector_pe_median"] * 100

    df = df[
        (df["pe_ttm"] > 3) &
        (df["pe_ttm"] < 150) &
        (df["pb"] > 0.3)
    ]

    after = len(df)
    result.data = df.reset_index(drop=True)
    result.warning = (result.warning or "") + f" | 价值陷阱过滤: {before}→{after}只"
    return result


def _compute_sector_pe_median(df: pd.DataFrame) -> dict:
    if "pe_ttm" not in df.columns:
        return {}
    return {"默认": float(df["pe_ttm"].median())}


def _guess_sector(code: str) -> str:
    if code.startswith("6008") or code.startswith("6000"):
        return "银行"
    if code.startswith("60") and int(code[:6]) < 601500:
        return "金融"
    return "默认"


def classify_by_theme(codes: list) -> dict:
    """
    将股票代码按主题分类（基于 config.DOMESTIC_SUB_THEMES）
    返回 {code: [theme1, theme2, ...]}
    """
    from investment_system import config as cfg
    theme_map = {}

    for code in codes:
        themes = []
        for theme_name, theme_info in cfg.DOMESTIC_SUB_THEMES.items():
            if code in theme_info.get("key_stocks_a", []):
                themes.append(theme_name)
        theme_map[code] = themes

    return theme_map


def get_decoupling_candidates() -> list:
    """
    中美脱钩主题候选池：从 DOMESTIC_SUB_THEMES 里提取所有 A 股标的
    按脱钩评分（decoupling_score）降序排列
    """
    from investment_system import config as cfg
    candidates = []
    seen = set()

    for theme_name, theme_info in cfg.DOMESTIC_SUB_THEMES.items():
        score = theme_info.get("decoupling_score", 5.0)
        for code in theme_info.get("key_stocks_a", []):
            if code not in seen:
                seen.add(code)
                candidates.append({
                    "code": code,
                    "theme": theme_name,
                    "decoupling_score": score,
                    "policy_driver": theme_info.get("policy_driver", ""),
                    "localization_rate": theme_info.get("localization_rate", None),
                })

    candidates.sort(key=lambda x: x["decoupling_score"], reverse=True)
    return candidates


def build_daily_scan_plan() -> dict:
    """
    构建每日扫描计划：
    - research_universe: 龙头研究池（约200只）
    - buy_universe: 买入候选池（全市场动态）
    - decoupling_candidates: 国产替代专项池
    返回各池的代码列表和元数据
    """
    research = get_research_universe()
    buy_result = get_buy_universe()
    decoupling = get_decoupling_candidates()

    buy_codes = []
    if buy_result.ok and buy_result.data is not None:
        buy_codes = buy_result.data["code"].tolist()

    logger.info("[ScanPlan] 研究池:%d 买入池:%d 脱钩池:%d",
                len(research), len(buy_codes), len(decoupling))

    return {
        "research_universe": research,
        "buy_universe_codes": buy_codes,
        "buy_universe_result": buy_result,
        "decoupling_candidates": decoupling,
        "total_to_score": len(set(research + buy_codes)),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
