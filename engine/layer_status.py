"""
六层状态聚合器 — L1→L6 供六层横条
"""
from typing import Optional
from datetime import datetime, date
import logging, json, os

logger = logging.getLogger(__name__)


class LayerStatus:
    def __init__(self, weekly_trade_limit=3, total_portfolio_value=1000000,
                 target_allocation=None):
        self.weekly_trade_limit = weekly_trade_limit
        self.total_value = total_portfolio_value
        self.target_allocation = target_allocation or {
            "A股": 25, "ETF": 20, "债券": 10, "黄金": 15, "商品": 15, "美股": 20, "港股": 10,
        }

    def get_all(self, macro_state=None, positions=None,
                pool_data=None, trades_this_week=None) -> dict:
        return {
            "l1_macro": self._l1_macro(macro_state),
            "l2_allocation": self._l2_allocation(positions),
            "l3_l4_stock_picking": self._l3_l4(pool_data),
            "l5_risk": self._l5_risk(positions),
            "l6_discipline": self._l6_discipline(trades_this_week),
        }

    def _l1_macro(self, macro_state=None) -> dict:
        m = macro_state or {}
        dg = m.get("dual_gate", {})
        return {
            "dual_gate": {"macro": dg.get("macro", "?"), "trend": dg.get("trend", "?")},
            "quadrant": m.get("quadrant", "未知"),
            "trend_temp": m.get("trend_temp", "平"),
            "strategy_switch": m.get("strategy_switch", "off"),
        }

    def _l2_allocation(self, positions=None) -> dict:
        pos = positions or []
        actual = {"A股": 0.0, "ETF": 0.0, "债券": 0.0, "黄金": 0.0, "商品": 0.0, "美股": 0.0, "港股": 0.0}
        for p in pos:
            mkt = p.get("market_value", 0)
            if not mkt:
                continue
            sym = p.get("symbol", "")
            if any(kw in sym.lower() for kw in ["etf", "159", "511", "513", "518"]):
                actual["ETF"] += mkt
            elif sym.startswith(("6", "0", "3")):
                actual["A股"] += mkt
        total = sum(actual.values()) or 1
        actual_pct = {k: round(v / total * 100, 1) for k, v in actual.items()}
        return {
            "target": self.target_allocation,
            "actual": actual_pct,
            "days_to_month_end": self._days_to_month_end(),
        }

    def _l3_l4(self, pool_data=None) -> dict:
        p = pool_data or {}
        return {
            "total_candidates": len(p.get("candidates", [])),
            "new_today": p.get("new_today", 0),
            "active_chains": p.get("active_chains", []),
        }

    def _l5_risk(self, positions=None) -> dict:
        pos = positions or []
        triggered = sum(1 for p in pos if p.get("entry_price", 0) and p.get("current_price", 0)
                       and p["current_price"] <= p["entry_price"] * 0.92)
        total_mkt = sum(p.get("market_value", 0) for p in pos)
        total_cost = sum(p.get("entry_price", 0) * p.get("quantity", 0) for p in pos)
        dd = round((total_mkt - total_cost) / total_cost * 100, 2) if total_cost > 0 else 0
        if triggered > 2:
            status = "critical"
        elif triggered > 0 or dd < -10:
            status = "warning"
        else:
            status = "normal"
        return {"status": status, "triggered_stops": triggered, "max_drawdown": dd}

    def _l6_discipline(self, trades_this_week=None) -> dict:
        trades = trades_this_week or []
        return {
            "weekly_trades": len(trades),
            "weekly_limit": self.weekly_trade_limit,
            "over_limit": len(trades) > self.weekly_trade_limit,
        }

    @staticmethod
    def _days_to_month_end() -> int:
        import calendar
        t = datetime.now()
        return calendar.monthrange(t.year, t.month)[1] - t.day

    @staticmethod
    def _is_etf(code):
        return any(code.startswith(p) for p in ["159", "511", "513", "518", "510"])
