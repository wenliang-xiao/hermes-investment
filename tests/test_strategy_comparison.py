"""strategy_comparison 对比引擎 — 数据健壮性与崩溃修复回归测试."""
import sys, os, json, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from engine import strategy_comparison as sc


@pytest.fixture
def _fake_snapshots(tmp_path, monkeypatch):
    """构造临时快照目录: 1个正常(list results) + 1个dict形态(无results)的快照."""
    from datetime import datetime, timedelta
    today = datetime.now()
    good_date = (today - timedelta(days=10)).strftime("%Y-%m-%d")   # 10天前=正常
    bad_date = (today - timedelta(days=5)).strftime("%Y-%m-%d")      # 5天前=坏dict形态
    fake_root = tmp_path / "data"
    fake_root.mkdir()
    # 正常快照: results=list[dict]
    good = {"date": good_date, "results": [
        {"symbol": "600900", "score": 7.5, "price": 28.0, "tech": {"ma20": 1, "ma60": 1}},
    ]}
    # 坏快照: 无 results 字段, 顶层是 dict (这正是触发 .get() 崩溃的形态)
    bad = {"date": bad_date, "macro_state": "复苏期", "a_share_count": 138}
    (fake_root / f"scan_snapshot_{good_date}.json").write_text(json.dumps(good), encoding="utf-8")
    (fake_root / f"scan_snapshot_{bad_date}.json").write_text(json.dumps(bad), encoding="utf-8")

    # 用临时 data 目录替换 sc.ROOT
    sc.ROOT = str(tmp_path)
    monkeypatch.setattr(sc, "ROOT", str(tmp_path))
    yield
    sc.ROOT = os.path.dirname(os.path.dirname(os.path.abspath(sc.__file__)))


def test_load_score_history_dict_form_snapshot_skipped(_fake_snapshots):
    """dict形态(无results)的快照被跳过, 不进入列表(否则下游遍历dict key字符串崩溃)."""
    history = sc.load_score_history(days=20)  # 窗口覆盖7-09(20天前)和7-20(7天前)
    # 只应包含有 results 的合法快照
    assert all(isinstance(h["results"], list) for h in history)
    symbols = [r["symbol"] for h in history for r in h["results"]]
    assert "600900" in symbols, "正常快照的标的应被加载"
    # 坏快照(无results)的dict字段不应作为列表项出现
    for h in history:
        assert not isinstance(h, str)


def test_run_comparison_no_crash_with_bad_snapshot(_fake_snapshots):
    """run_comparison 遇到 dict 形态快照不抛异常, 返回可用结果."""
    try:
        result = sc.run_comparison(days=20)
        # 至少返回三策略字段
        assert "faceji" in result or "strategies" in result
    except AttributeError as e:
        pytest.fail(f"run_comparison 崩溃(AttributeError): {e}")
    except Exception as e:
        # 其他异常(如无足够数据走degraded)也应正常返回, 非崩溃
        pytest.fail(f"run_comparison 崩溃: {e}")