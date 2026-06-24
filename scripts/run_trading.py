"""
每日三策略执行器
整合FactorScanner + TradingEngine → 输出 trading_signals.json
"""
import sys, os, json, math
from datetime import datetime, timedelta, date
import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)

from data.data_layer import get_stock_daily
from analysis.factor_scanner import FactorScanner
from analysis.trading_engine import TradingEngine
from config import FACTOR_WEIGHTS
from domain import WATCHLIST
import functools
print = functools.partial(print, flush=True)

# 核心标的（限定范围加速扫描）
CORE_TIERS = ("核心", "底仓", "关注")


def get_core_watchlist():
    """获取核心观察标的"""
    stocks = []
    for code, info in WATCHLIST.items():
        sym = str(code)
        if not (sym.isdigit() and (sym.startswith("0") or sym.startswith("3") or sym.startswith("6"))):
            continue
        tier = info.get("tier", "")
        if tier in CORE_TIERS:
            stocks.append({"symbol": sym, "name": info.get("name", sym), "tier": tier})
    return stocks


def fetch_technicals(symbols, days=120):
    """批量获取技术面数据（价格+MA+RSI+MACD）"""
    hist = {}
    for sym in symbols:
        df = get_stock_daily(sym, days=days)
        if df is not None and not df.empty:
            close_col = "close" if "close" in df.columns else (df.columns[4] if len(df.columns) > 4 else None)
            if close_col:
                df = df.copy()
                if "date" not in df.columns:
                    if "datetime" in df.columns: df["date"] = df["datetime"]
                    else: df["date"] = df.index.astype(str)
                df["close"] = pd.to_numeric(df[close_col], errors="coerce")
                df = df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
                hist[sym] = df
    return hist


def compute_technicals(sym, price, hist):
    """计算单个标的技术指标"""
    if sym not in hist:
        return {"ma20_dev": 0, "ma60_dev": 0, "rsi": 50, "macd_signal": "⚪", "total_tech_score": 5.0}

    df = hist[sym]
    close_arr = df[df["date"] <= str(date.today())]["close"].values.astype(float)
    if len(close_arr) == 0:
        close_arr = df["close"].values.astype(float)
    if len(close_arr) == 0:
        return {"ma20_dev": 0, "ma60_dev": 0, "rsi": 50, "macd_signal": "⚪", "total_tech_score": 5.0}

    te = {}
    if len(close_arr) >= 20:
        ma20 = np.mean(close_arr[-20:])
        te["ma20_dev"] = round((price - ma20) / ma20 * 100, 2)
    else: te["ma20_dev"] = 0
    if len(close_arr) >= 60:
        ma60 = np.mean(close_arr[-60:])
        te["ma60_dev"] = round((price - ma60) / ma60 * 100, 2)
    else: te["ma60_dev"] = 0

    # RSI 14
    if len(close_arr) >= 15:
        gains = sum(max(0, close_arr[-i]-close_arr[-i-1]) for i in range(1,15))
        losses = sum(max(0, close_arr[-i-1]-close_arr[-i]) for i in range(1,15))
        ag = gains/14; al = losses/14
        te["rsi"] = round(100 - 100/(1+ag/al) if al > 0 else (100 if ag > 0 else 50), 1)
    else: te["rsi"] = 50

    # MACD
    if len(close_arr) >= 26:
        s = pd.Series(close_arr)
        e12 = s.ewm(span=12).mean().iloc[-1]; e26 = s.ewm(span=26).mean().iloc[-1]
        macd = e12 - e26
        sig = s.ewm(span=9).mean().iloc[-1]
        pe12 = pd.Series(close_arr[:-1]).ewm(span=12).mean().iloc[-1] if len(close_arr)>26 else e12
        pe26 = pd.Series(close_arr[:-1]).ewm(span=26).mean().iloc[-1] if len(close_arr)>26 else e26
        pmacd = pe12 - pe26
        te["macd_signal"] = "🟢金叉" if macd > sig and pmacd <= pe12-pe26 else ("🔴死叉" if macd < sig else "⚪")
        te["total_tech_score"] = 5.0 + (1.0 if 30 < te["rsi"] < 70 else 0) + (1.5 if te["macd_signal"]=="🟢金叉" else 0)
    else:
        te["macd_signal"] = "⚪"; te["total_tech_score"] = 5.0

    return te


def run():
    """主流程"""
    print("=" * 50, flush=True)
    print(f"📊 每日三策略执行器", flush=True)
    print(f"   日期: {date.today()}", flush=True)
    print("=" * 50, flush=True)

    # 1. 获取观察池
    print("\n📋 Step 1: 获取核心观察池...", flush=True)
    stocks = get_core_watchlist()
    print(f"   {len(stocks)}只标的", flush=True)

    # 2. 扫描评分
    print("\n🔍 Step 2: 运行扫描器...", flush=True)
    scanner = FactorScanner(macro_engine=None)
    scanner.weights = FACTOR_WEIGHTS.get("default")

    score_results = []
    for s in stocks:
        sym = s["symbol"]
        r = scanner.score_stock(sym)
        if not r.get("error") and r.get("score", 0) > 0:
            score_results.append(r)
            print(f"   {sym} {s['name']}: 评分{r['score']:.1f}", flush=True)

    if not score_results:
        print("❌ 无有效评分结果", flush=True)
        return

    print(f"\n   ✅ 成功评分: {len(score_results)}只", flush=True)

    # 3. 获取技术面数据
    print("\n📈 Step 3: 获取技术面数据...", flush=True)
    symbols = [r["symbol"] for r in score_results]
    hist = fetch_technicals(symbols, days=120)
    print(f"   {len(hist)}只有历史数据", flush=True)

    # 4. 构建当日输入
    score_map = {}
    tech_map = {}
    price_map = {}
    for r in score_results:
        sym = r["symbol"]
        score = r.get("score", 0)
        price = r.get("price", 0)
        if score <= 0 or price <= 0:
            continue
        score_map[sym] = score
        price_map[sym] = price
        tech_map[sym] = compute_technicals(sym, price, hist)

    print(f"\n📊 Step 4: 调用TradingEngine...", flush=True)
    engine = TradingEngine()
    today_str = date.today().strftime("%Y-%m-%d")
    result = engine.run_daily(today_str, score_map, tech_map, price_map)

    # 5. 输出摘要
    print(f"\n{'='*50}", flush=True)
    print(f"📊 信号摘要 ({today_str})", flush=True)
    print(engine.get_summary_table(result), flush=True)
    print(f"{'='*50}", flush=True)

    # 也保持一份到scanner结果备份（供日报引用）
    scan_out = os.path.join(_PROJECT_DIR, "data", "scan_snapshot_latest.json")
    scan_data = {
        "date": today_str,
        "count": len(score_results),
        "results": score_results,
        "signals": result
    }
    with open(scan_out, "w") as f:
        json.dump(scan_data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 扫描+信号已保存: {scan_out}", flush=True)

    return result


if __name__ == "__main__":
    run()
