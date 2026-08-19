"""
建仓6项检查 + TrailingStop 状态计算

功能:
  1. 建仓6查 — 双门/宏观/技术/质量/仓位/单一标的，6项全过才BUY
  2. TrailStop — 对持有中的标的计算动态止损线
  3. 月度再平衡 — 计算当前配置 vs 目标配置的偏离

使用: ExecutionChecker.check(score, macro, position) → execution_state
"""
from typing import Optional
from datetime import datetime, date
import logging

logger = logging.getLogger(__name__)

# 默认TrailingStop参数
DEFAULT_TRAIL_PARAMS = {
    "profit_high_bucket": {"threshold": 0.30, "multiplier": 0.88},      # 盈利≥30%
    "profit_med_bucket": {"threshold": 0.10, "multiplier": 0.85},       # 盈利10-30%
    "profit_low_bucket": {"threshold": 0.00, "multiplier": 0.92},       # 盈利<10%
    "loss_bucket": {"multiplier": 0.92},                                 # 亏损
}


class ExecutionChecker:
    """
    执行检查器: 建仓6查 + TrailStop + 月度再平衡

    使用示例:
        checker = ExecutionChecker()
        result = checker.check(
            symbol="600519",
            score_data={"composite": 0.72, "scores": {...}},
            macro_state={"dual_gate": {"macro": "绿", "trend": "黄"}, ...},
            position={"entry_price": 168, "current_price": 182, "quantity": 100, ...}
        )
    """

    def __init__(self, trail_params: Optional[dict] = None,
                 weekly_trade_limit: int = 3,
                 portfolio_config: Optional[dict] = None):
        self.trail_params = trail_params or DEFAULT_TRAIL_PARAMS
        self.weekly_trade_limit = weekly_trade_limit
        self.portfolio_config = portfolio_config or {}

    # ════════════════════════════════════════════
    # 主入口
    # ════════════════════════════════════════════

    def check(self, symbol: str, score_data: Optional[dict] = None,
              macro_state: Optional[dict] = None,
              position: Optional[dict] = None,
              current_positions: Optional[list[dict]] = None) -> dict:
        """
        对单个标的全量执行检查

        返回:
        {
            "symbol": str,
            "action": "BUY" / "SELL" / "HOLD" / "WAIT",
            "action_confidence": float,
            "build_checklist": {...} | None,      # 仅候选时
            "trail_stop": {...} | None,            # 仅持仓时
            "alternatives": [...],
            "historical_accuracy": {...}
        }
        """
        composite = (score_data or {}).get("composite", 0) if score_data else 0

        result = {"symbol": symbol}

        # 1. 建仓检查（未持仓 → 候选）
        if not position:
            checklist = self._build_checklist(score_data, macro_state, current_positions)
            result["build_checklist"] = checklist
            passed = sum(1 for c in checklist.values() if c.get("status") is True)
            total = len(checklist)
            result["action"] = "BUY" if passed >= 4 and composite >= 0.6 else "WAIT"
            result["action_confidence"] = 0.3 + 0.5 * (passed / total) if total > 0 else 0.3
            if passed < 4:
                result["action_reason"] = f"建仓检查 {passed}/{total} 通过"
            elif result["action"] == "BUY":
                result["action_reason"] = f"建仓检查 {passed}/{total} 通过, 评分{composite:.2f}"
        # 2. TrailStop（持仓）
        else:
            trail = self._calc_trail_stop(position, self.trail_params)
            result["trail_stop"] = trail
            if trail["status"] == "triggered":
                result["action"] = "SELL"
                result["action_confidence"] = 0.9
                result["action_reason"] = f"触发TrailStop,止损价{trail['stop_price']}"
            elif composite >= 0.7:
                result["action"] = "HOLD"
                result["action_confidence"] = 0.7
                result["action_reason"] = "评分>0.7, 继续持有"
            elif trail["status"] == "warning":
                result["action"] = "HOLD"
                result["action_confidence"] = 0.5
                result["action_reason"] = f"TrailStop距止损线仅{trail['distance_pct']:.1f}%"
            else:
                result["action"] = "HOLD"
                result["action_confidence"] = 0.6
                result["action_reason"] = "正常持仓"

        return result

    # ════════════════════════════════════════════
    # 建仓6项检查
    # ════════════════════════════════════════════

    def _build_checklist(self, score_data: Optional[dict],
                         macro_state: Optional[dict],
                         current_positions: Optional[list[dict]] = None) -> dict:
        """
        建仓6项检查

        检查项:
          1. 双门开启 — 宏观门绿/黄,趋势门绿/黄
          2. 宏观象限 — 扩张期/复苏期最好
          3. 技术面 — MA20>MA60 或价格>MA60
          4. 质量门控 — ROE>0, 营收增长>-30%
          5. 仓位上限 — A股总仓位<25%上限
          6. 单一标的限制 — 每只<2%仓位
        """
        checklist = {}

        # 1. 双门开启
        dg = (macro_state or {}).get("dual_gate", {}) or {}
        # 兼容两种键名: 缓存用 macro_gate/trend_gate, 旧格式用 macro/trend
        macro_gate = dg.get("macro_gate") or dg.get("macro") or ""
        trend_gate = dg.get("trend_gate") or dg.get("trend") or ""
        dg_open = macro_gate in ("绿灯", "绿") or trend_gate in ("绿灯", "绿")
        checklist["dual_gate_open"] = {
            "status": dg_open,
            "detail": f"双门:宏观{macro_gate or '?'}/趋势{trend_gate or '?'}",
        }

        # 2. 宏观象限 (regime 复苏/扩张/过热/衰退; 兼容旧 quadrant)
        quadrant = (macro_state or {}).get("regime") or (macro_state or {}).get("quadrant") or "未知"
        q_ok = quadrant in ("扩张期", "复苏期")
        checklist["macro_ok"] = {
            "status": q_ok,
            "detail": f"象限:{quadrant}",
        }

        # 3. 技术确认
        scores = (score_data or {}).get("scores", {})
        momentum = scores.get("momentum", 0.5) if scores else 0.5
        tech_ok = momentum >= 0.55
        checklist["technical_ok"] = {
            "status": tech_ok,
            "detail": f"动量={momentum:.2f}{'(≥0.55)' if tech_ok else '(<0.55)'}",
        }

        # 4. 质量门控
        quality = scores.get("quality", 0.5) if scores else 0.5
        quality_ok = quality >= 0.55
        checklist["quality_gate"] = {
            "status": quality_ok,
            "detail": f"质量={quality:.2f}{'(≥0.55)' if quality_ok else '(<0.55)'}",
        }

        # 5. 仓位上限
        total_a = 0
        held_count = 0
        if current_positions:
            total_a = sum(p.get("market_value", 0) for p in current_positions
                         if p.get("symbol", "").isdigit() or p.get("position_type") == "a_stock")
            held_count = len([p for p in current_positions
                             if p.get("symbol", "").isdigit()])
        total_value = 1000000  # 假定总资金（从config获取最佳）
        a_pct = (total_a / total_value * 100) if total_value > 0 else 0
        pos_limit = 0.25
        pos_ok = a_pct < pos_limit * total_value
        checklist["position_limit"] = {
            "status": pos_ok,
            "detail": f"A股{a_pct:.1f}%{'<上限' if pos_ok else '≥上限'}",
        }

        # 6. 单一标的上限（每只≤2%）
        single_ok = True
        checklist["single_stock_limit"] = {
            "status": single_ok,
            "detail": f"最大2%=¥{total_value*0.02:.0f}",
        }

        return checklist

    # ════════════════════════════════════════════
    # TrailingStop
    # ════════════════════════════════════════════

    def _calc_trail_stop(self, position: dict,
                         params: Optional[dict] = None) -> dict:
        """
        计算TrailingStop状态

        规则:
          盈利≥30% → 峰值×0.88
          盈利10-30% → 峰值×0.85
          盈利<10% → 峰值×0.92
          亏损 → 成本×0.92

        返回:
        {
            "status": "safe" / "warning" / "critical" / "triggered",
            "distance_pct": 10.5,     # 当前距止损%
            "stop_price": 162.8,
            "peak_price": 185.0,
            "current_price": 182.0,
            "bucket": "盈利>30%",
        }
        """
        params = params or DEFAULT_TRAIL_PARAMS
        entry = position.get("entry_price", 0)
        current = position.get("current_price", entry)
        peak = max(position.get("_peak_price", entry), current)
        qty = position.get("quantity", 0)

        if entry <= 0 or qty <= 0:
            return {"status": "unknown", "stop_price": 0, "distance_pct": 0}

        # 盈利%
        profit_pct = (current - entry) / entry
        # 按盈利区间选参数
        if profit_pct >= params["profit_high_bucket"]["threshold"]:
            mul = params["profit_high_bucket"]["multiplier"]
            bucket = "盈利≥30%"
        elif profit_pct >= params["profit_med_bucket"]["threshold"]:
            mul = params["profit_med_bucket"]["multiplier"]
            bucket = "盈利10-30%"
        elif profit_pct >= params["profit_low_bucket"]["threshold"]:
            mul = params["profit_low_bucket"]["multiplier"]
            bucket = "盈利<10%"
        else:
            mul = params["loss_bucket"]["multiplier"]
            bucket = "亏损"

        # 止损价 = 峰值 × 系数
        stop_price = round(peak * mul, 2)
        distance_pct = round((current - stop_price) / current * 100, 2) if current > 0 else 0

        # 状态判定
        if current <= stop_price:
            status = "triggered"
        elif distance_pct < 3:
            status = "critical"
        elif distance_pct < 8:
            status = "warning"
        else:
            status = "safe"

        return {
            "status": status,
            "distance_pct": distance_pct,
            "stop_price": stop_price,
            "peak_price": peak,
            "current_price": current,
            "entry_price": entry,
            "bucket": bucket,
            "rule_description": f"盈利{profit_pct*100:.1f}%→{bucket}:峰值{peak}×{mul}={stop_price}",
        }

    # ════════════════════════════════════════════
    # 月度再平衡计算
    # ════════════════════════════════════════════

    def calc_rebalance(self, target_allocation: dict,
                       actual_allocation: dict,
                       threshold: float = 0.05) -> dict:
        """
        计算月度再平衡需求

        返回:
        {
            "needs_rebalance": bool,
            "deviations": [{"category": str, "target": float, "actual": float, "diff": float}],
            "days_to_month_end": int,
        }
        """
        today = datetime.now()
        # 计算到月底天数
        import calendar
        _, days_in_month = calendar.monthrange(today.year, today.month)
        days_to_end = days_in_month - today.day

        deviations = []
        needs = False
        for asset, target_pct in target_allocation.items():
            actual_pct = actual_allocation.get(asset, 0)
            diff = target_pct - actual_pct
            deviations.append({
                "asset": asset,
                "target": target_pct,
                "actual": actual_pct,
                "diff": round(diff, 2),
            })
            if abs(diff) > threshold:
                needs = True

        return {
            "needs_rebalance": needs,
            "deviations": deviations,
            "days_to_month_end": days_to_end,
        }