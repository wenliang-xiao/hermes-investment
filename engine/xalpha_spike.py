"""xalpha 适配层 spike — 用 baostock 真实A股数据构造 xalpha basicinfo, 跑通 trade 引擎.

验证链: baostock日线 → AStockInfo(最小实现 shengou/shuhui) → xalpha.trade 生成净值 → 指标合理.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd


class AStockInfo:
    """最小 A 股 info 对象 — 满足 xalpha trade 引擎契约 (基于 basicinfo 语义).

    xalpha 基金式契约: price 需有 date/netvalue/comment 三列;
    shengou(value,date)->(realdate, -cash, +share); shuhui(share,date,...)->(realdate, +cash, -share).
    A 股以 100 股 / 手 为单位, 佣金+滑点计入成本.
    """

    def __init__(self, code: str, name: str, df: pd.DataFrame, rate: float = 0.0003,
                 lot_size: int = 100, enforce_lot: bool = True):
        self.code = code
        self.name = name
        self.rate = rate  # 佣金费率
        self.lot_size = lot_size
        self.enforce_lot = enforce_lot
        self.specialdate = []
        self.fenhongdate = []
        self.zhesuandate = []
        # df: ['date','close'] → 转 xalpha 格式
        p = df.copy()
        p["netvalue"] = p["close"]
        p["comment"] = 0
        self.price = p[["date", "netvalue", "comment"]].reset_index(drop=True)
        self.price["date"] = pd.to_datetime(self.price["date"])

    # ── xalpha 契约: 申购(买入) ──
    def shengou(self, value, date, fee=None):
        """value 金额买入 → (成交日, -现金, +份额). 默认 A股按手取整; enforce_lot=False 允许任意份额."""
        if fee is None:
            fee = self.rate
        row = self.price[self.price["date"] >= pd.Timestamp(date)].iloc[0]
        price = float(row.netvalue)
        if self.enforce_lot:
            qty = int(value // (price * self.lot_size)) * self.lot_size  # 整手
        else:
            qty = value / price  # 任意份额(基金式)
        if qty <= 0:
            return (row.date, 0.0, 0.0)
        cash_out = qty * price * (1 + fee)  # 佣金
        return (row.date, -round(cash_out, 2), round(float(qty), 4))

    # ── xalpha 契约: 赎回(卖出) ──
    def shuhui(self, share, date, rem, value_label=None, fee=None):
        """share 份额卖出 → (成交日, +现金, -份额). 印花税 0.05% 卖出收取."""
        if fee is None:
            fee = self.rate
        row = self.price[self.price["date"] >= pd.Timestamp(date)].iloc[0]
        price = float(row.netvalue)
        cash_in = share * price * (1 - fee - 0.0005)  # 佣金+印花税
        return (row.date, round(cash_in, 2), -float(share))


if __name__ == "__main__":
    from data.data_layer import get_stock_daily

    df = get_stock_daily("600519", days=120)  # baostock 真实日线
    assert df is not None and len(df) > 60, f"数据不足: {None if df is None else len(df)}"
    print(f"[1] baostock 天: {len(df)} 行, cols={list(df.columns)}")
    print(df.head(3).to_string())

    info = AStockInfo("600519", "贵州茅台", df, enforce_lot=False)  # spike用基金式任意份额
    print(f"[2] info.price 行数: {len(info.price)}")

    # 用 buyandhold 策略: 首日全仓
    import xalpha.policy as pol
    import xalpha.backtest as bt

    start = str(info.price["date"].iloc[0].date())
    end = str(info.price["date"].iloc[-1].date())
    cp = pol.buyandhold(info, start, end, totmoney=100000)
    print(f"[3] policy.status: {len(cp.status)} 行")
    tr = bt.trade(info, cp.status)
    # 净值序列: briefdailyreport 生成每日持仓市值
    dates = tr.price[tr.price["date"] >= tr.cftable.iloc[0].date]["date"]
    nav = pd.Series(
        [tr.briefdailyreport(d).get("currentvalue", 0) for d in dates],
        index=dates,
        name="nav",
    )
    ret = (nav.iloc[-1] / 100000 - 1) * 100
    print(f"[4] 买入持有 100k 茅台 {len(nav)}天 → 终值 {nav.iloc[-1]:,.0f} 收益 {ret:+.2f}%")
    print(f"[5] NAV 前3: {[round(v,2) for v in nav.head(3).tolist()]}")

    # quantstats 全套指标 + 报告
    import quantstats as qs
    rets = nav.pct_change().dropna()
    print(f"[6] quantstats sharpe={qs.stats.sharpe(rets):.3f} sortino={qs.stats.sortino(rets):.3f} "
          f"mdd={qs.stats.max_drawdown(rets)*100:.2f}% cagr={qs.stats.cagr(rets)*100:.2f}%")
    qs.reports.html(rets, title="茅台 buyandhold spike", output="/tmp/xa_spike_report.html")
    print("[7] quantstats HTML OK")
    print("SPIKE PASSED" if ret != 0 and abs(ret) < 30 else "CHECK")