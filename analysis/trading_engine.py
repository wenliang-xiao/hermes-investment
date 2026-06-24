"""
三策略交易引擎 v1 
逐日运行 faceji / SilverQuant / TradingAgents，输出结构化信号
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
        with open(self.trade_log_path, "w") as f:
            json.dump(self.log, f, ensure_ascii=False, indent=2)

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

    def save_state(self):
        return {
            "cash": self.cash,
            "positions": self.positions,
            "history": self.history[-100:]  # 只保留最近100条
        }


# ═══════════════════════════════════════════
# 策略1: faceji（当前系统）
# ═══════════════════════════════════════════
class FacejiStrategy(BaseStrategy):
    def __init__(self, capital=1000000):
        super().__init__("faceji", capital)
        self.entry_threshold = 5.0
        self.exit_threshold = 4.0
        self.max_positions = 8

    def daily_step(self, date_str, score_map, tech_map, price_map):
        """返回信号列表"""
        self.signals = []
        held = set(self.positions.keys())

        # ── 建仓信号（保留面基趋势过滤 + Kelly动态分配）──
        candidates = sorted(
            [s for s in score_map if s not in held],
            key=lambda s: score_map.get(s, 0), reverse=True
        )[:5]

        for sym in candidates:
            if len(self.positions) >= self.max_positions:
                break
            score = score_map.get(sym, 0)
            if score < self.entry_threshold:
                continue
            tech = tech_map.get(sym, {})
            ma20d = tech.get("ma20_dev", 0) or 0
            ma60d = tech.get("ma60_dev", 0) or 0
            if ma60d <= ma20d and score < 5.5:
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            name = self._get_name(sym)

            # Kelly-like sizing
            kelly_pct = self._kelly_size(score)
            qty = max(100, int(self.cash * kelly_pct / 100 / price / 100) * 100)
            cost = price * qty
            if cost > self.cash:
                qty = max(100, int(self.cash / price / 100) * 100)

            self.signals.append(Signal(
                strategy="faceji", action="BUY", symbol=sym, name=name,
                price=price, reason=f"评分{score:.1f}+MA趋势ok",
                priority="HIGH" if score >= 5.5 else "MED",
                size_pct=round(kelly_pct, 1), score=score
            ))

        # ── 清仓信号（融合SilverQuant 4层风控）──
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            score = score_map.get(sym, 0)
            entry = pos["entry_price"]
            peak = pos.get("peak", entry)
            pnl_pct = (price - entry) / entry * 100
            dd = (price - peak) / peak * 100 if peak else 0
            name = self._get_name(sym)

            # 1. HardSeller: -8% 硬止损（SQ继承）
            if pnl_pct <= -8:
                self.signals.append(Signal(
                    strategy="faceji", action="SELL", symbol=sym, name=name,
                    price=price, reason=f"硬止损{pnl_pct:.1f}%",
                    priority="HIGH", pnl_pct=pnl_pct, score=score
                ))
                continue

            # 2. FallSeller: -12% 峰值回落止盈（SQ继承）
            if dd <= -12:
                self.signals.append(Signal(
                    strategy="faceji", action="SELL", symbol=sym, name=name,
                    price=price, reason=f"回落止盈{dd:.1f}%",
                    priority="HIGH", pnl_pct=pnl_pct, score=score
                ))
                continue

            # 3. ScoreDropSeller: 评分<4.5 基本面下滑（SQ收紧版，比原来4.0更早）
            if score < 4.5:
                self.signals.append(Signal(
                    strategy="faceji", action="SELL", symbol=sym, name=name,
                    price=price, reason=f"评分下滑{score:.1f}",
                    priority="MED", pnl_pct=pnl_pct, score=score
                ))
                continue

            # 4. MASeller: MA死叉 + 亏损未超-5%（SQ继承，附加评分条件）
            if score < 5.0:
                tech = tech_map.get(sym, {})
                if (tech.get("ma20_dev", 0) or 0) < (tech.get("ma60_dev", 0) or 0) and pnl_pct > -5:
                    self.signals.append(Signal(
                        strategy="faceji", action="SELL", symbol=sym, name=name,
                        price=price, reason="MA死叉+评分<5",
                        priority="MED", pnl_pct=pnl_pct, score=score
                    ))
        return self.signals

    def _kelly_size(self, score):
        wp = min(score / 10.0, 0.8)
        kelly = max(0, (wp * 2.0 - (1 - wp)) / 2.0) * 0.5
        return min(kelly, 0.08)

    def _get_name(self, sym):
        info = WATCHLIST.get(sym, {})
        return info.get("name", sym) if isinstance(info, dict) else str(info)

    def execute_buy(self, signal):
        """执行买入（内部状态更新）"""
        sym = signal.symbol
        price = signal.price
        pct = signal.size_pct or 3.0
        qty = max(100, int(self.cash * pct / 100 / price / 100) * 100)
        cost = price * qty
        if cost > self.cash:
            return False
        self.cash -= cost
        self.positions[sym] = {
            "entry_price": price, "quantity": qty,
            "entry_date": date.today().strftime("%Y-%m-%d"),
            "peak": price, "current_price": price
        }
        self.history.append({"date": str(date.today()), "symbol": sym,
                             "action": "买入", "price": price, "cost": round(cost, 2),
                             "reason": signal.reason})
        return True

    def execute_sell(self, signal):
        """执行卖出（内部状态更新）"""
        sym = signal.symbol
        if sym not in self.positions:
            return False
        pos = self.positions[sym]
        price = signal.price
        pnl = (price - pos["entry_price"]) * pos["quantity"]
        self.cash += price * pos["quantity"]
        self.history.append({"date": str(date.today()), "symbol": sym,
                             "action": "卖出", "price": price,
                             "pnl": round(pnl, 2), "reason": signal.reason})
        del self.positions[sym]
        return True


# ═══════════════════════════════════════════
# 策略2: SilverQuant 组件化
# ═══════════════════════════════════════════
class SilverQuantStrategy(BaseStrategy):
    def __init__(self, capital=1000000):
        super().__init__("silverquant", capital)
        self.entry_threshold = 5.0
        self.max_positions = 8

    def daily_step(self, date_str, score_map, tech_map, price_map):
        self.signals = []
        held = set(self.positions.keys())
        candidates = sorted(
            [s for s in score_map if s not in held],
            key=lambda s: score_map.get(s, 0), reverse=True
        )[:5]

        for sym in candidates:
            if len(self.positions) >= self.max_positions:
                break
            score = score_map.get(sym, 0)
            if score < self.entry_threshold:
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            name = self._get_name(sym)
            self.signals.append(Signal(
                strategy="silverquant", action="BUY", symbol=sym, name=name,
                price=price, reason=f"槽位建仓(评分{score:.1f})",
                priority="MED", size_pct=3.0, score=score
            ))

        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            entry = pos["entry_price"]
            peak = pos.get("peak", entry)
            pnl_pct = (price - entry) / entry * 100
            dd = (price - peak) / peak * 100 if peak else 0
            name = self._get_name(sym)

            # HardSeller: -8%
            if pnl_pct <= -8:
                self.signals.append(Signal(
                    strategy="silverquant", action="SELL", symbol=sym, name=name,
                    price=price, reason="HardSeller(-8%)", priority="HIGH",
                    pnl_pct=pnl_pct, score=score_map.get(sym, 0)
                ))
                continue

            # FallSeller: -12%
            if dd <= -12:
                self.signals.append(Signal(
                    strategy="silverquant", action="SELL", symbol=sym, name=name,
                    price=price, reason=f"FallSeller({dd:.1f}%)", priority="HIGH",
                    pnl_pct=pnl_pct, score=score_map.get(sym, 0)
                ))
                continue

            # MASeller: 死叉
            tech = tech_map.get(sym, {})
            if (tech.get("ma20_dev", 0) or 0) < (tech.get("ma60_dev", 0) or 0) and pnl_pct > -5:
                self.signals.append(Signal(
                    strategy="silverquant", action="SELL", symbol=sym, name=name,
                    price=price, reason="MASeller(MA死叉)", priority="MED",
                    pnl_pct=pnl_pct, score=score_map.get(sym, 0)
                ))
                continue

            # ScoreDrop: <4.5
            if score_map.get(sym, 10) < 4.5:
                self.signals.append(Signal(
                    strategy="silverquant", action="SELL", symbol=sym, name=name,
                    price=price, reason=f"ScoreDrop({score_map[sym]:.1f})", priority="MED",
                    pnl_pct=pnl_pct, score=score_map.get(sym, 0)
                ))
        return self.signals

    def _get_name(self, sym):
        info = WATCHLIST.get(sym, {})
        return info.get("name", sym) if isinstance(info, dict) else str(info)

    def execute_buy(self, signal):
        sym = signal.symbol; price = signal.price
        qty = max(100, int(30000 / price / 100) * 100)
        cost = price * qty
        if cost > self.cash:
            qty = max(100, int(self.cash / price / 100) * 100)
            cost = price * qty
            if cost > self.cash: return False
        self.cash -= cost
        self.positions[sym] = {"entry_price": price, "quantity": qty,
            "entry_date": str(date.today()), "peak": price, "current_price": price}
        self.history.append({"date": str(date.today()), "symbol": sym,
            "action": "买入", "price": price, "cost": round(cost, 2), "reason": signal.reason})
        return True

    def execute_sell(self, signal):
        sym = signal.symbol
        if sym not in self.positions: return False
        pos = self.positions[sym]
        price = signal.price
        pnl = (price - pos["entry_price"]) * pos["quantity"]
        self.cash += price * pos["quantity"]
        self.history.append({"date": str(date.today()), "symbol": sym,
            "action": "卖出", "price": price, "pnl": round(pnl, 2), "reason": signal.reason})
        del self.positions[sym]
        return True


# ═══════════════════════════════════════════
# 策略3: TradingAgents 辩论制
# ═══════════════════════════════════════════
class TradingAgentsStrategy(BaseStrategy):
    def __init__(self, capital=1000000):
        super().__init__("tradingagents", capital)
        self.max_positions = 6

    def _debate_score(self, score, tech):
        sc = score or 5.0
        ts = tech.get("total_tech_score", 5.0) if tech else 5.0
        bull = sc * 0.5 + ts * 0.5
        bp = 0
        if tech and tech.get("macd_signal", "") == "🔴死叉": bp += 1.0
        if tech and (tech.get("rsi", 50) or 50) > 70: bp += 0.5
        bear = sc - bp; neut = sc
        if bull >= bear and bull >= neut: final = bull * 0.6 + neut * 0.3 + bear * 0.1
        elif bear >= bull and bear >= neut: final = bear * 0.5 + neut * 0.3 + bull * 0.2
        else: final = neut
        return min(10, max(0, final))

    def daily_step(self, date_str, score_map, tech_map, price_map):
        self.signals = []
        held = set(self.positions.keys())
        debate = {sym: {"score": sm.get(sym, 5.0) if (sm := score_map) else 5.0,
                        "debate_score": self._debate_score(score_map.get(sym, 5.0), tech_map.get(sym, {}))}
                  for sym in score_map}

        candidates = sorted(
            [(s, d["debate_score"]) for s, d in debate.items() if s not in held],
            key=lambda x: x[1], reverse=True
        )[:3]

        for sym, ds in candidates:
            if len(self.positions) >= self.max_positions:
                break
            if ds < 5.5:
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            name = self._get_name(sym)

            # Kelly
            wp = min(ds / 10.0, 0.8)
            kelly = max(0, (wp * 1.8 - (1 - wp)) / 1.8) * 0.5
            size_pct = min(kelly, 0.12) * 100

            self.signals.append(Signal(
                strategy="tradingagents", action="BUY", symbol=sym, name=name,
                price=price, reason=f"辩论分{ds:.1f}(bull优先)",
                priority="HIGH" if ds >= 6.0 else "MED",
                size_pct=round(size_pct, 1), score=round(ds, 1)
            ))

        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            ds = debate.get(sym, {}).get("debate_score", 5.0)
            entry = pos["entry_price"]
            pnl_pct = (price - entry) / entry * 100
            name = self._get_name(sym)

            if ds < 4.0:
                reason = f"辩论分{ds:.1f}<4"
                priority = "HIGH"
            elif (price - entry) / entry * 100 <= -8:
                reason = f"止损{((price-entry)/entry*100):.1f}%"
                priority = "HIGH"
            elif ds < 5.0 and pnl_pct < 0:
                reason = f"辩论分{ds:.1f}+亏损"
                priority = "MED"
            else:
                continue

            self.signals.append(Signal(
                strategy="tradingagents", action="SELL", symbol=sym, name=name,
                price=price, reason=reason, priority=priority,
                pnl_pct=pnl_pct, score=round(ds, 1)
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
        with open(self.state_path, "w") as f:
            json.dump(states, f, ensure_ascii=False, indent=2)

    def _check_black_swan(self):
        """检查是否黑天鹅（简单实现：依赖宏观看跌信号）"""
        try:
            from analysis.macro_engine import get_macro_status
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

        # 冲突解决
        resolved = self._resolve_conflicts(all_signals)
        print(f"\n  🔄 冲突解决后: {len(resolved)} 个信号", flush=True)

        # 周频过滤
        final = self._filter_by_weekly_rule(resolved)
        print(f"\n  📋 周频过滤后: {len(final)} 个最终信号", flush=True)

        output = {
            "date": date_str,
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategies_run": list(self.strategies.keys()),
            "total_raw_signals": len(all_signals),
            "after_conflict_resolution": len(resolved),
            "after_weekly_filter": len(final),
            "signals": [s.to_dict() for s in final],
            "positions": {
                name: {sym: {"entry_price": pos["entry_price"],
                             "current_price": pos.get("current_price", pos["entry_price"]),
                             "quantity": pos["quantity"],
                             "pnl_pct": round((pos.get("current_price", pos["entry_price"]) - pos["entry_price"]) / pos["entry_price"] * 100, 2)}
                        for sym, pos in strategy.positions.items()}
                for name, strategy in self.strategies.items()
            }
        }

        if save:
            out_path = os.path.join(_PROJECT_DIR, "data", "trading_signals.json")
            with open(out_path, "w") as f:
                json.dump(output, f, ensure_ascii=False, indent=2, default=str)
            self._save_states()
            print(f"\n  💾 信号已保存: {out_path}", flush=True)

        return output

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
