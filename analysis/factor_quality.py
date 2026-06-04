"""
因子质量度量 v1.0 — IC追踪 + 衰减曲线 + 有效性评估

IC (Information Coefficient): 因子分与未来N日收益的Spearman秩相关系数
   IC > 0.05: 因子有效
   IC > 0.10: 因子显著
   IC < 0.02: 因子失效

存储: .hermes/factor_history.json
每日扫描后保存分数+价格快照，用于后续IC回溯计算
"""
import json, os, time
from datetime import datetime, timedelta
from pathlib import Path

HISTORY_FILE = Path(__file__).parent.parent / '.hermes' / 'factor_history.json'
MAX_HISTORY_DAYS = 90


def _load():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except: pass
    return {"scores": {}, "prices": {}}


def _save(data):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    # 只保留最近90天
    dates = sorted(data.get("scores", {}).keys(), reverse=True)
    for old in dates[MAX_HISTORY_DAYS:]:
        data["scores"].pop(old, None)
        data["prices"].pop(old, None)
    with open(HISTORY_FILE, 'w') as f:
        json.dump(data, f)


def save_snapshot(scan_results, prices_map=None):
    """保存当日扫描快照：分数 + 因子明细 + 价格"""
    today = datetime.now().strftime("%Y-%m-%d")
    data = _load()

    scores_entry = []
    for s in scan_results:
        sym = s.get("symbol", "")
        if not sym: continue
        entry = {
            "symbol": sym,
            "score": s.get("score", 0),
        }
        factors = s.get("factors", {})
        if factors:
            entry["factors"] = {k: round(v, 2) for k, v in factors.items()}
        scores_entry.append(entry)

    data["scores"][today] = scores_entry

    if prices_map:
        data["prices"][today] = {str(k): v for k, v in prices_map.items()
                                 if v is not None}

    _save(data)


def compute_ic(horizon_days=5):
    """计算综合因子IC: Spearman rank correlation between score(t) and return(t+horizon)"""
    data = _load()
    scores_hist = data.get("scores", {})
    prices_hist = data.get("prices", {})

    all_scores, all_returns = [], []
    dates = sorted(scores_hist.keys())

    for i, date_t in enumerate(dates):
        # 找 horizon 天后的日期
        dt_t = datetime.strptime(date_t, "%Y-%m-%d")
        dt_future = dt_t + timedelta(days=horizon_days)
        date_future = None
        for d in dates:
            if d >= dt_future.strftime("%Y-%m-%d"):
                date_future = d
                break
        if not date_future:
            continue

        day_scores = {s["symbol"]: s["score"] for s in scores_hist.get(date_t, [])}
        day_prices_t = prices_hist.get(date_t, {})
        day_prices_f = prices_hist.get(date_future, {})

        for sym, score in day_scores.items():
            if sym in day_prices_t and sym in day_prices_f:
                p_t = day_prices_t[sym]
                p_f = day_prices_f[sym]
                if p_t > 0 and p_f > 0:
                    ret = (p_f - p_t) / p_t
                    all_scores.append(score)
                    all_returns.append(ret)

    if len(all_scores) < 10:
        return None

    try:
        from scipy.stats import spearmanr
        ic, pvalue = spearmanr(all_scores, all_returns)
        return {"ic": round(ic, 4), "pvalue": round(pvalue, 4), "samples": len(all_scores), "horizon": horizon_days}
    except ImportError:
        # scipy不可用, 用纯Python计算近似
        n = len(all_scores)
        rank_x = _rank(all_scores)
        rank_y = _rank(all_returns)
        mean_rx = sum(rank_x) / n
        mean_ry = sum(rank_y) / n
        cov = sum((rx - mean_rx) * (ry - mean_ry) for rx, ry in zip(rank_x, rank_y))
        std_x = (sum((rx - mean_rx)**2 for rx in rank_x) / n) ** 0.5
        std_y = (sum((ry - mean_ry)**2 for ry in rank_y) / n) ** 0.5
        ic = cov / (n * std_x * std_y) if std_x > 0 and std_y > 0 else 0
        return {"ic": round(ic, 4), "pvalue": None, "samples": n, "horizon": horizon_days}


def _rank(values):
    sorted_pairs = sorted(enumerate(values), key=lambda x: x[1])
    ranks = [0] * len(values)
    for rank, (idx, _) in enumerate(sorted_pairs, 1):
        ranks[idx] = rank
    return ranks


def compute_ic_by_factor(horizon_days=5):
    """按六因子分别计算IC"""
    data = _load()
    scores_hist = data.get("scores", {})
    prices_hist = data.get("prices", {})

    factor_names = ["质量", "价值", "成长", "低波", "红利", "动量"]
    factor_results = {}

    for fn in factor_names:
        all_scores, all_returns = [], []
        dates = sorted(scores_hist.keys())

        for i, date_t in enumerate(dates):
            dt_t = datetime.strptime(date_t, "%Y-%m-%d")
            dt_future = dt_t + timedelta(days=horizon_days)
            date_future = None
            for d in dates:
                if d >= dt_future.strftime("%Y-%m-%d"):
                    date_future = d
                    break
            if not date_future: continue

            day_scores_list = scores_hist.get(date_t, [])
            day_prices_t = prices_hist.get(date_t, {})
            day_prices_f = prices_hist.get(date_future, {})

            for s in day_scores_list:
                sym = s["symbol"]
                factors = s.get("factors", {})
                score = factors.get(fn)
                if score is None: continue
                if sym in day_prices_t and sym in day_prices_f:
                    p_t = day_prices_t[sym]
                    p_f = day_prices_f[sym]
                    if p_t > 0 and p_f > 0:
                        ret = (p_f - p_t) / p_t
                        all_scores.append(score)
                        all_returns.append(ret)

        if len(all_scores) >= 10:
            try:
                from scipy.stats import spearmanr
                ic, pv = spearmanr(all_scores, all_returns)
                factor_results[fn] = {"ic": round(ic, 4), "pvalue": round(pv, 4), "samples": len(all_scores)}
            except ImportError:
                factor_results[fn] = {"ic": 0, "pvalue": None, "samples": len(all_scores)}
        else:
            factor_results[fn] = None

    return factor_results


def compute_decay(horizons=[1, 3, 5, 10, 20]):
    """因子衰减曲线: 不同持有期的IC变化"""
    results = {}
    for h in horizons:
        ic_result = compute_ic(h)
        if ic_result:
            results[str(h)] = ic_result
    return results


def get_quality_report():
    """日报调用: 返回因子质量报告"""
    ic_5d = compute_ic(5)
    factor_ic = compute_ic_by_factor(5)
    decay = compute_decay()

    # 有效/失效判断
    effective, weak, dead = [], [], []
    if factor_ic:
        for fn, r in factor_ic.items():
            if r is None: continue
            ic_val = r["ic"]
            if ic_val > 0.05: effective.append(fn)
            elif ic_val > 0.02: weak.append(fn)
            else: dead.append(fn)

    return {
        "composite_ic": ic_5d,
        "factor_ic": factor_ic,
        "decay": decay,
        "effective": effective,
        "weak": weak,
        "dead": dead,
        "samples_days": _count_days(),
    }


def _count_days():
    data = _load()
    return len(data.get("scores", {}))
