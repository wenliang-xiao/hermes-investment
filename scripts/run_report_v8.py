#!/usr/bin/env python3
"""
面基·LDS·Vibe-Trading 三源融合·日报 v8
架构：主日报（5分钟决策版）+ 详细研究文档（按需深读）

主日报内容（本文件生成）：
  1. 今日核心信号（宏观+市场情绪+关键数字）
  2. 观察池今日行情（每只票的今日状态+关键信号）
  3. 今日重要事件（最多5条，有影响才出现）
  4. 今日操作纪律（简洁，结合宏观象限）

详细研究文档（由 run_report_detail.py 生成，每日推送链接）：
  - 宏观趋势详解：桥水象限/债券/汇率/商品全景
  - 产业链深度研究：10链分析/挖掘主题/国家队
  - 全资产配置：多资产引擎/ETF排序/LDS组合详细
  - 多因子新票发现：A股/港股/美股完整列表
"""
import sys, time, json, os
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.output.report_v6 as rpt
from investment_system.output.full_asset_scanner import (
    scan_commodities, scan_fx, scan_bonds, determine_bridgewater_quadrant
)
from investment_system.output.fund_tracker import track_lds_portfolio_v2
from investment_system.analysis.news_engine import get_news_with_impact

LF = '/tmp/report_v8_log.txt'
with open(LF, 'w') as f: f.write('')
def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")


def _fmt_pct(v, plus=True):
    if v is None: return "?"
    try:
        s = f"{float(v):+.2f}%" if plus else f"{float(v):.2f}%"
        return s
    except Exception:
        return str(v)


def _arrow(v):
    if v is None: return "➖"
    try:
        return "🔺" if float(v) > 0 else ("🔻" if float(v) < 0 else "➖")
    except Exception:
        return "➖"


def build_main_report(w, doc_id, macro, bw, lds, comms, fx_data, bonds_data, news_list, summary_text):
    today = time.strftime('%Y/%m/%d')
    dual_gate = macro.get('dual_gate', {})
    macro_gate = dual_gate.get('macro_gate', '?')
    trend_gate = dual_gate.get('trend_gate', '?')
    action = dual_gate.get('action', '?')
    regime = macro.get('regime', '?')
    cpi = macro.get('macro_data', {}).get('cpi', '?')
    trend_temp = macro.get('trend_temp', '?')
    bw_name = bw.get('quadrant_name', '?') if isinstance(bw, dict) else '?'
    bw_assets = bw.get('recommended_assets', []) if isinstance(bw, dict) else []
    bw_avoid = bw.get('avoid_assets', []) if isinstance(bw, dict) else []

    gate_icon = "🔴" if macro_gate in ("红灯", "黄灯") else "🟢"
    trend_icon = "🔴" if trend_gate in ("红灯", "黄灯") else "🟢"
    dual_closed = macro_gate in ("红灯", "黄灯") and trend_gate in ("红灯", "黄灯")

    # ─── 标题 ─────────────────────────────────────
    w.write(doc_id, [
        ('h1', f"📊 {today} · 每日决策简报"),
        ('divider', ''),
    ])

    # ─── 板块1：今日核心信号 ─────────────────────
    w.write(doc_id, [('h2', '🚦 一、今日核心信号')])

    # 宏观一行总结
    if dual_closed:
        macro_summary = f"**双门关闭** | 宏观{gate_icon} + 趋势{trend_icon} → 🔒 {action}"
    else:
        macro_summary = f"双门 宏观{gate_icon} + 趋势{trend_icon} → ✅ {action}"
    w.write(doc_id, [('bold', macro_summary)])

    # 象限和建议
    w.write(doc_id, [
        ('bullet', f"宏观象限: {regime} | CPI={cpi}% | 趋势温度: {trend_temp}"),
        ('bullet', f"桥水象限: {bw_name}"),
    ])
    if bw_assets:
        w.write(doc_id, [('bullet', f"推荐配置: {' > '.join(str(a) for a in bw_assets[:4])}")])
    if bw_avoid:
        w.write(doc_id, [('bullet', f"回避: {' / '.join(str(a) for a in bw_avoid[:3])}")])

    # 实际利率信号（简洁版）
    md = macro.get('macro_data', {})
    us10y = None
    for y in bonds_data.get('us_treasury', {}).get('yields', []):
        if '10年' in y.get('name', '') and y.get('current'):
            us10y = y['current']
            break
    if us10y and cpi != '?':
        try:
            real_rate = round(float(us10y) - float(cpi), 2)
            real_icon = "🔴" if real_rate > 2 else ("🟡" if real_rate > 0.5 else "🟢")
            w.write(doc_id, [('bullet', f"实际利率={us10y:.2f}%-CPI{cpi}%={real_rate:.2f}% {real_icon} → {'黄金承压' if real_rate > 2 else '黄金中性' if real_rate > 0.5 else '黄金强驱动'}")])
        except Exception:
            pass

    # 市场快速扫描（关键数字一行）
    w.write(doc_id, [('h3', '📈 市场快照')])
    snap_lines = []
    # 从full_asset_scanner取数
    from investment_system.data.yf_data_layer import get_global_market_snapshot
    try:
        snap = get_global_market_snapshot()
        idx = snap.get('indices', {})
        for name in ['标普500', '纳斯达克', '恒生', '日经']:
            d = idx.get(name)
            if d:
                price = d.get('price') if isinstance(d, dict) else d
                if price:
                    snap_lines.append(f"{name}: {price:,.0f}")
        bonds_s = snap.get('bonds', {})
        tnx = bonds_s.get('美债10Y')
        if tnx:
            snap_lines.append(f"美债10Y: {tnx:.2f}%")
        vix = snap.get('sentiment', {}).get('VIX')
        if vix:
            vix_icon = "🔴" if vix > 30 else ("🟡" if vix > 20 else "🟢")
            snap_lines.append(f"VIX: {vix:.1f}{vix_icon}")
    except Exception:
        pass
    if snap_lines:
        w.write(doc_id, [('bullet', ' | '.join(snap_lines))])

    # 北向资金（从data_layer取）
    try:
        from investment_system.data.data_layer import get_northbound_flow
        nb = get_northbound_flow()
        if nb.get('data_ok'):
            nb_net = nb.get('today_net', 0)
            nb_5d = nb.get('5d_cumulative', 0)
            nb_icon = "🟢" if nb_net > 10 else ("🔴" if nb_net < -10 else "🟡")
            w.write(doc_id, [('bullet', f"北向资金: {nb_icon} 今日{nb_net:+.1f}亿 | 5日{nb_5d:+.1f}亿 | {nb.get('signal','?')}")])
        else:
            w.write(doc_id, [('bullet', f"北向资金: ⚠️ {nb.get('note', '数据不可用')}")])
    except Exception as e:
        w.write(doc_id, [('bullet', f"北向资金: ⚠️ {str(e)[:40]}")])

    # LDS全天候今日表现（一行）
    port_ret = lds.get('portfolio_ret_1d')
    port_ytd = lds.get('portfolio_ytd')
    rebal_note = lds.get('rebalance_note', '')
    need_rebal = lds.get('need_rebalance', False)
    w.write(doc_id, [('bullet',
        f"LDS全天候: 今日{_fmt_pct(port_ret)} | YTD{_fmt_pct(port_ytd)} | "
        f"{'⚠️再平衡信号' if need_rebal else '✅无需再平衡'}"
    )])
    if need_rebal and rebal_note:
        w.write(doc_id, [('quote', rebal_note)])

    # ─── 板块2：观察池今日行情 ─────────────────────
    w.write(doc_id, [('divider', ''), ('h2', '🎯 二、观察池今日行情')])
    w.write(doc_id, [('quote', '只显示今日有信号的标的（超买/超卖/放量/趋势转变）')])

    try:
        from investment_system.output.report_v6 import _fetch_watchlist_prices, _calc_tech_signal
        from investment_system.config import WATCHLIST
        all_codes = list(WATCHLIST.keys())
        prices = _fetch_watchlist_prices(all_codes)

        flagged = []
        unflagged_core = []

        for code, info in WATCHLIST.items():
            tier = info.get('tier', '关注')
            name = info.get('name', code)
            chain = info.get('chain', '')
            focus = info.get('focus', '')[:35]
            pd_info = prices.get(code, {})
            price = pd_info.get('price')
            chg = pd_info.get('chg')
            tech_score = pd_info.get('tech_score')
            badges = pd_info.get('badges', '')
            rsi = pd_info.get('rsi')
            ma60_dev = pd_info.get('ma60_dev')

            if price is None:
                continue

            price_str = f"¥{price:.2f}" if isinstance(price, (int, float)) else "—"
            arr = _arrow(chg)
            chg_str = f"{arr}{_fmt_pct(chg)}" if chg is not None else ""

            # 有信号的标的
            has_signal = False
            signal_tags = []
            if rsi is not None:
                if rsi > 80:
                    signal_tags.append(f"🔴超买RSI{rsi:.0f}")
                    has_signal = True
                elif rsi < 25:
                    signal_tags.append(f"💡超卖RSI{rsi:.0f}")
                    has_signal = True
            if ma60_dev is not None:
                if ma60_dev > 40:
                    signal_tags.append(f"⚠️偏MA60+{ma60_dev:.0f}%")
                    has_signal = True
                elif ma60_dev < -15:
                    signal_tags.append(f"📉偏MA60{ma60_dev:.0f}%")
                    has_signal = True
            if abs(chg or 0) >= 5:
                signal_tags.append(f"{'📈大涨' if chg > 0 else '📉大跌'}{abs(chg):.1f}%")
                has_signal = True

            line = f"**{name}**({code}) {price_str} {chg_str}"
            if signal_tags:
                line += " | " + " ".join(signal_tags)
            if tech_score is not None:
                line += f" | 技术{tech_score:.0f}分"
            line += f" [{chain}]: {focus}"

            if has_signal:
                flagged.append((tier, line))
            elif tier in ('核心', '底仓'):
                unflagged_core.append((tier, line))

        if flagged:
            w.write(doc_id, [('bold', '⭐ 今日有信号标的')])
            for tier, line in sorted(flagged, key=lambda x: {'核心':0,'底仓':1,'关注':2,'追踪':3}.get(x[0],4)):
                w.write(doc_id, [('bullet', line)])
        if unflagged_core:
            w.write(doc_id, [('bold', '📋 核心/底仓标的（无特殊信号）')])
            for _, line in unflagged_core[:8]:
                w.write(doc_id, [('bullet', line)])
    except Exception as e:
        w.write(doc_id, [('bullet', f"⚠️ 观察池加载失败: {str(e)[:60]}")])

    # ─── 板块3：今日重要事件（最多5条） ─────────────
    w.write(doc_id, [('divider', ''), ('h2', '📰 三、今日重要事件')])

    has_news = False
    if summary_text and len(summary_text.strip()) > 50:
        # 从LLM总结里提取【重要事件】板块
        lines = summary_text.strip().split('\n')
        in_events = False
        event_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if '重要事件' in line or 'TOP' in line.upper():
                in_events = True
                continue
            if in_events and line.startswith('#'):
                break
            if in_events and line.startswith(('①', '②', '③', '④', '⑤', '1.', '2.', '3.', '4.', '5.', '• ', '- ')):
                event_lines.append(line[:200])
            if len(event_lines) >= 5:
                break

        if event_lines:
            for el in event_lines:
                w.write(doc_id, [('bullet', el)])
            has_news = True
        else:
            # 直接输出前5行有内容的摘要
            count = 0
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and len(line) > 20:
                    w.write(doc_id, [('bullet', line[:200])])
                    count += 1
                    has_news = True
                    if count >= 5:
                        break

    if not has_news:
        # fallback：从news_list取影响最大的
        count = 0
        for n in sorted(news_list, key=lambda x: len(x.get('impacts', [])), reverse=True):
            title = n.get('title', '')
            if not title or len(title) < 10:
                continue
            impacts = n.get('impacts', [])
            imp_str = ' '.join(f"[{i['chain']}]{i['direction']}" for i in impacts[:2]) if impacts else ''
            line = f"{title[:80]}"
            if imp_str:
                line += f"  →  {imp_str}"
            w.write(doc_id, [('bullet', line)])
            count += 1
            has_news = True
            if count >= 5:
                break

    if not has_news:
        w.write(doc_id, [('bullet', '今日无重大市场事件')])

    # 市场情绪
    try:
        from investment_system.analysis.news_engine import _calc_sentiment_score
        from investment_system.analysis.news_engine import classify_impact
        nl = classify_impact(news_list[:20]) if news_list else []
        sent = _calc_sentiment_score(nl)
        bull, bear = sent.get('bullish', 0), sent.get('bearish', 0)
        overall = sent.get('overall', '🟡 中性')
        w.write(doc_id, [('bullet', f"市场情绪: {overall} | 利好{bull}条 利空{bear}条")])
    except Exception:
        pass

    # ─── 板块4：操作纪律 ─────────────────────────
    w.write(doc_id, [('divider', ''), ('h2', '⚙️ 四、操作纪律')])

    if dual_closed:
        w.write(doc_id, [
            ('bold', '🔒 双门关闭 → 防御模式'),
            ('bullet', '不开新仓 | 持有票检查8%止损线 | 不追高不加仓'),
        ])
        bw_q = bw.get('current_quadrant', '') if isinstance(bw, dict) else ''
        if 'Q4' in bw_q:
            w.write(doc_id, [('bullet', '象限4建议: 可建长债底仓(TLT/159926/511010)，黄金维持，等CPI回升至1.5%+')])
        cpi_v = macro.get('macro_data', {}).get('cpi')
        w.write(doc_id, [('bullet',
            f"双门转绿条件: CPI≥1.5%(当前={cpi_v}%) + 趋势温度回暖"
        )])
    else:
        favored = macro.get('favored_sectors', [])
        w.write(doc_id, [
            ('bold', '✅ 双门开启 → 可操作'),
            ('bullet', f"优先板块: {' / '.join(favored[:4])}"),
        ])

    w.write(doc_id, [
        ('bullet', '止损: 8%硬止损 | 止盈: +15%减半 +30%清仓'),
        ('bullet', '仓位: 单票≤2% | 最多8只 | 凯利/2'),
    ])

    # ─── 跳转链接 ─────────────────────────────────
    w.write(doc_id, [
        ('divider', ''),
        ('bold', '📚 深读专题 → 详见以下文档（每日自动更新）'),
    ])
    w.write(doc_id, [
        ('bullet', '📊 宏观趋势详解：桥水象限/债券曲线/汇率/商品全景/多资产配置'),
        ('bullet', '🔗 产业链深度研究：10链分析/A股利润池/挖掘主题/国家队资金'),
        ('bullet', '🔍 全市场新票发现：A股/港股/美股完整因子评分'),
        ('bullet', '📰 新闻事件详解：产业链影响/受益标的分析'),
    ])


log("=== 日报 v8 START ===")

try:
    # ─── 数据准备 ─────────────────────────────────
    macro_engine = rpt.MacroEngine()
    macro = macro_engine.refresh()

    from investment_system import config as cfg_sys
    regime = macro.get('regime', 'default')
    rotation = cfg_sys.MACRO_SECTOR_ROTATION.get(regime, cfg_sys.MACRO_SECTOR_ROTATION['default'])
    macro['favored_sectors'] = rotation['favored']
    macro['avoided_sectors'] = rotation.get('unfavored', [])

    bw = determine_bridgewater_quadrant(macro.get('macro_data', {}))
    bw_q = bw.get('current_quadrant', '') if isinstance(bw, dict) else ''
    dual_open = not (macro.get('dual_gate', {}).get('macro_gate') in ('红灯', '黄灯') and
                     macro.get('dual_gate', {}).get('trend_gate') in ('红灯', '黄灯'))

    lds = track_lds_portfolio_v2(version="A", bw_quadrant=bw_q, dual_gate_open=dual_open)
    comms = scan_commodities()
    fx_data = scan_fx()
    bonds_data = scan_bonds()

    log("Data loaded")

    news_list, summary_text = get_news_with_impact()
    log(f"News: {len(news_list)} items")

    # ─── 创建主日报文档 ─────────────────────────────
    w = rpt.FeishuWriter()
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·日报 {time.strftime('%Y/%m/%d')}")
    log(f"Main doc: {doc_id}")

    build_main_report(w, doc_id, macro, bw, lds, comms, fx_data, bonds_data, news_list, summary_text)

    macro['bw_quadrant'] = bw_q
    log("Main report done")

    # ─── 验证 ─────────────────────────────────────
    import urllib.request
    token = w._get_token()
    u = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks?page_size=500"
    req = urllib.request.Request(u, headers={'Authorization': f'Bearer {token}'})
    items = json.loads(urllib.request.urlopen(req).read()).get('data', {}).get('items', [])
    bullets = sum(1 for b in items if b.get('block_type') == 12)
    log(f"VERIFY: {len(items)} blocks, bullets={bullets}")
    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
