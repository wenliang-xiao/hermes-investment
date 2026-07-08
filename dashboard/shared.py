"""共享工具函数 — 数据加载、摘要构建、图表数据生成等"""

import json, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

# Stock name mapping
try:
    from data.stock_names import STOCK_NAMES, ETF_NAMES, get_name
except ImportError:
    STOCK_NAMES = {}
    ETF_NAMES = {}
    def get_name(code): return code


# 产业链映射
_CHAIN_NAMES = {
    "300502": "AI算力-光模块", "688041": "AI算力-处理器", "688008": "半导体-接口",
    "688256": "AI算力-处理器", "600519": "消费-白酒", "000858": "消费-白酒",
    "300750": "新能源-动力电池", "002594": "新能源-整车", "000333": "消费-家电",
    "300059": "金融-券商", "603259": "医药-CXO", "002371": "半导体-设备",
    "600030": "金融-券商", "601318": "金融-保险", "600036": "金融-银行",
    "002415": "AI算力-视觉", "300124": "新能源-工控", "688012": "半导体-设备",
    "300274": "新能源-逆变器", "601012": "新能源-光伏", "300014": "新能源-电池",
    "002304": "消费-白酒", "600585": "基建-建材", "000651": "消费-家电",
    "300136": "消费电子-射频", "002475": "消费电子-连接器", "002129": "半导体-材料",
    "002460": "新能源-锂资源", "002230": "AI算力-语音", "002129": "半导体-材料",
    "NVDA": "AI算力-GPU", "AMD": "AI算力-GPU", "MU": "半导体-存储",
    "TSM": "半导体-代工", "VST": "AI算力-电力", "CEG": "AI算力-电力",
    "GEV": "AI算力-电力", "0700.HK": "互联网-平台", "9988.HK": "互联网-平台",
    "BABA": "互联网-平台", "MSFT": "AI算力-软件", "META": "互联网-社交",
    "AAPL": "消费电子-手机", "AMZN": "互联网-电商",
}


def _guess_chain(symbol):
    return _CHAIN_NAMES.get(symbol, "其他")


def _classify_market(symbol):
    """根据代码分类市场"""
    sym = str(symbol)
    if sym.endswith(".HK"):
        return "hk"
    if sym.endswith(".US") or sym in ("GOOGL", "AAPL", "AMZN", "MSFT", "NVDA", "META", "TSLA",
                                       "GOOG", "NFLX", "JPM", "V", "JNJ", "WMT", "PG", "MA",
                                       "HD", "DIS", "BAC", "XOM", "KO", "PEP", "PFE", "MRK",
                                       "INTC", "CSCO", "VZ", "T", "ABT", "CVX", "MU", "QQQ",
                                       "SPY", "TLT", "GLD", "SLV", "USO", "XLF", "XLK", "VST"):
        return "us"
    if sym.startswith("=") or sym in ("CL=F", "GC=F", "HG=F"):
        return "us"
    if sym.isdigit() and len(sym) == 6:
        if sym.startswith(("51", "15", "16", "56", "58", "159")):
            return "etf"
        return "a_share"
    if sym.startswith("^"):
        return "us"
    return "us"


def load_shadow():
    path = ROOT / "data" / "shadow_account.json"
    if not path.exists():
        return {"capital": 1000000, "cash": 1000000, "positions": {}, "history": [], "realized_pnl": 0}
    with open(path) as f:
        return json.load(f)


def build_summary(book):
    total_pnl = book.get("realized_pnl", 0)
    positions = []
    for sym, pos in book.get("positions", {}).items():
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", entry)
        qty = pos.get("quantity", 0)
        cost = pos.get("cost", entry * qty)
        mkt_val = current * qty
        pnl = mkt_val - cost
        pnl_pct = (current - entry) / entry * 100 if entry else 0
        peak = pos.get("peak_price", entry)
        dd = (current - peak) / peak * 100 if peak else 0
        try:
            entry_dt = datetime.strptime(pos.get("entry_date", ""), "%Y-%m-%d")
            hold = (datetime.now() - entry_dt).days
        except:
            hold = 0
        positions.append({
            "symbol": sym, "name": pos.get("name", sym),
            "entry_price": round(entry, 4), "current_price": round(current, 4),
            "quantity": qty, "cost": round(cost, 2), "market_value": round(mkt_val, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "peak": round(peak, 4), "dd_from_peak": round(dd, 1),
            "hold_days": hold,
            "entry_score": pos.get("entry_score"),
            "pct": pos.get("pct", 0),
            "stop_loss": round(entry * 0.92, 4) if hold < 10 else round(peak * 0.88, 4),
        })

    cash = book.get("cash", 0)
    position_value = sum(p["market_value"] for p in positions)
    total_value = cash + position_value
    total_invested = sum(p["cost"] for p in positions)
    unrealized = position_value - total_invested
    realized = book.get("realized_pnl", 0)
    capital = book.get("capital", 1000000)

    return {
        "capital": round(capital, 2),
        "cash": round(cash, 2),
        "position_value": round(position_value, 2),
        "total_value": round(total_value, 2),
        "position_count": len(positions),
        "total_invested": round(total_invested, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "total_pnl": round(unrealized + realized, 2),
        "total_return": round((unrealized + realized) / capital * 100, 2) if capital else 0,
        "cash_pct": round(cash / total_value * 100, 1) if total_value else 100,
        "position_pct": round(position_value / total_value * 100, 1) if total_value else 0,
        "positions": sorted(positions, key=lambda p: -abs(p["pnl"])),
    }


def build_history(book):
    history = book.get("history", [])
    trades = []
    for h in history:
        pnl = h.get("pnl")
        trades.append({
            "time": h.get("time", ""),
            "symbol": h.get("symbol", ""),
            "name": h.get("name", ""),
            "action": h.get("action", ""),
            "price": h.get("price", 0),
            "quantity": h.get("quantity", 0),
            "reason": h.get("reason", ""),
            "cost": h.get("cost", 0),
            "pnl": pnl,
            "pnl_str": f"{pnl:+.0f}" if pnl is not None else "",
            "is_win": pnl > 0 if pnl is not None else None,
        })
    # Build PnL history for chart (daily PnL from history records)
    return trades[::-1]  # newest first


def build_chart_data(book):
    """Build portfolio value over time from history

    从每笔交易的 pnl 推算每日净值变化。
    策略初始资本 ×3 = ¥3,000,000（面基/SQ/TA 各 ¥1,000,000）。
    每日净值 = 初始总资本 + 截至该日的累计已实现 PnL。
    因为持仓字段可能不可靠，所以只从已平仓 pnl 推算。
    """
    capital = book.get("capital", 3000000)  # 三策略初始总资本
    history = book.get("history", [])
    # 历史最可能是倒序（newest first），但 pnl 累计不分方向
    # 按日期累积：daily_cumulative_pnl[t] = 该日及之前所有 pnl 之和
    daily_pnl = {}  # date -> sum of pnl for that date
    for h in history:
        pnl = h.get("pnl")
        time_str = h.get("time", "")
        date_part = time_str[:10] if time_str else ""
        if pnl is not None and date_part:
            daily_pnl[date_part] = daily_pnl.get(date_part, 0) + pnl

    # 累计净值序列
    sorted_dates = sorted(daily_pnl.keys())
    cumulative = capital
    points = []
    if sorted_dates:
        points.append({"date": sorted_dates[0], "value": capital})
    for d in sorted_dates:
        cumulative += daily_pnl[d]
        points.append({"date": d, "value": cumulative})

    # 加当前总值（可能含未平仓浮盈）
    summary = build_summary(book)
    final_val = summary.get("total_value", capital)
    points.append({"date": datetime.now().strftime("%Y-%m-%d"), "value": final_val})

    # 去重（同日期保留最后一条）
    by_date = {}
    for p in points:
        if p["date"]:
            by_date[p["date"]] = p["value"]
    sorted_dates = sorted(by_date.keys())

    return {
        "labels": sorted_dates,
        "values": [by_date[d] for d in sorted_dates],
        "return_pct": summary.get("total_return", 0),
    }


def _clean_signals(signals, context="signal"):
    """第三层防护：读路径过滤 price≤0 的毒信号"""
    if not signals:
        return signals, 0
    filtered = []
    dropped = 0
    for s in signals:
        p = s.get("price", 0)
        if p is None or p <= 0:
            dropped += 1
            continue
        filtered.append(s)
    if dropped:
        print(f"  🛡️ _clean_signals({context}): 过滤 {dropped}/{len(signals)} 条 price≤0 信号", flush=True)
    return filtered, dropped


def _aggregate_strategy_portfolios():
    """从策略状态文件聚合真实持仓和交易历史"""
    st_path = ROOT / "data" / "strategy_states.json"
    if not st_path.exists():
        return None
    with open(st_path) as f:
        states = json.load(f)

    total_cash = 0
    all_positions = {}
    all_history = []

    for sname, state in states.items():
        total_cash += state.get("cash", 0)
        for h in state.get("history", []):
            entry = {
                "time": h.get("date", ""),
                "symbol": h.get("symbol", ""),
                "action": "买入" if h.get("action") == "买入" else "卖出",
                "price": h.get("price", 0),
                "quantity": h.get("quantity", 0),
                "cost": h.get("cost", 0),
                "pnl": h.get("pnl"),
                "reason": h.get("reason", ""),
                "strategy": sname,
            }
            all_history.append(entry)
        for sym, pos in state.get("positions", {}).items():
            if sym not in all_positions:
                all_positions[sym] = {
                    "symbol": sym,
                    "entry_price": pos.get("entry_price", 0),
                    "quantity": pos.get("quantity", 0),
                    "entry_date": pos.get("entry_date", ""),
                    "current_price": pos.get("current_price", pos.get("entry_price", 0)),
                    "name": get_name(sym),
                }

    total_invested = sum(p["entry_price"] * p["quantity"] for p in all_positions.values())
    return {
        "capital": 3000000,  # 三策略各 ¥1,000,000 初始资本
        "cash": total_cash,
        "positions": all_positions,
        "history": sorted(all_history, key=lambda x: x.get("time", ""), reverse=True),
        "created_at": "2026-06-24",
        "realized_pnl": sum(h.get("pnl", 0) for h in all_history if h.get("pnl")),
    }
