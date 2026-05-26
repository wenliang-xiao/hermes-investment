#!/usr/bin/env python3
"""面基三源融合日报 v7 — 全资产·链优先·AI驱动
架构: 10链核心分析 + 全金融扫描(ETF/债/汇/商/全天候) + 多源新闻LLM
"""
import sys, time, json, os, urllib.request
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.report_v6 as rpt
from investment_system.full_asset_scanner import (
    track_lds_portfolio, scan_all_etfs, scan_bonds, scan_commodities, 
    scan_fx, determine_bridgewater_quadrant
)
from investment_system.news_engine import get_news_with_impact

LF = '/tmp/report_v7_log.txt'
with open(LF, 'w') as f: f.write('')
def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== 日报 v7 START ===")

try:
    scanner = rpt.FactorScanner()
    scanner.MAX_SCAN = 15
    macro = rpt.MacroEngine().refresh()
    macro['favored_sectors'] = ['AI算力', '半导体', '科技']
    macro['avoided_sectors'] = []

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
    w.write(doc_id, [
        ('h2', '二、🌐 桥水全天候·宏观象限'),
        ('bold', f"当前象限: {bw.get('quadrant_name', '?')}"),
        ('bullet', f"增长: {'↑' if bw.get('growth','')=='up' else '↓'} | 通胀: {'↑' if bw.get('inflation','')=='up' else '↓'}"),
        ('bullet', f"推荐资产: {', '.join(bw.get('recommended', [])[:4])}"),
        ('bullet', f"回避: {', '.join(bw.get('avoid', [])[:3])}"),
        ('bullet', f"中国对照: {bw.get('china_note', '')}"),
        ('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF')),
    ])
    log("Bridgewater done")

    # ═══ 三、LDS 全天候组合 ═══
    lds = track_lds_portfolio()
    port = lds.get('portfolio', {})
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '三、🏛️ LDS 全天候 ETF 组合'),
        ('quote', '非择时·月度再平衡·4类低相关资产对冲 — 桥水风险平价思想'),
        ('bold', f"今日: {port.get('daily_return', '?')} | YTD: {port.get('ytd_return', '?')}"),
    ])
    for comp in lds.get('components', []):
        w.write(doc_id, [('bullet', f"{comp['name']}({comp['symbol']}): {comp.get('weight',0)*100:.0f}%权重 | 今日{comp.get('daily_pct', '?')}% | YTD{comp.get('ytd_pct', '?')}%")])
    w.write(doc_id, [
        ('bold', f"再平衡信号: {port.get('rebalance_signal', '?')}"),
        ('text', lds.get('valuation_note', '')),
        ('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF')),
    ])
    log("LDS portfolio done")

    # ═══ 四、ETF 全景 ═══
    etfs = scan_all_etfs()
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '四、📦 ETF 动量-风险-费率 三维排序'),
    ])
    for etf in etfs.get('top5', [])[:5]:
        w.write(doc_id, [('bullet', f"{etf['name']}({etf['symbol']}): 综合{etf['composite_score']} | 动量{etf.get('momentum_score','?')} | 波动率倒数{etf.get('vol_score','?')} | 费率{etf.get('fee_score','?')}")])
    w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '二、资产配置·LDS全天候ETF'))])
    log("ETF done")

    # ═══ 五、债券 ═══
    bonds = scan_bonds()
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '五、🏦 债券与收益率曲线'),
        ('bold', f"美债10Y: {bonds.get('us_10y_yield', '?')}% | 30Y: {bonds.get('us_30y_yield', '?')}%"),
        ('bullet', f"2Y-10Y利差: {bonds.get('curve_spread_bp', '?')}bp → 曲线: {bonds.get('curve_signal', '?')}"),
        ('bullet', f"中美利差: {bonds.get('cn_us_spread_bp', '?')}bp"),
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
        w.write(doc_id, [('bullet', f"{c['name']}: ${c.get('price','?')} | 20日{c.get('chg_20d_pct','?')}% | RSI{c.get('rsi_14','?')} | {c.get('signal','?')}")])
    w.write(doc_id, [('text', rpt.FeishuWriter.ref(w, '十六、全球经济格局'))])
    log("Commodities done")

    # ═══ 七、外汇 ═══
    fx = scan_fx()
    w.write(doc_id, [
        ('divider', ''),
        ('h2', '七、💱 外汇与地缘折价'),
    ])
    for pair_name in ['dxy', 'usdcny', 'usdjpy', 'eurusd']:
        p = fx.get(pair_name, {})
        if p:
            w.write(doc_id, [('bullet', f"{p.get('name', pair_name)}: {p.get('price', '?')} | 20日{p.get('chg_pct', '?')}%")])
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
