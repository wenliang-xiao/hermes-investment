#!/usr/bin/env python3
"""推送面基日报 v10 盘前版摘要到知行合一群 (3条 post 消息)."""
import json, sys, urllib.request

GROUP_ID = "oc_4c9d6445fab7f3a2ada0c410f3aa7043"
CRED_PATH = "/home/admin/.feishu-user-plugin/credentials.json"
BASE_PATH = "/home/admin/.hermes/investment_system"

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

def send_post(token, title, lines):
    payload = json.dumps({
        "receive_id": GROUP_ID,
        "msg_type": "post",
        "content": json.dumps({"zh_cn": {"title": title, "content": lines}}, ensure_ascii=False)
    }, ensure_ascii=False)
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        payload.encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST"
    )
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    if resp.get("code") == 0:
        print(f"  ✅ 推送段落 '{title}' 成功")
    else:
        print(f"  ❌ 推送失败: {resp.get('code')} {resp.get('msg','')}")
    return resp.get("code") == 0

def main():
    doc_url = sys.argv[1] if len(sys.argv) > 1 else "https://my.feishu.cn/wiki/A9j0wjkCTif98vkxR5acGkICnNb"

    # 读数据
    with open(f"{BASE_PATH}/data/trading_signals.json") as f:
        ts = json.load(f)
    with open(f"{BASE_PATH}/data/strategy_states.json") as f:
        ss = json.load(f)

    all_signals = ts.get("all_signals", [])
    positions_file = ts.get("positions", {})
    
    # 提取三策略概况
    faceji = ss.get("faceji", {})
    sq = ss.get("silverquant", {})
    ta = ss.get("tradingagents", {})

    faceji_cash = faceji.get("cash", 0)
    sq_cash = sq.get("cash", 0)
    ta_cash = ta.get("cash", 0)
    
    # 计算持仓市值
    def calc_total(strat_data, pos_data):
        c = strat_data.get("cash", 0)
        ps = pos_data.get(strat_data.get("_key",""), {}) if isinstance(pos_data, dict) else {}
        for sym, p in (ps.items() if isinstance(ps, dict) else []):
            q = p.get("quantity", 0)
            pr = p.get("current_price") or p.get("entry_price", 0)
            c += q * pr
        return c

    # 持仓信息
    fj_pos = {}
    sq_pos = {}
    ta_pos = {}
    if isinstance(positions_file, dict):
        fj_pos = positions_file.get("faceji", {})
        sq_pos = positions_file.get("silverquant", {})
        ta_pos = positions_file.get("tradingagents", {})

    # 从 strategy_states 补 position 细节
    if not fj_pos and "positions" in faceji:
        fj_pos = faceji["positions"]
    if not sq_pos and "positions" in sq:
        sq_pos = sq["positions"]
    if not ta_pos and "positions" in ta:
        ta_pos = ta["positions"]

    token = get_token()
    ok = True

    # ── 消息1: 概况 + 信号表 ──
    msg1 = []
    msg1.append([{"tag":"text","text":"📊 面基日报 v10 | 2026-07-17 (盘前)","style":["bold"]}])
    msg1.append([{"tag":"text","text":""}])
    
    # 三策略对比
    fj_total = faceji_cash + sum(
        (p.get("quantity",0) * (p.get("current_price") or p.get("entry_price",0)))
        for sym,p in (fj_pos.items() if isinstance(fj_pos, dict) else []) if isinstance(p,dict)
    )
    ta_total = ta_cash + sum(
        (p.get("quantity",0) * (p.get("current_price") or p.get("entry_price",0)))
        for sym,p in (ta_pos.items() if isinstance(ta_pos, dict) else []) if isinstance(p,dict)
    )
    
    fj_pct = round((fj_total/1_000_000 - 1)*100, 2)
    sq_pct = round((sq_cash/1_000_000 - 1)*100, 2)
    ta_pct = round((ta_total/1_000_000 - 1)*100, 2)
    
    msg1.append([{"tag":"text","text":"📊 三策略模拟盘对比","style":["bold"]}])
    msg1.append([{"tag":"text","text":f"  面基: ¥{fj_total:,.0f}  ({fj_pct:+.2f}%) — {len(fj_pos)}只持仓"}])
    msg1.append([{"tag":"text","text":f"  SilverQuant: ¥{sq_cash:,.0f}  ({sq_pct:+.2f}%) — {len(sq_pos)}只持仓"}])
    msg1.append([{"tag":"text","text":f"  TradingAgents: ¥{ta_total:,.0f}  ({ta_pct:+.2f}%) — {len(ta_pos)}只持仓"}])
    msg1.append([{"tag":"text","text":""}])
    
    # 信号概况
    msg1.append([{"tag":"text","text":"🔔 昨日信号 (均被周频过滤)","style":["bold"]}])
    msg1.append([{"tag":"text","text":f"  共 {len(all_signals)} 个原始信号 → 0 个最终建议 (周频限制)"}])
    msg1.append([{"tag":"text","text":""}])
    
    # 面基信号
    fj_sigs = [s for s in all_signals if s.get("strategy")=="faceji"]
    if fj_sigs:
        msg1.append([{"tag":"text","text":"  面基原始信号:","style":["bold"]}])
        for s in fj_sigs[:5]:
            name = s.get("name", s.get("symbol","?"))
            msg1.append([{"tag":"text","text":f"    🟢 BUY {name}({s['symbol']}) 评分{s['score']} @¥{s['price']}"}])
    
    sq_sigs = [s for s in all_signals if s.get("strategy")=="silverquant"]
    if sq_sigs:
        msg1.append([{"tag":"text","text":"  SilverQuant原始信号:","style":["bold"]}])
        for s in sq_sigs[:5]:
            name = s.get("name", s.get("symbol","?"))
            msg1.append([{"tag":"text","text":f"    🟢 BUY {name}({s['symbol']}) 评分{s['score']} @¥{s['price']}"}])
    
    ta_sigs = [s for s in all_signals if s.get("strategy")=="tradingagents"]
    if ta_sigs:
        msg1.append([{"tag":"text","text":"  TradingAgents原始信号:","style":["bold"]}])
        for s in ta_sigs[:3]:
            name = s.get("name", s.get("symbol","?"))
            msg1.append([{"tag":"text","text":f"    🟢 BUY {name}({s['symbol']}) 评分{s['score']} @¥{s['price']}"}])
    
    ok &= send_post(token, "📊 面基日报 v10 | 2026-07-17 (盘前)", msg1)

    # ── 消息2: 持仓明细 ──
    msg2 = []
    msg2.append([{"tag":"text","text":"💼 持仓明细","style":["bold"]}])
    msg2.append([{"tag":"text","text":""}])
    
    # 面基持仓
    name_map = {"600900":"长江电力","300458":"全志科技","600887":"伊利股份","688343":"云天励飞"}
    msg2.append([{"tag":"text","text":"◇ 面基持仓 (现金¥782,198):","style":["bold"]}])
    if isinstance(fj_pos, dict):
        for sym,p in fj_pos.items():
            n = name_map.get(sym, sym)
            ep = p.get("entry_price","?")
            q = p.get("quantity",0)
            cp = p.get("current_price") or ep
            msg2.append([{"tag":"text","text":f"   {n}({sym}) 入¥{ep} {q}股 → 现¥{cp}"}])
    if not fj_pos:
        msg2.append([{"tag":"text","text":"   无持仓"}])
    
    msg2.append([{"tag":"text","text":""}])
    msg2.append([{"tag":"text","text":"◇ TA持仓 (现金¥682,534):","style":["bold"]}])
    if isinstance(ta_pos, dict):
        for sym,p in ta_pos.items():
            n = name_map.get(sym, sym)
            ep = p.get("entry_price","?")
            q = p.get("quantity",0)
            cp = p.get("current_price") or ep
            msg2.append([{"tag":"text","text":f"   {n}({sym}) 入¥{ep} {q}股 → 现¥{cp}"}])
    if not ta_pos:
        msg2.append([{"tag":"text","text":"   无持仓"}])
    
    msg2.append([{"tag":"text","text":""}])
    msg2.append([{"tag":"text","text":"◇ SilverQuant: 全现金 ¥931,221 (空仓)","style":["bold"]}])
    
    ok &= send_post(token, "💼 面基日报持仓明细", msg2)

    # ── 消息3: 行动指令 + 文档链接 ──
    msg3 = []
    msg3.append([{"tag":"text","text":"⚡ 行动指令","style":["bold"]}])
    msg3.append([{"tag":"text","text":""}])
    msg3.append([{"tag":"text","text":"今日面基建议信号: 0条 (全部被周频限制过滤)"}])
    msg3.append([{"tag":"text","text":"当前面基持仓无需操作，等待评分变化。"}])
    msg3.append([{"tag":"text","text":""}])
    msg3.append([{"tag":"text","text":"SQ/TA模拟盘自动运行，盘后信号将在下次运行后更新。"}])
    msg3.append([{"tag":"text","text":""}])
    msg3.append([{"tag":"text","text":"━━━━━━━━━━━━━━━━━━━━━━━━━"}])
    msg3.append([{"tag":"text","text":"📄 完整日报: "},{"tag":"a","text":"点击查看飞书文档","href":doc_url}])
    msg3.append([{"tag":"text","text":f"   {doc_url}"}])
    msg3.append([{"tag":"text","text":""}])
    msg3.append([{"tag":"text","text":"⚠️ 盘前运行 · 数据基准: 2026-07-16 缓存"}])
    
    ok &= send_post(token, "⚡ 面基日报行动指令", msg3)
    
    if ok:
        print("\n✅ 全部推送成功！")
    else:
        print("\n⚠️ 部分推送失败")

if __name__ == "__main__":
    main()
