"""
三方策略对比回测 v2 — 跳过因子扫描，用已有评分+历史价格
"""
import sys, os, json, math
from datetime import datetime, timedelta, date
import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)
os.chdir(_PROJECT_DIR)

from data.data_layer import get_stock_daily
from domain import WATCHLIST
import functools, signal
print = functools.partial(print, flush=True)

# ═══ 已扫描的19只评分 ═══
SCORED_STOCKS = [
    {"symbol": "300502", "name": "新易盛",   "score": 5.5},
    {"symbol": "300308", "name": "中际旭创", "score": 4.6},
    {"symbol": "688256", "name": "寒武纪",   "score": 5.1},
    {"symbol": "688008", "name": "澜起科技", "score": 5.2},
    {"symbol": "688012", "name": "中微公司", "score": 4.1},
    {"symbol": "688041", "name": "海光信息", "score": 5.0},
    {"symbol": "688120", "name": "华海清科", "score": 4.2},
    {"symbol": "002371", "name": "北方华创", "score": 4.5},
    {"symbol": "603501", "name": "韦尔股份", "score": 4.0},
    {"symbol": "688017", "name": "绿的谐波", "score": 3.5},
    {"symbol": "300124", "name": "汇川技术", "score": 4.7},
    {"symbol": "002747", "name": "埃斯顿",   "score": 4.4},
    {"symbol": "002472", "name": "双环传动", "score": 4.2},
    {"symbol": "300750", "name": "宁德时代", "score": 4.9},
    {"symbol": "601012", "name": "隆基绿能", "score": 4.8},
    {"symbol": "600760", "name": "中航沈飞", "score": 4.8},
    {"symbol": "002179", "name": "中航光电", "score": 4.0},
    {"symbol": "603259", "name": "药明康德", "score": 6.2},
    {"symbol": "300760", "name": "迈瑞医疗", "score": 5.0},
]
SCORE_MAP = {s["symbol"]: s for s in SCORED_STOCKS}

print(f"📋 使用 {len(SCORED_STOCKS)} 只已评分标的")
for s in sorted(SCORED_STOCKS, key=lambda x: x["score"], reverse=True):
    print(f"  {s['symbol']} {s['name']}: 评分{s['score']:.1f}")

# ═══ 策略定义 ═══
class BaseStrategy:
    def __init__(self, name, capital=1000000):
        self.name = name
        self.capital = capital
        self.cash = capital
        self.positions = {}
        self.history = []
        self.daily_values = []
    def reset(self, capital=1000000):
        self.cash = capital; self.positions = {}; self.history = []; self.daily_values = []
    def current_value(self, pm):
        return self.cash + sum(p["quantity"] * pm.get(s, p.get("current_price", p["entry_price"])) for s, p in self.positions.items())
    def record_value(self, d, pm):
        self.daily_values.append({"date": d, "value": round(self.current_value(pm), 2)})
    def get_summary(self, pm):
        rp = sum(h.get("pnl",0) for h in self.history if h.get("action")=="卖出")
        up = sum((pm.get(s, p.get("current_price", p["entry_price"])) - p["entry_price"]) * p["quantity"] for s, p in self.positions.items())
        v = self.current_value(pm)
        ret = (v - self.capital) / self.capital * 100
        buys = [h for h in self.history if h.get("action")=="买入"]
        sells = [h for h in self.history if h.get("action")=="卖出"]
        wins = [h for h in sells if h.get("pnl",0) > 0]
        peak = self.capital; mdd = 0
        for e in self.daily_values:
            peak = max(peak, e["value"])
            mdd = min(mdd, (e["value"] - peak) / peak * 100)
        rs = []; pv = self.capital
        for dv in self.daily_values:
            if pv > 0: rs.append((dv["value"] - pv) / pv)
            pv = dv["value"]
        sharpe = np.mean(rs) / (np.std(rs) + 1e-10) * np.sqrt(252) if rs else 0
        return {
            "name": self.name, "value": round(v,2), "cash": round(self.cash,2),
            "positions_count": len(self.positions),
            "total_return_pct": round(ret,2), "total_return_cny": round(rp+up,2),
            "realized_pnl": round(rp,2), "unrealized_pnl": round(up,2),
            "total_trades_closed": len(sells), "total_trades_opened": len(buys),
            "wins": len(wins), "losses": len(sells)-len(wins),
            "win_rate": round(len(wins)/len(sells)*100,1) if sells else 0,
            "max_drawdown_pct": round(abs(mdd),2), "sharpe_ratio": round(sharpe,2),
            "daily_values": self.daily_values, "trades": self.history
        }

class FacejiStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("faceji (面基)")
        self.entry_threshold, self.exit_threshold, self.max_positions = 5.0, 4.0, 8
    def daily_step(self, d, sm, tm, pm):
        held = set(self.positions.keys())
        cands = sorted([s for s in sm if s not in held], key=lambda s: sm.get(s,0), reverse=True)[:5]
        for sym in cands:
            if len(self.positions) >= self.max_positions: break
            sc = sm.get(sym, 0)
            if sc < self.entry_threshold: continue
            te = tm.get(sym, {})
            if (te.get("ma60_dev",0) or 0) <= (te.get("ma20_dev",0) or 0) and sc < 5.5: continue
            price = pm.get(sym, 0)
            if price <= 0: continue
            qty = max(100, int(30000/price/100)*100)
            cost = price * qty
            if cost > self.cash: qty = max(100, int(self.cash/price/100)*100); cost = price*qty
            if cost > self.cash: continue
            self.cash -= cost
            self.positions[sym] = {"entry_price": price, "quantity": qty, "entry_date": d, "peak": price, "current_price": price}
            self.history.append({"date": d, "symbol": sym, "action": "买入", "price": price, "quantity": qty, "cost": round(cost,2), "reason": f"评分{sc:.1f}"})
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = pm.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price; pos["peak"] = max(pos["peak"], price)
            sc = sm.get(sym, 0)
            if sc < self.exit_threshold:
                pnl = (price - pos["entry_price"]) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": d, "symbol": sym, "action": "卖出", "price": price, "pnl": round(pnl,2), "reason": f"评分{sc:.1f}<{self.exit_threshold}"})
                del self.positions[sym]; continue
            if sc < 5.0:
                te = tm.get(sym, {})
                if (te.get("ma20_dev",0) or 0) < (te.get("ma60_dev",0) or 0):
                    pnl = (price - pos["entry_price"]) * pos["quantity"]
                    self.cash += price * pos["quantity"]
                    self.history.append({"date": d, "symbol": sym, "action": "卖出", "price": price, "pnl": round(pnl,2), "reason": "MA死叉"})
                    del self.positions[sym]
        self.record_value(d, pm)

class SilverQuantStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("silverquant (组件化)")
        self.entry_threshold, self.max_positions = 5.0, 8
    def daily_step(self, d, sm, tm, pm):
        held = set(self.positions.keys())
        cands = sorted([s for s in sm if s not in held], key=lambda s: sm.get(s,0), reverse=True)[:5]
        for sym in cands:
            if len(self.positions) >= self.max_positions: break
            if sm.get(sym,0) < self.entry_threshold: continue
            price = pm.get(sym, 0)
            if price <= 0: continue
            qty = max(100, int(30000/price/100)*100)
            cost = price * qty
            if cost > self.cash: qty = max(100, int(self.cash/price/100)*100); cost = price*qty
            if cost > self.cash: continue
            self.cash -= cost
            self.positions[sym] = {"entry_price": price, "quantity": qty, "entry_date": d, "peak": price, "current_price": price}
            self.history.append({"date": d, "symbol": sym, "action": "买入", "price": price, "quantity": qty, "cost": round(cost,2), "reason": f"评分{sm[sym]:.1f}"})
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = pm.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price; pos["peak"] = max(pos["peak"], price)
            entry = pos["entry_price"]; peak = pos["peak"]
            pnl_pct = (price-entry)/entry*100; dd = (price-peak)/peak*100 if peak else 0
            if pnl_pct <= -8:
                pnl = (price-entry)*pos["quantity"]; self.cash += price*pos["quantity"]
                self.history.append({"date":d,"symbol":sym,"action":"卖出","price":price,"pnl":round(pnl,2),"reason":"HardSeller(-8%)"})
                del self.positions[sym]; continue
            if dd <= -12:
                pnl = (price-entry)*pos["quantity"]; self.cash += price*pos["quantity"]
                self.history.append({"date":d,"symbol":sym,"action":"卖出","price":price,"pnl":round(pnl,2),"reason":f"FallSeller({dd:.1f}%)"})
                del self.positions[sym]; continue
            te = tm.get(sym,{})
            if (te.get("ma20_dev",0) or 0) < (te.get("ma60_dev",0) or 0) and pnl_pct > -5:
                pnl = (price-entry)*pos["quantity"]; self.cash += price*pos["quantity"]
                self.history.append({"date":d,"symbol":sym,"action":"卖出","price":price,"pnl":round(pnl,2),"reason":"MASeller"})
                del self.positions[sym]; continue
            if sm.get(sym,10) < 4.5:
                pnl = (price-entry)*pos["quantity"]; self.cash += price*pos["quantity"]
                self.history.append({"date":d,"symbol":sym,"action":"卖出","price":price,"pnl":round(pnl,2),"reason":f"ScoreDrop({sm[sym]:.1f})"})
                del self.positions[sym]
        self.record_value(d, pm)

class TradingAgentsStrategy(BaseStrategy):
    def __init__(self):
        super().__init__("tradingagents (辩论制)")
        self.max_positions = 6
    def _debate(self, score, tech):
        sc = score or 5.0; ts = tech.get("total_tech_score",5.0) if tech else 5.0
        bull = sc*0.5 + ts*0.5; bp = 0
        if tech and tech.get("macd_signal","")=="🔴死叉": bp += 1.0
        if tech and (tech.get("rsi",50) or 50) > 70: bp += 0.5
        bear = sc - bp; neut = sc
        if bull >= bear and bull >= neut: final = bull*0.6 + neut*0.3 + bear*0.1
        elif bear >= bull and bear >= neut: final = bear*0.5 + neut*0.3 + bull*0.2
        else: final = neut
        return min(10, max(0, final))
    def daily_step(self, d, sm, tm, pm):
        held = set(self.positions.keys())
        debate = {sym: {"score": sm.get(sym,5.0), "debate_score": self._debate(sm.get(sym,5.0), tm.get(sym,{}))} for sym in sm}
        cands = sorted([(s,db["debate_score"]) for s,db in debate.items() if s not in held], key=lambda x:x[1], reverse=True)[:3]
        for sym, ds in cands:
            if len(self.positions) >= self.max_positions: break
            if ds < 5.5: continue
            price = pm.get(sym,0)
            if price <= 0: continue
            wp = min(ds/10.0, 0.8); kelly = max(0, (wp*1.8 - (1-wp))/1.8)*0.5
            pc = int(self.cash * min(kelly, 0.12)); qty = max(100, int(pc/price/100)*100); cost = price*qty
            if cost > self.cash: continue
            self.cash -= cost
            self.positions[sym] = {"entry_price": price, "quantity": qty, "entry_date": d, "peak": price, "current_price": price, "debate_score": ds}
            self.history.append({"date": d, "symbol": sym, "action": "买入", "price": price, "quantity": qty, "cost": round(cost,2), "reason": f"辩论分{ds:.1f}"})
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = pm.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price; pos["peak"] = max(pos["peak"], price)
            ds = debate.get(sym,{}).get("debate_score",5.0)
            entry = pos["entry_price"]; pnl_pct = (price-entry)/entry*100
            if ds < 4.0: reason = f"辩论分{ds:.1f}<4"
            elif pnl_pct <= -8: reason = f"止损{pnl_pct:.1f}%"
            elif ds < 5.0 and pnl_pct < 0: reason = f"辩论分{ds:.1f}+亏损"
            else: continue
            pnl = (price-entry)*pos["quantity"]; self.cash += price*pos["quantity"]
            self.history.append({"date": d, "symbol": sym, "action": "卖出", "price": price, "pnl": round(pnl,2), "reason": reason})
            del self.positions[sym]
        self.record_value(d, pm)

# ═══ 数据获取 ═══
def fetch_prices(symbols, days=120):
    signal.alarm(25)
    df = get_stock_daily(symbols[0], days=days) if symbols else None
    signal.alarm(0)
    
    hist = {}
    total = len(symbols)
    for i, sym in enumerate(symbols):
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
                name = SCORE_MAP.get(sym, {}).get("name", sym)
                print(f"  {sym} {name}: {len(df)}条 {df['date'].iloc[0]}→{df['date'].iloc[-1]}", flush=True)
            else: print(f"  {sym}: no close col", flush=True)
        else: print(f"  {sym}: no data", flush=True)
        if i % 5 == 0: print(f"  [{i+1}/{total}]", flush=True)
    return hist

def build_daily_snapshots(hist, lookback=60):
    all_dates = sorted(set().union(*[set(df["date"].tolist()) for df in hist.values()]))
    if not all_dates: return None
    dates = all_dates[-lookback:]
    print(f"\n📅 回测窗口: {dates[0]} → {dates[-1]} ({len(dates)}天)")
    
    daily = []
    for dt in dates:
        sm, tm, pm = {}, {}, {}
        for sym, df in hist.items():
            row = df[df["date"] <= dt]
            if row.empty: continue
            row = row.iloc[-1]
            price = float(row["close"])
            pm[sym] = price
            sm[sym] = SCORE_MAP.get(sym, {}).get("score", 5.0)
            
            close_arr = df[df["date"] <= dt]["close"].values.astype(float)
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
                macd = e12-e26
                sig = s.ewm(span=9).mean().iloc[-1]
                pe12 = pd.Series(close_arr[:-1]).ewm(span=12).mean().iloc[-1] if len(close_arr)>26 else e12
                pe26 = pd.Series(close_arr[:-1]).ewm(span=26).mean().iloc[-1] if len(close_arr)>26 else e26
                pmacd = pe12 - pe26
                psig = pd.Series(close_arr[:-1]).ewm(span=9).mean().iloc[-1] if len(close_arr) > 26 else sig
                te["macd_signal"] = "🟢金叉" if macd > sig and pmacd <= psig else ("🔴死叉" if macd < sig and pmacd >= psig else "⚪")
                te["total_tech_score"] = 5.0 + (1.0 if 30 < te["rsi"] < 70 else 0) + (1.5 if te["macd_signal"]=="🟢金叉" else 0)
            else:
                te["macd_signal"] = "⚪"; te["total_tech_score"] = 5.0
            tm[sym] = te
        daily.append({"date": dt, "score_map": sm, "tech_map": tm, "price_map": pm})
    return daily

# ═══ 主流程 ═══
def main():
    # 1. Fetch prices
    print("\n📈 Step 1: 获取历史价格...")
    symbols = [s["symbol"] for s in SCORED_STOCKS]
    hist = fetch_prices(symbols, days=120)
    
    # 2. Build snapshots
    print("\n🔄 Step 2: 构建逐日数据...")
    snapshots = build_daily_snapshots(hist, lookback=60)
    if not snapshots: print("❌ 无数据"); return
    
    # 3. Run backtest
    print("\n🏃 Step 3: 运行三方回测...")
    strategies = {"faceji": FacejiStrategy(), "silverquant": SilverQuantStrategy(), "tradingagents": TradingAgentsStrategy()}
    for day in snapshots:
        s = day["score_map"]; t = day["tech_map"]; p = day["price_map"]
        for st in strategies.values(): st.daily_step(day["date"], s, t, p)
    
    # 4. Summarize
    print("\n📊 Step 4: 汇总结果...")
    last_pm = snapshots[-1]["price_map"]
    results = {}
    for name, st in strategies.items():
        r = st.get_summary(last_pm)
        results[name] = r
        print(f"\n  {r['name']}:")
        print(f"    最终价值: ¥{r['value']:,.2f}")
        print(f"    收益率: {r['total_return_pct']:+.2f}%")
        print(f"    总盈亏: ¥{r['total_return_cny']:+,.2f}")
        print(f"    交易(开/平): {r['total_trades_opened']}/{r['total_trades_closed']}")
        print(f"    胜率: {r['win_rate']}%")
        print(f"    最大回撤: {r['max_drawdown_pct']}%")
        print(f"    Sharpe: {r['sharpe_ratio']}")
        print(f"    持仓: {r['positions_count']}只")
        if r['trades']:
            print(f"    最近交易:")
            for t in r['trades'][-5:]:
                print(f"      {t['date']} {t['symbol']} {t['action']} @{t['price']:.2f} 盈亏:{t.get('pnl',0):+.2f} 原因:{t.get('reason','')}")
    
    # 5. Save
    output = {
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days_analyzed": len(snapshots),
        "date_range": f"{snapshots[0]['date']} → {snapshots[-1]['date']}",
        "scored_stocks": len(SCORED_STOCKS),
        "results": results
    }
    out_path = os.path.join(_PROJECT_DIR, "data", "backtest_comparison.json")
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n✅ 结果已保存: {out_path}")
    print(f"\n🏆 最优: {max(results.items(), key=lambda x: x[1]['total_return_pct'])[1]['name']} ({max(results.values(), key=lambda x: x['total_return_pct'])['total_return_pct']:+.2f}%)")

if __name__ == "__main__":
    main()
