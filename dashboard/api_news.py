"""新闻/多源聚合/情绪分析 API v3 — 基于 news/ 包
数据源: 东方财富个股新闻 + 7×24快讯 + 财联社电报 + 巨潮公告
情绪分析: cnsenti + 自定义金融情绪词典

向后兼容 v2: /api/v2/news 读取新格式 data/news_cache.json
"""

import json
from datetime import datetime as _dt
from fastapi import APIRouter
from dashboard.shared import ROOT

router = APIRouter()

CACHE_PATH = ROOT / "data" / "news_cache.json"

# ════════════════════════════════════════════════
# 类别元信息
# ════════════════════════════════════════════════

CATEGORY_META = {
    "7×24快讯": {"label": "7×24快讯", "emoji": "⚡", "order": 1},
    "电报快讯": {"label": "电报快讯", "emoji": "📡", "order": 2},
    "个股新闻": {"label": "个股新闻", "emoji": "📊", "order": 3},
    "公告":     {"label": "公告",     "emoji": "📋", "order": 4},
}


def _load_cache():
    """从 data/news_cache.json 加载缓存数据"""
    if not CACHE_PATH.exists():
        return None
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return None


def _flat_items(data, category_filter=""):
    """从缓存数据中提取扁平化的 item 列表"""
    items = []
    categories = data.get("categories", {})
    for cat_name, cat_entries in categories.items():
        if category_filter and cat_name != category_filter:
            continue
        meta = CATEGORY_META.get(cat_name, {})
        if isinstance(cat_entries, list):
            for entry in cat_entries:
                if isinstance(entry, dict):
                    items.append({
                        "category": cat_name,
                        "category_label": meta.get("label", cat_name),
                        "category_emoji": meta.get("emoji", ""),
                        "title": entry.get("title", ""),
                        "content": entry.get("content", "")[:300],
                        "link": entry.get("link", ""),
                        "source": entry.get("source", ""),
                        "published": entry.get("published", ""),
                        "sentiment": entry.get("sentiment", "neutral"),
                        "score": entry.get("score", 0.0),
                        "keywords_found": entry.get("keywords_found", []),
                    })
    return items


def _calc_freshness(timestamp_str):
    """计算缓存新鲜度"""
    try:
        ts = timestamp_str[:19]
        data_dt = (
            _dt.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            if "T" in ts
            else _dt.strptime(ts, "%Y-%m-%d %H:%M:%S")
        )
        days_stale = (_dt.now() - data_dt).days
        freshness = (
            "fresh" if days_stale < 1
            else ("stale" if days_stale < 3 else "expired")
        )
        return days_stale, freshness
    except Exception:
        return 999, "expired"


# ════════════════════════════════════════════════
# API 端点
# ════════════════════════════════════════════════

@router.get("/api/v2/news")
def api_v2_news(category: str = "", limit: int = 50):
    """板块新闻 — 多源聚合（v3: 东方财富+财联社+巨潮）"""
    cache_data = _load_cache()
    if cache_data:
        categories = cache_data.get("categories", {})
        ts = cache_data.get("timestamp", "")
        days_stale, freshness = _calc_freshness(ts)

        items = _flat_items(cache_data, category_filter=category)
        available_cats = list(categories.keys())

        return {
            "total": len(items),
            "timestamp": ts,
            "days_stale": days_stale,
            "freshness": freshness,
            "summary": "",
            "categories": available_cats,
            "sentiment_summary": cache_data.get("sentiment_summary", {}),
            "items": items[:limit],
        }

    # → 回退到旧格式 (domain/news_fetcher.py 遗留缓存)
    if CACHE_PATH.exists():
        with open(CACHE_PATH) as f:
            old_data = json.load(f)
        if old_data and old_data.get("categories"):
            categories = old_data.get("categories", {})
            ts = old_data.get("timestamp", "")
            days_stale, freshness = _calc_freshness(ts)
            items = []
            for cat_name, cat_entries in categories.items():
                if category and cat_name != category:
                    continue
                if isinstance(cat_entries, list):
                    for entry in cat_entries:
                        if isinstance(entry, dict):
                            items.append({
                                "category": cat_name,
                                "title": entry.get("title", ""),
                                "content": entry.get("content", entry.get("summary", ""))[:300],
                                "link": entry.get("link", ""),
                                "source": entry.get("source", ""),
                                "published": entry.get("published", entry.get("date", "")),
                            })
            return {
                "total": len(items),
                "timestamp": ts,
                "days_stale": days_stale,
                "freshness": freshness,
                "summary": old_data.get("summary", ""),
                "categories": list(categories.keys()),
                "items": items[:limit],
            }

    # 最后回退: news_events.json（旧AKShare管线）
    events_path = ROOT / "data" / "news_events.json"
    if events_path.exists():
        with open(events_path) as f:
            events = json.load(f)
        return {
            "total": len(events) if isinstance(events, list) else 0,
            "items": events[:limit] if isinstance(events, list) else [],
            "source": "news_events (旧)",
        }

    return {"total": 0, "items": [], "error": "暂无新闻数据"}


@router.get("/api/v2/news/refresh")
def api_v2_news_refresh():
    """触发新闻刷新 — 调用 news/pipeline.py NewsPipeline.run()"""
    try:
        from news.pipeline import NewsPipeline
        pipeline = NewsPipeline(mode="quick")  # quick 模式更快，刷新用
        result = pipeline.run()
        return {
            "status": "ok",
            "total": result.get("total", 0),
            "timestamp": result.get("timestamp", ""),
            "sentiment_summary": result.get("sentiment_summary", {}),
            "sources": result.get("sources", {}),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/api/v2/news/sources")
def api_v2_news_sources():
    """新闻源列表 v3 — 国产 API 源"""
    sources = [
        {
            "name": "eastmoney_stock_news",
            "label": "东方财富个股新闻",
            "url": "https://search-api-web.eastmoney.com/",
            "category": "个股新闻",
            "enabled": True,
            "type": "api",
        },
        {
            "name": "eastmoney_flash",
            "label": "东方财富 7×24 快讯",
            "url": "https://np-weblist.eastmoney.com/",
            "category": "7×24快讯",
            "enabled": True,
            "type": "api",
        },
        {
            "name": "cls_telegraph",
            "label": "财联社电报",
            "url": "https://www.cls.cn/telegraph",
            "category": "电报快讯",
            "enabled": True,
            "type": "api",
        },
        {
            "name": "cninfo_announcements",
            "label": "巨潮资讯公告",
            "url": "https://www.cninfo.com.cn/",
            "category": "公告",
            "enabled": True,
            "type": "api",
        },
    ]
    return {"total": len(sources), "sources": sources}


@router.get("/api/v2/news/sentiment")
def api_v2_news_sentiment():
    """
    新闻情绪分析 — 从 news_cache.json 读取情绪标签
    支持按类别筛选: ?category=个股新闻
    """
    cache_data = _load_cache()
    if not cache_data:
        return {"error": "暂无情绪分析数据", "sentiments": [], "summary": {}}

    categories = cache_data.get("categories", {})
    all_sentiments = []

    for cat_name, cat_entries in categories.items():
        if isinstance(cat_entries, list):
            for entry in cat_entries:
                if not isinstance(entry, dict):
                    continue
                sentiment = entry.get("sentiment", "neutral")
                all_sentiments.append({
                    "title": entry.get("title", "")[:100],
                    "content": entry.get("content", "")[:200],
                    "sentiment": sentiment,
                    "score": entry.get("score", 0.0),
                    "keywords_found": entry.get("keywords_found", []),
                    "source": entry.get("source", ""),
                    "category": cat_name,
                    "link": entry.get("link", ""),
                })

    sentiment_counts = {"positive": 0, "negative": 0, "neutral": 0}
    for s in all_sentiments:
        sent = s.get("sentiment", "neutral")
        if sent in sentiment_counts:
            sentiment_counts[sent] += 1

    return {
        "total": len(all_sentiments),
        "summary": sentiment_counts,
        "avg_score": cache_data.get("sentiment_summary", {}).get("avg_score", 0.0),
        "sentiments": all_sentiments,
    }


@router.get("/api/v2/news/status")
def api_v2_news_status():
    """获取新闻管线状态（源更新情况 + 缓存新鲜度）"""
    cache_data = _load_cache()
    if not cache_data:
        return {
            "status": "no_cache",
            "message": "暂无缓存数据，请调用 /api/v2/news/refresh 触发首次抓取",
        }

    ts = cache_data.get("timestamp", "")
    days_stale, freshness = _calc_freshness(ts)
    sources = cache_data.get("sources", {})
    sentiment = cache_data.get("sentiment_summary", {})

    return {
        "status": "ok",
        "cached_at": ts,
        "days_stale": days_stale,
        "freshness": freshness,
        "total_items": cache_data.get("total", 0),
        "sources": {
            name: {
                "updated": info.get("updated", ""),
                "count": info.get("count", 0),
            }
            for name, info in sources.items()
        },
        "sentiment_summary": sentiment,
    }
