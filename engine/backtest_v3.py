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


def build_status_from_decisions(
    decisions: list[dict],
    price_map: dict[str, float],
    capital: float = 1_000_000.0,
) -> pd.DataFrame:
    """把策略逐日决策(信号序列)转成 xalpha status 记账单.

    decisions: [{"date": "YYYY-MM-DD", "symbol": "300502", "action": "BUY|SELL",
                 "amount": 金额(BUY) 或 份额比例(SELL), ...}]
    返回 DataFrame[date, code, amount]: BUY=+金额, SELL=-份额金额占比(用当时价格折算).
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
    return df


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