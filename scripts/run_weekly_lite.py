#!/usr/bin/env python3
"""
面基·LDS·Vibe-Trading 三源融合·周报 (极速版)
完全跳过所有不可用的数据源，使用缓存/静态数据
"""
import sys, time, json, os, socket
socket.setdefaulttimeout(2)

sys.path.insert(0, '/home/admin/.hermes')

import investment_system.output.report_v6 as rpt
from investment_system import config as cfg_sys

LF = '/tmp/report_weekly_log.txt'
with open(LF, 'w') as f: f.write('')

def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== 周报 LITE START ===")

try:
    # Load cached macro data if available
    macro = {}
    cached_macro_path = '/home/admin/.hermes/investment_system/data/macro_engine_cache.json'
    if os.path.exists(cached_macro_path):
        with open(cached_macro_path) as f:
            macro = json.load(f)
        log(f"从缓存加载宏观数据: {list(macro.keys())[:5]}")
    
    if not macro.get('regime'):
        # Try refreshing macro engine
        try:
            macro_engine = rpt.MacroEngine()
            macro = macro_engine.refresh()
        except Exception as e:
            log(f"MacroEngine刷新失败: {e}")
            macro = {'regime': 'default', 'dual_gate': {'macro_gate': '黄灯', 'trend_gate': '黄灯'}}
    
    regime = macro.get('regime', 'default')
    rotation = cfg_sys.MACRO_SECTOR_ROTATION.get(regime, cfg_sys.MACRO_SECTOR_ROTATION['default'])
    macro['favored_sectors'] = rotation['favored']
    macro['avoided_sectors'] = rotation.get('unfavored', [])
    macro['lds_note'] = rotation.get('lds_note', '')
    
    log(f"宏观 regime={regime}")

    w = rpt.FeishuWriter()
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·周报 {time.strftime('%Y/%m/%d')} (周{['一','二','三','四','五','六','日'][time.localtime().tm_wday]})")
    log(f"Doc: {doc_id}")

    t0 = time.time()

    # ─── 标题 ───
    w.write(doc_id, [
        ('h1', f"{rpt.SAN_YUAN_NAME}·周报"),
        ('text', f"周期: {time.strftime('%Y/%m/%d')} | 轻量版"),
        ('text', "架构: LDS双门→桥水象限→全资产概览→产业链配置"),
        ('divider', ''),
    ])

    # ─── 一、LDS双门 ───
    try:
        rpt.build_gate_section(w, doc_id, macro)
    except Exception as e:
        log(f"Gate失败: {e}")
    log("Gate done")

    # ─── 二、桥水全天候 ───
    try:
        from investment_system.output.full_asset_scanner import determine_bridgewater_quadrant
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

    # ─── 三、LDS组合 ───
    dual_open = not (macro.get("dual_gate", {}).get("macro_gate") == "红灯" and
                     macro.get("dual_gate", {}).get("trend_gate") == "红灯")
    try:
        # Use fund_tracker with minimal data fetches
        from investment_system.output.fund_tracker import track_lds_portfolio_v2
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
        log(f"LDS组合失败: {e}")
        w.write(doc_id, [('divider', ''), ('h2', '三、🏛️ LDS全天候ETF组合'), ('text', f'数据暂不可用')])
    log("LDS done")

    # ─── 四、市场快照 ───
    try:
        rpt.build_market_snapshot(w, doc_id)
    except Exception as e:
        log(f"Market snapshot failed: {e}")
    log("Market snapshot done")

    # ─── 五、产业链(静态) ───
    try:
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '四、🔗 产业链格局（面基框架）'),
            ('quote', f"宏观: {regime} | 双门: {'✅开启' if dual_open else '🔒关闭'}"),
        ])
        for cfg in rpt._CHAIN_CONFIGS:
            name = cfg.get('name', '?')
            stage = cfg.get('perez_stage', '')
            pool = cfg.get('profit_pool', '')
            gap = cfg.get('gap_direction', '')
            lead = cfg.get('lead_ticker', '')
            cond = '⚡条件性' if cfg.get('is_conditional', False) else ''
            w.write(doc_id, [('bullet', f"【{name}】{cond} Perez:{stage} | 利润池:{pool} | 脱钩方向:{gap} | 龙头:{lead}")])
    except Exception as e:
        log(f"Chain section failed: {e}")
    log("Chain section done")

    # ─── 六、催化剂日历 ───
    try:
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '五、📅 下周催化剂日历'),
            ('quote', '以下为各链预设催化剂，结合实际日历确认'),
        ])
        for cfg in rpt._CHAIN_CONFIGS:
            cats = cfg.get('catalysts', [])[:2]
            if cats:
                w.write(doc_id, [('bullet', f"【{cfg['name']}】 {' | '.join(cats)}")])
    except Exception as e:
        log(f"Catalyst calendar failed: {e}")
    log("Catalyst calendar done")

    # ─── 七、追踪+调仓+概念 ───
    try:
        from investment_system.analysis.factor_scanner import FactorScanner
        scanner = FactorScanner()
        scanner.MAX_SCAN = 5
        rpt.build_tracking_section(w, doc_id, scanner, macro)
        rpt.build_action_section(w, doc_id, macro)
        rpt.build_concept_section(w, doc_id)
    except Exception as e:
        log(f"Final sections failed: {e}")
    log("Final sections done")

    dt = time.time() - t0
    log(f"Total: {dt:.1f}s")
    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")

    print(f"✅ 面基三源融合周报(轻量版) 已生成")
    print(f"📄 飞书文档: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
    print(f"❌ 周报生成失败: {e}")
    sys.exit(1)
