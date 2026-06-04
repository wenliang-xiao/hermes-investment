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
    
    # 链内扩展: 构建已知链股票集合, 用于发现不在WATCHLIST但属于同链的新标的
    try:
        from investment_system.config import INDUSTRY_CHAINS, WATCHLIST as _CFG_WL
        _chain_stocks = {}  # chain_name → set of codes
        _watchlist_codes = set(str(k) for k in _CFG_WL if str(k).isdigit())
        for cn, cd in INDUSTRY_CHAINS.items():
            _chain_stocks[cn] = set(str(s) for s in cd.get('symbols', []) if str(s).isdigit())
        log(f"Chain discovery: {len(_chain_stocks)} chains, watchlist {len(_watchlist_codes)} A-shares")
    except Exception:
        _chain_stocks = {}
        _watchlist_codes = set()
    
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

    # ── ETF数据后台预取（与后续扫描并发执行）──
    _etf_future = None
    try:
        from concurrent.futures import ThreadPoolExecutor
        _etf_pool = ThreadPoolExecutor(max_workers=1)
        _etf_future = _etf_pool.submit(rpt.prefetch_etf_data)
    except Exception as _e:
        log(f"ETF预取启动失败: {_e}")

    w = rpt.FeishuWriter()
    today = time.strftime('%Y/%m/%d')
    today_short = time.strftime('%m-%d')
    weekday = ['一','二','三','四','五','六','日'][time.localtime().tm_wday]
    now_time = time.strftime('%H:%M')
    label = "盘前简报" if session == "开盘前" else "收盘简报"
    doc_id = w.create_doc(f"面基·{label} {today_short}({weekday}) {now_time}")
    log(f"Doc: {doc_id}")

    # ── 策略四模拟盘初始化 ──
    try:
        from investment_system.output.shadow_account import init_portfolio as _sa_init, get_portfolio_metrics as _sa_metrics
        _sa_init(1000000)
    except Exception:
        pass

    dual_gate = macro.get('dual_gate', {})
    macro_gate = dual_gate.get('macro_gate', '?')
    trend_gate = dual_gate.get('trend_gate', '?')
    action = dual_gate.get('action', '?')
    cpi = macro.get('macro_data', {}).get('cpi', '?')
    cpi_mom = macro.get('macro_data', {}).get('cpi_momentum_3m') or macro.get('macro_data', {}).get('cpi_delta', 0) or 0
    trend_temp = macro.get('trend_temp', '?')
    bw_name = bw.get('quadrant_name', '?') if isinstance(bw, dict) else '?'
    favored = macro.get('favored_sectors', [])
    guoyun = macro.get('guoyun', {})
    guoyun_dev = guoyun.get('deviation', '?')

    gate_icon = "🔴" if macro_gate in ("红灯","黄灯") else "🟢"
    trend_icon = "🔴" if trend_gate in ("红灯","黄灯") else "🟢"
    dual_closed = macro_gate in ("红灯","黄灯") and trend_gate in ("红灯","黄灯")

    # ═══════════════════════════════════════════════
    #  面基·LDS·桥水 三源融合量化投研日报 v7
    # ═══════════════════════════════════════════════
    lds_judgment = "只研究，不开仓" if dual_closed else ("控制仓位" if macro_gate=="黄灯" else "正常操作")

    # ── 0. 市场全景 ──
    w.write(doc_id, [('h2', '0. 市场全景')])
    # 全球快照
    try:
        mkts = []
        snap = get_global_market_snapshot()
        idx = snap.get('indices', {})
        for name in ['标普500','纳斯达克','恒生']:
            d = idx.get(name)
            if d:
                p = d.get('price') if isinstance(d, dict) else d
                obs = '[观测]' if name in ('标普500','纳斯达克') else ''
                if p: mkts.append(f'{name}:{p:,.0f}{obs}')
        if mkts: w.write(doc_id, [('text', ' | '.join(mkts))])
    except: pass
    # A股
    try:
        nb = get_northbound_flow()
        if nb.get('data_ok'):
            w.write(doc_id, [('text', f'A股: 北向{nb.get("today_net",0):+.1f}亿 | 5日{nb.get("5d_cumulative",0):+.1f}亿')])
    except: pass
    # 宏观
    guoyun = macro.get('guoyun', {})
    w.write(doc_id, [
        ('bold', f'{regime} | CPI={cpi}% 3月动量{cpi_mom:+.2f}% | 趋势{trend_temp} | 国运线{guoyun.get("deviation","?")}%'),
        ('text', f'双门{macro_gate}·{trend_gate} → {lds_judgment} | 偏好: {"/".join(favored[:3])}'),
    ])
    if dual_closed:
        prio_text = ""
        try:
            if os.path.exists('/tmp/hermes_top_priority.json'):
                with open('/tmp/hermes_top_priority.json') as f:
                    prio = json.load(f)
                prio_text = f" | 转绿第一优先级: {prio.get('name','?')}({prio.get('symbol','?')})"
        except: pass
        w.write(doc_id, [('text', f'转绿条件: CPI≥1.0%+趋势≥温{prio_text}')])
    w.write(doc_id, [('divider', '')])

    # ── 谁在赢 (实时价格信号) ──
    try:
        leaders, laggards = [], []
        for code, info in WATCHLIST.items():
            if not str(code).isdigit(): continue
            pd_info = prices.get(code, {})
            chg = pd_info.get('chg')
            if chg is None: continue
            chain = info.get('chain', '')
            if chg > 3: leaders.append((info.get('name',code), code, chg, chain))
            elif chg < -3: laggards.append((info.get('name',code), code, chg, chain))
        leaders.sort(key=lambda x: -x[2])
        if leaders or laggards:
            w.write(doc_id, [('bold', '🔥 谁在赢 — 价格是最贵的信号')])
            if leaders:
                w.write(doc_id, [('bullet', '领涨: ' + ' | '.join(f'{n}({c})+{chg:.1f}% [{chain}]' for n,c,chg,chain in leaders[:6]))])
            if laggards:
                w.write(doc_id, [('bullet', '领跌: ' + ' | '.join(f'{n}({c}){chg:.1f}%' for n,c,chg,_ in laggards[:3]))])
    except: pass
    w.write(doc_id, [('divider', '')])

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

    # ═══ 3. 选股引擎: 观察池 ═══
    w.write(doc_id, [('divider', ''), ('h2', '👁️ 3. 观察池信号')])
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

    # ═══ 3.4 低共识狩猎 — 跌幅大+基本面好的逆向机会 ═══
    try:
        contrarian = []
        for code, info in WATCHLIST.items():
            if not str(code).isdigit(): continue
            pd_info = prices.get(code, {})
            chg = pd_info.get('chg')
            rsi = pd_info.get('rsi')
            if chg is None: continue
            if chg <= -3 and rsi and rsi < 40:
                roe = pd_info.get('roe') if 'roe' in pd_info else None
                if not roe:
                    try:
                        from investment_system.data.data_layer import get_financial_report
                        fin = get_financial_report(code)
                        roe = fin.get('净资产收益率')
                    except: pass
                if roe and float(roe) > 15:
                    contrarian.append((info.get('name', code), code, chg, roe, rsi))
        if contrarian:
            w.write(doc_id, [('bold', f'🔎 3.4 低共识狩猎: {len(contrarian)}只 (跌幅>3%+ROE>15%→逆向研究)')])
            for name, code, chg, roe, rsi in contrarian[:3]:
                w.write(doc_id, [('bullet',
                    f"**{name}**({code}) {chg:+.1f}% | ROE{roe:.0f}% | RSI{rsi:.0f} | 市场悲观+基本面强=逆向机会"
                )])
    except Exception:
        pass

    # ─── 3.5 今日扫描发现 ───
    w.write(doc_id, [('divider', ''), ('h2', '🔍 3.5 扫描发现')])
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
            # 信号质量评估
            top_scores = [s.get('score', 0) for s in scan_results[:10]]
            score_range = max(top_scores) - min(top_scores) if top_scores else 0
            avg_score = sum(top_scores) / len(top_scores) if top_scores else 0
            
            # vs前次对比
            prev_avg = 0
            try:
                if os.path.exists(SNAP_FILE):
                    with open(SNAP_FILE) as f:
                        prev_snap = json.load(f)
                    prev_scores_list = [s.get('score', 0) for s in prev_snap.get('results', [])[:10]]
                    if prev_scores_list:
                        prev_avg = sum(prev_scores_list) / len(prev_scores_list)
            except: pass
            
            if score_range < 1.5 and avg_score < 6.5:
                quality = "⚠️ 偏低"
                quality_note = f"分数集中({min(top_scores):.1f}-{max(top_scores):.1f})均分{avg_score:.1f}"
            elif avg_score >= 6.5:
                quality = "✅ 良好"
                quality_note = f"均分{avg_score:.1f}"
            else:
                quality = "→ 一般"
                quality_note = f"均分{avg_score:.1f}区间{score_range:.1f}"
            
            if prev_avg > 0:
                delta = avg_score - prev_avg
                quality_note += f" | vs前次{delta:+.1f}{'↑改善' if delta > 0.2 else ('↓退步' if delta < -0.2 else '→持平')}"
            
            w.write(doc_id, [('bold', f'📊 今日TOP{len(scan_results)} | 信号质量: {quality} — {quality_note}')])
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

    # ═══ 3.6 因子有效性 ═══
    if scan_results and scan_status == "complete":
        try:
            from investment_system.analysis.factor_quality import save_snapshot, get_quality_report
            # 从扫描结果提取价格（scan_one自带的price字段）
            _price_map = {str(s.get('symbol', '')): s.get('price') 
                         for s in scan_results if s.get('price') is not None}
            save_snapshot(scan_results, prices_map=_price_map)
            log(f"Factor snapshot saved ({len(scan_results)} stocks, {len(_price_map)} prices)")

            # 保存今日最高分票 → 供明日报决策摘要「转绿第一优先级」
            best = max(scan_results, key=lambda s: s.get('score', 0))
            import json as _json
            try:
                with open('/tmp/hermes_top_priority.json', 'w') as _f:
                    _json.dump({
                        'name': best.get('name', ''),
                        'symbol': best.get('symbol', ''),
                        'score': round(best.get('score', 0), 1),
                        'date': time.strftime('%Y-%m-%d'),
                    }, _f)
            except Exception:
                pass

            qr = get_quality_report()
            factor_ic = qr.get("factor_ic", {})
            if factor_ic:
                parts = []
                for fn, r in factor_ic.items():
                    if r is None: continue
                    ic = r["ic"]
                    icon = "↑" if ic > 0.05 else ("→" if ic > 0.02 else "↓")
                    parts.append(f"{fn}{icon}{ic:.3f}")
                if parts:
                    eff = qr.get("effective", [])
                    weak = qr.get("weak", [])
                    w.write(doc_id, [('divider', ''), ('h2', '🔬 3.6 因子有效性')])
                    w.write(doc_id, [('bold', f"IC(5日): {' | '.join(parts)}")])
                    w.write(doc_id, [('text',
                        f"✅有效: {'/'.join(eff) if eff else '无'} | ⚠️弱: {'/'.join(weak) if weak else '无'} | 动态权重应偏向有效因子")])
        except Exception as e:
            log(f"Factor quality skipped: {e}")

    # ═══ 链内新发现: 扫描结果中属于已知链但不处于WATCHLIST的标的 ═══
    if scan_results and scan_status == "complete" and _chain_stocks:
        discoveries = []
        for s in scan_results:
            sym = str(s.get('symbol', ''))
            if not sym or sym in _watchlist_codes: continue
            score = s.get('score', 0)
            if score < 6.0: continue
            # 查找该票属于哪个链
            for cn, codes in _chain_stocks.items():
                if sym in codes:
                    discoveries.append((cn, s))
                    break
        if discoveries:
            w.write(doc_id, [('divider', ''), ('bold', f'🔎 链内新发现: {len(discoveries)}只 (已评分≥6, 同链但不在观察池)')])
            for cn, s in discoveries[:5]:
                w.write(doc_id, [('bullet',
                    f"**{s.get('name','?')}**({s.get('symbol','?')}) {s.get('score',0):.1f}分 | {cn} | ROE{s.get('roe','?')}%"
                )])

    # ═══ Nick四问 + 四重确认 — 对扫描TOP3做深度分析 ═══
    if scan_results and scan_status == "complete":
        w.write(doc_id, [('divider', ''), ('h2', '🔬 3.6 Nick四问+四重确认')])
        top3 = [s for s in scan_results[:3] if s.get('score', 0) > 0]
        if top3:
            for rank, s in enumerate(top3, 1):
                sym = s.get('symbol', '?')
                name = s.get('name', sym)
                score = s.get('score', 0)
                chain = s.get('sector', '?')
                chg = s.get('change_pct') or 0
                roe = s.get('roe')
                pe_pct = s.get('pe_percentile')

                # Nick四问
                q1 = "✅ 扫描TOP{0}".format(rank) if score >= 5 else "⚠️ 分数偏低"
                q2 = "✅" if chg > 0 else ("⚠️ 下跌" if chg < -2 else "→ 平稳")
                q3_score = sum(1 for rd in flagged if rd[1] == sym) if 'flagged' in dir() else 0
                q3 = "🔴 高共识" if abs(chg) >= 5 else ("🟡 有信号" if q3_score > 0 else "🟢 无异常共识")
                q4 = "⚠️ 偏MA60" if s.get('ma60_dev', 0) > 40 else "✅"

                # 四重确认
                check_macro = "❌ CPI<1%" if isinstance(cpi, (int,float)) and cpi < 1.0 else "✅"
                check_trend = "✅" if trend_temp in ('温','热') else ("⚠️ 平" if trend_temp == '平' else "❌")
                check_logic = "✅" if chain and chain not in ('?','') else "⚠️"
                check_tech = "✅" if score >= 5 else "⚠️"
                passes = sum(1 for c in [check_macro, check_trend, check_logic, check_tech] if c.startswith('✅'))
                
                w.write(doc_id, [
                    ('bold', f"#{rank} {name}({sym}) {score:.1f}分 | {chain}"),
                    ('text', f"  Q1紧迫度:{q1} | Q2趋势:{q2} | Q3共识:{q3} | Q4拥挤度:{q4}"),
                    ('text', f"  四重确认: 宏观{check_macro} 趋势{check_trend} 逻辑{check_logic} 技术{check_tech} → {'✅通过' if passes==4 else f'⚠️ {passes}/4 不通过'}"),
                ])
        else:
            w.write(doc_id, [('text', '⏳ 扫描数据不足，无法执行四重确认')])

        # 转绿后第一优先级 (持久化)
        if top3 and dual_closed:
            top_pick = top3[0]
            priority = {
                'name': top_pick.get('name', '?'),
                'symbol': top_pick.get('symbol', '?'),
                'score': top_pick.get('score', 0),
                'date': today,
                'regime': regime
            }
            try:
                with open('/tmp/hermes_top_priority.json', 'w') as f:
                    json.dump(priority, f)
            except: pass
            w.write(doc_id, [('bold', f"📌 转绿后第一优先级: {priority['name']}({priority['symbol']}) {priority['score']:.1f}分")])
            w.write(doc_id, [('text', f"需满足四重确认全部通过 → 首批50%仓位 | 单票≤2% | 止损-8%")])

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
                if _sc2 < 5.5:
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

    # ═══ 4. 策略四多资产模拟盘 ═══
    w.write(doc_id, [('divider', ''), ('h2', '💼 4. 组合状态')])
    try:
        from investment_system.output.strategy4_portfolio import snapshot as _s4_snap, init as _s4_init, daily as _s4_daily
        _s4_init(regime)
        _s4_daily(macro, scan_results if scan_results else [])
        snap = _s4_snap()

        w.write(doc_id, [('bold', f"总值 ¥{snap['total_value']:,.0f} | {snap['regime']} | 仓位{snap['position_pct']:.0f}%"),])

        alloc = snap.get('allocations', {})
        alloc_lines = []
        for key, label in [('a_share','A股链内'),('stock_etf','股票ETF'),('bond_etf','债券ETF'),
                           ('gold_etf','黄金ETF'),('commodity_etf','商品ETF'),('us_stock','美股'),('hk_stock','港股')]:
            a = alloc.get(key, {})
            target = a.get('target', 0)
            if key in ('stock_etf','bond_etf','commodity_etf','gold_etf'):
                pick = a.get('picked', {})
                sym = pick.get('symbol', '?')
                alloc_lines.append(f"{label}: ¥{target:,} → {sym}")
            elif key == 'a_share':
                status = "⏸️" if dual_closed else "待建仓"
                alloc_lines.append(f"{label}: ¥{target:,} → {status}")
            else:
                alloc_lines.append(f"{label}: ¥{target:,}")
        w.write(doc_id, [('text', ' | '.join(alloc_lines))])

        # Link to dashboard
        w.write(doc_id, [('text', w.ref("📊 详细面板 → http://47.85.161.255:8686/dashboard"))])

        # 今日操作
        actions = snap.get('daily_actions', [])
        if actions:
            for a in actions:
                w.write(doc_id, [('text', a)])
        else:
            reason = "双门关闭，ETF/黄金/商品维持配比" if dual_closed else "维持配比"
            w.write(doc_id, [('text', f"今日操作: {reason}")])

        # G=E×P×F×T
        w.write(doc_id, [('text',
            f"G=E×P×F×T: D+{snap['days_alive']} | 浮盈¥{snap['unrealized_pnl']:+,.0f} | 锁定¥{snap['realized_pnl']:+,.0f} | {'安全✅' if snap['traversal_ok'] else '⚠️注意回撤'}")])

    except Exception as e:
        w.write(doc_id, [('text', f'⏳ 策略四模拟盘加载中... ({str(e)[:60]})')])

    # ═══ 5. 国产替代追踪 ═══
    w.write(doc_id, [('divider', ''), ('h2', '🏭 5. 国产替代追踪')])
    w.write(doc_id, [('text', '国产化率<30%=替代空间巨大 | 30-60%=加速期 | >60%=成熟期')])
    try:
        from investment_system.config import DOMESTIC_SUB_THEMES
        themes = sorted(DOMESTIC_SUB_THEMES.items(), key=lambda x: x[1].get('localization_rate', 100))
        for tn, td in themes[:5]:
            lr = td.get('localization_rate', 0)
            lr_pct = round(lr * 100) if lr < 1 else lr
            score = td.get('decoupling_score', 0)
            stocks = td.get('key_stocks_a', [])[:3]
            w.write(doc_id, [('bullet',
                f"{'🔴' if lr_pct < 20 else '🟡'} **{tn}**: 国产化率{lr_pct}% | 脱钩评分{score}/10 | {'/'.join(stocks)}"
            )])
    except Exception:
        w.write(doc_id, [('text', '国产替代数据加载中...')])

    # ─── ETF/债券组合推荐 ───
    # ── 收集ETF预取数据 → 传入ETF板块（预取与扫描并发，缩短总耗时）──
    _a_etf_prices, _us_etf_prices = {}, {}
    if _etf_future is not None:
        try:
            _a_etf_prices, _us_etf_prices = _etf_future.result(timeout=120)
            log(f"ETF数据预取完成: A股{len(_a_etf_prices)}只/美股{len(_us_etf_prices)}只")
        except Exception as _e:
            log(f"ETF预取结果收集失败(不影响日报): {_e}")
        finally:
            try:
                _etf_pool.shutdown(wait=False)
            except Exception:
                pass

    rpt.build_etf_portfolio_section(w, doc_id, macro=macro, dual_closed=dual_closed,
                                    session=session, a_etf_prices=_a_etf_prices, us_etf_prices=_us_etf_prices)
    log("ETF portfolio done")

    # ─── 7. 链路摘要 ───
    w.write(doc_id, [('divider', ''), ('h2', '🔗 7. 链路摘要')])

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

    # ─── 8. 情报摘要 ───
    w.write(doc_id, [('divider', ''), ('h2', '📰 8. 情报摘要')])
    w.write(doc_id, [('bold', '8.1 异动分析')])

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
        w.write(doc_id, [('bold', '📡 8.2 市场情报')])
        import re as _re
        bullish, bearish, neutral = [], [], []
        for line in summary_text.strip().split('\n')[:20]:
            line = line.strip()
            line = _re.sub(r'^#{1,4}\s*', '', line)
            line = _re.sub(r'^>\s*', '', line)
            if '情绪得分' in line or not line: continue
            if any(kw in line for kw in ['利好', '↑', '增长', '突破', '超预期', '改善', '上升']):
                bullish.append(('🟢', line[:200]))
            elif any(kw in line for kw in ['利空', '↓', '下跌', '衰退', '制裁', '风险', '流出']):
                bearish.append(('🔴', line[:200]))
            else:
                neutral.append(('🟡', line[:200]))
        for icon, line in bullish[:3]:
            w.write(doc_id, [('bullet', f'{icon} {line}')])
        for icon, line in bearish[:3]:
            w.write(doc_id, [('bullet', f'{icon} {line}')])
        for icon, line in neutral[:2]:
            w.write(doc_id, [('bullet', f'{icon} {line}')])
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

    # ─── 9. 行动建议 ───
    rpt.build_action_section(w, doc_id, macro, section_prefix="9")

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
