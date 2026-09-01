"""
面基投资系统 · EvidencePacket 统一证据数据结构

所有评分/信号/决策共享的结构化推理链。

架构位置：
  每个模块输出 → EvidenceBuilder.build() → EvidencePacket → Dashboard 前端

使用场景：
  - factor_engine 评分 → 每个 score 加 evidence 字段
  - macro_engine 状态 → 双门加 evidence 字段  
  - trading_engine 信号 → 每个信号加 evidence 字段
  - execution_checker 执行检查 → 建仓6查 + TrailStop 证据
"""
from datetime import datetime
from typing import Any, Optional
import json, logging

logger = logging.getLogger(__name__)


class EvidenceStep:
    """推理链中的一步"""
    def __init__(self, order: int, label: str, data: dict, rationale: str, source: str,
                 status: str = "ok", warning: Optional[str] = None):
        self.order = order
        self.label = label
        self.data = data
        self.rationale = rationale
        self.source = source
        self.status = status          # ok / warning / missing / error
        self.warning = warning

    def to_dict(self) -> dict:
        return {
            "order": self.order,
            "label": self.label,
            "data": self.data,
            "rationale": self.rationale,
            "source": self.source,
            "status": self.status,
            "warning": self.warning,
        }


class EvidencePacket:
    """
    统一证据包 — 每个评分/信号/决策的推理全貌。

    7步证据链（典型顺序）:
      ① 数据层 — 来源新鲜度
      ② 因子层 — 19子→8风格→综合
      ③ 信号层 — 阈值对比+判定
      ④ 策略层 — 三策略裁决+冲突解决
      ⑤ 执行层 — 双门+建仓6查+TrailStop
      ⑥ 验证层 — 历史类似信号准确率
      ⑦ 归因层 — 收益亏损因子分解
    """
    def __init__(self, claim: str, confidence: float, chain: list[EvidenceStep],
                 why_high: Optional[list[str]] = None,
                 why_low: Optional[list[str]] = None,
                 alternatives: Optional[list[dict]] = None,
                 unknowns: Optional[list[str]] = None,
                 verify_plan: Optional[str] = None,
                 data_quality: float = 1.0,
                 data_dependency: Optional[list[dict]] = None,
                 timestamp: Optional[str] = None):
        self.claim = claim
        self.confidence = round(confidence, 4)
        self.chain = sorted(chain, key=lambda s: s.order)
        self.why_high = why_high or []
        self.why_low = why_low or []
        self.alternatives = alternatives or []
        self.unknowns = unknowns or []
        self.verify_plan = verify_plan or ""
        self.data_quality = round(data_quality, 4)
        self.data_dependency = data_dependency or []
        self.timestamp = timestamp or datetime.now().strftime("%Y-%m-%d %H:%M")

    def to_dict(self) -> dict:
        return {
            "claim": self.claim,
            "confidence": self.confidence,
            "chain": [s.to_dict() for s in self.chain],
            "chain_count": len(self.chain),
            "why_high": self.why_high,
            "why_low": self.why_low,
            "alternatives": self.alternatives,
            "unknowns": self.unknowns,
            "verify_plan": self.verify_plan,
            "data_quality": self.data_quality,
            "data_dependency": self.data_dependency,
            "timestamp": self.timestamp,
        }

    def to_json(self, indent=2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


class EvidenceBuilder:
    """
    证据包组装器 — 从多个模块的数据组装成统一 EvidencePacket。

    输入可能来自：
      - FactorEngine.score_batch()  → score_data
      - MacroEngine.to_dict()       → macro_state
      - trading_engine 执行状态     → position / decision
      - chain_scanner               → chain_data
    """

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.EvidenceBuilder")

    def build(self, symbol: str, score_data: Optional[dict] = None,
              macro_state: Optional[dict] = None,
              position: Optional[dict] = None,
              chain_data: Optional[dict] = None,
              signal_result: Optional[dict] = None) -> EvidencePacket:
        """
        组装单个标的的完整证据包。

        参数:
            symbol:      标的代码
            score_data:  FactorEngine.score_batch() 的单个结果项
            macro_state: MacroEngine.to_dict() 输出
            position:    持仓信息（如果有）
            chain_data:  链定位数据（可选）
            signal_result: 信号判定结果（可选）

        返回:
            EvidencePacket（7步链+置信度+替代方案）
        """
        chain: list[EvidenceStep] = []
        sources: list[dict] = []

        # ① 数据层
        chain.append(self._data_quality_step(symbol, score_data))
        sources.append(self._source_info("baostock", score_data))

        # ② 因子层
        chain.append(self._factor_step(symbol, score_data))
        sources.append(self._source_info("factor_engine", score_data))

        # ③ 信号层
        chain.append(self._signal_step(score_data, signal_result))

        # ④ 策略层 — 仅当有策略裁决时
        if signal_result and signal_result.get("strategy"):
            chain.append(self._strategy_step(signal_result))

        # ⑤ 执行层
        chain.append(self._execution_step(macro_state, position))

        # ⑥ 验证层
        chain.append(self._verification_step(symbol, score_data))

        # ⑦ 归因层 — 仅当有持仓
        if position:
            chain.append(self._attribution_step(position, score_data))

        # 提取 why_high / why_low
        why_high = self._extract_why_high(chain, score_data)
        why_low = self._extract_why_low(chain, score_data)

        # 替代方案
        alternatives = score_data.get("alternatives", []) if score_data else []

        # 未知领域
        unknowns = self._detect_unknowns(symbol, score_data, position)

        # 数据质量
        dq = self._calc_data_quality(chain)

        # 验证计划
        verify = self._build_verify_plan(symbol, score_data)

        # 置信度
        confidence = self._calc_confidence(chain, score_data)

        # 结论
        claim = self._build_claim(symbol, confidence, score_data, position)

        return EvidencePacket(
            claim=claim,
            confidence=confidence,
            chain=chain,
            why_high=why_high,
            why_low=why_low,
            alternatives=alternatives,
            unknowns=unknowns,
            verify_plan=verify,
            data_quality=dq,
            data_dependency=sources,
        )

    # ── 各步构建 ──

    def _data_quality_step(self, symbol: str, score_data: Optional[dict]) -> EvidenceStep:
        if score_data and score_data.get("data_quality"):
            dq = score_data["data_quality"]
            financial_age = dq.get("financial_age_days")
            price_age = dq.get("price_age_days")
            has_data = dq.get("has_data", False)
            parts = []
            if price_age is not None:
                parts.append(f"日线{price_age}天前")
            if financial_age is not None:
                parts.append(f"财报{'可用' if has_data else '暂缺'}")
            rationale = "数据正常" if has_data else "缺少历史数据"
            if price_age is not None and price_age > 30:
                rationale = f"日线数据已过期{price_age}天"
            return EvidenceStep(
                order=1, label="数据层",
                data={"has_data": has_data, "price_age_days": price_age,
                      "financial_age_days": financial_age},
                rationale=rationale,
                source="data_router",
                status="warning" if (price_age or 0) > 30 else "ok",
                warning=f"日线{price_age}天前" if (price_age or 0) > 30 else None,
            )
        return EvidenceStep(order=1, label="数据层", data={},
                            rationale="无评分数据", source="N/A",
                            status="missing", warning="无评分数据")

    def _factor_step(self, symbol: str, score_data: Optional[dict]) -> EvidenceStep:
        if score_data and score_data.get("scores"):
            scores = score_data["scores"]
            composite = score_data.get("composite", 0)
            high = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
            low = sorted(scores.items(), key=lambda x: x[1])[:3]
            return EvidenceStep(
                order=2, label="因子层",
                data={"composite": composite, "scores": scores,
                      "factor_breakdown": score_data.get("factor_breakdown", {}),
                      "weights": score_data.get("weights_used", {})},
                rationale=f"综合分{composite:.2f}, 最强因子:{high[0][0]}={high[0][1]:.2f}",
                source="factor_engine",
            )
        return EvidenceStep(order=2, label="因子层", data={},
                            rationale="无因子数据", source="N/A", status="missing")

    def _signal_step(self, score_data: Optional[dict],
                     signal_result: Optional[dict]) -> EvidenceStep:
        if signal_result:
            action = signal_result.get("action", "")
            thresholds = signal_result.get("thresholds", {})
            return EvidenceStep(
                order=3, label="信号层",
                data={"action": action, "thresholds": thresholds,
                      "score": signal_result.get("score")},
                rationale=f"score→{action}(阈值:{thresholds})",
                source="trading_engine",
            )
        # fallback: 从composite推断
        composite = (score_data or {}).get("composite", 0)
        if isinstance(composite, (int, float)):
            if composite >= 0.7:
                action = "BUY"
            elif composite >= 0.55:
                action = "HOLD"
            else:
                action = "SELL" if composite < 0.4 else "HOLD"
            return EvidenceStep(
                order=3, label="信号层",
                data={"action": action, "composite": composite},
                rationale=f"composite={composite:.2f}→{action}(默认阈值)",
                source="evidence_builder(inferred)",
            )
        return EvidenceStep(order=3, label="信号层", data={},
                            rationale="无评分数据", source="N/A", status="missing")

    def _strategy_step(self, signal_result: dict) -> EvidenceStep:
        return EvidenceStep(
            order=4, label="策略层",
            data={"strategy": signal_result.get("strategy", ""),
                  "strategy_reason": signal_result.get("reason", ""),
                  "conflicts": signal_result.get("conflicts", [])},
            rationale=f"策略裁决: {signal_result.get('strategy', 'N/A')}",
            source="trading_engine",
        )

    def _execution_step(self, macro_state: Optional[dict],
                        position: Optional[dict]) -> EvidenceStep:
        data = {}
        parts = []
        if macro_state:
            dg = macro_state.get("dual_gate", {})
            data["dual_gate"] = dg
            parts.append(f"双门:{dg.get('macro','?')}/{dg.get('trend','?')}")
        if position:
            data["position_size"] = position.get("quantity", 0)
            parts.append(f"持仓:{position.get('quantity', 0)}股")
        return EvidenceStep(
            order=5, label="执行层",
            data=data,
            rationale="; ".join(parts) if parts else "未见明显限制",
            source="macro_engine" if macro_state else "portfolio",
        )

    def _verification_step(self, symbol: str, score_data: Optional[dict]) -> EvidenceStep:
        return EvidenceStep(
            order=6, label="验证层",
            data={"symbol": symbol},
            rationale="尚无历史验证数据（需积累信号后回查）",
            source="signal_validator(not_yet_run)",
            status="missing",
            warning="需积累3天以上信号才能验证",
        )

    def _attribution_step(self, position: dict, score_data: Optional[dict]) -> EvidenceStep:
        return EvidenceStep(
            order=7, label="归因层",
            data={"pnl": position.get("pnl", 0),
                  "entry_price": position.get("entry_price", 0),
                  "current_price": position.get("current_price", 0)},
            rationale="归因分解待实现(Brinson归因需更多持仓数据)",
            source="portfolio",
            status="warning",
            warning="Brinson归因为P1功能",
        )

    # ── 提取辅助 ──

    def _extract_why_high(self, chain: list[EvidenceStep],
                          score_data: Optional[dict]) -> list[str]:
        lines = []
        # 从因子层提取TOP因子
        for step in chain:
            if step.label == "因子层" and step.data:
                scores = step.data.get("scores", {})
                if scores:
                    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:2]
                    for name, val in top:
                        rf = {"quality": "质量", "value": "价值", "momentum": "动量",
                              "growth": "成长", "low_vol": "低波", "dividend": "股息",
                              "sentiment": "情绪", "risk": "风险"}.get(name, name)
                        val = 0.0 if abs(val) < 0.005 else val
                        lines.append(f"{rf}={val:.2f}")
        # 从双门提取
        for step in chain:
            if step.label == "执行层" and step.data.get("dual_gate"):
                dg = step.data["dual_gate"]
                if dg.get("macro") in ("绿灯", "绿"):
                    lines.append("宏观双门绿灯")
                if dg.get("trend") in ("绿灯", "绿"):
                    lines.append("趋势双门绿灯")
        return lines[:5]

    def _extract_why_low(self, chain: list[EvidenceStep],
                         score_data: Optional[dict]) -> list[str]:
        lines = []
        for step in chain:
            if step.label == "因子层" and step.data:
                scores = step.data.get("scores", {})
                if scores:
                    bottom = sorted(scores.items(), key=lambda x: x[1])[:2]
                    for name, val in bottom:
                        rf = {"quality": "质量", "value": "价值", "momentum": "动量",
                              "growth": "成长", "low_vol": "低波", "dividend": "股息",
                              "sentiment": "情绪", "risk": "风险"}.get(name, name)
                        val = 0.0 if abs(val) < 0.005 else val
                        lines.append(f"{rf}={val:.2f}")
        return lines[:3]

    def _detect_unknowns(self, symbol: str, score_data: Optional[dict],
                         position: Optional[dict]) -> list[str]:
        unknowns = []
        if not score_data:
            unknowns.append(f"{symbol}未评分")
        else:
            dq = score_data.get("data_quality", {})
            if dq.get("financial_age_days") is None:
                unknowns.append("最新财报尚未获取")
            if dq.get("price_age_days") is not None and dq["price_age_days"] > 7:
                unknowns.append(f"日线数据已{dq['price_age_days']}天未更新")
        return unknowns

    def _calc_data_quality(self, chain: list[EvidenceStep]) -> float:
        """基于所有链步骤的状态计算综合数据质量"""
        if not chain:
            return 0.5
        statuses = [s.status for s in chain]
        ok_ratio = sum(1 for s in statuses if s == "ok") / len(statuses)
        warning_ratio = sum(1 for s in statuses if s == "warning") / len(statuses)
        return min(1.0, ok_ratio + warning_ratio * 0.6)

    def _calc_confidence(self, chain: list[EvidenceStep],
                         score_data: Optional[dict]) -> float:
        """置信度 = 链完整度 × 数据质量 × 评分偏离度"""
        # 链完整度
        completed = sum(1 for s in chain if s.status != "missing")
        total = max(len(chain), 1)
        completeness = completed / total
        # 数据质量
        dq_score = self._calc_data_quality(chain)
        # 评分偏离度（越极端越自信）
        composite = (score_data or {}).get("composite", 0.5)
        if isinstance(composite, (int, float)):
            deviation = abs(composite - 0.5) * 2  # 0→0, 1→1
        else:
            deviation = 0.5
        confidence = 0.4 * completeness + 0.4 * dq_score + 0.2 * deviation
        return max(0.0, min(1.0, confidence))

    def _build_verify_plan(self, symbol: str, score_data: Optional[dict]) -> str:
        if not score_data:
            return "暂无评分数据"
        composite = score_data.get("composite", 0)
        if isinstance(composite, (int, float)) and composite >= 0.7:
            return f"{symbol} 强度>0.7 → 3天后回查方向正确性"
        elif isinstance(composite, (int, float)) and composite < 0.4:
            return f"{symbol} 强度<0.4 → 7天后回查是否止跌"
        return f"{symbol} 5天后回查"

    def _build_claim(self, symbol: str, confidence: float,
                     score_data: Optional[dict],
                     position: Optional[dict]) -> str:
        if position:
            return f"{symbol} 持仓·置信度{confidence:.2f}"
        composite = (score_data or {}).get("composite", 0)
        if isinstance(composite, (int, float)):
            if composite >= 0.7:
                return f"{symbol} 评分{composite:.2f}·偏强(置信度{confidence:.2f})"
            elif composite >= 0.55:
                return f"{symbol} 评分{composite:.2f}·中性(置信度{confidence:.2f})"
            else:
                return f"{symbol} 评分{composite:.2f}·偏弱(置信度{confidence:.2f})"
        return f"{symbol} (置信度{confidence:.2f})"

    def _source_info(self, name: str, score_data: Optional[dict]) -> dict:
        info = {"source": name, "freshness": "unknown", "last_update": None}
        if score_data and score_data.get("date"):
            info["last_update"] = score_data["date"]
            info["freshness"] = "fresh"
        return info


# ── 便捷函数 ──

def build_evidence_from_score(symbol: str, score_item: dict) -> dict:
    """快速从单条评分构建证据包（最常用的场景）"""
    builder = EvidenceBuilder()
    packet = builder.build(symbol, score_data=score_item)
    return packet.to_dict()


def batch_evidence_from_scores(scores: list[dict]) -> list[dict]:
    """从批量评分结果列表构建证据包"""
    builder = EvidenceBuilder()
    results = []
    for item in scores:
        sym = item.get("symbol", "")
        if sym:
            packet = builder.build(sym, score_data=item)
            results.append(packet.to_dict())
    return results
