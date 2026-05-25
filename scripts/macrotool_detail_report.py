#!/usr/bin/env python3
"""
宏观趋势详解 — 深度文档1 (每周一更新)
=====================================
文档矩阵·深度层：周频更新，详解宏观经济全景

板块：
  LDS双门详细分析 + 桥水四象限 + 多资产配置
  + 10链景气度热力图 + 债券/商品/外汇全景

用法：
  from scripts.macrotool_detail_report import build_macro_detail
  build_macro_detail(writer, doc_id, macro_data)
"""
import sys, time
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.report_v6 as rpt
from investment_system.full_asset_scanner import (
    scan_commodities, scan_fx, scan_bonds,
    determine_bridgewater_quadrant
)
from investment_system.fund_tracker import track_lds_portfolio_v2
from investment_system import config as cfg


def build_macro_detail(w, doc_id, macro):
    """
    构建宏观趋势详解文档。

    Args:
        w: FeishuWriter 实例
        doc_id: 目标文档 ID
        macro: MacroEngine.summarize() 返回的 dict

    Returns:
        None (直接写入飞书文档)
    """
    # ── 标题 ──
    w.write(doc_id, [
        ('h2', '📚 宏观趋势详解 — {} 周报'.format(time.strftime("%Y/%m/%d"))),
        ('text', '文档矩阵·深度层 | 每周一更新 | 数据来源: LDS+桥水+10链'),
        ('divider', ''),
    ])

    # ═══ 第一部分: LDS 双门详细分析 ═══
    w.write(doc_id, [('h2', '一、🚪 LDS 双门详细分析')])

    # TODO: 从 macro 中提取双门状态并详细分析
    dual_gate = macro.get('dual_gate', {})
    macro_ok = dual_gate.get('macro_ok', False)
    trend_ok = dual_gate.get('trend_ok', False)

    gate_macro = '🟢 开' if macro_ok else '🔴 关'
    gate_trend = '🟢 开' if trend_ok else '🔴 关'
    w.write(doc_id, [
        ('bold', '宏观门: {} ｜ 趋势门: {}'.format(gate_macro, gate_trend)),
        ('text', '象限: {} | 周期阶段: {}'.format(
            macro.get('quadrant', '?'), macro.get('regime', '?'))),
        ('text', '趋势温度: {} | 操作建议: {}'.format(
            macro.get('trend_temp', '?'), macro.get('trend_action', '?'))),
    ])

    # TODO: 详细分析 — CPI 趋势 / PMI 趋势 / M2 增速 / Shibor 利率
    md = macro.get('macro_data', {})
    w.write(doc_id, [('h3', '核心指标')])
    w.write(doc_id, [
        ('bullet', 'CPI: {}% (趋势: {})'.format(
            md.get('cpi', '?'), md.get('cpi_trend', '?'))),
        ('bullet', 'PMI: {} (趋势: {})'.format(
            md.get('pmi', '?'), md.get('pmi_trend', '?'))),
        ('bullet', 'M2增速: {}%'.format(md.get('m2_growth', '?'))),
        ('bullet', 'Shibor: {}%'.format(md.get('shibor', '?'))),
        ('bullet', '人民币汇率: {}'.format(md.get('cny_usd', '?'))),
    ])

    # TODO: 国运线分析
    guoyun = macro.get('guoyun', {})
    if guoyun:
        w.write(doc_id, [('h3', '国运线视角')])
        w.write(doc_id, [
            ('bullet', '当前价: {}'.format(guoyun.get('price', '?'))),
            ('bullet', '偏离: {}'.format(guoyun.get('deviation', '?'))),
            ('text', guoyun.get('note', '')),
        ])

    # ═══ 第二部分: 桥水四象限 ═══
    w.write(doc_id, [('h2', '二、🌐 桥水全天候四象限')])

    try:
        quad = determine_bridgewater_quadrant(macro)
        w.write(doc_id, [
            ('text', '当前象限: {}'.format(quad.get('quadrant', '?'))),
            ('text', '增长方向: {} | 通胀方向: {}'.format(
                quad.get('growth_direction', '?'),
                quad.get('inflation_direction', '?'))),
        ])
        # TODO: 推荐资产类别
        recommended = quad.get('recommended_assets', [])
        if recommended:
            w.write(doc_id, [('bold', '推荐资产:')])
            for asset in recommended:
                w.write(doc_id, [('bullet', str(asset))])
    except Exception as e:
        w.write(doc_id, [
            ('bullet', '⚠️ 桥水象限暂时不可用: {}'.format(str(e)[:40]))
        ])

    # ═══ 第三部分: 多资产配置 ═══
    w.write(doc_id, [('h2', '三、💰 多资产配置全景')])

    # TODO: LDS 全天候组合追踪
    try:
        lds_portfolio = track_lds_portfolio_v2()
        if lds_portfolio:
            w.write(doc_id, [('h3', 'LDS 全天候组合')])
            positions = lds_portfolio.get('positions', [])
            for pos in positions[:6]:
                line = '{}: {}% | 价格: {} | 20日回报: {}'.format(
                    pos.get('name', '?'), pos.get('weight', '?'),
                    pos.get('price', '?'), pos.get('ret_20d', '?'))
                w.write(doc_id, [('bullet', line)])
    except Exception as e:
        w.write(doc_id, [
            ('bullet', '⚠️ LDS组合数据暂不可用: {}'.format(str(e)[:40]))
        ])

    # TODO: 建议仓位
    pos_pct = macro.get('suggested_position', 0.5) * 100
    w.write(doc_id, [
        ('bold', '建议总仓位: {:.0f}%'.format(pos_pct)),
        ('text', '策略开关: {} — {}'.format(
            macro.get('strategy_switch', '?'),
            macro.get('strategy_reason', ''))),
    ])

    # ═══ 第四部分: 10链景气度热力图 ═══
    w.write(doc_id, [('h2', '四、🔥 10链景气度热力图')])
    # TODO: 集成 sector_temp 数据，生成热力图描述
    sector_temp = macro.get('sector_temp', {})
    if sector_temp:
        w.write(doc_id, [('text', '板块温度分布（热/温/平/凉）:')])
        for sector, temp in sector_temp.items():
            w.write(doc_id, [('bullet', '{}: {}'.format(sector, temp))])
    else:
        w.write(doc_id, [('bullet', '⚠️ 板块温度数据暂未就绪')])

    # TODO: MACRO_SECTOR_ROTATION 轮动建议
    rotation = getattr(cfg, 'MACRO_SECTOR_ROTATION', {})
    regime = macro.get('regime', 'default')
    regime_rotation = rotation.get(regime, {})
    if regime_rotation:
        w.write(doc_id, [('h3', '{} 阶段轮动建议'.format(regime))])
        for k, v in regime_rotation.items():
            w.write(doc_id, [('bullet', '{}: {}'.format(k, v))])

    # ═══ 第五部分: 债券/商品/外汇全景 ═══
    w.write(doc_id, [('h2', '五、🏦 债券·商品·外汇全景')])

    # TODO: 债券
    try:
        bonds = scan_bonds()
        w.write(doc_id, [('h3', '债券市场')])
        w.write(doc_id, [
            ('bullet', '曲线形态: {}'.format(bonds.get('curve_shape', '?'))),
            ('bullet', '中美利差: {}'.format(bonds.get('cn_us_spread', '?'))),
        ])
    except Exception as e:
        w.write(doc_id, [
            ('bullet', '⚠️ 债券数据暂不可用: {}'.format(str(e)[:40]))
        ])

    # TODO: 商品
    try:
        commodities = scan_commodities(macro)
        w.write(doc_id, [('h3', '商品市场')])
        comm_list = commodities.get('commodities', [])[:6]
        for c in comm_list:
            line = '{}: ${} | 20日: {} | 信号: {}'.format(
                c.get('name', '?'), c.get('price', '?'),
                c.get('ret_20d', '?'), c.get('signal', '➖'))
            w.write(doc_id, [('bullet', line)])
        # 国运线视角
        guoyun_view = commodities.get('lds_guoyun_view', '')
        if guoyun_view:
            w.write(doc_id, [('quote', guoyun_view)])
    except Exception as e:
        w.write(doc_id, [
            ('bullet', '⚠️ 商品数据暂不可用: {}'.format(str(e)[:40]))
        ])

    # TODO: 外汇
    try:
        fx = scan_fx(macro)
        w.write(doc_id, [('h3', '外汇市场')])
        fx_list = fx.get('fx_rates', fx.get('currencies', []))[:6]
        if isinstance(fx_list, list):
            for item in fx_list:
                if isinstance(item, dict):
                    pair = item.get('pair', item.get('name', '?'))
                    rate = item.get('rate', item.get('price', '?'))
                    change = item.get('change', '?')
                    line = '{}: {} | 变动: {}'.format(pair, rate, change)
                    w.write(doc_id, [('bullet', line)])
                else:
                    w.write(doc_id, [('bullet', str(item))])
    except Exception as e:
        w.write(doc_id, [
            ('bullet', '⚠️ 外汇数据暂不可用: {}'.format(str(e)[:40]))
        ])

    # ═══ 脚注 ═══
    w.write(doc_id, [
        ('divider', ''),
        ('text', '📅 下次更新: 下周一 | 数据截止: {}'.format(
            time.strftime("%Y/%m/%d %H:%M"))),
        ('text', '📋 引用体系 → [知识总纲] | [每日日报] | [重点票深研] | [挖掘票库]'),
    ])


if __name__ == '__main__':
    """独立运行：生成宏观详解文档"""
    print("=== 宏观趋势详解生成 ===")
    try:
        me = rpt.MacroEngine()
        macro = me.refresh()
        w = rpt.FeishuWriter()
        doc_id = w.create_doc('📚 宏观趋势详解 — {}'.format(
            time.strftime('%Y/%m/%d')))
        print('文档 ID: {}'.format(doc_id))
        build_macro_detail(w, doc_id, macro)
        print('✅ 生成完成: https://bytedance.feishu.cn/docx/{}'.format(doc_id))
    except Exception as e:
        print('❌ 生成失败: {}'.format(e))
        import traceback
        traceback.print_exc()
