#!/usr/bin/env python3
"""
主日报 Builder v8 — 文档矩阵·指挥中心
每个 build_* 函数: (FeishuWriter, doc_id, macro_data) → writes to doc
原则：每个 builder 内部封装自己的数据获取+格式+降级显示+引用链接
"""
import sys
sys.path.insert(0, '/home/admin/.hermes')
from investment_system.full_asset_scanner import scan_commodities, scan_fx
from investment_system.fund_tracker import track_lds_portfolio_v2
from investment_system.news_engine import get_news_with_impact
from investment_system import config as cfg

# ── 辅助 ──
def _price_badge(price, fmt="%.1f"):
    """价格显示 + 数据质量降级"""
    if price is None:
        return "⚠️ 暂无"
    return fmt % price

def _ret_badge(ret, fmt="%+.1f%%"):
    if ret is None:
        return ""
    return f"({fmt % ret})"

def build_gate_line(w, doc_id, macro):
    """🚦 宏观信号 — 1行结论"""
    dual = macro.get('dual_gate', {})
    macro_ok = dual.get('macro_ok', False)
    trend_ok = dual.get('trend_ok', False)
    action = dual.get('action', '观望')
    mg = '🟢 开' if macro_ok else '🔴 关'
    tg = '🟢 开' if trend_ok else '🔴 关'
    cpi = macro.get('macro_data', {}).get('cpi', '?')
    regime = macro.get('regime', '?')
    drift = macro.get('trend_deviation_20', '?')
    switch = macro.get('strategy_switch', '?')
    w.write(doc_id, [
        ('h2', '🚦 今日宏观信号'),
        ('bold', f"双门: {mg} + {tg} → {action}"),
        ('bullet', f"象限: {regime} | CPI={cpi}% | 策略: {switch}"),
        ('bullet', f"趋势温度: {macro.get('trend_temp','?')} | 20日偏离: {drift}%"),
    ])

def build_market_snapshot(w, doc_id):
    """📊 市场快照 — 核心数字，无?，失败显示⚠️"""
    comm = scan_commodities()
    fx = scan_fx()
    w.write(doc_id, [('h2', '📊 市场快照')])
    
    # 黄金（核心关注）
    gold = None
    for c in comm.get('commodities', []):
        if '黄金' in c.get('name', ''):
            gold = c
            break
    if gold:
        price = _price_badge(gold.get('price'), "$%.0f")
        ret = _ret_badge(gold.get('ret_20d'))
        w.write(doc_id, [('bullet', f"黄金: {price} {ret}")])
    else:
        w.write(doc_id, [('bullet', '⚠️ 黄金数据延迟')])
    
    # 其他商品压缩1行
    others = [c for c in comm.get('commodities', [])[:4] if '黄金' not in c.get('name', '')]
    if others:
        parts = [f"{c['name']}: {_price_badge(c.get('price'), '$%.1f')} {_ret_badge(c.get('ret_20d'))}" for c in others]
        w.write(doc_id, [('bullet', ' | '.join(parts))])

def build_key_news(w, doc_id):
    """📰 今日重要事件 — 有影响才出现，≤3条"""
    news_list, summary = get_news_with_impact()
    w.write(doc_id, [('h2', '📰 今日重要事件')])
    if not news_list:
        w.write(doc_id, [('bullet', '今日无重大影响事件')])
        return
    for n in news_list[:3]:
        title = n.get('title', '')[:150]
        impacts = n.get('impacts', [])
        impact_str = ' → '.join([f"[{i.get('chain','')}]{i.get('direction','')}" for i in impacts]) if impacts else ''
        w.write(doc_id, [('bullet', f"{title}  {impact_str}")])

def build_position_status(w, doc_id):
    """🎯 重点票状态"""
    w.write(doc_id, [('h2', '🎯 重点票状态')])
    # 待配置持仓池后启用
    w.write(doc_id, [('bullet', '⚠️ 需先配置持仓池 → 详见 [重点票深度研究]')])

def build_mining_signals(w, doc_id, scanner, macro):
    """💡 今日挖掘信号 — 严格筛选 ≤3只"""
    w.write(doc_id, [('h2', '💡 今日挖掘信号')])
    try:
        picks = scanner.scan_market(top_n=5)
        shown = 0
        for p in picks[:5]:
            score = p.get('total', 0)
            if score < 7.0:  # 低于7分的不显示
                continue
            code = p.get('code', '?')
            name = p.get('name', code)
            w.write(doc_id, [('bullet', f"{name}({code}): 评分{score:.1f}/10 | PE={p.get('pe','?')} | ROE={p.get('roe','?')}%")])
            shown += 1
            if shown >= 3:
                break
        if shown == 0:
            w.write(doc_id, [('bullet', '今日无达标信号（评分≥7.0）')])
    except Exception as e:
        w.write(doc_id, [('bullet', f'⚠️ 扫描暂时不可用: {str(e)[:40]}')])

def build_discipline(w, doc_id, macro):
    """⚙ 今日操作纪律"""
    dual = macro.get('dual_gate', {})
    macro_ok = dual.get('macro_ok', False)
    trend_ok = dual.get('trend_ok', False)
    both_closed = not macro_ok and not trend_ok
    w.write(doc_id, [('h2', '⚙ 今日操作纪律')])
    if both_closed:
        w.write(doc_id, [
            ('bullet', '双门关闭 → 不开新仓'),
            ('bullet', '持有中: 检查是否触发8%止损线'),
            ('bullet', '观察中: 等待双门转绿再行动'),
        ])
    else:
        w.write(doc_id, [
            ('bullet', f"当前象限: {macro.get('regime','?')} — 正常操作"),
            ('bullet', '单票≤2%仓位 | 持有≤8只 | 8%硬止损不可商量'),
        ])
