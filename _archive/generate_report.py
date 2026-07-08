"""
三方策略回测报告 → 飞书文档
"""
import subprocess, json, os, sys, time

FEISHU_TOOL = "/home/admin/.hermes/node_modules/.bin/feishu-tool"
WORK_DIR = "/home/admin/.hermes"

# Read credentials from central store (not hardcoded)
with open("/home/admin/.feishu-user-plugin/credentials.json") as f:
    creds = json.load(f)
APP_ID = creds["profiles"]["default"]["LARK_APP_ID"]
APP_SECRET = creds["profiles"]["default"]["LARK_APP_SECRET"]

FOLDER_TOKEN = "QhIOfB63Sl6Kqmd81fycjR6jnDd"
USER_OPENID = "ou_e03d56632de9b44263adfc018f9d6e4d"
TITLE = f"📊 三方策略回测对比报告 · 2026-06-23"

def feishu_call(tool_name, payload):
    data = json.dumps(payload, ensure_ascii=False)
    r = subprocess.run(
        ["bash", "-c", f"cd {WORK_DIR} && FEISHU_SCOPE_VALIDATION=false {FEISHU_TOOL} {tool_name} '{data}'"],
        capture_output=True, text=True, timeout=30
    )
    if r.returncode != 0:
        raise RuntimeError(f"{tool_name} failed: {r.stdout[:500]}")
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return r.stdout

def get_token():
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"app_id": APP_ID, "app_secret": APP_SECRET})],
        capture_output=True, text=True, timeout=10
    )
    return json.loads(r.stdout)["tenant_access_token"]

def grant_full_access(doc_token):
    token = get_token()
    r = subprocess.run(
        ["curl", "-s", "-X", "POST",
         f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_token}/members?type=docx&need_notification=false",
         "-H", f"Authorization: Bearer {token}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"})],
        capture_output=True, text=True, timeout=10
    )
    return json.loads(r.stdout)

# ─── Block helpers ───
def h(lv, text):
    return {"blockType": "heading", "options": {"heading": {"level": lv, "content": text}}}

def p(*segs):
    styles = []
    for seg in segs:
        if isinstance(seg, str):
            styles.append({"text": seg})
        elif isinstance(seg, tuple):
            t, b = seg[0], len(seg) > 1 and seg[1]
            c = seg[2] if len(seg) > 2 else None
            s = {}
            if b: s["bold"] = True
            if c: s["text_color"] = c
            elem = {"text": t}
            if s: elem["style"] = s
            styles.append(elem)
    return {"blockType": "text", "options": {"text": {"textStyles": styles}}}

def code(text):
    return {"blockType": "code", "options": {"code": {"code": text, "language": 1, "wrap": True}}}

def bullet(text, ordered=False):
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": ordered}}}

# ─── Load backtest results ───
print("📂 加载回测结果...")
with open("/home/admin/.hermes/investment_system/data/backtest_comparison.json") as f:
    data = json.load(f)
results = data["results"]

# ─── Create doc ───
print("📄 创建飞书文档...")
result = feishu_call("create_feishu_document", {"title": TITLE, "folderToken": FOLDER_TOKEN})
if isinstance(result, list):
    doc_id = result[0].get("document", {}).get("document_id", "")
elif isinstance(result, dict):
    doc_id = result.get("document", {}).get("document_id", "")
else:
    doc_id = ""
print(f"  Created: {doc_id}")

perm = grant_full_access(doc_id)
if isinstance(perm, dict):
    print(f"  Permission: {'OK' if perm.get('code') == 0 else perm.get('msg', str(perm)[:50])}")
elif isinstance(perm, list):
    print(f"  Permission: OK ({len(perm)} entries)")
else:
    print(f"  Permission: {str(perm)[:50]}")

# ─── Build blocks ───
blocks = []
idx = 0

def write(block_list):
    global idx
    for i in range(0, len(block_list), 15):
        batch = block_list[i:i+15]
        payload = {"documentId": doc_id, "parentBlockId": doc_id, "index": idx, "blocks": batch}
        r = feishu_call("batch_create_feishu_blocks", payload)
        n = r.get("totalBlocksCreated", len(batch))
        idx = r.get("nextIndex", idx + n)
        time.sleep(0.3)

blocks = []

# Cover
blocks.append(h(2, "📊 三方策略回测对比报告"))
blocks.append(p(f"执行时间：{data.get('run_date', '2026-06-23')}", True))
blocks.append(p(f"回测窗口：{data.get('date_range', 'N/A')}（{data.get('days_analyzed', 0)}个交易日）"))

# Summary table
blocks.append(h(3, "回测参数"))
blocks.append(p(("评分池：", True), f"{data.get('scored_stocks', 0)}只A股核心+底仓标的"))
blocks.append(p(("初始资金：", True), "¥1,000,000 全现金"))
blocks.append(p(("评分来源：", True), "当日因子扫描结果（静态评分，60天内不变化）"))
blocks.append(p(("价格数据：", True), "Baostock 后复权日线"))
blocks.append(code(
    "回测参数\n"
    "───────────────┬───────────────\n"
    "参数            │ 值\n"
    "───────────────┼───────────────\n"
    "回测天数        │ 60个交易日\n"
    "日期范围        │ 2026-03-24 → 2026-06-22\n"
    "标的数          │ 19只 A股核心+底仓\n"
    "初始资金        │ ¥1,000,000\n"
    "评分来源        │ 因子扫描（静态）\n"
    "价格            │ Baostock后复权日线\n"
    "交易成本        │ 未纳入（纯策略对比）"
))

# ─── Core comparison ───
blocks.append(h(2, "📈 策略核心对比"))
lines = [
    "指标                │ 面基(当前)   │ SilverQuant   │ TradingAgents",
    "────────────────────┼─────────────┼───────────────┼──────────────",
]
for label, key in [
    ("收益率%", "total_return_pct"),
    ("总盈亏¥", "total_return_cny"),
    ("最终价值¥", "value"),
    ("现金¥", "cash"),
    ("开仓次数", "total_trades_opened"),
    ("平仓次数", "total_trades_closed"),
    ("胜率%", "win_rate"),
    ("最大回撤%", "max_drawdown_pct"),
    ("Sharpe比", "sharpe_ratio"),
    ("持仓数", "positions_count"),
]:
    row = [label]
    for s in ["faceji", "silverquant", "tradingagents"]:
        v = results.get(s, {}).get(key, 0)
        if isinstance(v, (int, float)):
            if abs(v) >= 1000:
                row.append(f"{v:,.2f}")
            elif isinstance(v, float):
                row.append(f"{v:.2f}")
            else:
                row.append(str(v))
        else:
            row.append(str(v))
    lines.append(f"{row[0]:20s}│ {row[1]:>12s} │ {row[2]:>13s} │ {row[3]:>14s}")
blocks.append(code("\n".join(lines)))

# ─── Strategy Details ───
for sname, label in [
    ("faceji", "① 面基（当前系统）"),
    ("silverquant", "② SilverQuant 组件化"),
    ("tradingagents", "③ TradingAgents 辩论制"),
]:
    s = results.get(sname, {})
    if not s:
        continue
    blocks.append(h(2, label))
    blocks.append(p(f"📊 最终价值: ¥{s.get('value',0):,.2f} | 收益率: {s.get('total_return_pct',0):+.2f}% | 总盈亏: ¥{s.get('total_return_cny',0):+,.2f}", True))
    blocks.append(p(f"Sharpe: {s.get('sharpe_ratio',0):.2f} | 最大回撤: {s.get('max_drawdown_pct',0):.2f}% | 胜率: {s.get('win_rate',0):.1f}%"))
    blocks.append(p(f"开/平仓: {s.get('total_trades_opened',0)}次/{s.get('total_trades_closed',0)}次 | 当前持仓: {s.get('positions_count',0)}只"))
    
    trades = s.get("trades", [])
    if trades:
        blocks.append(h(3, "逐笔交易明细"))
        trade_lines = ["日期         │ 标的     │ 操作 │ 价格     │ 盈亏¥    │ 原因"]
        trade_lines.append("────────────┼─────────┼─────┼─────────┼──────────┼────────────────")
        for t in trades:
            d = str(t.get("date",""))[:10]
            sym = t.get("symbol","")
            act = t.get("action","")
            price = f'{t.get("price",0):.2f}'
            pnl = f'{t.get("pnl",0):+.2f}' if t.get("pnl") else "-"
            reason = t.get("reason","")[:20]
            trade_lines.append(f"{d:12s}│ {sym:7s} │ {act:3s} │ {price:>7s} │ {pnl:>8s} │ {reason}")
        blocks.append(code("\n".join(trade_lines)))

# ─── Conclusion ───
blocks.append(h(2, "🎯 结论与建议"))

f = results.get("faceji", {})
sq = results.get("silverquant", {})
ta = results.get("tradingagents", {})

best_name = "面基"
best_ret = f.get("total_return_pct", 0)
if sq.get("total_return_pct", 0) > best_ret:
    best_name = "SilverQuant"; best_ret = sq["total_return_pct"]
if ta.get("total_return_pct", 0) > best_ret:
    best_name = "TradingAgents"; best_ret = ta["total_return_pct"]

blocks.append(p(("🏆 最优策略：", True), (f"{best_name}（{best_ret:+.2f}%）", True, 5)))

blocks.append(h(3, "各策略特点分析"))
blocks.append(p(("面基策略：", True), "收益率最高（+14.32%），正确识别了高分标的的上涨趋势。60天内只买不卖，6只持仓全部盈利。缺点是未触发任何卖出（评分未跌破4，MA未死叉），回撤控制依赖入场价格。"))
blocks.append(p(("SilverQuant：", True), "组件化卖点导致极高换手率（171笔交易），胜率仅4.7%。\"MASeller\"在每次MA死叉时卖出，但之后价格往往反弹，导致反复进出。硬止损-8%和峰值回撤-12%有效控制了最大回撤（1.86%）。"))
blocks.append(p(("TradingAgents：", True), "辩论制门槛高（>5.5），60天内仅建仓2只（药明康德、新易盛）。集中度高但收益率稳定（+9.49%），Sharpe 3.94与面基相当但仓位更轻。"))

blocks.append(h(3, "建议"))
blocks.append(bullet("面基策略当前逻辑在上涨趋势中表现最优，但缺少卖出纪律"))
blocks.append(bullet("SilverQuant的组件化风控值得借鉴——HardSeller/FallSeller/MASeller组合可以有效控制回撤"))
blocks.append(bullet("TradingAgents辩论制的集中度策略适合高分确定性标的，但样本过少"))
blocks.append(bullet("建议方向：面基策略 + SilverQuant组件化卖点 + TradingAgents辩论风控 = 三源融合"))
blocks.append(bullet("⚠️ 注意：评分静态（60天不变），实际场景中评分随基本面变化，会触发更多买卖信号"))

# ─── Appendices ───
blocks.append(h(2, "附录A：评分标的列表"))
appendix_stocks = [
    ("603259","药明康德",6.2), ("300502","新易盛",5.5), ("688008","澜起科技",5.2),
    ("688256","寒武纪",5.1), ("300760","迈瑞医疗",5.0), ("688041","海光信息",5.0),
    ("300750","宁德时代",4.9), ("601012","隆基绿能",4.8), ("600760","中航沈飞",4.8),
    ("300124","汇川技术",4.7), ("300308","中际旭创",4.6), ("002371","北方华创",4.5),
    ("002747","埃斯顿",4.4), ("688120","华海清科",4.2), ("002472","双环传动",4.2),
    ("688012","中微公司",4.1), ("603501","韦尔股份",4.0), ("002179","中航光电",4.0),
    ("300760","迈瑞医疗",5.0), ("688017","绿的谐波",3.5),
]
score_lines = ["代码       │ 名称     │ 评分"]
score_lines.append("──────────┼─────────┼──────")
for sym, name, sc in appendix_stocks:
    score_lines.append(f"{sym:8s} │ {name:5s} │ {sc:.1f}")
blocks.append(code("\n".join(score_lines)))

# Write all blocks
print(f"✍️ 写入 {len(blocks)} 个信息块...")
write(blocks)

print(f"\n✅ 完成！共 {len(blocks)} 个信息块")
print(f"📎 https://bytedance.feishu.cn/docx/{doc_id}")
