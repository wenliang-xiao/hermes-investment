"""
面基三源融合系统 v10 改版方案 → 飞书文档
"""
import subprocess, json, os, sys, time

FEISHU_TOOL = "/home/admin/.hermes/node_modules/.bin/feishu-tool"
WORK_DIR = "/home/admin/.hermes"
APP_ID = "cli_aa8445bca6f81bb7"

with open("/home/admin/.feishu-user-plugin/credentials.json") as f:
    creds = json.load(f)
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]
FOLDER_TOKEN = "QhIOfB63Sl6Kqmd81fycjR6jnDd"
USER_OPENID = "ou_e03d56632de9b44263adfc018f9d6e4d"
TITLE = "面基三源融合系统 v10 改版方案设计"

def feishu_call(tool, payload):
    d = json.dumps(payload, ensure_ascii=False)
    r = subprocess.run(["bash", "-c", f"cd {WORK_DIR} && FEISHU_SCOPE_VALIDATION=false {FEISHU_TOOL} {tool} '{d}'"],
        capture_output=True, text=True, timeout=30)
    return json.loads(r.stdout)

def get_token():
    r = subprocess.run(["curl", "-s", "-X", "POST",
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
        capture_output=True, text=True, timeout=10)
    return json.loads(r.stdout)["tenant_access_token"]

def grant(doc_id):
    token = get_token()
    r = subprocess.run(["curl", "-s", "-X", "POST",
        f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx&need_notification=false",
        "-H", f"Authorization: Bearer {token}", "-H", "Content-Type: application/json",
        "-d", json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"})],
        capture_output=True, text=True, timeout=10)

def h(lv, text):
    return {"blockType": "heading", "options": {"heading": {"level": lv, "content": text}}}
def p(*segs):
    styles = []
    for seg in segs:
        if isinstance(seg, str): styles.append({"text": seg})
        elif isinstance(seg, tuple):
            s = {}
            if len(seg) > 1 and seg[1]: s["bold"] = True
            if len(seg) > 2 and seg[2] is not None: s["text_color"] = seg[2]
            e = {"text": seg[0]}
            if s: e["style"] = s
            styles.append(e)
    return {"blockType": "text", "options": {"text": {"textStyles": styles}}}
def code(text, lang=1):
    return {"blockType": "code", "options": {"code": {"code": text, "language": lang, "wrap": True}}}
def bullet(text):
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}

print("📄 Creating doc...")
result = feishu_call("create_feishu_document", {"title": TITLE, "folderToken": FOLDER_TOKEN})
if isinstance(result, list): doc_id = result[0].get("document", {}).get("document_id", "")
else: doc_id = result.get("document", {}).get("document_id", "")
print(f"  {doc_id}")
grant(doc_id)

blocks = []
idx = 0
def write(blk):
    global idx
    for i in range(0, len(blk), 12):
        batch = blk[i:i+12]
        r = feishu_call("batch_create_feishu_blocks",
            {"documentId": doc_id, "parentBlockId": doc_id, "index": idx, "blocks": batch})
        n = r.get("totalBlocksCreated", len(batch))
        idx = r.get("nextIndex", idx + n)
        time.sleep(0.3)

# ── Cover ──
blocks.append(h(2, "面基三源融合系统 v10 改版方案设计"))
blocks.append(p(("目标：", True), "三策略融合 + 信号式交易 + 因子升级 + 中观产业链 + 专业日报"))
blocks.append(p(("日期：", True), "2026-06-24"))
blocks.append(p(("状态：", True, 3), "设计阶段 — 待讨论确认"))

# ── Architecture ──
blocks.append(h(2, "📐 总体架构变更"))
blocks.append(code(
    "当前(v9)              →     目标(v10)\n"
    "──────                      ────────\n"
    "run_daily.py 跑面基单策略  →  run_trading.py 跑三策略，输出信号\n"
    "日报=数据dump+分析        →  日报=信号驱动(信号是核心输出)\n"
    "无中观产业链分析          →  按链扫描(利润池→瓶颈→映射标的)\n"
    "模拟盘空转                →  信号输出→你手动执行→反馈记录\n"
    "新闻 GLM RSS              →  多源聚合+分级\n"
    "因子静态排序分位法        →  融合SQ风控+TA Kelly+动态评分"
))

# ── WP1 ──
blocks.append(h(2, "🧱 工作包1: 三策略融合运行引擎"))
blocks.append(p(("目标：", True), "每天跑三个策略，输出信号对比表"))
blocks.append(p(("新建文件：", True)))
blocks.append(bullet("scripts/run_trading.py — 三策略逐日执行器，输出 data/trading_signals.json"))
blocks.append(bullet("analysis/trading_engine.py — 策略调度器：顺序执行 faceji → SQ → TA"))
blocks.append(bullet("scripts/portfolio_server.py 新增 /api/signals 端点"))
blocks.append(h(3, "信号格式"))
blocks.append(code(
    "{\n"
    "  \"date\": \"2026-06-24\",\n"
    "  \"signals\": [\n"
    "    {\n"
    '      "id": "SIG-20260624-001",\n'
    '      "strategy": "faceji",\n'
    '      "action": "BUY",\n'
    '      "symbol": "603259",\n'
    '      "name": "药明康德",\n'
    '      "price": 92.21,\n'
    '      "size_pct": 3.0,\n'
    '      "reason": "评分6.2+MA趋势向上",\n'
    '      "priority": "HIGH"\n'
    "    }\n"
    "  ]\n"
    "}"
))
blocks.append(h(3, "信号冲突处理"))
blocks.append(bullet("同一标的多个策略同时希望买卖 → 面基策略优先级最高"))
blocks.append(bullet("同一个策略同一日同时BUY和SELL同一标的 → 只有SELL（先卖再买违反周频规则）"))

# ── WP2 ──
blocks.append(h(2, "🧱 工作包2: 信号式手动交易系统"))
blocks.append(p(("你的工作流：", True)))
blocks.append(bullet("日报生成 → 看到信号表"))
blocks.append(bullet("你打开富途/牛牛按信号手动执行"))
blocks.append(bullet("反馈给 agent → agent 记录到 shadow_account"))
blocks.append(h(3, "交易纪律（硬编码）"))
blocks.append(bullet("🚫 任一策略每周最多交易 1 次（开仓或清仓）"))
blocks.append(bullet("🚫 所有策略合计每周最多 3 次交易"))
blocks.append(bullet("🔒 黑天鹅例外：单日跌 >6% 或宏观危机"))
blocks.append(bullet("📊 A股交易日历自动识别"))

# ── WP3 ──
blocks.append(h(2, "🧱 工作包3: 因子升级（SilverQuant风控 + TA Kelly）"))
blocks.append(h(3, "清仓规则升级（融合 SilverQuant 4层组件）"))
blocks.append(code(
    "# 面基原清仓                    # 升级后\n"
    "评分<4 → 卖出                  ScoreDropSeller: 评分<4.5 → 卖出\n"
    "评分<5 + MA死叉 → 卖出         HardSeller: 浮动亏损≥-8% → 硬止损\n"
    "                                 FallSeller: 峰值回落≥-12% → 止盈\n"
    "                                 MASeller: MA死叉+亏损<5% → 卖出"
))
blocks.append(h(3, "仓位管理升级（融合 TA Kelly）"))
blocks.append(code(
    "# 面基原仓位                    # 升级后\n"
    "固定 ¥30K/槽位                 win_prob = min(score/10, 0.8)\n"
    "                                kelly = (wp×2 - (1-wp))/2 × 0.5\n"
    "                                position = cash × min(kelly, 0.08)"
))

# ── WP4 ──
blocks.append(h(2, "🧱 工作包4: 新闻管线升级"))
blocks.append(code(
    "层级    来源             用途          优先级\n"
    "────    ──────           ─────         ──────\n"
    "Tier1   财联社API        实时异动信号    HIGH (cron独立推送)\n"
    "Tier2   AKShare个股新闻   持仓标的分析    MED (日报)\n"
    "Tier3   GLM RSS聚合      宏观趋势        LOW (周报)"
))

# ── WP5 ──
blocks.append(h(2, "🧱 工作包5: 中观产业链分析"))
blocks.append(p(("核心理念：", True), "买在利润最厚的环节，不买整条链——面基播客核心方法论"))
blocks.append(bullet("新建 analysis/chain_scanner.py — 按12条产业链扫描利润池位置"))
blocks.append(bullet("因子评分增加 chain_position / profit_pool_score / bottleneck_score"))
blocks.append(h(3, "12条产业链（来自面基知识体系）"))
blocks.append(code(
    "链                    利润池\n"
    "───                   ──────\n"
    "英伟达算力链            光模块30-55%、HBM 50%+\n"
    "台积电先进制程链        设备40-55%、CoWoS 45%+\n"
    "机器人核心零部件        减速器40%、伺服电机30%\n"
    "半导体链                IP 80%+、设备\n"
    "AI电力                  核电PPA、燃气轮机\n"
    "新能源链                储能逆变器\n"
    "军工链                  连接器、材料\n"
    "医药创新链              CXO、创新药\n"
    "消费防守链              高端白酒\n"
    "金融链                  零售银行\n"
    "电网设备链              超高压变压器\n"
    "大宗商品链              铜、黄金"
))

# ── WP6 ──
blocks.append(h(2, "🧱 工作包6: 日报专业化升级"))
blocks.append(p(("新日报结构：", True)))
blocks.append(code(
    "H1: 面基三源融合日报 v10\n"
    "│\n"
    "├─ H2: ① 宏观速览 (3行结论)\n"
    "├─ H2: ② 今日信号 ← 核心新增\n"
    "│   策略        买入     卖出     理由\n"
    "│   面基        药明康德  -       评分6.2\n"
    "│   SilverQuant -       新易盛   MASeller\n"
    "│   TradingAgents -     -       无辩论分≥5.5\n"
    "│   ⭐ 执行建议  药明康德3%      面基优先\n"
    "├─ H2: ③ 组合状态(持仓+待执行)\n"
    "├─ H2: ④ 产业链发现(中观扫描)\n"
    "├─ H2: ⑤ 异动情报\n"
    "├─ H2: ⑥ 行动指令\n"
    "├─ H3: 附录A: 六层漏斗审计\n"
    "├─ H3: 附录B: 核心公式\n"
    "└─ H3: 附录C: 交易格言"
))

# ── Priority ──
blocks.append(h(2, "🗓 实施优先级与估算"))
blocks.append(code(
    "优先级   工作包                   工时    说明\n"
    "────    ──────                   ────    ────\n"
    "P0      2. 信号式交易             2h    最核心——日报先有信号\n"
    "P0      1. 三策略融合             3h    信号来源\n"
    "P1      3. 因子升级(SQ+TA)        2h    算法优化\n"
    "P1      6. 日报专业化             2h    输出格式\n"
    "P2      5. 中观产业链             3h    数据量大\n"
    "P3      4. 新闻升级               1h    锦上添花\n"
    "─────────────────────────────────────────\n"
    "合计                             ~13h"
))
blocks.append(h(3, "风险"))
blocks.append(bullet("三策略信号冲突 → 面基优先"))
blocks.append(bullet("周频限制错过入场 → 排队到下周再评估"))
blocks.append(bullet("baostock 速度瓶颈 → 降标的数或用缓存"))
blocks.append(bullet("日报写失败 → Phase1/2/3 三段架构已有保护"))

# Write
print(f"✍️ 写入 {len(blocks)} 块...")
write(blocks)
print(f"\n✅ 完成! https://bytedance.feishu.cn/docx/{doc_id}")