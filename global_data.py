"""
全局市场数据采集 — 多资产类别数据层 v3.3
面基全市场调研框架：汇率、债券、全球指数、港美股、大宗商品
同等权重关注所有关键资产类别

数据源：
  - ChinaMoney.com.cn (央行官方汇率) → FX
  - Yahoo Finance v8 API (港美股/债券/商品/全球指数)
  - Baostock (A股/ETF，与 data_layer.py 复用)
"""

import json
import time
import urllib.request
import urllib.error
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

from .config import (
    DATA_DIR, FX_PAIRS, BOND_MARKETS, GLOBAL_INDICES,
    HK_WATCHLIST, US_WATCHLIST, A_SHARE_ETF_WATCHLIST,
    REAL_ESTATE_WATCHLIST as REAL_ESTATE,
    COMMODITIES,
)

CACHE_FILE = DATA_DIR / "global_market_cache.json"
CACHE_TTL = 7200  # 2小时缓存

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


# ============================================================
# 核心查询函数
# ============================================================

def _yahoo_price(symbol: str) -> Optional[float]:
    """查询单个标的的最新价格"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        meta = data["chart"]["result"][0]["meta"]
        return meta.get("regularMarketPrice")
    except Exception:
        return None


def _yahoo_prev_close(symbol: str) -> Optional[float]:
    """查询前收盘价"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=5d"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        meta = data["chart"]["result"][0]["meta"]
        return meta.get("chartPreviousClose")
    except Exception:
        return None


def _get_change_pct(price, prev_close):
    """安全计算涨跌幅百分比"""
    if price and prev_close and prev_close != 0:
        return round((price - prev_close) / prev_close * 100, 2)
    return 0


# ============================================================
# 1. 汇率数据 — 中国外汇交易中心
# ============================================================

def fetch_fx_rates() -> Dict[str, Any]:
    """从中国货币网获取官方汇率"""
    url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/fx/ccpr.json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e), "source": "chinamoney"}

    key_map = {
        "美元/人民币": "USD/CNY", "欧元/人民币": "EUR/CNY",
        "100日元/人民币": "100JPY/CNY", "港元/人民币": "HKD/CNY",
        "英镑/人民币": "GBP/CNY", "澳元/人民币": "AUD/CNY",
        "新西兰元/人民币": "NZD/CNY", "新加坡元/人民币": "SGD/CNY",
        "瑞士法郎/人民币": "CHF/CNY", "加元/人民币": "CAD/CNY",
        "人民币/韩元": "CNY/KRW", "人民币/泰铢": "CNY/THB",
    }

    result = {"source": "chinamoney", "timestamp": datetime.now().isoformat()}
    for record in data.get("records", []):
        cname = record.get("vrtName", "")
        rate_key = key_map.get(cname)
        if rate_key:
            price = float(record.get("price", 0))
            bp = float(record.get("bp", 0))
            result[rate_key] = {"price": price, "change_bp": bp}
    return result


# ============================================================
# 2. 债券收益率 — Yahoo Finance
# ============================================================

def fetch_bond_yields() -> Dict[str, Any]:
    """获取主要国家债券收益率"""
    result = {"source": "yahoo"}
    for key, info in BOND_MARKETS.items():
        if key == "US10Y":
            price = _yahoo_price("^TNX")
            prev = _yahoo_prev_close("^TNX")
        elif key == "CN10Y":
            price = _fetch_china_bond_yield()
            prev = None
        else:
            price = info["default"]
            prev = None
        result[key] = {
            "price": price or info["default"],
            "name": info["name"],
            "risk_sense": info["risk_sense"],
            "change_pct": _get_change_pct(price, prev) if price and prev else None,
        }
        time.sleep(1.5)
    return result


def _fetch_china_bond_yield() -> Optional[float]:
    """尝试获取中国10Y国债收益率"""
    try:
        url = "https://www.chinamoney.com.cn/r/cms/www/chinamoney/data/yw/bond/list.json"
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        for item in data.get("records", []):
            if "10年" in item.get("bondName", ""):
                return float(item.get("yield", 0))
    except Exception:
        pass
    return None


# ============================================================
# 3. 全球指数 — Yahoo Finance
# ============================================================

def fetch_global_indices() -> Dict[str, Any]:
    """获取全球主要指数最新值"""
    result = {"source": "yahoo"}
    for symbol, info in GLOBAL_INDICES.items():
        price = _yahoo_price(symbol)
        prev = _yahoo_prev_close(symbol)
        if price:
            result[symbol] = {
                "price": price,
                "name": info["name"],
                "market": info["market"],
                "prev_close": prev,
                "change_pct": _get_change_pct(price, prev),
            }
        time.sleep(1.5)
    return result


# ============================================================
# 4. 港美股 — Yahoo Finance
# ============================================================

def fetch_hk_stocks(limit: int = 5) -> Dict[str, Dict]:
    """获取港股观测池报价（limit限制API调用）"""
    result = {}
    symbols = list(HK_WATCHLIST.keys())[:limit]
    for symbol in symbols:
        info = HK_WATCHLIST.get(symbol, {})
        price = _yahoo_price(symbol)
        prev = _yahoo_prev_close(symbol)
        if price:
            result[symbol] = {
                "name": info.get("name", symbol),
                "sector": info.get("sector", ""),
                "price": round(price, 2),
                "prev_close": round(prev, 2) if prev else None,
                "change_pct": _get_change_pct(price, prev),
            }
        time.sleep(1.5)
    return result


def fetch_us_stocks(limit: int = 6) -> Dict[str, Dict]:
    """获取美股中概观测池报价"""
    result = {}
    symbols = list(US_WATCHLIST.keys())[:limit]
    for symbol in symbols:
        info = US_WATCHLIST.get(symbol, {})
        price = _yahoo_price(symbol)
        prev = _yahoo_prev_close(symbol)
        if price:
            result[symbol] = {
                "name": info.get("name", symbol),
                "sector": info.get("sector", ""),
                "price": round(price, 2),
                "prev_close": round(prev, 2) if prev else None,
                "change_pct": _get_change_pct(price, prev),
            }
        time.sleep(1.5)
    return result


# ============================================================
# 5. 大宗商品 — Yahoo Finance
# ============================================================

def fetch_commodities() -> Dict[str, Any]:
    """获取大宗商品期货价格"""
    result = {"source": "yahoo"}
    for symbol, info in COMMODITIES.items():
        price = _yahoo_price(symbol)
        prev = _yahoo_prev_close(symbol)
        if price:
            # 按商品类型决定小数位
            decimals = 2 if (isinstance(price, (int, float)) and price < 100) else 1
            result[symbol] = {
                "name": info["name"],
                "unit": info["unit"],
                "sector": info["sector"],
                "price": round(price, decimals),
                "prev_close": round(prev, decimals) if prev else None,
                "change_pct": _get_change_pct(price, prev),
            }
        else:
            result[symbol] = {
                "name": info["name"],
                "price": info["default"],
                "unit": info["unit"],
                "sector": info["sector"],
                "change_pct": 0,
            }
        time.sleep(1.5)
    return result


# ============================================================
# 6. 汇总函数（一键获取全部）
# ============================================================

def fetch_all_global_market() -> Dict[str, Any]:
    """获取所有全球市场数据"""
    result = {
        "timestamp": datetime.now().isoformat(),
        "fx": {},
        "bonds": {},
        "indices": {},
        "hk_stocks": {},
        "us_stocks": {},
        "commodities": {},
    }

    try:
        result["fx"] = fetch_fx_rates()
    except Exception as e:
        result["fx"] = {"error": str(e)}

    try:
        result["bonds"] = fetch_bond_yields()
    except Exception as e:
        result["bonds"] = {"error": str(e)}

    try:
        result["indices"] = fetch_global_indices()
    except Exception as e:
        result["indices"] = {"error": str(e)}

    try:
        result["hk_stocks"] = fetch_hk_stocks(limit=5)
    except Exception as e:
        result["hk_stocks"] = {"error": str(e)}

    try:
        result["us_stocks"] = fetch_us_stocks(limit=6)
    except Exception as e:
        result["us_stocks"] = {"error": str(e)}

    try:
        result["commodities"] = fetch_commodities()
    except Exception as e:
        result["commodities"] = {"error": str(e)}

    _save_cache(result)
    return result


def _save_cache(data: dict):
    try:
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except Exception:
        pass


def load_cached_global_data() -> Optional[Dict[str, Any]]:
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            ts = data.get("timestamp", "")
            if ts:
                age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
                if age < CACHE_TTL:
                    return data
        except Exception:
            pass
    return None


# ============================================================
# 7. 格式化输出（直观版 v2）
# ============================================================

def format_fx_section(data: Dict[str, Any]) -> str:
    """汇率格式化 — 直观显示变动方向"""
    lines = ["🌐 **汇率观测**（中国外汇交易中心）"]
    fx_data = data.get("fx", {})
    if "error" in fx_data:
        lines.append(f"  ⚠ 数据暂不可用: {fx_data['error']}")
        return "\n".join(lines)

    for pair, meta in FX_PAIRS.items():
        val = fx_data.get(pair)
        if val and isinstance(val, dict):
            price = val.get("price", "—")
            bp = val.get("change_bp", 0)
            if abs(bp) >= 50:
                arrow = "🚨"
                direction = "大幅贬值" if bp > 0 else "大幅升值"
            elif abs(bp) >= 10:
                arrow = "⬆️" if bp > 0 else "⬇️"
                direction = "贬值" if bp > 0 else "升值"
            else:
                arrow = "➡️"
                direction = "平稳"
            sense = meta.get("risk_sense", "")
            lines.append(f"  {arrow} **{pair}**: {price} ({bp:+.0f}bp {direction}) — {sense}")

    # 综合解读
    usd = fx_data.get("USD/CNY", {})
    if isinstance(usd, dict):
        try:
            usd_bp = float(usd.get("change_bp", 0))
            if usd_bp > 10:
                lines.append("  💡 **解读**: 人民币贬值中，出口型行业受益，进口型企业承压")
            elif usd_bp < -10:
                lines.append("  💡 **解读**: 人民币升值中，航空/旅游/进口消费受益")
        except (ValueError, TypeError):
            pass
    return "\n".join(lines)


def format_bond_section(data: Dict[str, Any]) -> str:
    """债券格式化 — 含中美利差分析"""
    lines = ["📊 **债券市场**"]
    bonds = data.get("bonds", {})
    if "error" in bonds:
        lines.append(f"  ⚠ {bonds['error']}")
        return "\n".join(lines)

    us10y = bonds.get("US10Y", {})
    cn10y = bonds.get("CN10Y", {})
    us_val = us10y.get("price", "—") if isinstance(us10y, dict) else "—"
    cn_val = cn10y.get("price", "—") if isinstance(cn10y, dict) else "—"

    spread_str = ""
    try:
        us_f = float(us_val)
        cn_f = float(cn_val)
        spread = us_f - cn_f
        if spread > 2:
            spread_str = f"🔴 **中美利差 {spread:+.1f}%** — 利差过大，资金外流压力"
        elif spread > 1:
            spread_str = f"🟡 中美利差 {spread:+.1f}% — 关注变化"
        else:
            spread_str = f"🟢 中美利差 {spread:+.1f}% — 正常范围"
    except (ValueError, TypeError):
        pass

    us_chg = us10y.get("change_pct") if isinstance(us10y, dict) else None
    us_trend = ""
    if us_chg is not None:
        us_trend = f"({'📈' if us_chg > 0 else '📉'} {us_chg:+.2f}%)"

    lines.append(f"  🇺🇸 **美国10Y**: {us_val}% {us_trend}")
    lines.append(f"  🇨🇳 **中国10Y**: {cn_val}%")
    if spread_str:
        lines.append(f"  {spread_str}")
    if us_f and us_f > 5:
        lines.append("  💡 US10Y>5%历史高位，对全球风险资产形成压力")
    elif us_f and us_f > 4.5:
        lines.append("  💡 US10Y 4.5-5%中性偏高，关注美联储动向")
    elif us_f:
        lines.append("  💡 US10Y<4.5%，利率环境相对友好")
    return "\n".join(lines)


def format_index_section(data: Dict[str, Any]) -> str:
    """全球指数格式化"""
    lines = ["📈 **全球关键指数**"]
    indices = data.get("indices", {})
    if "error" in indices:
        lines.append(f"  ⚠ {indices['error']}")
        return "\n".join(lines)

    for sym, info in GLOBAL_INDICES.items():
        val = indices.get(sym, {})
        if isinstance(val, dict) and val.get("price"):
            price = val["price"]
            name = info["name"]
            market = info["market"]
            chg = val.get("change_pct", 0)
            if abs(chg) >= 2:
                arrow = "🔴" if chg < 0 else "🟢"
            elif abs(chg) >= 0.5:
                arrow = "📉" if chg < 0 else "📈"
            else:
                arrow = "➡️"
            lines.append(f"  {arrow} **{name}** ({market}): {price:,.2f} ({chg:+.2f}%)")
    return "\n".join(lines)


def format_hk_section(data: Dict[str, Any]) -> str:
    """港股格式化 — 含板块信息"""
    lines = ["🇭🇰 **港股关键观测**"]
    hk = data.get("hk_stocks", {})
    if "error" in hk:
        lines.append(f"  ⚠ {hk['error']}")
        return "\n".join(lines)
    if not hk:
        return "\n".join(lines)

    for sym, info in sorted(hk.items(), key=lambda x: x[1].get("change_pct", 0)):
        name = info.get("name", sym)
        price = info.get("price", "—")
        chg = info.get("change_pct", 0)
        sector = info.get("sector", "")
        if abs(chg) >= 3:
            arrow = "🚨🔴" if chg < 0 else "🚨🟢"
        elif abs(chg) >= 1.5:
            arrow = "🔴" if chg < 0 else "🟢"
        else:
            arrow = "➡️"
        prefix = f"  {arrow} **{name}** ({sector})" if sector else f"  {arrow} **{name}**"
        lines.append(f"{prefix}: {price} | {chg:+.2f}%")
    return "\n".join(lines)


def format_us_section(data: Dict[str, Any]) -> str:
    """美股中概格式化"""
    lines = ["🇺🇸 **美股中概观测**"]
    us = data.get("us_stocks", {})
    if "error" in us:
        lines.append(f"  ⚠ {us['error']}")
        return "\n".join(lines)
    if not us:
        return "\n".join(lines)

    for sym, info in sorted(us.items(), key=lambda x: x[1].get("change_pct", 0)):
        name = info.get("name", sym)
        price = info.get("price", "—")
        chg = info.get("change_pct", 0)
        sector = info.get("sector", "")
        if abs(chg) >= 3:
            arrow = "🚨🔴" if chg < 0 else "🚨🟢"
        elif abs(chg) >= 1.5:
            arrow = "🔴" if chg < 0 else "🟢"
        else:
            arrow = "➡️"
        prefix = f"  {arrow} **{name}** ({sector})" if sector else f"  {arrow} **{name}**"
        lines.append(f"{prefix}: {price} | {chg:+.2f}%")
    return "\n".join(lines)


def format_commodities_section(data: Dict[str, Any]) -> str:
    """大宗商品格式化 — 按板块分组"""
    lines = ["🪙 **大宗商品观测**"]
    comm = data.get("commodities", {})
    if "error" in comm:
        lines.append(f"  ⚠ 数据暂不可用")
        return "\n".join(lines)

    # 按板块分组展示
    sectors = {}
    for sym, info in COMMODITIES.items():
        sec = info["sector"]
        if sec not in sectors:
            sectors[sec] = []
        val = comm.get(sym, {}) if isinstance(comm, dict) else {}
        if isinstance(val, dict) and "price" in val:
            sectors[sec].append((sym, val, info))

    for sector in ["贵金属", "工业金属", "能源", "农产品"]:
        items = sectors.get(sector, [])
        if items:
            lines.append(f"  **{sector}**")
            for sym, val, info in items:
                name = info["name"]
                price = val.get("price", "—")
                chg = val.get("change_pct", 0)
                unit = info.get("unit", "")
                if abs(chg) >= 2:
                    arrow = "🔴" if chg < 0 else "🟢"
                elif abs(chg) >= 0.5:
                    arrow = "📉" if chg < 0 else "📈"
                else:
                    arrow = "➡️"
                p_str = f"{price}{' ' + unit if unit else ''}" if isinstance(price, (int, float)) else str(price)
                lines.append(f"    {arrow} {name}: {p_str} ({chg:+.2f}%)")

    # 金油比（重要宏观指标）
    gold = comm.get("GC=F", {})
    oil = comm.get("CL=F", {})
    if isinstance(gold, dict) and isinstance(oil, dict):
        try:
            g_price = float(gold.get("price", 0))
            o_price = float(oil.get("price", 0))
            if g_price > 0 and o_price > 0:
                ratio = g_price / o_price
                if ratio > 40:
                    lines.append(f"  💡 **金油比**: {ratio:.1f}（历史高位，反映地缘风险+经济担忧）")
                elif ratio > 25:
                    lines.append(f"  💡 **金油比**: {ratio:.1f}（中性偏高，风险偏好偏弱）")
                else:
                    lines.append(f"  💡 **金油比**: {ratio:.1f}（正常范围，风险偏好中性）")
        except (ValueError, TypeError):
            pass

    return "\n".join(lines)


def format_etf_section() -> str:
    """A股ETF参考"""
    lines = ["📦 **A股ETF配置参考**"]
    for code, name in A_SHARE_ETF_WATCHLIST:
        lines.append(f"  • **{name}** ({code})")
    return "\n".join(lines)


def format_real_estate_section() -> str:
    """房地产观测"""
    lines = ["🏠 **房地产观测**"]
    lines.append("  **A股地产龙头**")
    for code, name in list(REAL_ESTATE.items())[:7]:
        lines.append(f"  • {name} ({code})")
    lines.append("  **港股地产**")
    for code, name in list(REAL_ESTATE.items())[7:]:
        lines.append(f"  • {name} ({code})")
    lines.append("")
    lines.append("  💡 提示：房产作为政策敏感型资产，需结合信贷/限购政策判断")
    return "\n".join(lines)


# ============================================================
# CLI 测试
# ============================================================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "fast":
        data = load_cached_global_data()
        if data:
            print("✅ 缓存命中")
        else:
            print("🔄 未命中，重新获取...")
            data = fetch_all_global_market()
    else:
        data = fetch_all_global_market()

    print("=" * 50)
    print("🌐 面基全市场数据采集 v3.3")
    print("=" * 50)
    print()
    print(format_fx_section(data))
    print()
    print(format_bond_section(data))
    print()
    print(format_index_section(data))
    print()
    print(format_hk_section(data))
    print()
    print(format_us_section(data))
    print()
    print(format_commodities_section(data))
    print()
    print(format_etf_section())
    print()
    print(format_real_estate_section())
    print()
    print(f"🕒 采集时间: {data.get('timestamp', '')}")
