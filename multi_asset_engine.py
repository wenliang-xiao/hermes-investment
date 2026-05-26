"""
多资产轮动引擎 v1.0 — 风险调整收益最大化

设计原则（来自面基+LDS+Bridgewater）：
  - 赚钱不看裸收益，看夏普比率（收益/回撤/波动均衡）
  - 宏观象限决定各资产类别的"顺风/逆风"
  - 动量信号决定类别内的相对强弱
  - 风险平价思想决定仓位分配（不是等权，是等风险贡献）

三层架构：
  Layer 1 宏观过滤    CPI/PMI/趋势 → 哪些大类顺风（绿）/中性（黄）/逆风（红）
  Layer 2 动量评分    各资产的风险调整动量得分（Sharpe-like，多周期综合）
  Layer 3 配置建议    顺风类别内取前N，按风险平价或等权分配

覆盖资产类别：
  A股ETF（宽基/主题/策略/债券/商品）
  美股ETF（宽基/行业/债券/商品/货币）
  港股（跨境/中概）
  黄金/白银/原油/铜等大宗
  美元/人民币/日元汇率
  中国公募基金（主动/指数）
"""

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 全资产宇宙定义（覆盖所有可交易品类）
# ═══════════════════════════════════════════════════════════════

FULL_ASSET_UNIVERSE = {

    # ── A股宽基ETF（核心底仓候选）──
    "510050": {"name": "上证50ETF",       "class": "A股股票", "sub": "A股宽基",    "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.3, "衰退期": 0.2}, "src": "akshare"},
    "510300": {"name": "沪深300ETF",      "class": "A股股票", "sub": "A股宽基",    "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.3, "衰退期": 0.2}, "src": "akshare"},
    "510500": {"name": "中证500ETF",      "class": "A股股票", "sub": "A股中盘",    "macro_fit": {"扩张期": 0.9, "复苏期": 0.7, "过热期": 0.3, "衰退期": 0.1}, "src": "akshare"},
    "159845": {"name": "中证1000ETF",     "class": "A股股票", "sub": "A股小盘",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.7, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},
    "588000": {"name": "科创50ETF",       "class": "A股股票", "sub": "A股科技",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},
    "159915": {"name": "创业板ETF",       "class": "A股股票", "sub": "A股成长",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},

    # ── A股主题ETF（产业链主题）──
    "512480": {"name": "半导体ETF",       "class": "A股股票", "sub": "A股科技",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.7, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},
    "512660": {"name": "军工ETF",         "class": "A股股票", "sub": "A股防御成长","macro_fit": {"扩张期": 0.8, "复苏期": 0.7, "过热期": 0.5, "衰退期": 0.6}, "src": "akshare"},
    "159819": {"name": "人工智能ETF",     "class": "A股股票", "sub": "A股科技",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},
    "159995": {"name": "芯片ETF",         "class": "A股股票", "sub": "A股科技",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},
    "515220": {"name": "数字经济ETF",     "class": "A股股票", "sub": "A股科技",    "macro_fit": {"扩张期": 0.9, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},

    # ── A股策略ETF（红利/低波/价值）──
    "512890": {"name": "红利低波ETF",     "class": "A股股票", "sub": "A股红利",    "macro_fit": {"扩张期": 0.4, "复苏期": 0.6, "过热期": 0.7, "衰退期": 0.9}, "src": "akshare"},
    "510880": {"name": "红利ETF",         "class": "A股股票", "sub": "A股红利",    "macro_fit": {"扩张期": 0.4, "复苏期": 0.6, "过热期": 0.7, "衰退期": 0.9}, "src": "akshare"},
    "563020": {"name": "红利成长ETF",     "class": "A股股票", "sub": "A股红利",    "macro_fit": {"扩张期": 0.6, "复苏期": 0.7, "过热期": 0.5, "衰退期": 0.8}, "src": "akshare"},

    # ── A股跨境ETF（连接全球）──
    "513100": {"name": "纳指100ETF",      "class": "A股股票", "sub": "A股跨境",    "macro_fit": {"扩张期": 1.0, "复苏期": 0.7, "过热期": 0.3, "衰退期": 0.1}, "src": "akshare"},
    "513500": {"name": "标普500ETF",      "class": "A股股票", "sub": "A股跨境",    "macro_fit": {"扩张期": 0.9, "复苏期": 0.7, "过热期": 0.3, "衰退期": 0.2}, "src": "akshare"},
    "513050": {"name": "中概互联ETF",     "class": "A股股票", "sub": "A股跨境",    "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.3, "衰退期": 0.1}, "src": "akshare"},
    "159632": {"name": "恒生科技ETF",     "class": "A股股票", "sub": "A股跨境",    "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "akshare"},

    # ── A股债券ETF（防守仓）──
    "511010": {"name": "国债ETF",         "class": "债券",    "sub": "中国国债",   "macro_fit": {"扩张期": 0.2, "复苏期": 0.5, "过热期": 0.3, "衰退期": 0.9}, "src": "akshare"},
    "511520": {"name": "政金债ETF",       "class": "债券",    "sub": "中国政策债", "macro_fit": {"扩张期": 0.2, "复苏期": 0.5, "过热期": 0.3, "衰退期": 0.9}, "src": "akshare"},
    "159926": {"name": "30年国债ETF",     "class": "债券",    "sub": "中国长债",   "macro_fit": {"扩张期": 0.1, "复苏期": 0.4, "过热期": 0.2, "衰退期": 1.0}, "src": "akshare"},
    "511090": {"name": "10年国债ETF",     "class": "债券",    "sub": "中国国债",   "macro_fit": {"扩张期": 0.2, "复苏期": 0.5, "过热期": 0.2, "衰退期": 0.9}, "src": "akshare"},

    # ── A股商品ETF（通胀对冲）──
    "518880": {"name": "黄金ETF",         "class": "商品",    "sub": "贵金属",     "macro_fit": {"扩张期": 0.3, "复苏期": 0.5, "过热期": 0.8, "衰退期": 0.7}, "src": "akshare"},
    "159985": {"name": "豆粕ETF",         "class": "商品",    "sub": "农产品",     "macro_fit": {"扩张期": 0.5, "复苏期": 0.5, "过热期": 0.8, "衰退期": 0.3}, "src": "akshare"},
    "162411": {"name": "华宝油气ETF",     "class": "商品",    "sub": "能源",       "macro_fit": {"扩张期": 0.6, "复苏期": 0.5, "过热期": 0.9, "衰退期": 0.2}, "src": "akshare"},

    # ── 美股宽基ETF（全球配置）──
    "SPY":    {"name": "标普500",         "class": "美股股票", "sub": "美股宽基",   "macro_fit": {"扩张期": 0.9, "复苏期": 0.7, "过热期": 0.4, "衰退期": 0.2}, "src": "yfinance"},
    "QQQ":    {"name": "纳指100",         "class": "美股股票", "sub": "美股成长",   "macro_fit": {"扩张期": 1.0, "复苏期": 0.7, "过热期": 0.3, "衰退期": 0.1}, "src": "yfinance"},
    "IWM":    {"name": "罗素2000小盘",    "class": "美股股票", "sub": "美股小盘",   "macro_fit": {"扩张期": 1.0, "复苏期": 0.7, "过热期": 0.3, "衰退期": 0.1}, "src": "yfinance"},
    "VEA":    {"name": "发达市场ETF",     "class": "美股股票", "sub": "全球股票",   "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.3, "衰退期": 0.2}, "src": "yfinance"},
    "EEM":    {"name": "新兴市场ETF",     "class": "美股股票", "sub": "新兴市场",   "macro_fit": {"扩张期": 0.9, "复苏期": 0.6, "过热期": 0.3, "衰退期": 0.1}, "src": "yfinance"},

    # ── 美股行业ETF（板块轮动）──
    "SMH":    {"name": "半导体ETF",       "class": "美股股票", "sub": "美股科技",   "macro_fit": {"扩张期": 1.0, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "yfinance"},
    "XLK":    {"name": "科技板块",        "class": "美股股票", "sub": "美股科技",   "macro_fit": {"扩张期": 1.0, "复苏期": 0.6, "过热期": 0.2, "衰退期": 0.1}, "src": "yfinance"},
    "XLE":    {"name": "能源板块",        "class": "美股股票", "sub": "美股周期",   "macro_fit": {"扩张期": 0.6, "复苏期": 0.5, "过热期": 1.0, "衰退期": 0.2}, "src": "yfinance"},
    "XLV":    {"name": "医疗健康",        "class": "美股股票", "sub": "美股防御",   "macro_fit": {"扩张期": 0.4, "复苏期": 0.6, "过热期": 0.6, "衰退期": 0.8}, "src": "yfinance"},
    "XLU":    {"name": "公用事业",        "class": "美股股票", "sub": "美股防御",   "macro_fit": {"扩张期": 0.2, "复苏期": 0.4, "过热期": 0.5, "衰退期": 0.9}, "src": "yfinance"},
    "XLP":    {"name": "必需消费",        "class": "美股股票", "sub": "美股防御",   "macro_fit": {"扩张期": 0.3, "复苏期": 0.5, "过热期": 0.5, "衰退期": 0.9}, "src": "yfinance"},
    "XLF":    {"name": "金融板块",        "class": "美股股票", "sub": "美股周期",   "macro_fit": {"扩张期": 0.7, "复苏期": 0.7, "过热期": 0.5, "衰退期": 0.2}, "src": "yfinance"},

    # ── 美股REIT（另类资产）──
    "VNQ":    {"name": "美国REITs",       "class": "REIT",    "sub": "美国地产",   "macro_fit": {"扩张期": 0.5, "复苏期": 0.6, "过热期": 0.3, "衰退期": 0.6}, "src": "yfinance"},
    "EQIX":   {"name": "Equinix数据中心", "class": "REIT",    "sub": "数据中心",   "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.4, "衰退期": 0.5}, "src": "yfinance"},

    # ── 美债（收益率环境关键）──
    "TLT":    {"name": "20年+美债",       "class": "债券",    "sub": "美国长债",   "macro_fit": {"扩张期": 0.1, "复苏期": 0.4, "过热期": 0.1, "衰退期": 1.0}, "src": "yfinance"},
    "IEF":    {"name": "7-10年美债",      "class": "债券",    "sub": "美国中债",   "macro_fit": {"扩张期": 0.2, "复苏期": 0.5, "过热期": 0.2, "衰退期": 0.9}, "src": "yfinance"},
    "SHY":    {"name": "1-3年美债",       "class": "债券",    "sub": "美国短债",   "macro_fit": {"扩张期": 0.3, "复苏期": 0.4, "过热期": 0.5, "衰退期": 0.7}, "src": "yfinance"},
    "TIP":    {"name": "通胀保护债TIPS",  "class": "债券",    "sub": "美国通胀债", "macro_fit": {"扩张期": 0.4, "复苏期": 0.4, "过热期": 0.9, "衰退期": 0.5}, "src": "yfinance"},
    "BND":    {"name": "美国综合债",      "class": "债券",    "sub": "美国综合债", "macro_fit": {"扩张期": 0.2, "复苏期": 0.5, "过热期": 0.2, "衰退期": 0.8}, "src": "yfinance"},

    # ── 贵金属/大宗商品（通胀/避险）──
    "GLD":    {"name": "黄金",            "class": "商品",    "sub": "贵金属",     "macro_fit": {"扩张期": 0.3, "复苏期": 0.5, "过热期": 0.9, "衰退期": 0.7}, "src": "yfinance"},
    "SLV":    {"name": "白银",            "class": "商品",    "sub": "贵金属",     "macro_fit": {"扩张期": 0.5, "复苏期": 0.5, "过热期": 0.9, "衰退期": 0.5}, "src": "yfinance"},
    "GDX":    {"name": "黄金矿业股ETF",   "class": "商品",    "sub": "矿业",       "macro_fit": {"扩张期": 0.3, "复苏期": 0.5, "过热期": 0.9, "衰退期": 0.6}, "src": "yfinance"},
    "USO":    {"name": "WTI原油",         "class": "商品",    "sub": "能源",       "macro_fit": {"扩张期": 0.6, "复苏期": 0.5, "过热期": 1.0, "衰退期": 0.2}, "src": "yfinance"},
    "COPX":   {"name": "铜矿ETF",         "class": "商品",    "sub": "工业金属",   "macro_fit": {"扩张期": 0.8, "复苏期": 0.6, "过热期": 0.9, "衰退期": 0.2}, "src": "yfinance"},
    "DBA":    {"name": "农产品ETF",       "class": "商品",    "sub": "农产品",     "macro_fit": {"扩张期": 0.4, "复苏期": 0.4, "过热期": 0.8, "衰退期": 0.3}, "src": "yfinance"},
    "GSG":    {"name": "GSCI综合商品",    "class": "商品",    "sub": "综合商品",   "macro_fit": {"扩张期": 0.6, "复苏期": 0.5, "过热期": 1.0, "衰退期": 0.2}, "src": "yfinance"},

    # ── 货币/汇率（避险/套息）──
    "UUP":    {"name": "美元指数多头",    "class": "货币",    "sub": "避险货币",   "macro_fit": {"扩张期": 0.3, "复苏期": 0.4, "过热期": 0.5, "衰退期": 0.8}, "src": "yfinance"},
    "FXY":    {"name": "日元ETF",         "class": "货币",    "sub": "避险货币",   "macro_fit": {"扩张期": 0.2, "复苏期": 0.3, "过热期": 0.4, "衰退期": 0.9}, "src": "yfinance"},
    "FXE":    {"name": "欧元ETF",         "class": "货币",    "sub": "主流货币",   "macro_fit": {"扩张期": 0.5, "复苏期": 0.5, "过热期": 0.4, "衰退期": 0.4}, "src": "yfinance"},
}

# 桥水四象限 → A股宏观象限映射
REGIME_BRIDGE = {
    "扩张期":  "Q2_增长↑_通胀↓",
    "过热期":  "Q1_增长↑_通胀↑",
    "复苏期":  "Q2_增长↑_通胀↓",
    "衰退期":  "Q4_增长↓_通胀↓",
    "default": "Q2_增长↑_通胀↓",
}


# ═══════════════════════════════════════════════════════════════
# 核心评分数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class AssetScore:
    asset_id: str
    name: str
    asset_class: str
    sub_class: str
    price: Optional[float] = None
    momentum_score: float = 0.0
    macro_fit_score: float = 0.5
    risk_adj_score: float = 0.0
    vol_20d: Optional[float] = None
    max_dd: Optional[float] = None
    sharpe_approx: Optional[float] = None
    ret_20d: Optional[float] = None
    ret_60d: Optional[float] = None
    ret_120d: Optional[float] = None
    composite_score: float = 0.0
    rank: int = 0
    signal: str = "⚪"
    data_ok: bool = False
    data_badge: str = ""
    recommendation: str = ""


# ═══════════════════════════════════════════════════════════════
# 核心计算函数
# ═══════════════════════════════════════════════════════════════

def _compute_risk_adj_momentum(close: pd.Series, lookbacks=(20, 60, 120)) -> dict:
    """
    多周期风险调整动量
    每个周期：risk_adj = n日收益 / n日年化波动率
    最终得分 = 加权平均（短期权重低，中期权重高）
    """
    results = {}
    weights = {20: 0.30, 60: 0.45, 120: 0.25}

    for lb in lookbacks:
        if len(close) < lb + 5:
            results[f"ret_{lb}d"] = None
            results[f"ra_{lb}d"] = None
            continue
        ret = float((close.iloc[-1] / close.iloc[-lb] - 1) * 100)
        vol = float(close.pct_change().tail(lb).std() * np.sqrt(252) * 100)
        ra = (ret / vol) if vol > 0 else 0.0
        results[f"ret_{lb}d"] = round(ret, 2)
        results[f"ra_{lb}d"] = round(ra, 3)

    valid_ra = [results[f"ra_{lb}d"] for lb in lookbacks if results.get(f"ra_{lb}d") is not None]
    valid_w  = [weights[lb] for lb in lookbacks if results.get(f"ra_{lb}d") is not None]
    if valid_ra and sum(valid_w) > 0:
        wsum = sum(v * w for v, w in zip(valid_ra, valid_w))
        norm_w = sum(valid_w)
        results["composite_ra"] = round(wsum / norm_w, 3)
    else:
        results["composite_ra"] = None

    return results


def _normalize_scores(values: list) -> list:
    """
    截面标准化：将一组值归一化到 [0, 1]
    用 robust z-score（median + MAD），然后映射到 0-1
    """
    arr = np.array([v for v in values if v is not None], dtype=float)
    if len(arr) == 0:
        return [0.5] * len(values)
    med = np.median(arr)
    mad = np.median(np.abs(arr - med))
    if mad == 0:
        return [0.5] * len(values)
    result = []
    for v in values:
        if v is None:
            result.append(0.5)
        else:
            z = (v - med) / (1.4826 * mad)
            score = 1 / (1 + np.exp(-z))
            result.append(float(round(score, 3)))
    return result


def _inv_vol_weight(scores: list[AssetScore]) -> dict:
    """
    风险平价分配：按波动率倒数分配权重
    vol=None 的资产使用组内中位数
    """
    vols = [s.vol_20d for s in scores]
    median_vol = float(np.median([v for v in vols if v is not None])) if any(v for v in vols) else 20.0
    filled = [v if v is not None and v > 0 else median_vol for v in vols]
    inv_vols = [1.0 / v for v in filled]
    total = sum(inv_vols)
    return {s.asset_id: round(inv_v / total, 4) for s, inv_v in zip(scores, inv_vols)}


# ═══════════════════════════════════════════════════════════════
# 主引擎类
# ═══════════════════════════════════════════════════════════════

class MultiAssetEngine:
    """
    多资产评分与配置引擎

    每日运行流程：
      1. fetch_prices()   — 获取全资产历史价格
      2. score_all()      — 计算每个资产的动量 + 宏观匹配分
      3. recommend()      — 按宏观象限筛选 + 风险平价配置
      4. to_report()      — 输出结构化报告给日报使用
    """

    def __init__(self, macro_regime: str = "default"):
        self.regime = macro_regime
        self.bw_quadrant = REGIME_BRIDGE.get(macro_regime, "Q2_增长↑_通胀↓")
        self.scores: dict[str, AssetScore] = {}
        self.timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    def _get_price_series(self, asset_id: str, src: str) -> pd.Series:
        try:
            if src == "akshare":
                from .data_source_layer import get_a_etf_hist
                result = get_a_etf_hist(asset_id, days=180)
                if result.ok and result.data is not None:
                    df = result.data
                    close = pd.to_numeric(df["close"], errors="coerce").dropna()
                    close.index = range(len(close))
                    return close
            elif src == "yfinance":
                from .data_source_layer import get_yf_price_hist
                result = get_yf_price_hist(asset_id, period="6mo")
                if result.ok and result.data is not None:
                    df = result.data
                    close = pd.to_numeric(df["close"], errors="coerce").dropna()
                    close.index = range(len(close))
                    return close
        except Exception as e:
            logger.debug("[MultiAsset] %s 价格获取失败: %s", asset_id, e)
        return pd.Series(dtype=float)

    def score_asset(self, asset_id: str) -> AssetScore:
        meta = FULL_ASSET_UNIVERSE.get(asset_id, {})
        score = AssetScore(
            asset_id=asset_id,
            name=meta.get("name", asset_id),
            asset_class=meta.get("class", "其他"),
            sub_class=meta.get("sub", ""),
        )

        close = self._get_price_series(asset_id, meta.get("src", "yfinance"))
        if close.empty or len(close) < 21:
            return score

        score.price = round(float(close.iloc[-1]), 4)
        score.data_ok = True

        mom_data = _compute_risk_adj_momentum(close)
        score.ret_20d   = mom_data.get("ret_20d")
        score.ret_60d   = mom_data.get("ret_60d")
        score.ret_120d  = mom_data.get("ret_120d")
        score.risk_adj_score = mom_data.get("composite_ra") or 0.0

        if len(close) >= 20:
            score.vol_20d = round(float(close.pct_change().tail(20).std() * np.sqrt(252) * 100), 1)

        if len(close) >= 5:
            peak = close.expanding().max()
            dd = (close / peak - 1) * 100
            score.max_dd = round(float(dd.min()), 2)

        if score.vol_20d and score.vol_20d > 0 and score.ret_60d is not None:
            ann_ret = score.ret_60d / 60 * 252
            score.sharpe_approx = round(ann_ret / score.vol_20d, 2)

        fit_map = meta.get("macro_fit", {})
        score.macro_fit_score = fit_map.get(self.regime, fit_map.get("扩张期", 0.5))

        return score

    def score_all(self, asset_ids: list = None) -> dict[str, AssetScore]:
        targets = asset_ids or list(FULL_ASSET_UNIVERSE.keys())
        self.scores = {}
        for aid in targets:
            s = self.score_asset(aid)
            self.scores[aid] = s
            logger.debug("[MultiAsset] scored %s → ra=%.3f macro=%.2f",
                         aid, s.risk_adj_score, s.macro_fit_score)

        valid = [s for s in self.scores.values() if s.data_ok]
        if not valid:
            return self.scores

        ra_vals = [s.risk_adj_score for s in valid]
        ra_normed = _normalize_scores(ra_vals)
        sharpe_vals = [s.sharpe_approx or 0.0 for s in valid]
        sharpe_normed = _normalize_scores(sharpe_vals)

        for i, s in enumerate(valid):
            s.momentum_score = round(ra_normed[i], 3)
            norm_sharpe = sharpe_normed[i]
            s.composite_score = round(
                0.45 * s.momentum_score +
                0.35 * s.macro_fit_score +
                0.20 * norm_sharpe,
                3
            )
            if s.ret_20d is not None:
                if s.ret_20d > 5 and s.composite_score > 0.6:
                    s.signal = "🟢"
                elif s.ret_20d > 0 and s.composite_score > 0.5:
                    s.signal = "🟡"
                elif s.ret_20d < -5:
                    s.signal = "🔴"
                else:
                    s.signal = "⚪"

        ranked = sorted(valid, key=lambda x: x.composite_score, reverse=True)
        for i, s in enumerate(ranked):
            s.rank = i + 1

        return self.scores

    def recommend(self, top_per_class: int = 2, min_score: float = 0.30) -> dict:
        """
        生成配置建议

        逻辑：
        1. 按资产类别分组
        2. 每组取评分最高的 top_per_class 只（且评分 >= min_score）
        3. 组内用风险平价分配权重
        4. 跨组用宏观象限权重分配
        """
        if not self.scores:
            return {}

        by_class: dict[str, list[AssetScore]] = {}
        for s in self.scores.values():
            if not s.data_ok:
                continue
            by_class.setdefault(s.asset_class, []).append(s)

        CLASS_MACRO_WEIGHTS = {
            "扩张期":  {"A股股票": 0.35, "美股股票": 0.30, "债券": 0.10, "商品": 0.15, "REIT": 0.05, "货币": 0.05},
            "过热期":  {"A股股票": 0.20, "美股股票": 0.15, "债券": 0.10, "商品": 0.35, "REIT": 0.05, "货币": 0.15},
            "复苏期":  {"A股股票": 0.30, "美股股票": 0.25, "债券": 0.20, "商品": 0.10, "REIT": 0.10, "货币": 0.05},
            "衰退期":  {"A股股票": 0.10, "美股股票": 0.10, "债券": 0.45, "商品": 0.20, "REIT": 0.05, "货币": 0.10},
            "default": {"A股股票": 0.25, "美股股票": 0.25, "债券": 0.20, "商品": 0.15, "REIT": 0.05, "货币": 0.10},
        }
        class_weights = CLASS_MACRO_WEIGHTS.get(self.regime, CLASS_MACRO_WEIGHTS["default"])

        recommendations = {}
        for cls, assets in by_class.items():
            top = sorted(
                [a for a in assets if a.composite_score >= min_score],
                key=lambda x: x.composite_score, reverse=True,
            )[:top_per_class]

            if not top:
                top = sorted(assets, key=lambda x: x.composite_score, reverse=True)[:1]

            class_alloc = class_weights.get(cls, 0.0)
            inv_vol_w = _inv_vol_weight(top)

            for s in top:
                individual_w = class_alloc * inv_vol_w.get(s.asset_id, 1.0 / len(top))
                s.recommendation = f"配置{individual_w*100:.1f}% (类别{class_alloc*100:.0f}% × 风险平价)"
                recommendations[s.asset_id] = {
                    "name": s.name,
                    "class": cls,
                    "sub": s.sub_class,
                    "score": s.composite_score,
                    "signal": s.signal,
                    "ret_20d": s.ret_20d,
                    "ret_60d": s.ret_60d,
                    "vol_20d": s.vol_20d,
                    "sharpe": s.sharpe_approx,
                    "weight": round(individual_w, 4),
                    "macro_fit": s.macro_fit_score,
                    "recommendation": s.recommendation,
                }

        total_w = sum(v["weight"] for v in recommendations.values())
        if total_w > 0:
            for v in recommendations.values():
                v["weight_pct"] = round(v["weight"] / total_w * 100, 1)

        return recommendations

    def to_report(self, top_per_class: int = 2) -> dict:
        """
        输出完整报告结构供日报使用
        """
        recs = self.recommend(top_per_class=top_per_class)

        by_class: dict[str, list] = {}
        for aid, info in sorted(recs.items(), key=lambda x: -x[1]["score"]):
            by_class.setdefault(info["class"], []).append({**info, "id": aid})

        all_scored = sorted(
            [s for s in self.scores.values() if s.data_ok],
            key=lambda x: x.composite_score, reverse=True,
        )

        top_overall = [
            {
                "id": s.asset_id, "name": s.name, "class": s.asset_class,
                "sub": s.sub_class, "score": s.composite_score, "signal": s.signal,
                "ret_20d": s.ret_20d, "ret_60d": s.ret_60d,
                "vol": s.vol_20d, "sharpe": s.sharpe_approx,
                "macro_fit": s.macro_fit_score, "rank": s.rank,
            }
            for s in all_scored[:20]
        ]

        worst = sorted(
            [s for s in self.scores.values() if s.data_ok and s.ret_20d is not None],
            key=lambda x: x.composite_score,
        )[:5]
        avoid = [{"id": s.asset_id, "name": s.name, "class": s.asset_class,
                  "ret_20d": s.ret_20d, "signal": "🔴"} for s in worst]

        return {
            "regime": self.regime,
            "bw_quadrant": self.bw_quadrant,
            "timestamp": self.timestamp,
            "recommended_allocation": recs,
            "by_class": by_class,
            "top_20_overall": top_overall,
            "avoid_list": avoid,
            "total_scored": len([s for s in self.scores.values() if s.data_ok]),
            "summary": _build_summary(self.regime, by_class, recs),
        }


def _build_summary(regime: str, by_class: dict, recs: dict) -> str:
    total_w = sum(v.get("weight_pct", 0) for v in recs.values())
    lines = [f"当前象限：{regime} | 覆盖{len(recs)}类资产"]
    for cls, assets in by_class.items():
        cls_w = sum(a.get("weight_pct", 0) for a in assets)
        names = "、".join(a["name"] for a in assets[:2])
        lines.append(f"  {cls}({cls_w:.0f}%): {names}")
    return " | ".join(lines)


def run_daily_multi_asset_scan(regime: str = "default", asset_ids: list = None,
                               bw_quadrant_override: str = "") -> dict:
    """
    每日多资产扫描入口函数
    regime: 来自 MacroEngine().regime（如"复苏期"）
    bw_quadrant_override: 桥水实际象限（如"Q4_增长↓_通胀↓"），优先于 REGIME_BRIDGE 静态映射
    """
    effective_bw = bw_quadrant_override or REGIME_BRIDGE.get(regime, REGIME_BRIDGE["default"])
    engine = MultiAssetEngine(macro_regime=regime)
    engine.bw_quadrant = effective_bw
    engine.score_all(asset_ids=asset_ids)
    return engine.to_report()
