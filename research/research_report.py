import socket
from datetime import datetime, timedelta
from typing import Dict, List, Optional

socket.setdefaulttimeout(10)

_RATING_RANK = {"买入": 4, "增持": 3, "持有": 2, "中性": 2, "减持": 1, "卖出": 0}
_RATING_EMOJI = {"买入": "🟢", "增持": "🔵", "持有": "🟡", "中性": "🟡", "减持": "🔴", "卖出": "🔴"}


def get_research_summary(symbol: str, days: int = 30) -> Optional[Dict]:
    try:
        import akshare as ak
        df = ak.stock_research_report_em(symbol=symbol)
    except Exception:
        return None

    if df is None or df.empty:
        return None

    date_col = "日期" if "日期" in df.columns else None
    rating_col = "东财评级" if "东财评级" in df.columns else None
    broker_col = "机构" if "机构" in df.columns else None
    title_col = "报告名称" if "报告名称" in df.columns else None

    if not date_col:
        return None

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    try:
        recent = df[df[date_col].astype(str) >= cutoff].copy()
    except Exception:
        recent = df.head(20)

    if recent.empty:
        return None

    total = len(recent)
    ratings: Dict[str, int] = {}
    if rating_col and rating_col in recent.columns:
        for r in recent[rating_col].dropna():
            r = str(r).strip()
            if r:
                ratings[r] = ratings.get(r, 0) + 1

    avg_score = 0.0
    if ratings:
        total_rated = sum(ratings.values())
        weighted = sum(_RATING_RANK.get(r, 2) * cnt for r, cnt in ratings.items())
        avg_score = weighted / total_rated if total_rated else 2.0

    latest_broker = ""
    latest_title = ""
    if broker_col and broker_col in recent.columns:
        row = recent.iloc[0]
        latest_broker = str(row.get(broker_col, "")).strip()
    if title_col and title_col in recent.columns:
        row = recent.iloc[0]
        latest_title = str(row.get(title_col, "")).strip()[:40]

    dominant_rating = max(ratings, key=ratings.get) if ratings else ""
    emoji = _RATING_EMOJI.get(dominant_rating, "⚪")

    rating_str = " ".join(
        f"{_RATING_EMOJI.get(r,'⚪')}{r}×{cnt}"
        for r, cnt in sorted(ratings.items(), key=lambda x: -_RATING_RANK.get(x[0], 2))
    )

    return {
        "total": total,
        "days": days,
        "ratings": ratings,
        "rating_str": rating_str,
        "dominant_rating": dominant_rating,
        "dominant_emoji": emoji,
        "avg_score": round(avg_score, 1),
        "latest_broker": latest_broker,
        "latest_title": latest_title,
    }


def format_research_line(summary: Optional[Dict]) -> str:
    if not summary or summary.get("total", 0) == 0:
        return ""
    r = summary
    base = f"📋 近{r['days']}天研报 {r['total']} 篇"
    if r["rating_str"]:
        base += f" | {r['rating_str']}"
    if r["latest_broker"] and r["latest_title"]:
        base += f" | 最新: {r['latest_broker']}《{r['latest_title']}》"
    return base


def batch_research_summary(symbols: List[str], days: int = 30) -> Dict[str, Optional[Dict]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    results: Dict[str, Optional[Dict]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(get_research_summary, sym, days): sym for sym in symbols}
        for fut in as_completed(futures, timeout=45):
            sym = futures[fut]
            try:
                results[sym] = fut.result(timeout=15)
            except Exception:
                results[sym] = None
    return results
