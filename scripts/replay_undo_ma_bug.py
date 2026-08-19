#!/usr/bin/env python3
"""
P0 回放脚本 — 撤销 silverquant 因 MA死叉判定反向(金叉被当死叉)导致的 3 笔误卖
================================================================================
误卖清单 (2026-08-18/19):
  - 300750 宁德时代 100股  (2026-08-18 MASeller, 实际金叉 MA20=392.16>MA60=390.17)
  - 600887 伊利股份 1100股 (2026-08-18 MASeller, 实际金叉 MA20=26.44>MA60=25.65)
  - 600900 长江电力 900股  (2026-08-19 MASeller, 实际金叉 MA20=28.46>MA60=27.36)

恢复逻辑:
  - strategy_states.json: silverquant 恢复3持仓(原买入价/数量/日期), cash -= 卖出成交款, 删除卖出history
  - trading_signals.json: trade_history 删除3笔卖出; positions 恢复; portfolios 重算
  - trade_log.json: 删除3条SELL; cooldowns 还原为买入日
  - shadow_account.json: 用恢复后的 strategy_states 重新聚合

不变量校验:
  - silverquant: cash + Σ(entry×qty) == capital(1,000,000)
  - total_value == cash + Σ(current×qty)
  - history 仅剩买入, positions=4
"""
import json, sys, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path("/home/admin/.hermes/investment_system")
DATA = ROOT / "data"

# 备份
for f in ["strategy_states.json", "trading_signals.json", "trade_log.json", "shadow_account.json"]:
    src = DATA / f
    bak = DATA / f"{f}.bak_pre_mafix"
    if src.exists() and not bak.exists():
        shutil.copy2(src, bak)
        print(f"  backup -> {bak.name}")

# ── 还原数据 (来自 strategy_states 买入记录) ──
RESTORE = {
    "300750": dict(entry_price=396.4476, quantity=100, entry_date="2026-08-13",
                   entry_score=6.93, reason="槽位建仓(评分6.9)", current_price=396.26),
    "600887": dict(entry_price=25.9081, quantity=1100, entry_date="2026-08-13",
                   entry_score=6.57, reason="槽位建仓(评分6.6)", current_price=25.15),
    "600900": dict(entry_price=28.1403, quantity=900, entry_date="2026-08-18",
                   entry_score=8.75, reason="槽位建仓(评分8.8)", current_price=28.12),
}

def load(p):
    with open(p) as f:
        return json.load(f)

def dump(p, obj):
    with open(p, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

# ═══════════ 1. strategy_states.json ═══════════
st = load(DATA / "strategy_states.json")
sq = st["silverquant"]

# 卖出成交款 (adj sell price × qty) — 从 history 卖出记录取
sell_proceeds = 0.0
kept = []
for h in sq["history"]:
    if h.get("action") == "卖出" and h.get("symbol") in RESTORE:
        sell_proceeds += h.get("price", 0) * h.get("quantity", 0)
        print(f"  remove sell history: {h['symbol']} {h.get('price')} x {h.get('quantity')} proceeds={h.get('price',0)*h.get('quantity',0):.2f}")
        continue
    kept.append(h)
sq["history"] = kept
sq["cash"] = round(sq.get("cash", 0) - sell_proceeds, 2)
for sym, r in RESTORE.items():
    if sym not in sq["positions"]:
        sq["positions"][sym] = {
            "entry_price": r["entry_price"], "quantity": r["quantity"],
            "entry_date": r["entry_date"], "peak": max(r["entry_price"], r["current_price"]),
            "current_price": r["current_price"], "entry_score": r["entry_score"],
            "reason": r["reason"],
        }
# 清理 current_price<=0 的占位 (无)
st["silverquant"] = sq
dump(DATA / "strategy_states.json", st)
print(f"  strategy_states: silverquant cash={sq['cash']:.2f} positions={list(sq['positions'].keys())} history={len(sq['history'])}")

# ═══════════ 2. trading_signals.json ═══════════
ts = load(DATA / "trading_signals.json")

# trade_history: 删3笔卖出
th = ts.get("trade_history", {})
sq_h = [t for t in th.get("silverquant", []) if not (t.get("action") == "卖出" and t.get("symbol") in RESTORE)]
removed = len(th.get("silverquant", [])) - len(sq_h)
th["silverquant"] = sq_h
ts["trade_history"] = th
print(f"  trading_signals: 移除 {removed} 笔卖出记录")

# positions: 恢复3持仓 (按 _build_position_detail 结构)
def pos_detail(sym, r, sname="silverquant"):
    entry, cur, qty = r["entry_price"], r["current_price"], r["quantity"]
    cost = entry * qty
    mkt = cur * qty
    pnl = mkt - cost
    pnl_pct = (cur - entry) / entry * 100 if entry else 0
    peak = max(entry, cur)
    dd_peak = (cur - peak) / peak * 100 if peak else 0
    dd_entry = pnl_pct
    # total_value = cash + 全部持仓市值
    total_value = sq["cash"] + sum(
        (p.get("current_price", p.get("entry_price", 0))) * p.get("quantity", 0)
        for p in RESTORE.values()
    ) + ts["positions"]["silverquant"].get("300458", {}).get("current_price", 0) * 700
    pct = mkt / total_value * 100 if total_value else 0
    hold_days = (datetime.now() - datetime.strptime(r["entry_date"], "%Y-%m-%d")).days
    name = {"300750": "宁德时代", "600887": "伊利股份", "600900": "长江电力"}[sym]
    return {
        "symbol": sym, "name": name,
        "entry_price": round(entry, 4), "current_price": round(cur, 4),
        "quantity": qty, "cost": round(cost, 2), "market_value": round(mkt, 2),
        "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
        "peak_price": round(peak, 4),
        "drawdown_from_peak": round(dd_peak, 2), "drawdown_from_entry": round(dd_entry, 2),
        "pct": round(pct, 2), "entry_date": r["entry_date"],
        "entry_score": r["entry_score"],
        "current_score": {"300750": 8.0, "600887": 6.7, "600900": 8.9}[sym],
        "hold_days": hold_days, "reason": r["reason"],
        "stop_loss": round(entry * 0.92, 4), "strategy": "silverquant",
    }

pos_block = ts.get("positions", {})
for sym, r in RESTORE.items():
    pos_block["silverquant"][sym] = pos_detail(sym, r)
ts["positions"] = pos_block

# portfolios: 重算 silverquant
inv = sum(pd["entry_price"] * pd["quantity"] for pd in RESTORE.values()) + \
      pos_block["silverquant"]["300458"]["entry_price"] * 700
mkt_total = sum(pd["current_price"] * pd["quantity"] for pd in RESTORE.values()) + \
            pos_block["silverquant"]["300458"]["current_price"] * 700
total_value = sq["cash"] + mkt_total
pf = ts["portfolios"]["silverquant"]
pf.update({
    "cash": round(sq["cash"], 2),
    "total_value": round(total_value, 2),
    "total_invested": round(inv, 2),
    "total_pnl": round(total_value - pf.get("capital", 1000000), 2),
    "total_return": round((total_value - pf.get("capital", 1000000)) / pf.get("capital", 1000000) * 100, 2),
    "position_count": 4,
    "history_count": len(sq_h),
    "cash_pct": round(sq["cash"] / total_value * 100, 2),
    "invested_pct": round(inv / total_value * 100, 2),
    "win_rate": None, "win_trades": 0, "lose_trades": 0,
})
ts["portfolios"]["silverquant"] = pf
dump(DATA / "trading_signals.json", ts)
print(f"  trading_signals: silverquant total_value={pf['total_value']} invested={pf['total_invested']} pos={pf['position_count']} hist={pf['history_count']}")

# ═══════════ 3. trade_log.json ═══════════
tl = load(DATA / "trade_log.json")
tl["trades"] = [t for t in tl["trades"]
                if not (t.get("action") == "SELL" and t.get("symbol") in RESTORE)]
# cooldown 还原为买入日
cd = tl.get("cooldowns", {})
cd["silverquant:300750"] = "2026-08-13"
cd["silverquant:600887"] = "2026-08-13"
cd["silverquant:600900"] = "2026-08-18"
tl["cooldowns"] = cd
dump(DATA / "trade_log.json", tl)
print(f"  trade_log: trades={len(tl['trades'])} cooldowns还原")

# ═══════════ 4. shadow_account.json 重新聚合 ═══════════
sys.path.insert(0, str(ROOT))
from scripts.run_trading import _aggregate_shadow
agg = _aggregate_shadow(st)
dump(DATA / "shadow_account.json", agg)
print(f"  shadow_account: capital={agg['capital']} cash={agg['cash']:.2f} pos={len(agg['positions'])} hist={len(agg['history'])}")

# ═══════════ 不变量校验 ═══════════
sq2 = st["silverquant"]
cost_total = sum(p["entry_price"] * p["quantity"] for p in sq2["positions"].values())
print("\n── 校验 ──")
print(f"  cash + Σ(entry×qty) = {sq2['cash'] + cost_total:.2f} (期望 1,000,000.00)  {'✅' if abs(sq2['cash'] + cost_total - 1000000) < 1 else '❌'}")
mkt2 = sum(p["current_price"] * p["quantity"] for p in sq2["positions"].values())
print(f"  cash + Σ(现价×qty)  = {sq2['cash'] + mkt2:.2f} (total_value 应一致)          {'✅' if abs(sq2['cash'] + mkt2 - total_value) < 1 else '❌'}")
print(f"  positions = {len(sq2['positions'])} 只 {'✅' if len(sq2['positions']) == 4 else '❌'}")
print(f"  history 卖出数 = {sum(1 for h in sq2['history'] if h['action'] == '卖出')} {'✅' if sum(1 for h in sq2['history'] if h['action'] == '卖出') == 0 else '❌'}")
print("\n回放完成。")
