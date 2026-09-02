"""
证据层 API — 信号验证 + 数据质量 + 因子归因
每个端点返回的不是"原始数据"，是"为什么可以信任这个结论"的推理链
"""
import json, os
from datetime import datetime
from fastapi import APIRouter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

router = APIRouter()


@router.get("/api/v2/evidence/signal-accuracy")
def evidence_signal_accuracy():
    """
    信号预测准确率 — ✅ 最重要的证据模块
    返回: 过去信号的预测命中率（按分数段/策略/时间段拆分）
    """
    path = ROOT / "data" / "signal_accuracy_history.json"
    if not path.exists():
        return {
            "status": "no_data",
            "message": "尚未生成信号验证数据。run_trading.py 将在下次运行时自动记录。",
            "data": {
                "overall": {"hit_rate": 0, "total_signals": 0, "avg_return": 0},
                "by_score_band": [],
                "by_strategy": [],
                "last_30d_trend": []
            }
        }

    with open(path) as f:
        raw = json.load(f)

    # 解析验证历史
    history = raw.get("history", [])
    if not history:
        return {
            "status": "empty",
            "message": "历史信号记录为空",
            "data": {
                "overall": {"hit_rate": 0, "total_signals": 0, "avg_return": 0},
                "by_score_band": [],
                "by_strategy": [],
                "last_30d_trend": []
            }
        }

    # 按日期排序
    history.sort(key=lambda x: x.get("date", ""))

    # 统计总体
    total_signals = sum(h.get("score_results_count", 0) for h in history)
    total_price_valid = sum(h.get("price_valid_count", 0) for h in history)
    total_price_skipped = sum(h.get("price_zero_skipped", 0) for h in history)

    # 按策略的信号数量
    by_strategy = {}
    for h in history:
        for sig in h.get("signals", []):
            strat = sig.get("strategy", sig.get("strategy_name", "unknown")) if isinstance(sig, dict) else "unknown"
            by_strategy[strat] = by_strategy.get(strat, 0) + 1

    # 日期范围
    dates = [h.get("date", "") for h in history if h.get("date", "")]
    first_date = min(dates) if dates else "N/A"
    last_date = max(dates) if dates else "N/A"

    last_30d = dict(raw.get("last_30d", {}))
    if last_30d.get("hit_rate") in (None, 0):
        last_30d["hit_rate"] = None
        last_30d["verification_status"] = "pending"

    return {
        "status": "ok",
        "message": f"信号验证数据从 {first_date} 到 {last_date}，{len(history)} 个交易日",
        "data": {
            "overall": {
                "total_days": len(history),
                "total_signals": total_signals,
                "price_valid": total_price_valid,
                "price_zero_skipped": total_price_skipped,
                "last_update": last_date,
            },
            "by_strategy": by_strategy,
            "recent_history": [
                {
                    "date": h.get("date", ""),
                    "price_valid": h.get("price_valid_count", 0),
                    "price_skipped": h.get("price_zero_skipped", 0),
                    "signals_count": len(h.get("signals", [])),
                }
                for h in history[-30:]
            ],
            "last_30d": last_30d,
        }
    }


@router.get("/api/v2/evidence/data-quality")
def evidence_data_quality():
    """
    数据质量证据 — 每个数据源的新鲜度、完整度、错误率
    返回: 数据可信度评分 + 每个数据源的证据
    """
    data_dir = ROOT / "data"
    now = datetime.now()

    # 检查关键数据文件的新鲜度
    files_to_check = [
        ("trading_signals.json", "模拟盘快照", 3600, "交易信号、持仓、组合净值"),
        ("strategy_states.json", "策略状态", 3600, "各策略持仓/现金/交易历史"),
        ("signal_accuracy_history.json", "信号验证历史", 86400, "信号表现跟踪"),
        ("news_cache.json", "新闻缓存", 1800, "新闻多源聚合"),
        ("dragon_tiger.json", "龙虎榜", 86400, "龙虎榜当日数据"),
        ("etf_discovery.json", "ETF发现", 86400, "全市场ETF扫描"),
        ("etf_portfolio.json", "ETF组合", 86400, "ETF组合配置"),
        ("behavior_diagnosis.json", "行为诊断", 86400, "行为偏误分析"),
        ("shadow_account.json", "影子账户", 3600, "模拟盘总账"),
        ("pool/watch.json", "发现层票池", 86400, "三层票池—发现层"),
        ("pool/monitor.json", "盯住层票池", 86400, "三层票池—盯住层"),
        ("pool/deep.json", "深度层票池", 86400, "三层票池—深度层"),
    ]

    entries = []
    score_sum = 0
    score_count = 0

    for rel_path, label, ttl_seconds, description in files_to_check:
        fpath = data_dir / rel_path
        if fpath.exists():
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime)
            age_seconds = (now - mtime).total_seconds()
            age_hours = age_seconds / 3600

            if age_seconds <= ttl_seconds:
                freshness = "fresh"
                freshness_score = 1.0
            elif age_seconds <= ttl_seconds * 3:
                freshness = "stale"
                freshness_score = 0.5
            else:
                freshness = "expired"
                freshness_score = 0.2

            try:
                with open(fpath) as f:
                    file_size = len(f.read())
            except Exception:
                file_size = 0

            entries.append({
                "file": rel_path,
                "label": label,
                "description": description,
                "exists": True,
                "size_bytes": file_size,
                "last_updated": mtime.strftime("%Y-%m-%d %H:%M:%S"),
                "age_hours": round(age_hours, 1),
                "ttl_hours": round(ttl_seconds / 3600, 1),
                "freshness": freshness,
                "score": freshness_score,
                "evidence": f"{'最新' if freshness=='fresh' else '过期'} — 距上次更新 {age_hours:.0f}小时，预期更新 <{ttl_seconds/3600:.0f}h"
            })
        else:
            entries.append({
                "file": rel_path,
                "label": label,
                "exists": False,
                "freshness": "missing",
                "score": 0,
                "evidence": f"❌ 文件不存在 — 请先运行对应数据采集脚本"
            })

        score_sum += entries[-1].get("score", 0)
        score_count += 1

    avg_score = round(score_sum / score_count, 2) if score_count > 0 else 0

    # 打分评级
    if avg_score >= 0.85:
        grade = "A"
        grade_text = "✅ 数据质量良好，证据可信"
    elif avg_score >= 0.65:
        grade = "B"
        grade_text = "⚠️ 数据质量一般，部分数据过期"
    elif avg_score >= 0.40:
        grade = "C"
        grade_text = "⚠️ 数据质量差，多项数据过期"
    else:
        grade = "D"
        grade_text = "🔴 数据质量极差，大部分数据不可用"

    return {
        "status": "ok",
        "grade": grade,
        "grade_text": grade_text,
        "overall_score": avg_score,
        "entries": entries,
        "assessed_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "evidence": f"基于 {score_count} 个数据源的 {avg_score*100:.0f} 分 — {grade_text}"
    }


@router.get("/api/v2/evidence/factor-breakdown/{symbol}")
def evidence_factor_breakdown(symbol: str):
    """
    因子归因证据 — 单个标的的因子分解
    返回: 这个标的为什么得这个分
    """
    # 从 scan_snapshot_latest.json 获取最新因子数据
    scan_path = ROOT / "data" / "scan_snapshot_latest.json"
    if not scan_path.exists():
        return {
            "status": "no_data",
            "message": "尚未运行因子扫描",
            "symbol": symbol,
            "evidence": None
        }

    with open(scan_path) as f:
        scan = json.load(f)

    # 找这个标的
    for r in scan.get("results", []):
        if r.get("symbol", "") == symbol:
            scores = r.get("scores", {})
            breakdown = r.get("factor_breakdown", {})

            # 计算证据链
            evidence_chain = {}
            for factor_name, factor_score in scores.items():
                subs = breakdown.get(factor_name, {})
                if isinstance(subs, dict):
                    # 找出最强和最弱的子因子
                    sorted_subs = sorted(subs.items(), key=lambda x: abs(x[1]) if isinstance(x[1], (int, float)) else 0, reverse=True)
                    top_sub = sorted_subs[0] if sorted_subs else None
                    evidence_chain[factor_name] = {
                        "score": round(factor_score, 4) if isinstance(factor_score, (int, float)) else factor_score,
                        "sub_factors": {k: round(v, 4) if isinstance(v, (int, float)) else v for k, v in subs.items() if isinstance(v, (int, float)) or v is not None},
                        "top_driver": f"{top_sub[0]}={top_sub[1]:.4f}" if top_sub else "",
                    }

            return {
                "status": "ok",
                "symbol": symbol,
                "name": r.get("name", symbol),
                "composite": r.get("composite", 0),
                "composite_v3": r.get("score", 0),
                "signal": r.get("signal", "HOLD"),
                "price": r.get("price", 0),
                "evidence_chain": evidence_chain,
                "evidence": f"标的 {symbol}({r.get('name','?')}) 综合分 {r.get('composite',0):.4f}（v3={r.get('score',0):.1f}），信号={r.get('signal','HOLD')}。扫描日期: {scan.get('date','?')}",
                "score_date": scan.get("date", "N/A"),
            }

    return {
        "status": "not_found",
        "symbol": symbol,
        "message": f"{symbol} 不在最新扫描结果中，可能未评分或未覆盖",
        "evidence": None
    }


@router.get("/api/v2/evidence/score-justification/{symbol}")
def evidence_score_justification(symbol: str):
    """
    评分依据证据 — 每个子因子的原始值、方向、排名
    这个端点展示"为什么给了 0.72 而不是 0.68"
    """
    # 从因子引擎直接获取
    scan_path = ROOT / "data" / "scan_snapshot_latest.json"
    if not scan_path.exists():
        return {
            "status": "no_data",
            "symbol": symbol,
            "evidence": "❌ 未运行因子扫描，无法提供评分依据"
        }

    with open(scan_path) as f:
        scan = json.load(f)

    for r in scan.get("results", []):
        if r.get("symbol", "") == symbol:
            scores = r.get("scores", {})
            breakdown = r.get("factor_breakdown", {})
            composite = r.get("composite", 0)
            signal = r.get("signal", "HOLD")

            # 构建评分依据
            why_high = []  # 为什么得分高
            why_low = []   # 为什么得分低
            for factor_name, factor_score in scores.items():
                subs = breakdown.get(factor_name, {})
                if isinstance(subs, dict):
                    for sub_name, sub_val in subs.items():
                        if isinstance(sub_val, (int, float)):
                            if sub_val > 0.7:
                                why_high.append(f"{factor_name}.{sub_name}={sub_val:.2f}")
                            elif sub_val < 0.3:
                                why_low.append(f"{factor_name}.{sub_name}={sub_val:.2f}")

            return {
                "status": "ok",
                "symbol": symbol,
                "name": r.get("name", symbol),
                "composite": composite,
                "signal": signal,
                "price": r.get("price", 0),
                "why_high": why_high[:10],
                "why_low": why_low[:10],
                "evidence": f"综合分 {composite:.4f}→{signal}。拉高分: {len(why_high)}项({'·'.join(why_high[:4])})。拖低分: {len(why_low)}项({'·'.join(why_low[:4])})",
                "score_date": scan.get("date", ""),
            }

    return {"status": "not_found", "symbol": symbol, "evidence": "未找到评分记录"}


@router.get("/api/v2/evidence/portfolio-attribution")
def evidence_portfolio_attribution():
    """
    业绩归因证据 — 总收益的钱从哪里来
    返回: 归因分解（Brinson 类似）+ 基准对比
    """
    # 从 trading_signals.json 获取
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"status": "no_data", "evidence": "未运行交易引擎，无法归因"}

    with open(ts_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    trade_history = data.get("trade_history", {})

    attribution = {}
    for sname in ["faceji", "silverquant", "tradingagents"]:
        pf = portfolios.get(sname, {})
        th = trade_history.get(sname, [])

        cash = pf.get("cash", 1000000)
        invested = pf.get("total_invested", 0)
        total_value = cash + invested
        total_pnl = total_value - 1000000
        total_return = total_pnl / 1000000 * 100

        # 交易归因（如果有）
        wins = [t for t in th if t.get("pnl", 0) > 0]
        losses = [t for t in th if t.get("pnl", 0) < 0]
        avg_win = sum(t.get("pnl", 0) for t in wins) / len(wins) if wins else 0
        avg_loss = abs(sum(t.get("pnl", 0) for t in losses)) / len(losses) if losses else 0
        profit_factor = (avg_win * len(wins)) / (avg_loss * len(losses)) if losses and avg_loss > 0 else 0

        attribution[sname] = {
            "total_return": round(total_return, 2),
            "total_pnl": round(total_pnl, 2),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "position_count": pf.get("position_count", 0),
            "history_count": len(th),
            "win_count": len(wins),
            "loss_count": len(losses),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "evidence": (
                f"总收益{total_return:+.2f}%（¥{total_pnl:+.0f}）。"
                f"历史{len(th)}笔交易，{len(wins)}胜{len(losses)}负。"
                f"平均盈利¥{avg_win:.0f}、平均亏损¥{avg_loss:.0f}、" 
                f"盈利率{profit_factor:.2f}倍。"
            )
        }

    return {
        "status": "ok",
        "attribution": attribution,
        "evidence": (
            f"三策略全历史归因：面基{attribution.get('faceji',{}).get('total_return','?')}%、"
            f"SilverQuant{attribution.get('silverquant',{}).get('total_return','?')}%、"
            f"TradingAgents{attribution.get('tradingagents',{}).get('total_return','?')}%"
        ),
        "note": "⚠️ 交易历史为空：信号从未被自动执行，归因仅基于组合现金残值推算"
    }
