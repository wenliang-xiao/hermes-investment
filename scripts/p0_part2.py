#!/usr/bin/env python3
"""面基投资系统·全局架构诊断与重构方案 - 推送飞书文档"""
import sys, os, json, subprocess, time
from datetime import date

FEISHU_TOOL = "/home/admin/.hermes/node_modules/.bin/feishu-tool"
WORK_DIR = "/home/admin/.hermes"
FOLDER_TOKEN = "QhIOfB63Sl6Kqmd81fycjR6jnDd"
USER_OPENID = "ou_e03d56632de9b44263adfc018f9d6e4d"

with open("/home/admin/.feishu-user-plugin/credentials.json") as f:
    creds = json.load(f)
APP_ID = creds["profiles"]["default"]["LARK_APP_ID"]
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]

def feishu_call(tool, payload):
    d = json.dumps(payload, ensure_ascii=False)
    r = subprocess.run(["bash", "-c", "cd "+WORK_DIR+" && FEISHU_SCOPE_VALIDATION=false "+FEISHU_TOOL+" "+tool+" '"+d+"'"],
        capture_output=True, text=True, timeout=30)
    try: return json.loads(r.stdout)
    except: return {}

def h(lv, text):
    return {"blockType": "heading", "options": {"heading": {"level": lv, "content": text}}}
def t(text, bold=False, color=None):
    s = {"text": text}
    style = {}
    if bold: style["bold"] = True
    if color: style["text_color"] = color
    if style: s["style"] = style
    return s
def p(*segs):
    styles = []
    for seg in segs:
        if isinstance(seg, str): styles.append({"text": seg})
        elif isinstance(seg, dict): styles.append(seg)
    return {"blockType": "text", "options": {"text": {"textStyles": styles}}}
def cd(text):
    return {"blockType": "code", "options": {"code": {"code": text, "language": 1, "wrap": True}}}
def bl(text):
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}

def write_blocks(doc_id, blocks):
    for i in range(0, len(blocks), 12):
        batch = blocks[i:i+12]
        feishu_call("batch_create_feishu_blocks",
            {"documentId": doc_id, "parentBlockId": doc_id, "index": i, "blocks": batch})
        time.sleep(0.3)

def get_token():
    r = subprocess.run(["curl", "-s", "-X", "POST",
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
        capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout).get("tenant_access_token", "")

def grant(doc_id):
    token = get_token()
    if not token: return
    subprocess.run(["curl", "-s", "-X", "POST",
        "https://open.feishu.cn/open-apis/drive/v1/permissions/"+doc_id+"/members?type=docx&need_notification=false",
        "-H", "Authorization: Bearer "+token,
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"})],
        capture_output=True, timeout=10)

# ═══ 创建文档 ═══
today = date.today().isoformat()
doc_id = "XWa2df4yNoZ8WyxLTahc0TAtnGe"  # 追加到现有诊断文档
grant(doc_id)
print("APPENDING_TO", doc_id)

blocks = []
B = blocks.append

B(h(1, "P0 深度复盘 · Q1交易决策 + 三源方案 + Multiagent执行计划"))
B(p("编制: " + date.today().isoformat() + " | 基于铁证数据"))
B(p(""))

B(h(2, "一、Q1 深度复盘：为什么买了伊利/长电而不是科技主线？"))
B(p("结论: 不是操作失误, 是因子引擎结构性偏向防守因子"))
B(cd("7/9扫描快照评分排序(策略买入信号当天):\n长电7.19 > 全志6.60 > 云天励飞6.22 > 伊利6.02 > 海光5.91 > 宁德5.82 > 茅台5.63 > 北方华创4.87\n\n8/7同一点位评分排序(一个月后):\n宁德0.676 > 北方华创0.585 > 茅台0.574 > 海光0.570 > 伊利0.559"))
B(p(""))
B(p("因子分解铁证:"))
B(cd("长电600900: low_vol=1.0, value=0.833, sentiment=1.0, risk=1.0 → 防守因子满分\n北方华创002371: momentum=0.444, sentiment=0.167 → 科技因子低压\n伊利600887: momentum=1.0, value=0.667, risk=1.0 → 防守加权"))
B(p(""))
B(bl("根因1: 因子引擎默认权重偏向防守(low_vol/value/risk), 科技主线启动初期被系统性低估"))
B(bl("根因2: momentum因子只在涨起来后才追高, 无法识别启动初期(点回头逻辑缺失)"))
B(bl("根因3: sentiment因子(行业热度)数据缺失/滞后, 科技主线情绪高涨未被捕获"))
B(p(""))
B(h(3, "Q1 修复方向"))
B(bl("因子权重改造: 引入主线识别(行业景气+资金流向), 科技/成长风格在启动期加权"))
B(bl("新增'主线对齐'检查: 买入前验证标的所属链是否处于景气上行期(链景气因子)"))
B(bl("评分体系: 防守股(长电/伊利)不应因低波动/高分红获得远超成长股的分数"))
B(bl("不做数据恢复: 模拟盘从零重建, 但保留trade_log作为诊断样本"))
B(p(""))

B(h(2, "二、Q2 大师持仓三源方案 (最全数据)"))
B(bl("源1: aiyuan.ai/gurus — 21位顶级投资者13F持仓(段永平/木头姐/伯克希尔/阿申布伦纳)"))
B(bl("源2: SEC EDGAR 官方API — 13F filings原始数据(美股, 季度频)"))
B(bl("源3: HKEX CCASS — 港股中央结算持仓(日频, 大股东增减持)"))
B(p(""))
B(h(3, "实现管线"))
B(cd("1. scripts/guru_holdings.py — 爬aiyuan.ai/gurus (解析Next.js JSON)\n2. scripts/sec_edgar_13f.py — SEC EDGAR 13F下载+解析 (官方API, 免费)\n3. scripts/hkex_ccass.py — HKEX CCASS 抓取 (日频)\n4. data/guru_holdings.json + 3源合并归一化\n5. dashboard 新tab: 大师持仓 (按人/按股票/按变化)"))
B(p(""))

B(h(2, "三、Q3 未成交分析数据的深度利用"))
B(bl("现状: 每日策略产出大量信号, 但受交易纪律限制未成交 → 数据被浪费"))
B(bl("问题: 未成交信号反射了选股方向, 是宝贵的研究资产"))
B(p(""))
B(h(3, "方案: 观点库(Watchlist Insights)"))
B(cd("1. 每日扫描后, 所有信号(含未成交)沉淀到 data/insights.json\n2. 记录: 信号日期/标的/方向/评分/因子分解/为何未成交(周频限制?冷却?)\n3. 每周日报新section: 未成交信号回顾 — 如果当时买了会怎样(反事实演练)\n4. 链上榜: 被反复信号但未成交的标的上浮至Monitor层"))
B(p(""))

B(h(2, "四、数据管线修复 (P0-1/2/3)"))
B(bl("修复1: crontab 全部脚本改用 hermes-agent/venv 绝对路径 python"))
B(bl("修复2: 模拟盘冷却bug — TRADE_COOLDOWN_DAYS同天不算冷却, executed标记修正"))
B(bl("修复3: 验证全部cron脚本能跑通(numpy/pandas/baostock可用)"))
B(p(""))

B(h(2, "五、Multiagent 执行计划 (并行无冲突)"))
B(cd("WS1: 数据管线修复(crontab+venv+冷却bug) — 主线, 我直接做\nWS2: 大师持仓三源爬虫(guru_holdings+sec_edgar+hkex) — 并行subagent\nWS3: 未成交信号观点库(insights.json+日报section) — 并行subagent\nWS4: Dashboard新tab(大师持仓+观点库) — 在WS2/3完成后\nWS5: 因子权重优化(Q1复盘结论实施) — 大改, 独立评审"))
B(p(""))
B(bl("无冲突原则: 每WS独立文件集; WS4依赖WS2/3输出; 因子权重(WS5)隔离评审"))

write_blocks(doc_id, blocks)
print("PART2_OK blocks=", len(blocks))
