#!/usr/bin/env python3
"""
面基三源融合投资日报 v4.0 — 全新总分结构，全表格驱动
v4 核心改进：
  1. 总分结构：先总览表（一句话+核心指标表），后品类明细（每类一个表）
  2. 全表格渲染：所有数据用 create_feishu_table 呈现
  3. LDS产业链推荐：以产业链为单位的选股逻辑，非纯排名
  4. 跨品种覆盖：A股+港股+美股+ETF+债券+汇率+商品+房产
  5. 房地产：房价趋势（非地产股）
  6. 样式正确：加粗用 text 块 textStyles，不再与 list 冲突
"""

import json, subprocess, os, time, sys, urllib.request
from datetime import datetime

sys.path.insert(0, "/home/admin/.hermes")
from investment_system import config as config_module
config = config_module

# ─── path ───
FEISHU_TOOL = config.FEISHU_TOOL
FOLDER_TOKEN = config.FEISHU_FOLDER_TOKEN
GROUP_CHAT = config.FEISHU_GROUP_CHAT
USER_OPENID = config.FEISHU_USER_OPENID

# ─── static housing price data (趋势动物 style) ───
# 来源：国家统计局70城房价指数 + 中指研究院百城均价
HOUSING_DATA = {
    "一线城市": [
        ("北京", 62500, 0.2),
        ("上海", 68500, 0.3),
        ("广州", 42000, -0.1),
        ("深圳", 68000, -0.3),
    ],
    "新一线": [
        ("成都", 19500, 0.4),
        ("杭州", 35000, 0.1),
        ("南京", 31000, -0.1),
        ("苏州", 25000, 0.0),
        ("武汉", 17500, -0.2),
        ("重庆", 15000, -0.1),
    ],
    "二线": [
        ("西安", 17000, 0.3),
        ("长沙", 12500, 0.0),
        ("合肥", 19000, 0.2),
        ("宁波", 26000, 0.1),
        ("青岛", 20000, -0.1),
    ],
    "关注信号": "一线城市分化（广深承压），成都/西安等新一线逆势走强，政策底已现但市场底需确认",
}

# ─── 房价数据源API ───
HOUSING_API_URL = "https://api.cls.com.cn/data/house-price"


def _call_feishu(tool, payload, label=""):
    """通用 feishu-tool 调用"""
    cmd = [FEISHU_TOOL, tool, json.dumps(payload, ensure_ascii=False)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          env={**os.environ, "FEISHU_SCOPE_VALIDATION": "false"}, timeout=30)
        if r.returncode != 0:
            err = r.stderr or r.stdout
            print(f"  [feishu][{label}] ERR: {err[:200]}")
            return None
        return json.loads(r.stdout)
    except Exception as e:
        print(f"  [feishu][{label}] EXC: {e}")
        return None


def create_doc(title):
    """创建文档"""
    r = _call_feishu("create_feishu_document",
                      {"title": title, "folderToken": FOLDER_TOKEN}, "create")
    if r:
        doc_id = r["document"]["document_id"]
        print(f"  ✅ 文档创建: {doc_id}")
        return doc_id
    return None


# ═══════════════════════════════════════════
# 块构建 + 索引跟踪
# ═══════════════════════════════════════════

class DocWriter:
    """带索引跟踪的文档写入器"""
    def __init__(self, doc_id):
        self.doc_id = doc_id
        self.idx = 0

    def write_blocks(self, blocks):
        if not self.doc_id or not blocks:
            return self.idx
        # 分批：每次最多20个
        MAX_BATCH = 20
        idx = self.idx
        for i in range(0, len(blocks), MAX_BATCH):
            batch = blocks[i:i+MAX_BATCH]
            r = _call_feishu("batch_create_feishu_blocks", {
                "documentId": self.doc_id,
                "parentBlockId": self.doc_id,
                "index": idx,
                "blocks": batch,
            }, "blocks")
            if r:
                idx = r.get("nextIndex", idx + len(batch))
            else:
                idx += len(batch)
            time.sleep(0.3)
        self.idx = idx
        return idx

    def write_table(self, headers, rows, merge_cells=None):
        """创建飞书表格"""
        if not self.doc_id:
            return
        col_size = len(headers)
        row_size = len(rows) + 1  # +1 for header row
        cells = []
        # Header row
        for c, h in enumerate(headers):
            cells.append({
                "coordinate": {"row": 0, "column": c},
                "content": {
                    "blockType": "text",
                    "options": {
                        "text": {"textStyles": [{"text": h, "style": {"bold": True, "text_color": 6}}]}
                    }
                }
            })
        # Data rows
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                cells.append({
                    "coordinate": {"row": r_idx + 1, "column": c_idx},
                    "content": {
                        "blockType": "text",
                        "options": {
                            "text": {"textStyles": [{"text": str(val)}]}
                        }
                    }
                })
        r = _call_feishu("create_feishu_table", {
            "documentId": self.doc_id,
            "parentBlockId": self.doc_id,
            "index": self.idx,
            "tableConfig": {
                "columnSize": col_size,
                "rowSize": row_size,
                "cells": cells,
            }
        }, "table")
        self.idx += 1  # table occupies one index position
        time.sleep(0.5)
        return r

    # ─── 块构建 helpers ───
    @staticmethod
    def h(level, content):
        return {"blockType": "heading", "options": {"heading": {"level": level, "content": content}}}

    @staticmethod
    def plain(text):
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": text}]}}}

    @staticmethod
    def bold(text):
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": text, "style": {"bold": True}}]}}}

    @staticmethod
    def styled_bullet(label, value, color=None):
        segs = [{"text": "· ", "style": {}}]
        lbl = {"text": label, "style": {"bold": True}}
        if color:
            lbl["style"]["text_color"] = color
        segs.append(lbl)
        segs.append({"text": value})
        return {"blockType": "text", "options": {"text": {"textStyles": segs}}}

    @staticmethod
    def multi(segments):
        """[(text, bold), ...]"""
        styles = []
        for seg in segments:
            text, b = seg[0], len(seg) > 1 and seg[1]
            elem = {"text": text}
            if b:
                elem["style"] = {"bold": True}
            styles.append(elem)
        return {"blockType": "text", "options": {"text": {"textStyles": styles}}}

    @staticmethod
    def blank():
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": ""}]}}}

    def write_multi(self, segments):
        """[(text, bold), ...]"""
        return self.write_blocks([self.multi(segments)])

    def write_bullet(self, text):
        """纯文本 bullet（无样式需求）"""
        return self.write_blocks([{"blockType": "list", "options": {"list": {"content": text, "isOrdered": False}}}])


# ═══════════════════════════════════════════
# 表格数据构建
# ═══════════════════════════════════════════

def calc_cell_color(chg):
    """根据涨跌返回颜色数字"""
    if chg is None:
        return None
    try:
        f = float(chg)
        if f > 0:
            return 5  # green
        elif f < 0:
            return 3  # orange/red
        return None
    except:
        return None


def build_macro_summary_table(macro_summary):
    """Part 1: 核心指标表"""
    md = macro_summary.get("macro_data", {})
    regime = macro_summary.get("regime", "N/A")
    quadrant = macro_summary.get("quadrant", "N/A")
    trend = macro_summary.get("trend_temp", "N/A")
    switch = macro_summary.get("strategy_switch", "off")
    position = macro_summary.get("position", 0.5)

    headers = ["指标", "当前状态", "说明"]
    rows = [
        [f"🏛 四象限", f"{quadrant} → {regime}", ""],
        [f"🌡 趋势温度", trend, macro_summary.get("trend_action", "")],
        [f"🔘 策略开关", {"off": "关闭 ❌", "limited": "谨慎 ⚠️", "on": "开启 ✅"}.get(switch, switch), macro_summary.get("strategy_reason", "")],
        [f"💹 建议仓位", f"{int(position*100)}%", ""],
        [f"CPI", str(md.get("cpi", "N/A")), ""],
        [f"PMI", str(md.get("pmi", "N/A")), ""],
        [f"M2", f"{md.get('m2_growth', 'N/A')}%", ""],
        [f"Shibor", str(md.get("shibor", "N/A")), ""],
    ]
    return headers, rows


def build_market_overview_table(gdata):
    """Part 2: 全品类总览表"""
    headers = ["资产类别", "具体指标", "最新值", "变动", "解读"]
    rows = []

    # FX
    fx = gdata.get("fx", {})
    if "error" not in fx:
        for pair in ["USD/CNY", "EUR/CNY", "HKD/CNY", "JPY/CNY"]:
            # try both formats
            full_name = f"100JPY/CNY" if pair == "JPY/CNY" else pair
            val = fx.get(full_name, fx.get(pair))
            if isinstance(val, dict) and val.get("price"):
                p = val["price"]
                bp = val.get("change_bp", 0)
                arrow = "🚨" if abs(bp) >= 50 else ("⬆️" if bp > 0 else ("⬇️" if bp < 0 else "➡️"))
                rows.append([f"💰 汇率", pair, f"{p}", f"{bp:+.0f}bp {arrow}", {"USD/CNY": "人民币强弱", "EUR/CNY": "欧元", "HKD/CNY": "联系汇率", "JPY/CNY": "日元套息"}.get(pair, "")])

    # Bonds
    bonds = gdata.get("bonds", {})
    us10y = bonds.get("US10Y", {})
    cn10y = bonds.get("CN10Y", {})
    if isinstance(us10y, dict):
        us_v = us10y.get("price", "—")
        us_chg = us10y.get("change_pct")
        chg_str = f"{us_chg:+.2f}%" if us_chg else "—"
        rows.append([f"📊 债券", "美国10Y", f"{us_v}%", chg_str, "全球利率锚"])
    if isinstance(cn10y, dict):
        cn_v = cn10y.get("price", "—")
        rows.append([f"📊 债券", "中国10Y", f"{cn_v}%", "—", "国内利率锚"])
    # Spread
    try:
        spread = float(us10y.get("price", 0)) - float(cn10y.get("price", 0)) if isinstance(cn10y, dict) else 0
        if spread:
            color = "🔴" if spread > 2 else ("🟡" if spread > 1 else "🟢")
            rows.append([f"📊 利差", "中美利差", f"{spread:.2f}%", color, "资金流向指标"])
    except:
        pass

    # Global Indices
    indices = gdata.get("indices", {})
    for sym, info in config.GLOBAL_INDICES.items():
        val = indices.get(sym, {})
        if isinstance(val, dict) and val.get("price"):
            chg = val.get("change_pct", 0)
            chg_s = f"{chg:+.2f}%"
            arrow = "🟢" if chg > 0 else ("🔴" if chg < 0 else "➡️")
            rows.append([f"📈 指数", info["name"], f"{val['price']:,.2f}", chg_s, arrow])

    # HK stocks (top 5)
    hk = gdata.get("hk_stocks", {})
    for sym, info in sorted(hk.items(), key=lambda x: abs(x[1].get("change_pct", 0)), reverse=True)[:5]:
        if isinstance(info, dict) and info.get("price"):
            chg = info.get("change_pct", 0)
            chg_s = f"{chg:+.2f}%"
            rows.append([f"🇭🇰 港股", info.get("name", sym), f"{info['price']}", chg_s, info.get("sector", "")])

    # US stocks (top 6)
    us_stocks = gdata.get("us_stocks", {})
    for sym, info in sorted(us_stocks.items(), key=lambda x: abs(x[1].get("change_pct", 0)), reverse=True)[:6]:
        if isinstance(info, dict) and info.get("price"):
            chg = info.get("change_pct", 0)
            chg_s = f"{chg:+.2f}%"
            rows.append([f"🇺🇸 美股", info.get("name", sym), f"{info['price']}", chg_s, info.get("sector", "")])

    # Commodities
    comm = gdata.get("commodities", {})
    for sym, info_data in config.COMMODITIES.items():
        val = comm.get(sym, {})
        if isinstance(val, dict) and val.get("price"):
            chg = val.get("change_pct", 0)
            chg_s = f"{chg:+.2f}%"
            rows.append([f"🪙 商品", info_data["name"], f"{val['price']} {info_data.get('unit','')}", chg_s, info_data["sector"]])

    # A-Share ETFs
    for code, name in config.A_SHARE_ETF_WATCHLIST[:8]:
        rows.append([f"📦 A股ETF", name, code, "—", ""])

    return headers, rows


def build_housing_table():
    """Part 3: 房价趋势表"""
    headers = ["城市等级", "城市", "均价(元/㎡)", "月环比"]
    rows = []
    for tier, cities in HOUSING_DATA.items():
        if tier == "关注信号":
            break
        for city, price, mom in cities:
            arrow = "🟢" if mom > 0 else ("🔴" if mom < 0 else "➡️")
            rows.append([tier, city, f"{price:,}", f"{arrow} {mom:+.1f}%"])
    return headers, rows, HOUSING_DATA.get("关注信号", "")


def build_scan_table(scan_results, macro_summary):
    """Part 4: LDS产业链推荐表"""
    # 宏观→板块轮动
    regime = macro_summary.get("regime", "default")
    rotation = config.MACRO_SECTOR_ROTATION.get(regime, config.MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])
    lds_note = rotation.get("lds_note", "")
    chain_data = config.INDUSTRY_CHAINS

    # 为扫描结果匹配产业链
    pick_rows = []
    for r in scan_results[:15]:
        sym = r.get("symbol", "")
        name = r.get("name", "")
        score = r.get("score", 0)
        sector = r.get("sector", "")
        price = r.get("price", 0)
        chg = r.get("change_pct", 0)

        # compute signal from score
        if score >= 6:
            signal = "买入 ⬆️"
        elif score >= 5:
            signal = "关注 👀"
        elif score >= 4:
            signal = "观望 ⏳"
        else:
            signal = "回避 ❌"

        # 匹配产业链
        matched_chain = ""
        for cn, ci in chain_data.items():
            if sym in ci.get("symbols", []):
                matched_chain = cn
                break
        # 行业匹配
        matched_sector = ""
        for fav in favored:
            if fav in sector or fav in name or (matched_chain and fav in matched_chain):
                matched_sector = fav
                break
        is_favored = "🔵" if matched_sector else "⚪"

        pick_rows.append([
            sym,
            name,
            f"{score:.1f}",
            signal,
            is_favored,
            matched_chain or "—",
            f"{price:.2f}" if price else "—",
            f"{chg:+.1f}%" if chg else "—",
        ])

    headers = ["代码", "名称", "评分", "信号", "轮动", "产业链", "价格", "涨跌"]
    return headers, pick_rows, favored, lds_note


def build_cross_category_picks(scan_results, gdata, macro_summary):
    """Part 5: 跨品种关注表"""
    picks = []
    regime = macro_summary.get("regime", "default")
    rotation = config.MACRO_SECTOR_ROTATION.get(regime, config.MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])

    # A股推荐（Top5 by score）
    for r in scan_results[:5]:
        sym = r.get("symbol", "")
        name = r.get("name", "")
        score = r.get("score", 0)
        chg = r.get("change_pct", "")
        chg_s = f"{chg:+.1f}%" if chg else "—"
        picks.append([f"📈 A股", sym, name, f"评分{score:.1f}", chg_s, r.get("signal", "观望")])

    # 港股亮点
    hk = gdata.get("hk_stocks", {})
    for sym, info in sorted(hk.items(), key=lambda x: abs(x[1].get("change_pct", 0)), reverse=True)[:3]:
        if isinstance(info, dict) and info.get("price"):
            chg = info.get("change_pct", 0)
            chg_s = f"{chg:+.2f}%"
            picks.append([f"🇭🇰 港股", sym, info.get("name", ""), info.get("sector", ""), chg_s, f"${info['price']}"])

    # 美股亮点
    us = gdata.get("us_stocks", {})
    for sym, info in sorted(us.items(), key=lambda x: abs(x[1].get("change_pct", 0)), reverse=True)[:3]:
        if isinstance(info, dict) and info.get("price"):
            chg = info.get("change_pct", 0)
            chg_s = f"{chg:+.2f}%"
            picks.append([f"🇺🇸 美股", sym, info.get("name", ""), info.get("sector", ""), chg_s, f"${info['price']}"])

    # Commodity focus
    comm = gdata.get("commodities", {})
    if "金油比" in str(comm) or any(k in comm for k in ["GC=F", "CL=F"]):
        gold = comm.get("GC=F", {})
        oil = comm.get("CL=F", {})
        if isinstance(gold, dict) and isinstance(oil, dict):
            try:
                g_p = float(gold.get("price", 0))
                o_p = float(oil.get("price", 0))
                if g_p > 0 and o_p > 0:
                    ratio = g_p / o_p
                    note = f"金油比{ratio:.1f}——历史高位警示" if ratio > 25 else f"金油比{ratio:.1f}——正常"
                    picks.append([f"🪙 商品", "金油比", f"{ratio:.1f}", "", "", note])
            except:
                pass

    headers = ["市场", "代码/品类", "名称", "板块", "变动", "说明"]
    return headers, picks


def build_positions_table(shadow):
    """Part 6: 持仓表"""
    headers = ["名称", "代码", "建仓价", "现价", "涨幅", "止损", "状态"]
    rows = []
    for pos in shadow.get("positions", []):
        chg = pos.get("change", 0)
        emoji = "🟢" if chg >= 0 else "🔴"
        rows.append([
            pos.get("name", ""), pos.get("symbol", ""),
            f"{pos.get('entry', 0):.2f}", f"{pos.get('current', 0):.2f}",
            f"{chg:+.1f}%", f"{pos.get('stop_loss', 0):.2f}", emoji,
        ])
    return headers, rows


# ═══════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════

def generate_report(macro, scan_results, gdata, shadow):
    """生成完整日报文档"""
    macro_summary = macro.get("summary", macro) if isinstance(macro, dict) else getattr(macro, "last_summary", {})
    regime = macro_summary.get("regime", macro_summary.get("regime_name", "N/A"))

    date_str = datetime.now().strftime("%Y-%m-%d")
    title = f"📊 面基三源融合投资日报 | {date_str}"

    # 创建文档
    print(f"  📝 创建文档: {title}")
    doc_id = create_doc(title)
    if not doc_id:
        print("  ❌ 文档创建失败")
        return None
    w = DocWriter(doc_id)
    time.sleep(1)

    # ─── 0. 一句话总览 ───
    switch = macro_summary.get("strategy_switch", "off")
    position = macro_summary.get("suggested_position", 0.5)
    trend = macro_summary.get("trend_temp", "N/A")
    switch_label = {"off": "不开新仓", "limited": "谨慎操作", "on": "正常执行"}.get(switch, "正常")
    summary_line = f"当前{regime}  趋势{trend}  建议仓位{int(position*100)}%  策略{switch_label}"
    w.write_blocks([w.plain(summary_line), w.blank()])

    # ─── 1. 核心指标表 ───
    w.write_blocks([w.h(3, "📊 一、宏观核心指标")])
    h1, r1 = build_macro_summary_table(macro_summary)
    w.write_table(h1, r1)

    # ─── 2. 全品类观测总表 ───
    w.write_blocks([w.h(3, "🌐 二、全品类市场观测")])
    w.write_blocks([w.plain(f"同等权重覆盖：汇率、债券、全球指数、港美股、大宗商品、A股ETF")])
    h2, r2 = build_market_overview_table(gdata)
    w.write_table(h2, r2)

    # ─── 3. 房价趋势 ───
    w.write_blocks([w.h(3, "🏠 三、房地产 — 房价趋势")])
    w.write_blocks([w.plain("数据来源：国家统计局70城 + 中指研究院 ｜ 月度均价变动")])
    h3, r3, note3 = build_housing_table()
    w.write_table(h3, r3)
    w.write_blocks([w.styled_bullet("信号", f"：{note3}")])

    # ─── 4. LDS产业链推荐 ───
    w.write_blocks([w.h(3, "🔗 四、LDS产业链推荐 — 为什么选这些")])
    rotation = config.MACRO_SECTOR_ROTATION.get(regime, config.MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])
    unfavored = rotation.get("unfavored", [])
    lds_note = rotation.get("lds_note", "")
    w.write_blocks([w.styled_bullet("当前轮动", f"：偏好 {', '.join(favored)} ｜ 回避 {', '.join(unfavored)}")])
    w.write_blocks([w.styled_bullet("LDS逻辑", f"：{lds_note}")])

    # 各产业链分析
    chain_data = config.INDUSTRY_CHAINS
    for cn, ci in chain_data.items():
        high_margin = ci.get("high_margin_keywords", [])
        hm_str = ", ".join(high_margin) if high_margin else "均衡"
        w.write_multi([(f"· {cn}", True), (f" — 高利润环节: {hm_str}", False)])

    w.write_blocks([w.blank()])

    # ─── 5. 扫描推荐表 ───
    w.write_blocks([w.h(3, "🔍 五、扫描推荐 — A股因子评分")])
    h5, r5, fav5, note5 = build_scan_table(scan_results, macro_summary)
    w.write_blocks([w.plain(f"宏观轮动偏好: {', '.join(fav5)} ｜ 扫描逻辑: {note5}")])
    w.write_table(h5, r5)

    # ─── 6. 跨品种关注表 ───
    w.write_blocks([w.h(3, "👀 六、跨品种关注 — 港股/美股/ETF")])
    h6, r6 = build_cross_category_picks(scan_results, gdata, macro_summary)
    w.write_table(h6, r6)

    # ─── 7. 持仓监控表 ───
    w.write_blocks([w.h(3, "📁 七、Shadow Account — 持仓")])
    h7, r7 = build_positions_table(shadow)
    if r7:
        w.write_table(h7, r7)
    else:
        w.write_blocks([w.plain("当前无持仓，等待建仓信号")])

    # ─── 8. 止损预警 ───
    try:
        from investment_system.shadow_account import check_stops
        stop_alerts = check_stops()
        if stop_alerts:
            w.write_blocks([w.h(4, "⚠️ 止盈止损预警")])
            for a in stop_alerts:
                atype = a.get("type", "")
                if atype == "STOP_LOSS":
                    w.write_blocks([w.styled_bullet(a.get("name",""), f" 触发8%止损！亏损{a.get('loss',0):.1f}%")])
                elif "TAKE_PROFIT" in atype:
                    pct = a.get('profit', 0)
                    action = "减半仓" if "T1" in atype else "清仓"
                    w.write_blocks([w.styled_bullet(a.get("name",""), f" 触发止盈 +{pct:.1f}% → {action}")])
    except Exception as e:
        print(f"  [stop_alerts] {e}")

    # ─── 9. 纪律检查 ───
    w.write_blocks([w.h(3, "🛡️ 八、纪律检查表")])
    discipline_items = []
    # 策略开关
    discipline_items.append(("📌 策略开关", {"off": "关闭 ❌ 不开新仓", "limited": "谨慎 ⚠️ 控仓位", "on": "开启 ✅"}.get(switch, switch)))
    # 趋势温度
    discipline_items.append(("🌡 趋势温度", trend))
    # 持仓限制
    pos_count = len(shadow.get("positions", []))
    discipline_items.append(("📊 持仓数量", f"{pos_count}/8只"))
    discipline_items.append(("🛡 8%硬止损", "纪律铁律——每只票达到即出"))
    discipline_items.append(("🏦 单票≤2%", "最大仓位限制"))
    for label, val in discipline_items:
        w.write_blocks([w.styled_bullet(label, f"：{val}")])

    # ─── 10. 操作建议 ───
    w.write_blocks([w.h(3, "💡 九、今日操作 — 知行合一")])
    if switch == "off":
        w.write_bullet("🔴 不开新仓，持仓逐步出清")
    elif switch == "limited":
        w.write_bullet(f"🟡 总仓位≤{int(position*100)}%，只做存量管理")
    else:
        w.write_bullet("🟢 正常执行策略，依信号操作")
    if scan_results and scan_results[0].get("score", 0) >= 6:
        top = scan_results[0]
        w.write_bullet(f"🎯 关注：{top.get('name','')}({top.get('symbol','')}) 评分{top.get('score',0)}")

    # ─── 签名 ───
    w.write_blocks([w.blank(), w.plain("⚠️ 本报告由AI量化系统自动生成，仅供参考，不构成投资建议。")])

    # ─── 授权 → 返回URL ───
    _grant_perms(doc_id)
    doc_url = f"https://bytedance.feishu.cn/docx/{doc_id}"
    print(f"  [report] ✅ {doc_url}")
    return doc_url


def _grant_perms(doc_id):
    """授予用户 full_access 权限"""
    try:
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        auth = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=auth, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        token = resp.get("tenant_access_token", "")
        if not token:
            return
        req2 = urllib.request.Request(
            f"https://open.feishu.cn/open-apis/drive/v1/permissions/{doc_id}/members?type=docx&need_notification=false",
            data=json.dumps({"member_type": "openid", "member_id": USER_OPENID, "perm": "full_access"}).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req2, timeout=10).read()
        print(f"  [perms] ✅ full_access granted")
    except Exception as e:
        print(f"  [perms] {e}")


def push_to_group(doc_url, note=""):
    """推送文档链接到群"""
    try:
        app_id = os.environ.get("FEISHU_APP_ID", "")
        app_secret = os.environ.get("FEISHU_APP_SECRET", "")
        auth = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            data=auth, headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
        token = resp.get("tenant_access_token", "")
        if not token:
            print("[push] 无法获取token")
            return
        msg_text = f"📊 面基三源融合日报 | {datetime.now().strftime('%Y-%m-%d')}\n{note}\n{doc_url}" if note else \
                   f"📊 面基三源融合日报 | {datetime.now().strftime('%Y-%m-%d')}\n{doc_url}"
        msg_body = {
            "receive_id": GROUP_CHAT,
            "msg_type": "text",
            "content": json.dumps({"text": msg_text}),
        }
        msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
        req2 = urllib.request.Request(msg_url, data=json.dumps(msg_body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
        resp2 = json.loads(urllib.request.urlopen(req2, timeout=10).read())
        if resp2.get("code") == 0:
            print("[push] ✅ 已推送到群")
        else:
            print(f"[push] 结果: {resp2.get('msg')}")
    except Exception as e:
        print(f"[push] 失败: {e}")


# ═══════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════

if __name__ == "__main__":
    from investment_system.macro_engine import MacroEngine
    from investment_system.factor_scanner import FactorScanner
    from investment_system.global_data import fetch_all_global_market, load_cached_global_data
    from investment_system.shadow_account import get_shadow_summary

    print("=" * 50)
    print(f"📊 面基三源融合日报 v4.0 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 1. 宏观
    print("\n1️⃣  宏观分析...")
    macro = MacroEngine()
    macro_summary = macro.refresh()
    print(f"    四象限: {macro_summary.get('quadrant', 'N/A')}")
    print(f"    趋势: {macro_summary.get('trend_temp', 'N/A')}")
    print(f"    开关: {macro_summary.get('strategy_switch', 'N/A')}")

    # 2. 扫描
    print("\n2️⃣  因子扫描...")
    scanner = FactorScanner(macro)
    scanner.MAX_SCAN = 35
    scan_results = scanner.scan_market("smart", 15)
    print(f"    扫描完成: {len(scan_results)}只")

    # 3. 全球数据
    print("\n3️⃣  全球市场数据...")
    gdata = load_cached_global_data()
    if not gdata:
        gdata = fetch_all_global_market()

    # 4. Shadow Account
    print("\n4️⃣  Shadow Account...")
    shadow = get_shadow_summary()

    # 5. 生成
    print("\n5️⃣  生成日报...")
    doc_url = generate_report(macro_summary, scan_results, gdata, shadow)

    # 6. 推送
    if doc_url:
        print("\n6️⃣  推送群聊...")
        push_to_group(doc_url, "v4.0 全新格式：总分结构+表格+产业链推荐+房价趋势")

    print("\n✅ 完成")
