"""
analysis/etf_portfolio.py — ETF组合模块 (择时+非择时)

集成到新管线，生成ETF组合建议、信号和仓位。

架构:
  EtfPortfolioBuilder
    ├─ 择时组合 (TrendFollowing): 510300+511010+512480+518880+513100
    └─ 非择时组合 (RiskParity): 510300+511010+518880+159985 (季度再平衡)

用法:
    python3 analysis/etf_portfolio.py          # CLI 调用，输出到 data/etf_portfolio.json
    from etf.etf_portfolio import get_etf_signal, get_etf_portfolio

依赖:
    data/data_router.get_history()
    analysis.allocation_strategies.{TrendFollowing, RiskParity}
    data.etf_universe.ETF_BY_SYMBOL
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

# ── 项目路径 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data.data_router import get_history
from data.etf_universe import ETF_BY_SYMBOL
from etf.allocation_strategies import TrendFollowing, RiskParity

# ── 常量 ──

# 择时组合: MA20/MA60 趋势跟踪
TIMING_SYMBOLS = ["510300", "511010", "512480", "518880", "513100"]
TIMING_RISK_ASSETS = ["510300", "512480", "518880", "513100"]
TIMING_SAFE_ASSET = "511010"

# 非择时组合: 风险平价
RP_SYMBOLS = ["510300", "511010", "518880", "159985"]

# 全部唯一标的
ALL_SYMBOLS = sorted(set(TIMING_SYMBOLS + RP_SYMBOLS))

# ETF 名称映射 (补充 etf_universe 中未定义的)
_EXTRA_NAMES = {
    "518880": "黄金ETF",
    "513100": "纳指ETF",
    "159985": "豆粕ETF",
}

DATA_DIR = _PROJECT_ROOT / "data"

# 历史数据天数 (至少需要 60 个交易日计算 MA60 + 缓冲)
HISTORY_DAYS = 400

# 季度再平衡月份
QUARTER_MONTHS = {1, 4, 7, 10}


def _get_etf_name(symbol: str) -> str:
    """获取 ETF 中文名称"""
    if symbol in ETF_BY_SYMBOL:
        return ETF_BY_SYMBOL[symbol].name
    return _EXTRA_NAMES.get(symbol, symbol)


def _is_quarter_start() -> bool:
    """判断当前日期是否为季度首月 (1/4/7/10月)"""
    return datetime.now().month in QUARTER_MONTHS


def _build_price_df() -> pd.DataFrame | None:
    """从 data_router 获取所有 ETF 价格数据，组装成 DataFrame

    Returns:
        DataFrame with columns=symbols, index=dates, values=close prices
        或 None (数据不足)
    """
    price_dict: dict[str, pd.Series] = {}
    common_index: pd.DatetimeIndex | None = None

    for sym in ALL_SYMBOLS:
        raw = get_history(sym, days=HISTORY_DAYS)
        if raw is None or "dates" not in raw or "close" not in raw:
            print(f"[WARN] {sym}: 无数据，跳过")
            continue

        dates = pd.to_datetime(raw["dates"])
        closes = pd.Series(raw["close"], index=dates, name=sym)
        closes = closes.sort_index()

        # 用收盘价
        price_dict[sym] = closes

        if common_index is None:
            common_index = closes.index
        else:
            common_index = common_index.intersection(closes.index)

    if not price_dict or common_index is None or len(common_index) < 20:
        print("[ERROR] 价格数据不足 (至少需要 20 个交易日)")
        return None

    # 对齐到公共日期
    df = pd.DataFrame({sym: price_dict[sym] for sym in ALL_SYMBOLS if sym in price_dict})
    df = df.loc[common_index]
    df = df.dropna(how="any")
    return df


def _determine_action(current_weight: float, target_weight: float,
                      threshold: float = 0.02) -> str:
    """比较当前权重与目标权重，返回 HOLD / BUY / SELL

    Args:
        current_weight: 当前实际权重 (0~1)
        target_weight: 目标权重 (0~1)
        threshold: 触发买卖的偏离阈值

    Returns:
        "BUY" | "SELL" | "HOLD"
    """
    diff = target_weight - current_weight
    if diff > threshold:
        return "BUY"
    elif diff < -threshold:
        return "SELL"
    return "HOLD"


class EtfPortfolioBuilder:
    """ETF 组合构建器

    生成择时与非择时两个子组合的建议信号与目标仓位。
    """

    def __init__(self):
        self.price_df: pd.DataFrame | None = None
        self._timing_weights: dict[str, float] | None = None
        self._rp_weights: dict[str, float] | None = None
        self._latest_idx: int = -1
        self._full_signal: dict = {}
        self._built: bool = False

    def build(self) -> dict:
        """执行完整的信号计算，返回组合建议 dict

        Returns:
            {
                "timestamp": "2025-01-15T14:30:00",
                "timing_portfolio": { ... },
                "non_timing_portfolio": { ... },
                "combined": [ {etf_symbol, name, action, weight, reason, signal_type}, ... ]
            }
        """
        self.price_df = _build_price_df()
        if self.price_df is None or self.price_df.empty:
            return {"error": "价格数据不可用", "timestamp": datetime.now().isoformat()}

        self._latest_idx = len(self.price_df) - 1

        # ── 1. 择时组合 (TrendFollowing) ──
        self._compute_timing()

        # ── 2. 非择时组合 (RiskParity, 季度再平衡) ──
        self._compute_risk_parity()

        # ── 3. 合并输出 ──
        result = self._build_output()
        self._full_signal = result
        self._built = True
        return result

    def _compute_timing(self) -> None:
        """计算择时组合的目标权重"""
        # 找出 price_df 中实际存在的风险资产
        available_risk = [s for s in TIMING_RISK_ASSETS if s in self.price_df.columns]
        safe = TIMING_SAFE_ASSET if TIMING_SAFE_ASSET in self.price_df.columns else None

        if not available_risk:
            print("[WARN] 择时组合: 无可用风险资产")
            self._timing_weights = {}
            return

        strat = TrendFollowing(
            risk_assets=available_risk,
            safe_asset=safe or available_risk[0],
            fast_ma=20,
            slow_ma=60,
            name="TrendTiming",
        )
        self._timing_weights = strat.compute(self.price_df, self._latest_idx)

    def _compute_risk_parity(self) -> None:
        """计算非择时组合的目标权重 (季度再平衡)"""
        available_rp = [s for s in RP_SYMBOLS if s in self.price_df.columns]

        if len(available_rp) < 2:
            print(f"[WARN] 非择时组合: 可用标的不足 ({available_rp})")
            self._rp_weights = None
            return

        should_rebalance = _is_quarter_start()

        if should_rebalance or self._rp_weights is None:
            # 重新计算风险平价
            strat = RiskParity(
                symbols=available_rp,
                window=60,
                use_covariance=False,
                name="RiskParity_Quarterly",
            )
            self._rp_weights = strat.compute(self.price_df, self._latest_idx)
        else:
            # 非季度首月：保持上次权重不变
            pass

    def _build_output(self) -> dict:
        """组装最终输出

        输出两个独立子组合 + 一个合并视图:
          - timing 组合: 5 支 ETF, 权重和 = 1.0
          - rp 组合: 4 支 ETF, 权重和 = 1.0
          - combined: 去重合并，重叠标的以 timing 为准
        """
        # ── 构建 timing 输出 ──
        timing_out = []
        if self._timing_weights:
            tw_sum = sum(self._timing_weights.values())
            for sym in TIMING_SYMBOLS:
                target = self._timing_weights.get(sym, 0.0)
                if tw_sum > 0:
                    target = target / tw_sum  # 确保归一

                # 理由
                if sym in TIMING_RISK_ASSETS:
                    if target > 0:
                        reason = f"MA20>MA60 趋势向上，趋势权重 {self._timing_weights.get(sym, 0):.0%}"
                    else:
                        reason = f"MA20<=MA60 趋势向下，减仓至 {target:.0%}"
                elif sym == TIMING_SAFE_ASSET:
                    reason = f"安全资产对冲，趋势权重 {self._timing_weights.get(sym, 0):.0%}"
                else:
                    reason = f"择时信号，目标权重 {target:.0%}"

                timing_out.append({
                    "etf_symbol": sym,
                    "name": _get_etf_name(sym),
                    "weight": round(target, 4),
                    "reason": reason,
                    "signal_type": "trend",
                })

        # ── 构建 RP 输出 ──
        rp_out = []
        if self._rp_weights:
            rw_sum = sum(self._rp_weights.values())
            q_label = " (季度再平衡)" if _is_quarter_start() else " (持有期)"
            for sym in RP_SYMBOLS:
                target = self._rp_weights.get(sym, 0.0)
                if rw_sum > 0:
                    target = target / rw_sum

                reason = f"风险平价，目标权重 {self._rp_weights.get(sym, 0):.0%}{q_label}"
                rp_out.append({
                    "etf_symbol": sym,
                    "name": _get_etf_name(sym),
                    "weight": round(target, 4),
                    "reason": reason,
                    "signal_type": "rp",
                })

        # ── 合并视图: 重叠标的以 timing 为准 ──
        combined_map: dict[str, dict] = {}
        for e in timing_out:
            combined_map[e["etf_symbol"]] = dict(e)
        for e in rp_out:
            if e["etf_symbol"] not in combined_map:
                combined_map[e["etf_symbol"]] = dict(e)
        combined = [combined_map[sym] for sym in sorted(combined_map.keys())]

        # ── 为 combined 计算 action (与当前价格权重比较) ──
        latest_prices = {}
        for sym in ALL_SYMBOLS:
            if sym in self.price_df.columns:
                val = self.price_df[sym].iloc[self._latest_idx]
                if pd.notna(val):
                    latest_prices[sym] = float(val)

        total_price = sum(latest_prices.values())
        current_weights = {}
        if total_price > 0:
            for sym in ALL_SYMBOLS:
                current_weights[sym] = latest_prices.get(sym, 0) / total_price

        for entry in timing_out + rp_out + combined:
            sym = entry["etf_symbol"]
            target = entry["weight"]
            current = current_weights.get(sym, 0.0)
            entry["action"] = _determine_action(current, target)

        return {
            "timestamp": datetime.now().isoformat(),
            "price_date": str(self.price_df.index[self._latest_idx].date()),
            "timing_portfolio": {
                "strategy": "TrendFollowing (MA20/MA60)",
                "symbols": timing_out,
            },
            "non_timing_portfolio": {
                "strategy": "RiskParity (季度再平衡)",
                "symbols": rp_out,
            },
            "combined": combined,
        }

    def get_signal(self) -> dict:
        """返回当前ETF信号 (快捷接口)"""
        if not self._built:
            self._full_signal = self.build()
        return self._full_signal

    def get_portfolio(self) -> dict:
        """返回ETF目标仓位 (快捷接口)"""
        signal = self.get_signal()
        if "combined" in signal:
            return {
                "timestamp": signal.get("timestamp"),
                "target_allocations": signal["combined"],
                "summary": {
                    entry["etf_symbol"]: {
                        "name": entry["name"],
                        "weight": entry["weight"],
                        "action": entry["action"],
                    }
                    for entry in signal["combined"]
                },
            }
        return signal

    def save_json(self, output_path: str | Path | None = None) -> str:
        """保存结果到 JSON 文件"""
        signal = self.get_signal()
        if output_path is None:
            output_path = DATA_DIR / "etf_portfolio.json"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(signal, f, ensure_ascii=False, indent=2)
        print(f"[OK] ETF组合建议已保存 -> {output_path}")
        return str(output_path)


# ── 模块级快捷函数 ──

_builder_instance: EtfPortfolioBuilder | None = None


def _get_builder(force_rebuild: bool = False) -> EtfPortfolioBuilder:
    """获取/创建单例 Builder"""
    global _builder_instance
    if _builder_instance is None or force_rebuild:
        _builder_instance = EtfPortfolioBuilder()
    return _builder_instance


def get_etf_signal(force_rebuild: bool = False) -> dict:
    """返回当前ETF信号

    Returns:
        dict: 完整信号输出 (包含 timing / non_timing / combined)
    """
    builder = _get_builder(force_rebuild)
    return builder.get_signal()


def get_etf_portfolio(force_rebuild: bool = False) -> dict:
    """返回ETF目标仓位 (精简版)

    Returns:
        dict: {
            "timestamp": ...,
            "target_allocations": [...],
            "summary": { symbol: {name, weight, action} }
        }
    """
    builder = _get_builder(force_rebuild)
    return builder.get_portfolio()


# ── CLI ──

def main():
    """命令行入口: python3 analysis/etf_portfolio.py"""
    import argparse

    parser = argparse.ArgumentParser(
        description="ETF 组合模块 — 生成择时+非择时组合建议",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(DATA_DIR / "etf_portfolio.json"),
        help=f"输出 JSON 路径 (默认: {DATA_DIR / 'etf_portfolio.json'})",
    )
    parser.add_argument(
        "--force", "-f",
        action="store_true",
        help="强制重新获取数据并计算",
    )
    parser.add_argument(
        "--print", "-p",
        action="store_true",
        dest="print_output",
        help="同时打印到终端",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  ETF 组合构建器")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    builder = EtfPortfolioBuilder()
    signal = builder.build()

    if "error" in signal:
        print(f"[ERROR] {signal['error']}")
        sys.exit(1)

    # 保存 JSON
    output_path = builder.save_json(args.output)

    # 打印概要
    if args.print_output or True:
        print(f"\n📊 择时组合 (TrendFollowing {len(signal['timing_portfolio']['symbols'])}支):")
        for e in signal["timing_portfolio"]["symbols"]:
            icon = "🟢" if e["action"] == "BUY" else ("🔴" if e["action"] == "SELL" else "⏸️")
            print(f"  {icon} {e['name']} ({e['etf_symbol']}): "
                  f"{e['action']} @ {e['weight']:.1%} — {e['reason']}")

        print(f"\n📊 非择时组合 (RiskParity {len(signal['non_timing_portfolio']['symbols'])}支):")
        for e in signal["non_timing_portfolio"]["symbols"]:
            icon = "🟢" if e["action"] == "BUY" else ("🔴" if e["action"] == "SELL" else "⏸️")
            print(f"  {icon} {e['name']} ({e['etf_symbol']}): "
                  f"{e['action']} @ {e['weight']:.1%} — {e['reason']}")

        print(f"\n📊 合并视图 ({len(signal['combined'])}支):")
        for e in signal["combined"]:
            icon = "🟢" if e["action"] == "BUY" else ("🔴" if e["action"] == "SELL" else "⏸️")
            print(f"  {icon} [{e['signal_type'].upper()}] {e['name']} ({e['etf_symbol']}): "
                  f"{e['action']} @ {e['weight']:.1%} — {e['reason']}")

        print(f"\n📄 完整输出: {output_path}")

    return signal


if __name__ == "__main__":
    main()