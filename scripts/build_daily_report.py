#!/usr/bin/env python3
"""
主日报 Builder v8 — 完全重写版
覆盖6大资产类别 + 周度新闻 + 核心观察池 + 链趋势挖掘
每个 build_* 函数: (FeishuWriter, doc_id, macro_data) → writes to doc
原则：每个 builder 内部封装自己的数据获取+格式+降级显示
"""
import sys
sys.path.insert(0, '/home/admin/.hermes')
from investment_system.full_asset_scanner import scan_commodities, scan_fx, scan_bonds, scan_all_etfs
from investment_system.fund_tracker import track_lds_portfolio_v2
from investment_system.news_engine import get_news_with_impact
from investment_system import config as cfg

# ============================================================
# 辅助函数
# ============================================================

def _price(item, fmt="%.1f"):
    """价格 + 降级显示"""
    if not item:
        return "⚠️ 暂无"
    p = item.get('price')
    if p is not None:
        try:
            return fmt % p
        except Exception:
            return str(p)
    return "⚠️ 暂无"


def _chg(item, period='20d'):
    """涨跌幅显示"""
    if not item:
        return ""
    key = f"ret_{period}"
    v = item.get(key)
    if v is not None:
        try:
            return f"({v:+.1f}%)"
        except Exception:
            return f"({v})"
    return ""


def _find_by_name(data, name_part):
    """从商品列表中按名称模糊查找"""
    for c in data.get('commodities', []):
        if name_part in c.get('name', ''):
            return c
    return None


def _find_in_list(items, name_part, key='name'):
    """在 [{key: val}, ...] 列表中按字段模糊查找"""
    for item in items:
        val = item.get(key, '')
        if name_part in str(val):
            return item
    return None


def _safe_float(val, default=None):
    """安全转 float"""
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


# ============================================================
# 专家知识库：链瓶颈 + 挖掘方向
# ============================================================

CHAIN_BOTTLENECKS = {
    "英伟达算力链": {
        "bottleneck": "算力瓶颈已从GPU产能→光模块互联带宽（800G→1.6T→3.2T），电力供应成为新约束",
        "direction": "光模块升级链(中际旭创/天孚通信)、液冷散热(英维克/高澜)、数据中心电力(VST/CEG/EQIX)"
    },
    "台积电先进制程链": {
        "bottleneck": "CoWoS先进封装产能缺口>30%，是AI芯片物理瓶颈；先进制程(3nm以下)良率+设备限制→国产替代窗口",
        "direction": "国产设备(北方华创/中微)、chiplet先进封装(通富微电/长电)、EDA工具"
    },
    "半导体链": {
        "bottleneck": "先进制程(3nm以下)良率+设备出口限制→国产替代窗口期，成熟制程产能过剩拖累",
        "direction": "chiplet先进封装(通富微电/长电)、EDA工具、第三代半导体(三安光电)"
    },
    "存储/HBM链": {
        "bottleneck": "HBM由三星+SK海力士双寡头垄断，A股缺少纯正标的；封装基板国产化率<5%",
        "direction": "封装基板(兴森科技/深南电路)、测试设备(长川科技/华峰测控)、TSV工艺设备"
    },
    "机器人/自动化链": {
        "bottleneck": "精密减速器+力矩传感器→国产化率<20%，是最大成本项；人形机器人处于导入期，Winner未定",
        "direction": "谐波减速器(绿的谐波)、六维力传感器(柯力传感/宇立仪器)、灵巧手(鸣志电器)"
    },
    "新能源链": {
        "bottleneck": "光伏产能过剩→利润向下游EPC+储能转移；固态电池产业化前夜",
        "direction": "大储系统(阳光电源/宁德)、固态电解质(清陶/卫蓝未上市→关注天赐材料)"
    },
    "AI应用/Agent链": {
        "bottleneck": "Agent落地从Copilot→Autopilot，最大瓶颈在推理成本而非模型能力",
        "direction": "推理芯片定制(博通/迈威尔)、端侧AI(SOC/高通/晶晨)、AI+行业SaaS"
    },
    "医药创新链": {
        "bottleneck": "GLP-1减重赛道拥挤→下一个大单品在AD(阿尔茨海默)和NASH",
        "direction": "AD诊断+药物(卫材/渤健)、基因编辑CRISPR 2.0(Intellia/CRSP)"
    },
    "国产替代/信创链": {
        "bottleneck": "信创从党政→央企渗透，但多数企业仍亏损；工业软件比基础软件更早盈利",
        "direction": "工业软件(中望软件/中控技术)、办公软件AI化(金山办公)、CAD/CAE国产化"
    },
    "军工链": {
        "bottleneck": "定价机制从成本加成→目标价格管理，利润率能否打开是关键",
        "direction": "导弹/无人机(高消耗品)、军贸出口(打开新市场)、航空发动机(航发动力)"
    },
    "消费电子链": {
        "bottleneck": "AI手机/AI PC换机周期尚未启动，需等待杀手级应用",
        "direction": "AI手机芯片(高通/联发科)、折叠屏铰链、MR/空间计算(苹果Vision Pro)"
    },
}


CROSS_THEMES = {
    "default": [
        "AI×电力: 算力中心电力需求暴增→天然气+核电站+电网升级(CEG/VST/GE)",
        "AI×机器人: 具身智能→传感器+运动控制是瓶颈(宇树/傅利叶未上市→关注绿的谐波)",
        "中美脱钩×半导体: 设备国产化是最大增量市场(北方华创/中微公司)",
    ],
    "扩张期": [
        "AI×电力: 扩张期数据中心Capex加速→电力基础设施标的直接受益",
        "AI×机器人: 导入期→量产加速→零部件企业最先受益",
        "半导体×云端: 云端资本开支扩张→先进制程+CoWoS设备需求暴增",
    ],
    "过热期": [
        "大宗商品×通胀: 铜/原油/黄金→上游资源企业利润最大化",
        "能源×电力: 电网升级+天然气→公用事业防御+通胀对冲",
    ],
    "衰退期": [
        "黄金×债券: 避险+降息→长久期国债+黄金经典组合",
        "医药×消费必需品: 防御属性→创新药+必选消费龙头",
        "军工×自主可控: 地缘紧张+军费稳增→军工电子+国产替代",
    ],
    "复苏期": [
        "金融×消费: 信用扩张→银行+消费修复",
        "AI×应用: 风险偏好回升→AI概念弹性最大",
    ],
}


def _get_bottleneck(chain_id):
    """根据链ID获取瓶颈描述"""
    info = CHAIN_BOTTLENECKS.get(chain_id, {})
    return info.get('bottleneck', '')


def _get_mining_direction(chain_id):
    """根据链ID获取挖掘方向"""
    info = CHAIN_BOTTLENECKS.get(chain_id, {})
    return info.get('direction', '')


def _get_cross_themes(regime):
    """根据宏观象限获取跨链主题"""
    themes = CROSS_THEMES.get(regime, CROSS_THEMES.get('default', []))
    return themes


# ============================================================
# 板块1: 🚦 宏观信号
# ============================================================

def build_gate_line(w, doc_id, macro):
    """🚦 宏观信号 — 双门驱动桥水象限，不留逻辑矛盾"""
    dual = macro.get('dual_gate', {})
    macro_ok = dual.get('macro_ok', False)
    trend_ok = dual.get('trend_ok', False)
    action = dual.get('action', '观望')
    mg = '🟢 开' if macro_ok else '🔴 关'
    tg = '🟢 开' if trend_ok else '🔴 关'
    md = macro.get('macro_data', {})
    cpi = md.get('cpi', '?')
    pmi = md.get('pmi', '?')
    regime = macro.get('regime', '?')
    drift = macro.get('trend_deviation_20', '?')
    switch = macro.get('strategy_switch', '?')
    temp = macro.get('trend_temp', '?')
    
    w.write(doc_id, [
        ('h2', '🚦 今日宏观信号'),
        ('bold', f"双门: {mg} + {tg} → {action}"),
        ('bullet', f"象限: {regime} | CPI={cpi}% | PMI={pmi} | 策略: {switch}"),
    ])
    if drift != '?':
        w.write(doc_id, [('bullet', f"趋势温度: {temp} | 20日偏离: {drift}%")])
    
    # ── 桥水四象限：由双门状态驱动，CPI/PMI辅助判断 ──
    try:
        cpi_val = _safe_float(cpi)
        pmi_val = _safe_float(pmi)
        both_closed = not macro_ok and not trend_ok
        one_closed = (not macro_ok) or (not trend_ok)
        
        # ★ 核心规则：双门决定置信度，CPI/PMI决定具体象限
        if both_closed:
            # 双门全关 → 防御模式，保守判断象限
            if cpi_val is not None and cpi_val >= 2.5:
                bw_quad = "象限3（增长↓通胀↑）"
                bw_assets = "黄金 > 商品 > TIPS > 现金"
                bw_china = "滞胀风险 → 黄金+能源+必需消费"
                bw_confidence = "⚠️ 双门关闭锁定（CPI仍偏高→滞胀信号）"
            else:
                bw_quad = "象限4（增长↓通胀↓）"
                bw_assets = "长期国债 > 黄金 > 防御股 > 现金"
                bw_china = "衰退/通缩 → TLT/长债底仓+黄金+红利低波"
                bw_confidence = f"⚠️ 双门关闭锁定（CPI={cpi}%通缩压力→自动进入象限4）"
        
        elif one_closed:
            # 一扇门关 → 谨慎象限
            if not macro_ok:  # 宏观门关
                bw_quad = "象限4（增长↓通胀↓）"
                bw_assets = "长期国债 > 黄金 > 防御股 > 现金"
                bw_china = "宏观门关 → 偏防御配置"
                bw_confidence = "⚠️ 宏观门关闭（经济数据弱→保守默认Q4）"
            else:  # 趋势门关
                if cpi_val is not None and cpi_val >= 2.5:
                    bw_quad = "象限3（增长↓通胀↑）"
                    bw_assets = "黄金 > 商品 > TIPS > 现金"
                    bw_china = "趋势门关+通胀 → 黄金+能源"
                    bw_confidence = "⚠️ 趋势门关闭（动量弱→转防御）"
                else:
                    bw_quad = "象限4（增长↓通胀↓）"
                    bw_assets = "长期国债 > 防御股 > 黄金 > 现金"
                    bw_china = "趋势门关+通缩 → 长债+防御"
                    bw_confidence = "⚠️ 趋势门关闭（动量弱→默认Q4）"
        
        else:
            # 双门全开 → 进攻模式，CPI/PMI判断象限
            if cpi_val is not None and pmi_val is not None:
                growth_up = pmi_val >= 50
                inflation_up = cpi_val >= 2.5
                if growth_up and inflation_up:
                    bw_quad = "象限1（增长↑通胀↑）"
                    bw_assets = "商品 > 黄金 > 新兴市场股 > TIPS"
                    bw_china = "过热期 → 大宗商品+上游资源"
                elif growth_up and not inflation_up:
                    bw_quad = "象限2（增长↑通胀↓）"
                    bw_assets = "股票 > 信用债 > 商品 > 现金"
                    bw_china = "扩张期 → A股成长+美股科技"
                elif not growth_up and inflation_up:
                    bw_quad = "象限3（增长↓通胀↑）"
                    bw_assets = "黄金 > 商品 > TIPS > 现金"
                    bw_china = "滞胀风险 → 黄金+能源+必需消费"
                else:
                    bw_quad = "象限4（增长↓通胀↓）"
                    bw_assets = "长期国债 > 黄金 > 防御股 > 现金"
                    bw_china = "衰退/通缩 → TLT/长债底仓+黄金+红利低波"
                bw_confidence = "高（双门开+CPI/PMI数据完整）"
            else:
                bw_quad = "象限4（增长↓通胀↓）"
                bw_assets = "长期国债 > 黄金 > 防御股 > 现金"
                bw_china = "数据不足→保守默认Q4"
                bw_confidence = "低（CPI/PMI数据缺失）"
        
        w.write(doc_id, [
            ('h3', f'🌐 桥水参考: {bw_quad}'),
            ('bullet', f'置信度: {bw_confidence}'),
            ('bullet', f'资产排序: {bw_assets}'),
            ('bullet', f'中国对照: {bw_china}'),
        ])
        
        # ── 操作提示：与双门状态一致 ──
        if both_closed:
            w.write(doc_id, [
                ('bold', '🔒 双门关闭 → 防御模式'),
                ('bullet', '不开新仓 | 持有票检查8%止损 | 长债底仓(TLT/159926)可作为防御配置'),
            ])
        elif one_closed:
            w.write(doc_id, [
                ('bold', '⚠️ 一扇门关 → 谨慎模式'),
                ('bullet', '减仓至半仓以下 | 新仓需四重确认 | 优先持有防御性资产'),
            ])
        else:
            w.write(doc_id, [
                ('bold', '🟢 双门全开 → 正常操作'),
                ('bullet', '可建新仓（二重确认以上） | 单票≤2%仓位 | 持有≤8只'),
            ])
            
    except Exception:
        pass  # 静默降级


# ============================================================
# 板块2: 📊 全球市场全景（6大类全覆盖）
# ============================================================

def build_market_snapshot(w, doc_id):
    """📊 全球市场全景 — 贵金属/能源工业金属/债券/汇率/ETF/指数"""
    
    # ── 获取数据（全部包裹 try/except）──
    comm, fx, bonds, etfs = None, None, None, None
    try:
        comm = scan_commodities()
    except Exception as e:
        pass
    try:
        fx = scan_fx()
    except Exception as e:
        pass
    try:
        bonds = scan_bonds()
    except Exception as e:
        pass
    try:
        etfs = scan_all_etfs(top_n=3)
    except Exception as e:
        pass

    w.write(doc_id, [('h2', '📊 全球市场全景')])

    # ── 1. 贵金属（核心关注）──
    w.write(doc_id, [('h3', '🥇 贵金属')])
    if comm:
        gold = _find_by_name(comm, '黄金')
        silver = _find_by_name(comm, '白银')
        w.write(doc_id, [
            ('bullet', f"黄金: {_price(gold, '$%.0f')} {_chg(gold, '20d')}"),
            ('bullet', f"白银: {_price(silver, '$%.1f')} {_chg(silver, '20d')}"),
        ])
    else:
        w.write(doc_id, [('bullet', '⚠️ 贵金属数据暂不可用')])

    # ── 2. 能源+工业金属 ──
    w.write(doc_id, [('h3', '⛽ 能源·工业金属')])
    if comm:
        oil = _find_by_name(comm, 'WTI') or _find_by_name(comm, '原油')
        copper = _find_by_name(comm, '铜')
        gas = _find_by_name(comm, '天然气')
        parts = []
        p_oil = f"原油WTI: {_price(oil, '$%.1f')} {_chg(oil, '20d')}"
        parts.append(p_oil)
        p_cu = f"铜: {_price(copper, '$%.2f')} {_chg(copper, '20d')}"
        parts.append(p_cu)
        if gas and gas.get('price') is not None:
            p_gas = f"天然气: {_price(gas, '$%.1f')} {_chg(gas, '20d')}"
            parts.append(p_gas)
        w.write(doc_id, [('bullet', ' | '.join(parts))])
    else:
        w.write(doc_id, [('bullet', '⚠️ 能源工业金属数据暂不可用')])

    # ── 3. 债券收益率 ──
    w.write(doc_id, [('h3', '🏦 债券收益率')])
    if bonds:
        ust = bonds.get('us_treasury', {})
        yields = ust.get('yields', [])
        if yields:
            for y in yields[:3]:
                name = y.get('name', '?')
                value = y.get('current')  # scan_bonds uses 'current' not 'value'
                v_str = f"{value:.2f}%" if value is not None else "⚠️"
                w.write(doc_id, [('bullet', f"美{name}: {v_str}")])
        else:
            w.write(doc_id, [('bullet', '⚠️ 美债收益率数据暂不可用')])

        spread = ust.get('2y_10y_spread')
        curve = ust.get('curve_shape', '未知')
        if spread is not None:
            signal_icon = ust.get('signal', '')
            w.write(doc_id, [('bullet', f"曲线形态: {curve} (利差{spread}bp) {signal_icon[:30]}")])

        cn_spread = bonds.get('cn_us_spread')
        if cn_spread is not None:
            w.write(doc_id, [('bullet', f"中美利差: {cn_spread}bp")])
        # ★ 中国10Y收益率
        cn_10y = bonds.get('cn_10y_estimated')
        if cn_10y is not None:
            w.write(doc_id, [('bullet', f"中国10Y收益率: {cn_10y:.2f}%")])
    else:
        w.write(doc_id, [('bullet', '⚠️ 债券数据暂不可用')])

    # ── 4. 主要汇率 ──
    w.write(doc_id, [('h3', '💱 主要汇率')])
    if fx:
        fx_items = fx.get('fx_pairs', [])
        shown = 0
        for p in fx_items[:4]:
            name = p.get('name', '?')
            price = p.get('price')
            note = p.get('note', '')
            signal = p.get('signal', '')
            p_str = f"{price:.4f}" if price is not None else "⚠️ 暂无"
            extra = f" {signal}" if signal and signal != '➖' else ""
            if note:
                extra += f" [{note}]"
            w.write(doc_id, [('bullet', f"{name}: {p_str}{extra}")])
            shown += 1
        if shown == 0:
            w.write(doc_id, [('bullet', '⚠️ 汇率数据暂不可用')])
    else:
        w.write(doc_id, [('bullet', '⚠️ 汇率数据暂不可用')])

    # ── 5. ETF动量Top3 ──
    w.write(doc_id, [('h3', '📈 ETF动量Top3')])
    if etfs:
        top = etfs.get('top_5', [])
        shown = 0
        for e in top[:3]:
            name = e.get('name', '?')
            ret = e.get('ret_20d')
            composite = e.get('_composite')
            r_str = f"{ret:+.1f}%" if ret is not None else "⚠️"
            c_str = f" | 综合{composite:.1f}" if composite is not None else ""
            w.write(doc_id, [('bullet', f"{name}: 20日动量 {r_str}{c_str}")])
            shown += 1
        if shown == 0:
            w.write(doc_id, [('bullet', '⚠️ ETF动量数据暂不可用')])
    else:
        w.write(doc_id, [('bullet', '⚠️ ETF数据暂不可用')])

    # ── 6. 全球指数（快速抓取关键指数）──
    w.write(doc_id, [('h3', '🌍 全球关键指数')])
    try:
        indices = _fetch_indices_snapshot()
        for idx in indices:
            w.write(doc_id, [('bullet', f"{idx['name']}: {idx['price']} {idx['chg']}")])
    except Exception:
        w.write(doc_id, [('bullet', '⚠️ 指数数据暂不可用')])


def _fetch_indices_snapshot():
    """快速获取4个关键指数的快照数据"""
    import yfinance as yf
    index_map = {
        "^GSPC": "标普500",
        "^IXIC": "纳斯达克",
        "^HSI": "恒生指数",
        "000300.SS": "沪深300",
    }
    results = []
    for sym, name in index_map.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="1mo")
            if hist.empty:
                results.append({"name": name, "price": "⚠️", "chg": ""})
                continue
            close = hist["Close"]
            price = float(close.iloc[-1])
            chg_20 = float((close.iloc[-1] / close.iloc[-min(20, len(close))] - 1) * 100) if len(close) >= 2 else None
            p_str = f"{price:,.0f}" if price >= 1000 else f"{price:.2f}"
            c_str = f"({chg_20:+.1f}% 20d)" if chg_20 is not None else ""
            results.append({"name": name, "price": p_str, "chg": c_str})
        except Exception:
            results.append({"name": name, "price": "⚠️", "chg": ""})
    return results


# ============================================================
# 板块3: 📰 本周市场要闻与情绪
# ============================================================

def build_weekly_news(w, doc_id):
    """📰 本周市场要闻与情绪 — 周度视角+链影响分布"""
    w.write(doc_id, [('h2', '📰 本周市场要闻与情绪')])

    news_list, summary = None, None
    try:
        news_list, summary = get_news_with_impact(use_cache=True, use_llm=True)
    except Exception:
        try:
            news_list, summary = get_news_with_impact(use_cache=True, use_llm=False)
        except Exception:
            w.write(doc_id, [('bullet', '⚠️ 本周暂无重大新闻信号（数据源暂不可用）')])
            return

    if not news_list:
        w.write(doc_id, [('bullet', '⚠️ 本周暂无重大新闻信号')])
        return

    # LLM总结
    if summary and summary != '📰 今日无重大新闻信号' and summary != '📰 本周无重大新闻信号':
        w.write(doc_id, [('quote', f"📝 {summary[:250]}")])

    # 按链影响分组
    by_chain = {}
    for n in news_list:
        for imp in n.get('impacts', []):
            chain = imp.get('chain', '其他')
            by_chain.setdefault(chain, []).append(n)

    # 链影响分布
    if by_chain:
        w.write(doc_id, [('h3', '链影响分布')])
        for chain, items in sorted(by_chain.items(), key=lambda x: -len(x[1]))[:5]:
            directions = set()
            for n in items:
                for imp in n.get('impacts', []):
                    if imp.get('chain') == chain:
                        directions.add(imp.get('direction', ''))
            dir_str = ','.join(directions) if directions else '待判'
            w.write(doc_id, [('bullet', f"{chain}: {len(items)}条新闻 | 方向: {dir_str}")])

    # Top 5 关键事件
    w.write(doc_id, [('h3', '关键事件 Top 5')])
    shown = 0
    for n in news_list[:5]:
        title = n.get('title', '')
        if not title:
            continue
        impacts = n.get('impacts', [])
        direction = ''
        if impacts:
            dirs = [f"[{i.get('chain', '')}]{i.get('direction', '')}" for i in impacts[:3]]
            direction = ' → '.join(dirs)
        w.write(doc_id, [('bullet', f"{title[:120]}  {direction}")])
        shown += 1

    if shown == 0:
        w.write(doc_id, [('bullet', '⚠️ 无标题数据')])


# ============================================================
# 板块4: 🎯 核心观察池
# ============================================================

def build_key_watchlist(w, doc_id, macro):
    """🎯 核心观察池 — 面基/LDS框架下的重点票关注池（WATCHLIST） + LDS组合 + 跨资产"""

    w.write(doc_id, [('h2', '🎯 核心观察池')])

    # ── 1. 重点票关注池（来自config.WATCHLIST — 面基/LDS框架标的）──
    w.write(doc_id, [('h3', '🔗 重点票关注池')])
    try:
        watchlist = getattr(cfg, 'WATCHLIST', {})
        if watchlist:
            # 按chain分组展示
            by_chain = {}
            for code, info in watchlist.items():
                chain = info.get('chain', '其他')
                by_chain.setdefault(chain, []).append((code, info))

            for chain, items in sorted(by_chain.items()):
                # 每条链最多展示3个标的
                core_items = [i for i in items if i[1].get('tier') == '核心'][:2]
                focus_items = [i for i in items if i[1].get('tier') == '关注'][:1]
                show_items = core_items + focus_items
                if show_items:
                    parts = []
                    for code, info in show_items[:3]:
                        name = info.get('name', code)
                        focus = info.get('focus', '')[:40]
                        parts.append(f"{name}({focus})")
                    w.write(doc_id, [('bullet', f"{chain}: {' | '.join(parts)}")])
        else:
            # fallback to INDUSTRY_CHAINS
            chains = list(cfg.INDUSTRY_CHAINS.items())[:8]
            for chain_id, chain_data in chains:
                name = chain_data.get('name', chain_id)
                stocks = chain_data.get('key_stocks_a', [])
                if stocks:
                    w.write(doc_id, [('bullet', f"{name}: {', '.join(stocks[:3])}")])
    except Exception as e:
        w.write(doc_id, [('bullet', f'⚠️ 关注池暂不可用: {str(e)[:40]}')])

    # ── 2. LDS全天候组合状态 ──
    w.write(doc_id, [('h3', '📦 LDS全天候组合')])
    try:
        lds = track_lds_portfolio_v2(version='A')
        ret1d = lds.get('portfolio_ret_1d')
        ytd = lds.get('portfolio_ytd')
        ret1d_str = f"{ret1d:+.2f}%" if ret1d is not None else "⚠️"
        ytd_str = f"{ytd:+.2f}%" if ytd is not None else "⚠️"
        w.write(doc_id, [('bullet', f"今日: {ret1d_str} | YTD: {ytd_str}")])
        for comp in lds.get('components', [])[:5]:
            name = comp.get('name', '?')
            badge = comp.get('data_badge', '')
            ret1d = comp.get('ret_1d')
            ret_str = f"{ret1d:+.2f}%" if ret1d is not None else "⚠️"
            role = comp.get('role', '')
            role_str = f" [{role}]" if role else ''
            w.write(doc_id, [('bullet', f"  {name}: {ret_str} [{badge}]{role_str}")])
        # 再平衡提示（带数据置信度检查）
        if lds.get('need_rebalance'):
            # 检查数据质量 — 如果多个成分数据异常，抑制信号
            bad_components = [c for c in lds.get('components', []) 
                            if c.get('data_badge', '') in ('stale', 'error', 'fallback')]
            if len(bad_components) <= 1:
                w.write(doc_id, [('bullet', f"⚠️ {lds.get('rebalance_note', '')}")])
            else:
                w.write(doc_id, [('bullet', f"⚠️ 再平衡信号(低置信度): {len(bad_components)}个成分数据异常，请手动核实")])
        # 双门关闭时额外提示
        dual = macro.get('dual_gate', {})
        if not dual.get('macro_ok', False) and not dual.get('trend_ok', False):
            w.write(doc_id, [('text', '💡 双门关闭→底仓维持即可，此时不是调仓时机')])
    except Exception as e:
        w.write(doc_id, [('bullet', f'⚠️ LDS组合暂时不可用: {str(e)[:40]}')])

    # ── 3. 多资产扫描摘要 ──
    w.write(doc_id, [('h3', '🌐 跨资产观察')])
    try:
        from investment_system.multi_asset_engine import run_daily_multi_asset_scan
        regime = macro.get('regime', 'default')
        ma = run_daily_multi_asset_scan(regime=regime)
        by_class = ma.get('by_class', {})
        
        # 检查评分是否有效（如果全1分则跳过）
        all_scores = []
        for items in by_class.values():
            for i in items:
                s = i.get('score', 0)
                if s is not None: all_scores.append(s)
        
        if all_scores and max(all_scores) - min(all_scores) > 2:
            # 评分有区分度 → 正常展示
            class_order = ['A股股票', '美股股票', '商品', '债券', '货币', 'REIT']
            for cls in class_order:
                if cls in by_class:
                    items = by_class[cls][:2]
                    names = [f"{i.get('name', '?')}({i.get('score', 0):.0f}分)" for i in items]
                    w.write(doc_id, [('bullet', f"{cls}: {', '.join(names)}")])
            for cls, items in by_class.items():
                if cls not in class_order:
                    items_top = items[:2]
                    names = [f"{i.get('name', '?')}({i.get('score', 0):.0f}分)" for i in items_top]
                    w.write(doc_id, [('bullet', f"{cls}: {', '.join(names)}")])
        else:
            w.write(doc_id, [('bullet', '⚠️ 跨资产评分引擎初始化中，暂时不可用（所有分数无区分度）')])
    except Exception as e:
        w.write(doc_id, [('bullet', f'⚠️ 多资产扫描暂不可用: {str(e)[:40]}')])


# ============================================================
# 板块5: 💡 链趋势与挖掘方向
# ============================================================

def build_chain_mining(w, doc_id, macro):
    """💡 链趋势与挖掘信号 — 双门状态驱动分析模式"""

    w.write(doc_id, [('h2', '💡 链趋势与挖掘方向')])

    # ── 双门状态决定分析基调 ──
    dual = macro.get('dual_gate', {})
    macro_ok = dual.get('macro_ok', False)
    trend_ok = dual.get('trend_ok', False)
    both_closed = not macro_ok and not trend_ok

    # 获取宏观象限下的favored chains
    regime = macro.get('regime', 'default')
    rotation = cfg.MACRO_SECTOR_ROTATION.get(regime, cfg.MACRO_SECTOR_ROTATION.get('default', {}))
    favored = rotation.get('favored', ['科技', '消费'])
    lds_note = rotation.get('lds_note', '')

    w.write(doc_id, [
        ('quote', f"当前象限: {regime} → 偏向: {', '.join(favored[:5])}"),
    ])
    if lds_note:
        w.write(doc_id, [('text', f"LDS提示: {lds_note}")])

    # ★ 双门关闭 → 等待观察模式提示
    if both_closed:
        w.write(doc_id, [
            ('bold', '🛑 双门关闭 — 以下链分析为"等待布局区间观察"模式'),
            ('bullet', '逻辑分析保留（为什么这个方向是对的），但结论是"等信号"而非"现在买"'),
            ('bullet', '关注触发条件而非建仓时机：双门转绿、趋势温度回升、关键催化剂落地'),
        ])
    elif not macro_ok or not trend_ok:
        w.write(doc_id, [
            ('bold', '⚠️ 一扇门关闭 — 链分析为"谨慎观察"模式'),
            ('bullet', '可轻仓试探确定性最高的方向，但不开主仓位'),
        ])
    else:
        w.write(doc_id, [
            ('bold', '🟢 双门全开 — 链分析为"积极布局"模式'),
            ('bullet', '按四重确认标准筛选标的，可正常建仓'),
        ])

    # 遍历前6条链进行分析
    chains = list(cfg.INDUSTRY_CHAINS.items())[:6]
    for chain_id, chain_data in chains:
        name = chain_data.get('name', chain_id)
        if name == chain_id:
            name = chain_id
        perez = chain_data.get('perez_stage', '?')
        key_stocks = chain_data.get('key_stocks_a', [])
        if not key_stocks:
            key_stocks = chain_data.get('symbols', [])[:3]
        # 'doubling_logic' may not exist; check for 'lds_logic' or 'description'
        logic = chain_data.get('doubling_logic', '')
        if not logic:
            logic = chain_data.get('lds_logic', '')
        if not logic:
            logic = chain_data.get('description', '')

        # 链趋势图标
        stage_map = {
            '导入': '🌱', '展开': '📈', '成熟': '📊', '泡沫': '🫧',
            '导入期': '🌱', '展开期': '📈', '成熟期': '📊',
        }
        stage_icon = '❓'
        for k, v in stage_map.items():
            if k in str(perez):
                stage_icon = v
                break

        w.write(doc_id, [
            ('h3', f'{stage_icon} {name}'),
            ('bullet', f'Perez阶段: {perez}'),
        ])

        if key_stocks:
            w.write(doc_id, [('bullet', f'核心票: {", ".join(key_stocks[:4])}')])

        # 翻倍逻辑/产业链描述（截取关键部分）
        if logic:
            # 提取LDS相关部分
            short_logic = logic[:200]
            w.write(doc_id, [('bullet', f'核心逻辑: {short_logic}...' if len(logic) > 200 else f'核心逻辑: {short_logic}')])

        # ⭐ 瓶颈分析
        bottleneck = _get_bottleneck(chain_id)
        if bottleneck:
            w.write(doc_id, [('bold', f'🔍 当前瓶颈: {bottleneck}')])

        # ⭐ 挖掘方向
        direction = _get_mining_direction(chain_id)
        if direction:
            w.write(doc_id, [('bullet', f'💎 挖掘方向: {direction}')])

        # Nick四问（如果存在）
        nick = chain_data.get('nick_questions', '')
        if nick:
            w.write(doc_id, [('bullet', f'Nick四问: {nick[:150]}')])

        # ★ 双门关闭时 → 添加"等待信号"提示
        if both_closed:
            w.write(doc_id, [('text', '⏳ [等待信号：双门转绿 + 趋势温度回升 + 对应催化剂落地]')])

    # ── 跨链交叉机会 ──
    w.write(doc_id, [('h3', '🔗 跨链交叉机会')])
    cross_themes = _get_cross_themes(regime)
    for theme in cross_themes:
        w.write(doc_id, [('bullet', theme)])

    # ★ OPPORTUNITY_THEMES — 7大挖掘机会主题（来自config，面基/LDS产业逻辑验证）
    try:
        opp_themes = getattr(cfg, 'OPPORTUNITY_THEMES', {})
        if opp_themes:
            w.write(doc_id, [('h3', '⭐ 7大挖掘机会主题')])
            theme_items = list(opp_themes.items())
            for idx, (theme_name, theme_data) in enumerate(theme_items):
                logic = theme_data.get('logic', '')[:140]
                bottleneck = theme_data.get('bottleneck', '')[:120]
                stage = theme_data.get('perez_stage', '')
                catalysts = theme_data.get('key_catalysts', [])
                
                w.write(doc_id, [
                    ('bold', f'📌 主题{idx+1}: {theme_name}'),
                    ('bullet', f'逻辑: {logic}'),
                ])
                if bottleneck:
                    w.write(doc_id, [('bold', f'瓶颈: {bottleneck}')])
                if stage:
                    w.write(doc_id, [('bullet', f'阶段: {stage}')])
                if catalysts:
                    w.write(doc_id, [('bullet', f'催化剂: {", ".join(catalysts[:3])}')])
                # 标的
                a_stocks = theme_data.get('a_stocks_focus', [])
                us_stocks = theme_data.get('us_stocks_focus', [])
                hk_stocks = theme_data.get('hk_stocks_focus', [])
                stocks_parts = []
                if a_stocks: stocks_parts.append(f"A股: {', '.join(a_stocks[:3])}")
                if us_stocks: stocks_parts.append(f"美股: {', '.join(us_stocks[:3])}")
                if hk_stocks: stocks_parts.append(f"港股: {', '.join(hk_stocks[:3])}")
                if stocks_parts:
                    w.write(doc_id, [('bullet', ' | '.join(stocks_parts))])
                risk = theme_data.get('risk', '')
                if risk:
                    w.write(doc_id, [('bullet', f'⚠️ 风险: {risk[:100]}')])
    except Exception:
        pass  # 静默降级

    # ── 链资金流向信号（如果多资产扫描可用）──
    try:
        from investment_system.multi_asset_engine import run_daily_multi_asset_scan
        ma = run_daily_multi_asset_scan(regime=regime)
        top20 = ma.get('top_20_overall', [])
        if top20:
            # 展示Top 5资金最集中的资产
            w.write(doc_id, [('h3', '💰 全资产资金流向 Top 5')])
            for t in top20[:5]:
                name = t.get('name', '?')
                score = t.get('score', 0)
                ret = t.get('ret_20d')
                ret_str = f" {ret:+.1f}%" if ret is not None else ""
                w.write(doc_id, [('bullet', f"{name}: 综合{score:.0f}分{ret_str}")])
    except Exception:
        pass  # 静默降级


# ============================================================
# 板块6: ⚙️ 今日操作纪律
# ============================================================

def build_discipline(w, doc_id, macro):
    """⚙ 今日操作纪律 — 个性化信息"""
    dual = macro.get('dual_gate', {})
    macro_ok = dual.get('macro_ok', False)
    trend_ok = dual.get('trend_ok', False)
    both_closed = not macro_ok and not trend_ok
    
    md = macro.get('macro_data', {})
    cpi = _safe_float(md.get('cpi'))
    pmi = _safe_float(md.get('pmi'))
    is_q4 = (pmi is not None and cpi is not None and pmi < 50 and cpi < 2.5)
    
    w.write(doc_id, [('h2', '⚙ 今日操作纪律')])
    
    # ── 核心原则 ──
    if both_closed:
        w.write(doc_id, [
            ('bold', '🔒 双门关闭 → 防御模式'),
            ('bullet', '不开新仓 | 持有票检查8%止损线 | 不追高不加仓'),
        ])
        if is_q4:
            w.write(doc_id, [
                ('bullet', '🧊 通缩象限: TLT/159926长债底仓可作为防御配置（利率下行→长久期受益最大）'),
            ])
    elif not macro_ok or not trend_ok:
        w.write(doc_id, [
            ('bold', '⚠️ 一扇门关闭 → 谨慎模式'),
            ('bullet', '减仓至半仓以下 | 新仓需四重确认 | 优先防御性资产'),
        ])
    else:
        w.write(doc_id, [
            ('bold', '🟢 双门全开 → 正常操作'),
            ('bullet', '单票≤2%仓位 | 持有≤8只 | 8%硬止损不可商量'),
        ])
    
    # ── 转绿条件提示 ──
    if both_closed or (not macro_ok or not trend_ok):
        conditions = []
        if not macro_ok:
            conditions.append(f"CPI回升至1.5%+ (当前={cpi}%)")
        if not trend_ok:
            drift = macro.get('trend_deviation_20', '?')
            conditions.append(f"趋势温度回升至温 (当前偏离={drift}%)")
        if conditions:
            w.write(doc_id, [
                ('bullet', f'双门转绿条件: {"; ".join(conditions)}'),
            ])
    
    # ── 持仓风险提示（从 portfolio_monitor 获取）──
    try:
        from investment_system.portfolio_monitor import get_risk_alerts
        alerts = get_risk_alerts()
        if alerts:
            w.write(doc_id, [('h3', '⚠️ 风险警报')])
            for a in alerts[:3]:
                w.write(doc_id, [('bullet', f"{a.get('name', '?')}: {a.get('alert', '')}")])
    except Exception:
        pass
    
    # ── 今日关注催化剂 ──
    try:
        from investment_system.news_engine import load_cached_news
        cached = load_cached_news()
        if cached:
            # 找最近1天内有明确影响方向的新闻
            impactful = [n for n in cached if n.get('impacts') and any(
                i.get('direction') in ('利好', '利空') for i in n.get('impacts', [])
            )][:3]
            if impactful:
                w.write(doc_id, [('h3', '📋 今日可关注催化剂')])
                for n in impactful:
                    title = n.get('title', '')[:80]
                    directions = []
                    for imp in n.get('impacts', []):
                        if imp.get('direction') in ('利好', '利空'):
                            directions.append(f"[{imp.get('chain', '')}]{imp.get('direction', '')}")
                    w.write(doc_id, [('bullet', f"{title} → {', '.join(directions[:2])}")])
    except Exception:
        pass
