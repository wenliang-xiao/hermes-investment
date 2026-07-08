#!/usr/bin/env python3
"""
量化证据1：动量拥挤度分析（v2 - 修复前复权、兼容所有股票）
计算A股核心持仓在MA60偏离超过+30%时的信号统计：
- 从信号日往后60个交易日内的最大回撤
- 正收益概率
- 平均收益
"""

import baostock as bs
import pandas as pd
import numpy as np
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

# ========== 配置 ==========
STOCKS = {
    "300308": "中际旭创",
    "300502": "新易盛",
    "688008": "澜起科技",
    "688041": "海光信息",
    "002371": "北方华创",
    "688017": "绿的谐波",
    "688120": "华海清科",
    "002747": "埃斯顿",
    "300124": "汇川技术",
    "300750": "宁德时代",
}

END_DATE = datetime.now().strftime("%Y-%m-%d")
START_DATE = (datetime.now() - timedelta(days=3*365)).strftime("%Y-%m-%d")
MA_PERIOD = 60
DEVIATION_THRESHOLD = 0.30
LOOKAHEAD_DAYS = 60

print(f"[配置] 数据区间: {START_DATE} ~ {END_DATE}")
print(f"[配置] MA{MA_PERIOD} 偏离阈值: +{DEVIATION_THRESHOLD:.0%}")
print(f"[配置] 回看窗口: {LOOKAHEAD_DAYS} 个交易日")
print(f"[配置] 前复权数据\n")


def fetch_baostock_daily(symbol: str, start: str, end: str) -> pd.DataFrame:
    """用 baostock 获取个股日线数据（前复权）"""
    code = f"sz.{symbol}" if symbol.startswith(("0", "3")) else f"sh.{symbol}"
    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,close",
            start_date=start,
            end_date=end,
            frequency="d",
            adjustflag="1",  # 前复权
        )
        rows = []
        for _ in range(1500):  # max 1500 rows
            if rs.next():
                rows.append(rs.get_row_data())
            else:
                break
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows, columns=["date", "close"])
        df["date"] = pd.to_datetime(df["date"])
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"])
        df = df.sort_values("date").reset_index(drop=True)
        return df
    except Exception as e:
        print(f"  ⚠️  {symbol} ({STOCKS.get(symbol, '?')}) 获取失败: {e}")
        return pd.DataFrame()


def compute_ma60_deviation_signals(df: pd.DataFrame, stock_name: str) -> List[Dict]:
    if df.empty or len(df) < MA_PERIOD + LOOKAHEAD_DAYS:
        print(f"  ⚠️  {stock_name}: 数据不足 ({len(df)}行，需要>={MA_PERIOD+LOOKAHEAD_DAYS})")
        return []
    
    close = df["close"].values
    ma60 = pd.Series(close).rolling(window=MA_PERIOD).mean().values
    deviation = (close - ma60) / ma60
    
    signal_mask = deviation > DEVIATION_THRESHOLD
    signal_indices = np.where(signal_mask)[0]
    
    if len(signal_indices) == 0:
        print(f"  ℹ️  {stock_name}: 无 MA60 偏离超过+{DEVIATION_THRESHOLD:.0%} 的信号")
        return []
    
    # 去重：连续多日触发算同一个信号
    unique_signals = []
    prev = -999
    for idx in signal_indices:
        if idx - prev > 3:
            unique_signals.append(idx)
        prev = idx
    
    results = []
    for sig_idx in unique_signals:
        sig_date = df.iloc[sig_idx]["date"]
        sig_close = close[sig_idx]
        sig_deviation = deviation[sig_idx]
        
        end_idx = sig_idx + LOOKAHEAD_DAYS
        if end_idx >= len(close):
            continue
        
        future_prices = close[sig_idx:end_idx + 1]
        future_dates = df.iloc[sig_idx:end_idx + 1]["date"].values
        
        peak = np.maximum.accumulate(future_prices)
        dd_series = (future_prices - peak) / peak
        max_dd = dd_series.min()
        
        future_returns = (future_prices[1:] - sig_close) / sig_close
        positive_count = np.sum(future_returns > 0)
        total_count = len(future_returns)
        positive_prob = positive_count / total_count if total_count > 0 else 0
        avg_return = future_returns.mean()
        
        results.append({
            "股票": stock_name,
            "信号日": pd.Timestamp(sig_date).strftime("%Y-%m-%d"),
            "信号日收盘价": round(sig_close, 2),
            "MA60偏离度": f"{sig_deviation:.1%}",
            "60日最大回撤": f"{max_dd:.2%}",
            "60日正收益概率": f"{positive_prob:.1%}",
            "60日平均收益": f"{avg_return:.2%}",
        })
    
    print(f"  ✅ {stock_name}: {len(results)} 个信号")
    return results


def main():
    print("=" * 80)
    print("  量化证据1：动量拥挤度分析 — MA60偏离+30%信号")
    print("=" * 80)
    print(f"\n分析标的: {len(STOCKS)} 只核心持仓")
    print(f"数据源: baostock (前复权)")
    print(f"信号条件: MA60偏离度 > +{DEVIATION_THRESHOLD:.0%}")
    print(f"统计窗口: 信号日后 {LOOKAHEAD_DAYS} 个交易日\n")
    
    lg = bs.login()
    print(f"[登录] baostock: {lg.error_code} {lg.error_msg}\n")
    
    all_signals = []
    stock_summaries = []
    
    for symbol, name in STOCKS.items():
        print(f"[获取] {name} ({symbol}) ...")
        sys.stdout.flush()
        df = fetch_baostock_daily(symbol, START_DATE, END_DATE)
        if df.empty:
            print(f"  ❌ {name}: 无数据\n")
            continue
        first_d = df.iloc[0]["date"].strftime("%Y-%m-%d")
        last_d = df.iloc[-1]["date"].strftime("%Y-%m-%d")
        print(f"  📊 {len(df)} 行 ({first_d} ~ {last_d})")
        
        signals = compute_ma60_deviation_signals(df, name)
        all_signals.extend(signals)
        
        if signals:
            dds = [float(s["60日最大回撤"].rstrip("%")) for s in signals]
            probs = [float(s["60日正收益概率"].rstrip("%")) for s in signals]
            avgs = [float(s["60日平均收益"].rstrip("%")) for s in signals]
            stock_summaries.append({
                "股票": name,
                "信号次数": len(signals),
                "平均最大回撤": f"{np.mean(dds):.2f}%",
                "平均正收益概率": f"{np.mean(probs):.1f}%",
                "平均60日收益": f"{np.mean(avgs):.2f}%",
                "最差回撤": f"{min(dds):.2f}%",
                "最佳概率": f"{max(probs):.1f}%",
                "最佳收益": f"{max(avgs):.2f}%",
            })
        print()
        sys.stdout.flush()
    
    bs.logout()
    
    # ========== 输出 ==========
    
    # 1. 汇总
    print("\n" + "=" * 80)
    print("  📊 汇总统计：各股 MA60 偏离 >+30% 信号分析")
    print("=" * 80)
    if stock_summaries:
        sum_df = pd.DataFrame(stock_summaries)
        print(sum_df.to_string(index=False))
    else:
        print("  (无信号)")
    
    # 2. 明细
    print("\n" + "=" * 80)
    print("  📋 逐笔信号明细")
    print("=" * 80)
    if all_signals:
        detail_df = pd.DataFrame(all_signals)
        print(detail_df.to_string(index=False))
        
        # 全局统计
        print("\n" + "-" * 80)
        print("  🏆 全局汇总统计")
        all_dds = [float(s["60日最大回撤"].rstrip("%")) for s in all_signals]
        all_probs = [float(s["60日正收益概率"].rstrip("%")) for s in all_signals]
        all_avgs = [float(s["60日平均收益"].rstrip("%")) for s in all_signals]
        print(f"  总信号数: {len(all_signals)}")
        print(f"  平均最大回撤: {np.mean(all_dds):.2f}%")
        print(f"  中位数最大回撤: {np.median(all_dds):.2f}%")
        print(f"  平均正收益概率: {np.mean(all_probs):.1f}%")
        print(f"  平均60日收益: {np.mean(all_avgs):.2f}%")
        print(f"  信号胜率(收益>0): {sum(1 for a in all_avgs if a > 0) / len(all_avgs):.1%}")
    else:
        print("  (无信号)")
    
    print()
    print("=" * 80)
    print("  分析完成")
    print("=" * 80)


if __name__ == "__main__":
    main()