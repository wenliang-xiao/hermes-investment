"""
Shadow Account（Vibe-Trading概念）
模拟盘追踪：记录信号→模拟建仓→跟踪盈亏→纪律执行
"""
import json, os
from datetime import datetime
from investment_system import config

SHADOW_FILE = config.DATA_DIR / "shadow_account.json"


def load_shadow():
    """加载模拟盘"""
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


def entry(symbol: str, name: str, action: str, price: float, reason: str):
    """模拟盘记录一条交易"""
    book = load_shadow()
    entry = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "symbol": symbol, "name": name,
        "action": action, "price": price,
        "reason": reason,
    }
    book["history"].append(entry)
    book["history"] = book["history"][-200:]  # 只保留最近200条

    if action in ("买入", "加仓"):
        book["positions"][symbol] = {
            "name": name, "entry_price": price,
            "entry_time": entry["time"],
            "quantity": 0, "current_price": price,
            "pct": 0.02,  # 默认2%
            "stop_loss": price * 0.92,
            "take_profit_1": price * 1.15,
            "take_profit_2": price * 1.30,
        }
    elif action in ("卖出", "减仓"):
        book["positions"].pop(symbol, None)

    save_shadow(book)
    return book


def update_prices(symbol_price_map: dict):
    """批量更新模拟盘持仓价格"""
    book = load_shadow()
    for sym, price in symbol_price_map.items():
        if sym in book["positions"]:
            book["positions"][sym]["current_price"] = price
    save_shadow(book)
    return book


def check_stops() -> list:
    """检查8%硬止损"""
    book = load_shadow()
    alerts = []
    for sym, pos in book["positions"].items():
        current = pos.get("current_price", 0)
        entry_price = pos.get("entry_price", 0)
        if entry_price == 0:
            continue
        change = (current - entry_price) / entry_price * 100
        name = pos.get("name", "")
        if change <= -8:
            alerts.append({
                "symbol": sym, "name": name,
                "type": "STOP_LOSS",
                "entry": entry_price, "current": current,
                "loss": round(change, 1),
            })
        elif change >= 15 and change < 30:
            alerts.append({
                "symbol": sym, "name": name,
                "type": "TAKE_PROFIT_T1",
                "entry": entry_price, "current": current,
                "profit": round(change, 1),
            })
        elif change >= 30:
            alerts.append({
                "symbol": sym, "name": name,
                "type": "TAKE_PROFIT_T2",
                "entry": entry_price, "current": current,
                "profit": round(change, 1),
            })
    return alerts


def get_shadow_summary() -> dict:
    """模拟盘概况"""
    book = load_shadow()
    positions = book["positions"]
    total_value = book["cash"]
    pnl = 0

    items = []
    for sym, pos in positions.items():
        change = ((pos.get("current_price", 0) - pos["entry_price"]) / pos["entry_price"]) * 100
        items.append({
            "symbol": sym, "name": pos.get("name", ""),
            "entry": pos["entry_price"], "current": pos.get("current_price", pos["entry_price"]),
            "change": round(change, 1),
            "stop_loss": pos["stop_loss"],
            "status": "✅" if change >= 0 else "📉",
        })
        position_value = pos.get("current_price", 0) * pos.get("quantity", 0) or total_value * pos.get("pct", 0.02)
        total_value += position_value

    return {
        "positions": items,
        "count": len(items),
        "total_value": round(total_value, 0),
        "cash": book["cash"],
        "latest_entry": book["history"][-1] if book["history"] else None,
    }
