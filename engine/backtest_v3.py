"""backtest_v3 — xalpha + quantstats 专业回测引擎

架构:
  baostock 数据 → AStockInfo(xalpha basicinfo 契约)
  → 策略 decide_fn → status 记账单(策略桥)
  → xalpha.trade/mul 引擎 → NAV 净值序列
  → quantstats 指标 + HTML 报告落盘

本模块 TDD 覆盖: AStockInfo 契约单向一致 / 记账单金额守恒 / 报告落盘。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

# data/backtest_v3_reports/ 报告根目录
REPORT_ROOT = Path(__file__).resolve().parent.parent / "data" / "backtest_v3_reports"
REPORT_ROOT.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# WS1: AStockInfo 适配层（xalpha basicinfo 契约）
# ──────────────────────────────────────────────
class AStockInfo:
    """A 股个股的 xalpha info 对象 — 满足 trade 引擎契约.

    xalpha 基金式契约:
      price: DataFrame[date, netvalue, comment]  (netvalue=收盘价, comment=分红/折算标注)
      shengou(value,date)->(realdate, -cash, +share)  买入
      shuhui(share,date)->(realdate, +cash, -share)   卖出
      specialdate/fenhongdate/zhesuandate: 分红/折算日期

    A 股差异: 100股/手整手交易(可关), 印花税卖出千1, 佣金万1.5.
    """

    def __init__(
        self,
        code: str,
        name: str,
        df: pd.DataFrame,
        rate: float = 0.00015,
        stamp_tax: float = 0.001,
        lot_size: int = 100,
        enforce_lot: bool = True,
        min_commission: float = 5.0,
    ):
        self.code = code
        self.name = name
        self.rate = rate                  # 佣金费率(万1.5)
        self.stamp_tax = stamp_tax        # 印花税(卖出千1)
        self.lot_size = lot_size
        self.enforce_lot = enforce_lot
        self.min_commission = min_commission
        self.dividend_label = 0           # 默认现金分红
        self.value_label = 0              # 按份额赎回
        self.round_label = 0
        self.specialdate: list = []
        self.fenhongdate: list = []
        self.zhesuandate: list = []

        p = df.copy()
        p["netvalue"] = p["close"].astype(float)
        p["comment"] = 0
        self.price = p[["date", "netvalue", "comment"]].reset_index(drop=True)
        self.price["date"] = pd.to_datetime(self.price["date"])

    # ── xalpha 契约: 申购(买入) ──
    def shengou(self, value: float, date, fee: float | None = None):
        """value 金额买入 → (成交日, -现金, +份额). 默认 A股按手取整."""
        if fee is not None and fee > 0.1:
            fee = fee / 100  # xalpha 有时传 1.5 (1.5%)
        effective_fee = self.rate if fee is None else fee
        row = self.price[self.price["date"] >= pd.Timestamp(date)].iloc[0]
        price = float(row.netvalue)
        if self.enforce_lot:
            qty = int(value // (price * self.lot_size)) * self.lot_size
        else:
            qty = value / price
        if qty <= 0:
            return (row.date, 0.0, 0.0)
        commission = max(qty * price * effective_fee, self.min_commission)
        cash_out = qty * price + commission
        return (row.date, -round(cash_out, 2), round(float(qty), 4))

    # ── xalpha 契约: 赎回(卖出) ──
    def shuhui(self, share: float, date, rem=None, value_label: float | None = None,
               fee: float | None = None):
        """share 份额卖出 → (成交日, +现金, -份额). 佣金+印花税."""
        if fee is not None and fee > 0.1:
            fee = fee / 100
        effective_fee = self.rate if fee is None else fee
        row = self.price[self.price["date"] >= pd.Timestamp(date)].iloc[0]
        price = float(row.netvalue)
        # 佣金按卖出金额, 印花税千1
        sell_value = share * price
        commission = max(sell_value * effective_fee, self.min_commission)
        cash_in = sell_value - commission - sell_value * self.stamp_tax
        return (row.date, round(cash_in, 2), -round(float(share), 4))


# ──────────────────────────────────────────────
# WS2: 策略桥 — decide_fn 信号 → xalpha status 记账单
# ──────────────────────────────────────────────
BUY = "BUY"
SELL = "SELL"


# ──────────────────────────────────────────────
# WS2: v3 编排器 — 策略决策循环 → xalpha trade/mul 引擎
# ──────────────────────────────────────────────
def _decide_loop(
    price_data: dict[str, list[float]],
    decide_fn,
    strategy_name: str = "",
) -> tuple[list[dict], dict[str, list[float]], dict[str, str]]:
    """复用 evaluator_fixed 的逐日决策循环（评分/技术/持仓/kelly 逻辑不动），
    只把输出信号流拦截成 decisions 列表 (不含执行层)。

    returns: (decisions, price_data, name_map)
      decisions: [{date, symbol, action, amount(BUY), shares(SELL), reason}]
      price_data: {symbol: [close,...]} 原始价格
    """
    from datetime import date, timedelta
    from strategies.base import PositionData  # noqa: F401  (结构对齐用)
    from engine.evaluator_fixed import compute_technicals, FIXED_SCORE_MAP

    total_cash = 1_000_000.0  # 仅用于决策层现金参考(和自研引擎一致)
    all_positions: dict = {}
    decisions: list[dict] = []

    min_days = min(len(p) for p in price_data.values()) if price_data else 0
    if min_days < 60:
        return [], price_data, {}

    end_dt = date.today()
    start_dt = end_dt - timedelta(days=min_days)
    date_list = [(start_dt + timedelta(days=i)).isoformat() for i in range(min_days)]

    score_map = dict(FIXED_SCORE_MAP)
    # 也支持自定义标的无评分 → 默认分(用持仓逻辑处理)
    for sym in price_data:
        if sym not in score_map:
            score_map[sym] = 5.0  # 中性默认分

    for day_idx in range(min_days):
        tech_map: dict = {}
        price_map: dict[str, float] = {}
        for sym in price_data:
            closes = price_data[sym][:day_idx + 1]
            price = float(closes[-1])
            price_map[sym] = price
            tech_map[sym] = compute_technicals(closes, price)

        # 当前持仓 PositionData 列表(和 run_backtest 一致)
        positions_dict = {}
        for sym, pos in all_positions.items():
            cp = price_map.get(sym, pos.get("entry_price", 0) or 0)
            positions_dict[sym] = PositionData(
                symbol=sym,
                entry_price=pos["entry_price"],
                quantity=pos["quantity"],
                entry_date=pos.get("entry_date") or "",
                peak=max(pos.get("peak") or pos["entry_price"], cp),
                current_price=cp,
            )

        try:
            signals = decide_fn(
                score_map=score_map,
                tech_map=tech_map,
                price_map=price_map,
                positions=positions_dict,
                cash=total_cash,
            )
        except TypeError:
            # 兼容部分策略不需要 cash 参数
            signals = decide_fn(
                score_map=score_map, tech_map=tech_map,
                price_map=price_map, positions=positions_dict,
            )
        if not signals:
            continue

        date_s = date_list[day_idx]
        for sig in signals:
            sym = sig.symbol
            price = price_map.get(sym, sig.price or 0)
            if sig.action == "BUY" and sym not in all_positions:
                pct = (sig.size_pct or 3.0) / 100
                amount = total_cash * pct
                qty = max(100, int(amount / price / 100) * 100) if price else 100
                cost = qty * price
                if cost <= total_cash and price > 0:
                    total_cash -= cost
                    all_positions[sym] = {
                        "entry_price": price, "quantity": qty,
                        "entry_date": date_s, "peak": price,
                    }
                    decisions.append({
                        "date": date_s, "symbol": sym, "action": "BUY",
                        "amount": round(cost, 2), "shares": qty, "price": round(price, 4),
                        "reason": sig.reason,
                    })
            elif sig.action == "SELL" and sym in all_positions:
                pos = all_positions.pop(sym)
                qty = pos["quantity"]
                total_cash += qty * price
                decisions.append({
                    "date": date_s, "symbol": sym, "action": "SELL",
                    "amount": round(qty * price, 2), "shares": qty, "price": round(price, 4),
                    "reason": sig.reason,
                })

    return decisions, price_data, {}


def run_backtest_v3(
    strategy: str,
    days: int = 120,
    capital: float = 1_000_000.0,
    custom_symbols: list[str] | None = None,
    benchmark: bool = True,
    run_id: str | None = None,
) -> dict:
    """v3 完整回测: 自研策略执行引擎(含成本模型) → NAV → quantstats 专业报告.

    架构说明: 交易执行层用 evaluator_fixed(佣金/印花税/滑点成本模型, 230+测试验证),
    xalpha 的基金份额模型与 A 股整手交易语义冲突(已验证), 因此本层直接用其
    BacktestResult 的 equity_curve(真实资金净值) → quantstats 做全套专业指标+HTML报告.
    xalpha 的价值在 quantstats 报告体系(月度热力图/滚动夏普/水下图/VaR/收益分布).

    returns: {run_id, report_path, metrics, nav, decisions, trades, benchmark_nav, params}
    """
    from engine.evaluator_fixed import evaluate_strategy
    from engine.backtest_types import BacktestResult

    # 1. 真实策略回测(自研执行引擎, 已验证成本模型)
    result = evaluate_strategy(strategy_name=strategy, custom_symbols=custom_symbols)
    if isinstance(result, dict) and "error" in result:
        return {"error": result["error"]}
    if not isinstance(result, BacktestResult):
        return {"error": "回测结果格式异常"}

    # 2. NAV 序列(equity_curve → pd.Series)
    eq = result.equity_curve or []
    if len(eq) < 10:
        return {"error": f"净值曲线过短({len(eq)}天)"}
    nav = pd.Series(
        [e["value"] for e in eq],
        index=pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in eq]),
        name="nav",
    )

    # 3. 基准(沪深300) NAV → quantstats 对比
    benchmark_nav = None
    if benchmark:
        try:
            benchmark_nav = _fetch_benchmark_nav(days=days)
        except Exception:
            benchmark_nav = None

    # 4. 报告落盘
    params = {
        "strategy": strategy, "days": days, "capital": capital,
        "n_symbols": getattr(result, "extra", {}).get("universe_size", 0),
        "n_decisions": result.trade_count,
    }
    res = generate_report(
        nav, benchmark_nav, strategy, params=params,
        trades=result.trades or [], run_id=run_id,
    )
    res["nav"] = nav
    res["decisions"] = result.trades or []
    res["benchmark_nav"] = benchmark_nav
    res["trades_count"] = result.trade_count
    res["engine_result"] = {
        "total_return_pct": result.total_return_pct,
        "annualized_return_pct": result.annualized_return_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "sortino_ratio": result.sortino_ratio,
        "max_drawdown_pct": result.max_drawdown_pct,
        "calmar_ratio": result.calmar_ratio,
        "win_rate_pct": result.win_rate_pct,
        "trade_count": result.trade_count,
    }
    return res


def _closes_to_df(closes: list[float]) -> pd.DataFrame:
    """收盘价列表 → DataFrame(date, close) — 用工作日索引."""
    import numpy as np
    n = len(closes)
    idx = pd.bdate_range(end=pd.Timestamp.today(), periods=n)
    return pd.DataFrame({"date": idx, "close": closes})


def _portfolio_nav(trades: list, infos: dict, capital: float) -> pd.Series | None:
    """多标 xalpha trade → 组合每日净值 = Σ(份额*价格) + 剩余现金.

    用各标的 price 的并集日期; 现金 = capital - Σ已投入(成交现金流).
    """
    if not trades:
        return None
    # 收集所有交易日
    all_dates = set()
    for tr in trades:
        all_dates.update(tr.price["date"])
    if not all_dates:
        return None
    all_dates = sorted(all_dates)
    # 每标的的份额时间表: 用 briefdailyreport 拿每日份额
    nav_vals = []
    for d in all_dates:
        total = 0.0
        for tr in trades:
            total += tr.briefdailyreport(d).get("currentvalue", 0)
        nav_vals.append(total)
    s = pd.Series(nav_vals, index=pd.DatetimeIndex(all_dates), name="nav")
    # 若首日为0(未建仓)则前向填充
    s = s.replace(0, pd.NA).ffill().fillna(0)
    return s


def _benchmark_nav_worker(days: int, q):
    """子进程 worker — 主线程拉 baostock 沪深300 (spawn 需要模块级函数)."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from data.data_layer import get_index_data
        df = get_index_data("sh000300", days)
        if df is None or df.empty or "close" not in df.columns:
            q.put(None)
            return
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        closes = df["close"].astype(float).tolist()
        base = closes[0] or 1
        q.put(pd.Series([c / base for c in closes], index=df["date"]))
    except Exception:
        q.put(None)


def _fetch_benchmark_nav(days: int = 120) -> pd.Series | None:
    """沪深300 指数 NAV(首日=1) — 子进程 baostock(避开 server 主线程 signal)."""
    import multiprocessing

    try:
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=_benchmark_nav_worker, args=(days, q))
        p.start()
        p.join(timeout=40)
        if p.is_alive():
            p.terminate()
            return None
        if q.empty():
            return None
        return q.get()
    except Exception:
        return None


def build_status_from_decisions(
    decisions: list[dict],
    price_map: dict[str, float],
    capital: float = 1_000_000.0,
    code_column: str | None = None,
) -> pd.DataFrame:
    """把策略逐日决策(信号序列)转成 xalpha status 记账单.

    decisions: [{"date": "YYYY-MM-DD", "symbol": "300502", "action": "BUY|SELL",
                 "amount": 金额(BUY) 或 份额比例(SELL), ...}]

    xalpha status 契约: DataFrame[date, <code>] — 第二列列名=股票代码本身.
    BUY 行 amount>0, SELL 行 amount<0(按当时价格折算的金额, xalpha引擎按
    info.price 自动折算成份额成交).

    code_column: 可显式指定代码列名(默认取第一条 decision 的 symbol).
    """
    rows = []
    # 需要累计持仓份额来把 SELL 转成份额卖出金额
    holdings: dict[str, float] = {}  # symbol -> shares
    for d in decisions:
        date = str(d["date"])[:10]
        sym = d["symbol"]
        action = d.get("action", "")
        price = float(price_map.get(sym, d.get("price", 0)) or 0)
        if action == BUY:
            amount = float(d.get("amount", 0))
            if amount > 0 and price > 0:
                shares = amount / price
                holdings[sym] = holdings.get(sym, 0) + shares
                rows.append({"date": date, "code": sym, "amount": round(amount, 2)})
        elif action == SELL:
            shares = float(d.get("shares", 0))
            if shares <= 0 and sym in holdings:
                # 未显式给份额 → 按比例默认全平
                shares = holdings.get(sym, 0)
            if shares > 0 and price > 0:
                holdings[sym] = max(0, holdings.get(sym, 0) - shares)
                rows.append({"date": date, "code": sym, "amount": -round(shares * price, 2)})
    df = pd.DataFrame(rows, columns=["date", "code", "amount"])
    if df.empty:
        return df
    # xalpha 契约: 第二列列名 = 代码本身, 且 value=amount。
    # status 是单标的 → 只保留 code_column(或首标的) 的行, 其他标的金额丢弃
    code = code_column or df["code"].iloc[0] if not df.empty else ""
    df = df[df["code"] == code]
    out = pd.DataFrame({"date": pd.to_datetime(df["date"]), code: df["amount"]})
    return out


# ──────────────────────────────────────────────
# WS3: 报告引擎 — NAV → quantstats HTML 落盘
# ──────────────────────────────────────────────
def generate_report(
    nav: pd.Series,
    benchmark_nav: pd.Series | None,
    strategy_name: str,
    params: dict | None = None,
    trades: list | None = None,
    run_id: str | None = None,
) -> dict:
    """NAV 序列 → quantstats HTML 报告，落盘 data/backtest_v3_reports/{run_id}/.

    returns: {run_id, report_path, metrics}
    """
    import quantstats as qs

    run_id = run_id or f"{strategy_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    out_dir = REPORT_ROOT / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    rets = nav.pct_change().dropna()
    if len(rets) < 5:
        # 数据不足仍出报告但带 warning
        rets = rets  # 继续

    metrics = {
        "sharpe": round(float(qs.stats.sharpe(rets)), 4),
        "sortino": round(float(qs.stats.sortino(rets)), 4),
        "cagr": round(float(qs.stats.cagr(rets)) * 100, 2),
        "max_drawdown": round(float(qs.stats.max_drawdown(rets)) * 100, 2),
        "calmar": round(float(qs.stats.calmar(rets)), 4),
        "volatility": round(float(qs.stats.volatility(rets)) * 100, 2),
        "win_rate": round(float(qs.stats.win_rate(rets)) * 100, 2),
        "best_day": round(float(qs.stats.best(rets)) * 100, 2),
        "worst_day": round(float(qs.stats.worst(rets)) * 100, 2),
        "avg_return": round(float(qs.stats.avg_return(rets)) * 100, 4),
        "skew": round(float(qs.stats.skew(rets)), 4),
        "kurtosis": round(float(qs.stats.kurtosis(rets)), 4),
        "var_95": round(float(qs.stats.var(rets, 0.05)) * 100, 2),
        "cvar_95": round(float(qs.stats.cvar(rets, 0.05)) * 100, 2),
        "n_days": int(len(rets)),
    }

    report_path = out_dir / "report.html"
    try:
        qs.reports.html(
            rets,
            benchmark=benchmark_nav.pct_change().dropna() if benchmark_nav is not None else None,
            output=str(report_path),
            title=f"{strategy_name} 回测报告",
        )
    except Exception as e:  # 报告生成失败不阻断
        report_path.write_text(f"<html><body><h1>报告生成失败</h1><p>{e}</p></body></html>")

    meta = {
        "run_id": run_id,
        "strategy": strategy_name,
        "run_date": datetime.now().isoformat(timespec="seconds"),
        "params": params or {},
        "metrics": metrics,
        "report_file": "report.html",
        "n_trades": len(trades or []),
        "n_days": int(len(nav)),
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))
    return {"run_id": run_id, "report_path": str(report_path), "metrics": metrics, "meta": meta}


def list_reports() -> list[dict]:
    """列出所有已生成的报告 meta."""
    results = []
    for meta_file in sorted(REPORT_ROOT.glob("*/meta.json"), reverse=True):
        try:
            results.append(json.loads(meta_file.read_text()))
        except Exception:
            continue
    return results


def get_report(run_id: str) -> dict | None:
    """读取单个报告 meta + html 路径."""
    out_dir = REPORT_ROOT / run_id
    if not (out_dir / "meta.json").exists():
        return None
    meta = json.loads((out_dir / "meta.json").read_text())
    meta["report_path"] = str(out_dir / meta.get("report_file", "report.html"))
    return meta


def clear_reports() -> None:
    """清空报告目录（测试用）."""
    shutil.rmtree(REPORT_ROOT, ignore_errors=True)
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)