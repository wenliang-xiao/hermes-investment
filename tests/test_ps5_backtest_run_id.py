"""test_ps5_backtest_run_id.py — PS5: 验证回测 run_id 修复"""
import sys, os, json, tempfile
sys.path.insert(0, ".")

from analysis.backtest_storage import save_result, list_results, load_result, delete_result, BACKTEST_DIR


def test_save_sets_run_id():
    """save_result 必须写回 run_id 到 meta"""
    result = {
        "meta": {"strategy": "test_ps5", "symbols": ["000001"], "date_range": {"start": "2026-01-01", "end": "2026-06-30"}},
        "aggregate": {"avg_sortino": 2.5, "avg_return_pct": 15.0, "total_trades": 10},
    }
    path = save_result("test_ps5", result)
    assert os.path.exists(path)
    with open(path) as f:
        data = json.load(f)
    assert data["meta"].get("run_id"), f"run_id missing: {data['meta']}"
    assert data["meta"]["run_id"].startswith("test_ps5_"), f"wrong run_id prefix: {data['meta']['run_id']}"
    # Clean up
    os.remove(path)


def test_list_returns_run_id():
    """list_results 返回的记录必须有非空 run_id"""
    results = list_results()
    for r in results:
        assert r.get("run_id"), f"run_id is None: {r}"


def test_load_by_run_id():
    """load_result(run_id) 必须能找到记录"""
    results = list_results()
    if not results:
        return  # no backtests to test with
    rid = results[-1]["run_id"]
    data = load_result(rid)
    assert data is not None, f"load_result({rid}) returned None"
    assert data["meta"].get("run_id") == rid


def test_load_nonexistent():
    """不存在的 run_id 返回 None"""
    data = load_result("nonexistent_run_id_123456")
    assert data is None