"""
中文金融新闻情绪分析模块 v3
基于 cnsenti + 自定义金融情绪词典

回退策略：cnsenti 不可用时自动 fallback 到纯关键词匹配
"""

import re
from typing import Dict, List, Optional

# ════════════════════════════════════════════════
# 自定义金融情绪词典
# ════════════════════════════════════════════════

FINANCIAL_SENTIMENT_DICT = {
    "strong_positive": [
        "涨停", "大涨", "突破", "中标", "签约", "获批",
        "增持", "回购", "分红", "超预期", "量产", "创新高",
    ],
    "positive": [
        "增长", "利好", "回暖", "回升", "扩张", "合作",
        "加速", "提振", "改善", "反弹", "盈利", "扭亏",
    ],
    "strong_negative": [
        "跌停", "大跌", "暴雷", "亏损", "退市", "立案",
        "调查", "处罚", "停产", "召回", "违约", "破产",
    ],
    "negative": [
        "下跌", "利空", "下滑", "萎缩", "减持", "诉讼",
        "降级", "警告", "风险", "亏损", "暴跌", "违规",
    ],
}

WEIGHTS = {
    "strong_positive": 1.0,
    "positive": 0.5,
    "strong_negative": -1.0,
    "negative": -0.5,
}


# ════════════════════════════════════════════════
# cnsenti 封装
# ════════════════════════════════════════════════

_cnsenti_available = False
_sentiment_tool = None

try:
    from cnsenti import Sentiment
    _sentiment_tool = Sentiment()
    _cnsenti_available = True
except ImportError:
    _cnsenti_available = False


def _cnsenti_analyze(text: str) -> Optional[Dict]:
    """使用 cnsenti 分析单条文本的情感分数"""
    if not _cnsenti_available or not _sentiment_tool:
        return None
    if not text or len(text.strip()) < 2:
        return None
    try:
        result = _sentiment_tool.sentiment_count(text)
        pos = result.get("pos", 0) or 0
        neg = result.get("neg", 0) or 0
        total = pos + neg
        if total == 0:
            return {"score": 0.0, "label": "neutral", "raw": {"pos": pos, "neg": neg}}
        # 映射为 -1.0 ~ 1.0
        score = round((pos - neg) / total, 4)
        label = "positive" if score > 0.1 else ("negative" if score < -0.1 else "neutral")
        return {"score": score, "label": label, "raw": {"pos": pos, "neg": neg}}
    except Exception:
        return None


def _keyword_analyze(text: str) -> Dict:
    """纯关键词匹配的情绪分析（cnsenti 不可用时的 fallback）"""
    if not text:
        return {"sentiment": "neutral", "score": 0.0, "keywords_found": []}

    found = []
    total_weight = 0.0

    for category, keywords in FINANCIAL_SENTIMENT_DICT.items():
        weight = WEIGHTS.get(category, 0.0)
        for kw in keywords:
            if kw in text:
                found.append((kw, category, weight))

    if not found:
        return {"sentiment": "neutral", "score": 0.0, "keywords_found": []}

    max_abs_weight = max(abs(w) for _, _, w in found)
    total_weight = sum(w for _, _, w in found)
    # 限制在 [-1.0, 1.0]
    score = max(-1.0, min(1.0, total_weight / len(found)))

    if score >= 0.15:
        sentiment = "positive"
    elif score <= -0.15:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    return {
        "sentiment": sentiment,
        "score": round(score, 4),
        "keywords_found": [kw for kw, _, _ in found],
    }


# ════════════════════════════════════════════════
# 公共接口
# ════════════════════════════════════════════════

def analyze_sentiment(text: str) -> Dict:
    """
    分析单条文本的情绪

    Args:
        text: 待分析的文本

    Returns:
        {
            sentiment: "positive" / "negative" / "neutral",
            score: -1.0 ~ 1.0,
            keywords_found: [...],
            method: "cnsenti" / "keyword",
        }
    """
    if not text or len(text.strip()) < 2:
        return {
            "sentiment": "neutral",
            "score": 0.0,
            "keywords_found": [],
            "method": "empty",
        }

    # 合并标题类关键词快速判断
    quick = _keyword_analyze(text)
    if abs(quick["score"]) >= 0.3:
        quick["method"] = "keyword"
        return quick

    # 使用 cnsenti 做更精确的分析
    if _cnsenti_available:
        cnsenti_result = _cnsenti_analyze(text)
        if cnsenti_result is not None:
            # 融合两套结果
            combined_score = round(
                cnsenti_result["score"] * 0.6 + quick["score"] * 0.4,
                4
            )
            if combined_score >= 0.1:
                sentiment = "positive"
            elif combined_score <= -0.1:
                sentiment = "negative"
            else:
                sentiment = "neutral"

            return {
                "sentiment": sentiment,
                "score": combined_score,
                "keywords_found": quick["keywords_found"],
                "method": "cnsenti+keyword",
                "cnsenti_raw": cnsenti_result.get("raw"),
            }

    # Fallback: 纯关键词
    quick["method"] = "keyword"
    return quick


def analyze_batch(news_items: List[Dict]) -> List[Dict]:
    """
    批量分析新闻情绪

    Args:
        news_items: 新闻条目列表，每项需有 title/content 字段

    Returns:
        原列表，每项增加了 sentiment, score, keywords_found 字段
    """
    results = []
    for item in news_items:
        if not isinstance(item, dict):
            results.append(item)
            continue

        # 用 title + content 的组合进行分析
        combined_text = (
            (item.get("title") or "") + " " +
            (item.get("content") or "")
        )
        sentiment_result = analyze_sentiment(combined_text)

        item["sentiment"] = sentiment_result["sentiment"]
        item["score"] = sentiment_result["score"]
        item["keywords_found"] = sentiment_result.get("keywords_found", [])
        results.append(item)

    return results


def summarize_sentiments(news_items: List[Dict]) -> Dict:
    """
    从新闻列表汇总情绪统计

    Returns:
        {
            "positive": N,
            "negative": N,
            "neutral": N,
            "total": N,
            "avg_score": float,
        }
    """
    counts = {"positive": 0, "negative": 0, "neutral": 0}
    scores = []

    for item in news_items:
        if not isinstance(item, dict):
            continue
        sentiment = item.get("sentiment", "neutral")
        if sentiment in counts:
            counts[sentiment] += 1
        scores.append(item.get("score", 0.0))

    avg_score = round(sum(scores) / len(scores), 4) if scores else 0.0

    return {
        "positive": counts["positive"],
        "negative": counts["negative"],
        "neutral": counts["neutral"],
        "total": sum(counts.values()),
        "avg_score": avg_score,
    }
