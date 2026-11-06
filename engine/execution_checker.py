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

try:
    from investment_system import config as _config
except ImportError:
    import config as _config

from strategies.base import (
    TRAILING_MIN_HOLD_DAYS, hold_days, trailing_stop_threshold,
)

logger = logging.getLogger(__name__)

_RISK = getattr(_config, "RISK_PARAMS", {}) or {}
_DISC = getattr(_config, "TRADING_DISCIPLINE", {}) or {}

# 无组合总资产信息时的兜底（模拟盘初始资金）
DEFAULT_TOTAL_VALUE = 1000000.0


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

    def __init__(self, weekly_trade_limit: Optional[int] = None,
                 portfolio_config: Optional[dict] = None):
        self.weekly_trade_limit = weekly_trade_limit or int(
            _DISC.get("max_trades_per_week_per_strategy", 3)
        )
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
            trail = self._calc_trail_stop(position)
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

        # 5. 仓位上限（ADR-0005：从 RISK_PARAMS 读，按比率比较）
        total_a = 0
        if current_positions:
            total_a = sum(p.get("market_value", 0) for p in current_positions
                         if p.get("symbol", "").isdigit() or p.get("position_type") == "a_stock")
        total_value = float(
            self.portfolio_config.get("total_value")
            or self.portfolio_config.get("capital")
            or 0
        )
        if total_value <= 0 and current_positions:
            total_value = sum(p.get("market_value", 0) for p in current_positions)
        if total_value <= 0:
            total_value = DEFAULT_TOTAL_VALUE
        a_pct = (total_a / total_value * 100) if total_value > 0 else 0
        pos_limit_pct = float(_RISK.get("max_a_share_position", 0.25)) * 100
        pos_ok = a_pct <= pos_limit_pct
        checklist["position_limit"] = {
            "status": pos_ok,
            "detail": f"A股{a_pct:.1f}%{'≤' if pos_ok else '>'}上限{pos_limit_pct:.1f}%",
        }

        # 6. 单一标的上限（取 RISK_PARAMS.max_single_position，默认 12%）
        single_limit = float(_RISK.get("max_single_position", 0.12))
        max_single = max(
            (p.get("market_value", 0) for p in (current_positions or [])),
            default=0,
        )
        single_pct = (max_single / total_value * 100) if total_value > 0 else 0
        single_ok = single_pct <= single_limit * 100
        checklist["single_stock_limit"] = {
            "status": single_ok,
            "detail": (
                f"最大单票{single_pct:.2f}%{'≤' if single_ok else '>'}上限"
                f"{single_limit*100:.0f}% (¥{total_value*single_limit:.0f})"
            ),
        }

        return checklist

    # ════════════════════════════════════════════
    # TrailingStop
    # ════════════════════════════════════════════

    def _calc_trail_stop(self, position: dict) -> dict:
        """
        计算TrailingStop状态（ADR-0005：与策略层共用一套四档规则）

        规则(docs/STRATEGY.md §5.4):
          持仓 < TRAILING_MIN_HOLD_DAYS 天 → 仅成本价 -8% 硬止损
          持仓满后：盈利≥30% → 峰值-12%；10-30% → 峰值-15%；其余 → 峰值-20%
        最终止损线取「硬止损线」与「四档 trailing 线」中更紧（更高）的一条。

        返回:
        {
            "status": "safe" / "warning" / "critical" / "triggered",
            "distance_pct": 10.5,     # 当前距止损%
            "stop_price": 162.8,
            "peak_price": 185.0,
            "current_price": 182.0,
            "bucket": "T3",
        }
        """
        entry = position.get("entry_price", 0)
        current = position.get("current_price", entry)
        peak = max(position.get("_peak_price", entry), current)
        qty = position.get("quantity", 0)

        if entry <= 0 or qty <= 0:
            return {"status": "unknown", "stop_price": 0, "distance_pct": 0}

        profit_pct = (current - entry) / entry
        stop_loss_pct = abs(float(_RISK.get("stop_loss_pct", 0.08))) * 100
        hard_stop_price = entry * (1 - stop_loss_pct / 100)

        hold = hold_days(position.get("entry_date", ""))
        if hold is not None and hold < TRAILING_MIN_HOLD_DAYS:
            stop_price = round(hard_stop_price, 2)
            bucket = f"持仓<{TRAILING_MIN_HOLD_DAYS}天"
            rule = f"持仓{hold}天→硬止损{stop_loss_pct:.0f}%:成本{entry}×{-stop_loss_pct:.0f}%={stop_price}"
        else:
            trail_pct, tier = trailing_stop_threshold(profit_pct * 100)
            trail_stop_price = peak * (1 + trail_pct / 100)
            bucket = tier
            # 硬止损与 trailing 取更紧的一条（止损价更高者先触发）
            if hard_stop_price >= trail_stop_price:
                stop_price = round(hard_stop_price, 2)
                rule = (
                    f"盈利{profit_pct*100:.1f}%→{tier}:峰值{peak}×{1+trail_pct/100:.2f}="
                    f"{trail_stop_price:.2f}，硬止损{hard_stop_price:.2f}更紧"
                )
            else:
                stop_price = round(trail_stop_price, 2)
                rule = f"盈利{profit_pct*100:.1f}%→{tier}:峰值{peak}×{1+trail_pct/100:.2f}={stop_price}"

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
            "rule_description": rule,
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