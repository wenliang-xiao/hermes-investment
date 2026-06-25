"""
analysis/audit.py — 六层漏斗审计工具

面基系统核心审计流程。逐层检查系统6个层次的完整性和覆盖率。

六层:
  1. 宏观气候   — 当前宏观状态 + 信号一致性
  2. 资产配置   — 股/债/商品/现金配比 vs 当前宏观
  3. 多因子引擎 — 因子评分分布 + 当前top因子
  4. 找票执行   — 当前信号质量 + 执行状态
  5. 风控监控   — 持仓风险指标 + 止损执行
  6. 交易纪律   — 交易频率/仓位/规则遵守

用法:
    from analysis.audit import run_audit, print_audit_report

    report = run_audit()
    print_audit_report(report)
"""
from __future__ import annotations

import json, math, os, sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# 确保模块可以找到（独立运行或被调用皆可）
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_json(filename: str) -> dict:
    path = DATA_DIR / filename
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


# ─── 第1层: 宏观气候 ───

def audit_macro() -> dict:
    """审计宏观气候层的完整性和一致性"""
    findings = []
    score = 0

    macro = load_json("macro_engine_cache.json")
    macro_raw = load_json("macro_raw_cache.json")
    scan = load_json("scan_snapshot_latest.json")

    # 宏观状态是否存在
    regime = macro.get("regime", "unknown") if isinstance(macro, dict) else "unknown"
    if regime != "unknown":
        score += 1
        findings.append({"item": "宏观状态", "status": "✅", "detail": f"当前: {regime}"})
    else:
        findings.append({"item": "宏观状态", "status": "❌", "detail": "无宏观数据"})

    # 是否有宏观引擎
    try:
        from analysis.macro_engine import get_macro_state
        state = get_macro_state()
        findings.append({"item": "宏观引擎", "status": "✅", "detail": f"macro_engine.py 可用"})
        score += 1
    except Exception:
        findings.append({"item": "宏观引擎", "status": "❌", "detail": "macro_engine.py 不可用"})

    # 多资产信号
    if isinstance(macro_raw, dict) and len(macro_raw) > 0:
        score += 1
        findings.append({"item": "宏观数据", "status": "✅", "detail": f"{len(macro_raw)} 个数据点"})
    else:
        findings.append({"item": "宏观数据", "status": "⚠️", "detail": "宏观原始数据为空"})

    return {
        "layer": 1, "name": "宏观气候",
        "score": score, "max_score": 3,
        "coverage_pct": round(score / 3 * 100, 1),
        "findings": findings,
    }


# ─── 第2层: 资产配置 ───

def audit_allocation() -> dict:
    """审计资产配置层的覆盖"""
    findings = []
    score = 0

    # ETF 策略是否存在
    try:
        from analysis.etf_backtest import run_etf_backtest
        from analysis.allocation_strategies import FixedMix, RiskParity
        findings.append({"item": "ETF配置模型", "status": "✅", "detail": "4种策略: Fixed/RiskParity/Grid/Trend"})
        score += 1
    except Exception as e:
        findings.append({"item": "ETF配置模型", "status": "❌", "detail": f"缺少: {e}"})

    # ETF标的池
    try:
        from data.etf_universe import ALL_ETF
        findings.append({"item": "ETF标的池", "status": "✅", "detail": f"{len(ALL_ETF)}只 (A股{sum(1 for e in ALL_ETF if e.region=='CN')}+美股{sum(1 for e in ALL_ETF if e.region=='US')})"})
        score += 1
    except Exception:
        findings.append({"item": "ETF标的池", "status": "⚠️", "detail": "etf_universe.py 不可用"})

    # 日报里是否有ETF建议
    report_path = DATA_DIR / "run_report_v10.py"
    if report_path.exists():
        with open(report_path) as f:
            content = f.read()
        if "ETF" in content or "etf" in content.lower():
            findings.append({"item": "ETF日报集成", "status": "⚠️", "detail": "报告中提到ETF但无独立ETF板块"})
        else:
            findings.append({"item": "ETF日报集成", "status": "❌", "detail": "日报无ETF配置建议段"})
    else:
        findings.append({"item": "ETF日报集成", "status": "❌", "detail": "日报脚本不可用"})

    return {
        "layer": 2, "name": "资产配置",
        "score": score, "max_score": 3,
        "coverage_pct": round(score / 3 * 100, 1),
        "findings": findings,
    }


# ─── 第3层: 多因子引擎 ───

def audit_factor_engine() -> dict:
    """审计多因子引擎层的状态"""
    findings = []
    score = 0

    # 是否有最新扫描快照
    scan = load_json("scan_snapshot_latest.json")
    results = scan.get("results", []) if isinstance(scan, dict) else []

    n_scored = len(results)
    if n_scored > 0:
        score += 1
        avg_score = sum(r.get("score", 0) for r in results) / n_scored
        findings.append({"item": "因子扫描", "status": "✅", "detail": f"最近扫描 {n_scored}只, 平均分{avg_score:.2f}"})
    else:
        findings.append({"item": "因子扫描", "status": "⚠️", "detail": "无最近扫描结果"})

    # 因子分布
    if results:
        high = sum(1 for r in results if r.get("score", 0) >= 6)
        med = sum(1 for r in results if 4 <= r.get("score", 0) < 6)
        low = sum(1 for r in results if r.get("score", 0) < 4)
        findings.append({"item": "因子分布", "status": "✅", "detail": f"高分{high} 中分{med} 低分{low}"})
        score += 1

    # 权重是否自适应
    try:
        from analysis.factor_scanner import LDSWeights
        w = LDSWeights()
        findings.append({"item": "因子权重", "status": "✅", "detail": f"LDS自适应权重可用"})
        score += 1
    except Exception:
        findings.append({"item": "因子权重", "status": "⚠️", "detail": "LDS权重不可用"})

    return {
        "layer": 3, "name": "多因子引擎",
        "score": score, "max_score": 3,
        "coverage_pct": round(score / 3 * 100, 1),
        "findings": findings,
    }


# ─── 第4层: 找票执行 ───

def audit_execution() -> dict:
    """审计信号执行层的状态"""
    findings = []
    score = 0

    signals = load_json("trading_signals.json")
    signals_list = signals.get("signals", []) if isinstance(signals, dict) else []

    if signals_list:
        score += 1
        n_buy = sum(1 for s in signals_list if s.get("action") == "BUY")
        n_sell = sum(1 for s in signals_list if s.get("action") == "SELL")
        high_priority = sum(1 for s in signals_list if s.get("priority") == "HIGH")
        findings.append({"item": "今日信号", "status": "✅", "detail": f"{len(signals_list)}信号(B{n_buy}/S{n_sell}), HIGH{high_priority}"})
    else:
        findings.append({"item": "今日信号", "status": "⚠️", "detail": "无信号或无信号文件"})

    # 三策略覆盖率
    portfolios = signals.get("portfolios", {}) if isinstance(signals, dict) else {}
    n_strategies = len(portfolios)
    if n_strategies >= 3:
        score += 1
        findings.append({"item": "策略覆盖", "status": "✅", "detail": f"3/3 策略全量运行 (faceji+SQ+TA)"})
    elif n_strategies > 0:
        findings.append({"item": "策略覆盖", "status": "⚠️", "detail": f"仅 {n_strategies}/3 策略运行"})
    else:
        findings.append({"item": "策略覆盖", "status": "❌", "detail": "无策略数据"})

    # 模拟盘状态
    shadow = load_json("shadow_account.json")
    if shadow and shadow.get("positions"):
        score += 1
        findings.append({"item": "模拟盘", "status": "✅", "detail": f"{len(shadow.get('positions', {}))}只持仓"})
    else:
        findings.append({"item": "模拟盘", "status": "⚠️", "detail": "空仓或模拟盘未运行"})

    return {
        "layer": 4, "name": "找票执行",
        "score": score, "max_score": 3,
        "coverage_pct": round(score / 3 * 100, 1),
        "findings": findings,
    }


# ─── 第5层: 风控监控 ───

def audit_risk() -> dict:
    """审计风控监控层的状态"""
    findings = []
    score = 0

    shadow = load_json("shadow_account.json")
    positions = shadow.get("positions", {}) if isinstance(shadow, dict) else {}

    if positions:
        # 检查止损
        at_stop = 0
        for sym, pos in positions.items():
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            if entry > 0 and current / entry - 1 <= -0.08:  # -8%止损
                at_stop += 1
        if at_stop > 0:
            findings.append({"item": "止损预警", "status": "🔴", "detail": f"{at_stop}只触发硬止损线!"})
        else:
            findings.append({"item": "止损状态", "status": "✅", "detail": f"{len(positions)}只均未触止损"})
        score += 1
    else:
        findings.append({"item": "持仓风险", "status": "✅", "detail": "空仓无风险"})

    # SQ风控层
    try:
        from analysis.trading_engine import SQRiskOverlay
        findings.append({"item": "SQ风控", "status": "✅", "detail": "SQ 4层风控(HS/FS/SDS/MA)可用"})
        score += 1
    except Exception:
        findings.append({"item": "SQ风控", "status": "⚠️", "detail": "SQRiskOverlay 不可用"})

    # 集中度检查
    if positions:
        total_value = shadow.get("cash", 0) + sum(
            p.get("current_price", p.get("entry_price", 0)) * p.get("quantity", 0)
            for p in positions.values()
        )
        max_pos_pct = 0
        for pos in positions.values():
            val = pos.get("current_price", pos.get("entry_price", 0)) * pos.get("quantity", 0)
            pct = val / total_value * 100 if total_value > 0 else 0
            max_pos_pct = max(max_pos_pct, pct)
        if max_pos_pct > 20:
            findings.append({"item": "集中度", "status": "⚠️", "detail": f"最大仓位占比{max_pos_pct:.0f}% > 20%"})
        else:
            findings.append({"item": "集中度", "status": "✅", "detail": f"最大仓位占比{max_pos_pct:.0f}%"})
        score += 1

    return {
        "layer": 5, "name": "风控监控",
        "score": score, "max_score": 3,
        "coverage_pct": round(score / 3 * 100, 1),
        "findings": findings,
    }


# ─── 第6层: 交易纪律 ───

def audit_discipline() -> dict:
    """审计交易纪律层的遵守情况"""
    findings = []
    score = 0

    shadow = load_json("shadow_account.json")
    history = shadow.get("history", []) if isinstance(shadow, dict) else []

    # 交易频率检查
    recent_trades = [h for h in history if h.get("action") in ("买入", "卖出")]
    if recent_trades:
        # 最近7天交易次数
        from datetime import timedelta
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        weekly_trades = sum(1 for h in recent_trades if h.get("time", "")[:10] >= week_ago)
        if weekly_trades > 6:
            findings.append({"item": "交易频率", "status": "⚠️", "detail": f"过去7天{weekly_trades}笔 > 6笔限制"})
        else:
            findings.append({"item": "交易频率", "status": "✅", "detail": f"过去7天{weekly_trades}笔, 在限制内"})
        score += 1
    else:
        findings.append({"item": "交易记录", "status": "⚠️", "detail": "无交易历史"})

    # 仓位纪律
    positions = shadow.get("positions", {}) if isinstance(shadow, dict) else {}
    if positions:
        n_pos = len(positions)
        if n_pos > 8:
            findings.append({"item": "持仓数量", "status": "⚠️", "detail": f"{n_pos}只 > 8只限制"})
        else:
            findings.append({"item": "持仓数量", "status": "✅", "detail": f"{n_pos}/{8}只"})
        score += 1
    else:
        findings.append({"item": "持仓数量", "status": "✅", "detail": "空仓"})

    # 不为清单检查
    try:
        from analysis.stop_list import StopListFilter
        findings.append({"item": "不为清单", "status": "✅", "detail": "StopListFilter 10条规则可用"})
        score += 1
    except Exception:
        findings.append({"item": "不为清单", "status": "❌", "detail": "未部署"})

    return {
        "layer": 6, "name": "交易纪律",
        "score": score, "max_score": 3,
        "coverage_pct": round(score / 3 * 100, 1),
        "findings": findings,
    }


# ─── 汇总 ───

def run_audit() -> dict:
    """运行完整六层审计"""
    layers = [
        audit_macro(),
        audit_allocation(),
        audit_factor_engine(),
        audit_execution(),
        audit_risk(),
        audit_discipline(),
    ]

    total_score = sum(l["score"] for l in layers)
    total_max = sum(l["max_score"] for l in layers)
    overall_pct = round(total_score / total_max * 100, 1)

    # 逐层评级
    def rating(pct: float) -> str:
        if pct >= 90: return "A"
        elif pct >= 70: return "B"
        elif pct >= 50: return "C"
        elif pct >= 30: return "D"
        return "F"

    gaps = []
    for l in layers:
        l["rating"] = rating(l["coverage_pct"])
        if l["coverage_pct"] < 70:
            gaps.append(f"{l['name']}({l['rating']})")
        for f in l["findings"]:
            if f["status"] == "❌":
                gaps.append(f"  {f['item']}: {f['detail']}")
            elif f["status"] == "🔴":
                gaps.append(f"  ⚠️ {f['item']}: {f['detail']}")

    return {
        "audit_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "overall_score": total_score,
        "overall_max": total_max,
        "overall_coverage_pct": overall_pct,
        "overall_rating": rating(overall_pct),
        "layers": layers,
        "gaps": gaps,
        "n_gaps": len([g for g in gaps if not g.startswith("  ⚠️")]),
    }


def print_audit_report(report: dict = None):
    """打印审计报告"""
    if report is None:
        report = run_audit()

    print(f"\n{'='*60}")
    print(f"📊 六层漏斗审计报告 · {report['audit_date']}")
    print(f"{'='*60}")
    print(f"总体覆盖率: {report['overall_coverage_pct']}% ({report['overall_score']}/{report['overall_max']})")
    print(f"总体评级:   {report['overall_rating']}")
    print(f"Gap数量:    {report['n_gaps']}")

    for l in report["layers"]:
        bar = "▓" * int(l["coverage_pct"] / 10) + "░" * (10 - int(l["coverage_pct"] / 10))
        print(f"\n{l['layer']}. {l['name']:12s} [{bar}] {l['coverage_pct']:.0f}% ({l['rating']})")
        for f in l["findings"]:
            print(f"    {f['status']} {f['item']:12s} {f['detail']}")

    if report["gaps"]:
        print(f"\n🔴 关键缺口:")
        for g in report["gaps"]:
            print(f"  {g}")

    print(f"\n{'='*60}")
    return report


if __name__ == "__main__":
    report = run_audit()
    print_audit_report(report)
