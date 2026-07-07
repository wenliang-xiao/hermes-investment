"""
每日三策略执行器 — v2 (双引擎合并版)
整合 FactorEngine + strategies/(纯函数) → 输出 trading_signals.json
"""
import sys, os, json
from datetime import datetime, date
import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)

from data.data_layer import get_stock_daily
from analysis.factor_engine import FactorEngine
from analysis.factor_engine import score_to_signal, convert_v4_to_v3
from analysis.trading_engine import TradingEngine
from config import FACTOR_WEIGHTS
from domain import WATCHLIST
from utils.atomic_io import atomic_write_json
import functools
print = functools.partial(print, flush=True)

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
        te["macd_signal"] = "🟢金叉" if macd > sig and pmacd <= sig else ("🔴死叉" if macd < sig else "⚪")
        te["total_tech_score"] = 5.0 + (1.0 if 30 < te["rsi"] < 70 else 0) + (1.5 if te["macd_signal"]=="🟢金叉" else 0)
    else:
        te["macd_signal"] = "⚪"; te["total_tech_score"] = 5.0

    return te


def run():
    """主流程 — 使用FactorEngine评分 + TradingEngine执行"""
    print("=" * 50, flush=True)
    print("📊 每日三策略执行器 v2", flush=True)
    print(f"   日期: {date.today()}", flush=True)
    print("=" * 50, flush=True)

    # 1. 获取观察池
    print("\n📋 Step 1: 获取核心观察池...", flush=True)
    stocks = get_core_watchlist()
    print(f"   {len(stocks)}只标的", flush=True)

    # 2. FactorEngine 批量评分
    print("\n🔍 Step 2: FactorEngine 批量评分...", flush=True)
    symbols = [s["symbol"] for s in stocks]
    engine = FactorEngine()
    batch_results = engine.score_batch(symbols)
    print(f"   ✅ {len(batch_results)}只评分完成", flush=True)

    # 3. 转换评分 → v3兼容格式 (供TradingEngine使用)
    score_results = []

    # 预加载已有持仓的最后价格作为降级用
    st_path = os.path.join(_PROJECT_DIR, "data", "strategy_states.json")
    fallback_prices = {}
    try:
        import json as _json
        with open(st_path) as _f:
            _states = _json.load(_f)
        for _sname, _sdata in _states.items():
            for _sym, _pos in _sdata.get("positions", {}).items():
                _cp = _pos.get("current_price", 0) or _pos.get("entry_price", 0)
                if _cp > 0:
                    fallback_prices[_sym] = _cp
    except Exception:
        pass

    for br in batch_results:
        sym = br["symbol"]
        name = next((s["name"] for s in stocks if s["symbol"] == sym), sym)
        v3_score = convert_v4_to_v3(br["composite"])
        price = 0
        # 尝试从数据层获取价格
        try:
            from data.data_router import get_rt
            rt = get_rt(sym)
            if rt and rt.get("price"):
                price = float(rt["price"])
        except Exception:
            pass
        # 降级: 用上次已知价格
        if not price or price <= 0:
            price = fallback_prices.get(sym, 0)

        score_results.append({
            "symbol": sym,
            "name": name,
            "score": round(v3_score, 2),              # v3兼容 [1,10]
            "composite_v4": br["composite"],           # v4原始 [0,1]
            "scores": br["scores"],                     # 7维风格分
            "factor_breakdown": br["factor_breakdown"], # 子因子明细
            "price": price,
            "signal": score_to_signal(br["composite"]),
        })
        print(f"   {sym} {name}: v4={br['composite']:.4f} → v3={v3_score:.1f}", flush=True)

    if not score_results:
        print("❌ 无有效评分结果", flush=True)
        return

    # 4. 获取技术面数据
    print("\n📈 Step 4: 获取技术面数据...", flush=True)
    hist = fetch_technicals(symbols, days=120)
    print(f"   {len(hist)}只有历史数据", flush=True)

    # 5. 构建当日输入（v3兼容评分）
    score_map = {}
    tech_map = {}
    price_map = {}
    for r in score_results:
        sym = r["symbol"]
        score = r.get("score", 0)
        price = r.get("price", 0)
        if score <= 0:
            continue
        # 关键防护: price <= 0 的标的不进入策略决策
        # （避免策略基于无效价格生成伪信号，如 price=0 触发 -100% 硬止损）
        if not price or price <= 0:
            print(f"  ⚠️ 跳过 {sym}: price={price} 无效, 不进入策略决策", flush=True)
            continue
        score_map[sym] = score
        price_map[sym] = price
        tech_map[sym] = compute_technicals(sym, price, hist)

    # 6. TradingEngine 执行（使用v3兼容评分）
    print(f"\n📊 Step 6: TradingEngine (strategies/纯函数)...", flush=True)
    engine_te = TradingEngine()
    today_str = date.today().strftime("%Y-%m-%d")
    result = engine_te.run_daily(today_str, score_map, tech_map, price_map)

    # 7. 输出
    print(f"\n{'='*50}", flush=True)
    print(f"📊 信号摘要 ({today_str})", flush=True)
    print(f"   总信号: {result.get('total_raw_signals', 0)}", flush=True)
    print(f"   最终建议: {result.get('after_weekly_filter', 0)}", flush=True)
    print(f"   模拟盘交易: {result.get('simulated_trades', 0)}笔", flush=True)
    for s in result.get("signals", []):
        print(f"   [{s['priority']}] {s['strategy']} {s['action']} {s['symbol']} @{s['price']:.2f} - {s['reason']}", flush=True)
    print(f"{'='*50}", flush=True)

    # 保存扫描快照（供日报引用）
    scan_out = os.path.join(_PROJECT_DIR, "data", "scan_snapshot_latest.json")
    scan_data = {
        "date": today_str,
        "engine": "factor_engine_v4",
        "count": len(score_results),
        "results": score_results,
        "signals": result
    }
    atomic_write_json(scan_out, scan_data)
    print(f"\n💾 扫描+信号已保存: {scan_out}", flush=True)

    return result


if __name__ == "__main__":
    run()

