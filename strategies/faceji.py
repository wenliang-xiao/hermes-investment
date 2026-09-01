"""
strategies/faceji.py — 面基策略纯决策函数

从 analysis/trading_engine.py FacejiStrategy.daily_step() 提取，
去掉所有 IO 和状态突变，输出与原始 daily_step() 一致。
"""
from __future__ import annotations

from .base import Signal, PositionData, FacejiConfig


def _kelly_size(score: float, cfg: FacejiConfig) -> float:
    """Kelly 仓位计算"""
    wp = min(score / 10.0, 0.8)
    kelly = max(0, (wp * cfg.kelly_odds - (1 - wp)) / cfg.kelly_odds)
    kelly = kelly * cfg.kelly_fraction  # 半凯利
    return min(kelly, cfg.max_position_pct)


def decide(
    score_map: dict[str, float],
    tech_map: dict[str, dict],
    price_map: dict[str, float],
    positions: dict[str, PositionData],
    cash: float,
    config: FacejiConfig | None = None,
) -> list[Signal]:
    """面基策略决策函数。

    纯函数：输入市场数据+持仓快照 → 输出信号。
    不读文件、不改全局、不调外部 API。

    参数:
        score_map: {symbol -> 综合评分(1-10)}
        tech_map: {symbol -> {ma20_dev, ma60_dev, ...}}
        price_map: {symbol -> 当前价格}
        positions: {symbol -> PositionData} 当前持仓快照
        cash: 可用现金
        config: 策略参数
    返回:
        Signal 列表（BUY / SELL）
    """
    cfg = config or FacejiConfig()
    signals: list[Signal] = []
    held = set(positions.keys())

    # ─── 建仓信号 ───
    candidates = sorted(
        [s for s in score_map if s not in held],
        key=lambda s: score_map.get(s, 0), reverse=True
    )[:cfg.max_candidates]

    for sym in candidates:
        if len(positions) >= cfg.max_positions:
            break
        score = score_map.get(sym, 0)
        if score < cfg.entry_threshold:
            continue
        tech = tech_map.get(sym, {})
        ma20d = tech.get("ma20_dev", 0) or 0
        ma60d = tech.get("ma60_dev", 0) or 0
        if ma60d <= ma20d and score < cfg.ma_trend_boost_threshold:
            continue
        price = price_map.get(sym, 0)
        if price <= 0:
            continue

        # Kelly 仓位
        kelly_pct = _kelly_size(score, cfg)
        qty = max(100, int(cash * kelly_pct / 100 / price / 100) * 100)
        cost = price * qty
        if cost > cash:
            qty = max(100, int(cash / price / 100) * 100)

        signals.append(Signal(
            symbol=sym, action="BUY", price=price,
            reason=f"评分{score:.1f}+MA趋势ok",
            priority="HIGH" if score >= 5.5 else "MED",
            size_pct=round(kelly_pct * 100, 1),
            score=score,
        ))

    # ─── 清仓信号（4层风控）───
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
                reason=f"止损{pnl_pct:.1f}%(ATR{atr_pct:.1f}%)",
                priority="HIGH", pnl_pct=pnl_pct, score=score,
            ))
            continue

        # 2. FallSeller
        if dd <= cfg.trailing_stop_pct:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"回落止盈{dd:.1f}%",
                priority="HIGH", pnl_pct=pnl_pct, score=score,
            ))
            continue

        # 3. ScoreDropSeller
        if score < cfg.exit_threshold:
            signals.append(Signal(
                symbol=sym, action="SELL", price=price,
                reason=f"评分下滑{score:.1f}",
                priority="MED", pnl_pct=pnl_pct, score=score,
            ))
            continue

        # 4. MASeller: MA死叉(MA20<MA60 ⟺ ma20d>ma60d)
        if score < 5.0:
            tech = tech_map.get(sym, {})
            ma20d = tech.get("ma20_dev", 0) or 0
            ma60d = tech.get("ma60_dev", 0) or 0
            if ma20d > ma60d and pnl_pct > -5:
                signals.append(Signal(
                    symbol=sym, action="SELL", price=price,
                    reason="MA死叉+评分<5",
                    priority="MED", pnl_pct=pnl_pct, score=score,
                ))

    return signals
