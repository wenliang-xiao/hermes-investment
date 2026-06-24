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
    events = fetch_all_stock_events(core_symbols, days=5)
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

    return {"events": events, "summary": summary}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="新闻管线")
    parser.add_argument("--mode", choices=["full", "quick"], default="full")
    args = parser.parse_args()
    run(mode=args.mode)