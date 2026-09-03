"""
evaluator_fixed.py — 固定评估器

╔══════════════════════════════════════════════════════════╗
║  本文件是固定评估口径。一旦确定，禁止为提分而修改。        ║
║  HL 循环只允许修改 strategies/ 下的策略文件。             ║
║  要提分，只能改 strategies/*.py 里的逻辑和参数。          ║
╚══════════════════════════════════════════════════════════╝

用法:
    python evaluator_fixed.py faceji                          # 评估面基策略
    python evaluator_fixed.py silverquant                     # 评估SilverQuant
    python evaluator_fixed.py tradingagents                   # 评估TradingAgents
    python evaluator_fixed.py --all                           # 评估全部三个策略
    python evaluator_fixed.py faceji --check-baseline         # 与已接受基线对比
    python evaluator_fixed.py faceji --walk-forward --cycles 3  # Walk-Forward评估
    python evaluator_fixed.py --all --walk-forward            # 全部策略WF评估
"""
from __future__ import annotations

import json
import math
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
import functools
from dataclasses import dataclass

from engine.backtest_types import BacktestResult

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


def build_universe_with_delisted(base_symbols: list[str] | None = None,
                                 delisted_limit: int = 30) -> list[str]:
    """把历史退市股加入回测池，消除幸存者偏差。

    base_symbols: 基准股票池(默认 FIXED_UNIVERSE 的 symbol)。
    delisted_limit: 纳入退市股数量上限(按退市日降序, 最近退市的优先)。
    返回: 合并后的 symbol 列表(含退市股, 去重保序)。
    """
    base = base_symbols or [s["symbol"] for s in FIXED_UNIVERSE]
    try:
        from data.data_layer import get_delisted_stocks
        delisted = get_delisted_stocks()
    except Exception:  # noqa: BLE001 - 退市股名单拉取失败时退回基准池
        delisted = []
    if not delisted:
        return base
    recent = sorted(delisted, key=lambda x: x.get("out_date", ""), reverse=True)[:delisted_limit]
    codes = [d["code"] for d in recent
             if d.get("code") and len(str(d["code"])) == 6]
    return list(dict.fromkeys(base + codes))


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
# Walk-Forward Split
# ──────────────────────────────────────────────
@dataclass
class WalkForwardCycle:
    """单次 Walk-Forward 滚动的起止索引"""
    train_start: int
    train_end: int
    test_start: int
    test_end: int

class WalkForwardSplit:
    """Walk-Forward 时间序列分割

    Train{252d} + Test{63d}, 滚动 cycles 次, stride=63
    每次移动 63 天（一个测试窗口的宽度），前一个 test 被纳入后一个 train。
    共产生 cycles 个滚动窗。

    时间线 (cycles=3):
        W1: Train[0:252]   Test[252:315]   ← 第1个测试结果
        W2: Train[63:315]  Test[315:378]    ← 第2个
        W3: Train[126:378] Test[378:441]    ← 第3个
        最终: 汇总 3 个 test 窗口的结果
    """

    def __init__(self, total_days: int, train_days: int = 252, test_days: int = 63, cycles: int = 3):
        self.train_days = train_days
        self.test_days = test_days
        self.cycles = min(cycles, (total_days - train_days) // test_days)
        self.total_days = total_days

    def split(self) -> list[WalkForwardCycle]:
        if self.cycles < 1:
            return []
        result = []
        stride = self.test_days
        for i in range(self.cycles):
            test_start = self.train_days + i * stride
            test_end = test_start + self.test_days
            if test_end > self.total_days:
                break
            # For cycle 1: train starts at 0
            # For cycle 2+: shift forward by stride each time (include previous test in new train)
            train_start = i * stride
            train_end = test_start
            result.append(WalkForwardCycle(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            ))
        return result

    def describe(self) -> str:
        cycles = self.split()
        lines = [f"Walk-Forward: {self.train_days}d train + {self.test_days}d test, {len(cycles)} cycles"]
        for i, c in enumerate(cycles):
            lines.append(f"  W{i+1}: Train[{c.train_start}:{c.train_end}] → Test[{c.test_start}:{c.test_end}]")
        return "\n".join(lines)


# ──────────────────────────────────────────────
# 数据层：拉取并缓存日线数据
# ──────────────────────────────────────────────
def load_price_history(symbol: str, days: int = FIXED_DAYS) -> list[float] | None:
    """从 data_router 获取日线收盘价，缓存到本地 pickle

    缓存 DataFrame 含 close + open（T+1 成交需要开盘价）;
    旧缓存缺 open 列时回退 close（无 T+1 能力但兼容读取）。
    """
    import numpy as np
    import pandas as pd

    cache_file = CACHE_DIR / f"{symbol}_{days}d.pkl"
    if cache_file.exists():
        df = pd.read_pickle(cache_file)
        if "close" not in df.columns:
            return None
        return df["close"].tolist()

    # 使用新的 data_router
    try:
        from data.data_router import get_history
        result = get_history(symbol, days=days)
        if result and result.get("close"):
            n = len(result["close"])

            def _col(v):
                return v if (v and len(v) == n) else [None] * n

            df = pd.DataFrame({
                "close": result["close"],
                "open": _col(result.get("open", result["close"])),
                "volume": _col(result.get("volume")),
                "amount": _col(result.get("amount")),
                "pe": _col(result.get("pe")),
                "date": result.get("dates", list(range(n))),
            })
            df = df.dropna(subset=["close"]).sort_values("date")
            if len(df) >= 60:
                df.to_pickle(cache_file)
                return df["close"].tolist()
    except Exception:
        pass

    # 回退到旧的 data_layer
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


def load_price_history_open(symbol: str, days: int = FIXED_DAYS) -> list[float] | None:
    """获取日线开盘价（T+1 成交用；与 load_price_history 同缓存源）。

    缓存缺 open 列（旧缓存）时回退 close，保证不崩但无 T+1 能力。
    """
    import pandas as pd

    cache_file = CACHE_DIR / f"{symbol}_{days}d.pkl"
    if cache_file.exists():
        try:
            df = pd.read_pickle(cache_file)
            if "open" in df.columns:
                return df["open"].tolist()
            return df["close"].tolist()
        except Exception:
            return None

    # 无缓存时与 load_price_history 同源拉取一次（触发缓存写入）
    load_price_history(symbol, days)
    if cache_file.exists():
        try:
            df = pd.read_pickle(cache_file)
            if "open" in df.columns:
                return df["open"].tolist()
            return df["close"].tolist()
        except Exception:
            return None
    return None


def load_price_history_full(symbol: str, days: int = FIXED_DAYS) -> dict | None:
    """返回完整字段 dict(close/open/volume/amount/pe/dates), 供时点评分注入。

    与 load_price_history 同缓存源; 缺字段时该键为空列表。
    """
    import pandas as pd

    cache_file = CACHE_DIR / f"{symbol}_{days}d.pkl"
    if not cache_file.exists():
        load_price_history(symbol, days)
    if not cache_file.exists():
        return None
    try:
        df = pd.read_pickle(cache_file)
    except Exception:
        return None
    out = {"close": df["close"].tolist()}
    for col in ("open", "volume", "amount", "pe", "date"):
        if col in df.columns:
            out[col] = df[col].tolist()
        else:
            out[col] = []
    return out


def preload_all_data(days: int = FIXED_DAYS, custom_symbols: list[str] | None = None) -> dict[str, list[float]]:
    """预加载所有标的日线数据

    Args:
        days: 需要的数据天数（Walk-Forward 需较大值如 500+）
        custom_symbols: 自定义标的列表（None=使用 FIXED_UNIVERSE）
    """
    result: dict[str, list[float]] = {}
    if custom_symbols:
        universe = [
            {"symbol": s, "name": s} for s in custom_symbols
        ]
    else:
        universe = FIXED_UNIVERSE
    for s in universe:
        sym = s["symbol"]
        prices = load_price_history(sym, days)
        if prices:
            result[sym] = prices
            print(f"  {sym} {s['name']}: {len(prices)} 天")
    return result


def load_dates_map(days: int = FIXED_DAYS, custom_symbols: list[str] | None = None) -> dict[str, list[str]]:
    """预加载各标的真实交易日序列 (YYYY-MM-DD ISO 字符串).

    与 preload_all_data 同一缓存来源 — 直接从缓存 pickle 读 date 列,
    无缓存时从 data_router get_history 拉取 (与价格同源, 保证日期-价格对齐).
    """
    import numpy as np
    import pandas as pd

    dates_map: dict[str, list[str]] = {}
    if custom_symbols:
        universe = [{"symbol": s, "name": s} for s in custom_symbols]
    else:
        universe = FIXED_UNIVERSE
    for s in universe:
        sym = s["symbol"]
        try:
            cache_file = CACHE_DIR / f"{sym}_{days}d.pkl"
            if cache_file.exists():
                df = pd.read_pickle(cache_file)
                if "date" in df.columns:
                    dts = [str(d)[:10] for d in df["date"].tolist()]
                else:
                    dts = [str(d)[:10] for d in df.index]
            else:
                from data.data_router import get_history
                r = get_history(sym, days=days)
                if r and r.get("dates") and r.get("close"):
                    dts = [str(d)[:10] for d in r["dates"]]
                else:
                    continue
            if len(dts) >= 60:
                dates_map[sym] = dts[-len(dts):]
            elif len(dts) >= 5:
                # 测试/短数据窗口允许 (>=5天即可用)
                dates_map[sym] = dts[-len(dts):]
        except Exception:
            continue
    return dates_map


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

    # ATR (14日平均真实波幅, 基于 close 简化: TR=|close-prev_close|; 无 high/low 源)
    if n >= 15:
        trs = [abs(close_arr[i] - close_arr[i - 1]) for i in range(1, 15)]
        atr = float(np.mean(trs))
        te["atr"] = round(atr, 4)
        te["atr_pct"] = round(atr / price * 100, 2) if price > 0 else 0.0
    else:
        te["atr"] = 0.0
        te["atr_pct"] = 0.0

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
        psig = float(pd.Series(close_arr[:-1]).ewm(span=9).mean().iloc[-1]) if n > 26 else sig
        if macd > sig and pmacd <= psig:
            te["macd_signal"] = "金叉"
        elif macd < sig and pmacd >= psig:
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
    dates_map: dict[str, list[str]] | None = None,
    use_t1: bool = True,
    use_point_in_time: bool = False,
) -> dict:
    """固定评估器的回测核心。

    对每个标的独立运行策略，最后汇总计算组合级指标。

    dates_map: {symbol: [YYYY-MM-DD,...]} 真实交易日序列。传了就用真实
    交易日(与数据对齐), 不传退回旧的自然日倒推逻辑。

    use_t1: True = 信号 T 日收盘生成, T+1 开盘价成交(消除前视);
            False = 旧行为: 信号当日收盘价成交。

    use_point_in_time: True = 每 5 交易日用时点评分重算评分(消除评分前视);
            False = 固定 FIXED_SCORE_MAP(旧行为, 前视)。默认 False 保持向后兼容,
            供新旧评分并行对比(ADR-001 精神)。
    """
    from strategies.base import PositionData, Signal

    opens_map: dict[str, list[float]] = {}
    # ── 临时兼容: 保持旧签名 (price_data 可能已是 dict 或仍为纯 list)
    if isinstance(price_data, dict) and price_data and isinstance(
            next(iter(price_data.values())), dict):
        # 新版: {"close": [...], "open": [...], "dates": [...]}
        pd_new = price_data
        opens_map = {s: list(v.get("open", v["close"])) for s, v in pd_new.items()}
        price_data = {s: v["close"] for s, v in pd_new.items()}
        dates_map = dates_map or {s: v.get("dates", []) for s, v in pd_new.items()}

    total_cash = INITIAL_CASH
    all_positions: dict[str, PositionData] = {}
    equity_curve: list[float] = []
    all_trades: list[dict] = []
    trade_count = 0
    closed_count = 0
    win_count = 0

    # 找出最短的时间序列
    min_days = min(len(p) for p in price_data.values()) if price_data else 0
    if min_days < 60:
        return {"error": f"数据不足(最少60天, 实际{min_days}天)"}  # type: ignore[return-value]

    # 生成日期序列: 优先用真实交易日(dates_map), 退回旧的自然日倒推
    if dates_map:
        # 取最短标的的 dates 尾部(与 min_days 对齐)
        cand = [d for d in dates_map.values() if d]
        if cand:
            shortest = min(cand, key=len)
            date_list = shortest[-min_days:] if len(shortest) >= min_days else shortest
            # 若因停牌数据长度不一, 以首个有值的为准向后补齐不足部分用自然日
            while len(date_list) < min_days:
                last_d = date_list[-1] if date_list else "2026-01-01"
                from datetime import date as _d, timedelta as _td
                nxt = (_d.fromisoformat(last_d) + _td(days=1)).isoformat()
                date_list.append(nxt)
        else:
            end_dt = date.today()
            start_dt = end_dt - timedelta(days=min_days)
            date_list = [(start_dt + timedelta(days=i)).isoformat() for i in range(min_days)]
    else:
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=min_days)
        date_list = [(start_dt + timedelta(days=i)).isoformat() for i in range(min_days)]

    # 逐日推进
    score_map = dict(FIXED_SCORE_MAP)  # 固定评分 (use_point_in_time=False 时用)

    # T+1 机制: 前一交易日生成的信号, 本交易日开盘价成交
    pending_signals: list = []

    # P0-1 (2026-09-01): 时点评分 — 每 5 交易日用时点评分重算, 消除"固定评分"前视。
    # 仅 use_point_in_time=True 时启用; 评分失败降级沿用上次, 不崩。
    _symbols = list(price_data.keys())
    _rescore_every = 5
    _last_rescore = -10**9
    _full_data: dict = {}  # 惰性加载完整字段(close/open/volume/amount/pe/dates), 供时点评分注入

    def _rescore(day_idx: int):
        nonlocal score_map, _last_rescore, _full_data
        as_of = date_list[day_idx] if day_idx < len(date_list) else date_list[-1]
        injected = {}
        for sym in _symbols:
            closes = price_data.get(sym, [])
            dts = (dates_map or {}).get(sym, [])
            n = min(day_idx + 1, len(closes))
            if n <= 0:
                continue
            if sym not in _full_data:
                try:
                    _full_data[sym] = load_price_history_full(sym, days=FIXED_DAYS) or {}
                except Exception:
                    _full_data[sym] = {}
            fd = _full_data.get(sym, {})

            def _tail(seq):
                seq = seq or []
                return list(seq[:n]) if len(seq) >= n else list(seq)

            injected[sym] = {
                "close": list(closes[:n]),
                "dates": _tail(fd.get("dates")) or _tail(dts) or [str(i) for i in range(n)],
                "open": _tail(fd.get("open")),
                "volume": _tail(fd.get("volume")),
                "amount": _tail(fd.get("amount")),
                "pe": _tail(fd.get("pe")),
            }
        try:
            from engine.factor_engine import FactorEngine, convert_v4_to_v3
            results = FactorEngine().score_batch(_symbols, as_of_date=as_of, price_series=injected)
            score_map = {r["symbol"]: convert_v4_to_v3(r["composite"]) for r in results}
        except Exception as e:
            print(f"[backtest] 时点评分失败(沿用上次评分): {e}", flush=True)
        _last_rescore = day_idx

    def _execute_signal(sig, exec_price: float, day_idx: int):
        """执行单条信号 (SELL 先, BUY 后) — 共享 T+1 与旧模式执行逻辑."""
        nonlocal total_cash, trade_count, closed_count, win_count
        if sig.action == "SELL" and sig.symbol in all_positions:
            pos = all_positions[sig.symbol]
            # 使用成本模型
            try:
                from engine.cost_model import calc_adjusted_price
                adjusted_price, cost_detail = calc_adjusted_price(exec_price, pos.quantity, "sell", sig.symbol)
            except Exception:
                slippage_cost = exec_price * SLIPPAGE
                adjusted_price = exec_price - slippage_cost
                cost_detail = {"total": max(exec_price * SLIPPAGE * pos.quantity, MIN_COMMISSION)}
            net_proceeds = adjusted_price * pos.quantity
            pnl = net_proceeds - (pos.entry_price * pos.quantity)
            total_cash += net_proceeds
            if pnl > 0:
                win_count += 1
            trade_count += 1
            closed_count += 1
            all_trades.append({
                "symbol": sig.symbol, "action": "SELL",
                "price": round(exec_price, 2), "quantity": pos.quantity,
                "pnl": round(pnl, 2), "cost": round(cost_detail.get("total", 0), 2),
                "reason": sig.reason,
                "day": day_idx,
            })
            del all_positions[sig.symbol]

        elif sig.action == "BUY" and sig.symbol not in all_positions:
            try:
                from engine.cost_model import calc_adjusted_price, calc_trade_cost
                exec_price_adj, cost_detail = calc_adjusted_price(exec_price, 100, "buy", sig.symbol)
            except Exception:
                slippage_cost = exec_price * SLIPPAGE
                exec_price_adj = exec_price + slippage_cost
                cost_detail = {"total": slippage_cost + max(exec_price * COMMISSION_RATE, MIN_COMMISSION),
                               "commission": max(exec_price * COMMISSION_RATE, MIN_COMMISSION)}
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

    for day_idx in range(min_days):
        # 降频重算评分 (时点评分模式): 每 _rescore_every 个交易日重算, 其余沿用
        if use_point_in_time and (day_idx == 0 or (day_idx - _last_rescore) >= _rescore_every):
            _rescore(day_idx)

        # 构建当日 market data
        tech_map: dict[str, dict] = {}
        price_map: dict[str, float] = {}
        for sym in price_data:
            closes = price_data[sym][:day_idx + 1]
            price = float(closes[-1])
            price_map[sym] = price
            tech_map[sym] = compute_technicals(closes, price)

        # T+1: 先执行上一交易日生成的信号, 成交价 = 今日开盘价 (消除前视)
        if use_t1 and pending_signals:
            for sig in pending_signals:
                op_arr = opens_map.get(sig.symbol, [])
                raw = float(op_arr[day_idx]) if day_idx < len(op_arr) and op_arr[day_idx] else price_map.get(sig.symbol, sig.price)
                exec_price = raw or sig.price
                _execute_signal(sig, exec_price, day_idx)
            pending_signals = []

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

        if use_t1:
            # 信号 T 日收盘生成 → 存入队列, T+1 日开盘价成交
            pending_signals = list(signals)
        else:
            # 旧模式: 信号当日收盘价立即成交
            for sig in signals:
                exec_price = price_map.get(sig.symbol, sig.price) or sig.price
                _execute_signal(sig, exec_price, day_idx)

        # 当日组合价值
        position_value = sum(
            price_map.get(sym, 0) * pos.quantity
            for sym, pos in all_positions.items()
        )
        total_value = total_cash + position_value
        equity_curve.append(total_value)

    # ─── 构建 BacktestResult ───
    # 添加日期到 equity_curve
    eq_curve = [
        {"date": date_list[i], "value": round(equity_curve[i], 2)}
        for i in range(min_days)
    ]

    # 添加日期到 trades
    dated_trades = []
    for t in all_trades:
        d_idx = t.get("day", 0)
        t_date = date_list[d_idx] if d_idx < len(date_list) else date_list[-1]
        dated_trades.append({
            "date": t_date,
            "symbol": t.get("symbol", ""),
            "action": t.get("action", ""),
            "price": t.get("price", 0),
            "qty": t.get("quantity", 0),
            "pnl": t.get("pnl"),
            "reason": t.get("reason", ""),
        })

    # 计算指标
    metrics = _compute_metrics(equity_curve, all_trades, trade_count, win_count,
                               strategy_name, score_map, price_data, min_days,
                               closed_count=closed_count)

    mdd = metrics.get("max_drawdown_pct", 0.0)
    annualized = metrics.get("annualized_return_pct", 0.0)
    calmar = annualized / mdd if mdd > 0 else 0.0

    return BacktestResult(
        strategy_name=strategy_name,
        start_date=date_list[0],
        end_date=date_list[-1],
        initial_cash=INITIAL_CASH,
        final_value=metrics.get("final_value", INITIAL_CASH),
        total_return_pct=metrics.get("total_return_pct", 0.0),
        annualized_return_pct=annualized,
        sharpe_ratio=metrics.get("sharpe_ratio", 0.0),
        sortino_ratio=metrics.get("sortino_ratio"),
        max_drawdown_pct=mdd,
        calmar_ratio=round(calmar, 4),
        win_rate_pct=metrics.get("win_rate_pct", 0.0),
        trade_count=metrics.get("trade_count", 0),
        equity_curve=eq_curve,
        trades=dated_trades,
        benchmark=None,
        extra={
            "total_days": metrics.get("total_days", min_days),
            "universe_size": metrics.get("universe_size", len(score_map)),
            "stocks_with_data": metrics.get("stocks_with_data", len(price_data)),
            "scoring_mode": "point_in_time" if use_point_in_time else "fixed_score",
            "survivorship_bias": "fixed_universe(19只当前龙头,未含历史退市/剔除标的)",
        },
    )


def _compute_metrics(
    equity_curve: list[float],
    trades: list[dict],
    trade_count: int,
    win_count: int,
    strategy_name: str,
    score_map: dict,
    price_data: dict,
    total_days: int,
    closed_count: int | None = None,
) -> dict:
    """计算评估指标

    closed_count: 平仓(卖出)交易数。胜率 = win_count / closed_count, 语义是
    「盈利平仓占比」, 而非 win_count / trade_count(后者分子只统计盈利卖出、
    分母却含买入, 会系统性低估胜率)。缺省时向后兼容用 trade_count。
    """
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

    # 胜率: 盈利平仓占比。优先用 closed_count(卖出数), 缺省回退 trade_count(旧行为)
    calc_closed_count = closed_count if closed_count is not None else trade_count
    calc_win_count = win_count
    win_rate = calc_win_count / calc_closed_count if calc_closed_count > 0 else 0.0

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
# Walk-Forward 评估
# ──────────────────────────────────────────────
def run_walk_forward(
    price_data: dict[str, list[float]],
    decide_fn: Callable,
    strategy_name: str,
    train_days: int = 252,
    test_days: int = 63,
    cycles: int = 3,
) -> dict:
    """Walk-Forward 评估

    将数据分为滚动 train/test 窗口，在 test 窗口上评估策略。
    最后汇总所有 test 窗口结果。
    """
    # 找最短数据序列
    min_days = min(len(p) for p in price_data.values()) if price_data else 0
    if min_days < train_days + test_days:
        return {"error": f"数据不足(需要至少{train_days+test_days}天, 实际{min_days}天)"}

    wf = WalkForwardSplit(min_days, train_days=train_days, test_days=test_days, cycles=cycles)
    windows = wf.split()
    if not windows:
        return {"error": "Walk-Forward 窗口数为0，请检查数据量"}

    print(f"\n📊 Walk-Forward 配置:")
    print(wf.describe())

    cycle_results = []
    all_trades = []

    for i, window in enumerate(windows):
        print(f"\n🔄 W{i+1}: Train[{window.train_start}:{window.train_end}] → Test[{window.test_start}:{window.test_end}]")

        # 构建 test 窗口数据（只回测 test 段）
        test_data: dict[str, list[float]] = {}
        for sym, prices in price_data.items():
            # 给策略提供到 test day 的数据（含 train 段用于技术指标计算）
            test_end = window.test_end
            if len(prices) >= test_end:
                test_data[sym] = prices[:test_end]

        # 运行回测，但只从 test_start 开始输出净值曲线
        from strategies.base import PositionData, Signal

        total_cash = INITIAL_CASH
        all_positions: dict[str, PositionData] = {}
        cycle_equity: list[float] = []
        cycle_trades: list[dict] = []
        trade_count = 0
        win_count = 0

        score_map = dict(FIXED_SCORE_MAP)

        for day_idx in range(test_end):
            tech_map: dict[str, dict] = {}
            price_map: dict[str, float] = {}
            for sym in test_data:
                closes = test_data[sym][:day_idx + 1]
                price = float(closes[-1])
                price_map[sym] = price
                tech_map[sym] = compute_technicals(closes, price)

            positions_dict: dict[str, PositionData] = {}
            for sym, pos in all_positions.items():
                cp = price_map.get(sym, pos.current_price or pos.entry_price)
                positions_dict[sym] = PositionData(
                    symbol=sym, entry_price=pos.entry_price,
                    quantity=pos.quantity, entry_date=pos.entry_date or "",
                    peak=max(pos.peak or pos.entry_price, cp),
                    current_price=cp,
                )

            signals = decide_fn(
                score_map=score_map, tech_map=tech_map, price_map=price_map,
                positions=positions_dict, cash=total_cash,
            )

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
                    if pnl > 0: win_count += 1
                    trade_count += 1
                    cycle_trades.append({
                        "symbol": sig.symbol, "action": "SELL",
                        "price": round(exec_price, 2), "quantity": pos.quantity,
                        "pnl": round(pnl, 2), "reason": sig.reason,
                        "day": day_idx, "cycle": i + 1,
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
                            peak=exec_price_adj, current_price=exec_price_adj,
                        )
                        trade_count += 1
                        cycle_trades.append({
                            "symbol": sig.symbol, "action": "BUY",
                            "price": round(exec_price, 2), "quantity": qty,
                            "cost": round(total_cost, 2), "reason": sig.reason,
                            "day": day_idx, "cycle": i + 1,
                        })

            position_value = sum(price_map.get(sym, 0) * pos.quantity for sym, pos in all_positions.items())
            total_value = total_cash + position_value
            cycle_equity.append(total_value)

        # 平掉尾盘仓位
        for sym, pos in list(all_positions.items()):
            exec_price = price_map.get(sym, pos.entry_price)
            proceeds = exec_price * pos.quantity
            commission = max(proceeds * COMMISSION_RATE, MIN_COMMISSION)
            tax = proceeds * STAMP_TAX_RATE
            net_proceeds = proceeds - commission - tax
            pnl = net_proceeds - (pos.entry_price * pos.quantity)
            total_cash += net_proceeds
            if pnl > 0: win_count += 1
            trade_count += 1
            cycle_trades.append({
                "symbol": sym, "action": "SELL",
                "price": round(exec_price, 2), "quantity": pos.quantity,
                "pnl": round(pnl, 2), "reason": "WF平仓",
                "day": test_end, "cycle": i + 1,
            })

        # 计算 test 段指标（只取 test 窗口的 equity）
        test_start_idx = max(0, window.test_start - 1)  # include first day of test
        test_equity = cycle_equity[test_start_idx:]

        if len(test_equity) > 1:
            import numpy as np
            import pandas as pd

            equity_s = pd.Series(test_equity)
            test_return = equity_s.iloc[-1] / equity_s.iloc[0] - 1.0
            daily_ret = equity_s.pct_change().dropna()
            sharpe = float(daily_ret.mean()) / float(daily_ret.std()) * math.sqrt(252) if float(daily_ret.std()) > 0 else 0
            dstd = float(daily_ret[daily_ret < 0].std())
            sortino = float(daily_ret.mean()) / dstd * math.sqrt(252) if dstd > 0 else 0
            running_max = equity_s.cummax()
            dd = float(-((equity_s - running_max) / running_max).min())

            cycle_result = {
                "cycle": i + 1,
                "test_days": len(test_equity),
                "return_pct": round(test_return * 100, 2),
                "sharpe": round(sharpe, 4),
                "sortino": round(sortino, 4),
                "max_drawdown_pct": round(dd * 100, 2),
                "trade_count": trade_count,
                "win_count": win_count,
            }
        else:
            cycle_result = {
                "cycle": i + 1,
                "test_days": len(test_equity),
                "return_pct": 0, "sharpe": 0, "sortino": 0,
                "max_drawdown_pct": 0, "trade_count": 0, "win_count": 0,
            }

        cycle_results.append(cycle_result)
        all_trades.extend(cycle_trades)

        print(f"  W{i+1}: Return={cycle_result['return_pct']:+.2f}%  "
              f"Sortino={cycle_result['sortino']:.4f}  "
              f"DD={cycle_result['max_drawdown_pct']:.2f}%")

    # ─── 汇总 ───
    if not cycle_results:
        return {"error": "无可用 cycle 结果"}

    import numpy as np
    returns = [c["return_pct"] for c in cycle_results]
    sortinos = [c["sortino"] for c in cycle_results]
    dd_list = [c["max_drawdown_pct"] for c in cycle_results]
    total_trades = sum(c["trade_count"] for c in cycle_results)
    total_wins = sum(c["win_count"] for c in cycle_results)

    master_result = {
        "strategy": strategy_name,
        "mode": "walk_forward",
        "cycles": len(cycle_results),
        "avg_return_pct": round(np.mean(returns), 2),
        "avg_sortino": round(np.mean(sortinos), 4),
        "avg_max_drawdown_pct": round(np.mean(dd_list), 2),
        "min_sortino": round(min(sortinos), 4),
        "max_sortino": round(max(sortinos), 4),
        "avg_sharpe": round(np.mean([c["sharpe"] for c in cycle_results]), 4),
        "min_return_pct": round(min(returns), 2),
        "max_return_pct": round(max(returns), 2),
        "total_trades": total_trades,
        "win_rate_pct": round(total_wins / total_trades * 100, 1) if total_trades > 0 else 0,
        "cycle_details": cycle_results,
    }

    print(f"\n{'='*50}")
    print(f"📊 Walk-Forward MASTER: {strategy_name}")
    print(f"{'='*50}")
    print(f"  平均收益     : {master_result['avg_return_pct']:+.2f}%")
    print(f"  平均Sortino  : {master_result['avg_sortino']:.4f}")
    print(f"  Sortino范围  : [{master_result['min_sortino']:.4f} ~ {master_result['max_sortino']:.4f}]")
    print(f"  平均最大回撤 : {master_result['avg_max_drawdown_pct']:.2f}%")
    print(f"  收益范围     : [{master_result['min_return_pct']:+.2f}% ~ {master_result['max_return_pct']:+.2f}%]")
    print(f"  总交易       : {master_result['total_trades']}笔, 胜率{master_result['win_rate_pct']}%")

    # 包装为 BacktestResult
    wf_annualized = master_result["avg_return_pct"]
    wf_mdd = master_result["avg_max_drawdown_pct"]
    calmar = wf_annualized / wf_mdd if wf_mdd > 0 else 0.0

    return BacktestResult(
        strategy_name=strategy_name,
        start_date=date.today().isoformat(),
        end_date=date.today().isoformat(),
        initial_cash=INITIAL_CASH,
        final_value=INITIAL_CASH * (1 + master_result["avg_return_pct"] / 100),
        total_return_pct=master_result["avg_return_pct"],
        annualized_return_pct=wf_annualized,
        sharpe_ratio=master_result["avg_sharpe"],
        sortino_ratio=master_result["avg_sortino"],
        max_drawdown_pct=wf_mdd,
        calmar_ratio=round(calmar, 4),
        win_rate_pct=master_result["win_rate_pct"],
        trade_count=master_result["total_trades"],
        equity_curve=[],
        trades=[],
        benchmark=None,
        extra={"mode": "walk_forward", "cycle_details": cycle_results, **master_result},
    )


# ──────────────────────────────────────────────
# 市场状态分析
# ──────────────────────────────────────────────
def analyze_market_regime(closes: list[float]) -> str:
    """对市场状态做粗糙分类: 牛市/熊市/震荡"""
    import numpy as np
    if len(closes) < 60:
        return "unknown"

    ret_20d = closes[-1] / closes[-20] - 1
    ret_60d = closes[-1] / closes[-60] - 1
    vol_20d = float(np.std([closes[i] / closes[i-1] - 1 for i in range(-20, 0)]))
    vol_60d = float(np.std([closes[i] / closes[i-1] - 1 for i in range(-60, 0)]))
    ma60 = np.mean(closes[-60:])
    ma200 = np.mean(closes[-200:]) if len(closes) >= 200 else ma60

    if ret_60d > 0.05 and closes[-1] > ma60 > ma200:
        return "bull"
    elif ret_60d < -0.05 and closes[-1] < ma60 < ma200:
        return "bear"
    elif abs(ret_20d) < 0.03 and vol_20d < vol_60d:
        return "consolidation"
    return "mixed"
# ──────────────────────────────────────────────
def save_to_run_log(strategy: str, result):
    """记录到实验账本（支持 BacktestResult 和 dict）"""
    run_id = f"{strategy}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = HL_RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # 保存结果
    if isinstance(result, BacktestResult):
        data = result.to_json()
    else:
        data = result
    with open(run_dir / "result.json", "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # 追加到汇总
    summary_file = HL_RUNS_DIR / "runs.jsonl"
    entry = {"run_id": run_id, "strategy": strategy,
             "timestamp": datetime.now().isoformat(), **data}
    with open(summary_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def evaluate_strategy(strategy_name: str, walk_forward: bool = False,
                       cycles: int = 3, train_days: int = 252, test_days: int = 63,
                       custom_symbols: list[str] | None = None,
                       days: int | None = None,
                       use_point_in_time: bool = False) -> BacktestResult | dict:
    """评估单个策略

    Args:
        strategy_name: 策略名
        walk_forward: 是否使用 Walk-Forward 评估
        cycles: WF 滚动次数
        train_days: WF 训练窗口天数
        test_days: WF 测试窗口天数
        custom_symbols: 自定义标的列表（None=使用 FIXED_UNIVERSE）
        days: 回测交易日窗口（None=默认 FIXED_DAYS，WF 模式自动 ≥ train+test*cycles+100）
        use_point_in_time: 时点评分模式 (True=每5日 rescore 消除前视, 慢~10x)
    """
    if walk_forward:
        data_days = max(FIXED_DAYS, train_days + test_days * cycles + 100)
    else:
        data_days = days if days and days >= 60 else FIXED_DAYS

    # 加载数据
    print(f"\n📦 加载数据{' (WF模式)' if walk_forward else ''}...")
    price_data = preload_all_data(days=data_days, custom_symbols=custom_symbols)
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

    if walk_forward:
        print(f"🏃 Walk-Forward 评估: {strategy_name} ({cycles} cycles)")
        return run_walk_forward(price_data, decide_fn, strategy_name,
                                 train_days=train_days, test_days=test_days, cycles=cycles)
    else:
        print(f"🏃 运行回测: {strategy_name} ({data_days}天窗口)")
        dates_map = load_dates_map(days=data_days, custom_symbols=custom_symbols)
        return run_backtest(price_data, decide_fn, strategy_name, dates_map=dates_map,
                            use_point_in_time=use_point_in_time)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="固定评估器")
    parser.add_argument("strategy", nargs="?", default="", help="策略名: faceji / silverquant / tradingagents")
    parser.add_argument("--all", action="store_true", help="评估全部策略")
    parser.add_argument("--check-baseline", action="store_true", help="与基线对比")
    parser.add_argument("--no-log", action="store_true", help="不写入实验账本")
    parser.add_argument("--walk-forward", action="store_true", help="Walk-Forward 评估模式")
    parser.add_argument("--cycles", type=int, default=3, help="Walk-Forward 滚动次数 (默认3)")
    parser.add_argument("--train-days", type=int, default=252, help="WF 训练窗口天数 (默认252)")
    parser.add_argument("--test-days", type=int, default=63, help="WF 测试窗口天数 (默认63)")
    parser.add_argument("--with-dsr", action="store_true", help="DSR 统计检验")
    parser.add_argument("--point-in-time", action="store_true",
                        help="时点评分模式 (True=每5日 rescore 消除前视, 慢~10x)")

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
        result = evaluate_strategy(
            strat_name,
            walk_forward=args.walk_forward,
            cycles=args.cycles,
            train_days=args.train_days,
            test_days=args.test_days,
            use_point_in_time=args.point_in_time,
        )
        results[strat_name] = result

        # 处理便捷访问（兼容 BacktestResult 和 error dict）
        is_br = isinstance(result, BacktestResult)
        is_error = isinstance(result, dict) and "error" in result

        print(f"\n{'='*50}")
        print(f"📊 {strat_name}")
        print(f"{'='*50}")
        if is_error:
            print(f"  ❌ {result['error']}")
        elif args.walk_forward:
            extra = result.extra if is_br else result
            print(f"  WF平均收益     : {extra['avg_return_pct']:+.2f}%")
            print(f"  WF平均Sortino  : {extra['avg_sortino']:.4f}")
            print(f"  WF排序范围     : [{extra['min_sortino']:.4f} ~ {extra['max_sortino']:.4f}]")
            print(f"  WF平均回撤     : {extra['avg_max_drawdown_pct']:.2f}%")
            print(f"  总交易         : {extra['total_trades']}笔, 胜率{extra['win_rate_pct']}%")
        elif is_br:
            print(f"  SCORE (Sortino) : {result.sortino_ratio}")
            print(f"  总收益         : {result.total_return_pct:+.2f}%")
            print(f"  年化           : {result.annualized_return_pct:+.2f}%")
            print(f"  Sharpe         : {result.sharpe_ratio}")
            print(f"  Sortino        : {result.sortino_ratio}")
            print(f"  Calmar         : {result.calmar_ratio}")
            print(f"  最大回撤       : {result.max_drawdown_pct:.2f}%")
            print(f"  胜率           : {result.win_rate_pct:.1f}% ({result.trade_count}笔)")
            print(f"  组合终值       : ¥{result.final_value:,.0f}")
            print(f"  标的数         : {result.extra.get('stocks_with_data', 0)}")
            print(f"  评分模式       : {result.scoring_mode}")
        else:
            print(f"  SCORE (Sortino) : {result['score']}")
            print(f"  总收益         : {result['total_return_pct']:+.2f}%")
            print(f"  年化           : {result['annualized_return_pct']:+.2f}%")
            print(f"  Sharpe         : {result['sharpe_ratio']}")
            print(f"  最大回撤       : {result['max_drawdown_pct']:.2f}%")
            print(f"  胜率           : {result['win_rate_pct']:.1f}% ({result['trade_count']}笔)")
            print(f"  组合终值       : ¥{result['final_value']:,.0f}")
            print(f"  标的数         : {result['stocks_with_data']}")

        if not args.no_log and not is_error:
            save_to_run_log(strat_name, result)

        # DSR 统计检验
        if args.with_dsr and not is_error and not args.walk_forward:
            try:
                from engine.dsr_test import compute_dsr, dsr_verdict, compare_strategies_with_dsr
                n_trials = 50
                if is_br:
                    sortino_val = result.sortino_ratio
                    n_days = result.extra.get("total_days", 120)
                else:
                    sortino_val = result.get("sortino_ratio") or result.get("score", 0)
                    n_days = result.get("total_days", 120)
                dsr, comp = compute_dsr(
                    sharpe_observed=sortino_val * 0.7,
                    n_observations=n_days,
                    n_trials=n_trials,
                )
                print(f"  DSR检验      : {dsr:.4f}")
                print(f"  {dsr_verdict(dsr)}")
            except Exception as e:
                print(f"  DSR检验失败: {e}")

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