#!/usr/bin/env python3
"""前视偏差 + 幸存者偏差 对照实验（只读审计，不修改任何现有代码）

用法:
  source .opencode/env.sh
  python3 scripts/audit_lookahead_bias.py

目标: 量化 FIXED_SCORE_MAP 固定评分带来的回测收益失真 + FIXED_UNIVERSE 幸存者偏差。

实验组 (同样 19 只 FIXED_UNIVERSE、同样 120 天真实日线、同样策略/成本模型):
  组A (现状/基线)    : FIXED_SCORE_MAP 固定评分 → 线上 dashboard 回测数字来源
  组B (等权买入持有)  : 等权持有 19 只到期末   → 量化幸存者偏差(选对池子的收益)
  组C (随机评分)      : 评分随机 shuffle       → 量化评分排序是否有真实 alpha
  组D (中性评分)      : 全部评分 = 5.0        → 量化去掉静态评分后的策略收益

结论指标:
  幸存者偏差 ≈ 组B收益 − 沪深300同期收益
  评分排序 alpha ≈ 组A收益 − 组C收益
  静态评分贡献 ≈ 组A收益 − 组D收益
"""
from __future__ import annotations

import sys, json, random
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # 项目根
sys.path.insert(0, str(ROOT))

import engine.evaluator_fixed as ef
from engine.evaluator_fixed import (
    FIXED_UNIVERSE, FIXED_SCORE_MAP, preload_all_data, load_dates_map,
)
from strategies.faceji import decide as faceji_decide
from strategies.silverquant import decide as silverquant_decide

DAYS = 120
STRATEGIES = {"faceji": faceji_decide, "silverquant": silverquant_decide}


def run_with_scores(score_map: dict, decide_fn, price_data, dates_map):
    """复用 ef.run_backtest，通过 monkeypatch FIXED_SCORE_MAP 注入自定义评分。"""
    old = ef.FIXED_SCORE_MAP
    ef.FIXED_SCORE_MAP = dict(score_map)
    try:
        r = ef.run_backtest(price_data, decide_fn, "audit", dates_map=dates_map)
    finally:
        ef.FIXED_SCORE_MAP = old
    return r


def result_summary(r):
    if isinstance(r, dict) and "error" in r:
        return {"error": r["error"]}
    return {
        "total_return_pct": round(r.total_return_pct, 2),
        "annualized_pct": round(r.annualized_return_pct, 2),
        "sharpe": round(r.sharpe_ratio, 3),
        "max_drawdown_pct": round(r.max_drawdown_pct, 2),
        "win_rate_pct": round(r.win_rate_pct, 1),
        "trade_count": r.trade_count,
        "final_value": round(r.final_value, 0),
    }


def buy_and_hold(price_data) -> float:
    """等权买入持有到期末，返回组合总收益率(%)。"""
    rets = [closes[-1] / closes[0] - 1 for closes in price_data.values()
            if len(closes) >= 2 and closes[0] > 0]
    return round(sum(rets) / len(rets) * 100, 2) if rets else 0.0


def fetch_benchmark() -> dict:
    """沪深300同期收益(量化幸存者偏差的大盘参照)。"""
    import baostock as bs
    from datetime import datetime, timedelta
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=DAYS * 2)).strftime("%Y-%m-%d")
    try:
        lg = bs.login()
        if lg.error_code != "0":
            return {"error": "login failed"}
        rs = bs.query_history_k_data_plus(
            "sh.000300", "date,close", start_date=start, end_date=end, frequency="d"
        )
        closes = []
        while rs.error_code == "0" and rs.next():
            closes.append(float(rs.get_row_data()[1]))
        bs.logout()
        if len(closes) < 2:
            return {"error": "no data"}
        return {"return_pct": round((closes[-1] / closes[0] - 1) * 100, 2), "n_days": len(closes)}
    except Exception as e:
        return {"error": str(e)}


def main():
    print("📦 加载 19 只股票 120 天日线...")
    price_data = preload_all_data(days=DAYS)
    if not price_data:
        print("❌ 无数据")
        return
    print(f"   有效标的 {len(price_data)}/{len(FIXED_UNIVERSE)}")
    dates_map = load_dates_map(days=DAYS)

    symbols = [s["symbol"] for s in FIXED_UNIVERSE]
    score_a = dict(FIXED_SCORE_MAP)
    score_c = dict(FIXED_SCORE_MAP)
    vals = list(score_c.values())
    random.Random(42).shuffle(vals)
    score_c = {sym: v for sym, v in zip(symbols, vals)}
    score_d = {sym: 5.0 for sym in symbols}

    out = {"universe_size": len(price_data), "days": DAYS, "groups": {}}

    bh = buy_and_hold(price_data)
    out["groups"]["B_buy_hold"] = {"total_return_pct": bh}
    print(f"\n组B 等权买入持有: {bh:+.2f}%")

    for sname, decide_fn in STRATEGIES.items():
        for gname, score_map in [("A_fixed", score_a), ("C_shuffled", score_c), ("D_neutral", score_d)]:
            r = run_with_scores(score_map, decide_fn, price_data, dates_map)
            key = f"{sname}_{gname}"
            out["groups"][key] = result_summary(r)
            s = out["groups"][key]
            if "error" in s:
                print(f"{key}: ERROR {s['error']}")
            else:
                print(f"{key}: 收益{s['total_return_pct']:+.2f}% 年化{s['annualized_pct']:+.2f}% "
                      f"Sharpe{s['sharpe']} MDD{s['max_drawdown_pct']}% 胜率{s['win_rate_pct']}% 交易{s['trade_count']}笔")

    bm = fetch_benchmark()
    out["benchmark_hs300"] = bm
    print(f"\n沪深300同期: {bm}")

    outpath = ROOT / "data" / "lookahead_bias_result.json"
    outpath.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ 结果已写 {outpath}")


if __name__ == "__main__":
    main()
