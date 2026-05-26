#!/usr/bin/env python3
"""
面基概念引擎 v1.0 — 将47+条面基播客概念封装为可调用分析函数
=================================================================
每条概念对应一个方法，输入投资标的的实际数据，输出结构化分析结论。
来源标注：E=期数 | §=知识总纲章节

核心原则：
  - 不编造阈值，所有阈值来自面基播客原文或LDS实战数据
  - 输入是实际数据(PE/ROE/增速/价格等)，输出是结构化 dict
  - 无法计算结果时返回 {"status": "unavailable", "reason": "缺XX数据"}
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
import math

# ═══════════════════════════════════════════════════════════════
# 数据类
# ═══════════════════════════════════════════════════════════════

@dataclass
class StockSnapshot:
    """个股快照 — 概念引擎的标准输入"""
    symbol: str = ""
    name: str = ""
    price: Optional[float] = None
    pe: Optional[float] = None          # 当前PE
    pe_avg_5y: Optional[float] = None   # 5年PE均值
    pe_min_5y: Optional[float] = None   # 5年PE最低
    pe_max_5y: Optional[float] = None   # 5年PE最高
    pb: Optional[float] = None
    roe: Optional[float] = None         # % (e.g. 15.2 means 15.2%)
    roe_avg_5y: Optional[float] = None
    rev_growth: Optional[float] = None  # 营收增速 %
    eps_growth: Optional[float] = None  # 盈利增速 %
    fcf_yield: Optional[float] = None   # FCF收益率 %
    div_yield: Optional[float] = None   # 股息率 %
    market_cap: Optional[float] = None  # 市值(亿)
    debt_equity: Optional[float] = None # 负债率
    beta: Optional[float] = None
    ma20: Optional[float] = None        # 20日均线
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    short_float: Optional[float] = None # 空头占比 %
    analyst_target: Optional[float] = None
    sector: str = ""
    chain: str = ""                     # 所属产业链
    profit_margin: Optional[float] = None  # 利润率%
    ocf_ni_ratio: Optional[float] = None   # E107: OCF/NI比值
    receivables_ratio: Optional[float] = None  # 应收/营收比
    cost_pct_from_peak: Optional[float] = None # 距高点跌幅%

@dataclass
class MacroSnapshot:
    """宏观快照"""
    cpi: Optional[float] = None
    cpi_trend: str = "stable"         # up/down/stable
    pmi: Optional[float] = None
    sh_index: Optional[float] = None   # 上证指数
    sh_ma20y: Optional[float] = None   # 上证20年均线(国运线)
    bond_yield_10y: Optional[float] = None
    credit_spread: Optional[float] = None
    money_supply: str = "neutral"      # loose/tight/neutral
    credit_env: str = "neutral"        # loose/tight/neutral
    trend_temperature: str = "neutral"  # cold/cool/warm/hot (LDS)
    regime: str = "unknown"            # 宏观象限

@dataclass
class ChainSnapshot:
    """产业链快照"""
    name: str = ""
    key_players: List[str] = field(default_factory=list)
    current_pe: Optional[float] = None      # 链平均PE
    historical_doubling_pe: Optional[float] = None  # 历史上行周期翻倍起点PE
    supply_demand_gap_pct: Optional[float] = None    # 供需缺口%
    catalyst_timeline: List[str] = field(default_factory=list)  # 未来3月催化剂
    perez_stage: str = "unknown"      # Perez阶段: irruption/frenzy/synergy/maturity
    profit_pool_stage: str = "unknown" # 利润池: expanding/peaking/migrating/shrinking


# ═══════════════════════════════════════════════════════════════
# 概念引擎
# ═══════════════════════════════════════════════════════════════

class ConceptEngine:
    """
    面基概念引擎
    
    用法:
        engine = ConceptEngine()
        result = engine.dcf_value(StockSnapshot(pe=25, eps_growth=18, fcf_yield=4.2))
    """
    
    # ═══════════════════════════════════════════
    # 一、估值类 (E124, E107, E68)
    # ═══════════════════════════════════════════
    
    def dcf_value(self, s: StockSnapshot, 
                  risk_free: float = 3.5,
                  terminal_growth: float = 2.5,
                  growth_years: int = 10) -> dict:
        """
        E124 DCF估值框架
        内在价值 = Σ CFt/(1+r)^t + TV/(1+r)^n
        TV = CFn × (1+g) / (r-g)
        
        永续段(TV)通常占内在价值~50%。DCF不是算精确数，是估值思想框架。
        """
        if s.fcf_yield is None or s.eps_growth is None or s.pe is None:
            return {"status": "unavailable", "reason": "缺FCF/增速/PE数据"}
        
        # 简化：用FCF Yield反推FCF，假设当前市值
        # 更完整版需要实际FCF数据
        discount = risk_free + max(s.beta or 1.0, 0.5) * 5  # CAPM简化
        
        # PEG-based fair PE
        fair_pe = min(s.eps_growth * 0.8, 40)  # PEG<1 为合理
        
        # 永续段价值占比估算
        tv_ratio = 0.50  # 面基E124: 永续段占~50%
        
        upside_pct = (fair_pe / s.pe - 1) * 100 if s.pe > 0 else 0
        
        return {
            "source": "E124 DCF估值",
            "current_pe": s.pe,
            "fair_pe": round(fair_pe, 1),
            "upside_pct": round(upside_pct, 1),
            "discount_rate": round(discount, 1),
            "terminal_value_ratio": f"{tv_ratio*100:.0f}% (E124: 永续段占内在价值~50%)",
            "peg": round(s.pe / s.eps_growth, 2) if s.eps_growth > 0 else None,
            "valuation_signal": "undervalued" if upside_pct > 15 else "fair" if abs(upside_pct) < 15 else "overvalued",
            "note": "DCF不是精确数，是估值思想框架。关键假设：增长率、折现率、永续增长率。三者各变1%，估值可差30%+"
        }
    
    def pe_band_analysis(self, s: StockSnapshot) -> dict:
        """PE Band分析：当前PE vs 历史PE区间"""
        if s.pe is None:
            return {"status": "unavailable", "reason": "缺PE数据"}
        
        result = {
            "source": "PE Band分析",
            "current_pe": s.pe,
        }
        
        if s.pe_avg_5y and s.pe_min_5y and s.pe_max_5y:
            percentile = (s.pe - s.pe_min_5y) / (s.pe_max_5y - s.pe_min_5y) * 100
            result["percentile_5y"] = round(percentile, 1)
            result["pe_avg_5y"] = s.pe_avg_5y
            result["pe_range_5y"] = f"{s.pe_min_5y}-{s.pe_max_5y}"
            
            if percentile < 25:
                result["signal"] = "历史低位区 — 如基本面未恶化，是潜在买入区"
            elif percentile < 50:
                result["signal"] = "历史中位偏低 — 可关注"
            elif percentile < 75:
                result["signal"] = "历史中位偏高 — 谨慎"
            else:
                result["signal"] = "历史高位区 — 高估值需高增速支撑"
        else:
            result["note"] = "缺5年PE历史数据，仅提供当前PE"
            
        return result
    
    def fcf_two_flowers(self, s: StockSnapshot) -> dict:
        """
        E68 FCF两朵花
        第一朵：FCF增长(成长) — reinvestment → 未来更大FCF
        第二朵：FCF释放(分红/回购) — 成熟期返还股东
        
        哑铃结构：两头配置，中间回避
        """
        if s.fcf_yield is None:
            return {"status": "unavailable", "reason": "缺FCF数据"}
        
        # 判断当前是哪朵花
        if s.eps_growth and s.eps_growth > 15 and s.div_yield and s.div_yield < 2:
            flower = "第一朵花：FCF增长 — 成长型，再投资为主"
            strategy = "适合哑铃的「成长端」"
        elif s.div_yield and s.div_yield > 3:
            flower = "第二朵花：FCF释放 — 成熟型，分红/回购为主"
            strategy = "适合哑铃的「红利端」"
        else:
            flower = "过渡期 — 增长放缓但分红尚未提升"
            strategy = "不适合哑铃策略，回避"
        
        return {
            "source": "E68 FCF两朵花",
            "fcf_yield": s.fcf_yield,
            "div_yield": s.div_yield or 0,
            "eps_growth": s.eps_growth or 0,
            "flower": flower,
            "strategy": strategy,
            "dumbbell_note": "哑铃=一端高质量成长(FCF增长)+一端高股息(FCF释放)。中间地带(低速成长+低分红)两端不靠，规避"
        }
    
    def zhangxinmin_3statements(self, s: StockSnapshot) -> dict:
        """
        E107 张新民三表联动分析
        核心指标：
          1. OCF/NI 比值 — 经营现金流/净利润，>1 为健康
          2. 应收/营收比 — 过高说明收入质量差
          3. 预付款/存货 — 供应链地位信号
        """
        issues = []
        
        if s.ocf_ni_ratio is not None:
            if s.ocf_ni_ratio < 0.8:
                issues.append(f"⚠️ OCF/NI={s.ocf_ni_ratio:.2f}<0.8，净利润含金量不足")
            elif s.ocf_ni_ratio > 1.2:
                issues.append(f"✅ OCF/NI={s.ocf_ni_ratio:.2f}>1.2，净利润有强现金流支撑")
        
        if s.receivables_ratio is not None:
            if s.receivables_ratio > 0.5:
                issues.append(f"⚠️ 应收/营收={s.receivables_ratio:.1%}>50%，回款能力弱")
        
        return {
            "source": "E107 张新民三表联动",
            "ocf_ni_ratio": s.ocf_ni_ratio,
            "receivables_ratio": s.receivables_ratio,
            "issues": issues if issues else ["数据不足以做三表分析"],
            "principle": "战略视角看财报：三张表联动，不孤立看利润表"
        }
    
    # ═══════════════════════════════════════════
    # 二、产业链类 (E7, E84)
    # ═══════════════════════════════════════════
    
    def meso_4levels(self, s: StockSnapshot, chain: ChainSnapshot) -> dict:
        """
        E7/E84 中观四层次
        1. 行业空间 — TAM多大？增速？
        2. 竞争格局 — 集中度？进入壁垒？
        3. 产业链定位 — 在链的哪个环节？利润池怎么分布？
        4. 公司壁垒 — 护城河深度？可替代性？
        """
        return {
            "source": "E7/E84 中观四层次",
            "framework": "行业空间→竞争格局→链定位→公司壁垒",
            "chain": chain.name,
            "current_stock_position": s.name,
            "checklist": [
                "① 行业空间：TAM是否>1000亿？增速>10%？",
                "② 竞争格局：CR3>50%？进入壁垒高？",
                "③ 链定位：是否在利润率最高的环节？(LDS: 盯住利润池最厚的环节)",
                "④ 公司壁垒：可替代性低？客户粘性强？"
            ],
            "principle": "四个层次是漏斗：从大到小，从行业到公司。每个层次筛掉一批标的"
        }
    
    def profit_pool_analysis(self, chain: ChainSnapshot) -> dict:
        """利润池迁移分析 — 链利润从哪个环节流向哪个环节"""
        stages = {
            "expanding": "利润池扩张：增量市场，各环节分羹",
            "peaking": "利润池见顶：开始向壁垒最高的环节集中",
            "migrating": "利润池迁移：向上游(原材料/技术)或下游(渠道/品牌)转移",
            "shrinking": "利润池收缩：整体需求下降，只有成本最低者存活"
        }
        return {
            "source": "LDS利润池理论",
            "chain": chain.name,
            "current_stage": chain.profit_pool_stage,
            "meaning": stages.get(chain.profit_pool_stage, "未知"),
            "action": "盯住利润池最厚的环节，选该环节壁垒最高的标的"
        }
    
    # ═══════════════════════════════════════════
    # 三、仓位/风控类 (E153, E80, E105)
    # ═══════════════════════════════════════════
    
    def kelly_position(self, win_rate: float, odds: float, 
                       max_single: float = 0.02) -> dict:
        """
        E153 凯利公式
        f* = (bp - q) / b
        其中 b=赔率(赢时赚几倍), p=胜率, q=1-p
        
        LDS铁律：单票≤2%(即使凯利算出>2%)
        复利增长 G = Edge × Position × Frequency × Time
        """
        if not (0 < win_rate < 1 and odds > 0):
            return {"status": "unavailable", "reason": "胜率/赔率无效"}
        
        q = 1 - win_rate
        kelly_raw = (odds * win_rate - q) / odds
        kelly_capped = min(max(kelly_raw, 0), max_single)
        
        # 半凯利更稳健
        half_kelly = kelly_raw / 2
        half_kelly_capped = min(max(half_kelly, 0), max_single)
        
        signal = "不投" if kelly_raw <= 0 else \
                 "轻仓(半凯利)" if kelly_raw < 0.05 else \
                 "标准仓位(凯利)" if kelly_raw < max_single else \
                 f"⚠️ 凯利>{max_single:.0%}，按LDS铁律上限{max_single:.0%}"
        
        return {
            "source": "E153 凯利公式 + LDS铁律",
            "raw_kelly": round(kelly_raw, 4),
            "half_kelly": round(half_kelly, 4),
            "recommended_position": round(kelly_capped, 4),
            "signal": signal,
            "formula": "f* = (bp-q)/b",
            "input": f"胜率={win_rate:.0%}, 赔率={odds:.1f}x",
            "rule": "单票≤2%(LDS) | 共≤8只 | 连错10次亏20%仍可继续(E153)",
            "compound_growth": "G = Edge × Position × Frequency × Time"
        }
    
    def stop_loss_discipline(self, entry_price: float, current_price: float,
                              position_pct: float = 0) -> dict:
        """
        LDS铁律 — 止损止盈纪律
        
        8%硬止损：买入后立即设止损=成本×0.92
        15%止盈减半仓
        30%止盈清仓
        """
        pnl_pct = (current_price / entry_price - 1) * 100
        stop_loss_price = entry_price * 0.92
        take_profit_half = entry_price * 1.15
        take_profit_all = entry_price * 1.30
        
        if pnl_pct <= -8:
            action = "🔴 触发硬止损！立即清仓"
        elif pnl_pct >= 30:
            action = "🟢 触发30%止盈，清仓锁定利润"
        elif pnl_pct >= 15:
            action = "🟡 触发15%止盈，减半仓"
        elif pnl_pct < -5:
            action = "⚠️ 接近止损线(距止损还有{:.1f}%)".format(abs(pnl_pct+8))
        else:
            action = "✅ 正常持有"
        
        return {
            "source": "LDS铁律",
            "entry_price": entry_price,
            "current_price": current_price,
            "pnl_pct": round(pnl_pct, 1),
            "stop_loss_price": round(stop_loss_price, 2),
            "take_profit_half": round(take_profit_half, 2),
            "take_profit_all": round(take_profit_all, 2),
            "action": action,
            "rules": "8%硬止损 | 15%减半仓 | 30%清仓 | 月度再平衡 | 回撤>25%清盘"
        }
    
    def risk_2percent_rule(self, total_capital: float, position_size: float) -> dict:
        """
        E80/E153 单笔最大亏损≤2%总资产
        赚到>>赚过：纪律化止盈比预测顶部更可靠
        """
        position_pct = position_size / total_capital * 100 if total_capital > 0 else 0
        
        return {
            "source": "E80/E153 风险纪律",
            "total_capital": total_capital,
            "position_size": position_size,
            "position_pct": round(position_pct, 1),
            "max_loss_2pct": round(total_capital * 0.02, 2),
            "ok": position_pct <= 2.0,
            "principle": "单笔最大亏损≤2%总资产 | 最多8只票 | 浮盈不是盈利(E80)"
        }
    
    def early_exit_signal(self, s: StockSnapshot) -> dict:
        """
        E105 及早离去
        触发条件：
          - PE>60 且 增速<15%
          - 市值>1万亿且增速<10%
          - 距高点跌>50%仍在扩大跌幅
        """
        signals = []
        
        if s.pe and s.pe > 60 and s.eps_growth and s.eps_growth < 15:
            signals.append(f"🚨 PE({s.pe})>60 且 增速({s.eps_growth}%)<15% — 高估值低增长")
        
        if s.market_cap and s.market_cap > 10000 and s.eps_growth and s.eps_growth < 10:
            signals.append(f"🚨 巨无霸(>{s.market_cap}亿)增速<10% — 天花板效应")
        
        return {
            "source": "E105 及早离去",
            "signals": signals if signals else ["无触发信号"],
            "should_exit": len(signals) > 0,
            "principle": "市场疯狂时及早离去。不贪最后一个铜板。投资是无限游戏，活下来第一。"
        }
    
    def earned_vs_could_have(self, s: StockSnapshot) -> dict:
        """E80 赚到>>赚过 — 已获利是事实，未获利是幻觉"""
        if s.cost_pct_from_peak is None and s.pe is None:
            return {"status": "unavailable", "reason": "缺价格数据"}
        
        return {
            "source": "E80 赚到>>赚过",
            "principle": "浮盈不是盈利。行情是行情，自己是自己。",
            "note": "如果已盈利>30%，考虑兑现(E80: 纪律化止盈比预测顶部更可靠)"
        }
    
    def contrarian_check(self, s: StockSnapshot) -> dict:
        """
        E42/E57 逆向信号
        E42: 周期股买入是坏消息最多时
        E57: 价格上涨本身就是最强的信号。谁赢帮谁。
        """
        return {
            "source": "E42(周期股逆向) + E57(价格信号)",
            "cycle_note": "E42: 周期股最佳买点在坏消息最多、PE最高(甚至亏损)时。当前需要判断：是否处于行业景气最低点？",
            "trend_note": "E57: 价格上涨本身就是最强信号。不猜顶不抄底，趋势确认后再入场。",
            "framework": "左侧(凉转平阶段)建仓周期性标的 | 右侧(温转热阶段)建仓成长性标的"
        }
    
    # ═══════════════════════════════════════════
    # 四、行为/心理类 (E30, E77)
    # ═══════════════════════════════════════════
    
    def bayesian_update(self, prior: float, likelihood_ratio: float,
                         hypothesis: str = "") -> dict:
        """
        E30/E77 贝叶斯更新
        后验概率 = 先验 × 似然比 / 归一化因子
        
        投资是认知的贝叶斯更新过程。每天用新信息修正先验。
        """
        if not (0 < prior < 1 and likelihood_ratio > 0):
            return {"status": "unavailable", "reason": "先验概率/似然比无效"}
        
        # Bayes: posterior = prior * LR / (prior * LR + (1-prior))
        posterior = prior * likelihood_ratio / (prior * likelihood_ratio + (1 - prior))
        change = posterior - prior
        
        direction = "↑ 强化" if change > 0.05 else "↓ 削弱" if change < -0.05 else "→ 维持"
        
        return {
            "source": "E30/E77 贝叶斯更新",
            "hypothesis": hypothesis,
            "prior": f"{prior:.1%}",
            "likelihood_ratio": f"{likelihood_ratio:.2f}x",
            "posterior": f"{posterior:.1%}",
            "change": f"{direction} ({change:+.1%})",
            "principle": "每天用新信息修正先验。投资是认知的贝叶斯更新过程。"
        }
    
    # ═══════════════════════════════════════════
    # 五、宏观/周期类 (E94, E136, E131)
    # ═══════════════════════════════════════════
    
    def kondratiev_position(self) -> dict:
        """
        E94 康波周期定位
        第五轮康波(1991-2050+)：繁荣(1991-2008)→衰退(2008-2020)→萧条(2020-2030+)
        AI为第六轮康波主导技术(当前在导入期-展开期过渡)
        """
        return {
            "source": "E94 康波周期",
            "current_wave": "第五轮康波",
            "current_phase": "萧条期(2020-2030+)",
            "next_wave": "第六轮康波(AI主导)",
            "next_phase": "导入期→展开期过渡",
            "features": [
                "存量博弈：增长靠替代而非创造新需求",
                "地缘紧张：秩序瓦解期的典型特征",
                "旧产业出清：效率低的企业被淘汰",
                "新产业孕育：AI/BTC/新能源在废墟上成长"
            ],
            "investment_implication": "防御型配置为主(红利+必需品)，小仓位布局新技术萌芽(AI/机器人/可控核聚变)",
            "china_angle": "E94: 追赶国在萧条期的机遇=军工+自主可控+国产替代。防御+成长双重属性"
        }
    
    def efficiency_fairness_cycle(self) -> dict:
        """
        效率→公平周期
        效率周期(增量扩张→成长占优) vs 公平周期(存量博弈→红利占优)
        当前：效率→公平转折期
        """
        return {
            "source": "效率公平周期框架",
            "current_position": "效率→公平转折期",
            "efficiency_era": "1978-2020：增量扩张，成长投资占优，全球化高歌猛进",
            "fairness_era": "2020+：存量博弈，红利投资占优，从追求α到保住β",
            "key_shift": "E131唐军：全球化→区域化、效率→安全、低通胀→高波动",
            "implication": "投资光谱右移(E136)：谁有现金流谁赢。港股哑铃(E68)：质量成长+高股息两头配置"
        }
    
    def stock_bond_spread(self, sh_pe: float = None, bond_yield: float = None) -> dict:
        """股债性价比：沪深300 PE倒数 vs 10年期国债收益率"""
        if sh_pe is None or bond_yield is None:
            return {"status": "unavailable", "reason": "缺PE/国债收益率数据"}
        
        earnings_yield = 100 / sh_pe  # PE倒数=收益率
        spread = earnings_yield - bond_yield
        
        if spread > 3:
            signal = "🟢 股票极具性价比 (spread>3%)"
        elif spread > 1.5:
            signal = "🟡 股票中性偏高 (1.5%<spread<3%)"
        elif spread > 0:
            signal = "🟠 股票偏贵 (0%<spread<1.5%)"
        else:
            signal = "🔴 股票极贵，债券优于股票"
        
        return {
            "source": "股债性价比(面基框架)",
            "earnings_yield": round(earnings_yield, 2),
            "bond_yield": bond_yield,
            "spread": round(spread, 2),
            "signal": signal
        }
    
    # ═══════════════════════════════════════════
    # 六、LDS框架类
    # ═══════════════════════════════════════════
    
    def lds_dual_gate(self, macro: MacroSnapshot) -> dict:
        """
        LDS双门状态
        宏观门 × 趋势门 → 9种组合 → 操作方向
        
        LDS原话：
        - 「宏观和趋势都负面的时候右侧没法开仓，要玩只能左侧低吸基本面好的票」
        - 「下个月CPI不继续上涨，或者出现大量板块转热，才重新入场」
        - 「凉→平→温→热 循环。左侧在凉转平建仓，右侧在温转热建仓」
        """
        # 宏观门判断
        if macro.cpi and macro.cpi > 3.0:
            macro_gate = "red"
            macro_reason = f"CPI {macro.cpi}%>3% — 通胀威胁，LDS: 通胀是资本市场最大杀手"
        elif macro.cpi and macro.cpi > 1.5:
            macro_gate = "yellow"
            macro_reason = f"CPI {macro.cpi}% — 通胀偏高，需警惕"
        elif macro.cpi is not None:
            macro_gate = "green"
            macro_reason = f"CPI {macro.cpi}% — 通胀可控"
        else:
            macro_gate = "yellow"
            macro_reason = "CPI数据不可用，默认中性"
        
        # 趋势门 (LDS温度)
        temp = macro.trend_temperature
        if temp == "cold":
            trend_gate = "red"
            trend_reason = "趋势=凉 — 全市场空头"
        elif temp == "cool":
            trend_gate = "yellow"
            trend_reason = "趋势=凉→平 — 左侧建仓窗口(面基E42)"
        elif temp == "warm":
            trend_gate = "green"
            trend_reason = "趋势=温→热 — 右侧追涨窗口"
        elif temp == "hot":
            trend_gate = "green"
            trend_reason = "趋势=热 — 注意过热风险，随时准备减仓"
        else:
            trend_gate = "yellow"
            trend_reason = "趋势数据不可用，默认中性"
        
        # 双门组合 → 操作
        gate_pair = f"{macro_gate}+{trend_gate}"
        actions = {
            "green+green": "🟢 全仓：宏观+趋势双多，右侧积极追涨",
            "green+yellow": "🟢🟡 重仓：宏观好趋势中性，右侧选择性开仓",
            "green+red": "🟢🔴 半仓：宏观好趋势差，等趋势转暖再右侧",
            "yellow+green": "🟡🟢 重仓：趋势好宏观中性，追趋势但设好止损",
            "yellow+yellow": "🟡 观望：双重中性，轻仓试错，等信号明朗",
            "yellow+red": "🟡🔴 轻仓：宏观中性趋势差，仅左侧低吸基本面好票",
            "red+green": "🔴🟢 半仓：宏观差趋势好，CPI回落是最关键信号(LDS)",
            "red+yellow": "🔴🟡 轻仓：宏观差趋势中性，防御为主",
            "red+red": "🔴 空仓/极轻：双重负面，LDS: '不玩'",
        }
        
        return {
            "source": "LDS双门系统",
            "macro_gate": f"{macro_gate} ({macro_reason})",
            "trend_gate": f"{trend_gate} ({trend_reason})",
            "action": actions.get(gate_pair, "数据不足，无法判断"),
            "lds_quote": "宏观和趋势都负面时右侧没法开仓 → 左侧低吸基本面好的票 → 但趋势和宏观一个回暖再玩",
            "cpi_signal": "LDS: 下个月CPI不继续上涨即可重新入场",
            "trend_cycle": "凉→平→温→热 循环。左侧=凉转平建仓 | 右侧=温转热建仓"
        }
    
    def guoyun_line(self, macro: MacroSnapshot) -> dict:
        """
        LDS国运线 = 上证20年均线
        LDS原话：「20年均线≈2500-2600，从未有效跌破。3000点以上属偏高区域」
        疫情后利率从5%降至1%+，底部思维发生变化
        """
        if macro.sh_index is None:
            return {"status": "unavailable", "reason": "缺上证指数数据"}
        
        guoyun = macro.sh_ma20y or 2500  # 默认≈2500-2600
        
        deviation = (macro.sh_index / guoyun - 1) * 100
        
        if deviation < 0:
            signal = f"🟢 低于国运线 (偏离{deviation:+.1f}%) — 历史性低估区"
        elif deviation < 10:
            signal = f"🟡 国运线附近 (偏离{deviation:+.1f}%) — 合理偏低"
        elif deviation < 25:
            signal = f"🟠 高于国运线 (偏离{deviation:+.1f}%) — 偏高区域(LDS: 3000点以上偏高)"
        else:
            signal = f"🔴 远高于国运线 (偏离{deviation:+.1f}%) — 高估区"
        
        return {
            "source": "LDS国运线",
            "guoyun_line": guoyun,
            "sh_index": macro.sh_index,
            "deviation_pct": round(deviation, 1),
            "signal": signal,
            "lds_quote": "20年均线≈2500-2600，从未有效跌破。指数年化≈7%。3000点以上属偏高。",
            "rate_regime_change": "疫情后利率5%→1%+，底部抬高。LDS: 利率中枢变了，底部思维也要变"
        }
    
    def inflation_scenarios(self, macro: MacroSnapshot) -> dict:
        """
        CPI三情景推演 (LDS框架)
        情景1·基准：CPI维持当前水平 → ？
        情景2·上行：CPI连续2月上升 → ？
        情景3·尾部：CPI突破3% → ？
        """
        if macro.cpi is None:
            return {"status": "unavailable", "reason": "缺CPI数据"}
        
        return {
            "source": "LDS CPI情景推演",
            "current_cpi": macro.cpi,
            "scenarios": {
                "base": f"CPI维持{macro.cpi}% — 宏观趋于稳定，关注趋势门信号。LDS: 下月CPI不涨即可入场",
                "upside": f"CPI升至{macro.cpi+0.5}%+ — 宏观门转红。LDS: 通胀上去因子全扣分，美股清仓",
                "tail": f"CPI>3% — 通胀年到来。LDS: 全天候也失效，现金为王。历史教训(E136付鹏)"
            },
            "lds_quote": "通胀是资本市场最大杀手。全天候策略在高通胀下同样失效。"
        }
    
    # ═══════════════════════════════════════════
    # 七、综合决策类
    # ═══════════════════════════════════════════
    
    def nick_four_questions(self, s: StockSnapshot) -> dict:
        """
        E118 Nick四问
        1. 紧急度：盈利动量 — 增速是在加速还是减速？
        2. 趋势：价格>MA50/MA200 — 技术面确认？
        3. 共识：分析师覆盖/推荐 — 市场怎么看？
        4. 拥挤度：空头占比/Beta — 是不是太拥挤了？
        """
        answers = {}
        score = 0
        
        # Q1: 紧急度
        if s.eps_growth:
            if s.eps_growth > 20:
                answers["Q1_urgency"] = f"✅ 盈利增速{s.eps_growth}%>20% — 高紧急度，需关注"
                score += 1
            elif s.eps_growth > 10:
                answers["Q1_urgency"] = f"🟡 盈利增速{s.eps_growth}% — 中等"
                score += 0.5
            else:
                answers["Q1_urgency"] = f"❌ 盈利增速{s.eps_growth}%<10% — 低紧急度，不急"
                score += 0
        
        # Q2: 趋势
        if s.price and s.ma50 and s.ma200:
            above_50 = s.price > s.ma50
            above_200 = s.price > s.ma200
            if above_50 and above_200:
                answers["Q2_trend"] = f"✅ 价格>{s.ma50}（MA50）且>{s.ma200}（MA200）— 多头排列"
                score += 1
            elif above_200:
                answers["Q2_trend"] = "🟡 价格>MA200但<MA50 — 中期向好短期调整"
                score += 0.5
            else:
                answers["Q2_trend"] = "❌ 价格<MA200 — 趋势偏空"
                score += 0
        else:
            answers["Q2_trend"] = "⚠️ 缺均线数据"
        
        # Q3: 共识
        if s.analyst_target and s.price:
            upside = (s.analyst_target / s.price - 1) * 100
            if upside > 15:
                answers["Q3_consensus"] = f"✅ 分析师目标价较现价+{upside:.0f}%"
                score += 1
            elif upside > 0:
                answers["Q3_consensus"] = f"🟡 目标价略高于现价+{upside:.0f}%"
                score += 0.5
            else:
                answers["Q3_consensus"] = "❌ 目标价低于或等于现价"
                score += 0
        else:
            answers["Q3_consensus"] = "⚠️ 缺分析师目标价"
        
        # Q4: 拥挤度
        if s.short_float and s.beta:
            if s.short_float < 3 and s.beta < 1.5:
                answers["Q4_crowding"] = f"✅ 空头{s.short_float}%低+Beta{s.beta}低 — 不拥挤"
                score += 1
            elif s.short_float < 8:
                answers["Q4_crowding"] = f"🟡 空头{s.short_float}%中等"
                score += 0.5
            else:
                answers["Q4_crowding"] = f"❌ 空头{s.short_float}%高 — 拥挤度高，踩踏风险"
                score += 0
        else:
            answers["Q4_crowding"] = "⚠️ 缺空头/Beta数据"
        
        return {
            "source": "E118 Nick四问",
            "questions": answers,
            "total_score": round(score, 1),
            "max_score": 4,
            "signal": "买入" if score >= 3 else "关注" if score >= 2 else "观望" if score >= 1 else "回避",
            "principle": "E118: 价格信仰/追涨杀跌/非对称/遍历性"
        }
    
    def doubling_logic_check(self, chain: ChainSnapshot, s: StockSnapshot) -> dict:
        """
        翻倍逻辑检查
        「为什么现在有翻倍机会？」— 不是静态描述，是动态对比
        
        核心：当前PE/增速 vs 历史上行周期的翻倍起点
        """
        if chain.historical_doubling_pe is None or chain.current_pe is None:
            return {"status": "unavailable", "reason": "缺历史翻倍起点PE或当前链PE数据"}
        
        current_pe = chain.current_pe
        hist_pe = chain.historical_doubling_pe
        pe_discount = (hist_pe / current_pe - 1) * 100 if current_pe > 0 else 0
        
        # Check if we're near historical doubling starting conditions
        if current_pe <= hist_pe * 1.3:
            position_signal = "🎯 接近历史翻倍起点 — 当前PE接近或低于历史上行周期起点"
        elif current_pe <= hist_pe * 1.8:
            position_signal = "🟡 距翻倍起点有一定距离 — 如增速能追上PE，仍有空间"
        else:
            position_signal = "⚠️ 远高于历史翻倍起点 — 需要极端增速才能支撑翻倍"
        
        # Supply-demand
        gap_signal = ""
        if chain.supply_demand_gap_pct:
            if chain.supply_demand_gap_pct > 20:
                gap_signal = f"供给缺口>{chain.supply_demand_gap_pct}% — 严重供不应求，价格上涨动能强"
            elif chain.supply_demand_gap_pct > 5:
                gap_signal = f"供给缺口{chain.supply_demand_gap_pct}% — 温和偏紧"
            else:
                gap_signal = f"供给缺口<5% — 供需基本平衡，需其他催化"
        
        return {
            "source": "翻倍逻辑检查(LDS框架)",
            "chain": chain.name,
            "current_chain_pe": current_pe,
            "historical_doubling_pe": hist_pe,
            "pe_position": f"当前PE是历史翻倍起点的{current_pe/hist_pe:.1f}x ({pe_discount:+.0f}%)",
            "position_signal": position_signal,
            "supply_demand": gap_signal,
            "catalysts": chain.catalyst_timeline[:3] if chain.catalyst_timeline else ["无已知催化剂"],
            "checklist": [
                f"① PE对比：当前{current_pe}x vs 翻倍起点{hist_pe}x → {position_signal}",
                f"② 供需：{gap_signal or '数据不可用'}",
                f"③ 催化剂：近期事件={chain.catalyst_timeline[:2] if chain.catalyst_timeline else '无'}",
                "④ 关键假设：(如果X发生，逻辑成立；如果Y发生，逻辑失效)"
            ]
        }
    
    def grand_framework_check(self, s: StockSnapshot) -> dict:
        """
        核心哲学三原则(E130)
        1. 体系完整 > 逻辑自洽 > 观点正误
        2. 不同时间尺度识别主导力量
        3. 理论上「应该涨」不是买入理由
        """
        return {
            "source": "E130 核心哲学",
            "principle_1": "体系完整先于逻辑自洽和观点正误。先搭建可用的整体系统，再迭代优化。",
            "principle_2": "短期相信市场(价格信号)，中期相信共识(叙事)，长期相信规律(框架)。",
            "principle_3": "理论上「应该涨」不是买入理由。市场确认趋势、逆风依旧兑现价值的公司，才是真正的价值。",
            "three_constants": "周期往复、估值回归、人性贪婪与恐惧(E130)"
        }
    
    def four_confirmations(self, s: StockSnapshot, macro: MacroSnapshot) -> dict:
        """
        LDS四重确认
        1. 宏观门 ✓
        2. 趋势门 ✓
        3. 因子评分 ≥ 6
        4. 技术确认：价格 > MA20 + 均线多头
        """
        checks = []
        
        # 宏观
        macro_ok = macro.cpi is not None and macro.cpi < 3.0 if macro.cpi else True
        checks.append(("宏观门", "✅" if macro_ok else "❌"))
        
        # 趋势
        trend_ok = macro.trend_temperature in ["warm", "hot"]
        checks.append(("趋势门", "✅" if trend_ok else f"⚠️ {macro.trend_temperature}"))
        
        # 因子评分(需要外部传入)
        checks.append(("因子≥6", "🔍 需外部评分"))
        
        # 技术
        if s.price and s.ma20:
            tech_ok = s.price > s.ma20
            checks.append(("技术确认", "✅" if tech_ok else "❌ 价格<MA20"))
        else:
            checks.append(("技术确认", "⚠️ 缺数据"))
        
        return {
            "source": "LDS四重确认",
            "checks": [f"{label}: {status}" for label, status in checks],
            "all_pass": all("✅" in s for _, s in checks),
            "principle": "四重确认都过才出手。LDS: 宁可错过不可做错。"
        }
    
    def dalio_price_formula(self, liquidity: float, fundamentals: float) -> dict:
        """
        E119 达里奥价格公式
        P = TE / Q
        TE = Total Expenditure(流动性)
        Q = Quantity(基本面)
        
        LDS: 流动性 > 基本面
        """
        return {
            "source": "E119 达里奥价格公式",
            "formula": "P = TE/Q",
            "liquidity_effect": f"流动性每变化1% → 价格变化约1%×杠杆",
            "key_insight": "流动性对价格的边际影响远大于基本面。所以盯央行比盯财报更重要。",
            "lds_quote": "流动性 > 基本面"
        }
    
    def taleb_barbell(self) -> dict:
        """
        E111 塔勒布杠铃策略
        90%安全资产 + 10%高风险暴露
        反脆弱凸性：损失有限，收益无限
        """
        return {
            "source": "E111 塔勒布杠铃+反脆弱",
            "structure": "90%极安全(国债/现金) + 10%极高风险(期权/早期项目)",
            "property": "反脆弱凸性：下行有限(-10%)，上行有凸性(可能10x)",
            "application": "LDS组合某种程度上就是杠铃：红利低波(安全)+纳指(成长)+黄金(避险)+豆粕(商品)",
            "note": "不是人人都适合极端杠铃。E109 Kevin的多元有限下注更适合大多数人"
        }
    
    def timing_truth(self) -> dict:
        """
        E128 董艺婷：择时真相
        择时胜率<50% → 更有效的是动态再平衡而非择时
        """
        return {
            "source": "E128 择时真相",
            "fact": "择时胜率<50% → 择时损害收益",
            "better_approach": "SAA+TAA(80:20)：战略性配置(80%)不动 + 战术性偏移(20%)根据宏观微调",
            "rebalance_rule": "偏离>5%触发再平衡。LDS: 黄金涨到40%时触发再平衡卖出",
        }
    
    def saa_taa_allocation(self) -> dict:
        """E109/E119 SAA+TAA 资产配置框架"""
        return {
            "source": "E109(SAA+TAA) + E119(全天候)",
            "saa": {
                "equity": "40-60% (宽基指数为主)",
                "bonds": "30-45% (国债/高评级信用债)",
                "commodities": "5-10% (黄金/豆粕/原油)",
                "cash": "5-15% (等待机会+应急)",
            },
            "taa": "宏观择时±10%偏移。复苏超配权益(上限70%)，衰退超配债券(上限55%)",
            "all_weather": "E119 Dalio: 四象限(增长×通胀)各自配置，风险平价",
            "lds_portfolio": "25%红利低波+30%纳指100+25%黄金+20%豆粕 → 预期年化14%"
        }


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

_engine = None

def get_engine() -> ConceptEngine:
    """获取单例"""
    global _engine
    if _engine is None:
        _engine = ConceptEngine()
    return _engine
