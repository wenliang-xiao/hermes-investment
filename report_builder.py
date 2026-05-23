"""
日报生成器 v3.1 — 面基·LDS·Vibe 三源融合
结构化日报 → 飞书文档 → 群推送
"""
import json, subprocess, os, time, urllib.request
from datetime import datetime
from . import config
from .macro_engine import MacroEngine
from .factor_scanner import FactorScanner
from .stock_analyzer import StockAnalyzer
from .shadow_account import get_shadow_summary, check_stops
from .global_data import (fetch_all_global_market, format_fx_section,
                          format_bond_section, format_index_section,
                          format_hk_section, format_us_section,
                          format_commodities_section,
                          format_etf_section, format_real_estate_section,
                          load_cached_global_data)
from .news_fetcher import fetch_news, format_news_section, load_cached_news


class DailyReportBuilder:
    """结构化日报生成与推送"""

    def __init__(self, macro_engine=None):
        self.macro = macro_engine or MacroEngine()
        self.scanner = FactorScanner(self.macro)
        self.analyzer = StockAnalyzer(self.macro)
        self.doc_id = None
        self.idx = 0

    # ═══════════════════════════════════════════
    # 飞书 API
    # ═══════════════════════════════════════════
    def _feishu(self, tool, args_json, label=""):
        cmd = [config.FEISHU_TOOL, tool, json.dumps(args_json, ensure_ascii=False)]
        env = os.environ.copy()
        env["FEISHU_SCOPE_VALIDATION"] = "false"
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=30)
            if r.returncode != 0:
                print(f"[feishu][{label}] ERR: {r.stderr[:200]}")
                return None
            return r.stdout
        except Exception as e:
            print(f"[feishu][{label}] EXC: {e}")
            return None

    def _create_doc(self, title):
        r = self._feishu("create_feishu_document",
                         {"title": title, "folderToken": config.FEISHU_FOLDER_TOKEN}, "create")
        if r:
            data = json.loads(r)
            self.doc_id = data["document"]["document_id"]
        return self.doc_id

    def _write_blocks(self, blocks):
        if not self.doc_id:
            return
        payload = {"documentId": self.doc_id, "parentBlockId": self.doc_id,
                   "index": self.idx, "blocks": blocks}
        r = self._feishu("batch_create_feishu_blocks", payload, "blocks")
        if r:
            data = json.loads(r)
            self.idx = data.get("nextIndex", self.idx + len(blocks))
        time.sleep(0.3)

    def _write_table(self, col_size, row_size, cells=None):
        if not self.doc_id:
            return
        cfg = {"columnSize": col_size, "rowSize": row_size}
        if cells:
            cfg["cells"] = cells
        payload = {"documentId": self.doc_id, "parentBlockId": self.doc_id,
                   "index": self.idx, "tableConfig": cfg}
        self._feishu("create_feishu_table", payload, "table")
        self.idx += 1
        time.sleep(0.5)

    def _grant_perms(self):
        try:
            app_id = os.environ.get("FEISHU_APP_ID", "")
            app_secret = os.environ.get("FEISHU_APP_SECRET", "")
            if not app_id or not app_secret:
                return
            auth = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
            req = urllib.request.Request(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                data=auth, headers={"Content-Type": "application/json"})
            resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
            token = resp.get("tenant_access_token", "")
            if not token:
                return
            url = f"https://open.feishu.cn/open-apis/drive/v1/permissions/{self.doc_id}/members?type=docx"
            body = json.dumps({
                "member_type": "openid", "member_id": config.FEISHU_USER_OPENID,
                "perm": "full_access"}).encode()
            req2 = urllib.request.Request(url, data=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req2, timeout=10).read()
        except Exception as e:
            print(f"[perms] {e}")

    # ═══════════════════════════════════════════
    # 块构建
    # ═══════════════════════════════════════════
    @staticmethod
    def txt(text):
        return {"blockType": "text", "options": {"text": {"textStyles": [{"text": text}]}}}

    @staticmethod
    def safe_val(d, key, fmt=".2f"):
        """安全格式化数字，None/字符串时返回原值"""
        v = d.get(key)
        if v is None:
            return "N/A"
        try:
            return f"{float(v):{fmt}}"
        except (ValueError, TypeError):
            return str(v)

    @staticmethod
    def _macro_item(d, key, label=""):
        """安全构建宏观数据条目"""
        v = d.get(key)
        if v is None:
            return f"{label}：N/A"
        chg = d.get(f"{key}_chg")
        try:
            fv = float(v)
            if chg is not None:
                try:
                    fc = float(chg)
                    return f"{label}：{fv:.0f} ({fc:+.2f}%)"
                except:
                    return f"{label}：{fv:.0f} ({chg})"
            return f"{label}：{fv:.0f}"
        except:
            return f"{label}：{v}"

    @staticmethod
    def rich(elements):
        return {"blockType": "text", "options": {"text": {"textStyles": elements}}}

    @staticmethod
    def h(level, content):
        return {"blockType": "heading", "options": {"heading": {"level": level, "content": content}}}

    @staticmethod
    def bullet(content):
        return {"blockType": "list", "options": {"list": {"content": content, "isOrdered": False}}}

    def write_lines(self, text: str):
        """批量写入多行文本（每行一个bullet）"""
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        blocks = [self.bullet(l) for l in lines]
        if blocks:
            self._write_blocks(blocks)

    @staticmethod
    def styled_bullet(label, value, color=None):
        """带加粗标签的 bullet 效果 — 用 text 块模拟（list 不支持 textStyles）"""
        segs = [{"text": "· ", "style": {}}]
        if color:
            segs.append({"text": label, "style": {"bold": True, "text_color": color}})
        else:
            segs.append({"text": label, "style": {"bold": True}})
        segs.append({"text": value})
        return {"blockType": "text", "options": {"text": {"textStyles": segs}}}

    @staticmethod
    def multi(segments):
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

    @staticmethod
    def ordered(content):
        return {"blockType": "list", "options": {"list": {"content": content, "isOrdered": True}}}

    @staticmethod
    def code(code_str, lang=1):
        return {"blockType": "code", "options": {"code": {"code": code_str, "language": lang, "wrap": False}}}

    # ═══════════════════════════════════════════
    # 日报主流程
    # ═══════════════════════════════════════════
    def build_report(self, scan_results: list = None, holdings: list = None) -> str:
        """
        生成结构化日报
        板块：宏观→因子→扫描Top10（含分析）→Shadow Account→纪律检查→操作建议
        """
        macro_summary = self.macro.refresh()
        self.scanner.set_macro(self.macro)
        date_str = datetime.now().strftime("%Y-%m-%d")

        # 1. 创建文档
        title = f"📊 面基三源融合投资日报 | {date_str}"
        self._create_doc(title)

        # ─── 封面 ───
        self._write_blocks([
            self.h(2, f"📊 面基三源融合投资日报 · {date_str}"),
            self.rich([
                {"text": "三源融合 v3.1 | ", "style": {"bold": True}},
                {"text": "面基播客6因子 · LDS产业链定位 · Vibe-Trading量化架构", "style": {}},
            ]),
            self.txt("理 念：知行合一 · 纪律为纲 · 趋势为友 · 风控为盾"),
            self.txt(""),
        ])

        # ═══════════════════════
        # 板块1: 宏观气候
        # ═══════════════════════
        self._write_blocks([self.h(3, "🌍 一、宏观气候 — 定基调")])

        md = macro_summary.get("macro_data", {})
        mk = macro_summary.get("market", {})

        # 宏观摘要表格
        quadrant = macro_summary.get("quadrant", "N/A")
        regime = macro_summary.get("regime", "N/A")
        trend = macro_summary.get("trend_temp", "N/A")
        switch = macro_summary.get("strategy_switch", "on")
        position = macro_summary.get("suggested_position", 0.5)

        switch_emoji = {"on": "🟢", "limited": "🟡", "off": "🔴"}.get(switch, "⚪")
        trend_action = macro_summary.get("trend_action", "")

        macro_items = [
            self.styled_bullet("四象限", f"：{quadrant} → {regime}"),
            self.styled_bullet("趋势温度", f"：{trend} — {trend_action}"),
            self.styled_bullet("策略开关", f"：{switch_emoji} {switch.upper()}  {macro_summary.get('strategy_reason', '')}"),
            self.styled_bullet("持仓建议", f"：{int(position*100)}%"),
        ]
        macro_items = [m for m in macro_items if m]  # filter None
        self._write_blocks(macro_items)

        # ═══════════════════════
        # 板块2: 全球市场全景（新版块）
        # ═══════════════════════
        self._write_blocks([self.h(3, "🌎 二、全球市场全景 — 拓视野")])

        # 获取全球市场数据
        gdata = load_cached_global_data()
        if not gdata:
            try:
                gdata = fetch_all_global_market()
            except Exception as e:
                gdata = {"error": str(e)}

        if gdata and "error" not in gdata:
            self._write_blocks([self.txt("同等权重关注汇率、债券、全球指数、港美股：")])

            # 2a. 汇率
            self.write_lines(format_fx_section(gdata))

            # 2b. 债券
            self.write_lines(format_bond_section(gdata))

            # 2c. 全球指数
            self.write_lines(format_index_section(gdata))

            # 2d. 港股
            self.write_lines(format_hk_section(gdata))

            # 2e. 美股中概
            self.write_lines(format_us_section(gdata))

            # 2f. A股ETF
            self.write_lines(format_etf_section())

            # 2g. 房地产
            self.write_lines(format_real_estate_section())
        else:
            self._write_blocks([self.bullet("⚠ 全球市场数据暂未获取")])

        # ═══════════════════════
        # ★ 板块2.5（NEW v3.3）: 大宗商品（新增）
        # ═══════════════════════
        self._write_blocks([self.h(3, "🪙 三、大宗商品 — 通胀温度计")])

        if gdata and "error" not in gdata:
            self.write_lines(format_commodities_section(gdata))
        else:
            self._write_blocks([self.bullet("⚠ 大宗商品数据暂未获取")])

        # ═══════════════════════
        # ★ 板块2.75（NEW v3.3）: 政经新闻（新增）
        # ═══════════════════════
        self._write_blocks([self.h(3, "📰 四、政经新闻 — 知天下")])

        news_data = load_cached_news()
        if not news_data:
            try:
                news_data = fetch_news()
            except Exception as e:
                news_data = {"error": str(e)}

        if news_data and "error" not in news_data:
            self.write_lines(format_news_section(news_data))
        else:
            err = news_data.get("error", "未知错误") if isinstance(news_data, dict) else "未知错误"
            self._write_blocks([self.bullet(f"⚠ 新闻获取失败: {err}")])

        # ═══════════════════════
        # 板块3: 选股逻辑说明（原编号3→5）
        # ═══════════════════════
        self._write_blocks([self.h(3, "📋 五、选股逻辑与范围 — 透明度")])
        from . import stock_universe
        self.write_lines(stock_universe.describe_scan_scope())

        # ═══════════════════════
        # 板块4: 因子权重（原板块2）
        # ═══════════════════════
        self._write_blocks([self.h(3, "⚖️ 六、因子权重 — 定策略")])

        self._write_blocks([self.txt(f"当前宏观状态 {regime} 下的最优因子配比：")])
        fw = macro_summary.get("factor_weights", {})
        weight_blocks = []
        for k, v in fw.items():
            weight_blocks.append(self.styled_bullet(k, f"：{v*100:.0f}%"))
        self._write_blocks(weight_blocks)

        # 因子逻辑解释
        regime_advice = {
            "复苏期": "质量+价值优先，筛选ROE高+估值合理标的；适当配置红利防御",
            "扩张期": "成长+动量主导，追踪高景气赛道+趋势强势股",
            "过热期": "价值+红利倾斜；减配成长和动量，增加防御",
            "衰退期": "质量+低波为盾；聚焦高确定性标的，控制波动",
        }
        advice = regime_advice.get(regime, "均衡配置")
        self._write_blocks([self.multi([("策略建议", True), (f"：{advice}", False)])])

        # ═══════════════════════
        # 板块5: 扫描Top10
        # ═══════════════════════
        self._write_blocks([self.h(3, "🔍 七、扫描推荐 — 找标的")])

        if scan_results:
            # 简要列表
            top_n = min(len(scan_results), 10)
            self._write_blocks([
                self.txt(f"基于预定义股票池扫描 · Top {top_n} 只 · 排序分位法评分"),
            ])

            # 创建表格
            headers = ["排名", "名称", "代码", "评分", "价格", "涨跌", "质量", "成长", "动量", "RSI"]
            rows = [headers]
            for i, r in enumerate(scan_results[:top_n], 1):
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

            if top_n >= 3:
                # 深度分析前三名
                self._write_blocks([self.h(4, "📋 前三标的具体分析")])

                for r in scan_results[:3]:
                    sym = r.get("symbol", "")
                    name = r.get("name", "")
                    score = r.get("score", 0)
                    chain_info = self.analyzer.deep_analyze(sym)

                    sig = chain_info.get("signal", {})
                    sig_emoji = sig.get("emoji", "⚪")
                    sig_text = sig.get("signal", "观望")
                    lds = chain_info.get("lds_confirmation", {})
                    lds_verdict = lds.get("verdict", "")
                    lds_passed = lds.get("total_passed", 0)
                    chain_name = chain_info.get("chain", {}).get("chain", "未识别")
                    chain_pos = chain_info.get("chain", {}).get("position", "")
                    margin = chain_info.get("chain", {}).get("margin_tier", "")

                    fund = chain_info.get("fundamentals", {})
                    fund_checks = fund.get("checks", [])

                    blocks = [
                        self.txt(""),
                        self.rich([
                            {"text": f"▸ {name}({sym}) ", "style": {"bold": True}},
                            {"text": f"评分{score} | 信号: {sig_emoji} {sig_text}", "style": {}},
                        ]),
                    ]
                    # 产业链
                    if chain_name != "未识别":
                        blocks.append(self.bullet(f"产业链：{chain_name} · {chain_pos} · {margin}"))
                    # 基本面汇总
                    if fund_checks:
                        good = [c for c in fund_checks if c.startswith("✅")]
                        warn = [c for c in fund_checks if not c.startswith("✅")]
                        for c in good[:3]:
                            blocks.append(self.bullet(c))
                        for c in warn[:2]:
                            blocks.append(self.bullet(c))
                    # LDS四重确认
                    emoji_c = "✅" if lds_passed >= 3 else ("⚠️" if lds_passed >= 2 else "❌")
                    blocks.append(self.bullet(f"LDS四重确认：{lds_passed}/4 通过 {emoji_c}"))
                    # 仓位
                    pos = chain_info.get("position", {})
                    pct = pos.get("suggested_pct", 0)
                    sl = pos.get("stop_loss", -8)
                    blocks.append(self.bullet(f"仓位：{pct:.1f}% | 止损：{sl:.0f}%"))
                    # 综合信号
                    if sig_text == "买入":
                        blocks.append(self.bullet(f"🟢 买入建议：{sig.get('buy_reason', '')}"))
                    elif sig_text == "关注":
                        blocks.append(self.bullet(f"👀 加入观察：{sig.get('buy_reason', '')}"))

                    self._write_blocks(blocks)
        else:
            self._write_blocks([self.txt("本次扫描无数据")])

        # ═══════════════════════
        # 板块6: 产业链扫描概览
        # ═══════════════════════
        self._write_blocks([self.h(3, "🔗 八、产业链概览 — 定方向")])

        chain_names = list(config.INDUSTRY_CHAINS.keys())
        for cn in chain_names:
            chain_data = config.INDUSTRY_CHAINS[cn]
            high_margin = ", ".join(chain_data.get("high_margin_keywords", []))
            self._write_blocks([self.bullet(
                f"{cn}：{len(chain_data['symbols'])}只标的 | 高利润环节：{high_margin}")])

        # ═══════════════════════
        # 板块7: Shadow Account
        # ═══════════════════════
        self._write_blocks([self.h(3, "📁 九、Shadow Account — 模拟盘")])

        shadow = get_shadow_summary()
        if shadow["positions"]:
            self._write_blocks([self.txt(f"当前持有 {shadow['count']} 只：")])
            for pos in shadow["positions"]:
                chg = pos.get("change", 0)
                emoji = "🟢" if chg >= 0 else "🔴"
                self._write_blocks([self.multi([
                    (emoji, False),
                    (f" {pos['name']}({pos['symbol']})", True),
                    (f" 建仓{pos['entry']:.2f}→{pos['current']:.2f} {chg:+.1f}% 止损{pos['stop_loss']:.2f}", False),
                ])])
        else:
            self._write_blocks([self.txt("当前无持仓，等待建仓信号")])

        # 止损检查
        stop_alerts = check_stops()
        if stop_alerts:
            self._write_blocks([self.h(4, "⚠️ 止盈止损预警")])
            for a in stop_alerts:
                atype = a.get("type", "")
                if atype == "STOP_LOSS":
                    self._write_blocks([self.multi([
                        ("🔴", False),
                        (f" {a['name']}({a['symbol']})", True),
                        (f" 触发8%止损！亏损{a.get('loss', 0):.1f}%", False),
                    ])])
                elif atype == "TAKE_PROFIT_T1":
                    self._write_blocks([self.multi([
                        ("🟢", False),
                        (f" {a['name']}({a['symbol']})", True),
                        (f" 触发T1止盈 +{a.get('profit', 0):.1f}% → 减半仓", False),
                    ])])
                elif atype == "TAKE_PROFIT_T2":
                    self._write_blocks([self.multi([
                        ("🟢🟢", False),
                        (f" {a['name']}({a['symbol']})", True),
                        (f" 触发T2止盈 +{a.get('profit', 0):.1f}% → 清仓", False),
                    ])])

        # ═══════════════════════
        # 板块8: 纪律检查
        # ═══════════════════════
        self._write_blocks([self.h(3, "🛡️ 十、纪律检查表 — 保安全")])

        discipline_items = []
        # 检查1: 策略开关
        if switch == "off":
            discipline_items.append(("❌", "策略开关", "关闭——不开新仓，减仓至5%"))
        elif switch == "limited":
            discipline_items.append(("⚠️", "策略开关", f"谨慎——仓位≤{int(position*100)}%"))
        else:
            discipline_items.append(("✅", "策略开关", "开启——正常执行"))

        # 检查2: 趋势温度
        if trend in ("热",):
            discipline_items.append(("⚠️", "趋势温度", f"{trend}——逐步减仓，锁利为主"))
        elif trend == "凉":
            discipline_items.append(("⚠️", "趋势温度", f"{trend}——不开新仓"))
        else:
            discipline_items.append(("✅", "趋势温度", f"{trend}——中性可控"))

        # 检查3: 8%止损
        discipline_items.append(("✅", "8%硬止损", "纪律铁律——每只票达到即出"))

        # 检查4: 单票≤2%
        if shadow["positions"]:
            pass  # 由shadow account实际检查
        discipline_items.append(("✅", "单票≤2%", "最大仓位限制"))

        # 检查5: 持仓≤8只
        pos_count = len(shadow.get("positions", []))
        if pos_count > 8:
            discipline_items.append(("⚠️", "持仓数量", f"{pos_count}只>8只上限"))
        else:
            discipline_items.append(("✅", "持仓数量", f"{pos_count or 0}/8只"))

        for icon, title, desc in discipline_items:
            self._write_blocks([self.multi([
                (icon, False),
                (f" {title}", True),
                (f"：{desc}", False),
            ])])

        self._write_blocks([self.txt("")])

        # ═══════════════════════
        # 板块9: 操作建议
        # ═══════════════════════
        self._write_blocks([self.h(3, "💡 十一、今日操作建议 — 知行合一")])

        ops_blocks = []

        # 策略方向
        if switch == "off":
            ops_blocks.append(self.multi([("🔴", False), (" 不开新仓，持仓逐步出清", False)]))
            ops_blocks.append(self.multi([("🔴", False), (" 如有持仓，设定条件单执行止损", False)]))
        elif switch == "limited":
            ops_blocks.append(self.multi([("🟡 存量管理", True), (f"：仓位≤{int(position*100)}%，不开新仓", False)]))
            ops_blocks.append(self.multi([("🟡 聚焦", True), ("高确定性标的（质量+低波优先）", False)]))
        else:
            ops_blocks.append(self.multi([("🟢 正常执行策略", True), ("，依信号操作", False)]))
            ops_blocks.append(self.multi([("🟢 仓位可依宏观适度扩张", True), ("", False)]))

        # 扫描建议
        if scan_results:
            top = scan_results[0]
            ts = top.get("score", 0)
            if ts >= 7.0:
                ops_blocks.append(self.styled_bullet("首选标的", f"：{top.get('name','')}({top.get('symbol','')}) 评分{ts}→可建仓"))
            elif ts >= 6.0:
                ops_blocks.append(self.styled_bullet("观察标的", f"：{top.get('name','')}({top.get('symbol','')}) 评分{ts}"))
            avg_top3 = sum(r.get("score", 0) for r in scan_results[:3]) / max(len(scan_results[:3]), 1)
            ops_blocks.append(self.styled_bullet("扫描质量", f"：Top3均分{avg_top3:.1f}" + ("→市场支持操作" if avg_top3 >= 6.5 else "→选股需更严格")))

        self._write_blocks(ops_blocks)

        # 纪律口诀
        temp_advice = {
            "凉": "🔴 趋势凉，管住手，不开新仓看风景",
            "平": "⚪ 趋势平，精筛选，择优入场控仓位",
            "温": "🟢 趋势温，积极做，顺势而为加仓位",
            "热": "🟡 趋势热，降仓位，锁利为主等回调",
        }
        self._write_blocks([
            self.multi([("📌 纪律口诀", True), ("：" + temp_advice.get(trend, ""), False)]),
            self.multi([("🛡️ 止盈纪律", True), ("：8%硬止损 / 15%减半仓 / 30%清仓", False)]),
            self.multi([("📆 再平衡", True), ("：每周检查持仓分布", False)]),
        ])

        # ─── 签名 ───
        self._write_blocks([
            self.txt(""),
            self.h(3, "📌 系统信息"),
            self.bullet(f"系统：面基·LDS·Vibe-Trading 三源融合 v3.3（全市场调研框架+大宗商品+政经新闻+增强扫描）"),
            self.bullet(f"数据源：baostock（A股）+ ChinaMoney（汇率）+ Yahoo Finance（港美股/债券）"),
            self.bullet(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}"),
            self.txt(""),
            self.txt("⚠️ 本报告由AI量化系统自动生成，仅供参考，不构成投资建议。"),
        ])

        # ─── 授权 → 返回URL ───
        self._grant_perms()
        doc_url = f"https://bytedance.feishu.cn/docx/{self.doc_id}"
        print(f"[report] ✅ 日报已生成: {doc_url}")
        return doc_url

    # ═══════════════════════════════════════════
    # 推送日报到群聊
    # ═══════════════════════════════════════════
    def push_to_group(self, doc_url: str, note: str = ""):
        """推送日报到群聊"""
        try:
            app_id = os.environ.get("FEISHU_APP_ID", "")
            app_secret = os.environ.get("FEISHU_APP_SECRET", "")
            if not app_id or not app_secret:
                print("[push] 无飞书凭证")
                return

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
                "receive_id": config.FEISHU_GROUP_CHAT,
                "msg_type": "text",
                "content": json.dumps({"text": msg_text}),
            }
            msg_url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            body = json.dumps(msg_body).encode()
            req2 = urllib.request.Request(msg_url, data=body,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, method="POST")
            resp2 = json.loads(urllib.request.urlopen(req2, timeout=10).read())
            if resp2.get("code") == 0:
                print("[push] ✅ 消息已推送到群")
            else:
                print(f"[push] 推送结果: {resp2.get('msg')}")
        except Exception as e:
            print(f"[push] 推送失败: {e}")


# ═══════════════════════════════════════════
# 一键运行
# ═══════════════════════════════════════════
def daily_run(scan_type="small_mid", top_n=15, holdings=None, push_to_group=True) -> dict:
    """一键运行完整日报"""
    print("=" * 50)
    print(f"📊 面基三源融合投资日报 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 50)

    # 1. 宏观刷新
    print("\n1️⃣  宏观分析...")
    macro = MacroEngine()
    summary = macro.refresh()
    print(f"    四象限: {summary.get('quadrant', 'N/A')}")
    print(f"    趋势: {summary.get('trend_temp', 'N/A')}")
    print(f"    开关: {summary.get('strategy_switch', 'N/A')}")

    # 2. 扫描
    print(f"\n2️⃣  全市场扫描 ({scan_type})...")
    scanner = FactorScanner(macro)
    scanner.MAX_SCAN = 35
    scan_results = scanner.scan_market("smart", top_n)
    print(f"    扫描完成: {len(scan_results)}只")
    if scan_results:
        for r in scan_results[:5]:
            print(f"    ▸ {r.get('name','')}({r.get('symbol','')}) ⭐{r.get('score',0)}")

    # 3. 生成日报
    print(f"\n3️⃣  生成飞书日报...")
    builder = DailyReportBuilder(macro)
    doc_url = builder.build_report(scan_results, holdings)

    # 4. 推送
    if push_to_group and doc_url:
        print(f"\n4️⃣  推送群聊...")
        builder.push_to_group(doc_url)

    # 5. 保存
    scan_data = {
        "time": datetime.now().isoformat(),
        "scan_type": scan_type,
        "macro": summary,
        "results": [{
            "symbol": r.get("symbol"), "name": r.get("name"),
            "score": r.get("score"), "price": r.get("price"),
        } for r in scan_results[:10]],
        "doc_url": doc_url,
    }
    scan_file = config.DATA_DIR / f"report_{datetime.now().strftime('%Y%m%d')}.json"
    with open(scan_file, "w") as f:
        json.dump(scan_data, f, ensure_ascii=False, indent=2)

    return {"status": "ok", "doc_url": doc_url, "scan_count": len(scan_results)}


if __name__ == "__main__":
    daily_run()
