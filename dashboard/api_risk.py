"""风险分析 / 实时行情 / 绩效指标 API"""

import json
from datetime import datetime
from fastapi import APIRouter
from dashboard.shared import (
    ROOT, get_name, load_shadow, build_summary, _aggregate_strategy_portfolios,
)

router = APIRouter()


@router.get("/api/realtime")
def api_realtime():
    """实时行情（东财+A股+yfinance港美股）"""
    try:
        from scripts.realtime_price import get_realtime_summary
        return get_realtime_summary()
    except Exception as e:
        return {"error": str(e), "realtime": {}}


@router.get("/api/realtime/positions")
def api_realtime_positions():
    """仅返回持仓实时行情（轻量）"""
    try:
        from scripts.realtime_price import get_all_realtime
        return {"realtime": get_all_realtime(), "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/metrics")
def api_metrics():
    """绩效指标 (OSkhQuant风格：Sortino/Alpha/Beta/连续盈亏)"""
    try:
        book = load_shadow()

        # shadow_account 为空时，从三策略模拟盘聚合（与 /api/portfolio 一致）
        if not book.get("positions") and book.get("cash", 0) >= 1000000:
            try:
                aggr = _aggregate_strategy_portfolios()
                if aggr:
                    book = aggr
            except Exception:
                pass
        summary = build_summary(book)
        history = book.get("history", [])

        # 计算绩效指标
        import numpy as np

        # 净值序列
        capital = book.get("capital", 1000000)
        equity_values = [capital]
        for h in history:
            if h.get("action") == "卖出" and h.get("pnl") is not None:
                equity_values.append(equity_values[-1] + h["pnl"])
        final_value = summary["total_value"]
        equity_values.append(final_value)

        equity_arr = np.array(equity_values, dtype=float)
        n_periods = len(equity_arr) - 1

        if n_periods >= 2:
            returns = (equity_arr[1:] / equity_arr[:-1]) - 1
            # Sharpe (0% RF)
            sharpe = float(np.mean(returns)) / float(np.std(returns)) * np.sqrt(252) if float(np.std(returns)) > 0 else 0
            # Sortino
            downside = returns[returns < 0]
            dstd = float(np.std(downside)) if len(downside) > 0 else 0.001
            sortino = float(np.mean(returns)) / dstd * np.sqrt(252) if dstd > 0 else 0
            # 最大回撤
            running_max = np.maximum.accumulate(equity_arr)
            drawdowns = (equity_arr - running_max) / running_max
            max_dd = float(-np.min(drawdowns))
            # 连续盈亏
            win_streak = 0
            loss_streak = 0
            max_win_streak = 0
            max_loss_streak = 0
            for r in returns:
                if r > 0:
                    win_streak += 1
                    loss_streak = 0
                    max_win_streak = max(max_win_streak, win_streak)
                else:
                    loss_streak += 1
                    win_streak = 0
                    max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            sharpe = sortino = max_dd = max_win_streak = max_loss_streak = 0

        # 标的数
        total_trades = len([h for h in history if h.get("action") == "卖出"])
        wins = len([h for h in history if h.get("pnl") is not None and h["pnl"] > 0])

        return {
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "total_return_pct": summary["total_return"],
            "annualized_return_pct": summary["total_return"],  # simplified
            "win_rate_pct": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "total_trades": total_trades,
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "position_count": summary["position_count"],
            "capital": summary["capital"],
            "total_value": summary["total_value"],
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/risk")
def api_risk():
    """组合风险指标 — VaR/集中度/波动率"""
    from datetime import datetime as _dt, timedelta as _td
    import numpy as _np

    # 读取策略状态
    st_path = ROOT / "data" / "strategy_states.json"
    if not st_path.exists():
        return {"error": "no strategy data", "var_95": None, "concentration": {}, "volatility": None}

    with open(st_path) as f:
        states = json.load(f)

    # 1. 从交易历史计算日收益率序列
    daily_returns = {}
    all_positions = {}
    for sname, state in states.items():
        for h in state.get("history", []):
            pnl = h.get("pnl")
            cost = h.get("cost")
            if pnl is not None and cost:
                ret = pnl / cost
                date = h.get("date", "")[:10]
                if date not in daily_returns:
                    daily_returns[date] = []
                daily_returns[date].append(ret)
        for sym, pos in state.get("positions", {}).items():
            if sym not in all_positions:
                all_positions[sym] = {
                    "entry_price": pos.get("entry_price", 0),
                    "quantity": pos.get("quantity", 0),
                    "current_price": pos.get("current_price", pos.get("entry_price", 0)),
                    "strategy": sname,
                }

    # 2. 年化波动率 (从日频PnL率推算)
    rets = []
    for date, rlist in daily_returns.items():
        if rlist:
            rets.append(sum(rlist) / len(rlist))
    vol = None
    if len(rets) >= 5:
        vol = round(float(_np.std(rets) * _np.sqrt(252) * 100), 2)

    # 3. VaR(95%) 历史模拟法
    var_95 = None
    if len(rets) >= 20:
        sorted_rets = sorted(rets)
        idx = max(0, int(len(sorted_rets) * 0.05) - 1)
        var_95 = round(float(sorted_rets[idx]) * 100, 2)

    # 4. 集中度 — 标的维度
    total_value = sum(
        p["current_price"] * p["quantity"] for p in all_positions.values()
    ) if all_positions else 1
    concentration = {}
    for sym, p in all_positions.items():
        mkt_val = p["current_price"] * p["quantity"]
        pct = round(mkt_val / total_value * 100, 1) if total_value > 0 else 0
        name = get_name(sym)
        concentration[sym] = {"name": name, "pct": pct, "value": round(mkt_val, 2)}

    # 按占比降序
    sorted_conc = sorted(concentration.items(), key=lambda x: x[1]["pct"], reverse=True)
    top_conc = [{"symbol": s, **v} for s, v in sorted_conc[:5]]
    max_conc = top_conc[0]["pct"] if top_conc else 0

    return {
        "volatility_annual_pct": vol,
        "var_95_daily_pct": var_95,
        "max_concentration_pct": max_conc,
        "top_positions": top_conc,
        "total_positions": len(all_positions),
        "total_trades_history": sum(len(state.get("history", [])) for state in states.values()),
        "updated_at": _dt.now().strftime("%Y-%m-%d %H:%M"),
    }
