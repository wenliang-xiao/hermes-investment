"""
面基日报 v10 — 信号驱动版
Phase 1: 运行 run_trading 获取信号
Phase 2: 构建报告内容
Phase 3: 飞书文档发布
"""
import sys, os, json, subprocess, time, urllib.request
from datetime import datetime, date

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))
sys.path.insert(0, _PROJECT_DIR)

import functools
print = functools.partial(print, flush=True)

# ── Feishu 配置 ──
FEISHU_TOOL = "/home/admin/.hermes/node_modules/.bin/feishu-tool"
WORK_DIR = "/home/admin/.hermes"
FOLDER_TOKEN = "QhIOfB63Sl6Kqmd81fycjR6jnDd"
USER_OPENID = "ou_e03d56632de9b44263adfc018f9d6e4d"
APP_ID = "cli_aa8445bca6f81bb7"

with open("/home/admin/.feishu-user-plugin/credentials.json") as f:
    creds = json.load(f)
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]

def feishu_call(tool, payload):
    d = json.dumps(payload, ensure_ascii=False)
    r = subprocess.run(
        ["bash", "-c", f"cd {WORK_DIR} && FEISHU_SCOPE_VALIDATION=false {FEISHU_TOOL} {tool} '{d}'"],
        capture_output=True, text=True, timeout=30
    )
    try: return json.loads(r.stdout)
    except: return {}

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
        f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx&need_notification=false",
        "-H", f"Authorization: Bearer {token}"
        "-H", "Content-Type: application/json",
        "-d", json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"})],
        capture_output=True, timeout=10)

# ── Block helpers ──
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
def cd(text, lang=1):
    return {"blockType": "code", "options": {"code": {"code": text, "language": lang, "wrap": True}}}
def bl(text):
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}

def write_blocks(doc_id, blocks):
    idx = 0
    for i in range(0, len(blocks), 12):
        batch = blocks[i:i+12]
        r = feishu_call("batch_create_feishu_blocks",
            {"documentId": doc_id, "parentBlockId": doc_id, "index": idx, "blocks": batch})
        n = r.get("totalBlocksCreated", len(batch))
        idx = r.get("nextIndex", idx + n)
        time.sleep(0.3)
    return True

# ── 主流程 ──
def main():
    today_str = date.today().strftime("%Y-%m-%d")
    print(f"{'='*50}")
    print(f"📊 面基日报 v10 · {today_str}")
    print(f"{'='*50}")

    # ═══ Phase 1: 执行扫描+信号生成 ═══
    print("\n📡 Phase 1: 运行扫描器 + TradingEngine...")
    sig_path = os.path.join(_PROJECT_DIR, "data", "trading_signals.json")

    scan_ok = False
    try:
        r = subprocess.run(
            f"cd {_PROJECT_DIR} && PYTHONUNBUFFERED=1 python3 -u scripts/run_trading.py > /tmp/report_v10_scan.log 2>&1",
            capture_output=True, text=True, timeout=600, shell=True
        )
        scan_ok = r.returncode == 0
        if not scan_ok:
            print(f"  ⚠️ 扫描exit code={r.returncode}，尝试使用已有信号文件")
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ 扫描超时，尝试使用已有信号文件")

    if not os.path.exists(sig_path):
        print(f"  ❌ 无信号文件，无法继续")
        return

    with open(sig_path) as f:
        signals_data = json.load(f)

    signals = signals_data.get("signals", [])
    positions = signals_data.get("positions", {})
    print(f"  ✅ {len(signals)}个信号 · {sum(len(v) for v in positions.values())}个持仓")

    # ═══ Phase 2: 构建文档内容 ═══
    print("\n📝 Phase 2: 构建报告...")
    title = f"📊 面基日报 v10 · {today_str}"
    doc_result = feishu_call("create_feishu_document", {"title": title, "folderToken": FOLDER_TOKEN})
    if isinstance(doc_result, list):
        doc_id = doc_result[0].get("document", {}).get("document_id", "")
    else:
        doc_id = doc_result.get("document", {}).get("document_id", "")

    if not doc_id:
        print("  ❌ 文档创建失败")
        return
    print(f"  ✅ 文档: {doc_id}")
    grant(doc_id)

    blocks = []

    # ── 封面 ──
    blocks.append(h(2, f"📊 面基日报 v10 · {today_str}"))
    blocks.append(p(f"三源融合：面基 × SilverQuant × TradingAgents · {datetime.now().strftime('%H:%M')}"))

    # ── ① 今日信号 ──
    blocks.append(h(2, "① 今日信号"))
    if signals:
        lines = ["优先级  策略            动作  标的            价格      理由"]
        lines.append("────── ────────────── ──── ────────────── ──────── ───────────────────")
        for s in signals:
            pct = {"HIGH": "🔴", "MED": "🟡", "LOW": "⚪"}.get(s.get("priority", "MED"), "⚪")
            sym = s.get("symbol", "")
            nm = s.get("name", "")
            pr = s.get("price", 0)
            rc = s.get("reason", "")
            lines.append(f"{pct}      {s['strategy']:<14s} {s['action']:<4s} {sym}({nm:<6s}) {pr:>8.2f}  {rc}")
        blocks.append(cd("\n".join(lines)))
        best = signals[0]
        blocks.append(p(
            ("⭐ 今日建议：", True),
            (f"{best['strategy']} {best['action']} {best['symbol']}({best.get('name','')}) @{best['price']:.2f}", True, 5)
        ))
        blocks.append(p("手动执行后告知我记录交易日志"))
    else:
        blocks.append(p("📋 今日无交易信号", True, 3))
        blocks.append(p("所有标的评分均低于阈值，三策略无信号"))

    # ── ② 三策略对比 ──
    blocks.append(h(2, "② 三策略对比"))
    for sname, label in [("faceji", "面基"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
        s_sigs = [s for s in signals if s["strategy"] == sname]
        s_pos = positions.get(sname, {})
        buys = sum(1 for s in s_sigs if s["action"] == "BUY")
        sells = sum(1 for s in s_sigs if s["action"] == "SELL")
        pnl_strs = []
        for sym, pdata in list(s_pos.items())[:3]:
            pnl = pdata.get("pnl_pct", 0)
            pnl_strs.append(f"{sym} {pnl:+.2f}%")
        blocks.append(p(
            (f"• {label}", True),
                        (f" 信号{buys+sells}个(B{buys}/S{sells}) 持仓{len(s_pos)}只", False),
            (f" {' | '.join(pnl_strs)}" if pnl_strs else ""),
        ))

    # ── ③ 组合状态 ──
    blocks.append(h(2, "③ 组合状态"))
    blocks.append(p(("模拟盘：", True), "¥1,000,000 全现金 · 0持仓（双门关闭未自动执行）"))
    blocks.append(p(("待执行信号：", True), f"{len(signals)}个"))

    # ── ④ 行动指令 ──
    blocks.append(h(2, "④ 行动指令"))
    if signals:
        best = signals[0]
        blocks.append(p((f"🎯 {best['strategy']} {best['action']} {best['symbol']} @{best['price']:.2f}", True, 5)))
        blocks.append(bl("确认执行后告知我"))
    else:
        blocks.append(bl("今日无建议操作"))
    blocks.append(bl("每周最多1次 · 黑天鹅豁免"))

    # ── 附录: 评分Top10 ──
    blocks.append(h(2, "附录A: 评分Top10"))
    scan_path = os.path.join(_PROJECT_DIR, "data", "scan_snapshot_latest.json")
    if os.path.exists(scan_path):
        with open(scan_path) as f:
            scan = json.load(f)
        sc_rs = scan.get("results", [])
        sc_rs.sort(key=lambda x: x.get("score", 0), reverse=True)
        top_lines = ["代码      名称          评分  ma20_dev  ma60_dev"]
        top_lines.append("──────── ────────── ─────  ───────  ───────")
        for r in sc_rs[:10]:
            sym = r.get("symbol", "")
            nm = r.get("name", "")[:10]
            sc = r.get("score", 0)
            tech = r.get("tech", {}) or {}
            m20 = tech.get("ma20_dev", "")
            m60 = tech.get("ma60_dev", "")
            top_lines.append(f"{sym:8s} {nm:10s} {sc:.1f}   {str(m20):>7s}  {str(m60):>7s}")
        blocks.append(cd("\n".join(top_lines)))
    blocks.append(h(2, "附录B: 交易纪律"))
    blocks.append(bl("每周每策略最多交易1次 · 合计最多3次"))
    blocks.append(bl("黑天鹅豁免 · 信号由agent生成→你手动执行→反馈记录"))
    blocks.append(bl("执行记录: python3 scripts/manual_trade.py"))

    # ═══ Phase 3: 发布 ═══
    print(f"\n📤 Phase 3: 发布文档 ({len(blocks)}块)...")
    try:
        write_blocks(doc_id, blocks)
        print(f"\n{'='*50}")
        print(f"✅ 面基日报 v10 完成!")
        print(f"📎 https://bytedance.feishu.cn/docx/{doc_id}")
        print(f"{'='*50}")
    except Exception as e:
        print(f"\n❌ 发布失败: {e}")
        # 清理残篇
        token = get_token()
        if token:
            req = urllib.request.Request(
                f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}?type=docx",
                headers={"Authorization": f"Bearer {token}"}, method="DELETE")
            urllib.request.urlopen(req, timeout=10)
            print(f"  🗑️ 已删除残篇 {doc_id}")

if __name__ == "__main__":
    main()
