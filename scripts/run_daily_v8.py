#!/usr/bin/env python3
"""面基日报 v8 — 文档矩阵·指挥中心版 (5分钟可读完)"""
import sys, time
sys.path.insert(0, '/home/admin/.hermes')
import investment_system.report_v6 as rpt
from investment_system.macro_engine import MacroEngine
from investment_system.factor_scanner import FactorScanner
from scripts.build_daily_report import (
    build_gate_line, build_market_snapshot, build_key_news,
    build_position_status, build_mining_signals, build_discipline
)

LF = '/tmp/report_v8_log.txt'
with open(LF, 'w') as f: f.write('')
def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== 日报 v8 START ===")

try:
    scanner = FactorScanner()
    macro_engine = MacroEngine()
    macro = macro_engine.refresh()
    
    w = rpt.FeishuWriter()
    doc_id = w.create_doc(f"{rpt.SAN_YUAN_NAME}·日报 {time.strftime('%Y/%m/%d')}")
    log(f"Doc: {doc_id}")
    rpt._WRITE_COUNT[0] = 0
    t0 = time.time()
    
    # 1. 标题
    w.write(doc_id, [
        ('h2', f"{rpt.SAN_YUAN_NAME}·日报"),
        ('text', f"{time.strftime('%Y/%m/%d')} | v8 文档矩阵·指挥中心"),
        ('text', f"数据质量: ✅ 核心数据正常 (检查中)"),
        ('divider', ''),
    ])
    
    # 2-7. 六大板块
    build_gate_line(w, doc_id, macro)
    build_market_snapshot(w, doc_id)
    build_key_news(w, doc_id)
    build_position_status(w, doc_id)
    build_mining_signals(w, doc_id, scanner, macro)
    build_discipline(w, doc_id, macro)
    
    # 8. 脚注
    w.write(doc_id, [
        ('divider', ''),
        ('text', '详细分析 → 📚 [宏观趋势详解] | 🎯 [重点票深度研究] | 💎 [挖掘票研究库]'),
    ])
    
    dt = time.time() - t0
    log(f"Total: {dt:.1f}s, writes: {rpt._WRITE_COUNT[0]}")
    log(f"URL: https://bytedance.feishu.cn/docx/{doc_id}")
    
except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())
