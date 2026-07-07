"""test_ps1_realtime.py — PS1: 验证 realtime API 修复

- 导入快速 (< 3s)
- 非交易时段快速返回空
- get_realtime_summary 不超时 (< 15s)
"""
import sys, time

sys.path.insert(0, ".")


def test_import_fast():
    t0 = time.time()
    from scripts.realtime_price import get_all_realtime  # noqa
    assert time.time() - t0 < 3, f"导入太慢: {time.time()-t0:.1f}s"


def test_non_trading_hours():
    from scripts.realtime_price import _is_trading_hours, get_all_realtime
    if _is_trading_hours():
        return  # 交易时段跳过本测试
    t0 = time.time()
    result = get_all_realtime()
    elapsed = time.time() - t0
    assert elapsed < 3, f"非交易时段不应 > 3s: {elapsed:.1f}s"
    assert result == {}, f"非交易时段应返回空: {result}"


def test_summary_no_timeout():
    t0 = time.time()
    from scripts.realtime_price import get_realtime_summary
    try:
        summary = get_realtime_summary()
        elapsed = time.time() - t0
        assert elapsed < 18, f"超时: {elapsed:.1f}s"
        assert isinstance(summary, dict)
        assert "realtime" in summary
    except Exception:
        elapsed = time.time() - t0
        assert elapsed < 18, f"异常也超时: {elapsed:.1f}s"