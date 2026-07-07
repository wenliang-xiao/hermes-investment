"""
scripts/realtime_price.py — 实时行情服务

从 data_router 获取全持仓实时行情。
支持东财(A股) + yfinance(港美股) + AKShare(期货) 多源聚合。
每个请求带 5s 超时，不阻塞 Dashboard。

用法:
    from scripts.realtime_price import get_all_realtime

    prices = get_all_realtime()     # 默认读取 shadow_account.json
    # => {"300502": {"price": 552, "change": 1.23, ...}, ...}
"""
from __future__ import annotations

import json, sys, time, socket
from datetime import datetime
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

try:
    from data.data_router import get_rt
except Exception:
    get_rt = None

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def get_holding_symbols() -> list[dict]:
    """从模拟盘读取当前持仓标的"""
    shadow_path = DATA_DIR / "shadow_account.json"
    if not shadow_path.exists():
        return []

    with open(shadow_path) as f:
        book = json.load(f)

    positions = book.get("positions", {})
    symbols = []
    for sym, pos in positions.items():
        symbols.append({
            "symbol": sym,
            "name": pos.get("name", sym),
            "qty": pos.get("quantity", 0),
            "entry_price": pos.get("entry_price", 0),
        })
    return symbols


def get_signals_symbols() -> list[str]:
    """从今日信号读取标的"""
    sig_path = DATA_DIR / "trading_signals.json"
    if not sig_path.exists():
        return []
    with open(sig_path) as f:
        data = json.load(f)
    symbols = set()
    for sig in data.get("signals", []):
        sym = sig.get("symbol", "")
        if sym:
            symbols.add(sym)
    return list(symbols)


def _is_trading_hours() -> bool:
    """粗略判断是否在 A 股交易时段，非强制阻断仅用于提前返回"""
    from datetime import datetime
    now = datetime.now()
    # 周末不交易
    if now.weekday() >= 5:
        return False
    # 9:25-15:00 为交易时段（含集合竞价）
    hour, minute = now.hour, now.minute
    total_min = hour * 60 + minute
    return 565 <= total_min <= 900  # 9:25 ~ 15:00


def get_all_realtime(
    include_holdings: bool = True,
    include_signals: bool = True,
    extra_symbols: list[str] = None,
) -> dict[str, dict]:
    """获取所有相关标的的实时行情

    自动轮询 data_router.get_rt()，带间隔保护(0.5s)。
    非交易时段直接返回空（避免无效 API 调用）。

    Args:
        include_holdings: 是否包含持仓标的
        include_signals: 是否包含信号标的
        extra_symbols: 额外标的列表

    Returns:
        {symbol: {price, change_pct, volume, ...}}
    """
    if not _is_trading_hours():
        return {}  # 非交易时段跳过

    symbols = []

    if include_holdings:
        for h in get_holding_symbols():
            if h["symbol"] not in [s["symbol"] for s in symbols]:
                symbols.append(h)

    if include_signals:
        sig_syms = get_signals_symbols()
        for sym in sig_syms:
            if sym not in [s["symbol"] for s in symbols]:
                symbols.append({"symbol": sym})

    if extra_symbols:
        for sym in extra_symbols:
            if sym not in [s["symbol"] for s in symbols]:
                symbols.append({"symbol": sym})

    if not symbols:
        return {}
    if not get_rt:  # 数据源不可用时直接返回
        return {}

    # 总体10s硬超时（防止外网 API 卡死 Dashboard）
    start_time = time.time()
    result = {}
    for item in symbols:
        sym = item["symbol"]
        if time.time() - start_time > 8:
            result[sym] = {"symbol": sym, "name": item.get("name", sym),
                           "price": 0, "change_pct": 0, "error": "overall_timeout"}
            continue
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                fut = pool.submit(get_rt, sym)
                rt = fut.result(timeout=6)
            if rt:
                result[sym] = {
                    "symbol": sym,
                    "name": rt.get("name", item.get("name", sym)),
                    "price": rt.get("price", 0),
                    "change_pct": rt.get("change_pct", 0),
                    "change": rt.get("change", 0),
                    "volume": rt.get("volume", 0),
                    "amount": rt.get("amount", 0),
                    "turnover_rate": rt.get("turnover_rate", 0),
                    "pe": rt.get("pe"),
                    "source": rt.get("source", ""),
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                }
        except Exception as e:
            result[sym] = {
                "symbol": sym, "name": item.get("name", sym),
                "price": 0, "change_pct": 0,
                "error": str(e),
            }
        time.sleep(0.5)  # 防限流

    return result


def get_realtime_summary() -> dict:
    """获取包含组合快照的实时行情汇总"""
    rt_data = get_all_realtime()

    shadow_path = DATA_DIR / "shadow_account.json"
    if not shadow_path.exists():
        return {"realtime": rt_data, "error": "no shadow account"}

    with open(shadow_path) as f:
        book = json.load(f)

    positions = book.get("positions", {})
    total_market_value = 0
    total_cost = 0
    position_details = []

    for sym, rt in rt_data.items():
        pos = positions.get(sym)
        if pos:
            qty = pos.get("quantity", 0)
            entry_price = pos.get("entry_price", 0)
            cost = entry_price * qty
            market_value = rt["price"] * qty if rt["price"] else cost
            pnl = market_value - cost
            pnl_pct = (rt["price"] / entry_price - 1) * 100 if entry_price and rt["price"] else 0
            total_market_value += market_value
            total_cost += cost
            position_details.append({
                "symbol": sym,
                "name": pos.get("name", sym),
                "qty": qty,
                "entry_price": entry_price,
                "current_price": rt["price"],
                "cost": cost,
                "market_value": market_value,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "change_pct": rt.get("change_pct", 0),
            })

    cash = book.get("cash", 0)
    total_value = cash + total_market_value

    return {
        "total_value": round(total_value, 2),
        "cash": round(cash, 2),
        "position_value": round(total_market_value, 2),
        "unrealized_pnl": round(total_market_value - total_cost, 2),
        "position_count": len(position_details),
        "positions": position_details,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "realtime": rt_data,
    }


if __name__ == "__main__":
    import json
    data = get_all_realtime()
    print(json.dumps(data, ensure_ascii=False, indent=2))
