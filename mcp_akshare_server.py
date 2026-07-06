"""
AkShare MCP Server — 面基投资系统金融数据 MCP 代理

将 Hermes 投资系统的数据源（AKShare/baostock/yfinance）+ 因子引擎
封装为标准 MCP 工具，供 Hermes Agent 通过工具名直接调用。

Usage:
    python mcp_akshare_server.py                   # stdio (默认)
    python mcp_akshare_server.py --port 8090        # SSE
"""
import argparse
import json
import sys
import os
from datetime import date, datetime
from typing import Any

# Path setup
_PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
_PARENT = os.path.dirname(_PROJECT_DIR)
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp import FastMCP

server = FastMCP(
    "akshare-mcp",
    instructions="面基投资系统金融数据 — 股票/行情/财务/ETF/产业链/因子评分"
)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _to_serializable(obj):
    """Convert pandas/NumPy/non-serializable to plain Python types."""
    if obj is None:
        return None
    if hasattr(obj, "to_dict"):
        return obj.to_dict() if hasattr(obj, "to_dict") and callable(getattr(obj, "to_dict", None)) else str(obj)
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _to_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_serializable(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, float):
        return obj if not (obj != obj) else None  # NaN → None
    return obj


def _ok(data: Any) -> str:
    """Wrap result in success envelope."""
    return json.dumps({"ok": True, "data": _to_serializable(data)}, ensure_ascii=False)


def _err(msg: str) -> str:
    """Wrap error in structured envelope."""
    return json.dumps({"ok": False, "error": msg}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# MCP Tools — Data Layer
# ---------------------------------------------------------------------------

@server.tool()
def ak_search_stock(keyword: str) -> str:
    """Search A-share stocks by keyword (code or Chinese name)."""
    try:
        from data.data_router import _detect_source
        # 匹配代码前缀
        if keyword.isdigit() and len(keyword) <= 6:
            padded = keyword.zfill(6)
            # 尝试通过 akshare 获取代码列表
            import akshare as ak
            df = ak.stock_info_a_code_name()
            mask = df["code"].astype(str).str.contains(padded) | df["name"].str.contains(keyword, case=False)
            result = df[mask].head(20).to_dict(orient="records")
            return _ok(result)
        return _ok({"msg": "仅支持A股代码/名称搜索", "keyword": keyword})
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_quote(ticker: str) -> str:
    """Get real-time stock quote (A股 via AKShare, 港美股 via yfinance).

    Args:
        ticker: Stock code (e.g., "300502" for A股, "0700.HK" for港股, "NVDA" for美股)
    """
    try:
        from data.data_router import get_rt
        rt = get_rt(ticker)
        if rt:
            return _ok(rt)
        return _err(f"no data for {ticker}")
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_historical(ticker: str, days: int = 365) -> str:
    """Get historical OHLCV price data.

    Args:
        ticker: Stock code
        days: Number of trading days of history (default 365)
    """
    try:
        from data.data_router import get_history
        hist = get_history(ticker, days)
        if hist:
            return _ok(hist)
        return _err(f"no historical data for {ticker}")
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_financials(ticker: str) -> str:
    """Get latest financial report data for an A-share stock.

    Returns ROE, gross margin, debt ratio, OCF per share, net margin,
    revenue growth, profit growth, dividend yield, etc.
    """
    try:
        from data.data_layer import get_financial_report
        fin = get_financial_report(ticker)
        if fin:
            return _ok(fin)
        return _err(f"no financial data for {ticker}")
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_industry_stocks(industry: str = "") -> str:
    """List stocks in an industry (东方财富行业分类).

    Args:
        industry: Industry name in Chinese (e.g., "半导体", "银行", "白酒").
                  If empty, returns all available industry names.
    """
    try:
        import akshare as ak
        if not industry:
            df = ak.stock_board_industry_name_em()
            return _ok(df[["板块名称", "板块代码"]].head(50).to_dict(orient="records"))
        cons = ak.stock_board_industry_cons_em(symbol=industry)
        return _ok(cons.to_dict(orient="records"))
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_index(index_code: str = "000001") -> str:
    """Get A-share index historical data.

    Args:
        index_code: Index code. Common: 000001(上证), 399001(深证),
                    399006(创业板), 000688(科创50), 000300(沪深300)
    """
    try:
        import akshare as ak
        mapping = {
            "000001": "sh000001", "399001": "sz399001",
            "399006": "sz399006", "000688": "sh000688",
            "000300": "sh000300", "000016": "sh000016",
        }
        symbol = mapping.get(index_code, f"sh{index_code}" if index_code.startswith("00") else index_code)
        df = ak.stock_zh_index_daily(symbol=symbol)
        return _ok(df.tail(500).to_dict(orient="records"))
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_stock_info(ticker: str) -> str:
    """Get company profile for an A-share stock.

    Returns industry, market cap, listing date, business scope, etc.
    """
    try:
        import akshare as ak
        info = ak.stock_individual_info_em(symbol=ticker)
        return _ok(info.to_dict(orient="records"))
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# MCP Tools — Factor Engine (面基特色)
# ---------------------------------------------------------------------------

@server.tool()
def ak_get_factor_scores(ticker: str) -> str:
    """Score a single stock using the 8-factor engine.

    Returns 8 style factor scores (quality/value/growth/momentum/low_vol/
    sentiment/risk/dividend), composite score [0,1], and sub-factor breakdown.
    """
    try:
        from analysis.factor_engine import FactorEngine
        engine = FactorEngine()
        result = engine.score_symbol(ticker)
        return _ok(result)
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_batch_scores(tickers: str) -> str:
    """Score multiple stocks with cross-sectional standardization (排名分位).

    Args:
        tickers: Comma-separated stock codes (e.g., "300502,688041,600519")

    Returns ranked list with composite scores and style breakdown.
    """
    try:
        symbols = [s.strip() for s in tickers.split(",") if s.strip()]
        if not symbols:
            return _err("no tickers provided")
        from analysis.factor_engine import FactorEngine
        engine = FactorEngine()
        results = engine.score_batch(symbols)
        return _ok(results)
    except Exception as e:
        return _err(str(e))


@server.tool()
def ak_get_technical_indicators(ticker: str) -> str:
    """Compute technical indicators for a stock.

    Returns: RSI(14), MACD (金叉/死叉), MA20/MA60 deviation,
    Bollinger position, composite tech score.
    """
    try:
        from data.data_layer import get_stock_daily
        import numpy as np
        import pandas as pd

        df = get_stock_daily(ticker, days=120)
        if df is None or df.empty:
            return _err(f"no data for {ticker}")

        close_col = "close" if "close" in df.columns else df.columns[4]
        close = df[close_col].values.astype(float)

        tech = {}
        # MA deviations
        if len(close) >= 20:
            tech["ma20_dev"] = round((close[-1] / np.mean(close[-20:]) - 1) * 100, 2)
        if len(close) >= 60:
            tech["ma60_dev"] = round((close[-1] / np.mean(close[-60:]) - 1) * 100, 2)

        # RSI(14)
        if len(close) > 14:
            gains = np.maximum(np.diff(close[-15:]), 0)
            losses = np.maximum(-np.diff(close[-15:]), 0)
            avg_g = np.mean(gains)
            avg_l = np.mean(losses) if np.mean(losses) > 0 else 1
            tech["rsi"] = round(100 - 100 / (1 + avg_g / avg_l), 1)
        else:
            tech["rsi"] = 50

        # MACD
        if len(close) > 35:
            s = pd.Series(close)
            ema12 = s.ewm(span=12, adjust=False).mean()
            ema26 = s.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            hist = macd_line - signal_line
            tech["macd_hist"] = round(float(hist.iloc[-1]), 4)
            prev_macd = macd_line.iloc[-2] - signal_line.iloc[-2]
            tech["macd_signal"] = "金叉" if hist.iloc[-1] > 0 and prev_macd <= 0 else ("死叉" if hist.iloc[-1] < 0 and prev_macd >= 0 else "中性")
            tech["macd"] = round(float(macd_line.iloc[-1]), 4)
        else:
            tech["macd_signal"] = "中性"

        # Bollinger
        if len(close) > 20:
            ma = np.mean(close[-20:])
            std = np.std(close[-20:])
            upper = ma + 2 * std
            lower = ma - 2 * std
            if close[-1] >= upper:
                tech["bollinger_pos"] = "上轨"
            elif close[-1] <= lower:
                tech["bollinger_pos"] = "下轨"
            else:
                tech["bollinger_pos"] = "中轨"

        # Composite tech score
        score = 5.0
        if tech.get("rsi", 50) and 30 < tech["rsi"] < 70:
            score += 1
        if tech.get("macd_signal", "") == "金叉":
            score += 1.5
        if -5 < tech.get("ma60_dev", 0) < 10:
            score += 1
        if tech.get("ma20_dev", 0) and tech["ma20_dev"] > 0:
            score += 0.5
        tech["total_tech_score"] = round(score, 1)

        return _ok(tech)
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=0, help="SSE port (0 = stdio)")
    args = parser.parse_args()

    if args.port:
        print(f"[akshare-mcp] SSE mode on port {args.port}", file=sys.stderr, flush=True)
        server.run(transport="sse", port=args.port)
    else:
        print("[akshare-mcp] stdio mode", file=sys.stderr, flush=True)
        server.run(transport="stdio")
