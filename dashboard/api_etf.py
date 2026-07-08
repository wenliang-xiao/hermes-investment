"""ETF 扫描/组合/详情 API"""

import json
from datetime import datetime
from fastapi import APIRouter
from dashboard.shared import ROOT

router = APIRouter()


@router.get("/api/v2/etf")
def api_v2_etf():
    """ETF组合建议"""
    path = ROOT / "data" / "etf_portfolio.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


@router.get("/api/v2/etf/universe")
def api_v2_etf_universe(category: str = "", region: str = ""):
    """ETF标的池 — 按类别/地区筛选"""
    from data.etf_universe import ALL_ETF, ETF_BY_SYMBOL
    result = []
    for e in ALL_ETF:
        if category and e.category != category:
            continue
        if region and e.region != region:
            continue
        result.append({
            "symbol": e.symbol, "name": e.name, "category": e.category,
            "region": e.region, "benchmark": e.benchmark, "fee_pct": e.fee_pct,
        })
    return {"total": len(result), "etfs": result}


@router.get("/api/v2/etf/scan")
def api_v2_etf_scan(category: str = "", region: str = ""):
    """ETF扫描 — 趋势+动量+波动率"""
    from data.etf_universe import ALL_ETF
    from data.data_router import get_history
    import numpy as _np

    etfs = ALL_ETF
    if category:
        etfs = [e for e in etfs if e.category == category]
    if region:
        etfs = [e for e in etfs if e.region == region]

    results = []
    for e in etfs:
        try:
            raw = get_history(e.symbol, days=130)
            if not raw or "close" not in raw or len(raw["close"]) < 20:
                continue
            closes = raw["close"]
            current = closes[-1]
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / min(60, len(closes)) if len(closes) >= 60 else sum(closes) / len(closes)
            ret_20d = (closes[-1] - closes[-20]) / closes[-20] * 100 if len(closes) >= 20 and closes[-20] > 0 else 0
            ret_60d = (closes[-1] - closes[-60]) / closes[-60] * 100 if len(closes) >= 60 and closes[-60] > 0 else 0
            vol_20d = _np.std(closes[-20:] / _np.array(closes[-21:-1]) - 1) * (252**0.5) * 100 if len(closes) >= 21 else 0
            trend = "↑" if ma20 > ma60 else "↓"
            trend_strength = abs(ma20 - ma60) / ma60 * 100 if ma60 > 0 else 0
            results.append({
                "symbol": e.symbol, "name": e.name, "category": e.category,
                "region": e.region, "benchmark": e.benchmark,
                "price": round(current, 4), "ma20": round(ma20, 4), "ma60": round(ma60, 4),
                "trend": trend, "trend_strength": round(trend_strength, 2),
                "ret_20d": round(ret_20d, 2), "ret_60d": round(ret_60d, 2),
                "vol_20d": round(vol_20d, 2),
                "is_timing": e.symbol in ("510300", "511010", "512480", "518880", "513100"),
                "is_rp": e.symbol in ("510300", "511010", "518880", "159985"),
            })
        except Exception:
            continue
    results.sort(key=lambda x: x.get("ret_20d", 0), reverse=True)
    return {"total": len(results), "scan_date": datetime.now().strftime("%Y-%m-%d"), "etfs": results}


@router.get("/api/v2/etf/detail/{symbol}")
def api_v2_etf_detail(symbol: str):
    """ETF深度分析 — 价格+趋势+历史回报+组合归属"""
    from data.etf_universe import ETF_BY_SYMBOL
    from data.data_router import get_history
    import numpy as _np

    etf = ETF_BY_SYMBOL.get(symbol)
    if not etf:
        return {"error": f"未知ETF: {symbol}"}

    raw = get_history(symbol, days=400)
    if not raw or "close" not in raw or len(raw["close"]) < 20:
        return {"error": f"数据不足: {symbol}", "etf": {"symbol": etf.symbol, "name": etf.name}}

    closes = raw["close"]
    dates = raw.get("dates", [])
    current = closes[-1]
    ma5 = sum(closes[-5:]) / 5 if len(closes) >= 5 else current
    ma20 = sum(closes[-20:]) / 20 if len(closes) >= 20 else current
    ma60 = sum(closes[-60:]) / min(60, len(closes)) if len(closes) >= 60 else current
    ma120 = sum(closes[-120:]) / min(120, len(closes)) if len(closes) >= 120 else current

    returns = {}
    for label, days in [("1d", 1), ("1w", 5), ("1m", 20), ("3m", 60), ("6m", 120), ("1y", 250)]:
        if len(closes) > days and closes[-days - 1] > 0:
            returns[label] = round((closes[-1] - closes[-days - 1]) / closes[-days - 1] * 100, 2)

    vol_20d = 0
    if len(closes) >= 21:
        rets = _np.array(closes[-20:]) / _np.array(closes[-21:-1]) - 1
        vol_20d = round(_np.std(rets) * (252**0.5) * 100, 2)

    max_dd = 0
    if len(closes) >= 60:
        peak = closes[-60]
        for c in closes[-60:]:
            peak = max(peak, c)
            dd = (c - peak) / peak * 100 if peak > 0 else 0
            max_dd = min(max_dd, dd)

    trend_signals = []
    if ma5 > ma20:
        trend_signals.append("MA5>MA20 短期强势")
    if ma20 > ma60:
        trend_signals.append("MA20>MA60 中期上升趋势")
    if ma60 > ma120:
        trend_signals.append("MA60>MA120 长期上升通道")
    if ma20 < ma60:
        trend_signals.append("MA20<MA60 中期下降趋势")
    if not trend_signals:
        trend_signals.append("均线纠缠 方向不明")

    portfolio_role = []
    if symbol in ("510300", "511010", "512480", "518880", "513100"):
        portfolio_role.append("择时组合")
    if symbol in ("510300", "511010", "518880", "159985"):
        portfolio_role.append("非择时组合")

    return {
        "etf": {"symbol": etf.symbol, "name": etf.name, "category": etf.category,
                "region": etf.region, "benchmark": etf.benchmark, "fee_pct": etf.fee_pct},
        "price": {"current": round(current, 4), "ma5": round(ma5, 4), "ma20": round(ma20, 4),
                  "ma60": round(ma60, 4), "ma120": round(ma120, 4)},
        "returns": returns,
        "volatility": {"annualized_20d": vol_20d},
        "max_drawdown_60d": round(max_dd, 2),
        "trend_signals": trend_signals,
        "portfolio_role": portfolio_role,
        "latest_date": dates[-1] if dates else "",
    }


@router.get("/api/v2/etf/portfolio")
def api_v2_etf_portfolio():
    """ETF组合配置 — 择时+非择时"""
    path = ROOT / "data" / "etf_portfolio.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    try:
        from analysis.etf_portfolio import EtfPortfolioBuilder
        builder = EtfPortfolioBuilder()
        result = builder.build()
        if "error" not in result:
            builder.save_json()
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/v2/etf/discovery")
def api_v2_etf_discovery():
    """ETF动态发现 — 读取最新扫描结果的精简版

    返回 top_picks + market_regime + safe_haven, 适合 Dashboard 前端展示。
    """
    path = ROOT / "data" / "etf_discovery.json"
    if not path.exists():
        return {
            "error": "未找到发现结果，请先运行 python3 scripts/run_etf_discovery.py",
            "scan_date": None,
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 返回精简版: top_picks 仅保留核心字段
        slim_picks = []
        for e in data.get("top_picks", []):
            slim_picks.append({
                "rank": e.get("rank"),
                "symbol": e.get("symbol"),
                "name": e.get("name"),
                "category": e.get("category"),
                "composite_score": e.get("composite_score"),
                "momentum": e.get("momentum"),
                "trend_signal": e.get("trend_signal"),
                "volatility_20d": e.get("volatility_20d"),
                "recommendation": e.get("recommendation"),
            })
        return {
            "scan_date": data.get("scan_date"),
            "market_regime": data.get("market_regime"),
            "safe_haven_recommended": data.get("safe_haven_recommended"),
            "total_scanned": data.get("total_scanned"),
            "category_stats": data.get("category_stats"),
            "top_picks": slim_picks,
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/v2/etf/scan_full")
def api_v2_etf_scan_full(category: str = ""):
    """ETF全量扫描结果 — 返回完整排名列表含所有因子分

    支持按类别过滤: ?category=broad_index
    不传则返回全部排名。
    """
    path = ROOT / "data" / "etf_discovery.json"
    if not path.exists():
        return {
            "error": "未找到发现结果，请先运行 python3 scripts/run_etf_discovery.py",
            "scan_date": None,
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        top_picks = data.get("top_picks", [])
        if category:
            top_picks = [e for e in top_picks if e.get("category") == category]

        return {
            "scan_date": data.get("scan_date"),
            "scan_timestamp": data.get("scan_timestamp"),
            "market_regime": data.get("market_regime"),
            "safe_haven_recommended": data.get("safe_haven_recommended"),
            "total_scanned": data.get("total_scanned"),
            "category_stats": data.get("category_stats"),
            "filtered_count": len(top_picks),
            "top_picks": top_picks,
        }
    except Exception as e:
        return {"error": str(e)}
