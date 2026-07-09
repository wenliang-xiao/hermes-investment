"""
三策略交易引擎 v2 — 策略纯函数薄封装
======================================
已重构: daily_step() 委托给 strategies/(纯函数)。
回退方案: 移除 __init__.py 注释第7-8行可恢复旧版 inline 逻辑。
"""
import sys, os, json, math
from datetime import datetime, date, timedelta
import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)

from data.data_layer import get_stock_daily
from domain import WATCHLIST
from config import FACTOR_WEIGHTS
from strategies.base import PositionData, FacejiConfig, SilverQuantConfig, TradingAgentsConfig
from engine.cost_model import calc_adjusted_price
from strategies import faceji as _faceji_pure, silverquant as _sq_pure, tradingagents as _ta_pure
from utils.atomic_io import atomic_write_json
import functools
print = functools.partial(print, flush=True)

# ═══════════════════════════════════════════
# 交易纪律常量
# ═══════════════════════════════════════════
MAX_TRADES_PER_WEEK_PER_STRATEGY = 1
MAX_TRADES_PER_WEEK_TOTAL = 3
TRADE_COOLDOWN_DAYS = 1  # 同一标的买卖后冷却天数

# ═══════════════════════════════════════════
# 信号记录
# ═══════════════════════════════════════════
class Signal:
    """交易信号"""
    def __init__(self, strategy, action, symbol, name, price, reason, priority="MED",
                 size_pct=None, pnl_pct=None, score=None):
        self.strategy = strategy
        self.action = action        # "BUY" or "SELL"
        self.symbol = symbol
        self.name = name
        self.price = price
        self.reason = reason
        self.priority = priority    # HIGH / MED / LOW
        self.size_pct = size_pct    # 建议仓位%（仅BUY）
        self.pnl_pct = pnl_pct     # 浮动盈亏%（仅SELL）
        self.score = score

    def to_dict(self):
        return {
            "strategy": self.strategy,
            "action": self.action,
            "symbol": self.symbol,
            "name": self.name,
            "price": round(self.price, 2) if self.price else 0,
            "reason": self.reason,
            "priority": self.priority,
            "size_pct": self.size_pct,
            "pnl_pct": round(self.pnl_pct, 2) if self.pnl_pct else None,
            "score": round(self.score, 1) if self.score else None,
        }


# ═══════════════════════════════════════════
# 周频规则检查器
# ═══════════════════════════════════════════
class TradeCalendar:
    """交易日历 + 周频规则检查"""
    def __init__(self):
        self.trade_log_path = os.path.join(_PROJECT_DIR, "data", "trade_log.json")
        self._load()

    def _load(self):
        if os.path.exists(self.trade_log_path):
            with open(self.trade_log_path) as f:
                self.log = json.load(f)
        else:
            self.log = {"trades": [], "week_count": {}, "cooldowns": {}}

    def _save(self):
        os.makedirs(os.path.dirname(self.trade_log_path), exist_ok=True)
        atomic_write_json(self.trade_log_path, self.log)

    def current_week(self):
        return date.today().isocalendar()[1]

    def current_year(self):
        return date.today().year

    def week_key(self):
        return f"{self.current_year()}-W{self.current_week():02d}"

    def can_trade(self, strategy_name, symbol=None):
        """检查是否可以交易"""
        wk = self.week_key()

        # 策略级周频检查
        strat_count = self.log.get("week_count", {}).get(wk, {}).get(strategy_name, 0)
        if strat_count >= MAX_TRADES_PER_WEEK_PER_STRATEGY:
            return False, f"{strategy_name}本周已交易{strat_count}次，达到上限"

        # 总周频检查
        total = sum(self.log.get("week_count", {}).get(wk, {}).values())
        if total >= MAX_TRADES_PER_WEEK_TOTAL:
            return False, f"所有策略本周合计已交易{total}次，达到上限"

        # 标的冷却检查
        if symbol:
            cooldowns = self.log.get("cooldowns", {})
            if symbol in cooldowns:
                last_trade_date = datetime.strptime(cooldowns[symbol], "%Y-%m-%d")
                if (datetime.now() - last_trade_date).days < TRADE_COOLDOWN_DAYS:
                    return False, f"{symbol}在冷却期内(最后交易{cooldowns[symbol]})"

        return True, "ok"

    def record_trade(self, strategy_name, signal_dict):
        """记录已执行的交易"""
        wk = self.week_key()
        if wk not in self.log["week_count"]:
            self.log["week_count"][wk] = {}
        self.log["week_count"][wk][strategy_name] = \
            self.log["week_count"][wk].get(strategy_name, 0) + 1

        # 冷却
        sym = signal_dict.get("symbol", "")
        if sym:
            self.log["cooldowns"][sym] = date.today().strftime("%Y-%m-%d")

        # 记录
        entry = signal_dict.copy()
        entry["recorded_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        entry["executed"] = False
        self.log["trades"].append(entry)
        self._save()

    def get_trades_this_week(self):
        wk = self.week_key()
        return [t for t in self.log.get("trades", [])
                if t.get("recorded_at", "").startswith(date.today().strftime("%Y-%m"))]

    def is_black_swan(self, macro_data=None):
        """黑天鹅检测（简化版：单日大跌检测）"""
        if macro_data and macro_data.get("market_crash", False):
            return True
        return False


# ═══════════════════════════════════════════
# 策略基类
# ═══════════════════════════════════════════
class BaseStrategy:
    def __init__(self, name, capital=1000000):
        self.name = name
        self.capital = capital
        self.cash = capital
        self.positions = {}  # symbol -> {entry_price, quantity, entry_date, current_price}
        self.history = []
        self.signals = []    # 本轮生成的信号

    def reset(self):
        self.cash = self.capital
        self.positions = {}
        self.history = []
        self.signals = []

    def load_state(self, state_dict):
        """从持久化状态恢复"""
        self.cash = state_dict.get("cash", self.capital)
        self.positions = state_dict.get("positions", {})
        self.history = state_dict.get("history", [])

    def current_value(self):
        """计算当前总资产 = 现金 + 持仓市值"""
        total = self.cash
        for pos in self.positions.values():
            price = pos.get("current_price", pos.get("entry_price", 0))
            qty = pos.get("quantity", 0)
            total += price * qty
        return total

    def save_state(self):
        return {
            "cash": self.cash,
            "positions": self.positions,
            "history": self.history[-100:]  # 只保留最近100条
        }

    def execute_buy(self, signal):
        """通用买入执行（各策略可覆盖）— 含滑点+手续费成本模型"""
        sym = signal.symbol
        price = signal.price
        if not price or price <= 0:
            print(f"  ⚠️ 跳过 buy({sym}): price={price} 无效", flush=True)
            return False
        pct = signal.size_pct or 3.0
        qty = max(100, int(self.cash * pct / 100 / price / 100) * 100)
        adj_price, cost_detail = calc_adjusted_price(price, qty, "buy", sym)
        total_cost = adj_price * qty
        if total_cost > self.cash:
            return False
        self.cash -= total_cost
        self.positions[sym] = {
            "entry_price": adj_price, "quantity": qty,
            "entry_date": date.today().strftime("%Y-%m-%d"),
            "peak": adj_price, "current_price": adj_price,
            "entry_score": getattr(signal, "score", None),
            "reason": signal.reason,
        }
        self.history.append({"date": str(date.today()), "symbol": sym,
                             "action": "买入", "price": adj_price, "cost": round(total_cost, 2),
                             "reason": signal.reason,
                             "score": getattr(signal, "score", None)})
        return True

    def execute_sell(self, signal):
        """通用卖出执行（各策略可覆盖）— 含滑点+印花税成本模型"""
        sym = signal.symbol
        if sym not in self.positions:
            return False
        if not signal.price or signal.price <= 0:
            print(f"  ⚠️ 跳过 sell({sym}): price={signal.price} 无效", flush=True)
            return False
        pos = self.positions[sym]
        price = signal.price
        adj_price, cost_detail = calc_adjusted_price(price, pos["quantity"], "sell", sym)
        pnl = (adj_price - pos["entry_price"]) * pos["quantity"]
        self.cash += adj_price * pos["quantity"]
        self.history.append({"date": str(date.today()), "symbol": sym,
                             "action": "卖出", "price": adj_price,
                             "pnl": round(pnl, 2), "reason": signal.reason,
                             "entry_price": pos["entry_price"],
                             "entry_date": pos.get("entry_date", ""),
                             "hold_days": (date.today() - datetime.strptime(pos.get("entry_date", str(date.today())), "%Y-%m-%d").date()).days if pos.get("entry_date") else 0})
        del self.positions[sym]
        return True


# ═══════════════════════════════════════════
# 策略1: faceji — 委托 strategies/faceji.py 纯函数
# ═══════════════════════════════════════════
class FacejiStrategy(BaseStrategy):
    def __init__(self, capital=1000000, config=None):
        super().__init__("faceji", capital)
        self.config = config or FacejiConfig()

    def _positions_to_pd(self) -> dict[str, PositionData]:
        return {
            sym: PositionData(
                symbol=sym,
                entry_price=pos["entry_price"],
                quantity=pos["quantity"],
                entry_date=pos.get("entry_date", ""),
                peak=pos.get("peak"),
                current_price=pos.get("current_price"),
            )
            for sym, pos in self.positions.items()
        }

    def daily_step(self, date_str, score_map, tech_map, price_map):
        """委托 strategies/faceji.decide() 纯函数"""
        self.signals = []
        positions = self._positions_to_pd()
        pure_signals = _faceji_pure.decide(
            score_map, tech_map, price_map,
            positions, self.cash, self.config
        )
        for s in pure_signals:
            name = self._get_name(s.symbol)
            self.signals.append(Signal(
                strategy="faceji", action=s.action, symbol=s.symbol,
                name=name, price=s.price, reason=s.reason,
                priority=s.priority, size_pct=s.size_pct,
                pnl_pct=s.pnl_pct, score=s.score
            ))
        return self.signals

    def _get_name(self, sym):
        info = WATCHLIST.get(sym, {})
        return info.get("name", sym) if isinstance(info, dict) else str(info)


# ═══════════════════════════════════════════
# 策略2: SilverQuant — 委托 strategies/silverquant.py 纯函数
# ═══════════════════════════════════════════
class SilverQuantStrategy(BaseStrategy):
    def __init__(self, capital=1000000, config=None):
        super().__init__("silverquant", capital)
        self.config = config or SilverQuantConfig()

    def _positions_to_pd(self) -> dict[str, PositionData]:
        return {
            sym: PositionData(
                symbol=sym,
                entry_price=pos["entry_price"],
                quantity=pos["quantity"],
                entry_date=pos.get("entry_date", ""),
                peak=pos.get("peak"),
                current_price=pos.get("current_price"),
            )
            for sym, pos in self.positions.items()
        }

    def daily_step(self, date_str, score_map, tech_map, price_map):
        """委托 strategies/silverquant.decide() 纯函数"""
        self.signals = []
        positions = self._positions_to_pd()
        pure_signals = _sq_pure.decide(
            score_map, tech_map, price_map,
            positions, self.cash, self.config
        )
        for s in pure_signals:
            name = self._get_name(s.symbol)
            self.signals.append(Signal(
                strategy="silverquant", action=s.action, symbol=s.symbol,
                name=name, price=s.price, reason=s.reason,
                priority=s.priority, size_pct=s.size_pct,
                pnl_pct=s.pnl_pct, score=s.score
            ))
        return self.signals

    def _get_name(self, sym):
        info = WATCHLIST.get(sym, {})
        return info.get("name", sym) if isinstance(info, dict) else str(info)


# ═══════════════════════════════════════════
# 策略3: TradingAgents — 委托 strategies/tradingagents.py 纯函数
# ═══════════════════════════════════════════
class TradingAgentsStrategy(BaseStrategy):
    def __init__(self, capital=1000000, config=None):
        super().__init__("tradingagents", capital)
        self.config = config or TradingAgentsConfig()

    def _positions_to_pd(self) -> dict[str, PositionData]:
        return {
            sym: PositionData(
                symbol=sym,
                entry_price=pos["entry_price"],
                quantity=pos["quantity"],
                entry_date=pos.get("entry_date", ""),
                peak=pos.get("peak"),
                current_price=pos.get("current_price"),
            )
            for sym, pos in self.positions.items()
        }

    def daily_step(self, date_str, score_map, tech_map, price_map):
        """委托 strategies/tradingagents.decide() 纯函数"""
        self.signals = []
        positions = self._positions_to_pd()
        pure_signals = _ta_pure.decide(
            score_map, tech_map, price_map,
            positions, self.cash, self.config
        )
        for s in pure_signals:
            name = self._get_name(s.symbol)
            self.signals.append(Signal(
                strategy="tradingagents", action=s.action, symbol=s.symbol,
                name=name, price=s.price, reason=s.reason,
                priority=s.priority, size_pct=s.size_pct,
                pnl_pct=s.pnl_pct, score=s.score
            ))
        return self.signals

    def _get_name(self, sym):
        info = WATCHLIST.get(sym, {})
        return info.get("name", sym) if isinstance(info, dict) else str(info)


# ═══════════════════════════════════════════
# 主调度器
# ═══════════════════════════════════════════
class TradingEngine:
    """
    每日调度器
    1. 加载当前评分 + 价格 + 技术数据
    2. 运行全部3个策略
    3. 合并信号，冲突时按优先级裁决
    4. 应用周频规则过滤
    5. 输出 data/trading_signals.json
    """
    def __init__(self, capital=1000000):
        self.strategies = {
            "faceji": FacejiStrategy(capital),
            "silverquant": SilverQuantStrategy(capital),
            "tradingagents": TradingAgentsStrategy(capital)
        }
        self.calendar = TradeCalendar()
        self.state_path = os.path.join(_PROJECT_DIR, "data", "strategy_states.json")
        self._load_states()

    def _load_states(self):
        """从持久化文件恢复策略状态"""
        if os.path.exists(self.state_path):
            with open(self.state_path) as f:
                states = json.load(f)
            for name, state in states.items():
                if name in self.strategies:
                    self.strategies[name].load_state(state)

    def _save_states(self):
        """保存策略状态"""
        states = {name: s.save_state() for name, s in self.strategies.items()}
        atomic_write_json(self.state_path, states)

    def _check_black_swan(self):
        """检查是否黑天鹅（简单实现：依赖宏观看跌信号）"""
        try:
            from engine.macro_engine import get_macro_status
            macro = get_macro_status()
            if macro.get("market_crash", False):
                return True
        except:
            pass
        return self.calendar.is_black_swan()

    def _resolve_conflicts(self, all_signals):
        """
        信号冲突解决：
        1. 同一标的多策略同时买卖 → 面基优先
        2. 同一标的同一策略同时买卖 → 只取SELL（先卖再买）
        3. 按优先级排序输出
        """
        # 按标的分组
        by_symbol = {}
        for sig in all_signals:
            by_symbol.setdefault(sig.symbol, []).append(sig)

        resolved = []
        for sym, sigs in by_symbol.items():
            buys = [s for s in sigs if s.action == "BUY"]
            sells = [s for s in sigs if s.action == "SELL"]

            if buys and sells:
                # 冲突：选面基的建议
                faceji_sigs = [s for s in sigs if s.strategy == "faceji"]
                if faceji_sigs:
                    resolved.extend(faceji_sigs)
                else:
                    # 无面基信号，取优先级最高的
                    sigs.sort(key=lambda s: {"HIGH": 0, "MED": 1, "LOW": 2}[s.priority])
                    resolved.append(sigs[0])
            elif buys:
                # 只有买入信号：取优先级最高的
                buys.sort(key=lambda s: {"HIGH": 0, "MED": 1, "LOW": 2}[s.priority])
                resolved.append(buys[0])
            elif sells:
                # 只有卖出信号
                sells.sort(key=lambda s: {"HIGH": 0, "MED": 1, "LOW": 2}[s.priority])
                resolved.append(sells[0])

        # 排序：优先级 + 策略
        strat_order = {"faceji": 0, "silverquant": 1, "tradingagents": 2}
        resolved.sort(key=lambda s: (
            {"HIGH": 0, "MED": 1, "LOW": 2}[s.priority],
            strat_order.get(s.strategy, 99)
        ))
        return resolved

    def _filter_by_weekly_rule(self, resolved_signals):
        """应用周频规则"""
        black_swan = self._check_black_swan()
        if black_swan:
            return resolved_signals  # 黑天鹅豁免

        filtered = []
        for sig in resolved_signals:
            ok, msg = self.calendar.can_trade(sig.strategy, sig.symbol)
            if ok:
                filtered.append(sig)
            else:
                print(f"  📋 周频过滤: [{sig.strategy}] {sig.action} {sig.symbol} - {msg}", flush=True)
        return filtered

    def run_daily(self, date_str, score_map, tech_map, price_map, save=True):
        """每日运行全部策略"""
        print(f"\n{'='*50}", flush=True)
        print(f"🏃 TradingEngine 运行: {date_str}", flush=True)
        print(f"{'='*50}", flush=True)

        all_signals = []
        for name, strategy in self.strategies.items():
            sigs = strategy.daily_step(date_str, score_map, tech_map, price_map)
            print(f"\n  📊 {name}: {len(sigs)} 个信号", flush=True)
            for s in sigs:
                print(f"    [{s.priority}] {s.action} {s.symbol}({s.name}) @{s.price:.2f} - {s.reason}", flush=True)
            all_signals.extend(sigs)

        # === 自动执行模拟盘（每个策略独立执行自己的信号） ===
        print(f"\n  🖥️ 自动执行模拟盘...", flush=True)
        sim_trades = 0
        for name, strategy in self.strategies.items():
            strategy_sigs = [s for s in all_signals if s.strategy == name]
            for sig in strategy_sigs:
                if sig.action == "BUY":
                    # 周频检查: BUY信号受每周交易次数限制
                    ok, msg = self.calendar.can_trade(sig.strategy, sig.symbol)
                    if not ok:
                        print(f"  📋 模拟盘跳过(周频限制): [{sig.strategy}] BUY {sig.symbol} - {msg}", flush=True)
                        continue
                    ok = strategy.execute_buy(sig)
                    if ok:
                        self.calendar.record_trade(sig.strategy, sig.to_dict())
                elif sig.action == "SELL":
                    # SELL 不受 can_trade 阻止(止损优先于周频限制)，但需 record_trade 计入周频预算
                    ok = strategy.execute_sell(sig)
                    if ok:
                        self.calendar.record_trade(sig.strategy, sig.to_dict())
                else:
                    continue
                if ok:
                    sim_trades += 1
        print(f"  ✅ 模拟盘执行 {sim_trades} 笔交易", flush=True)

        # 冲突解决（仅用于给用户的建议信号）
        resolved = self._resolve_conflicts(all_signals)
        print(f"\n  🔄 冲突解决后: {len(resolved)} 个建议信号", flush=True)

        # 周频过滤（仅用于给用户的建议信号）
        final = self._filter_by_weekly_rule(resolved)
        print(f"\n  📋 周频过滤后: {len(final)} 个最终建议", flush=True)

        output = {
            "date": date_str,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategies_run": list(self.strategies.keys()),
            "total_raw_signals": len(all_signals),
            "after_conflict_resolution": len(resolved),
            "after_weekly_filter": len(final),
            "signals": [s.to_dict() for s in final],
            "all_signals": [s.to_dict() for s in all_signals],
            "simulated_trades": sim_trades,
            "positions": {
                name: {
                    sym: self._build_position_detail(sym, pos, strategy, score_map, price_map)
                    for sym, pos in strategy.positions.items()
                }
                for name, strategy in self.strategies.items()
            },
            "portfolios": {
                name: self._build_portfolio_detail(strategy, score_map, price_map)
                for name, strategy in self.strategies.items()
            },
            "trade_history": {
                name: strategy.history[-50:]
                for name, strategy in self.strategies.items()
            },
        }

        if save:
            out_path = os.path.join(_PROJECT_DIR, "data", "trading_signals.json")
            atomic_write_json(out_path, output)
            self._save_states()
            print(f"\n  💾 信号+模拟盘已保存: {out_path}", flush=True)

        return output

    def _build_position_detail(self, sym, pos, strategy, score_map, price_map):
        """构建单持仓的完整详情"""
        entry_price = pos["entry_price"]
        current_price = pos.get("current_price", entry_price)
        quantity = pos["quantity"]
        peak = pos.get("peak", entry_price)
        cost = entry_price * quantity
        market_value = current_price * quantity
        pnl = (current_price - entry_price) * quantity
        pnl_pct = (current_price - entry_price) / entry_price * 100 if entry_price else 0
        dd_from_peak = (current_price - peak) / peak * 100 if peak else 0
        dd_from_entry = (current_price - entry_price) / entry_price * 100 if entry_price else 0
        total_value = strategy.current_value()
        pct = market_value / total_value * 100 if total_value else 0
        entry_date = pos.get("entry_date", "")
        hold_days = 0
        if entry_date:
            try:
                hold_days = (date.today() - datetime.strptime(entry_date, "%Y-%m-%d").date()).days
            except Exception:
                pass
        entry_score = pos.get("entry_score")
        current_score = score_map.get(sym, 0)
        name = strategy._get_name(sym) if hasattr(strategy, "_get_name") else sym
        return {
            "symbol": sym,
            "name": name,
            "entry_price": round(entry_price, 4),
            "current_price": round(current_price, 4),
            "quantity": quantity,
            "cost": round(cost, 2),
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "peak_price": round(peak, 4),
            "drawdown_from_peak": round(dd_from_peak, 2),
            "drawdown_from_entry": round(dd_from_entry, 2),
            "pct": round(pct, 2),
            "entry_date": entry_date,
            "entry_score": entry_score,
            "current_score": round(current_score, 2) if isinstance(current_score, (int, float)) else current_score,
            "hold_days": hold_days,
            "reason": pos.get("reason", ""),
            "stop_loss": round(entry_price * 0.92, 4),
            "strategy": strategy.name,
        }

    def _build_portfolio_detail(self, strategy, score_map, price_map):
        """构建策略组合的完整详情"""
        total_value = strategy.current_value()
        total_invested = sum(pos["entry_price"] * pos["quantity"] for pos in strategy.positions.values())
        total_pnl = total_value - strategy.capital
        total_return = total_pnl / strategy.capital * 100 if strategy.capital else 0
        win_trades = [h for h in strategy.history if h.get("action") == "卖出" and h.get("pnl", 0) > 0]
        lose_trades = [h for h in strategy.history if h.get("action") == "卖出" and h.get("pnl", 0) <= 0]
        win_rate = len(win_trades) / max(1, len(win_trades) + len(lose_trades)) * 100
        return {
            "label": strategy.name,
            "cash": round(strategy.cash, 2),
            "capital": strategy.capital,
            "total_value": round(total_value, 2),
            "total_invested": round(total_invested, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": len(strategy.positions),
            "history_count": len(strategy.history),
            "cash_pct": round((strategy.cash / total_value) * 100, 2) if total_value else 0,
            "invested_pct": round((total_invested / total_value) * 100, 2) if total_value else 0,
            "win_rate": round(win_rate, 1),
            "win_trades": len(win_trades),
            "lose_trades": len(lose_trades),
        }

    def get_summary_table(self, output):
        """生成日报用的信号摘要表（文本）"""
        signals = output.get("signals", [])
        if not signals:
            return "今日无交易信号"

        lines = []
        lines.append("策略             动作    标的          价格      理由")
        lines.append("─" * 65)
        for s in signals:
            lines.append(f"{s['strategy']:<16s} {s['action']:<4s}   {s['symbol']}({s['name']:<4s})  {s['price']:>8.2f}  {s['reason']}")
        return "\n".join(lines)

    def execute_signal(self, signal_dict):
        """执行一个信号（内部更新策略状态 + 日历记录）"""
        strategy_name = signal_dict["strategy"]
        strategy = self.strategies.get(strategy_name)
        if not strategy:
            return False, f"Unknown strategy: {strategy_name}"

        sig = Signal(
            strategy=signal_dict["strategy"],
            action=signal_dict["action"],
            symbol=signal_dict["symbol"],
            name=signal_dict.get("name", ""),
            price=signal_dict.get("price", 0),
            reason=signal_dict.get("reason", ""),
            size_pct=signal_dict.get("size_pct"),
            pnl_pct=signal_dict.get("pnl_pct"),
            score=signal_dict.get("score"),
        )

        if sig.action == "BUY":
            ok = strategy.execute_buy(sig)
        elif sig.action == "SELL":
            ok = strategy.execute_sell(sig)
        else:
            return False, f"Unknown action: {sig.action}"

        if ok:
            self.calendar.record_trade(strategy_name, signal_dict)
            self._save_states()
            return True, "执行成功"
        return False, "执行失败（现金不足或无持仓）"

# ─── 简易测试 ───
if __name__ == "__main__":
    print("TradingEngine v1 loaded. 测试信号生成...")
    engine = TradingEngine()
    # 测试用模拟数据
    test_scores = {"300502": 5.5, "603259": 6.2, "600519": 7.0}
    test_tech = {s: {"ma20_dev": 2.0, "ma60_dev": 1.0, "rsi": 55,
                     "macd_signal": "🟢金叉", "total_tech_score": 6.0}
                 for s in test_scores}
    test_prices = {"300502": 580.0, "603259": 92.0, "600519": 1500.0}
    result = engine.run_daily("2026-06-24", test_scores, test_tech, test_prices)
    print("\n\n📊 信号摘要:")
    print(engine.get_summary_table(result))
