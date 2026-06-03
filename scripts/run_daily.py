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
from investment_system.analysis.factor_scanner import FactorScanner

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

    scanner = FactorScanner()
    scanner.macro = macro_engine
    log("Scanner ready")
    stock_context = []
    try:
        from investment_system.domain import WATCHLIST
        from investment_system.analysis.anomaly_news import fetch_stock_news
        core_codes = [k for k, v in WATCHLIST.items()
                      if str(k).isdigit() and v.get("tier") == "核心"][:15]
        from concurrent.futures import ThreadPoolExecutor, as_completed as _as_completed
        def _fetch_one(code):
            try:
                items = fetch_stock_news(code, max_items=3)
                return code, [it.get("title", "") for it in items if it.get("title")]
            except Exception:
                return code, []
        with ThreadPoolExecutor(max_workers=5) as _pool:
            _futs = {_pool.submit(_fetch_one, c): c for c in core_codes}
            core_news_map = {}
            for _f in _as_completed(_futs, timeout=30):
                c, titles = _f.result(timeout=10)
                if titles:
                    core_news_map[c] = titles
        for code, info in WATCHLIST.items():
            if code not in core_codes:
                continue
            pd_info = prices.get(code, {}) if 'prices' in dir() else {}
            chg_val = pd_info.get("chg")
            rsi_val = pd_info.get("rsi")
            sig = ""
            if chg_val and abs(chg_val) >= 5:
                sig = f"大涨跌{chg_val:+.1f}%"
            elif rsi_val and rsi_val < 25:
                sig = f"超卖RSI{rsi_val:.0f}"
            stock_context.append({
                "code": code,
                "name": info.get("name", code),
                "chg": chg_val,
                "signal": sig,
                "recent_news": core_news_map.get(code, []),
            })
    except Exception as _e:
        log(f"个股新闻预拉取失败(不影响日报): {_e}")

    news_list, summary_text = get_news_with_impact(
        window_days=1, stock_context=stock_context if stock_context else None
    )
    log("Data loaded")

    w = rpt.FeishuWriter()
    today = time.strftime('%Y/%m/%d')
    today_short = time.strftime('%m-%d')
    weekday = ['一','二','三','四','五','六','日'][time.localtime().tm_wday]
    now_time = time.strftime('%H:%M')
    label = "盘前简报" if session == "开盘前" else "收盘简报"
    doc_id = w.create_doc(f"面基·{label} {today_short}({weekday}) {now_time}")
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
        ('h1', f"{'🌅' if session == '开盘前' else '🌆'} 面基·{label} {today_short}({weekday}) {now_time}"),
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
        cpi_mom = macro.get('macro_data', {}).get('cpi_momentum_3m') or macro.get('macro_data', {}).get('cpi_delta', 0) or 0
        if isinstance(cpi, (int, float)) and cpi < 1.0:
            mom_str = f"3月动量{'已改善' if cpi_mom > 0.2 else '需改善'}(+{cpi_mom:.2f}%)"
            w.write(doc_id, [('bullet', f"双门转绿条件: CPI≥1.0%(当前={cpi}%) | {mom_str} + 趋势温度回暖(当前={trend_temp})")])
        else:
            w.write(doc_id, [('bullet', f"双门转绿条件: CPI≥1.0%(当前={cpi}%) + 趋势温度回暖(当前={trend_temp})")])
    else:
        w.write(doc_id, [('bold', f"✅ 可操作 | 单票≤2%仓位 | 8%硬止损")])

    log("Panel done")

    # ─── 模拟盘风控：价格更新 + 自动止损 ───
    log("Shadow pre-check...")
    try:
        from investment_system.output.shadow_account import (
            load_shadow as _sa_load, update_prices as _sa_update,
            check_stops as _sa_check, exit_position as _sa_exit,
            is_on_cooldown as _sa_cool, entry as _sa_entry,
            get_shadow_summary as _sa_summary, get_cooldown_list as _sa_cdlist,
        )
        from investment_system.output.report_v6 import _fetch_watchlist_prices as _sa_fetch
        _sa_book = _sa_load()
        _sa_syms = list(_sa_book.get("positions", {}).keys())
        if _sa_syms:
            _sa_pr = _sa_fetch(_sa_syms)
            _sa_pm = {str(k): v.get('price') for k, v in _sa_pr.items() if v.get('price')}
            if _sa_pm:
                _sa_update(_sa_pm)
            _sa_alerts = _sa_check()
            for _a in _sa_alerts:
                _ep = _sa_pm.get(_a["symbol"], _a.get("current", 0))
                if _ep:
                    _sa_exit(_a["symbol"], _ep, f"自动风控: {_a['type']}")
                    log(f"⚠️ Shadow AUTO-EXIT {_a['name']}({_a['symbol']}): {_a['type']}")
    except Exception as _e:
        log(f"⚠️ Shadow price/stop update: {_e}")
    # 冷却期垃圾清理
    try:
        from investment_system.output.shadow_account import clean_cooldown
        clean_cooldown()
    except Exception:
        pass
    log("Shadow pre-check done")

    # ─── 板块2：持仓风控 ───
    rpt.build_tracking_section(w, doc_id, scanner=scanner, macro=macro, section_prefix="二")
    log("Tracking done")

    # ─── 板块3：观察池今日信号 ───
    w.write(doc_id, [('divider', ''), ('h2', '👁️ 三、观察池今日信号')])
    w.write(doc_id, [('quote', '核心/底仓持续显示 | 有信号的关注票才展开')])

    try:
        from investment_system.output.report_v6 import _fetch_watchlist_prices, _calc_tech_signal
        from investment_system.domain import WATCHLIST
        prices = _fetch_watchlist_prices(list(WATCHLIST.keys()))

        flagged, core_no_signal = [], []
        flagged_codes = []
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

            is_etf = not str(code).isdigit() or str(code).startswith(("5", "51", "15"))
            signal_tags = []
            has_signal = False
            if rsi is not None:
                if rsi > 80:
                    signal_tags.append(f"🔴超买RSI{rsi:.0f}"); has_signal = not dual_closed
                elif rsi < 25:
                    if not dual_closed and not is_etf:
                        signal_tags.append(f"💡超卖RSI{rsi:.0f}"); has_signal = True
            if ma60_dev is not None:
                if ma60_dev > 40: signal_tags.append(f"⚠️偏MA60+{ma60_dev:.0f}%"); has_signal = True
                elif ma60_dev < -15 and not is_etf:
                    signal_tags.append(f"📉偏MA60{ma60_dev:.0f}%"); has_signal = True
            if abs(chg or 0) >= 5:
                signal_tags.append(f"{'📈大涨' if chg > 0 else '📉大跌'}{abs(chg):.1f}%"); has_signal = True

            buypoint_str = ""
            if ma20 and ma60:
                buypoint_str = f" | MA20¥{ma20:.2f} MA60¥{ma60:.2f}"

            line = f"**{name}**({code}) {price_str} {chg_str}{buypoint_str}"
            if signal_tags: line += " | " + " ".join(signal_tags)
            if tech_score is not None: line += f" | 技术{tech_score:.0f}分"
            line += f" [{chain}]"

            if has_signal:
                flagged.append((tier, code, line))
                flagged_codes.append(code)
            elif tier in ('核心', '底仓'):
                core_no_signal.append((tier, line))

        research_map = {}
        if flagged_codes:
            try:
                from investment_system.analysis.research_report import batch_research_summary, format_research_line
                research_map = batch_research_summary(flagged_codes, days=30)
            except Exception:
                pass

        if flagged:
            w.write(doc_id, [('bold', '⭐ 今日有信号')])
            for tier, code, line in sorted(flagged, key=lambda x: {'核心':0,'底仓':1,'关注':2,'追踪':3}.get(x[0],4)):
                w.write(doc_id, [('bullet', line)])
                rr_line = format_research_line(research_map.get(code)) if research_map else ""
                if rr_line:
                    w.write(doc_id, [('bullet', rr_line)])
        if core_no_signal:
            show_count = min(5, len(core_no_signal))
            w.write(doc_id, [('bold', f'📋 核心/底仓（无特殊信号，{show_count}/{len(core_no_signal)}只）')])
            for _, line in core_no_signal[:show_count]:
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

    # ─── 板块3.5：今日扫描发现（跨cron分批续扫）───
    w.write(doc_id, [('divider', ''), ('h2', '🔍 三点五、今日扫描发现')])
    w.write(doc_id, [('quote', f'宏观象限:{regime} | 六因子动态扫描 | 板块轮抽覆盖')])
    scan_results = []
    scan_status = ""
    try:
        scanner.MAX_SCAN = 30
        scan_results, scan_status = scanner.scan_market_batch(batch_size=15, top_n=10)

        # 加载上次扫描快照 — 用于显示排名/分数变化
        prev_scores = {}
        SNAP_FILE = '/tmp/hermes_scan_snapshot.json'
        if scan_status == "complete":
            try:
                if os.path.exists(SNAP_FILE):
                    with open(SNAP_FILE) as f:
                        snap = json.load(f)
                    for s in snap.get("results", []):
                        prev_scores[s.get("symbol", "")] = {
                            "score": s.get("score", 0), "rank": s.get("rank", 0)}
            except Exception:
                pass
            # 保存本次快照供下次对比
            snap_data = {"date": today, "regime": regime,
                         "results": [{"symbol": s.get("symbol",""), "name": s.get("name",""),
                                      "score": s.get("score",0), "rank": i+1}
                                     for i, s in enumerate(scan_results[:15])]}
            try:
                with open(SNAP_FILE, 'w') as f:
                    json.dump(snap_data, f)
            except Exception:
                pass

        if scan_status == "complete":
            w.write(doc_id, [('bold', f'📊 今日TOP{len(scan_results)} 综合排名')])
            for rank, s in enumerate(scan_results[:10], 1):
                name = s.get("name", s.get("symbol", "?"))
                sym = s.get("symbol", "?")
                score = s.get("score", 0)
                sector = s.get("sector", "")
                chg = s.get("change_pct")
                chg_s = f"{_arrow(chg)}{_fmt(chg)}" if chg is not None else ""
                reasons = []
                if s.get("pe_percentile") is not None:
                    reasons.append(f"PE分位{s['pe_percentile']:.0f}%")
                if s.get("roe"):
                    reasons.append(f"ROE{s['roe']:.0f}%")
                r_str = ' | '.join(reasons[:2]) if reasons else ''
                # 变化标注
                delta = ""
                if sym in prev_scores:
                    p = prev_scores[sym]
                    if p["rank"] and rank != p["rank"]:
                        dr = p["rank"] - rank
                        delta += f" {'↑' if dr > 0 else '↓'}{abs(dr)}(#{p['rank']}→#{rank})"
                    ds = score - p["score"]
                    if abs(ds) > 0.3:
                        delta += f" 分{'↑' if ds > 0 else '↓'}{abs(ds):.1f}"
                else:
                    delta = " 🆕"
                w.write(doc_id, [('bullet',
                    f"#{rank} **{name}**({sym})  {chg_s} | 综合{score:.1f}分 | {sector}{delta}{' | '+r_str if r_str else ''}"
                )])
        elif scan_status.startswith("partial:"):
            prog = scan_status.split(":")[1]
            w.write(doc_id, [('text', f'⏳ 扫描进行中 ({prog}) — 下次cron续扫剩余批次')])
            if scan_results:
                w.write(doc_id, [('bold', f'📊 部分结果（{len(scan_results)}只，待全量后排名）')])
                for rank, s in enumerate(scan_results[:5], 1):
                    name = s.get("name", s.get("symbol", "?"))
                    sym = s.get("symbol", "?")
                    score = s.get("score", 0)
                    sector = s.get("sector", "")
                    chg = s.get("change_pct")
                    chg_s = f"{_arrow(chg)}{_fmt(chg)}" if chg is not None else ""
                    w.write(doc_id, [('bullet',
                        f"#{rank} **{name}**({sym})  {chg_s} | 综合{score:.1f}分 | {sector}"
                    )])
        else:
            w.write(doc_id, [('text', '⏳ 扫描批次已初始化，下次cron开始评分')])
    except Exception as scan_err:
        w.write(doc_id, [('bullet', f'⚠️ 扫描跳过: {str(scan_err)[:60]}')])
        log(f"Scanner failed (non-critical): {scan_err}")
    log("Scanner section done")

    # ─── 模拟盘建仓/清仓（六因子评分驱动 + 组合风控）───
    log("Shadow entry/exit engine...")
    try:
        if scan_results and not dual_closed and scan_status == "complete":
            _sa_sum = _sa_summary()
            _hold = {p["symbol"] for p in _sa_sum.get("positions", [])}
            _hold_count = len(_hold)
            _sc_map = {s.get("symbol", ""): s.get("score", 0) for s in scan_results}
            MAX_POSITIONS = 8

            # ── 建仓：TOP5中非持仓+非冷却+非异动+评分≥6 ──
            _n = 0
            for _i, _s in enumerate(scan_results[:5], 1):
                if _hold_count + _n >= MAX_POSITIONS:
                    log(f"  MAX_POSITIONS({MAX_POSITIONS}) reached, stop entry")
                    break
                _sy = _s.get("symbol", "")
                if not _sy or _sy in _hold:
                    continue
                if _sa_cool(_sy):
                    log(f"  COOLDOWN skip {_sy}"); continue
                if abs(_s.get("change_pct", 0) or 0) >= 5:
                    log(f"  VOLATILE skip {_sy}"); continue
                _sc2 = _s.get("score", 0)
                if _sc2 < 6.0:
                    log(f"  LOW_SCORE skip {_sy}: {_sc2:.1f}"); continue
                _pr = _s.get("price", 0)
                if _pr <= 0:
                    continue
                _nm = _s.get("name", _sy)
                _q = max(100, int(20000 / _pr))
                _sa_entry(_sy, _nm, "买入", _pr,
                         f"六因子扫描TOP{_i} 综合{_sc2:.1f}分",
                         quantity=_q, pct=0.02, entry_score=_sc2)
                _n += 1
                log(f"✅ Shadow ENTRY {_nm}({_sy}) @¥{_pr:.2f} score={_sc2:.1f}")
            log(f"Shadow new entries: {_n}")

            # ── 清仓：评分<4 或 持仓>20天且不在TOP30 ──
            _sa_sum2 = _sa_summary()
            for _p in _sa_sum2.get("positions", []):
                _sy = _p["symbol"]
                _score = _sc_map.get(_sy)
                _ep = _p.get("current", 0)
                if _score is not None and _score < 4.0:
                    if _ep:
                        _sa_exit(_sy, _ep, f"六因子评分降至{_score:.1f}分<4 → 清仓")
                        log(f"🔻 Shadow EXIT {_p['name']}({_sy}): score={_score:.1f}")
                elif _score is None:
                    _hd = _p.get("hold_days", 0)
                    if _hd > 20:
                        if _ep:
                            _sa_exit(_sy, _ep, f"持仓{_hd}天未进TOP30 → 清仓")
                            log(f"🔻 Shadow EXIT {_p['name']}({_sy}): hold={_hd}d, not in scan")

        elif scan_results and not dual_closed and scan_status.startswith("partial:"):
            log(f"Scan partial ({scan_status}): skip entry/exit until full scan completes")

        else:
            log(f"Shadow entry/exit skipped: results={bool(scan_results)} dual_closed={dual_closed} status={scan_status}")

    except Exception as _e:
        log(f"⚠️ Shadow entry/exit: {_e}")
    log("Shadow entry/exit done")

    # ─── 板块4：ETF/债券组合推荐 ───
    rpt.build_etf_portfolio_section(w, doc_id, macro=macro, dual_closed=dual_closed, session=session)
    log("ETF portfolio done")

    # ─── 板块4：链路摘要Hook ───
    w.write(doc_id, [('divider', ''), ('h2', '🔗 五、链路摘要')])

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
        # fallback: 无周报时从链定义直出摘要
        w.write(doc_id, [('text', "⏳ 周报尚未运行 → 展示产业链基本面摘要（链定义数据）")])
        try:
            from investment_system.domain import OPPORTUNITY_THEMES, INDUSTRY_CHAINS, WATCHLIST
            # 统计各链当前持仓数
            chain_stocks = {}
            for code, info in WATCHLIST.items():
                c = info.get("chain", "")
                if c:
                    chain_stocks.setdefault(c, []).append(info["name"])
            # 主题机会摘要（取前4条最重要的）
            theme_items = []
            for tn, td in sorted(OPPORTUNITY_THEMES.items(), key=lambda x: len(x[1].get("key_catalysts",[])), reverse=True)[:4]:
                stage = td.get("perez_stage", "")
                logic = td.get("logic", "")[:80]
                catalysts = " / ".join(td.get("key_catalysts", [])[:3])
                stocks_in = []
                for a in td.get("a_stocks_focus", []):
                    if a in WATCHLIST:
                        stocks_in.append(WATCHLIST[a]["name"])
                for us in td.get("us_stocks_focus", []):
                    if us in WATCHLIST:
                        stocks_in.append(WATCHLIST[us]["name"])
                for hk in td.get("hk_stocks_focus", []):
                    if hk in WATCHLIST:
                        stocks_in.append(WATCHLIST[hk]["name"])
                stock_tag = f"🔗 {'/'.join(stocks_in[:3])}" if stocks_in else ""
                theme_items.append(f"**{tn}**【{stage}】{logic[:60]}… | 催化: {catalysts} {stock_tag}")
            if theme_items:
                w.write(doc_id, [('bold', '🏭 机会主题（面基概念链）')])
                for ti in theme_items:
                    w.write(doc_id, [('bullet', ti)])
            # 产业链利润池摘要
            chain_items = []
            for cn, cd in INDUSTRY_CHAINS.items():
                desc = cd.get("description", "")[:80]
                perez = cd.get("perez_stage", "")
                ml = cd.get("meso_layer", {})
                lifecycle = ml.get("lifecycle", "")
                valuation = ml.get("valuation", "")[:60]
                lds_logic = cd.get("lds_logic", "")[:100]
                stocks_in = chain_stocks.get(cn, [])
                stock_tag = f"📊 {'/'.join(stocks_in[:4])}" if stocks_in else ""
                chain_items.append(f"**{cn}** | {perez} | {lifecycle} | {desc}")
                if valuation:
                    chain_items.append(f"· 估值: {valuation}")
                if lds_logic:
                    chain_items.append(f"· LDS逻辑: {lds_logic}…")
                if stock_tag:
                    chain_items.append(f"· {stock_tag}")
            if chain_items:
                w.write(doc_id, [('bold', '🔬 产业链核心追踪')])
                for ci in chain_items[:12]:
                    w.write(doc_id, [('bullet', ci)])
                w.write(doc_id, [('text', '→ 完整研究请等待本周周报运行')])
        except Exception as e:
            w.write(doc_id, [('bullet', f"⚠️ 链定义加载失败: {str(e)[:60]}")
            ])
    log("Chain hooks done")

    # ─── 板块5：今日情报（异动解读优先）───
    w.write(doc_id, [('divider', ''), ('h2', '📰 六、今日情报')])

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
        import re as _re
        clean_lines = []
        for line in summary_text.strip().split('\n')[:15]:
            line = line.strip()
            # 去掉markdown标题符号
            line = _re.sub(r'^#{1,4}\s*', '', line)
            # 去掉blockquote符号
            line = _re.sub(r'^>\s*', '', line)
            # 去掉LLM自带的"情绪得分"行（我们有独立的）
            if '情绪得分' in line or '利好0' in line or '利空0' in line:
                continue
            if line:
                clean_lines.append(line[:250])
        for line in clean_lines:
            w.write(doc_id, [('bullet', line)])
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
        # fallback: 如果RSS空，用个股新闻标题做情绪打分
        if not nl and stock_context:
            ctx_news = [{"title": t} for sc in stock_context for t in sc.get("recent_news", []) if sc.get("recent_news")]
            if ctx_news:
                nl = classify_impact(ctx_news[:20])
        sent = _calc_sentiment_score(nl)
        w.write(doc_id, [('bullet', f"市场情绪: {sent.get('overall','?')} | 利好{sent.get('bullish',0)}条 利空{sent.get('bearish',0)}条")])
    except Exception:
        pass
    log("News done")

    # ─── 板块6：调仓建议 ───
    rpt.build_action_section(w, doc_id, macro, section_prefix="七")

    # ── 今日具体行动（基于今日实际信号）──
    w.write(doc_id, [('h3', '🎯 今日具体行动')])
    try:
        today_movers = []
        for a in (anomaly_stocks_for_news or []):
            today_movers.append(f"{a['name']}({a.get('symbol','')}) {a.get('chg',0):+.1f}%")
        if dual_closed:
            w.write(doc_id, [('bullet', '🔒 双门关闭，不开新仓。持有票检查trailing stop。')])
            if today_movers:
                w.write(doc_id, [('bullet',
                    f"⚠️ 异动股{' / '.join(today_movers)} → 双门关闭期内大涨不可追，检查是否触发止盈线"
                )])
            nb_val = locals().get('nb_net')
            if nb_val is not None:
                w.write(doc_id, [('bullet',
                    f"💨 北向资金{'流出' if nb_val < -10 else '中性'} {nb_val:+.1f}亿 → 与双门信号一致，不做任何加仓"
                )])
            w.write(doc_id, [('bullet',
                f"⏰ 转绿条件: CPI≥1.0%(当前={cpi}%){' 或通缩持续改善' if isinstance(cpi, (int,float)) and cpi < 1.0 else ''} + 趋势温度回暖(当前={trend_temp})"
            )])
        else:
            w.write(doc_id, [('bullet', f"✅ 双门开启 → 正常操作。优先进攻方向: {'/'.join(favored[:3] or ['均衡'])}")])
            if today_movers and len(today_movers) <= 3:
                w.write(doc_id, [('bullet',
                    f"💡 {today_movers[0].split('(')[0]}今日异动 → 检查是否有催化事件，如双门开启可逐步建仓"
                )])
            nb_val = locals().get('nb_net')
            if nb_val is not None and nb_val > 30:
                w.write(doc_id, [('bullet', f"🟢 北向大幅流入 {nb_val:+.1f}亿，与双门信号共振 → 积极关注")])
        if 'flagged' in dir() or 'flagged' in locals():
            f_stocks = [x for x in locals().get('flagged', [])[:3]]
            if f_stocks and not dual_closed:
                w.write(doc_id, [('bullet', f"📌 关注今日有信号的票: {', '.join(x[2].split('**')[1] for x in f_stocks if len(x[2].split('**'))>1)} — 优先选趋势右侧+ROE>15%的")])
        log("Today actions written")
    except Exception as e:
        log(f"Today actions failed (non-critical): {e}")
    log("Action done")

    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")
    print(f"✅ 面基三源融合日报 {session} 已生成")
    print(f"📄 飞书文档: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
