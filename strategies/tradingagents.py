"""
strategies/tradingagents.py — TradingAgents 策略纯决策函数

辩论制：bull/bear/neutral 三角色评分 + Kelly动态仓位。
"""
from __future__ import annotations

from .base import Signal, PositionData, TradingAgentsConfig


def _debate_score(score: float, tech: dict | None, cfg: TradingAgentsConfig) -> float:
    """辩论裁决：bull / bear / neutral 三角色加权"""
    sc = score or 5.0
    ts = tech.get("total_tech_score", 5.0) if tech else 5.0
    bull = sc * 0.5 + ts * 0.5

    bp = 0.0
    if tech and tech.get("macd_signal", "") in ("死叉", "🔴死叉"):
        bp += 1.0
    if tech and (tech.get("rsi", 50) or 50) > 70:
        bp += 0.5
    bear = sc - bp
    neut = sc

    if bull >= bear and bull >= neut:
        final = bull * 0.6 + neut * 0.3 + bear * 0.1
    elif bear >= bull and bear >= neut:
        final = bear * 0.5 + neut * 0.3 + bull * 0.2
    else:
        final = neut

    return min(10, max(0, final))


def decide(
    score_map: dict[str, float],
    tech_map: dict[str, dict],
    price_map: dict[str, float],
    positions: dict[str, PositionData],
    cash: float,
    config: TradingAgentsConfig | None = None,
) -> list[Signal]:
    """TradingAgents 策略决策函数。

    建仓：全市场辩论分TOP3 + 辩论分≥5.5 + Kelly动态仓位
    清仓：辩论分强卖(<4.0) / 硬止损(-8%) / 弱持仓(<5.0+亏损)
    """
    cfg = config or TradingAgentsConfig()
    signals: list[Signal] = []
    held = set(positions.keys())

    # 预先计算辩论分
    debate: dict[str, float] = {}
    for sym in score_map:
        debate[sym] = _debate_score(
            score_map.get(sym, 5.0), tech_map.get(sym, {}), cfg
        )

    # ─── 建仓 ───
    candidates = sorted(
        [(s, debate[s]) for s in score_map if s not in held],
        key=lambda x: x[1], reverse=True
    )[:cfg.max_candidates]

    for sym, ds in candidates:
        if len(positions) >= cfg.max_positions:
            break
        if ds < cfg.debate_entry_threshold:
            continue
        price = price_map.get(sym, 0)
        if price <= 0:
            continue

        # Kelly 仓位
        wp = min(ds / 10.0, 0.8)
        kelly = max(0, (wp * cfg.kelly_odds - (1 - wp)) / cfg.kelly_odds)
        kelly = kelly * cfg.kelly_fraction
        size_pct = min(kelly, cfg.max_position_pct) * 100

        signals.append(Signal(
            symbol=sym, action="BUY", price=price,
            reason=f"辩论分{ds:.1f}(bull优先)",
            priority="HIGH" if ds >= 6.0 else "MED",
            size_pct=round(size_pct, 1),
            score=round(ds, 1),
        ))

    # ─── 清仓 ───
    for sym, pos in positions.items():
        price = price_map.get(sym, pos.current_price or pos.entry_price)
        ds = debate.get(sym, 5.0)
        entry = pos.entry_price
        pnl_pct = (price - entry) / entry * 100

        # 1. 辩论分强卖
        if ds < cfg.debate_force_sell:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"辩论分{ds:.1f}<{cfg.debate_force_sell}",
                priority="HIGH", pnl_pct=pnl_pct, score=round(ds, 1),
            ))
            continue

        # 2. 硬止损
        if pnl_pct <= cfg.hard_stop_loss_pct:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"止损{pnl_pct:.1f}%",
                priority="HIGH", pnl_pct=pnl_pct, score=round(ds, 1),
            ))
            continue

        # 3. 弱持仓
        if ds < cfg.debate_weak_sell and pnl_pct < 0:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"辩论分{ds:.1f}+亏损",
                priority="MED", pnl_pct=pnl_pct, score=round(ds, 1),
            ))

    return signals
