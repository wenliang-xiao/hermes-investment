"""
analysis/dsr_test.py — Deflated Sharpe Ratio 统计检验

DSR 校正多重假设检验（多个策略/参数组合下 Sharpe 的假阳性）。
参考: https://github.com/marcoslopezv/deflated-sharpe-ratio

原理:
    SR_observed = Sharpe observed
    E[max SR] = 期望最大 Sharpe (取决于 N 个独立尝试)
    V[max SR] = 期望最大 Sharpe 方差
    DSR = (SR_observed - E[max SR]) / sqrt(V[max SR])

当 DSR > 2.0 时，策略有统计显著的 alpha（非过拟合）。

用法:
    from engine.dsr_test import compute_dsr, dsr_verdict

    dsr, components = compute_dsr(sharpe_observed=2.5, n_trials=50, n_obs=252)
    print(dsr_verdict(dsr))
"""
from __future__ import annotations

import math
import numpy as np
from scipy import stats as sp_stats


def expected_max_sharpe(n_trials: int, n_obs: int) -> tuple[float, float]:
    """计算 N 次独立尝试下的期望最大 Sharpe 及其方差

    使用 Bailey & López de Prado (2014) 的简化近似。

    Args:
        n_trials: 独立尝试次数（策略×参数组合数）
        n_obs: 观测期数（回测天数）

    Returns:
        (E[max_SR], V[max_SR])
    """
    if n_trials <= 1:
        return 0.0, 1.0 / max(n_obs - 1, 1)

    n_eff = max(n_obs - 1, 1)

    # 标准误差
    se = 1.0 / math.sqrt(n_eff)

    # E[max Z] ≈ sqrt(2*ln(N)) （最大 N 个 i.i.d. 标准正态的期望）
    e_max_z = math.sqrt(2 * math.log(n_trials))

    # V[max Z] ≈ π²/(6*2*ln(N)) （最大值的渐近方差）
    # 更稳健: 用 1 做上限, 避免太小
    v_max_z = min(1.0, math.pi**2 / (12 * math.log(n_trials)))

    # 调整到 Sharpe 尺度
    e_max_sr = e_max_z * se
    v_max_sr = v_max_z * se**2

    return e_max_sr, v_max_sr


def compute_dsr(
    sharpe_observed: float,
    n_observations: int = 252,
    n_trials: int = 50,
    sharpe_theoretical: float = 0.0,
) -> tuple[float, dict]:
    """计算 Deflated Sharpe Ratio

    Args:
        sharpe_observed: 观察到（回测）的 Sharpe
        n_observations: 观测期数（默认 252 = 1年交易日）
        n_trials: 独立尝试次数（策略×参数组合数，默认50）
        sharpe_theoretical: 理论 Sharpe（默认 0 = 随机策略）

    Returns:
        (dsr, components) — dsr > 2.0 表示统计显著
    """
    e_max_sr, v_max_sr = expected_max_sharpe(n_trials, n_observations)
    std_max_sr = math.sqrt(v_max_sr) if v_max_sr > 0 else 1.0

    # DSR = (SR_obs - E[max SR]) / sqrt(V[max SR])
    dsr = (sharpe_observed - sharpe_theoretical - e_max_sr) / std_max_sr

    # p-value (单侧)
    p_value = 1.0 - sp_stats.norm.cdf(dsr)

    components = {
        "sharpe_observed": round(sharpe_observed, 4),
        "sharpe_theoretical": round(sharpe_theoretical, 4),
        "n_observations": n_observations,
        "n_trials": n_trials,
        "e_max_sharpe": round(e_max_sr, 4),
        "std_max_sharpe": round(std_max_sr, 4),
        "dsr": round(dsr, 4),
        "p_value": round(p_value, 6),
    }

    return dsr, components


def dsr_verdict(dsr: float) -> str:
    """根据 DSR 给出判断"""
    if dsr < 0:
        return f"🔴 DSR={dsr:.2f}: 策略表现低于随机期望，强烈过拟合信号"
    elif dsr < 1.0:
        return f"🟡 DSR={dsr:.2f}: 策略可能有alpha但统计不显著"
    elif dsr < 2.0:
        return f"🟢 DSR={dsr:.2f}: 策略有较显著alpha，接近95%置信"
    else:
        return f"✅ DSR={dsr:.2f}: 策略有统计显著的alpha(p<0.05)，拒绝过拟合假设"


def compute_dsr_for_strategy(
    sortino_observed: float,
    n_observations: int = 120,
    n_trials: int = 50,
) -> float:
    """针对 Sortino 计算类似 DSR（使用 Sortino 代替 Sharpe）

    Args:
        sortino_observed: 策略的 Sortino
        n_observations: 回测天数
        n_trials: 尝试次数

    Returns:
        DSR-like 值
    """
    dsr, comp = compute_dsr(
        sharpe_observed=sortino_observed * 0.7,  # Sortino → Sharpe 近似
        n_observations=n_observations,
        n_trials=n_trials,
    )
    return dsr


def compare_strategies_with_dsr(
    strategy_results: dict[str, dict],
    n_trials: int = 50,
) -> list[dict]:
    """对多个策略结果进行 DSR 比较排序

    Args:
        strategy_results: {name: {"sortino": X, "total_days": Y}}
        n_trials: 尝试次数

    Returns:
        [(排名, 策略名, DSR, Verdict), ...]
    """
    rankings = []
    for name, result in strategy_results.items():
        sortino = result.get("sortino_ratio") or result.get("sortino") or result.get("score", 0)
        n_days = result.get("total_days") or result.get("n_observations", 252)

        dsr, comp = compute_dsr(
            sharpe_observed=sortino * 0.7,  # 近似
            n_observations=n_days,
            n_trials=n_trials,
        )

        rankings.append({
            "strategy": name,
            "sortino": sortino,
            "dsr": round(dsr, 4),
            "verdict": dsr_verdict(dsr),
            "components": comp,
        })

    rankings.sort(key=lambda x: x["dsr"], reverse=True)

    for i, r in enumerate(rankings):
        r["rank"] = i + 1

    return rankings


if __name__ == "__main__":
    import sys, json

    if len(sys.argv) > 1:
        sharpe = float(sys.argv[1])
        n_trials = int(sys.argv[2]) if len(sys.argv) > 2 else 50
        dsr, comp = compute_dsr(sharpe, n_trials=n_trials)
        print(json.dumps(comp, indent=2))
        print(dsr_verdict(dsr))
    else:
        # Demo
        print("DSR Demo:")
        for sharpe, trials in [(1.5, 10), (2.0, 50), (3.0, 100), (5.0, 100)]:
            dsr, comp = compute_dsr(sharpe, n_trials=trials)
            print(f"  Sharpe={sharpe:.1f}, trials={trials}: DSR={dsr:.2f} — {dsr_verdict(dsr)}")
