"""
analysis/delta_tracker.py — 每日变化追踪引擎

面基系统的核心价值是"抓变化"(delta追踪)。
本模块跟踪每日:
1. 评分变化 Top5 — 哪些标的评分上升/下降最多
2. 池子进出 — 哪些标的进入/退出关注池
3. 因子漂移 — 哪些因子权重变化最大
4. 技术指标突变 — MACD金叉/死叉, RSI极端

用法:
    from analysis.delta_tracker import DeltaTracker

    dt = DeltaTracker()
    deltas = dt.compute_daily_deltas()
    print(deltas["score_changes_top5"])
"""
from __future__ import annotations

import json
import os
import copy
from datetime import datetime, date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
HISTORY_DIR = DATA_DIR / "delta_history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> dict:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def save_json(path: Path, data: dict):
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class DeltaTracker:
    """每日变化追踪器

    工作原理:
        - 每次 compute_daily_deltas() 时取当前快照, 与昨天的快照对比
        - 输出变化摘要
        - 保存今天快照作为明天的 baseline
    """

    def __init__(self):
        self.today_str = date.today().isoformat()
        self.yesterday_file = HISTORY_DIR / "previous_snapshot.json"

    def compute_daily_deltas(self) -> dict:
        """计算每日变化"""
        # 加载当前快照
        current = self._load_current_snapshot()
        if not current:
            return {"error": "当前快照不可用", "date": self.today_str}

        # 加载昨天快照
        previous = load_json(self.yesterday_file)

        deltas = {
            "date": self.today_str,
            "score_changes": self._compute_score_deltas(current, previous),
            "pool_changes": self._compute_pool_deltas(current, previous),
            "factor_drift": self._compute_factor_drift(current, previous),
            "tech_signals": self._compute_tech_signals(current),
        }

        # 保存今天快照
        save_json(self.yesterday_file, current)

        return deltas

    def _load_current_snapshot(self) -> dict | None:
        """从 scan_snapshot_latest.json + trading_signals.json 构建快照"""
        scan = load_json(DATA_DIR / "scan_snapshot_latest.json")
        signals = load_json(DATA_DIR / "trading_signals.json")
        shadow = load_json(DATA_DIR / "shadow_account.json")

        if not scan and not signals:
            return None

        return {
            "timestamp": datetime.now().isoformat(),
            "scan": scan,
            "signals": signals,
            "shadow": shadow,
        }

    def _compute_score_deltas(self, current: dict, previous: dict) -> dict:
        """计算评分变化 Top5"""
        cur_scan = current.get("scan", {}) if isinstance(current, dict) else {}
        prev_scan = previous.get("scan", {}) if isinstance(previous, dict) else {}

        cur_results = cur_scan.get("results", []) if isinstance(cur_scan, dict) else []
        prev_results = prev_scan.get("results", []) if isinstance(prev_scan, dict) else []

        if not cur_results or not prev_results:
            return {"available": False, "reason": "缺少历史快照"}

        # 建立 {symbol: score} 映射
        cur_scores = {r.get("symbol", ""): r.get("score", 0) for r in cur_results}
        prev_scores = {r.get("symbol", ""): r.get("score", 0) for r in prev_results}

        # 计算变化
        changes = []
        for sym, score in cur_scores.items():
            if sym in prev_scores:
                delta = score - prev_scores[sym]
                if abs(delta) >= 0.1:  # 过滤微变
                    changes.append({"symbol": sym, "previous": prev_scores[sym],
                                    "current": score, "delta": round(delta, 2)})

        changes.sort(key=lambda x: abs(x["delta"]), reverse=True)

        return {
            "available": True,
            "total_changed": len(changes),
            "rising": [c for c in changes[:5] if c["delta"] > 0],
            "falling": [c for c in changes[:5] if c["delta"] < 0],
            "top5_rising": changes[:5],
            "top5_falling": sorted(changes, key=lambda x: x["delta"])[:5],
        }

    def _compute_pool_deltas(self, current: dict, previous: dict) -> dict:
        """计算标的池进出"""
        cur_scan = current.get("scan", {}) if isinstance(current, dict) else {}
        prev_scan = previous.get("scan", {}) if isinstance(prev_scan, dict) else {}

        cur_results = cur_scan.get("results", []) if isinstance(cur_scan, dict) else []
        prev_results = prev_scan.get("results", []) if isinstance(prev_scan, dict) else []

        if not cur_results or not prev_results:
            return {"available": False}

        cur_symbols = {r.get("symbol", "") for r in cur_results}
        prev_symbols = {r.get("symbol", "") for r in prev_results}

        new_entries = cur_symbols - prev_symbols
        removals = prev_symbols - cur_symbols

        return {
            "available": True,
            "new_entries": list(new_entries)[:10],
            "removals": list(removals)[:10],
            "n_new": len(new_entries),
            "n_removed": len(removals),
        }

    def _compute_factor_drift(self, current: dict, previous: dict) -> dict:
        """计算因子权重漂移"""
        cur_scan = current.get("scan", {}) if isinstance(current, dict) else {}
        prev_scan = previous.get("scan", {}) if isinstance(prev_scan, dict) else {}

        # 因子权重可能在扫描结果中或单独文件
        cur_factors = None
        prev_factors = None

        if isinstance(cur_scan, dict):
            cur_factors = cur_scan.get("factor_weights") or cur_scan.get("lds_weights")
        if isinstance(prev_scan, dict):
            prev_factors = prev_scan.get("factor_weights") or prev_scan.get("lds_weights")

        if not cur_factors:
            # 尝试从专门文件加载
            cur_factors = load_json(DATA_DIR / "factor_weights_latest.json")
            prev_factors = load_json(HISTORY_DIR / "previous_factor_weights.json")

            if cur_factors:
                save_json(HISTORY_DIR / "previous_factor_weights.json", cur_factors)

        if not cur_factors or not prev_factors:
            return {"available": False}

        drifts = []
        for key, cur_val in cur_factors.items():
            if key in prev_factors:
                drift = cur_val - prev_factors[key]
                if abs(drift) >= 0.01:
                    drifts.append({"factor": key, "previous": prev_factors[key],
                                   "current": cur_val, "drift": round(drift, 4)})

        drifts.sort(key=lambda x: abs(x["drift"]), reverse=True)

        return {
            "available": True,
            "top_changes": drifts[:5],
            "n_changes": len(drifts),
        }

    def _compute_tech_signals(self, current: dict) -> dict:
        """提取当日技术信号"""
        cur_scan = current.get("scan", {}) if isinstance(current, dict) else {}
        cur_results = cur_scan.get("results", []) if isinstance(cur_scan, dict) else []

        signals = []
        for r in cur_results:
            tech = r.get("tech", {}) or {}
            if isinstance(tech, dict):
                macd = tech.get("macd_signal", "")
                rsi = tech.get("rsi", 50)
                sym = r.get("symbol", "")
                name = r.get("name", sym)

                if macd == "金叉":
                    signals.append({"symbol": sym, "name": name, "signal": "MACD金叉",
                                    "detail": f"RSI={rsi}"})
                elif macd == "死叉":
                    signals.append({"symbol": sym, "name": name, "signal": "MACD死叉",
                                    "detail": f"RSI={rsi}"})
                if rsi and rsi > 80:
                    signals.append({"symbol": sym, "name": name, "signal": "RSI超买",
                                    "detail": f"RSI={rsi}"})
                elif rsi and rsi < 20:
                    signals.append({"symbol": sym, "name": name, "signal": "RSI超卖",
                                    "detail": f"RSI={rsi}"})

        return {
            "available": True,
            "total_signals": len(signals),
            "signals": signals[:20],
        }

    def format_delta_report(self, deltas: dict = None) -> str:
        """将 delta 结果格式化为报告文本"""
        if deltas is None:
            deltas = self.compute_daily_deltas()

        if "error" in deltas:
            return f"❌ Delta追踪不可用: {deltas['error']}"

        lines = [f"📊 每日变化追踪 · {deltas['date']}"]
        lines.append("=" * 40)

        # 评分变化
        sc = deltas.get("score_changes", {})
        if sc.get("available"):
            rising = sc.get("rising", [])
            falling = sc.get("falling", [])
            if rising:
                rising_str = " ".join(f'{r["symbol"]}({r["delta"]:+.2f})' for r in rising[:3])
                lines.append(f"\n📈 评分上升 Top: {rising_str}")
            if falling:
                falling_str = " ".join(f'{r["symbol"]}({r["delta"]:+.2f})' for r in falling[:3])
                lines.append(f"📉 评分下降 Top: {falling_str}")
            lines.append(f"   {sc.get('total_changed', 0)}只有变化")
        else:
            lines.append("\n📈 评分变化: 需积累历史数据")

        # 池子变化
        pc = deltas.get("pool_changes", {})
        if pc.get("available"):
            new_entries = pc.get("new_entries", [])
            removals = pc.get("removals", [])
            if new_entries:
                lines.append(f"\n🆕 新进池: {', '.join(new_entries[:5])}")
            if removals:
                lines.append(f"🚫 出池: {', '.join(removals[:5])}")
        else:
            lines.append("\n🆕 池子进出: 需积累历史数据")

        # 技术信号
        ts = deltas.get("tech_signals", {})
        if ts.get("available") and ts.get("signals"):
            macd_signals = [s for s in ts["signals"] if "MACD" in s.get("signal", "")]
            if macd_signals:
                macd_str = "; ".join(f'{s["symbol"]} {s["signal"]}' for s in macd_signals[:5])
                lines.append(f"\n⚡ MACD信号: {macd_str}")
            rsi_extreme = [s for s in ts["signals"] if "RSI" in s.get("signal", "")]
            if rsi_extreme:
                rsi_str = "; ".join(f'{s["symbol"]}({s["detail"]})' for s in rsi_extreme[:3])
                lines.append(f"   RSI极端: {rsi_str}")

        return "\n".join(lines)


if __name__ == "__main__":
    dt = DeltaTracker()
    # 先生成初始快照（如果还没有）
    if not dt.yesterday_file.exists():
        snapshot = dt._load_current_snapshot()
        if snapshot:
            import json
            with open(dt.yesterday_file, "w") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
            print("✅ 已保存今天快照作为 baseline")
        else:
            print("❌ 无法获取当前快照")
    else:
        deltas = dt.compute_daily_deltas()
        print(dt.format_delta_report(deltas))
