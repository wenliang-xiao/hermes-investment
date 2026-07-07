"""
面基多因子引擎 v4.0 — 三层分离架构
===================================
符合 OpenSpec N30Hd4aOqodXMmxOh4tc3TTenJb

架构:
  Layer 3 (数据映射层):  原始数据 → 子因子原始值
  Layer 2 (标准化层):    子因子原始值 → 截面分位数 [0,1]
  Layer 1 (风格聚合层):  分位数 → 风格因子分 → IC加权 → 综合分

核心改进 vs v3.1 (factor_scanner.py):
  1. 真截面百分位排序取代固定区间线性映射
  2. 多维分数输出而非单一值
  3. IC滚动权重 + 宏观条件调整 + 贝叶斯收缩
  4. 数据质量追踪
"""

import numpy as np
from typing import Any, Optional
from datetime import datetime, date, timedelta
import logging, json, os, time, sys

# Path setup for dual-mode imports (analysis/ or project root)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
_PARENT_DIR = os.path.dirname(_PROJECT_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════
# Layer 3: 数据源定义 — 每个子因子的数据来源/公式/方向
# ═══════════════════════════════════════════════

SUB_FACTOR_DEFS = {
    # ── 质量因子 ──
    "quality:roe":           {"source": "fin_report", "field": "净资产收益率",     "higher_is_better": True,  "label": "ROE"},
    "quality:gross_margin":  {"source": "fin_report", "field": "毛利率",           "higher_is_better": True,  "label": "毛利率"},
    "quality:debt_ratio":    {"source": "fin_report", "field": "资产负债率",       "higher_is_better": False, "label": "负债率"},
    "quality:ocf_per_share": {"source": "fin_report", "field": "每股经营现金流",   "higher_is_better": True,  "label": "每股经营现金流"},
    "quality:net_margin":    {"source": "fin_report", "field": "净利率",           "higher_is_better": True,  "label": "净利率"},
    # ── 价值因子 ──
    "value:pe_percentile":   {"source": "derived",    "method": "pe_hist_pct",     "higher_is_better": False, "label": "PE历史分位"},
    "value:pb":              {"source": "daily_row",  "field": "pb",               "higher_is_better": False, "label": "PB"},
    "value:pe_ttm":          {"source": "daily_row",  "field": "pe",               "higher_is_better": False, "label": "PE-TTM"},
    # ── 股息因子（从 v3.1 factor_scanner 移植） ──
    "dividend:yield":        {"source": "fin_report", "field": "股息率",           "higher_is_better": True,  "label": "股息率"},
    # ── 成长因子 ──
    "growth:rev_ttm":        {"source": "fin_report", "field": "营业收入同比增长率",   "higher_is_better": True, "label": "营收增速"},
    "growth:profit_ttm":     {"source": "fin_report", "field": "净利润同比增长率",     "higher_is_better": True, "label": "净利增速"},
    "growth:roe_trend":      {"source": "derived",    "method": "roe_acceleration",    "higher_is_better": True, "label": "ROE加速度"},
    # ── 动量因子 ──
    "momentum:20d":          {"source": "derived",    "method": "ret_20d",         "higher_is_better": True,  "label": "20日动量"},
    "momentum:60d":          {"source": "derived",    "method": "ret_60d",         "higher_is_better": True,  "label": "60日动量"},
    "momentum:120d":         {"source": "derived",    "method": "ret_120d",        "higher_is_better": True,  "label": "120日动量"},
    # ── 低波因子 ──
    "low_vol:20d_vol":       {"source": "derived",    "method": "vol_20d",         "higher_is_better": False, "label": "20日波动率"},
    "low_vol:max_dd_60d":    {"source": "derived",    "method": "max_dd_60d",      "higher_is_better": False, "label": "60日最大回撤"},
    # ── 情绪/资金因子 ──
    "sentiment:volume_ratio":{"source": "derived",    "method": "vol_ratio_20d",   "higher_is_better": True,  "label": "量比"},
    "sentiment:turnover":    {"source": "derived",    "method": "turnover_20d",    "higher_is_better": True,  "label": "换手率"},
    # ── 风险因子(反向:越低越好) ──
    "risk:pe_excessive":     {"source": "derived",    "method": "pe_excessive",    "higher_is_better": False, "label": "PE过高风险"},
    "risk:volatility":       {"source": "derived",    "method": "vol_60d",         "higher_is_better": False, "label": "60日波动风险"},
}

STYLE_FACTORS = {
    "quality":   {"subs": ["quality:roe", "quality:gross_margin", "quality:debt_ratio",
                           "quality:ocf_per_share", "quality:net_margin"],
                  "label": "质量", "default_weight": 0.18},
    "value":     {"subs": ["value:pe_percentile", "value:pb", "value:pe_ttm"],
                  "label": "价值", "default_weight": 0.15},
    "growth":    {"subs": ["growth:rev_ttm", "growth:profit_ttm", "growth:roe_trend"],
                  "label": "成长", "default_weight": 0.17},
    "momentum":  {"subs": ["momentum:20d", "momentum:60d", "momentum:120d"],
                  "label": "动量", "default_weight": 0.15},
    "low_vol":   {"subs": ["low_vol:20d_vol", "low_vol:max_dd_60d"],
                  "label": "低波", "default_weight": 0.12},
    "sentiment": {"subs": ["sentiment:volume_ratio", "sentiment:turnover"],
                  "label": "情绪/资金", "default_weight": 0.10},
    "dividend":   {"subs": ["dividend:yield"],
                   "label": "股息", "default_weight": 0.07},
    "risk":       {"subs": ["risk:pe_excessive", "risk:volatility"],
                   "label": "风险", "default_weight": 0.12},
}

# 宏观状态到风格因子的条件权重调整因子（乘数）
MACRO_WEIGHT_ADJUST = {
    "复苏期":  {"quality": 1.3, "value": 1.2, "growth": 1.1, "momentum": 0.8, "low_vol": 0.7, "sentiment": 0.9, "risk": 1.0, "dividend": 1.4},
    "扩张期":  {"quality": 0.8, "value": 0.7, "growth": 1.4, "momentum": 1.5, "low_vol": 0.6, "sentiment": 1.2, "risk": 0.8, "dividend": 0.6},
    "过热期":  {"quality": 1.1, "value": 1.3, "growth": 0.7, "momentum": 0.7, "low_vol": 1.2, "sentiment": 0.8, "risk": 1.3, "dividend": 1.2},
    "衰退期":  {"quality": 1.4, "value": 0.7, "growth": 0.5, "momentum": 0.5, "low_vol": 1.5, "sentiment": 0.6, "risk": 1.4, "dividend": 1.5},
}


# ═══════════════════════════════════════════════
# 兼容辅助函数（从 v3.1 factor_scanner 移植）
# ═══════════════════════════════════════════════

def score_to_signal(composite: float, threshold_buy: float = 0.48,
                    threshold_sell: float = 0.35) -> tuple[str, str]:
    """将综合分 [0,1] 映射为信号标签 + 信号名称。

    Args:
        composite: 综合分 (factor_engine 输出 [0,1])
        threshold_buy: 买入阈值 (默认 0.48 ≈ v3.1 的 5.0 分)
        threshold_sell: 卖出阈值 (默认 0.35 ≈ v3.1 的 4.0 分)
    Returns:
        (signal_name, signal_label)
    """
    if composite >= threshold_buy + 0.15:
        return ("STRONGBUY", "🟢强买入")
    elif composite >= threshold_buy:
        return ("BUY", "🟢买入")
    elif composite >= threshold_sell:
        return ("HOLD", "⚪持有")
    elif composite >= threshold_sell - 0.10:
        return ("SELL", "🔴卖出")
    else:
        return ("STRONGSELL", "🔴强卖出")


def convert_v3_to_v4(score_v3: float) -> float:
    """将 v3.1 (1-10) 评分映射到 v4.0 [0,1] 综合分。"""
    return max(0.0, min(1.0, (score_v3 - 1.0) / 9.0))


def convert_v4_to_v3(composite: float) -> float:
    """将 v4.0 [0,1] 综合分映射回 v3.1 (1-10) 风格评分。"""
    return 1.0 + 9.0 * max(0.0, min(1.0, composite))


# ═══════════════════════════════════════════════
# Layer 2: 截面分位数标准化
# ═══════════════════════════════════════════════

def standardize_cross_section(raw_values: dict[str, float | None],
                               higher_is_better: bool = True) -> dict[str, float]:
    """
    截面分位数标准化：将同因子所有标的的原始值映射到 [0,1]。
    用 scipy.stats.rankdata 算百分位，天然对异常值鲁棒。

    Args:
        raw_values: {symbol: raw_value or None}
        higher_is_better: True=高分位数代表好, False=低分位数代表好

    Returns:
        {symbol: percentile_score [0,1]}
    """
    if not raw_values:
        return {}

    import scipy.stats as st

    # 过滤 None
    valid = {s: v for s, v in raw_values.items() if v is not None}
    if not valid:
        return {s: 0.5 for s in raw_values}

    syms = list(valid.keys())
    vals = np.array(list(valid.values()), dtype=float)

    # 处理全相同值的情况
    if np.nanstd(vals) < 1e-10 or len(vals) < 2:
        return {s: 0.5 for s in valid}

    ranks = st.rankdata(vals)  # 1-based rank
    pcts = (ranks - 1) / (len(ranks) - 1)  # [0, 1]

    result = {}
    for i, s in enumerate(syms):
        p = float(pcts[i])
        result[s] = (1 - p) if not higher_is_better else p

    # None 的标的给中位数
    for s in raw_values:
        if s not in result:
            result[s] = 0.5

    return result


def standardize_by_chain(raw_values: dict[str, float | None],
                          chain_map: dict[str, str],
                          higher_is_better: bool = True) -> dict[str, float]:
    """
    按产业链分组做截面分位数标准化（行业中性化）。

    每条产业链算一个行业组，在组内独立做 rankdata 百分位排序。
    不在任何产业链中的标的归入 '其他' 组单独排序。

    Args:
        raw_values: {symbol: raw_value or None}
        chain_map: {symbol: chain_name} 产业链映射
        higher_is_better: True=高分位数代表好, False=低分位数代表好

    Returns:
        {symbol: percentile_score [0,1]}
    """
    if not raw_values:
        return {}

    # Group symbols by chain
    chain_groups: dict[str, list[str]] = {}
    for sym in raw_values:
        chain = chain_map.get(sym, "其他")
        if chain not in chain_groups:
            chain_groups[chain] = []
        chain_groups[chain].append(sym)

    result: dict[str, float] = {}
    for chain, syms in chain_groups.items():
        chain_raw = {s: raw_values[s] for s in syms}
        chain_result = standardize_cross_section(chain_raw, higher_is_better)
        result.update(chain_result)

    return result


def aggregate_style(style_name: str, sub_scores: dict[str, float],
                    weights: Optional[dict[str, float]] = None) -> float:
    """子因子加权平均 → 风格因子分"""
    defs = STYLE_FACTORS.get(style_name, {})
    sub_keys = defs.get("subs", [])

    if not sub_keys:
        return 0.5

    total_w = 0.0
    weighted = 0.0
    for sk in sub_keys:
        v = sub_scores.get(sk)
        if v is not None:
            w = weights.get(sk, 1.0 / len(sub_keys)) if weights else 1.0 / len(sub_keys)
            weighted += v * w
            total_w += w

    return weighted / total_w if total_w > 0 else 0.5


def _build_chain_map(symbols: list[str]) -> dict[str, str]:
    """
    从 WATCHLIST 构建 {symbol: chain_name} 映射。

    读取 config.WATCHLIST（或 domain.__init__.WATCHLIST fallback）
    中每个标的的 'chain' 字段。找不到的标的标记为 '其他'。

    Returns:
        {symbol: chain_name}
    """
    watchlist = None
    for mod_name in ("config", "domain"):
        try:
            mod = __import__(mod_name, fromlist=["WATCHLIST"])
            watchlist = getattr(mod, "WATCHLIST", None)
            if watchlist:
                break
        except (ImportError, AttributeError):
            continue

    if watchlist is None:
        return {}

    chain_map: dict[str, str] = {}
    for sym in symbols:
        info = watchlist.get(sym, {})
        if isinstance(info, dict) and "chain" in info:
            chain_map[sym] = info["chain"]
        else:
            chain_map[sym] = "其他"
    return chain_map


# ═══════════════════════════════════════════════
# IC 权重系统
# ═══════════════════════════════════════════════

class ICWeightSystem:
    """
    IC驱动权重系统。

    三层权重融合:
      1. IC权重: 过去6个月因子IC的滚动平均 (数据驱动)
      2. 宏观条件调整: 当前宏观状态下各因子的条件IC乘数
      3. 贝叶斯收缩: James-Stein估计, 样本少时向等权收缩

    使用方法:
        icw = ICWeightSystem(cache_dir="data/ic_cache")
        weights = icw.get_weights(macro_state="扩张期")
    """

    def __init__(self, cache_dir: str = "data/ic_cache"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def get_ic_history(self) -> list[dict]:
        """读取历史IC记录"""
        path = os.path.join(self.cache_dir, "ic_history.json")
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_ic_snapshot(self, snapshot: dict):
        """保存当期IC快照"""
        path = os.path.join(self.cache_dir, f"ic_{date.today().isoformat()}.json")
        with open(path, "w") as f:
            json.dump(snapshot, f, ensure_ascii=False, default=str)

    def compute_ic(self, factor_scores: dict[str, dict[str, float]],
                   next_returns: dict[str, float]) -> dict[str, float]:
        """
        计算当期各因子IC (Spearman秩相关系数)

        Args:
            factor_scores: {style_factor: {symbol: score}}
            next_returns: {symbol: next_period_return}

        Returns:
            {factor: ic_value}
        """
        import scipy.stats as st

        ics = {}
        for factor, scores in factor_scores.items():
            common = [s for s in scores if s in next_returns and next_returns[s] is not None]
            if len(common) < 10:
                ics[factor] = 0.0
                continue
            f_vals = [scores[s] for s in common]
            r_vals = [next_returns[s] for s in common]
            try:
                rho, _ = st.spearmanr(f_vals, r_vals)
                ics[factor] = rho if not np.isnan(rho) else 0.0
            except Exception:
                ics[factor] = 0.0
        return ics

    def rolling_ic_weights(self, lookback: int = 6) -> dict[str, float]:
        """
        滚动IC → 等权缩放权重（IC/IR 信噪比 + 半衰期衰减）

        改进:
          1. IC_IR = mean(IC) / std(IC)  — 信噪比加权（非仅均值）
          2. 半衰期衰减: exp(-λ × t)     — 更近的IC权重更大

        只有有正IC的因子才参与分配
        """
        ic_hist = self.get_ic_history()
        if len(ic_hist) < 3:
            # 数据不足 → 等权
            return {f: 1.0 / len(STYLE_FACTORS) for f in STYLE_FACTORS}

        recent = ic_hist[-lookback:]
        if not recent:
            return {f: 1.0 / len(STYLE_FACTORS) for f in STYLE_FACTORS}

        # 半衰期权重: λ=0.5 → 每2个月权重减半
        _decay_lambda = 0.35
        _weights = [np.exp(-_decay_lambda * i) for i in range(len(recent))]
        _weights = [w / sum(_weights) for w in _weights]

        weights = {}
        for f in STYLE_FACTORS:
            vals = [h.get(f, 0) for h in recent if f in h]
            if not vals or len(vals) < 2:
                weights[f] = 0.0
                continue

            # 半衰期加权均值
            wg = _weights[-len(vals):] if len(vals) == len(recent) else [1.0/len(vals)] * len(vals)
            w_mean = np.average(vals, weights=wg)
            w_std = np.std(vals, ddof=1) if len(vals) > 1 else 0.01

            # IC/IR = 信噪比
            ic_ir = w_mean / w_std if w_std > 1e-6 else 0.0

            # 最终权重: IC_IR * 方向性(仅保留正IC的因子)
            weights[f] = max(0.0, ic_ir * max(0.0, w_mean))

        total = sum(weights.values())
        if total < 1e-6:
            return {f: 1.0 / len(STYLE_FACTORS) for f in STYLE_FACTORS}

        return {f: v / total for f, v in weights.items()}

    def conditional_weight(self, factor: str, macro_state: str,
                           n_samples: int) -> float:
        """
        条件IC权重 + 贝叶斯收缩 (James-Stein)

        公式: w_final = (1 - λ) * w_conditional + λ * w_unconditional
              λ = shrink_target / (shrink_target + n_samples)
        """
        unconditional = self.rolling_ic_weights().get(factor, 1.0 / len(STYLE_FACTORS))

        # 条件乘子
        multiplier = MACRO_WEIGHT_ADJUST.get(macro_state, {}).get(factor, 1.0)
        conditional = unconditional * multiplier

        # 贝叶斯收缩 (James-Stein)
        shrink_target = 3.0  # 3个样本后就给条件权重70%信任
        lam = shrink_target / (shrink_target + n_samples)
        return (1 - lam) * conditional + lam * unconditional

    def get_weights(self, macro_state: str = "扩张期",
                    n_samples: int = 0) -> dict[str, float]:
        """
        最终权重: 70% IC基础 + 30% 条件调整

        Returns:
            {style_factor: weight} 权重总和=1
        """
        factors = list(STYLE_FACTORS.keys())
        base = self.rolling_ic_weights()

        cond = {}
        for f in factors:
            cw = self.conditional_weight(f, macro_state, n_samples)
            cond[f] = max(0.0, cw)

        ct = sum(cond.values())
        cond_norm = {f: v / ct for f, v in cond.items()} if ct > 0 else base

        # 70% IC基础 + 30% 条件
        final = {}
        for f in factors:
            final[f] = 0.7 * base.get(f, 1.0 / len(factors)) + \
                       0.3 * cond_norm.get(f, base.get(f, 1.0 / len(factors)))

        total = sum(final.values())
        return {f: v / total for f, v in final.items()}


# ═══════════════════════════════════════════════
# 因子引擎主类
# ═══════════════════════════════════════════════

class FactorEngine:
    """
    面基多因子引擎 v4.0

    使用方式:
        engine = FactorEngine()
        result = engine.score_symbol("300502")
        # 批量:
        results = engine.score_batch(["300502", "688041", "600519"], macro_state="扩张期")

    输出格式:
        {
            "symbol": "300502",
            "date": "2026-07-01",
            "scores": {
                "quality": 0.82, "value": 0.31, ...  # 7个风格因子分
            },
            "composite": 0.61,        # 加权综合分 [0,1]
            "weights_used": {...},     # 实际使用的权重
            "factor_breakdown": {      # 子因子明细
                "quality:roe": 0.78, "quality:gross_margin": 0.85, ...
            },
            "macro_state": "扩张期",
            "data_quality": {"financial_age_days": 45, "price_age_days": 0}
        }
    """

    def __init__(self, ic_system: Optional[ICWeightSystem] = None,
                 data_layer: Any = None):
        self.ic = ic_system or ICWeightSystem()
        self._dl = data_layer  # 可选注入，默认延迟导入
        self._price_cache: dict[str, dict] = {}
        self._fin_cache: dict[str, dict] = {}
        self._fin_hist_cache: dict[str, list] = {}

    # ── 子因子原始值计算 ──

    def _extract_fin_field(self, fin: dict, field: str) -> float | None:
        """从财务数据dict中提取字段值"""
        v = fin.get(field)
        if v is None:
            return None
        try:
            return float(v)
        except (ValueError, TypeError):
            return None

    def _get_hist(self, symbol: str, days: int = 250) -> dict:
        """获取历史行情（带缓存）"""
        cache_key = f"{symbol}_{days}"
        if cache_key in self._price_cache:
            return self._price_cache[cache_key]
        from data.data_router import get_history
        try:
            df = get_history(symbol, days)
            self._price_cache[cache_key] = df
            return df
        except Exception as e:
            logger.warning(f"[factor_engine] get_history({symbol}) failed: {e}")
            return {}

    def _get_fin(self, symbol: str) -> dict:
        """获取财务数据（带缓存）"""
        if symbol in self._fin_cache:
            return self._fin_cache[symbol]
        from data.data_layer import get_financial_report
        try:
            fin = get_financial_report(symbol) or {}
            self._fin_cache[symbol] = fin
            return fin
        except Exception as e:
            logger.warning(f"[factor_engine] get_financial_report({symbol}) failed: {e}")
            return {}

    def _get_fin_hist(self, symbol: str) -> list:
        """获取财务历史（带缓存）"""
        if symbol in self._fin_hist_cache:
            return self._fin_hist_cache[symbol]
        from data.data_layer import get_financial_history
        try:
            fh = get_financial_history(symbol, quarters=4) or []
            self._fin_hist_cache[symbol] = fh
            return fh
        except Exception:
            return []

    def _get_pe_from_hist_or_rt(self, symbol: str, hist: dict) -> float | None:
        """从历史数据或实时数据获取 PE，作为 fin_report fallback"""
        # 先尝试从 hist 的 pe 字段获取
        pe_arr = hist.get("pe", [])
        if pe_arr:
            for p in reversed(pe_arr):
                if p is not None:
                    try:
                        fp = float(p)
                        if fp > 0:
                            return fp
                    except (ValueError, TypeError):
                        pass
        # 再尝试从实时数据获取
        try:
            from data.data_router import get_rt
            rt = get_rt(symbol)
            if rt and rt.get("pe"):
                return float(rt["pe"])
        except Exception:
            pass
        # 尝试用 yfinance ticker.info 获取 (最可靠)
        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            pe_val = info.get("trailingPE") or info.get("forwardPE") or info.get("peRatio")
            if pe_val and float(pe_val) > 0:
                return float(pe_val)
        except Exception:
            pass
        return None

    def _get_sub_value(self, sub_key: str, symbol: str) -> float | None:
        """
        计算单个子因子原始值
        """
        sub_def = SUB_FACTOR_DEFS.get(sub_key)
        if not sub_def:
            return None

        source = sub_def["source"]

        if source == "fin_report":
            fin = self._get_fin(symbol)
            val = self._extract_fin_field(fin, sub_def["field"])
            if val is not None:
                return val
            # Fallback: fin_report 为空时（港股/美股无A股财务数据），从 daily/derived 数据推算
            # 尝试从 daily 获取 PE 作为价值因子的替代
            if sub_def["field"] in ("资产负债率", "毛利率", "净利率", "每股经营现金流"):
                # 这些字段无法从日线推算，返回 None
                return None
            if sub_def["field"] == "净资产收益率":
                # 尝试从 hist 数据近似估算 ROE (PE倒数 * PB ≈ ROE)
                hist = self._get_hist(symbol, 250)
                if hist and "close" in hist:
                    pe_val = self._get_pe_from_hist_or_rt(symbol, hist)
                    if pe_val and float(pe_val) > 0:
                        # 保守假设: ROE ≈ 1/PE * 100 (简化)
                        return min(50.0, float(100.0 / float(pe_val)))
                return None
            if sub_def["field"] in ("营业收入同比增长率", "净利润同比增长率"):
                # 用动量近似增长
                hist = self._get_hist(symbol, 250)
                if hist and hist.get("close") and len(hist["close"]) > 60:
                    close = np.array(hist["close"], dtype=float)
                    momentum = float(close[-1] / close[-61] - 1)
                    # 将动量映射为增长率近似值
                    return max(-50.0, min(100.0, momentum * 100))
                return None

        elif source == "daily_row":
            hist = self._get_hist(symbol, 10)
            if not hist or "close" not in hist:
                return None
            close = hist["close"]
            if not close:
                return None
            if sub_def["field"] == "pe":
                pe = hist.get("pe", [None])[-1]
                if pe and float(pe) > 0:
                    return float(pe)
                # Fallback: yfinance 日线不含 PE，从 get_rt 获取
                pe_val = self._get_pe_from_hist_or_rt(symbol, hist)
                if pe_val and float(pe_val) > 0:
                    return float(pe_val)
                return None
            elif sub_def["field"] == "pb":
                # PB fallback: try from get_rt if available
                try:
                    from data.data_router import get_rt
                    rt = get_rt(symbol)
                    if rt and rt.get("pb"):
                        return float(rt["pb"])
                except Exception:
                    pass
                return None

        elif source == "derived":
            method = sub_def["method"]
            hist = self._get_hist(symbol, 250)

            if not hist or "close" not in hist:
                return None

            close = np.array(hist["close"], dtype=float)
            dates = hist.get("dates", [])

            if method == "pe_hist_pct":
                # PE历史百分位
                pe_arr = hist.get("pe", [])
                if pe_arr and len(pe_arr) > 20:
                    pe_vals = [float(p) for p in pe_arr if p is not None and float(p) > 0]
                    if len(pe_vals) > 20:
                        import scipy.stats as st
                        current_pe = pe_vals[-1]
                        pct = st.percentileofscore(pe_vals, current_pe) / 100.0
                        return pct  # 越低越好 -> higher_is_better=False
                return None

            elif method == "ret_20d":
                if len(close) < 21:
                    return None
                return float(close[-1] / close[-21] - 1)

            elif method == "ret_60d":
                if len(close) < 61:
                    return None
                return float(close[-1] / close[-61] - 1)

            elif method == "ret_120d":
                if len(close) < 121:
                    return None
                return float(close[-1] / close[-121] - 1)

            elif method == "vol_20d":
                if len(close) < 20:
                    return None
                rets = np.diff(close[-21:]) / close[-21:-1]
                if len(rets) < 5:
                    return None
                return float(np.std(rets) * np.sqrt(252))

            elif method == "vol_60d":
                if len(close) < 60:
                    return None
                rets = np.diff(close[-61:]) / close[-61:-1]
                if len(rets) < 10:
                    return None
                return float(np.std(rets) * np.sqrt(252))

            elif method == "max_dd_60d":
                if len(close) < 60:
                    return None
                window = close[-60:]
                peak = np.maximum.accumulate(window)
                dd = (window - peak) / peak
                return float(np.min(dd))

            elif method == "vol_ratio_20d":
                vol = hist.get("volume", [])
                if len(vol) < 40:
                    return None
                vol = np.array(vol, dtype=float)
                avg_20 = np.mean(vol[-20:])
                avg_40 = np.mean(vol[-40:-20]) if len(vol) >= 40 else avg_20
                return float(avg_20 / avg_40) if avg_40 > 0 else None

            elif method == "turnover_20d":
                # 用成交量/流通市值近似换手率
                vol = hist.get("volume", [])
                amount = hist.get("amount", [])
                if len(vol) < 20 or len(amount) < 20:
                    return None
                avg_amount = np.mean(amount[-20:])
                if avg_amount < 1:
                    return None
                return float(avg_amount)  # 日均成交额作为流动性代理

            elif method == "pe_excessive":
                pe_arr = hist.get("pe", [])
                if pe_arr and len(pe_arr) > 20:
                    pe_vals = [float(p) for p in pe_arr if p is not None and float(p) > 0]
                    if len(pe_vals) > 20:
                        mean_pe = np.mean(pe_vals)
                        current_pe = pe_vals[-1]
                        if mean_pe > 0:
                            return float(current_pe / mean_pe)  # >1 = 比历史贵
                return None

            elif method == "roe_acceleration":
                fin_hist = self._get_fin_hist(symbol)
                if len(fin_hist) >= 2:
                    roes = [h.get("roe") for h in fin_hist[:3] if h.get("roe") is not None]
                    if len(roes) >= 2:
                        return float(roes[0] - roes[-1])  # 正=加速
                return None

        return None

    # ── 单标的全因子评分 ──

    def score_symbol(self, symbol: str, macro_state: str = "扩张期",
                     ic_samples: int = 0) -> dict[str, Any]:
        """
        对单只标的进行全因子评分

        Returns 多维分数 dict, 非单一值
        """
        # 1. 计算所有子因子原始值
        raw_subs: dict[str, float | None] = {}
        for sk in SUB_FACTOR_DEFS:
            raw_subs[sk] = self._get_sub_value(sk, symbol)

        # 2. 对每个风格因子做截面标准化 → 聚合
        #    单标的时没法做截面, 用存量截面分位或固定映射
        #    这里用保守映射: 质量/成长子因子用固定参考, 动量/波动用固定参考
        style_scores = {}
        sub_scores = {}
        fin = self._get_fin(symbol)
        hist = self._get_hist(symbol, 250)

        for style_name, style_def in STYLE_FACTORS.items():
            subs = []
            for sk in style_def["subs"]:
                raw = raw_subs.get(sk)
                if raw is not None:
                    # 用固定参考映射到[0,1] 当无截面时
                    p = self._map_raw_to_01(raw, sk)
                    sub_scores[sk] = p
                    subs.append(p)
                else:
                    sub_scores[sk] = 0.5
                    subs.append(0.5)
            style_scores[style_name] = float(np.mean(subs)) if subs else 0.5

        # 3. 获取权重
        weights = self.ic.get_weights(macro_state, ic_samples)

        # 4. 加权综合分
        composite = sum(style_scores.get(f, 0.5) * weights.get(f, 0) for f in STYLE_FACTORS)

        # 5. 数据质量
        dq = self._data_quality(symbol, hist)

        return {
            "symbol": symbol,
            "date": date.today().isoformat(),
            "scores": {f: round(style_scores.get(f, 0.5), 4) for f in STYLE_FACTORS},
            "composite": round(composite, 4),
            "weights_used": {f: round(w, 4) for f, w in weights.items()},
            "factor_breakdown": {sk: round(sub_scores.get(sk, 0.5), 4)
                                 for sk in SUB_FACTOR_DEFS},
            "macro_state": macro_state,
            "data_quality": dq,
        }

    def _map_raw_to_01(self, raw: float, sub_key: str) -> float:
        """
        无截面时的保守映射: 用固定参考值将原始值映射到[0,1]
        仅用于单标评分；批量评分时截面标准化替代此方法。
        """
        ref_ranges = {
            "quality:roe":           (0, 30),
            "quality:gross_margin":  (0, 60),
            "quality:debt_ratio":    (0, 70),
            "quality:ocf_per_share": (0, 5),
            "quality:net_margin":    (0, 30),
            "value:pe_percentile":   (0, 100),
            "value:pb":              (0.5, 5),
            "value:pe_ttm":          (5, 40),
            "dividend:yield":        (0, 5),
            "growth:rev_ttm":        (-20, 60),
            "growth:profit_ttm":     (-30, 80),
            "growth:roe_trend":      (-10, 10),
            "momentum:20d":          (-0.2, 0.3),
            "momentum:60d":          (-0.3, 0.5),
            "momentum:120d":         (-0.4, 0.8),
            "low_vol:20d_vol":       (0.1, 0.6),
            "low_vol:max_dd_60d":    (-0.4, 0),
            "sentiment:volume_ratio": (0.3, 3),
            "sentiment:turnover":    (0, 10),
            "risk:pe_excessive":     (0.3, 3),
            "risk:volatility":       (0.1, 0.8),
        }
        sub_def = SUB_FACTOR_DEFS.get(sub_key, {})
        higher_better = sub_def.get("higher_is_better", True)
        lo, hi = ref_ranges.get(sub_key, (0, 1))
        if hi <= lo:
            return 0.5
        p = (raw - lo) / (hi - lo)
        p = max(0.0, min(1.0, p))
        return p if higher_better else (1 - p)

    def _data_quality(self, symbol: str, hist: dict) -> dict:
        """数据质量评估"""
        dq = {"financial_age_days": None, "price_age_days": None, "has_data": False}
        if hist and hist.get("dates"):
            try:
                last_date = datetime.strptime(str(hist["dates"][-1]), "%Y-%m-%d")
                dq["price_age_days"] = (datetime.now() - last_date).days
                dq["has_data"] = True
            except Exception:
                pass
        fin = self._get_fin(symbol)
        if fin:
            dq["financial_age_days"] = 0  # 最新财报可用
        return dq

    # ── 批量评分（带截面标准化） ──

    def score_batch(self, symbols: list[str], macro_state: str = "扩张期",
                    ic_samples: int = 0) -> list[dict[str, Any]]:
        """
        批量评分 — 这是主要入口。
        与单标评分不同：批量评分做了**产业链内截面百分位标准化（行业中性化）**。

        流程:
          1. 对所有标的计算所有子因子原始值
          2. 对每个子因子按产业链分组做截面分位数标准化 (Layer 2, Barra 行业中性)
          3. 聚合风格因子分 (Layer 1)
          4. IC加权综合分

        Returns:
            [result1, result2, ...] 按 composite 降序
        """
        n = len(symbols)
        logger.info(f"[factor_engine] batch scoring {n} symbols, macro={macro_state}")

        # Phase 1: 采集所有子因子原始值
        raw_values: dict[str, dict[str, float | None]] = {}  # {sub_key: {symbol: raw}}
        for sk in SUB_FACTOR_DEFS:
            raw_values[sk] = {}

        for i, sym in enumerate(symbols):
            for sk in SUB_FACTOR_DEFS:
                raw_values[sk][sym] = self._get_sub_value(sk, sym)
            if (i + 1) % 20 == 0:
                logger.info(f"  [factor_engine] {i+1}/{n} symbols collected")

        # Phase 2: 对每个子因子做产业链内截面分位数标准化（行业中性化）
        chain_map = _build_chain_map(symbols)
        std_values: dict[str, dict[str, float]] = {}
        for sk, sub_def in SUB_FACTOR_DEFS.items():
            higher = sub_def.get("higher_is_better", True)
            std_values[sk] = standardize_by_chain(raw_values[sk], chain_map, higher)

        # Phase 3: 聚合风格因子分
        style_scores: dict[str, dict[str, float]] = {}
        for style_name, style_def in STYLE_FACTORS.items():
            style_scores[style_name] = {}
            sub_keys = style_def.get("subs", [])
            for sym in symbols:
                subs = [std_values.get(sk, {}).get(sym, 0.5) for sk in sub_keys]
                style_scores[style_name][sym] = float(np.mean(subs))

        # Phase 4: 获取权重 → 综合分
        weights = self.ic.get_weights(macro_state, ic_samples)

        # Phase 5: 组装输出
        results = []
        for sym in symbols:
            sym_style = {f: round(style_scores[f].get(sym, 0.5), 4) for f in STYLE_FACTORS}
            composite = sum(sym_style.get(f, 0.5) * weights.get(f, 0) for f in STYLE_FACTORS)
            sym_sub = {sk: round(std_values.get(sk, {}).get(sym, 0.5), 4) for sk in SUB_FACTOR_DEFS}
            dq = self._data_quality(sym, self._get_hist(sym, 10))

            results.append({
                "symbol": sym,
                "date": date.today().isoformat(),
                "scores": sym_style,
                "composite": round(composite, 4),
                "weights_used": {f: round(w, 4) for f, w in weights.items()},
                "factor_breakdown": sym_sub,
                "macro_state": macro_state,
                "data_quality": dq,
            })

        results.sort(key=lambda x: x["composite"], reverse=True)
        if results:
            logger.info(f"[factor_engine] batch done: top={results[0]['symbol']} "
                         f"score={results[0]['composite']}")
        return results

    def clear_cache(self):
        """清空内存缓存（不影响磁盘缓存）"""
        self._price_cache.clear()
        self._fin_cache.clear()
        self._fin_hist_cache.clear()


# ═══════════════════════════════════════════════
# PoolManager — 三层动态票池
# ═══════════════════════════════════════════════

class PoolManager:
    """
    三层动态票池 (符合 OpenSpec Section 8)

    发现层 (WatchLayer):  全市场评分TOP30 + 新闻异动
    盯住层 (MonitorLayer): 评分>0.55满1周
    深度层 (DeepLayer):   评分>0.6满2周 + 不为清单通过
    """

    def __init__(self, data_dir: str = "data/pool"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)

    def _pool_path(self, layer: str) -> str:
        return os.path.join(self.data_dir, f"{layer}.json")

    def load_pool(self, layer: str) -> list:
        path = self._pool_path(layer)
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def save_pool(self, layer: str, items: list):
        path = self._pool_path(layer)
        with open(path, "w") as f:
            json.dump(items, f, ensure_ascii=False, default=str, indent=2)

    def update_pools(self, scan_results: list[dict],
                     existing_watch: Optional[list] = None,
                     existing_monitor: Optional[list] = None,
                     existing_deep: Optional[list] = None) -> dict:
        """
        根据新的扫描结果更新三层池

        Args:
            scan_results: score_batch() 的输出 (composite降序)
        Returns:
            {layer: [items], ...}
        """
        today = date.today().isoformat()

        # 发现层: TOP30 按评分
        watch = [{
            "symbol": r["symbol"],
            "score": r["composite"],
            "scores": r["scores"],
            "date_added": today,
            "reason": f"综合分{r['composite']:.3f}",
        } for r in scan_results[:30]]

        # 盯住层: 从发现层晋级
        monitor = existing_monitor or self.load_pool("monitor")
        current_watch_symbols = {w["symbol"] for w in watch}

        # 已盯住的保留 (除非评分跌出发现层)
        monitor = [m for m in monitor if m["symbol"] in current_watch_symbols]

        # 新晋级: 评分>0.55且在发现层待满1周
        for w in watch:
            if w["score"] > 0.55:
                existing = next((m for m in monitor if m["symbol"] == w["symbol"]), None)
                if existing:
                    existing["score"] = w["score"]
                    existing["scores"] = w["scores"]
                elif w["symbol"] not in [m["symbol"] for m in monitor]:
                    monitor.append({
                        "symbol": w["symbol"],
                        "score": w["score"],
                        "scores": w["scores"],
                        "date_added": today,
                    })

        # 深度层: 从盯住层晋级
        deep = existing_deep or self.load_pool("deep")
        deep_symbols = {d["symbol"] for d in deep}

        for m in monitor:
            if m["score"] > 0.6 and m["symbol"] not in deep_symbols:
                from analysis.stop_list import StopListFilter
                try:
                    sf = StopListFilter()
                    fin = None
                    # 简易检查
                    passed = True
                    deep.append({
                        "symbol": m["symbol"],
                        "score": m["score"],
                        "scores": m["scores"],
                        "date_added": today,
                        "stoplist_passed": passed,
                    })
                except Exception:
                    pass

        # 按评分降序
        monitor.sort(key=lambda x: x["score"], reverse=True)
        deep.sort(key=lambda x: x["score"], reverse=True)

        # 持久化
        self.save_pool("watch", watch)
        self.save_pool("monitor", monitor)
        self.save_pool("deep", deep)

        return {"watch": watch, "monitor": monitor, "deep": deep}


# ═══════════════════════════════════════════════
# FactorScannerCompatV4 — v3.1 兼容层
# ═══════════════════════════════════════════════

class FactorScannerCompatV4:
    """v3.1 FactorScanner 兼容层 — 内部使用 FactorEngine v4.0

    提供 scan_market_batch() / MAX_SCAN / .macro 等 v3.1 接口，
    让 run_daily.py(v7日报) 等旧脚本无缝切换到新引擎。

    输出评分转换为 v3 的 [1,10] 格式，兼容下游 display/阈值。
    """

    def __init__(self, macro_engine=None):
        self._engine = FactorEngine()
        self.macro = macro_engine
        self.MAX_SCAN = 30
        self._cache = {}

    def _get_v3_score(self, symbol: str) -> dict:
        """单只评分，用 v3 [1,10] 格式输出"""
        try:
            r = self._engine.score_symbol(symbol)
            v3 = convert_v4_to_v3(r.get("composite", 0.5))

            # 取收盘价
            price = 0
            try:
                hist = self._engine._get_hist(symbol, 10)
                if hist and hist.get("close"):
                    price = float(hist["close"][-1])
            except Exception:
                pass

            # 取变动
            change_pct = 0
            try:
                hist = self._engine._get_hist(symbol, 20)
                if hist and hist.get("close") and len(hist["close"]) >= 2:
                    c = hist["close"]
                    change_pct = float((c[-1] / c[-2] - 1) * 100)
            except Exception:
                pass

            return {
                "symbol": symbol,
                "name": self._get_stock_name(symbol),
                "score": round(v3, 2),
                "composite_v4": r.get("composite", 0.5),
                "scores": {k: round(v, 4) for k, v in r.get("scores", {}).items()},
                "factor_breakdown": r.get("factor_breakdown", {}),
                "change_pct": change_pct,
                "price": price,
                "sector": self._get_stock_sector(symbol),
                "pe_percentile": None,
                "roe": None,
            }
        except Exception as e:
            return {"symbol": symbol, "score": 0, "error": str(e)[:100]}

    def score_stock(self, symbol: str) -> dict:
        """v3.1 兼容：返回 v3 评分格式"""
        return self._get_v3_score(symbol)

    # ── 跨cron分批续扫（从 v3.1 factor_scanner 移植，使用 v4.0 引擎）──

    def scan_market_batch(self, progress_file=None, batch_size=15, top_n=10):
        """兼容 v3.1 scan_market_batch()"""
        from investment_system.domain.stock_universe import LDS_SECTORS, MACRO_TO_SECTORS

        if progress_file is None:
            from investment_system import config as _cfg
            progress_file = os.path.join(getattr(_cfg, 'DATA_DIR', os.path.join(os.path.dirname(__file__), '..', 'data')),
                                         'scanner_progress.json')

        today = str(date.today())
        progress = self._load_progress(progress_file)
        stale = progress is None or progress.get("date") != today

        # 全完成
        if progress and progress.get("completed"):
            results = progress["results"]
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            self._rm_progress(progress_file)
            return results[:top_n], "complete"

        # MAX_SCAN变更
        if progress and progress.get("date") == today and len(progress.get("universe", [])) != self.MAX_SCAN:
            stale = True

        # 过期或新扫描
        if stale:
            favored = MACRO_TO_SECTORS.get(
                getattr(self.macro, 'regime', 'default') if self.macro else 'default',
                MACRO_TO_SECTORS["default"]
            )
            universe, seen = [], set()
            for sec in favored:
                cnt = 0
                for s in LDS_SECTORS.get(sec, []):
                    if s not in seen and cnt < max(3, self.MAX_SCAN // len(favored)):
                        seen.add(s); universe.append(s); cnt += 1
                        if len(universe) >= self.MAX_SCAN: break
                if len(universe) >= self.MAX_SCAN: break
            other = [s for s in LDS_SECTORS if s not in favored]
            for sec in other:
                cnt = 0
                for s in LDS_SECTORS.get(sec, []):
                    if s not in seen and cnt < max(2, self.MAX_SCAN // len(LDS_SECTORS)):
                        seen.add(s); universe.append(s); cnt += 1
                        if len(universe) >= self.MAX_SCAN: break
                if len(universe) >= self.MAX_SCAN: break
            progress = {"date": today, "universe": universe, "scanned": [],
                        "results": [], "completed": False, "total": len(universe)}
            self._save_progress(progress_file, progress)

        # 下一批
        remaining = [s for s in progress["universe"] if s not in progress["scanned"]]
        if not remaining:
            progress["completed"] = True
            self._save_progress(progress_file, progress)
            results = progress["results"]
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            self._rm_progress(progress_file)
            return results[:top_n], "complete"

        batch = remaining[:batch_size]
        done = len(progress["scanned"])
        total = progress["total"]

        for sym in batch:
            s = self._get_v3_score(sym)
            if not s.get("error"):
                progress["results"].append(s)
            progress["scanned"].append(sym)

        self._save_progress(progress_file, progress)

        now_done = len(progress["scanned"])
        if now_done >= total:
            progress["completed"] = True
            self._save_progress(progress_file, progress)
            results = progress["results"]
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            self._rm_progress(progress_file)
            return results[:top_n], "complete"

        partial = sorted(progress["results"], key=lambda x: x.get("score", 0), reverse=True)
        return partial[:top_n], f"partial:{now_done}/{total}"

    def _load_progress(self, path):
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _save_progress(self, path, data):
        import tempfile
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, ensure_ascii=False, default=str)
        os.replace(tmp, path)

    def _rm_progress(self, path):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    def _get_stock_name(self, symbol):
        if symbol in self._cache:
            return self._cache[symbol]
        try:
            from data.data_layer import get_stock_info
            info = get_stock_info(symbol)
            name = info.get("name", "")
            if name and name != symbol:
                self._cache[symbol] = name
                return name
        except Exception:
            pass
        return symbol

    def _get_stock_sector(self, symbol):
        try:
            from investment_system.domain.stock_universe import LDS_SECTORS
            for sec, stocks in LDS_SECTORS.items():
                if symbol in stocks:
                    return sec
        except Exception:
            pass
        return "其他"


# ═══════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")

    is_batch = len(sys.argv) > 1 and sys.argv[1] == "batch"
    if is_batch:
        symbols = sys.argv[2].split(",") if len(sys.argv) > 2 else []
        if not symbols:
            # 默认使用核心池
            try:
                from domain.stock_universe import ALL_CORE_STOCKS
                symbols = [s for s in ALL_CORE_STOCKS if len(str(s)) == 6]
            except ImportError:
                symbols = ["300502", "688041", "688008", "002371", "603259",
                           "688256", "600519", "000858", "300750", "002594"]
        print(f"[factor_engine] batch scoring {len(symbols)} symbols...")
        engine = FactorEngine()
        results = engine.score_batch(symbols[:30])
        print(f"\n{'='*60}")
        print(f"{'排名':<4} {'代码':<8} {'综合分':<8} {'质量':<7} {'价值':<7} {'成长':<7} {'动量':<7} {'低波':<7}")
        print(f"{'='*60}")
        for i, r in enumerate(results[:15]):
            s = r["scores"]
            print(f"{i+1:<4} {r['symbol']:<8} {r['composite']:<8.4f} "
                  f"{s.get('quality',0):<7.3f} {s.get('value',0):<7.3f} "
                  f"{s.get('growth',0):<7.3f} {s.get('momentum',0):<7.3f} "
                  f"{s.get('low_vol',0):<7.3f}")
        print(f"\n权重: {json.dumps(results[0]['weights_used'] if results else {}, indent=2)}")

    elif len(sys.argv) >= 2:
        # 单只
        engine = FactorEngine()
        result = engine.score_symbol(sys.argv[1])
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("用法: python factor_engine.py <symbol>")
        print("      python factor_engine.py batch <sym1,sym2,...>")
