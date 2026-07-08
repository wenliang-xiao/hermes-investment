"""
etf/discovery.py — 动态ETF发现扫描器

从全量A股ETF市场中扫描、多因子评分、动态构建最优ETF池。

核心流程:
  1. 通过 AKShare fund_etf_spot_em() 获取全市场 ETF 列表
  2. 分类 (broad_index/sector/theme/bond/commodity/cross_border/dividend/other)
  3. 多因子评分 (动量/趋势/流动性/波动率/费率)
  4. 动态池构建 (跨类别分散 + 安全港)
  5. 输出到 data/etf_discovery.json

用法:
    python3 etf/discovery.py                              # CLI 运行
    from etf.discovery import EtfDiscoveryScanner         # 编程接口

依赖:
    akshare (全市场扫描)
    data/data_router.get_history() (历史价格+缓存)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── 项目路径 ──
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from data.data_router import get_history

# ── 常量 ──
DATA_DIR = _PROJECT_ROOT / "data"
OUTPUT_PATH = DATA_DIR / "etf_discovery.json"
HISTORY_DAYS = 250  # 需要至少120天计算R120，加缓冲取250
MIN_HISTORY = 60    # 最少需要60天数据

# ── ETF 分类规则 (基于名称关键词) ──
CATEGORY_RULES: dict[str, list[str]] = {
    "bond":          ["债", "货币", "银华日利", "国债", "企业债", "信用债", "可转债", "短融", "城投债",
                      "金融债", "利率债", "地方债", "政金债"],
    "commodity":     ["黄金", "豆粕", "有色", "白银", "原油", "能源化工", "沪铜", "沪铝", "沪锌",
                      "农产品", "铁矿石", "煤炭", "钢铁"],
    "cross_border":  ["纳指", "标普", "恒生", "港股", "海外", "QDII", "中概", "德国", "日经",
                      "法国", "韩国", "印度", "越南", "东南亚", "亚太", "全球", "道琼斯"],
    "dividend":      ["红利", "股息", "高息", "自由现金流"],
    "broad_index":   ["沪深300", "中证500", "上证50", "科创50", "创业板", "中证1000",
                      "中证2000", "深证100", "上证180", "科创100", "中证A50", "A500"],
    "sector":        ["医药", "医疗", "创新药", "新能源", "光伏", "锂电", "电池", "新能源车",
                      "半导体", "芯片", "集成电路", "消费", "白酒", "食品饮料", "家电",
                      "军工", "国防", "证券", "券商", "银行", "保险", "金融",
                      "房地产", "化工", "有色", "钢铁", "建材", "建筑",
                      "汽车", "电力", "公用", "环保", "碳中和", "ESG",
                      "煤炭", "养殖", "畜牧", "农业", "旅游", "传媒", "游戏",
                      "计算机", "软件", "通信", "5G", "物联网", "电子",
                      "人工智能", "AI", "机器人", "云计算", "大数据", "区块链",
                      "稀土", "航运", "物流", "教育", "体育"],
    "theme":         ["国企", "央企", "一带一路", "长江经济带", "大湾区", "科创", "专精特新",
                      "数字经济", "信创", "高端制造", "智能制造", "新质生产力"],
}

# ── 排除规则 (货基/杠杆/反向/小众) ──
EXCLUDE_KEYWORDS: list[str] = [
    "货币", "银华日利", "保证金", "理财金", "添富快", "华夏快", "招商快",
    "添益宝", "天天利", "融通", "场内货", "交易货",
    "分级", "两倍", "三倍", "杠杆", "反向", "看跌", "看空", "做空",
    "联接", "LOF",
]


def _classify_etf(name: str, symbol: str = "") -> str:
    """根据ETF名称关键词进行分类

    Args:
        name: ETF 名称
        symbol: ETF 代码 (辅助判断)

    Returns:
        类别: broad_index | sector | theme | bond | commodity | cross_border | dividend | other
    """
    # 特殊代码硬匹配 (优先)
    if symbol == "511010":
        return "bond"
    if symbol == "511880":
        return "bond"
    if symbol == "518880":
        return "commodity"

    for cat, keywords in CATEGORY_RULES.items():
        for kw in keywords:
            if kw in name:
                return cat
    return "other"


def _should_exclude(name: str) -> bool:
    """判断是否应排除(货基/杠杆/反向/联接等)"""
    for kw in EXCLUDE_KEYWORDS:
        if kw in name:
            return True
    return False


def _get_etf_list() -> pd.DataFrame:
    """从 AKShare 获取全量 A股 ETF 列表

    Returns:
        DataFrame with columns: symbol, name, price, change_pct, volume, amount
    """
    import akshare as ak

    print("[INFO] 正在从东方财富获取全量ETF数据...")
    try:
        df = ak.fund_etf_spot_em()
        print(f"[INFO] 获取到 {len(df)} 只ETF")
        return df
    except Exception as e:
        print(f"[ERROR] 获取ETF列表失败: {e}")
        return pd.DataFrame()


def _normalize_score(values: np.ndarray, invert: bool = False) -> np.ndarray:
    """百分位归一化到 [0, 1]

    Args:
        values: 原始数值数组
        invert: True=反向 (如波动率越低越好)

    Returns:
        归一化后的 [0,1] 分数数组，处理NaN
    """
    mask = ~np.isnan(values)
    result = np.full(len(values), np.nan)
    if mask.sum() < 2:
        return result

    v = values[mask]
    ranks = np.argsort(np.argsort(v))  # 百分位排名
    percentiles = ranks / (len(v) - 1) if len(v) > 1 else np.ones_like(ranks) * 0.5
    if invert:
        percentiles = 1.0 - percentiles
    result[mask] = percentiles
    return np.nan_to_num(result, nan=0.5)


class EtfDiscoveryScanner:
    """ETF 动态发现扫描器

    从全量 A股 ETF 市场中扫描，应用多因子过滤，输出排名打分结果。

    用法:
        scanner = EtfDiscoveryScanner()
        result = scanner.scan()
        scanner.save()
    """

    def __init__(self, top_n_per_category: int = 5, total_output: int = 30):
        """
        Args:
            top_n_per_category: 每个类别保留前N只
            total_output: 最终输出总数
        """
        self.top_n_per_category = top_n_per_category
        self.total_output = total_output
        self._results: list[dict] = []
        self._scanned = False

    # ────────── 主流程 ──────────

    def scan(self, verbose: bool = True) -> dict:
        """执行完整扫描流程

        Returns:
            {
                "scan_date": "2026-07-08",
                "total_scanned": 800,
                "total_valid": 350,
                "market_regime": "risk_on",
                "safe_haven_recommended": false,
                "top_picks": [...],
                "all_ranked": [...]
            }
        """
        df = _get_etf_list()
        if df.empty:
            self._scanned = True
            return {"error": "无法获取ETF列表", "scan_date": datetime.now().strftime("%Y-%m-%d")}

        # 列名映射 (兼容不同版本)
        col_map = self._map_columns(df)
        if verbose:
            print(f"[INFO] 列映射: {col_map}")

        # Step 1: 分类 & 过滤
        etf_list = self._classify_and_filter(df, col_map, verbose)
        if verbose:
            print(f"[INFO] 分类+过滤后剩余 {len(etf_list)} 只ETF")

        # Step 2: 获取历史价格 + 多因子评分
        scored = self._score_all(etf_list, verbose)
        if verbose:
            print(f"[INFO] 成功评分 {len(scored)} 只ETF")

        # Step 3: 动态池构建
        result = self._build_pool(scored, verbose)

        self._results = scored
        self._scanned = True
        return result

    # ────────── Step 1: 分类与过滤 ──────────

    def _map_columns(self, df: pd.DataFrame) -> dict:
        """将 AKShare DataFrame 列名映射到标准名"""
        cols = {c: c for c in df.columns}

        # 常见列名映射
        name_maps = {
            "代码": "symbol", "基金代码": "symbol",
            "名称": "name", "基金名称": "name",
            "最新价": "price", "最新净值": "price",
            "涨跌幅": "change_pct",
            "成交量": "volume", "成交额": "amount",
            "换手率": "turnover_rate",
            "基金管理人": "manager",
            "基金规模": "aum",
        }

        mapped = {}
        for orig, new in name_maps.items():
            if orig in cols:
                mapped[new] = orig
        return mapped

    def _classify_and_filter(self, df: pd.DataFrame, col_map: dict,
                             verbose: bool) -> list[dict]:
        """分类、过滤、提取基本信息"""
        col_sym = col_map.get("symbol", "代码")
        col_name = col_map.get("name", "名称")
        col_price = col_map.get("price", "最新价")
        col_vol = col_map.get("volume")
        col_amt = col_map.get("amount")
        col_aum = col_map.get("aum")

        result: list[dict] = []
        excluded_count = 0

        for _, row in df.iterrows():
            symbol = str(row.get(col_sym, "")).strip()
            name = str(row.get(col_name, "")).strip()

            # 过滤: 需要是6位数字代码 (A股ETF)
            if not symbol.isdigit() or len(symbol) != 6:
                continue

            # 过滤: 排除货基/杠杆/反向
            if _should_exclude(name):
                excluded_count += 1
                continue

            price = self._safe_float(row.get(col_price, 0))
            if price <= 0:
                continue

            category = _classify_etf(name, symbol)
            entry = {
                "symbol": symbol,
                "name": name,
                "category": category,
                "price": price,
            }
            if col_vol:
                entry["volume"] = self._safe_float(row.get(col_vol, 0))
            if col_amt:
                entry["amount"] = self._safe_float(row.get(col_amt, 0))
            if col_aum:
                entry["aum"] = self._safe_float(row.get(col_aum, 0))

            result.append(entry)

        if verbose:
            print(f"[INFO] 排除 {excluded_count} 只(货基/杠杆/反向/联接)")
        return result

    # ────────── Step 2: 多因子评分 ──────────

    def _score_all(self, etf_list: list[dict], verbose: bool) -> list[dict]:
        """对所有ETF进行多因子评分"""
        symbols = [e["symbol"] for e in etf_list]
        total = len(symbols)

        # 批量获取价格数据
        price_data: dict[str, dict] = {}
        failed = 0
        for i, sym in enumerate(symbols):
            try:
                raw = get_history(sym, days=HISTORY_DAYS)
                if raw and "close" in raw and len(raw.get("close", [])) >= MIN_HISTORY:
                    price_data[sym] = raw
                else:
                    failed += 1
            except Exception:
                failed += 1
                continue

            if verbose and (i + 1) % 20 == 0:
                print(f"  ... 数据获取进度: {i+1}/{total} (失败{failed})")

        if verbose:
            print(f"[INFO] 数据获取完成: {len(price_data)}/{total} 有效 (失败{failed})")

        # 计算各因子原始值
        raw_scores: list[dict] = []
        for entry in etf_list:
            sym = entry["symbol"]
            raw = price_data.get(sym)
            if raw is None:
                continue

            scores = self._compute_factors(sym, raw, entry)
            if scores:
                raw_scores.append(scores)

        if not raw_scores:
            return []

        # 归一化各因子到 [0,1]
        self._normalize_factors(raw_scores)

        # 计算综合分数
        for s in raw_scores:
            s["composite_score"] = round(
                s.get("momentum_norm", 0.5) * 0.35 +
                s.get("trend_health", 0) * 0.25 +
                s.get("liquidity_norm", 0.5) * 0.15 +
                s.get("vol_inv_norm", 0.5) * 0.15 +
                s.get("fee_norm", 0.5) * 0.10,
                4,
            )

        # 按综合分排序
        raw_scores.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        return raw_scores

    def _compute_factors(self, symbol: str, raw: dict,
                         entry: dict) -> Optional[dict]:
        """计算单只ETF的多因子指标

        Returns:
            dict with raw factor values, or None if insufficient data
        """
        closes = raw.get("close", [])
        volumes = raw.get("volume", [])
        n = len(closes)

        if n < MIN_HISTORY:
            return None

        # ── 动量因子 ──
        r20 = (closes[-1] - closes[-20]) / closes[-20] * 100 if n >= 20 and closes[-20] > 0 else 0
        r60 = (closes[-1] - closes[-60]) / closes[-60] * 100 if n >= 60 and closes[-60] > 0 else 0
        r120 = (closes[-1] - closes[-120]) / closes[-120] * 100 if n >= 120 and closes[-120] > 0 else 0
        momentum_raw = 0.5 * r20 + 0.3 * r60 + 0.2 * r120

        # ── 趋势健康度 ──
        trend_health = self._compute_trend_health(closes)

        # ── 流动性 (20日均成交量) ──
        vol_window = volumes[-20:] if len(volumes) >= 20 else volumes
        avg_volume_20d = sum(vol_window) / len(vol_window) if vol_window else 0

        # ── 年化波动率 ──
        vol_20d = 0.0
        if n >= 21:
            rets = np.array(closes[-21:])
            daily_rets = (rets[1:] - rets[:-1]) / rets[:-1]
            vol_20d = float(np.std(daily_rets, ddof=1) * np.sqrt(252))

        # ── 最大回撤 ──
        max_dd = 0.0
        if n >= 20:
            peak = closes[-20]
            for c in closes[-20:]:
                peak = max(peak, c)
                dd = (c - peak) / peak * 100 if peak > 0 else 0
                max_dd = min(max_dd, dd)

        # ── MA 指标 ──
        ma5 = float(np.mean(closes[-5:])) if n >= 5 else closes[-1]
        ma20 = float(np.mean(closes[-20:])) if n >= 20 else closes[-1]
        ma60 = float(np.mean(closes[-60:])) if n >= 60 else closes[-1]
        ma120 = float(np.mean(closes[-120:])) if n >= 120 else closes[-1]

        # ── 趋势信号 ──
        trend_signals = []
        if ma5 > ma20:
            trend_signals.append("MA5>MA20↗")
        if ma20 > ma60:
            trend_signals.append("MA20>MA60↗")
        if ma60 > ma120:
            trend_signals.append("MA60>MA120↗")
        if ma20 < ma60:
            trend_signals.append("MA20<MA60↘")

        trend_signal = "BULL" if len([s for s in trend_signals if "↗" in s]) >= 2 else (
            "BEAR" if len([s for s in trend_signals if "↘" in s]) >= 1 else "NEUTRAL")

        # ── 费率 (默认0.5%管理费，可通过扩展获取精确值) ──
        fee_pct = entry.get("fee_pct", 0.005)

        return {
            "symbol": symbol,
            "name": entry["name"],
            "category": entry["category"],
            "price": entry.get("price", closes[-1]),
            # 原始因子值
            "momentum_raw": round(momentum_raw, 4),
            "trend_health": round(trend_health, 4),
            "avg_volume_20d": round(avg_volume_20d, 0),
            "vol_20d": round(vol_20d, 4),
            "max_dd_60d": round(abs(max_dd), 2),
            "fee_pct": round(fee_pct, 4),
            # MA
            "ma5": round(ma5, 4),
            "ma20": round(ma20, 4),
            "ma60": round(ma60, 4),
            "ma120": round(ma120, 4),
            # 趋势信号
            "trend_signal": trend_signal,
            "trend_signals": trend_signals,
            "r20d": round(r20, 2),
            "r60d": round(r60, 2),
            "r120d": round(r120, 2),
            # 归一化占位
            "momentum_norm": 0.0,
            "liquidity_norm": 0.0,
            "vol_inv_norm": 0.0,
            "fee_norm": 0.0,
        }

    def _compute_trend_health(self, closes: list[float]) -> float:
        """计算趋势健康度: 均线多头排列的布尔加分

        MA5>MA20: +0.5
        MA20>MA60: +0.3
        MA60>MA120: +0.2
        total: [0, 1]
        """
        n = len(closes)
        score = 0.0
        if n >= 20:
            ma5 = sum(closes[-5:]) / 5
            ma20 = sum(closes[-20:]) / 20
            if ma5 > ma20:
                score += 0.5
            if n >= 60:
                ma60 = sum(closes[-60:]) / 60
                if ma20 > ma60:
                    score += 0.3
                if n >= 120:
                    ma120 = sum(closes[-120:]) / 120
                    if ma60 > ma120:
                        score += 0.2
        return score

    def _normalize_factors(self, scores: list[dict]) -> None:
        """对所有ETF的因子做百分位归一化"""
        n = len(scores)
        if n < 2:
            for s in scores:
                s["momentum_norm"] = 0.5
                s["liquidity_norm"] = 0.5
                s["vol_inv_norm"] = 0.5
                s["fee_norm"] = 0.5
            return

        momentum_vals = np.array([s.get("momentum_raw", 0) for s in scores])
        volume_vals = np.array([s.get("avg_volume_20d", 0) for s in scores])
        vol_vals = np.array([s.get("vol_20d", 0) for s in scores])
        fee_vals = np.array([s.get("fee_pct", 0.005) for s in scores])

        momentum_norm = _normalize_score(momentum_vals, invert=False)   # 越高越好
        volume_norm = _normalize_score(volume_vals, invert=False)        # 越高越好
        vol_inv_norm = _normalize_score(vol_vals, invert=True)           # 越低越好
        fee_norm = _normalize_score(fee_vals, invert=True)               # 越低越好

        for i, s in enumerate(scores):
            s["momentum_norm"] = round(float(momentum_norm[i]), 4)
            s["liquidity_norm"] = round(float(volume_norm[i]), 4)
            s["vol_inv_norm"] = round(float(vol_inv_norm[i]), 4)
            s["fee_norm"] = round(float(fee_norm[i]), 4)

    # ────────── Step 3: 动态池构建 ──────────

    def _build_pool(self, scored: list[dict], verbose: bool) -> dict:
        """构建动态ETF池，确保跨类别分散 + 安全港逻辑"""
        if not scored:
            return {"error": "无可用ETF", "scan_date": datetime.now().strftime("%Y-%m-%d")}

        # ── 市场情绪判定 ──
        market_regime = self._determine_regime(scored)
        safe_haven = market_regime == "risk_off"

        if verbose:
            print(f"[INFO] 市场情绪: {market_regime}{' → 推荐安全港511010' if safe_haven else ''}")

        # ── 跨类别选TOP ──
        by_category: dict[str, list[dict]] = {}
        for s in scored:
            cat = s.get("category", "other")
            by_category.setdefault(cat, []).append(s)

        top_picks: list[dict] = []
        for cat in ["bond", "commodity", "cross_border", "dividend",
                     "broad_index", "sector", "theme", "other"]:
            items = by_category.get(cat, [])
            for item in items[:self.top_n_per_category]:
                top_picks.append(item)

        # 按综合分排序
        top_picks.sort(key=lambda x: x.get("composite_score", 0), reverse=True)
        top_picks = top_picks[:self.total_output]

        # ── 安全港: 确保 511010 在列 ──
        has_safe = any(e["symbol"] == "511010" for e in top_picks)
        safe_entry = next((e for e in scored if e["symbol"] == "511010"), None)
        if safe_haven and not has_safe and safe_entry:
            top_picks.insert(0, safe_entry)
        elif not has_safe and safe_entry:
            # 即使非 risk_off 也加入国债作为对冲选项
            top_picks.append(safe_entry)
            top_picks.sort(key=lambda x: x.get("composite_score", 0), reverse=True)

        # ── 输出格式 ──
        output = []
        for i, s in enumerate(top_picks):
            rec = ""
            if safe_haven and s["symbol"] == "511010":
                rec = "🛡️ 安全港推荐"
            elif s.get("composite_score", 0) >= 0.7:
                rec = "⭐ 强烈建议"
            elif s.get("composite_score", 0) >= 0.5:
                rec = "👍 关注"
            else:
                rec = "观察"

            output.append({
                "rank": i + 1,
                "symbol": s["symbol"],
                "name": s["name"],
                "category": s["category"],
                "composite_score": s.get("composite_score", 0),
                "momentum": s.get("momentum_raw", 0),
                "momentum_norm": s.get("momentum_norm", 0),
                "trend_signal": s.get("trend_signal", "NEUTRAL"),
                "trend_health": s.get("trend_health", 0),
                "volatility_20d": s.get("vol_20d", 0),
                "liquidity_score": s.get("liquidity_norm", 0),
                "r20d": s.get("r20d", 0),
                "r60d": s.get("r60d", 0),
                "max_dd_60d": s.get("max_dd_60d", 0),
                "recommendation": rec,
            })

        return {
            "scan_date": datetime.now().strftime("%Y-%m-%d"),
            "scan_timestamp": datetime.now().isoformat(),
            "total_scanned": len(scored),
            "market_regime": market_regime,
            "safe_haven_recommended": safe_haven,
            "safe_haven_symbol": "511010" if safe_haven else None,
            "category_stats": {
                cat: len(items) for cat, items in by_category.items()
            },
            "top_picks": output,
        }

    def _determine_regime(self, scored: list[dict]) -> str:
        """根据全市场动量判定市场情绪

        risk_off: 超过80%的ETF动量为负 → 风险规避
        risk_on:  超过60%的ETF动量为正 → 风险偏好
        neutral:  中间状态
        """
        momentums = [s.get("momentum_raw", 0) for s in scored]
        positive = sum(1 for m in momentums if m > 0)
        negative = sum(1 for m in momentums if m < 0)
        total = positive + negative

        if total == 0:
            return "neutral"

        neg_ratio = negative / total
        pos_ratio = positive / total

        if neg_ratio > 0.8:
            return "risk_off"
        elif pos_ratio > 0.6:
            return "risk_on"
        return "neutral"

    # ────────── 保存 ──────────

    def save(self, path: Optional[Path] = None) -> str:
        """保存扫描结果到 JSON"""
        if not self._scanned:
            self.scan()

        output_path = path or OUTPUT_PATH
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # 构建完整输出
        full_output = self.scan(verbose=False) if self._scanned else {"error": "未扫描"}

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(full_output, f, ensure_ascii=False, indent=2)

        print(f"[OK] ETF发现结果已保存 -> {output_path}")
        return str(output_path)

    def get_full_ranked(self) -> list[dict]:
        """返回完整排名列表(含所有因子分)"""
        if not self._scanned:
            self.scan()
        return self._results

    # ────────── 工具 ──────────

    @staticmethod
    def _safe_float(val) -> float:
        try:
            return float(val)
        except (ValueError, TypeError):
            return 0.0


# ── 模块级快捷函数 ──

def run_discovery(verbose: bool = True) -> dict:
    """运行ETF发现扫描，保存结果"""
    scanner = EtfDiscoveryScanner()
    result = scanner.scan(verbose=verbose)
    scanner.save()
    return result


def get_discovery_result() -> dict:
    """从缓存文件读取最新发现结果"""
    path = DATA_DIR / "etf_discovery.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"error": "未找到发现结果，请先运行 run_discovery()"}


# ── CLI ──

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="ETF动态发现扫描器 — 全市场A股ETF扫描+多因子评分",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=str(OUTPUT_PATH),
        help=f"输出 JSON 路径 (默认: {OUTPUT_PATH})",
    )
    parser.add_argument(
        "--top-n", "-n",
        type=int,
        default=30,
        help="最终输出数量 (默认: 30)",
    )
    parser.add_argument(
        "--per-category", "-c",
        type=int,
        default=5,
        help="每个类别最大数量 (默认: 5)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=True,
        help="详细输出",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="静默模式",
    )
    args = parser.parse_args()

    verbose = not args.quiet

    print("=" * 60)
    print("  ETF 动态发现扫描器")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    scanner = EtfDiscoveryScanner(
        top_n_per_category=args.per_category,
        total_output=args.top_n,
    )
    result = scanner.scan(verbose=verbose)

    if "error" in result:
        print(f"[ERROR] {result['error']}")
        sys.exit(1)

    scanner.save(Path(args.output))

    # 打印概要
    print(f"\n📊 市场情绪: {result['market_regime']}")
    if result.get("safe_haven_recommended"):
        print("  🛡️ 建议切换至安全港模式!")
    print(f"📊 扫描 {result['total_scanned']} 只ETF, TOP {len(result['top_picks'])}:")

    if result.get("category_stats"):
        print(f"  类别分布: {result['category_stats']}")
    print()

    for e in result["top_picks"][:15]:
        icon = {
            "BULL": "🟢", "BEAR": "🔴", "NEUTRAL": "⚪"
        }.get(e.get("trend_signal", ""), "⚪")
        rec_icon = {"🛡️": "🛡️", "⭐": "⭐", "👍": "  ", "观察": "  "}.get(
            e.get("recommendation", "").split(" ")[0] if e.get("recommendation") else "",
            "  ")
        print(f"  {icon} [{e['category']:12s}] {e['name']:16s} ({e['symbol']}) "
              f"综合{e['composite_score']:.3f} 动量{e['momentum']:+.2f}% {e['recommendation']}")

    print(f"\n📄 完整输出: {args.output}")
    return result


if __name__ == "__main__":
    main()
