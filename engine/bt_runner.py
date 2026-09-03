"""backtrader 多市场回测适配层。

用 backtrader 做 A股/港股/美股多市场回测 + 多空对冲，引擎不自研。
数据来自 data_router.get_history（A股 baostock/腾讯、港股腾讯、美股 finnhub/yfinance），
backtrader 只负责回测引擎（事件驱动、成本模型、净值、多空）。

T+1 结算: backtrader 默认「信号 T 日收盘生成 → T+1 日开盘成交」即 A股 T+1。
美股/港股 T+0 用 t0=True（coc 收盘成交）。
"""
from __future__ import annotations

import backtrader as bt

from data.data_router import get_history, _detect_source


# ═══════════════════════════════════════════════
# 市场差异化 commission
# ═══════════════════════════════════════════════
class AShareCommission(bt.CommissionInfo):
    """A股: 佣金万1.5(最低5元) + 卖出印花税千1"""

    def getcommission(self, size, price):
        value = abs(size) * price
        comm = max(value * 0.00015, 5.0)
        if size < 0:
            comm += value * 0.001
        return comm


class HKCommission(bt.CommissionInfo):
    """港股: 佣金万2.5(最低3港币) + 双边印花税千1"""

    def getcommission(self, size, price):
        value = abs(size) * price
        comm = max(value * 0.00025, 3.0)
        comm += value * 0.001
        return comm


class USCommission(bt.CommissionInfo):
    """美股: 无印花税, 佣金万0.5(最低1美元)"""

    def getcommission(self, size, price):
        return max(abs(size) * price * 0.00005, 1.0)


_COMMISSION_BY_MARKET = {
    "a": AShareCommission,
    "hk": HKCommission,
    "us": USCommission,
}


def market_of(symbol: str) -> str:
    """识别标的所属市场: a(股) / hk(港股) / us(美股)。"""
    if symbol.upper().endswith(".HK"):
        return "hk"
    src = _detect_source(symbol)
    if src in ("baostock", "akshare_etf"):
        return "a"
    return "us"


def commission_for(symbol: str) -> bt.CommissionInfo:
    return _COMMISSION_BY_MARKET[market_of(symbol)]()


def load_feed(symbol: str, days: int = 250) -> bt.feeds.PandasData | None:
    """get_history 的 dict → backtrader PandasData feed。"""
    h = get_history(symbol, days)
    if not h or not h.get("dates"):
        return None
    import pandas as pd
    df = pd.DataFrame({
        "open": h["open"], "high": h["high"], "low": h["low"],
        "close": h["close"], "volume": h["volume"],
    }, index=pd.to_datetime(h["dates"]))
    df = df.dropna(subset=["close"])
    if df.empty:
        return None
    return bt.feeds.PandasData(dataname=df)


# ═══════════════════════════════════════════════
# 多空策略（long 高分组 / short 低分组）
# ═══════════════════════════════════════════════
class LongShortMomentum(bt.Strategy):
    """动量多空: 动量 > 阈值 做多(buy→净多头), < -阈值 做空(sell→净空头)。"""

    params = (
        ("lookback", 20),
        ("threshold", 0.02),
    )

    def __init__(self):
        self.moms = {}
        for d in self.datas:
            self.moms[d._name] = bt.ind.Momentum(d.close, period=self.p.lookback)

    def next(self):
        for d in self.datas:
            mom = self.moms[d._name][0]
            pos = self.getposition(d).size
            if mom > self.p.threshold and pos <= 0:
                self.buy(data=d)
            elif mom < -self.p.threshold and pos >= 0:
                self.sell(data=d)


def run_long_short(symbols: list[str], days: int = 250, cash: float = 1_000_000,
                   lookback: int = 20, threshold: float = 0.02, t0: bool = False) -> dict:
    """多空回测入口: 喂 symbols → backtrader → 返回净值 + 收益 + 各市场佣金。

    t0: True=美股/港股 T+0(信号收盘生成即成交, coc); False=A股 T+1(信号收盘生成→次日开盘成交)。
    """
    cerebro = bt.Cerebro()
    cerebro.addstrategy(LongShortMomentum, lookback=lookback, threshold=threshold)
    if t0:
        cerebro.broker.set_coc(True)
    for sym in symbols:
        feed = load_feed(sym, days)
        if feed is None:
            continue
        cerebro.adddata(feed, name=sym)
        cerebro.broker.addcommissioninfo(commission_for(sym), name=sym)
    cerebro.broker.setcash(cash)

    start = cerebro.broker.getvalue()
    results = cerebro.run()
    end = cerebro.broker.getvalue()

    return {
        "start": start,
        "end": end,
        "return_pct": round((end / start - 1) * 100, 2),
        "n_datas": len(cerebro.datas),
    }
