"""
面基组合构建器 + 执行引擎 (OpenSpec Phase 2)
==============================================
Layer 2: 将多维因子分 → 三策略各自目标仓位
Layer 3: 交易纪律检查 + 信号生成

设计原则:
  - 与现有 trading_engine.py 并行 (只叠加不拆除)
  - 纯函数 + 固定评估器 (hl-quant 范式)
  - 所有策略共享因子引擎输出

依赖:
  - factor_engine.py (Layer 1)
  - stop_list.py (不为清单)
"""

import json, os, logging, sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# Path setup for dual-mode imports
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)
_PARENT_DIR = os.path.dirname(_PROJECT_DIR)
if _PARENT_DIR not in sys.path:
    sys.path.insert(0, _PARENT_DIR)

# ═══════════════════════════════════════════════
# 全局约束 (OpenSpec Section 4.1)
# ═══════════════════════════════════════════════

PORTFOLIO_CONSTRAINTS = {
    "max_positions": 8,              # 最大持仓数
    "max_single_weight": 0.15,       # 单标的最大权重
    "min_single_weight": 0.02,       # 单标的最小权重 (太小无意义)
    "max_sector_exposure": 0.35,     # 单行业最大暴露
    "max_turnover": 0.15,            # 单日最大换手率
    "min_cash_reserve": 0.15,        # 最低现金留存
    "target_volatility": 0.20,       # 目标年化波动
    "max_volatility": 0.28,          # 最大年化波动
}


@dataclass
class TargetPosition:
    """目标仓位"""
    symbol: str
    name: str = ""
    weight: float = 0.0           # 目标权重 [0, 1]
    reason: str = ""               # 建仓/清仓理由
    kelly_fraction: float = 0.0   # Kelly建议仓位


@dataclass
class Signal:
    """可执行信号"""
    strategy: str                  # faceji / silverquant / tradingagents
    action: str                    # BUY / SELL / HOLD
    symbol: str
    name: str = ""
    price: float = 0.0
    score: float = 0.0
    size_pct: float = 0.0         # 仓位百分比
    reason: str = ""
    priority: str = "normal"      # high / normal / low

    # 4层风控 (SQ风控)
    hard_sell: bool = False       # -8%止损
    fall_sell: bool = False       # -12%峰值回落
    score_drop: bool = False      # 评分跌穿
    ma_sell: bool = False         # MA死叉


# ═══════════════════════════════════════════════
# 全局约束检查
# ═══════════════════════════════════════════════

def check_constraints(targets: list[TargetPosition],
                       current_positions: dict) -> tuple[list[TargetPosition], list[str]]:
    """
    检查全局约束，返回 (通过的目标, 违反约束列表)
    """
    violations = []

    # 1. 最大持仓数
    if len(targets) > PORTFOLIO_CONSTRAINTS["max_positions"]:
        violations.append(f"持仓数{len(targets)}超过上限{PORTFOLIO_CONSTRAINTS['max_positions']}")
        targets = targets[:PORTFOLIO_CONSTRAINTS["max_positions"]]

    # 2. 单个权重上限
    for t in targets:
        if t.weight > PORTFOLIO_CONSTRAINTS["max_single_weight"]:
            violations.append(f"{t.symbol}权重{t.weight:.1%}超过上限{PORTFOLIO_CONSTRAINTS['max_single_weight']:.0%}")
            t.weight = PORTFOLIO_CONSTRAINTS["max_single_weight"]

    # 3. 行业集中度
    # (需要行业映射，暂略 — 用 symbol 前缀近似)
    sector_map = _guess_sector(targets)
    for sector, syms in sector_map.items():
        total_w = sum(t.weight for t in targets if t.symbol in syms)
        if total_w > PORTFOLIO_CONSTRAINTS["max_sector_exposure"]:
            violations.append(f"行业{sector}权重{total_w:.1%}超过上限{PORTFOLIO_CONSTRAINTS['max_sector_exposure']:.0%}")

    # 4. 现金留存
    total_weight = sum(t.weight for t in targets)
    if total_weight > 1 - PORTFOLIO_CONSTRAINTS["min_cash_reserve"]:
        violations.append(f"总权重{total_weight:.1%}超过现金留存限制")
        # 等比压缩
        max_allowed = 1 - PORTFOLIO_CONSTRAINTS["min_cash_reserve"]
        scale = max_allowed / total_weight if total_weight > 0 else 1
        for t in targets:
            t.weight *= scale

    # 5. 最低权重过滤
    targets = [t for t in targets if t.weight >= PORTFOLIO_CONSTRAINTS["min_single_weight"]]

    return targets, violations


def _guess_sector(targets: list[TargetPosition]) -> dict:
    """简易行业猜测 — 基于代码前缀"""
    from domain.stock_universe import LDS_SECTORS
    mapping = {}
    for sector, syms in LDS_SECTORS.items():
        for s in syms:
            mapping[s] = sector
    result = {}
    for t in targets:
        sec = mapping.get(t.symbol, "其他")
        result.setdefault(sec, set()).add(t.symbol)
    return result


# ═══════════════════════════════════════════════
# 面基策略组合器 (OpenSpec 4.2)
# ═══════════════════════════════════════════════

def faceji_portfolio(scored_items: list[dict],
                     current_positions: dict = None,
                     macro_state: str = "扩张期",
                     cash_reserve: float = 0.3) -> list[TargetPosition]:
    """
    面基策略: 质量/价值/成长三因子等权 + MA过滤 + Kelly仓位

    Args:
        scored_items: factor_engine 输出的多维分数列表
        current_positions: {symbol: {cost, shares, ...}}
        macro_state: 当前宏观状态

    Returns:
        [TargetPosition, ...] 按综合分降序
    """
    targets = []
    for item in scored_items:
        scores = item.get("scores", {})
        composite = item.get("composite", 0)

        # 建仓条件: composite >= 0.50
        if composite < 0.50:
            continue

        # MA过滤
        tech_ok = _check_ma_filter(item.get("symbol", ""))
        if not tech_ok:
            continue

        # 不为清单
        if not _pass_stoplist(item):
            continue

        # 核心分 = 质量/价值/成长三因子等权
        core_score = np.mean([scores.get("quality", 0),
                              scores.get("value", 0),
                              scores.get("growth", 0)])

        # Kelly仓位 (max 8%)
        kelly = _calc_kelly(core_score, composite)
        weight = min(kelly, PORTFOLIO_CONSTRAINTS["max_single_weight"])

        # 宏观调仓
        if macro_state in ("衰退期",):
            weight *= 0.6

        target = TargetPosition(
            symbol=item.get("symbol", ""),
            name=item.get("name", ""),
            weight=round(weight, 4),
            reason=f"核心{core_score:.3f} 综合{composite:.3f} kelly_{kelly:.1%}",
            kelly_fraction=kelly,
        )
        targets.append(target)

    targets.sort(key=lambda t: t.weight, reverse=True)
    targets, _ = check_constraints(targets, current_positions or {})
    return targets


# ═══════════════════════════════════════════════
# SilverQuant 组合器 (OpenSpec 4.3)
# ═══════════════════════════════════════════════

def silverquant_portfolio(scored_items: list[dict],
                          current_positions: dict = None) -> list[TargetPosition]:
    """
    SilverQuant: 评分≥0.50 + 固定¥30K/槽位 + 无MA过滤

    4层风控在 execution_agent 中做
    """
    SLOT_SIZE = 0.03  # 每个槽位 3% (= ¥30K / ¥100万)
    MAX_SLOTS = 8

    candidates = [item for item in scored_items
                  if item.get("composite", 0) >= 0.50]

    candidates.sort(key=lambda x: x["composite"], reverse=True)
    candidates = candidates[:MAX_SLOTS]

    targets = []
    for item in candidates:
        if not _pass_stoplist(item):
            continue
        targets.append(TargetPosition(
            symbol=item.get("symbol", ""),
            name=item.get("name", ""),
            weight=SLOT_SIZE,
            reason=f"SQslot composite={item['composite']:.3f}",
        ))

    targets, _ = check_constraints(targets, current_positions or {})
    return targets


# ═══════════════════════════════════════════════
# TradingAgents 组合器 (OpenSpec 4.4)
# ═══════════════════════════════════════════════

def tradingagents_portfolio(scored_items: list[dict],
                            current_positions: dict = None,
                            macro_state: str = "扩张期") -> list[TargetPosition]:
    """
    TradingAgents: 辩论制评分 + Kelly仓位 (max 12%)

    模拟三辩论角色: bull/bear/neutral
    """
    candidates = [item for item in scored_items
                  if item.get("composite", 0) >= 0.50]
    candidates.sort(key=lambda x: x["composite"], reverse=True)

    targets = []
    for item in candidates[:6]:
        if not _pass_stoplist(item):
            continue

        scores = item.get("scores", {})
        c = item["composite"]

        # 模拟辩论: 三角色不同视角
        bull_score = c * 1.15  # 乐观
        bear_score = c * 0.85  # 悲观
        neutral_score = c * 1.0  # 中性
        debate_score = np.mean([bull_score, bear_score, neutral_score])

        if debate_score < 0.55:
            continue

        # Kelly
        kelly = _calc_kelly(debate_score, c, max_fraction=0.12)
        weight = min(kelly, 0.12)

        if macro_state in ("衰退期",):
            weight *= 0.5

        targets.append(TargetPosition(
            symbol=item.get("symbol", ""),
            name=item.get("name", ""),
            weight=round(weight, 4),
            reason=f"debate={debate_score:.3f} composite={c:.3f}",
            kelly_fraction=kelly,
        ))

    targets.sort(key=lambda t: t.weight, reverse=True)
    targets, _ = check_constraints(targets, current_positions or {})
    return targets


# ═══════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════

def _calc_kelly(score: float, composite: float,
                max_fraction: float = 0.08,
                win_prob: float = 0.55) -> float:
    """
    Kelly仓位计算

    Args:
        score: 策略核心分 [0,1]
        composite: 综合分 [0,1]
        max_fraction: 最大仓位
        win_prob: 先验胜率

    Returns:
        kelly_fraction [0, max_fraction]
    """
    # 赔率从评分推算
    odds = 1.0 + score * 2.0
    kelly = (win_prob * odds - (1 - win_prob)) / odds
    kelly = max(0, min(kelly, 1.0))
    # 综合分衰减
    kelly *= composite
    return min(kelly, max_fraction)


def _check_ma_filter(symbol: str) -> bool:
    """MA过滤: MA20 > MA60 表示趋势向上。请求120天确保有60个交易日。"""
    try:
        from data.data_router import get_history
        h = get_history(symbol, 120)
        if not h or "close" not in h or len(h["close"]) < 40:
            return True
        close = h["close"]
        ma20 = np.mean(close[-20:])
        if len(close) >= 60:
            ma60 = np.mean(close[-60:])
        else:
            ma60 = ma20  # 数据不足时通过
        return ma20 > ma60
    except Exception:
        return True


def _pass_stoplist(item: dict) -> bool:
    """简易不为清单检查"""
    try:
        from analysis.stop_list import StopListFilter
        sf = StopListFilter()
        result = sf.apply(item)
        if isinstance(result, dict):
            return result.get("passed", True)
        return bool(result)
    except Exception:
        return True


# ═══════════════════════════════════════════════
# 执行引擎 (ExecutionAgent)
# ═══════════════════════════════════════════════

class ExecutionAgent:
    """
    执行引擎 (OpenSpec Section 5)
    职责: Signal生成 + 交易纪律检查 + 止损/止盈 + 不为清单
    """

    def __init__(self, strategy: str = "faceji",
                 slot_size: float = 30000.0,
                 total_capital: float = 1000000.0):
        self.strategy = strategy
        self.slot_size = slot_size
        self.total_capital = total_capital

    def generate_signals(self,
                         targets: list[TargetPosition],
                         current_positions: dict[str, dict],
                         current_prices: dict[str, float],
                         macro_state: str = "扩张期") -> list[Signal]:
        """
        对比当前持仓 vs 目标仓位 → 信号列表

        Args:
            targets: 组合构建器输出的目标仓位
            current_positions: {symbol: {shares, avg_cost, ...}}
            current_prices: {symbol: price}
            macro_state: 当前宏观状态

        Returns:
            [Signal, ...]
        """
        signals = []

        # 1. 现有持仓中要清仓的
        current_symbols = set(current_positions.keys())
        target_symbols = {t.symbol for t in targets}

        for sym in current_symbols:
            if sym not in target_symbols:
                pos = current_positions[sym]
                price = current_prices.get(sym, pos.get("avg_cost", 0))
                # 检查止损
                hard_sell, fall_sell = self._check_stop_loss(pos, price)

                signals.append(Signal(
                    strategy=self.strategy,
                    action="SELL",
                    symbol=sym,
                    name=pos.get("name", sym),
                    price=price,
                    size_pct=0,
                    reason="移出目标池",
                    hard_sell=hard_sell,
                    fall_sell=fall_sell,
                    priority="high" if hard_sell or fall_sell else "normal",
                ))

        # 2. 目标持仓中要建的
        for t in targets:
            if t.symbol in current_symbols:
                # 已有持仓 → 检查是否需要调整
                pos = current_positions[t.symbol]
                current_weight = pos.get("current_weight", 0)
                delta = t.weight - current_weight
                if abs(delta) > 0.01:  # 1%以上才调
                    signals.append(Signal(
                        strategy=self.strategy,
                        action="BUY" if delta > 0 else "SELL",
                        symbol=t.symbol,
                        name=t.name,
                        price=current_prices.get(t.symbol, 0),
                        score=t.kelly_fraction,
                        size_pct=abs(delta),
                        reason=t.reason,
                    ))
            else:
                # 新建仓
                price = current_prices.get(t.symbol, 0)
                signals.append(Signal(
                    strategy=self.strategy,
                    action="BUY",
                    symbol=t.symbol,
                    name=t.name,
                    price=price,
                    score=t.kelly_fraction,
                    size_pct=t.weight,
                    reason=t.reason,
                ))

        # 3. 交易纪律检查
        signals = self._check_discipline(signals, macro_state)

        return signals

    def _check_stop_loss(self, position: dict, current_price: float) -> tuple[bool, bool]:
        """4层SQ风控: hard_sell(-8%), fall_sell(-12%)"""
        avg_cost = position.get("avg_cost", 0)
        if avg_cost <= 0:
            return False, False

        pnl_pct = (current_price - avg_cost) / avg_cost
        peak_price = position.get("peak_price", avg_cost)
        peak_dd = (current_price - peak_price) / peak_price if peak_price > 0 else 0

        hard_sell = pnl_pct <= -0.08
        fall_sell = peak_dd <= -0.12

        return hard_sell, fall_sell

    def _check_discipline(self, signals: list[Signal],
                          macro_state: str) -> list[Signal]:
        """
        交易纪律检查:
        - 宏观风控: 衰退期SELL可, BUY仅限最高质量
        - 高频过滤: 同标的同日内不重复BUY
        """
        filtered = []
        seen_buy = set()

        for s in signals:
            # 宏观风控
            if s.action == "BUY" and macro_state == "衰退期" and s.score < 0.6:
                s.reason += " [宏观风控拦截]"
                continue

            # 同标的日内只允许一个反向信号
            if s.action == "BUY":
                if s.symbol in seen_buy:
                    continue
                seen_buy.add(s.symbol)

            filtered.append(s)

        return filtered


# ═══════════════════════════════════════════════
# 一键管线: FactorEngine → PortfolioBuilder → ExecutionAgent
# ═══════════════════════════════════════════════

def run_full_pipeline(symbols: list[str],
                      strategy: str = "faceji",
                      macro_state: str = "扩张期",
                      current_positions: dict = None,
                      current_prices: dict = None) -> dict:
    """
    全流程: 因子评分 → 组合构建 → 信号生成

    Returns:
        {
            "scored_items": [...],       # 因子引擎输出
            "targets": [...],            # 目标仓位
            "signals": [...],            # 可执行信号
            "constraints": [...],        # 约束检查
        }
    """
    from analysis.factor_engine import FactorEngine

    # Phase 1: 因子评分
    engine = FactorEngine()
    scored = engine.score_batch(symbols, macro_state=macro_state)

    # Phase 2: 组合构建
    if strategy == "faceji":
        targets = faceji_portfolio(scored, current_positions, macro_state)
    elif strategy == "silverquant":
        targets = silverquant_portfolio(scored, current_positions)
    elif strategy == "tradingagents":
        targets = tradingagents_portfolio(scored, current_positions, macro_state)
    else:
        raise ValueError(f"Unknown strategy: {strategy}")

    # Phase 3: 执行引擎
    agent = ExecutionAgent(strategy=strategy)
    signals = agent.generate_signals(targets, current_positions or {},
                                     current_prices or {}, macro_state)

    return {
        "scored_items": scored,
        "targets": [asdict(t) for t in targets],
        "signals": [asdict(s) for s in signals],
    }


# ═══════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    symbols = sys.argv[1].split(",") if len(sys.argv) > 1 else [
        "300502", "688041", "688008", "002371", "603259", "688256",
        "600519", "000858", "300750", "002594", "000333", "002415",
    ]
    strategy = sys.argv[2] if len(sys.argv) > 2 else "faceji"

    result = run_full_pipeline(symbols, strategy=strategy)
    print(f"=== 面基 {strategy} 管线输出 ===")
    print(f"评分标的: {len(result['scored_items'])}")
    print(f"目标仓位: {len(result['targets'])}")
    print(f"生成信号: {len(result['signals'])}")
    print()
    if result["targets"]:
        print(f"{'代码':<8} {'权重%':<8} {'理由'}")
        print("-" * 50)
        for t in result["targets"]:
            print(f"{t['symbol']:<8} {t['weight']*100:<8.1f} {t['reason'][:40]}")
    print()
    if result["signals"]:
        print(f"{'方向':<6} {'代码':<8} {'仓位%':<8} {'理由'}")
        print("-" * 50)
        for s in result["signals"][:10]:
            print(f"{s['action']:<6} {s['symbol']:<8} {s['size_pct']*100:<8.1f} {s['reason'][:40]}")
