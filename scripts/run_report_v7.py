#!/usr/bin/env python3
"""面基三源融合日报 v7 — 全资产·链优先·AI驱动
架构: 10链核心分析 + 全金融扫描(ETF/债/汇/商/全天候) + 多源新闻LLM
"""
import sys, time, json, os, urllib.request
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.report_v6 as rpt
from investment_system.full_asset_scanner import (
    scan_all_etfs, scan_bonds, scan_commodities,
    scan_fx, determine_bridgewater_quadrant
)
from investment_system.fund_tracker import track_lds_portfolio_v2, scan_all_etf_groups
from investment_system.universe_builder import build_daily_scan_plan
from investment_system.multi_asset_engine import run_daily_multi_asset_scan
from investment_system.news_engine import get_news_with_impact

LF = '/tmp/report_v7_log.txt'
with open(LF, 'w') as f: f.write('')
def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== 日报 v7 START ===")

try:
    scanner = rpt.FactorScanner()
    macro_engine = rpt.MacroEngine()
    macro = macro_engine.refresh()
    macro['favored_sectors'] = ['AI算力', '半导体', '科技', '国产替代']
    macro['avoided_sectors'] = []

    # 构建每日动态扫描计划（研究池+买入池+脱钩池）
    try:
        scan_plan = build_daily_scan_plan()
        scanner.MAX_SCAN = min(len(scan_plan.get('buy_universe_codes', [])), 120)
        log(f"扫描计划: 研究池{len(scan_plan['research_universe'])}只 "
            f"买入池{len(scan_plan['buy_universe_codes'])}只 "
            f"脱钩池{len(scan_plan['decoupling_candidates'])}只")
    except Exception as e:
        scan_plan = {}
        scanner.MAX_SCAN = 50
        log(f"扫描计划构建失败(使用默认): {e}")

    w = rpt.FeishuWriter()
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·日报 v7 {time.strftime('%Y/%m/%d')}")
    log(f"Doc: {doc_id}")
    rpt._WRITE_COUNT[0] = 0
    
    t0 = time.time()

    # ═══ 标题 ═══
    w.write(doc_id, [
        ('h2', f"{rpt.SAN_YUAN_NAME}·日报 v7"),
        ('text', f"日期: {time.strftime('%Y/%m/%d')} | v7 链优先·全资产·AI驱动"),
        ('text', "架构: LDS双门→桥水象限→10链→全金融(ETF/债/汇/商/全天候)→新闻→概念"),
        ('divider', ''),
    ])
    log("Title done")

    # ═══ 一、LDS 双门 ═══
    rpt.build_gate_section(w, doc_id, macro)
    log("Gate done")

    # ═══ 二、桥水全天候四象限 ═══
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
        ('bullet', f"中国对照: {bw.get('china_parallel', '')}"),
        ('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF')),
    ])
    log("Bridgewater done")

    # ═══ 三、LDS 全天候组合 ═══
    lds = track_lds_portfolio_v2(version="A")
    dq = lds.get('data_quality', {})
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '三、🏛️ LDS 全天候 ETF 组合'),
        ('quote', '非择时·月度再平衡·4类低相关资产对冲 — 桥水风险平价思想'),
        ('bold', f"今日: {lds.get('portfolio_ret_1d', '?')} | YTD: {lds.get('portfolio_ytd', '?')}"),
    ])
    for comp in lds.get('components', []):
        ret1d = comp.get('ret_1d')
        ytd   = comp.get('ytd')
        badge = comp.get('data_badge', '')
        w.write(doc_id, [('bullet',
            f"{comp['name']}({comp.get('code','?')}): {comp.get('weight',0)*100:.0f}%权重 | "
            f"今日{f'{ret1d:+.2f}%' if ret1d is not None else '?'} | "
            f"YTD{f'{ytd:+.2f}%' if ytd is not None else '?'} | {badge}"
        )])
    rebalance_note = lds.get('rebalance_note', '')
    need = lds.get('need_rebalance', False)
    w.write(doc_id, [
        ('bold', f"再平衡信号: {'⚠️ ' + rebalance_note if need else '✅ ' + rebalance_note}"),
        ('text', f"数据质量: {dq.get('badge', '')}"),
        ('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF')),
    ])
    log("LDS portfolio done")

    # ═══ 四、多资产配置引擎（风险调整收益最大化）═══
    try:
        regime_for_engine = macro.get('regime', 'default')
        ma_report = run_daily_multi_asset_scan(regime=regime_for_engine)
        w.write(doc_id, [
            ('divider', ''),
            ('h2', '四、🎯 多资产配置建议（风险平价 × 宏观匹配）'),
            ('quote', f"宏观象限: {ma_report.get('regime','?')} → {ma_report.get('bw_quadrant','?')} | 评分资产: {ma_report.get('total_scored','?')}只"),
            ('bold', ma_report.get('summary', '')),
        ])
        by_class = ma_report.get('by_class', {})
        for cls, assets in by_class.items():
            if not assets:
                continue
            cls_lines = []
            for a in assets[:2]:
                ret20 = f"{a['ret_20d']:+.1f}%" if a.get('ret_20d') is not None else "?%"
                sharpe = f"夏普≈{a['sharpe']:.2f}" if a.get('sharpe') is not None else ""
                cls_lines.append(
                    f"{a['signal']} {a['name']}({a['id']}): "
                    f"评分{a['score']:.2f} | 20日{ret20} | {sharpe} | "
                    f"建议仓位{a.get('weight_pct','?')}%"
                )
            w.write(doc_id, [('bullet', f"【{cls}】 " + " / ".join(cls_lines))])
        avoid = ma_report.get('avoid_list', [])
        if avoid:
            avoid_str = "、".join(f"{a['name']}({a['id']})" for a in avoid[:3])
            w.write(doc_id, [('bullet', f"🔴 当前回避：{avoid_str}")])
        w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF'))])
        log(f"MultiAsset engine done: {ma_report.get('total_scored',0)} assets scored")
    except Exception as e:
        log(f"MultiAsset engine failed: {e}")
        w.write(doc_id, [('bullet', f"多资产引擎暂时不可用: {e}")])

    # ═══ 四B、ETF 全景三维排序（保留）═══
    etfs = scan_all_etfs()
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '四B、📦 ETF 动量-风险-费率 三维排序'),
    ])
    for etf in etfs.get('top_5', [])[:5]:
        w.write(doc_id, [('bullet', f"{etf['name']}({etf['symbol']}): 综合{etf.get('_composite','?')} | 动量{etf.get('ret_20d','?')}%")])
    w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF'))])
    log("ETF done")

    # ═══ 五、债券 ═══
    bonds = scan_bonds()
    ut = bonds.get('us_treasury', {})
    yields_by_name = {}
    for y in ut.get('yields', []):
        yields_by_name[y.get('name', '')] = y.get('current', '?')
    y10 = yields_by_name.get('美国10年期国债收益率', '?')
    y30 = yields_by_name.get('美国30年期国债收益率', '?')
    curve_spread = ut.get('2y_10y_spread', '?')
    curve_signal = ut.get('signal', '?')
    cn_spread = bonds.get('cn_us_spread', '?')
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '五、🏦 债券与收益率曲线'),
        ('bold', f"美债10Y: {y10}% | 30Y: {y30}%"),
        ('bullet', f"2Y-10Y利差: {curve_spread}bp → 曲线: {curve_signal}"),
        ('bullet', f"中美利差: {cn_spread}bp"),
        ('text', rpt.FeishuWriter.ref(w, '十六、全球经济格局')),
    ])
    log("Bonds done")

    # ═══ 六、商品 ═══
    comms = scan_commodities()
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '六、🛢️ 大宗商品'),
    ])
    for c in comms.get('commodities', [])[:6]:
        w.write(doc_id, [('bullet', f"{c['name']}: ${c.get('price','?')} | 20日{c.get('ret_20d','?')}% | RSI{c.get('rsi_14','?')} | {c.get('signal','?')}")])
    w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '十六、全球经济格局'))])
    log("Commodities done")

    # ═══ 七、外汇 ═══
    fx = scan_fx()
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '七、💱 外汇与地缘折价'),
    ])
    fx_pairs = fx.get('fx_pairs', [])
    fx_by_key = {p.get('key'): p for p in fx_pairs if p.get('key')}
    for pair_name in ['DXY', 'USDCNY', 'USDJPY', 'EURUSD']:
        p = fx_by_key.get(pair_name, {})
        if p:
            w.write(doc_id, [('bullet', f"{p.get('name', pair_name)}: {p.get('price', '?')} | 20日{p.get('ret_20d', '?')}%")])
    w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '十六、全球经济格局'))])
    log("FX done")

    # ═══ 八、全球市场快照 ═══
    rpt.build_market_snapshot(w, doc_id)
    log("Market snapshot done")

    # ═══ 九、10链深度分析 ═══
    rpt.build_chain_section(w, doc_id, scanner, macro)
    log("Chain section done")

    # ═══ 十、多因子新票发现 ═══
    rpt.build_discovery_section(w, doc_id, scanner, macro)
    log("Discovery done")

    # ═══ 十一、新闻 ═══
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '十一、📰 政经要闻（多源+LLM总结+链影响）'),
    ])
    news_list, summary_text = get_news_with_impact()
    if summary_text:
        for line in summary_text.strip().split('\n')[:12]:
            line = line.strip()
            if line:
                w.write(doc_id, [('bullet', line[:250])])
    else:
        for n in news_list[:8]:
            impacts_str = ' → '.join([f"[{i['chain']}]{i['direction']}" for i in n.get('impacts', [])]) if n.get('impacts') else ''
            w.write(doc_id, [('bullet', f"{n['title'][:120]}{' ['+impacts_str+']' if impacts_str else ''}")])
    w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '十六、全球经济格局'))])
    log("News done")

    # ═══ 十二、追踪+调仓+概念 ═══
    rpt.build_tracking_section(w, doc_id, scanner, macro)
    rpt.build_action_section(w, doc_id, macro)
    rpt.build_concept_section(w, doc_id)
    log("Final sections done")

    dt = time.time() - t0
    log(f"Total: {dt:.1f}s, writes: {rpt._WRITE_COUNT[0]}")

    # 验证
    token = w._get_token()
    u = f"https://open.feishu.cn/open-apis/docx/v1/documents/{doc_id}/blocks?page_size=500"
    req = urllib.request.Request(u, headers={'Authorization': f'Bearer {token}'})
    items = json.loads(urllib.request.urlopen(req).read()).get('data', {}).get('items', [])
    bullets = sum(1 for b in items if b.get('block_type') == 12)
    heads = sum(1 for b in items if b.get('block_type') in [4, 5])
    log(f"VERIFY: {len(items)} blocks, headings={heads}, bullets={bullets}")
    log(f"RESULT: {'PASS (>100 bullets)' if bullets > 100 else 'FAIL'}")
    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
