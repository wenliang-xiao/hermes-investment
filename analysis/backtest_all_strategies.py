"""
三方策略对比回测（独立运行版）
1. 跑当前扫描获取评分
2. 拉 baostock 60天日线
3. 逐日回放三策略
4. 输出完整报告
"""
import sys, os, json, math
from datetime import datetime, timedelta, date
import numpy as np
import pandas as pd

# Fix path: this script lives at investment_system/analysis/backtest_all_strategies.py
# We need investment_system/.. in sys.path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)  # investment_system/
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)
os.chdir(_PROJECT_DIR)  # Always run from investment_system/

# Local imports (investment_system/)
from config import FACTOR_WEIGHTS
from data.data_layer import get_stock_daily, get_financial_report
from analysis.factor_scanner import FactorScanner
from domain import WATCHLIST
import functools
print = functools.partial(print, flush=True)

# ═══════════════════════════════════════════
# 策略定义（精简版，与 strategy_comparison.py 一致）
# ═══════════════════════════════════════════

class BaseStrategy:
    def __init__(self, name, capital=1000000):
        self.name = name
        self.capital = capital
        self.cash = capital
        self.positions = {}
        self.history = []
        self.daily_values = []

    def reset(self, capital=1000000):
        self.cash = capital
        self.positions = {}
        self.history = []
        self.daily_values = []

    def current_value(self, price_map):
        pos_value = 0
        for sym, p in self.positions.items():
            price = price_map.get(sym, p.get("current_price", p["entry_price"]))
            pos_value += p["quantity"] * price
        return self.cash + pos_value

    def record_value(self, date_str, price_map):
        val = round(self.current_value(price_map), 2)
        self.daily_values.append({"date": date_str, "value": val})

    def get_summary(self, price_map):
        realized_pnl = sum(h.get("pnl", 0) for h in self.history if h.get("action") == "卖出")
        pos_pnl = 0
        for sym, p in self.positions.items():
            price = price_map.get(sym, p.get("current_price", p["entry_price"]))
            pos_pnl += (price - p["entry_price"]) * p["quantity"]
        total_pnl = realized_pnl + pos_pnl
        value = self.current_value(price_map)
        returns = (value - self.capital) / self.capital * 100 if self.capital else 0

        buys = [h for h in self.history if h.get("action") == "买入"]
        sells = [h for h in self.history if h.get("action") == "卖出"]
        wins = [h for h in sells if h.get("pnl", 0) > 0]
        losses = [h for h in sells if h.get("pnl", 0) <= 0]

        # Max drawdown
        peak = self.capital
        max_dd = 0
        for entry in self.daily_values:
            peak = max(peak, entry["value"])
            dd = (entry["value"] - peak) / peak * 100
            max_dd = min(max_dd, dd)

        # Sharpe-like ratio (daily)
        returns_series = []
        prev_val = self.capital
        for dv in self.daily_values:
            if prev_val > 0:
                returns_series.append((dv["value"] - prev_val) / prev_val)
            prev_val = dv["value"]
        sharpe = np.mean(returns_series) / (np.std(returns_series) + 1e-10) * np.sqrt(252) if returns_series else 0

        trade_details = []
        for h in self.history:
            trade_details.append({
                "date": h["date"], "symbol": h["symbol"], "action": h["action"],
                "price": h.get("price", 0), "quantity": h.get("quantity", 0),
                "pnl": h.get("pnl", 0), "reason": h.get("reason", "")
            })

        return {
            "name": self.name,
            "value": round(value, 2),
            "cash": round(self.cash, 2),
            "positions_count": len(self.positions),
            "total_return_pct": round(returns, 2),
            "total_return_cny": round(total_pnl, 2),
            "realized_pnl": round(realized_pnl, 2),
            "unrealized_pnl": round(pos_pnl, 2),
            "total_trades_closed": len(sells),
            "total_trades_opened": len(buys),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(len(wins) / len(sells) * 100, 1) if sells else 0,
            "max_drawdown_pct": round(abs(max_dd), 2),
            "sharpe_ratio": round(sharpe, 2),
            "daily_values": self.daily_values,
            "trades": trade_details
        }


class FacejiStrategy(BaseStrategy):
    def __init__(self, capital=1000000):
        super().__init__("faceji (面基)", capital)
        self.entry_threshold = 5.0
        self.exit_threshold = 4.0
        self.max_positions = 8

    def daily_step(self, date_str, score_map, tech_map, price_map):
        held = set(self.positions.keys())

        # Buy: top5 candidates with score >= 5.0 + trend check
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
            qty = max(100, int(30000 / price / 100) * 100)
            cost = price * qty
            if cost > self.cash:
                qty = max(100, int(self.cash / price / 100) * 100)
                cost = price * qty
                if cost > self.cash:
                    continue
            self.cash -= cost
            self.positions[sym] = {"entry_price": price, "quantity": qty,
                                   "entry_date": date_str, "peak": price, "current_price": price}
            self.history.append({"date": date_str, "symbol": sym, "action": "买入",
                                 "price": price, "quantity": qty, "cost": round(cost, 2),
                                 "reason": f"评分{score:.1f}+技术{ma20d:.1f}/{ma60d:.1f}"})

        # Update prices & check exits
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            price = price_map.get(sym, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = price
            pos["peak"] = max(pos["peak"], price)

            score = score_map.get(sym, 0)
            # Exit: score < 4
            if score < self.exit_threshold:
                pnl = (price - pos["entry_price"]) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": f"评分{score:.1f}<{self.exit_threshold}"})
                del self.positions[sym]
                continue
            # Exit: score < 5 + MA death cross
            if score < 5.0:
                tech = tech_map.get(sym, {})
                if (tech.get("ma20_dev", 0) or 0) < (tech.get("ma60_dev", 0) or 0):
                    pnl = (price - pos["entry_price"]) * pos["quantity"]
                    self.cash += price * pos["quantity"]
                    self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                         "price": price, "pnl": round(pnl, 2),
                                         "reason": "MA死叉+评分<5"})
                    del self.positions[sym]

        self.record_value(date_str, price_map)


class SilverQuantStrategy(BaseStrategy):
    def __init__(self, capital=1000000):
        super().__init__("silverquant (组件化)", capital)
        self.entry_threshold = 5.0
        self.max_positions = 8

    def daily_step(self, date_str, score_map, tech_map, price_map):
        held = set(self.positions.keys())
        candidates = sorted(
            [s for s in score_map if s not in held],
            key=lambda s: score_map.get(s, 0), reverse=True
        )[:5]

        # ── SilverQuant BUYER ──
        for sym in candidates:
            if len(self.positions) >= self.max_positions:
                break
            score = score_map.get(sym, 0)
            if score < self.entry_threshold:
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            slot_cap = 30000
            qty = max(100, int(slot_cap / price / 100) * 100)
            cost = price * qty
            if cost > self.cash:
                qty = max(100, int(self.cash / price / 100) * 100)
                cost = price * qty
                if cost > self.cash:
                    continue
            self.cash -= cost
            self.positions[sym] = {"entry_price": price, "quantity": qty,
                                   "entry_date": date_str, "peak": price,
                                   "current_price": price, "entry_close": price}
            self.history.append({"date": date_str, "symbol": sym, "action": "买入",
                                 "price": price, "quantity": qty, "cost": round(cost, 2),
                                 "reason": f"槽位建仓(评分{score:.1f})"})

        # ── SilverQuant SELLER_COMPONENTS ──
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
                self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": "HardSeller(-8%)"})
                del self.positions[sym]
                continue
            # FallSeller: 峰值回落 >12%
            if dd <= -12:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": f"FallSeller({dd:.1f}%)"})
                del self.positions[sym]
                continue
            # MASeller: MA20死叉
            tech = tech_map.get(sym, {})
            if (tech.get("ma20_dev", 0) or 0) < (tech.get("ma60_dev", 0) or 0) and pnl_pct > -5:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": "MASeller(MA死叉)"})
                del self.positions[sym]
                continue
            # ScoreDrop exit
            score = score_map.get(sym, 0)
            if score < 4.5:
                pnl = (price - entry) * pos["quantity"]
                self.cash += price * pos["quantity"]
                self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                     "price": price, "pnl": round(pnl, 2),
                                     "reason": f"ScoreDrop({score:.1f})"})
                del self.positions[sym]

        self.record_value(date_str, price_map)


class TradingAgentsStrategy(BaseStrategy):
    def __init__(self, capital=1000000):
        super().__init__("tradingagents (辩论制)", capital)
        self.max_positions = 6

    def _debate_score(self, score, tech):
        score = score or 5.0
        tech_score = tech.get("total_tech_score", 5.0) if tech else 5.0
        bull = score * 0.5 + tech_score * 0.5
        bear_penalty = 0
        if tech and tech.get("macd_signal", "") == "🔴死叉":
            bear_penalty += 1.0
        if tech and (tech.get("rsi", 50) or 50) > 70:
            bear_penalty += 0.5
        bear = score - bear_penalty
        neutral = score
        if bull >= bear and bull >= neutral:
            final = bull * 0.6 + neutral * 0.3 + bear * 0.1
        elif bear >= bull and bear >= neutral:
            final = bear * 0.5 + neutral * 0.3 + bull * 0.2
        else:
            final = neutral
        return min(10, max(0, final))

    def daily_step(self, date_str, score_map, tech_map, price_map):
        held = set(self.positions.keys())

        # Debate scores
        debate = {}
        for sym in score_map:
            score = score_map.get(sym, 5.0)
            tech = tech_map.get(sym, {})
            debate[sym] = {
                "score": score,
                "debate_score": self._debate_score(score, tech),
            }

        # Buy: debate high + concentrated
        candidates = sorted(
            [(s, d["debate_score"]) for s, d in debate.items() if s not in held],
            key=lambda x: x[1], reverse=True
        )[:3]

        for sym, dscore in candidates:
            if len(self.positions) >= self.max_positions:
                break
            if dscore < 5.5:
                continue
            price = price_map.get(sym, 0)
            if price <= 0:
                continue
            # Kelly sizing
            win_p = min(dscore / 10.0, 0.8)
            kelly = max(0, (win_p * 1.8 - (1 - win_p)) / 1.8) * 0.5
            position_cash = int(self.cash * min(kelly, 0.12))
            qty = max(100, int(position_cash / price / 100) * 100)
            cost = price * qty
            if cost > self.cash:
                qty = max(100, int(self.cash / price / 100) * 100)
                cost = price * qty
                if cost > self.cash:
                    continue
            self.cash -= cost
            self.positions[sym] = {"entry_price": price, "quantity": qty,
                                   "entry_date": date_str, "peak": price,
                                   "current_price": price, "debate_score": dscore}
            self.history.append({"date": date_str, "symbol": sym, "action": "买入",
                                 "price": price, "quantity": qty, "cost": round(cost, 2),
                                 "reason": f"辩论分{dscore:.1f}"})

        # Sell: debate-based risk
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

            if dscore < 4.0:
                reason = f"辩论分{dscore:.1f}<4"
            elif pnl_pct <= -8:
                reason = f"止损{pnl_pct:.1f}%"
            elif dscore < 5.0 and pnl_pct < 0:
                reason = f"辩论分{dscore:.1f}+亏损"
            else:
                continue

            pnl = (price - entry) * pos["quantity"]
            self.cash += price * pos["quantity"]
            self.history.append({"date": date_str, "symbol": sym, "action": "卖出",
                                 "price": price, "pnl": round(pnl, 2), "reason": reason})
            del self.positions[sym]

        self.record_value(date_str, price_map)


# ═══════════════════════════════════════════
# 数据准备
# ═══════════════════════════════════════════

def get_watchlist_a_shares():
    """获取WATCHLIST中的A股（只限核心+底仓）"""
    a_stocks = []
    for code, info in WATCHLIST.items():
        sym = str(code)
        if sym.isdigit() and (sym.startswith("0") or sym.startswith("3") or sym.startswith("6")):
            tier = info.get("tier", "")
            if tier in ("核心", "底仓"):
                a_stocks.append({"symbol": sym, "name": info.get("name", sym), "tier": tier})
    return a_stocks


def run_scanner(stocks):
    """运行扫描器获取评分"""
    scanner = FactorScanner(macro_engine=None)
    scanner.weights = FACTOR_WEIGHTS.get("default")

    results = []
    for s in stocks:
        sym = s["symbol"]
        r = scanner.score_stock(sym)
        if not r.get("error"):
            r["name"] = s["name"]
            r["sector"] = scanner._get_stock_sector(sym)
            results.append(r)
        print(f"  {sym} {s['name']}: 评分{r.get('score', 0):.1f}", flush=True)
    return results


def fetch_historical_prices(stocks, days=120):
    """从data_layer获取历史日线价格"""
    hist_data = {}
    for s in stocks:
        sym = s["symbol"]
        df = get_stock_daily(sym, days=days)
        if df is not None and not df.empty:
            if "close" in df.columns:
                close_col = "close"
            else:
                close_col = df.columns[4] if len(df.columns) > 4 else None
            if close_col:
                df = df.reset_index(drop=True) if "date" not in df.columns else df
                # Ensure date column
                if "date" not in df.columns and "datetime" in df.columns:
                    df["date"] = df["datetime"]
                elif "date" not in df.columns and "index" in df.columns:
                    df["date"] = df["index"]
                elif "date" not in df.columns:
                    df["date"] = df.index.astype(str) if hasattr(df.index, 'astype') else range(len(df))
                df["close"] = pd.to_numeric(df[close_col], errors="coerce")
                df = df.dropna(subset=["close"])
                df = df.sort_values("date").reset_index(drop=True)
                hist_data[sym] = df
                print(f"  {sym} {s['name']}: {len(df)}条 {df['date'].iloc[0]}→{df['date'].iloc[-1]}", flush=True)
            else:
                print(f"  {sym} {s['name']}: 无close列（{list(df.columns)}）", flush=True)
        else:
            print(f"  {sym} {s['name']}: 无数据", flush=True)
    return hist_data


def build_daily_snapshots(results, hist_data, lookback=60):
    """
    构建逐日回测数据。
    对每个回测日期，使用当前评分（fundamental稳定）+ 当日技术指标（从历史价格计算）
    """
    # 确定日期范围：取所有股票历史日期的交集
    all_dates = set()
    for sym, df in hist_data.items():
        all_dates.update(df["date"].tolist())
    all_dates = sorted(all_dates)
    if not all_dates:
        return None

    # 取最后 lookback 天
    dates = all_dates[-lookback:]
    print(f"\n回测日期范围: {dates[0]} → {dates[-1]} ({len(dates)}个交易日)")

    # 构建评分 map (symbol -> score) - 使用扫描结果
    score_map_base = {}
    for r in results:
        sym = r.get("symbol", "")
        if sym and sym in hist_data:
            score_map_base[sym] = r.get("score", 5.0)

    # 逐日构建
    daily_snapshots = []
    for dt in dates:
        score_map = {}
        tech_map = {}
        price_map = {}

        for sym, df in hist_data.items():
            # 找到该日期或之前最近的价格
            row = df[df["date"] <= dt]
            if row.empty:
                continue
            row = row.iloc[-1]

            price = float(row["close"])
            price_map[sym] = price
            score_map[sym] = score_map_base.get(sym, 5.0)

            # 计算技术指标
            close_series = df[df["date"] <= dt]["close"].values
            close_series = np.array([float(c) for c in close_series])

            tech = {}
            if len(close_series) >= 20:
                ma20 = np.mean(close_series[-20:])
                tech["ma20_dev"] = round((price - ma20) / ma20 * 100, 2)
            else:
                tech["ma20_dev"] = 0
            if len(close_series) >= 60:
                ma60 = np.mean(close_series[-60:])
                tech["ma60_dev"] = round((price - ma60) / ma60 * 100, 2)
            else:
                tech["ma60_dev"] = 0

            # RSI(14)
            if len(close_series) >= 15:
                gains, losses = 0, 0
                for i in range(1, 15):
                    diff = close_series[-i] - close_series[-i-1]
                    if diff >= 0:
                        gains += diff
                    else:
                        losses += abs(diff)
                avg_gain = gains / 14
                avg_loss = losses / 14
                if avg_loss > 0:
                    rsi = 100 - (100 / (1 + avg_gain / avg_loss))
                else:
                    rsi = 100 if avg_gain > 0 else 50
                tech["rsi"] = round(rsi, 1)
            else:
                tech["rsi"] = 50

            # MACD
            if len(close_series) >= 26:
                ema12 = pd.Series(close_series).ewm(span=12).mean().iloc[-1]
                ema26 = pd.Series(close_series).ewm(span=26).mean().iloc[-1]
                macd_line = ema12 - ema26
                signal = pd.Series(close_series).ewm(span=9).mean().iloc[-1]
                prev_ema12 = pd.Series(close_series[:-1]).ewm(span=12).mean().iloc[-1] if len(close_series) > 26 else ema12
                prev_ema26 = pd.Series(close_series[:-1]).ewm(span=26).mean().iloc[-1] if len(close_series) > 26 else ema26
                prev_macd = prev_ema12 - prev_ema26
                tech["macd_signal"] = "🟢金叉" if macd_line > signal and prev_macd <= prev_ema12 - prev_ema26 else \
                                       "🔴死叉" if macd_line < signal else "⚪"
                tech["total_tech_score"] = 5.0 + (
                    1.0 if tech.get("rsi", 50) and 30 < tech["rsi"] < 70 else 0
                ) + (1.5 if tech.get("macd_signal") == "🟢金叉" else 0)
            else:
                tech["macd_signal"] = "⚪"
                tech["total_tech_score"] = 5.0

            tech_map[sym] = tech

        daily_snapshots.append({
            "date": dt,
            "score_map": score_map,
            "tech_map": tech_map,
            "price_map": price_map
        })

    return daily_snapshots


# ═══════════════════════════════════════════
# 主执行
# ═══════════════════════════════════════════

def main():
    print("=" * 60)
    print("三方策略对比回测")
    print("=" * 60)

    # Step 1: Get watchlist
    print("\n📋 Step 1: 获取WATCHLIST A股...")
    stocks = get_watchlist_a_shares()
    print(f"  {len(stocks)}只A股在观察池中")

    # Step 2: Run scanner
    print("\n🔍 Step 2: 运行扫描器获取评分...")
    results = run_scanner(stocks)
    scored_stocks = [r for r in results if r.get("score", 0) > 0]
    print(f"  {len(scored_stocks)}只成功评分")
    for r in sorted(scored_stocks, key=lambda x: x.get("score",0), reverse=True)[:10]:
        print(f"    #{scored_stocks.index(r)+1}: {r['symbol']} {r.get('name','')} 评分{r.get('score',0):.1f}")

    # Step 3: Fetch historical prices
    print("\n📈 Step 3: 获取60天历史价格...")
    hist_data = fetch_historical_prices(stocks, days=180)

    # Step 4: Build daily snapshots
    print("\n🔄 Step 4: 构建逐日回测数据...")
    daily_snapshots = build_daily_snapshots(scored_stocks, hist_data, lookback=60)
    if not daily_snapshots:
        print("❌ 无历史数据，无法回测")
        return

    # Step 5: Run backtest for all 3 strategies
    print("\n🏃 Step 5: 运行三方回测...")
    strategies = {
        "faceji": FacejiStrategy(),
        "silverquant": SilverQuantStrategy(),
        "tradingagents": TradingAgentsStrategy()
    }

    for day in daily_snapshots:
        dt = day["date"]
        sm = day["score_map"]
        tm = day["tech_map"]
        pm = day["price_map"]
        for s in strategies.values():
            s.daily_step(dt, sm, tm, pm)

    # Step 6: Get summaries
    print("\n📊 Step 6: 汇总结果...")
    results_out = {}
    for name, s in strategies.items():
        # Last day price map for final valuation
        summary = s.get_summary(daily_snapshots[-1]["price_map"] if daily_snapshots else {})
        results_out[name] = summary
        print(f"\n  {summary['name']}:")
        print(f"    最终价值: ¥{summary['value']:,.2f}")
        print(f"    收益率: {summary['total_return_pct']:+.2f}%")
        print(f"    总盈亏: ¥{summary['total_return_cny']:+,.2f}")
        print(f"    交易次数(开/平): {summary['total_trades_opened']}/{summary['total_trades_closed']}")
        print(f"    胜率: {summary['win_rate']}%")
        print(f"    最大回撤: {summary['max_drawdown_pct']}%")
        print(f"    Sharpe: {summary['sharpe_ratio']}")
        print(f"    最后持仓: {summary['positions_count']}只")

    # Save results to JSON for report generation
    output = {
        "run_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "days_analyzed": len(daily_snapshots),
        "date_range": f"{daily_snapshots[0]['date']} → {daily_snapshots[-1]['date']}",
        "scored_stocks": len(scored_stocks),
        "results": results_out
    }

    out_path = os.path.join(_PROJECT_DIR, "data", "backtest_comparison.json")
    with open(out_path, "w") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 结果已保存到: {out_path}")

    return output


if __name__ == "__main__":
    result = main()
