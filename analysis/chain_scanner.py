"""
链内候选动态扫描器 v1.0
目标：每周从14条链里找出3-5只「本周最值得关注的候选」

设计原则（来自面基+LDS+脱钩框架）：
  - 先过滤后排序（不是靠单一总分）
  - 低波动质量型而非追热点型
  - 脱钩方向（国产替代）独立于双门，持续追踪
  - 输出四维度而非一个总分，保留人工判断空间

四段筛选：
  第1段：可交易性硬过滤（ST/退市/流动性）
  第2段：低波动+不追高过滤（核心差异化）
  第3段：链路对齐（Perez阶段+宏观regime匹配）
  第4段：双轨评分排序（脱钩方向 vs 宏观敏感方向）

双轨评分：
  轨道A（脱钩/国产替代方向）：质量韧性(40%)+低波动(30%)+链路确定性(30%)
  轨道B（宏观敏感方向）：趋势强度(35%)+质量韧性(30%)+估值安全边际(20%)+链路匹配(15%)
"""
import json
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from investment_system import config
from investment_system.data.data_layer import get_stock_daily, get_financial_report

DECOUPLING_CHAINS = {
    "半导体链", "国产替代/信创链", "半导体国产替代",
    "军工链", "医药创新链",
}

MAX_CANDIDATES = 5
MIN_CANDIDATES = 3

CACHE_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "chain_candidates_cache.json"
)


def _load_cache() -> dict:
    try:
        if os.path.exists(CACHE_PATH):
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(CACHE_PATH))).total_seconds()
            if age < 86400 * 6:
                with open(CACHE_PATH) as f:
                    return json.load(f)
    except Exception:
        pass
    return {}


def _save_cache(data: dict):
    try:
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        with open(CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _get_stock_basics(symbol: str) -> dict:
    try:
        import baostock as bs
        code = f"sz.{symbol}" if symbol.startswith(("0", "3")) else f"sh.{symbol}"
        rs = bs.query_stock_basic(code=code)
        if rs.error_code == "0":
            while rs.next():
                r = rs.get_row_data()
                return {
                    "name": r[1] if len(r) > 1 else symbol,
                    "status": r[5] if len(r) > 5 else "1",
                }
    except Exception:
        pass
    return {"name": symbol, "status": "1"}


def _stage1_hard_filter(symbol: str, basics: dict) -> Tuple[bool, str]:
    status = basics.get("status", "1")
    if status not in ("1", ""):
        return False, "ST/退市"
    return True, ""


def _stage2_lowvol_filter(daily: pd.DataFrame) -> Tuple[bool, str, dict]:
    if daily.empty or len(daily) < 60:
        return False, "数据不足60日", {}

    close = daily["close"].values
    price = float(close[-1])

    ret = pd.Series(close).pct_change().dropna()
    vol_90d = float(ret.tail(90).std() * np.sqrt(252) * 100) if len(ret) >= 90 else None
    vol_180d = float(ret.tail(180).std() * np.sqrt(252) * 100) if len(ret) >= 180 else None

    max_dd_90 = 0.0
    if len(close) >= 90:
        window = close[-90:]
        running_max = np.maximum.accumulate(window)
        drawdowns = (window - running_max) / running_max * 100
        max_dd_90 = float(np.min(drawdowns))

    rsi = 50.0
    if len(close) >= 15:
        diffs = np.diff(close[-15:])
        gains = np.mean(np.maximum(diffs, 0))
        losses = np.mean(np.maximum(-diffs, 0))
        if losses > 0:
            rsi = 100 - 100 / (1 + gains / losses)

    ma60 = float(np.mean(close[-60:])) if len(close) >= 60 else price
    ma20 = float(np.mean(close[-20:])) if len(close) >= 20 else price
    ma120 = float(np.mean(close[-120:])) if len(close) >= 120 else price
    ma60_dev = (price - ma60) / ma60 * 100

    if rsi > 80:
        return False, f"极端超买RSI={rsi:.0f}", {}
    if ma60_dev > 50:
        return False, f"偏离MA60过高={ma60_dev:.0f}%", {}

    metrics = {
        "price": price,
        "rsi": round(rsi, 1),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
        "ma120": round(ma120, 2),
        "ma60_dev": round(ma60_dev, 1),
        "vol_90d": round(vol_90d, 1) if vol_90d else None,
        "vol_180d": round(vol_180d, 1) if vol_180d else None,
        "max_dd_90": round(max_dd_90, 1),
        "above_ma60": price > ma60,
        "above_ma120": price > ma120,
        "trend_up": ma20 > ma60 > ma120 if len(close) >= 120 else ma20 > ma60,
    }
    return True, "", metrics


def _stage3_chain_alignment(chain_name: str, regime: str, perez_stage: str) -> Tuple[bool, str]:
    bad_perez = ["maturity", "decline", "成熟期", "衰退", "沉寂"]
    if any(kw in (perez_stage or "").lower() for kw in bad_perez):
        if chain_name not in DECOUPLING_CHAINS:
            return False, f"Perez阶段不佳({perez_stage[:20]})"

    from investment_system.config import MACRO_SECTOR_ROTATION
    rotation = MACRO_SECTOR_ROTATION.get(regime, MACRO_SECTOR_ROTATION["default"])
    unfavored = rotation.get("unfavored", [])
    chain_keywords_map = {
        "新能源链": ["新能源"],
        "消费电子链": ["消费必需品"],
        "AI应用/Agent链": [],
    }
    chain_unfavored = chain_keywords_map.get(chain_name, [])
    if any(uf in unfavored for uf in chain_unfavored):
        return False, f"宏观象限不支持({regime}回避)"

    return True, ""


def _score_decoupling(fin: dict, metrics: dict, chain_name: str) -> dict:
    roe = fin.get("净资产收益率") or 0
    rev_growth = fin.get("营业收入同比增长率") or 0
    ocps = fin.get("每股经营现金流") or 0

    quality = min(10, max(1,
        (min(roe, 40) / 40 * 4) +
        (min(max(rev_growth, 0), 60) / 60 * 3) +
        (min(max(ocps, 0), 5) / 5 * 3)
    ))

    vol = metrics.get("vol_90d") or 40
    dd = abs(metrics.get("max_dd_90") or 25)
    lowvol = min(10, max(1, 10 - (vol - 15) / 4 - dd / 5))

    above_ma60 = 1 if metrics.get("above_ma60") else 0
    trend_up = 1 if metrics.get("trend_up") else 0
    rsi_ok = 1 if 30 < (metrics.get("rsi") or 50) < 75 else 0
    chain_certainty = min(10, max(1, 5 + above_ma60 * 2 + trend_up * 2 + rsi_ok))

    total = quality * 0.40 + lowvol * 0.30 + chain_certainty * 0.30
    return {
        "track": "A_脱钩",
        "total": round(total, 2),
        "quality": round(quality, 1),
        "lowvol": round(lowvol, 1),
        "chain_certainty": round(chain_certainty, 1),
        "trend_strength": None,
        "valuation": None,
        "chain_match": round(chain_certainty, 1),
    }


def _score_macro_sensitive(fin: dict, metrics: dict, daily: pd.DataFrame, chain_name: str, regime: str) -> dict:
    close = daily["close"].values

    ret_20d = float((close[-1] / close[-21] - 1) * 100) if len(close) >= 21 else 0
    ret_60d = float((close[-1] / close[-61] - 1) * 100) if len(close) >= 61 else 0
    ret_120d = float((close[-1] / close[-121] - 1) * 100) if len(close) >= 121 else 0
    above_ma60 = 1 if metrics.get("above_ma60") else 0
    trend_up = 1 if metrics.get("trend_up") else 0
    rsi = metrics.get("rsi") or 50
    not_overheated = 1 if rsi < 75 else 0
    trend_strength = min(10, max(1,
        max(ret_20d, 0) / 20 * 3 +
        max(ret_60d, 0) / 40 * 2.5 +
        max(ret_120d, 0) / 60 * 1.5 +
        above_ma60 * 2 +
        trend_up * 1 +
        not_overheated * 0 +
        1
    ))

    roe = fin.get("净资产收益率") or 0
    ocps = fin.get("每股经营现金流") or 0
    quality = min(10, max(1, min(roe, 40) / 40 * 7 + min(max(ocps, 0), 5) / 5 * 3))

    pe_val = None
    if "pe" in daily.columns and not daily["pe"].isna().all():
        pe_val = float(daily["pe"].iloc[-1]) if daily["pe"].iloc[-1] > 0 else None
    valuation = 5.0
    if pe_val:
        valuation = min(10, max(1, 10 - (pe_val - 10) / 5))

    from investment_system.config import MACRO_SECTOR_ROTATION
    rotation = MACRO_SECTOR_ROTATION.get(regime, MACRO_SECTOR_ROTATION["default"])
    favored = rotation.get("favored", [])
    chain_keywords_map = {
        "英伟达算力链": ["科技", "半导体", "AI"],
        "机器人/自动化链": ["科技", "高端制造", "机器人"],
        "医药创新链": ["医药"],
        "军工链": ["军工"],
        "新能源汽车链": ["消费", "汽车"],
        "苹果产业链": ["消费", "科技"],
    }
    chain_keys = chain_keywords_map.get(chain_name, [])
    match_score = 7 if any(k in favored for k in chain_keys) else 5
    chain_match = float(match_score)

    total = trend_strength * 0.35 + quality * 0.30 + valuation * 0.20 + chain_match * 0.15
    return {
        "track": "B_宏观敏感",
        "total": round(total, 2),
        "trend_strength": round(trend_strength, 1),
        "quality": round(quality, 1),
        "valuation": round(valuation, 1),
        "chain_match": round(chain_match, 1),
        "lowvol": None,
        "chain_certainty": None,
    }


def _build_entry_reason(symbol: str, metrics: dict, fin: dict, score_detail: dict) -> List[str]:
    reasons = []

    rsi = metrics.get("rsi", 50)
    ma60_dev = metrics.get("ma60_dev", 0)
    trend_up = metrics.get("trend_up", False)
    above_ma60 = metrics.get("above_ma60", False)

    if trend_up and above_ma60 and rsi < 70:
        reasons.append(f"趋势健康: MA20>MA60>MA120，RSI={rsi:.0f}不过热")
    elif above_ma60 and ma60_dev < 20:
        reasons.append(f"站稳MA60偏离{ma60_dev:.0f}%，未过热")

    roe = fin.get("净资产收益率")
    rev = fin.get("营业收入同比增长率")
    if roe and roe >= 15:
        reasons.append(f"ROE={roe:.1f}%达LDS质量门槛(≥15%)")
    elif roe and roe >= 10:
        reasons.append(f"ROE={roe:.1f}%合格")
    if rev and rev >= 20:
        reasons.append(f"营收增速{rev:.0f}%超LDS成长门槛")

    track = score_detail.get("track", "")
    if "脱钩" in track:
        reasons.append("国产替代方向，独立于宏观双门")

    return reasons[:3]


def _build_trigger_condition(metrics: dict, fin: dict) -> str:
    ma20 = metrics.get("ma20")
    ma60 = metrics.get("ma60")
    price = metrics.get("price")
    rsi = metrics.get("rsi", 50)

    if price and ma20 and price > ma20 * 1.05:
        return f"等待回踩MA20(¥{ma20:.2f})附近，RSI回落至50-60"
    if rsi > 65:
        return f"等待RSI回落至50以下（当前{rsi:.0f}），再评估"
    return "技术面已具备，等财报/催化剂验证基本面"


def _build_invalidation(fin: dict, chain_name: str) -> str:
    roe = fin.get("净资产收益率")
    if roe and roe < 8:
        return f"ROE跌破8%（当前{roe:.1f}%），或链路核心假设破灭"
    if chain_name in DECOUPLING_CHAINS:
        return "政策退坡/国产替代进度停滞，或出口管制取消"
    return "跌破MA60且成交量放大，或行业链景气逆转"


def scan_chain_candidates(
    regime: str = "default",
    dual_open: bool = True,
    max_candidates: int = MAX_CANDIDATES,
    verbose: bool = True,
) -> List[dict]:
    cache = _load_cache()
    cache_key = f"{regime}_{dual_open}_{datetime.now().strftime('%Y%m%d')}"
    if cache_key in cache:
        if verbose:
            print(f"[chain_scanner] 使用缓存结果: {len(cache[cache_key])} 只候选")
        return cache[cache_key]

    chains = config.INDUSTRY_CHAINS
    all_candidates = []

    try:
        import baostock as bs
        bs.login()
        bs_logged = True
    except Exception:
        bs_logged = False

    for chain_name, chain_data in chains.items():
        perez_stage = chain_data.get("perez_stage", "")
        is_decoupling = chain_name in DECOUPLING_CHAINS
        symbols_a = [s for s in chain_data.get("symbols", []) if s.isdigit()]

        if not symbols_a:
            continue

        for symbol in symbols_a:
            if verbose:
                print(f"  [{chain_name}] {symbol}...")

            basics = _get_stock_basics(symbol)
            ok, reason = _stage1_hard_filter(symbol, basics)
            if not ok:
                continue

            try:
                daily = get_stock_daily(symbol, 200)
            except Exception:
                continue
            if daily is None or (hasattr(daily, 'empty') and daily.empty):
                continue

            ok, reason, metrics = _stage2_lowvol_filter(daily)
            if not ok:
                if verbose:
                    print(f"    ❌ Stage2: {reason}")
                continue

            ok, reason = _stage3_chain_alignment(chain_name, regime, perez_stage)
            if not ok and not is_decoupling:
                if verbose:
                    print(f"    ❌ Stage3: {reason}")
                continue

            try:
                fin = get_financial_report(symbol) or {}
            except Exception:
                fin = {}

            if is_decoupling or not dual_open:
                score_detail = _score_decoupling(fin, metrics, chain_name)
            else:
                score_detail = _score_macro_sensitive(fin, metrics, daily, chain_name, regime)

            entry_reasons = _build_entry_reason(symbol, metrics, fin, score_detail)
            trigger = _build_trigger_condition(metrics, fin)
            invalidation = _build_invalidation(fin, chain_name)

            candidate = {
                "symbol": symbol,
                "name": basics.get("name", symbol),
                "chain": chain_name,
                "is_decoupling": is_decoupling,
                "perez_stage": perez_stage[:30] if perez_stage else "",
                "score": score_detail["total"],
                "score_detail": score_detail,
                "price": metrics.get("price"),
                "rsi": metrics.get("rsi"),
                "ma20": metrics.get("ma20"),
                "ma60": metrics.get("ma60"),
                "ma60_dev": metrics.get("ma60_dev"),
                "vol_90d": metrics.get("vol_90d"),
                "max_dd_90": metrics.get("max_dd_90"),
                "trend_up": metrics.get("trend_up"),
                "roe": fin.get("净资产收益率"),
                "rev_growth": fin.get("营业收入同比增长率"),
                "entry_reasons": entry_reasons,
                "trigger_condition": trigger,
                "invalidation": invalidation,
                "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            }
            all_candidates.append(candidate)

    if bs_logged:
        try:
            import baostock as bs
            bs.logout()
        except Exception:
            pass

    all_candidates.sort(key=lambda x: x["score"], reverse=True)

    selected = []
    seen_chains = set()
    for c in all_candidates:
        if len(selected) >= max_candidates:
            break
        if c["chain"] in seen_chains and len(selected) >= MIN_CANDIDATES:
            continue
        selected.append(c)
        seen_chains.add(c["chain"])

    result = selected[:max_candidates]

    cache[cache_key] = result
    _save_cache(cache)

    if verbose:
        print(f"[chain_scanner] 完成: 扫描{len(all_candidates)}只通过过滤，选出{len(result)}只候选")
        for c in result:
            print(f"  {'🔵脱钩' if c['is_decoupling'] else '🟡宏观'} {c['name']}({c['symbol']}) "
                  f"[{c['chain']}] 评分{c['score']:.1f}")

    return result


def format_candidate_for_report(c: dict) -> str:
    name = c.get("name", c.get("symbol"))
    symbol = c.get("symbol", "")
    chain = c.get("chain", "")
    score = c.get("score", 0)
    price = c.get("price")
    ma20 = c.get("ma20")
    ma60 = c.get("ma60")
    rsi = c.get("rsi")
    ma60_dev = c.get("ma60_dev")
    roe = c.get("roe")
    track = c.get("score_detail", {}).get("track", "")
    track_tag = "🔵脱钩" if "脱钩" in track else "🟡宏观"

    price_str = f"¥{price:.2f}" if price else "?"
    ma_str = f"MA20¥{ma20:.2f} MA60¥{ma60:.2f}" if ma20 and ma60 else ""
    rsi_str = f"RSI{rsi:.0f}" if rsi else ""
    dev_str = f"偏MA60{ma60_dev:+.0f}%" if ma60_dev is not None else ""
    roe_str = f"ROE{roe:.0f}%" if roe else ""

    header = f"{track_tag} **{name}**({symbol}) [{chain}] 评分{score:.1f}"
    metrics_line = " | ".join(filter(None, [price_str, ma_str, rsi_str, dev_str, roe_str]))

    reasons = c.get("entry_reasons", [])
    reasons_str = "、".join(reasons) if reasons else "综合因子评分优秀"

    trigger = c.get("trigger_condition", "")
    invalid = c.get("invalidation", "")

    lines = [
        header,
        f"  数据: {metrics_line}",
        f"  入选原因: {reasons_str}",
        f"  触发条件: {trigger}",
        f"  失效条件: {invalid}",
    ]
    return "\n".join(lines)
