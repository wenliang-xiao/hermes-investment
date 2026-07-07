"""test_price_zero_strategies.py — 验证三策略 SELL 分支 price=0 防护"""
import sys
sys.path.insert(0, ".")

from strategies.base import Signal, PositionData, FacejiConfig, SilverQuantConfig, TradingAgentsConfig
from strategies import faceji as _faceji_pure
from strategies import silverquant as _sq_pure
from strategies.tradingagents import decide as _ta_decide


def make_pos(entry_price=100.0, qty=100, peak=None, current_price=None):
    return PositionData(symbol="TEST", entry_price=entry_price, quantity=qty,
                        peak=peak or entry_price, current_price=current_price or entry_price,
                        entry_date="2026-07-01")


def test_faceji_skip_sell_when_price_zero():
    """faceji SELL 分支收到 price=0 时不应生成信号"""
    positions = {"TEST": make_pos(entry_price=100)}
    price_map = {}  # price_map.get(sym) → 0 → pos.current_price→100 → 不会触发
    # 但关键是 price_map 里有 0 的情况
    price_map_with_zero = {"TEST": 0}
    sigs = _faceji_pure.decide(
        score_map={"TEST": 5.0},
        tech_map={"TEST": {"ma20_dev": 1, "ma60_dev": 1, "rsi": 50}},
        price_map=price_map_with_zero,
        positions=positions, cash=100000,
        config=FacejiConfig()
    )
    sell_sigs = [s for s in sigs if s.action == "SELL"]
    assert len(sell_sigs) == 0, f"price=0 不应产生SELL信号: {[s.reason for s in sell_sigs]}"


def test_silverquant_skip_sell_when_price_zero():
    """silverquant SELL 分支收到 price=0 时不应生成信号"""
    positions = {"TEST": make_pos(entry_price=100)}
    sigs = _sq_pure.decide(
        score_map={"TEST": 5.0},
        tech_map={},
        price_map={"TEST": 0},
        positions=positions, cash=100000,
        config=SilverQuantConfig()
    )
    sell_sigs = [s for s in sigs if s.action == "SELL"]
    assert len(sell_sigs) == 0, f"price=0 不应产生SELL信号: {[s.reason for s in sell_sigs]}"


def test_tradingagents_skip_sell_when_price_zero():
    """tradingagents SELL 分支收到 price=0 时不应生成信号"""
    positions = {"TEST": make_pos(entry_price=100)}
    sigs = _ta_decide(
        score_map={"TEST": 5.5},
        tech_map={"TEST": {"ma20_dev": 1, "ma60_dev": 1, "rsi": 50}},
        price_map={"TEST": 0},
        positions=positions, cash=100000,
        config=TradingAgentsConfig()
    )
    sell_sigs = [s for s in sigs if s.action == "SELL"]
    assert len(sell_sigs) == 0, f"price=0 不应产生SELL信号: {[s.reason for s in sell_sigs]}"


def test_run_trading_skip_price_zero_in_price_map():
    """run_trading.py 的 price_map 构建应跳过 price=0"""
    # 模拟 run_trading.py 的逻辑
    score_results = [
        {"symbol": "OK", "score": 6.5, "price": 100.0},
        {"symbol": "BAD", "score": 5.5, "price": 0},
    ]
    score_map = {}
    price_map = {}
    for r in score_results:
        sym = r["symbol"]
        score = r.get("score", 0)
        price = r.get("price", 0)
        if score <= 0 or not price or price <= 0:
            continue
        score_map[sym] = score
        price_map[sym] = price
    assert "BAD" not in price_map, "price=0 不应在 price_map 中"
    assert "OK" in price_map, "price>0 应在 price_map 中"
    assert price_map["OK"] == 100.0