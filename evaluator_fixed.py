"""
evaluator_fixed.py — 固定评估器

╔══════════════════════════════════════════════════════════╗
║  本文件是固定评估口径。一旦确定，禁止为提分而修改。        ║
║  HL 循环只允许修改 strategies/ 下的策略文件。             ║
║  要提分，只能改 strategies/*.py 里的逻辑和参数。          ║
╚══════════════════════════════════════════════════════════╝

用法:
    python evaluator_fixed.py faceji         # 评估面基策略
    python evaluator_fixed.py silverquant    # 评估SilverQuant
    python evaluator_fixed.py tradingagents  # 评估TradingAgents
    python evaluator_fixed.py --all          # 评估全部三个策略
    python evaluator_fixed.py faceji --check-baseline  # 与已接受基线对比
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable
import functools

print = functools.partial(print, flush=True)

# ──────────────────────────────────────────────
# 固定研究口径（FIXED —— 不要为了提分而修改）
# ──────────────────────────────────────────────

# 固定标的池（来自 backtest_v2.py 的 19 只已评分核心标的）
FIXED_UNIVERSE = [
    {"symbol": "300502", "name": "新易盛",   "score": 5.5},
    {"symbol": "300308", "name": "中际旭创", "score": 4.6},
    {"symbol": "688256", "name": "寒武纪",   "score": 5.1},
    {"symbol": "688008", "name": "澜起科技", "score": 5.2},
    {"symbol": "688012", "name": "中微公司", "score": 4.1},
    {"symbol": "688041", "name": "海光信息", "score": 5.0},
    {"symbol": "688120", "name": "华海清科", "score": 4.2},
    {"symbol": "002371", "name": "北方华创", "score": 4.5},
    {"symbol": "603501", "name": "韦尔股份", "score": 4.0},
    {"symbol": "688017", "name": "绿的谐波", "score": 3.5},
    {"symbol": "300124", "name": "汇川技术", "score": 4.7},
    {"symbol": "002747", "name": "埃斯顿",   "score": 4.4},
    {"symbol": "002472", "name": "双环传动", "score": 4.2},
    {"symbol": "300750", "name": "宁德时代", "score": 4.9},
    {"symbol": "601012", "name": "隆基绿能", "score": 4.8},
    {"symbol": "600760", "name": "中航沈飞", "score": 4.8},
    {"symbol": "002179", "name": "中航光电", "score": 4.0},
    {"symbol": "603259", "name": "药明康德", "score": 6.2},
    {"symbol": "300760", "name": "迈瑞医疗", "score": 5.0},
]
FIXED_SCORE_MAP: dict[str, float] = {s["symbol"]: s["score"] for s in FIXED_UNIVERSE}
FIXED_NAME_MAP: dict[str, str] = {s["symbol"]: s["name"] for s in FIXED_UNIVERSE}

# 固定回测参数
FIXED_DAYS = 120              # 回测数据窗口
INITIAL_CASH = 1_000_000.0    # 初始资金
TRADING_DAYS_PER_YEAR = 252

# 固定交易成本（A股实际费率）
COMMISSION_RATE = 0.00015     # 佣金万1.5
STAMP_TAX_RATE = 0.001        # 卖出印花税千1
SLIPPAGE = 0.001              # 滑点千1
MIN_COMMISSION = 5.0          # 最低佣金5元

# ──────────────────────────────────────────────
# 缓存
# ──────────────────────────────────────────────
_SCRIPT_DIR = Path(__file__).parent.resolve()  # .../investment_system/
_PROJECT_DIR = _SCRIPT_DIR
_PARENT_DIR = _SCRIPT_DIR.parent                 # for investment_system package import
CACHE_DIR = _PROJECT_DIR / "data" / "eval_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
HL_RUNS_DIR = _PROJECT_DIR / "data" / "hl_runs"
HL_RUNS_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# 数据层：拉取并缓存日线数据
# ──────────────────────────────────────────────
def load_price_history(symbol: str, days: int = FIXED_DAYS) -> list[float] | None:
    """从 baostock 获取日线收盘价，缓存到本地 pickle"""
    import numpy as np
    import pandas as pd

    cache_file = CACHE_DIR / f"{symbol}_{days}d.pkl"
    if cache_file.exists():
        df = pd.read_pickle(cache_file)
        return df["close"].tolist()

    # 从 data_layer 获取
    sys.path.insert(0, str(_PARENT_DIR))
    sys.path.insert(0, str(_PROJECT_DIR))
    from investment_system.data.data_layer import get_stock_daily
    df = get_stock_daily(symbol, days=days)
    if df is None or df.empty:
        return None
    df = df.copy()
    close_col = "close" if "close" in df.columns else (df.columns[4] if len(df.columns) > 4 else None)
    if close_col is None:
        return None
    df["close"] = pd.to_numeric(df[close_col], errors="coerce")
    df = df.dropna(subset=["close"]).sort_index()
    if len(df) < 60:
        return None
    df.to_pickle(cache_file)
    return df["close"].tolist()


def preload_all_data() -> dict[str, list[float]]:
    """预加载所有标的日线数据"""
    result: dict[str, list[float]] = {}
    for s in FIXED_UNIVERSE:
        sym = s["symbol"]
        prices = load_price_history(sym, FIXED_DAYS)
        if prices:
            result[sym] = prices
            print(f"  {sym} {s['name']}: {len(prices)} 天")
    return result


# ──────────────────────────────────────────────
# 技术指标计算
# ──────────────────────────────────────────────
def compute_technicals(
    closes: list[float],
    price: float,
) -> dict:
    """计算单标的单日技术指标"""
    import numpy as np

    close_arr = np.array(closes[-120:], dtype=float)
    n = len(close_arr)
    te: dict = {}

    if n >= 20:
        ma20 = float(np.mean(close_arr[-20:]))
        te["ma20_dev"] = round((price - ma20) / ma20 * 100, 2)
    else:
        te["ma20_dev"] = 0.0
    if n >= 60:
        ma60 = float(np.mean(close_arr[-60:]))
        te["ma60_dev"] = round((price - ma60) / ma60 * 100, 2)
    else:
        te["ma60_dev"] = 0.0

    # RSI 14
    if n >= 15:
        gains = sum(max(0, close_arr[-i] - close_arr[-i-1]) for i in range(1, 15))
        losses = sum(max(0, close_arr[-i-1] - close_arr[-i]) for i in range(1, 15))
        ag = gains / 14
        al = losses / 14
        te["rsi"] = round(100 - 100 / (1 + ag / al) if al > 0 else (100 if ag > 0 else 50), 1)
    else:
        te["rsi"] = 50.0

    # MACD
    if n >= 26:
        import pandas as pd
        s = pd.Series(close_arr)
        e12 = float(s.ewm(span=12).mean().iloc[-1])
        e26 = float(s.ewm(span=26).mean().iloc[-1])
        macd = e12 - e26
        se = float(s.ewm(span=9).mean().iloc[-1])
        sig = se
        pe12 = float(pd.Series(close_arr[:-1]).ewm(span=12).mean().iloc[-1]) if n > 26 else e12
        pe26 = float(pd.Series(close_arr[:-1]).ewm(span=26).mean().iloc[-1]) if n > 26 else e26
        pmacd = pe12 - pe26
        if macd > sig and pmacd <= (pe12 - pe26):
            te["macd_signal"] = "金叉"
        elif macd < sig:
            te["macd_signal"] = "死叉"
        else:
            te["macd_signal"] = "⚪"
        te["total_tech_score"] = 5.0 + (1.0 if 30 < te.get("rsi", 50) < 70 else 0) + (1.5 if te.get("macd_signal") == "金叉" else 0)
    else:
        te["macd_signal"] = "⚪"
        te["total_tech_score"] = 5.0

    return te


# ──────────────────────────────────────────────
# 回测引擎：逐日模拟
# ──────────────────────────────────────────────
def run_backtest(
    price_data: dict[str, list[float]],
    decide_fn: Callable,
    strategy_name: str,
) -> dict:
    """固定评估器的回测核心。

    对每个标的独立运行策略，最后汇总计算组合级指标。
    """
    from strategies.base import PositionData, Signal

    total_cash = INITIAL_CASH
    all_positions: dict[str, PositionData] = {}
    equity_curve: list[float] = []
    all_trades: list[dict] = []
    trade_count = 0
    win_count = 0

    # 找出最短的时间序列
    min_days = min(len(p) for p in price_data.values()) if price_data else 0
    if min_days < 60:
        return {"error": f"数据不足(最少60天, 实际{min_days}天)"}

    # 逐日推进
    score_map = dict(FIXED_SCORE_MAP)  # 固定评分

    for day_idx in range(min_days):
        # 构建当日 market data
        tech_map: dict[str, dict] = {}
        price_map: dict[str, float] = {}
        for sym in price_data:
            closes = price_data[sym][:day_idx + 1]
            price = float(closes[-1])
            price_map[sym] = price
            tech_map[sym] = compute_technicals(closes, price)

        # 当前持仓 PositionData 列表
        positions_dict: dict[str, PositionData] = {}
        for sym, pos in all_positions.items():
            cp = price_map.get(sym, pos.current_price or pos.entry_price)
            positions_dict[sym] = PositionData(
                symbol=sym, entry_price=pos.entry_price,
                quantity=pos.quantity, entry_date=pos.entry_date or "",
                peak=max(pos.peak or pos.entry_price, cp),
                current_price=cp,
            )

        # 执行决策
        signals = decide_fn(
            score_map=score_map,
            tech_map=tech_map,
            price_map=price_map,
            positions=positions_dict,
            cash=total_cash,
        )

        # 执行信号（先卖后买）
        for sig in signals:
            if sig.action == "SELL" and sig.symbol in all_positions:
                pos = all_positions[sig.symbol]
                exec_price = price_map.get(sig.symbol, sig.price)
                slippage_cost = exec_price * SLIPPAGE
                exec_price_adj = exec_price - slippage_cost
                proceeds = exec_price_adj * pos.quantity
                commission = max(proceeds * COMMISSION_RATE, MIN_COMMISSION)
                tax = proceeds * STAMP_TAX_RATE
                net_proceeds = proceeds - commission - tax
                pnl = net_proceeds - (pos.entry_price * pos.quantity)
                total_cash += net_proceeds
                if pnl > 0:
                    win_count += 1
                trade_count += 1
                all_trades.append({
                    "symbol": sig.symbol, "action": "SELL",
                    "price": round(exec_price, 2), "quantity": pos.quantity,
                    "pnl": round(pnl, 2),
                    "reason": sig.reason,
                    "day": day_idx,
                })
                del all_positions[sig.symbol]

            elif sig.action == "BUY" and sig.symbol not in all_positions:
                exec_price = price_map.get(sig.symbol, sig.price)
                slippage_cost = exec_price * SLIPPAGE
                exec_price_adj = exec_price + slippage_cost
                pct = (sig.size_pct or 3.0) / 100
                qty = max(100, int(total_cash * pct / exec_price_adj / 100) * 100)
                cost = exec_price_adj * qty
                commission = max(cost * COMMISSION_RATE, MIN_COMMISSION)
                total_cost = cost + commission
                if total_cost <= total_cash:
                    total_cash -= total_cost
                    all_positions[sig.symbol] = PositionData(
                        symbol=sig.symbol, entry_price=exec_price_adj,
                        quantity=qty, entry_date=f"day{day_idx}",
                        peak=exec_price_adj,
                        current_price=exec_price_adj,
                    )
                    trade_count += 1
                    all_trades.append({
                        "symbol": sig.symbol, "action": "BUY",
                        "price": round(exec_price, 2), "quantity": qty,
                        "cost": round(total_cost, 2),
                        "reason": sig.reason,
                        "day": day_idx,
                    })

        # 当日组合价值
        position_value = sum(
            price_map.get(sym, 0) * pos.quantity
            for sym, pos in all_positions.items()
        )
        total_value = total_cash + position_value
        equity_curve.append(total_value)

    # ─── 计算指标 ───
    return _compute_metrics(equity_curve, all_trades, trade_count, win_count,
                            strategy_name, score_map, price_data, min_days)


def _compute_metrics(
    equity_curve: list[float],
    trades: list[dict],
    trade_count: int,
    win_count: int,
    strategy_name: str,
    score_map: dict,
    price_data: dict,
    total_days: int,
) -> dict:
    """计算评估指标"""
    import numpy as np
    import pandas as pd

    if not equity_curve:
        return {"error": "无净值曲线"}

    equity = pd.Series(equity_curve)
    n_days = len(equity)
    final_value = equity.iloc[-1]

    total_return = final_value / INITIAL_CASH - 1.0
    annualized_return = (
        (1.0 + total_return) ** (TRADING_DAYS_PER_YEAR / n_days) - 1.0
        if n_days > 0 else 0.0
    )

    daily_returns = equity.pct_change().dropna()
    std = float(daily_returns.std())
    sharpe = (
        float(daily_returns.mean()) / std * math.sqrt(TRADING_DAYS_PER_YEAR)
        if std > 0 else 0.0
    )
    downside = daily_returns[daily_returns < 0]
    dstd = float(downside.std())
    sortino = (
        float(daily_returns.mean()) / dstd * math.sqrt(TRADING_DAYS_PER_YEAR)
        if dstd > 0 else 0.0
    )

    running_max = equity.cummax()
    drawdown = (equity - running_max) / running_max
    max_drawdown = float(-drawdown.min())

    win_rate = win_count / trade_count if trade_count > 0 else 0.0

    result = {
        "strategy": strategy_name,
        "score": round(sortino, 4),  # 主评分：Sortino
        "total_return_pct": round(total_return * 100, 2),
        "annualized_return_pct": round(annualized_return * 100, 2),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "max_drawdown_pct": round(max_drawdown * 100, 2),
        "win_rate_pct": round(win_rate * 100, 1),
        "trade_count": trade_count,
        "total_days": total_days,
        "final_value": round(final_value, 2),
        "universe_size": len(score_map),
        "stocks_with_data": len(price_data),
    }

    return result


# ──────────────────────────────────────────────
# HL 实验账本
# ──────────────────────────────────────────────
def save_to_run_log(strategy: str, result: dict):
    """记录到实验账本"""
    run_id = f"{strategy}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = HL_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 保存结果
    with open(run_dir / "result.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 追加到汇总
    summary_file = HL_RUNS_DIR / "runs.jsonl"
    entry = {"run_id": run_id, "strategy": strategy,
             "timestamp": datetime.now().isoformat(), **result}
    with open(summary_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def evaluate_strategy(strategy_name: str) -> dict:
    """评估单个策略"""
    # 加载数据
    print(f"\n📦 加载数据...")
    price_data = preload_all_data()
    if not price_data:
        return {"error": "无有效数据"}

    # 导入策略
    decide_fn: Callable | None = None
    strat_map = {
        "faceji": ("strategies.faceji", "decide"),
        "silverquant": ("strategies.silverquant", "decide"),
        "tradingagents": ("strategies.tradingagents", "decide"),
    }
    if strategy_name not in strat_map:
        return {"error": f"未知策略: {strategy_name}, 可选: {list(strat_map.keys())}"}

    mod_path, func_name = strat_map[strategy_name]
    import importlib
    try:
        mod = importlib.import_module(mod_path)
        decide_fn = getattr(mod, func_name)
    except Exception as e:
        return {"error": f"导入策略失败: {e}"}

    print(f"🏃 运行回测: {strategy_name}")
    result = run_backtest(price_data, decide_fn, strategy_name)
    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="固定评估器")
    parser.add_argument("strategy", nargs="?", default="", help="策略名: faceji / silverquant / tradingagents")
    parser.add_argument("--all", action="store_true", help="评估全部策略")
    parser.add_argument("--check-baseline", action="store_true", help="与基线对比")
    parser.add_argument("--no-log", action="store_true", help="不写入实验账本")

    args = parser.parse_args()

    strategies = ["faceji", "silverquant", "tradingagents"]
    if args.all:
        to_run = strategies
    elif args.strategy:
        to_run = [args.strategy]
    else:
        parser.print_help()
        return

    results = {}
    for strat_name in to_run:
        result = evaluate_strategy(strat_name)
        results[strat_name] = result

        print(f"\n{'='*50}")
        print(f"📊 {strat_name}")
        print(f"{'='*50}")
        if "error" in result:
            print(f"  ❌ {result['error']}")
        else:
            print(f"  SCORE (Sortino) : {result['score']}")
            print(f"  总收益         : {result['total_return_pct']:+.2f}%")
            print(f"  年化           : {result['annualized_return_pct']:+.2f}%")
            print(f"  Sharpe         : {result['sharpe_ratio']}")
            print(f"  最大回撤       : {result['max_drawdown_pct']:.2f}%")
            print(f"  胜率           : {result['win_rate_pct']:.1f}% ({result['trade_count']}笔)")
            print(f"  组合终值       : ¥{result['final_value']:,.0f}")
            print(f"  标的数         : {result['stocks_with_data']}")

        if not args.no_log and "error" not in result:
            save_to_run_log(strat_name, result)

    # baseline check
    if args.check_baseline and results:
        baseline_file = CACHE_DIR / "baseline.json"
        if baseline_file.exists():
            with open(baseline_file) as f:
                baseline = json.load(f)
            for name, result in results.items():
                if "error" not in result:
                    old = baseline.get(name, {}).get("score", 0)
                    new = result["score"]
                    status = "✅ 更好" if new > old else ("⚠️ 持平" if abs(new - old) < 0.01 else "❌ 退化")
                    print(f"  {name}: 基线{old:.4f} -> 当前{new:.4f} {status}")


if __name__ == "__main__":
    main()