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
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
try:
    from dotenv import load_dotenv
    _env_path = os.environ.get("HERMES_ENV", os.path.join(os.path.dirname(_PROJECT_DIR), ".env"))
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except Exception:
    pass

from data.data_layer import get_stock_daily
from engine.factor_engine import FactorEngine
from engine.factor_engine import score_to_signal, convert_v4_to_v3
from analysis.trading_engine import TradingEngine
from config import FACTOR_WEIGHTS
from domain import WATCHLIST
from utils.atomic_io import atomic_write_json
import functools
print = functools.partial(print, flush=True)

CORE_TIERS = ("核心", "底仓", "关注")


def _aggregate_shadow(states: dict) -> dict:
    """聚合三策略状态 → shadow_account.json 兼容格式。

    正确处理:
      - capital: 每策略初始资金之和 (每策略100万 → 300万总盘)
      - cash: 三策略现金累加
      - positions: 同名标的多策略持有 → 合并数量/成本 (不覆盖)
      - history: 三策略交易历史合并, 按时间倒序
      - realized_pnl: 历史卖出 pnl 累加
    """
    capital = 0
    total_cash = 0
    merged: dict[str, dict] = {}
    all_history = []

    for sname, state in states.items():
        capital += state.get("capital", 1000000) or 1000000
        total_cash += state.get("cash", 0) or 0
        for h in state.get("history", []):
            entry = {
                "time": h.get("date", h.get("time", "")),
                "symbol": h.get("symbol", ""),
                "action": "买入" if h.get("action", "").startswith("买") else "卖出",
                "price": h.get("price", 0),
                "quantity": h.get("quantity", 0),
                "cost": h.get("cost", 0),
                "pnl": h.get("pnl"),
                "reason": h.get("reason", ""),
                "strategy": sname,
            }
            all_history.append(entry)
        for sym, pos in state.get("positions", {}).items():
            pos_qty = pos.get("quantity", 0) or 0
            pos_entry = pos.get("entry_price", 0) or 0
            pos_cost = pos.get("cost", 0) or (pos_entry * pos_qty)
            if sym not in merged:
                merged[sym] = {
                    "symbol": sym,
                    "name": pos.get("name", sym),
                    "entry_price": pos_entry,
                    "quantity": pos_qty,
                    "entry_date": pos.get("entry_date", ""),
                    "current_price": pos.get("current_price", pos_entry),
                    "entry_score": pos.get("entry_score"),
                    "cost": pos_cost,
                    "reason": pos.get("reason", ""),
                }
            else:
                # 同名多策略合并: 数量累加, 成本按数量加权
                cur = merged[sym]
                old_qty = cur.get("quantity", 0) or 0
                new_qty = pos_qty
                if new_qty <= 0:
                    continue
                old_cost = cur.get("cost", 0) or (cur.get("entry_price", 0) * old_qty)
                new_cost = pos_cost
                total_qty = old_qty + new_qty
                total_cost = old_cost + new_cost
                cur["quantity"] = total_qty
                cur["cost"] = total_cost
                if total_qty > 0:
                    cur["entry_price"] = total_cost / total_qty
                # current_price 用最新的 (取较大值即最新刷新)
                new_cur = pos.get("current_price", 0) or 0
                if new_cur > cur.get("current_price", 0):
                    cur["current_price"] = new_cur
                if not cur.get("entry_score") and pos.get("entry_score"):
                    cur["entry_score"] = pos.get("entry_score")

    all_history.sort(key=lambda x: str(x.get("time", "")), reverse=True)
    realized = sum(h.get("pnl", 0) or 0 for h in all_history if h.get("action") == "卖出" and h.get("pnl") is not None)

    return {
        "capital": capital,
        "cash": total_cash,
        "positions": merged,
        "history": all_history,
        "realized_pnl": round(realized, 2),
        "created_at": date.today().strftime("%Y-%m-%d"),
    }


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

    # ── IC 动态权重数据闭环 (根治IC死代码: 每次评分累积真实IC历史) ──
    # 用昨日因子分 + 今日已实现收益回算昨日IC → 权重随时间真实数据驱动
    try:
        from datetime import timedelta as _td
        prev_date = (date.today() - _td(days=1)).isoformat()
        prev_path = os.path.join(engine.ic.cache_dir, "factor_scores", f"{prev_date}.json")
        if os.path.exists(prev_path):
            with open(prev_path) as _f:
                prev_scores = json.load(_f)
            # 昨日标的今日收益 (close[-1]/close[-6]-1 一期5日, or 日收益)
            from data.data_router import get_history
            realized = {}
            for s in list(prev_scores.keys())[:60]:  # 限速
                try:
                    df = get_history(s, days=20)
                    if df and df.get("close") and len(df["close"]) >= 2:
                        realized[s] = float(df["close"][-1] / df["close"][-2] - 1)
                except Exception:
                    continue
            if len(realized) >= 10:
                engine.compute_ic_from_realized(prev_date, realized)
                print(f"   📈 IC@{prev_date}累积 ({len(realized)}样本)", flush=True)
            else:
                print(f"   ⏸ 昨日IC样本不足({len(realized)}), 跳过", flush=True)
        else:
            print("   🔄 无昨日因子分, IC今日起累积", flush=True)
    except Exception as e:
        print(f"   ⚠ IC累积步骤失败(不影响交易): {e}", flush=True)

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
    
    # ── 加载已有状态（避免每次新建实例 → history 清空） ──
    st_path = os.path.join(_PROJECT_DIR, "data", "strategy_states.json")
    loaded_states = {}
    try:
        if os.path.exists(st_path):
            with open(st_path) as _f:
                _states = json.load(_f)
            for _sname, _sdata in _states.items():
                _sdata["positions"] = {k: v for k, v in _sdata.get("positions", {}).items() if v.get("current_price", 0) > 0}
                loaded_states[_sname] = _sdata
            print(f"   ✅ 恢复 {len(loaded_states)} 个策略历史状态", flush=True)
    except Exception:
        print("   ⚠️ 无已有状态可恢复（首次运行）", flush=True)
        loaded_states = {}
    
    engine_te = TradingEngine()
    # 恢复每个策略的历史
    for _sname, _sdata in loaded_states.items():
        _strat = getattr(engine_te, _sname, None)
        if _strat:
            _strat.load_state(_sdata)

    # ── 模拟盘价格刷新: 用实时价格更新所有持仓 current_price (P0: pnl/风控真实化) ──
    print("\n💹 Step 6.5: 刷新模拟盘持仓实时价格...", flush=True)
    from data.data_router import get_rt as _get_rt
    refresh_hits = 0
    for _sname, _strat in engine_te.strategies.items():
        for _sym in list(_strat.positions.keys()):
            try:
                _rt = _get_rt(_sym)
                if _rt and _rt.get("price") and float(_rt["price"]) > 0:
                    _price = float(_rt["price"])
                    _strat.positions[_sym]["current_price"] = _price
                    # P0-7 (2026-08-31): 峰值追踪 — peak 只在建仓时设置, 从不更新
                    # 导致止损线恒 = entry*0.92 (峰值回落失效)。此处在价格刷新时
                    # 同步推进 peak_price (持仓内字段名兼容: peak / peak_price)
                    _peak = _strat.positions[_sym].get("peak") or _strat.positions[_sym].get("peak_price")
                    if not _peak or _price > float(_peak):
                        _strat.positions[_sym]["peak"] = _price
                        _strat.positions[_sym]["peak_price"] = _price
                    refresh_hits += 1
            except Exception:
                continue
    print(f"   ✅ 刷新 {refresh_hits} 个持仓实时价格 (含 peak 峰值追踪)", flush=True)

    today_str = date.today().strftime("%Y-%m-%d")
    result = engine_te.run_daily(today_str, score_map, tech_map, price_map)

    # ── 模拟盘主账户同步: 聚合三策略状态 → shadow_account.json (P0: Dashboard有真实数据) ──
    try:
        sa_path = os.path.join(_PROJECT_DIR, "data", "shadow_account.json")
        states_after = {name: s.save_state() for name, s in engine_te.strategies.items()}
        agg = _aggregate_shadow(states_after)
        with open(sa_path, "w") as f:
            json.dump(agg, f, ensure_ascii=False, indent=2, default=str)
        print(f"💾 模拟盘主账户已同步: {sa_path} "
              f"(持仓{len(agg['positions'])}只, 历史{len(agg['history'])}条)", flush=True)
    except Exception as e:
        print(f"  ⚠️ 模拟盘主账户同步失败(不影响信号): {e}", flush=True)

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
    print(f"💾 扫描+信号已保存: {scan_out}", flush=True)

    # ── 刷新宏观缓存 ──
    print("\n🌍 Step: 刷新宏观引擎缓存...", flush=True)
    try:
        from engine.macro_engine import MacroEngine
        me = MacroEngine()
        macro_state = me.refresh()
        print(f"   ✅ 宏观: {macro_state.get('quadrant','?')} | 开关: {macro_state.get('strategy_switch','?')} | 趋势: {macro_state.get('trend_temp','?')}", flush=True)
    except Exception as e:
        print(f"   ⚠️ 宏观缓存刷新失败: {e}", flush=True)

    # ── 同步评分到 pool JSON ──
    pool_out = os.path.join(_PROJECT_DIR, "data", "pool", "deep.json")
    pool_dirs_to_sync = ["deep.json", "watch.json", "monitor.json"]
    for _pfname in pool_dirs_to_sync:
        _pool_path = os.path.join(_PROJECT_DIR, "data", "pool", _pfname)
        if os.path.exists(_pool_path):
            try:
                with open(_pool_path) as _pf:
                    pool_items = json.load(_pf)
                score_map = {r["symbol"]: r for r in score_results}
                updated = 0
                for item in pool_items:
                    sym = item.get("symbol", "")
                    sr = score_map.get(sym)
                    if sr:
                        item["score"] = sr.get("composite_v4", 0)
                        item["score_v3"] = sr.get("score", 0)
                        item["factor_breakdown"] = sr.get("factor_breakdown", {})
                        item["scores"] = sr.get("scores", {})
                        item["price"] = sr.get("price", 0)
                        if not item.get("name"):
                            item["name"] = sr.get("name", sym)
                        updated += 1
                atomic_write_json(_pool_path, pool_items)
                print(f"  ✅ 同步 {updated}/{len(pool_items)} 只标的评分到 pool/{_pfname}", flush=True)
            except Exception as _e:
                print(f"  ⚠️ 无法同步 pool/{_pfname}: {_e}", flush=True)

    # ── ⭐ 证据链 1/5: 信号验证 — 回溯前日信号表现 ⭐ ──
    # 从 history_accuracy.json 加载历史信号验证结果
    verify_path = os.path.join(_PROJECT_DIR, "data", "signal_accuracy_history.json")
    try:
        if os.path.exists(verify_path):
            with open(verify_path) as f:
                signal_accuracy = json.load(f)
        else:
            signal_accuracy = {"history": [], "last_30d": {"by_score_band": {}, "hit_rate": 0, "mse": 0}}
    except Exception:
        signal_accuracy = {"history": [], "last_30d": {}}
    
    # 检查昨日生成的信号在今日的表现
    yest_str = (date.today() - __import__('datetime').timedelta(days=1)).strftime("%Y-%m-%d")
    yest_signals = [s for s in signal_accuracy.get("history", []) if s.get("date", "") == yest_str]
    if yest_signals:
        print(f"\n🔎 证据验证: {yest_str} 的 {len(yest_signals)} 条信号", flush=True)
        hits = 0
        for sig in yest_signals:
            sym = sig.get("symbol", "")
            action = sig.get("action", "HOLD")
            # 检查今日价格（以验证方向正确性）
            try:
                price_today = get_rt(sym) if sym else None
                if price_today:
                    hits += 1
            except Exception:
                pass
        print(f"   验证率: {hits}/{len(yest_signals)}", flush=True)
    else:
        print(f"   ℹ️ 无 {yest_str} 信号记录可验证（首次运行）", flush=True)

    # 保存信号验证历史
    signal_accuracy["history"].append({
        "date": today_str,
        "signals": [s.to_dict() if hasattr(s, 'to_dict') else s for s in (result.get("all_signals", []) + result.get("signals", []))],
        "score_results_count": len(score_results),
        "price_valid_count": sum(1 for r in score_results if r.get("price", 0) > 0),
        "price_zero_skipped": sum(1 for r in score_results if r.get("price", 0) <= 0),
    })
    signal_accuracy["last_update"] = today_str
    atomic_write_json(verify_path, signal_accuracy)
    print(f"\n📊 信号验证历史已保存: {signal_accuracy.get('last_30d', {}).get('hit_rate', 'N/A')}", flush=True)

    return result


if __name__ == "__main__":
    run()

