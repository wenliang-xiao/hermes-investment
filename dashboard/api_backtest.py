"""回测 API — 三方策略对比、自定义回测"""

import json
from datetime import datetime as _dt
from fastapi import APIRouter
from dashboard.shared import ROOT, _clean_signals

router = APIRouter()


def _backtest_result_to_frontend(br, strategy_label: str = "") -> dict:
    """将 BacktestResult 转为前端期望的格式"""
    return {
        "name": strategy_label or br.strategy_name,
        "value": round(br.final_value, 2),
        "cash": round(br.initial_cash - (br.final_value - br.initial_cash * br.total_return_pct / 100), 2)
        if br.trade_count > 0 else br.initial_cash,
        "positions": 0,
        "total_return_pct": br.total_return_pct,
        "realized_pnl": round(br.final_value - br.initial_cash, 2),
        "unrealized_pnl": 0,
        "total_trades": br.trade_count,
        "win_rate": br.win_rate_pct,
        "max_drawdown_pct": br.max_drawdown_pct,
        "sharpe_ratio": br.sharpe_ratio,
        "sortino_ratio": br.sortino_ratio,
        "calmar_ratio": br.calmar_ratio,
        "daily_values": br.equity_curve,
        "trades": br.trades,
    }


def _persist_backtest_result(br, strategy: str, symbols) -> None:
    """把 BacktestResult 落盘到 data/backtest/，供历史列表读取。失败静默（不影响回测返回）。"""
    try:
        from engine.backtest_storage import save_result

        result = {
            "meta": {
                "run_id": f"{strategy}_{_dt.now().strftime('%Y%m%d_%H%M%S')}",
                "strategy": strategy,
                "date_range": {"start": br.start_date, "end": br.end_date},
                "symbols": symbols or [],
            },
            "aggregate": {
                "avg_sortino": br.sortino_ratio,
                "avg_return_pct": br.total_return_pct,
                "total_trades": br.trade_count,
            },
        }
        save_result(strategy, result)
    except Exception:  # noqa: BLE001 - 落盘失败不影响回测返回
        pass


def _run_single_backtest(strategy: str, start_date: str, end_date: str,
                          symbols: list[str], capital: float, days: int) -> dict:
    """运行单个策略回测，返回前端格式的 dict"""
    from engine.evaluator_fixed import evaluate_strategy
    from engine.backtest_types import BacktestResult

    sym_list = symbols if symbols else None
    result = evaluate_strategy(strategy_name=strategy, custom_symbols=sym_list)
    if isinstance(result, dict) and "error" in result:
        return {"error": result["error"], "name": strategy, "daily_values": [], "trades": []}
    if isinstance(result, BacktestResult):
        _persist_backtest_result(result, strategy, sym_list)
        label_map = {
            "faceji": "faceji (面基)",
            "silverquant": "silverquant (组件化)",
            "tradingagents": "tradingagents (辩论制)",
        }
        return _backtest_result_to_frontend(result, label_map.get(strategy, strategy))
    return {"name": strategy, "daily_values": [], "trades": [], "error": "未知结果格式"}


@router.get("/api/comparison")
def get_comparison(days: int = 60):
    """三方策略对比数据 — 支持自定义天数"""
    try:
        from engine.strategy_comparison import run_comparison
        result = run_comparison(days=min(max(days, 7), 365))
        sig_path = ROOT / "data" / "trading_signals.json"
        if sig_path.exists():
            with open(sig_path) as f:
                live = json.load(f)
            live["signals"], _dropped = _clean_signals(live.get("signals", []), "comparison")
            result["live_signals"] = live
        return result
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/v2/backtest")
def api_v2_backtest():
    """回测历史列表"""
    from engine.backtest_storage import list_results
    results = list_results()
    return {"count": len(results), "results": results}


@router.get("/api/v2/backtest/strategies")
def api_v2_backtest_strategies():
    """可用的回测策略列表"""
    return {
        "strategies": [
            {"key": "faceji", "label": "面基策略", "desc": "评分驱动+MA趋势+Kelly仓位+4层风控"},
            {"key": "silverquant", "label": "SilverQuant", "desc": "固定¥30K槽位+不为清单+4层风控"},
            {"key": "tradingagents", "label": "TradingAgents", "desc": "辩论制评分+Kelly仓位+3层风控"},
            {"key": "all", "label": "三策略对比", "desc": "同时运行三个策略对比"},
        ],
        "defaults": {
            "capital": 1000000,
            "days_range": [7, 30, 60, 90, 180, 365],
        }
    }


@router.get("/api/v2/backtest/custom")
def api_v2_backtest_custom(
    strategy: str = "faceji",
    start_date: str = "",
    end_date: str = "",
    symbols: str = "",
    capital: float = 1000000,
    days: int = 60,
):
    """自定义回测 — 指定策略/时间范围/股票池

    当提供了自定义参数（策略/日期/标的）时，使用 evaluator_fixed 引擎进行
    真实数据回测；无自定义参数时回退到 scan_snapshot 对比引擎。

    参数:
        strategy: faceji / silverquant / tradingagents / all
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        symbols: 逗号分隔的标的代码（空=默认 FIXED_UNIVERSE）
        capital: 初始资金
        days: 回测天数（无日期时使用）
    """
    has_custom_params = bool(start_date) or bool(end_date) or bool(symbols)

    try:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else []

        if has_custom_params or strategy != "all":
            # ─── 使用 evaluator_fixed 引擎进行真实数据回测 ───
            strategies_to_run = (
                ["faceji", "silverquant", "tradingagents"]
                if strategy == "all"
                else [strategy]
            )

            result = {}
            for s_name in strategies_to_run:
                output = _run_single_backtest(s_name, start_date, end_date,
                                               sym_list, capital, days)
                result[s_name] = output

            result["run_date"] = _dt.now().strftime("%Y-%m-%d %H:%M")
            days_analyzed = 0
            for s_name in strategies_to_run:
                cv = result.get(s_name, {})
                dv = cv.get("daily_values", [])
                if dv:
                    days_analyzed = max(days_analyzed, len(dv))
            result["days_analyzed"] = days_analyzed
            result["params"] = {
                "strategy": strategy,
                "start_date": start_date,
                "end_date": end_date,
                "symbols": symbols,
                "capital": capital,
                "days": days,
            }
            return result

        # ─── 默认参数：使用 scan_snapshot 对比引擎 ───
        from engine.strategy_comparison import run_comparison
        result = run_comparison(days=min(max(days, 7), 365))
        result["params"] = {
            "strategy": strategy,
            "start_date": start_date,
            "end_date": end_date,
            "symbols": symbols,
            "capital": capital,
            "days": days,
        }
        return result

    except Exception as e:
        return {"error": str(e)}


@router.get("/api/v2/backtest/{run_id}")
def api_v2_backtest_detail(run_id: str):
    """回测详情"""
    from engine.backtest_storage import load_result
    result = load_result(run_id)
    if result is None:
        return {"error": f"run_id '{run_id}' not found"}
    return result
