"""板块反转层 (Sector Reversal Engine)

存在理由
────────
个股截面打分只能回答"这几只票里谁更好", 回答不了"现在该不该提高某板块敞口"。
2026-10 费半于 10-22 单日 -6.8% 后 4 日 V 型收复, A股科创50 滞后 5 日仍在下跌,
系统当时无任何一层能表达这个事实 —— 因为全系统没有板块级/时序级信号。

本引擎只做板块级、时序级判断, 输出四类可审计指标:
  1. 动量与回撤:    ret_1d / ret_5d / ret_20d / dd_60d (距 60 日高点回撤)
  2. 相对强度:      rs_5d / rs_20d = 板块收益 − 基准收益 (百分点)
  3. 反转识别:      大跌(≤-3%) 后 N 日收复 50% 失地 + 量能放大 → 反转启动
  4. 跨市场传导:    费半 → A股半导体 的领先滞后 (lag) 与传导缺口 (gap_pp)

设计约束 (对齐 AGENTS.md)
────────────────────────
- 纯函数优先: 所有计算函数只吃 list[float], 不碰 IO, 可单测
- 方法透明: 每个输出附 method 字段, 写明数据源/公式/阈值
- 截面不排名: 板块之间不互相 compete, 各自独立给绝对状态
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Sequence

logger = logging.getLogger(__name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ─── 阈值 (全部集中在此, 便于审计与调参) ───
DROP_THRESHOLD = -3.0        # 单日跌幅 ≤ -3% 视为大跌
RECOVER_RATIO = 0.5          # 收复 50% 失地才算修复
REVERSAL_LOOKBACK = 5        # 只在最近 5 个交易日内找大跌日
VOLUME_MULT = 1.2            # 反弹期均量 / 跌前 20 日均量 ≥ 1.2 才算放量
HIGH_WINDOW = 60             # 距高点回撤的窗口

STAGE_LEAD = "领涨"
STAGE_REVERSAL = "反转启动"
STAGE_BASING = "筑底抬升"
STAGE_FALLING = "补跌"
STAGE_LAG_HIGH = "高位滞涨"
STAGE_NO_DATA = "数据不足"


# ═══════════════════════════════════════════
# 纯函数层
# ═══════════════════════════════════════════
def pct_return(close: Sequence[float], n: int) -> float | None:
    """最新 n 个交易日收益率 (%)。数据不足返回 None。"""
    if n <= 0 or len(close) <= n:
        return None
    prev = close[-1 - n]
    if not prev:
        return None
    return round((close[-1] / prev - 1) * 100, 2)


def drawdown_from_high(close: Sequence[float], window: int = HIGH_WINDOW) -> float | None:
    """相对最近 window 根 K 线最高收盘的回撤 (%)。"""
    if len(close) < 2:
        return None
    seg = close[-window:] if window > 0 else close
    hi = max(seg)
    if not hi:
        return None
    return round((close[-1] / hi - 1) * 100, 2)


def detect_reversal(
    close: Sequence[float],
    volume: Sequence[float],
    drop_thr: float = DROP_THRESHOLD,
    recover_ratio_thr: float = RECOVER_RATIO,
    lookback: int = REVERSAL_LOOKBACK,
    vol_mult: float = VOLUME_MULT,
) -> dict:
    """识别"大跌 → 放量收复"的反转形态。

    规则 (可审计):
      1. 在最近 lookback 根 K 线内, 找单日跌幅 ≤ drop_thr 的最近一根 (记为 D 日)
      2. recover_ratio = (最新收盘 − D日收盘) / (D-1日收盘 − D日收盘)
      3. vol_ratio = mean(volume[D+1:]) / mean(volume[D-20:D])
      4. fired = recover_ratio ≥ recover_ratio_thr 且 vol_ratio ≥ vol_mult
    """
    empty = {"fired": False, "drop_date_idx": None, "drop_pct": 0.0,
             "recover_ratio": 0.0, "days_since": 0, "vol_ratio": 0.0,
             "reason": "数据不足"}
    if len(close) < 6 or len(close) != len(volume):
        return empty

    lo = max(1, len(close) - 1 - lookback)
    drop_idx = None
    for i in range(len(close) - 1, lo - 1, -1):
        if close[i - 1] and (close[i] / close[i - 1] - 1) * 100 <= drop_thr:
            drop_idx = i
            break

    if drop_idx is None:
        return {**empty, "reason": f"最近{lookback}日无≤{drop_thr}%大跌"}

    prev_close = close[drop_idx - 1]
    drop_close = close[drop_idx]
    lost = prev_close - drop_close
    if lost <= 0:
        return {**empty, "reason": "跌幅计算异常"}

    recover_ratio = round((close[-1] - drop_close) / lost, 4)
    rebound_vol = volume[drop_idx + 1:] or volume[drop_idx:]
    base_seg = volume[max(0, drop_idx - 20):drop_idx] or volume[:drop_idx] or list(volume)
    base_vol = sum(base_seg) / len(base_seg)
    # 量能确认取"跌日恐慌放量"与"反弹期均量"两者较大者:
    # 放量可以在跌日(capitulation), 也可以在反弹途中; 只要任一侧放大即视为有效换手。
    vol_ratio_drop = round(volume[drop_idx] / base_vol, 2) if base_vol else 0.0
    vol_ratio_rebound = round((sum(rebound_vol) / len(rebound_vol)) / base_vol, 2) if base_vol else 0.0
    vol_ratio = max(vol_ratio_drop, vol_ratio_rebound)
    days_since = len(close) - 1 - drop_idx
    fired = recover_ratio >= recover_ratio_thr and vol_ratio >= vol_mult

    if fired:
        reason = f"{days_since}日前跌{round((drop_close/prev_close-1)*100,2)}%后放量收复失地{recover_ratio*100:.0f}%"
    elif recover_ratio < recover_ratio_thr:
        reason = f"跌幅{round((drop_close/prev_close-1)*100,2)}%后仅修复{max(recover_ratio,0)*100:.0f}%"
    else:
        reason = f"已收复{recover_ratio*100:.0f}%但量能不足({vol_ratio}x<{vol_mult}x)"

    return {
        "fired": fired,
        "drop_date_idx": drop_idx,
        "drop_pct": round((drop_close / prev_close - 1) * 100, 2),
        "recover_ratio": round(min(recover_ratio, 2.0), 4),
        "days_since": days_since,
        "vol_ratio": vol_ratio,
        "vol_ratio_drop": vol_ratio_drop,
        "vol_ratio_rebound": vol_ratio_rebound,
        "reason": reason,
    }


def relative_strength(a_close: Sequence[float], b_close: Sequence[float], n: int = 5) -> float | None:
    """a 相对 b 的 n 日超额收益 (百分点)。"""
    ra = pct_return(a_close, n)
    rb = pct_return(b_close, n)
    if ra is None or rb is None:
        return None
    return round(ra - rb, 2)


def lead_lag(leader_close: Sequence[float], follower_close: Sequence[float],
             max_lag: int = 5) -> dict:
    """领先滞后: 找出 follower 对 leader 日收益相关性最高的滞后天数。

    lag=0 同日同步, lag=1 表示 leader 领先 follower 一个交易日。
    """
    n = min(len(leader_close), len(follower_close))
    if n < 12:
        return {"lag": None, "corr": 0.0, "samples": 0}

    lr = [leader_close[i] / leader_close[i - 1] - 1 for i in range(len(leader_close) - n + 1, len(leader_close))]
    fr = [follower_close[i] / follower_close[i - 1] - 1 for i in range(len(follower_close) - n + 1, len(follower_close))]

    best_lag, best_corr = None, 0.0
    for lag in range(0, max_lag + 1):
        if lag >= len(lr):
            break
        a = lr[:len(lr) - lag] if lag else lr
        b = fr[lag:] if lag else fr
        m = min(len(a), len(b))
        if m < 10:
            continue
        a, b = a[-m:], b[-m:]
        ma, mb = sum(a) / m, sum(b) / m
        cov = sum((x - ma) * (y - mb) for x, y in zip(a, b))
        va = sum((x - ma) ** 2 for x in a) ** 0.5
        vb = sum((y - mb) ** 2 for y in b) ** 0.5
        corr = cov / (va * vb) if va and vb else 0.0
        if abs(corr) > abs(best_corr):
            best_lag, best_corr = lag, corr
    return {"lag": best_lag, "corr": round(best_corr, 3), "samples": len(lr)}


def classify_stage(rs5: float | None, dd60: float | None, reversal_fired: bool) -> str:
    """阶段判定 (绝对判断, 不做板块间排名)。"""
    if rs5 is None or dd60 is None:
        return STAGE_NO_DATA
    if dd60 > -10:
        return STAGE_LEAD if rs5 > 0 else STAGE_LAG_HIGH
    if reversal_fired:
        return STAGE_REVERSAL
    if rs5 > 0:
        return STAGE_BASING
    return STAGE_FALLING


def score_reversal(recover_ratio: float, rs5: float, vol_ratio: float, dd60: float) -> float:
    """反转评分 0-100, 四段权重固定且可审计。

    反转确认 40 (收复比例, 上限 1.0)
    相对强度 25 (rs5/10, 上限 1.0)
    量能     15 ((vol_ratio-1)/0.5, 上限 1.0)
    回撤空间 20 ((-dd60-10)/30, 上限 1.0)  — 跌得越深, 向上空间越大
    """
    def clip(x: float) -> float:
        return max(0.0, min(1.0, x))

    s = (40 * clip(recover_ratio or 0)
         + 25 * clip((rs5 or 0) / 10)
         + 15 * clip(((vol_ratio or 0) - 1) / 0.5)
         + 20 * clip((-(dd60 or 0) - 10) / 30))
    return round(s, 1)


def transmission_gap(leader_5d: float, follower_5d: float) -> dict:
    """传导缺口: 领先市场已涨/跌多少, 滞后市场还没跟。"""
    return {
        "gap_pp": round(leader_5d - follower_5d, 2),
        "leader_ahead": leader_5d > follower_5d,
    }


# ═══════════════════════════════════════════
# 组合层: 单板块完整状态
# ═══════════════════════════════════════════
METHOD = {
    "data_source": "data_router.get_history (A股ETF: 腾讯/baostock; 海外: yfinance)",
    "ret_formula": "ret_n = close[-1]/close[-1-n] - 1",
    "dd_formula": f"dd60 = close[-1]/max(close[-{HIGH_WINDOW}:]) - 1",
    "rs_formula": "rs_n = ret_n(板块) - ret_n(基准), 单位百分点",
    "reversal_rule": (f"最近{REVERSAL_LOOKBACK}日内单日跌幅≤{DROP_THRESHOLD}%, 且 "
                      f"(最新-跌日收盘)/(跌日前收盘-跌日收盘)≥{RECOVER_RATIO}, 且 "
                      f"max(跌日量比, 反弹期均量比)≥{VOLUME_MULT} (跌日恐慌放量或反弹放量均可)"),
    "score_weights": "反转40% + 相对强度25% + 量能15% + 回撤空间20%",
    "stage_rule": "dd60>-10→领涨/高位滞涨; dd60≤-10且反转→反转启动; rs5>0→筑底抬升; 否则补跌",
}


def analyze_sector(key: str, name: str, symbol: str, market: str,
                   close: Sequence[float], volume: Sequence[float],
                   bench_close: Sequence[float],
                   dates: Sequence[str] | None = None) -> dict:
    """把一条板块价格序列压成一个可审计的状态对象。"""
    close = list(close or [])
    volume = list(volume or [])
    bench_close = list(bench_close or [])

    ret_1d = pct_return(close, 1)
    ret_5d = pct_return(close, 5)
    ret_20d = pct_return(close, 20)
    dd60 = drawdown_from_high(close)
    rev = detect_reversal(close, volume) if len(close) >= 6 else {
        "fired": False, "reason": "数据不足", "recover_ratio": 0.0,
        "vol_ratio": 0.0, "drop_pct": 0.0, "days_since": 0, "drop_date_idx": None,
    }
    rs_5d = relative_strength(close, bench_close, 5)
    rs_20d = relative_strength(close, bench_close, 20)
    vol_ratio_5d = None
    if len(volume) >= 25:
        recent = sum(volume[-5:]) / 5
        base = sum(volume[-25:-5]) / 20
        vol_ratio_5d = round(recent / base, 2) if base else None

    stage = classify_stage(rs_5d, dd60, bool(rev.get("fired")))
    # 评分语义 = "反转证据强度"。补跌/高位滞涨无反转证据, 直接记 0,
    # 避免"跌得深就分高"把下跌板块顶到榜首。
    if stage in (STAGE_NO_DATA, STAGE_FALLING, STAGE_LAG_HIGH):
        score = 0.0
    else:
        score = score_reversal(rev.get("recover_ratio", 0.0), rs_5d or 0.0,
                               rev.get("vol_ratio", 0.0), dd60 or 0.0)

    return {
        "key": key,
        "name": name,
        "symbol": symbol,
        "market": market,
        "as_of": dates[-1] if dates else None,
        "stage": stage,
        "score": score,
        "ret_1d": ret_1d,
        "ret_5d": ret_5d,
        "ret_20d": ret_20d,
        "dd_60d": dd60,
        "rs_5d": rs_5d,
        "rs_20d": rs_20d,
        "vol_ratio_5d": vol_ratio_5d,
        "reversal": rev,
        "score_note": "反转证据强度 0-100; 补跌/高位滞涨/数据不足记 0",
        "method": METHOD,
    }


def format_report_blocks(payload: dict, max_falling: int = 3) -> list[tuple]:
    """把板块反转快照转成日报 blocks (纯函数, 供 run_daily 写入飞书)。

    blocks 形如 ('h3', text) / ('bullet', text) / ('bold', text) / ('text', text)
    """
    blocks: list[tuple] = []
    secs = payload.get("sectors") or []
    if not secs:
        return [("text", "板块反转数据为空")]

    rev = sorted([s for s in secs if s.get("stage") == STAGE_REVERSAL],
                 key=lambda x: x.get("score", 0), reverse=True)
    basing = sorted([s for s in secs if s.get("stage") == STAGE_BASING],
                    key=lambda x: x.get("score", 0), reverse=True)
    falling = sorted([s for s in secs if s.get("stage") == STAGE_FALLING],
                     key=lambda x: x.get("ret_5d") or 0)

    if rev:
        for s in rev[:3]:
            rv = s.get("reversal") or {}
            blocks.append(("bullet",
                f"🔄 **{s['key']}** 反转启动 | 评分{s['score']:.0f} | "
                f"5日{(s.get('ret_5d') or 0):+.2f}% 距高{(s.get('dd_60d') or 0):.1f}% | "
                f"{rv.get('reason', '')}"))
    else:
        blocks.append(("text", "本轮无板块触发反转信号"))

    if basing:
        blocks.append(("bullet", "🌱 筑底抬升: " + " / ".join(
            f"{s['key']}({(s.get('ret_5d') or 0):+.1f}%)" for s in basing[:4])))

    gap = (payload.get("summary") or {}).get("gap_top")
    if gap:
        blocks.append(("bullet",
            f"🌉 传导缺口最大: {gap['leader']} {(gap.get('leader_5d') or 0):+.2f}% → "
            f"{gap['follower']} {(gap.get('follower_5d') or 0):+.2f}% | "
            f"缺口{gap.get('gap_pp', 0):+.2f}pp | 历史领先{gap.get('lag')}日"))

    if falling:
        blocks.append(("text", "❄️ 补跌: " + " / ".join(
            f"{s['key']}{(s.get('ret_5d') or 0):+.1f}%" for s in falling[:max_falling])))
    return blocks


def save_snapshot(payload: dict, path: str | None = None) -> str:
    """落盘 data/sector_reversal.json (原子写)。"""
    path = path or os.path.join(_PROJECT_DIR, "data", "sector_reversal.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    logger.info("[sector_reversal] saved -> %s (%d sectors)", path, len(payload.get("sectors", [])))
    return path
