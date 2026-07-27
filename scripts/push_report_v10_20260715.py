"""
Push v10 daily report to Feishu group.
Follows the skill's recipe: credentials.json -> token -> post messages -> IM API
"""
import json, urllib.request, sys

DOC_URL = "https://my.feishu.cn/wiki/EdUOw8XRpiiNYPkMyadcKNhynQL"
GROUP_ID = "oc_4c9d6445fab7f3a2ada0c410f3aa7043"  # 知行合一群
DATE = "2026-07-15"

# 1. Read credentials
with open("/home/admin/.feishu-user-plugin/credentials.json") as f:
    creds = json.load(f)
APP_ID = creds["profiles"]["default"]["LARK_APP_ID"]
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]
# 2. Get tenant_access_token
auth = json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
    {"Content-Type": "application/json"}), timeout=10).read())
token = auth["tenant_access_token"]
print(f"Token obtained: {token[:10]}...")

def send_post(title, content_lines):
    """Send a post message."""
    content = {"zh_cn": {"title": title, "content": content_lines}}
    payload = json.dumps({
        "receive_id": GROUP_ID,
        "msg_type": "post",
        "content": json.dumps(content, ensure_ascii=False)
    }, ensure_ascii=False)
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        payload.encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST")
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    if resp.get("code") == 0:
        print(f"  OK: {title[:40]}")
    else:
        print(f"  FAIL: {resp.get('msg', resp)}")
    return resp

# === Post 1: Overview + Faceji Signals ===
title1 = f"📊 面基日报 v10 | {DATE} (周三) 盘前版"
lines1 = [
    [{"tag":"text","text":"📡 13条原始信号 / 0条最终建议（全部被周频过滤）","style":["bold"]}],
    [{"tag":"text","text":"","style":[]}],
    [{"tag":"text","text":"⚡ 面基(Faceji) 5条BUY — 周频已达上限","style":["bold"]}],
    [{"tag":"text","text":"① 688343 云天励飞 评分6.2 ¥85.28","style":[]}],
    [{"tag":"text","text":"② 301269 华大九天 评分6.1 ¥116.79","style":[]}],
    [{"tag":"text","text":"③ 300124 汇川技术 评分6.1 ¥60.25","style":[]}],
    [{"tag":"text","text":"④ 600887 伊利股份 评分6.0 ¥25.28","style":[]}],
    [{"tag":"text","text":"⑤ 600036 招商银行 评分6.0 ¥37.18","style":[]}],
]
send_post(title1, lines1)

# === Post 2: SQ + TA Signals ===
title2 = f"🔩 SQ & TA 信号 | {DATE}"
lines2 = [
    [{"tag":"text","text":"🔩 SilverQuant 5条BUY (槽位建仓)","style":["bold"]}],
    [{"tag":"text","text":"① 300458 全志科技 评分6.6 ¥38.78 仓位3%","style":[]}],
    [{"tag":"text","text":"② 688343 云天励飞 评分6.2 ¥85.28 仓位3%","style":[]}],
    [{"tag":"text","text":"③ 301269 华大九天 评分6.1 ¥116.79 仓位3%","style":[]}],
    [{"tag":"text","text":"④ 300124 汇川技术 评分6.1 ¥60.25 仓位3%","style":[]}],
    [{"tag":"text","text":"⑤ 600887 伊利股份 评分6.0 ¥25.28 仓位3%","style":[]}],
    [{"tag":"text","text":"","style":[]}],
    [{"tag":"text","text":"🤖 TradingAgents 3条BUY (辩论制)","style":["bold"]}],
    [{"tag":"text","text":"① 600900 长江电力 辩论分7.2 ¥28.55 仓位12%","style":[]}],
    [{"tag":"text","text":"② 300458 全志科技 辩论分6.6 ¥38.78 仓位12%","style":[]}],
    [{"tag":"text","text":"③ 301269 华大九天 辩论分6.1 ¥116.79 仓位12%","style":[]}],
]
send_post(title2, lines2)

# === Post 3: Strategy comparison + Positions + Action items ===
title3 = f"📊 三策略持仓 & 行动指令 | {DATE}"
lines3 = [
    [{"tag":"text","text":"📊 三策略对比","style":["bold"]}],
    [{"tag":"text","text":"面基：¥917,475 (-8.25%) 2仓","style":[]}],
    [{"tag":"text","text":"SilverQuant：¥931,050 (-6.90%) 1仓","style":[]}],
    [{"tag":"text","text":"TradingAgents：¥869,606 (-13.04%) 2仓","style":[]}],
    [{"tag":"text","text":"","style":[]}],
    [{"tag":"text","text":"📋 面基持仓","style":["bold"]}],
    [{"tag":"text","text":"600900 长江电力 2600股 ¥71,314 止损¥25.23","style":[]}],
    [{"tag":"text","text":"300458 全志科技 1600股 ¥63,963 止损¥36.78","style":[]}],
    [{"tag":"text","text":"","style":[]}],
    [{"tag":"text","text":"🎯 行动指令","style":["bold"]}],
    [{"tag":"text","text":"⚠️ 面基本周交易已达上限，今日不执行","style":[]}],
    [{"tag":"text","text":"SQ/TA自动建仓不受周频限制","style":[]}],
    [{"tag":"text","text":"📰 281条新闻事件已扫描","style":[]}],
    [{"tag":"text","text":"📄 "+DOC_URL,"style":["bold"]}],
]
send_post(title3, lines3)

print("\nAll messages sent!")
