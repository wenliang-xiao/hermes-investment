"""
trading/bridge.py — 从现有数据文件桥接到新 PaperTradingEngine

将 strategy_states.json / trading_signals.json 中的三策略
持仓+历史+信号，转换为新引擎的 PaperAccount/Position/Order 模型。

保持向后兼容：不删除旧文件，不修改 analysis/trading_engine.py。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

from trading.models import PaperAccount, Position, Order
from trading.engine import PaperTradingEngine

# 尝试加载 stock_names (同项目内部)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from data.stock_names import get_name as _get_name
except ImportError:
    def _get_name(sym):
        return sym


# ── 路径解析 ──
def _project_data_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _read_json(filepath: str) -> dict | None:
    if not os.path.exists(filepath):
        return None
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════
# 从 strategy_states.json 桥接
# ═══════════════════════════════════════════

def from_strategy_states(
    states_path: str | None = None,
    initial_cash_per_strategy: float = 1_000_000,
    total_account_id: str = "bridged-from-states",
) -> PaperAccount:
    """从 strategy_states.json 恢复 PaperAccount

    将三策略(faceji/silverquant/tradingagents)的持仓合并到一个账户。
    """
    if states_path is None:
        states_path = os.path.join(_project_data_dir(), "strategy_states.json")

    states = _read_json(states_path)
    if states is None:
        return PaperAccount(
            account_id=total_account_id,
            initial_cash=initial_cash_per_strategy * 3,
        )

    total_initial = initial_cash_per_strategy * 3
    total_cash = 0.0
    all_positions: dict[str, Position] = {}
    all_history: list[dict] = []

    for sname, sdata in states.items():
        total_cash += sdata.get("cash", 0)

        # 合并持仓 (同标的累加)
        for sym, sp in sdata.get("positions", {}).items():
            entry_price = sp.get("entry_price", 0)
            qty = sp.get("quantity", 0)
            buy_date = sp.get("entry_date", "")
            peak = sp.get("peak", entry_price)
            current_price = sp.get("current_price", entry_price)
            entry_score = sp.get("entry_score", 0)

            if sym in all_positions:
                pos = all_positions[sym]
                # 加权合并
                old_cost = pos.cost_price * pos.total_quantity
                new_cost = entry_price * qty
                pos.total_quantity += qty
                if pos.total_quantity > 0:
                    pos.cost_price = (old_cost + new_cost) / pos.total_quantity
                pos.peak_price = max(pos.peak_price, peak)
                pos.current_price = current_price
                # 取最早的 buy_date
                if buy_date and (not pos.buy_date or buy_date < pos.buy_date):
                    pos.buy_date = buy_date
                if entry_score > pos.entry_score:
                    pos.entry_score = entry_score
            else:
                name = _get_name(sym)
                pos = Position(
                    symbol=sym,
                    name=name,
                    total_quantity=qty,
                    cost_price=entry_price,
                    current_price=current_price,
                    buy_date=buy_date,
                    peak_price=peak,
                    entry_score=entry_score,
                )
                # 判断 T+1 解锁
                today = date.today().strftime("%Y-%m-%d")
                if buy_date and buy_date != today:
                    pos.available_quantity = qty
                all_positions[sym] = pos

        # 合并历史
        for h in sdata.get("history", []):
            all_history.append(h)

    # 计算已实现盈亏(从历史中提取已卖出交易的 PnL)
    realized_pnl = sum(
        h.get("pnl", 0) for h in all_history if h.get("action") == "卖出" and h.get("pnl")
    )

    account = PaperAccount(
        account_id=total_account_id,
        initial_cash=total_initial,
        available_cash=total_cash,
        positions=all_positions,
        realized_pnl=realized_pnl,
    )

    # 转换为 Order 对象加入历史
    all_history.sort(key=lambda x: x.get("date", ""))
    for h in all_history:
        direction = "buy" if h.get("action") == "买入" else "sell"
        order = Order(
            order_id=f"bridged-{h.get('date','')}-{h.get('symbol','')}-{direction}",
            symbol=h.get("symbol", ""),
            direction=direction,
            price=h.get("price", 0),
            quantity=h.get("quantity", 0),
            filled_quantity=h.get("quantity", 0),
            filled_price=h.get("price", 0),
            status="filled",
            reason=h.get("reason", ""),
            created_at=h.get("date", ""),
            filled_at=h.get("date", ""),
        )
        account.order_history.append(order)

    return account


# ═══════════════════════════════════════════
# 从 trading_signals.json 桥接
# ═══════════════════════════════════════════

def from_trading_signals(
    signals_path: str | None = None,
    account_id: str = "bridged-from-signals",
    initial_cash: float = 3_000_000,
) -> PaperTradingEngine:
    """从 trading_signals.json 创建 PaperTradingEngine

    导入三策略持仓、交易历史、信号记录。
    """
    if signals_path is None:
        signals_path = os.path.join(_project_data_dir(), "trading_signals.json")

    engine = PaperTradingEngine(initial_cash=initial_cash, account_id=account_id)
    data = _read_json(signals_path)

    if data is None:
        return engine

    # 从 portfolios 恢复各策略现金
    portfolios = data.get("portfolios", {})
    total_cash = 0.0
    for sname, pf in portfolios.items():
        total_cash += pf.get("cash", 0)

    engine.account.available_cash = total_cash

    # 从 positions 恢复持仓
    positions_data = data.get("positions", {})
    for sname, pos_map in positions_data.items():
        for sym, pd in pos_map.items():
            entry_price = pd.get("entry_price", 0)
            qty = pd.get("quantity", 0)
            buy_date = pd.get("entry_date", "")
            current_price = pd.get("current_price", entry_price)
            peak = pd.get("peak_price", entry_price)
            entry_score = pd.get("entry_score", 0)
            name = _get_name(sym)

            if sym in engine.account.positions:
                pos = engine.account.positions[sym]
                old_cost = pos.cost_price * pos.total_quantity
                new_cost = entry_price * qty
                pos.total_quantity += qty
                if pos.total_quantity > 0:
                    pos.cost_price = (old_cost + new_cost) / pos.total_quantity
                pos.current_price = current_price
                pos.peak_price = max(pos.peak_price, peak)
                if entry_score > pos.entry_score:
                    pos.entry_score = entry_score
            else:
                pos = Position(
                    symbol=sym, name=name,
                    total_quantity=qty,
                    cost_price=entry_price,
                    current_price=current_price,
                    buy_date=buy_date,
                    peak_price=peak,
                    entry_score=entry_score,
                )
                today = date.today().strftime("%Y-%m-%d")
                if buy_date and buy_date != today:
                    pos.available_quantity = qty
                engine.account.positions[sym] = pos

    # 从 trade_history 恢复历史订单
    trade_history = data.get("trade_history", {})
    all_trades = []
    for sname, trades in trade_history.items():
        for t in trades:
            all_trades.append((t.get("date", ""), t, sname))

    all_trades.sort(key=lambda x: x[0])
    for _, t, sname in all_trades:
        direction = "buy" if t.get("action") == "买入" else "sell"
        price = t.get("price", 0)
        qty = t.get("quantity", 0)

        order = Order(
            order_id=f"bridged-{t.get('date','')}-{t.get('symbol','')}-{direction}-{sname}",
            symbol=t.get("symbol", ""),
            direction=direction,
            price=price,
            quantity=qty,
            filled_quantity=qty,
            filled_price=price,
            status="filled",
            reason=t.get("reason", f"[{sname}]"),
            created_at=t.get("date", ""),
            filled_at=t.get("date", ""),
        )
        engine.account.order_history.append(order)

        # 统计已实现 PnL
        if t.get("pnl"):
            engine.account.realized_pnl += t.get("pnl", 0)

    return engine


# ═══════════════════════════════════════════
# 导出为旧 format (兼容 Dashboard)
# ═══════════════════════════════════════════

def to_shadow_account_format(engine: PaperTradingEngine) -> dict:
    """将 PaperTradingEngine 状态导出为 shadow_account.json 兼容格式

    供 Dashboard 现有 API 直接消费。
    """
    return {
        "capital": engine.account.initial_cash,
        "cash": engine.account.available_cash,
        "positions": {
            sym: {
                "symbol": p.symbol,
                "name": p.name,
                "entry_price": p.cost_price,
                "current_price": p.current_price,
                "quantity": p.total_quantity,
                "cost": p.total_cost,
                "entry_date": p.buy_date,
                "peak_price": p.peak_price,
                "entry_score": p.entry_score,
                "reason": "",
            }
            for sym, p in engine.account.positions.items()
        },
        "history": [
            {
                "time": o.filled_at or o.created_at,
                "symbol": o.symbol,
                "action": "买入" if o.is_buy else "卖出",
                "price": o.filled_price,
                "quantity": o.filled_quantity,
                "cost": o.total_cost,
                "pnl": None,  # 简化
                "reason": o.reason,
            }
            for o in engine.account.order_history
            if o.status == "filled"
        ],
        "realized_pnl": round(engine.account.realized_pnl, 2),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def export_to_json(engine: PaperTradingEngine, filepath: str | None = None):
    """导出为 shadow_account.json 兼容文件"""
    if filepath is None:
        filepath = os.path.join(_project_data_dir(), "shadow_account.json")

    data = to_shadow_account_format(engine)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    tmp_path = filepath + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, filepath)
    return data
