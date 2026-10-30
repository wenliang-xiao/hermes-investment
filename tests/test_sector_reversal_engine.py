"""板块反转层 (Sector Reversal Engine) — 纯函数单测

覆盖:
  1. 基础收益 / 回撤计算
  2. 反转日识别 (大跌 ≥3% 后 N 日收复 50% 失地 + 量能放大)
  3. 相对强度 (板块 vs 基准)
  4. 跨市场领先滞后 (费半 → A股半导体)
  5. 阶段分类 + 反转评分
  6. analyze_sector 输出契约 (字段齐全, 方法透明)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from engine.sector_reversal_engine import (
    pct_return,
    drawdown_from_high,
    detect_reversal,
    relative_strength,
    lead_lag,
    classify_stage,
    score_reversal,
    transmission_gap,
    analyze_sector,
)


# ─── 1. 基础计算 ───
def test_pct_return_1d():
    assert pct_return([100.0, 110.0], 1) == pytest.approx(10.0)


def test_pct_return_5d():
    close = [100, 101, 102, 103, 104, 110]
    assert pct_return(close, 5) == pytest.approx(10.0)


def test_pct_return_insufficient_data():
    assert pct_return([100.0], 5) is None


def test_drawdown_from_high():
    close = [100, 110, 120, 108]
    # 高点 120, 最新 108 → -10%
    assert drawdown_from_high(close, window=60) == pytest.approx(-10.0)


def test_drawdown_uses_window_only():
    # 高点 200 在窗口外, 窗口内高点 100 → 最新 90 是 -10% 而非 -55%
    close = [200, 100, 95, 90]
    assert drawdown_from_high(close, window=3) == pytest.approx(-10.0)


# ─── 2. 反转识别 ───
def _series_with_reversal():
    """第 1 天 -6.8%, 随后 4 天连涨, 收复全部失地, 量能放大 — 复刻 SOXX 10-22 形态"""
    close = [100.0, 93.2, 93.7, 96.4, 100.1, 102.2, 100.7]
    #             ↑跌-6.8%  ↑+0.5  ↑+2.9  ↑+3.8  ↑+2.1  ↑-1.5
    volume = [100, 100, 300, 300, 280, 260, 250]
    return close, volume


def test_detect_reversal_fires():
    close, volume = _series_with_reversal()
    r = detect_reversal(close, volume)
    assert r["fired"] is True
    assert r["drop_pct"] == pytest.approx(-6.8, abs=0.05)
    assert r["recover_ratio"] >= 0.5
    assert r["vol_ratio"] > 1.2
    assert r["days_since"] >= 1


def test_detect_reversal_no_recovery():
    """大跌后横盘 — 只修复了 20%, 不应触发"""
    close = [100.0, 93.0, 93.5, 94.0, 94.2, 94.3]
    volume = [100, 100, 120, 120, 110, 110]
    r = detect_reversal(close, volume)
    assert r["fired"] is False
    assert "未收复" in r["reason"] or "回撤" in r["reason"] or r["recover_ratio"] < 0.5


def test_detect_reversal_no_volume_expansion():
    """完美收复但量能没放大 — 不触发 (缩量反弹不可信)"""
    close = [100.0, 100.0, 100.0, 93.0, 96.0, 100.5]
    volume = [100, 100, 100, 100, 90, 85]
    r = detect_reversal(close, volume)
    assert r["fired"] is False
    assert r["recover_ratio"] >= 0.5


def test_detect_reversal_drop_day_capitulation():
    """跌日恐慌放量 + 反弹收复, 反弹期缩量也算有效 (复刻 SOXX 10-22 形态)"""
    close = [100.0, 100.0, 100.0, 93.2, 93.7, 96.4, 100.1]
    volume = [100, 100, 100, 195, 86, 93, 87]
    r = detect_reversal(close, volume)
    assert r["fired"] is True
    assert r["vol_ratio_drop"] > 1.8
    assert r["vol_ratio_rebound"] < 1.0


def test_detect_reversal_respects_lookback():
    """大跌发生在 10 天前, lookback=5 → 不触发"""
    close = [100.0, 93.0, 94.0, 95.0, 96.0, 97.0, 98.0, 99.0, 100.0, 101.0, 102.0]
    volume = [100] + [100] * 10
    r = detect_reversal(close, volume, lookback=5)
    assert r["fired"] is False


def test_detect_reversal_ignores_small_drop():
    """跌幅 -1.5% 不是大跌, 不触发"""
    close = [100.0, 98.5, 99.0, 100.5]
    volume = [100, 100, 300, 300]
    r = detect_reversal(close, volume)
    assert r["fired"] is False


# ─── 3. 相对强度 ───
def test_relative_strength():
    leader = [100, 100, 100, 100, 100, 108]   # 5日 +8%
    bench = [100, 100, 100, 100, 100, 93]     # 5日 -7%
    assert relative_strength(leader, bench, 5) == pytest.approx(15.0, abs=0.1)


def test_relative_strength_none_on_short():
    assert relative_strength([100.0], [100.0], 5) is None


# ─── 4. 跨市场领先滞后 ───
def test_lead_lag_detects_one_day_lag():
    """follower 是 leader 的 1 日滞后复制 → lag=1"""
    import random
    random.seed(7)
    leader_ret = [random.uniform(-3, 3) for _ in range(80)]
    leader = [100.0]
    for r in leader_ret:
        leader.append(leader[-1] * (1 + r / 100))
    follower_ret = [0.0] + leader_ret[:-1]          # 滞后一期
    follower = [100.0]
    for r in follower_ret:
        follower.append(follower[-1] * (1 + r / 100))
    res = lead_lag(leader, follower, max_lag=5)
    assert res["lag"] == 1
    assert res["corr"] > 0.8


def test_lead_lag_same_day():
    import random
    random.seed(11)
    ret = [random.uniform(-3, 3) for _ in range(80)]
    a = [100.0]
    for r in ret:
        a.append(a[-1] * (1 + r / 100))
    res = lead_lag(a, a, max_lag=5)
    assert res["lag"] == 0
    assert res["corr"] > 0.95


# ─── 5. 阶段分类 + 评分 ───
def test_classify_stage():
    assert classify_stage(rs5=5, dd60=-3, reversal_fired=False) == "领涨"
    assert classify_stage(rs5=6, dd60=-25, reversal_fired=True) == "反转启动"
    assert classify_stage(rs5=2, dd60=-25, reversal_fired=False) == "筑底抬升"
    assert classify_stage(rs5=-6, dd60=-25, reversal_fired=False) == "补跌"


def test_score_reversal_monotonic():
    hot = score_reversal(recover_ratio=1.0, rs5=10, vol_ratio=1.6, dd60=-40)
    warm = score_reversal(recover_ratio=0.5, rs5=3, vol_ratio=1.2, dd60=-25)
    cold = score_reversal(recover_ratio=0.0, rs5=-5, vol_ratio=1.0, dd60=-15)
    assert hot > warm > cold
    assert 0 <= cold <= warm <= hot <= 100


# ─── 6. 输出契约 ───
def test_transmission_gap():
    g = transmission_gap(leader_5d=8.02, follower_5d=-7.41)
    assert g["gap_pp"] == pytest.approx(15.43)
    assert g["leader_ahead"] is True


def test_analyze_sector_contract():
    close, volume = _series_with_reversal()
    bench = [100.0] * len(close)
    out = analyze_sector(
        key="半导体", name="半导体ETF", symbol="512480", market="A",
        close=close, volume=volume, bench_close=bench,
        dates=[f"2026-10-{d:02d}" for d in range(20, 20 + len(close))],
    )
    for field in ("key", "name", "symbol", "market", "stage", "score",
                  "ret_1d", "ret_5d", "ret_20d", "dd_60d", "rs_5d",
                  "reversal", "vol_ratio_5d", "method"):
        assert field in out, f"缺字段 {field}"
    assert out["key"] == "半导体"
    assert out["stage"] in ("领涨", "反转启动", "筑底抬升", "补跌", "高位滞涨", "数据不足")
    assert isinstance(out["reversal"], dict)
    assert out["method"]["reversal_rule"], "反转规则必须可审计"


def test_falling_stage_score_is_zero():
    """补跌板块没有反转证据, 评分必须为 0 (不能因为跌得深就拿高分)"""
    close = [100.0, 100.0, 100.0, 95.0, 93.0, 91.0, 89.0]
    volume = [100] * 7
    out = analyze_sector(
        key="X", name="X", symbol="000000", market="A",
        close=close, volume=volume, bench_close=[100.0] * 7,
    )
    assert out["stage"] == "补跌"
    assert out["score"] == 0.0


def test_format_report_blocks_surfaces_reversal():
    """日报 blocks 必须把反转启动板块与传导缺口顶到可见位置"""
    from engine.sector_reversal_engine import format_report_blocks
    payload = {
        "sectors": [
            {"key": "费城半导体", "stage": "反转启动", "score": 75.2, "ret_5d": 8.02,
             "dd_60d": -12.83, "reversal": {"reason": "5日前跌-6.79%后放量收复失地110%"}},
            {"key": "半导体", "stage": "补跌", "score": 0.0, "ret_5d": -6.31, "dd_60d": -33.13,
             "reversal": {"reason": "跌幅-5.02%后仅修复0%"}},
            {"key": "新能源", "stage": "筑底抬升", "score": 13.8, "ret_5d": 1.89,
             "dd_60d": -23.96, "reversal": {"reason": "最近5日无大跌"}},
        ],
        "summary": {"gap_top": {"leader": "SOXX", "follower": "512480",
                                "leader_5d": 8.02, "follower_5d": -6.31,
                                "gap_pp": 14.33, "lag": 5}},
    }
    blocks = format_report_blocks(payload)
    text = "\n".join(b[1] for b in blocks)
    assert "费城半导体" in text and "反转启动" in text
    assert "传导缺口" in text and "14.33pp" in text
    assert "筑底抬升" in text
    assert "补跌" in text
    assert blocks[0][0] == "bullet", "反转块必须排在首位"
