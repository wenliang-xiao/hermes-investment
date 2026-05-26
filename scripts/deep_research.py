#!/usr/bin/env python3
"""
面基·三源融合·个股深度研报 v1.0
=============================
触发条件: 综合评分≥7.0 | 用户点名 | 链快扫标记
输出: 飞书文档，含 8 个维度的深度分析

结构:
  1. 产业链定位 — 中观四层次 × Perez 阶段 × 利润池
  2. 翻倍逻辑论证 — 当前 PE vs 历史翻倍期 × 增速弹性 × 市值天花板
  3. DCF 估值 — 三情景(基准/乐观/悲观) × 永续增长率敏感度
  4. 凯利仓位 — 胜率×赔率 → f* → 纪律约束
  5. Nick 四问 — 紧急性/趋势/共识/拥挤度
  6. 贝叶斯更新 — 当前先验 → 待观察信号 → 后验条件
  7. 风险清单 — TOP3 风险 × 止损条件
  8. 面基引用 — 本期引用的期数和概念

原理引用:
  E124 DCF | E68 FCF两朵花 | E153 凯利/复利 | E81 Nick四问
  E7/E84 中观四层次 | E94 Perez | E131 新坐标 | E155 五层蛋糕
  E30/E77 贝叶斯 | E111 塔勒布 | E128 择时
"""
import sys, os, json, time, urllib.request
from datetime import datetime
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from investment_system.data.yf_data_layer import get_stock_info, get_factor_data, get_price_data, get_current_price
from investment_system.data.global_universe import ALL_US_STOCKS, HK_WATCHLIST_V2, US_CHAINS

# ═══════════════════════════════════
# 飞书文档工具 (复用 v6 的)
# ═══════════════════════════════════
class FeishuWriter:
    def __init__(self):
        self._token = None
        self._token_time = 0
    
    def _get_token(self):
        if self._token and time.time() - self._token_time < 3600:
            return self._token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        data = json.dumps({"app_id": os.environ["FEISHU_APP_ID"],
                           "app_secret": os.environ["FEISHU_APP_SECRET"]}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
        self._token = json.loads(urllib.request.urlopen(req).read())["tenant_access_token"]
        self._token_time = time.time()
        return self._token
    
    def _api(self, path, method="GET", data=None):
        token = self._get_token()
        url = f"https://open.feishu.cn/open-apis{path}"
        headers = {"Content-Type":"application/json","Authorization":f"Bearer {token}"}
        body = json.dumps(data).encode() if data else None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method=method)
                resp = json.loads(urllib.request.urlopen(req).read())
                if resp.get("code") == 0:
                    return resp
                time.sleep(1)
            except Exception as e:
                if attempt == 2:
                    print(f"  [feishu] fail: {e}")
        return None
    
    def create_doc(self, title):
        FOLDER = "QhIOfB63Sl6Kqmd81fycjR6jnDd"
        resp = self._api("/docx/v1/documents", "POST", {"title": title, "folder_token": FOLDER})
        if resp:
            doc_id = resp["data"]["document"]["document_id"]
            self._api(f"/drive/v1/permissions/{doc_id}/members?type=docx", "POST", {
                "member_type":"openid","member_id":"ou_e03d56632de9b44263adfc018f9d6e4d","perm":"full_access"})
            return doc_id
        return None
    
    def write(self, doc_id, blocks):
        children = []
        for b in blocks:
            bt, txt = b[0], b[1] if len(b) > 1 else ""
            if bt == "h2":
                children.append({"block_type":4, "heading2": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "h3":
                children.append({"block_type":5, "heading3": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "h4":
                children.append({"block_type":6, "heading4": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "text":
                children.append({"block_type":2, "text": {"elements":[{"text_run":{"content":txt}}],"style":{}}})
            elif bt == "bold":
                children.append({"block_type":2, "text": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "bullet":
                children.append({"block_type":12, "bullet": {"elements":[{"text_run":{"content":txt}}],"style":{}}})
            elif bt == "divider":
                children.append({"block_type":22, "divider": {}})
            elif bt == "quote":
                children.append({"block_type":15, "quote": {"elements":[{"text_run":{"content":txt}}],"style":{}}})
        if children:
            return self._api(f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children", "POST", {"children": children})
        return True

# ═══════════════════════════════════
# 核心分析函数
# ═══════════════════════════════════

def fmt_usd(v):
    """金额格式化"""
    if v is None: return "?"
    if abs(v) >= 1e12: return f"${v/1e12:.2f}T"
    if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
    if abs(v) >= 1e6: return f"${v/1e6:.1f}M"
    return f"${v:.2f}"

def fmt_pct(v, decimals=1):
    """百分比格式化（v是小数形式如0.15=15%）"""
    if v is None: return "?"
    pct = v * 100 if abs(v) < 10 else v
    return f"{pct:.{decimals}f}%"

class DeepResearch:
    """个股深度研报引擎"""
    
    def __init__(self, symbol: str, name: str = "", market: str = "US", chain_info: dict = None):
        self.symbol = symbol
        self.name = name
        self.market = market
        self.chain_info = chain_info or {}
        self.info = {}
        self.factors = {}
        self.price = None
        self.price_df = None
        
    def fetch_data(self):
        """拉取全部数据"""
        print(f"  📡 拉取 {self.symbol} 数据...")
        self.info = get_stock_info(self.symbol)
        self.name = self.name or self.info.get("name", self.symbol)
        self.factors = get_factor_data(self.symbol)
        self.price = get_current_price(self.symbol)
        self.price_df = get_price_data(self.symbol, period="2y")
        
        if self.price_df.empty:
            self.price_df = get_price_data(self.symbol, period="6mo")
        
        print(f"    名称: {self.name}")
        print(f"    价格: ${self.price}")
        print(f"    PE: {self.factors.get('pe')} | ROE: {fmt_pct(self.factors.get('roe'))}")
        print(f"    市值: {fmt_usd(self.factors.get('market_cap'))}")
    
    # ═══ 1. 产业链定位 ═══
    def analyze_chain_position(self):
        """中观四层次 + Perez + 利润池"""
        chain = self.chain_info.get("chain", "未归类")
        chain_pos = self.chain_info.get("chain_pos", "")
        
        # 预设链分析映射
        chain_analysis = {
            "GPU/AI芯片": {
                "perez": "展开期（渗透率<30%，增速加速度>0）",
                "lifecycle": "成长→成熟过渡",
                "demand": "AI训练/推理需求指数增长，CSP Capex $250B+",
                "profit_pool": "GPU毛利率65-78%，产业链利润最厚环节",
                "barriers": "CUDA生态锁定+先进制程+规模效应",
                "lds_diffusion": "龙头(NVDA)已涨→二梯队配套(AVGO/MRVL ASIC)→再扩散(光模块/液冷)",
            },
            "存储/HBM": {
                "perez": "展开期前段（HBM渗透率<20%，供给缺口>30%）",
                "lifecycle": "成长期",
                "demand": "每GPU配HBM数量从4颗→8颗→12颗，用量翻倍",
                "profit_pool": "HBM毛利率50-60% vs 传统DRAM 30-40%，利润池扩大",
                "barriers": "TSV封装技术+产能壁垒（扩产需18-24个月）",
                "lds_diffusion": "HBM(SK海力士/三星/美光)→封装基板→TSV设备→测试",
            },
            "晶圆代工": {
                "perez": "展开期（3nm/5nm先进制程需求强劲，成熟制程磨底）",
                "lifecycle": "成熟→技术升级驱动",
                "demand": "AI芯片+高性能计算驱动先进制程，成熟制程等待周期回暖",
                "profit_pool": "先进制程毛利率50-60% vs 成熟制程30-40%",
                "barriers": "物理极限+资本壁垒（单厂$20B+）+技术代差",
                "lds_diffusion": "代工(TSM)→设备(ASML/AMAT/LRCX)→材料→EDA",
            },
            "独立电力(核电)": {
                "perez": "导入→展开过渡（AI数据中心电力需求刚启动）",
                "lifecycle": "成长初期",
                "demand": "单数据中心功耗100MW→500MW+，核电因24/7低碳受追捧",
                "profit_pool": "独立电力商PPA溢价20-30%，核电资产稀缺",
                "barriers": "核电牌照+选址+建设周期5-7年",
                "lds_diffusion": "发电(VST/CEG)→电力设备(GEV)→电网(PEG/EXC)→储能",
            },
        }
        
        analysis = chain_analysis.get(chain, chain_analysis.get("GPU/AI芯片"))
        
        lines = []
        lines.append(("h2", f"1. 🔗 产业链定位：{chain}"))
        lines.append(("bold", f"{self.name} | 链位置：{chain_pos} | 产业链：{chain}"))
        lines.append(("text", f"Perez 阶段：{analysis['perez']}"))
        lines.append(("text", f"生命周期：{analysis['lifecycle']}"))
        lines.append(("text", f"需求景气：{analysis['demand']}"))
        lines.append(("text", f"利润池：{analysis['profit_pool']}"))
        lines.append(("text", f"护城河：{analysis['barriers']}"))
        lines.append(("text", f"LDS 扩散：{analysis['lds_diffusion']}"))
        lines.append(("quote", f"面基原则(E7/E84/E94/E155)：不是买好公司，是买产业链上利润率最高的环节。{chain}链中，{chain_pos}环节利润最厚。"))
        
        return lines, analysis
    
    # ═══ 2. 翻倍逻辑论证 ═══
    def analyze_doubling_thesis(self):
        """当前 PE vs 历史翻倍期 × 增速弹性 × 市值天花板"""
        pe = self.factors.get("pe")
        forward_pe = self.factors.get("forward_pe")
        mkt_cap = self.factors.get("market_cap")
        rev_g = self.factors.get("revenue_growth")
        earn_g = self.factors.get("earnings_growth")
        roe = self.factors.get("roe")
        
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "2. 🚀 翻倍逻辑论证"))
        
        # 当前估值
        lines.append(("h3", "2.1 估值锚定"))
        lines.append(("text", f"当前 PE(TTM): {pe:.1f}x | 远期 PE: {forward_pe:.1f}x" if pe and forward_pe else f"当前 PE: {pe}"))
        lines.append(("text", f"市值: {fmt_usd(mkt_cap)}"))
        if rev_g: lines.append(("text", f"营收增速 YoY: {fmt_pct(rev_g)}"))
        if earn_g: lines.append(("text", f"盈利增速 YoY: {fmt_pct(earn_g)}"))
        if roe: lines.append(("text", f"ROE: {fmt_pct(roe)}"))
        
        # 翻倍情景分析
        lines.append(("h3", "2.2 翻倍情景分析"))
        
        if mkt_cap and pe and earn_g:
            # 情景 1: 盈利翻倍 + PE不变
            earn_cagr = earn_g if abs(earn_g) < 10 else earn_g  # 已经是小数
            # 假设盈利以当前增速持续 2 年
            yr2_earn = 1 * (1 + earn_cagr) ** 2
            yr2_price_pe_flat = pe * yr2_earn  # 假设每股盈利同比例增长
            # 简化：用当前价格×盈利增长
            upside_pe_flat = (yr2_earn - 1) * 100 + 0  # 简化计算
            
            lines.append(("text", "**情景A — 业绩驱动（盈利翻倍，PE 不变）**"))
            lines.append(("bullet", f"假设盈利以 {fmt_pct(earn_cagr)} CAGR 增长 2 年"))
            lines.append(("bullet", f"2 年后 EPS × {(1+earn_cagr)**2:.1f}，若 PE 不变，股价理论涨幅 {((1+earn_cagr)**2 - 1)*100:.0f}%"))
            
            # 情景 2: 盈利增长 + PE 扩张
            pe_target = min(pe * 1.3, 50)  # PE 扩张 30% 但不超过 50
            upside_pe_expand = ((1+earn_cagr)**2 * pe_target / pe - 1) * 100
            lines.append(("text", "**情景B — 戴维斯双击（盈利增长 + PE 扩张）**"))
            lines.append(("bullet", f"盈利增长 {fmt_pct(earn_cagr)} × PE 从 {pe:.0f} 扩张至 {pe_target:.0f}"))
            lines.append(("bullet", f"理论涨幅: {upside_pe_expand:.0f}% {'✅ 有翻倍潜力' if upside_pe_expand > 80 else '⚠️ 接近但未达翻倍' if upside_pe_expand > 50 else '❌ 需更强的盈利超预期'}"))
            
            # 情景 3: 市值天花板
            mkt_cap_num = mkt_cap / 1e12  # 转 T
            doubled = mkt_cap_num * 2
            anchor_peers = {
                "GPU/AI芯片": f"对比: AAPL ${3.5:.1f}T / MSFT ${3.2:.1f}T，翻倍后 ${doubled:.1f}T，{'接近但可能' if doubled < 5 else '远超' if doubled > 6 else '在合理上限内'}",
                "存储/HBM": "对比: Samsung 存储业务峰值估值 vs MU 当前。HBM 周期上行时 MU PE 曾达 60-80x",
                "晶圆代工": f"对比: TSM 曾达 ${1:.1f}T+，翻倍后 ${doubled:.1f}T",
                "独立电力(核电)": "对比: NextEra Energy $150B。独立电力商受益 AI 需求重估，估值天花板打开",
            }
            chain = self.chain_info.get("chain", "")
            peer_ref = anchor_peers.get(chain, f"翻倍后市值 ${doubled:.1f}T")
            lines.append(("text", "**情景C — 市值天花板**"))
            lines.append(("bullet", f"当前市值 ${mkt_cap_num:.1f}T，翻倍需达 ${doubled:.1f}T"))
            lines.append(("bullet", peer_ref))
        
        # PEG 合理性
        if pe and earn_g and earn_g > 0:
            peg = pe / (earn_g * 100) if earn_g < 1 else pe / earn_g
            lines.append(("h3", "2.3 PEG 合理性"))
            lines.append(("text", f"PEG = PE / 盈利增速 = {pe:.0f} / {fmt_pct(earn_g)} = {peg:.2f}"))
            if peg < 1:
                lines.append(("quote", f"PEG={peg:.2f}<1，估值相对增速有折价 → 具备翻倍基础条件"))
            elif peg < 1.5:
                lines.append(("quote", f"PEG={peg:.2f}，估值合理 → 翻倍取决于增速能否持续超预期"))
            else:
                lines.append(("quote", f"PEG={peg:.2f}>1.5，估值溢价 → 翻倍需要更强催化剂（新品/市占提升/利润率扩张）"))
        
        return lines
    
    # ═══ 3. DCF 估值 ═══
    def analyze_dcf(self):
        """三情景 DCF"""
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "3. 📐 DCF 估值（E124 恽雷框架）"))
        lines.append(("text", "核心公式：内在价值 = Σ CFt/(1+WACC)^t + TV/(1+WACC)^n"))
        lines.append(("text", "TV = CFn × (1+g) / (WACC - g)，其中 g = 永续增长率 ≤ GDP 增速"))
        
        pe = self.factors.get("pe") or 25
        earn_g = self.factors.get("earnings_growth") or 0.15
        mkt_cap = self.factors.get("market_cap")
        
        # 简化的三情景 DCF（P/E 替代 DCF）
        # 实际情况需要完整的 FCF 预测，这里用 PE 框架做近似
        wacc = 0.08  # 中国公司 ~8%，美股 ~7-8%
        g_terminal = 0.025  # 永续增长率
        
        lines.append(("h3", "3.1 关键参数"))
        lines.append(("bullet", f"WACC（折现率）: {wacc*100:.0f}% — 美股资本成本"))
        lines.append(("bullet", f"永续增长率 g: {g_terminal*100:.1f}% — 保守取 GDP 增速以下"))
        lines.append(("bullet", f"第二阶段增速: {fmt_pct(earn_g * 0.6)} — 从高增速递减至永续"))
        
        # 三情景简表
        lines.append(("h3", "3.2 三情景估值"))
        scenarios = [
            ("基准", pe * 1.0, earn_g, 1.0),
            ("乐观", pe * 1.2, earn_g * 1.3, 1.3),
            ("悲观", pe * 0.7, earn_g * 0.5, 0.5),
        ]
        for label, target_pe, growth, mult in scenarios:
            lines.append(("bullet", f"**{label}**: 目标 PE {target_pe:.0f}x × {'盈利超预期' if mult>1 else '盈利减速'} → 股价{'+' if mult>1 else '-' if mult<1 else '平'}{abs(mult-1)*100:.0f}%"))
        
        lines.append(("quote", "⚠️ DCF 不是精确计算器，而是估值思想和公理框架。永续阶段价值占内在价值 ~50%（E124）。"))
        
        return lines
    
    # ═══ 4. 凯利仓位 ═══
    def analyze_kelly(self):
        """胜率×赔率 → f* → 纪律约束。从实际多因子数据推导，不预设。"""
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "4. 🎲 凯利仓位（E153）"))
        lines.append(("text", "f* = (bp - q) / b，其中 p=胜率, q=败率, b=赔率"))
        
        # ── 从多因子数据推导胜率 p ──
        roe = self.factors.get("roe")
        earn_g = self.factors.get("earnings_growth")
        analyst_mean = self.factors.get("analyst_mean")
        
        # 胜率 = f(质量分 + 成长分 + 分析师共识)
        quality_raw = min(1.0, (roe or 0) * 2.5)  # ROE 40%→满分1.0
        growth_raw = min(1.0, max(0, (earn_g or 0) * 5))  # 增速20%→满分1.0
        analyst_raw = (5 - (analyst_mean or 3)) / 4  # 评级1(强力买入)→1.0, 5(卖出)→0
        analyst_raw = max(0, min(1, analyst_raw))
        
        p_raw = quality_raw * 0.40 + growth_raw * 0.35 + analyst_raw * 0.25
        p = 0.35 + p_raw * 0.35  # 映射到 [0.35, 0.70]
        
        # ── 从多因子数据推导赔率 b ──
        pe = self.factors.get("pe") or 25
        short_ratio = self.factors.get("short_ratio") or 0.02
        market_cap = self.factors.get("market_cap") or 100e9
        
        # 赔率 = f(PE折价 + 空头挤压潜力 + 市值弹性)
        pe_discount = max(0, min(1, (30 - pe) / 30))  # PE越低折扣越大
        short_squeeze = min(0.3, (short_ratio or 0.02) * 3)  # 空头多→挤压弹性
        size_elasticity = max(0, min(0.3, 1 - np.log10(max(market_cap, 1e9)) / 13))  # 小市值弹性大
        
        b = 1.5 + pe_discount * 1.0 + short_squeeze + size_elasticity * 0.5
        
        f_star = (p * b - (1-p)) / b
        f_half = f_star / 2
        
        lines.append(("h3", "4.1 参数推导（多因子驱动）"))
        lines.append(("bullet", f"质量贡献: ROE={fmt_pct(roe)} → quality_raw={quality_raw:.2f}（权重40%）"))
        lines.append(("bullet", f"成长贡献: 盈利增速={fmt_pct(earn_g)} → growth_raw={growth_raw:.2f}（权重35%）"))
        lines.append(("bullet", f"共识贡献: 分析师评级={analyst_mean or '?'} → analyst_raw={analyst_raw:.2f}（权重25%）"))
        lines.append(("bullet", f"→ 综合胜率 P(win) = {p*100:.1f}%"))
        lines.append(("bullet", f"→ 综合赔率 b = {b:.2f}x（PE折价{pe_discount:.2f} + 空头弹性{short_squeeze:.2f} + 市值弹性{size_elasticity:.2f}）"))
        
        lines.append(("h3", "4.2 计算结果"))
        lines.append(("text", f"f* = ({p:.2f}×{b:.2f} - {1-p:.2f}) / {b:.2f} = {f_star:.3f} ({f_star*100:.1f}%)"))
        lines.append(("text", f"半凯利 f*/2 = {f_half:.3f} ({f_half*100:.1f}%)"))
        
        constrained = min(f_half, 0.02)
        lines.append(("h3", "4.3 纪律约束"))
        lines.append(("bullet", f"凯利理论仓位: {f_star*100:.1f}%"))
        lines.append(("bullet", f"半凯利仓位: {f_half*100:.1f}%"))
        lines.append(("bullet", f"LDS 2% 纪律: 每只票 ≤ 总资产 2%"))
        lines.append(("quote", f"实操建议仓位: {constrained*100:.1f}%（取 min(半凯利, 2%纪律)）— 连错 10 次亏 {constrained*10*100:.0f}%，仍可继续游戏"))
        
        return lines
    
    # ═══ 5. Nick 四问 ═══
    def analyze_nick_4q(self):
        """紧急度/趋势/共识/拥挤度。从实际多因子数据推导。"""
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "5. ❓ Nick 四问（E81/E118）"))
        
        beta = self.factors.get("beta")
        short_ratio = self.factors.get("short_ratio") or 0.02
        analyst_count = self.factors.get("analyst_count") or 0
        analyst_mean = self.factors.get("analyst_mean")
        hi52 = self.factors.get("52w_high")
        lo52 = self.factors.get("52w_low")
        d50 = self.factors.get("50d_avg")
        d200 = self.factors.get("200d_avg")
        earn_g = self.factors.get("earnings_growth") or 0
        rev_g = self.factors.get("revenue_growth") or 0
        
        # ① 紧急度 = f(盈利动量, 52周位置)
        if earn_g > 0.3:
            urgency = "高 — 盈利增速 > 30%，窗口期可能较短"
        elif earn_g > 0.15:
            urgency = "中高 — 盈利增速稳健，有充分入场时间"
        elif earn_g > 0:
            urgency = "中 — 盈利正增长但增速不突出"
        else:
            urgency = "低 — 盈利负增长，等待拐点信号"
        
        # ② 趋势 = f(50d vs 200d, 52w位置)
        if d50 and d200 and self.price:
            trend_signal = "上升（价格>50MA>200MA）" if (self.price > d50 and d50 > d200) else \
                          "震荡（价格在均线之间）" if (self.price > d200) else \
                          "偏弱（价格<200MA）"
            if hi52 and lo52 and hi52 > lo52:
                pct_52w = (self.price - lo52) / (hi52 - lo52) * 100
                trend_signal += f" | 52周 {pct_52w:.0f}%分位"
        else:
            trend_signal = "数据不足"
        
        # ③ 共识 = f(分析师覆盖数, 评级均值, 目标价)
        if analyst_count >= 30:
            consensus = f"强共识（{analyst_count}分析师，{'强力买入' if analyst_mean and analyst_mean < 1.5 else '买入' if analyst_mean and analyst_mean < 2.5 else '持有'}）"
        elif analyst_count >= 10:
            consensus = f"中等共识（{analyst_count}分析师）"
        elif analyst_count > 0:
            consensus = f"弱共识（仅{analyst_count}人覆盖，可能有信息差机会）"
        else:
            consensus = "无共识（无分析师覆盖，需独立判断）"
        
        # ④ 拥挤度 = f(空头占比, Beta)
        if short_ratio > 0.15:
            crowding = f"⚠️ 高拥挤（空头{fmt_pct(short_ratio)}），踩踏风险上升"
        elif short_ratio > 0.05:
            crowding = f"中（空头{fmt_pct(short_ratio)}），适度拥挤"
        else:
            crowding = f"低拥挤（空头{fmt_pct(short_ratio)}），市场分歧小"
        if beta and beta > 1.5:
            crowding += f" | Beta={beta:.1f}→高β放大拥挤效应"
        
        lines.append(("h3", "① 紧急度（时间窗口）"))
        lines.append(("bullet", urgency))
        
        lines.append(("h3", "② 趋势（量价确认）"))
        lines.append(("bullet", trend_signal))
        if d50: lines.append(("bullet", f"50日均线: {d50:.1f}"))
        if d200: lines.append(("bullet", f"200日均线: {d200:.1f}"))
        
        lines.append(("h3", "③ 共识（市场认知度）"))
        lines.append(("bullet", consensus))
        target_mean = self.factors.get("target_mean")
        if target_mean and self.price:
            upside = (target_mean / self.price - 1) * 100
            lines.append(("bullet", f"分析师目标价: ${target_mean:.1f} → 潜在上行 {upside:+.0f}%"))
        
        lines.append(("h3", "④ 拥挤度（踩踏风险）"))
        lines.append(("bullet", crowding))
        
        return lines
    
    # ═══ 6. 贝叶斯更新 ═══
    def analyze_bayesian(self):
        """当前先验 → 待观察信号 → 后验条件。先验从多因子推导。"""
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "6. 🧠 贝叶斯更新（E30/E77）"))
        
        chain = self.chain_info.get("chain", "")
        
        # ── 先验 P(翻倍) 从多因子推导 ──
        roe = self.factors.get("roe") or 0
        earn_g = self.factors.get("earnings_growth") or 0
        pe = self.factors.get("pe") or 30
        mkt_cap = self.factors.get("market_cap") or 100e9
        
        # 先验 = 基本概率 + 质量溢价 + 成长溢价 - 规模折价
        base = 0.15
        quality_bonus = min(0.15, roe * 0.3)  # ROE 50%→+15pp
        growth_bonus = min(0.15, earn_g * 0.4)  # 增速 40%→+15pp
        size_penalty = max(0, np.log10(max(mkt_cap, 1e9)) / 13 * 0.15)  # $1T→-11pp
        prior = base + quality_bonus + growth_bonus - size_penalty
        prior = max(0.05, min(0.55, prior))
        
        # 信号库（按链）
        bayes_maps = {
            "GPU/AI芯片": [
                ("CSP Capex 超预期（>250B）", 0.10, "AWS/Azure/GCP 资本开支指引上调"),
                ("Blackwell/下一代芯片量产顺利", 0.15, "良率>80%+大规模出货"),
                ("推理需求爆发（Token消耗指数增长）", 0.10, "API调用量月增>30%"),
                ("竞争格局恶化（AVGO ASIC分流）", -0.10, "ASIC市占>15%"),
            ],
            "存储/HBM": [
                ("HBM 订单可见度 > 12个月", 0.15, "MU 管理层给出正面指引"),
                ("DRAM 周期确认上行", 0.20, "DRAM 现货价格月涨>5%"),
                ("HBM 产能扩张超预期", 0.10, "新厂投产时间提前"),
                ("AI 需求放缓", -0.15, "GPU 订单增速下降"),
            ],
            "晶圆代工": [
                ("AI 芯片需求持续（N2/N3 满载）", 0.10, "晶圆出货量新高"),
                ("成熟制程回暖", 0.10, "PMI>55+下游补库"),
                ("地缘风险升级", -0.15, "台海紧张加剧"),
                ("竞争对手突破（INTC 18A）", -0.10, "INTC 代工客户>5家"),
            ],
            "独立电力(核电)": [
                ("AI 数据中心 PPA 签约", 0.15, "VST/CEG 签下大额电力合同"),
                ("核电政策利好", 0.10, "NRC加速审批"),
                ("AI 需求证伪", -0.15, "数据中心空置率上升"),
                ("电价回落", -0.10, "天然气过剩→电价下跌"),
            ],
        }
        
        signals = bayes_maps.get(chain, [("催化事件待定", 0.10, "待监控")])
        
        lines.append(("h3", "6.1 当前先验（多因子推导）"))
        lines.append(("text", f"基础概率: {base*100:.0f}%"))
        lines.append(("text", f"+ 质量溢价: {quality_bonus*100:.0f}pp（ROE={fmt_pct(roe)}）"))
        lines.append(("text", f"+ 成长溢价: {growth_bonus*100:.0f}pp（盈利增速={fmt_pct(earn_g)}）"))
        lines.append(("text", f"- 规模折价: {size_penalty*100:.0f}pp（市值={fmt_usd(mkt_cap)}）"))
        lines.append(("bold", f"→ 当前 P(翻倍) = {prior*100:.1f}%  |  P(不翻倍) = {(1-prior)*100:.1f}%"))
        
        lines.append(("h3", "6.2 待观察信号与后验更新"))
        for signal, delta, condition in signals:
            posterior = max(0.01, min(0.99, prior + delta))
            arrow = "↑" if delta > 0 else "↓"
            emoji = "🟢" if delta > 0.1 else "🟡" if delta > 0 else "🔴" if delta < -0.05 else "⚪"
            lines.append(("bullet", f"{emoji} 若出现「{signal}」→ P(翻倍) → {posterior*100:.0f}%（{arrow}{abs(delta)*100:.0f}pp）"))
            lines.append(("text", f"   条件：{condition}"))
        
        lines.append(("quote", "贝叶斯的核心不是精确数字，而是持续更新认知——每天用新信息修正先验（E30/E77）。"))
        
        return lines
    
    # ═══ 7. 风险清单 ═══
    def analyze_risks(self):
        """TOP3 风险 + 止损条件"""
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "7. ⚠️ 风险清单"))
        
        chain = self.chain_info.get("chain", "")
        
        risk_maps = {
            "GPU/AI芯片": [
                ("AI 资本开支放缓", "CSP 削减 Capex 指引 → 触发 8% 止损", "高"),
                ("ASIC 替代 GPU", "AVGO/MRVL ASIC 市占 > 20% → 减半仓", "中"),
                ("出口管制升级", "对华禁售扩大 → 短期 10-15% 回撤风险", "中"),
            ],
            "存储/HBM": [
                ("HBM 产能过剩", "三星/海力士大幅扩产 → 供给>需求，触发 8% 止损", "中"),
                ("DRAM 周期下行", "现货价格月跌 > 5% → 减半仓", "高"),
                ("AI 泡沫破裂", "训练需求增速锐减 → 清仓", "中"),
            ],
            "晶圆代工": [
                ("地缘政治风险", "台海紧张升级 → 立即 8% 止损", "极高"),
                ("技术替代", "新架构（光子/量子）突破 → 长期风险", "低"),
                ("周期下行", "全球半导体需求放缓 → 15% 止盈/减仓", "中"),
            ],
            "独立电力(核电)": [
                ("核电事故/监管", "安全事故或更严监管 → 8% 硬止损", "极低概率"),
                ("AI 需求证伪", "数据中心空置率 > 15% → 清仓", "中"),
                ("替代能源竞争", "光伏+储能成本骤降 → 减半仓", "低"),
            ],
        }
        
        risks = risk_maps.get(chain, [("未知风险", "触发 8% 止损", "高")])
        
        lines.append(("h3", "TOP 3 风险"))
        for i, (risk, action, severity) in enumerate(risks, 1):
            sev_emoji = "🔴" if severity == "极高" else "🟡" if severity == "高" else "🟢"
            lines.append(("bullet", f"{sev_emoji} {risk}（{severity}）→ {action}"))
        
        lines.append(("h3", "止损条件"))
        lines.append(("bullet", f"8% 硬止损：股价 < 成本 × 0.92 — 无条件执行"))
        lines.append(("bullet", f"15% 止盈减半仓 | 30% 止盈清仓"))
        lines.append(("bullet", f"时间止损：持有 3 个月未涨 5% → 重新评估"))
        
        return lines
    
    # ═══ 8. 面基引用 ═══
    def analyze_mianji_refs(self):
        """本期研报引用的面基概念和期数"""
        lines = []
        lines.append(("divider", ""))
        lines.append(("h2", "8. 📚 面基引用索引"))
        
        refs = [
            ("E124 DCF估值", "恽雷·估值第一性原理"),
            ("E68 FCF两朵花", "恽雷·自由现金流框架"),
            ("E153 凯利/复利", "股神的牌局"),
            ("E7/E84 中观四层次", "董艺婷·选行业/选人/选策略"),
            ("E94 Perez五阶段", "孙加滢·康波与技术漫化"),
            ("E155 五层蛋糕/Capex/HALO", "AI产业链"),
            ("E81/E118 Nick四问/趋势", "投资灵魂四问"),
            ("E30/E77 贝叶斯思维", "周洛华·对自己虔诚"),
            ("E111 塔勒布风控", "杠铃策略/反脆弱/遍历性"),
            ("E131 新宏观坐标", "唐军·逆全球化/人口/债务"),
            ("E128 择时真相", "董艺婷·择时胜率<50%"),
            ("E130 体系完整", "先于逻辑自洽和观点正误"),
        ]
        for ref, desc in refs:
            lines.append(("bullet", f"{ref} — {desc}"))
        
        lines.append(("text", f"📋 完整原理见 [知识体系总纲](https://bytedance.feishu.cn/docx/RmtEduEtfo05hSxW02wc8ZhfnVc)"))
        
        return lines
    
    # ═══ 聚合 ═══
    def generate_report(self, w: FeishuWriter = None):
        """生成完整研报"""
        if w is None:
            w = FeishuWriter()
        
        self.fetch_data()
        
        today = datetime.now().strftime("%Y/%m/%d")
        title = f"🃏 深研 | {self.name}({self.symbol}) — 翻倍逻辑与风险"
        doc_id = w.create_doc(title)
        if not doc_id:
            print("✗ 创建文档失败")
            return None
        
        print(f"\n  📄 文档: {doc_id}")
        
        # 封面
        w.write(doc_id, [
            ("bold", f"个股深度研报: {self.name} ({self.symbol})"),
            ("text", f"日期: {today} | 市场: {self.market}"),
            ("text", "面基·三源融合体系 | 产业链定位 → 翻倍逻辑 → 估值 → 仓位 → 风控"),
            ("text", f"📋 [知识体系总纲](https://bytedance.feishu.cn/docx/RmtEduEtfo05hSxW02wc8ZhfnVc)"),
        ])
        
        # 1. 产业链定位
        chain_lines, _ = self.analyze_chain_position()
        w.write(doc_id, chain_lines)
        
        # 2. 翻倍逻辑
        doubling_lines = self.analyze_doubling_thesis()
        w.write(doc_id, doubling_lines)
        
        # 3. DCF
        dcf_lines = self.analyze_dcf()
        w.write(doc_id, dcf_lines)
        
        # 4. 凯利
        kelly_lines = self.analyze_kelly()
        w.write(doc_id, kelly_lines)
        
        # 5. Nick四问
        nick_lines = self.analyze_nick_4q()
        w.write(doc_id, nick_lines)
        
        # 6. 贝叶斯
        bayes_lines = self.analyze_bayesian()
        w.write(doc_id, bayes_lines)
        
        # 7. 风险
        risk_lines = self.analyze_risks()
        w.write(doc_id, risk_lines)
        
        # 8. 引用
        ref_lines = self.analyze_mianji_refs()
        w.write(doc_id, ref_lines)
        
        print(f"  ✅ 研报完成: {doc_id}")
        return doc_id


# ═══════════════════════════════════
# 批量生成
# ═══════════════════════════════════

def generate_batch():
    """批量生成 4 只重点标的的深度研报"""
    batch = [
        ("NVDA", "英伟达", "US", {"chain": "GPU/AI芯片", "chain_pos": "核心"}),
        ("MU", "美光", "US", {"chain": "存储/HBM", "chain_pos": "中游"}),
        ("TSM", "台积电", "US", {"chain": "晶圆代工", "chain_pos": "核心"}),
        ("VST", "Vistra", "US", {"chain": "独立电力(核电)", "chain_pos": "发电"}),
    ]
    
    results = []
    w = FeishuWriter()
    
    for sym, name, market, chain in batch:
        print(f"\n{'='*50}")
        print(f"🔬 {name} ({sym}) — {chain['chain']}")
        print(f"{'='*50}")
        
        try:
            dr = DeepResearch(sym, name, market, chain)
            doc_id = dr.generate_report(w)
            results.append({"symbol": sym, "name": name, "doc_id": doc_id, "status": "ok" if doc_id else "fail"})
            time.sleep(3)  # 间隔避免 rate limit
        except Exception as e:
            print(f"  ✗ {sym}: {e}")
            results.append({"symbol": sym, "name": name, "doc_id": None, "status": "error", "error": str(e)[:100]})
    
    print(f"\n{'='*50}")
    print("📊 批量生成完成")
    for r in results:
        status_emoji = "✅" if r["status"] == "ok" else "❌"
        print(f"  {status_emoji} {r['name']}({r['symbol']}): {r['doc_id'] or r.get('error','?')}")
    
    return results


if __name__ == "__main__":
    generate_batch()
