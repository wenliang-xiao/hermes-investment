"""
strategies/silverquant.py — SilverQuant 策略纯决策函数

组件化风控：评分建仓 + 4层独立卖出组件。
"""
from __future__ import annotations

from .base import (
    Signal, PositionData, SilverQuantConfig,
    TRAILING_MIN_HOLD_DAYS, hold_days, trailing_stop_threshold,
)


def decide(
    score_map: dict[str, float],
    tech_map: dict[str, dict],
    price_map: dict[str, float],
    positions: dict[str, PositionData],
    cash: float,
    config: SilverQuantConfig | None = None,
) -> list[Signal]:
    """SilverQuant 策略决策函数。

    建仓：评分≥5.0，固定¥30K/槽位
    清仓：4层独立卖出组件，按优先级逐一检查
    """
    cfg = config or SilverQuantConfig()
    signals: list[Signal] = []
    held = set(positions.keys())

    # ─── 建仓 ───
    candidates = sorted(
        [s for s in score_map if s not in held],
        key=lambda s: score_map.get(s, 0), reverse=True
    )[:cfg.max_candidates]

    # 剩余可建仓槽位（含本轮已生成的 BUY，修复静态快照越界）
    slots_left = max(0, cfg.max_positions - len(positions))

    for sym in candidates:
        if slots_left <= 0:
            break
        score = score_map.get(sym, 0)
        if score < cfg.entry_threshold:
            continue
        price = price_map.get(sym, 0)
        if price <= 0:
            continue
        if cash < cfg.slot_amount:
            break  # 现金不足一个固定槽位
        # ADR-0005: 固定 ¥slot_amount/槽位（用当前现金折算成百分比）
        size_pct = round(min(100.0, cfg.slot_amount / cash * 100), 2)

        signals.append(Signal(
            symbol=sym, action="BUY", price=price,
            reason=f"槽位建仓(评分{score:.1f})",
            priority="MED", size_pct=size_pct, score=score,
        ))
        slots_left -= 1

    # ─── 清仓：4层卖出组件 ───
    for sym, pos in positions.items():
        price = price_map.get(sym, pos.current_price or pos.entry_price)
        if not price or price <= 0:
            continue
        score = score_map.get(sym, 0)
        entry = pos.entry_price
        peak = pos.peak or entry
        pnl_pct = (price - entry) / entry * 100
        dd = (price - peak) / peak * 100 if peak else 0

        # 1. HardSeller: ATR 自适应止损(高波动股更宽, 保底 -8%)
        tech = tech_map.get(sym, {})
        atr_pct = tech.get("atr_pct", 0) or 0
        stop_pct = -max(abs(cfg.hard_stop_loss_pct), 2 * atr_pct)
        if pnl_pct <= stop_pct:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"HardSeller({pnl_pct:.1f}%,ATR{atr_pct:.1f}%)", priority="HIGH",
                pnl_pct=pnl_pct, score=score,
            ))
            continue

        # 2. FallSeller: 四档 trailing（docs/STRATEGY.md §5.4）
        #    持仓满 TRAILING_MIN_HOLD_DAYS 天后启用；日期缺失时不放宽风控。
        hd = hold_days(pos.entry_date)
        if hd is None or hd >= TRAILING_MIN_HOLD_DAYS:
            trail_pct, tier = trailing_stop_threshold(pnl_pct)
            if dd <= trail_pct:
                signals.append(Signal(
                    symbol=sym, action="SELL", price=price,
                    reason=f"FallSeller({tier}{dd:.1f}%)", priority="HIGH",
                    pnl_pct=pnl_pct, score=score,
                ))
                continue

        # 3. MASeller: MA死叉(MA20<MA60 ⟺ ma20d>ma60d)，亏损未达-5%豁免
        tech = tech_map.get(sym, {})
        ma20d = tech.get("ma20_dev", 0) or 0
        ma60d = tech.get("ma60_dev", 0) or 0
        if ma20d > ma60d and pnl_pct > cfg.ma_sell_pnl_exemption:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason="MASeller(MA死叉)", priority="MED",
                pnl_pct=pnl_pct, score=score,
            ))
            continue

        # 4. ScoreDropSeller: 评分<4.5
        if score > 0 and score < cfg.score_drop_threshold:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"ScoreDrop({score:.1f})", priority="MED",
                pnl_pct=pnl_pct, score=score,
            ))

    return signals
