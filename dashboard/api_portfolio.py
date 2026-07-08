"""模拟盘/持仓/信号 API"""

import json
from datetime import datetime
from fastapi import APIRouter
from dashboard.shared import (
    ROOT, get_name, load_shadow, build_summary, build_chart_data,
    build_history, _clean_signals, _aggregate_strategy_portfolios,
)

router = APIRouter()


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
        total_value = cash + invested
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

    result = {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "total_raw_signals": data.get("total_raw_signals", 0),
        "after_conflict_resolution": data.get("after_conflict_resolution", 0),
        "after_weekly_filter": data.get("after_weekly_filter", 0),
        "simulated_trades": data.get("simulated_trades", 0),
        "portfolios": data.get("portfolios", {}),
        "positions": data.get("positions", {}),
        "trade_history": data.get("trade_history", {}),
        "final_signals": data.get("signals", []),
        "all_signals": data.get("all_signals", []),
    }

    for strat_name, positions in result["positions"].items():
        for sym, pos in positions.items():
            pos["name"] = get_name(sym)

    return result


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
