#!/usr/bin/env python3
"""
面基三源融合投资日报 v6.1 — 全量信息·引用体系
==============================================
v6.1 修复：恢复 v5.3 所有动态分析板块 + 静态框架引用总纲

结构（v5.3全量 + 引用总纲）：
  零、LDS双门状态（宏观门×趋势门）→ 操作方向
  一、全球市场全景（股债汇商+VIX+国运线+CPI情景）
  二、ETF全景（A股35只+跨境+LDS参考组合）
  三、房价趋势
  四、产业链12链分析（中观四层次×Perez×翻倍逻辑）
  五、多因子新票发现（A股/美股/港股/ETF/中小市值）
  六、政经要闻与产业链影响
  七、重点票追踪
  八、调仓建议
  九、每日面基概念

引用规则：
  - 静态原则/公式 → 链接到 [知识体系总纲](KNOWLEDGE_DOC_URL) §对应章节
  - 日报只写今日数据 + 分析结论
  - 结论末尾标注引用来源
"""
import sys, os, json, time, urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from investment_system import config as cfg
from investment_system.data.data_layer import (
    get_stock_daily, get_financial_report, get_macro_data,
    get_market_overview, get_sector_hotmap, get_concept_hotmap
)
from investment_system.analysis.factor_scanner import FactorScanner
from investment_system.domain.stock_universe import LDS_SECTORS, MACRO_TO_SECTORS, INDEX_DATA
from investment_system.analysis.macro_engine import MacroEngine

from investment_system.data.yf_data_layer import (
    get_global_market_snapshot, score_stock, get_current_price,
    scan_us_stocks, scan_hk_stocks, scan_us_etfs,
    get_factor_data
)
from investment_system.data.global_universe import (
    ALL_US_STOCKS, US_CHAINS, US_ETFS, HK_WATCHLIST_V2,
    COMMODITIES_V2, FX_V2, BONDS_V2
)

# 飞书写入频率控制
_WRITE_COUNT = [0]

KNOWLEDGE_DOC_URL = "https://bytedance.feishu.cn/docx/RmtEduEtfo05hSxW02wc8ZhfnVc"
KNOWLEDGE_DOC_ID = "RmtEduEtfo05hSxW02wc8ZhfnVc"
FOLDER_TOKEN = cfg.FEISHU_FOLDER_TOKEN
GROUP_CHAT = cfg.FEISHU_GROUP_CHAT
USER_OPENID = cfg.FEISHU_USER_OPENID
SAN_YUAN_NAME = "面基·LDS·Vibe-Trading 三源融合"

# ═══════════════════════════════════
# 飞书文档写入层
# ═══════════════════════════════════
class FeishuWriter:
    def __init__(self):
        self._token = None; self._token_time = 0
    def _get_token(self):
        if self._token and time.time() - self._token_time < 3600: return self._token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        data = json.dumps({"app_id": os.environ["FEISHU_APP_ID"],
                           "app_secret": os.environ["FEISHU_APP_SECRET"]}).encode()
        req = urllib.request.Request(url, data=data, headers={"Content-Type":"application/json"})
        self._token = json.loads(urllib.request.urlopen(req).read())["tenant_access_token"]
        self._token_time = time.time(); return self._token
    def _api(self, path, method="GET", data=None):
        token = self._get_token()
        url = f"https://open.feishu.cn/open-apis{path}"
        headers = {"Content-Type":"application/json","Authorization":f"Bearer {token}"}
        body = json.dumps(data).encode() if data else None
        last_err = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, data=body, headers=headers, method=method)
                resp = json.loads(urllib.request.urlopen(req).read())
                if resp.get("code") == 0: return resp
                last_err = f"code={resp.get('code')}, msg={resp.get('msg','')}"
                time.sleep(1)
            except Exception as e: 
                last_err = str(e)
                time.sleep(0.5)
        print(f"  [API FAIL] {method} {path}: {last_err}", file=sys.stderr)
        return None
    def create_doc(self, title):
        resp = self._api("/docx/v1/documents", "POST", {"title": title, "folder_token": FOLDER_TOKEN})
        if resp:
            doc_id = resp["data"]["document"]["document_id"]
            self._api(f"/drive/v1/permissions/{doc_id}/members?type=docx", "POST",
                {"member_type":"openid","member_id":USER_OPENID,"perm":"full_access"})
            return doc_id
        return None
    def write(self, doc_id, blocks, parent_id=None):
        pid = parent_id or doc_id
        children = []
        for b in blocks:
            bt, txt = b[0], b[1] if len(b) > 1 else ""
            if bt == "h2":
                children.append({"block_type":4, "heading2": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "h3":
                children.append({"block_type":5, "heading3": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "text":
                children.append({"block_type":2, "text": {"elements":[{"text_run":{"content":txt}}],"style":{}}})
            elif bt == "bold":
                children.append({"block_type":2, "text": {"elements":[{"text_run":{"content":txt,"text_element_style":{"bold":True}}}],"style":{}}})
            elif bt == "bullet":
                children.append({"block_type":12, "bullet": {"elements":[{"text_run":{"content":txt,"text_element_style":{}}}],"style":{}}})
            elif bt == "divider":
                children.append({"block_type":22, "divider": {}})
            elif bt == "quote":
                children.append({"block_type":15, "quote": {"elements":[{"text_run":{"content":txt}}],"style":{}}})
        if not children:
            return True
        # 限流保护: 每次写入后等待0.5s，避免触发飞书频率限制
        result = self._api(f"/docx/v1/documents/{doc_id}/blocks/{pid}/children", "POST", {"children": children})
        time.sleep(0.5)
        _WRITE_COUNT[0] += 1
        if _WRITE_COUNT[0] % 20 == 0:
            time.sleep(2)  # 每20次写入额外休息2秒
        return result
    def ref(self, section):
        return f"📋 详见 [知识总纲]({KNOWLEDGE_DOC_URL}) §{section}"

# ═══════════════════════════════════
# 工具函数
# ═══════════════════════════════════
def fmt_pct(v, dec=1):
    if v is None: return "?"
    pct = v * 100 if abs(v) < 10 else v
    return f"{pct:.{dec}f}%"

def fmt_usd(v):
    if v is None: return "?"
    if abs(v) >= 1e12: return f"${v/1e12:.2f}T"
    if abs(v) >= 1e9: return f"${v/1e9:.1f}B"
    return f"${v:.2f}"

def push_to_group(url, summary):
    """推送草稿到飞书群"""
    try:
        msg = f"📊 {SAN_YUAN_NAME}\n{summary}\n📄 [查看完整日报]({url})"
        from investment_system import config as c2
        token = FeishuWriter()._get_token()
        cid = GROUP_CHAT
        data = json.dumps({"receive_id": cid, "msg_type": "interactive", "content": json.dumps({
            "config": {"wide_screen_mode": True},
            "elements": [{"tag": "markdown", "content": msg}]
        })}).encode()
        req = urllib.request.Request("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
            data=data, headers={"Content-Type":"application/json","Authorization":f"Bearer {token}"})
        urllib.request.urlopen(req)
    except: pass

# ═══════════════════════════════════
# 板块 0: LDS双门状态 + CPI + 国运线
# ═══════════════════════════════════
def build_gate_section(w, doc_id, macro):
    w.write(doc_id, [("divider", ""), ("h2", "零、🚪 LDS 双门状态")])
    dual = macro.get("dual_gate", {})
    action = dual.get("action", "观望")
    macro_ok = dual.get("macro_ok", False)
    trend_ok = dual.get("trend_ok", False)
    
    w.write(doc_id, [
        ("bold", f"宏观门: {'🟢 开' if macro_ok else '🔴 关'} ｜ 趋势门: {'🟢 开' if trend_ok else '🔴 关'} ｜ 操作: {action}"),
        ("text", f"宏观象限: {macro.get('regime','?')} ｜ CPI: {macro.get('macro_data',{}).get('cpi','?')}% ｜ 策略开关: {macro.get('strategy_switch','?')}"),
        ("text", f"趋势温度: {macro.get('trend_temp','?')} ｜ 20日均线偏离: {macro.get('trend_deviation_20','?')}%"),
        ("text", w.ref("一、面基四象限")),
    ])
    
    # CPI情景
    w.write(doc_id, [("h3", "CPI 情景推演")])
    cpi = macro.get("macro_data", {}).get("cpi")
    if cpi is not None:
        if cpi < 1:
            w.write(doc_id, [("quote", f"CPI={cpi}% → 通缩压力 → LDS策略限制敞口 → 消费/防御为主")])
        elif cpi < 2:
            w.write(doc_id, [("quote", f"CPI={cpi}% → 正常区间 → LDS策略正常执行 → 均衡配置")])
        elif cpi < 3:
            w.write(doc_id, [("quote", f"CPI={cpi}% → 高景气 → 周期/商品占优")])
        else:
            w.write(doc_id, [("quote", f"CPI={cpi}% → 过热 → LDS减仓防御")])
    
    # 债券/黄金主动信号
    w.write(doc_id, [("h3", "💡 债券·黄金主动信号")])
    try:
        md = macro.get("macro_data", {})
        cpi_val = md.get("cpi")
        us10y_val = None
        cn10y_val = None
        try:
            from investment_system.data.yf_data_layer import get_current_price
            us10y_raw = get_current_price("^TNX")
            if isinstance(us10y_raw, (int, float)) and 0 < us10y_raw < 15:
                us10y_val = round(float(us10y_raw), 2)
            cn10y_val = 2.80
        except Exception:
            pass

        if us10y_val and cpi_val is not None:
            real_rate = round(us10y_val - cpi_val, 2)
            if real_rate > 2.0:
                gold_signal = f"🔴 实际利率{real_rate:.1f}% 偏高 → 黄金承压，关注回调买入机会"
                tlt_signal = f"🟢 实际利率高位 → TLT/长债有配置价值（等待利率见顶）"
            elif real_rate > 0.5:
                gold_signal = f"🟡 实际利率{real_rate:.1f}% 中性 → 黄金中性，央行购金支撑底部"
                tlt_signal = f"🟡 债券中性 → 维持底仓即可"
            else:
                gold_signal = f"🟢 实际利率{real_rate:.1f}% 偏低/负值 → 黄金强驱动，增配信号"
                tlt_signal = f"🟢 低实际利率 → 长债/黄金均受益，象限4核心配置"
            w.write(doc_id, [("bullet", f"美债实际利率 = 名义{us10y_val:.2f}% - CPI{cpi_val:.1f}% = {real_rate:.2f}%")])
            w.write(doc_id, [("bullet", gold_signal)])
            w.write(doc_id, [("bullet", tlt_signal)])

        if us10y_val and cn10y_val:
            spread = round(cn10y_val - us10y_val, 2)
            if spread < -150:
                spread_signal = f"🔴 中美利差{spread*100:.0f}bp → 极度倒挂，人民币贬值压力大，外资流出A股"
            elif spread < -50:
                spread_signal = f"🟡 中美利差{spread*100:.0f}bp → 倒挂，关注汇率压力"
            else:
                spread_signal = f"🟢 中美利差{spread*100:.0f}bp → 正常，A股承压减轻"
            w.write(doc_id, [("bullet", f"中美利差 = CN10Y{cn10y_val:.2f}% - US10Y{us10y_val:.2f}% = {spread:.2f}%")])
            w.write(doc_id, [("bullet", spread_signal)])
    except Exception as e:
        w.write(doc_id, [("bullet", f"⚠️ 利率信号获取失败: {str(e)[:40]}")])

    # 国运线
    w.write(doc_id, [("h3", "国运线（上证20年趋势线）")])
    guoyun = macro.get("guoyun_line", {})
    deviation = guoyun.get("deviation")
    if deviation is not None:
        level = "超跌安全区" if deviation < -10 else "价值区间" if deviation < -5 else "中性" if deviation < 5 else "过热"
        emoji = "🟢" if deviation < -5 else "🟡" if deviation < 5 else "🔴"
        w.write(doc_id, [
            ("text", f"当前偏离: {deviation:+.1f}% → {emoji} {level}"),
            ("text", f"国运线点位: {guoyun.get('line_price','?')} ｜ 当前上证: {guoyun.get('current_price','?')}"),
            ("quote", f"穿越牛熊30年。当前在国运线{'下方' if deviation and deviation < 0 else '上方'}→ {'估值较低' if deviation and deviation < 0 else '估值合理'}"),
            ("text", w.ref("十六、全球经济格局")),
        ])

# ═══════════════════════════════════
# 板块 1: 全球市场全景
# ═══════════════════════════════════
def build_market_snapshot(w, doc_id):
    """一、全球市场全景 — 统一使用 full_asset_scanner 数据源（有价格校验）"""
    from investment_system.output.full_asset_scanner import (
        scan_commodities as _fas_comm, scan_fx as _fas_fx, scan_bonds as _fas_bonds
    )
    fas_comm = _fas_comm()
    fas_fx = _fas_fx()
    fas_bonds = _fas_bonds()

    w.write(doc_id, [("divider", ""), ("h2", "八、🌐 全球市场全景")])

    w.write(doc_id, [("h3", "核心指数")])
    try:
        snap = get_global_market_snapshot()
        indices = snap.get("indices", {})
        for idx_name in ["标普500", "纳斯达克", "恒生", "日经"]:
            d = indices.get(idx_name)
            if d:
                price = d.get("price") if isinstance(d, dict) else d
                chg = d.get("change_pct") if isinstance(d, dict) else None
                price_str = f"{price:,.0f}" if price else "⚠️"
                chg_str = f" ({chg:+.2f}%)" if chg is not None else ""
                w.write(doc_id, [("bullet", f"{idx_name}: {price_str}{chg_str}")])
        bonds_snap = snap.get("bonds", {})
        if bonds_snap:
            b_parts = [f"{n}: {v:.2f}%" for n, v in bonds_snap.items() if v is not None]
            if b_parts:
                w.write(doc_id, [("bullet", " | ".join(b_parts))])
    except Exception as e:
        w.write(doc_id, [("bullet", f"⚠️ 市场快照失败: {str(e)[:40]}")])



    # ── VIX 恐慌指数 + 北向资金（情绪信号）──
    w.write(doc_id, [("h3", "市场情绪信号")])
    try:
        snap = get_global_market_snapshot()
        vix = snap.get("sentiment", {}).get("VIX")
        if vix is not None:
            if vix > 30:
                vix_signal = f"🔴 {vix:.1f} 极度恐慌"
            elif vix > 20:
                vix_signal = f"🟡 {vix:.1f} 市场不安"
            else:
                vix_signal = f"🟢 {vix:.1f} 市场平稳"
            w.write(doc_id, [("bullet", f"VIX恐慌指数: {vix_signal}")])
        else:
            w.write(doc_id, [("bullet", "VIX: ⚠️ 数据不可用")])
    except Exception:
        w.write(doc_id, [("bullet", "VIX: ⚠️ 获取失败")])

    try:
        from investment_system.data.data_layer import get_northbound_flow
        nb = get_northbound_flow()
        if nb.get("data_ok"):
            today_net = nb.get("today_net", 0)
            cumul_5d = nb.get("5d_cumulative", 0)
            signal = nb.get("signal", "⚪")
            w.write(doc_id, [("bullet",
                f"北向资金: {signal} 今日{today_net:+.1f}亿 | 5日累计{cumul_5d:+.1f}亿 | {nb.get('confirmation','')}"
            )])
        else:
            w.write(doc_id, [("bullet", f"北向资金: ⚠️ {nb.get('note','数据不可用')}")])
    except Exception as e:
        w.write(doc_id, [("bullet", f"北向资金: ⚠️ {str(e)[:30]}")])

    w.write(doc_id, [("text", w.ref("十六、全球经济格局")), ("text", w.ref("十七、产业链详细分析"))])

# ═══════════════════════════════════
# 板块 2: ETF全景（三维数据驱动 + LDS组合对照）
# ═══════════════════════════════════

def _etf_volatility(symbol: str) -> float:
    """计算ETF 1个月年化波动率"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        hist = t.history(period="1mo")
        if hist.empty or len(hist) < 5:
            return None
        close = hist["Close"]
        daily_ret = close.pct_change().dropna()
        vol = float(daily_ret.std() * (252 ** 0.5) * 100)
        return round(vol, 1)
    except:
        return None

def _etf_expense_ratio(symbol: str) -> float:
    """获取ETF费率"""
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.info
        er = info.get("annualReportExpenseRatio") or info.get("expenseRatio")
        if er is not None:
            return round(er * 100, 2)
        return None
    except:
        return None

def _get_lds_component_prices():
    """获取LDS参考组合各成分今日价格变化"""
    lds_map = {
        "红利低波": "512890",     # A股红利低波ETF
        "纳指100": "QQQ",
        "黄金": "GLD",
        "豆粕": "DBA",
    }
    results = {}
    for name, sym in lds_map.items():
        try:
            from investment_system.data.yf_data_layer import get_current_price, get_price_data
            price = get_current_price(sym)
            df = get_price_data(sym, period="5d")
            chg = None
            if not df.empty and len(df) >= 2:
                chg = float((df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100)
            results[name] = {"price": price, "chg_pct": chg}
        except:
            results[name] = {"price": None, "chg_pct": None}
    return results

def build_etf_section(w, doc_id, macro):
    w.write(doc_id, [("divider", ""), ("h2", "二、📦 ETF 全景")])
    
    # ── 三维排序：动量 + 波动率 + 费率 ──
    w.write(doc_id, [("h3", "📦 ETF 动量-风险-费率 三维排序")])
    try:
        etfs = scan_us_etfs()
        if etfs:
            enriched = []
            for e in etfs[:15]:
                sym = e.get("symbol", "")
                vol = _etf_volatility(sym)
                er = _etf_expense_ratio(sym)
                e["_volatility"] = vol
                e["_expense_ratio"] = er
                # 三维综合：动量(正) + 低波动(正) + 低费率(正)
                ret = e.get("ret_20d", 0) or 0
                vol_score = max(0, 30 - (vol or 20))  # 波动率越低越好
                er_score = max(0, 2.0 - (er or 0.5)) * 10  # 费率越低越好
                e["_composite"] = round(ret * 0.5 + vol_score * 0.3 + er_score * 0.2, 1)
                enriched.append(e)
            enriched.sort(key=lambda x: x.get("_composite", 0), reverse=True)
            
            w.write(doc_id, [("text", "前5只（动量+低波+低费率综合排序):")])
            for e in enriched[:5]:
                name = e.get("name", "?")
                sym = e.get("symbol", "?")
                ret20 = fmt_pct(e.get("ret_20d", 0) / 100 if abs(e.get("ret_20d", 0) or 0) > 1 else e.get("ret_20d", 0))
                ret60 = fmt_pct(e.get("ret_60d", 0) / 100 if abs(e.get("ret_60d", 0) or 0) > 1 else e.get("ret_60d", 0))
                vol = f"{e.get('_volatility')}%" if e.get("_volatility") is not None else "?"
                er = f"{e.get('_expense_ratio')}%" if e.get("_expense_ratio") is not None else "?"
                w.write(doc_id, [("bullet", f"{name}({sym}): 1月动量 {ret20} | 3月动量 {ret60} | 波动率 {vol} | 费率 {er}")])
        else:
            w.write(doc_id, [("text", "⚠️ ETF扫描无结果")])
    except Exception as e:
        w.write(doc_id, [("text", f"⚠️ ETF三维排序失败，回退基础动量展示")])
        try:
            etfs = scan_us_etfs()
            for e in etfs[:5]:
                w.write(doc_id, [("bullet", f"{e.get('name','?')}({e.get('symbol','?')}): 1月 {fmt_pct(e.get('ret_20d',0)/100) if e.get('ret_20d') and abs(e.get('ret_20d',0))>1 else fmt_pct(e.get('ret_20d',0))} | {fmt_usd(e.get('price',0))}")])
        except:
            pass
    
    # ── LDS参考组合对照 ──
    w.write(doc_id, [("h3", "🏛️ LDS参考组合对照（25%红利低波+30%纳指100+25%黄金+20%豆粕）")])
    try:
        lds_prices = _get_lds_component_prices()
        combo_chg = 0.0
        weights = {"红利低波": 0.25, "纳指100": 0.30, "黄金": 0.25, "豆粕": 0.20}
        has_data = False
        
        for name, data in lds_prices.items():
            price = data.get("price")
            chg = data.get("chg_pct")
            if chg is not None:
                combo_chg += chg * weights.get(name, 0)
                has_data = True
            arrow = "🔺" if (chg or 0) > 0 else "🔻" if (chg or 0) < 0 else "➖"
            price_str = f"${price:.2f}" if price else "?"
            chg_str = f"{chg:+.2f}%" if chg is not None else "?"
            w.write(doc_id, [("bullet", f"{arrow} {name}: {price_str} ({chg_str})")])
        
        if has_data:
            w.write(doc_id, [
                ("bold", f"组合估算今日涨跌: {combo_chg:+.2f}%"),
                ("text", "月度再平衡 · 定投不需择时 · 4类低相关资产对冲"),
            ])
        else:
            w.write(doc_id, [("text", "⚠️ 部分成分价格不可用")])
    except Exception as e:
        w.write(doc_id, [("text", f"⚠️ LDS组合对照数据不可用")])
    
    w.write(doc_id, [("text", w.ref("二、资产配置·LDS全天候ETF"))])
    # 房价趋势已移至月报，日报不包含

# ═══════════════════════════════════
# 板块 4: 产业链10链深度分析（链内多因子+龙头标记+5段式增强）
# ═══════════════════════════════════

# —— 链配置静态数据（不常变的部分硬编码，实时数据从Yahoo Finance拉取）——
# 新10链结构：8核心链 + 2条件触发链
#   移除：消费复苏、金融地产、创新药（通缩+脱钩环境下太弱）
#   新增：网络安全/国产替代（脱钩核心受益）、AI网络设备(交换机/光模块)
#   合并：先进封装(CoWoS) → 先进制程+先进封装链
_CHAIN_CONFIGS = [
    # ═══ 核心链1: GPU/AI芯片 ═══
    {
        "name": "GPU/AI芯片", "key_players": "NVDA→AVGO→AMD",
        "lead_ticker": "NVDA", "support_tickers": ["AVGO", "AMD"],
        "all_tickers": ["NVDA", "AVGO", "AMD", "MRVL", "SMCI", "DELL", "ARM"],
        "is_conditional": False,
        "hist_doubling_pe": 20, "prev_doubling": "2022.10→2024.6, $12→$140, 历时20月",
        "supply": "台积电CoWoS产能2025扩至3.5万片/月；三星/Intel代工追赶中；Blackwell Ultra 2026H2量产",
        "demand": "四大云厂Capex $250B+；推理需求拐点2026H2；企业AI训练军备竞赛；GB300单卡算力翻倍→需求非线性",
        "gap_pct": 15, "gap_direction": "缩小中（CoWoS扩产+ASIC分流）",
        "catalysts": ["GTC 2026(6月): Rubin架构发布", "AVGO/AMD Q2财报(7月)", "云厂Capex指引更新(季报期)"],
        "assumption_hold": ["AI训练Capex不出现断崖式下降", "CUDA生态护城河维持（无竞争性替代）"],
        "assumption_break": "如果开源模型效率突破→专用芯片需求下降→AVGO/AMD受益、NVDA受损",
        "perez_stage": "frenzy(狂热期)→synergy过渡", "profit_pool": "expanding—上游GPU环节利润池最厚，但ASIC定制化分流在加速",
        "dcf_tv": "NVDA $5T市值翻倍需$10T→永续段占比需>60%→概率低。关注AVGO(ASIC替代)和AMD(性价比路径)",
        "mianji_refs": "E7/E84(中观四层次), E124(DCF永续段), E94(Perez狂热期), E155(五层蛋糕Capex层)",
        "a_profit_pool": [
            {"code": "300502", "name": "新易盛",  "env": "光模块(毛利率35-45%)", "roe_ref": 38, "why": "800G→1.6T升级直接受益，AI算力互联核心"},
            {"code": "300308", "name": "中际旭创", "env": "光模块(毛利率35-45%)", "roe_ref": 43, "why": "全球光模块市占率TOP3，ROE43%是链上最高"},
            {"code": "688183", "name": "海目星",   "env": "激光器件(毛利率45%+)", "roe_ref": 18, "why": "CPO共封装光学的上游激光光源"},
            {"code": "002463", "name": "沪电股份",  "env": "高速光模块PCB(毛利率20-30%)", "roe_ref": 15, "why": "AI服务器高速背板PCB配套，量价齐升"},
        ],
        "a_avoid": "服务器组装（毛利率5-8%）：工控/组装利润极薄，不符合LDS选股逻辑",
    },
    # ═══ 核心链2: 先进制程+先进封装 ═══
    {
        "name": "先进制程+先进封装", "key_players": "TSM→ASML→AMAT→LRCX",
        "lead_ticker": "TSM", "support_tickers": ["ASML", "AMAT", "LRCX", "KLAC"],
        "all_tickers": ["TSM", "ASML", "AMAT", "LRCX", "KLAC", "INTC"],
        "is_conditional": False,
        "hist_doubling_pe": 15, "prev_doubling": "2020.3→2021.1, TSM $45→$140, 历时10月",
        "supply": "TSM 3nm产能2025满负荷；2nm 2026H2量产；CoWoS-L 2025产能3.5万片/月→2026扩至5.5万；Intel 18A追赶中",
        "demand": "AI芯片(CoWoS必需)+手机SoC(3nm)+汽车芯片三线拉动；先进封装(CoWoS/InFO)成为制程微缩外的第二增长曲线",
        "gap_pct": 20, "gap_direction": "扩大中（2nm+CoWoS需求超预期，设备交期>12月）",
        "catalysts": ["TSM月度营收(每月10日)", "2nm试产良率报告(2026Q3)", "CoWoS扩产进度更新(季报)", "台海地缘事件(持续关注)"],
        "assumption_hold": ["台海不发生军事冲突", "3nm/2nm技术领先优势维持>18个月", "CoWoS作为AI芯片封装标准不被替代"],
        "assumption_break": "如果台海封锁→全球芯片断供→TSM折价扩大但短期无法变现；地缘折价修复是翻倍核心逻辑",
        "perez_stage": "synergy(协同期)", "profit_pool": "peaking→设备上游迁移—代工利润池见顶，CoWoS/先进封装成为新利润池增长点",
        "dcf_tv": "TSM永续段占比~50%；地缘折价(PE 15x vs 全球同业25x)提供安全边际；CoWoS贡献2026年营收>8%",
        "mianji_refs": "E7/E84(链定位=核心制造环节), E124(DCF+地缘折价), E42(周期逆向=地缘恐慌时买入), E155(CoWoS=HALO层关键封装)",
        "a_profit_pool": [
            {"code": "688012", "name": "中微公司",  "env": "刻蚀设备(毛利率45-55%)", "roe_ref": 22, "why": "CoWoS需要特殊刻蚀，台积电扩产=确定性订单"},
            {"code": "688041", "name": "北方华创", "env": "CVD/刻蚀(毛利率45%+)", "roe_ref": 20, "why": "大基金三期设备招标最大受益方"},
            {"code": "688328", "name": "华海清科", "env": "CMP设备(毛利率40%+)",   "roe_ref": 18, "why": "国内CMP唯一规模化，稀缺标的"},
            {"code": "603501", "name": "韦尔股份",  "env": "图像传感器(毛利率35%)", "roe_ref": 16, "why": "AI手机+汽车芯片双驱动"},
        ],
        "a_avoid": "封测代工（毛利率15-20%）：通富/长电毛利薄，不如设备商确定性高",
    },
    # ═══ 核心链3: 存储/HBM ═══
    {
        "name": "存储/HBM", "key_players": "MU→SK海力士→三星",
        "lead_ticker": "MU", "support_tickers": [],
        "all_tickers": ["MU"],
        "is_conditional": False,
        "hist_doubling_pe": 8, "prev_doubling": "MU 2016→2018: $10→$60, 周期上行涨幅200-300%",
        "supply": "HBM3E仅SK海力士+三星+MU三家；扩产周期12-18月；产能2026年前排满；HBM4样品2026H2送样",
        "demand": "B200/GB300每GPU配8颗HBM；HBM4 2026量产需求翻倍；缺口>30%",
        "gap_pct": 30, "gap_direction": "持续扩大（GPU功耗每代翻倍→HBM位宽需求非线性增长）",
        "catalysts": ["三星HBM3E认证通过(关键!)", "MU财报(6月)—HBM毛利率指引", "HBM4规格发布(JEDEC)"],
        "assumption_hold": ["三星HBM3E通过英伟达认证(当前最大变量)", "HBM价格不出现暴跌"],
        "assumption_break": "如果HBM产能过剩→存储周期下行→MU从周期高点回落50%+。但2026年缺口>30%，过剩风险低",
        "perez_stage": "synergy(协同期)", "profit_pool": "expanding—HBM是存储行业利润池最大的细分",
        "dcf_tv": "MU周期股不适合DCF；用PB-Band：PB<1.5x为周期底部买点，当前PB约2.5x",
        "mianji_refs": "E42(周期股逆向买入), E68(FCF两朵花), E155(五层蛋糕HALO层=HBM是关键硬件)",
        "a_profit_pool": [
            {"code": "688008", "name": "澜起科技",  "env": "内存接口芯片(毛利率60%+)", "roe_ref": 28, "why": "HBM接口芯片唯一A股纯正标的，毛利率极高"},
            {"code": "603986", "name": "兆易创新",  "env": "存储设计(毛利率45%)",    "roe_ref": 20, "why": "国产存储设计龙头，NOR Flash+MCU"},
            {"code": "688110", "name": "东芯股份",  "env": "NAND存储(毛利率35%)",   "roe_ref": 12, "why": "国产NAND Flash，存储国产化方向"},
        ],
        "a_avoid": "封装基板（毛利率25-30%）：HBM铲子逻辑成立，但IC载板毛利低于接口芯片",
    },
    # ═══ 核心链4: AI电力 ═══
    {
        "name": "AI电力", "key_players": "VST→CEG→GEV",
        "lead_ticker": "VST", "support_tickers": ["CEG", "GEV"],
        "all_tickers": ["VST", "CEG", "GEV", "TLN", "PEG", "EXC"],
        "is_conditional": False,
        "hist_doubling_pe": 12, "prev_doubling": "VST 2023.1→2024.11: $22→$170, 历时22月",
        "supply": "美国核电重启周期(三哩岛+Duane Arnold)；燃气轮机交期>24月；电网互联排队>5年",
        "demand": "单座AI数据中心=300-500MW；2026-2030年美国数据中心电力需求CAGR 15%+；GB300单机柜功耗>100kW",
        "gap_pct": 25, "gap_direction": "持续扩大（AI数据中心电力需求增速远超电网扩容速度）",
        "catalysts": ["VST/CEG PPA合同签订公告(持续)", "NRC核电站延寿审批(2026H2)", "GEV燃气轮机订单数据(季报)"],
        "assumption_hold": ["AI数据中心电力需求增长非线性(即每代GPU功耗倍增)", "核电重启不遭遇重大政策阻力"],
        "assumption_break": "如果AI芯片能效比大幅提升(10x)→电力需求增速放缓→电力股估值重估下行",
        "perez_stage": "irruption(导入期)", "profit_pool": "expanding—独立电力商(IPP)是利润池最大受益者，PPA合同锁定10-20年现金流",
        "dcf_tv": "VST永续段占比~40%；PPA合同锁定10-20年现金流→DCF确定性高。当前PE 25x，高增长消化中",
        "mianji_refs": "E7/E84(链定位=基础设施层), E124(DCF+长期合同现金流), E94(导入期=最大涨幅阶段)",
    },
    # ═══ 核心链5: AI网络+云计算（★ 新增：交换机/光模块 + 云基础设施）═══
    {
        "name": "AI网络+云计算", "key_players": "ANET→COHR→EQIX→AMZN",
        "lead_ticker": "ANET", "support_tickers": ["COHR", "LITE", "EQIX", "DLR", "AMZN"],
        "all_tickers": ["ANET", "COHR", "LITE", "EQIX", "DLR", "AMZN", "GOOGL", "CIEN"],
        "is_conditional": False,
        "hist_doubling_pe": 25, "prev_doubling": "ANET 2022.10→2024.6: $90→$380+, AI网络升级驱动, 历时20月",
        "supply": "800G/1.6T光模块产能爬坡(COHR/LITE)；Arista 400G/800G交换机交付周期改善至8周；数据中心REITs供给刚性(建设周期>3年)",
        "demand": "AI集群从万卡→十万卡→百万卡→网络带宽需求指数增长；每GPU需配2-3个800G光模块；云AI推理流量2026年翻3倍",
        "gap_pct": 20, "gap_direction": "扩大中（AI集群规模扩大→光模块+交换机需求超线性增长）",
        "catalysts": ["Arista/COHR财报(7-8月): AI网络收入占比", "800G→1.6T光模块切换(2026H2)", "AWS/GCP新数据中心区域开通(持续)"],
        "assumption_hold": ["AI训练集群持续从万卡向十万卡+扩展(网络成为瓶颈→利好)", "800G光模块不被CPO(共封装光学)快速替代"],
        "assumption_break": "如果CPO技术2027前成熟→传统可插拔光模块需求下降→COHR/LITE受损。但ANET交换机层不受影响",
        "perez_stage": "irruption→synergy过渡", "profit_pool": "expanding—网络设备+光模块是AI基础设施的新利润池；云平台是AI推理的必经枢纽",
        "dcf_tv": "ANET PE 45x定价高增长(AI网络份额>40%)；COHR/LITE PE 20-25x更合理。EQIX/DLR用FFO模型，FFO增速~12%支撑25x P/FFO",
        "mianji_refs": "E7/E84(链定位=网络基础设施+云平台), E124(DCF+经常性收入), E155(五层蛋糕=云基础设施层)",
    },
    # ═══ 核心链6: AI应用/Agent ═══
    {
        "name": "AI应用/Agent", "key_players": "MSFT→META→CRM",
        "lead_ticker": "MSFT", "support_tickers": ["META", "CRM"],
        "all_tickers": ["MSFT", "META", "CRM", "NOW", "SNOW", "PLTR", "ADBE"],
        "is_conditional": False,
        "hist_doubling_pe": 25, "prev_doubling": "MSFT 2016→2020: $50→$200+, 云转型驱动, 历时48月",
        "supply": "LLM能力供给充足(GPT-5/Claude-4/Gemini-3)；Agent框架(Copilot/Salesforce Einstein/Now Assist)快速迭代",
        "demand": "企业AI渗透率<15%→拐点将至；Agent替代客服/编码/数据分析→ARPU提升$30-50/月",
        "gap_pct": 0, "gap_direction": "即将出现（Agent需求爆发但企业IT预算审批滞后→2026H2释放）",
        "catalysts": ["MSFT Build 2026(5月): Copilot企业版更新", "META Llama-4开源(2026H2)", "CRM Dreamforce(9月): Agentforce数据"],
        "assumption_hold": ["企业AI预算不削减(即使经济放缓)", "Agent定价模型成立(按conversation/seat付费)"],
        "assumption_break": "如果Agent幻觉问题无法解决→企业信任度下降→增长放缓。但技术迭代速度支持乐观预期",
        "perez_stage": "irruption→frenzy过渡", "profit_pool": "expanding—应用层利润池即将爆发，Agent是SaaS之后最大软件浪潮",
        "dcf_tv": "MSFT $3T市值；Copilot ARPU提升若实现→永续段占比>55%。当前PE 32x, PEG~1.3",
        "mianji_refs": "E7/E84(链定位=应用层), E124(DCF+ARPU模型), E118(Nick四问=趋势确认), E155(五层蛋糕用户层)",
    },
    # ═══ 核心链7: 网络安全/国产替代（★ 新增：脱钩核心受益）═══
    {
        "name": "网络安全/国产替代", "key_players": "CRWD→PANW→奇安信→深信服",
        "lead_ticker": "CRWD", "support_tickers": ["PANW", "ZS", "FTNT"],
        "all_tickers": ["CRWD", "PANW", "ZS", "FTNT", "S", "CHKP"],
        "is_conditional": False,
        "hist_doubling_pe": 50, "prev_doubling": "CRWD 2023.1→2024.7: $100→$400, AI安全+端点扩张, 历时18月",
        "supply": "全球网安人才缺口400万+；AI攻击(Spear-phishing/Deepfake)呈指数增长→安全产品需求刚性；中国信创/国产替代政策强制采购",
        "demand": "AI时代攻击面扩大(Agent/API/数据管道)；地缘脱钩→各国自建网安体系→中美双轨需求；中国网安市场25%+ CAGR",
        "gap_pct": 15, "gap_direction": "持续扩大（AI攻击复杂度指数级增长→传统防御失效→AI原生安全需求爆发）",
        "catalysts": ["CRWD/PANW财报(8月): AI安全ARR增速", "美国联邦网安预算2027(6月)", "中国数据安全法执行细则(持续)"],
        "assumption_hold": ["AI驱动的网络攻击持续增长(不出现'AI安全奇点'解决所有漏洞)", "企业网安预算占IT支出比例从5%→10%+"],
        "assumption_break": "如果AI安全自动化太成功→安全需求反而下降(效率替代人力)。但目前AI攻击>AI防御，缺口反而是扩大的",
        "perez_stage": "synergy(协同期)", "profit_pool": "expanding—网安是IT支出中最刚性的部分，AI时代从成本中心变为业务使能者",
        "dcf_tv": "CRWD PE 80x定价高增长(ARR 40%+)→需维持3年+高增速消化。PANW PE 45x更合理(平台化+经常性收入)。中国标的关注政策催化",
        "mianji_refs": "E7/E84(链定位=安全基础设施), E124(DCF+ARR经常性收入), E136(逆潮=脱钩受益), E42(周期逆向=恐慌时安全股抗跌)",
    },
    # ═══ 核心链8: 机器人 ═══
    {
        "name": "机器人", "key_players": "特斯拉→发那科→埃斯顿",
        "lead_ticker": "TSLA", "support_tickers": [],
        "all_tickers": ["TSLA"],
        "is_conditional": False,
        "hist_doubling_pe": 50, "prev_doubling": "TSLA 2019.6→2021.1: $12→$300(拆股前), 历时19月",
        "supply": "Optimus 2026试产线投产；发那科/ABB传统工业机器人产能充足；中国埃斯顿本土替代加速",
        "demand": "Optimus量产预期2027→TAM $10T+(Elon估算)；工业机器人中国密度全球第5仍偏低；人形机器人从实验室→工厂→家庭三阶段",
        "gap_pct": 0, "gap_direction": "即将出现（Optimus量产初期供不应求确定性高，但时间不确定）",
        "catalysts": ["特斯拉AI Day(2026H2): Optimus Gen-3演示", "发那科中国工厂扩建(2026)", "中国机器人产业政策(持续)", "Optimus试产线进展更新(季报)"],
        "assumption_hold": ["Optimus 2027量产时间表不推迟", "人形机器人BOM成本能降至$2万以下"],
        "assumption_break": "如果量产推迟到2028+→TSLA估值承压(机器人预期已在股价中)。但AI技术进步加速量产概率",
        "perez_stage": "irruption(导入期)", "profit_pool": "nascent—利润池尚未形成，当前是Capex投入期",
        "dcf_tv": "TSLA机器人业务无法用DCF(无收入)；用期权思维：下行有限(汽车业务支撑)，上行有凸性(机器人TAM)",
        "mianji_refs": "E94(Perez导入期=最大不确定性+最大涨幅), E111(杠铃策略=小仓位博凸性), E7(行业空间=TAM)",
    },
    # ═══ 条件触发链9: 消费电子（仅CPI>1%或重大产品催化时分析）═══
    {
        "name": "消费电子", "key_players": "苹果→小米→传音",
        "lead_ticker": "AAPL", "support_tickers": [],
        "all_tickers": ["AAPL", "1810.HK"],
        "is_conditional": True,  # 条件触发：需要CPI>1%或重大AI手机催化
        "hist_doubling_pe": 18, "prev_doubling": "AAPL 2019.1→2021.12: $38→$180, 历时35月",
        "supply": "iPhone 18(AI手机)2026Q3发布；折叠屏供应链成熟；小米/传音新兴市场渠道深耕",
        "demand": "全球换机周期从36月→30月(AI驱动)；AI手机渗透率从5%→25%(2027E)",
        "gap_pct": 0, "gap_direction": "稳定（AI手机催化换机需求，但整体市场饱和）",
        "catalysts": ["AAPL WWDC 2026(6月): AI功能升级", "iPhone 18发布(9月): AI硬件级升级", "小米14T/传音AI手机新兴市场出货数据"],
        "assumption_hold": ["AI手机能驱动消费者换机(而非纯噱头)", "苹果AI功能在中国市场合规落地"],
        "assumption_break": "如果AI功能对换机拉动不显著→苹果增速回到低个位数→PE从30x回归22x。关注iPhone 18预订数据验证",
        "perez_stage": "maturity→synergy(AI注入)", "profit_pool": "stable—品牌终端利润池稳定，AI创造增量",
        "dcf_tv": "AAPL $3.5T市值；永续段>60%→翻倍空间有限。关注小米(PE 25x)和传音(PE 15x)的新兴市场翻倍机会",
        "mianji_refs": "E7/E84(链定位=品牌终端), E124(DCF+品牌溢价), E105(及早离去=巨无霸增速放缓信号)",
    },
    # ═══ 条件触发链10: 新能源车（仅宏观配合时分析）═══
    {
        "name": "新能源车", "key_players": "比亚迪→特斯拉→宁德",
        "lead_ticker": "TSLA", "support_tickers": [],
        "all_tickers": ["TSLA", "1211.HK", "9868.HK", "2015.HK"],
        "is_conditional": True,  # 条件触发：需要渗透率上升+无重大关税升级
        "hist_doubling_pe": 50, "prev_doubling": "TSLA 2020.3→2021.11: $20→$400(拆股前), 历时20月",
        "supply": "比亚迪年产能500万+；特斯拉Cybertruck/Model 2爬坡；宁德全球动力电池份额37%",
        "demand": "全球新能源渗透率~25%→40%+；出海(东南亚/欧洲/南美)第二增长曲线",
        "gap_pct": 0, "gap_direction": "收窄中（国内产能过剩→价格战压缩利润，海外关税壁垒升高）",
        "catalysts": ["特斯拉Robotaxi发布(2026)", "比亚迪海外工厂投产(泰国/巴西)", "宁德固态电池量产时间表"],
        "assumption_hold": ["全球新能源渗透率持续提升(政策+成本优势)", "比亚迪出海不遭遇重大关税壁垒"],
        "assumption_break": "如果欧美对中国新能源车加征50%+关税→比亚迪海外增速腰斩。但国内+东盟+南美市场仍可支撑",
        "perez_stage": "synergy(协同期)→maturity过渡", "profit_pool": "migrating—从整车→电池/智驾上游迁移，整车利润池承压",
        "dcf_tv": "TSLA核心争议：汽车业务(PE 50x) vs Robotaxi/机器人(期权价值)。比亚迪PE 18x更合理",
        "mianji_refs": "E7/E84(链定位=整车+电池), E124(DCF+期权价值分离), E42(周期逆向=渗透率怀疑时买入)",
    },

    # ═══ 核心链11: 半导体国产替代（设备+材料+EDA）═══
    {
        "name": "半导体国产替代", "key_players": "北方华创→中微公司→中芯国际",
        "lead_ticker": "688041", "support_tickers": ["688012", "688981"],
        "all_tickers": ["688041", "688012", "688981", "688328", "688536", "688120"],
        "is_conditional": False,
        "hist_doubling_pe": 25, "prev_doubling": "北方华创 2020→2022: ¥50→¥380, 历时24月",
        "supply": "大基金三期2024年募资3440亿；设备国产化率从15%→35%；28nm+成熟制程全线铺开",
        "demand": "国内晶圆厂持续扩产（中芯南京/华虹无锡）；信创采购政策DDL→2027年央企完成替代",
        "gap_pct": 65, "gap_direction": "扩大中（出口管制倒逼国产替代加速，设备每年新增需求>300亿）",
        "catalysts": ["大基金三期设备招标落地", "国产EDA突破28nm制程", "中芯国际月产能突破10万片", "美国扩大出口管制范围"],
        "assumption_hold": ["大基金三期持续投入", "国产设备良率达到客户采购标准", "晶圆厂扩产节奏不放缓"],
        "assumption_break": "如果中美半导体谈判达成协议→国产替代紧迫性下降；国产设备良率长期无法达标→客户不采购",
        "perez_stage": "synergy(协同期)—国产化率加速提升阶段", "profit_pool": "expanding—设备厂利润率40-55%是链上最厚，国产替代提供额外溢价",
        "dcf_tv": "北方华创PE 35-50x含国产替代溢价；中微PE 40x；用渗透率×TAM估算潜在收入>历史估值",
        "mianji_refs": "E131(逆全球化=国产替代最大驱动), E7/E84(链定位=设备是利润最厚环节), E136(逆潮受益)",
        "a_profit_pool": [
            {"code": "688041", "name": "北方华创", "env": "CVD/刻蚀设备(毛利率45%+)", "roe_ref": 20, "why": "大基金三期最大受益，在手订单可见度18个月"},
            {"code": "688012", "name": "中微公司",  "env": "刻蚀设备(毛利率45-55%)",  "roe_ref": 22, "why": "刻蚀设备龙头，台积电CoWoS扩产=确定性订单"},
            {"code": "688328", "name": "华海清科", "env": "CMP设备(毛利率40%+)",    "roe_ref": 18, "why": "国内CMP唯一规模化，稀缺性高"},
            {"code": "688099", "name": "华大九天", "env": "EDA软件(毛利率60%+)",    "roe_ref": 15, "why": "国产EDA龙头，2027信创DDL政策支撑"},
        ],
        "a_avoid": "晶圆代工整厂（毛利率<20%）：中芯是行业贝塔，不是利润最厚环节",
    },

    # ═══ 核心链12: 医药创新（创新药+CXO+器械国产替代）═══
    {
        "name": "医药创新", "key_players": "恒瑞医药→药明康德→迈瑞医疗",
        "lead_ticker": "603259", "support_tickers": [],
        "all_tickers": ["603259", "300760", "300347"],
        "is_conditional": False,
        "hist_doubling_pe": 30, "prev_doubling": "药明康德 2019→2021: ¥60→¥170, CXO爆量+新冠订单, 历时24月",
        "supply": "全球CXO产能集中中国（成本优势40%+）；中国创新药管线数量全球第二；器械国产化率<30%",
        "demand": "GLP-1减肥药全球渗透率<5%→25%；中国创新药出海BD交易额2025年>1350亿美元；老龄化驱动医疗器械需求",
        "gap_pct": 15, "gap_direction": "扩大中（AI制药+GLP-1新适应症+器械国产替代三线驱动）",
        "catalysts": ["药明康德CXO订单增速转正确认", "恒瑞/百济FDA关键三期数据", "国产高端器械医保招标", "GLP-1国内获批"],
        "assumption_hold": ["中美CXO不脱钩（BIOSECURE法案未严格执行）", "创新药出海BD持续", "老龄化医疗需求刚性"],
        "assumption_break": "如果BIOSECURE法案严格执行→药明康德美国业务中断；医保控费超预期→创新药定价受压",
        "perez_stage": "irruption→synergy—创新药从me-too向first-in-class突破", "profit_pool": "expanding—创新药毛利率70-95%，CXO30-45%，器械50-70%",
        "dcf_tv": "恒瑞PE 30-45x（管线估值法）；药明PE 20-30x（盈利恢复）；迈瑞PE 25-35x（国产替代溢价）",
        "mianji_refs": "E26(医药子版块赛道投资), E42(周期底部逆向买入), E68(FCF两朵花=创新药现金流)",
        "a_profit_pool": [
            {"code": "603259", "name": "药明康德", "env": "CXO(毛利率30-45%)", "roe_ref": 18, "why": "全球CXO龙头，订单触底回暖，出海能力最强"},
            {"code": "300760", "name": "迈瑞医疗", "env": "医疗器械(毛利率60-70%)", "roe_ref": 25, "why": "器械龙头，国产替代+出海双驱动"},
            {"code": "300347", "name": "泰格医药", "env": "CRO(毛利率35-45%)", "roe_ref": 20, "why": "临床CRO龙头，创新药出海必要环节"},
        ],
        "a_avoid": "仿制药（毛利率<20%）：带量采购压价，利润空间极薄",
    },

    # ═══ 核心链13: 数据中心/云计算（IDC+液冷+云服务）═══
    {
        "name": "数据中心/云计算", "key_players": "科华数据→依米康→光环新网",
        "lead_ticker": "002453", "support_tickers": [],
        "all_tickers": ["002453", "300459", "300451"],
        "is_conditional": False,
        "hist_doubling_pe": 20, "prev_doubling": "科华数据 2022→2024: ¥15→¥50, AI数据中心+液冷, 历时18月",
        "supply": "AI数据中心建设周期>18月；液冷渗透率仅5%→20%（2026E）；IDC一线城市资源稀缺",
        "demand": "CSP资本开支2025年合计$250B+；GB300单机柜功耗>100kW→风冷失效→液冷刚需；国内算力中心政策驱动",
        "gap_pct": 25, "gap_direction": "扩大中（AI集群功耗每代翻倍→液冷渗透加速）",
        "catalysts": ["CSP季度Capex指引", "液冷标准化进展（ASHRAE规范）", "国内算力补贴政策", "大模型推理流量爆发"],
        "assumption_hold": ["AI集群功耗持续提升（GPU每代TDP翻倍）", "液冷技术标准化推进", "CSP不削减Capex"],
        "assumption_break": "如果AI芯片能效比突破（10x）→功耗下降→液冷需求放缓；IDC产能过剩→价格下行",
        "perez_stage": "irruption→synergy—AI驱动液冷从0→1渗透", "profit_pool": "expanding—液冷35-45%，IDC25-35%，云服务30-50%",
        "dcf_tv": "科华/依米康PE 25-40x（液冷高增速）；用订单可见度+扩产计划做前向估值",
        "mianji_refs": "E155(五层蛋糕=Capex层基础设施), E124(DCF+经常性收入=IDC长约), E7/E84(链定位=AI算力物理底座)",
        "a_profit_pool": [
            {"code": "002453", "name": "科华数据",  "env": "UPS/液冷(毛利率35-45%)", "roe_ref": 15, "why": "数据中心电力+液冷双主线，AI IDC核心配套"},
            {"code": "300459", "name": "依米康",   "env": "精密空调/液冷(毛利率30-40%)", "roe_ref": 12, "why": "液冷进入放量期，AI数据中心标配"},
            {"code": "300451", "name": "创业慧康", "env": "IDC运营(毛利率25-35%)", "roe_ref": 10, "why": "算力中心资源稀缺，长期合约锁定收益"},
        ],
        "a_avoid": "通用服务器组装（毛利率5-8%）：高度竞争，没有差异化壁垒",
    },

    # ═══ 核心链14: 苹果产业链（AI换机周期+A股供应商）═══
    {
        "name": "苹果产业链", "key_players": "AAPL→立讯精密→蓝思科技",
        "lead_ticker": "AAPL", "support_tickers": [],
        "all_tickers": ["AAPL", "QCOM", "AVGO"],
        "is_conditional": True,
        "hist_doubling_pe": 22, "prev_doubling": "AAPL 2020.3→2021.12: $55→$180, 历时21月",
        "supply": "iPhone 18 AI版2026Q3发布；A股供应商：立讯精密/蓝思科技/歌尔股份/鹏鼎控股",
        "demand": "AI手机换机周期从36月→30月；折叠屏渗透率1%→5%（2027E）；服务收入占比持续提升",
        "gap_pct": 0, "gap_direction": "稳定→温和扩大（AI功能推动换机需求，但整体市场已饱和）",
        "catalysts": ["AAPL WWDC 2026: AI功能更新", "iPhone 18秋季发布会+预订数据", "折叠屏首发时间", "AI功能用户激活率"],
        "assumption_hold": ["AI手机能驱动消费者换机", "苹果AI功能在中国市场合规落地", "A股供应商份额不流失"],
        "assumption_break": "AI功能不能驱动换机→苹果增速回归低个位数→A股供应商业绩平淡",
        "perez_stage": "maturity→synergy（AI注入成熟产品创造增量）", "profit_pool": "stable—品牌端利润稳定，A股供应商是β而非α",
        "dcf_tv": "AAPL $3.5T市值，永续段>60%，翻倍难度大；A股供应商看换机周期弹性，PE 15-25x合理",
        "mianji_refs": "E32(南添光谱右移=消费电子右侧逻辑), E94(Perez成熟期注入AI催化), E105(及早离去=AAPL巨无霸增速放缓)",
        "a_profit_pool": [
            {"code": "002475", "name": "立讯精密", "env": "精密组装(毛利率15-20%)", "roe_ref": 18, "why": "苹果最大组装商，iPhone份额>70%，AirPods独家"},
            {"code": "300433", "name": "蓝思科技", "env": "玻璃/结构件(毛利率20-28%)", "roe_ref": 12, "why": "屏幕玻璃+折叠屏铰链，新产品驱动毛利率提升"},
            {"code": "002241", "name": "歌尔股份", "env": "声学/VR(毛利率18-25%)", "roe_ref": 14, "why": "AirPods声学独家+Vision Pro供应商"},
            {"code": "601138", "name": "鹏鼎控股", "env": "FPC软板(毛利率20-25%)", "roe_ref": 16, "why": "苹果FPC最大供应商，AI手机内部连接升级"},
        ],
        "a_avoid": "低端组装代工（毛利率<8%）：富士康等利润极薄，非LDS选股逻辑",
    },

    # ═══ 核心链15: 新能源汽车（宽体：整车+三电+智驾）═══
    {
        "name": "新能源汽车", "key_players": "比亚迪→宁德时代→小鹏",
        "lead_ticker": "TSLA", "support_tickers": ["LI", "NIO"],
        "all_tickers": ["TSLA", "LI", "NIO", "XPEV"],
        "is_conditional": True,
        "hist_doubling_pe": 25, "prev_doubling": "比亚迪 2020→2022: ¥25→¥350, 历时24月（新能源渗透率5%→25%）",
        "supply": "比亚迪年产能500万+；宁德全球份额37%；智驾算法：华为ADS/小鹏XNGP/特斯拉FSD",
        "demand": "全球新能源渗透率~25%→40%+；智驾渗透率从10%→40%（2027E）；出海东南亚/欧洲",
        "gap_pct": 0, "gap_direction": "整车收窄（产能过剩）| 智驾扩大（渗透率仍低）",
        "catalysts": ["特斯拉FSD入华时间表", "比亚迪海外工厂投产", "宁德固态电池量产", "华为ADS渗透率数据"],
        "assumption_hold": ["全球新能源渗透率持续提升", "比亚迪出海不遭遇重大关税", "智驾商业化模式成立"],
        "assumption_break": "欧美对中国新能源车加征50%+关税→比亚迪海外增速腰斩；整车价格战持续→全行业利润率趋零",
        "perez_stage": "synergy→maturity过渡—整车成熟，智驾S2爆发", "profit_pool": "migrating—从整车→智驾/电池上游迁移，整车利润池承压",
        "dcf_tv": "比亚迪PE 18-25x（合理）；宁德PE 15-20x（合理）；智驾标的PE 40-80x（成长溢价）",
        "mianji_refs": "E126(三周期嵌套=新能源是朱格拉周期), E42(周期逆向=出清后买), E7/E84(链定位=买智驾不买组装)",
        "a_profit_pool": [
            {"code": "002594", "name": "比亚迪",   "env": "整车+电池(毛利率18-22%)", "roe_ref": 20, "why": "行业贝塔，全球销量第一，出海逻辑最强"},
            {"code": "300750", "name": "宁德时代", "env": "动力电池(毛利率22-28%)", "roe_ref": 16, "why": "全球电池份额37%，储能+海外是增量"},
            {"code": "002459", "name": "晶澳科技", "env": "智驾域控(毛利率40-50%)", "roe_ref": 14, "why": "智驾域控国内TOP3，利润率高于整车"},
        ],
        "a_avoid": "上游锂/正极材料（产能严重过剩，价格战利润崩塌）",
    },
]

# ═══════════════════════════════════
# 链内多因子扫描辅助函数
# ═══════════════════════════════════

def _fetch_chain_ticker_data(cfg, live_data_cache):
    """
    从Yahoo Finance拉取链内所有ticker的因子数据，并缓存。
    返回: {ticker: factor_dict, ...}
    """
    result = {}
    all_tickers = cfg.get("all_tickers", [])
    if not all_tickers:
        # fallback: 使用 lead + support
        all_tickers = [cfg["lead_ticker"]] + cfg.get("support_tickers", [])

    for t in all_tickers:
        if t in live_data_cache:
            result[t] = live_data_cache[t]
            continue
        # 跳过港股A股代码（纯数字或含.HK/.SS/.SZ），这些用yfinance格式也能拉但可能失败
        try:
            from investment_system.data.yf_data_layer import get_factor_data, get_current_price
            fd = get_factor_data(t)
            price = get_current_price(t)
            if fd and "error" not in fd:
                fd["_price"] = price
                result[t] = fd
                live_data_cache[t] = fd
        except Exception:
            pass
    return result


def _score_intra_chain(chain_ticker_data):
    """
    链内多因子评分：对链内所有ticker计算综合得分（质量/成长/动量/价值）。
    返回排序后的列表: [{ticker, name, score, quality, growth, momentum, value, market_cap, pe, ...}, ...]
    """
    scored = []
    for ticker, fd in chain_ticker_data.items():
        if not fd or "error" in fd:
            continue

        # 提取因子数据
        pe = fd.get("pe")
        pb = fd.get("pb")
        roe = fd.get("roe")
        margin = fd.get("profit_margin")
        rev_g = fd.get("revenue_growth")
        earn_g = fd.get("earnings_growth")
        mkt_cap = fd.get("market_cap")
        price = fd.get("_price")
        beta = fd.get("beta")

        # —— 质量因子 (ROE+利润率) ——
        s_roe = max(1, min(10, 1 + 9 * min(abs(roe or 0), 0.50) / 0.50)) if roe is not None else 5.0
        s_margin = max(1, min(10, 1 + 9 * min(abs(margin or 0), 0.45) / 0.45)) if margin is not None else 5.0
        quality = round(s_roe * 0.6 + s_margin * 0.4, 1)

        # —— 成长因子 (营收+盈利增速) ——
        s_rev = max(1, min(10, 1 + 9 * (max(-0.2, min(rev_g or 0, 1.0)) + 0.2) / 1.2)) if rev_g is not None else 5.0
        s_earn = max(1, min(10, 1 + 9 * (max(-0.3, min(earn_g or 0, 2.0)) + 0.3) / 2.3)) if earn_g is not None else 5.0
        growth = round(s_rev * 0.4 + s_earn * 0.6, 1)

        # —— 价值因子 (PE低=高分) ——
        if pe is not None and pe > 0:
            s_pe = max(1, min(10, 10 - 9 * (min(pe, 80) - 5) / 75))  # PE 5-80 范围内越低越好
        else:
            s_pe = 5.0
        if pb is not None and pb > 0:
            s_pb = max(1, min(10, 10 - 9 * (min(pb, 20) - 0.5) / 19.5))
        else:
            s_pb = 5.0
        value = round(s_pe * 0.6 + s_pb * 0.4, 1)

        # —— 动量因子 (从52周位置估算) ——
        hi52 = fd.get("52w_high")
        lo52 = fd.get("52w_low")
        if price and hi52 and lo52 and hi52 > lo52:
            pct_52w = (price - lo52) / (hi52 - lo52) * 100
            momentum = round(max(1, min(10, 1 + 9 * min(pct_52w, 100) / 100)), 1)
        else:
            momentum = 5.0

        # —— 综合得分（质量35% + 成长30% + 价值20% + 动量15%）——
        composite = round(quality * 0.35 + growth * 0.30 + value * 0.20 + momentum * 0.15, 1)

        scored.append({
            "ticker": ticker,
            "name": fd.get("name", ticker),
            "score": composite,
            "quality": quality,
            "growth": growth,
            "value": value,
            "momentum": momentum,
            "market_cap": mkt_cap,  # 可能为 None
            "pe": pe,
            "price": price,
        })

    # 按综合得分降序排列
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _tag_chain_leaders(scored_list):
    """
    标记链龙头和中小市值高潜票。
    - 「链龙头」：市值最大或评分最高的票（选市值最大的作为龙头）
    - 「高潜中小市值」：市值<$50B 且 成长因子>7.0 的票
    返回: (leader_tag, smid_list)
    """
    if not scored_list:
        return None, []

    # 找市值最大的作为龙头
    with_cap = [s for s in scored_list if s.get("market_cap")]
    if with_cap:
        leader = max(with_cap, key=lambda x: x["market_cap"] or 0)
    else:
        # 无市值数据时，用评分最高的
        leader = scored_list[0]

    # 找高潜中小市值：市值<$50B 且成长>7.0
    SMID_CAP_THRESHOLD = 50e9  # $50B
    smid_candidates = [
        s for s in scored_list
        if s.get("market_cap") and s["market_cap"] < SMID_CAP_THRESHOLD and s["growth"] > 7.0
    ]

    return leader, smid_candidates


def _fmt_mkt_cap(mkt_cap):
    """格式化市值显示"""
    if mkt_cap is None:
        return "?"
    if mkt_cap >= 1e12:
        return f"${mkt_cap/1e12:.2f}T"
    if mkt_cap >= 1e9:
        return f"${mkt_cap/1e9:.1f}B"
    if mkt_cap >= 1e6:
        return f"${mkt_cap/1e6:.0f}M"
    return f"${mkt_cap:.0f}"


def build_chain_section(w, doc_id, scanner, macro):
    """
    产业链10链深度分析 — 链内多因子扫描 + 龙头/中小市值标记 + 5段式增强分析
    
    新增功能 vs v6.1:
      1. 每链内多因子扫描（质量/成长/动量/价值），链内排名
      2. 标记「链龙头」（市值最大）和「高潜中小市值」（市值<$50B但成长>7）
      3. 周期位置增加「当前PE vs 翻倍起点PE → 安全边际百分比」
      4. 供需缺口增加「缺口方向变化(扩大/缩小)」
      5. 条件触发链标⚡，通缩环境下注明不满足条件
    """
    w.write(doc_id, [("divider", ""), ("h2", "九、🔗 产业链 10 链深度分析")])

    chain_mode = macro.get('chain_mode', 'active')
    if chain_mode == 'observation':
        w.write(doc_id, [("quote", "🔒 双门关闭：宏观门×趋势门均未开启。当前处于等待信号、观察阶段，静待入场条件触发。")])
    else:
        w.write(doc_id, [("quote", "E7 董艺婷：不是买好公司，是买利润率最高的环节。E94 Perez：盯住技术漫化阶段。E155 五层蛋糕：Capex→HALO→用户→应用→设备。")])

    from investment_system.output.concept_engine import ConceptEngine, ChainSnapshot, StockSnapshot
    engine = ConceptEngine()

    favored = macro.get("favored_sectors", [])
    avoided = macro.get("avoided_sectors", [])
    cpi = macro.get("macro_data", {}).get("cpi")
    regime = macro.get("regime", "?")

    # —— 分拣：核心链 vs 条件触发链 ——
    core_chains = [c for c in _CHAIN_CONFIGS if not c.get("is_conditional")]
    cond_chains = [c for c in _CHAIN_CONFIGS if c.get("is_conditional")]

    # 条件触发判断
    analyze_cond_chains = False
    cond_skip_reason = ""
    if cpi is not None and cpi > 1.0:
        analyze_cond_chains = True
    else:
        cond_skip_reason = f"当前CPI={cpi}%（通缩压力），消费电子和新能源车链需求逻辑弱化，以下仅展示框架不深入分析"

    # —— 拉取所有链的ticker实时数据（批量优化）——
    all_tickers_set = set()
    for cfg in _CHAIN_CONFIGS:
        all_tickers_set.add(cfg["lead_ticker"])
        for st in cfg.get("support_tickers", []):
            all_tickers_set.add(st)
        for at in cfg.get("all_tickers", []):
            all_tickers_set.add(at)

    live_data_cache = {}  # 全局缓存
    fetch_ok = False
    try:
        from investment_system.data.yf_data_layer import get_factor_data, get_current_price
        for t in all_tickers_set:
            if t in live_data_cache:
                continue
            # 跳过港股/A股代码
            if t.endswith(".HK") or t.endswith(".SS") or t.endswith(".SZ") or t.isdigit():
                continue
            try:
                fd = get_factor_data(t)
                price = get_current_price(t)
                if fd and "error" not in fd:
                    fd["_price"] = price
                    live_data_cache[t] = fd
            except Exception:
                pass
        if live_data_cache:
            fetch_ok = True
    except Exception:
        pass

    if not fetch_ok:
        w.write(doc_id, [("text", "⚠️ 实时数据不可用（Yahoo Finance连接失败），使用静态框架数据。PE等数值为近似参考。")])

    # ═══════════════════════════════════
    # 阶段1: 核心8链完整分析
    # ═══════════════════════════════════
    w.write(doc_id, [("h3", "🔵 核心8链 · 深度分析")])

    for cfg in core_chains:
        _build_single_chain_analysis(w, doc_id, cfg, live_data_cache, favored, regime, engine, is_cond=False, chain_mode=chain_mode)

    # ═══════════════════════════════════
    # 阶段2: 条件触发2链
    # ═══════════════════════════════════
    w.write(doc_id, [("divider", ""), ("h3", "⚡ 条件触发2链")])

    if not analyze_cond_chains:
        w.write(doc_id, [("quote", f"⚠️ 条件不满足: {cond_skip_reason}")])

    for cfg in cond_chains:
        _build_single_chain_analysis(w, doc_id, cfg, live_data_cache, favored, regime, engine,
                                     is_cond=True, is_active=analyze_cond_chains, chain_mode=chain_mode)

    w.write(doc_id, [
        ("divider", ""),
        ("text", f"⏫ 宏观偏好板块: {', '.join(favored[:3]) if favored else '均衡配置'} | ⏬ 回避板块: {', '.join(avoided[:3]) if avoided else '无'}"),
        ("text", f"宏观象限: {regime} | CPI: {cpi}% | 条件触发链状态: {'✅激活' if analyze_cond_chains else '🔒冻结（通缩环境）'}"),
        ("text", w.ref("十七、产业链详细分析")),
    ])


def _build_single_chain_analysis(w, doc_id, cfg, live_data_cache, favored, regime, engine,
                                  is_cond=False, is_active=True, chain_mode='active'):
    """
    构建单条链的完整5段式分析（含链内多因子扫描）
    
    参数:
      is_cond: 是否为条件触发链
      is_active: 条件链是否激活（不激活时仅输出框架）
      chain_mode: 'active' → 正常分析; 'observation' → 双门关闭观察模式
    """
    chain_name = cfg["name"]
    fav_tag = "⭐" if chain_name in str(favored) else ""
    cond_tag = " ⚡条件触发" if is_cond else ""
    ticker = cfg["lead_ticker"]
    fd = live_data_cache.get(ticker, {})

    # 提取实时PE和价格
    live_pe = fd.get("pe")
    live_price = fd.get("_price")
    live_growth = fd.get("earnings_growth")
    if live_growth is not None and abs(live_growth) < 10:
        live_growth = live_growth * 100  # 转为百分比
    live_mkt_cap = fd.get("market_cap")

    blocks = []

    # ── 标题 ──
    status_tag = ""
    if is_cond and not is_active:
        status_tag = " 🔒（条件不满足，仅框架展示）"
    if chain_mode == 'observation':
        blocks.append(("h3", f"{fav_tag} {chain_name}{cond_tag}{status_tag} — 等待信号，观察阶段"))
    else:
        blocks.append(("h3", f"{fav_tag} {chain_name}{cond_tag}{status_tag} — 为什么现在有翻倍机会？"))

    # ═══════════════════════════════════
    # ★ 链内多因子扫描（NEW）
    # ═══════════════════════════════════
    if is_active:
        blocks.append(("bold", "📊 链内多因子扫描"))

        # 获取链内所有ticker数据
        chain_data = _fetch_chain_ticker_data(cfg, live_data_cache)
        scored_list = _score_intra_chain(chain_data)
        leader, smid_list = _tag_chain_leaders(scored_list)

        # 输出扫描摘要
        scanned_count = len(scored_list)
        blocks.append(("bullet", f"链内扫描 {scanned_count} 只标的，按质量(35%)+成长(30%)+价值(20%)+动量(15%)综合排名"))

        # 链龙头标记
        if leader:
            leader_mkt = _fmt_mkt_cap(leader.get("market_cap"))
            leader_pe = f"{leader['pe']:.1f}x" if leader.get("pe") else "?"
            blocks.append(("bullet",
                f"🏆 链龙头: {leader['name']}({leader['ticker']}) | 市值 {leader_mkt} | PE {leader_pe} | 评分 {leader['score']:.1f}"))

        # 排名前3（不含龙头）
        top3 = [s for s in scored_list if s != leader][:3]
        if top3:
            rank_lines = []
            for i, s in enumerate(top3, 1):
                pe_str = f"{s['pe']:.1f}x" if s.get("pe") else "?"
                mkt_str = _fmt_mkt_cap(s.get("market_cap"))
                rank_lines.append(
                    f"#{i+1} {s['name']}({s['ticker']}) 评分{s['score']:.1f} | PE {pe_str} | 市值{mkt_str} | "
                    f"质量{s['quality']:.1f}/成长{s['growth']:.1f}/价值{s['value']:.1f}"
                )
            for rl in rank_lines:
                blocks.append(("bullet", rl))

        # 高潜中小市值标记
        if smid_list:
            blocks.append(("bold", "🔍 链内高潜中小市值（市值<$50B 且 成长因子>7.0）："))
            for smid in smid_list[:3]:
                mkt_str = _fmt_mkt_cap(smid.get("market_cap"))
                blocks.append(("bullet",
                    f"💎 {smid['name']}({smid['ticker']}) | 市值 {mkt_str} | 成长 {smid['growth']:.1f} | "
                    f"评分 {smid['score']:.1f} | PE {smid.get('pe','?')}"))
        else:
            blocks.append(("bullet", "链内暂无满足「市值<$50B + 成长>7.0」的中小市值高潜标的"))

        blocks.append(("divider", ""))

    # ═══════════════════════════════════
    # ① 周期位置（增强：PE vs 翻倍起点PE → 安全边际%）
    # ═══════════════════════════════════
    hist_pe = cfg["hist_doubling_pe"]
    current_pe_str = f"{live_pe:.1f}x" if live_pe else "?x"
    pe_ratio_str = ""
    position_signal = ""
    safety_margin_str = ""

    if live_pe and hist_pe and hist_pe > 0:
        ratio = live_pe / hist_pe
        pe_ratio_str = f"当前PE是历史翻倍起点的{ratio:.1f}倍"
        safety_margin = (1 - ratio) * 100  # 正数=低于翻倍起点（安全），负数=高于翻倍起点
        safety_margin_str = f"安全边际: {safety_margin:+.1f}% (负值=高于翻倍起点，需增速消化)"

        if ratio <= 1.3:
            position_signal = "🎯 接近历史翻倍起点，估值有安全边际"
        elif ratio <= 2.0:
            position_signal = "🟡 高于翻倍起点但增速可消化"
        else:
            position_signal = "⚠️ 远高于翻倍起点，需要极端增速支撑"

    blocks.extend([
        ("bold", "① 周期位置"),
        ("bullet", f"当前PE={current_pe_str}, 历史翻倍起点PE={hist_pe}x"),
        ("bullet", f"{pe_ratio_str} → {safety_margin_str}" if pe_ratio_str else f"当前距翻倍起点：{'需实时数据' if not live_pe else '?%'}"),
        ("bullet", f"参考：上一轮翻倍 {cfg['prev_doubling']}"),
    ])
    if position_signal:
        blocks.append(("bullet", position_signal))

    # ── ② 供给-需求缺口（增强：缺口方向） ──
    gap = cfg["gap_pct"]
    gap_direction = cfg.get("gap_direction", "")
    gap_str = f"缺口>{gap}%" if gap > 0 else "供需基本平衡"
    blocks.extend([
        ("bold", "② 供给-需求缺口"),
        ("bullet", f"供给端：{cfg['supply']}"),
        ("bullet", f"需求端：{cfg['demand']}"),
        ("bullet", f"缺口：当前{gap_str}"),
    ])
    if gap_direction:
        direction_emoji = "📈" if "扩大" in gap_direction else "📉" if "缩小" in gap_direction or "收窄" in gap_direction else "➡️"
        blocks.append(("bullet", f"缺口方向: {direction_emoji} {gap_direction}"))

    # ── ③ 催化剂时间线 ──
    cat_lines = [f"▸ {c}" for c in cfg["catalysts"]]
    blocks.append(("bold", "③ 催化剂时间线（未来3个月）"))
    for cl in cat_lines:
        blocks.append(("bullet", cl))

    # ── ④ 关键假设 ──
    ah_lines = [f"假设{i+1}: {h}" for i, h in enumerate(cfg["assumption_hold"])]
    blocks.append(("bold", "④ 关键假设（逻辑成立的条件）"))
    for ah in ah_lines:
        blocks.append(("bullet", ah))
    blocks.append(("bullet", f"破灭重估: {cfg['assumption_break']}"))

    # ── ⑤ 面基框架标注 ──
    blocks.extend([
        ("bold", "⑤ 面基框架标注"),
        ("bullet", f"E7/E84 中观四层次 → 利润池阶段: {cfg['profit_pool']}"),
        ("bullet", f"E124 DCF → {cfg['dcf_tv']}"),
        ("bullet", f"Perez阶段: {cfg['perez_stage']}"),
        ("bullet", f"相关期数: {cfg['mianji_refs']}"),
    ])

    # ── ⑥ A股利润池排序（LDS核心：找利润率最高的环节）──
    a_pool = cfg.get("a_profit_pool", [])
    a_avoid = cfg.get("a_avoid", "")
    if a_pool and is_active:
        blocks.append(("bold", "🇨🇳 A股利润池映射（按毛利率排序）"))
        for rank, item in enumerate(a_pool, 1):
            code = item["code"]
            name = item["name"]
            env = item["env"]
            roe_ref = item.get("roe_ref")
            why = item.get("why", "")
            roe_str = f"ROE参考~{roe_ref}%" if roe_ref else ""
            price_info = ""
            try:
                from investment_system.data.data_layer import get_stock_daily
                d = get_stock_daily(code, 3)
                if not d.empty:
                    px = float(d.iloc[-1]["close"])
                    chg = float((d.iloc[-1]["close"] / d.iloc[-2]["close"] - 1) * 100) if len(d) >= 2 else 0
                    arrow = "🔺" if chg > 0 else "🔻"
                    price_info = f" ¥{px:.2f} {arrow}{chg:+.1f}%"
            except Exception:
                pass
            blocks.append(("bullet",
                f"#{rank} {name}({code}){price_info} | {env} | {roe_str} | {why}"
            ))
        if a_avoid:
            blocks.append(("bullet", f"❌ 回避: {a_avoid}"))

    w.write(doc_id, blocks)

# ═══════════════════════════════════
# 板块 5: 多因子新票发现（A/HK/US三市场独立通道+中小市值）
# ═══════════════════════════════════

def _build_a_channel(w, doc_id, scanner, exclude_sectors=None):
    """A股 Top Picks — 独立因子通道（质量+估值+动量+LDS板块偏好）"""
    if exclude_sectors is None:
        exclude_sectors = []
    w.write(doc_id, [("h3", "🇨🇳 A股 Top Picks（质量+估值+动量+LDS板块偏好）")])
    try:
        a_picks = scanner.scan_market(top_n=50)
    except Exception:
        try:
            a_picks = scanner.scan_market("small_mid", top_n=50)
        except Exception:
            w.write(doc_id, [("text", "⚠️ A股扫描失败")])
            return
    
    if not a_picks:
        # fallback：直接从 WATCHLIST 核心票展示技术信号
        from investment_system.domain import WATCHLIST
        a_picks = [
            {"symbol": code, "name": info.get("name", code),
             "score": 0, "sector": info.get("chain", ""),
             "tier": info.get("tier", "")}
            for code, info in WATCHLIST.items()
            if code.isdigit() and info.get("tier") in ("核心", "底仓")
        ][:12]
        if a_picks:
            w.write(doc_id, [("text", "⚠️ 因子扫描数据不足，展示观察池核心A股票（技术信号为主）")])
        else:
            w.write(doc_id, [("text", "⚠️ A股数据暂不可用")])
            return
    
    from investment_system.output.concept_engine import get_engine
    engine = get_engine()
    
    filtered_count = 0
    shown_count = 0
    for p in a_picks:
        if shown_count >= 8:
            break
        name = p.get("name", p.get("symbol", "?"))
        code = p.get("code", p.get("symbol", "?"))
        score = p.get("score", 0)
        pe = p.get("pe")
        pe_str = f"{pe:.1f}x" if isinstance(pe, (int, float)) else "?"
        roe_raw = p.get("roe")
        roe_str = f"{roe_raw:.1f}%" if isinstance(roe_raw, (int, float)) else "?"
        rev_g = p.get("rev_growth")
        rev_str = f" 营收{rev_g:+.1f}%" if isinstance(rev_g, (int, float)) else ""
        sector = p.get("sector", "?")
        
        # 扩张期过滤防御板块
        if exclude_sectors and any(ds in str(sector) for ds in exclude_sectors):
            filtered_count += 1
            continue
        
        shown_count += 1
        chain_tag = f" | 链: {sector}" if sector and sector != "?" else ""
        
        # Kelly仓位建议
        kelly_str = ""
        try:
            kelly = engine.kelly_position(win_rate=0.55, odds=1.5)
            kelly_str = f" | 凯利仓位建议: {kelly.get('recommended_position', 0)*100:.1f}%"
        except Exception:
            pass
        
        chg = p.get("change_pct", 0) or 0
        chg_arrow = "🔺" if chg > 0 else ("🔻" if chg < 0 else "➖")
        price = p.get("price", 0)
        price_str = f"¥{price:.2f}" if price else ""

        roe_num = roe_raw if isinstance(roe_raw, (int, float)) else None
        rev_num = p.get("rev_growth") if isinstance(p.get("rev_growth"), (int, float)) else None

        lds_checks = []
        if roe_num is not None:
            lds_checks.append("✅ROE" if roe_num >= 15 else "⚠️ROE低")
        if rev_num is not None:
            lds_checks.append("✅增速" if rev_num >= 20 else "⚠️增速低")
        lds_tag = " [" + " ".join(lds_checks) + "]" if lds_checks else ""

        pe_pct = p.get("pe_percentile")
        pe_level = p.get("pe_level", "")
        pe_pct_str = f" {pe_level}({pe_pct:.0f}%分位)" if pe_pct is not None else ""

        vol_sig = p.get("vol_signal", "")
        vol_str = f" | {vol_sig}" if vol_sig and vol_sig != "➖量能平稳" else ""

        roe_trend = p.get("roe_trend")
        roe_trend_str = ""
        if roe_trend is not None:
            if roe_trend > 2:
                roe_trend_str = " ROE↑趋升"
            elif roe_trend < -2:
                roe_trend_str = " ROE↓趋降"

        fcf = p.get("fcf_亿")
        fcf_str = f" FCF{fcf:+.1f}亿" if fcf is not None else ""

        w.write(doc_id, [("bullet",
            f"{name}({code}) {price_str} {chg_arrow}{chg:+.2f}%: "
            f"评分{score:.1f} | PE {pe_str}{pe_pct_str} | ROE {roe_str}{roe_trend_str}{rev_str}{fcf_str}"
            f"{lds_tag}{vol_str}{chain_tag}{kelly_str}"
        )])
    
    if exclude_sectors:
        w.write(doc_id, [("text", f"⚡ 已过滤 {filtered_count} 只防御板块标的（{'/'.join(exclude_sectors)}），聚焦进攻逻辑")])

def _build_a_smallmid_channel(w, doc_id, scanner, exclude_sectors=None):
    """A股 中小市值 Top 5（市值<$30B独立通道）"""
    if exclude_sectors is None:
        exclude_sectors = []
    w.write(doc_id, [("h3", "🇨🇳 A股 中小市值 Top 5（市值<$30B独立通道）")])
    try:
        all_picks = scanner.scan_market(top_n=80)
    except Exception:
        try:
            all_picks = scanner.scan_market("small_mid", top_n=80)
        except Exception:
            w.write(doc_id, [("text", "⚠️ 中小市值扫描失败")])
            return
    
    if not all_picks:
        w.write(doc_id, [("text", "⚠️ 无入选")])
        return
    
    # 尝试获取市值信息，无确切数据时用价格×成交量估算
    small_mid_candidates = []
    for p in all_picks:
        symbol = p.get("symbol", "")
        # 尝试从data_layer获取市值
        mkt_cap = None
        try:
            from investment_system.data.data_layer import get_stock_daily
            daily = get_stock_daily(symbol, 20)
            if not daily.empty and "close" in daily.columns and len(daily) >= 5:
                avg_vol = daily.get("volume", pd.Series()).tail(5).mean() if "volume" in daily.columns else 0
                price = float(daily["close"].iloc[-1])
                # A股粗略市值估算：价格×成交量×行业系数(1500-3000倍)
                mkt_cap = price * avg_vol * 1500 / 1e8 if avg_vol and avg_vol > 0 else None
        except Exception:
            pass
        if mkt_cap is None:
            mkt_cap = 999  # fallback
        p["_est_mkt_cap"] = mkt_cap
        small_mid_candidates.append(p)
    
    # 按市值升序（小的优先），结合评分
    small_mid_candidates.sort(key=lambda x: (x.get("_est_mkt_cap", 999), -x.get("score", 0)))
    
    count = 0
    for p in small_mid_candidates:
        if count >= 5:
            break
        name = p.get("name", p.get("symbol", "?"))
        code = p.get("code", p.get("symbol", "?"))
        score = p.get("score", 0)
        pe = p.get("pe", "?")
        mkt_cap = p.get("_est_mkt_cap")
        mkt_str = f"{mkt_cap:.0f}亿" if mkt_cap and isinstance(mkt_cap, (int, float)) and mkt_cap != 999 else "?"
        sector = p.get("sector", "?")
        
        # 扩张期过滤防御板块
        if exclude_sectors and any(ds in str(sector) for ds in exclude_sectors):
            continue
        
        chain_tag = f" | 链: {sector}" if sector and sector != "?" else ""
        
        w.write(doc_id, [("bullet", f"{name}({code}): 评分 {score:.1f} | 市值≈{mkt_str} | PE {pe}{chain_tag}")])
        count += 1

def _build_us_channel(w, doc_id):
    """美股 Top Picks — 独立因子通道（ROE/盈利动量/Nick四问/空头/PE折价）"""
    w.write(doc_id, [("h3", "🇺🇸 美股 Top Picks（ROE/盈利动量/Nick四问/PE折价）")])
    
    from investment_system.output.concept_engine import ConceptEngine, StockSnapshot, get_engine
    engine = get_engine()
    
    try:
        us_picks = scan_us_stocks(max_stocks=50)
    except Exception:
        w.write(doc_id, [("text", "⚠️ 美股扫描失败")])
        return
    
    if not us_picks:
        w.write(doc_id, [("text", "⚠️ 美股扫描无结果")])
        return
    
    for p in us_picks[:8]:
        name = p.get("name", "?")
        symbol = p.get("symbol", "?")
        score = p.get("score", 0)
        pe = p.get("pe", "?")
        pe_str = f"{pe:.1f}" if isinstance(pe, (int, float)) else str(pe)
        roe_raw = p.get("roe")
        roe_str = f"{roe_raw*100:.0f}%" if isinstance(roe_raw, (int, float)) and abs(roe_raw) < 10 else (
            f"{roe_raw:.1f}" if isinstance(roe_raw, (int, float)) else "?")
        mkt_cap = p.get("market_cap")
        mkt_str = fmt_usd(mkt_cap)
        chain = p.get("chain", "?")
        chain_tag = f" | 链: {chain}" if chain else ""
        
        # Nick四问
        nick_str = ""
        try:
            factors = p.get("factors", {})
            nick = engine.nick_four_questions(StockSnapshot(
                symbol=symbol,
                eps_growth=(p.get("earnings_growth") or 0) * 100 if p.get("earnings_growth") and abs(p.get("earnings_growth", 0)) < 1 else p.get("earnings_growth"),
                price=p.get("price"),
                ma50=p.get("50d_avg"),
                ma200=p.get("200d_avg"),
                analyst_target=p.get("target_mean"),
                short_float=p.get("short_ratio"),
                beta=p.get("beta"),
            ))
            nick_score = nick.get("total_score", 0)
            nick_signal = nick.get("signal", "?")
            nick_str = f" | Nick: {nick_score}/4({nick_signal})"
        except Exception:
            nick_str = ""
        
        w.write(doc_id, [("bullet", f"{name}({symbol}): 评分 {score:.1f} | PE {pe_str} | ROE {roe_str} | {mkt_str}{nick_str}{chain_tag}")])

def _build_hk_channel(w, doc_id):
    """港股 Top Picks — 跨境PE折价+南向资金+地缘风险溢价"""
    w.write(doc_id, [("h3", "🇭🇰 港股 Top Picks（跨境PE折价+南向资金+地缘风险溢价）")])
    
    from investment_system.output.concept_engine import ConceptEngine, StockSnapshot, get_engine
    engine = get_engine()
    
    try:
        hk_picks = scan_hk_stocks(max_stocks=24)
    except Exception:
        w.write(doc_id, [("text", "⚠️ 港股扫描失败")])
        return
    
    if not hk_picks:
        w.write(doc_id, [("text", "⚠️ 港股扫描无结果")])
        return
    
    # 计算PE折价：港股PE vs 同类美股/A股PE
    us_pe_map = {}  # 缓存美股同行业PE用于折价计算
    try:
        us_scan = scan_us_stocks(max_stocks=20)
        for u in us_scan:
            chain = u.get("chain", "")
            if chain and u.get("pe"):
                if chain not in us_pe_map:
                    us_pe_map[chain] = []
                us_pe_map[chain].append(u["pe"])
        for k in us_pe_map:
            us_pe_map[k] = sum(us_pe_map[k]) / len(us_pe_map[k]) if us_pe_map[k] else None
    except Exception:
        pass
    
    for p in hk_picks[:6]:
        name = p.get("name", "?")
        symbol = p.get("symbol", "?")
        score = p.get("score", 0)
        pe = p.get("pe")
        pe_str = f"{pe:.1f}" if isinstance(pe, (int, float)) else str(pe)
        mkt_cap = p.get("market_cap")
        mkt_str = fmt_usd(mkt_cap)
        chain = p.get("chain", "")
        
        # PE折价计算
        discount_str = ""
        tag = ""
        if isinstance(pe, (int, float)) and pe > 0:
            if chain and chain in us_pe_map and us_pe_map[chain]:
                us_pe_avg = us_pe_map[chain]
                if us_pe_avg > 0:
                    discount = (1 - pe / us_pe_avg) * 100
                    discount_str = f" | PE折价: {discount:+.0f}%"
                    tag = "🔻 地缘折价" if discount > 20 else ("📈 修复中" if discount < 0 else "")
            else:
                if pe < 12:
                    tag = "🔻 地缘折价"
                elif pe < 18:
                    tag = "🟡 中性"
        
        tag_str = f" | {tag}" if tag else ""
        
        # 尝试Kelly
        kelly_str = ""
        try:
            kelly = engine.kelly_position(win_rate=0.50, odds=1.8)
            kelly_str = f" | 凯利: {kelly.get('recommended_position', 0)*100:.1f}%"
        except Exception:
            pass
        
        w.write(doc_id, [("bullet", f"{name}({symbol}): 评分 {score:.1f} | PE {pe_str}{discount_str}{tag_str}{kelly_str} | {mkt_str}")])

def _calc_tech_signal(closes: list) -> dict:
    if not closes or len(closes) < 5:
        return {}
    import numpy as np
    c = np.array([float(x) for x in closes if x])
    if len(c) < 5:
        return {}
    signal = {}
    signal["price"] = round(float(c[-1]), 2)
    signal["chg"] = round((c[-1] / c[-2] - 1) * 100, 2) if len(c) >= 2 else 0

    if len(c) >= 14:
        diff = np.diff(c[-15:])
        gains = np.where(diff > 0, diff, 0)
        losses = np.where(diff < 0, -diff, 0)
        avg_g = np.mean(gains) if np.mean(gains) > 0 else 1e-10
        avg_l = np.mean(losses) if np.mean(losses) > 0 else 1e-10
        rsi = 100 - 100 / (1 + avg_g / avg_l)
        signal["rsi"] = round(float(rsi), 1)
        if rsi > 70:
            signal["rsi_signal"] = "⚠️超买"
        elif rsi < 30:
            signal["rsi_signal"] = "💡超卖"
        else:
            signal["rsi_signal"] = "✅健康"

    if len(c) >= 20:
        ma20 = float(np.mean(c[-20:]))
        signal["ma20"] = round(ma20, 2)
        signal["ma20_dev"] = round((c[-1] / ma20 - 1) * 100, 1)
        signal["above_ma20"] = c[-1] > ma20

    if len(c) >= 60:
        ma60 = float(np.mean(c[-60:]))
        signal["ma60"] = round(ma60, 2)
        signal["ma60_dev"] = round((c[-1] / ma60 - 1) * 100, 1)
        signal["above_ma60"] = c[-1] > ma60

    if len(c) >= 35:
        s = list(c)
        from statistics import mean
        ema12 = s[-1]
        ema26 = s[-1]
        for v in s[-35:]:
            ema12 = ema12 * (1 - 2/13) + v * (2/13)
            ema26 = ema26 * (1 - 2/27) + v * (2/27)
        macd = ema12 - ema26
        signal["macd_positive"] = macd > 0

    score = 5.0
    if signal.get("above_ma20"):
        score += 1.0
    if signal.get("above_ma60"):
        score += 1.5
    if signal.get("macd_positive"):
        score += 1.0
    rsi_val = signal.get("rsi", 50)
    if 40 <= rsi_val <= 65:
        score += 1.5
    elif rsi_val > 70:
        score -= 1.0
    signal["tech_score"] = round(min(10, max(1, score)), 1)

    badges = []
    if signal.get("above_ma60") and signal.get("macd_positive"):
        badges.append("🟢趋势向上")
    elif not signal.get("above_ma20"):
        badges.append("🔴均线下方")
    if signal.get("rsi_signal"):
        badges.append(signal["rsi_signal"])
    signal["badges"] = " ".join(badges) if badges else "⚪中性"

    return signal


def _fetch_watchlist_prices(codes: list) -> dict:
    prices = {}
    a_codes = [c for c in codes if c.isdigit() and len(c) == 6]
    other_codes = [c for c in codes if c not in a_codes]

    if a_codes:
        try:
            import baostock as bs
            lg = bs.login()
            if lg.error_code == "0":
                for code in a_codes[:30]:
                    sym = f"sh.{code}" if code.startswith(("5", "6")) else f"sz.{code}"
                    rs = bs.query_history_k_data_plus(
                        sym, "date,close,pctChg",
                        start_date=(datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d"),
                        end_date=datetime.now().strftime("%Y-%m-%d"),
                        frequency="d",
                    )
                    rows = []
                    while rs.next():
                        rows.append(rs.get_row_data())
                    if rows:
                        closes = [r[1] for r in rows if r[1]]
                        tech = _calc_tech_signal(closes)
                        if tech:
                            r = rows[-1]
                            try:
                                tech["chg"] = float(r[2]) if r[2] else tech.get("chg", 0)
                                prices[code] = tech
                            except (ValueError, IndexError):
                                pass
                bs.logout()
        except Exception:
            pass

    if other_codes:
        try:
            from investment_system.data.yf_data_layer import get_current_price
            import time
            for code in other_codes[:15]:
                try:
                    p = get_current_price(code)
                    if p:
                        prices[code] = {"price": round(float(p), 2), "chg": None}
                    time.sleep(0.3)
                except Exception:
                    pass
        except Exception:
            pass

    return prices


def _build_watchlist_section(w, doc_id):
    try:
        from investment_system import config as _cfg
        watchlist = getattr(_cfg, "WATCHLIST", {})
        if not watchlist:
            return
        w.write(doc_id, [("h3", "📋 核心观察池（含今日行情）")])

        tiers = {"核心": [], "底仓": [], "关注": [], "追踪": []}
        for code, info in watchlist.items():
            tiers.setdefault(info.get("tier", "关注"), []).append((code, info))

        all_codes = list(watchlist.keys())
        prices = _fetch_watchlist_prices(all_codes)

        tier_icons = {"核心": "⭐", "底仓": "🏛️", "关注": "👁️", "追踪": "📡"}
        for tier_name in ["核心", "底仓", "关注", "追踪"]:
            items = tiers.get(tier_name, [])
            if not items:
                continue
            w.write(doc_id, [("bold", f"{tier_icons.get(tier_name,'')} {tier_name}标的")])
            for code, info in items[:10]:
                name = info.get("name", code)
                chain = info.get("chain", "")
                focus = info.get("focus", "")[:45]
                pd_info = prices.get(code, {})
                price = pd_info.get("price")
                chg = pd_info.get("chg")

                price = pd_info.get("price")
                chg = pd_info.get("chg")
                tech_score = pd_info.get("tech_score")
                badges = pd_info.get("badges", "")
                rsi = pd_info.get("rsi")
                ma60_dev = pd_info.get("ma60_dev")

                price_str = f"¥{price:.2f}" if isinstance(price, (int, float)) else "—"
                if chg is not None:
                    arrow = "🔺" if chg > 0 else ("🔻" if chg < 0 else "➖")
                    chg_str = f" {arrow}{chg:+.2f}%"
                else:
                    chg_str = ""

                signal_parts = []
                if tech_score is not None:
                    signal_parts.append(f"技术{tech_score:.0f}分")
                if rsi is not None:
                    signal_parts.append(f"RSI{rsi:.0f}")
                if ma60_dev is not None:
                    signal_parts.append(f"偏MA60{ma60_dev:+.1f}%")
                if badges:
                    signal_parts.append(badges)
                signal_str = f" | {' '.join(signal_parts)}" if signal_parts else ""

                w.write(doc_id, [("bullet",
                    f"{name}({code}) {price_str}{chg_str}{signal_str} [{chain}]: {focus}"
                )])
    except Exception as e:
        w.write(doc_id, [("bullet", f"⚠️ 观察池加载失败: {str(e)[:60]}")])


def _build_opportunity_themes_section(w, doc_id):
    try:
        from investment_system import config as _cfg
        themes = getattr(_cfg, "OPPORTUNITY_THEMES", {})
        if not themes:
            return
        w.write(doc_id, [("h3", "💡 链趋势挖掘方向（基于产业瓶颈逻辑）")])
        w.write(doc_id, [("quote", "挖掘逻辑：找产业链上的瓶颈环节 → 瓶颈被解决时利润最大 → 中小市值优先（LDS翻倍逻辑）")])

        for theme_name, theme in themes.items():
            logic = theme.get("logic", "")[:100]
            bottleneck = theme.get("bottleneck", "")[:80]
            catalysts = theme.get("key_catalysts", [])
            a_stocks = theme.get("a_stocks_focus", [])
            us_stocks = theme.get("us_stocks_focus", [])
            perez = theme.get("perez_stage", "")

            cat_str = " | ".join(catalysts[:2]) if catalysts else ""
            a_str = " / ".join(a_stocks[:4]) if a_stocks else "暂无A股纯正标的"
            us_str = " / ".join(us_stocks[:3]) if us_stocks else ""

            lines = [
                f"📍 逻辑: {logic}",
                f"🔴 瓶颈: {bottleneck}",
            ]
            if perez:
                lines.append(f"📊 Perez阶段: {perez}")
            lines.append(f"🇨🇳 A股关注: {a_str}")
            if us_str:
                lines.append(f"🇺🇸 美股关注: {us_str}")
            if cat_str:
                lines.append(f"⚡ 近期催化剂: {cat_str}")

            w.write(doc_id, [("bold", f"▶ {theme_name}")])
            for line in lines:
                w.write(doc_id, [("bullet", line)])
    except Exception as e:
        w.write(doc_id, [("bullet", f"⚠️ 挖掘主题加载失败: {str(e)[:40]}")])


def _build_state_fund_section(w, doc_id):
    """国家队资金追踪：社保/汇金/中证金融持仓方向"""
    try:
        import akshare as ak
        w.write(doc_id, [("h3", "🏛️ 国家队资金信号")])
        w.write(doc_id, [("quote",
            "国家队（社保/汇金/中证金融）=A股最大逆向买手；重仓方向=政策背书+安全边际。"
            "季报滞后45天，但方向价值极高。"
        )])

        try:
            sector_flow = ak.stock_sector_fund_flow_rank(indicator="5日", sector_type="行业资金流")
            if not sector_flow.empty:
                top5 = sector_flow.head(5)
                w.write(doc_id, [("bold", "近5日行业资金净流入 Top5（国家队惯用板块确认）")])
                for _, row in top5.iterrows():
                    name = str(row.iloc[0]) if len(row) > 0 else "?"
                    flow = str(row.iloc[1]) if len(row) > 1 else "?"
                    w.write(doc_id, [("bullet", f"{name}: {flow}")])
        except Exception:
            w.write(doc_id, [("bullet", "⚠️ 行业资金流数据暂不可用")])

        w.write(doc_id, [("bold", "国家队惯用重仓方向（基于历史季报规律）")])
        STATE_FUND_FAVORITES = [
            ("大型银行（招商/工商/建设）", "高股息+低估值，托底核心", "600036/601398/601939"),
            ("公用事业（长江电力/华能）", "稳定分红，防御核心仓", "600900/600011"),
            ("央企高股息（中石化/神华）", "过热期配置+稳定分红", "600028/601088"),
            ("A股宽基ETF（510300/510050）", "直接购买ETF托底大盘", "510300/510050"),
            ("半导体设备（北方华创/中微）", "政策战略资产，大基金三期重点", "688041/688012"),
        ]
        for name, logic, codes in STATE_FUND_FAVORITES:
            w.write(doc_id, [("bullet", f"【{name}】{logic} | 关注: {codes}")])

        w.write(doc_id, [("bullet",
            "📌 AKShare追踪接口: ak.stock_institute_hold_detail_em(stock='600036', quarter='20241')"
            " → 查询特定股票的机构持仓季报"
        )])
    except Exception as e:
        w.write(doc_id, [("bullet", f"⚠️ 国家队信号加载失败: {str(e)[:50]}")])


def build_discovery_section(w, doc_id, scanner, macro):
    w.write(doc_id, [("divider", ""), ("h2", "十、🔍 多因子新票发现")])

    regime = macro.get('regime', '')
    exclude_sectors = []
    if regime == '扩张期':
        exclude_sectors = ['白酒', '红利', '公用事业', '消费必需品', '新能源']
        w.write(doc_id, [("quote", "⚡ 扩张期逻辑：聚焦科技/半导体/AI/国产替代/高端制造，已自动过滤防御品种")])

    _build_a_channel(w, doc_id, scanner, exclude_sectors=exclude_sectors)
    _build_a_smallmid_channel(w, doc_id, scanner, exclude_sectors=exclude_sectors)
    _build_us_channel(w, doc_id)
    _build_hk_channel(w, doc_id)

    _build_watchlist_section(w, doc_id)
    _build_opportunity_themes_section(w, doc_id)
    _build_state_fund_section(w, doc_id)

    w.write(doc_id, [("text", w.ref("三、多因子引擎")), ("text", w.ref("四、找票执行·产业链定位"))])

# ═══════════════════════════════════
# 板块 6: 政经要闻（结构化摘要+链影响标注）
# ═══════════════════════════════════

# 链→影响方向 关键词映射（匹配10链结构）
_CHAIN_IMPACT_KEYWORDS = {
    "GPU/AI芯片": ["AI", "芯片", "GPU", "NVIDIA", "英伟达", "半导体", "算力", "Capex", "Blackwell", "Rubin"],
    "先进制程+封装": ["制程", "CoWoS", "先进封装", "台积电", "TSMC", "3nm", "2nm", "光刻"],
    "存储/HBM": ["存储", "HBM", "美光", "三星", "SK海力士", "HBM3E", "HBM4"],
    "AI电力": ["电力", "核电", "数据中心", "电网", "Vistra", "能源", "PPA", "NRC"],
    "AI网络+云": ["网络", "交换机", "光模块", "800G", "Arista", "云计算", "AWS", "数据中心REIT"],
    "AI应用/Agent": ["Copilot", "Agent", "SaaS", "AI应用", "GPT", "Claude", "Llama", "企业AI"],
    "网络安全/国产替代": ["安全", "网安", "CRWD", "Palo Alto", "信创", "国产替代", "脱钩", "数据安全"],
    "机器人": ["机器人", "Optimus", "人形", "自动化", "特斯拉Optimus"],
    "消费电子": ["苹果", "iPhone", "手机", "换机", "小米", "消费电子", "WWDC"],
    "新能源车": ["新能源", "电动车", "比亚迪", "特斯拉", "电池", "宁德", "Robotaxi"],
    "地缘/关税": ["关税", "脱钩", "制裁", "台海", "中美", "出口管制", "实体清单"],
    "宏观/利率": ["美联储", "加息", "降息", "CPI", "PCE", "非农", "央行", "通胀", "通缩"],
}

def _classify_news_impact(title: str) -> list:
    """根据标题关键词标注影响链和方向"""
    results = []
    title_lower = title.lower()
    for chain, keywords in _CHAIN_IMPACT_KEYWORDS.items():
        for kw in keywords:
            if kw.lower() in title_lower:
                # 判断方向
                direction = "→"
                bearish_words = ["跌", "暴跌", "崩", "危机", "衰退", "加税", "制裁", "脱钩", "下行", "低于预期"]
                bullish_words = ["涨", "大涨", "突破", "利好", "复苏", "反弹", "高于预期", "降息", "宽松"]
                for bw in bearish_words:
                    if bw in title_lower:
                        direction = "↓"
                        break
                for bw in bullish_words:
                    if bw in title_lower:
                        direction = "↑"
                        break
                results.append(f"[{chain}]{direction}")
                break
    return results if results else ["[综合]→"]

def _try_llm_summary(news_items: list) -> str:
    """尝试用LLM对新闻做结构化总结，不可用时返回None"""
    try:
        import os, json, urllib.request
        api_key = os.environ.get("ARK_API_KEY") or os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        
        titles = [item.get("title", "")[:200] for item in news_items[:15]]
        prompt = f"""请用3-5段话总结以下今日财经新闻要点，每段格式：
[N] [摘要标题] → 影响链: [产业链名称] → 方向: [↑利好/↓利空/→中性]
最后加一段综合判断。

新闻列表：
{chr(10).join(f"{i+1}. {t}" for i, t in enumerate(titles))}"""
        
        # 尝试调用LLM (支持多种API格式)
        base_url = os.environ.get("ARK_BASE_URL", "https://api.ark.cn/v1")
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps({
                "model": os.environ.get("LLM_MODEL", "deepseek-v3"),
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 600,
                "temperature": 0.3,
            }).encode(),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return resp["choices"][0]["message"]["content"]
    except Exception:
        return None

def build_news_section(w, doc_id):
    w.write(doc_id, [("divider", ""), ("h2", "六、📰 政经要闻（结构化摘要+链影响）")])
    
    news_items = []
    try:
        from investment_system.domain.news_fetcher import fetch_news
        news = fetch_news()
        if news and news.get("items"):
            news_items = news.get("items", [])
    except Exception:
        pass
    
    if not news_items:
        w.write(doc_id, [("text", "⚠️ 今日无重大新闻信号或新闻模块未就绪")])
        w.write(doc_id, [("text", w.ref("十六、全球经济格局"))])
        return
    
    # ── 尝试LLM总结 ──
    llm_summary = _try_llm_summary(news_items)
    
    if llm_summary:
        w.write(doc_id, [("h3", "📰 今日要点（LLM总结）")])
        # 按段落拆分
        for line in llm_summary.strip().split("\n"):
            line = line.strip()
            if line:
                w.write(doc_id, [("bullet", line)])
    else:
        # ── 无LLM：结构化标注每条新闻 ──
        w.write(doc_id, [("h3", "📰 今日要点（结构化标注）")])
        
        # 聚合同链新闻
        chain_groups = {}
        for item in news_items[:12]:
            title = item.get("title", "")[:150]
            source = item.get("source", "")
            impacts = _classify_news_impact(title)
            
            for impact in impacts:
                chain_key = impact.split("]")[0].replace("[", "") if "]" in impact else "综合"
                if chain_key not in chain_groups:
                    chain_groups[chain_key] = []
                chain_groups[chain_key].append((title, impact, source))
        
        # 按链输出
        count = 0
        for chain_name, items in chain_groups.items():
            if count >= 8:
                break
            chain_title = f"🔗 {chain_name}链" if chain_name != "综合" else "🌐 综合"
            titles_list = [f"{imp} {title} — {src}" for title, imp, src in items[:3]]
            combined = "；".join(titles_list)
            w.write(doc_id, [("bullet", f"{chain_title}: {combined}")])
            count += 1
    
    # ── 综合判断 ──
    bearish_count = sum(1 for item in news_items[:15] 
                        if any(w in (item.get("title", "") or "").lower() 
                              for w in ["跌", "暴跌", "崩", "危机", "衰退", "制裁", "低于预期"]))
    bullish_count = sum(1 for item in news_items[:15]
                        if any(w in (item.get("title", "") or "").lower()
                              for w in ["涨", "突破", "利好", "复苏", "反弹", "高于预期", "降息"]))
    
    if bullish_count > bearish_count:
        sentiment = f"🟢 今日偏多（利好{bullish_count}条 vs 利空{bearish_count}条）"
    elif bearish_count > bullish_count:
        sentiment = f"🔴 今日偏空（利空{bearish_count}条 vs 利好{bullish_count}条）"
    else:
        sentiment = "🟡 今日中性，信号混杂"
    
    w.write(doc_id, [
        ("bold", f"综合判断: {sentiment}"),
        ("text", w.ref("十六、全球经济格局")),
    ])

# ═══════════════════════════════════
# 板块 7: 重点票追踪
# ═══════════════════════════════════
def build_tracking_section(w, doc_id, scanner, macro, section_prefix="七"):
    w.write(doc_id, [("divider", ""), ("h2", f"{section_prefix}、👀 重点票追踪")])
    try:
        from investment_system.output.shadow_account import get_shadow_summary, check_stops
        summary = get_shadow_summary()
        positions = summary.get("positions", [])
        alerts = check_stops()
        alert_symbols = {a["symbol"] for a in alerts}

        if not positions:
            w.write(doc_id, [("text", "📭 模拟盘暂无持仓 — 使用 shadow_account.entry() 记录交易")])
        else:
            w.write(doc_id, [("bold", f"持仓 {len(positions)} 只 | 总估值 ¥{summary.get('total_value', 0):,.0f}")])
            for pos in positions:
                sym = pos["symbol"]
                name = pos.get("name", sym)
                entry_p = pos.get("entry", 0)
                current_p = pos.get("current", entry_p)
                chg = pos.get("change", 0)
                stop = entry_p * 0.92
                t1 = entry_p * 1.15
                t2 = entry_p * 1.30
                status = pos.get("status", "")
                alert_tag = " 🚨止损!" if sym in alert_symbols else ""
                w.write(doc_id, [("bullet",
                    f"{status}{alert_tag} {name}({sym}) 买入¥{entry_p:.2f} → 现¥{current_p:.2f} "
                    f"({chg:+.1f}%) | 止损¥{stop:.2f} | 止盈¥{t1:.2f}/¥{t2:.2f}"
                )])

        if alerts:
            w.write(doc_id, [("bold", f"⚠️ 触发信号 {len(alerts)} 条：")])
            for a in alerts:
                kind = "🔴 止损" if a["type"] == "STOP_LOSS" else "🟡 止盈T1" if a["type"] == "TAKE_PROFIT_T1" else "🟢 止盈T2"
                val = a.get("loss") or a.get("profit", 0)
                w.write(doc_id, [("bullet", f"{kind} {a['name']}({a['symbol']}) 浮{val:+.1f}%")])

    except Exception as e:
        w.write(doc_id, [("text", f"⚠️ 持仓追踪加载失败: {str(e)[:60]}")])

    w.write(doc_id, [("text", w.ref("五、风控监控·四重确认"))])

# ═══════════════════════════════════
# 板块 8: 调仓建议
# ═══════════════════════════════════
def build_action_section(w, doc_id, macro, section_prefix="八"):
    regime = macro.get("regime", "?")
    dual_gate = macro.get("dual_gate", {})
    dual_action = dual_gate.get("action", "")
    macro_gate = dual_gate.get("macro_gate", "")
    trend_gate = dual_gate.get("trend_gate", "")
    dual_closed = dual_action in ("观望为主", "空仓等待", "减仓观望", "左侧试探") or \
                  (macro_gate in ("红灯", "黄灯") and trend_gate in ("红灯", "黄灯"))
    bw_q = macro.get("bw_quadrant", "")
    credit_src = macro.get("credit_signal_source", "")

    regime_to_favor = {
        "扩张期": ("科技/半导体/AI/国产替代/高端制造", "公用事业/消费必需品/地产"),
        "复苏期": ("消费/金融/地产/汽车 + 国产替代(政策独立驱动)", "能源/材料"),
        "过热期": ("能源/材料/大宗商品/银行", "科技/消费/地产"),
        "衰退期": ("公用事业/医药/消费必需品/黄金/长债", "科技/金融/地产/工业"),
    }
    favor, avoid = regime_to_favor.get(regime, ("均衡配置", "无明显回避"))

    bw_asset_hint = {
        "Q1": "商品>黄金>TIPS>股票>现金>长债",
        "Q2": "股票>信用债>商品>国债 ← 最优象限",
        "Q3": "黄金>TIPS>商品>现金 ← 滞胀最难",
        "Q4": "长期国债(TLT/159926)>防御股>黄金 ← 增配债券",
    }
    bw_key = bw_q[:2] if bw_q else ""
    bw_hint = bw_asset_hint.get(bw_key, "")

    w.write(doc_id, [("divider", ""), ("h2", f"{section_prefix}、⚖️ 调仓建议")])

    w.write(doc_id, [("h3", "宏观基调")])
    w.write(doc_id, [("bullet", f"当前象限: {regime} → 偏好: {favor}")])
    w.write(doc_id, [("bullet", f"回避: {avoid}")])
    if credit_src:
        w.write(doc_id, [("bullet", f"信用判断来源: {credit_src}")])
    if bw_hint:
        w.write(doc_id, [("bullet", f"桥水{bw_key}象限资产排序: {bw_hint}")])

    if dual_closed:
        w.write(doc_id, [("bold", "🔒 双门关闭 → 防御模式")])
        w.write(doc_id, [("bullet", "不开新仓 | 持有票检查8%止损线 | 不追高不加仓")])
        if "Q4" in bw_q:
            w.write(doc_id, [("bullet",
                "象限4(增长↓通胀↓)建议: 可建长债底仓(TLT/159926/511010)，黄金维持底仓，"
                "等待CPI回升至1.5%+再考虑股票"
            )])
        cpi = macro.get("macro_data", {}).get("cpi")
        trend = macro.get("trend_temp", "?")
        cpi_need = "1.5%+" if cpi is not None else "?"
        w.write(doc_id, [("bullet",
            f"双门转绿条件: CPI回升至{cpi_need} (当前={cpi}%) + 趋势温度回升至温 (当前={trend})"
        )])
    else:
        w.write(doc_id, [("bold", "✅ 双门开启 → 正常操作")])
        w.write(doc_id, [("bullet", f"优先进攻: {favor}")])

    w.write(doc_id, [
        ("h3", "纪律检查"),
        ("bullet", "8% 硬止损：每票买入后立即设止损价 = 成本 × 0.92"),
        ("bullet", "15% 止盈减半仓 / 30% 止盈清仓"),
        ("bullet", "凯利仓位上限：每票 ≤ 总资产 2%"),
        ("bullet", "月度再平衡 + 6个月评估"),
        ("text", w.ref("六、交易纪律")),
    ])

# ═══════════════════════════════════
# 板块 9: 每日面基概念（动态激活，根据市场状态）
# ═══════════════════════════════════

def _get_market_state():
    """获取当前市场状态用于概念动态激活"""
    state = {"cpi": None, "trend": "?", "guoyun_deviation": None}
    try:
        from investment_system.analysis.macro_engine import MacroEngine
        me = MacroEngine()
        macro = me.refresh()
        md = macro.get("macro_data", {})
        state["cpi"] = md.get("cpi")
        state["trend"] = macro.get("trend_temperature", "?")
        gy = macro.get("guoyun_line", {})
        state["guoyun_deviation"] = gy.get("deviation")
    except Exception:
        pass
    return state

def _scan_high_pe_low_growth(engine):
    """扫描PE>60且增速<15%的票（E105及早离去信号）"""
    warning_list = []
    try:
        from investment_system.data.yf_data_layer import scan_us_stocks
        us = scan_us_stocks(max_stocks=30)
        for p in us[:15]:
            pe = p.get("pe")
            # 尝试获取增速
            fd = None
            try:
                from investment_system.data.yf_data_layer import get_factor_data
                fd = get_factor_data(p.get("symbol", ""))
            except Exception:
                pass
            eps_g = fd.get("earnings_growth") if fd else None
            if pe and pe > 60:
                if eps_g is not None and eps_g < 0.15:
                    warning_list.append(f"{p.get('name', p.get('symbol','?'))}(PE={pe:.0f}, 增速={eps_g*100:.0f}%)" if eps_g < 1 else f"{p.get('name', p.get('symbol','?'))}(PE={pe:.0f}, 增速={eps_g:.0f}%)")
                elif eps_g is None:
                    warning_list.append(f"{p.get('name', p.get('symbol','?'))}(PE={pe:.0f})")
        return warning_list[:5]
    except Exception:
        return []

def _scan_big_rally_stocks(engine):
    """扫描今日涨幅>15%的票（E80赚到>赚过）"""
    return []  # 需要实时数据，日报执行时通常为盘后，保留接口

def build_concept_section(w, doc_id):
    w.write(doc_id, [("divider", ""), ("h2", "九、📖 今日面基概念")])
    
    from investment_system.output.concept_engine import ConceptEngine, MacroSnapshot, get_engine
    engine = get_engine()
    
    # ── 获取市场状态 ──
    state = _get_market_state()
    cpi = state.get("cpi")
    trend = state.get("trend", "?")
    guoyun_dev = state.get("guoyun_deviation")
    
    # ── 状态摘要 ──
    status_parts = []
    if cpi is not None:
        status_parts.append(f"CPI={cpi}%")
    status_parts.append(f"趋势={trend}")
    if guoyun_dev is not None:
        status_parts.append(f"国运线偏离={guoyun_dev:+.1f}%")
    status_line = "、".join(status_parts) if status_parts else "数据暂缺"
    
    w.write(doc_id, [("text", f"基于当前市场状态（{status_line}）：")])
    
    # ═══ 🔴 当前相关概念 ═══
    w.write(doc_id, [("h3", "🔴 当前相关")])
    
    # E105 及早离去
    high_pe_list = _scan_high_pe_low_growth(engine)
    if high_pe_list:
        w.write(doc_id, [("bullet", f"E105 及早离去: PE>60且增速<15%的票今日有: {', '.join(high_pe_list)}")])
    else:
        w.write(doc_id, [("bullet", "E105 及早离去: 当前无触发信号（或数据不可用），持续监控高PE低增速标的")])
    
    # E42 周期逆向（CPI相关）
    if cpi is not None:
        if cpi < 1:
            w.write(doc_id, [("bullet", f"E42 周期逆向: 当前CPI={cpi}%（通缩压力）→ 消费/防御周期占优，周期股需等待CPI回升信号")])
        elif cpi < 2:
            w.write(doc_id, [("bullet", f"E42 周期逆向: 当前CPI={cpi}%（正常区间）→ 均衡配置，周期股中性")])
        elif cpi < 3:
            w.write(doc_id, [("bullet", f"E42 周期逆向: 当前CPI={cpi}%（上升中）→ 利好周期股（能源/材料/工业），但警惕过热")])
        else:
            w.write(doc_id, [("bullet", f"E42 周期逆向: 当前CPI={cpi}%（过热）→ LDS减仓信号！周期股虽好但宏观门已转红")])
    
    # E136 逆潮（全球化退潮）
    w.write(doc_id, [("bullet", "E136 逆潮: 全球化退潮背景下，关税/脱钩持续影响产业链。关注自主可控（半导体设备、信创）和对冲地缘（黄金、军工）")])
    
    # E94 康波定位
    try:
        kond = engine.kondratiev_position()
        w.write(doc_id, [("bullet", f"E94 康波: {kond.get('current_wave','?')}·{kond.get('current_phase','?')} → {kond.get('investment_implication','?')[:80]}")])
    except Exception:
        w.write(doc_id, [("bullet", "E94 康波: 第五轮康波萧条期(2020-2030+)，第六轮(AI主导)导入期。防御为主+小仓位布局新技术")])
    
    # ═══ 🟡 提醒概念 ═══
    w.write(doc_id, [("h3", "🟡 提醒")])
    
    # E153 凯利
    try:
        # 根据国运线偏离估算市场胜率
        win_rate = 0.55  # 默认
        if guoyun_dev is not None:
            if guoyun_dev < -10:
                win_rate = 0.65  # 超跌安全区
            elif guoyun_dev < -5:
                win_rate = 0.60  # 价值区间
            elif guoyun_dev < 5:
                win_rate = 0.55  # 中性
            else:
                win_rate = 0.45  # 过热
        kelly = engine.kelly_position(win_rate=win_rate, odds=1.5)
        w.write(doc_id, [("bullet", f"E153 凯利: 当前市场胜率≈{win_rate:.0%}，全凯利仓位={kelly.get('raw_kelly',0)*100:.1f}%，建议仓位上限={kelly.get('recommended_position',0)*100:.1f}%（单票≤2%）")])
    except Exception:
        w.write(doc_id, [("bullet", "E153 凯利/复利: 连错10次亏20%仍可继续。仓位纪律第一，单票≤2%。")])
    
    # E80 赚到>赚过
    rally_stocks = _scan_big_rally_stocks(engine)
    if rally_stocks:
        w.write(doc_id, [("bullet", f"E80 赚到>赚过: 今日涨幅>15%的票: {', '.join(rally_stocks)}，考虑兑现利润")])
    else:
        w.write(doc_id, [("bullet", "E80 赚到>赚过: 浮盈不是盈利。纪律化止盈比预测顶部更可靠。15%减半仓，30%清仓。")])
    
    # ═══ 核心概念速查 ═══
    w.write(doc_id, [("h3", "📋 核心概念速查")])
    core_concepts = [
        ("E155 五层蛋糕", "Capex→HALO→用户→应用→设备。当前AI处于Capex+HALO叠加阶段。"),
        ("E7/E84 中观四层次", "行业空间→竞争格局→链定位→公司壁垒。盯住利润率最高的环节。"),
        ("E124 DCF估值", "永续段占内在价值~50%。DCF不是精确数，是估值思想框架。"),
        ("E30/E77 贝叶斯", "每天用新信息修正先验。投资是认知的贝叶斯更新过程。"),
    ]
    for title, desc in core_concepts:
        w.write(doc_id, [("bullet", f"{title}: {desc}")])
    
    w.write(doc_id, [("text", w.ref("零、核心哲学"))])

# ═══════════════════════════════════
# 主流程
# ═══════════════════════════════════
def main():
    print("📊 面基三源融合日报 v6.1 — 全量信息·引用体系")
    print("=" * 60)
    
    # 初始化
    w = FeishuWriter()
    scanner = FactorScanner()
    macro_engine = MacroEngine()
    
    # 宏观刷新
    print("  🔄 宏观引擎...")
    macro = macro_engine.refresh()
    
    # 扫描
    print("  🔍 A股因子扫描...")
    scanner.MAX_SCAN = 20  # 日报量：20只覆盖主要板块
    scanner.scan_market(top_n=20)
    
    # 创建文档
    today = datetime.now().strftime("%Y年%m月%d日")
    title = f"📊 {SAN_YUAN_NAME}日报·{today}"
    doc_id = w.create_doc(title)
    if not doc_id:
        print("❌ 创建文档失败"); return
    
    print(f"  📄 文档: {doc_id}")
    
    # 封面
    w.write(doc_id, [
        ("bold", f"{SAN_YUAN_NAME}·日报"),
        ("text", f"日期: {datetime.now().strftime('%Y/%m/%d')} | v6.1 全量·引用体系"),
        ("text", "结构：LDS双门→全球市场→ETF→房价→10链→新票→新闻→追踪→调仓→概念"),
        ("text", f"📋 所有静态框架引用 [知识体系总纲]({KNOWLEDGE_DOC_URL})"),
    ])
    
    # 各板块
    build_gate_section(w, doc_id, macro)       # 0
    build_market_snapshot(w, doc_id)            # 1
    build_etf_section(w, doc_id, macro)         # 2
    # build_housing_section(w, doc_id)            # 3 — 已移至月报
    build_chain_section(w, doc_id, scanner, macro) # 4
    build_discovery_section(w, doc_id, scanner, macro) # 5
    build_news_section(w, doc_id)               # 6
    build_tracking_section(w, doc_id, scanner, macro) # 7
    build_action_section(w, doc_id, macro)      # 8
    build_concept_section(w, doc_id)             # 9
    
    doc_url = f"https://bytedance.feishu.cn/docx/{doc_id}"
    print(f"\n✅ 日报完成: {doc_url}")
    
    # 推送
    push_to_group(doc_url, f"v6.1 全量日报 | LDS双门={macro.get('dual_gate',{}).get('action','?')} | 宏观={macro.get('regime','?')}")
    print("  📤 已推送到群")

if __name__ == "__main__":
    main()
