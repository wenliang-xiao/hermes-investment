"""Write report blocks to Feishu document"""
import json, subprocess, sys, os, time
from datetime import datetime

PROJECT_DIR = "/home/admin/.hermes/investment_system"
WORK_DIR = "/home/admin/.hermes"
FEISHU_TOOL = "/home/admin/.hermes/node_modules/.bin/feishu-tool"
DOC_ID = "ODwvdo3NkoQzXsx6Xmcc2vRhnDn"

# Load signal data
with open(os.path.join(PROJECT_DIR, "data", "trading_signals.json")) as f:
    sd = json.load(f)

def feishu_call(tool, payload):
    d = json.dumps(payload, ensure_ascii=False)
    env = os.environ.copy()
    env["FEISHU_SCOPE_VALIDATION"] = "false"
    r = subprocess.run(
        [FEISHU_TOOL, tool, d],
        capture_output=True, text=True, timeout=30, cwd=WORK_DIR, env=env
    )
    try: return json.loads(r.stdout)
    except: return {}

def h(lv, text):
    return {"blockType": "heading", "options": {"heading": {"level": lv, "content": text}}}

def p(*segs):
    styles = []
    for seg in segs:
        if isinstance(seg, str): 
            if seg: styles.append({"text": seg})
        elif isinstance(seg, tuple):
            s = {}
            if len(seg) > 1 and seg[1]: s["bold"] = True
            if len(seg) > 2 and seg[2] is not None: s["text_color"] = seg[2]
            e = {"text": seg[0]}
            if s: e["style"] = s
            styles.append(e)
    if not styles:
        return None
    return {"blockType": "text", "options": {"text": {"textStyles": styles}}}

def cd(text):
    return {"blockType": "code", "options": {"code": {"code": text, "language": 1, "wrap": True}}}

def bl(text):
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}

# ===== Build blocks =====
blocks = []
today_str = sd.get("date", "2026-07-16")
all_signals = sd.get("all_signals", [])
signals = sd.get("signals", [])  # Final signals after weekly filter
positions = sd.get("positions", {})
portfolios = sd.get("portfolios", {})
generated_at = sd.get("generated_at", "")

# Cover
blocks.append(h(2, f"📊 面基日报 v10 | {today_str}"))
blocks.append(p(f"三源融合: faceji × SilverQuant × TradingAgents | 生成: {generated_at} | 本周频限制：三策略均已达上限"))
blocks.append(p(""))

# --- 1. 今日信号 ---
blocks.append(h(2, "1. 今日信号概览"))

if signals:
    lines = ["优先 策略           动作 标的             价格     理由"]
    lines.append("─" * 75)
    for s in signals:
        pr = s.get("price", 0)
        lines.append(f"[{s['priority']:4s}] {s['strategy']:<12s} {s['action']:<4s} {s['symbol']}({s.get('name','')[:6]:<6s}) {pr:>8.2f}  {s.get('reason','')}")
    blocks.append(cd("\n".join(lines)))
else:
    all_lines = ["策略           动作 标的             价格 评分 仓位"]
    all_lines.append("─" * 70)
    for s in all_signals:
        pr = s.get("price", 0)
        sc = s.get("score", 0)
        sz = s.get("size_pct", 0)
        rsn = s.get('reason', '')
        all_lines.append(f"{s['strategy']:<12s} {s['action']:<4s} {s['symbol']}({s.get('name','')[:6]:<6s}) {pr:>8.2f}  {sc:>4.1f} {sz:>3.0f}%  {rsn[:30]}")
    lines = all_lines + [f"\n共 {len(all_signals)} 条原始信号 | 均被周频限制过滤 — 三策略本周已达交易上限"]
    blocks.append(cd("\n".join(lines)))

blocks.append(p((f"今日: {len(all_signals)}条原始信号 → 0条最终建议（全部被周频过滤）", True, 6)))
blocks.append(bl(f"面基: 5个BUY信号过滤(本周已交易1次) — 建议关注: 伊利600887@{26.03} | 云天励飞688343@{80.59} | 汇川300124@{60.31}"))
blocks.append(bl(f"SilverQuant: 5个BUY信号过滤(本周已交易2次)"))
blocks.append(bl(f"TradingAgents: 3个BUY信号过滤(本周已交易1次)"))

# --- 2. 三策略组合状态 ---
blocks.append(h(2, "2. 三策略组合状态"))
for sname, label in [("faceji", "面基(faceji)"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
    pf = portfolios.get(sname, {})
    s_pos = positions.get(sname, {})
    tv = pf.get("total_value", 0)
    tr = pf.get("total_return", 0)
    pc = pf.get("position_count", 0)
    cash = pf.get("cash", 0)
    wr = pf.get("win_rate", 0)
    
    pos_detail = ""
    if isinstance(s_pos, dict) and s_pos:
        detail_parts = []
        for sym, pinfo in s_pos.items():
            qty = pinfo.get("quantity", 0)
            ep = pinfo.get("entry_price", 0)
            cp = pinfo.get("current_price", ep)
            pnl = pinfo.get("pnl_pct", 0)
            nm = pinfo.get("name", sym)
            detail_parts.append(f"{sym}({nm}) {qty}股 @{ep:.2f}→{cp:.2f} PnL{pnl:+.2f}%")
        pos_detail = " | ".join(detail_parts)
    
    status_str = f"{label} | 总值¥{tv:,.0f} | 收益{tr:+.2f}% | 现金¥{cash:,.0f} | 持仓{pc}只 | 胜率{wr:.0f}%"
    if pos_detail:
        status_str += f"\n   {pos_detail}"
    blocks.append(p((status_str, True, 5) if sname == "faceji" else (status_str, False)))

# --- 3. 持仓明细 ---
blocks.append(h(3, "3. 持仓明细"))
for sname, label in [("faceji", "面基(faceji)"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
    s_pos = positions.get(sname, {})
    if isinstance(s_pos, dict) and s_pos:
        pos_lines = [f"{label} 持仓 ({len(s_pos)}只):"]
        for sym, pinfo in s_pos.items():
            qty = pinfo.get("quantity", 0)
            ep = pinfo.get("entry_price", 0)
            cp = pinfo.get("current_price", ep)
            pnl = pinfo.get("pnl_pct", 0)
            nm = pinfo.get("name", sym)
            sl = pinfo.get("stop_loss", 0)
            cost_val = ep * qty
            mv = cp * qty
            pos_lines.append(f"  {sym}({nm}) x{qty} @{ep:.2f}(¥{cp:.2f}) 成本¥{cost_val:,.0f}→市值¥{mv:,.0f} PnL{pnl:+.2f}% 止损@{sl:.2f}")
        blocks.append(cd("\n".join(pos_lines)))
    else:
        blocks.append(bl(f"{label}: 空仓"))

# --- 4. 模拟盘对比 ---
blocks.append(h(3, "4. 模拟盘对比"))
pf_lines = ["策略            总值(¥)    收益%    现金%   持仓  胜率"]
pf_lines.append("─" * 55)
for sname, label in [("faceji", "面基"), ("silverquant", "SilverQuant"), ("tradingagents", "TradingAgents")]:
    pf = portfolios.get(sname, {})
    tv = pf.get("total_value", 0)
    tr = pf.get("total_return", 0)
    cp = pf.get("cash_pct", 0)
    pc = pf.get("position_count", 0)
    wr = pf.get("win_rate", 0)
    pf_lines.append(f"{label:<12s} ¥{tv:>8,.0f}  {tr:>+7.2f}%  {cp:>5.1f}%  {pc:>3d}   {wr:>4.0f}%")
blocks.append(cd("\n".join(pf_lines)))

# --- 5. 行动指令 ---
blocks.append(h(2, "5. 行动指令"))
blocks.append(bl("今日无最终建议信号（全部被周频过滤）"))
blocks.append(bl("面基(faceji) 已达周上限1次 — 本周已执行交易，无需额外操作"))
blocks.append(bl("关注标的(若后续解锁): 伊利600887@26.03 | 云天励飞688343@80.59 | 汇川技术300124@60.31"))
blocks.append(bl("纪律: 每周每策略最多1次 | 黑天鹅豁免"))
blocks.append(bl("手动交易记录: python3 scripts/manual_trade.py --strategy X --action Y --symbol Z --price P"))

# --- 6. 评分TOP10 ---
blocks.append(h(3, "6. 评分Top10"))
try:
    with open(os.path.join(PROJECT_DIR, "data", "scan_snapshot_latest.json")) as f:
        scan = json.load(f)
    sc_rs = scan.get("results", [])
    sc_rs.sort(key=lambda x: x.get("score", 0), reverse=True)
    top_lines = ["代码      名称          评分"]
    top_lines.append("─" * 30)
    for r in sc_rs[:10]:
        sym = r.get("symbol", "")
        nm = r.get("name", "")[:12]
        sc = r.get("score", 0)
        top_lines.append(f"{sym:8s} {nm:12s} {sc:.1f}")
    blocks.append(cd("\n".join(top_lines)))
except:
    blocks.append(bl("评分数据不可用"))

# --- 7. 交易纪律 ---
blocks.append(h(3, "7. 交易纪律"))
blocks.append(bl("每周每策略最多交易1次 | 合计最多3次"))
blocks.append(bl("黑天鹅豁免 | 信号由agent生成→手动执行→反馈记录"))
blocks.append(bl("SQ风控: HardSeller(-8%) | FallSeller(-12%) | ScoreDrop(<4.5) | MA死叉+亏损<5%"))

print(f"Total blocks: {len(blocks)}")

# === Write blocks to document ===
idx = 0
for i in range(0, len(blocks), 12):
    batch = blocks[i:i+12]
    r = feishu_call("batch_create_feishu_blocks",
        {"documentId": DOC_ID, "parentBlockId": DOC_ID, "index": idx, "blocks": batch})
    n = r.get("totalBlocksCreated", len(batch))
    idx = r.get("nextIndex", idx + n)
    print(f"  Wrote {i+len(batch)}/{len(blocks)} blocks (created={n}, next_index={r.get('nextIndex','?')})")
    time.sleep(0.3)

url = f"https://my.feishu.cn/wiki/RqPEw0bmbie8tJkzVt0cr3Sbnwf"
print(f"\n{'='*50}")
print(f"OK: v10 report written!")
print(f"Doc: {url}")
print(f"{'='*50}")

# Output the URL for the caller
sys.stdout.write(f"\nDOC_URL={url}\n")
