#!/usr/bin/env python3
"""
面基三源融合投资日报 v5.2 — 产业链分析深度版
v5.2 核心升级：
  1. 产业链全面重构：从6条→12条链，每条链含中观四层次×Perez五阶段×LDS翻倍逻辑
  2. 新增6条关键产业链：台积电先进制程链、存储/HBM链、AI应用/Agent链、机器人链、消费电子链、数据/云计算链
  3. LDS翻倍逻辑复盘：每条链嵌入历史翻倍案例和驱动因子分析
  4. 播客全框架注入：中观四层次(E7/E84)、Perez五阶段(E94/E98)、五层蛋糕(E155)、Nick四问(E81/E118)、复利凯利(E153)、效率公平(E75)
  5. 产业链分析板块：环节定位×标的竞争壁垒×翻倍逻辑×Nick四问×凯利仓位参考×催化剂×风险
  6. 新增 Layer 4-附：产业链分析原则块，写入日报正文
v5.1 原有：
  - LDS双门状态：宏观门×趋势门 → 9种操作方向
  - CPI情景推演 + 国运线 + ETF全景 + 房价趋势
v5 原有：
  - ETF全景覆盖：A股ETF(35只)+跨境ETF+FOF+LDS参考组合
  - 原理解读层：每决策标注 面基/LDS/Vibe-Trading思想来源
  - 策略配置基准：LDS全天候组合 + 桥水风险平价参考
  - 择时 vs 非择时分析
  - 附录：三源融合核心原则/公式/纪律
"""

import json, subprocess, os, time, sys, urllib.request
from datetime import datetime

sys.path.insert(0, "/home/admin/.hermes")
from investment_system import config as config_module
config = config_module
from investment_system.etf_data import (
    A_ETF, CROSS_BORDER_ETF, LDS_PORTFOLIO, FUND_TIMING
)

# ─── path ───
FEISHU_TOOL = config.FEISHU_TOOL
FOLDER_TOKEN = config.FEISHU_FOLDER_TOKEN
GROUP_CHAT = config.FEISHU_GROUP_CHAT
USER_OPENID = config.FEISHU_USER_OPENID

# ─── static data ───
HOUSING_DATA = {
    "一线城市": [("北京",62500,0.2),("上海",68500,0.3),("广州",42000,-0.1),("深圳",68000,-0.3)],
    "新一线": [("成都",19500,0.4),("杭州",35000,0.1),("南京",31000,-0.1),("苏州",25000,0.0),("武汉",17500,-0.2),("重庆",15000,-0.1)],
    "二线": [("西安",17000,0.3),("长沙",12500,0.0),("合肥",19000,0.2),("宁波",26000,0.1),("青岛",20000,-0.1)],
    "关注信号": "一线分化(京沪微涨/广深承压)，成都/西安新一线逆势走强，政策底已现但市场底需确认",
}

# 三源融合原则
SAN_YUAN_PRINCIPLES = {
    "宏观": {
        "title": "Layer 1: 宏观气候（三源融合）",
        "principles": [
            ("面基四象限", "宽/紧货币 × 宽/紧信用 → 经济扩张/复苏/过热/衰退。当前复苏期：宽货币·紧信用，利率低位利好消费金融。"),
            ("LDS趋势温度", "凉→平→温→热四阶温度计，基于20/60日均线偏离度。当前趋势『平』=轻仓试探，中性操作。"),
            ("LDS策略开关", "CPI<1%通缩→限制敞口/1-2%正常/2-3%高景气/>3%减仓防御。当前CPI不足→按默认执行。"),
            ("Vibe全球因子", "利率/通胀/就业/PMI多维度整合。美联储利率追踪、期限利差、信用利差实时监测。"),
        ]
    },
    "配置": {
        "title": "Layer 2: 资产配置（三源融合）",
        "principles": [
            ("面基SAA+TAA", "SAA基准：权益40-60%/债券30-45%/商品5-10%/现金5-15%。TAA基于宏观±10%偏移。"),
            ("LDS全天候ETF", "4类低相关资产对冲：红利低波25%+纳斯达克30%+黄金25%+豆粕20%。月度再平衡，定投不需择时。"),
            ("桥水风险平价", "风险敞口相等而非资金相等。债券波动小→多配，股票波动大→少配。All Weather: 30%股+55%债+15%商品。"),
            ("Vibe多资产回测", "CompositeEngine：跨市场混合组合回测（A股+港股+美股+黄金+商品+债券）。Walk-Forward验证。"),
        ]
    },
    "因子": {
        "title": "Layer 3: 多因子引擎（三源融合）",
        "principles": [
            ("面基6因子", "质量(ROE>15%)、价值(PE分位<30%)、成长(营收增速>20%)、低波(Beta<0.8)、红利(股息率>3%)、动量(6个月前30%)。"),
            ("LDS动态权重", "权重随宏观状态自适应：复苏期→质量+成长主导；扩张期→动量+成长；过热期→价值+红利+低波；衰退期→质量+低波+红利。"),
            ("Vibe Alpha Zoo", "452个预构建Alpha因子，IC/IR分层检验。Spearman Rank IC + 分组收益曲线验证因子有效性。"),
        ]
    },
    "选股": {
        "title": "Layer 4: 找票执行（三源融合）",
        "principles": [
            ("面基三层漏斗", "粗筛排除毒药(ST/现金流为负/高质押率) → 因子打分排序 → DCF估值安全边际>30%确认。"),
            ("LDS产业链定位", "不是买好公司，是买『利润率最高的环节』。龙头已涨→找二梯队（产业链扩散）。30-200亿市值+ROE>15%+增速>20%。"),
            ("Vibe全市场扫描", "因子研究小组多智能体扫描 + 452 Alpha全选股域IC检验。"),
        ]
    },
    "产业链": {
        "title": "Layer 4-附: 产业链分析（面基完整框架 v5.2）",
        "principles": [
            ("中观四层次(E7/E84)", "产业生命周期→需求景气度→短期业绩兑现度→估值性价比。二阶导>一阶导，环比增速>同比增速，增速斜率>增速本身。渗透率早期回报最肥美。"),
            ("Perez五阶段(E94/E98)", "导入→转折→展开→成熟→沉寂。AI是第六轮康波主导技术，当前处于导入→转折期。每轮胜出的不是技术最牛的，而是让技术大规模高效走入社会的企业。"),
            ("五层蛋糕(E155/黄仁勋)", "芯片→硬件→模型→应用→终端用户。Capex是护城河，合同负债是业绩前瞻。HALO特征（重资产、低淘汰）公司更安全。"),
            ("LDS产业扩散", "龙头已涨→找二梯队配套。GPU大热→挖英伟达供应链→挖数据中心供应链→挖液冷/电力。买不到整机就买『铲子』（核心零部件）。"),
            ("Nick灵魂四问(E81/E118)", "①紧急度 ②真实趋势 ③身边人共识 ④持有者拥挤度。低共识+强趋势=最佳入场时机。高共识+高热度=危险信号。"),
            ("复利增长×凯利(E153)", "G=Edge×Position×Frequency×Time。凯利f*=p-q/b→半凯利→2%风险常数。不同链的Edge不同，仓位应差异化。"),
            ("投资光谱右移(E32)", "增量时代看左侧（新技术/营收），存量时代看右侧（现金流/股息）。判断链处于光谱的哪个位置决定买什么。"),
            ("效率→公平周期(E75/丁昶)", "一代人级别的范式转换。公平周期=自主可控优先级↑。直接影响信创、半导体国产替代的估值中枢。"),
        ]
    },
    "风控": {
        "title": "Layer 5: 风控监控（三源融合）",
        "principles": [
            ("凯利公式", "f*=(bp-q)/b → 半凯利→min(凯利/2, 2%)。单笔最大亏损≤总资产2%，连错10次亏20%，需25%回本。"),
            ("8%硬止损", "每笔交易预设8%止损线，到了就执行。这是纪律铁律，不可商量。"),
            ("15%/30%分级止盈", "第一目标15%减半仓锁定利润→第二目标30%清仓。不贪最后一分钱。"),
            ("组合相关性", "两两相关性>0.6的资产不超过2个。确保组合分散效果。最大回撤>15%强制减仓50%。"),
            ("Monte Carlo + Walk-Forward", "随机路径压力测试 + 滚动窗口避免过拟合 + Drawdown分析。"),
        ]
    },
    "纪律": {
        "title": "Layer 6: 交易纪律（三源融合）",
        "principles": [
            ("四重确认入场", "宏观→趋势→因子→选股全部通过才买入。任意一重不通过→等待。"),
            ("月度再平衡", "每月检查配比，偏离>5%触发调仓。涨多了的减一点，保持配比。"),
            ("持仓6个月评估", "持仓超6个月未达预期→评估是否逻辑变了。逻辑没变就持有，逻辑变了就砍。"),
            ("Shadow Account复盘", "对比实际交易 vs 策略规则偏离。行为诊断（处置效应/过度交易/动量追逐）。"),
        ]
    }
}


def _get_feishu_token():
    """获取 Feishu API token，缓存5分钟"""
    global _token_cache
    now = time.time()
    if _token_cache and now - _token_cache["ts"] < 250:
        return _token_cache["token"]
    try:
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=data, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        token = resp.get("tenant_access_token", "")
        _token_cache = {"token": token, "ts": now}
        return token
    except Exception as e:
        print(f"  [auth] ❌ {e}")
        return ""

_token_cache = None

# ── Feishu API 块类型常量 ──
_FEISHU_BLOCK_TEXT = 2
_FEISHU_BLOCK_H1, _FEISHU_BLOCK_H2, _FEISHU_BLOCK_H3 = 3, 4, 5
_FEISHU_BLOCK_H4, _FEISHU_BLOCK_H5 = 6, 7
_FEISHU_BLOCK_UNORDERED = 12
_FEISHU_BLOCK_ORDERED = 13
_FEISHU_BLOCK_CODE = 14

def _simplified_to_api_block(b):
    """将简化格式块转换为 Feishu REST API 块格式"""
    bt = b.get("blockType", "text")
    opts = b.get("options", {})
    
    def _convert_styles(text_styles):
        """将 textStyles 转为 elements"""
        elements = []
        for ts in text_styles:
            text = ts.get("text", "")
            style = ts.get("style", {})
            elem_style = {}
            if style.get("bold"):
                elem_style["bold"] = True
            if style.get("italic"):
                elem_style["italic"] = True
            if style.get("strikethrough"):
                elem_style["strikethrough"] = True
            if style.get("inline_code"):
                elem_style["inline_code"] = True
            elements.append({
                "text_run": {
                    "content": text,
                    "text_element_style": elem_style
                }
            })
        return elements
    
    if bt == "heading":
        h_opts = opts.get("heading", {})
        level = h_opts.get("level", 3)
        content = h_opts.get("content", "")
        block_type_map = {1: 3, 2: 4, 3: 5, 4: 6, 5: 7}
        api_type = block_type_map.get(level, 5)
        field_name = {3: "heading1", 4: "heading2", 5: "heading3", 6: "heading4", 7: "heading5"}.get(api_type, "heading3")
        return {
            "block_type": api_type,
            field_name: {
                "elements": [{"text_run": {"content": content, "text_element_style": {}}}],
                "style": {}
            }
        }
    
    elif bt == "text":
        text_opts = opts.get("text", {})
        text_styles = text_opts.get("textStyles", [])
        elements = _convert_styles(text_styles)
        return {
            "block_type": 2,
            "text": {
                "elements": elements,
                "style": {}
            }
        }
    
    elif bt == "list":
        list_opts = opts.get("list", {})
        content = list_opts.get("content", "")
        is_ordered = list_opts.get("isOrdered", False)
        return {
            "block_type": _FEISHU_BLOCK_ORDERED if is_ordered else _FEISHU_BLOCK_UNORDERED,
            "ordered" if is_ordered else "bullet": {
                "elements": [{"text_run": {"content": content, "text_element_style": {}}}],
                "style": {}
            }
        }
    
    elif bt == "code":
        code_opts = opts.get("code", {})
        return {
            "block_type": _FEISHU_BLOCK_CODE,
            "code": {
                "elements": [{"text_run": {"content": code_opts.get("content", ""), "text_element_style": {}}}],
                "style": {"language": code_opts.get("language", 1), "wrap": code_opts.get("wrap", True)}
            }
        }
    
    # fallback: plain text
    return {
        "block_type": 2,
        "text": {
            "elements": [{"text_run": {"content": str(b), "text_element_style": {}}}],
            "style": {}
        }
    }


def _rest_api_write_blocks(doc_id, parent_id, blocks, start_index, max_retries=3):
    """通过 Feishu REST API 批量写入块。返回新的 next_index。"""
    if not blocks:
        return start_index
    
    token = _get_feishu_token()
    if not token:
        print(f"  [rest] ❌ 无法获取token")
        return start_index
    
    api_blocks = [_simplified_to_api_block(b) for b in blocks]
    
    for attempt in range(max_retries):
        try:
            data = json.dumps({"children": api_blocks, "index": start_index}).encode()
            req = urllib.request.Request(
                f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks/{parent_id}/children",
                data=data, method="POST",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            resp = urllib.request.urlopen(req, timeout=60)
            result = json.loads(resp.read())
            code = result.get("code", -1)
            if code == 0:
                children = result.get("data", {}).get("children", [])
                return start_index + len(children)
            elif code == 99991600 or code == 99991601:  # rate limit
                wait = 2 ** attempt
                print(f"  [rest] ⚠️ rate limited, retry {attempt+1}/{max_retries} in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [rest] ❌ API error code={code} msg={result.get('msg','?')[:100]}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                else:
                    # fallback: increment by batch size
                    return start_index + len(blocks)
        except Exception as e:
            print(f"  [rest] ❌ exception: {e}, attempt {attempt+1}")
            if attempt < max_retries - 1:
                time.sleep(2)
            else:
                return start_index + len(blocks)
    
    return start_index + len(blocks)


def create_doc(title):
    token = _get_feishu_token()
    if not token:
        print("  ❌ 无法获取token")
        return None
    try:
        data = json.dumps({"title": title, "folder_token": FOLDER_TOKEN}).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/docx/v1/documents",
            data=data, method="POST",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read())
        code = result.get("code", -1)
        if code == 0:
            doc = result.get("data", {}).get("document", {})
            doc_id = doc.get("document_id", "")
            print(f"  ✅ 文档创建: {doc_id}")
            return doc_id
        else:
            print(f"  ❌ 创建失败: code={code} msg={result.get('msg','?')[:100]}")
            return None
    except Exception as e:
        print(f"  ❌ create_doc error: {e}")
        return None


class DocWriter:
    def __init__(self, doc_id):
        self.doc_id = doc_id
        self.idx = 0

    def write_blocks(self, blocks):
        if not self.doc_id or not blocks:
            return self.idx
        MAX_BATCH = 30  # REST API can handle more
        idx = self.idx
        for i in range(0, len(blocks), MAX_BATCH):
            batch = blocks[i:i+MAX_BATCH]
            next_idx = _rest_api_write_blocks(self.doc_id, self.doc_id, batch, idx)
            idx = next_idx
            time.sleep(0.15)
        self.idx = idx
        return idx

    def write_table(self, headers, rows):
        if not self.doc_id:
            return
        col_size = len(headers)
        row_size = len(rows) + 1
        cells = []
        for c, h in enumerate(headers):
            cells.append({
                "coordinate": {"row": 0, "column": c},
                "content": {"blockType": "text", "options": {
                    "text": {"textStyles": [{"text": h, "style": {"bold": True, "text_color": 6}}]}}}
            })
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                cells.append({
                    "coordinate": {"row": r_idx + 1, "column": c_idx},
                    "content": {"blockType": "text", "options": {
                        "text": {"textStyles": [{"text": str(val)}]}}}
                })
        payload = json.dumps({
            "documentId": self.doc_id,
            "parentBlockId": self.doc_id,
            "index": self.idx,
            "tableConfig": {"columnSize": col_size, "rowSize": row_size, "cells": cells},
        }, ensure_ascii=False)
        try:
            r = subprocess.run([FEISHU_TOOL, "create_feishu_table", payload],
                capture_output=True, text=True,
                env={**os.environ, "FEISHU_SCOPE_VALIDATION": "false"}, timeout=30)
            if r.returncode == 0:
                result = json.loads(r.stdout)
                idx_delta = result.get("blockCount", 1)
                self.idx += idx_delta
            else:
                print(f"  [table] ⚠️ rc={r.returncode}")
                self.idx += 1
        except Exception as e:
            print(f"  [table] ❌ {e}")
            self.idx += 1
        time.sleep(0.3)
        return self.idx
    @staticmethod
    def h(level, content):
        return {"blockType": "heading", "options": {"heading": {"level": level, "content": content}}}

    @staticmethod
    def plain(text):
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": text}]}}}

    @staticmethod
    def styled_bullet(label, value, color=None):
        segs = [{"text": "· ", "style": {}}]
        lbl = {"text": label, "style": {"bold": True}}
        if color:
            lbl["style"]["text_color"] = color
        segs.append(lbl)
        segs.append({"text": value})
        return {"blockType": "text", "options": {"text": {"textStyles": segs}}}

    @staticmethod
    def multi(segments):
        styles = []
        for seg in segments:
            text, b = seg[0], len(seg) > 1 and seg[1]
            elem = {"text": text}
            if b:
                elem["style"] = {"bold": True}
            styles.append(elem)
        return {"blockType": "text", "options": {"text": {"textStyles": styles}}}

    @staticmethod
    def blank():
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": ""}]}}}

    @staticmethod
    def empty_line():
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": "."}]}}}

    def write_bullet(self, text):
        return self.write_blocks([{"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}])

    def write_multi(self, segments):
        """Write multi-style text segment"""
        return self.write_blocks([self.multi(segments)])


# ═══════════════════════════════════════════
# 表格数据构建
# ═══════════════════════════════════════════

def build_macro_table(macro_summary):
    md = macro_summary.get("macro_data", {})
    regime = macro_summary.get("regime", "N/A")
    quadrant = macro_summary.get("quadrant", "N/A")
    trend = macro_summary.get("trend_temp", "N/A")
    switch = macro_summary.get("strategy_switch", "off")
    position = macro_summary.get("suggested_position", 0.5)
    cpi = md.get("cpi", "N/A")
    pmi = md.get("pmi", "N/A")
    cpi_trend = md.get("cpi_trend", "")
    pmi_trend = md.get("pmi_trend", "")
    cpi_date = md.get("cpi_date", "")
    pmi_date = md.get("pmi_date", "")
    trend_arrow = {"up": "↑", "down": "↓", "flat": "→"}.get(cpi_trend, "")
    
    # CPI门槛标注
    if isinstance(cpi, (int, float)):
        if cpi < 1.0: cpi_label = f"⚠️ {cpi}%{trend_arrow} 通缩风险"
        elif cpi < 2.0: cpi_label = f"🟢 {cpi}%{trend_arrow} 正常"
        elif cpi < 3.0: cpi_label = f"🟡 {cpi}%{trend_arrow} 抬头"
        else: cpi_label = f"🔴 {cpi}%{trend_arrow} 高通胀"
    else:
        cpi_label = str(cpi)
    
    return ["指标","当前状态","原理说明"], [
        ["🏛 面基四象限", f"{quadrant} → {regime}", "宽货币·紧信用→复苏期，利率低位利好消费金融"],
        ["🌡 LDS趋势温度", trend, {"凉":"空仓等待","平":"轻仓试探","温":"正常仓位","热":"满仓运行"}.get(trend,"")],
        ["🔘 LDS策略开关", {"off":"关闭", "limited":"谨慎", "on":"开启"}.get(switch,switch), macro_summary.get("strategy_reason","")],
        ["💹 建议仓位", f"{int(position*100)}%", "凯利/2 ≤ 2%风险常数，连错10次亏20%"],
        ["📊 CPI", cpi_label, f"LDS首要关注：CPI决定加息预期，影响全部因子{' ｜ ' + str(cpi_date) if cpi_date else ''}"],
        ["📊 PMI", f"{pmi}{'↑' if pmi_trend=='up' else '↓' if pmi_trend=='down' else '→'}" if isinstance(pmi, (int,float)) else str(pmi), f"≧52扩张，<48收缩，{' ｜ ' + str(pmi_date) if pmi_date else ''}"],
    ]


def build_market_table(gdata):
    headers = ["资产类别","具体指标","最新值","变动","解读"]
    rows = []
    fx = gdata.get("fx", {})
    if "error" not in fx:
        for pair,k in [("USD/CNY","人民币强弱"),("EUR/CNY","欧元"),("HKD/CNY","联系汇率"),("100JPY/CNY","日元套息")]:
            val = fx.get(pair)
            if isinstance(val, dict) and val.get("price"):
                bp = val.get("change_bp", 0)
                rows.append([f"💰 汇率", pair, f"{val['price']}", f"{bp:+.0f}bp {'⬆️' if bp>0 else ('⬇️' if bp<0 else '➡️')}", k])
    bonds = gdata.get("bonds", {})
    us = bonds.get("US10Y", {})
    cn = bonds.get("CN10Y", {})
    if isinstance(us, dict):
        rows.append(["📊 债券","美国10Y",f"{us.get('price','—')}%",f"{us.get('change_pct',0):+.2f}%" if us.get('change_pct') else "—","全球利率锚"])
    if isinstance(cn, dict):
        rows.append(["📊 债券","中国10Y",f"{cn.get('price','—')}%","—","国内利率锚"])
    try:
        s = float(us.get("price",0)) - float(cn.get("price",0))
        if s:
            rows.append(["📊 利差","中美利差",f"{s:.2f}%",{"2":"🔴>2%",">2":"🔴"},"资金流向指标"])
    except:
        pass

    indices = gdata.get("indices", {})
    for sym, info in config.GLOBAL_INDICES.items():
        val = indices.get(sym, {})
        if isinstance(val, dict) and val.get("price"):
            chg = val.get("change_pct", 0)
            rows.append(["📈 指数", info["name"], f"{val['price']:,.2f}", f"{chg:+.2f}%", "🟢" if chg>0 else ("🔴" if chg<0 else "➡️")])

    hk = gdata.get("hk_stocks", {})
    for sym, info in sorted(hk.items(), key=lambda x: abs(x[1].get("change_pct",0)), reverse=True)[:5]:
        if isinstance(info, dict) and info.get("price"):
            rows.append(["🇭🇰 港股", info.get("name",sym), f"{info['price']}", f"{info.get('change_pct',0):+.2f}%", info.get("sector","")])

    us_s = gdata.get("us_stocks", {})
    for sym, info in sorted(us_s.items(), key=lambda x: abs(x[1].get("change_pct",0)), reverse=True)[:5]:
        if isinstance(info, dict) and info.get("price"):
            rows.append(["🇺🇸 美股", info.get("name",sym), f"{info['price']}", f"{info.get('change_pct',0):+.2f}%", info.get("sector","")])

    comm = gdata.get("commodities", {})
    for sym, info_data in config.COMMODITIES.items():
        val = comm.get(sym, {})
        if isinstance(val, dict) and val.get("price"):
            rows.append(["🪙 商品", info_data["name"], f"{val['price']} {info_data.get('unit','')}", f"{val.get('change_pct',0):+.2f}%", info_data["sector"]])
    # 金油比
    gold = comm.get("GC=F", {})
    oil = comm.get("CL=F", {})
    if isinstance(gold, dict) and isinstance(oil, dict):
        try:
            gp, op = float(gold.get("price",0)), float(oil.get("price",0))
            if gp>0 and op>0:
                ratio = gp/op
                note = f"金油比{ratio:.1f}——{'⚠️ 历史高位，地缘风险+经济担忧' if ratio>40 else ('🟡 中性偏高，风险偏好偏弱' if ratio>25 else '🟢 正常范围')}"
                rows.append(["🔑 金油比", f"{ratio:.1f}", "—", "—", note])
        except:
            pass

    # ETF
    for code, name, etype in A_ETF[:12]:
        rows.append([f"📦 {etype}ETF", name, code, "—", ""])

    return headers, rows


def build_lds_portfolio_table():
    """LDS参考组合解释"""
    headers = ["比例","基金/代码","类型","LDS选基逻辑"]
    rows = []
    for item in LDS_PORTFOLIO["items"]:
        rows.append([f"{item['pct']}%", f"{item['fund']}({item['code']})", item["type"], item["logic"]])
    return headers, rows, LDS_PORTFOLIO["principle"], LDS_PORTFOLIO["rebalance"]


def build_etf_overview_table():
    """全品类ETF全景"""
    headers = ["ETF类型","代表标的","代码","特征/择时建议"]
    rows = []
    # 宽基
    for code, name, etype in A_ETF:
        if etype == "宽基":
            rows.append(["📍 宽基", name, code, "定投不需择时，核心底仓"])
    # 策略
    for code, name, etype in A_ETF:
        if etype == "策略":
            rows.append(["🎯 策略ETF", name, code, "因子暴露，定投不需择时"])
    # 行业
    for code, name, etype in A_ETF:
        if etype == "行业":
            rows.append(["🥩 行业ETF", name, code, "需择时，宏观轮动指示"])
    # 商品
    for code, name, etype in A_ETF:
        if etype == "商品":
            rows.append(["🪙 商品ETF", name, code, "对冲通胀，可定投"])
    # 债券
    for code, name, etype in A_ETF:
        if etype == "债券":
            rows.append(["📊 债券ETF", name, code, f"利率下行期强势"])
    # 跨境
    for code, name, etype in A_ETF:
        if etype == "跨境":
            rows.append(["🌍 跨境ETF", name, code, "QDII额度有限，场内折溢价注意"])
    # FOF
    for code, name, etype in A_ETF:
        if etype == "FOF":
            rows.append(["🧩 FOF-LOF", name, code, "一篮子配置，适合定投"])
    # 跨境(Yahoo)
    for sym, info in CROSS_BORDER_ETF.items():
        rows.append(["🌍 境外ETF", f"{info['name']}({sym})", info["market"], info["type"]])
    return headers, rows


def build_housing_table():
    headers = ["城市等级","城市","均价(元/㎡)","月环比"]
    rows = []
    for tier, cities in HOUSING_DATA.items():
        if tier == "关注信号": continue
        for city, price, mom in cities:
            a = "🟢" if mom>0 else ("🔴" if mom<0 else "➡️")
            rows.append([tier, city, f"{price:,}", f"{a} {mom:+.1f}%"])
    return headers, rows, HOUSING_DATA["关注信号"]


def build_scan_table(scan_results, macro_summary):
    regime = macro_summary.get("regime", "default")
    rotation = config.MACRO_SECTOR_ROTATION.get(regime, config.MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])
    lds_note = rotation.get("lds_note", "")
    chain_data = config.INDUSTRY_CHAINS

    pick_rows = []
    for r in scan_results[:15]:
        sym = r.get("symbol", "")
        name = r.get("name", "")
        score = r.get("score", 0)
        sector = r.get("sector", "")
        price = r.get("price", 0)
        chg = r.get("change_pct", 0)

        if score >= 6: signal = "买入 ⬆️"
        elif score >= 5: signal = "关注 👀"
        elif score >= 4: signal = "观望 ⏳"
        else: signal = "回避 ❌"

        matched_chain = ""
        for cn, ci in chain_data.items():
            if sym in ci.get("symbols", []):
                matched_chain = cn
                break

        matched_sector = ""
        for fav in favored:
            if fav in sector or fav in name or (matched_chain and fav in matched_chain):
                matched_sector = fav
                break
        is_favored = "🔵" if matched_sector else "⚪"
        pick_rows.append([sym, name, f"{score:.1f}", signal, is_favored, matched_chain or "—", f"{price:.2f}" if price else "—", f"{chg:+.1f}%" if chg else "—"])

    headers = ["代码","名称","评分","信号","轮动","产业链","价格","涨跌"]
    return headers, pick_rows, favored, lds_note


def build_cross_picks(scan_results, gdata, macro_summary):
    picks = []
    for r in scan_results[:5]:
        chg_s = f"{r.get('change_pct',0):+.1f}%" if r.get('change_pct') else "—"
        score = r.get('score', 0)
        sig = "买入" if score >= 6 else ("关注" if score >= 5 else ("观望" if score >= 4 else "回避"))
        picks.append(["📈 A股", r.get("symbol",""), r.get("name",""), f"评分{score:.1f}", chg_s, sig])

    hk = gdata.get("hk_stocks", {})
    for sym, info in sorted(hk.items(), key=lambda x: abs(x[1].get("change_pct",0)), reverse=True)[:3]:
        if isinstance(info, dict) and info.get("price"):
            picks.append(["🇭🇰 港股", sym.split('.')[0], info.get("name",""), info.get("sector",""), f"{info.get('change_pct',0):+.2f}%", f"${info['price']}"])

    us = gdata.get("us_stocks", {})
    for sym, info in sorted(us.items(), key=lambda x: abs(x[1].get("change_pct",0)), reverse=True)[:3]:
        if isinstance(info, dict) and info.get("price"):
            picks.append(["🇺🇸 美股", sym, info.get("name",""), info.get("sector",""), f"{info.get('change_pct',0):+.2f}%", f"${info['price']}"])

    return ["市场","代码","名称","板块","变动","说明"], picks


def build_positions_table(shadow):
    headers = ["名称","代码","建仓价","现价","涨幅","止损","状态"]
    rows = []
    for pos in shadow.get("positions", []):
        chg = pos.get("change", 0)
        rows.append([pos.get("name",""), pos.get("symbol",""),
                     f"{pos.get('entry',0):.2f}", f"{pos.get('current',0):.2f}",
                     f"{chg:+.1f}%", f"{pos.get('stop_loss',0):.2f}", "🟢" if chg>=0 else "🔴"])
    return headers, rows


# ═══════════════════════════════════════════
# v5.1 新增：LDS双门 + 国运线 + CPI情景
# ═══════════════════════════════════════════

def build_dual_gate_section(macro_summary):
    """LDS双门状态 — 宏观门×趋势门 → 操作方向"""
    md = macro_summary.get("macro_data", {})
    dual = macro_summary.get("dual_gate", {})
    cpi = md.get("cpi", "N/A")
    pmi = md.get("pmi", "N/A")
    cpi_trend = md.get("cpi_trend", "?")
    pmi_trend = md.get("pmi_trend", "?")
    
    gate_icon = {"绿灯": "🟢", "黄灯": "🟡", "红灯": "🔴"}
    trend_icon = {"热": "🔥", "温": "☀️", "平": "🌤️", "凉": "❄️"}
    
    mg = dual.get("macro_gate", "?")
    tg = dual.get("trend_gate", "?")
    tp = dual.get("trend_phase", "?")
    
    headers = ["门", "状态", "数据支撑", "含义"]
    rows = [
        ["🚪 宏观门", f"{gate_icon.get(mg,'?')} {mg}", 
         f"CPI={cpi}%({'↑' if cpi_trend=='up' else '↓' if cpi_trend=='down' else '→'}) ｜ PMI={pmi}({'↑' if pmi_trend=='up' else '↓' if pmi_trend=='down' else '→'})",
         dual.get("macro_detail", "")],
        ["📈 趋势门", f"{gate_icon.get(tg,'?')} {tg}",
         f"趋势温度={tp}({trend_icon.get(tp,'?')})",
         f"凉→平→温→热周期：当前{tp}位"],
        ["🎯 双门判定", f"**{dual.get('action', '?')}**",
         f"组合={dual.get('combo', '?')}",
         dual.get("detail", "")],
    ]
    return headers, rows


def build_guoyun_section(macro_summary):
    """国运线 — 上证20年均线偏离"""
    guoyun = macro_summary.get("guoyun", {})
    gp = guoyun.get("price")
    dev = guoyun.get("deviation")
    note = guoyun.get("note", "")
    
    if not gp:
        return None
    
    headers = ["指标", "数值", "解读"]
    rows = [
        ["📐 20年国运线", f"{gp:,.0f} 点", "上证从未有效跌破此线，底部铁锚"],
        ["📍 当前点位偏离", f"{dev:+.1f}%" if dev else "—", note],
        ["💡 LDS原话", "「3000点以上属偏高区域」", "疫情后利率从5%→1%+，底部思维变化"],
        ["🏛 利率环境", f"Shibor隔夜≈{macro_summary.get('macro_data',{}).get('shibor','1.75')}%", "低利率环境支持更高估值中枢"],
    ]
    return headers, rows


def write_cpi_scenarios(w, macro_summary):
    """CPI三种情景推演（LDS核心关注点）"""
    md = macro_summary.get("macro_data", {})
    cpi = md.get("cpi", "N/A")
    cpi_trend = md.get("cpi_trend", "flat")
    
    w.write_blocks([w.h(4, "🔮 CPI三情景推演 — LDS：「下个月CPI不继续上涨 即可重新入场」")])
    
    # 根据CPI趋势构建情景
    if isinstance(cpi, (int, float)):
        base_up = cpi + 0.2
        base_down = cpi - 0.1
        tail = cpi + 1.5
    else:
        base_up = "?"
        base_down = "?"
        tail = "?"
    
    scenarios = [
        ("🟢 基准（概率60%）", f"CPI温和在{cpi}~{base_up}%区间，降息预期稳定。LDS：趋势回暖后右侧入场，聚焦金融+地产基建+汽车。"),
        ("🟡 上行（概率25%）", f"CPI突破{base_up}%向2%靠拢。「CPI直接影响加息」→LDS宏观权重提升，红利低波+黄金+豆粕增配。"),
        ("🔴 尾部（概率15%）", f"CPI跳升至{tail}%+，通胀杀估值。LDS：「宏观趋势双空→关仓」。全天候策略失效→全仓防御。"),
    ]
    
    for icon, text in scenarios:
        w.write_blocks([w.styled_bullet(icon, f"：{text}")])


def write_chain_picks(w, scan_results, macro_summary):
    """产业链选票 v5.2 — 中观四层次 × Perez五阶段 × LDS翻倍逻辑 × Nick四问 × 凯利参考"""
    from investment_system import config as cfg
    regime = macro_summary.get("regime", "default")
    rotation = cfg.MACRO_SECTOR_ROTATION.get(regime, cfg.MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])
    chain_data = cfg.INDUSTRY_CHAINS
    
    w.write_blocks([w.h(3, "🔗 七-附、产业链选票 v5.2 — 环节定位 × 翻倍逻辑 × 面基全框架")])
    w.write_blocks([w.plain("面基三层漏斗(E7/E84)：产业生命周期→需求景气→业绩兑现→估值性价比 + LDS产业链定位：『买利润率最高的环节』")])
    w.write_blocks([w.plain(f"当前宏观偏好：{', '.join(favored)} ｜ 回避：{', '.join(rotation.get('unfavored', []))}")])
    w.write_blocks([w.blank()])
    
    # 扫描结果按产业链分组
    chain_stocks = {}
    for r in scan_results[:25]:
        sym = r.get("symbol", "")
        for cn, ci in chain_data.items():
            if sym in ci.get("symbols", []):
                if cn not in chain_stocks:
                    chain_stocks[cn] = []
                chain_stocks[cn].append(r)
                break
    
    for cn, ci in chain_data.items():
        stocks_in_chain = chain_stocks.get(cn, [])
        if not stocks_in_chain:
            continue
        
        hm = ci.get("high_margin_keywords", [])
        hm_str = "、".join(hm[:3])
        desc = ci.get("description", "")
        perez = ci.get("perez_stage", "")
        meso = ci.get("meso_layer", {})
        lds = ci.get("lds_logic", "")
        nick = ci.get("nick_questions", "")
        edge = ci.get("edge", "")
        catalyst = ci.get("catalyst", "")
        risk = ci.get("risk_factors", "")
        
        # ── 链标题 + 描述 ──
        w.write_blocks([w.h(4, f"🏭 {cn} — 高利润环节: {hm_str}")])
        w.write_blocks([w.plain(f"📌 {desc}")])
        w.write_blocks([w.blank()])
        
        # ── 中观四层次 ──
        if meso:
            w.write_blocks([w.styled_bullet("📊 中观四层次(E7/E84)", 
                f"：生命周期={meso.get('lifecycle','?')} | 需求={meso.get('demand_boom','?')} | 业绩={meso.get('earnings_delivery','?')} | 估值={meso.get('valuation','?')}")])
        if perez:
            w.write_blocks([w.styled_bullet("🧭 Perez阶段(E94/E98)", f"：{perez}")])
        w.write_blocks([w.blank()])
        
        # ── LDS翻倍逻辑 ──
        if lds:
            w.write_blocks([w.styled_bullet("💰 LDS翻倍逻辑", f"：{lds}", 3)])  # green
        w.write_blocks([w.blank()])
        
        # ── Nick四问 + 凯利参考 ──
        if nick:
            w.write_blocks([w.styled_bullet("🔍 Nick四问(E81/E118)", f"：{nick}")])
        if edge:
            w.write_blocks([w.styled_bullet("🎲 复利Edge(E153)", f"：{edge}")])
        if catalyst:
            w.write_blocks([w.styled_bullet("⚡ 催化剂", f"：{catalyst}")])
        if risk:
            w.write_blocks([w.styled_bullet("⚠️ 风险", f"：{risk}")])
        w.write_blocks([w.blank()])
        
        # ── 链上标的（按环节分组）───
        # 获取上游/中游/下游环节定义
        positions = ci.get("chain_position", {})
        stock_by_pos = {"上游": [], "中游": [], "下游": [], "其他": []}
        
        for stock in sorted(stocks_in_chain, key=lambda x: x.get("score", 0), reverse=True)[:6]:
            name = stock.get("name", "")
            sym = stock.get("symbol", "")
            sector = stock.get("sector", "")
            # 尝试匹配环节
            matched_pos = "其他"
            for pos, sectors in positions.items():
                if any(s in sector or s in name for s in sectors):
                    matched_pos = pos
                    break
            stock_by_pos[matched_pos].append(stock)
        
        for pos in ["上游", "中游", "下游", "其他"]:
            pos_stocks = stock_by_pos.get(pos, [])
            if not pos_stocks:
                continue
            pos_label = {"上游": "上游·材料/器件", "中游": "中游·核心制造", "下游": "下游·集成/应用", "其他": "其他环节"}.get(pos, pos)
            w.write_blocks([w.styled_bullet(f"【{pos_label}】", "")])
            for stock in pos_stocks:
                name = stock.get("name", "")
                sym = stock.get("symbol", "")
                score = stock.get("score", 0)
                price = stock.get("price", 0)
                chg = stock.get("change_pct", 0)
                sig = "✅" if score >= 6 else ("👀" if score >= 5 else ("⏳" if score >= 4 else "❌"))
                w.write_blocks([w.styled_bullet(
                    f"  {sig} {name}({sym})",
                    f"：评分{score:.1f} ｜ ¥{price:.2f} ｜ {chg:+.1f}% ｜ {stock.get('sector', '')}"
                )])
        
        w.write_blocks([w.blank()])


# ═══════════════════════════════════════════
# 原则解读块
# ═══════════════════════════════════════════

def write_principles_block(w, layer_key, macro_summary):
    """写一个原则层的解读"""
    layer = SAN_YUAN_PRINCIPLES.get(layer_key)
    if not layer:
        return
    w.write_blocks([w.h(3, layer["title"])])
    for name, text in layer["principles"]:
        w.write_blocks([w.styled_bullet(f"{name}", f"：{text}")])


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def generate_report(macro, scan_results, gdata, shadow, news_data=None):
    macro_summary = macro if isinstance(macro, dict) else getattr(macro, "last_summary", {})
    regime = macro_summary.get("regime", macro_summary.get("regime_name", "N/A"))
    switch = macro_summary.get("strategy_switch", "off")
    position = macro_summary.get("suggested_position", 0.5)
    trend = macro_summary.get("trend_temp", "N/A")

    date_str = datetime.now().strftime("%Y-%m-%d")
    title = f"📊 面基三源融合投资日报 v5.3 | {date_str}"
    print(f"  📝 创建文档: {title}")
    doc_id = create_doc(title)
    if not doc_id:
        return None
    w = DocWriter(doc_id)
    time.sleep(1)

    switch_label = {"off":"不开新仓","limited":"谨慎操作","on":"正常执行"}.get(switch,"正常")
    w.write_blocks([w.plain(f"当前{regime}  趋势{trend}  建议仓位{int(position*100)}%  策略{switch_label}")])
    w.write_blocks([w.blank()])

    # ═══════════ PART 1: 宏观总览 ═══════════
    w.write_blocks([w.h(3, "📊 一、宏观核心指标")])
    w.write_blocks([w.plain(f"• 原理来源：{SAN_YUAN_PRINCIPLES['宏观']['principles'][0][0]} + {SAN_YUAN_PRINCIPLES['宏观']['principles'][1][0]}")])
    h1, r1 = build_macro_table(macro_summary)
    w.write_table(h1, r1)
    write_principles_block(w, "宏观", macro_summary)

    # ═══════════ PART 1.5: LDS双门状态 ═══════════
    w.write_blocks([w.h(3, "🚦 一-附、LDS双门状态 — 宏观 × 趋势 = 开仓方向")])
    w.write_blocks([w.plain("LDS决策核心：「宏观和趋势都负面的时候右侧没法开仓，要玩就只能左侧低吸基本面好的票」")])
    dual_headers, dual_rows = build_dual_gate_section(macro_summary)
    w.write_table(dual_headers, dual_rows)
    w.write_blocks([w.blank()])
    
    # CPI情景推演
    write_cpi_scenarios(w, macro_summary)
    w.write_blocks([w.blank()])

    # ═══════════ PART 2: LDS参考组合 ═══════════
    w.write_blocks([w.h(3, "🎯 二、策略配置基准 — LDS全天候组合")])
    w.write_blocks([w.plain(f"核心理念：{LDS_PORTFOLIO['principle']}")])
    h2, r2, p2, rb2 = build_lds_portfolio_table()
    w.write_table(h2, r2)
    w.write_blocks([w.styled_bullet("再平衡规则", f"：{rb2}")])
    # 桥水对比
    w.write_blocks([w.styled_bullet("桥水风险平价参考", f"：{FUND_TIMING['桥水全天候思路']}")])
    # 择时 vs 不择时
    w.write_blocks([w.h(4, "📌 基金的择时 vs 非择时分类")])
    for cat, desc in FUND_TIMING.items():
        if "桥水" not in cat:
            w.write_blocks([w.styled_bullet(cat, f"：{desc}")])
    write_principles_block(w, "配置", macro_summary)

    # ═══════════ PART 3: 全品类观测 ═══════════
    w.write_blocks([w.h(3, "🌐 三、全品类市场观测")])
    h3, r3 = build_market_table(gdata)
    w.write_table(h3, r3)

    # ═══════════ PART 4: ETF全景 ═══════════
    w.write_blocks([w.h(3, "📦 四、ETF全景扫描 — 全品类覆盖")])
    etf_principle = "LDS全天候组合+桥水风险平价思想：4类低相关资产联合配置，月度再平衡。以下为A股+境外可投ETF全景表："
    w.write_blocks([w.plain(etf_principle)])
    h4, r4 = build_etf_overview_table()
    w.write_table(h4, r4)

    # ETF策略逻辑
    w.write_blocks([w.h(4, "📌 当前宏观→ETF配置建议")])
    if regime == "复苏期":
        w.write_bullet("复苏期：宽货币初见效果，利率低位→利好红利低波+消费+金融类ETF")
        w.write_bullet("LDS推荐：华泰柏瑞红利低波(008279) + 沪深300ETF + 黄金ETF")
    elif regime == "扩张期":
        w.write_bullet("扩张期：信用扩张+PMI>52→成长股主导，科技/半导体/新能源ETF")
        w.write_bullet("LDS推荐：纳指ETF(513100) + 科创50ETF + 创业板ETF")
    elif regime == "过热期":
        w.write_bullet("过热期：CPI>3%/PMI>55→通胀交易，大宗商品+上游")
        w.write_bullet("LDS推荐：黄金ETF + 豆粕ETF + 能源相关")
    else:
        w.write_bullet("衰退期：防御为主，债券+红利+医药")
        w.write_bullet("LDS推荐：政金债券ETF + 红利低波ETF + 纳指ETF")

    # ═══════════ PART 5: 房价 ═══════════
    w.write_blocks([w.h(3, "🏠 五、房地产 — 房价趋势")])
    w.write_blocks([w.plain("数据来源：国家统计局70城 + 中指研究院 ｜ 月度均价变动")])
    h5, r5, n5 = build_housing_table()
    w.write_table(h5, r5)
    w.write_blocks([w.styled_bullet("信号", f"：{n5}")])

    # ═══════════ PART 5.5: 国运线 ═══════════
    guoyun_result = build_guoyun_section(macro_summary)
    if guoyun_result:
        w.write_blocks([w.h(3, "📐 五-附、国运线 — 上证20年均线")])
        w.write_blocks([w.plain("LDS：「上证20年均线≈2500-2600，从未有效跌破；3000点以上属偏高区域。疫情后利率从5%→1%+，底部思维要变化」")])
        gh, gr = guoyun_result
        w.write_table(gh, gr)
        w.write_blocks([w.blank()])

    # ═══════════ 新闻板块（v5.4新增） ═══════════
    if news_data and news_data.get("categories"):
        w.write_blocks([w.h(3, "📰 五-附·二、今日政经新闻 — 总分结构 + 产业链关联")])
        # 总述
        summary = news_data.get("summary", "")
        if summary:
            w.write_blocks([w.plain(f"**📋 总述：**{summary}")])
        w.write_blocks([w.blank()])
        
        # 按分类展现
        cats = news_data.get("categories", {})
        cat_order = ["宏观政策", "市场动态", "产业消息", "大宗商品", "产业趋势", "综合"]
        for cat in cat_order:
            items = cats.get(cat, [])
            if not items:
                continue
            emoji = {"宏观政策": "🏛️", "市场动态": "📈", "产业消息": "🔗", "大宗商品": "🛢️", "产业趋势": "🚀"}.get(cat, "📌")
            w.write_blocks([w.h(4, f"{emoji} {cat}（{len(items)}条）")])
            for item in items[:5]:  # 每类最多5条
                title = item.get("title", "")[:120]
                link = item.get("link", "")
                source = item.get("source_name", "")
                chain = item.get("chain", "")
                line = title
                if chain:
                    line += f"  🔗{chain}"
                if link:
                    line += f"  [原文]({link})"
                w.write_blocks([w.styled_bullet("", line)])
            w.write_blocks([w.blank()])

    # ═══════════ PART 6: LDS产业链 ═══════════
    w.write_blocks([w.h(3, "🔗 六、LDS产业链推荐 — 中观四层次 × Perez阶段 × 为什么选这些")])
    rotation = config.MACRO_SECTOR_ROTATION.get(regime, config.MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])
    unfavored = rotation.get("unfavored", [])
    w.write_blocks([w.styled_bullet("当前轮动", f"：偏好 {', '.join(favored)}  |  回避 {', '.join(unfavored)}")])
    w.write_blocks([w.styled_bullet("LDS逻辑", f"：{rotation.get('lds_note','')}")])
    w.write_blocks([w.styled_bullet("面基框架", "：中观四层次(E7/E84) × Perez五阶段(E94/E98) × 五层蛋糕(E155) × Nick四问(E81)")])
    w.write_blocks([w.blank()])
    
    chain_data = config.INDUSTRY_CHAINS
    for cn, ci in chain_data.items():
        hm = ci.get("high_margin_keywords", [])
        hm_str = "、".join(hm[:2])
        perez = ci.get("perez_stage", "")
        meso = ci.get("meso_layer", {})
        lifecycle = meso.get("lifecycle", "?") if meso else "?"
        
        # 每条链一行：链名 + 生命周期 + 核心高利润环节
        w.write_blocks([w.styled_bullet(
            f"🏭 {cn}", f"：{lifecycle} | {perez[:20] + '...' if len(perez) > 20 else perez} | 核心利润环节→{hm_str}"
        )])
    w.write_blocks([w.blank()])
    write_principles_block(w, "选股", macro_summary)
    write_principles_block(w, "产业链", macro_summary)

    # ═══════════ PART 7: 扫描 + 跨品种 ═══════════
    w.write_blocks([w.h(3, "🔍 七、扫描推荐 — 因子评分 + LDS确认")])
    h7, r7, fav7, note7 = build_scan_table(scan_results, macro_summary)
    w.write_blocks([w.plain(f"🔵 = 宏观轮动偏好板块标的 ｜ 扫描逻辑: {note7}")])
    w.write_table(h7, r7)
    w.write_blocks([w.blank()])

    w.write_blocks([w.h(3, "👀 八、跨品种关注 — 港股/美股/ETF")])
    h8, r8 = build_cross_picks(scan_results, gdata, macro_summary)
    w.write_table(h8, r8)

    # ═══════════ 产业链选票 — 环节定位 ═══════════
    write_chain_picks(w, scan_results, macro_summary)

    # ═══════════ PART 8: Shadow Account ═══════════
    w.write_blocks([w.h(3, "📁 九、Shadow Account — 持仓监控")])
    h9, r9 = build_positions_table(shadow)
    if r9:
        w.write_table(h9, r9)
    else:
        w.write_blocks([w.plain("当前无持仓，等待建仓信号")])

    # 止损预警
    try:
        from investment_system.shadow_account import check_stops
        alerts = check_stops()
        if alerts:
            w.write_blocks([w.h(4, "⚠️ 止盈止损预警")])
            for a in alerts:
                atype = a.get("type","")
                if atype == "STOP_LOSS":
                    w.write_blocks([w.styled_bullet(a.get("name",""), f" 触发8%止损！亏损{a.get('loss',0):.1f}%")])
                elif "TAKE_PROFIT" in atype:
                    p = a.get('profit',0)
                    a2 = "减半仓" if "T1" in atype else "清仓"
                    w.write_blocks([w.styled_bullet(a.get("name",""), f" 触发止盈 +{p:.1f}% → {a2}")])
    except Exception as e:
        print(f"  [stops] {e}")

    # ═══════════ PART 9: 纪律 ═══════════
    w.write_blocks([w.h(3, "🛡️ 十、纪律检查表 — 知行合一")])
    items = [
        ("策略开关", {"off":"关闭 ❌ 不开新仓","limited":"谨慎 ⚠️ 控仓位","on":"开启 ✅"}.get(switch,switch)),
        ("趋势温度", trend),
        ("持仓数量", f"{len(shadow.get('positions',[]))}/8只"),
        ("8%硬止损", "纪律铁律——每只票达到即出，不可商量"),
        ("单票≤总资产2%", "凯利/2 ≤ 2%，连错10次亏20%"),
        ("月度再平衡", "偏离>5%触发调仓"),
    ]
    for label, val in items:
        w.write_blocks([w.styled_bullet(label, f"：{val}")])
    write_principles_block(w, "风控", macro_summary)
    write_principles_block(w, "纪律", macro_summary)

    # ═══════════ PART 10: 操作 ═══════════
    w.write_blocks([w.h(3, "💡 十一、今日操作 — 知行合一")])
    if switch == "off":
        w.write_bullet("🔴 不开新仓，持仓逐步出清。宏观偏空，尊重概率。")
    elif switch == "limited":
        w.write_bullet(f"🟡 总仓位≤{int(position*100)}%，只做存量管理，不开新仓。")
    else:
        w.write_bullet("🟢 正常执行策略，依信号操作。四重确认通过再入场。")
    if scan_results and scan_results[0].get("score",0) >= 5:
        top = scan_results[0]
        w.write_bullet(f"🎯 关注：{top.get('name','')}({top.get('symbol','')}) 评分{top.get('score',0)} — {top.get('sector','')}")
    w.write_bullet("💰 ETF定投：参考LDS全天候组合，月度定投不需择时")

    # ═══════════ 每日面基概念 ═══════════
    # 从30条轮换概念中取当天的
    from investment_system.morning_brief import CONCEPTS, DAILY_MANTRA
    today_idx = datetime.now().timetuple().tm_yday % len(CONCEPTS)
    concept_name, concept_insight = CONCEPTS[today_idx]
    w.write_blocks([w.h(3, "🧠 今日面基概念 — 每日重温一条播客思想")])
    w.write_blocks([w.plain(f"**来源：{concept_name}**")])
    w.write_blocks([w.plain(f"> {concept_insight}")])
    w.write_blocks([w.blank()])

    # ═══════════ PART 11: 附录 ═══════════
    w.write_blocks([w.h(3, "📖 附录A：核心公式与计算")])
    formulas = [
        ("凯利公式", "f*=(bp-q)/b  b=赔率, p=胜率, q=1-p。半凯利→min(凯利/2, 2%)"),
        ("2%风险常数", "单笔最大亏损≤总资产2%。连错10次亏20%，需25%回本"),
        ("LDS趋势温度", "凉(偏离<-10%)→平(-5%~5%)→温(5%~15%)→热(>15%)"),
        ("四象限门槛", "宽货币=Shibor<1.8%, 宽信用=M2>8%, CPI>2.5%过热, PMI<48收缩"),
        ("因子权重", "复苏期:质量0.23+价值0.18+成长0.20+低波0.12+红利0.15+动量0.12"),
        ("风险平价", "σ₁×w₁=σ₂×w₂=...=σₙ×wₙ。对组合风险贡献相等"),
    ]
    for label, val in formulas:
        w.write_blocks([w.styled_bullet(label, f"：{val}")])

    w.write_blocks([w.h(3, "📖 附录B：六层递进架构")])
    layers = [
        ("Layer 1: 宏观气候", "面基四象限+LDS趋势温度+Vibe全球因子 — 宏观定开关"),
        ("Layer 2: 资产配置", "面基SAA+TAA+LDS全天候ETF+Vibe多资产回测 — 配置定仓位"),
        ("Layer 3: 多因子引擎", "面基6因子+LDS动态权重+Vibe Alpha Zoo — 因子定配比"),
        ("Layer 4: 找票执行", "面基三层漏斗+LDS产业链定位+Vibe全市场扫描 — 产业链定标的"),
        ("Layer 5: 风控监控", "凯利公式+8%止损+Monte Carlo+Shadow Account — 风控定仓位"),
        ("Layer 6: 交易纪律", "四重确认+月度再平衡+6个月评估+复盘机制 — 纪律定生死"),
    ]
    for label, val in layers:
        w.write_blocks([w.styled_bullet(f"📌 {label}", f"：{val}")])

    w.write_blocks([w.h(3, "📖 附录C：学习交易原则语录")])
    quotes = [
        "短期相信市场，中期相信共识，长期相信规律 — 南添(面基)",
        "宏观+趋势双空→关仓。不硬扛，尊重趋势。 — LDS",
        "不是买好公司，是买『利润率最高的环节』 — LDS",
        "对冲策略牛市跑不赢指数但不会输太多，熊市也能盈利 — LDS全天候",
        "系统占绝大多数+最后一层主观判断 — LDS因子方法论",
        "胜率和赔率不能同时优化，凯利公式帮你找到最优解 — 面基E153",
        "结论是反人性的，但要尊重基于统计学概率学的结果 — 面基理念",
        "先想好怎么死，再谈怎么活 — 三源共识",
    ]
    for q in quotes:
        w.write_blocks([w.multi([("📌 " + q.split("—")[0].strip(), False), (" —", True), (q.split("—")[-1] if "—" in q else "", False)])])

    # ═══════════ 附录D：面基播客全部概念体系 ═══════════
    w.write_blocks([w.h(3, "📖 附录D：面基154期 · 全部概念体系")])
    w.write_blocks([w.plain("> 按投资架构分层整理，来源标注期数。每日重读以加深理解。\n")])

    full_concepts = [
        ("——— Layer 1: 第一性原理与估值 ———", [
            ("DCF模型(E124 恽雷)", "公司内在价值=ΣCFt/(1+r)^t+TV/(1+r)^n。DCF是估值思想而非精确计算器。永续阶段占内在价值近50%，业绩空间天花板>增速本身。"),
            ("FCF两朵花(E68 恽雷)", "FCF增长(经济上行)→质量成长(外资定价)。FCF释放(经济下行/震荡)→高股息(南下偏好)。二者构成哑铃结构。"),
            ("估值乘数体系(E29/E102)", "PE/盈利稳定/PB-金融周期/PS-高成长未盈利/EV-EBITDA-跨资本结构/FCF Yield-现金流充裕。估值不仅是数学，更是人类学和社会学问题(周洛华)。"),
            ("达里奥价格公式(E119)", "P=TE/Q。价格=总支出/总销量。理解价格变动不仅要看基本面Q，更要看钱TE的流向。流动性>基本面。"),
        ]),
        ("——— Layer 2: 宏观周期与坐标 ———", [
            ("面基四象限", "宽/紧货币×宽/紧信用→经济扩张/复苏/过热/衰退。Shibor<1.8%=宽货币，M2>8%=宽信用，CPI>2.5%过热。"),
            ("康波周期(E94 孙加滢)", "康德拉季耶夫周期≈60年。内含3次房地产+6次固投+18次库存周期。当前处于第五轮康波衰退期→存量博弈。"),
            ("三周期嵌套(E126 林晓明)", "基钦周期(42月库存)+朱格拉周期(100月设备)+库兹涅茨周期(20年基建)。技术不是驱动周期的原因，而是周期的结果。"),
            ("债务周期(E119 Dalio)", "短期6±3年+长期80±25年。五大经济部门：居民+企业+政府+金融+海外。GDP增速>利率，否则债务/GDP持续上升。"),
            ("新宏观坐标(E131 唐军)", "逆全球化→供应链重构、人口结构→老龄化→低利率→资产重估、债务约束→高杠杆→低增长→财政货币化。"),
            ("效率→公平周期(E75 丁昶)", "一代人级别的范式转换。效率周期=全球化/比较优势→成长股溢价(2010-2020)。公平周期=自主可控→国产替代估值中枢上移(2021+)。"),
            ("短期/中期/长期框架(E72 南添)", "短期信市场(价格信号)、中期信共识(叙事)、长期信规律(框架)。实事求是=在不同时间尺度识别主导力量。"),
            ("r>g>w(E72 南添)", "利率>经济增长>工资增长=财富分配底层逻辑。r>g时存量财富增长快于增量→贫富分化加剧→政策纠偏。"),
        ]),
        ("——— Layer 3: 因子体系与选股策略 ———", [
            ("面基6因子", "质量(ROE>15%)+价值(PE分位<30%)+成长(营收增速>20%)+低波(Beta<0.8)+红利(股息率>3%)+动量(6个月前30%)。动态权重随宏观状态自适应。"),
            ("中观四层次(E7/E84)", "产业生命周期→需求景气度→短期业绩兑现度→估值性价比。二阶导>一阶导，环比增速>同比增速，增速斜率>增速本身。"),
            ("Perez五阶段(E94/E98)", "导入→转折→展开→成熟→沉寂。AI是第六轮康波主导技术，处于导入→转折期。胜出的不是技术最牛的，而是让技术大规模高效走入社会的企业。"),
            ("五层蛋糕(E155/黄仁勋)", "芯片→硬件→模型→应用→终端用户。Capex是护城河，合同负债是业绩前瞻。HALO特征(重资产、低淘汰)公司更安全。"),
            ("三层漏斗(E13 南添)", "粗筛排除毒药(ST/现金流负/高质押)→因子打分排序→DCF估值安全边际>30%确认。实事求是=事实层(what)→解释层(why)→决策层(how)。"),
            ("红利策略(E55 莽叔+E75 丁昶)", "红利因子在低利率/震荡市中持续有效。公平周期→红利策略占优。效率周期→成长策略占优。关注：股息率、分红连续性、分红比例可持续性。"),
            ("轮动策略(E54 张翼轸)", "有纪律地追涨杀跌—基于相对强度在各ETF间轮动。回看N月涨幅排名前K→持有到反转→没感情地跟随大哥。"),
            ("量化阿尔法公式(E85 田大伟)", "阿尔法=能力×宽度²。A股动量与反转都很强但周期短。价值因子长期有效但时滞长。指增核心：跟踪误差vs信息比率的平衡。"),
            ("地效飞行器策略(E31 丁昶)", "买最小市值的一批股票等量持有。底层逻辑：A股小票有壳价值+散户主导的波动红利。小市值因子长期有效。"),
            ("冠军基金魔咒(E7)", "过去表现最好的基金未来表现往往最差——均值回归的经典体现。选策略≠选冠军。"),
        ]),
        ("——— Layer 4: 交易纪律与风险管理 ———", [
            ("凯利公式(E153)", "f*=(bp-q)/b。b=赔率，p=胜率，q=1-p。半凯利=min(凯利/2, 2%)。同时追求两件事：不出局+长期增长最大化。"),
            ("复利增长公式(E153)", "G=Edge×Position×Frequency×Time。不同流派本质是寻找不同维度的Edge。普通投资者买指数=承认自己没有优势→市场平均β。"),
            ("杠铃策略(E111 塔勒布)", "90%极度安全(国债/现金)+10%极度风险(期权/VC/BTC)。不要在中间地带浪费仓位。反脆弱=凸性结构：损失有限、收益无限。"),
            ("遍历性(E111/E118)", "存在爆仓可能的策略，长期亏损概率=100%。不出局是复利的第一前提。避免策略无关的灾难性风险。"),
            ("2%风险常数(E153)", "单笔交易最大亏损≤总资金2%。连错10次亏20%→需25%回本。合理仓位比大部分人想象的低很多。"),
            ("8%硬止损(LDS)", "每笔交易预设8%止损线，到了就执行。这是纪律铁律，不可商量。截断亏损，让利润奔跑。"),
            ("15%/30%分级止盈(LDS)", "第一目标15%减半仓锁定利润→第二目标30%清仓。不贪最后一分钱。"),
            ("Nick灵魂四问(E81/E118)", "①紧急度②真实趋势③身边人共识④持有者拥挤度。低共识+强趋势=最佳入场。高共识+高热度=危险信号。"),
            ("四重确认入场(LDS)", "宏观→趋势→因子→选股全部通过才买入。任意一重不通过→等待。宁愿错过也不要买错。"),
            ("空仓哲学(E65 何潇)", "当市场没有能力圈内的机会时，空仓是最佳策略。找最悲观的时候买(非最低)，最乐观的时候卖(非最高)。"),
        ]),
        ("——— Layer 5: 行为金融与投资哲学 ———", [
            ("复杂适应系统(E114)", "CAS vs 传统经济学：有机/动态/非线性 vs 机械/均衡。非均衡是常态。乱纪元防住风险=收益。收益递增：规模效应的非线性。"),
            ("控制论·正负反馈(E147)", "正反馈=成长投资(自我强化)。负反馈=价值投资(均值回归)。尺度问题：不同时间尺度不同机制。结构决定行为：商业模式决定盈利。"),
            ("塔勒布五部曲(E111)", "随机漫步的傻瓜(区分运气与技能)→黑天鹅(极端斯坦vs平均斯坦)→反脆弱(脆弱/坚韧/反脆弱三元结构)→非对称风险(Skin in the game)→肥尾效应(高阶矩风险)。"),
            ("贝叶斯哲学(E30/E77)", "用新信息不断更新先验概率。不当聪明投资者，只做合格持有人。先对自己虔诚，别盲目拜大神。体系完整先于逻辑自洽。"),
            ("趋势动物四原则(E118 Nick)", "价格信仰(价格反映一切信息)→追涨杀跌(赔率不对称)→非对称(截断亏损/让利润奔跑)→遍历性(避免爆仓/确保活到下一轮趋势)。"),
            ("交易艺术四原则(E144 Nick)", "不预测→统计优势→分散红利→随机波动。趋势跟踪哲学：价格代表一切，跟价格走就行。"),
            ("周期·估值·人性(E35 凌鹏)", "投资中不变的三件事。万物皆周期，估值终有效，人性永不变。涨多了会跌，跌多了会涨——刻在基因里的规律。"),
            ("投资光谱右移(E32 南添)", "增量时代看左侧(新技术/营收)，存量时代看右侧(现金流/股息)。判断标的处于光谱哪个位置，决定买什么。"),
            ("择时的真相(E128 董艺婷)", "择时胜率长期<50%，时间成本极高。更有效策略：动态再平衡(纪律化低买高卖)。雷击时刻效应：市场暴跌集中在极少数交易日。"),
            ("基金经理三类画像(E103)", "猎手(寻找机会/灵活调仓)、教主(理念驱动/长期持有)、军师(系统思维/配置驱动)。不同市场环境适配不同画像。"),
        ]),
        ("——— Layer 6: 资产配置与组合构建 ———", [
            ("有效前沿(最新期)", "组合收益=Σw×E(R)，组合风险≠各资产风险的简单相加。要么找更好的资产，要么找更不一样的资产(低/负相关性)。资产配置的真正对象是资产之间的相关性。"),
            ("全天候策略(E119)", "All Weather: 30%股+55%债+15%商品。四象限框架：增长↑↓×通胀↑↓各对应不同资产配置。风险平价：每个资产风险贡献相等。"),
            ("多元资产九宫格(E109 Kevin)", "进攻型/均衡型/防御型×中国/发达/另类。弱者思维→对未来没有观点→必须分散。四字诀：薄情、逆向、多元、有限下注。"),
            ("LDS全天候ETF", "4类低相关资产对冲：红利低波25%+纳斯达克30%+黄金25%+豆粕20%。月度再平衡，定投不需择时。"),
            ("退休传家组合(E99 丁昶)", "标普500+全球黄金ETF+全球REITs=穿越周期的三大支柱。不需要择时，需要的是耐心持有。"),
        ]),
    ]

    for section_title, items in full_concepts:
        w.write_blocks([w.h(4, section_title)])
        for name, detail in items:
            w.write_blocks([w.styled_bullet(f"📌 {name}", f"：{detail}")])
        w.write_blocks([w.blank()])

    # 概念统计
    total_concepts = sum(len(items) for _, items in full_concepts)
    w.write_blocks([w.plain(f"> 📊 共计 **{total_concepts}** 条面基播客核心概念（154期提炼），分布在估值/宏观/因子/交易/行为/配置6大层级。每日日报中随机轮换1条结合市场分析。\n")])

    # 签名
    w.write_blocks([w.blank(), w.plain("⚠️ 本报告由AI量化系统自动生成，仅供参考，不构成投资建议。系统基于面基播客+LDS实战框架+Vibe-Trading量化工具三源融合构建。")])

    # 授权
    _grant_perms(doc_id)
    doc_url = f"https://bytedance.feishu.cn/docx/{doc_id}"
    print(f"  [report] ✅ {doc_url}")
    return doc_url


def _grant_perms(doc_id):
    try:
        token = _get_feishu_token()
        if not token:
            print(f"  [perms] ❌ no token")
            return
        req2 = urllib.request.Request(
            f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx&need_notification=false",
            data=json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req2, timeout=10).read()
        print(f"  [perms] ✅ full_access")
    except Exception as e:
        print(f"  [perms] {e}")


def push_to_group(doc_url, note=""):
    try:
        token = _get_feishu_token()
        if not token:
            return
        msg_text = f"📊 面基三源融合日报 v5 | {datetime.now().strftime('%Y-%m-%d')}\n{note}\n{doc_url}" if note else f"📊 面基三源融合日报 v5 | {datetime.now().strftime('%Y-%m-%d')}\n{doc_url}"
        body = {"receive_id": GROUP_CHAT, "msg_type": "text", "content": json.dumps({"text": msg_text})}
        r2 = urllib.request.Request(
            "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(r2, timeout=10)
        print("[push] ✅")
    except Exception as e:
        print(f"[push] {e}")


if __name__ == "__main__":
    from investment_system.macro_engine import MacroEngine
    from investment_system.factor_scanner import FactorScanner
    from investment_system.global_data import fetch_all_global_market, load_cached_global_data
    from investment_system.shadow_account import get_shadow_summary

    print("=" * 50)
    print(f"📊 面基三源融合日报 v5.3 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    print("\n1️⃣  宏观...")
    macro = MacroEngine()
    s = macro.refresh()
    print(f"    四象限={s.get('quadrant','')} 趋势={s.get('trend_temp','')} 开关={s.get('strategy_switch','')}")
    # v5.1: 显示双门
    dual = s.get('dual_gate', {})
    print(f"    双门={dual.get('combo','?')} → {dual.get('action','?')}")
    guoyun = s.get('guoyun', {})
    if guoyun.get('price'):
        print(f"    国运线={guoyun['price']:.0f} 偏离={guoyun.get('deviation','?')}%")

    print("\n2️⃣  扫描...")
    scanner = FactorScanner(macro)
    scanner.MAX_SCAN = 50  # 扩容：50只板块轮抽，确保行业覆盖均衡
    results = scanner.scan_market("smart", 10)
    print(f"    完成: {len(results)}只")

    print("\n3️⃣  全球数据...")
    gdata = load_cached_global_data()
    if not gdata:
        gdata = fetch_all_global_market()

    print("\n3.5️⃣  新闻...")
    try:
        from investment_system.news_fetcher import fetch_news
        news_data = fetch_news()
        print(f"    抓取: {news_data.get('total', 0)}条")
    except Exception as e:
        print(f"    ⚠️ {e}")
        news_data = None

    print("\n4️⃣  Shadow Account...")
    shadow = get_shadow_summary()

    print("\n5️⃣  生成日报 v5.3...")
    url = generate_report(s, results, gdata, shadow, news_data)

    if url:
        print("\n6️⃣  推送...")
        push_to_group(url, f"v5.3 产业链深度+全部概念附录 | LDS双门={dual.get('action','?')} 国运线偏离{guoyun.get('deviation','?')}% CPI={s.get('macro_data',{}).get('cpi','?')}%")
    print("\n✅ 完成")
