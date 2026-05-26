"""
ETF/债券/基金评分器 v1.0

面基+LDS框架对非股票资产的评分逻辑：
  ETF不看财务报表，看：动量 + 相对强度 + 费率 + 流动性 + 宏观匹配度
  债券ETF：额外看利率环境（CPI、实际利率方向决定债券配置价值）
  黄金/商品ETF：看实际利率 + 美元方向
  全天候组合中的ETF：看再平衡信号（偏离度）

资产分类：
  A_EQUITY_ETF  - A股宽基/行业ETF（512480、513100等）
  A_BOND_ETF    - A股债券ETF（511010、511520等）
  A_COMMODITY   - 黄金/豆粕ETF（518880、159985等）
  US_ETF        - 美股ETF（TLT、QQQ、SPY等）
  HK_STOCK      - 港股（特殊：有财务但需折价调整）
"""
from typing import Dict, List, Optional, Tuple


ETF_UNIVERSE = {
    "512480": {"name": "半导体ETF",    "type": "A_EQUITY_ETF",  "theme": "科技"},
    "513100": {"name": "纳指100ETF",   "type": "A_EQUITY_ETF",  "theme": "海外科技"},
    "512890": {"name": "红利低波ETF",  "type": "A_EQUITY_ETF",  "theme": "红利"},
    "510300": {"name": "沪深300ETF",   "type": "A_EQUITY_ETF",  "theme": "宽基"},
    "510500": {"name": "中证500ETF",   "type": "A_EQUITY_ETF",  "theme": "宽基"},
    "512660": {"name": "军工ETF",      "type": "A_EQUITY_ETF",  "theme": "军工"},
    "588000": {"name": "科创50ETF",    "type": "A_EQUITY_ETF",  "theme": "科技"},
    "159915": {"name": "创业板ETF",    "type": "A_EQUITY_ETF",  "theme": "成长"},
    "511010": {"name": "国债ETF",      "type": "A_BOND_ETF",    "theme": "利率"},
    "511520": {"name": "政金债ETF",    "type": "A_BOND_ETF",    "theme": "利率"},
    "159926": {"name": "30年国债ETF",  "type": "A_BOND_ETF",    "theme": "久期"},
    "518880": {"name": "黄金ETF",      "type": "A_COMMODITY",   "theme": "黄金"},
    "159985": {"name": "豆粕ETF",      "type": "A_COMMODITY",   "theme": "农产品"},
    "TLT":    {"name": "20年+美债",    "type": "US_ETF",        "theme": "利率"},
    "QQQ":    {"name": "纳指100",      "type": "US_ETF",        "theme": "科技"},
    "SPY":    {"name": "标普500",      "type": "US_ETF",        "theme": "宽基"},
    "GLD":    {"name": "黄金ETF",      "type": "US_ETF",        "theme": "黄金"},
    "TIP":    {"name": "TIPS通胀债",   "type": "US_ETF",        "theme": "通胀"},
    "XLU":    {"name": "公用事业ETF",  "type": "US_ETF",        "theme": "防守"},
    "GDX":    {"name": "黄金矿业ETF",  "type": "US_ETF",        "theme": "黄金"},
}

REGIME_ETF_FIT = {
    "复苏期": {
        "A_EQUITY_ETF": {"宽基": 8, "红利": 7, "成长": 6, "科技": 7, "军工": 6},
        "A_BOND_ETF":   {"利率": 5, "久期": 4},
        "A_COMMODITY":  {"黄金": 5, "农产品": 6},
        "US_ETF":       {"宽基": 7, "科技": 6, "利率": 5, "黄金": 5, "防守": 4},
    },
    "扩张期": {
        "A_EQUITY_ETF": {"宽基": 9, "科技": 10, "成长": 9, "军工": 8, "红利": 5},
        "A_BOND_ETF":   {"利率": 3, "久期": 2},
        "A_COMMODITY":  {"黄金": 4, "农产品": 5},
        "US_ETF":       {"宽基": 9, "科技": 10, "利率": 3, "黄金": 4, "防守": 3},
    },
    "过热期": {
        "A_EQUITY_ETF": {"宽基": 5, "红利": 8, "科技": 4, "军工": 7, "成长": 4},
        "A_BOND_ETF":   {"利率": 2, "久期": 1},
        "A_COMMODITY":  {"黄金": 9, "农产品": 8},
        "US_ETF":       {"宽基": 5, "科技": 4, "利率": 2, "黄金": 9, "通胀": 9, "防守": 6},
    },
    "衰退期": {
        "A_EQUITY_ETF": {"宽基": 3, "红利": 7, "科技": 3, "成长": 2, "军工": 6},
        "A_BOND_ETF":   {"利率": 9, "久期": 10},
        "A_COMMODITY":  {"黄金": 8, "农产品": 5},
        "US_ETF":       {"宽基": 3, "科技": 3, "利率": 10, "黄金": 8, "防守": 9, "通胀": 5},
    },
    "default": {
        "A_EQUITY_ETF": {"宽基": 6, "红利": 7, "科技": 6, "成长": 5, "军工": 5},
        "A_BOND_ETF":   {"利率": 6, "久期": 5},
        "A_COMMODITY":  {"黄金": 6, "农产品": 5},
        "US_ETF":       {"宽基": 6, "科技": 6, "利率": 6, "黄金": 6, "防守": 6, "通胀": 5},
    },
}


def _bounded(value, lo, hi, invert=False) -> float:
    if value is None:
        return 5.0
    score = 1 + 9 * (value - lo) / max(hi - lo, 1e-6)
    score = max(1, min(10, score))
    return round(10 - score + 1 if invert else score, 1)


def score_etf(symbol: str, macro: dict, daily_df=None) -> dict:
    """
    对单只 ETF/债券 资产打分，返回结构与 factor_scanner.score_stock() 兼容。
    macro: MacroEngine.refresh() 的输出
    daily_df: pandas DataFrame，含 close 列（可选，无则只用宏观评分）
    """
    info = ETF_UNIVERSE.get(symbol)
    if info is None:
        return {"symbol": symbol, "score": 0, "error": "not_in_etf_universe"}

    asset_type = info["type"]
    theme = info["theme"]
    name = info["name"]
    regime = macro.get("regime", "default") if macro else "default"

    regime_scores = REGIME_ETF_FIT.get(regime, REGIME_ETF_FIT["default"])
    type_scores = regime_scores.get(asset_type, {})
    macro_fit = type_scores.get(theme, 5)

    momentum_score = 5.0
    vol_score = 5.0
    tech_score = 5.0
    ret_20d = None
    ret_60d = None

    if daily_df is not None and not daily_df.empty:
        try:
            import numpy as np
            close = daily_df["close"].values if "close" in daily_df.columns else daily_df.iloc[:, 4].values
            if len(close) >= 21:
                ret_20d = float((close[-1] / close[-21] - 1) * 100)
                s20 = _bounded(ret_20d, -15, 25)
            else:
                s20 = 5.0
            if len(close) >= 61:
                ret_60d = float((close[-1] / close[-61] - 1) * 100)
                s60 = _bounded(ret_60d, -20, 40)
            else:
                s60 = 5.0
            momentum_score = round(s20 * 0.5 + s60 * 0.5, 1)

            if len(close) >= 20:
                returns = np.diff(close[-21:]) / close[-21:-1]
                vol = float(np.std(returns) * np.sqrt(252) * 100)
                vol_score = _bounded(vol, 5, 40, invert=True)

            rsi = 50.0
            if len(close) >= 15:
                diffs = np.diff(close[-15:])
                gains = np.mean(np.maximum(diffs, 0))
                losses = np.mean(np.maximum(-diffs, 0))
                if losses > 0:
                    rsi = 100 - 100 / (1 + gains / losses)
            ma60_dev = 0.0
            if len(close) >= 60:
                ma60 = float(np.mean(close[-60:]))
                ma60_dev = (close[-1] - ma60) / ma60 * 100
            tech_score = 5.0
            if 30 < rsi < 70:
                tech_score += 1
            if -5 < ma60_dev < 15:
                tech_score += 1.5
            if ma60_dev > 0:
                tech_score += 0.5
            tech_score = round(min(10, max(1, tech_score)), 1)
        except Exception:
            pass

    total = macro_fit * 0.40 + momentum_score * 0.35 + vol_score * 0.15 + tech_score * 0.10
    total = round(min(10, max(1, total)), 2)

    return {
        "symbol": symbol,
        "name": name,
        "score": total,
        "asset_type": asset_type,
        "theme": theme,
        "macro_fit": macro_fit,
        "momentum_score": momentum_score,
        "vol_score": vol_score,
        "tech_score": tech_score,
        "ret_20d": round(ret_20d, 2) if ret_20d is not None else None,
        "ret_60d": round(ret_60d, 2) if ret_60d is not None else None,
        "regime": regime,
        "factors": {
            "宏观匹配": macro_fit,
            "动量": momentum_score,
            "低波": vol_score,
            "技术": tech_score,
        },
    }


def scan_all_etfs_scored(macro: dict, use_price_data: bool = True) -> List[dict]:
    """扫描 ETF_UNIVERSE 所有资产并评分，返回按分排序的列表。"""
    results = []
    for symbol in ETF_UNIVERSE:
        daily_df = None
        if use_price_data:
            try:
                from investment_system.data.data_layer import get_stock_daily
                daily_df = get_stock_daily(symbol, 90)
            except Exception:
                try:
                    from investment_system.data.yf_data_layer import get_price_data
                    daily_df = get_price_data(symbol, period="3mo")
                except Exception:
                    pass
        result = score_etf(symbol, macro, daily_df)
        if "error" not in result:
            results.append(result)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results


def get_lds_allweather_status(macro: dict) -> dict:
    """
    LDS全天候组合状态：
    红利低波(25%) + 纳指100(30%) + 黄金(18880, 25%) + 豆粕(20%)
    基于宏观象限给出再平衡建议。
    """
    regime = macro.get("regime", "default") if macro else "default"
    components = [
        {"code": "512890", "name": "红利低波", "weight": 0.25, "type": "A_EQUITY_ETF", "theme": "红利"},
        {"code": "513100", "name": "纳指100",  "weight": 0.30, "type": "A_EQUITY_ETF", "theme": "海外科技"},
        {"code": "518880", "name": "黄金ETF",  "weight": 0.25, "type": "A_COMMODITY",  "theme": "黄金"},
        {"code": "159985", "name": "豆粕ETF",  "weight": 0.20, "type": "A_COMMODITY",  "theme": "农产品"},
    ]
    regime_adjust = {
        "复苏期": {"红利": +0.02, "海外科技": +0.03, "黄金": -0.02, "农产品": -0.03},
        "扩张期": {"红利": -0.03, "海外科技": +0.05, "黄金": -0.04, "农产品": +0.02},
        "过热期": {"红利": +0.03, "海外科技": -0.05, "黄金": +0.05, "农产品": +0.02},
        "衰退期": {"红利": +0.05, "海外科技": -0.05, "黄金": +0.03, "农产品": -0.02},
        "default": {},
    }
    adjustments = regime_adjust.get(regime, {})
    for comp in components:
        adj = adjustments.get(comp["theme"], 0)
        comp["regime_suggested_weight"] = round(comp["weight"] + adj, 2)

    return {
        "regime": regime,
        "components": components,
        "note": f"当前象限{regime}下的建议权重调整（月度再平衡参考）",
    }
