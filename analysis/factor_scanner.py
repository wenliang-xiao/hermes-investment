"""
多因子扫描引擎 v3.1 — 三源融合
面基6因子排序分位法 + LDS动态权重 + Vibe多时间框架

核心升级:
  1. 排序分位法（面基思想）：每个因子用百分位排名而非硬阈值打分
  2. 因子权重随宏观状态自适应（LDS原则）
  3. 多时间框架技术信号（日线+周线动量）
  4. IC:IR概念：因子得分反映相对强度
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from investment_system import config
from investment_system.data.data_layer import (get_stock_daily, get_financial_report,
                         get_financial_history, calc_pe_percentile, get_volume_signal)


class FactorScanner:
    """全市场多因子扫描器 — 排序分位法"""

    def __init__(self, macro_engine=None):
        self.macro = macro_engine
        self.weights = config.FACTOR_WEIGHTS["default"]
        self._cache = {}  # 天内缓存stock basic

    def set_macro(self, macro_engine):
        self.macro = macro_engine
        self.weights = macro_engine.get_factor_weights()

    # ═══════════════════════════════════════════
    # 排序分位法评分（面基思想）
    # 每个因子输出 1-10 分，反映该因子在全市场的百分位
    # ═══════════════════════════════════════════

    def _bounded_linear_score(self, value, reference_range) -> float:
        """将值映射到1-10分（固定区间线性插值，非真实截面百分位）
        reference_range: (min_val, max_val) 参考范围
        """
        if value is None or reference_range is None:
            return 5.0
        lo, hi = reference_range
        if hi <= lo:
            return 5.0
        score = 1 + 9 * (value - lo) / (hi - lo)
        return max(1, min(10, score))

    def calc_quality_score(self, fin: dict) -> float:
        """质量因子：ROE + 现金流 + 盈利能力 → 百分位评分
        ROE / 营收增速来自 query_growth_data（可靠）
        毛利率/净利率来自 duPont（不同公式），仅做辅助参考
        """
        roe = min(abs(fin.get("净资产收益率", 0) or 0), 60)  # 截断异常值
        rev = min(abs(fin.get("营业收入同比增长率", 0) or 0), 100)
        ocps = min(abs(fin.get("每股经营现金流", 0) or 0), 10)

        s_roe = self._bounded_linear_score(roe, (0, 30))
        s_rev = self._bounded_linear_score(rev, (0, 50))  # 营收增速作为质量佐证
        s_oc = self._bounded_linear_score(ocps, (0, 5))

        # ROE权重最高，营收增速辅助，现金流保底
        return round(s_roe * 0.5 + s_rev * 0.25 + s_oc * 0.25, 1)

    def calc_value_score(self, daily: pd.DataFrame) -> float:
        """价值因子：PE分位 + PB估值"""
        if daily.empty:
            return 5.0
        pe = daily.iloc[-1].get("pe") if "pe" in daily.columns else None
        pb = daily.iloc[-1].get("pb") if "pb" in daily.columns else None
        pe = abs(pe) if pe and pe > 0 else None
        pb = abs(pb) if pb and pb > 0 else None

        # A股典型PE: 10-40, PB: 0.8-5
        s_pe = self._bounded_linear_score(pe, (10, 40)) if pe else 5.0
        # 反向：PE越低越有价值
        s_pe = 10 - s_pe + 1

        s_pb = self._bounded_linear_score(pb, (0.8, 5)) if pb else 5.0
        s_pb = 10 - s_pb + 1  # PB越低越好

        return round(s_pe * 0.6 + s_pb * 0.4, 1)

    def calc_growth_score(self, fin: dict) -> float:
        """成长因子：营收增速+利润增速（data_layer已输出百分比）"""
        rev = abs(fin.get("营业收入同比增长率", 0) or 0)
        profit = abs(fin.get("净利润同比增长率", 0) or 0)

        s_rev = self._bounded_linear_score(rev, (0, 60))
        s_profit = self._bounded_linear_score(profit, (0, 80))

        return round(s_rev * 0.4 + s_profit * 0.6, 1)

    def calc_lowvol_score(self, close_series: pd.Series) -> float:
        """低波因子：20日波动率 ← 越低越好"""
        if len(close_series) < 20:
            return 5.0
        daily_ret = close_series.pct_change().dropna()
        if len(daily_ret) < 10:
            return 5.0
        vol = daily_ret.tail(20).std() * np.sqrt(252) * 100  # 年化波动率%
        s_vol = self._bounded_linear_score(vol, (15, 60))
        s_vol = 10 - s_vol + 1  # 波动率越低越好
        return round(s_vol, 1)

    def calc_dividend_score(self, fin: dict) -> float:
        """红利因子：股息率（A股典型 0-5%）"""
        div = abs(fin.get("股息率", 0) or 0)
        return round(self._bounded_linear_score(div, (0, 5)), 1)

    def calc_momentum_score(self, close_series: pd.Series) -> float:
        """动量因子（Vibe Trading多时间框架）：20日+60日+120日组合"""
        if len(close_series) < 21:
            return 5.0

        # 多时间框架动量
        ret_20d = (close_series.iloc[-1] / close_series.iloc[-21] - 1) * 100
        ret_60d = (close_series.iloc[-1] / close_series.iloc[-61] - 1) * 100 if len(close_series) >= 61 else 0
        ret_120d = (close_series.iloc[-1] / close_series.iloc[-121] - 1) * 100 if len(close_series) >= 121 else 0

        # 分别评分后加权（Vibe：短期40%+中期35%+长期25%）
        s20 = self._bounded_linear_score(ret_20d, (-20, 30))
        s60 = self._bounded_linear_score(ret_60d, (-30, 50))
        s120 = self._bounded_linear_score(ret_120d, (-40, 80))

        return round(s20 * 0.4 + s60 * 0.35 + s120 * 0.25, 1)

    # ═══════════════════════════════════════════
    # LDS技术面分析（多时间框架）
    # ═══════════════════════════════════════════
    def calc_technical_score(self, df: pd.DataFrame) -> dict:
        """LDS技术面：RSI+MACD+均线+布林 → 综合技术信号"""
        result = {
            "rsi": 50, "rsi_signal": "⚪中性",
            "macd": 0, "macd_signal": "⚪中性",
            "ma60_dev": 0, "ma20_dev": 0,
            "bollinger_pos": "⚪中轨",
            "total_tech_score": 5.0,
        }
        if df.empty or len(df) < 26:
            return result

        close = df["close"].values

        # RSI(14)
        if len(close) > 14:
            gains = np.maximum(np.diff(close[-15:]), 0)
            losses = np.maximum(-np.diff(close[-15:]), 0)
            avg_g = np.mean(gains)
            avg_l = np.mean(losses) if np.mean(losses) > 0 else 1
            rsi = 100 - 100 / (1 + avg_g / avg_l)
            result["rsi"] = round(rsi, 1)
            result["rsi_signal"] = "🔴超买" if rsi > 70 else ("🟢超卖" if rsi < 30 else "⚪中性")

        # MACD（标准：DIF=EMA12-EMA26，DEA=EMA9(DIF)，柱=DIF-DEA）
        if len(close) > 35:
            s = pd.Series(close)
            ema12 = s.ewm(span=12, adjust=False).mean()
            ema26 = s.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26                          # DIF
            signal_line = macd_line.ewm(span=9, adjust=False).mean()  # DEA=EMA9(DIF)
            hist = macd_line - signal_line                     # 柱
            result["macd"] = round(float(macd_line.iloc[-1]), 4)
            result["macd_hist"] = round(float(hist.iloc[-1]), 4)
            result["macd_signal"] = "🟢金叉" if hist.iloc[-1] > 0 else "🔴死叉"

        # 均线偏离
        price = close[-1]
        if len(close) > 60:
            ma60 = np.mean(close[-60:])
            result["ma60_dev"] = round((price - ma60) / ma60 * 100, 2)
        if len(close) > 20:
            ma20 = np.mean(close[-20:])
            result["ma20_dev"] = round((price - ma20) / ma20 * 100, 2)

        # 布林带
        if len(close) > 20:
            ma = np.mean(close[-20:])
            std = np.std(close[-20:])
            upper = ma + 2 * std
            lower = ma - 2 * std
            if price >= upper: result["bollinger_pos"] = "🔴上轨"
            elif price <= lower: result["bollinger_pos"] = "🟢下轨"
            else: result["bollinger_pos"] = "⚪中轨"

        # 综合技术评分 (面基：多头技术环境加分)
        score = 5.0
        if 30 < result["rsi"] < 70: score += 1
        if result["macd_signal"] == "🟢金叉": score += 1.5
        if -5 < result.get("ma60_dev", 0) < 10: score += 1
        if result.get("ma20_dev", 0) > 0: score += 0.5
        result["total_tech_score"] = round(score, 1)

        return result

    # ═══════════════════════════════════════════
    # 单股综合评分
    # ═══════════════════════════════════════════
    def score_stock(self, symbol: str) -> dict:
        """单只股票全因子评分（排序分位法）"""
        try:
            daily = get_stock_daily(symbol, 180)
            if daily.empty:
                return {"symbol": symbol, "score": 0, "error": "no_data"}

            fin = get_financial_report(symbol)
            close = daily["close"] if "close" in daily.columns else daily.iloc[:, 4]

            # 6因子评分
            quality = self.calc_quality_score(fin)
            value = self.calc_value_score(daily)
            growth = self.calc_growth_score(fin)
            lowvol = self.calc_lowvol_score(close)
            div = self.calc_dividend_score(fin)
            momentum = self.calc_momentum_score(close)
            tech = self.calc_technical_score(daily)

            # 加权综合（权重来自宏观状态）
            total_score = (
                self.weights["质量"] * quality +
                self.weights["价值"] * value +
                self.weights["成长"] * growth +
                self.weights["低波"] * lowvol +
                self.weights["红利"] * div +
                self.weights["动量"] * momentum
            )

            # LDS技术加成（最多+1分）
            tech_bonus = max(0, (tech["total_tech_score"] - 5) * 0.2)
            total_score = min(10, total_score + tech_bonus)

            last_row = daily.iloc[-1]
            pe_val = last_row.get("pe") if "pe" in daily.columns else None
            pb_val = last_row.get("pb") if "pb" in daily.columns else None
            roe_val = fin.get("净资产收益率")
            rev_growth = fin.get("营业收入同比增长率")
            profit_growth = fin.get("净利润同比增长率")

            # PE 历史百分位（价值投资核心信号）
            pe_pct_info = {}
            if pe_val and pe_val > 0:
                try:
                    pe_pct_info = calc_pe_percentile(symbol, float(pe_val), years=5)
                except Exception:
                    pass

            # 成交量放量/缩量信号
            vol_signal = {}
            try:
                vol_signal = get_volume_signal(symbol)
            except Exception:
                pass

            # ROE 趋势 + FCF（最近4季）
            roe_trend = None
            latest_fcf = None
            try:
                fin_hist = get_financial_history(symbol, quarters=4)
                if len(fin_hist) >= 2:
                    roes = [h["roe"] for h in fin_hist if h.get("roe") is not None]
                    if len(roes) >= 2:
                        roe_trend = round(roes[0] - roes[-1], 1)
                if fin_hist and fin_hist[0].get("fcf") is not None:
                    latest_fcf = fin_hist[0]["fcf"]
            except Exception:
                pass

            return {
                "symbol": symbol,
                "score": round(total_score, 2),
                "factors": {
                    "质量": quality, "价值": value, "成长": growth,
                    "低波": lowvol, "红利": div, "动量": momentum,
                },
                "tech": tech,
                "price": float(close.iloc[-1]) if len(close) > 0 else 0,
                "change_pct": self._calc_chg(daily),
                "pe": round(float(pe_val), 1) if pe_val and pe_val > 0 else None,
                "pb": round(float(pb_val), 2) if pb_val and pb_val > 0 else None,
                "roe": round(float(roe_val), 1) if roe_val is not None else None,
                "rev_growth": round(float(rev_growth), 1) if rev_growth is not None else None,
                "profit_growth": round(float(profit_growth), 1) if profit_growth is not None else None,
                "pe_percentile": pe_pct_info.get("percentile"),
                "pe_level": pe_pct_info.get("level", ""),
                "vol_signal": vol_signal.get("signal", ""),
                "vol_ratio": vol_signal.get("ratio"),
                "roe_trend": roe_trend,
                "fcf_亿": latest_fcf,
            }
        except Exception as e:
            return {"symbol": symbol, "score": 0, "error": str(e)[:100]}

    def _calc_chg(self, df):
        if df.empty or len(df) < 2:
            return 0
        close = df["close"] if "close" in df.columns else df.iloc[:, 4]
        return float((close.iloc[-1] / close.iloc[-2] - 1) * 100)

    # ═══════════════════════════════════════════
    # 全市场扫描（LDS宏观驱动版 v3.3）
    # ═══════════════════════════════════════════
    def scan_market(self, scan_type="small_mid", top_n=30) -> list:
        """排序分位法全市场扫描 — LDS宏观→板块→个股
        板块轮抽：每个板块取N只，确保行业覆盖均衡。
        评分排序后取top_n。"""
        from investment_system.domain.stock_universe import ALL_LDS_STOCKS, get_stocks_for_macro, LDS_SECTORS, INDEX_DATA, MACRO_TO_SECTORS
        
        # 获取当前宏观状态
        regime = self.macro.regime if self.macro and hasattr(self.macro, 'regime') else "default"
        max_scan = getattr(self, "MAX_SCAN", 50)  # 默认50只

        # ═══ 板块轮抽：favored板块多取，其他补齐 ═══
        favored_sector_names = MACRO_TO_SECTORS.get(regime, MACRO_TO_SECTORS["default"])
        all_sector_names = list(LDS_SECTORS.keys())
        favored_per_sec = max(3, max_scan // len(favored_sector_names)) if favored_sector_names else 5
        rest_per_sec = max(2, max_scan // len(all_sector_names))
        
        universe = []
        seen = set()
        
        # 先取favored板块（每板块 favored_per_sec 只）
        for sec in favored_sector_names:
            count = 0
            for s in LDS_SECTORS.get(sec, []):
                if s not in seen and count < favored_per_sec:
                    seen.add(s)
                    universe.append(s)
                    count += 1
                    if len(universe) >= max_scan:
                        break
            if len(universe) >= max_scan:
                break
        
        # 再取其他板块补齐（每板块 rest_per_sec 只）
        other_sectors = [s for s in all_sector_names if s not in favored_sector_names]
        for sec in other_sectors:
            count = 0
            for s in LDS_SECTORS.get(sec, []):
                if s not in seen and count < rest_per_sec:
                    seen.add(s)
                    universe.append(s)
                    count += 1
                    if len(universe) >= max_scan:
                        break
            if len(universe) >= max_scan:
                break
        
        print(f"[scanner] 板块轮抽 | 宏观:{regime} | 池{len(universe)}只 | favored:{', '.join(favored_sector_names[:3])}")
        
        scored = []
        for i, sym in enumerate(universe):
            if i >= max_scan:
                break
            s = self.score_stock(sym)
            if s.get("error"):
                continue
            s["name"] = self._get_stock_name(sym)
            s["sector"] = self._get_stock_sector(sym)
            scored.append(s)
            if i % 10 == 0 and i > 0:
                print(f"  [scanner] {i}/{max_scan}...")

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_n]

    def _get_stock_sector(self, symbol: str) -> str:
        """查询股票所属LDS板块"""
        from investment_system.domain.stock_universe import LDS_SECTORS
        for sector_name, stocks in LDS_SECTORS.items():
            if symbol in stocks:
                return sector_name
        return "其他"

    # ═══════════════════════════════════════════
    # 产业链扫描（LDS法）
    # ═══════════════════════════════════════════
    def scan_chain(self, chain_name: str = "") -> list:
        """按产业链扫描"""
        chains = config.INDUSTRY_CHAINS
        if chain_name and chain_name in chains:
            targets = chains[chain_name]["symbols"]
        else:
            targets = list(set(s for c in chains.values() for s in c["symbols"]))

        print(f"[scanner] 产业链扫描: {chain_name or '全部'} → {len(targets)}只")
        scored = []
        for sym in targets:
            s = self.score_stock(sym)
            if not s.get("error"):
                s["name"] = self._get_stock_name(sym)
                scored.append(s)
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored

    def _get_stock_name(self, symbol: str) -> str:
        """获取股票名称（带缓存）"""
        if symbol in self._cache:
            return self._cache[symbol]
        try:
            import baostock as bs
            bs_code = f"sz.{symbol.zfill(6)}" if not symbol.startswith("6") else f"sh.{symbol.zfill(6)}"
            rs = bs.query_stock_basic(code=bs_code)
            if rs.error_code == "0":
                while rs.next():
                    r = rs.get_row_data()
                    name = r[1] if len(r) > 1 else ""
                    self._cache[symbol] = name
                    return name
        except:
            pass
        return ""

    @staticmethod
    def _baostock_code(symbol: str) -> str:
        sym = symbol.zfill(6)
        if sym.startswith("6"): return f"sh.{sym}"
        elif sym.startswith("0") or sym.startswith("3"): return f"sz.{sym}"
        else: return f"sz.{sym}"


if __name__ == "__main__":
    fs = FactorScanner()
    r = fs.score_stock("300502")
    import json
    print("300502:", json.dumps(r, ensure_ascii=False, indent=2))
