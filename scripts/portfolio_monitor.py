"""
持仓监控引擎 — 偏离追踪+再平衡信号+风控检查
"""
from datetime import datetime
from investment_system import config
from investment_system.data.data_layer import get_stock_daily
from investment_system.scripts.stock_analyzer import StockAnalyzer


class PortfolioMonitor:
    """持仓监控"""

    def __init__(self, holdings: list = None, macro_engine=None):
        """
        holdings: [{"symbol":"300502","name":"新易盛","target_pct":0.02,"current_pct":0.025}]
        """
        self.holdings = holdings or []
        self.macro = macro_engine
        self.analyzer = StockAnalyzer(macro_engine)

    def set_holdings(self, holdings: list):
        self.holdings = holdings

    def check_rebalance(self) -> list:
        """检查再平衡信号（偏离>5%触发）"""
        signals = []
        threshold = config.RISK_PARAMS["rebalance_threshold"]
        for h in self.holdings:
            deviation = h.get("current_pct", 0) - h.get("target_pct", 0)
            if abs(deviation) > threshold:
                action = "减持" if deviation > 0 else "加仓"
                signals.append({
                    "symbol": h["symbol"],
                    "name": h.get("name", ""),
                    "target": h.get("target_pct", 0) * 100,
                    "current": h.get("current_pct", 0) * 100,
                    "deviation": deviation * 100,
                    "action": action,
                    "priority": "高" if abs(deviation) > 0.1 else "中",
                })
        return signals

    def check_risk(self) -> list:
        """风控检查"""
        warnings = []

        # 宏观风控
        if self.macro:
            switch = getattr(self.macro, "strategy_switch", "on")
            if switch == "off":
                warnings.append("🔴 宏观+趋势双空→建议空仓！")
                warnings.append("   CPI趋势偏空 + 趋势温度凉，不开新仓")

            position = getattr(self.macro, "suggest_total_position", lambda: 0.5)()
            if position < 0.3:
                warnings.append(f"🟡 建议总仓位≤{int(position*100)}%（宏观偏谨）")

        # 持仓集中度
        if self.holdings and len(self.holdings) > 0:
            top_pct = max(h.get("current_pct", 0) for h in self.holdings)
            if top_pct > 0.05:
                warnings.append(f"🟡 单票集中度{top_pct*100:.1f}%>5%，注意风险")

            total_pct = sum(h.get("current_pct", 0) for h in self.holdings)
            if total_pct > 0.8:
                warnings.append(f"🟡 总仓位{total_pct*100:.1f}%>80%，保留子弹")

        return warnings

    def monitor_stocks(self, symbols: list) -> list:
        """监控指定股票列表"""
        results = []
        for sym in symbols[:10]:
            analysis = self.analyzer.deep_analyze(sym)
            results.append(analysis)
        return results

    def check_price_alerts(self, alerts: list) -> list:
        """
        价格预警
        alerts: [{"symbol":"300502","name":"新易盛","target_price":85}]
        """
        triggered = []
        for a in alerts:
            daily = get_stock_daily(a["symbol"], 5)
            if daily.empty:
                continue
            price = float(daily.iloc[-1]["close"]) if "close" in daily.columns else float(daily.iloc[-1].iloc[3])
            target = a.get("target_price", 0)
            if target > 0:
                if price >= target:
                    triggered.append({
                        "symbol": a["symbol"],
                        "name": a.get("name", ""),
                        "price": price,
                        "target": target,
                        "level": "above",  # 突破目标价
                    })
                elif price <= target * 0.92:
                    triggered.append({
                        "symbol": a["symbol"],
                        "name": a.get("name", ""),
                        "price": price,
                        "target": target,
                        "level": "below",  # 跌破止损
                    })
        return triggered
