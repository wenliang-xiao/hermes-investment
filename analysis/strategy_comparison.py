"""
三方策略对比引擎
faceji (ours) vs silverquant-inspired vs tradingagents-inspired

对所有策略使用同一套数据输入（面基WATCHLIST + 六因子评分），
只在交易执行（建仓/清仓/风控）环节体现风格差异。
"""
import json, os, sys
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 公共数据层 ───
def load_score_history(days=7):
    """加载最近N天的扫描结果快照"""
    snapshots = []
    for d in range(days, 0, -1):
        date = (datetime.now() - timedelta(days=d)).strftime("%Y-%m-%d")
        path = os.path.join(ROOT, "data", f"scan_snapshot_{date}.json")
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
                snapshots.append({"date": date, "results": data.get("results", data)})
            except:
                pass
    return snapshots

def load_shadow_history():
    """加载模拟盘历史"""
    path = os.path.join(ROOT, "data", "shadow_account.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"capital": 1000000, "cash": 1000000, "positions": {}, "history": [], "realized_pnl": 0}

def get_watchlist():
    """获取当前WATCHLIST"""
    try:
        sys.path.insert(0, os.path.join(ROOT, ".."))
        from investment_system.domain import WATCHLIST
        # Filter A-share stocks
        a_stocks = []
        for code, info in WATCHLIST.items():
            sym = str(code)
            if sym.isdigit() and (sym.startswith("0") or sym.startswith("3") or sym.startswith("6")):
                a_stocks.append({"symbol": sym, "name": info.get("name", sym), "tier": info.get("tier", "")})
        return a_stocks
    except:
        return []

# ─── 策略状态机 ───
class BaseStrategy:
    """策略基类"""
    def __init__(self, name, capital=1000000):
        self.name = name
        self.capital = capital
        self.cash = capital
        self.positions = {}  # symbol -> {entry_price, quantity, entry_date, peak}
        self.history = []
        self.daily_values = []
    
    def reset(self, capital=1000000):
        self.cash = capital
        self.positions = {}
        self.history = []
        self.daily_values = []
    
    def current_value(self):
        pos_value = sum(p["quantity"] * p.get("current_price", p["entry_price"]) for p in self.positions.values())
        return self.cash + pos_value
    
    def record_value(self, date):
        self.daily_values.append({"date": date, "value": round(self.current_value(), 2)})
    
    def get_summary(self):
        realized_pnl = sum(h.get("pnl", 0) for h in self.history if h.get("action") == "卖出")
        pos_pnl = sum(
            (p.get("current_price", p["entry_price"]) - p["entry_price"]) * p["quantity"]
            for p in self.positions.values()
        )
        total_pnl = realized_pnl + pos_pnl
        value = self.current_value()
        returns = (value - self.capital) / self.capital * 100 if self.capital else 0
        
        trades = len([h for h in self.history if h.get("action") == "买入"])
        wins = len([h for h in self.history if h.get("action") == "卖出" and h.get("pnl", 0) > 0])
        losses = len([h for h in self.history if h.get("action") == "卖出" and h.get("pnl", 0) <= 0])
        closed_trades = wins + losses
        
        # Calculate max drawdown
        peak = self.capital
        max_dd = 0
        for entry in self.daily_values:
            peak = max(peak, entry["value"])
            dd = (entry["value"] - peak) / peak * 100
            max_dd = min(max_dd, dd)
        
        return {
            "name": self.name,
            "value": round(value, 2),
            "cash": round(self.cash, 2),
            "positions": len(self.positions),
            "total_return_pct": round(returns, 2),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(pos_pnl, 2),
            "total_trades": closed_trades,
            "win_rate": round(wins/closed_trades*100, 1) if closed_trades > 0 else 0,
            "max_drawdown_pct": round(abs(max_dd), 2),
            "daily_values": self.daily_values[-30:] if self.daily_values else [],
            "trades": self.history[-20:] if self.history else []
        }


# ═══════════════════════════════════════════
# 策略1: faceji (当前系统逻辑)
# ═══════════════════════════════════════════
class FacejiStrategy(BaseStrategy):
    """当前面基策略：评分驱动"""
    def __init__(self, capital=1000000):
        super().__init__("faceji (面基)", capital)
        self.entry_threshold = 5.0
        self.exit_threshold = 4.0
        self.max_positions = 8
    
    def daily_step(self, date, score_map, tech_map, price_map):
        """每日决策"""
        # 建仓：TOP5中非持仓+评分>=5.0+趋势ok
        held = set(self.positions.keys())
        candidates = sorted(
            [s for s in score_map if s not in held],
            key=lambda s: score_map.get(s, 0), reverse=True
        )[:5]
        
        for sym in candidates:
            score = score_map.get(sym, 0)
            if len(self.positions) >= self.max_positions:
                break
            if score < self.entry_threshold:
                continue
            # Trend check
            tech = tech_map.get(sym, {})
            ma20d = tech.get("ma20_dev", 0) or 0
            ma60d = tech.get("ma60_dev", 0) or 0
            if ma60d <= ma20d and score < 5.5:
                continue
            # Entry
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            qty = max(100, int(30000 / price))
            cost = price * qty
            if cost > self.cash:
                qty = max(100, int(self.cash / price / 100) * 100)
                cost = price * qty
                if cost > self.cash:
                    continue
            self.cash -= cost
            self.positions[sym] = {
                "entry_price": price, "quantity": qty,
                "entry_date": date, "peak": price,
                "current_price": price
            }
            self.history.append({"date": date, "symbol": sym, "action": "买入",
                                 "price": price, "quantity": qty, "cost": cost})
        
        # Update prices & check exits
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price
            pos["peak"] = max(pos["peak"], price)
            
            score = score_map.get(sym, 0)
            # Exit: score < 4
            if score is not None and score < self.exit_threshold:
                pnl = (price - pos["entry_price"]) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": f"评分{score:.1f}<{self.exit_threshold}"})
                del self.positions[sym]
                continue
            
            # Exit: score < 5 + trend death
            if score is not None and score < 5.0:
                tech = tech_map.get(sym, {})
                ma20d = tech.get("ma20_dev", 0) or 0
                ma60d = tech.get("ma60_dev", 0) or 0
                if ma20d < ma60d:  # MA死叉
                    pnl = (price - pos["entry_price"]) * pos["quantity"]
                    self.cash += price * pos["quantity"]
                    self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                         "price": price, "pnl": round(pnl, 2),
                                         "reason": "MA死叉"})
                    del self.positions[sym]
        
        self.record_value(date)


# ═══════════════════════════════════════════
# 策略2: SilverQuant-inspired
# ═══════════════════════════════════════════
class SilverQuantStrategy(BaseStrategy):
    """SilverQuant风格：组件化卖点"""
    def __init__(self, capital=1000000):
        super().__init__("silverquant (组件化)", capital)
        self.entry_threshold = 5.0
        self.max_positions = 8
    
    def daily_step(self, date, score_map, tech_map, price_map, hist_prices=None):
        held = set(self.positions.keys())
        candidates = sorted(
            [s for s in score_map if s not in held],
            key=lambda s: score_map.get(s, 0), reverse=True
        )[:5]
        
        # ── SilverQuant-style BUYER ──
        for sym in candidates:
            if len(self.positions) >= self.max_positions:
                break
            score = score_map.get(sym, 0)
            if score < self.entry_threshold:
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            
            # Slot-based sizing (SilverQuant: slot_capacity)
            slot_cap = 30000
            qty = max(100, int(slot_cap / price / 100) * 100)
            cost = price * qty
            if cost > self.cash:
                qty = max(100, int(self.cash / price / 100) * 100)
                cost = price * qty
                if cost > self.cash:
                    continue
            
            self.cash -= cost
            self.positions[sym] = {
                "entry_price": price, "quantity": qty,
                "entry_date": date, "peak": price,
                "current_price": price, "entry_close": price
            }
            self.history.append({"date": date, "symbol": sym, "action": "买入",
                                 "price": price, "quantity": qty})
        
        # ── SilverQuant-style SELLER_COMPONENTS ──
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price
            pos["peak"] = max(pos["peak"], price)
            
            entry = pos["entry_price"]
            peak = pos["peak"]
            pnl_pct = (price - entry) / entry * 100
            dd = (price - peak) / peak * 100 if peak else 0
            
            # HardSeller: 硬止损 -8%
            if pnl_pct <= -8:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": "HardSeller(-8%)"})
                del self.positions[sym]
                continue
            
            # FallSeller: 峰值回落 >12%
            if dd <= -12:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": f"FallSeller({dd:.1f}%)"})
                del self.positions[sym]
                continue
            
            # MASeller: MA20死叉
            tech = tech_map.get(sym, {})
            ma20d = tech.get("ma20_dev", 0) or 0
            ma60d = tech.get("ma60_dev", 0) or 0
            if ma20d < ma60d and pnl_pct > -5:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": "MASeller(MA死叉)"})
                del self.positions[sym]
                continue
            
            # VolumeDropSeller: 缩量 (if hist_prices available)
            score = score_map.get(sym, 0)
            if score is not None and score < 4.5:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": f"ScoreDrop({score:.1f})"})
                del self.positions[sym]
        
        self.record_value(date)


# ═══════════════════════════════════════════
# 策略3: TradingAgents-inspired (辩论制信号)
# ═══════════════════════════════════════════
class TradingAgentsStrategy(BaseStrategy):
    """TradingAgents风格：多信号辩论→综合裁决"""
    def __init__(self, capital=1000000):
        super().__init__("tradingagents (辩论制)", capital)
        self.max_positions = 6  # 集中度高
    
    def _debate_score(self, score, tech, vol_signal=""):
        """模拟多Agent辩论：bull/bear/neutral 三方打分后裁决"""
        score = score or 5.0
        tech_score = (tech or {}).get("total_tech_score", 5.0)
        
        # Bull case: score + tech
        bull = score * 0.5 + tech_score * 0.5
        
        # Bear case: volatility + weakness
        bear_penalty = 0
        if vol_signal in ("缩量", "极度缩量"):
            bear_penalty += 1.5
        if (tech or {}).get("macd_signal", "") == "🔴死叉":
            bear_penalty += 1.0
        if (tech or {}).get("rsi", 50) > 70:
            bear_penalty += 0.5
        bear = score - bear_penalty
        
        # Neutral: average
        neutral = score
        
        # Research Manager裁决：取bull/bear的加权平均
        if bull >= bear and bull >= neutral:
            final = bull * 0.6 + neutral * 0.3 + bear * 0.1
        elif bear >= bull and bear >= neutral:
            final = bear * 0.5 + neutral * 0.3 + bull * 0.2
        else:
            final = neutral
        
        return min(10, max(0, final))
    
    def daily_step(self, date, score_map, tech_map, price_map, vol_signals=None):
        held = set(self.positions.keys())
        
        # 辩论制裁决每个标的
        debate = {}
        for sym in score_map:
            score = score_map.get(sym, 5.0)
            tech = tech_map.get(sym, {})
            vsig = ""
            if vol_signals:
                vsig = vol_signals.get(sym, {}).get("signal", "")
            debate[sym] = {
                "score": score,
                "debate_score": self._debate_score(score, tech, vsig),
                "bull": score * 0.5 + (tech or {}).get("total_tech_score", 5.0) * 0.5,
                "bear": score - (1.5 if vsig in ("缩量","极度缩量") else 0) - 
                        (1.0 if (tech or {}).get("macd_signal") == "🔴死叉" else 0),
            }
        
        # 建仓：辩论分高+集中度高
        candidates = sorted(
            [(s, d["debate_score"]) for s, d in debate.items() if s not in held],
            key=lambda x: x[1], reverse=True
        )[:3]
        
        for sym, dscore in candidates:
            if len(self.positions) >= self.max_positions:
                break
            if dscore < 5.5:  # Debate entry threshold higher
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            
            # Kelly position sizing
            win_p = min(dscore / 10.0, 0.8)
            kelly = max(0, (win_p * 1.8 - (1 - win_p)) / 1.8) * 0.5
            position_cash = int(self.cash * min(kelly, 0.12))  # Higher上限
            qty = max(100, int(position_cash / price / 100) * 100)
            cost = price * qty
            if cost > self.cash:
                continue
            
            self.cash -= cost
            self.positions[sym] = {
                "entry_price": price, "quantity": qty,
                "entry_date": date, "peak": price,
                "current_price": price,
                "debate_score": dscore
            }
            self.history.append({"date": date, "symbol": sym, "action": "买入",
                                 "price": price, "quantity": qty,
                                 "reason": f"辩论分{dscore:.1f}(bull:{debate[sym]['bull']:.1f}/bear:{debate[sym]['bear']:.1f})"})
        
        # 清仓：辩论制风控
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price
            pos["peak"] = max(pos["peak"], price)
            
            dscore = debate.get(sym, {}).get("debate_score", 5.0)
            entry = pos["entry_price"]
            peak = pos["peak"]
            pnl_pct = (price - entry) / entry * 100
            dd = (price - peak) / peak * 100 if peak else 0
            
            # Risk Judge裁决
            if dscore < 4.0:  # 强卖
                reason = f"辩论分{dscore:.1f}<4"
            elif pnl_pct <= -8:  # 硬止损
                reason = f"止损{pnl_pct:.1f}%"
            elif dscore < 5.0 and pnl_pct < 0:  # 弱势持仓
                reason = f"辩论分{dscore:.1f}+亏损"
            else:
                continue
            
            pnl = (price - entry) * pos["quantity"]
            self.cash += price * pos["quantity"]
            self.history.append({"date": date, "symbol": sym, "action": "卖出",
                                 "price": price, "pnl": round(pnl, 2), "reason": reason})
            del self.positions[sym]
        
        self.record_value(date)


# ═══════════════════════════════════════════
# 对比运行引擎
# ═══════════════════════════════════════════
def run_comparison(days=60):
    """
    运行三方策略对比回测
    使用最近 days 天的数据
    """
    # 获取每日评分/技术/价格数据
    # 用模拟盘历史+扫描快照作为数据源
    shadow_data = load_shadow_history()
    
    # 初始化策略
    faceji = FacejiStrategy()
    silverquant = SilverQuantStrategy()
    tradingagents = TradingAgentsStrategy()
    
    # 生成模拟数据：从现有的 scanner_results 反推
    # 这里使用每日扫描快照
    score_history = load_score_history(days=days)
    
    if not score_history:
        # 无历史数据 — 返回空，Dashboard 显示"数据尚未积累"替代假数据
        # 每日扫描自动积累，约60个交易日后有真实对比曲线
        return {
            "faceji": {"name": "faceji（面基）", "value": 1000000, "total_return_pct": 0,
                       "daily_values": [], "trades": [], "note": "数据积累中…"},
            "silverquant": {"name": "SilverQuant", "value": 1000000, "total_return_pct": 0,
                            "daily_values": [], "trades": [], "note": "数据积累中…"},
            "tradingagents": {"name": "TradingAgents", "value": 1000000, "total_return_pct": 0,
                              "daily_values": [], "trades": [], "note": "数据积累中…"},
        }
    
    # 逐日回放
    for day in score_history:
        date = day["date"]
        results = day["results"]
        
        score_map = {}
        tech_map = {}
        price_map = {}
        vol_signals = {}
        
        for r in results:
            sym = r.get("symbol", "")
            if not sym:
                continue
            score_map[sym] = r.get("score", 0)
            tech_map[sym] = r.get("tech", {})
            price_map[sym] = r.get("price", 0)
            vs = r.get("vol_signal", "")
            if vs:
                vol_signals[sym] = {"signal": vs}
        
        if not score_map:
            continue
        
        faceji.daily_step(date, score_map, tech_map, price_map)
        silverquant.daily_step(date, score_map, tech_map, price_map)
        tradingagents.daily_step(date, score_map, tech_map, price_map, vol_signals)
    
    return {
        "faceji": faceji.get_summary(),
        "silverquant": silverquant.get_summary(),
        "tradingagents": tradingagents.get_summary(),
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days_analyzed": len(score_history),
    }


def _generate_sample_comparison():
    """无历史数据时生成示例数据（展示dashboard结构）"""
    import random
    base = 1000000
    
    def gen_daily_values(strategy_name, start_val, days=30):
        vals = []
        v = start_val
        for i in range(days):
            d = (datetime.now() - timedelta(days=days-i-1)).strftime("%Y-%m-%d")
            # Slightly different drift per strategy
            if strategy_name == "faceji":
                drift = random.uniform(-0.003, 0.005)
            elif strategy_name == "silverquant":
                drift = random.uniform(-0.002, 0.006)
            else:
                drift = random.uniform(-0.004, 0.008)
            v = v * (1 + drift)
            vals.append({"date": d, "value": round(v, 2)})
        return vals
    
    return {
        "faceji": {
            "name": "faceji (面基)",
            "value": round(base * 1.042, 2),
            "cash": 850000,
            "positions": 5,
            "total_return_pct": 4.2,
            "realized_pnl": 18000,
            "unrealized_pnl": 24000,
            "total_trades": 12,
            "win_rate": 50.0,
            "max_drawdown_pct": 6.8,
            "daily_values": gen_daily_values("faceji", base),
            "trades": [
                {"date":"2026-07-01","symbol":"300750","action":"买入","price":185.50,"quantity":200,"cost":37100,"reason":"评分5.8+趋势向上"},
                {"date":"2026-07-01","symbol":"002594","action":"买入","price":265.30,"quantity":100,"cost":26530,"reason":"评分5.6+新能源板块"},
                {"date":"2026-06-28","symbol":"300059","action":"卖出","price":24.80,"quantity":1500,"pnl":1350,"reason":"评分<4.5"},
                {"date":"2026-06-25","symbol":"600519","action":"买入","price":1580.00,"quantity":20,"cost":31600,"reason":"评分6.2+消费复苏"},
                {"date":"2026-06-20","symbol":"000858","action":"卖出","price":148.50,"quantity":200,"pnl":-1120,"reason":"评分<4尾部风险"},
                {"date":"2026-06-18","symbol":"002371","action":"买入","price":328.00,"quantity":100,"cost":32800,"reason":"评分5.9+半导体周期"},
                {"date":"2026-06-15","symbol":"300502","action":"买入","price":98.60,"quantity":300,"cost":29580,"reason":"评分6.0+AI算力光模块"},
                {"date":"2026-06-12","symbol":"688041","action":"卖出","price":72.30,"quantity":400,"pnl":2520,"reason":"评分<5+MA死叉"},
                {"date":"2026-06-10","symbol":"601318","action":"买入","price":52.80,"quantity":600,"cost":31680,"reason":"评分5.4+保险估值修复"},
                {"date":"2026-06-08","symbol":"300750","action":"卖出","price":178.20,"quantity":200,"pnl":-640,"reason":"MA死叉"},
                {"date":"2026-06-05","symbol":"002594","action":"买入","price":258.00,"quantity":100,"cost":25800,"reason":"评分5.5+新能源政策"},
                {"date":"2026-06-01","symbol":"300059","action":"买入","price":23.50,"quantity":1500,"cost":35250,"reason":"评分5.7+券商活跃"},
            ]
        },
        "silverquant": {
            "name": "silverquant (组件化)",
            "value": round(base * 1.058, 2),
            "cash": 820000,
            "positions": 6,
            "total_return_pct": 5.8,
            "realized_pnl": 32000,
            "unrealized_pnl": 26000,
            "total_trades": 18,
            "win_rate": 55.6,
            "max_drawdown_pct": 5.2,
            "daily_values": gen_daily_values("silverquant", base),
            "trades": [
                {"date":"2026-07-01","symbol":"300059","action":"买入","price":24.50,"quantity":1200,"cost":29400,"reason":"评分5.7+组件信号BUYER"},
                {"date":"2026-06-30","symbol":"002415","action":"买入","price":42.80,"quantity":700,"cost":29960,"reason":"评分5.5+视觉AI"},
                {"date":"2026-06-28","symbol":"000333","action":"卖出","price":68.50,"quantity":400,"pnl":1200,"reason":"MASeller(MA死叉)"},
                {"date":"2026-06-25","symbol":"300750","action":"买入","price":182.00,"quantity":200,"cost":36400,"reason":"评分5.9+动力电池"},
                {"date":"2026-06-22","symbol":"000651","action":"卖出","price":58.20,"quantity":500,"pnl":-900,"reason":"ScoreDrop(4.3)"},
                {"date":"2026-06-18","symbol":"300502","action":"买入","price":95.00,"quantity":300,"cost":28500,"reason":"评分5.8+光模块"},
                {"date":"2026-06-15","symbol":"600519","action":"买入","price":1560.00,"quantity":20,"cost":31200,"reason":"评分6.1+白酒龙头"},
                {"date":"2026-06-10","symbol":"002594","action":"买入","price":260.00,"quantity":100,"cost":26000,"reason":"评分5.6+整车"},
                {"date":"2026-06-05","symbol":"601318","action":"卖出","price":51.20,"quantity":500,"pnl":-1400,"reason":"HardSeller(-8%)"},
            ]
        },
        "tradingagents": {
            "name": "tradingagents (辩论制)",
            "value": round(base * 1.035, 2),
            "cash": 750000,
            "positions": 4,
            "total_return_pct": 3.5,
            "realized_pnl": 15000,
            "unrealized_pnl": 20000,
            "total_trades": 8,
            "win_rate": 62.5,
            "max_drawdown_pct": 4.5,
            "daily_values": gen_daily_values("tradingagents", base),
            "trades": [
                {"date":"2026-07-01","symbol":"NVDA","action":"买入","price":128.50,"quantity":300,"cost":38550,"reason":"辩论分8.2(bull:7.8/bear:6.0)"},
                {"date":"2026-06-28","symbol":"300750","action":"买入","price":180.00,"quantity":200,"cost":36000,"reason":"辩论分7.5(bull:7.2/bear:5.8)"},
                {"date":"2026-06-25","symbol":"300059","action":"卖出","price":24.00,"quantity":1200,"pnl":-600,"reason":"辩论分3.8<4"},
                {"date":"2026-06-20","symbol":"300502","action":"买入","price":92.00,"quantity":300,"cost":27600,"reason":"辩论分7.2(bull:7.0/bear:5.5)"},
                {"date":"2026-06-15","symbol":"600519","action":"买入","price":1540.00,"quantity":20,"cost":30800,"reason":"辩论分7.8(bull:7.5/bear:6.2)"},
                {"date":"2026-06-10","symbol":"002594","action":"卖出","price":255.00,"quantity":100,"pnl":-500,"reason":"止损-5.8%"},
                {"date":"2026-06-05","symbol":"002415","action":"卖出","price":40.50,"quantity":600,"pnl":-1800,"reason":"辩论分3.5+亏损"},
            ]
        },
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days_analyzed": 0,
        "note": "⚠️ 示例数据（未找到历史扫描快照），实际数据将在日报运行后自动填充"
    }
