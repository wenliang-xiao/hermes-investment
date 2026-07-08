"""Create and populate the daily report document, then push to group."""
import json, urllib.request, os, sys

# ─── Config ───
DOC_ID = "VLw6dEfdUoCDsOxcwKtczFafnUb"
DOC_URL = "https://my.feishu.cn/wiki/EgklwhGEYiE6L6kAg6AcZI73n8d"
GROUP_ID = "oc_4c9d6445fab7f3a2ada0c410f3aa7043"

# ─── Auth ───
with open(os.path.expanduser("~/.feishu-user-plugin/credentials.json")) as f:
    creds = json.load(f)
APP_ID = creds["profiles"]["default"]["LARK_APP_ID"]
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]

auth = json.loads(urllib.request.urlopen(urllib.request.Request(
    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
    json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET}).encode(),
    {"Content-Type": "application/json"}), timeout=10).read())
TOKEN = auth["tenant_access_token"]

API_BASE = "https://open.feishu.cn/open-apis"

def api_call(method, path, body=None):
    url = f"{API_BASE}{path}"
    data = json.dumps(body, ensure_ascii=False).encode() if body else None
    req = urllib.request.Request(url, data=data,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
        method=method)
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return resp
    except urllib.error.HTTPError as e:
        return {"error": str(e), "body": e.read().decode()[:500]}

def add_block(block_type, content, extra=None):
    """Build a block dict."""
    block = {"block_type": block_type}
    if block_type == 2:  # text
        block["text"] = {"elements": [{"tag": "text", "text": content}]}
    elif block_type == 3:  # heading1
        block["heading1"] = {"elements": [{"tag": "text", "text": content}]}
    elif block_type == 4:  # heading2
        block["heading2"] = {"elements": [{"tag": "text", "text": content}]}
    elif block_type == 15:  # bullet
        block["bullet"] = {"elements": [{"tag": "text", "text": content}]}
    elif block_type == 17:  # divider
        block["divider"] = {}
    elif block_type == 22:  # callout
        block["callout"] = {
            "background_color": extra.get("bg", 1) if extra else 1,
            "elements": [{"tag": "text", "text": content}]
        }
    return block

def batch_create_blocks(blocks, parent_id=None, index=0):
    """Create blocks in the document."""
    pid = parent_id or DOC_ID
    body = {
        "documentId": DOC_ID,
        "parentBlockId": pid,
        "index": index,
        "blocks": blocks
    }
    return api_call("POST", f"/docx/v1/documents/{DOC_ID}/blocks/{pid}/children/batch_create", body)

# ─── Build Report ───
blocks = []
idx = 0

def add(block_type, text="", extra=None):
    global idx
    blocks.append(add_block(block_type, text, extra))
    idx += 1
    if len(blocks) >= 20:
        flush()

def flush():
    global blocks, idx
    if not blocks:
        return
    result = batch_create_blocks(blocks, index=idx - len(blocks))
    if result.get("data", {}).get("nextIndex"):
        idx = result["data"]["nextIndex"]
    elif result.get("code") != 0:
        print(f"  WARN: batch create result: {result.get('msg', result)}", file=sys.stderr)
    blocks = []

# Title
add(3, "📊 面基日报 v10 | 2026-07-08")
add(2, "生成时间: 2026-07-08 盘后版 | 数据基准: 2026-07-08 08:37")
add(17)  # divider

# Section 1: Signal Overview
add(3, "一、今日信号总览")
add(2, "今日盘后扫描，原始信号13条，冲突解决后5条，周频过滤后0条——今日无新执行信号。")
add(2, "三策略各新建1个仓位，均为今日买入建仓，无平仓操作。")
add(17)

# Section 2: Portfolio
add(3, "二、三策略持仓明细")

# Faceji
add(4, "面基策略 — 现金: ¥846,161 | 总投入: ¥71,314 | 总收益: -¥82,525 (-8.25%)")
add(15, "📦 长江电力(600900) — ¥27.43 × 2600股 = ¥71,314 | 盈亏: 0% | 止损: ¥25.23")
add(2, "风格: 面基(评分+趋势+Kelly+SQ风控) | 历史交易: 21笔")

# SilverQuant
add(4, "SilverQuant — 现金: ¥903,265 | 总投入: ¥26,829 | 总收益: -¥69,906 (-6.99%)")
add(15, "📦 全志科技(300458) — ¥38.33 × 700股 = ¥26,829 | 盈亏: 0% | 止损: ¥35.26")
add(2, "风格: 组件化(评分建仓+4层风控) | 历史交易: 67笔")

# TradingAgents
add(4, "TradingAgents — 现金: ¥766,750 | 总投入: ¥102,856 | 总收益: -¥130,394 (-13.04%)")
add(15, "📦 伊利股份(600887) — ¥25.09 × 4100股 = ¥102,856 | 盈亏: 0% | 止损: ¥23.08")
add(2, "风格: 辩论制(Kelly动态+技术融合) | 历史交易: 7笔")
add(17)

# Section 3: News
add(3, "三、新闻异动")
add(2, "AKShare 扫描到 281 条新闻事件，覆盖 57 只标的。")
add(2, "新闻管线已扫描完成，评分偏移数据为空（盘后时段新闻量较少）。")
add(17)

# Section 4: Actions
add(3, "四、行动指令")
add(15, "面基信号: 无新信号 — 今日无需要你在富途执行的交易")
add(15, "SQ模拟盘: 持仓全志科技(300458)，等待收盘价更新")
add(15, "TA模拟盘: 持仓伊利股份(600887)，等待收盘价更新")
add(17)

# Summary
add(3, "五、盘后总结")
add(2, "今日为2026-07-08盘后运行，三策略均于盘前建仓完成。")
add(2, "由于Phase 1扫描超时（600s），信号数据取自08:37快照。")
add(2, "三策略各持1只标的，总仓位适中。")
add(2, f"完整日报: {DOC_URL}")

flush()

print(f"✅ Document content written")
print(f"   URL: {DOC_URL}")
print(f"   Doc ID: {DOC_ID}")