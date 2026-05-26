"""
yfinance 全球数据层 v1.0
美股/港股/ETF/大宗商品/汇率/债券 统一数据获取
支持多因子评分（与A股baostock因子等价可比）
"""
import yfinance as yf
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

_LAST_CALL = 0
_MIN_INTERVAL = 0.5

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

# ═══════════════════════════════════════════
# 1. 价格数据
# ═══════════════════════════════════════════

def get_price_data(symbol: str, period: str = "6mo") -> pd.DataFrame:
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
        result = _fetch_with_retry(_fetch)
        return result if result is not None else pd.DataFrame()
    except Exception as e:
        logger.warning("[yf] %s 价格获取失败: %s", symbol, e)
        return pd.DataFrame()

def get_current_price(symbol: str) -> Optional[float]:
    _rate_limit()
    def _fetch():
        t = yf.Ticker(symbol)
        hist = t.history(period="5d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        info = t.fast_info
        p = info.get("lastPrice") or info.get("regularMarketPrice")
        return float(p) if p else None
    try:
        return _fetch_with_retry(_fetch)
    except Exception as e:
        logger.warning("[yf] %s 价格获取失败: %s", symbol, e)
        return None

def get_current_prices_batch(symbols: list) -> Dict[str, float]:
    """批量获取最新价格"""
    results = {}
    for sym in symbols:
        price = get_current_price(sym)
        if price:
            results[sym] = price
    return results

# ═══════════════════════════════════════════
# 2. 基础信息
# ═══════════════════════════════════════════

def get_stock_info(symbol: str) -> dict:
    """获取个股基础信息"""
    _rate_limit()
    try:
        t = yf.Ticker(symbol)
        info = t.info
        return {
            "name": info.get("longName") or info.get("shortName", symbol),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap"),
            "country": info.get("country", ""),
            "exchange": info.get("exchange", ""),
            "currency": info.get("currency", "USD"),
            "website": info.get("website", ""),
            "employees": info.get("fullTimeEmployees"),
        }
    except Exception as e:
        return {"name": symbol, "error": str(e)[:100]}

# ═══════════════════════════════════════════
# 3. 财务因子数据（用于多因子评分）
# ═══════════════════════════════════════════

def get_factor_data(symbol: str) -> dict:
    """获取因子计算所需财务+市场数据"""
    _rate_limit()
    try:
        t = yf.Ticker(symbol)
        info = t.info
        return {
            # ── 估值因子 ──
            "pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb": info.get("priceToBook"),
            "ps": info.get("priceToSalesTrailing12Months"),
            "ev_to_ebitda": info.get("enterpriseToEbitda"),
            # ── 质量因子 ──
            "roe": info.get("returnOnEquity"),      # 小数形式，如0.20=20%
            "roa": info.get("returnOnAssets"),
            "profit_margin": info.get("profitMargins"),
            "operating_margin": info.get("operatingMargins"),
            # ── 成长因子 ──
            "revenue_growth": info.get("revenueGrowth"),    # YoY小数
            "earnings_growth": info.get("earningsGrowth"),
            "earnings_quarterly_growth": info.get("earningsQuarterlyGrowth"),
            # ── 红利因子 ──
            "dividend_yield": info.get("dividendYield"),    # 小数，如0.02=2%
            "payout_ratio": info.get("payoutRatio"),
            # ── 风险因子 ──
            "beta": info.get("beta"),
            "short_ratio": info.get("shortPercentOfFloat"),
            # ── 价格位置 ──
            "52w_high": info.get("fiftyTwoWeekHigh"),
            "52w_low": info.get("fiftyTwoWeekLow"),
            "50d_avg": info.get("fiftyDayAverage"),
            "200d_avg": info.get("twoHundredDayAverage"),
            # ── 市场数据 ──
            "market_cap": info.get("marketCap"),
            "volume": info.get("volume"),
            "avg_volume": info.get("averageVolume"),
            # ── 分析师 ──
            "analyst_mean": info.get("recommendationMean"),  # 1=强力买入,5=卖出
            "analyst_count": info.get("numberOfAnalystOpinions"),
            "target_mean": info.get("targetMeanPrice"),
        }
    except Exception as e:
        return {"error": str(e)[:100]}

# ═══════════════════════════════════════════
# 4. 多因子评分（与A股6因子体系对齐）
# ═══════════════════════════════════════════

def _bounded_linear_score(value, lo, hi, reverse=False) -> float:
    """将值映射到1-10分"""
    if value is None or hi <= lo:
        return 5.0
    score = 1 + 9 * (value - lo) / (hi - lo)
    score = max(1, min(10, score))
    return 10 - score + 1 if reverse else score

def score_stock(symbol: str, name: str = "", chain_info: dict = None) -> dict:
    """
    对单只美股/港股进行6因子评分
    返回格式与A股FactorScanner兼容
    """
    # 获取数据
    factor_data = get_factor_data(symbol)
    if "error" in factor_data:
        return {"symbol": symbol, "name": name, "score": 0, "error": factor_data["error"]}
    
    price_df = get_price_data(symbol, period="6mo")
    price = get_current_price(symbol)
    
    # ── 1. 价值因子 (PE低=高分, PB低=高分) ──
    pe = factor_data.get("pe")
    pb = factor_data.get("pb")
    # 美股PE参考范围: 10-45, PB: 1-15
    s_pe = _bounded_linear_score(pe, 10, 45, reverse=True) if pe and pe > 0 else 5.0
    s_pb = _bounded_linear_score(pb, 1, 15, reverse=True) if pb and pb > 0 else 5.0
    value_score = round(s_pe * 0.6 + s_pb * 0.4, 1)
    
    # ── 2. 质量因子 (ROE高=高分) ──
    roe = factor_data.get("roe")
    margin = factor_data.get("profit_margin")
    s_roe = _bounded_linear_score(roe, 0, 0.50) if roe is not None else 5.0  # ROE 0-50%
    s_margin = _bounded_linear_score(margin, 0, 0.45) if margin is not None else 5.0
    quality_score = round(s_roe * 0.6 + s_margin * 0.4, 1)
    
    # ── 3. 成长因子 (营收增速+盈利增速) ──
    rev_g = factor_data.get("revenue_growth")
    earn_g = factor_data.get("earnings_growth")
    s_rev = _bounded_linear_score(rev_g, -0.1, 0.80) if rev_g is not None else 5.0
    s_earn = _bounded_linear_score(earn_g, -0.2, 1.50) if earn_g is not None else 5.0
    growth_score = round(s_rev * 0.4 + s_earn * 0.6, 1)
    
    # ── 4. 低波因子 (波动率低=高分) ──
    if not price_df.empty and len(price_df) >= 20:
        close = price_df["close"]
        daily_ret = close.pct_change().dropna()
        vol = float(daily_ret.tail(20).std() * np.sqrt(252) * 100)
        # 美股波动率参考: 15-70%
        lowvol_score = round(_bounded_linear_score(vol, 15, 70, reverse=True), 1)
    else:
        lowvol_score = 5.0
    
    # ── 5. 红利因子 (股息率高=高分) ──
    div_yield = factor_data.get("dividend_yield")
    if div_yield is not None:
        div_pct = div_yield * 100 if div_yield < 1 else div_yield  # 转百分比
        dividend_score = round(_bounded_linear_score(div_pct, 0, 6), 1)
    else:
        dividend_score = 5.0
    
    # ── 6. 动量因子 (近期回报) ──
    if not price_df.empty and len(price_df) >= 60:
        close = price_df["close"]
        ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0
        ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else 0
        # 混合动量
        momentum_raw = ret_20d * 0.6 + ret_60d * 0.4
        momentum_score = round(_bounded_linear_score(momentum_raw, -25, 50), 1)
    else:
        momentum_score = 5.0
    
    # ── 技术面加成 ──
    tech_bonus = 0.0
    if not price_df.empty and len(price_df) >= 200:
        close = price_df["close"]
        ma50 = float(close.tail(50).mean())
        ma200 = float(close.tail(200).mean())
        curr = float(close.iloc[-1])
        if curr > ma50: tech_bonus += 0.3
        if curr > ma200: tech_bonus += 0.3
        if ma50 > ma200: tech_bonus += 0.4  # 金叉
    
    # ── 加权综合（当前默认权重，可由宏观引擎动态调整） ──
    weights = {"质量": 0.23, "价值": 0.17, "成长": 0.17, "低波": 0.17, "红利": 0.17, "动量": 0.09}
    total = (
        weights["质量"] * quality_score +
        weights["价值"] * value_score +
        weights["成长"] * growth_score +
        weights["低波"] * lowvol_score +
        weights["红利"] * dividend_score +
        weights["动量"] * momentum_score
    )
    total = min(10, total + tech_bonus)
    
    # 价格位置
    hi52 = factor_data.get("52w_high")
    lo52 = factor_data.get("52w_low")
    pct_52w = round((price - lo52) / (hi52 - lo52) * 100, 1) if price and hi52 and lo52 and hi52 > lo52 else None
    
    return {
        "symbol": symbol,
        "name": name or factor_data.get("name", symbol),
        "market": "HK" if ".HK" in symbol else "US",
        "score": round(total, 2),
        "factors": {
            "质量": quality_score,
            "价值": value_score,
            "成长": growth_score,
            "低波": lowvol_score,
            "红利": dividend_score,
            "动量": momentum_score,
        },
        "price": price,
        "pe": factor_data.get("pe"),
        "pb": factor_data.get("pb"),
        "roe": factor_data.get("roe"),
        "market_cap": factor_data.get("market_cap"),
        "pct_52w": pct_52w,
        "analyst_mean": factor_data.get("analyst_mean"),
        # ── Nick四问所需字段 ──
        "earnings_growth": factor_data.get("earnings_growth"),
        "50d_avg": factor_data.get("50d_avg"),
        "200d_avg": factor_data.get("200d_avg"),
        "target_mean": factor_data.get("target_mean"),
        "short_ratio": factor_data.get("short_ratio"),
        "beta": factor_data.get("beta"),
        "chain": chain_info.get("chain", "") if chain_info else "",
        "chain_pos": chain_info.get("chain_pos", "") if chain_info else "",
    }

# ═══════════════════════════════════════════
# 5. 批量扫描
# ═══════════════════════════════════════════

def scan_us_stocks(chain_filter: str = None, max_stocks: int = 50) -> list:
    """扫描美股选票池，返回因子评分排序"""
    from investment_system.data.global_universe import ALL_US_STOCKS, US_CHAINS, US_ETFS
    
    candidates = {}
    if chain_filter and chain_filter in US_CHAINS:
        candidates = US_CHAINS[chain_filter]
    else:
        candidates = ALL_US_STOCKS
    
    results = []
    count = 0
    for sym, info in candidates.items():
        if count >= max_stocks:
            break
        print(f"  [yf] 扫描 {sym} ({info['name']})...")
        result = score_stock(sym, name=info["name"],
                           chain_info={"chain": info.get("sector", ""),
                                      "chain_pos": info.get("chain_pos", "")})
        if result.get("score", 0) > 0:
            results.append(result)
        count += 1
    
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results

def scan_hk_stocks(max_stocks: int = 24) -> list:
    """扫描港股权重池"""
    from investment_system.data.global_universe import HK_WATCHLIST_V2
    
    results = []
    count = 0
    for sym, info in HK_WATCHLIST_V2.items():
        if count >= max_stocks:
            break
        print(f"  [yf] 扫描港股 {sym} ({info['name']})...")
        result = score_stock(sym, name=info["name"],
                           chain_info={"chain": info.get("chain", ""), "chain_pos": ""})
        if result.get("score", 0) > 0:
            results.append(result)
        count += 1
    
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results

def scan_us_etfs(max_etfs: int = 22) -> list:
    """扫描美股ETF"""
    from investment_system.data.global_universe import US_ETFS
    
    results = []
    for sym, info in US_ETFS.items():
        print(f"  [yf] 扫描ETF {sym} ({info['name']})...")
        try:
            _rate_limit()
            t = yf.Ticker(sym)
            hist = t.history(period="6mo")
            if hist.empty:
                continue
            close = hist["Close"]
            price = float(close.iloc[-1])
            ret_20d = float((close.iloc[-1] / close.iloc[-20] - 1) * 100) if len(close) >= 20 else 0
            ret_60d = float((close.iloc[-1] / close.iloc[-60] - 1) * 100) if len(close) >= 60 else 0
            
            info_full = t.info
            results.append({
                "symbol": sym,
                "name": info["name"],
                "market": "US",
                "category": info.get("category", ""),
                "price": price,
                "ret_20d": round(ret_20d, 2),
                "ret_60d": round(ret_60d, 2),
                "ytd_return": info_full.get("ytdReturn"),
                "fifty_day_avg": info_full.get("fiftyDayAverage"),
                "volume": info_full.get("volume"),
            })
        except Exception as e:
            print(f"    ✗ {sym}: {e}")
    
    results.sort(key=lambda x: x.get("ret_20d", 0), reverse=True)
    return results

def scan_commodities_fx_bonds() -> dict:
    """扫描大宗商品/汇率/债券/情绪"""
    from investment_system.data.global_universe import COMMODITIES_V2, FX_V2, BONDS_V2, SENTIMENT_V2
    
    results = {"commodities": [], "fx": [], "bonds": [], "sentiment": []}
    
    for sym, info in COMMODITIES_V2.items():
        try:
            price = get_current_price(sym)
            results["commodities"].append({**info, "symbol": sym, "price": price})
        except:
            pass
    
    for sym, info in FX_V2.items():
        try:
            price = get_current_price(sym)
            results["fx"].append({**info, "symbol": sym, "price": price})
        except:
            pass
    
    for sym, info in BONDS_V2.items():
        try:
            price = get_current_price(sym)
            results["bonds"].append({**info, "symbol": sym, "price": price})
        except:
            pass
    
    for sym, info in SENTIMENT_V2.items():
        try:
            price = get_current_price(sym)
            results["sentiment"].append({**info, "symbol": sym, "price": price})
        except:
            pass
    
    return results

# ═══════════════════════════════════════════
# 6. 快速概览（日报开篇用）
# ═══════════════════════════════════════════

_SNAPSHOT_SANITY = {
    "GC=F":     (2000, 5500),   # 黄金 USD/oz（央行购金+地缘驱动，2025年已破4500）
    "CL=F":     (30,   130),    # WTI原油 USD/bbl
    "HG=F":     (2.5,  7.0),    # 铜 USD/lb
    "SI=F":     (15,   100),    # 白银 USD/oz（工业+贵金属双属性，弹性大）
    "NG=F":     (1.0,  10.0),   # 天然气 USD/MMBtu
    "^TNX":     (0.1,  8.0),    # 美债10Y收益率 %
    "^TYX":     (0.1,  8.0),    # 美债30Y收益率 %
    "^VIX":     (5,    80),     # VIX恐慌指数
    "CNY=X":    (6.0,  7.5),    # USD/CNY 在岸（人民币升值趋势）
    "EURUSD=X": (0.9,  1.5),    # EUR/USD 正向
}

def _validated_price(sym: str, price) -> Optional[float]:
    if price is None:
        return None
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    bounds = _SNAPSHOT_SANITY.get(sym)
    if bounds and not (bounds[0] <= p <= bounds[1]):
        logger.warning("[快照价格异常] %s=%.4f 超出%s，丢弃", sym, p, bounds)
        return None
    return p

def get_global_market_snapshot() -> dict:
    snap = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "indices": {},
        "commodities": {},
        "fx": {},
        "bonds": {},
        "sentiment": {},
    }

    for sym, name in [("^GSPC", "标普500"), ("^IXIC", "纳斯达克"), ("^DJI", "道指"),
                      ("^HSI", "恒生"), ("^N225", "日经")]:
        try:
            price = get_current_price(sym)
            if price is not None:
                snap["indices"][name] = {"price": round(float(price), 2), "change_pct": None}
        except Exception as e:
            logger.debug("[快照] 指数 %s 失败: %s", sym, e)

    for sym, name in [("GC=F", "黄金"), ("CL=F", "WTI原油"), ("HG=F", "铜")]:
        try:
            raw = get_current_price(sym)
            p = _validated_price(sym, raw)
            snap["commodities"][name] = p
        except Exception as e:
            logger.debug("[快照] 商品 %s 失败: %s", sym, e)

    for sym, name in [("CNY=X", "USD/CNY"), ("EURUSD=X", "EUR/USD"), ("JPY=X", "USD/JPY")]:
        try:
            raw = get_current_price(sym)
            p = _validated_price(sym, raw)
            if sym == "EURUSD=X" and p is not None and not (0.8 <= p <= 1.6):
                logger.warning("[快照] EUR/USD=%.4f 方向可能倒置，丢弃", p)
                p = None
            snap["fx"][name] = p
        except Exception as e:
            logger.debug("[快照] 汇率 %s 失败: %s", sym, e)

    for sym, name in [("^TNX", "美债10Y"), ("^TYX", "美债30Y")]:
        try:
            raw = get_current_price(sym)
            p = _validated_price(sym, raw)
            snap["bonds"][name] = p
        except Exception as e:
            logger.debug("[快照] 债券 %s 失败: %s", sym, e)

    try:
        raw = get_current_price("^VIX")
        p = _validated_price("^VIX", raw)
        snap["sentiment"]["VIX"] = p
    except Exception as e:
        logger.debug("[快照] VIX 失败: %s", e)

    return snap

if __name__ == "__main__":
    # 快速测试
    snap = get_global_market_snapshot()
    for cat, data in snap.items():
        if isinstance(data, dict):
            print(f"\n{cat}:")
            for k, v in data.items():
                print(f"  {k}: {v}")
