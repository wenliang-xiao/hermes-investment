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

B(h(1, "P0 数据管线修复 · 最终诊断 + 共识"))
B(p("编制: " + date.today().isoformat() + " | 状态: 铁证诊断完成, 待拍板后执行"))
B(p(""))

B(h(2, "一、根因铁证链（实测, 非推测）"))
B(p(""))

B(h(3, "根因A: crontab 用 /usr/bin/python3 (Py3.6.8无numpy) → 数据管线断5天"))
B(cd("crontab -l:\n0 8 * * 1-5  cd ... && python3 scripts/run_trading.py > /tmp/run_trading.log\n\n/tmp/run_trading.log:\nModuleNotFoundError: No module named 'numpy'\n\n原因: crontab PATH不含venv → python3解析为 /usr/bin/python3 (Py3.6.8)\n交互shell: /home/admin/.hermes/hermes-agent/venv/bin/python3 (Py3.11.15, 有numpy)"))
B(bl("影响: run_trading/run_factor_daily/ipo_discovery 全部崩溃"))
B(p(""))

B(h(3, "根因B: 模拟盘冷却期bug → 三策略互相卡死 (持仓长期为空)"))
B(cd("TRADE_COOLDOWN_DAYS = 1\ncan_trade(): if (datetime.now() - last_trade_date).days < COOLDOWN:\n\n同一天 diff=0天 < 1 → 必被拒!\n实测: faceji先买后, silverquant/tradingagents同批同标的全部被'冷却期'拦截\n→ 只有排最前的faceji能落仓, 后两个策略永远空"))
B(bl("铁证: 隔离数据源测试, 6个raw信号只execute 2笔(全是faceji)"))
B(bl("trade_log.json: 所有记录 executed:False (record_trade硬编码)"))
B(bl("record_trade()里 entry['executed']=False → 实际已成交却标False → dashboard模拟盘tab错误"))
B(p(""))

B(h(3, "根因C: dashboard tab 数据陈旧 + 港美股大户无数据源"))
B(bl("龙虎榜/票池/模拟盘: 因cron断→数据停8/7, 非端点错(端点已核对正确)"))
B(bl("港美股大师持仓(段永平/木头姐/伯克希尔/阿申布伦纳): 完全无数据源"))
B(bl("可爬: aiyuan.ai/gurus (21位顶级投资者13F, Next.js返回260KB HTML)"))
B(p(""))

B(h(2, "二、待拍板共识 (grill-me)"))
B(bl("Q1-模拟盘: 已查明非操作失误——是冷却bug+执行标记bug。恢复历史持仓(从trade_log回放) + 修冷却逻辑防复发"))
B(bl("Q2-大师持仓: 数据源=aiyuan.ai/gurus爬取 + SEC EDGAR 13F 官方API + HKEX CCASS 港股"))
B(bl("Q3-范围: 全部完成 (今天P0)。修复并行用multiagent, 隔离文件避免冲突"))

write_blocks(doc_id, blocks)
print("PART1_OK blocks=", len(blocks))
