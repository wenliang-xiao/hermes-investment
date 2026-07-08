"""
标准化回测存储模块 — 管理 data/backtest/ 目录下的回测结果。

Schema 参见 tests/test_backtest_storage.py 中定义的 SAMPLE。

用法:
    from analysis.backtest_storage import save_result, list_results, load_result
    save_result("faceji", {"meta": {...}, "cycles": [...], ...})
"""
import os, json, glob
from datetime import datetime
from utils.atomic_io import atomic_write_json

BACKTEST_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "data", "backtest")


def _ensure_dir():
    os.makedirs(BACKTEST_DIR, exist_ok=True)


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
    return path


def list_results(strategy=None):
    """列出所有回测结果摘要"""
    _ensure_dir()
    pattern = os.path.join(BACKTEST_DIR, "bt_*.json")
    files = sorted(glob.glob(pattern), reverse=True)
    summaries = []
    for fp in files:
        try:
            with open(fp) as f:
                data = json.load(f)
            meta = data.get("meta", {})
            agg = data.get("aggregate", {})
            if strategy and meta.get("strategy") != strategy:
                continue
            summaries.append({
                "path": fp,
                "strategy": meta.get("strategy"),
                "run_id": meta.get("run_id"),
                "date_range": meta.get("date_range", {}),
                "generated_at": meta.get("generated_at"),
                "avg_sortino": agg.get("avg_sortino"),
                "avg_return_pct": agg.get("avg_return_pct"),
                "total_trades": agg.get("total_trades"),
                "symbols": meta.get("symbols", []),
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
