"""新闻管线 v2 - 多源分级聚合
Tier 1: AKShare 个股新闻(东方财富)
Tier 2: GLM-4-Flash 宏观/板块级新闻分析

用法:
  python3 -u scripts/news_pipeline.py               # 全量运行
  python3 -u scripts/news_pipeline.py --mode quick  # 仅Tier1
"""
import sys, os, json, subprocess, urllib.request
from datetime import datetime, date, timedelta
import re

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_DIR)

import functools
print = functools.partial(print, flush=True)

from domain import WATCHLIST

# ═══════════════════════════════════════════
# 数据目录
# ═══════════════════════════════════════════
DATA_DIR = os.path.join(_PROJECT_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# ═══════════════════════════════════════════
# Tier 1: AKShare 个股新闻
# ═══════════════════════════════════════════
def fetch_stock_events_akshare(symbol, limit=10):
    """获取个股新闻 via AKShare stock_news_em"""
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=symbol, limit=limit)
        if df is None or df.empty:
            return []
        events = []
        for _, row in df.iterrows():
            ev = {}
            for c in df.columns:
                ev[c.lower()] = str(row[c])[:300]
            ev["symbol"] = symbol
            events.append(ev)
        return events
    except Exception as e:
        return [{"symbol": symbol, "error": str(e)[:100]}]


def fetch_all_stock_events(symbols, limit=5):
    """批量获取个股新闻"""
    result = {}
    for sym in symbols:
        evs = fetch_stock_events_akshare(sym, limit=limit)
        if evs:
            result[sym] = evs
    return result


# ═══════════════════════════════════════════
# Tier 2: GLM-4-Flash 新闻分析
# ═══════════════════════════════════════════
def analyze_with_glm(prompt, max_tokens=1000):
    """调用GLM-4-Flash分析新闻"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        api_key = os.environ.get("ARK_API_KEY", "")
        if not api_key:
            return "API key not configured"

        url = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
        data = {
            "model": "glm-4-flash",
            "messages": [
                {"role": "system", "content": "你是一个金融新闻分析师，擅长从新闻中提取对A股投资有价值的信息。简洁、专业。输出格式：bullet point列表。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST"
        )
        resp = urllib.request.urlopen(req, timeout=30)
        result = json.loads(resp.read())
        return result.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        return f"GLM分析失败: {e}"


def generate_news_summary(events_by_symbol):
    """从个股新闻事件生成分析摘要"""
    if not events_by_symbol:
        return "今日无个股新闻"

    summary_parts = []
    for sym, evs in list(events_by_symbol.items())[:10]:
        info = WATCHLIST.get(sym, {})
        name = info.get("name", sym) if isinstance(info, dict) else str(info)

        # 提取新闻标题
        titles = []
        for ev in evs[:3]:
            title = ev.get("新闻标题", ev.get("title", ev.get("content", "")))
            if title and len(title) > 5:
                titles.append(title[:120])
        if titles:
            summary_parts.append(f"• {sym}({name}): {'; '.join(titles)}")

    if not summary_parts:
        return "今日无显著新闻"

    base = "\n".join(summary_parts[:8])

    prompt = f"""以下是今日A股个股新闻，请从投资角度分析哪些可能对持股或核心关注标的有实质性影响：

{base}

按影响程度排序输出（利好/利空/中性），每行一条。"""
    analysis = analyze_with_glm(prompt, 800)

    return f"{base}\n\n📊 GLM分析:\n{analysis}"


# ═══════════════════════════════════════════
# Tier 3: 新闻→评分偏移
# ═══════════════════════════════════════════
def compute_news_scoring_offset(events_by_symbol: dict[str, list]) -> dict[str, dict]:
    """从新闻分析结果计算每只标的的评分偏移

    规则:
        - 正面新闻 → +0.3 ~ +0.5 (取决于强度)
        - 负面新闻 → -0.3 ~ -0.5
        - 中性新闻 → 0
        - 重大利好 → +1.0 (如并购/业绩暴增)
        - 重大利空 → -1.0 (如监管/退市风险)

    Returns:
        {symbol: {"offset": float, "reason": str, "articles": int}}
    """
    offsets = {}

    for sym, events in events_by_symbol.items():
        if not events:
            continue

        # 收集所有标题
        titles = []
        for ev in events[:5]:
            title = ev.get("新闻标题", ev.get("title", ev.get("content", "")))
            if title and len(title) > 5:
                titles.append(title[:200])

        if not titles:
            continue

        # 简单关键词情绪分析
        scores = []
        reasons = []

        for title in titles:
            title_lower = title.lower()

            # 强正面信号
            strong_positive = ["涨停", "大涨", "突破", "创新高", "业绩大增", "翻倍",
                               "中标", "拿下", "签约", "投产", "量产",
                               "获批", "注册", "准入", "纳入"]
            # 正面信号
            positive = ["增长", "利好", "回暖", "回升", "扩张", "合作", "增持",
                        "回购", "分红", "超预期", "加速", "提振"]
            # 强负面信号
            strong_negative = ["跌停", "大跌", "暴雷", "亏损", "退市", "st",
                               "立案", "调查", "处罚", "停产", "召回",
                               "违约", "破产", "清算"]
            # 负面信号
            negative = ["下跌", "利空", "下滑", "萎缩", "减持", "减持",
                        "诉讼", "仲裁", "降级", "警告", "风险"]

            score = 0.0
            reason = ""

            if any(kw in title_lower for kw in strong_positive):
                score += 1.0
                reason += "重大利好 "
            elif any(kw in title_lower for kw in strong_negative):
                score -= 1.0
                reason += "重大利空 "

            if any(kw in title_lower for kw in positive):
                score += 0.3
                reason += "利好 "
            elif any(kw in title_lower for kw in negative):
                score -= 0.3
                reason += "利空 "

            scores.append(score)
            if score != 0:
                reasons.append(reason.strip())

        if scores:
            avg_score = sum(scores) / len(scores)
            # 限制偏移范围 [-0.5, +0.5] or [-1.0, +1.0] for strong signals
            offset_val = max(-1.0, min(1.0, avg_score))
            # 只有有明显倾向的才保存
            if abs(offset_val) >= 0.2:
                offsets[sym] = {
                    "offset": round(offset_val, 2),
                    "reason": "; ".join(reasons[:3]) if reasons else "新闻情绪分析",
                    "articles": len(titles),
                    "titles": titles[:3],
                }

    return offsets


# ═══════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════
def run(mode="full"):
    """主流程"""
    print(f"{'='*50}")
    print(f"📰 新闻管线 v2 · {date.today()}")
    print(f"{'='*50}")

    # 从WATCHLIST获取核心标的
    core_symbols = []
    for code, info in WATCHLIST.items():
        sym = str(code)
        if sym.isdigit():
            tier = info.get("tier", "") if isinstance(info, dict) else ""
            if tier in ("核心", "底仓", "关注"):
                core_symbols.append(sym)

    print(f"\n📡 Tier 1: AKShare个股事件 ({len(core_symbols)}只)")
    events = fetch_all_stock_events(core_symbols, limit=5)
    total = sum(len(v) for v in events.values())
    syms_with_events = len(events)
    print(f"   {total}条事件 · {syms_with_events}只有事件")

    news_path = os.path.join(DATA_DIR, "news_events.json")
    with open(news_path, "w") as f:
        json.dump({
            "date": str(date.today()),
            "time": datetime.now().strftime("%H:%M"),
            "total_events": total,
            "symbols_with_events": syms_with_events,
            "events": {k: v[:5] for k, v in events.items()}  # 每只最多5条
        }, f, ensure_ascii=False, indent=2)
    print(f"   💾 已保存: {news_path}")

    if mode == "quick":
        return

    # Tier 2: GLM分析
    print(f"\n🧠 Tier 2: GLM-4-Flash分析...")
    summary = generate_news_summary(events)
    print(summary)

    # 保存摘要
    summary_path = os.path.join(DATA_DIR, "news_summary.txt")
    with open(summary_path, "w") as f:
        f.write(summary)
    print(f"   💾 已保存: {summary_path}")

    # Tier 3: 新闻→评分偏移
    print(f"\n📊 Tier 3: 新闻→评分偏移...")
    try:
        offset = compute_news_scoring_offset(events)
        offset_path = os.path.join(DATA_DIR, "news_score_offset.json")
        with open(offset_path, "w") as f:
            json.dump(offset, f, ensure_ascii=False, indent=2)
        total_offset = sum(abs(v["offset"]) for v in offset.values())
        print(f"   {len(offset)} 只有偏移, 总偏移量{total_offset:.1f}")
    except Exception as e:
        print(f"   WARNING: offset failed: {e}")

    return {"events": events, "summary": summary}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="新闻管线")
    parser.add_argument("--mode", choices=["full", "quick"], default="full")
    args = parser.parse_args()
    run(mode=args.mode)