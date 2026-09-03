"""验证幸存者偏差补池效果: 对比「固定池等权」 vs「补池后等权」的超额收益。

补池前: 19 只当前龙头等权持有, 超额绝大部分来自"选对池子"(幸存者偏差)。
补池后: 纳入历史退市股, 等权持有的超额应显著下降 → 反映真实可投资域。

运行: python3 scripts/verify_survivorship_bias.py
(需 baostock 网络 + 生产环境 investment_system 依赖, 本地可 mock 验证逻辑)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from engine.evaluator_fixed import FIXED_UNIVERSE, build_universe_with_delisted, preload_all_data


def equal_weight_return(symbols: list[str], days: int = 120) -> float:
    prices = preload_all_data(days, custom_symbols=symbols)
    returns = []
    for closes in prices.values():
        if len(closes) > 1 and closes[0]:
            returns.append(closes[-1] / closes[0] - 1)
    return float(np.mean(returns)) if returns else 0.0


def main():
    base = [s["symbol"] for s in FIXED_UNIVERSE]
    with_delisted = build_universe_with_delisted(base, delisted_limit=30)

    print("=" * 60)
    print("幸存者偏差补池验证")
    print("=" * 60)

    base_ret = equal_weight_return(base)
    pool_ret = equal_weight_return(with_delisted)

    print(f"固定池(19只当前龙头)等权持有: {base_ret*100:+.2f}%")
    print(f"补池后({len(with_delisted)}只含退市)等权持有: {pool_ret*100:+.2f}%")
    print(f"补池纳入退市股数量: {len(with_delisted) - len(base)}")
    print("-" * 60)
    print(f"结论: 补池后等权收益下降 {base_ret - pool_ret:+.2%}pp, "
          f"即幸存者偏差虚增约 {(base_ret - pool_ret)*100:+.1f}pp")


if __name__ == "__main__":
    main()
