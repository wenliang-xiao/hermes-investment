"""
trading/engine.py — PaperTradingEngine 模拟交易引擎

核心能力:
  1. 委托提交 → T+1 检查 + 涨跌停检查 + 最小单位检查
  2. 订单撮合 → market 立即成交 / limit 价格穿越成交
  3. 账户更新 → 现金/持仓/冻结 四挂钩
  4. 每日快照 → 持久化到 data/paper_trading_snapshots.json
  5. 状态恢复 → JSON 序列化/反序列化

独立于 analysis/trading_engine.py，不修改现有系统。
"""
from __future__ import annotations

import json
import math
import os
import uuid
from datetime import date, datetime
from typing import Optional

from trading.models import PaperAccount, Position, Order
from trading.cost import calc_buy_cost, calc_sell_cost
from trading.rules import (
    check_t1, check_price_limit, check_min_units,
    unlock_t1_positions, get_price_limit_range, get_board,
)


class PaperTradingEngine:
    """专业 A 股模拟交易引擎

    用法:
        engine = PaperTradingEngine(initial_cash=1000000)
        order = engine.submit_order("300502", "buy", 580.0, 300, reason="面基BUY信号")
        filled = engine.match_orders({"300502": 582.0})
        engine.update_prices({"300502": 583.5, "600519": 1520.0})
        summary = engine.get_account_summary()
        engine.snapshot("2026-07-08")
        engine.save_state("data/paper_account.json")
    """

    def __init__(self, initial_cash: float = 1_000_000, account_id: str = ""):
        self._data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data"
        )
        account_id = account_id or f"paper-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.account = PaperAccount(
            account_id=account_id,
            initial_cash=initial_cash,
        )
        self._prev_close: dict[str, float] = {}  # symbol → 前收盘价
        self._order_counter = 0

    # ═══════════════════════════════════════════
    # 委托提交
    # ═══════════════════════════════════════════

    def submit_order(
        self,
        symbol: str,
        direction: str,
        price: float,
        quantity: int,
        order_type: str = "market",
        reason: str = "",
    ) -> Order:
        """提交委托单（三重校验: 涨跌停 → 最小单位 → T+1/资金）

        返回 Order 对象，status 为 "filled"(成交)/"pending"(待撮合)/"rejected"(拒绝)
        """
        direction = str(direction).lower()
        symbol = str(symbol).strip()

        # ── 生成订单 ID ──
        self._order_counter += 1
        order_id = f"{symbol}-{direction}-{self._order_counter:06d}"

        order = Order(
            order_id=order_id,
            symbol=symbol,
            direction=direction,
            order_type=order_type,
            price=float(price),
            quantity=int(quantity),
            reason=reason,
        )

        # ── 校验 1: 涨跌停 ──
        prev_close = self._prev_close.get(symbol)
        board = get_board(symbol)
        if board in ("main", "chinext", "star") and prev_close and prev_close > 0:
            ok, msg = check_price_limit(symbol, price, prev_close)
            if not ok:
                order.status = "rejected"
                order.reject_reason = msg
                self.account.order_history.append(order)
                return order

        # ── 校验 2: 最小单位 ──
        ok, msg = check_min_units(direction, quantity)
        if not ok:
            order.status = "rejected"
            order.reject_reason = msg
            self.account.order_history.append(order)
            return order

        # ── 校验 3: 方向特有规则 ──
        if direction == "buy":
            ok, msg = self._validate_buy(symbol, price, quantity)
        else:
            ok, msg = self._validate_sell(symbol, price, quantity)

        if not ok:
            order.status = "rejected"
            order.reject_reason = msg
            self.account.order_history.append(order)
            return order

        # ── 冻结资金/持仓 ──
        if direction == "buy":
            # 冻结买入所需资金(含预估费用)
            est_cost = self._estimate_buy_cost(price, quantity)
            self.account.available_cash -= est_cost
            self.account.frozen_cash += est_cost
        else:
            # 冻结卖出持仓
            pos = self.account.positions.get(symbol)
            if pos:
                pos.frozen_quantity += quantity
                pos.available_quantity -= quantity

        order.status = "pending"
        self.account.pending_orders.append(order)
        return order

    def _validate_buy(self, symbol: str, price: float, quantity: int) -> tuple:
        """买入校验"""
        est_cost = self._estimate_buy_cost(price, quantity)
        if est_cost > self.account.available_cash:
            return (False,
                    f"可用资金不足: 需要 ¥{est_cost:.2f}, 可用 ¥{self.account.available_cash:.2f}")
        return (True, "")

    def _validate_sell(self, symbol: str, price: float, quantity: int) -> tuple:
        """卖出校验: T+1 + 持仓充足"""
        pos = self.account.positions.get(symbol)

        # T+1 检查
        ok, msg = check_t1(pos)
        if not ok:
            return (False, msg)

        # 可用数量检查 (T+1 后 available_quantity 已被更新)
        if pos.available_quantity < quantity:
            return (False,
                    f"可卖数量不足: 委托 {quantity} 股, 可用 {pos.available_quantity} 股")
        return (True, "")

    def _estimate_buy_cost(self, price: float, quantity: int) -> float:
        """预估买入总成本(成交价 + 费用)"""
        detail = calc_buy_cost(price, quantity)
        return detail["actual_payment"]

    # ═══════════════════════════════════════════
    # 撤单
    # ═══════════════════════════════════════════

    def cancel_order(self, order_id: str) -> Optional[Order]:
        """撤销未成交委托，解冻资金/持仓"""
        for order in self.account.pending_orders:
            if order.order_id == order_id:
                if order.status not in ("pending",):
                    return order  # 已成交/已拒绝不能撤

                order.status = "cancelled"

                # 解冻
                self._unfreeze_order(order)

                # 移出 pending_orders
                self.account.pending_orders.remove(order)
                return order

        return None

    def _unfreeze_order(self, order: Order):
        """撤销时解冻资金/持仓"""
        if order.direction == "buy":
            est_cost = self._estimate_buy_cost(order.price, order.quantity)
            self.account.frozen_cash -= est_cost
            self.account.available_cash += est_cost
        else:
            pos = self.account.positions.get(order.symbol)
            if pos:
                pos.frozen_quantity = max(0, pos.frozen_quantity - order.quantity)
                pos.available_quantity += order.quantity

    # ═══════════════════════════════════════════
    # 订单撮合
    # ═══════════════════════════════════════════

    def match_orders(self, current_prices: dict[str, float]) -> list[Order]:
        """撮合所有待成交订单

        规则:
        - 市价单: 以 current_price 立即成交
        - 限价单: buy 价 >= current_price 成交; sell 价 <= current_price 成交
        - 均以 current_price 计算成交价(不做盘口深度模拟)

        Returns:
            已成交的订单列表
        """
        filled_orders = []
        still_pending = []

        for order in self.account.pending_orders:
            if order.status != "pending":
                still_pending.append(order)
                continue

            current_price = current_prices.get(order.symbol)
            if current_price is None or current_price <= 0:
                # 无价格，保持 pending
                still_pending.append(order)
                continue

            # 判断是否可成交
            can_fill = False
            if order.order_type == "market":
                can_fill = True
                fill_price = current_price
            elif order.order_type == "limit":
                if order.direction == "buy" and current_price <= order.price:
                    can_fill = True
                    fill_price = current_price
                elif order.direction == "sell" and current_price >= order.price:
                    can_fill = True
                    fill_price = current_price
                else:
                    still_pending.append(order)
                    continue
            else:
                # 未知类型 → 按市价单处理
                can_fill = True
                fill_price = current_price

            if not can_fill:
                still_pending.append(order)
                continue

            # ── 执行成交 ──
            fill_price = float(fill_price)
            self._fill_order(order, fill_price)
            filled_orders.append(order)

        self.account.pending_orders = still_pending
        return filled_orders

    def _fill_order(self, order: Order, fill_price: float):
        """执行订单成交: 更新账户、持仓、订单状态"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = date.today().strftime("%Y-%m-%d")

        order.filled_price = fill_price
        order.filled_quantity = order.quantity
        order.filled_at = now

        if order.direction == "buy":
            self._execute_buy_fill(order, fill_price, today)
        else:
            self._execute_sell_fill(order, fill_price, today)

        order.status = "filled"
        self.account.order_history.append(order)

    def _execute_buy_fill(self, order: Order, fill_price: float, today: str):
        """买入成交: 计算成本、更新持仓、扣除现金"""
        cost = calc_buy_cost(fill_price, order.quantity)

        order.commission = cost["commission"]
        order.stamp_tax = cost["stamp_tax"]
        order.transfer_fee = cost["transfer_fee"]
        order.slippage_cost = cost["slippage_cost"]

        actual_payment = cost["actual_payment"]

        # 解冻多余资金(原冻结可能多估了)
        est_cost = self._estimate_buy_cost(order.price, order.quantity)
        unfreeze = est_cost - actual_payment
        self.account.frozen_cash -= est_cost
        self.account.available_cash += unfreeze

        # 扣款
        self.account.available_cash -= actual_payment

        # 更新持仓
        pos = self.account.positions.get(order.symbol)
        if pos is None:
            pos = Position(
                symbol=order.symbol,
                name=getattr(order, "name", order.symbol),
                buy_date=today,
                entry_score=getattr(order, "entry_score", 0.0),
            )
            self.account.positions[order.symbol] = pos

        # 加权平均成本
        old_cost = pos.cost_price * pos.total_quantity
        new_shares = order.quantity
        old_shares = pos.total_quantity
        pos.cost_price = (old_cost + actual_payment) / (old_shares + new_shares)
        pos.total_quantity += new_shares

        # T+1 锁定: T 日买入全部冻结
        pos.available_quantity = max(0, pos.total_quantity - new_shares)
        pos.buy_date = today
        pos.current_price = fill_price
        pos.peak_price = max(pos.peak_price, fill_price)

    def _execute_sell_fill(self, order: Order, fill_price: float, today: str):
        """卖出成交: 计算费用、解冻持仓、更新现金"""
        cost = calc_sell_cost(fill_price, order.quantity)

        order.commission = cost["commission"]
        order.stamp_tax = cost["stamp_tax"]
        order.transfer_fee = cost["transfer_fee"]
        order.slippage_cost = cost["slippage_cost"]

        net_proceeds = cost["net_proceeds"]

        # 解冻持仓
        pos = self.account.positions.get(order.symbol)
        if pos:
            pos.frozen_quantity = max(0, pos.frozen_quantity - order.quantity)

        # 计算盈亏
        if pos:
            sell_cost_basis = pos.cost_price * order.quantity
            realized = net_proceeds - sell_cost_basis
            self.account.realized_pnl += realized

        # 到账
        self.account.available_cash += net_proceeds

        # 减少持仓
        if pos:
            pos.total_quantity -= order.quantity
            pos.available_quantity = max(0, pos.available_quantity - order.quantity)
            if pos.total_quantity <= 0:
                del self.account.positions[order.symbol]

    # ═══════════════════════════════════════════
    # 市价更新
    # ═══════════════════════════════════════════

    def update_prices(self, current_prices: dict[str, float]):
        """更新持仓市价 + 前收盘价缓存"""
        for sym, price in current_prices.items():
            # 缓存为前收盘价(下次委托用)
            self._prev_close[sym] = float(price)

            # 更新持仓 current_price
            pos = self.account.positions.get(sym)
            if pos:
                pos.current_price = float(price)
                if price > pos.peak_price:
                    pos.peak_price = float(price)

    def set_prev_close(self, prev_closes: dict[str, float]):
        """批量设置前收盘价"""
        self._prev_close.update({k: float(v) for k, v in prev_closes.items()})

    # ═══════════════════════════════════════════
    # 账户查询
    # ═══════════════════════════════════════════

    def get_account_summary(self) -> dict:
        """账户总览"""
        return {
            "account_id": self.account.account_id,
            "initial_cash": self.account.initial_cash,
            "available_cash": round(self.account.available_cash, 2),
            "frozen_cash": round(self.account.frozen_cash, 2),
            "total_cash": round(self.account.cash, 2),
            "position_value": round(self.account.position_value, 2),
            "total_equity": round(self.account.total_equity, 2),
            "realized_pnl": round(self.account.realized_pnl, 2),
            "unrealized_pnl": round(
                sum(p.unrealized_pnl for p in self.account.positions.values()), 2
            ),
            "total_pnl": round(self.account.total_pnl, 2),
            "return_pct": round(self.account.return_pct, 2),
            "position_count": len(self.account.positions),
            "pending_orders": sum(1 for o in self.account.pending_orders if o.status == "pending"),
        }

    def get_positions(self) -> list[dict]:
        """持仓列表"""
        return [p.to_dict() for p in self.account.positions.values()]

    def get_order_history(self, limit: int = 100) -> list[dict]:
        """历史委托(最近 N 条)"""
        return [o.to_dict() for o in self.account.order_history[-limit:]]

    def get_pending_orders(self) -> list[dict]:
        """待成交委托"""
        return [o.to_dict() for o in self.account.pending_orders]

    # ═══════════════════════════════════════════
    # 每日快照
    # ═══════════════════════════════════════════

    def snapshot(self, date_str: str) -> dict:
        """生成每日快照，追加到内存 snapshots 列表"""
        snap = {
            "date": date_str,
            "total_equity": round(self.account.total_equity, 2),
            "available_cash": round(self.account.available_cash, 2),
            "frozen_cash": round(self.account.frozen_cash, 2),
            "position_value": round(self.account.position_value, 2),
            "realized_pnl": round(self.account.realized_pnl, 2),
            "total_pnl": round(self.account.total_pnl, 2),
            "return_pct": round(self.account.return_pct, 2),
            "position_count": len(self.account.positions),
            "positions": self.get_positions(),
        }
        self.account.snapshots.append(snap)
        return snap

    def save_snapshots(self, filepath: str | None = None):
        """持久化快照到 JSON 文件"""
        if filepath is None:
            filepath = os.path.join(self._data_dir, "paper_trading_snapshots.json")

        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(self.account.snapshots, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, filepath)

    # ═══════════════════════════════════════════
    # 状态持久化
    # ═══════════════════════════════════════════

    def save_state(self, filepath: str):
        """保存完整引擎状态到 JSON"""
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

        state = {
            "account": {
                "account_id": self.account.account_id,
                "initial_cash": self.account.initial_cash,
                "available_cash": self.account.available_cash,
                "frozen_cash": self.account.frozen_cash,
                "realized_pnl": self.account.realized_pnl,
                "positions": {
                    sym: p.to_dict() for sym, p in self.account.positions.items()
                },
                "order_history": [o.to_dict() for o in self.account.order_history],
                "snapshots": self.account.snapshots,
            },
            "pending_orders": [o.to_dict() for o in self.account.pending_orders],
            "prev_close": self._prev_close,
            "order_counter": self._order_counter,
        }

        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, filepath)

    def load_state(self, filepath: str):
        """从 JSON 恢复引擎状态"""
        with open(filepath, encoding="utf-8") as f:
            state = json.load(f)

        acct = state["account"]
        self.account.account_id = acct["account_id"]
        self.account.initial_cash = acct["initial_cash"]
        self.account.available_cash = acct["available_cash"]
        self.account.frozen_cash = acct.get("frozen_cash", 0)
        self.account.realized_pnl = acct.get("realized_pnl", 0)

        # 恢复持仓
        self.account.positions = {}
        for sym, pd in acct.get("positions", {}).items():
            self.account.positions[sym] = Position(
                symbol=pd["symbol"],
                name=pd.get("name", sym),
                total_quantity=pd["total_quantity"],
                available_quantity=pd["available_quantity"],
                frozen_quantity=pd["frozen_quantity"],
                cost_price=pd["cost_price"],
                current_price=pd["current_price"],
                buy_date=pd.get("buy_date", ""),
                peak_price=pd.get("peak_price", 0),
                entry_score=pd.get("entry_score", 0),
            )

        # 恢复委托
        self.account.order_history = []
        for od in acct.get("order_history", []):
            self.account.order_history.append(self._dict_to_order(od))

        self.account.pending_orders = []
        for od in state.get("pending_orders", []):
            self.account.pending_orders.append(self._dict_to_order(od))

        self.account.snapshots = acct.get("snapshots", [])
        self._prev_close = state.get("prev_close", {})
        self._order_counter = state.get("order_counter", 0)

    def _dict_to_order(self, od: dict) -> Order:
        return Order(
            order_id=od["order_id"],
            symbol=od["symbol"],
            direction=od["direction"],
            order_type=od.get("order_type", "market"),
            price=od.get("price", 0),
            quantity=od.get("quantity", 0),
            filled_quantity=od.get("filled_quantity", 0),
            filled_price=od.get("filled_price", 0),
            status=od.get("status", "pending"),
            commission=od.get("commission", 0),
            stamp_tax=od.get("stamp_tax", 0),
            transfer_fee=od.get("transfer_fee", 0),
            slippage_cost=od.get("slippage_cost", 0),
            reason=od.get("reason", ""),
            reject_reason=od.get("reject_reason", ""),
            created_at=od.get("created_at", ""),
            filled_at=od.get("filled_at", ""),
        )

    # ═══════════════════════════════════════════
    # 快捷: 完整一日流程
    # ═══════════════════════════════════════════

    def daily_open(self, today_str: str):
        """每日开市: T+1 解锁"""
        unlock_t1_positions(self.account, today_str)

    def daily_close(self, today_str: str, save_snapshots: bool = True):
        """每日收市: 快照 + 持久化"""
        snap = self.snapshot(today_str)
        if save_snapshots:
            self.save_snapshots()
        return snap
