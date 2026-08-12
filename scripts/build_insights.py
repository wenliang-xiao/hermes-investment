#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_insights.py —— 未成交信号观点库构建器(P0 修复)

把每日 data/trading_signals.json 里"已生成但未成交"的策略信号, 沉淀为可研究的观点资产。

判定流程 (与 engine/trading_engine.py 的 run_daily 管线对齐):
  all_signals(原始) --冲突消解--> resolved --周频过滤--> signals(最终建议)
  另, 每个策略的原始信号会进入"自动执行模拟盘", 但受周频(MAX_TRADES_PER_WEEK)
  与冷却期(TRADE_COOLDOWN_DAYS)限制, 可能只生成不执行。

对每个"生成但未成交"的信号记录:
  - date      : 信号日期 (trading_signals.json.date)
  - symbol    : 标的代码
  - name      : 股票名
  - action    : BUY/SELL
  - score     : 评分
  - reason_signal : 原始信号触发原因
  - not_executed_reason :
        周频过滤   = 在 resolved 之后被 _filter_by_weekly_rule 拦下
        冲突消解   = 同标的被 faceji/最高优先级信号挤出
        周频限制   = 进入最终建议但模拟盘 BUY 被每周次数上限拦截
        冷却期     = 标的进入交易冷却期未执行
  - strategy  : 信号来源策略

用法:
  python build_insights.py                # 全量重建(基于当前 trading_signals.json)
  python build_insights.py --since 2026-08-01   # 增量: 仅保留 >= since 的观点, 与历史合并
  python build_insights.py --summarize    # 打印本周未成交信号统计
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_PROJECT_DIR, "data")
SIGNALS_PATH = os.path.join(DATA_DIR, "trading_signals.json")
OUT_PATH = os.path.join(DATA_DIR, "insights.json")

# 与 engine/trading_engine.py 保持一致
MAX_TRADES_PER_WEEK_PER_STRATEGY = 3
MAX_TRADES_PER_WEEK_TOTAL = 5
TRADE_COOLDOWN_DAYS = 1
PRIORITY_W = {"HIGH": 0, "MED": 1, "LOW": 2}
STRAT_ORDER = {"faceji": 0, "silverquant": 1, "tradingagents": 2}

_NOT_EXEC_REASONS = ("周频过滤", "冲突消解", "周频限制", "冷却期")


# ---------------------------------------------------------------- 冲突消解重建
def _resolve_conflicts(all_signals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """复刻 _resolve_conflicts: 按标的分组, 冲突时面基优先, 否则取最高优先级。"""
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for sig in all_signals:
        by_symbol.setdefault(sig.get("symbol"), []).append(sig)

    resolved: List[Dict[str, Any]] = []
    for sym, sigs in by_symbol.items():
        buys = [s for s in sigs if s.get("action") == "BUY"]
        sells = [s for s in sigs if s.get("action") == "SELL"]

        if buys and sells:
            faceji = [s for s in sigs if s.get("strategy") == "faceji"]
            if faceji:
                resolved.extend(faceji)
            else:
                sigs = sorted(sigs, key=lambda s: (PRIORITY_W.get(s.get("priority"), 9)))
                resolved.append(sigs[0])
        elif buys:
            buys = sorted(buys, key=lambda s: (PRIORITY_W.get(s.get("priority"), 9), STRAT_ORDER.get(s.get("strategy"), 99)))
            resolved.append(buys[0])
        elif sells:
            sells = sorted(sells, key=lambda s: (PRIORITY_W.get(s.get("priority"), 9), STRAT_ORDER.get(s.get("strategy"), 99)))
            resolved.append(sells[0])
    return resolved


def _is_executed(sig: Dict[str, Any], positions: Dict, trade_history: Dict) -> bool:
    """判断某条原始信号是否实际成交(进入持仓 或 交易历史)。"""
    symbol = sig.get("symbol")
    strategy = sig.get("strategy")
    action = sig.get("action")

    # 1) 是否进入该策略持仓
    strat_pos = (positions or {}).get(strategy) or {}
    if symbol in strat_pos:
        return True

    # 2) 是否出现在该策略交易历史(含模拟盘实际成交)
    hist = (trade_history or {}).get(strategy) or []
    for t in hist:
        if t.get("symbol") == symbol:
            return True
    return False


def _infer_not_executed_reason(
    sig: Dict[str, Any],
    resolved_sigs: List[Dict[str, Any]],
    final_sigs: List[Dict[str, Any]],
    executed_syms: set,
) -> str:
    """推断未成交原因: 冲突消解(未进resolved), 周频过滤(进resolved未进final), 周频限制/冷却期(进final未成交)。"""
    sym = sig.get("symbol")
    strat = sig.get("strategy")

    # 已成交 → 不归类为未成交
    if (sym, strat) in executed_syms:
        return ""

    in_resolved = any(s.get("symbol") == sym and s.get("strategy") == strat for s in resolved_sigs)
    in_final = any(s.get("symbol") == sym and s.get("strategy") == strat for s in final_sigs)

    if not in_resolved:
        return "冲突消解"          # 同标的被 faceji / 更高优先级信号挤出
    if not in_final:
        return "周频过滤"          # 进过冲突消解, 但被 _filter_by_weekly_rule 拦下
    # 进入最终建议但未实际成交 → 模拟盘与真实交易纪律的周频/冷却限制
    if sig.get("action") == "BUY":
        return "周频限制"          # BUY 受每周次数与策略级上限拦截
    return "冷却期"                # 卖出/其他被冷却期或未知纪律拦截


# ---------------------------------------------------------------- 主构建
def build(since: Optional[str] = None) -> List[Dict[str, Any]]:
    if not os.path.exists(SIGNALS_PATH):
        raise FileNotFoundError(f"未找到 {SIGNALS_PATH}, 请先运行交易引擎生成每日信号")

    with open(SIGNALS_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    sig_date = data.get("date", "")
    all_signals: List[Dict[str, Any]] = data.get("all_signals") or []
    final_sigs: List[Dict[str, Any]] = data.get("signals") or []
    positions: Dict = data.get("positions") or {}
    trade_history: Dict = data.get("trade_history") or {}

    resolved_sigs: List[Dict[str, Any]] = _resolve_conflicts(all_signals)

    # 已成交的 (symbol,strategy) 集合
    executed = set()
    for strategy, strat_pos in (positions or {}).items():
        for sym in strat_pos:
            executed.add((sym, strategy))
    for strategy, hist in (trade_history or {}).items():
        for t in hist:
            executed.add((t.get("symbol"), t.get("strategy") or strategy))

    insights: List[Dict[str, Any]] = []
    for sig in all_signals:
        sym = sig.get("symbol")
        strat = sig.get("strategy")
        if (sym, strat) in executed:
            continue  # 已成交, 不属于"未成交信号"
        _reason = _infer_not_executed_reason(sig, resolved_sigs, final_sigs, executed)
        if not _reason:
            continue
        insights.append({
            "date": sig_date,
            "symbol": sym,
            "name": sig.get("name"),
            "action": sig.get("action"),
            "score": sig.get("score"),
            "reason_signal": sig.get("reason"),
            "not_executed_reason": _reason,
            "factor_decomposition": sig.get("factor_decomposition") or sig.get("factors"),
            "strategy": strat,
        })

    # --since 增量模式: 只保留信号日期 >= since 的观点
    if since:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError(f"--since 格式应为 YYYY-MM-DD, 收到 {since!r}")
        sig_dt = datetime.strptime(sig_date, "%Y-%m-%d").date() if sig_date else date.min
        if sig_dt < since_dt:
            insights = []

    # 与既有 insights.json 合并(历史观点保留, 当日重建替换避免重复)
    merged = _merge_existing(insights, sig_date, since)
    return merged


def _merge_existing(new_insights: List[Dict[str, Any]], sig_date: str, since: Optional[str]) -> List[Dict[str, Any]]:
    """合并历史 insights.json: 当日日期的观点以本次重建为准, 其余历史保留; --since 时丢弃更早的历史。"""
    existing = []
    if os.path.exists(OUT_PATH):
        try:
            with open(OUT_PATH, "r", encoding="utf-8") as f:
                existing = (json.load(f).get("insights") or [])
        except Exception:
            existing = []

    # 丢弃更早于 since 的历史(增量模式下不保留)
    keep = []
    for it in existing:
        if it.get("date"):
            keep.append(it)
    if since:
        try:
            since_dt = datetime.strptime(since, "%Y-%m-%d").date()
        except ValueError:
            since_dt = date.min
        keep = [it for it in keep if it.get("date") and datetime.strptime(it["date"], "%Y-%m-%d").date() >= since_dt]

    # 本次日期的观点取代旧版(去重: 去掉同日期同symbol同strategy的旧条目)
    keep = [it for it in keep if it.get("date") != sig_date]
    return keep + new_insights


def summarize(insights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """返回本周未成交信号统计: 哪些标的总被信号却没成交。"""
    if not insights:
        return {
            "week_key": "", "date_range": (),
            "total": 0, "total_unexecuted": 0,
            "by_symbol": [], "by_reason": {}, "by_strategy": {},
        }

    dates = [it.get("date") for it in insights if it.get("date")]
    latest = max(dates) if dates else ""
    try:
        dt = datetime.strptime(latest, "%Y-%m-%d").date()
        year, week_num, _ = dt.isocalendar()
        week_key = f"{year}-W{week_num:02d}"
        monday = dt - timedelta(days=dt.weekday())
        sunday = monday + timedelta(days=6)
    except Exception:
        week_key, monday, sunday = "", None, None

    week_insights = [
        it for it in insights
        if it.get("date") and monday
        and monday <= datetime.strptime(it["date"], "%Y-%m-%d").date() <= sunday
    ] if monday else insights

    by_symbol: Dict[str, Dict[str, Any]] = defaultdict(lambda: {"names": set(), "count": 0, "actions": Counter(), "reasons": Counter(), "max_score": 0.0})
    by_reason: Counter = Counter()
    by_strategy: Counter = Counter()

    for it in week_insights:
        sym = it.get("symbol")
        name = it.get("name") or sym
        by_symbol[sym]["names"].add(name)
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["actions"][it.get("action")] += 1
        by_symbol[sym]["reasons"][it.get("not_executed_reason")] += 1
        try:
            by_symbol[sym]["max_score"] = max(by_symbol[sym]["max_score"], float(it.get("score") or 0))
        except (TypeError, ValueError):
            pass
        by_reason[it.get("not_executed_reason")] += 1
        by_strategy[it.get("strategy")] += 1

    symbol_rows = []
    for sym, agg in sorted(by_symbol.items(), key=lambda kv: -kv[1]["count"]):
        symbol_rows.append({
            "symbol": sym,
            "name": next(iter(agg["names"])),
            "signal_count": agg["count"],
            "actions": dict(agg["actions"]),
            "reasons": dict(agg["reasons"]),
            "max_score": agg["max_score"],
        })

    return {
        "week_key": week_key,
        "date_range": (monday.isoformat(), sunday.isoformat()) if monday else (),
        "total_unexecuted": len(week_insights),
        "by_symbol": symbol_rows,
        "by_reason": dict(by_reason),
        "by_strategy": dict(by_strategy),
    }


def _print_summary(summ: Dict[str, Any]) -> None:
    sys.stderr.write(f"\n═══ 本周未成交信号统计 ({summ['week_key']}) ═══\n")
    sys.stderr.write(f"未成交观点数: {summ['total_unexecuted']}\n")
    if summ.get("by_reason"):
        sys.stderr.write(f"按原因: {dict(summ['by_reason'])}\n")
    if summ.get("by_strategy"):
        sys.stderr.write(f"按策略: {dict(summ['by_strategy'])}\n")
    sys.stderr.write("-- 总被信号却没成交的标的 --\n")
    if summ["by_symbol"]:
        for row in summ["by_symbol"]:
            sys.stderr.write(f"  {row['symbol']} {row['name']}: {row['signal_count']}次 "
                             f"actions={row['actions']} reasons={row['reasons']} max_score={row['max_score']}\n")
    else:
        sys.stderr.write("  (无)\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="未成交信号观点库构建器")
    parser.add_argument("--since", type=str, default=None, help="增量模式: 仅保留信号日期 >= YYYY-MM-DD 的观点")
    parser.add_argument("--summarize", action="store_true", help="仅打印本周未成交信号统计")
    parser.add_argument("--out", type=str, default=OUT_PATH, help="输出路径")
    args = parser.parse_args()

    insights = build(args.since)

    if args.summarize:
        _print_summary(summarize(insights))
        return 0

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "insights": insights},
                  f, ensure_ascii=False, indent=2)

    _print_summary(summarize(insights))
    sys.stderr.write(f"\n✅ 已写 {len(insights)} 条未成交观点 → {args.out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
