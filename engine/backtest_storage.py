"""
标准化回测存储模块 — 管理 data/backtest/ 目录下的回测结果。

Schema 参见 tests/test_backtest_storage.py 中定义的 SAMPLE。

用法:
    from engine.backtest_storage import save_result, list_results, load_result
    save_result("faceji", {"meta": {...}, "cycles": [...], ...})
"""
import os, json, glob, uuid
from datetime import datetime, date
from utils.atomic_io import atomic_write_json

BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "backtest")

SCHEMA_VERSION = 2


def _ensure_dir():
    os.makedirs(BACKTEST_DIR, exist_ok=True)


def _get(obj, key, default=None):
    """BacktestResult / dict 统一取字段"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _default_cost_model() -> dict:
    """回测成本模型参数 (与 evaluator_fixed 常量同源, 避免文档口径漂移)。"""
    try:
        from engine import evaluator_fixed as ef
        return {
            "initial_cash": ef.INITIAL_CASH,
            "commission_rate": ef.COMMISSION_RATE,
            "stamp_tax_rate": ef.STAMP_TAX_RATE,
            "slippage": ef.SLIPPAGE,
            "min_commission": ef.MIN_COMMISSION,
            "model": "evaluator_fixed: T+1 开盘成交 + 滑点/佣金(最低5元)/卖出印花税",
        }
    except Exception:  # noqa: BLE001 - 仅元信息, 取不到不影响落盘
        return {}


def build_result(strategy: str, br, *, from_date: str = "", to_date: str = "",
                 walk_forward: bool = False, cycles: int = 0,
                 include_delisted: bool = False, symbols=None,
                 source: str = "cli", cost_model: dict | None = None) -> dict:
    """把 BacktestResult / 旧 dict 结果转成统一落盘 schema。

    ⚠️ 2026-11-06: CLI 与面板原来各写一套 schema —— CLI 用 `date_range:{from,to}`
    + actual_date_range + cost_model, 面板用 `date_range:{start,end}` 且**丢掉**
    equity_curve/trades → 历史报告只有 4 个聚合数, 无法复核。现统一走本函数:
      - 单次回测也落 equity_curve / trades / benchmark
      - date_range 固定 {from,to}, 另有 actual_date_range / data_window_days
      - WF 的净值/交易从 cycle_details 汇总
    """
    extra = _get(br, "extra", {}) or {}
    if not isinstance(extra, dict):
        extra = {}
    dw = extra.get("data_window", {}) or {}
    cycle_details = extra.get("cycle_details", []) or []

    actual_from = _get(br, "start_date") or dw.get("actual_start")
    actual_to = _get(br, "end_date") or dw.get("actual_end")

    equity = list(_get(br, "equity_curve", []) or [])
    trades = list(_get(br, "trades", []) or [])
    if walk_forward and cycle_details:
        # WF 的 BacktestResult 顶层 equity/trades 为空 → 从 cycle 明细拉平
        trades = [t for c in cycle_details for t in (c.get("trades") or [])] or trades

    run_id = f"{strategy}_{date.today().strftime('%Y%m%d')}_{uuid.uuid4().hex[:4]}"
    use_pit = bool(dw.get("use_point_in_time", extra.get("use_point_in_time", False)))
    scoring_mode = "point_in_time" if use_pit else "fixed_score"

    if walk_forward:
        aggregate = {
            "avg_sortino": extra.get("avg_sortino"),
            "avg_return_pct": extra.get("avg_return_pct"),
            "avg_max_dd_pct": extra.get("avg_max_drawdown_pct"),
            "total_trades": extra.get("total_trades", len(trades)),
            "total_symbols_traded": extra.get("stocks_with_data", 0),
            "win_rate_pct": extra.get("win_rate_pct"),
        }
    else:
        aggregate = {
            "avg_sortino": _get(br, "sortino_ratio"),
            "avg_return_pct": _get(br, "total_return_pct"),
            "avg_max_dd_pct": _get(br, "max_drawdown_pct"),
            "total_trades": _get(br, "trade_count", len(trades)),
            "total_symbols_traded": extra.get("stocks_with_data", 0),
            "win_rate_pct": _get(br, "win_rate_pct"),
        }

    return {
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "run_id": run_id,
            "strategy": strategy,
            "symbols": symbols or [],
            "date_range": {"from": from_date or actual_from or "",
                           "to": to_date or actual_to or ""},
            "actual_date_range": {"from": actual_from, "to": actual_to},
            "data_window_days": dw.get("data_window_days", 0),
            "engine": "evaluator_fixed",
            "scoring_mode": scoring_mode,
            "use_point_in_time": use_pit,
            "include_delisted": include_delisted,
            "survivorship_bias": dw.get("survivorship_bias"),
            "walk_forward_cycles": cycles if walk_forward else 0,
            "source": source,
            "generated_at": datetime.now().isoformat(),
        },
        "metrics": {
            "initial_cash": _get(br, "initial_cash"),
            "final_value": _get(br, "final_value"),
            "total_return_pct": _get(br, "total_return_pct"),
            "annualized_return_pct": _get(br, "annualized_return_pct"),
            "sharpe_ratio": _get(br, "sharpe_ratio"),
            "sortino_ratio": _get(br, "sortino_ratio"),
            "max_drawdown_pct": _get(br, "max_drawdown_pct"),
            "calmar_ratio": _get(br, "calmar_ratio"),
            "win_rate_pct": _get(br, "win_rate_pct"),
            "trade_count": _get(br, "trade_count", len(trades)),
        },
        "aggregate": aggregate,
        "cycles": cycle_details if walk_forward else [],
        "equity_curve": equity,
        "trades": trades,
        "benchmark": _get(br, "benchmark", None) or [],
        "cost_model": cost_model if cost_model is not None else _default_cost_model(),
    }


def save_result(strategy: str, result: dict) -> str:
    """保存一次回测结果到 data/backtest/，返回文件路径"""
    _ensure_dir()
    meta = result.get("meta", {})
    run_id = meta.get("run_id", f"{strategy}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    # 确保 run_id 写回 meta，供 list_results 返回
    meta["run_id"] = run_id
    filename = f"bt_{run_id}.json"
    path = os.path.join(BACKTEST_DIR, filename)
    meta.setdefault("generated_at", datetime.now().isoformat())
    result["meta"] = meta
    atomic_write_json(path, result)
    # ADR-0007: 旁挂 meta.json，报告引用数字时可直接对照口径与数据窗口，
    # 不必解析完整回测结果（equity_curve 可能很大）。
    meta_path = os.path.join(BACKTEST_DIR, f"bt_{run_id}.meta.json")
    atomic_write_json(meta_path, {
        **meta,
        "cost_model": result.get("cost_model", {}),
    })
    return path


def list_results(strategy=None):
    """列出所有回测结果摘要"""
    _ensure_dir()
    pattern = os.path.join(BACKTEST_DIR, "bt_*.json")
    files = sorted((f for f in glob.glob(pattern) if not f.endswith(".meta.json")),
                   reverse=True)
    summaries = []
    for fp in files:
        try:
            with open(fp) as f:
                data = json.load(f)
            meta = data.get("meta", {})
            agg = data.get("aggregate", {})
            if strategy and meta.get("strategy") != strategy:
                continue
            dr = meta.get("date_range", {}) or {}
            # 兼容旧面板 schema (start/end) 与 CLI schema (from/to)
            dr = {"from": dr.get("from") or dr.get("start"),
                  "to": dr.get("to") or dr.get("end")}
            summaries.append({
                "path": fp,
                "strategy": meta.get("strategy"),
                "run_id": meta.get("run_id"),
                "date_range": dr,
                "actual_date_range": meta.get("actual_date_range"),
                "schema_version": meta.get("schema_version", 1),
                "generated_at": meta.get("generated_at"),
                "avg_sortino": agg.get("avg_sortino"),
                "avg_return_pct": agg.get("avg_return_pct"),
                "total_trades": agg.get("total_trades"),
                "symbols": meta.get("symbols", []),
                "has_equity_curve": bool(data.get("equity_curve")),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return summaries


def load_result(run_id):
    """按 run_id 加载回测结果"""
    _ensure_dir()
    path = os.path.join(BACKTEST_DIR, f"bt_{run_id}.json")
    if not os.path.exists(path):
        # 尝试模糊匹配
        for fp in glob.glob(os.path.join(BACKTEST_DIR, f"bt_{run_id}*.json")):
            if fp.endswith(".meta.json"):
                continue
            path = fp
            break
        else:
            return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def delete_result(run_id: str) -> bool:
    """删除回测结果"""
    _ensure_dir()
    path = os.path.join(BACKTEST_DIR, f"bt_{run_id}.json")
    if os.path.exists(path):
        os.remove(path)
        return True
    return False
