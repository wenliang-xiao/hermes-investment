#!/usr/bin/env python3
"""
推送面基日报摘要到知行合一群 (Feishu post 消息)。

数据源优先级（遵循 Dashboard 为最终依据原则）:
  1. Dashboard API (http://47.85.161.255/api/simulated + /api/signals)
  2. 本地 JSON 文件 (data/trading_signals.json + data/strategy_states.json) 做补充

用法:
  python3 push_report_to_group.py <doc_url>

示例:
  python3 push_report_to_group.py "https://bytedance.feishu.cn/docx/NgtUd6kX8o2jsAxNa60cE6Fanyf"
"""
import json, sys, urllib.request

# ── 配置 ──
GROUP_ID = "oc_4c9d6445fab7f3a2ada0c410f3aa7043"  # 知行合一群
CRED_PATH = "/home/admin/.feishu-user-plugin/credentials.json"
BASE_PATH = "/home/admin/.hermes/investment_system"
DASHBOARD_BASE = "http://47.85.161.255"

SYMBOL_NAMES = {
    "300502": "新易盛", "300308": "中际旭创", "688256": "寒武纪",
    "688008": "澜起科技", "688012": "中微公司", "688041": "海光信息",
    "688120": "华海清科", "002371": "北方华创", "603501": "韦尔股份",
    "688017": "绿的谐波", "300124": "汇川技术", "002747": "埃斯顿",
    "002472": "双环传动", "300750": "宁德时代", "601012": "隆基绿能",
    "600760": "中航沈飞", "002179": "中航光电", "603259": "药明康德",
    "300760": "迈瑞医疗", "600519": "贵州茅台", "600809": "山西汾酒",
    "000858": "五粮液", "002304": "洋河股份", "300015": "爱尔眼科",
    "300347": "泰格医药", "002475": "立讯精密", "601138": "工业富联",
    "002050": "三花智控", "300751": "迈为股份",
    "688599": "天合光能",
}

def get_token():
    with open(CRED_PATH) as f:
        creds = json.load(f)
    aid = creds["profiles"]["default"]["LARK_APP_ID"]
    sec = creds["profiles"]["default"]["LARK_APP_SECRET"]
    r = json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json.dumps({"app_id": aid, "app_secret": sec}).encode(),
        {"Content-Type": "application/json"}), timeout=10).read())
    return r["tenant_access_token"]

def fetch_dashboard(path):
    """拉取 Dashboard API 数据"""
    url = f"{DASHBOARD_BASE}{path}"
    try:
        req = urllib.request.Request(url)
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        print(f"  ⚠ Dashboard API {path} 不可用: {e}")
        return {}

def read_local_json(rel_path):
    """读取本地 JSON 文件作为补充"""
    full = f"{BASE_PATH}/{rel_path}"
    try:
        with open(full) as f:
            return json.load(f)
    except Exception:
        return {}

def build_post_content(doc_url, dashboard, signals_api):
    """构建飞书 post 富文本消息体"""
    user_signals = signals_api.get("signals", dashboard.get("user_signals", []))
    ports = dashboard.get("portfolios", {})
    sl = {"faceji": "面基", "silverquant": "SQ", "tradingagents": "TA"}

    c = []  # content lines

    # 标题
    c.append([{"tag":"text","text":"📊 面基三源融合日报 v10","style":["bold"]}])
    c.append([{"tag":"text","text":""}])

    # ── 信号表 ──
    c.append([{"tag":"text","text":"🔔 今日信号","style":["bold"]}])
    if user_signals:
        for s in user_signals:
            em = "🔴" if s.get("action")=="SELL" else "🟢"
            lbl = sl.get(s.get("strategy",""), s.get("strategy",""))
            name = s.get("name","") or SYMBOL_NAMES.get(s.get("symbol",""), s.get("symbol",""))
            pnl = f" | PnL {s['pnl_pct']:+.2f}%" if s.get("pnl_pct") is not None else ""
            sz = f" | 仓位{s['size_pct']}%" if s.get("size_pct") else ""
            line = f"{em} [{lbl}] {s['action']} {name}({s.get('symbol','?')}) @¥{s.get('price','?')} 评分{s.get('score','?')}{sz}{pnl}"
            c.append([{"tag":"text","text":line}])
            r = s.get("reason","")
            if r:
                c.append([{"tag":"text","text":f"  ⤷ {r}"}])
    else:
        c.append([{"tag":"text","text":"  今日无新信号"}])
    c.append([{"tag":"text","text":""}])

    # ── 三策略对比 ──
    c.append([{"tag":"text","text":"📊 三策略模拟盘对比","style":["bold"]}])
    for key, lbl in [("faceji","面基策略"),("silverquant","SilverQuant"),("tradingagents","TradingAgents")]:
        p = ports.get(key, {})
        tv = p.get("total_value", 0) or (p.get("cash", 0) + p.get("invested", 0))
        pct = round((tv/1_000_000 - 1)*100, 2)
        sp = "+" if pct >= 0 else ""
        np = p.get("position_count", 0)
        c.append([{"tag":"text","text":f"  {lbl}:  ¥{tv:,.0f}  ({sp}{pct}%) — {np}只持仓"}])
    c.append([{"tag":"text","text":""}])

    # ── 面基持仓明细 ──
    fj_pos = ports.get("faceji",{}).get("positions",[])
    if fj_pos:
        c.append([{"tag":"text","text":"📋 面基持仓","style":["bold"]}])
        for pos in fj_pos:
            sym = pos.get("symbol","?")
            name = SYMBOL_NAMES.get(sym, sym)
            ep = pos.get("entry_price","?")
            cp = pos.get("current_price","?")
            qty = pos.get("quantity",0)
            pnl = pos.get("pnl_pct",0)
            ps = f" ({pnl:+.2f}%)" if isinstance(pnl,(int,float)) and pnl != 0 else ""
            c.append([{"tag":"text","text":f"  {name}({sym})  入¥{ep}  现¥{cp}  {qty}股{ps}"}])
        c.append([{"tag":"text","text":""}])

    # ── 其他策略持仓概况 ──
    for key, lbl in [("silverquant","SilverQuant"),("tradingagents","TradingAgents")]:
        pl = ports.get(key,{}).get("positions",[])
        if pl:
            ps = "、".join([f"{SYMBOL_NAMES.get(p.get('symbol','?'), p.get('symbol','?'))}(¥{p.get('entry_price','?')})" for p in pl])
            c.append([{"tag":"text","text":f"  {lbl}持仓: {ps}"}])
    c.append([{"tag":"text","text":""}])

    # ── 关键交易记录 ──
    highlights = []
    for s in user_signals:
        name = s.get("name","") or SYMBOL_NAMES.get(s.get("symbol",""), "")
        if s.get("pnl_pct") is not None and s.get("pnl_pct",0) <= -5:
            highlights.append(f"  🔴 {lbl} {name} 止损 {s['pnl_pct']:.1f}%")
        elif s.get("pnl_pct") is not None and s.get("pnl_pct",0) >= 5:
            highlights.append(f"  🟢 {lbl} {name} 获利 {s['pnl_pct']:+.1f}%")
    if highlights:
        c.append([{"tag":"text","text":"📈 关键交易记录","style":["bold"]}])
        for h in highlights:
            c.append([{"tag":"text","text":h}])
        c.append([{"tag":"text","text":""}])

    # ── 文档链接 ──
    c.append([{"tag":"text","text":"━━━━━━━━━━━━━━━━━━━━━━━━"}])
    c.append([
        {"tag":"text","text":"📄 完整日报: "},
        {"tag":"a","text":"点击查看飞书文档","href":doc_url}
    ])

    return {"zh_cn":{"title":"📊 面基日报 v10","content":c}}

def push(doc_url):
    # 1. 拉取 Dashboard API（权威数据源）
    print("📡 拉取 Dashboard API...")
    dashboard = fetch_dashboard("/api/simulated")
    signals_api = fetch_dashboard("/api/signals")
    signals_count = len(signals_api.get("signals", dashboard.get("user_signals", [])))
    print(f"   Dashboard 信号数: {signals_count}")

    # 2. 补充本地数据
    signals_file = read_local_json("data/trading_signals.json")
    local_count = len(signals_file.get("signals", []))
    print(f"   本地 signals 补充: {local_count}")

    # 3. 构建 post 消息
    content = build_post_content(doc_url, dashboard, signals_api)

    # 4. 发送
    print("🔑 获取飞书 token...")
    token = get_token()

    print("📤 推送知行合一群...")
    payload = json.dumps({
        "receive_id": GROUP_ID,
        "msg_type": "post",
        "content": json.dumps(content, ensure_ascii=False)
    }, ensure_ascii=False)

    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        payload.encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    code = resp.get("code", -1)

    if code == 0:
        print("✅ 推送成功！")
    else:
        print(f"❌ 推送失败: {json.dumps(resp, ensure_ascii=False, indent=2)[:500]}")
    return code == 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 push_report_to_group.py <doc_url>")
        sys.exit(1)
    doc_url = sys.argv[1]
    ok = push(doc_url)
    sys.exit(0 if ok else 1)
