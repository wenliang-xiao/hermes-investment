#!/usr/bin/env python3
"""
面基·LDS·Vibe-Trading 三源融合·周报 (快速版)
优化版：跳过不可用的数据源，使用缓存，适用于受限网络环境
"""
import sys, time, json, os, socket

# Set aggressive socket timeout to fail fast
socket.setdefaulttimeout(3)

sys.path.insert(0, '/home/admin/.hermes')

import investment_system.output.report_v6 as rpt
from investment_system.output.full_asset_scanner import (
    scan_commodities, scan_fx, scan_bonds, determine_bridgewater_quadrant
)
from investment_system.output.fund_tracker import track_lds_portfolio_v2, scan_all_etf_groups
from investment_system.analysis.news_engine import get_news_with_impact

LF = '/tmp/report_weekly_log.txt'
with open(LF, 'w') as f: f.write('')

def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== 周报 FAST START ===")

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

    # Reduce scan size significantly for speed
    scanner.MAX_SCAN = 10
    log(f"扫描计划: MAX_SCAN=10 (快速版)")

    w = rpt.FeishuWriter()
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·周报 {time.strftime('%Y/%m/%d')} (周{['一','二','三','四','五','六','日'][time.localtime().tm_wday]})")
    log(f"Doc: {doc_id}")

    t0 = time.time()

    w.write(doc_id, [
        ('h1', f"{rpt.SAN_YUAN_NAME}·周报"),
        ('text', f"周期: {time.strftime('%Y/%m/%d')} | 快速版(网络受限环境)"),
        ('text', "架构: LDS双门→桥水象限→全资产配置→链研究"),
        ('divider', ''),
    ])

    # ═══ 一、LDS双门 ═══
    rpt.build_gate_section(w, doc_id, macro)
    log("Gate done")

    # ═══ 二、桥水全天候象限 ═══
    try:
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
        bw_q = bw.get("current_quadrant", "")
    except Exception as e:
        log(f"Bridgewater失败: {e}")
        bw_q = ""
    log("Bridgewater done")

    # ═══ 三、LDS全天候ETF组合 ═══
    dual_open = not (macro.get("dual_gate", {}).get("macro_gate") == "红灯" and
                     macro.get("dual_gate", {}).get("trend_gate") == "红灯")
    try:
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
        w.write(doc_id, [('bold', f"再平衡: {'⚠️ ' + lds.get('rebalance_note','') if lds.get('need_rebalance',False) else '✅ ' + lds.get('rebalance_note','')}")])
    except Exception as e:
        log(f"LDS portfolio失败: {e}")
        w.write(doc_id, [('h2', '三、🏛️ LDS全天候ETF组合'), ('text', f"数据获取暂不可用: {e}")])
    log("LDS portfolio done")

    # ═══ 四、多资产配置 (简化) ═══
    try:
        w.write(doc_id, [('divider', ''), ('h2', '四、🎯 多资产配置建议')])
        ma_report = {}
        try:
            from investment_system.analysis.multi_asset_engine import run_daily_multi_asset_scan
            ma_report = run_daily_multi_asset_scan(regime=regime, bw_quadrant_override=bw_q)
            w.write(doc_id, [('bold', ma_report.get('summary', ''))])
            by_class = ma_report.get('by_class', {})
            for cls, assets in by_class.items():
                if not assets: continue
                lines = []
                for a in assets[:2]:
                    ret20 = f"{a['ret_20d']:+.1f}%" if a.get('ret_20d') is not None else "?%"
                    lines.append(f"{a.get('signal','⚪')} {a['name']}({a['id']}): 评分{a.get('score',0):.2f} | 20日{ret20} | 建议{a.get('weight_pct','?')}%")
                w.write(doc_id, [('bullet', f"【{cls}】 " + " / ".join(lines))])
            log(f"MultiAsset done")
        except Exception as e:
            log(f"MultiAsset failed(允许): {e}")
            w.write(doc_id, [('text', '多资产配置数据暂不可用')])
    except Exception as e:
        log(f"Section四失败: {e}")

    # ═══ 五、债券 ═══
    try:
        bonds = scan_bonds()
        ut = bonds.get('us_treasury', {})
        yields_by_name = {y.get('name', ''): y.get('current', '?') for y in ut.get('yields', [])}
        y10 = yields_by_name.get('美国10年期国债收益率', '?')
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '五、🏦 债券与收益率曲线'),
            ('bold', f"美债10Y: {y10}% | 2Y-10Y利差: {ut.get('2y_10y_spread','?')}bp | 中美利差: {bonds.get('cn_us_spread','?')}bp"),
        ])
    except Exception as e:
        log(f"Bonds failed: {e}")
    log("Bonds done")

    # ═══ 六、大宗商品 ═══
    try:
        comms = scan_commodities()
        w.write(doc_id, [('divider', ''), ('h2', '六、🛢️ 大宗商品')])
        for c in comms.get('commodities', [])[:6]:
            price = c.get('price')
            ret20 = c.get('ret_20d')
            price_str = f"${price:.2f}" if isinstance(price, (int, float)) else "⚠️"
            ret_str = f"{ret20:.2f}%" if isinstance(ret20, (int, float)) else "?"
            w.write(doc_id, [('bullet', f"{c['name']}: {price_str} | 20日{ret_str} | RSI{c.get('rsi_14','?')} | {c.get('signal','?')}")])
    except Exception as e:
        log(f"Commodities failed: {e}")
    log("Commodities done")

    # ═══ 七、外汇 ═══
    try:
        fx = scan_fx()
        w.write(doc_id, [('divider', ''), ('h2', '七、💱 外汇')])
        fx_by_key = {p.get('key'): p for p in fx.get('fx_pairs', []) if p.get('key')}
        for pair_name in ['DXY', 'USDCNY', 'USDJPY', 'EURUSD']:
            p = fx_by_key.get(pair_name, {})
            if p:
                w.write(doc_id, [('bullet', f"{p.get('name', pair_name)}: {p.get('price', '?')} | 20日{p.get('ret_20d', '?')}%")])
    except Exception as e:
        log(f"FX failed: {e}")
    log("FX done")

    # ═══ 八、全球市场快照 ═══
    try:
        rpt.build_market_snapshot(w, doc_id)
    except Exception as e:
        log(f"Market snapshot failed: {e}")
    log("Market snapshot done")

    # ═══ 九、15链(简化) ═══
    macro['chain_mode'] = 'active' if dual_open else 'observation'
    macro['bw_quadrant'] = bw_q
    try:
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '九、🔗 产业链研究（简化版）'),
            ('quote', f"本周宏观: {regime} | 双门: {'✅开启' if dual_open else '🔒关闭'}"),
        ])
        # Use cached chain configs
        for cfg in rpt._CHAIN_CONFIGS[:6]:
            name = cfg.get('name', '?')
            stage = cfg.get('perez_stage', '')
            pool = cfg.get('profit_pool', '')
            gap = cfg.get('gap_direction', '')
            lead = cfg.get('lead_ticker', '')
            w.write(doc_id, [('bullet', f"【{name}】Perez:{stage} | 利润池:{pool} | 缺口:{gap} | 龙头:{lead}")])
    except Exception as e:
        log(f"Chain section failed: {e}")
    log("Chain section done")

    # ═══ 十、新闻 ═══
    try:
        w.write(doc_id, [('divider', ''), ('h2', '十、📰 本周政经情报')])
        news_list, summary_text = get_news_with_impact()
        if summary_text:
            for line in summary_text.strip().split('\n')[:10]:
                line = line.strip()
                if line:
                    w.write(doc_id, [('bullet', line[:300])])
        else:
            for n in news_list[:5]:
                w.write(doc_id, [('bullet', n['title'][:120])])
    except Exception as e:
        log(f"News failed: {e}")
    log("News done")

    # ═══ 十一、催化剂日历 ═══
    try:
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '十一、📅 下周催化剂日历'),
            ('quote', '以下为各链预设催化剂，结合实际日历确认'),
        ])
        for cfg in rpt._CHAIN_CONFIGS[:6]:
            cats = cfg.get('catalysts', [])[:2]
            if cats:
                w.write(doc_id, [('bullet', f"【{cfg['name']}】 {' | '.join(cats)}")])
    except Exception as e:
        log(f"Catalyst calendar failed: {e}")
    log("Catalyst calendar done")

    # ═══ 十二、最终板块 ═══
    try:
        rpt.build_tracking_section(w, doc_id, scanner, macro)
        rpt.build_action_section(w, doc_id, macro)
        rpt.build_concept_section(w, doc_id)
    except Exception as e:
        log(f"Final sections failed: {e}")
    log("Final sections done")

    dt = time.time() - t0
    log(f"Total: {dt:.1f}s")

    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")
    print(f"✅ 面基三源融合周报(快速版) 已生成")
    print(f"📄 飞书文档: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
    print(f"❌ 周报生成失败: {e}")
