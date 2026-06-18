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
          quantity: int = 100, pct: float = 0.02, entry_score: float = None):
    book = load_shadow()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    if action in ("买入", "加仓"):
        # 已有持仓不覆盖 — run_daily建仓前已检查_hold
        if symbol in book["positions"]:
            return book
        cost = price * quantity
        if cost > book["cash"]:
            # 现金不足时按比例缩减数量
            quantity = max(100, int(book["cash"] / price / 100) * 100)
            cost = price * quantity
            if cost > book["cash"]:
                return book  # 现金连最小单位都不够
        book["cash"] -= cost

        pos = {
            "name": name, "entry_price": price,
            "entry_time": now,
            "quantity": quantity, "current_price": price,
            "peak_price": price, "peak_time": now,
            "pct": pct,
            "entry_date": datetime.now().strftime("%Y-%m-%d"),
            "cost": cost,
        }
        if entry_score is not None:
            pos["entry_score"] = entry_score
        book["positions"][symbol] = pos
        book["history"].append({
            "time": now, "symbol": symbol, "name": name,
            "action": action, "price": price, "reason": reason,
            "quantity": quantity, "cost": cost,
        })
    elif action in ("卖出", "减仓"):
        pos = book["positions"].pop(symbol, None)
        if pos:
            pnl = (price - pos["entry_price"]) * pos.get("quantity", 0)
            book["cash"] += price * pos.get("quantity", 0)
            book["realized_pnl"] = book.get("realized_pnl", 0) + pnl
            book["history"].append({
                "time": now, "symbol": symbol, "name": pos.get("name", symbol),
                "action": action, "price": price, "reason": reason,
                "quantity": pos.get("quantity", 0), "pnl": round(pnl, 2),
            })

    book["history"] = book["history"][-200:]
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


def exit_position(symbol: str, price: float = None, reason: str = "手动清仓") -> dict:
    """退出持仓：加回现金、计算盈亏、加入5天冷却期"""
    book = load_shadow()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    pos = book["positions"].pop(symbol, None)

    if pos and price:
        qty = pos.get("quantity", 0)
        pnl = (price - pos["entry_price"]) * qty
        proceeds = price * qty
        book["cash"] += proceeds
        book["realized_pnl"] = book.get("realized_pnl", 0) + pnl

        book["history"].append({
            "time": now, "symbol": symbol,
            "name": pos.get("name", symbol),
            "action": "卖出", "price": price, "reason": reason,
            "quantity": qty, "pnl": round(pnl, 2),
            "proceeds": round(proceeds, 2),
        })
    else:
        book["history"].append({
            "time": now, "symbol": symbol,
            "name": pos.get("name", symbol) if pos else symbol,
            "action": "卖出", "price": price or 0,
            "reason": reason,
        })

    book["history"] = book["history"][-200:]

    # 加入冷却期
    if "cooldown" not in book:
        book["cooldown"] = {}
    book["cooldown"][symbol] = datetime.now().strftime("%Y-%m-%d")

    save_shadow(book)
    return book


def is_on_cooldown(symbol: str, days: int = 5) -> bool:
    """检查某只股票是否在冷却期内（默认5天）"""
    book = load_shadow()
    cd = book.get("cooldown", {})
    exit_date_str = cd.get(symbol)
    if not exit_date_str:
        return False
    try:
        exit_dt = datetime.strptime(exit_date_str, "%Y-%m-%d")
        return (datetime.now() - exit_dt).days < days
    except:
        return False


def get_cooldown_list() -> list:
    """返回当前仍在冷却期的股票列表"""
    book = load_shadow()
    cd = book.get("cooldown", {})
    now = datetime.now()
    result = []
    for sym, ds in cd.items():
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d")
            remaining = 5 - (now - dt).days
            if remaining > 0:
                result.append({"symbol": sym, "exit_date": ds, "remaining_days": remaining})
        except:
            pass
    return result


def clean_cooldown(max_days: int = 30):
    """清理30天前的冷却期记录"""
    book = load_shadow()
    cd = book.get("cooldown", {})
    cutoff = (datetime.now() - timedelta(days=max_days)).strftime("%Y-%m-%d")
    book["cooldown"] = {k: v for k, v in cd.items() if v >= cutoff}
    save_shadow(book)


# ═══ 策略四投资组合管理 ═══


def get_no_trade_reasons(symbol: str, score: float, scan_results: list,
                           positions: list, dual_closed: bool,
                           cool_func=None, max_positions=8) -> list:
    """返回该标的不建仓的所有原因列表"""
    reasons = []
    
    # Check if already held
    held_symbols = {p.get("symbol", "") for p in positions}
    if symbol in held_symbols:
        return []
    
    # Check cooldown
    if cool_func and cool_func(symbol):
        reasons.append("冷却期(5天)")
    
    # Check dual gate
    if dual_closed:
        reasons.append("双门关闭")
    
    # Check score
    if score < 5.0:
        reasons.append(f"评分不足({score:.1f}<5.0)")
    
    # Check max positions
    if len(positions) >= max_positions:
        reasons.append(f"仓位已满({len(positions)}/{max_positions})")
    
    return reasons

def get_all_no_trade_reasons(scan_results: list, positions: list,
                              dual_closed: bool, cool_func=None,
                              max_positions=8) -> dict:
    """返回所有未建仓标的的完整不交易原因"""
    held_symbols = {p.get("symbol", "") for p in positions}
    reasons = {}
    if not scan_results:
        return {"整体": "无扫描结果"}
    
    for s in scan_results[:15]:
        sym = s.get("symbol", "")
        if not sym or sym in held_symbols:
            continue
        score = s.get("score", 0)
        r = get_no_trade_reasons(sym, score, scan_results, positions,
                                  dual_closed, cool_func, max_positions)
        if r:
            reasons[s.get("name", sym)] = r
    return reasons

def init_portfolio(capital: float = 1000000.0) -> dict:
    """初始化策略四投资组合。仅在 shadow_account.json 不存在时调用。"""
    book = load_shadow()
    if book.get("capital", 0) > 0 and book.get("initialized"):
        return book
    book["capital"] = capital
    book["cash"] = capital
    book["initialized"] = True
    book["realized_pnl"] = 0.0
    book["created_at"] = datetime.now().strftime("%Y-%m-%d")
    book["positions"] = {}
    book["history"] = []
    save_shadow(book)
    return book


def get_portfolio_metrics() -> dict:
    """计算 G=E×P×F×T 复利指标"""
    book = load_shadow()
    summary = get_shadow_summary()
    capital = book.get("capital", 1000000)
    cash = book.get("cash", capital)
    total = summary.get("total_value", cash)

    # E(Edge): 持仓中的总盈亏
    unrealized = total - capital - book.get("realized_pnl", 0)
    realized = book.get("realized_pnl", 0)
    total_pnl = realized + unrealized
    total_return = total_pnl / capital if capital else 0

    # 胜率统计
    history = book.get("history", [])
    exited_trades = [h for h in history if h.get("action") in ("卖出", "减仓")]
    wins = sum(1 for t in exited_trades if t.get("pnl", 0) > 0)
    total_closed = len(exited_trades) or 1
    win_rate = wins / total_closed

    # P(Position): 当前仓位占比
    position_pct = (total - cash) / total if total > 0 else 0

    # F(Frequency): 交易次数
    trade_count = len(exited_trades)

    # T(Time): 存活天数
    created = book.get("created_at", datetime.now().strftime("%Y-%m-%d"))
    try:
        days_alive = (datetime.now() - datetime.strptime(created, "%Y-%m-%d")).days
    except:
        days_alive = 0

    return {
        "capital": capital,
        "cash": cash,
        "total_value": total,
        "unrealized_pnl": round(unrealized, 0),
        "realized_pnl": round(realized, 0),
        "total_pnl": round(total_pnl, 0),
        "total_return": round(total_return * 100, 2),
        "win_rate": round(win_rate * 100, 1),
        "position_pct": round(position_pct * 100, 1),
        "trade_count": trade_count,
        "days_alive": days_alive,
        "position_count": summary.get("count", 0),
        "max_positions": 8,
        "edge_active": unrealized > 0 or realized > 0,
        "traversal_ok": total > capital * 0.75,  # 遍历性: 不爆仓
    }
