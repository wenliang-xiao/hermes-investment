#!/usr/bin/env python3
"""
面基·LDS 每日决策简报
运行时间：每天 08:30（开盘前）+ 18:00（收盘后）
目标：5分钟读完，决策清晰

Hermes cron:
  command: python /home/admin/.hermes/investment_system/scripts/run_daily.py
  schedule: 0 8 30 * * 1-5   # 工作日08:30
  schedule: 0 18 0 * * 1-5   # 工作日18:00
"""
import sys, time, json, os
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.output.report_v6 as rpt
from investment_system.output.full_asset_scanner import (
    scan_commodities, scan_fx, scan_bonds, determine_bridgewater_quadrant
)
from investment_system.output.fund_tracker import track_lds_portfolio_v2
from investment_system.analysis.news_engine import get_news_with_impact
from investment_system.data.yf_data_layer import get_global_market_snapshot
from investment_system.data.data_layer import get_northbound_flow

LF = '/tmp/report_daily_log.txt'
with open(LF, 'w') as f: f.write('')

def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

def _fmt(v, plus=True, unit='%', digits=2):
    if v is None: return "?"
    try:
        s = f"{float(v):+.{digits}f}{unit}" if plus else f"{float(v):.{digits}f}{unit}"
        return s
    except Exception:
        return str(v)

def _arrow(v):
    if v is None: return "➖"
    try: return "🔺" if float(v) > 0 else ("🔻" if float(v) < 0 else "➖")
    except: return "➖"

session = "开盘前" if time.localtime().tm_hour < 12 else "收盘后"

log(f"=== 日报 {session} START ===")

try:
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
    bonds_data = scan_bonds()
    news_list, summary_text = get_news_with_impact()
    log("Data loaded")

    w = rpt.FeishuWriter()
    today = time.strftime('%Y/%m/%d')
    weekday = ['一','二','三','四','五','六','日'][time.localtime().tm_wday]
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·{session}决策简报 {today}(周{weekday})")
    log(f"Doc: {doc_id}")

    dual_gate = macro.get('dual_gate', {})
    macro_gate = dual_gate.get('macro_gate', '?')
    trend_gate = dual_gate.get('trend_gate', '?')
    action = dual_gate.get('action', '?')
    cpi = macro.get('macro_data', {}).get('cpi', '?')
    trend_temp = macro.get('trend_temp', '?')
    bw_name = bw.get('quadrant_name', '?') if isinstance(bw, dict) else '?'
    favored = macro.get('favored_sectors', [])

    gate_icon = "🔴" if macro_gate in ("红灯","黄灯") else "🟢"
    trend_icon = "🔴" if trend_gate in ("红灯","黄灯") else "🟢"
    dual_closed = macro_gate in ("红灯","黄灯") and trend_gate in ("红灯","黄灯")

    w.write(doc_id, [
        ('h1', f"{'🌅' if session == '开盘前' else '🌆'} {today}(周{weekday}) · {session}决策简报"),
        ('divider', ''),
    ])

    # ─── 板块1：决策面板（30秒）───
    w.write(doc_id, [('h2', '🚦 一、今日决策面板')])

    if dual_closed:
        w.write(doc_id, [('bold', f"🔒 双门关闭 → {action}")])
    else:
        w.write(doc_id, [('bold', f"✅ 双门开启 → {action}")])

    w.write(doc_id, [
        ('bullet', f"宏观门{gate_icon} {macro_gate} | 趋势门{trend_icon} {trend_gate} | 象限: {regime} → {bw_name}"),
        ('bullet', f"CPI={cpi}% | 趋势温度={trend_temp} | 偏好: {' / '.join(favored[:3]) or '均衡'}"),
    ])

    try:
        snap = get_global_market_snapshot()
        idx = snap.get('indices', {})
        snap_parts = []
        for name in ['标普500', '纳斯达克', '恒生', '沪深300']:
            d = idx.get(name)
            if d:
                p = d.get('price') if isinstance(d, dict) else d
                if p: snap_parts.append(f"{name}:{p:,.0f}")
        bonds_s = snap.get('bonds', {})
        tnx = bonds_s.get('美债10Y')
        if tnx: snap_parts.append(f"美债10Y:{tnx:.2f}%")
        vix = snap.get('sentiment', {}).get('VIX')
        if vix:
            vix_icon = "🔴" if vix > 30 else ("🟡" if vix > 20 else "🟢")
            snap_parts.append(f"VIX:{vix:.1f}{vix_icon}")
        if snap_parts:
            w.write(doc_id, [('bullet', ' | '.join(snap_parts))])
    except Exception:
        pass

    try:
        nb = get_northbound_flow()
        if nb.get('data_ok'):
            nb_net = nb.get('today_net', 0)
            nb_icon = "🟢" if nb_net > 10 else ("🔴" if nb_net < -10 else "🟡")
            w.write(doc_id, [('bullet', f"北向资金: {nb_icon} 今日{nb_net:+.1f}亿 | 5日{nb.get('5d_cumulative',0):+.1f}亿 | {nb.get('signal','?')}")])
        else:
            w.write(doc_id, [('bullet', f"北向资金: ⚠️ {nb.get('note','数据不可用')}")])
    except Exception:
        pass

    us10y = None
    for y in bonds_data.get('us_treasury', {}).get('yields', []):
        if '10年' in y.get('name', '') and y.get('current'):
            us10y = y['current']; break
    if us10y and cpi != '?':
        try:
            real_rate = round(float(us10y) - float(cpi), 2)
            rr_icon = "🔴" if real_rate > 2 else ("🟡" if real_rate > 0.5 else "🟢")
            w.write(doc_id, [('bullet', f"实际利率={us10y:.2f}%-CPI{cpi}%={real_rate:.2f}% {rr_icon}")])
        except Exception:
            pass

    port_ret = lds.get('portfolio_ret_1d')
    need_rebal = lds.get('need_rebalance', False)
    w.write(doc_id, [('bullet',
        f"LDS全天候: 今日{_fmt(port_ret)} | YTD{_fmt(lds.get('portfolio_ytd'))} | "
        f"{'⚠️再平衡信号' if need_rebal else '✅无需再平衡'}"
    )])

    # 凯利开关
    if dual_closed:
        w.write(doc_id, [('bold', f"🔒 凯利f*关闭 → 不开新仓 | 止损线检查: 成本×0.92")])
        w.write(doc_id, [('bullet', f"双门转绿条件: CPI≥1.5%(当前={cpi}%) + 趋势温度回暖(当前={trend_temp})")])
    else:
        w.write(doc_id, [('bold', f"✅ 可操作 | 单票≤2%仓位 | 8%硬止损")])

    log("Panel done")

    # ─── 板块2：持仓风控 ───
    rpt.build_tracking_section(w, doc_id, scanner=None, macro=macro, section_prefix="二")
    log("Tracking done")

    # ─── 板块3：观察池今日信号 ───
    w.write(doc_id, [('divider', ''), ('h2', '👁️ 三、观察池今日信号')])
    w.write(doc_id, [('quote', '核心/底仓持续显示 | 有信号的关注票才展开')])

    try:
        from investment_system.output.report_v6 import _fetch_watchlist_prices, _calc_tech_signal
        from investment_system.domain import WATCHLIST
        prices = _fetch_watchlist_prices(list(WATCHLIST.keys()))

        flagged, core_no_signal = [], []
        for code, info in WATCHLIST.items():
            tier = info.get('tier', '关注')
            name = info.get('name', code)
            chain = info.get('chain', '')
            pd_info = prices.get(code, {})
            price = pd_info.get('price')
            if price is None: continue

            chg = pd_info.get('chg')
            rsi = pd_info.get('rsi')
            ma20 = pd_info.get('ma20')
            ma60 = pd_info.get('ma60')
            ma60_dev = pd_info.get('ma60_dev')
            tech_score = pd_info.get('tech_score')

            price_str = f"¥{price:.2f}" if isinstance(price, (int,float)) else "—"
            chg_str = f"{_arrow(chg)}{_fmt(chg)}" if chg is not None else ""

            signal_tags = []
            has_signal = False
            if rsi is not None:
                if rsi > 80: signal_tags.append(f"🔴超买RSI{rsi:.0f}"); has_signal = True
                elif rsi < 25: signal_tags.append(f"💡超卖RSI{rsi:.0f}"); has_signal = True
            if ma60_dev is not None:
                if ma60_dev > 40: signal_tags.append(f"⚠️偏MA60+{ma60_dev:.0f}%"); has_signal = True
                elif ma60_dev < -15: signal_tags.append(f"📉偏MA60{ma60_dev:.0f}%"); has_signal = True
            if abs(chg or 0) >= 5:
                signal_tags.append(f"{'📈大涨' if chg > 0 else '📉大跌'}{abs(chg):.1f}%"); has_signal = True

            # MA20/MA60具体价格作为买点参考
            buypoint_str = ""
            if ma20 and ma60:
                buypoint_str = f" | MA20¥{ma20:.2f} MA60¥{ma60:.2f}"

            line = f"**{name}**({code}) {price_str} {chg_str}{buypoint_str}"
            if signal_tags: line += " | " + " ".join(signal_tags)
            if tech_score is not None: line += f" | 技术{tech_score:.0f}分"
            line += f" [{chain}]"

            if has_signal:
                flagged.append((tier, line))
            elif tier in ('核心', '底仓'):
                core_no_signal.append((tier, line))

        if flagged:
            w.write(doc_id, [('bold', '⭐ 今日有信号')])
            for tier, line in sorted(flagged, key=lambda x: {'核心':0,'底仓':1,'关注':2,'追踪':3}.get(x[0],4)):
                w.write(doc_id, [('bullet', line)])
        if core_no_signal:
            w.write(doc_id, [('bold', '📋 核心/底仓（无特殊信号）')])
            for _, line in core_no_signal[:10]:
                w.write(doc_id, [('bullet', line)])

        anomaly_stocks_for_news = []
        for code, info in WATCHLIST.items():
            pd_info = prices.get(code, {})
            chg_val = pd_info.get("chg")
            if chg_val is not None and abs(chg_val) >= 5:
                anomaly_stocks_for_news.append({
                    "symbol": code,
                    "name": info.get("name", code),
                    "chg": chg_val,
                    "price": pd_info.get("price"),
                })

    except Exception as e:
        anomaly_stocks_for_news = []
        w.write(doc_id, [('bullet', f"⚠️ 观察池加载失败: {str(e)[:60]}")])
    log("Watchlist done")

    # ─── 板块4：链路摘要Hook ───
    w.write(doc_id, [('divider', ''), ('h2', '🔗 四、链路摘要')])

    SUMMARY_PATH = '/home/admin/.hermes/investment_system/data/weekly_chain_summary.json'
    chain_summary = None
    try:
        if os.path.exists(SUMMARY_PATH):
            with open(SUMMARY_PATH) as f:
                chain_summary = json.load(f)
    except Exception:
        pass

    if chain_summary:
        generated_at = chain_summary.get('generated_at', '?')
        weekly_url = chain_summary.get('doc_url', '')
        w.write(doc_id, [('quote', f"数据来源：周报 {generated_at} | 点击查看完整研究")])
        if weekly_url:
            w.write(doc_id, [('bullet', f"📊 完整周报: {weekly_url}")])

        chains_data = chain_summary.get('chains', {})
        changed, unchanged = [], []
        for chain_name, cdata in chains_data.items():
            gap_dir = cdata.get('gap_direction', '')
            perez = cdata.get('perez_stage', '')
            is_cond = cdata.get('is_conditional', False)
            cond_tag = "⚡条件触发" if is_cond else ""
            summary_line = f"{cond_tag}**{chain_name}**: {perez[:25]} | 缺口:{gap_dir[:20]}"
            unchanged.append(summary_line)

        w.write(doc_id, [('bold', f"本周链状态（{len(unchanged)}条链）：")])
        for line in unchanged:
            w.write(doc_id, [('bullet', line)])
        w.write(doc_id, [('bullet', f"→ 完整链研究详见周报文档（链接见上）")])

        candidates = chain_summary.get('candidates', [])
        if candidates:
            w.write(doc_id, [('bold', f"🎯 本周候选 ({len(candidates)}只，周报扫描结果)：")])
            for c in candidates:
                track = c.get("score_detail", {}).get("track", "")
                track_tag = "🔵" if "脱钩" in track else "🟡"
                price = c.get("price")
                ma20 = c.get("ma20")
                ma60 = c.get("ma60")
                price_str = f"¥{price:.2f}" if price else "?"
                ma_str = f"MA20¥{ma20:.2f}/MA60¥{ma60:.2f}" if ma20 and ma60 else ""
                reasons = "、".join(c.get("entry_reasons", [])[:2])
                w.write(doc_id, [('bullet',
                    f"{track_tag} **{c['name']}**({c['symbol']}) {price_str} {ma_str} | {c['chain']} | {reasons}"
                )])
    else:
        w.write(doc_id, [('text', "⚠️ 周报尚未生成，请先运行 run_weekly.py")])
    log("Chain hooks done")

    # ─── 板块5：今日情报（异动解读优先）───
    w.write(doc_id, [('divider', ''), ('h2', '📰 五、今日情报')])

    anomaly_results = []
    if anomaly_stocks_for_news:
        w.write(doc_id, [('quote', f"发现 {len(anomaly_stocks_for_news)} 只异动股（≥5%），正在搜索驱动因素...")])
        try:
            from investment_system.analysis.anomaly_news import (
                analyze_anomaly_stocks, format_anomaly_analysis_for_report
            )
            anomaly_results = analyze_anomaly_stocks(anomaly_stocks_for_news)
            lines = format_anomaly_analysis_for_report(anomaly_results)
            for block_type, content in lines:
                w.write(doc_id, [(block_type, content)])
            log(f"Anomaly analysis done: {len(anomaly_results)} stocks")
        except Exception as e:
            w.write(doc_id, [('bullet', f"⚠️ 异动分析失败: {str(e)[:80]}")])
            log(f"Anomaly analysis failed: {e}")
    else:
        w.write(doc_id, [('quote', '今日观察池无≥5%异动，展示常规市场情报')])

    if summary_text and len(summary_text.strip()) > 50:
        w.write(doc_id, [('bold', '📡 市场情报（AI分析）')])
        for line in summary_text.strip().split('\n')[:12]:
            line = line.strip()
            if line:
                w.write(doc_id, [('bullet', line[:250])])
    elif news_list:
        w.write(doc_id, [('bold', '📡 今日快讯')])
        for n in sorted(news_list, key=lambda x: len(x.get('impacts', [])), reverse=True)[:5]:
            title = n.get('title', '')
            if not title or len(title) < 10: continue
            impacts = n.get('impacts', [])
            imp_str = ' '.join(f"[{i['chain']}]{i['direction']}" for i in impacts[:2]) if impacts else ''
            w.write(doc_id, [('bullet', f"{title[:100]}{' → '+imp_str if imp_str else ''}")])

    try:
        from investment_system.analysis.news_engine import _calc_sentiment_score, classify_impact
        nl = classify_impact(news_list[:20]) if news_list else []
        sent = _calc_sentiment_score(nl)
        w.write(doc_id, [('bullet', f"市场情绪: {sent.get('overall','?')} | 利好{sent.get('bullish',0)}条 利空{sent.get('bearish',0)}条")])
    except Exception:
        pass
    log("News done")

    # ─── 板块6：调仓建议 ───
    rpt.build_action_section(w, doc_id, macro, section_prefix="六")
    log("Action done")

    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")
    print(f"✅ 面基三源融合日报 {session} 已生成")
    print(f"📄 飞书文档: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
