#!/usr/bin/env python3
"""
面基三源融合投资日报 v3.2 — feishu-mcp 规范格式化版
严格遵循 feishu-mcp 的 block 类型:
  - heading: 标题（带 level）
  - text: 段落（支持 textStyles 混合样式）
  - list: 纯列表（不支持混合样式）
  - code: 代码块
  - create_feishu_table: 交互表格
"""

import json, subprocess, os, time, sys, urllib.request
from datetime import datetime
from pathlib import Path

BASE = Path("/home/admin/.hermes")
sys.path.insert(0, str(BASE))

from investment_system.macro_engine import MacroEngine
from investment_system.factor_scanner import FactorScanner
from investment_system.stock_analyzer import StockAnalyzer
from investment_system.shadow_account import get_shadow_summary, check_stops
from investment_system.global_data import (
    fetch_all_global_market, load_cached_global_data,
    format_fx_section, format_bond_section, format_index_section,
    format_hk_section, format_us_section, format_etf_section, format_real_estate_section
)
from investment_system import config

FEISHU_TOOL = config.FEISHU_TOOL
FOLDER_TOKEN = config.FEISHU_FOLDER_TOKEN
USER_OPENID = config.FEISHU_USER_OPENID
GROUP_CHAT = config.FEISHU_GROUP_CHAT
ENV = {**os.environ, "FEISHU_SCOPE_VALIDATION": "false"}

# ─────────── helpers ───────────

def feishu(tool, args, label=""):
    """调用 feishu-tool（每次刷新环境变量）"""
    cmd = [FEISHU_TOOL, tool, json.dumps(args, ensure_ascii=False)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
            env={**os.environ, "FEISHU_SCOPE_VALIDATION": "false"}, timeout=30)
        if r.returncode != 0:
            print(f"[feishu][{label}] ERR: {(r.stderr[:300] or r.stdout[:300])}")
            return None
        return r.stdout
    except Exception as e:
        print(f"[feishu][{label}] EXC: {e}")
        return None


def create_doc(title):
    """创建飞书文档并返回 doc_id"""
    r = feishu("create_feishu_document",
               {"title": title, "folderToken": FOLDER_TOKEN}, "create")
    if r:
        data = json.loads(r)
        return data["document"]["document_id"]
    return None


def write_blocks(doc_id, blocks, index=0):
    """批量写入blocks，返回nextIndex"""
    payload = {"documentId": doc_id, "parentBlockId": doc_id,
               "index": index, "blocks": blocks}
    r = feishu("batch_create_feishu_blocks", payload, "blocks")
    if r:
        data = json.loads(r)
        return data.get("nextIndex", index + len(blocks))
    return index + len(blocks)


def write_table(doc_id, col_size, row_size, cells=None, index=0):
    """创建交互表格"""
    cfg = {"columnSize": col_size, "rowSize": row_size}
    if cells:
        cfg["cells"] = cells
    payload = {"documentId": doc_id, "parentBlockId": doc_id,
               "index": index, "tableConfig": cfg}
    r = feishu("create_feishu_table", payload, "table")
    if r:
        return index + 1
    return index + 1


def grant_perms(doc_id):
    """授权用户 full_access"""
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        return
    try:
        auth = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=auth, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        token = resp.get("tenant_access_token", "")
        if not token:
            return
        url = f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx&need_notification=false"
        body = json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"}).encode()
        req2 = urllib.request.Request(url, data=body,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req2, timeout=10).read()
    except Exception as e:
        print(f"[perms] {e}")


def push_to_group(doc_url, date_str):
    """推送日报到群聊"""
    app_id = os.environ.get("FEISHU_APP_ID", "")
    app_secret = os.environ.get("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("[push] 无凭证")
        return
    try:
        auth = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=auth, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        token = resp.get("tenant_access_token", "")
        if not token:
            return
        msg_text = f"📊 面基三源融合日报 | {date_str}\n{doc_url}"
        msg_body = {
            "receive_id": GROUP_CHAT,
            "msg_type": "text",
            "content": json.dumps({"text": msg_text}),
        }
        msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        req2 = urllib.request.Request(msg_url,
            data=json.dumps(msg_body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
        resp2 = json.loads(urllib.request.urlopen(req2, timeout=10).read())
        if resp2.get("code") == 0:
            print("[push] ✅ 已推送")
        else:
            print(f"[push] {resp2.get('msg')}")
    except Exception as e:
        print(f"[push] 失败: {e}")


# ─────────── block builders (feishu-mcp 规范) ───────────

def h(level, content):
    """heading — 支持, list 不支持混合样式"""
    return {"blockType": "heading", "options": {"heading": {"level": level, "content": content}}}

def txt(text, bold=False, color=None):
    """纯文本段落"""
    style = {}
    if bold:
        style["bold"] = True
    if color is not None:
        style["text_color"] = color
    elem = {"text": text}
    if style:
        elem["style"] = style
    return {"blockType": "text", "options": {"text": {"textStyles": [elem]}}}

def multi_txt(segments):
    """多段样式文本：[(text, bold, color), ...]"""
    styles = []
    for seg in segments:
        text = seg[0]
        style = {}
        if len(seg) > 1 and seg[1]:
            style["bold"] = True
        if len(seg) > 2 and seg[2] is not None:
            style["text_color"] = seg[2]
        elem = {"text": text}
        if style:
            elem["style"] = style
        styles.append(elem)
    return {"blockType": "text", "options": {"text": {"textStyles": styles}}}

def txt_color(text, color):
    """带颜色的文本"""
    return {"blockType": "text", "options": {"text": {"textStyles": [{"text": text, "style": {"text_color": color}}]}}}

def bullet(text):
    """纯 bullets（不支持混合样式）"""
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}

def ordered(text):
    """纯 ordered list"""
    return {"blockType": "list", "options": {"list": {"content": text, "isOrdered": True}}}

def code_block(code_str, lang=49):
    """代码块"""
    return {"blockType": "code", "options": {"code": {"code": code_str, "language": lang, "wrap": False}}}

def blank():
    """空行"""
    return {"blockType": "text", "options": {"text": {"textStyles": [{"text": ""}]}}}

def tb_label(label, value, color=None):
    """标签式段落：加粗标签 + 普通值"""
    segs = [{"text": label, "style": {"bold": True}}, {"text": value}]
    if color:
        segs[0]["style"]["text_color"] = color
    return {"blockType": "text", "options": {"text": {"textStyles": segs}}}

def bullet_bold(label, value, color=None):
    """bullet 风格的带样式段落（用 · 前缀模拟 bullet，text 块支持混合样式）"""
    segs = [{"text": f"· ", "style": {}}]
    if color:
        segs.append({"text": label, "style": {"bold": True, "text_color": color}})
    else:
        segs.append({"text": label, "style": {"bold": True}})
    segs.append({"text": value})
    return {"blockType": "text", "options": {"text": {"textStyles": segs}}}


# ═══════════════════════════════════════
# 日报生成主流程
# ═══════════════════════════════════════

def build_report():
    date_str = datetime.now().strftime("%Y-%m-%d")
    print(f"📊 生成日报: {date_str}")

    # 1. 宏观
    print("1️⃣ 宏观分析...")
    macro = MacroEngine()
    summary = macro.refresh()
    q = summary.get("quadrant", "N/A")
    regime = summary.get("regime", "N/A")
    trend = summary.get("trend_temp", "平")
    switch = summary.get("strategy_switch", "on")
    position = int(summary.get("suggested_position", 0.5) * 100)
    trend_action = summary.get("trend_action", "")
    fw = summary.get("factor_weights", {})
    md = summary.get("macro_data", {})
    mk = summary.get("market", {})

    # 2. 扫描
    print("2️⃣ 因子扫描...")
    scanner = FactorScanner(macro)
    scanner.MAX_SCAN = 15
    results = scanner.scan_market("small_mid", 10)
    print(f"   扫描: {len(results)}只")

    # 3. 全市场数据（带缓存）
    print("3️⃣ 全市场数据...")
    gdata = load_cached_global_data()
    if not gdata:
        try:
            gdata = fetch_all_global_market()
        except Exception as e:
            gdata = {"error": str(e)}

    # 4. 创建文档
    print("4️⃣ 创建飞书文档...")
    title = f"📊 面基三源融合投资日报 | {date_str}"
    doc_id = create_doc(title)
    if not doc_id:
        print("❌ 创建文档失败")
        return None
    print(f"   文档ID: {doc_id}")
    time.sleep(2)  # 等待文档初始化
    idx = 0

    # ─────────── 内容写入手动控制 idx ───────────

    # === 封面 ===
    blocks = [
        h(2, f"📊 面基三源融合投资日报 · {date_str}"),
        multi_txt([
            ("面基播客6因子 · LDS产业链定位 · Vibe-Trading量化架构", False),
        ]),
        txt("知行合一 · 纪律为纲 · 趋势为友 · 风控为盾"),
        blank(),
    ]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.3)

    # === 板块1: 宏观气候 ===
    blocks = [h(3, "🌍 一、宏观气候 — 定基调")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    # 四象限 — 用 bullet_bold 实现加粗标签+普通值
    switch_emoji = {"on": "🟢", "limited": "🟡", "off": "🔴"}.get(switch, "⚪")
    blocks = [
        bullet_bold("四象限", f"：{q} → {regime}"),
        bullet_bold("趋势温度", f"：{trend} — {trend_action}"),
        bullet_bold("策略开关", f"：{switch_emoji} {switch.upper()} — {summary.get('strategy_reason', '')}"),
    ]
    # 大盘指数
    sh_val = mk.get("sh")
    if sh_val:
        try:
            sh_f = float(sh_val)
            blocks.append(bullet_bold("上证指数", f"：{sh_f:.0f}"))
        except:
            pass
    blocks.append(bullet_bold("建议仓位", f"：{position}%"))
    blocks.append(bullet("宏观数据：CPI={} PMI={} M2={}% Shibor={}".format(
        md.get("cpi", "N/A"), md.get("pmi", "N/A"),
        md.get("m2_growth", "N/A"), md.get("shibor", "N/A"))))
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.3)

    # === 板块2: 因子权重 ===
    blocks = [h(3, "⚖️ 二、因子权重 — 定策略")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    blocks = [txt(f"当前 {regime} 下的最优因子配比：")]
    for k, v in fw.items():
        blocks.append(bullet(f"{k}：{v*100:.0f}%"))
    # 板块轮动建议
    from investment_system.config import MACRO_SECTOR_ROTATION
    rot = MACRO_SECTOR_ROTATION.get(regime, MACRO_SECTOR_ROTATION["default"])
    favored = " / ".join(rot.get("favored", []))
    unfavored = " / ".join(rot.get("unfavored", []))
    blocks.append(blank())
    blocks.append(bullet_bold("偏好板块", f"：{favored}"))
    if unfavored:
        blocks.append(bullet_bold("回避板块", f"：{unfavored}"))
    blocks.append(txt(rot.get("lds_note", ""), color=1))
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.3)

    # === 板块3: 扫描推荐Top10 ===
    blocks = [h(3, "🔍 三、扫描推荐 — 找标的")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    if results:
        top_n = min(len(results), 10)
        blocks = [
            multi_txt([
                ("标的池", True, 6),
                (f"：预定义47只中小市值 · Top {top_n}", False),
            ]),
            blank(),
        ]
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.2)

        # === 表格：扫描Top10 ===
        headers = ["排名", "名称", "代码", "评分", "价格", "涨跌", "质量", "成长", "动量", "RSI"]
        rows = [headers]
        for i, r in enumerate(results[:top_n], 1):
            f = r.get("factors", {})
            tech = r.get("tech", {})
            rows.append([
                str(i),
                r.get("name", "")[:8],
                r.get("symbol", ""),
                f"{r.get('score', 0):.1f}",
                f"{r.get('price', 0):.2f}",
                f"{r.get('change_pct', 0):+.1f}%",
                f"{f.get('质量', 0):.1f}",
                f"{f.get('成长', 0):.1f}",
                f"{f.get('动量', 0):.1f}",
                f"{tech.get('rsi', 'N/A'):.0f}",
            ])

        cells = []
        for ri, row in enumerate(rows):
            for ci, cell in enumerate(row):
                is_header = ri == 0
                text_style = {"bold": True} if is_header else {}
                cells.append({
                    "coordinate": {"row": ri, "column": ci},
                    "content": {
                        "blockType": "text",
                        "options": {"text": {"textStyles": [{"text": cell, "style": text_style}]}}
                    }
                })

        idx = write_table(doc_id, len(headers), top_n + 1, cells, idx)
        time.sleep(0.5)
        idx += 1  # table occupies one index slot

        # === 前三分析（text 块混合样式）===
        blocks = [blank(), h(4, "📋 前三标的具体分析")]
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.2)

        analyzer = StockAnalyzer(macro)
        for r in results[:3]:
            sym = r.get("symbol", "")
            name = r.get("name", "")
            score = r.get("score", 0)
            info = analyzer.deep_analyze(sym)

            sig = info.get("signal", {})
            sig_emoji = sig.get("emoji", "⚪")
            sig_text = sig.get("signal", "观望")
            lds = info.get("lds_confirmation", {})
            lds_passed = lds.get("total_passed", 0)
            chain_name = info.get("chain", {}).get("chain", "未识别")
            chain_pos = info.get("chain", {}).get("position", "")
            margin = info.get("chain", {}).get("margin_tier", "")
            fund = info.get("fundamentals", {})
            fund_checks = fund.get("checks", [])
            pos_info = info.get("position", {})
            pct = pos_info.get("suggested_pct", 0)
            sl = pos_info.get("stop_loss", -8)

            blocks = [
                blank(),
                multi_txt([("▸ ", False), (name, True, 6), (f"({sym})", False),
                          (f"  ⭐{score}", False)]),
                multi_txt([("信号", True), (f"：{sig_emoji} {sig_text}", False)]),
            ]

            if chain_name != "未识别":
                blocks.append(bullet_bold("产业链", f"：{chain_name} · {chain_pos} · {margin}"))

            if fund_checks:
                good = [c for c in fund_checks if c.startswith("✅")]
                warn = [c for c in fund_checks if not c.startswith("✅")]
                for c in good[:3]:
                    blocks.append(bullet(c))
                for c in warn[:2]:
                    blocks.append(bullet(c))

            emoji_c = "✅" if lds_passed >= 3 else ("⚠️" if lds_passed >= 2 else "❌")
            blocks.append(bullet_bold("LDS确认", f"：{lds_passed}/4 {emoji_c}"))
            blocks.append(bullet_bold("仓位建议", f"：{pct:.1f}% | 止损 {sl:.0f}%"))

            if sig_text == "买入":
                blocks.append(multi_txt([("🟢 建议", True, 5), (f"：{sig.get('buy_reason', '')}", False)]))
            elif sig_text == "关注":
                blocks.append(multi_txt([("👀 观察", True, 3), (f"：{sig.get('buy_reason', '')}", False)]))

            idx = write_blocks(doc_id, blocks, idx)
            time.sleep(0.2)
    else:
        idx = write_blocks(doc_id, [txt("本次扫描无数据")], idx)
        time.sleep(0.2)

    # === 板块4: 全球市场全景 ===
    blocks = [blank(), h(3, "🌎 四、全球市场全景 — 拓视野")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    if gdata and "error" not in gdata:
        blocks = [txt("同等权重关注汇率、债券、全球指数、港美股：")]
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.2)

        sections = [
            ("🌐 汇率（中国外汇交易中心）", format_fx_section(gdata)),
            ("📊 债券市场", format_bond_section(gdata)),
            ("📈 全球指数", format_index_section(gdata)),
            ("🇭🇰 港股观测", format_hk_section(gdata)),
            ("🇺🇸 美股中概", format_us_section(gdata)),
        ]
        for sec_title, sec_text in sections:
            lines = [l.strip() for l in sec_text.split("\n") if l.strip()]
            blocks = [multi_txt([(sec_title, True, 6)])]
            for line in lines:
                # 跳过标题行（已有 colored heading）
                if line.startswith("**") or line.startswith("🌐") or line.startswith("📊") or line.startswith("📈") or line.startswith("🇭🇰") or line.startswith("🇺🇸") or line.startswith("📦") or line.startswith("🏠"):
                    continue
                # 去除markdown
                clean = line.replace("**", "").replace("*", "")
                if clean.strip():
                    blocks.append(bullet(clean))
            idx = write_blocks(doc_id, blocks, idx)
            time.sleep(0.3)

        # A股ETF + 房地产（静态指引）
        blocks = [
            multi_txt([("📦 A股ETF配置参考", True, 6)]),
        ]
        for code, name in config.A_SHARE_ETF_WATCHLIST:
            blocks.append(bullet(f"{name} ({code})"))
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.3)

        blocks = [
            multi_txt([("🏠 房地产观测", True, 6)]),
            bullet("A股：万科A / 招商蛇口 / 保利发展 / 金地集团 / 华发股份 / 滨江集团"),
            bullet("港股：长实集团 / 恒基地产 / 新鸿基地产 / 华润置地 / 中国海外发展"),
            bullet("ETF：房地产ETF (512200)"),
        ]
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.3)
    else:
        idx = write_blocks(doc_id, [bullet("⚠️ 全球市场数据暂未获取")], idx)
        time.sleep(0.2)

    # === 板块5: 产业链概览 ===
    blocks = [blank(), h(3, "🔗 五、产业链概览 — 定方向")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    from investment_system.config import INDUSTRY_CHAINS
    blocks = []
    for cn, cd in INDUSTRY_CHAINS.items():
        hm = ", ".join(cd.get("high_margin_keywords", []))
        blocks.append(multi_txt([
            (cn, True, 7),
            (f"：{len(cd['symbols'])}只标的", False),
            (f" | 高利润：{hm}", False),
        ]))
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.3)

    # === 板块6: Shadow Account ===
    blocks = [blank(), h(3, "📁 六、Shadow Account — 模拟盘")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    shadow = get_shadow_summary()
    if shadow["positions"]:
        blocks = [multi_txt([("当前持仓", True), (f"：{shadow['count']}只", False)])]
        for pos in shadow["positions"]:
            chg = pos.get("change", 0)
            emoji = "🟢" if chg >= 0 else "🔴"
            blocks.append(bullet(
                f"{emoji} {pos['name']}({pos['symbol']}) "
                f"建仓{pos['entry']:.2f}→{pos['current']:.2f} "
                f"{chg:+.1f}% 止损{pos['stop_loss']:.2f}"))
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.3)
    else:
        idx = write_blocks(doc_id, [txt("当前无持仓，等待建仓信号")], idx)
        time.sleep(0.2)

    # 止损检查
    stop_alerts = check_stops()
    if stop_alerts:
        blocks = [multi_txt([("⚠️ 止盈止损预警", True, 3)])]
        for a in stop_alerts:
            atype = a.get("type", "")
            if atype == "STOP_LOSS":
                blocks.append(multi_txt([
                    ("🔴", False), (f" {a['name']}({a['symbol']})", True),
                    (f" 触发8%止损！亏损{a.get('loss', 0):.1f}%", False),
                ]))
            elif atype == "TAKE_PROFIT_T1":
                blocks.append(multi_txt([
                    ("🟢", False), (f" {a['name']}({a['symbol']})", True),
                    (f" 触发T1止盈 +{a.get('profit', 0):.1f}% → 减半仓", False),
                ]))
            elif atype == "TAKE_PROFIT_T2":
                blocks.append(multi_txt([
                    ("🟢🟢", False), (f" {a['name']}({a['symbol']})", True),
                    (f" 触发T2止盈 +{a.get('profit', 0):.1f}% → 清仓", False),
                ]))
        idx = write_blocks(doc_id, blocks, idx)
        time.sleep(0.3)

    # === 板块7: 纪律检查 ===
    blocks = [blank(), h(3, "🛡️ 七、纪律检查表 — 保安全")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    pos_count = len(shadow.get("positions", []))
    checks = []
    if switch == "off":
        checks.append(("❌", "策略开关", "关闭——不开新仓，减仓至5%"))
    elif switch == "limited":
        checks.append(("⚠️", "策略开关", f"谨慎——仓位≤{position}%"))
    else:
        checks.append(("✅", "策略开关", "开启——正常执行"))

    if trend == "热":
        checks.append(("⚠️", "趋势温度", "热——逐步减仓，锁利为主"))
    elif trend == "凉":
        checks.append(("⚠️", "趋势温度", "凉——不开新仓"))
    else:
        checks.append(("✅", "趋势温度", f"{trend}——中性可控"))

    checks.append(("✅", "8%硬止损", "纪律铁律——每只票达到即出"))
    checks.append(("✅", "单票≤2%", "最大仓位限制"))

    if pos_count > 8:
        checks.append(("⚠️", "持仓数量", f"{pos_count}只>8只上限"))
    else:
        checks.append(("✅", "持仓数量", f"{pos_count}/8只"))

    blocks = []
    for icon, title, desc in checks:
        blocks.append(multi_txt([
            (icon, False),
            (f" {title}", True),
            (f"：{desc}", False),
        ]))
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.3)

    # === 板块8: 操作建议 ===
    blocks = [blank(), h(3, "💡 八、今日操作建议 — 知行合一")]
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.2)

    ops = []
    if switch == "off":
        ops.append(("🔴", "不开新仓", "持仓逐步出清"))
        ops.append(("🔴", "止损执行", "如有持仓设定条件单"))
    elif switch == "limited":
        ops.append(("🟡", "总仓位", f"≤{position}%，只做存量管理"))
        ops.append(("🟡", "选股方向", "聚焦高确定性标的（质量+低波优先）"))
    else:
        ops.append(("🟢", "策略执行", "正常执行，依信号操作"))
        ops.append(("🟢", "仓位管理", "可依宏观适度扩张"))

    if results:
        top = results[0]
        ts = top.get("score", 0)
        if ts >= 7.0:
            ops.append(("✅", "首选标的", f"{top.get('name','')}({top.get('symbol','')}) 评分{ts}→可建仓"))
        elif ts >= 6.0:
            ops.append(("👀", "观察标的", f"{top.get('name','')}({top.get('symbol','')}) 评分{ts}"))

        avg_top3 = sum(r.get("score", 0) for r in results[:3]) / max(len(results[:3]), 1)
        if avg_top3 >= 6.5:
            ops.append(("📈", "扫描质量", f"Top3均分{avg_top3:.1f}，市场支持操作"))
        else:
            ops.append(("📉", "扫描质量", f"Top3均分{avg_top3:.1f}，选股需更严格"))

    temp_advice = {
        "凉": "🔴 趋势凉，管住手，不开新仓看风景",
        "平": "⚪ 趋势平，精筛选，择优入场控仓位",
        "温": "🟢 趋势温，积极做，顺势而为加仓位",
        "热": "🟡 趋势热，降仓位，锁利为主等回调",
    }
    ops.append(("📌", "温度口诀", temp_advice.get(trend, "")))
    ops.append(("🛡️", "止盈纪律", "8%硬止损，15%减半仓，30%清仓"))

    blocks = []
    for icon, title, desc in ops:
        blocks.append(multi_txt([
            (icon, False),
            (f" {title}", True, 6),
            (f"：{desc}", False),
        ]))
    idx = write_blocks(doc_id, blocks, idx)
    time.sleep(0.3)

    # === 签名 ===
    blocks = [
        blank(),
        h(3, "📌 系统信息"),
        bullet(f"系统：面基·LDS·Vibe-Trading 三源融合 v3.2（全市场调研框架）"),
        bullet(f"数据源：baostock + ChinaMoney + Yahoo Finance"),
        bullet(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"),
        blank(),
        txt("⚠️ 本报告由AI量化系统自动生成，仅供参考，不构成投资建议。", color=1),
    ]
    idx = write_blocks(doc_id, blocks, idx)

    # 授权
    grant_perms(doc_id)
    doc_url = f"https://bytedance.feishu.cn/docx/{doc_id}"
    print(f"[report] ✅ {doc_url}")

    # 推送
    push_to_group(doc_url, date_str)
    return doc_url


if __name__ == "__main__":
    build_report()
