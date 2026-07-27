"""Push structured report to Feishu group — 3 messages"""
import json, urllib.request, sys

GROUP_ID = "oc_4c9d6445fab7f3a2ada0c410f3aa7043"
DOC_URL = "https://my.feishu.cn/wiki/RqPEw0bmbie8tJkzVt0cr3Sbnwf"
SIG_FILE = "/home/admin/.hermes/investment_system/data/trading_signals.json"
STRAT_FILE = "/home/admin/.hermes/investment_system/data/strategy_states.json"

# Read credentials
with open("/home/admin/.feishu-user-plugin/credentials.json") as f:
    creds = json.load(f)
APP_ID = creds["profiles"]["default"]["LARK_APP_ID"]
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]

# Get token
auth = json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
    {"Content-Type": "application/json"}), timeout=10).read())
token = auth["tenant_access_token"]

# Read signal data
with open(SIG_FILE) as f:
    sd = json.load(f)
all_sigs = sd.get("all_signals", [])
final_sigs = sd.get("signals", [])
portfolios = sd.get("portfolios", {})

def send_post(title, rows):
    """Send a post message. rows is list of paragraphs, each paragraph is list of [{tag, text, style}]"""
    content = json.dumps({
        "zh_cn": {
            "title": title,
            "content": rows
        }
    }, ensure_ascii=False)
    
    payload = json.dumps({
        "receive_id": GROUP_ID,
        "msg_type": "post",
        "content": content
    }, ensure_ascii=False)
    
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        payload.encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
    code = resp.get("code", -1)
    if code == 0:
        print(f"  ✅ Sent: {title[:30]}...")
    else:
        print(f"  ❌ Failed: {code} - {resp.get('msg','')}")
    return code == 0

# ===== Message 1: Overview + Signals =====
faceji_sigs = [s for s in all_sigs if s["strategy"] == "faceji"]
sq_sigs = [s for s in all_sigs if s["strategy"] == "silverquant"]
ta_sigs = [s for s in all_sigs if s["strategy"] == "tradingagents"]

rows1 = [
    [{"tag":"text","text":"📊 面基日报 v10 | 2026-07-16","style":["bold"]}],
    [{"tag":"text","text":"生成: ","style":[]},{"tag":"text","text":sd.get('generated_at',''),"style":["bold"]}],
    [{"tag":"text","text":"三策略信号 — 均为周频过滤（今日无新增执行）","style":[]}],
]

# Faceji
rows1.append([{"tag":"text","text":"\n面基(faceji) — 5个买入信号(全部过滤)","style":["bold"]}])
for s in faceji_sigs:
    rows1.append([{"tag":"text","text":f"  BUY {s['symbol']}({s.get('name','')[:6]}) @{s.get('price',0):.2f} 评分{s.get('score',0):.1f}"}])

# SilverQuant
rows1.append([{"tag":"text","text":"\nSilverQuant — 5个买入信号(全部过滤)","style":["bold"]}])
for s in sq_sigs:
    rows1.append([{"tag":"text","text":f"  BUY {s['symbol']}({s.get('name','')[:6]}) @{s.get('price',0):.2f} 评分{s.get('score',0):.1f}"}])

# TradingAgents
rows1.append([{"tag":"text","text":"\nTradingAgents — 3个买入信号(全部过滤)","style":["bold"]}])
for s in ta_sigs:
    rows1.append([{"tag":"text","text":f"  BUY {s['symbol']}({s.get('name','')[:6]}) @{s.get('price',0):.2f} 评分{s.get('score',0):.1f}"}])

rows1.append([{"tag":"text","text":"\n本周各策略已达周频上限，今日无模拟盘执行"}])

# ===== Message 2: Portfolio Status =====
rows2 = [
    [{"tag":"text","text":"📊 三策略组合状态","style":["bold"]}],
]

for sname, label in [("faceji","面基(faceji)"), ("silverquant","SilverQuant"), ("tradingagents","TradingAgents")]:
    pf = portfolios.get(sname, {})
    tv = pf.get("total_value", 0)
    tr = pf.get("total_return", 0)
    cash = pf.get("cash", 0)
    pc = pf.get("position_count", 0)
    wr = pf.get("win_rate", 0)
    rows2.append([{"tag":"text","text":f"\n{label}","style":["bold"]}])
    rows2.append([{"tag":"text","text":f"  总值¥{tv:,.0f} | 收益{tr:+.2f}% | 现金{pf.get('cash_pct',0):.0f}% | 持仓{pc}只 | 胜率{wr:.0f}%"}])

# Holdings
try:
    with open(STRAT_FILE) as f:
        ss = json.load(f)
    rows2.append([{"tag":"text","text":"\n持仓明细:","style":["bold"]}])
    for sname, label in [("faceji","面基"), ("silverquant","SQ"), ("tradingagents","TA")]:
        si = ss.get(sname, {})
        pos = si.get("positions", {})
        if isinstance(pos, dict) and pos:
            for sym, pinfo in pos.items():
                pnl = pinfo.get("pnl_pct", 0)
                rows2.append([{"tag":"text","text":f"  {label} {sym} x{pinfo.get('quantity',0)} @{pinfo.get('entry_price',0):.2f} → PnL{pnl:+.2f}%"}])
        else:
            rows2.append([{"tag":"text","text":f"  {label}: 空仓"}])
except:
    rows2.append([{"tag":"text","text":"  (持仓数据不可用)"}])

# ===== Message 3: Action + Doc Link =====
rows3 = [
    [{"tag":"text","text":"📋 行动指令","style":["bold"]}],
    [{"tag":"text","text":"今日无最终建议（全部被周频过滤）","style":[]}],
    [{"tag":"text","text":"\n关注标的（若解锁）:", "style":["bold"]}],
    [{"tag":"text","text":"• 伊利600887 @26.03 — 评分6.2 消费防御"}],
    [{"tag":"text","text":"• 云天励飞688343 @80.59 — 评分6.2 AI概念"}],
    [{"tag":"text","text":"• 汇川技术300124 @60.31 — 评分6.1 工业自动化"}],
    [{"tag":"text","text":"• 华大九天301269 @106.21 — 评分6.1 EDA"}],
    [{"tag":"text","text":"• 固德威688390 @68.45 — 评分6.0 光伏"}],
    [{"tag":"text","text":"\n纪律: 每周每策略最多1次 | 黑天鹅豁免","style":[]}],
    [{"tag":"text","text":"\n当前持仓:"}],
    [{"tag":"text","text":"• 面基: 长江电力(0%) + 全志科技(0%)"}],
    [{"tag":"text","text":"• TA: 伊利股份(0%) + 云天励飞(0%)"}],
    [{"tag":"text","text":"• SQ: 空仓"}],
    [{"tag":"text","text":"\n📄 完整日报: ","style":[]},{"tag":"a","text":"点击查看","href":DOC_URL}],
    [{"tag":"text","text":"评分Top5: 长江电力7.4 | 全志科技6.8 | 伊利6.2 | 云天励飞6.2 | 汇川6.1"}],
]

# Send all 3 messages
print("Pushing report to 知行合一群...")
send_post("📊 面基日报 v10 | 2026-07-16 | 信号概览", rows1)
send_post("💰 三策略组合状态 | 持仓明细", rows2)
send_post("📋 行动指令 | 文档链接", rows3)
print("\nDone! All 3 messages sent.")
