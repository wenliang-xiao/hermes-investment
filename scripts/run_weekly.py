#!/usr/bin/env python3
"""
面基·LDS·Vibe-Trading 三源融合·周报
运行时间：每周日 18:00
内容：14条链深度分析 + 多资产配置 + ETF排序 + 催化剂日历 + 机会主题 + 链摘要写入

Hermes cron: 每周日 18:00
  command: python /home/admin/.hermes/investment_system/scripts/run_weekly.py
"""
import sys, time, json, os
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.output.report_v6 as rpt
from investment_system.output.full_asset_scanner import (
    scan_all_etfs, scan_bonds, scan_commodities,
    scan_fx, determine_bridgewater_quadrant
)
from investment_system.output.fund_tracker import track_lds_portfolio_v2, scan_all_etf_groups
from investment_system.analysis.universe_builder import build_daily_scan_plan
from investment_system.analysis.multi_asset_engine import run_daily_multi_asset_scan
from investment_system.analysis.news_engine import get_news_with_impact

LF = '/tmp/report_weekly_log.txt'
with open(LF, 'w') as f: f.write('')

def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== 周报 START ===")

try:
    scanner = rpt.FactorScanner()
    macro_engine = rpt.MacroEngine()
    macro = macro_engine.refresh()

    from investment_system import config as cfg_sys
    regime = macro.get('regime', 'default')
    rotation = cfg_sys.MACRO_SECTOR_ROTATION.get(regime, cfg_sys.MACRO_SECTOR_ROTATION['default'])
    macro['favored_sectors'] = rotation['favored']
    macro['avoided_sectors'] = rotation.get('unfavored', [])
    macro['lds_note'] = rotation.get('lds_note', '')

    try:
        scan_plan = build_daily_scan_plan()
        scanner.MAX_SCAN = min(len(scan_plan.get('buy_universe_codes', [])), 120)
        log(f"扫描计划: 研究池{len(scan_plan['research_universe'])}只")
    except Exception as e:
        scan_plan = {}
        scanner.MAX_SCAN = 50
        log(f"扫描计划构建失败(使用默认): {e}")

    w = rpt.FeishuWriter()
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·周报 {time.strftime('%Y/%m/%d')} (周{['一','二','三','四','五','六','日'][time.localtime().tm_wday]})")
    log(f"Doc: {doc_id}")

    t0 = time.time()

    w.write(doc_id, [
        ('h1', f"{rpt.SAN_YUAN_NAME}·周报"),
        ('text', f"周期: {time.strftime('%Y/%m/%d')} | 15条链全景研究 + 多资产配置"),
        ('text', "架构: LDS双门→桥水象限→15链深度→全资产配置→新票发现→催化剂日历"),
        ('divider', ''),
    ])

    # ═══ 一、LDS双门 ═══
    rpt.build_gate_section(w, doc_id, macro)
    log("Gate done")

    # ═══ 二、桥水全天候象限 ═══
    bw = determine_bridgewater_quadrant(macro.get('macro_data', {}))
    d = bw.get('detail', {})
    gw = '↑' if d.get('growth_signal') == 'up' else '↓'
    iw = '↑' if d.get('inflation_signal') == 'up' else '↓'
    w.write(doc_id, [
        ('h2', '二、🌐 桥水全天候·宏观象限'),
        ('bold', f"当前象限: {bw.get('quadrant_name', '?')}"),
        ('bullet', f"增长: {gw} ({d.get('pmi','?')}) | 通胀: {iw} ({d.get('cpi','?')}%)"),
        ('bullet', f"推荐资产: {', '.join(bw.get('recommended_assets', [])[:4])}"),
        ('bullet', f"回避: {', '.join(bw.get('avoid_assets', [])[:3])}"),
    ])
    log("Bridgewater done")

    # ═══ 三、LDS全天候ETF组合 ═══
    bw_q = bw.get("current_quadrant", "") if isinstance(bw, dict) else ""
    dual_open = not (macro.get("dual_gate", {}).get("macro_gate") == "红灯" and
                     macro.get("dual_gate", {}).get("trend_gate") == "红灯")
    lds = track_lds_portfolio_v2(version="A", bw_quadrant=bw_q, dual_gate_open=dual_open)
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '三、🏛️ LDS全天候ETF组合'),
        ('bold', f"本周: {lds.get('portfolio_ret_1d', '?')} | YTD: {lds.get('portfolio_ytd', '?')}"),
    ])
    for comp in lds.get('components', []):
        ret1d = comp.get('ret_1d')
        ytd = comp.get('ytd')
        w.write(doc_id, [('bullet',
            f"{comp['name']}({comp.get('code','?')}): {comp.get('weight',0)*100:.0f}%权重 | "
            f"今日{f'{ret1d:+.2f}%' if ret1d is not None else '?'} | "
            f"YTD{f'{ytd:+.2f}%' if ytd is not None else '?'}"
        )])
    rebalance_note = lds.get('rebalance_note', '')
    need = lds.get('need_rebalance', False)
    w.write(doc_id, [('bold', f"再平衡: {'⚠️ ' + rebalance_note if need else '✅ ' + rebalance_note}")])
    log("LDS portfolio done")

    # ═══ 四、多资产配置建议 ═══
    try:
        ma_report = run_daily_multi_asset_scan(regime=regime, bw_quadrant_override=bw_q)
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '四、🎯 多资产配置建议（风险平价×宏观匹配）'),
            ('bold', ma_report.get('summary', '')),
        ])
        by_class = ma_report.get('by_class', {})
        for cls, assets in by_class.items():
            if not assets: continue
            lines = []
            for a in assets[:2]:
                ret20 = f"{a['ret_20d']:+.1f}%" if a.get('ret_20d') is not None else "?%"
                lines.append(f"{a.get('signal','⚪')} {a['name']}({a['id']}): 评分{a.get('score',0):.2f} | 20日{ret20} | 建议{a.get('weight_pct','?')}%")
            w.write(doc_id, [('bullet', f"【{cls}】 " + " / ".join(lines))])
        log(f"MultiAsset done: {ma_report.get('total_scored',0)} assets")
    except Exception as e:
        log(f"MultiAsset failed: {e}")

    # ═══ 四B、ETF三维排序 ═══
    etfs = scan_all_etfs()
    w.write(doc_id, [('divider', ''), ('h2', '四B、📦 ETF动量-风险-费率三维排序')])
    for etf in etfs.get('top_5', [])[:5]:
        w.write(doc_id, [('bullet', f"{etf['name']}({etf['symbol']}): 综合{etf.get('_composite','?')} | 动量{etf.get('ret_20d','?')}%")])
    log("ETF done")

    # ═══ 五、债券与收益率曲线 ═══
    bonds = scan_bonds()
    ut = bonds.get('us_treasury', {})
    yields_by_name = {y.get('name', ''): y.get('current', '?') for y in ut.get('yields', [])}
    y10 = yields_by_name.get('美国10年期国债收益率', '?')
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '五、🏦 债券与收益率曲线'),
        ('bold', f"美债10Y: {y10}% | 2Y-10Y利差: {ut.get('2y_10y_spread','?')}bp | 中美利差: {bonds.get('cn_us_spread','?')}bp"),
    ])

    # ═══ 六、大宗商品 ═══
    comms = scan_commodities()
    w.write(doc_id, [('divider', ''), ('h2', '六、🛢️ 大宗商品')])
    for c in comms.get('commodities', [])[:6]:
        price = c.get('price')
        ret20 = c.get('ret_20d')
        price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "⚠️"
        ret_str = f"{ret20:.2f}%" if isinstance(ret20, (int, float)) else "?"
        w.write(doc_id, [('bullet', f"{c['name']}: {price_str} | 20日{ret_str} | RSI{c.get('rsi_14','?')} | {c.get('signal','?')}")])

    # ═══ 七、外汇 ═══
    fx = scan_fx()
    w.write(doc_id, [('divider', ''), ('h2', '七、💱 外汇')])
    fx_by_key = {p.get('key'): p for p in fx.get('fx_pairs', []) if p.get('key')}
    for pair_name in ['DXY', 'USDCNY', 'USDJPY', 'EURUSD']:
        p = fx_by_key.get(pair_name, {})
        if p:
            w.write(doc_id, [('bullet', f"{p.get('name', pair_name)}: {p.get('price', '?')} | 20日{p.get('ret_20d', '?')}%")])

    # ═══ 八、全球市场快照 ═══
    rpt.build_market_snapshot(w, doc_id)
    log("Market snapshot done")

    # ═══ 九、15链深度分析（核心，全部运行）═══
    macro['chain_mode'] = 'active' if dual_open else 'observation'
    macro['bw_quadrant'] = bw_q

    w.write(doc_id, [
        ('divider', ''),
        ('h2', '九、🔗 15链深度研究（周度全景）'),
        ('quote', f"本周宏观: {regime} | 双门: {'✅开启' if dual_open else '🔒关闭'} | 脱钩方向独立跟踪"),
    ])
    rpt.build_chain_section(w, doc_id, scanner, macro)
    log("Chain section done (all 15 chains)")

    # ═══ 十、多因子新票发现 ═══
    rpt.build_discovery_section(w, doc_id, scanner, macro)
    log("Discovery done")

    # ═══ 十一、新闻与情报（30天视角）═══
    w.write(doc_id, [('divider', ''), ('h2', '十一、📰 本周政经情报（30天视角+链影响）')])
    news_list, summary_text = get_news_with_impact()
    if summary_text:
        for line in summary_text.strip().split('\n')[:20]:
            line = line.strip()
            if line:
                w.write(doc_id, [('bullet', line[:300])])
    else:
        for n in news_list[:10]:
            impacts_str = ' '.join([f"[{i['chain']}]{i['direction']}" for i in n.get('impacts', [])]) if n.get('impacts') else ''
            w.write(doc_id, [('bullet', f"{n['title'][:120]}{' → '+impacts_str if impacts_str else ''}")])
    log("News done")

    # ═══ 十二、下周催化剂日历 ═══
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '十二、📅 下周催化剂日历'),
        ('quote', '以下为各链预设催化剂，结合实际日历确认'),
    ])
    from investment_system.output.report_v6 import _CHAIN_CONFIGS
    for cfg in _CHAIN_CONFIGS[:8]:
        cats = cfg.get('catalysts', [])[:2]
        if cats:
            w.write(doc_id, [('bullet', f"【{cfg['name']}】 {' | '.join(cats)}")])
    log("Catalyst calendar done")

    # ═══ 十三、追踪+调仓+概念 ═══
    rpt.build_tracking_section(w, doc_id, scanner, macro)
    rpt.build_action_section(w, doc_id, macro)
    rpt.build_concept_section(w, doc_id)
    log("Final sections done")

    dt = time.time() - t0
    log(f"Total: {dt:.1f}s")

    try:
        from investment_system.analysis.score_history import save_scores, save_macro_gate
        today_str = time.strftime('%Y-%m-%d')
        scored = scanner.scan_market(top_n=60)
        score_snapshot = {s["symbol"]: s["score"] for s in scored if not s.get("error")}
        if score_snapshot:
            save_scores(today_str, score_snapshot)
            log(f"因子分快照已保存: {len(score_snapshot)} 只 ({today_str})")
        dg = macro.get("dual_gate", {})
        save_macro_gate(today_str, dg.get("macro_gate", "?"), dg.get("trend_gate", "?"))
        log(f"双门状态已保存: {dg.get('macro_gate','?')}+{dg.get('trend_gate','?')}")

        try:
            from investment_system.analysis.score_history import build_historical_scores_from_prices
            from investment_system.data.data_layer import get_stock_daily
            from investment_system.config import WATCHLIST, INDUSTRY_CHAINS
            chain_syms = list({str(s) for c in INDUSTRY_CHAINS.values() for s in c.get("symbols", []) if str(s).isdigit()})
            watchlist_syms = [k for k in WATCHLIST.keys() if str(k).isdigit() and str(k) in set(chain_syms)]
            price_snap = {}
            for sym in watchlist_syms[:40]:
                try:
                    from datetime import datetime, timedelta
                    start_180 = (datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=180)).strftime("%Y-%m-%d")
                    df = get_stock_daily(sym, start=start_180, end=today_str)
                    if df is not None and not df.empty:
                        price_snap[sym] = df
                except Exception:
                    pass
            if price_snap:
                dlite_scores = build_historical_scores_from_prices(list(price_snap.keys()), price_snap, today_str, today_str, use_fundamentals=False)
                dlite_top8 = set(sorted(dlite_scores.get(today_str, {}).items(), key=lambda x: x[1], reverse=True)[:8])
                six_top8 = set(sorted(score_snapshot.items(), key=lambda x: x[1], reverse=True)[:8])
                dlite_syms = {s for s, _ in dlite_top8}
                six_syms = {s for s, _ in six_top8}
                overlap = len(dlite_syms & six_syms)
                overlap_pct = overlap / max(len(six_syms), 1)
                log(f"Shadow run: 六因子Top8={list(six_syms)} DLite Top8={list(dlite_syms)} 重叠{overlap}/8={overlap_pct:.0%}")
                w.write(doc_id, [
                    ('divider', ''),
                    ('h2', f'十五、🔬 Shadow Run — 六因子 vs D-lite 重叠率'),
                    ('bullet', f"本周六因子Top8: {', '.join(sorted(six_syms))}"),
                    ('bullet', f"D-lite动量Top8: {', '.join(sorted(dlite_syms))}"),
                    ('bold', f"重叠率: {overlap_pct:.0%} ({overlap}/8) — {'✅ 因子收敛良好' if overlap_pct >= 0.5 else '⚠️ 因子分歧，继续观察'}"),
                ])
        except Exception as e:
            log(f"Shadow run 对比失败(不影响报告): {e}")
    except Exception as e:
        log(f"因子分/双门快照保存失败(不影响报告): {e}")

    # ═══ 写入链摘要供日报引用 ═══
    chain_summary = {
        "generated_at": time.strftime('%Y-%m-%d %H:%M'),
        "doc_url": f"https://bytedance.feishu.cn/docx/{doc_id}",
        "regime": regime,
        "bw_quadrant": bw_q,
        "dual_open": dual_open,
        "chains": {}
    }
    for cfg in _CHAIN_CONFIGS:
        chain_summary["chains"][cfg["name"]] = {
            "perez_stage": cfg.get("perez_stage", ""),
            "profit_pool": cfg.get("profit_pool", ""),
            "gap_direction": cfg.get("gap_direction", ""),
            "is_conditional": cfg.get("is_conditional", False),
            "lead_ticker": cfg.get("lead_ticker", ""),
        }

    try:
        from investment_system.analysis.chain_scanner import scan_chain_candidates, format_candidate_for_report
        log("开始链内候选扫描...")
        candidates = scan_chain_candidates(regime=regime, dual_open=dual_open, verbose=True)
        chain_summary["candidates"] = candidates

        if candidates:
            w.write(doc_id, [
                ('divider', ''),
                ('h2', '十四、🎯 本周链内候选（动态扫描）'),
                ('quote', f"四段筛选+双轨评分 | 脱钩方向独立于双门 | {len(candidates)}只候选"),
            ])

            candidate_syms = [c['symbol'] for c in candidates if c.get('symbol')]
            research_map = {}
            try:
                from investment_system.analysis.research_report import batch_research_summary, format_research_line
                research_map = batch_research_summary(candidate_syms, days=30)
                log(f"研报数据获取: {sum(1 for v in research_map.values() if v)} / {len(candidate_syms)} 只有数据")
            except Exception as e:
                log(f"研报数据获取失败(不影响主报告): {e}")

            for c in candidates:
                track = c.get("score_detail", {}).get("track", "")
                track_tag = "🔵脱钩方向" if "脱钩" in track else "🟡宏观敏感"
                price = c.get("price")
                ma20 = c.get("ma20")
                ma60 = c.get("ma60")
                rsi = c.get("rsi")
                ma60_dev = c.get("ma60_dev")
                price_str = f"¥{price:.2f}" if price else "?"
                ma_str = f"MA20¥{ma20:.2f} MA60¥{ma60:.2f}" if ma20 and ma60 else ""
                w.write(doc_id, [
                    ('bold', f"{track_tag} {c['name']}({c['symbol']}) [{c['chain']}] 评分{c['score']:.1f}"),
                    ('bullet', f"价格: {price_str} | {ma_str} | RSI{rsi:.0f} | 偏MA60{ma60_dev:+.0f}%" if all([price,ma20,ma60,rsi,ma60_dev is not None]) else f"价格: {price_str}"),
                ])
                reasons = c.get("entry_reasons", [])
                if reasons:
                    w.write(doc_id, [('bullet', f"入选: {'、'.join(reasons)}")])
                w.write(doc_id, [
                    ('bullet', f"触发: {c.get('trigger_condition','')}"),
                    ('bullet', f"失效: {c.get('invalidation','')}"),
                ])
                rr_line = format_research_line(research_map.get(c.get('symbol', '')))
                if rr_line:
                    w.write(doc_id, [('bullet', rr_line)])
            log(f"候选扫描完成: {len(candidates)} 只")
    except Exception as e:
        log(f"候选扫描失败(不影响主报告): {e}")

    summary_path = '/home/admin/.hermes/investment_system/data/weekly_chain_summary.json'
    try:
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(chain_summary, f, ensure_ascii=False, indent=2)
        log(f"链摘要已写入: {summary_path}")
    except Exception as e:
        log(f"链摘要写入失败: {e}")

    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")
    print(f"✅ 面基三源融合周报 已生成")
    print(f"📄 飞书文档: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
