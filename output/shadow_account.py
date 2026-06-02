"""
Shadow Account（Vibe-Trading概念）
模拟盘追踪：记录信号→模拟建仓→跟踪盈亏→纪律执行
"""
import json, os
from datetime import datetime, timedelta
from investment_system import config

SHADOW_FILE = config.DATA_DIR / "shadow_account.json"


def load_shadow():
    if os.path.exists(SHADOW_FILE):
        try:
            with open(SHADOW_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"positions": {}, "history": [], "capital": 1000000, "cash": 1000000}


def save_shadow(data):
    with open(SHADOW_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def entry(symbol: str, name: str, action: str, price: float, reason: str,
          quantity: int = 100, pct: float = 0.02):
    book = load_shadow()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry_record = {
        "time": now, "symbol": symbol, "name": name,
        "action": action, "price": price, "reason": reason,
    }
    book["history"].append(entry_record)
    book["history"] = book["history"][-200:]

    if action in ("买入", "加仓"):
        book["positions"][symbol] = {
            "name": name, "entry_price": price,
            "entry_time": now,
            "quantity": quantity, "current_price": price,
            "peak_price": price, "peak_time": now,
            "pct": pct,
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
        }
    elif action in ("卖出", "减仓"):
        book["positions"].pop(symbol, None)

    save_shadow(book)
    return book


def update_prices(symbol_price_map: dict):
    book = load_shadow()
    for sym, price in symbol_price_map.items():
        if sym in book["positions"]:
            pos = book["positions"][sym]
            pos["current_price"] = price
            if pos.get("peak_price", 0) < price:
                pos["peak_price"] = price
                pos["peak_time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    save_shadow(book)
    return book


def check_stops() -> list:
    book = load_shadow()
    alerts = []
    for sym, pos in book["positions"].items():
        current = pos.get("current_price", 0)
        entry_price = pos.get("entry_price", 0)
        peak_price = pos.get("peak_price", entry_price)
        if entry_price == 0:
            continue

        entry_date_str = pos.get("entry_date", "")
        hold_days = 0
        try:
            entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
            hold_days = (datetime.now() - entry_dt).days
        except:
            pass

        pnl_pct = (current - entry_price) / entry_price
        dd_from_peak = (current - peak_price) / peak_price if peak_price else 0

        if hold_days < 10:
            if pnl_pct <= -0.08:
                alerts.append({
                    "symbol": sym, "name": pos.get("name", ""),
                    "type": "STOP_LOSS_HARD",
                    "entry": entry_price, "current": current,
                    "loss": round(pnl_pct * 100, 1),
                    "note": f"持仓{hold_days}天<10天，触发-8%硬止损"
                })
        else:
            if pnl_pct >= 0.30:
                threshold = -0.12
                label = "T3(-12%)"
            elif pnl_pct >= 0.10:
                threshold = -0.15
                label = "T2(-15%)"
            else:
                threshold = -0.20
                label = "T1(-20%)"

            if dd_from_peak <= threshold:
                alerts.append({
                    "symbol": sym, "name": pos.get("name", ""),
                    "type": f"TRAILING_STOP_{label}",
                    "entry": entry_price, "current": current,
                    "peak": peak_price,
                    "dd_from_peak": round(dd_from_peak * 100, 1),
                    "pnl": round(pnl_pct * 100, 1),
                    "note": f"持仓{hold_days}天，峰值回撤{abs(dd_from_peak)*100:.1f}%触发trailing stop"
                })
    return alerts


def get_shadow_summary() -> dict:
    book = load_shadow()
    positions = book["positions"]
    total_value = book["cash"]

    items = []
    for sym, pos in positions.items():
        current = pos.get("current_price", pos.get("entry_price", 0))
        entry = pos["entry_price"]
        change = ((current - entry) / entry * 100) if entry else 0
        peak = pos.get("peak_price", current) or current
        dd_peak = (current - peak) / peak * 100 if peak else 0

        entry_date_str = pos.get("entry_date", pos.get("entry_time", "")[:10])
        hold_days = 0
        try:
            entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d")
            hold_days = (datetime.now() - entry_dt).days
        except:
            pass

        quantity = pos.get("quantity", 0)
        position_value = current * quantity if quantity else total_value * pos.get("pct", 0.02)
        total_value += position_value

        items.append({
            "symbol": sym, "name": pos.get("name", ""),
            "entry": entry, "current": current,
            "change": round(change, 1),
            "peak": round(peak, 2),
            "dd_from_peak": round(dd_peak, 1),
            "hold_days": hold_days,
            "stop_loss": pos.get("stop_loss", entry * 0.92) if "stop_loss" in pos else entry * 0.92,
            "status": "✅" if change >= 0 else "📉",
        })

    return {
        "positions": items,
        "count": len(items),
        "total_value": round(total_value, 0),
        "cash": book["cash"],
        "latest_entry": book["history"][-1] if book["history"] else None,
    }
