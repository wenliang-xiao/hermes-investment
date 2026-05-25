#!/usr/bin/env python3
"""
全资产扫描模块 v1.0 — LDS全天候 + ETF + 债券 + 商品 + 外汇 + 桥水四象限
==============================================================
涵盖6大资产类别的每日扫描与结构化输出：
  1. LDS全天候组合追踪（25%红利低波+30%纳指100+25%黄金+20%豆粕）
  2. ETF全景扫描（美股行业+跨境+A股，动量/波动率/费率三维排序）
  3. 债券扫描（美债曲线+中美利差+曲线形态）
  4. 商品扫描（黄金/原油/铜/豆粕 + 国运线视角）
  5. 外汇扫描（美元指数+USDCNY+USDJPY+EURUSD + 地缘折价）
  6. 桥水全天候四象限（增长↑/↓ × 通胀↑/↓ → 资产推荐）

原则：
  - 所有函数接受宏观数据dict（macro_data），返回结构化dict
  - 中文注释 + 代码风格与现有system保持一致
  - 数据源：yfinance (Yahoo Finance) 为主，baostock为辅
  - 函数独立可测，不做飞书写入（报告层在report_v6.py处理）
"""
import yfinance as yf
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_LAST_CALL = 0
_MIN_INTERVAL = 0.4

def _rate_limit():
    global _LAST_CALL
    elapsed = time.time() - _LAST_CALL
    if elapsed < _MIN_INTERVAL:
        time.sleep(_MIN_INTERVAL - elapsed)
    _LAST_CALL = time.time()

def _fetch_with_retry(fn, max_attempts: int = 3, delay: float = 0.8):
    last_err = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                time.sleep(delay * (2 ** attempt))
    raise last_err

COMMODITY_SANITY = {
    "黄金":   (1000, 4500),
    "原油":   (40,   130),
    "铜":     (2.0,  8.0),
    "白银":   (10,   80),
    "天然气": (1.0,  20),
    "豆粕/农产品": (0.15, 0.80),
}

def _validate_commodity_price(name: str, price: float) -> Optional[float]:
    if price is None:
        return None
    r = COMMODITY_SANITY.get(name)
    if r and not (r[0] <= price <= r[1]):
        logger.warning("[价格异常] %s=%.4f 超出合理区间%s，丢弃", name, price, r)
        return None
    return price


# ═══════════════════════════════════════════════════════════════
# 0. 基础工具函数
# ═══════════════════════════════════════════════════════════════

def _get_price_data(symbol: str, period: str = "6mo") -> pd.DataFrame:
    _rate_limit()
    def _fetch():
        t = yf.Ticker(symbol)
        df = t.history(period=period)
        if df.empty:
            return pd.DataFrame()
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        return df
    try:
        df = _fetch_with_retry(_fetch, max_attempts=3, delay=0.8)
        if not df.empty and "date" in df.columns:
            last_date = pd.to_datetime(df["date"].iloc[-1])
            if (datetime.now() - last_date.replace(tzinfo=None)).days > 5:
                logger.warning("[数据过期] %s 最新数据日期 %s，可能不是交易日最新值", symbol, last_date.date())
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        logger.warning("[数据获取失败] %s: %s", symbol, e)
        return pd.DataFrame()

def _get_current_price(symbol: str) -> Optional[float]:
    _rate_limit()
    def _fetch():
        t = yf.Ticker(symbol)
        info = t.fast_info
        return info.get("lastPrice") or info.get("regularMarketPrice")
    try:
        return _fetch_with_retry(_fetch, max_attempts=3, delay=0.8)
    except Exception as e:
        logger.warning("[价格获取失败] %s: %s", symbol, e)
        return None

def _get_info(symbol: str) -> dict:
    """获取标的基础信息"""
    _rate_limit()
    try:
        t = yf.Ticker(symbol)
        return t.info or {}
    except:
        return {}

def _compute_returns(close: pd.Series) -> dict:
    """
    从价格序列计算各周期收益率
    返回: {ret_1d, ret_5d, ret_20d, ytd, max_drawdown}
    """
    if close.empty or len(close) < 2:
        return {}
    
    returns = {}
    curr = float(close.iloc[-1])
    
    # 1日
    if len(close) >= 2:
        returns["ret_1d"] = round(float((curr / close.iloc[-2] - 1) * 100), 2)
    
    # 5日
    if len(close) >= 5:
        returns["ret_5d"] = round(float((curr / close.iloc[-5] - 1) * 100), 2)
    
    # 20日（约1个月）
    if len(close) >= 20:
        returns["ret_20d"] = round(float((curr / close.iloc[-20] - 1) * 100), 2)
    
    # YTD（年初至今）
    close_idx = close.index if hasattr(close, 'index') else range(len(close))
    close_values = close.values if hasattr(close, 'values') else list(close)
    
    # 找今年第一个交易日
    first_of_year = None
    for i, idx in enumerate(close_idx):
        ts = idx if hasattr(idx, 'year') else None
        if ts and hasattr(ts, 'year') and ts.year == datetime.now().year:
            first_of_year = i
            break
    if first_of_year is not None:
        returns["ytd"] = round(float((curr / close_values[first_of_year] - 1) * 100), 2)
    else:
        # fallback: 用滚动YTD
        returns["ytd"] = returns.get("ret_20d")
    
    # 最大回撤（从最高点到当前的最低跌幅）
    cummax = close.expanding().max() if hasattr(close, 'expanding') else pd.Series(close).expanding().max()
    drawdown = (close / cummax - 1) * 100
    returns["max_drawdown"] = round(float(drawdown.min()), 2)
    
    return returns

def _compute_volatility(close: pd.Series, window: int = 20) -> Optional[float]:
    """计算年化波动率（%）"""
    if close.empty or len(close) < window:
        return None
    daily_ret = close.pct_change().dropna().tail(window)
    if daily_ret.empty:
        return None
    return round(float(daily_ret.std() * np.sqrt(252) * 100), 1)

def _compute_rsi(close: pd.Series, period: int = 14) -> Optional[float]:
    """计算RSI指标"""
    if close.empty or len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1) if not rsi.empty else None

def _bounded_linear_score(value, lo, hi, reverse=False) -> float:
    """将值映射到1-10分（与yf_data_layer保持一致）"""
    if value is None or hi <= lo:
        return 5.0
    score = 1 + 9 * (value - lo) / (hi - lo)
    score = max(1, min(10, score))
    return 10 - score + 1 if reverse else score


# ═══════════════════════════════════════════════════════════════
# 1. LDS全天候组合追踪
# ═══════════════════════════════════════════════════════════════

# LDS组合配置：4类低相关资产，月度再平衡
LDS_CONFIG = {
    "name": "LDS全天候参考组合",
    "principle": "25%红利低波 + 30%纳指100 + 25%黄金 + 20%豆粕 · 月度再平衡偏离>5%触发",
    "components": {
        "红利低波": {
            "symbol": "512890.SS",    # A股红利低波ETF（yfinance用.SS后缀）
            "fallback": "512890",     # baostock格式
            "weight": 0.25,
            "asset_class": "A股策略",
            "logic": "红利+低波双重筛选，过滤银行/地产高波动。宏观复苏期→红利低波占优。",
        },
        "纳指100": {
            "symbol": "QQQ",
            "fallback": "159941.SZ",  # A股跨境纳指ETF
            "weight": 0.30,
            "asset_class": "美股科技",
            "logic": "全球科技龙头，ROE中位数>25%。定投磨平波动，长期看多科技生产力。",
        },
        "黄金": {
            "symbol": "GLD",
            "fallback": "518880.SS",  # A股黄金ETF
            "weight": 0.25,
            "asset_class": "商品贵金属",
            "logic": "央行购金趋势不可逆，对冲地缘与通胀。金油比>40→避险情绪高。",
        },
        "豆粕": {
            "symbol": "DBA",          # 农产品ETF（含豆粕敞口）
            "fallback": "159985.SZ",  # A股豆粕ETF
            "weight": 0.20,
            "asset_class": "商品农产品",
            "logic": "与股债低相关(相关系数<0.2)，组合有效前沿外推。全球极端天气+库存低位。",
        },
    },
    "rebalance_threshold": 5.0,  # 偏离超过5%触发再平衡
    "max_drawdown_warn": 15.0,   # 回撤超过15%发出警告
}

def track_lds_portfolio(macro_data: dict = None) -> dict:
    """
    LDS全天候组合每日追踪
    
    参数:
        macro_data: 宏观数据dict（可选，用于情景分析）
    
    返回:
        {
            "portfolio": {
                "daily_return": 组合今日涨跌(%),
                "ytd_return": 组合YTD(%),
                "max_drawdown": 组合最大回撤(%),
                "need_rebalance": 是否需要再平衡(bool),
                "risk_signal": "正常"/"警告"/"危险"
            },
            "components": [
                {名称, 代码, 权重, 今日涨跌, 偏离度, 信号, ...}
            ],
            "correlation_matrix": {...},  # 4资产相关阵（如有足够数据）
            "valuation_note": "...",
        }
    """
    macro_data = macro_data or {}
    result = {
        "portfolio": {
            "name": LDS_CONFIG["name"],
            "principle": LDS_CONFIG["principle"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "daily_return": None,
            "ytd_return": None,
            "max_drawdown": None,
            "need_rebalance": False,
            "rebalance_detail": "",
            "risk_signal": "未知",
        },
        "components": [],
        "correlation_matrix": {},
        "valuation_note": "",
    }
    
    daily_returns = []
    weights = {}
    all_close_data = {}
    
    for name, cfg in LDS_CONFIG["components"].items():
        weight = cfg["weight"]
        weights[name] = weight
        
        comp = {
            "name": name,
            "symbol": cfg["symbol"],
            "weight": weight,
            "asset_class": cfg["asset_class"],
            "price": None,
            "ret_1d": None,
            "ret_20d": None,
            "ytd": None,
            "volatility_20d": None,
            "deviation": None,        # 距目标权重偏离
            "signal": "➖",
            "note": "",
        }
        
        # 尝试获取数据（主代码+fallback）
        df = _get_price_data(cfg["symbol"], period="6mo")
        if df.empty and cfg.get("fallback"):
            df = _get_price_data(cfg["fallback"], period="6mo")
            if not df.empty:
                comp["symbol"] = cfg["fallback"]
        
        if not df.empty and "close" in df.columns:
            close = df["close"]
            comp["price"] = round(float(close.iloc[-1]), 2)
            
            rets = _compute_returns(close)
            comp["ret_1d"] = rets.get("ret_1d")
            comp["ret_20d"] = rets.get("ret_20d")
            comp["ytd"] = rets.get("ytd")
            
            comp["volatility_20d"] = _compute_volatility(close, 20)
            
            if comp["ret_1d"] is not None:
                daily_returns.append((comp["ret_1d"], weight))
            
            if comp["ret_1d"] is not None and comp["ret_1d"] > 0:
                comp["signal"] = "🔺"
            elif comp["ret_1d"] is not None and comp["ret_1d"] < 0:
                comp["signal"] = "🔻"
            
            # 估值备注
            if name == "纳指100":
                comp["note"] = f"波动率{comp['volatility_20d']}%" if comp['volatility_20d'] else ""
            elif name == "黄金":
                rsi = _compute_rsi(close, 14)
                if rsi:
                    comp["note"] = f"RSI={rsi}"
                    if rsi > 70:
                        comp["note"] += " (超买)"
                    elif rsi < 30:
                        comp["note"] += " (超卖)"
            elif name == "红利低波":
                comp["note"] = f"A股策略/防御"
            
            all_close_data[name] = close
        else:
            comp["note"] = "数据不可用"
        
        result["components"].append(comp)
    
    # ── 组合层面计算 ──
    if daily_returns:
        combo_ret = sum(r * w for r, w in daily_returns)
        result["portfolio"]["daily_return"] = round(combo_ret, 2)
    
    # YTD：用各成分YTD加权
    ytd_vals = []
    for comp in result["components"]:
        if comp["ytd"] is not None:
            ytd_vals.append((comp["ytd"], comp["weight"]))
    if ytd_vals:
        result["portfolio"]["ytd_return"] = round(
            sum(r * w for r, w in ytd_vals), 2
        )
    
    # 最大回撤：用等权组合近似
    if all_close_data:
        # 构建组合净值曲线（等权）
        common_len = min(len(v) for v in all_close_data.values())
        if common_len >= 2:
            combo_nav = pd.Series(0.0, index=range(common_len))
            for name, close in all_close_data.items():
                norm = close.iloc[-common_len:] / close.iloc[-common_len:].iloc[0]
                combo_nav += norm * weights[name]
            dd = (combo_nav / combo_nav.cummax() - 1) * 100
            result["portfolio"]["max_drawdown"] = round(float(dd.min()), 2)
    
    # ── 再平衡判断 ──
    # 用20日收益率近似估算当前权重偏离
    max_deviation = 0
    deviation_detail = []
    for comp in result["components"]:
        wt = comp["weight"]
        ret20 = comp.get("ret_20d") or 0
        # 简单近似：权重×（1+收益率）后的归一化偏离
        # 更精确的计算需要实际持仓份额，这里用20日表现差异作为代理
        deviation_detail.append(f"{comp['name']}: 20日{ret20:+.1f}%")
    
    # 检查成分间20日收益差：最大差超过阈值则再平衡
    rets_20 = [c.get("ret_20d") or 0 for c in result["components"]]
    if rets_20 and all(r is not None for r in rets_20):
        spread = max(rets_20) - min(rets_20)
        if spread > LDS_CONFIG["rebalance_threshold"]:
            result["portfolio"]["need_rebalance"] = True
            result["portfolio"]["rebalance_detail"] = (
                f"成分20日收益差={spread:.1f}% > 阈值{LDS_CONFIG['rebalance_threshold']}%，"
                f"建议卖出超涨成分、补入超跌成分。"
            )
        else:
            result["portfolio"]["rebalance_detail"] = (
                f"成分20日收益差={spread:.1f}%，未触发再平衡阈值。"
            )
    
    # ── 风险信号 ──
    max_dd = result["portfolio"].get("max_drawdown") or 0
    if max_dd < -LDS_CONFIG["max_drawdown_warn"]:
        result["portfolio"]["risk_signal"] = "⚠️ 警告：回撤超阈值"
    elif max_dd < -10:
        result["portfolio"]["risk_signal"] = "🟡 注意：回撤较大"
    else:
        result["portfolio"]["risk_signal"] = "🟢 正常"
    
    # ── 相关性矩阵 ──
    if len(all_close_data) >= 4:
        names = list(all_close_data.keys())
        corr_matrix = {}
        for i, na in enumerate(names):
            row = {}
            for j, nb in enumerate(names):
                if i == j:
                    row[nb] = 1.0
                elif j > i:
                    ser_a = all_close_data[na].pct_change().dropna()
                    ser_b = all_close_data[nb].pct_change().dropna()
                    common = min(len(ser_a), len(ser_b))
                    if common > 10:
                        corr = float(ser_a.iloc[-common:].corr(ser_b.iloc[-common:]))
                        row[nb] = round(corr, 2)
                    else:
                        row[nb] = None
                else:
                    row[nb] = corr_matrix.get(nb, {}).get(na)
            corr_matrix[na] = row
        result["correlation_matrix"] = corr_matrix
    
    # ── 估值注释 ──
    result["valuation_note"] = (
        f"【LDS全天候】{datetime.now().strftime('%Y-%m-%d')} "
        f"组合今日: {result['portfolio'].get('daily_return') or '?'}% | "
        f"YTD: {result['portfolio'].get('ytd_return') or '?'}% | "
        f"最大回撤: {result['portfolio'].get('max_drawdown') or '?'}% | "
        f"再平衡: {'需要' if result['portfolio']['need_rebalance'] else '不需'} | "
        f"定投不加择时，4类低相关资产对冲"
    )
    
    return result


# ═══════════════════════════════════════════════════════════════
# 2. ETF全景扫描（全市场 + 三维排序）
# ═══════════════════════════════════════════════════════════════

# ─── ETF选票池定义 ───

# 美股行业/主题ETF
US_SECTOR_ETFS = {
    "XLK":  {"name": "科技板块",       "category": "科技",      "market": "US"},
    "XLF":  {"name": "金融板块",       "category": "金融",      "market": "US"},
    "XLE":  {"name": "能源板块",       "category": "能源",      "market": "US"},
    "XLV":  {"name": "医疗健康板块",   "category": "防御",      "market": "US"},
    "XLI":  {"name": "工业板块",       "category": "工业",      "market": "US"},
    "XLY":  {"name": "可选消费板块",   "category": "消费",      "market": "US"},
    "XLP":  {"name": "必需消费板块",   "category": "防御",      "market": "US"},
    "XLB":  {"name": "材料板块",       "category": "材料",      "market": "US"},
    "XLU":  {"name": "公用事业板块",   "category": "防御",      "market": "US"},
    "SMH":  {"name": "半导体ETF",      "category": "科技",      "market": "US"},
    "SOXX": {"name": "费城半导体ETF",  "category": "科技",      "market": "US"},
    "IGV":  {"name": "软件/SaaS ETF",  "category": "科技",      "market": "US"},
}

# 跨境/新兴市场ETF
CROSS_BORDER_ETFS = {
    "FXI":  {"name": "中国大盘股ETF",   "category": "跨境-CN",   "market": "US"},
    "KWEB": {"name": "中概互联网ETF",   "category": "跨境-CN",   "market": "US"},
    "ASHR": {"name": "沪深300海外ETF",  "category": "跨境-CN",   "market": "US"},
    "EEM":  {"name": "新兴市场ETF",     "category": "新兴市场",  "market": "US"},
}

# A股行业ETF（通过yfinance .SS后缀尝试，fallback到baostock）
A_SHARE_ETFS = {
    "512890.SS": {"name": "红利低波ETF",     "category": "策略-A股",  "market": "CN"},
    "510050.SS": {"name": "上证50ETF",        "category": "宽基-A股",  "market": "CN"},
    "510300.SS": {"name": "沪深300ETF",       "category": "宽基-A股",  "market": "CN"},
    "510500.SS": {"name": "中证500ETF",       "category": "宽基-A股",  "market": "CN"},
    "588000.SS": {"name": "科创50ETF",        "category": "科技-A股",  "market": "CN"},
    "512880.SS": {"name": "证券ETF",          "category": "金融-A股",  "market": "CN"},
    "512660.SS": {"name": "军工ETF",          "category": "军工-A股",  "market": "CN"},
    "512480.SS": {"name": "半导体ETF",        "category": "科技-A股",  "market": "CN"},
    "515030.SS": {"name": "新能源车ETF",      "category": "新能源-A股","market": "CN"},
    "518880.SS": {"name": "黄金ETF",          "category": "商品-A股",  "market": "CN"},
    "159985.SZ": {"name": "豆粕ETF",          "category": "商品-A股",  "market": "CN"},
    "511520.SS": {"name": "政金债券ETF",      "category": "债券-A股",  "market": "CN"},
    "513050.SS": {"name": "中概互联ETF",      "category": "跨境-A股",  "market": "CN"},
    "513100.SS": {"name": "纳指ETF",          "category": "跨境-A股",  "market": "CN"},
    "513500.SS": {"name": "标普500ETF",       "category": "跨境-A股",  "market": "CN"},
}

# LDS参考组合对照映射（用于对比展示）
LDS_BENCHMARK_ETFS = {
    "红利低波": "512890.SS",
    "纳指100": "QQQ",
    "黄金": "GLD",
    "豆粕": "DBA",
}


def _scan_single_etf(symbol: str, info: dict) -> Optional[dict]:
    """
    扫描单只ETF，返回三维排序所需数据
    
    三维指标：
      - 动量(momentum): 20日收益率（越高越好）
      - 风险(risk): 20日波动率倒数（越低越好）
      - 成本(cost): 费率倒数（越低越好）
    """
    _rate_limit()
    try:
        t = yf.Ticker(symbol)
        hist = t.history(period="6mo")
        if hist.empty:
            return None
        
        close = hist["Close"]
        price = float(close.iloc[-1])
        
        # 动量：20日收益率
        ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0
        ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else 0
        
        # 波动率
        daily_ret = close.pct_change().dropna()
        vol_20d = float(daily_ret.tail(20).std() * np.sqrt(252) * 100) if len(daily_ret) >= 20 else None
        
        # YTD
        ytd = None
        if len(close) >= 2:
            idx_series = close.index
            start_of_year = None
            for i, ts in enumerate(idx_series):
                if hasattr(ts, 'year') and ts.year == datetime.now().year:
                    start_of_year = i
                    break
            if start_of_year is not None:
                ytd = float((close.iloc[-1] / close.iloc[start_of_year] - 1) * 100)
        
        # RSI
        rsi = _compute_rsi(close, 14)
        
        # 费率
        info_full = t.info or {}
        expense_ratio = info_full.get("annualReportExpenseRatio") or info_full.get("expenseRatio")
        if expense_ratio is not None:
            expense_ratio = round(expense_ratio * 100, 4)  # 转百分比
        
        result = {
            "symbol": symbol,
            "name": info.get("name", symbol),
            "category": info.get("category", ""),
            "market": info.get("market", "US"),
            "price": round(price, 2),
            "ret_20d": round(ret_20d, 2),
            "ret_60d": round(ret_60d, 2),
            "ytd": round(ytd, 2) if ytd else None,
            "volatility_20d": round(vol_20d, 1) if vol_20d else None,
            "rsi_14": rsi,
            "expense_ratio": expense_ratio,
            "volume": info_full.get("volume"),
            "avg_volume": info_full.get("averageVolume"),
        }
        return result
    except Exception as e:
        print(f"    ✗ {symbol}: {e}")
        return None


def scan_all_etfs(macro_data: dict = None, top_n: int = 5) -> dict:
    """
    全市场ETF三维扫描
    
    三维排序权重（可随宏观调整）:
      - 动量(momentum): 40%（趋势跟踪）
      - 低波动率(inverse vol): 30%（风险调整）
      - 低费率(inverse expense): 30%（成本效益）
    
    返回:
        {
            "top_5": [...],
            "by_market": {"US": [...], "CN": [...], "cross": [...]},
            "lds_benchmark": {...},  # LDS参考组合成分对比
            "ranking_methodology": "动量40%+低波30%+低费率30%",
        }
    """
    macro_data = macro_data or {}
    all_results = []
    
    # ── 扫描美股行业ETF ──
    for sym, info in US_SECTOR_ETFS.items():
        result = _scan_single_etf(sym, info)
        if result:
            all_results.append(result)
    
    # ── 扫描跨境ETF ──
    for sym, info in CROSS_BORDER_ETFS.items():
        result = _scan_single_etf(sym, info)
        if result:
            all_results.append(result)
    
    # ── 扫描A股ETF ──
    for sym, info in A_SHARE_ETFS.items():
        result = _scan_single_etf(sym, info)
        if result:
            all_results.append(result)
    
    if not all_results:
        return {"error": "无ETF数据可用", "top_5": [], "by_market": {}, "lds_benchmark": {}}
    
    # ── 三维排序计算 ──
    # 先找出各维度范围用于归一化
    rets = [r["ret_20d"] for r in all_results if r["ret_20d"] is not None]
    vols = [r["volatility_20d"] for r in all_results if r["volatility_20d"] is not None]
    ers  = [r["expense_ratio"] for r in all_results if r["expense_ratio"] is not None]
    
    ret_lo, ret_hi = (min(rets), max(rets)) if rets else (-20, 20)
    vol_lo, vol_hi = (min(vols), max(vols)) if vols else (5, 80)
    er_lo,  er_hi  = (min(ers), max(ers)) if ers else (0.01, 1.0)
    
    for r in all_results:
        # 动量得分（越高越好）
        ret20 = r.get("ret_20d") or 0
        mom_score = _bounded_linear_score(ret20, ret_lo, ret_hi, reverse=False)
        
        # 低波得分（波动率越低越好）
        vol = r.get("volatility_20d") or 30
        vol_score = _bounded_linear_score(vol, vol_lo, vol_hi, reverse=True)
        
        # 低费率得分（费率越低越好）
        er = r.get("expense_ratio") or 0.5
        er_score = _bounded_linear_score(er, er_lo, er_hi, reverse=True)
        
        # 三维综合得分
        # 权重：动量40% + 低波30% + 低费率30%
        composite = round(mom_score * 0.4 + vol_score * 0.3 + er_score * 0.3, 2)
        r["_momentum_score"] = round(mom_score, 1)
        r["_volatility_score"] = round(vol_score, 1)
        r["_expense_score"] = round(er_score, 1)
        r["_composite"] = composite
    
    # 排序
    all_results.sort(key=lambda x: x.get("_composite", 0), reverse=True)
    
    # ── 按市场分组 ──
    by_market = {"US": [], "CN": [], "cross": []}
    for r in all_results:
        mkt = r.get("market", "US")
        if mkt == "CN":
            by_market["CN"].append(r)
        elif mkt == "US":
            cat = r.get("category", "")
            if "跨境" in cat or "cross" in cat.lower():
                by_market["cross"].append(r)
            else:
                by_market["US"].append(r)
        else:
            by_market["cross"].append(r)
    
    # ── LDS参考组合对照 ──
    lds_benchmark = {}
    for name, sym in LDS_BENCHMARK_ETFS.items():
        # 在已扫描结果中查找
        found = [r for r in all_results if r["symbol"] == sym]
        if not found:
            # 单独获取
            info = {"name": name, "category": "LDS组合", "market": "US"}
            found = [_scan_single_etf(sym, info)] if _scan_single_etf(sym, info) else []
        
        if found:
            r = found[0]
            lds_benchmark[name] = {
                "symbol": r["symbol"],
                "price": r["price"],
                "ret_20d": r.get("ret_20d"),
                "volatility_20d": r.get("volatility_20d"),
                "rsi_14": r.get("rsi_14"),
                "_composite": r.get("_composite"),
            }
    
    return {
        "top_5": all_results[:top_n],
        "top_10": all_results[:max(top_n * 2, 10)],
        "all_ranked": all_results,
        "by_market": by_market,
        "lds_benchmark": lds_benchmark,
        "ranking_methodology": "三维排序：动量(40%) + 低波动率(30%) + 低费率(30%)，各维度归一化到1-10分后加权",
        "total_scanned": len(all_results),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ═══════════════════════════════════════════════════════════════
# 3. 债券扫描
# ═══════════════════════════════════════════════════════════════

# 债券观测标的
BOND_UNIVERSE = {
    "TLT":  {"name": "20年+美国国债ETF",     "duration": "超长端(17年+)", "type": "价格"},
    "IEF":  {"name": "7-10年美国国债ETF",    "duration": "中长端(7-10年)", "type": "价格"},
    "SHY":  {"name": "1-3年美国国债ETF",     "duration": "短端(1-3年)",   "type": "价格"},
    "TIP":  {"name": "通胀保护国债ETF",      "duration": "通胀挂钩",      "type": "价格"},
    "^TNX": {"name": "美国10年期国债收益率",  "duration": "10年期",        "type": "收益率"},
    "^TYX": {"name": "美国30年期国债收益率",  "duration": "30年期",        "type": "收益率"},
    "^FVX": {"name": "美国5年期国债收益率",   "duration": "5年期",         "type": "收益率"},
    "^IRX": {"name": "美国13周国债收益率",    "duration": "13周(≈3月)",    "type": "收益率"},
}

# 中国国债（yfinance代码）
CN_BOND_SYMBOLS = {
    "CN10Y": {"symbol": None, "name": "中国10年期国债收益率", "note": "需baostock或央行数据"},
    "CN2Y":  {"symbol": None, "name": "中国2年期国债收益率",  "note": "需baostock或央行数据"},
}

def scan_bonds(macro_data: dict = None) -> dict:
    """
    债券市场扫描：美债收益率曲线 + 中美利差 + 曲线形态信号
    
    参数:
        macro_data: dict含cpi/pmi等可影响利率判断
    
    返回:
        {
            "us_treasury": {
                "yields": [{tenor, yield_pct, change_20d}],
                "curve_shape": "陡峭"/"平坦"/"倒挂",
                "2y_10y_spread": 利差(bp),
                "signal": "...",
            },
            "bond_etfs": [{TLT/IEF/SHY/TIP的价格/收益率数据}],
            "cn_us_spread": 中美利差(bp),
            "analysis": "综合债券市场分析",
            "bridgewater_quadrant_hint": "在桥水框架中的地位",
        }
    """
    macro_data = macro_data or {}
    result = {
        "us_treasury": {"yields": [], "curve_shape": "未知", "2y_10y_spread": None, "signal": ""},
        "bond_etfs": [],
        "cn_us_spread": None,
        "cn_10y_estimated": None,
        "analysis": "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    
    # ── 获取美国国债收益率 ──
    yield_data = {}
    for sym, info in BOND_UNIVERSE.items():
        if info["type"] == "收益率":
            try:
                _rate_limit()
                t = yf.Ticker(sym)
                hist = t.history(period="6mo")
                if not hist.empty:
                    close = hist["Close"]
                    curr_yield = float(close.iloc[-1])
                    
                    # 20日变化
                    y20 = float(close.iloc[-20]) if len(close) >= 20 else curr_yield
                    chg_20d = curr_yield - y20
                    
                    tenor = info["duration"]
                    yield_data[tenor] = {
                        "symbol": sym,
                        "name": info["name"],
                        "current": round(curr_yield, 2),
                        "change_20d_bp": round(chg_20d * 100, 1),  # 转为bp
                    }
            except Exception as e:
                print(f"    ✗ {sym}: {e}")
    
    result["us_treasury"]["yields"] = list(yield_data.values())
    
    # ── 曲线形态：2Y-10Y利差（用5Y-13W近似如无2Y） ──
    y10 = yield_data.get("10年期", {}).get("current")
    y5  = yield_data.get("5年期", {}).get("current")
    y3m = yield_data.get("13周(≈3月)", {}).get("current")
    
    # 若没有直接2Y，用5Y近似短端
    spread_2y10y = None
    if y10 is not None and y5 is not None:
        spread_2y10y = round((y10 - y5) * 100, 1)  # bp，5Y-10Y近似
    elif y10 is not None and y3m is not None:
        spread_2y10y = round((y10 - y3m) * 100, 1)  # 3M-10Y
    
    result["us_treasury"]["2y_10y_spread"] = spread_2y10y
    
    # 曲线形态判断
    if spread_2y10y is not None:
        if spread_2y10y > 100:
            result["us_treasury"]["curve_shape"] = "陡峭 (Steep)"
            result["us_treasury"]["signal"] = "🟢 陡峭→经济扩张预期，利好股票、利空长久期债券"
        elif spread_2y10y > 20:
            result["us_treasury"]["curve_shape"] = "正常 (Normal)"
            result["us_treasury"]["signal"] = "🟡 正常→中性"
        elif spread_2y10y > -10:
            result["us_treasury"]["curve_shape"] = "平坦 (Flat)"
            result["us_treasury"]["signal"] = "🟡 平坦→经济不确定性高，市场观望"
        else:
            result["us_treasury"]["curve_shape"] = "倒挂 (Inverted)"
            result["us_treasury"]["signal"] = "🔴 倒挂→衰退预警信号！历史准确率>80%。利好长久期国债(TLT)"
    
    # ── 债券ETF（价格型）──
    for sym in ["TLT", "IEF", "SHY", "TIP"]:
        try:
            _rate_limit()
            t = yf.Ticker(sym)
            hist = t.history(period="6mo")
            if not hist.empty:
                close = hist["Close"]
                price = float(close.iloc[-1])
                ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0
                ytd = None
                start_yr = None
                for i, ts in enumerate(close.index):
                    if hasattr(ts, 'year') and ts.year == datetime.now().year:
                        start_yr = i; break
                if start_yr is not None:
                    ytd = float((close.iloc[-1] / close.iloc[start_yr] - 1) * 100)
                
                vol = _compute_volatility(close, 20)
                
                result["bond_etfs"].append({
                    "symbol": sym,
                    "name": BOND_UNIVERSE.get(sym, {}).get("name", sym),
                    "duration": BOND_UNIVERSE.get(sym, {}).get("duration", ""),
                    "price": round(price, 2),
                    "ret_20d": round(ret_20d, 2),
                    "ytd": round(ytd, 2) if ytd else None,
                    "volatility_20d": vol,
                })
        except:
            pass
    
    # ── 中美利差估算 ──
    # 用宏观数据中的CN10Y，或默认约2.8%
    cn_10y = macro_data.get("cn_10y") or macro_data.get("bond_yield_cn") or 2.8
    us_10y = y10 if y10 is not None else 4.5
    
    if isinstance(cn_10y, (int, float)) and isinstance(us_10y, (int, float)):
        spread_cn_us = round((cn_10y - us_10y) * 100, 1)  # bp
        result["cn_us_spread"] = spread_cn_us
        result["cn_10y_estimated"] = cn_10y
        
        if spread_cn_us < -200:
            cn_signal = "🔴 中美利差深度倒挂→人民币贬值压力大、资本外流→A股承压"
        elif spread_cn_us < -100:
            cn_signal = "🟡 中美利差倒挂→央行宽松空间受限"
        else:
            cn_signal = "🟢 中美利差正常→政策空间充足"
    else:
        cn_signal = "⚠️ 中国10Y数据缺失"
    
    # ── 综合分析 ──
    analysis_parts = []
    
    if result["us_treasury"]["curve_shape"] == "倒挂 (Inverted)":
        analysis_parts.append("美债曲线倒挂→经典衰退预警。建议超配长久期国债(TLT/IEF)对冲权益风险。")
    elif result["us_treasury"]["curve_shape"] == "陡峭 (Steep)":
        analysis_parts.append("美债曲线陡峭→经济复苏预期强。建议低配长债，超配股票/商品。")
    
    if result.get("cn_us_spread") is not None:
        spread = result["cn_us_spread"]
        analysis_parts.append(f"中美利差={spread}bp。" + cn_signal)
    
    cpi = macro_data.get("cpi") or macro_data.get("macro_data", {}).get("cpi")
    if cpi is not None:
        if cpi > 3:
            analysis_parts.append(f"CPI={cpi}%→通胀压力→短债优于长债，TIP有保护价值。")
        elif cpi < 1:
            analysis_parts.append(f"CPI={cpi}%→通缩风险→长久期国债配置价值高。")
    
    result["analysis"] = " | ".join(analysis_parts) if analysis_parts else "数据有限，参考美债曲线信号。"
    
    # ── 桥水象限提示 ──
    result["bridgewater_quadrant_hint"] = _bridgewater_bond_hint(
        result["us_treasury"].get("curve_shape", ""),
        macro_data
    )
    
    return result


def _bridgewater_bond_hint(curve_shape: str, macro_data: dict) -> str:
    """根据曲线形态和宏观数据给出桥水象限中的债券配置提示"""
    cpi = macro_data.get("cpi") or macro_data.get("macro_data", {}).get("cpi", 2.0)
    pmi = macro_data.get("pmi") or macro_data.get("macro_data", {}).get("pmi", 50)
    
    if cpi is not None and pmi is not None:
        if pmi > 52 and cpi > 2.5:
            return "象限1(增长↑通胀↑): 商品>黄金>通胀挂钩债>股票, 避长债"
        elif pmi > 52 and cpi <= 2.5:
            return "象限2(增长↑通胀↓): 股票>信用债>商品, 最优象限"
        elif pmi <= 48 and cpi > 2.5:
            return "象限3(增长↓通胀↑): 黄金>TIPS>商品, 滞胀配置"
        elif pmi <= 48 and cpi <= 2.5:
            return "象限4(增长↓通胀↓): 长期国债>防御股>黄金, 通缩衰退配置"
    
    if "倒挂" in curve_shape:
        return "曲线倒挂→衰退概率高→象限4概率大: 长久期国债最受益"
    return "关注曲线形态+CPI/PMI判断所处象限"


# ═══════════════════════════════════════════════════════════════
# 4. 商品扫描
# ═══════════════════════════════════════════════════════════════

# 商品观测池（优先用ETF，价格更准；期货代码作为fallback）
COMMODITY_UNIVERSE = {
    "黄金": {
        "primary": "GC=F", "fallback": "GLD",
        "name": "黄金", "type": "贵金属", "unit": "USD/oz",
        "lds_view": "央行购金+地缘对冲",
        "price_scale": 1.0,
    },
    "原油": {
        "primary": "CL=F", "fallback": "USO",
        "name": "WTI原油", "type": "能源", "unit": "USD/bbl",
        "lds_view": "周期波动+地缘供给",
        "price_scale": 1.0,
    },
    "铜": {
        "primary": "HG=F", "fallback": "COPX",
        "name": "铜", "type": "工业金属", "unit": "USD/lb",
        "lds_view": "全球经济晴雨表",
        "price_scale": 1.0,
    },
    "豆粕/农产品": {
        "primary": "DBA", "fallback": "ZM=F",
        "name": "豆粕/农产品", "type": "农产品", "unit": "USD/share(ETF)",
        "lds_view": "通胀周期+天气供给",
        "price_scale": 1.0,
    },
    "白银": {
        "primary": "SI=F", "fallback": "SLV",
        "name": "白银", "type": "贵金属", "unit": "USD/oz",
        "lds_view": "工业+贵金属双重属性",
        "price_scale": 1.0,
    },
    "天然气": {
        "primary": "NG=F", "fallback": "UNG",
        "name": "天然气", "type": "能源", "unit": "USD/MMBtu",
        "lds_view": "季节性+地缘",
        "price_scale": 1.0,
    },
}

def scan_commodities(macro_data: dict = None) -> dict:
    """
    商品市场扫描：价格/动量/RSI + 国运线视角
    
    参数:
        macro_data: 含cpi，用于黄金vs美元vs人民币判断
    
    返回:
        {
            "commodities": [{name, price, ret_20d, rsi, signal, ...}],
            "lds_guoyun_view": "黄金vs美元vs人民币的国运线分析",
            "heatmap": "商品热力图(超买/超卖分布)",
            "analysis": "...",
        }
    """
    macro_data = macro_data or {}
    results = []
    
    for key, cfg in COMMODITY_UNIVERSE.items():
        item = {
            "name": cfg["name"],
            "type": cfg["type"],
            "unit": cfg["unit"],
            "lds_view": cfg["lds_view"],
            "price": None,
            "ret_5d": None,
            "ret_20d": None,
            "rsi_14": None,
            "volatility_20d": None,
            "signal": "➖",
            "note": "",
        }
        
        # 尝试主代码→fallback
        df = _get_price_data(cfg["primary"], period="6mo")
        if df.empty:
            df = _get_price_data(cfg["fallback"], period="6mo")
            if not df.empty:
                item["source_symbol"] = cfg["fallback"]
        else:
            item["source_symbol"] = cfg["primary"]
        
        if not df.empty and "close" in df.columns:
            close = df["close"]
            raw_price = float(close.iloc[-1])
            validated_price = _validate_commodity_price(cfg["name"], raw_price)
            if validated_price is None:
                item["note"] = f"⚠️ 价格异常({raw_price:.2f})，已丢弃"
                results.append(item)
                continue
            item["price"] = round(validated_price, 2)

            rets = _compute_returns(close)
            item["ret_5d"] = rets.get("ret_5d")
            item["ret_20d"] = rets.get("ret_20d")

            item["rsi_14"] = _compute_rsi(close, 14)
            item["volatility_20d"] = _compute_volatility(close, 20)

            if item["ret_20d"] is not None:
                if item["ret_20d"] > 5:
                    item["signal"] = "🟢 强势"
                elif item["ret_20d"] > 0:
                    item["signal"] = "🟡 偏强"
                elif item["ret_20d"] > -5:
                    item["signal"] = "🟠 偏弱"
                else:
                    item["signal"] = "🔴 弱势"

            if item["rsi_14"]:
                if item["rsi_14"] > 70:
                    item["note"] += "超买 "
                elif item["rsi_14"] < 30:
                    item["note"] += "超卖 "
        else:
            item["note"] = "⚠️ 数据获取失败"
        
        results.append(item)
    
    # ── 排序：按20日动量降序 ──
    results.sort(key=lambda x: x.get("ret_20d") or -999, reverse=True)
    
    # ── 热力图 ──
    heatmap = {}
    for r in results:
        rsi = r.get("rsi_14")
        if rsi is not None:
            if rsi > 70:
                heatmap[r["name"]] = "🔴 超买"
            elif rsi > 60:
                heatmap[r["name"]] = "🟠 偏强"
            elif rsi > 40:
                heatmap[r["name"]] = "🟡 中性"
            elif rsi > 30:
                heatmap[r["name"]] = "🟢 偏弱"
            else:
                heatmap[r["name"]] = "🟢 超卖"
    
    # ── LDS国运线视角：黄金vs美元vs人民币 ──
    gold_rsi = None
    for r in results:
        if "黄金" in r["name"]:
            gold_rsi = r.get("rsi_14")
            gold_ret = r.get("ret_20d")
    
    # 尝试获取DXY和USDCNY
    dxy_price = _get_current_price("DX-Y.NYB") or _get_current_price("UUP")
    usdcny = _get_current_price("CNY=X")
    
    guoyun_view = []
    guoyun_view.append("【LDS国运线：黄金·美元·人民币三角】")
    
    if gold_ret is not None:
        guoyun_view.append(f"黄金20日: {gold_ret:+.1f}% | RSI={gold_rsi if gold_rsi else '?'}")
    if dxy_price:
        guoyun_view.append(f"美元指数≈{dxy_price:.1f}")
    if usdcny:
        guoyun_view.append(f"USD/CNY≈{usdcny:.4f}")
    
    # 判断逻辑
    cpi = macro_data.get("cpi") or macro_data.get("macro_data", {}).get("cpi")
    if cpi is not None:
        if cpi > 2.5:
            guoyun_view.append(f"CPI={cpi}%→通胀高位→黄金有支撑，央行购金动机增强")
        elif cpi < 1:
            guoyun_view.append(f"CPI={cpi}%→通缩压力→实际利率高→黄金承压但央行购金仍持续")
    
    if usdcny and usdcny > 7.3:
        guoyun_view.append("⚠️ 人民币破7.3→资本外流压力→国内黄金溢价上升(人民币计价黄金跑赢美元计价)")
    
    # ── 库存数据（如能从yfinance获取） ──
    # yfinance不直接提供库存数据；标注为需外部源
    inventory_note = "库存数据需EIA(原油)/LME(铜)/USDA(农产品)等外部源获取，本扫描器不直接提供。"
    
    # ── 分析 ──
    analysis = []
    strong = [r["name"] for r in results if r.get("ret_20d") and r["ret_20d"] > 3]
    weak = [r["name"] for r in results if r.get("ret_20d") and r["ret_20d"] < -3]
    
    if strong:
        analysis.append(f"强势品种: {', '.join(strong)}")
    if weak:
        analysis.append(f"弱势品种: {', '.join(weak)}")
    
    overbought = [r["name"] for r in results if r.get("rsi_14") and r["rsi_14"] > 70]
    oversold = [r["name"] for r in results if r.get("rsi_14") and r["rsi_14"] < 30]
    
    if overbought:
        analysis.append(f"⚠️ 超买(RSI>70): {', '.join(overbought)}")
    if oversold:
        analysis.append(f"💡 超卖(RSI<30): {', '.join(oversold)}")
    
    return {
        "commodities": results,
        "heatmap": heatmap,
        "lds_guoyun_view": " | ".join(guoyun_view) if guoyun_view else "数据不足",
        "inventory_note": inventory_note,
        "analysis": " | ".join(analysis) if analysis else "商品市场数据有限",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ═══════════════════════════════════════════════════════════════
# 5. 外汇扫描
# ═══════════════════════════════════════════════════════════════

# 外汇观测池
FX_UNIVERSE = {
    "DXY": {
        "symbol": "DX-Y.NYB",   # 美元指数期货
        "fallback": "UUP",      # 美元指数ETF
        "name": "美元指数(DXY)",
        "impact": "↑美元强→新兴承压、大宗商品跌",
        "key_level": "100-105",
    },
    "USDCNY": {
        "symbol": "CNY=X",
        "fallback": None,
        "name": "USD/CNY（在岸人民币）",
        "impact": "↑人民币贬值→A股承压、资本外流",
        "key_level": "7.0-7.3",
    },
    "USDJPY": {
        "symbol": "JPY=X",
        "fallback": None,
        "name": "USD/JPY（日元）",
        "impact": "↑日元升值→套息交易平仓风险、风险资产承压",
        "key_level": "140-155",
    },
    "EURUSD": {
        "symbol": "EURUSD=X",
        "fallback": None,
        "name": "EUR/USD（欧元）",
        "impact": "↑欧元强→美元弱、利好新兴市场",
        "key_level": "1.05-1.15",
    },
    "USDCNH": {
        "symbol": "CNH=X",
        "fallback": None,
        "name": "USD/CNH（离岸人民币）",
        "impact": "离岸-在岸价差=市场预期与政策意图的分歧",
        "key_level": "7.0-7.3",
    },
}

def scan_fx(macro_data: dict = None) -> dict:
    """
    外汇市场扫描：主要货币对 + 地缘折价视角
    
    参数:
        macro_data: 可用于判断地缘风险溢价
    
    返回:
        {
            "fx_pairs": [{name, price, ret_20d, volatility, signal, impact}],
            "geopolitical_discount": "人民币汇率偏离度分析",
            "carry_trade_risk": "套息交易风险评估",
            "analysis": "...",
        }
    """
    macro_data = macro_data or {}
    results = []
    usdcny_price = None
    usdcnh_price = None
    
    for key, cfg in FX_UNIVERSE.items():
        item = {
            "key": key,
            "name": cfg["name"],
            "impact": cfg["impact"],
            "key_level": cfg["key_level"],
            "price": None,
            "ret_5d": None,
            "ret_20d": None,
            "volatility_20d": None,
            "signal": "➖",
        }
        
        # 获取数据
        df = _get_price_data(cfg["symbol"], period="6mo")
        if df.empty and cfg.get("fallback"):
            df = _get_price_data(cfg["fallback"], period="6mo")
            if not df.empty:
                item["source_symbol"] = cfg["fallback"]
        else:
            item["source_symbol"] = cfg["symbol"]
        
        if not df.empty and "close" in df.columns:
            close = df["close"]
            raw_price = round(float(close.iloc[-1]), 4)

            if key == "EURUSD" and not (0.8 <= raw_price <= 1.6):
                logger.warning("[汇率异常] EURUSD=%.4f，可能是倒置或错误ticker，丢弃", raw_price)
                item["note"] = f"⚠️ EUR/USD价格异常({raw_price})，请检查ticker"
                results.append(item)
                continue

            item["price"] = raw_price

            rets = _compute_returns(close)
            item["ret_5d"] = rets.get("ret_5d")
            item["ret_20d"] = rets.get("ret_20d")
            item["volatility_20d"] = _compute_volatility(close, 20)

            if item["ret_20d"] is not None:
                if abs(item["ret_20d"]) < 1:
                    item["signal"] = "🟡 窄幅震荡"
                elif item["ret_20d"] > 0:
                    item["signal"] = f"🔺 +{item['ret_20d']}%"
                else:
                    item["signal"] = f"🔻 {item['ret_20d']}%"

            if key == "USDCNY":
                usdcny_price = item["price"]
            if key == "USDCNH":
                usdcnh_price = item["price"]
        else:
            item["note"] = "⚠️ 数据获取失败"
        
        results.append(item)
    
    # ── 地缘折价：人民币汇率偏离度 ──
    geopolitical_discount = ""
    if usdcny_price and usdcnh_price:
        spread = round((usdcnh_price - usdcny_price) * 10000, 0)  # pip
        if abs(spread) > 200:
            geopolitical_discount = (
                f"离岸-在岸价差={spread}pips（较大）→市场对人民币有额外折价预期，"
                f"反映地缘风险溢价。离岸{'贬' if spread > 0 else '升'}值压力>在岸。"
            )
        else:
            geopolitical_discount = (
                f"离岸-在岸价差={spread}pips（正常）→市场定价与政策意图基本一致，"
                f"地缘折价不显著。"
            )
    else:
        geopolitical_discount = "人民币汇率数据不完整，无法计算偏离度。"
    
    # ── 套息交易风险 ──
    carry_trade_risk = ""
    usdjpy = next((r for r in results if r["key"] == "USDJPY"), None)
    if usdjpy and usdjpy.get("ret_20d") is not None:
        if usdjpy["ret_20d"] < -3:
            carry_trade_risk = (
                f"⚠️ 日元20日升值{abs(usdjpy['ret_20d']):.1f}%→套息交易平仓压力大！"
                f"历史上日元快速升值常伴随风险资产(美股/新兴市场)下跌。"
            )
        elif usdjpy["ret_20d"] > 3:
            carry_trade_risk = (
                f"日元20日贬值{usdjpy['ret_20d']:.1f}%→套息交易环境友好，"
                f"风险资产受益。但需警惕突然逆转。"
            )
        else:
            carry_trade_risk = "日元窄幅波动→套息交易环境稳定。"
    else:
        carry_trade_risk = "USDJPY数据不可用，无法评估套息风险。"
    
    # ── 综合分析 ──
    analysis_parts = []
    for r in results:
        if r.get("ret_20d") is not None and abs(r["ret_20d"]) > 2:
            analysis_parts.append(f"{r['name']} 20日{'涨' if r['ret_20d'] > 0 else '跌'}{abs(r['ret_20d']):.1f}%")
    
    dxy = next((r for r in results if r["key"] == "DXY"), None)
    if dxy and dxy.get("ret_20d") is not None:
        if dxy["ret_20d"] > 1:
            analysis_parts.append("美元走强→新兴市场+商品承压")
        elif dxy["ret_20d"] < -1:
            analysis_parts.append("美元走弱→利好新兴市场+商品")
    
    return {
        "fx_pairs": results,
        "geopolitical_discount": geopolitical_discount,
        "carry_trade_risk": carry_trade_risk,
        "analysis": " | ".join(analysis_parts) if analysis_parts else "汇率市场窄幅波动",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ═══════════════════════════════════════════════════════════════
# 6. 桥水全天候四象限框架
# ═══════════════════════════════════════════════════════════════

# 桥水四象限定义
# 增长↑/↓ × 通胀↑/↓ → 4种经济环境 + 对应最优资产
BRIDGEWATER_QUADRANTS = {
    "Q1_增长↑_通胀↑": {
        "name": "象限1：增长上升 + 通胀上升",
        "environment": "过热/繁荣期——经济扩张但通胀压力增大",
        "best_assets": ["大宗商品", "黄金", "通胀挂钩债券(TIP)", "资源股"],
        "worst_assets": ["长期国债", "高估值成长股"],
        "allocation_hint": "商品>黄金>TIPS>股票>现金>长债",
        "china_parallel": "类似中国PMI>52+CPI>2.5%——周期/资源品占优",
    },
    "Q2_增长↑_通胀↓": {
        "name": "象限2：增长上升 + 通胀下降",
        "environment": "金发女孩/复苏期——最佳宏观环境",
        "best_assets": ["股票(特别是成长股)", "信用债", "新兴市场"],
        "worst_assets": ["现金", "黄金"],
        "allocation_hint": "股票>信用债>商品>国债>现金>黄金",
        "china_parallel": "类似中国PMI>52+CPI<2%——成长股领涨",
    },
    "Q3_增长↓_通胀↑": {
        "name": "象限3：增长下降 + 通胀上升",
        "environment": "滞胀——最难投资的环境",
        "best_assets": ["黄金", "通胀挂钩债券(TIP)", "大宗商品", "现金"],
        "worst_assets": ["股票", "长期国债", "信用债"],
        "allocation_hint": "黄金>TIPS>商品>现金>>股票>长债",
        "china_parallel": "类似中国PMI<48+CPI>2.5%——防御为上",
    },
    "Q4_增长↓_通胀↓": {
        "name": "象限4：增长下降 + 通胀下降",
        "environment": "衰退/通缩——央行降息周期",
        "best_assets": ["长期国债(TLT)", "防御性股票(公用事业/消费必需品)", "黄金"],
        "worst_assets": ["大宗商品", "周期性股票", "新兴市场"],
        "allocation_hint": "长债>防御股>黄金>现金>商品>周期股",
        "china_parallel": "类似中国PMI<48+CPI<1%——债券为王",
    },
}

def determine_bridgewater_quadrant(macro_data: dict) -> dict:
    """
    根据宏观数据判断当前所处的桥水四象限
    
    使用指标:
      - PMI: 增长方向 (>52=增长↑, <48=增长↓)
      - CPI: 通胀方向 (>2.5=通胀↑, <1.0=通胀↓)
      - 中间区域为过渡/中性
    
    参数:
        macro_data: {
            "cpi": float,           # CPI同比%
            "pmi": float,           # 制造业PMI
            "gdp_growth": float,    # GDP增速(可选)
            "unemployment": float,  # 失业率(可选)
            ...
        }
    
    返回:
        {
            "current_quadrant": "Q2_增长↑_通胀↓",
            "quadrant_name": "象限2：增长上升+通胀下降",
            "environment": "金发女孩/复苏期",
            "recommended_assets": [...],
            "avoid_assets": [...],
            "allocation_advice": "...",
            "confidence": "高/中/低",
            "detail": {...},
        }
    """
    # 提取数据（兼容嵌套和扁平格式）
    md = macro_data.get("macro_data", macro_data) if isinstance(macro_data, dict) else {}
    if not isinstance(md, dict):
        md = macro_data or {}
    
    cpi = md.get("cpi")
    pmi = md.get("pmi")
    gdp = md.get("gdp_growth") or md.get("gdp")
    
    # 判断增长方向
    growth_signal = None
    if pmi is not None:
        if pmi > 52:
            growth_signal = "up"
        elif pmi < 48:
            growth_signal = "down"
        else:
            growth_signal = "neutral"
    elif gdp is not None:
        if gdp > 5:
            growth_signal = "up"
        elif gdp < 2:
            growth_signal = "down"
        else:
            growth_signal = "neutral"
    
    # 判断通胀方向
    inflation_signal = None
    if cpi is not None:
        if cpi > 2.5:
            inflation_signal = "up"
        elif cpi < 1.0:
            inflation_signal = "down"
        else:
            inflation_signal = "neutral"
    
    # 确定象限
    if growth_signal == "up" and inflation_signal == "up":
        quadrant_key = "Q1_增长↑_通胀↑"
        confidence = "高" if pmi and cpi else "中"
    elif growth_signal == "up" and inflation_signal == "down":
        quadrant_key = "Q2_增长↑_通胀↓"
        confidence = "高" if pmi and cpi else "中"
    elif growth_signal == "down" and inflation_signal == "up":
        quadrant_key = "Q3_增长↓_通胀↑"
        confidence = "高" if pmi and cpi else "中"
    elif growth_signal == "down" and inflation_signal == "down":
        quadrant_key = "Q4_增长↓_通胀↓"
        confidence = "高" if pmi and cpi else "中"
    else:
        # 中间状态——用最接近的象限
        if growth_signal == "neutral" and inflation_signal == "neutral":
            quadrant_key = "Q2_增长↑_通胀↓"  # 默认偏乐观
            confidence = "低（增长和通胀均在中间区）"
        elif growth_signal == "neutral":
            if inflation_signal == "up":
                quadrant_key = "Q1_增长↑_通胀↑"
            else:
                quadrant_key = "Q4_增长↓_通胀↓"
            confidence = "中（增长方向不确定）"
        elif inflation_signal == "neutral":
            if growth_signal == "up":
                quadrant_key = "Q2_增长↑_通胀↓"
            else:
                quadrant_key = "Q3_增长↓_通胀↑"
            confidence = "中（通胀方向不确定）"
        else:
            quadrant_key = "Q2_增长↑_通胀↓"
            confidence = "低（数据不足）"
    
    quad = BRIDGEWATER_QUADRANTS.get(quadrant_key, BRIDGEWATER_QUADRANTS["Q2_增长↑_通胀↓"])
    
    # ── LDS全天候对接建议 ──
    lds_adjustment = ""
    if quadrant_key == "Q1_增长↑_通胀↑":
        lds_adjustment = "LDS建议：增加商品/资源品敞口，减少长债配置。红利低波中的资源股受益。"
    elif quadrant_key == "Q2_增长↑_通胀↓":
        lds_adjustment = "LDS建议：最优象限，维持LDS全天候基准配置。纳指100在此象限表现最佳。"
    elif quadrant_key == "Q3_增长↓_通胀↑":
        lds_adjustment = "LDS建议：滞胀最难——黄金+TIPS是最佳组合。LDS中黄金25%提供保护。"
    elif quadrant_key == "Q4_增长↓_通胀↓":
        lds_adjustment = "LDS建议：增配国债/防御。红利低波在此象限有超额收益。可考虑超配TLT。"
    
    return {
        "current_quadrant": quadrant_key,
        "quadrant_name": quad["name"],
        "environment": quad["environment"],
        "recommended_assets": quad["best_assets"],
        "avoid_assets": quad["worst_assets"],
        "allocation_advice": quad["allocation_hint"],
        "china_parallel": quad.get("china_parallel", ""),
        "confidence": confidence,
        "lds_adjustment": lds_adjustment,
        "detail": {
            "growth_signal": growth_signal or "未知",
            "inflation_signal": inflation_signal or "未知",
            "cpi": cpi,
            "pmi": pmi,
            "gdp": gdp,
            "data_quality": "高" if (pmi is not None and cpi is not None) else "中" if (pmi or cpi) else "低",
        },
        "all_quadrants_summary": {
            k: {"name": v["name"], "best": v["best_assets"][:3]} 
            for k, v in BRIDGEWATER_QUADRANTS.items()
        },
    }


# ═══════════════════════════════════════════════════════════════
# 7. 综合扫描（一键调用所有模块）
# ═══════════════════════════════════════════════════════════════

def full_asset_scan(macro_data: dict = None, skip: list = None) -> dict:
    """
    一键全资产扫描 — 整合所有6大模块
    
    参数:
        macro_data: 宏观数据dict
        skip: 要跳过的模块列表，如 ["fx", "bonds"]
    
    返回:
        {
            "lds_portfolio": {...},     # LDS全天候组合追踪
            "etf_scan": {...},          # ETF三维扫描
            "bonds": {...},             # 债券扫描
            "commodities": {...},       # 商品扫描
            "fx": {...},                # 外汇扫描
            "bridgewater": {...},       # 桥水四象限
            "executive_summary": "...", # 执行摘要
            "timestamp": "...",
        }
    """
    skip = skip or []
    macro_data = macro_data or {}
    
    result = {
        "executive_summary": "",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    
    # ── 1. LDS全天候组合 ──
    if "lds" not in skip:
        try:
            result["lds_portfolio"] = track_lds_portfolio(macro_data)
        except Exception as e:
            result["lds_portfolio"] = {"error": str(e)}
    
    # ── 2. ETF扫描 ──
    if "etf" not in skip:
        try:
            result["etf_scan"] = scan_all_etfs(macro_data, top_n=5)
        except Exception as e:
            result["etf_scan"] = {"error": str(e)}
    
    # ── 3. 债券 ──
    if "bonds" not in skip:
        try:
            result["bonds"] = scan_bonds(macro_data)
        except Exception as e:
            result["bonds"] = {"error": str(e)}
    
    # ── 4. 商品 ──
    if "commodities" not in skip:
        try:
            result["commodities"] = scan_commodities(macro_data)
        except Exception as e:
            result["commodities"] = {"error": str(e)}
    
    # ── 5. 外汇 ──
    if "fx" not in skip:
        try:
            result["fx"] = scan_fx(macro_data)
        except Exception as e:
            result["fx"] = {"error": str(e)}
    
    # ── 6. 桥水四象限 ──
    if "bridgewater" not in skip:
        try:
            result["bridgewater"] = determine_bridgewater_quadrant(macro_data)
        except Exception as e:
            result["bridgewater"] = {"error": str(e)}
    
    # ── 执行摘要 ──
    summary_parts = []
    
    lds = result.get("lds_portfolio", {})
    if lds and "error" not in lds:
        pf = lds.get("portfolio", {})
        summary_parts.append(
            f"【LDS组合】今日{pf.get('daily_return') or '?'}% | "
            f"YTD {pf.get('ytd_return') or '?'}% | "
            f"{pf.get('risk_signal', '?')}"
        )
    
    etf = result.get("etf_scan", {})
    if etf and "error" not in etf:
        top = etf.get("top_5", [])
        if top:
            top_names = [f"{t['name']}({t.get('ret_20d', '?')}%)" for t in top[:3]]
            summary_parts.append(f"【ETF Top3】{', '.join(top_names)}")
    
    bw = result.get("bridgewater", {})
    if bw and "error" not in bw:
        summary_parts.append(
            f"【桥水象限】{bw.get('quadrant_name', '?')} | "
            f"推荐: {', '.join(bw.get('recommended_assets', [])[:3])}"
        )
    
    bonds = result.get("bonds", {})
    if bonds and "error" not in bonds:
        us_t = bonds.get("us_treasury", {})
        summary_parts.append(
            f"【美债】{us_t.get('curve_shape', '?')} | "
            f"2Y10Y利差={us_t.get('2y_10y_spread', '?')}bp"
        )
    
    result["executive_summary"] = " | ".join(summary_parts) if summary_parts else "扫描完成（部分数据不可用）"
    
    return result


def scan_summary_text(macro_data: dict = None, skip: list = None) -> str:
    """
    生成全资产扫描的纯文本摘要（适合嵌入日报/群消息）
    
    返回格式化的中文文本
    """
    data = full_asset_scan(macro_data, skip)
    lines = []
    lines.append("═" * 50)
    lines.append(f"📊 全资产扫描日报 — {data.get('timestamp', '?')}")
    lines.append("═" * 50)
    
    # LDS组合
    lds = data.get("lds_portfolio", {})
    if lds and "error" not in lds:
        pf = lds.get("portfolio", {})
        lines.append(f"\n🏛️ LDS全天候组合")
        lines.append(f"  今日涨跌: {pf.get('daily_return') or '?'}%")
        lines.append(f"  YTD: {pf.get('ytd_return') or '?'}%")
        lines.append(f"  最大回撤: {pf.get('max_drawdown') or '?'}%")
        lines.append(f"  风险信号: {pf.get('risk_signal', '?')}")
        lines.append(f"  再平衡: {'⚠️ 需要' if pf.get('need_rebalance') else '✅ 不需'}")
        for comp in lds.get("components", []):
            lines.append(
                f"  {comp.get('signal','➖')} {comp['name']}: "
                f"{comp.get('price') or '?'} "
                f"({comp.get('ret_1d') or '?'}%) "
                f"[{comp.get('asset_class','')}]"
            )
    
    # ETF Top 5
    etf = data.get("etf_scan", {})
    if etf and "error" not in etf:
        lines.append(f"\n📦 ETF三维排序 Top 5 (动量40%+低波30%+低费率30%)")
        for i, e in enumerate(etf.get("top_5", [])[:5]):
            lines.append(
                f"  {i+1}. {e['name']}({e['symbol']}): "
                f"动量{e.get('ret_20d','?')}% | "
                f"波动率{e.get('volatility_20d','?')}% | "
                f"费率{e.get('expense_ratio','?')}% | "
                f"综合{e.get('_composite','?')}"
            )
    
    # 债券
    bonds = data.get("bonds", {})
    if bonds and "error" not in bonds:
        us_t = bonds.get("us_treasury", {})
        lines.append(f"\n🏦 债券市场")
        lines.append(f"  曲线形态: {us_t.get('curve_shape', '?')}")
        lines.append(f"  2Y10Y利差: {us_t.get('2y_10y_spread', '?')}bp")
        lines.append(f"  信号: {us_t.get('signal', '?')}")
        if bonds.get("cn_us_spread"):
            lines.append(f"  中美利差: {bonds['cn_us_spread']}bp")
    
    # 商品
    comm = data.get("commodities", {})
    if comm and "error" not in comm:
        lines.append(f"\n🛢️ 商品市场")
        for c in comm.get("commodities", [])[:4]:
            lines.append(
                f"  {c.get('signal','➖')} {c['name']}: "
                f"{c.get('price') or '?'} | "
                f"20日{c.get('ret_20d','?')}% | "
                f"RSI={c.get('rsi_14','?')}"
            )
        lines.append(f"  国运线: {comm.get('lds_guoyun_view', '?')[:120]}")
    
    # 外汇
    fx = data.get("fx", {})
    if fx and "error" not in fx:
        lines.append(f"\n💱 外汇市场")
        for f in fx.get("fx_pairs", [])[:4]:
            lines.append(
                f"  {f.get('signal','➖')} {f['name']}: {f.get('price') or '?'}"
            )
        lines.append(f"  {fx.get('carry_trade_risk', '?')[:120]}")
    
    # 桥水象限
    bw = data.get("bridgewater", {})
    if bw and "error" not in bw:
        lines.append(f"\n🌉 桥水全天候四象限")
        lines.append(f"  当前: {bw.get('quadrant_name', '?')}")
        lines.append(f"  环境: {bw.get('environment', '?')}")
        lines.append(f"  推荐资产: {', '.join(bw.get('recommended_assets', [])[:3])}")
        lines.append(f"  回避资产: {', '.join(bw.get('avoid_assets', [])[:3])}")
        lines.append(f"  置信度: {bw.get('confidence', '?')}")
        lines.append(f"  {bw.get('lds_adjustment', '')}")
    
    lines.append("\n" + "═" * 50)
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# 自测入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  全资产扫描模块 v1.0 — 自测")
    print("=" * 60)
    
    # 模拟宏观数据
    test_macro = {
        "cpi": 2.1,
        "pmi": 51.5,
        "gdp_growth": 4.8,
        "cn_10y": 2.85,
    }
    
    # 1. LDS组合
    print("\n[1/6] LDS全天候组合追踪...")
    lds = track_lds_portfolio(test_macro)
    pf = lds.get("portfolio", {})
    print(f"  组合今日: {pf.get('daily_return')}% | YTD: {pf.get('ytd_return')}%")
    print(f"  最大回撤: {pf.get('max_drawdown')}% | 再平衡: {pf.get('need_rebalance')}")
    for c in lds.get("components", []):
        print(f"    {c['signal']} {c['name']}: {c.get('price')} ({c.get('ret_1d')}%)")
    
    # 2. ETF扫描
    print("\n[2/6] ETF全景扫描...")
    etf = scan_all_etfs(test_macro, top_n=5)
    for i, e in enumerate(etf.get("top_5", [])[:5]):
        print(f"  {i+1}. {e['name']}({e['symbol']}): 综合{e.get('_composite')} | 动量{e.get('ret_20d')}%")
    print(f"  总共扫描: {etf.get('total_scanned')}只ETF")
    
    # 3. 债券
    print("\n[3/6] 债券扫描...")
    bonds = scan_bonds(test_macro)
    us_t = bonds.get("us_treasury", {})
    print(f"  曲线形态: {us_t.get('curve_shape')} | 2Y10Y利差: {us_t.get('2y_10y_spread')}bp")
    print(f"  中美利差: {bonds.get('cn_us_spread')}bp")
    
    # 4. 商品
    print("\n[4/6] 商品扫描...")
    comm = scan_commodities(test_macro)
    for c in comm.get("commodities", [])[:4]:
        print(f"  {c['signal']} {c['name']}: {c.get('price')} | RSI={c.get('rsi_14')}")
    
    # 5. 外汇
    print("\n[5/6] 外汇扫描...")
    fx = scan_fx(test_macro)
    for f in fx.get("fx_pairs", [])[:4]:
        print(f"  {f['name']}: {f.get('price')}")
    print(f"  {fx.get('carry_trade_risk')[:100]}")
    
    # 6. 桥水象限
    print("\n[6/6] 桥水四象限...")
    bw = determine_bridgewater_quadrant(test_macro)
    print(f"  当前: {bw.get('quadrant_name')}")
    print(f"  推荐: {', '.join(bw.get('recommended_assets', []))}")
    print(f"  置信度: {bw.get('confidence')}")
    
    # 综合文本摘要
    print("\n" + "=" * 60)
    print("  综合文本摘要")
    print("=" * 60)
    summary = scan_summary_text(test_macro)
    print(summary)
    
    print("\n✅ 全资产扫描模块自测完成")
