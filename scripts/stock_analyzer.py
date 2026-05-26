"""
个股深度分析引擎 v3.1 — LDS产业链定位法 + 四重确认

六步法：
  1. 宏观定位—该标的是否符合当前宏观环境
  2. 产业链定位—利润率最高环节？景气度？
  3. 基本面验证—ROE/增速/现金流三重确认
  4. 技术面确认—RSI/MACD/均线/布林四维
  5. LDS逻辑检查—持有逻辑是否成立
  6. 交易策略—信号级别+仓位+止损止盈
"""
import pandas as pd
import numpy as np
from datetime import datetime
from investment_system import config
from investment_system.data.data_layer import get_stock_daily, get_financial_report
from investment_system.analysis.factor_scanner import FactorScanner


class StockAnalyzer:
    """个股六步深度分析"""

    def __init__(self, macro_engine=None):
        self.macro = macro_engine
        self.scanner = FactorScanner(macro_engine)

    # ═══════════════════════════════════════════
    # 第一步：代码解析
    # ═══════════════════════════════════════════
    def resolve_symbol(self, text: str) -> str:
        """智能解析：输入 300502 / 新易盛 → 返回symbol"""
        t = text.strip()
        # 纯数字（可能带后缀）→ 代码
        if t.replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "").isdigit():
            return t[-6:].zfill(6)
        # 名称→查baostock
        try:
            import baostock as bs
            # 扫描预定义池
            from investment_system.domain.stock_universe import ALL_CORE_STOCKS
            for sym in ALL_CORE_STOCKS:
                name = self.scanner._get_stock_name(sym)
                if t in name:
                    return sym
        except:
            pass
        return t

    # ═══════════════════════════════════════════
    # 六步深度分析
    # ═══════════════════════════════════════════
    def deep_analyze(self, symbol: str) -> dict:
        """六步深度分析"""
        symbol = self.resolve_symbol(symbol)

        # 数据获取
        daily = get_stock_daily(symbol, 365)
        fin = get_financial_report(symbol)
        if daily.empty:
            return {"symbol": symbol, "error": "无法获取行情数据"}

        name = self.scanner._get_stock_name(symbol)
        factor_result = self.scanner.score_stock(symbol)

        # ═══ 各维度分析 ═══
        tech = self._technical_analysis(daily)
        macro_check = self._macro_check(symbol)
        chain = self._identify_chain(symbol, name)
        fundamentals = self._fundamental_check(fin, daily)
        lds_confirmation = self._lds_four_check(factor_result, tech, chain, fundamentals)
        signal = self._calc_signal(factor_result, tech, lds_confirmation)
        position = self._calc_position(signal, factor_result)

        return {
            "symbol": symbol,
            "name": name,
            "price": float(daily.iloc[-1]["close"]) if "close" in daily.columns else float(daily.iloc[-1].iloc[3]),
            "change_pct": self._calc_chg(daily),
            "score": factor_result.get("score", 0),
            "factors": factor_result.get("factors", {}),
            "tech": tech,
            "macro_check": macro_check,
            "chain": chain,
            "fundamentals": fundamentals,
            "lds_confirmation": lds_confirmation,
            "signal": signal,
            "position": position,
        }

    # ═══════════════════════════════════════════
    # 第二步：宏观定位
    # ═══════════════════════════════════════════
    def _macro_check(self, symbol: str) -> dict:
        """宏观环境对标的的影响"""
        if not self.macro:
            return {"macro_context": "无宏观引擎", "compatible": True}
        regime = getattr(self.macro, "regime", "复苏期")
        switch = getattr(self.macro, "strategy_switch", "on")

        # 产业链匹配
        from investment_system.domain.stock_universe import INDEX_DATA
        in_growth_chain = any(symbol in chains for chains in INDEX_DATA.get("chains", {}).values())
        tech_chains = ["英伟达算力链", "半导体链", "国产替代链"]

        result = {
            "regime": regime,
            "switch": switch,
            "compatible": True,
            "notes": [],
        }

        if switch == "off":
            result["compatible"] = False
            result["notes"].append("🔴 策略全关，不开新仓")
            return result

        if switch == "limited":
            result["notes"].append("🟡 策略谨慎，控制仓位≤50%")

        # 宏观→风格匹配
        regime_to_preference = {
            "复苏期": "质量+价值",
            "扩张期": "成长+动量",
            "过热期": "价值+红利",
            "衰退期": "质量+低波",
        }
        result["preferred_style"] = regime_to_preference.get(regime, "均衡")

        return result

    # ═══════════════════════════════════════════
    # 第三步：产业链定位（LDS法）
    # ═══════════════════════════════════════════
    def _identify_chain(self, symbol: str, name: str) -> dict:
        """产业链精细定位"""
        chains = config.INDUSTRY_CHAINS
        result = {"chain": "未识别", "position": "未知",
                  "is_high_margin": False, "margin_tier": "未知",
                  "chain_peers": []}

        for chain_name, chain_data in chains.items():
            matched = symbol in chain_data.get("symbols", [])
            if not matched and name:
                for kw in chain_data.get("keywords", []):
                    if kw in name:
                        matched = True
                        break
            if not matched:
                continue

            result["chain"] = chain_name
            result["chain_peers"] = chain_data.get("symbols", [])

            # 定位
            for pos, kws in chain_data.get("chain_position", {}).items():
                for kw in kws:
                    if kw in name:
                        result["position"] = pos
                        break
                if result["position"] != "未知":
                    break
            if result["position"] == "未知":
                result["position"] = "中游"

            # 利润率层级（LDS核心）
            for hk in chain_data.get("high_margin_keywords", []):
                if hk in name:
                    result["is_high_margin"] = True
                    result["margin_tier"] = "高利润✅"
                    break
            if not result["is_high_margin"]:
                result["margin_tier"] = "中游⚪"

            break

        return result

    # ═══════════════════════════════════════════
    # 第四步：基本面验证
    # ═══════════════════════════════════════════
    def _fundamental_check(self, fin: dict, daily: pd.DataFrame) -> dict:
        """基本面三重验证（LDS标准）"""
        roe = abs(fin.get("净资产收益率", 0) or 0)
        rev = abs(fin.get("营业收入同比增长率", 0) or 0)
        profit = abs(fin.get("净利润同比增长率", 0) or 0)
        gm = abs(fin.get("毛利率", 0) or 0)
        nm = abs(fin.get("净利率", 0) or 0)

        pe = daily.iloc[-1].get("pe") if "pe" in daily.columns else None
        pb = daily.iloc[-1].get("pb") if "pb" in daily.columns else None

        checks = []
        details = {}

        # ROE检验
        if roe >= 20:
            checks.append("✅ ROE≥20% 优秀")
            details["roe_tier"] = "优秀"
        elif roe >= 15:
            checks.append("✅ ROE≥15% 达标")
            details["roe_tier"] = "达标"
        elif roe >= 10:
            checks.append("⚪ ROE≥10% 一般")
            details["roe_tier"] = "一般"
        else:
            checks.append("❌ ROE<10% 不合格")
            details["roe_tier"] = "不合格"

        # 营收增速检验
        if rev >= 30:
            checks.append("✅ 营收增速≥30% 高增长")
            details["rev_tier"] = "高增长"
        elif rev >= 20:
            checks.append("✅ 营收增速≥20% 达标")
            details["rev_tier"] = "达标"
        elif rev >= 10:
            checks.append("⚪ 营收增速≥10% 稳健")
            details["rev_tier"] = "稳健"
        else:
            checks.append("⚠️ 营收增速<10% 缓慢")
            details["rev_tier"] = "缓慢"

        # 毛利率检验
        if gm >= 40:
            checks.append("✅ 毛利率≥40% 护城河明显")
            details["gm_tier"] = "高"
        elif gm >= 25:
            checks.append("⚪ 毛利率≥25% 中等")
            details["gm_tier"] = "中"
        else:
            checks.append("⚠️ 毛利率<25% 偏低")
            details["gm_tier"] = "低"

        # 估值检查
        if pe and pe > 0:
            pe_str = f"PE={pe:.1f}"
            if pe < 15: pe_str += " ✅低估"
            elif pe < 30: pe_str += " ⚪合理"
            else: pe_str += " ⚠️偏高"
            checks.append(f"{pe_str}")
        if pb and pb > 0:
            pb_str = f"PB={pb:.1f}"
            if pb < 2: pb_str += " ✅低估"
            elif pb < 5: pb_str += " ⚪合理"
            else: pb_str += " ⚠️偏高"
            checks.append(f"{pb_str}")

        return {
            "roe": roe, "rev_growth": rev, "profit_growth": profit,
            "gross_margin": gm, "net_margin": nm,
            "pe": pe, "pb": pb,
            "checks": checks,
            "pass_count": sum(1 for c in checks if c.startswith("✅")),
        }

    # ═══════════════════════════════════════════
    # 第五步：LDS四重确认
    # ═══════════════════════════════════════════
    def _lds_four_check(self, factor_result, tech, chain, fundamentals) -> dict:
        """LDS四重确认法"""
        score = factor_result.get("score", 0)
        tech_score = tech.get("total_tech_score", 5)
        rsi = tech.get("rsi", 50)
        ma60_dev = tech.get("ma60_dev", 0)

        confirms = []
        total_passed = 0

        # 确认①：因子评分是否足够高（面基6因子标准）
        if score >= 6.5:
            confirms.append(("✅", "因子评分≥6.5", "6因子综合" if score >= 7.5 else "6因子中等"))
            total_passed += 1
        elif score >= 5.5:
            confirms.append(("⚪", "评分5.5-6.4", "可关注但需谨慎"))
        else:
            confirms.append(("❌", f"评分{score}<5.5", "评分偏低"))

        # 确认②：技术面是否健康
        if 30 < rsi < 70:
            confirms.append(("✅", "RSI健康区间", f"RSI={rsi}"))
            total_passed += 1
        elif rsi < 30:
            confirms.append(("🟢", "RSI超卖", f"RSI={rsi}→低吸窗口"))
        else:
            confirms.append(("🔴", "RSI超买", f"RSI={rsi}→注意回调"))

        if tech.get("macd_signal") == "🟢金叉":
            confirms.append(("✅", "MACD金叉", "中期趋势向好"))
            total_passed += 1
        elif tech.get("macd_signal") == "🔴死叉":
            confirms.append(("⚪", "MACD死叉", "中期趋势偏弱"))
        else:
            confirms.append(("⚪", "MACD零轴附近", "方向不明"))

        # 确认③：均线位置（LDS国运线）
        if -5 < ma60_dev < 15:
            confirms.append(("✅", "贴近国运线", f"60日偏离{ma60_dev:+.1f}%"))
            total_passed += 1
        elif ma60_dev > 20:
            confirms.append(("🔴", "远离国运线>20%", "回调风险较大"))
        elif ma60_dev < -10:
            confirms.append(("🟢", "大幅低于国运线", "潜在价值洼地"))
            total_passed += 1

        # 确认④：产业链位置（LDS核心）
        if chain.get("is_high_margin"):
            confirms.append(("✅", "高利润率环节", f"{chain['chain']} {chain['position']}"))
            total_passed += 1
        else:
            confirms.append(("⚪", "非高利润环节", f"{chain['chain']} {chain['position']}"))

        return {
            "total_passed": total_passed,
            "max_possible": 4,
            "confirms": confirms,
            "verdict": "四重确认通过 🟢" if total_passed >= 3 else (
                       "部分确认 ⚪" if total_passed >= 2 else "确认不足 ❌"),
        }

    # ═══════════════════════════════════════════
    # 技术面分析
    # ═══════════════════════════════════════════
    def _technical_analysis(self, df: pd.DataFrame) -> dict:
        return self.scanner.calc_technical_score(df)

    # ═══════════════════════════════════════════
    # 第六步：交易信号+仓位
    # ═══════════════════════════════════════════
    def _calc_signal(self, factor_result, tech, lds) -> dict:
        """信号级别（三级体系）"""
        score = factor_result.get("score", 0)
        tech_score = tech.get("total_tech_score", 5)
        lds_passed = lds.get("total_passed", 0)
        rsi = tech.get("rsi", 50)

        # 综合评分
        composite = score * 0.5 + tech_score * 0.3 + (lds_passed / 4 * 10) * 0.2

        signal = "观望"
        strength = 0
        buy_reason = ""
        sell_reason = ""

        if composite >= 7.0 and rsi < 65 and lds_passed >= 3:
            signal = "买入"
            strength = 2
            buy_reason = "高评分+技术共振+四重确认"
        elif composite >= 6.0 and rsi < 70 and lds_passed >= 2:
            signal = "关注"
            strength = 1
            buy_reason = "基本面良好+技术面中性偏多"
        elif composite >= 5.0:
            signal = "观察"
            strength = 0
        elif composite < 4.5 or rsi > 75:
            signal = "卖出"
            strength = -1
            sell_reason = "评分下降/RSI超买/趋势走弱"

        return {
            "signal": signal,
            "strength": strength,
            "composite_score": round(composite, 2),
            "buy_reason": buy_reason,
            "sell_reason": sell_reason,
            "emoji": {
                "买入": "🟢", "关注": "👀", "观察": "📊", "卖出": "🔴", "观望": "⚪",
            }.get(signal, "⚪"),
        }

    def _calc_position(self, signal_dict: dict, factor_result) -> dict:
        """仓位计算（凯利+宏观折扣+LDS限量）"""
        signal = signal_dict.get("signal", "观望")
        strength = signal_dict.get("strength", 0)
        score = factor_result.get("score", 5)

        # 基准仓位
        base_map = {"买入": 2.0, "关注": 1.0, "观察": 0.5, "卖出": -2.0, "观望": 0.0}
        base_pct = base_map.get(signal, 0.0)

        # 宏观折扣
        macro_factor = 0.5
        if self.macro:
            try:
                macro_factor = self.macro.suggest_total_position()
            except:
                macro_factor = 0.5

        # 质量折扣
        quality_factor = min(1.0, max(0.3, score / 8))

        # 止盈止损
        final_pct = base_pct * macro_factor * quality_factor

        return {
            "suggested_pct": round(final_pct, 1),
            "max_pct": config.RISK_PARAMS["max_single_position"] * 100,
            "stop_loss": -config.RISK_PARAMS["stop_loss_pct"] * 100,
            "take_profit_tier1": config.RISK_PARAMS["take_profit_tier1"] * 100,
            "take_profit_tier2": config.RISK_PARAMS["take_profit_tier2"] * 100,
            "macro_discount": round(macro_factor, 2),
            "quality_discount": round(quality_factor, 2),
            "risk_per_share": f"{round(final_pct * config.RISK_PARAMS['stop_loss_pct'], 2)}%",
        }

    def _calc_chg(self, df):
        if df.empty or len(df) < 2:
            return 0
        close = df["close"] if "close" in df.columns else df.iloc[:, 4]
        return float((close.iloc[-1] / close.iloc[-2] - 1) * 100)


if __name__ == "__main__":
    sa = StockAnalyzer()
    r = sa.deep_analyze("300502")
    import json
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
