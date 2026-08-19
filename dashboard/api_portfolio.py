"""模拟盘/持仓/信号 API"""

import json
from datetime import datetime
from fastapi import APIRouter
from dashboard.shared import (
    ROOT, get_name, load_shadow, build_summary, build_chart_data,
    build_history, _clean_signals, _aggregate_strategy_portfolios,
)
from engine.execution_checker import ExecutionChecker
from engine.evidence_builder import EvidenceBuilder

router = APIRouter()

_checker = ExecutionChecker()
_builder = EvidenceBuilder()


def _load_scan_score_map() -> dict:
    """scan_snapshot_latest.json → {symbol: score_item} (含 7 维风格分, 供持仓因子雷达)"""
    path = ROOT / "data" / "scan_snapshot_latest.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return {r.get("symbol", ""): r for r in data.get("results", []) if r.get("symbol")}
    except (json.JSONDecodeError, KeyError):
        return {}


def _annotate_signals(all_signals, final_signals, trade_history, today_str):
    """给原始信号打状态: executed(今日已执行) / filtered(冲突或周频过滤) / pending"""
    def norm(a):
        a = str(a or "")
        if a.upper().startswith("BUY") or a.startswith("买"):
            return "BUY"
        if a.upper().startswith("SELL") or a.startswith("卖"):
            return "SELL"
        return a.upper()

    executed = set()
    for sname, txns in trade_history.items():
        for t in (txns or []):
            if str(t.get("date", ""))[:10] == today_str:
                executed.add((sname, t.get("symbol"), norm(t.get("action"))))
    final_keys = {(s.get("strategy"), s.get("symbol"), norm(s.get("action")))
                  for s in final_signals}
    for s in all_signals:
        k = (s.get("strategy"), s.get("symbol"), norm(s.get("action")))
        if k in executed:
            s["status"] = "executed"
        elif k not in final_keys:
            s["status"] = "filtered"
        else:
            s["status"] = "pending"
    return all_signals


@router.get("/api/portfolio")
def api_portfolio():
    book = load_shadow()

    # shadow_account 为空时，从三策略模拟盘聚合真实数据
    if not book.get("positions") and book.get("cash", 0) >= 1000000:
        try:
            aggr = _aggregate_strategy_portfolios()
            if aggr:
                book = aggr
        except Exception:
            pass

    summary = build_summary(book)
    chart = build_chart_data(book)
    history = build_history(book)
    return {
        "summary": summary,
        "chart": chart,
        "history": history[:100],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "history_count": len(book.get("history", [])),
    }


@router.get("/api/signals")
def api_signals():
    """今日实时信号（第三层防护：过滤 price≤0）"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if sig_path.exists():
        with open(sig_path) as f:
            data = json.load(f)
        data["signals"], _dropped = _clean_signals(data.get("signals", []), "api_signals")
        return data
    return {"error": "no signals yet today", "signals": []}


@router.get("/api/behavior")
def api_behavior():
    """行为诊断（四维度：处置效应/过度交易/追涨/锚定）"""
    path = ROOT / "data" / "behavior_diagnosis.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"error": "no behavior diagnosis data yet", "strategies": {}}


@router.get("/api/simulated")
def api_simulated():
    """三个策略模拟盘全方位数据"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if not sig_path.exists():
        return {"error": "no simulated data yet", "portfolios": {}}

    with open(sig_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    positions = data.get("positions", {})
    signals, _dropped = _clean_signals(data.get("signals", []), "api_simulated")

    # 各策略汇总
    result = {}
    strategy_labels = {
        "faceji": {"name": "面基", "color": "#58a6ff", "style": "面基(评分+趋势+Kelly+SQ风控)"},
        "silverquant": {"name": "SilverQuant", "color": "#3fb950", "style": "组件化(评分建仓+4层风控)"},
        "tradingagents": {"name": "TradingAgents", "color": "#bc8cff", "style": "辩论制(Kelly动态+技术融合)"},
    }

    for sname in ["faceji", "silverquant", "tradingagents"]:
        pf = portfolios.get(sname, {})
        pos = positions.get(sname, {})
        s_sigs = [s for s in signals if s["strategy"] == sname]
        label = strategy_labels.get(sname, {})

        cash = pf.get("cash", 1000000)
        invested = pf.get("total_invested", 0)
        # 总资产 = 现金 + 持仓市值 (优先用生成方算好的 total_value, 兜底用市值重算)
        total_value = pf.get("total_value")
        if total_value is None:
            total_value = cash + sum(
                (pd.get("current_price") or 0) * (pd.get("quantity") or 0)
                for pd in pos.values()
            )
        total_pnl = total_value - 1000000
        total_return = total_pnl / 1000000 * 100

        pos_list = []
        for sym, pd in pos.items():
            entry = pd.get("entry_price", 0)
            current = pd.get("current_price", entry)
            qty = pd.get("quantity", 0)
            cost = entry * qty
            mkt_val = current * qty
            pnl = mkt_val - cost
            pnl_pct = pd.get("pnl_pct", 0)
            pos_list.append({
                "symbol": sym, "name": get_name(sym),
                "entry_price": entry, "current_price": current,
                "quantity": qty, "cost": cost, "market_value": mkt_val,
                "pnl": round(pnl, 2), "pnl_pct": pnl_pct,
                "entry_date": pd.get("entry_date", ""),
                "reason": pd.get("reason", f"建仓评分{pd.get('entry_score','?')}分"),
                "stop_loss": round(entry * 0.92, 2),
                "peak_price": pd.get("peak_price", entry),
            })

        # 每个策略的信号也要做 price=0 过滤
        s_sigs = []
        for s in signals:
            if s.get("strategy", "") == sname:
                s_sigs.append(s)
        # 再过滤一遍标的位置中 price=0 的（持仓中已平的无效标的）
        pos_list = [p for p in pos_list if p.get("current_price", 0) > 0]

        result[sname] = {
            "label": label.get("name", sname),
            "color": label.get("color", "#fff"),
            "style": label.get("style", ""),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": sum(1 for p in pos_list if p.get("current_price", 0) > 0),
            "history_count": pf.get("history_count", 0),
            "positions": pos_list,
            "signals": s_sigs,
        }

    return {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "simulated_trades": data.get("simulated_trades", 0),
        "portfolios": result,
        "user_signals": signals,
    }


@router.get("/api/v2/portfolio/detail")
def api_v2_portfolio_detail():
    """模拟盘完整详情 — 持仓+交易历史+信号日志+因子分解"""
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"error": "no data", "date": "", "portfolios": {}, "trade_history": {}, "all_signals": []}

    with open(ts_path) as f:
        data = json.load(f)

    raw_portfolios = data.get("portfolios", {})
    raw_positions = data.get("positions", {})
    raw_signals = data.get("signals", [])
    trade_history = data.get("trade_history", {})
    scan_map = _load_scan_score_map()

    # ── 补充统计字段 (匹配 JS loadDashboardV2 的期望) ──
    strategy_labels = {
        "faceji": {"name": "面基", "color": "#58a6ff", "style": "面基(评分+趋势+Kelly+SQ风控)"},
        "silverquant": {"name": "SilverQuant", "color": "#3fb950", "style": "组件化(评分建仓+4层风控)"},
        "tradingagents": {"name": "TradingAgents", "color": "#bc8cff", "style": "辩论制(Kelly动态+技术融合)"},
    }
    CAPITAL = 1_000_000

    enriched_portfolios = {}
    for sname in ["faceji", "silverquant", "tradingagents"]:
        pf = raw_portfolios.get(sname, {})
        cash = pf.get("cash", CAPITAL)
        invested = pf.get("total_invested", 0)
        # 总资产 = 现金 + 持仓市值 (优先用生成方算好的 total_value, 兜底用市值重算)
        total_value = pf.get("total_value")
        if total_value is None:
            syms = raw_positions.get(sname, {})
            total_value = cash + sum(
                (p.get("current_price") or 0) * (p.get("quantity") or 0)
                for p in syms.values()
            )
        total_pnl = total_value - CAPITAL
        total_return = total_pnl / CAPITAL * 100 if CAPITAL else 0

        # 胜率: 只统计已平仓(卖出)且有盈亏记录的交易; 无平仓 → None(前端显示 —)
        txns = trade_history.get(sname, [])
        closed = [t for t in txns
                  if str(t.get("action", "")).startswith(("卖", "SELL", "sell"))
                  and t.get("pnl") is not None]
        wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
        win_rate = round(wins / len(closed) * 100, 1) if closed else None

        label = strategy_labels.get(sname, {})
        enriched_portfolios[sname] = {
            "label": label.get("name", sname),
            "color": label.get("color", "#fff"),
            "style": label.get("style", ""),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": pf.get("position_count", 0),
            "history_count": pf.get("history_count", 0),
            "win_rate": win_rate,
        }

    # ── 补充持仓字段 ──
    enriched_positions = {}
    for sname in ["faceji", "silverquant", "tradingagents"]:
        syms = raw_positions.get(sname, {})
        pf = raw_portfolios.get(sname, {})
        pf_cash = pf.get("cash", CAPITAL)
        pos_list = {}
        for sym, pos in syms.items():
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            qty = pos.get("quantity", 0)
            cost = entry * qty
            mkt_val = current * qty
            pnl = mkt_val - cost
            pnl_pct = round((current - entry) / entry * 100, 2) if entry else 0
            hold_days = 0
            if pos.get("entry_date"):
                try:
                    ed = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
                    hold_days = (datetime.now() - ed).days
                except ValueError:
                    pass

            # 仓位占比
            total_assets = pf_cash + sum(p.get("current_price", 0) * p.get("quantity", 0) for p in syms.values())
            pct = round(mkt_val / total_assets * 100, 2) if total_assets else 0

            pos_list[sym] = {
                "symbol": sym,
                "name": get_name(sym),
                "entry_price": entry,
                "current_price": current,
                "quantity": qty,
                "pnl": round(pnl, 2),
                "pnl_pct": pnl_pct,
                "hold_days": hold_days,
                "entry_date": pos.get("entry_date", ""),
                "reason": pos.get("reason", f"建仓评分{pos.get('entry_score', '?')}分") if pos.get("reason") else "无理由（需run_trading生成）",
                "stop_loss": round(entry * 0.92, 2),
                "pct": pct,
                "peak_price": pos.get("peak_price", entry),
                "drawdown_from_peak": pos.get("drawdown_from_peak", 0),
                "drawdown_from_entry": pos.get("drawdown_from_entry", 0),
                "entry_score": pos.get("entry_score"),
                "current_score": pos.get("current_score"),
                # 无持仓因子数据时, 从当日扫描快照富集 7 维风格分 (修复"无因子数据")
                "factor_scores": pos.get("factor_scores")
                                  or scan_map.get(sym, {}).get("scores"),
                "is_delisted": not current or current <= 0,
                "evidence": _build_position_evidence(sym, current, qty, entry, pnl, pos, sname),
            }
        enriched_positions[sname] = pos_list

    final_sigs = _clean_signals(raw_signals, "v2_detail")[0]
    all_sigs = data.get("all_signals", [])
    _annotate_signals(all_sigs, final_sigs, trade_history, data.get("date", ""))

    result = {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "total_raw_signals": data.get("total_raw_signals", 0),
        "after_conflict_resolution": data.get("after_conflict_resolution", 0),
        "after_weekly_filter": data.get("after_weekly_filter", 0),
        "simulated_trades": data.get("simulated_trades", 0),
        "portfolios": enriched_portfolios,
        "positions": enriched_positions,
        "trade_history": trade_history,
        "final_signals": final_sigs,
        "all_signals": all_sigs,
    }

    return result


def _build_position_evidence(sym, current, qty, entry, pnl, pos, strategy):
    """为持仓构建TrailStop证据包"""
    position_data = {"entry_price": entry, "current_price": current,
                     "quantity": qty, "pnl": pnl, "_peak_price": pos.get("peak_price", current)}
    check = _checker.check(sym, position=position_data)
    packet = _builder.build(sym, position=position_data)
    return {"trail_stop": check.get("trail_stop", {}), "evidence_packet": packet.to_dict()}


@router.get("/api/v2/portfolio/netvalue")
def api_v2_portfolio_netvalue():
    """净值曲线 — 从交易历史推算 + 沪深300基准"""
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"error": "no data", "labels": [], "series": []}

    with open(ts_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    trade_history = data.get("trade_history", {})

    series = []
    for strat_name, strat_data in portfolios.items():
        history = trade_history.get(strat_name, [])
        capital = strat_data.get("capital", 1000000)
        labels = []
        values = []
        current_value = capital
        for trade in history:
            trade_date = trade.get("date", "")
            if trade_date:
                labels.append(trade_date)
                pnl = trade.get("pnl", 0)
                if trade.get("action") == "卖出":
                    current_value += pnl
                values.append(round(current_value, 2))
        if labels:
            labels.append(datetime.now().strftime("%Y-%m-%d"))
            total_value = strat_data.get("total_value", capital)
            values.append(round(total_value, 2))

        series.append({
            "label": strat_data.get("label", strat_name),
            "name": strat_name,
            "labels": labels,
            "values": values,
            "total_return": strat_data.get("total_return", 0),
            "color": {"faceji": "#58a6ff", "silverquant": "#f0883e", "tradingagents": "#bc8cff"}.get(strat_name, "#7ee787"),
        })

    return {"labels": series[0]["labels"] if series else [], "series": series}


@router.get("/api/v2/reports")
def api_v2_reports():
    """日报链接列表"""
    path = ROOT / "data" / "daily_report_links.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []
