"""回测 API — 三方策略对比、自定义回测"""

import json
from datetime import datetime as _dt, date as _date
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from dashboard.shared import ROOT, _clean_signals

router = APIRouter()


def _benchmark_window_days(daily_values: list, default_days: int = 60) -> int:
    """从策略净值曲线首末日期推算基准线应拉取的日历天数, 保证两线日期范围对齐.

    引擎跑 FIXED_DAYS=120 交易日(约5个多月), 若基准只用 UI 的 days(如60) 拉取,
    两线日期范围错位导致叠加失真。此函数用曲线实际跨度 + 20 天缓冲。
    无可解析日期时降级到 default_days(保底 30)。
    """
    dates = []
    for e in daily_values or []:
        ds = (e or {}).get("date", "")
        if not ds:
            continue
        try:
            dates.append(_date.fromisoformat(str(ds)[:10]))
        except (ValueError, TypeError):
            continue
    if len(dates) >= 2:
        span = (max(dates) - min(dates)).days + 20
        return max(span, 30)
    return max(default_days, 30)


def _normalize_benchmark(closes: list) -> list:
    """基准净值归一化到首日=1.0 (量化终端基准线的标准做法). 空输入返回[]."""
    if not closes:
        return []
    base = float(closes[0])
    if base == 0:
        return []
    return [round(float(c) / base, 4) for c in closes]


def _fetch_benchmark_curve(days: int = 60, code: str = "sh000300") -> dict | None:
    """拉取指数基准(默认沪深300)的净值曲线.

    优先 baostock(完整历史); 在 FastAPI 非主线程中 baostock 的 signal 登录会失败,
    故用子进程跑(子进程有自己的主线程, signal 正常)。若仍失败 fallback yfinance。
    数据不可用返回 None (无基准时报缺失而非假全零, 符合验收标准).
    """
    r = _fetch_benchmark_baostock_subproc(days, code)
    if r:
        return r
    return _fetch_benchmark_yf(days)


def _benchmark_worker(days: int, code: str, q):
    """子进程 worker — 在主线程拉 baostock 指数."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from data.data_layer import get_index_data
        df = get_index_data(code, days)
        if df is None or df.empty or "close" not in df.columns:
            q.put(None)
            return
        closes = [float(c) for c in df["close"].tolist()]
        dates = [str(d) for d in df["date"].tolist()]
        values = [round(c / closes[0], 4) for c in closes] if closes and closes[0] else []
        if not values:
            q.put(None)
            return
        pct = round((closes[-1] / closes[0] - 1) * 100, 2) if closes[0] else 0
        name = {"sh000300": "沪深300", "sh000001": "上证指数",
                "sz399001": "深证成指"}.get(code, code)
        q.put({"dates": dates, "values": values, "name": name, "pct_change": pct})
    except Exception:
        q.put(None)


def _fetch_benchmark_baostock_subproc(days: int = 60, code: str = "sh000300") -> dict | None:
    """用子进程跑 baostock(避开主线程 signal 限制), 返回归一化基准或 None."""
    try:
        import multiprocessing
        ctx = multiprocessing.get_context("spawn")
        q = ctx.Queue()
        p = ctx.Process(target=_benchmark_worker, args=(days, code, q))
        p.start()
        p.join(timeout=40)
        if p.is_alive():
            p.terminate()
            return None
        if q.empty():
            return None
        return q.get()
    except Exception:
        return None


def _fetch_benchmark_yf(days: int = 60) -> dict | None:
    """yfinance 沪深300基准源 — 线程安全, 作为 baostock 非主线程失败的兜底."""
    try:
        import yfinance as yf
        df = yf.Ticker("000300.SS").history(period="6mo")
        if df is None or df.empty:
            return None
        closes = [float(c) for c in df["Close"].tolist()]
        # yf 延迟/数据短, 截取最近 days
        closes = closes[-days:]
        dates = [d.strftime("%Y-%m-%d") for d in df.index][-days:]
        values = _normalize_benchmark(closes)
        if not values:
            return None
        pct = round((closes[-1] / closes[0] - 1) * 100, 2) if closes[0] else 0
        return {"dates": dates, "values": values, "name": "沪深300",
                "pct_change": pct}
    except Exception:
        return None


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
        "extra": getattr(br, "extra", {}) or {},
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
                          symbols: list[str], capital: float, days: int,
                          walk_forward: bool = False, cycles: int = 3,
                          train_days: int = 252, test_days: int = 63) -> dict:
    """运行单个策略回测，返回前端格式的 dict"""
    from engine.evaluator_fixed import evaluate_strategy
    from engine.backtest_types import BacktestResult

    sym_list = symbols if symbols else None
    result = evaluate_strategy(strategy_name=strategy, custom_symbols=sym_list,
                               walk_forward=walk_forward, cycles=cycles,
                               train_days=train_days, test_days=test_days)
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
    walk_forward: bool = False,
    cycles: int = 3,
    test_days: int = 63,
):
    """自定义回测 — 指定策略/时间范围/股票池

    当提供了自定义参数（策略/日期/标的）时，使用 evaluator_fixed 引擎进行
    真实数据回测；无自定义参数时回退到 scan_snapshot 对比引擎。
    walk_forward=True 启动样本外滚动评估(训练→测试窗口逐期前移)。

    参数:
        strategy: faceji / silverquant / tradingagents / all
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        symbols: 逗号分隔的标的代码（空=默认 FIXED_UNIVERSE）
        capital: 初始资金
        days: 回测天数（无日期时使用）
        walk_forward: 是否走 Walk-Forward 样本外评估
        cycles: WF 滚动次数
        test_days: WF 每个测试窗口天数
    """
    has_custom_params = bool(start_date) or bool(end_date) or bool(symbols)

    try:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else []

        # ─── 使用 evaluator_fixed 引擎进行真实数据回测（含 strategy=all 三策略对比）
        # 真实引擎有完整109天净值/回撤/夏普/交易明细(类似 xalpha/backtrader 专业框架),
        # 优于旧的 scan_snapshot 对比引擎(仅2天有效且7-20脏快照曾崩溃)。
        strategies_to_run = (
            ["faceji", "silverquant", "tradingagents"]
            if strategy == "all"
            else [strategy]
        )

        result = {}
        for s_name in strategies_to_run:
            output = _run_single_backtest(s_name, start_date, end_date,
                                          sym_list, capital, days,
                                          walk_forward=walk_forward,
                                          cycles=cycles, test_days=test_days)
            result[s_name] = output

        result["run_date"] = _dt.now().strftime("%Y-%m-%d %H:%M")
        days_analyzed = 0
        for s_name in strategies_to_run:
            cv = result.get(s_name, {})
            dv = cv.get("daily_values", [])
            if dv:
                days_analyzed = max(days_analyzed, len(dv))
        result["days_analyzed"] = days_analyzed
        # 基准线(沪深300)归一化净值 — 供前端叠加对比。
        # 窗口对齐到策略净值曲线的实际跨度, 避免基准只覆盖曲线末尾一段。
        bm_days = _benchmark_window_days(
            [e for s_name in strategies_to_run
             for e in result.get(s_name, {}).get("daily_values", [])],
            default_days=max(days, 30),
        )
        result["benchmark"] = _fetch_benchmark_curve(days=bm_days)
        result["params"] = {
            "strategy": strategy,
            "start_date": start_date,
            "end_date": end_date,
            "symbols": symbols,
            "capital": capital,
            "days": days,
            "walk_forward": walk_forward,
            "cycles": cycles,
        }
        return result

    except Exception as e:
        return {"error": str(e)}


# ──────────────────────────────────────────────
# WS4: v3 端点 — xalpha + quantstats 专业回测报告
# 路由均为多段路径(backtest/v3/...), 与 /backtest/{run_id} 单段不冲突。
# 注意: 用模块引用 engine.backtest_v3(而非 from-import 绑定), 便于测试 monkeypatch。
# ──────────────────────────────────────────────
def _v3_nav_to_list(series) -> list[dict]:
    """pd.Series(带日期索引) → [{date, value}] 可 JSON 序列化. 非序列直接返回空."""
    if series is None:
        return []
    try:
        idx = [str(d)[:10] for d in series.index]
        vals = [round(float(v), 4) for v in series.values]
        return [{"date": d, "value": v} for d, v in zip(idx, vals)]
    except Exception:
        return []


@router.get("/api/v2/backtest/v3/list")
def api_v2_backtest_v3_list():
    """v3 专业回测报告列表 (按生成时间倒序)."""
    from engine import backtest_v3

    reports = backtest_v3.list_reports()
    return {"count": len(reports), "reports": reports}


@router.get("/api/v2/backtest/v3/run")
def api_v2_backtest_v3_run(
    strategy: str = "faceji",
    days: int = 120,
    capital: float = 1000000,
    symbols: str = "",
    benchmark: bool = True,
    run_id: str = "",
):
    """运行 v3 专业回测 → quantstats 报告落盘, 返回指标 + 报告链接.

    参数:
        strategy: faceji / silverquant / tradingagents
        days: 回测交易日数(用于基准线拉取跨度)
        capital: 初始资金
        symbols: 逗号分隔标的(空=策略默认 FIXED_UNIVERSE)
        benchmark: 是否拉取沪深300基准
        run_id: 指定报告 ID(空=自动 strategy_时间戳)
    """
    from engine import backtest_v3

    try:
        sym_list = [s.strip() for s in symbols.split(",") if s.strip()] if symbols else None
        result = backtest_v3.run_backtest_v3(
            strategy=strategy,
            days=days,
            capital=capital,
            custom_symbols=sym_list,
            benchmark=benchmark,
            run_id=run_id or None,
        )
        if "error" in result:
            return {"error": result["error"], "strategy": strategy}
        rid = result["run_id"]
        out = {k: v for k, v in result.items() if k not in ("nav", "benchmark_nav")}
        out["report_url"] = f"/api/v2/backtest/v3/report/{rid}"
        out["nav"] = _v3_nav_to_list(result.get("nav"))
        out["benchmark_nav"] = _v3_nav_to_list(result.get("benchmark_nav"))
        return out
    except Exception as e:
        return {"error": str(e), "strategy": strategy}


@router.get("/api/v2/backtest/v3/{run_id}")
def api_v2_backtest_v3_detail(run_id: str):
    """单个 v3 报告 meta + 报告链接."""
    from engine import backtest_v3

    meta = backtest_v3.get_report(run_id)
    if meta is None:
        return {"error": f"run_id '{run_id}' not found"}
    meta["report_url"] = f"/api/v2/backtest/v3/report/{run_id}"
    return meta


@router.get("/api/v2/backtest/v3/report/{run_id}")
def api_v2_backtest_v3_report(run_id: str):
    """直接返回 quantstats HTML 报告全文 (可新窗口打开 / iframe 嵌入)."""
    from engine import backtest_v3

    out_dir = backtest_v3.REPORT_ROOT / run_id
    report_file = out_dir / "report.html"
    meta_file = out_dir / "meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            report_file = out_dir / meta.get("report_file", "report.html")
        except Exception:
            pass
    if not report_file.exists():
        return HTMLResponse(
            f"<html><body><h1>报告不存在</h1><p>run_id: {run_id}</p></body></html>",
            status_code=404,
        )
    return HTMLResponse(report_file.read_text(encoding="utf-8"))


@router.get("/api/v2/backtest/{run_id}")
def api_v2_backtest_detail(run_id: str):
    """回测详情"""
    from engine.backtest_storage import load_result
    result = load_result(run_id)
    if result is None:
        return {"error": f"run_id '{run_id}' not found"}
    return result
