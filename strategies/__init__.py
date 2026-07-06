"""strategies package — 三策略纯决策函数

使用方式:
    from strategies import faceji, silverquant, tradingagents
    from strategies.base import Signal, PositionData, FacejiConfig

    signals = faceji.decide(score_map, tech_map, price_map, positions, cash, config)
"""
from . import base, faceji, silverquant, tradingagents

__all__ = ["base", "faceji", "silverquant", "tradingagents"]
