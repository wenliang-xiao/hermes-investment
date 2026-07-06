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
doc_result = feishu_call("create_feishu_document", {
    "title": "面基投资系统 · 全局架构诊断与重构方案 · "+today,
    "folderToken": FOLDER_TOKEN})
doc_id = ""
if isinstance(doc_result, list) and len(doc_result) > 0:
    doc_id = doc_result[0].get("document", {}).get("document_id", "")
if not doc_id:
    doc_id = doc_result.get("document", {}).get("document_id", "")
if not doc_id:
    print("FAIL")
    sys.exit(1)
grant(doc_id)
print(doc_id)

blocks = []
B = blocks.append

B(h(1, "面基投资系统 · 全局架构诊断与重构方案"))
B(p("编制日期: "+today+" | 作者: AI Agent | 状态: 待讨论定稿"))
B(p(""))

B(h(2, "一、核心发现摘要"))
B(p("通过对系统全量代码审查 + 今日运行数据分析, 发现 5 类关键问题:"))
B(bl("【交易纪律】三策略缺乏周频限制, 今日SilverQuant生成5个信号(1BUY+4SELL), 严重违反纪律"))
B(bl("【Dashboard】数据不更新、无导航、无详情页、无日报/周报入口、无新闻汇总"))
B(bl("【票池】19只固定标的硬编码在evaluator_fixed.py, 无动态发现机制"))
B(bl("【覆盖范围】只有A股19只, 港股0只, 美股仅间接覆盖, ETF择时/非择时未落地"))
B(bl("【药明康德】评分系统给6.2(全池最高), 但US生物安全法案尾风险完全未被捕获"))
B(p(""))

B(h(2, "二、交易纪律: 周频限制缺失"))
B(p("今日SilverQuant信号:"))
B(cd("[MED] silverquant BUY  603259 药明康德 @124.51   槽位建仓(评分5.5)\n[MED] silverquant SELL 300502 新易盛   @607.00   MASeller\n[MED] silverquant SELL 688008 澜起科技  @309.90   MASeller\n[MED] silverquant SELL 002371 北方华创  @884.56   MASeller\n[MED] silverquant SELL 688256 寒武纪   @1595.55  MASeller"))
B(p("同一策略一天5个信号, 违反纪律。修复: WeekTradeCounter", True))

B(h(3, "修复方案"))
B(bl("WeekTradeCounter: 记录每策略本周BUY次数, 上限1次/周"))
B(bl("SELL信号: 不受限(止损优先)"))
B(bl("BUY信号: 生成前检查本周额度"))
B(bl("黑天鹅豁免: 组合跌幅>3%或指数跌>5%时临时放开"))
B(cd('''class WeekTradeCounter:
    def __init__(self):
        self.file = "data/week_trade_counter.json"
        self.data = self._load()
    def _load(self):
        import json, os
        if os.path.exists(self.file):
            with open(self.file) as f: d = json.load(f)
            if d.get("week_start") == self._week_start(): return d
        return {"week_start": self._week_start(), "counts": {}}
    def _week_start(self):
        from datetime import datetime, timedelta
        return (datetime.now()-timedelta(days=datetime.now().weekday())).strftime("%Y-%m-%d")
    def can_trade(self, s): return self.data["counts"].get(s,0) < 1
    def record(self, s):
        self.data["counts"][s]=self.data["counts"].get(s,0)+1
        with open(self.file,"w") as f: json.dump(self.data,f)'''))
B(p(""))

B(h(2, "三、药明康德(603259)深度分析"))
B(p("为什么评分6.2(全池最高)?", True))
B(bl("基本面因子: ROE~15%+, 毛利率~40%+, 自由现金流正数, CXO赛道龙头"))
B(bl("技术因子: RSI中性, MACD死叉修复中"))
B(bl("行业因子: 创新药产业链, 国内CRO绝对龙头"))
B(bl("因子系统只看到这些, 没看到地缘政治风险"))
B(p(""))
B(p("【US BIOSECURE Act】美国生物安全法案直接针对药明, 限制联邦合同。股价从$120跌到$30再反弹, 法案风险仍悬顶。"))
B(p(""))
B(p("修复方向:", True))
B(bl("A方案: FIXED_UNIVERSE评分从6.2降至3.0(体现地缘政治折价)"))
B(bl("B方案: 移出核心池, 加入外部观察池"))
B(bl("C方案: 新增'地缘政治风险'因子(-1~-3)"))
B(bl("推荐: A+B — 降评分至3.0 + 移出核心池"))
B(p(""))

B(h(2, "四、票池重构: 发现-盯住-深度三层动态池"))
B(h(3, "4.1 发现层 (WatchLayer)"))
B(bl("每日因子扫描 Top30 + 新闻异动"))
B(bl("保留条件: 评分>5.0, 否则淘汰"))
B(bl("输出: 日报'今日发现'专栏"))
B(h(3, "4.2 盯住层 (MonitorLayer)"))
B(bl("发现层评分>5.5满1周自动升级"))
B(bl("保留条件: 评分>5.0, 可手动移除"))
B(bl("每只显示: 价格/评分趋势/技术状态/止损价"))
B(h(3, "4.3 深度分析层 (DeepLayer)"))
B(bl("盯住层评分>6.0满2周 + 通过不为清单 → 自动出研报"))
B(bl("研报8维: 产业链/DCF/凯利/Nick四问/贝叶斯/风险/面基引用"))
B(h(3, "4.4 ETF组合层"))
B(bl("择时组合: TrendFollowing(MA20/MA60), 标的: SPY+QQQ+TLT+GLD+510300"))
B(bl("非择时组合: RiskParity, 标的: 510300+511010+SPY+TLT"))
B(p(""))

B(h(2, "五、Dashboard重构: 7面板+侧边栏导航"))
B(bl("概览面板: 总资产/绩效指标/今日信号 — 已有 /api/metrics"))
B(bl("持仓面板: 分策略, 可点击展开详情 — 已有 /api/simulated"))
B(bl("信号面板: 按策略分组, 含投票记录 — 已有 /api/signals"))
B(bl("票池面板: 发现/盯住/深度三层 — 新建 /api/v2/pool"))
B(bl("ETF面板: 择时/非择时组合+再平衡提醒 — 新建 /api/v2/etf"))
B(bl("新闻面板: 东财板块新闻+个股异动 — 调用 news_pipeline"))
B(bl("日报面板: 最新文档链接自动检测 — 新建 /api/v2/reports"))
B(p(""))

B(h(2, "六、覆盖范围目标"))
make_table = lambda hd, rows: cd("\n".join(
    [" | ".join(hd)] + ["|".join(["---"]*len(hd))] + [" | ".join(str(c) for c in r) for r in rows]
))
B(make_table(["市场","目标数量","数据源","用途"],
    [["A股","30-50只","factor_scanner+baostock","核心交易池"],
     ["港股","10-15只","yfinance","港股通+中概"],
     ["美股","15-20只","yfinance","科技+消费+ETF"],
     ["ETF择时","8-10只","etf_universe+yfinance","宏观轮动"],
     ["ETF非择时","4-6只","etf_universe+baostock","底仓配置"]]))
B(p(""))

B(h(2, "七、分阶段实施路径"))
B(h(3, "Phase 1 本周"))
B(bl("WeekTradeCounter -> 修复run_trading.py (1h)"))
B(bl("药明康德降评分至3.0 + 移出核心池 (15min)"))
B(bl("FIXED_UNIVERSE增加不为清单权重字段 (30min)"))
B(bl("Dashboard日报链接改为自动检测 (30min)"))
B(p(""))
B(h(3, "Phase 2 1-2周"))
B(bl("PoolManager: watch/monitor/deep三层 + 每日自动升降级"))
B(bl("Dashboard 7面板 + 侧边栏导航"))
B(bl("日报新增发现/盯住/深度三专栏"))
B(bl("新增 /api/v2/pool + /api/v2/reports"))
B(p(""))
B(h(3, "Phase 3 2-4周"))
B(bl("港股/美股纳入factor_scanner扫描"))
B(bl("ETF择时组合实盘信号"))
B(bl("ETF非择时组合季度再平衡"))
B(bl("不为清单集成到策略执行层"))
B(p(""))

B(h(2, "八、需讨论确认"))
B(bl("1. 药明康德: 降评分(A) vs 移出(B) vs 新增地缘因子(C)?"))
B(bl("2. 周频限制: BUY每周1次/策略, SELL不受限 → 接受?"))
B(bl("3. 港股/美股池: 你给我清单 vs 我按面基产业链自动生成?"))
B(bl("4. ETF择时策略: TrendFollowing vs RiskParity vs 你指定?"))
B(bl("5. Dashboard 7面板: 够不够? 需要增减什么?"))
B(bl("6. 深度分析触发: 评分>6.0自动出 vs 你手动触发?"))
B(bl("7. 不为清单10条规则: 你先review还是先用默认?"))

write_blocks(doc_id, blocks)
url = "https://bytedance.feishu.cn/docx/"+doc_id
print("OK")
print("Doc:", url)
