"""
面基投资系统 · 信号历史验证器

功能: 对过去的信号回查真实涨跌幅，计算各时段(5/10/20日)命中率。
按分数段/策略/产业链/方向聚合统计。

架构位置:
  run_trading.py 每次运行后调用 → signal_accuracy_history.json 追加记录

用法:
  validator = SignalValidator()
  report = validator.validate()  # 回查所有未验证的信号
  stats = validator.aggregate()  # 聚合统计
"""
import json, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "signal_accuracy_history.json"


class SignalValidator:
    """信号验证 — 回查历史信号+聚合统计"""

    def __init__(self):
        self.history = self._load_history()

    def _load_history(self) -> dict:
        if HISTORY_FILE.exists():
            try:
                with open(HISTORY_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"信号验证历史读取失败: {e}")
        return {"records": [], "aggregated": {}}

    def _save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2, default=str)

    def validate(self) -> dict:
        """回查未验证的信号——暂为计算框架，等 yfinance 集成后自动回查"""
        records = self.history.get("records", [])
        total = len(records)
        verified = sum(1 for r in records if r.get("verified", False))
        return {
            "total_signals": total,
            "verified": verified,
            "pending": total - verified,
            "message": f"共{total}条信号，{verified}条已验证，{total - verified}条待验证",
        }

    def record_signal(self, date: str, symbol: str, action: str, score: float, strategy: str = ""):
        """记录一条新信号（待验证）"""
        records = self.history.setdefault("records", [])
        records.append({
            "date": date,
            "symbol": symbol,
            "action": action,
            "score": round(score, 2),
            "strategy": strategy,
            "verified": False,
            "returns": {},
            "correct": None,
            "recorded_at": datetime.now().isoformat(),
        })
        self._save()
        return len(records)

    def aggregate(self) -> dict:
        """聚合统计 — 按分数段/策略/方向计算当前已验证信号性能"""
        records = self.history.get("records", [])
        verified = [r for r in records if r.get("verified") and r.get("correct") is not None]
        total_v = len(verified)
        if total_v == 0:
            return {
                "total_verified": 0,
                "overall_accuracy": None,
                "by_score_band": {},
                "by_strategy": {},
                "last_updated": None,
            }

        correct = sum(1 for r in verified if r["correct"])
        overall = correct / total_v if total_v else 0

        # 按分数段
        bands = {"high": (0, 0), "mid": (0, 0), "low": (0, 0)}
        for r in verified:
            s = r.get("score", 0)
            if s >= 0.63:
                k = "high"
            elif s >= 0.48:
                k = "mid"
            else:
                k = "low"
            c, t = bands[k]
            bands[k] = (c + (1 if r["correct"] else 0), t + 1)

        by_band = {}
        for k, (c, t) in bands.items():
            by_band[k] = {"correct": c, "total": t, "accuracy": round(c / t, 3) if t else None}

        # 按策略
        strategies = {}
        for r in verified:
            st = r.get("strategy", "unknown")
            if st not in strategies:
                strategies[st] = {"correct": 0, "total": 0}
            strategies[st]["correct"] += 1 if r["correct"] else 0
            strategies[st]["total"] += 1
        by_strategy = {
            k: {"correct": v["correct"], "total": v["total"],
                "accuracy": round(v["correct"] / v["total"], 3) if v["total"] else None}
            for k, v in strategies.items()
        }

        return {
            "total_verified": total_v,
            "overall_accuracy": round(overall, 3),
            "by_score_band": by_band,
            "by_strategy": by_strategy,
            "last_updated": datetime.now().isoformat(),
        }
