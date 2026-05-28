"""
异动股新闻联动引擎 v1.0

核心逻辑：
  价格异动（单日涨跌≥5%）→ 自动搜索个股新闻 + 市场电报
  → LLM联动分析：这次异动是什么驱动的？该怎么应对？

数据源优先级：
  1. ak.stock_news_em(symbol)  — 东方财富个股新闻（最近100条）
  2. ak.stock_info_global_cls  — 财联社重点电报（实时性最好）
  3. ak.stock_info_global_sina — 新浪财经快讯

输出格式（供日报情报板块使用）：
  每只异动股 → 驱动因素（1-2句）+ 建议动作 + 置信度
"""
import os
import json
import time
import signal
import socket
from datetime import datetime, timedelta
from typing import Dict, List, Optional

socket.setdefaulttimeout(8)  # 全局socket超时8秒

class _TimeLimitError(Exception):
    pass

def _timeout_call(seconds, func, *args, **kwargs):
    """信号超时包装器——用于AKShare等不遵守socket超时的调用"""
    def _handler(signum, frame):
        raise _TimeLimitError(f"调用超时（{seconds}s限制）")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        result = func(*args, **kwargs)
        return result
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def _fetch_stock_news_ak(symbol: str, name: str) -> List[Dict]:
    try:
        import akshare as ak
        df = ak.stock_news_em(symbol=symbol)
        if df is None or df.empty:
            return []
        cutoff = datetime.now() - timedelta(days=3)
        results = []
        for _, row in df.iterrows():
            try:
                pub_str = str(row.get("发布时间", ""))
                pub_dt = datetime.strptime(pub_str[:10], "%Y-%m-%d") if pub_str else datetime.now()
                if pub_dt < cutoff:
                    continue
            except Exception:
                pass
            results.append({
                "title": str(row.get("新闻标题", "")),
                "summary": str(row.get("新闻内容", ""))[:200],
                "source": str(row.get("新闻来源", "东方财富")),
                "time": str(row.get("发布时间", "")),
                "stock": name,
                "symbol": symbol,
            })
        return results[:15]
    except Exception as e:
        print(f"  [anomaly_news] ak.stock_news_em({symbol}) 失败: {e}")
        return []


def _fetch_cls_flash() -> List[Dict]:
    try:
        import akshare as ak
        df = _timeout_call(15, ak.stock_info_global_cls, symbol="重点")
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            title = str(row.get("标题", "") or row.get("内容", ""))
            if not title or len(title) < 5:
                continue
            results.append({
                "title": title,
                "summary": str(row.get("内容", ""))[:200],
                "source": "财联社",
                "time": str(row.get("发布时间", "") or row.get("发布日期", "")),
            })
        return results[:20]
    except Exception as e:
        print(f"  [anomaly_news] CLS电报失败: {e}")
        return []


def _fetch_sina_flash() -> List[Dict]:
    try:
        import akshare as ak
        df = _timeout_call(15, ak.stock_info_global_sina)
        if df is None or df.empty:
            return []
        results = []
        for _, row in df.iterrows():
            content = str(row.get("内容", "") or row.get("标题", ""))
            if not content or len(content) < 10:
                continue
            results.append({
                "title": content[:150],
                "summary": "",
                "source": "新浪财经",
                "time": str(row.get("时间", "")),
            })
        return results[:15]
    except Exception as e:
        print(f"  [anomaly_news] 新浪快讯失败: {e}")
        return []


def _call_llm_for_anomaly(prompt: str) -> Optional[str]:
    ark_key = os.environ.get("ARK_API_KEY", "")
    ark_model = os.environ.get("ARK_MODEL", "")
    openai_key = os.environ.get("OPENAI_API_KEY", "")

    if ark_key and ark_model:
        api_url = os.environ.get("ARK_API_BASE", "https://ark.cn-beijing.volces.com/api/v3/chat/completions")
        model = ark_model
        api_key = ark_key
    elif openai_key:
        api_url = os.environ.get("OPENAI_API_BASE", "https://api.openai.com/v1/chat/completions")
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        api_key = openai_key
    else:
        return None

    import json as _json
    import urllib.request
    system = (
        "你是一名专业投资研究助理。你的任务是根据个股异动数据和相关新闻，"
        "判断异动的驱动因素，并给出简洁的应对建议。只输出事实分析，不提供投资建议。"
    )
    payload = _json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
    }).encode("utf-8")

    try:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        req = urllib.request.Request(api_url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            return content if content and content.strip() else None
    except Exception as e:
        print(f"  [anomaly_news] LLM调用失败: {e}")
        return None


def _build_anomaly_prompt(stock_name: str, symbol: str, chg: float,
                           price: float, stock_news: List[Dict],
                           market_news: List[Dict]) -> str:
    chg_str = f"{'大涨' if chg > 0 else '大跌'}{abs(chg):.1f}%"

    stock_news_text = ""
    if stock_news:
        stock_news_text = "\n".join(
            f"- [{n['time'][:10]}][{n['source']}] {n['title']}"
            for n in stock_news[:8]
        )
    else:
        stock_news_text = "（未找到个股专属新闻）"

    market_news_text = ""
    if market_news:
        relevant = [n for n in market_news if
                    any(kw in n["title"] for kw in [stock_name, symbol,
                        "半导体", "AI", "芯片", "华为", "政策", "利率",
                        "美联储", "关税", "制裁"])][:5]
        if not relevant:
            relevant = market_news[:5]
        market_news_text = "\n".join(
            f"- [{n['source']}] {n['title'][:100]}"
            for n in relevant
        )
    else:
        market_news_text = "（市场快讯获取失败）"

    return f"""今日价格异动：{stock_name}({symbol}) {chg_str}，现价¥{price:.2f}

【个股相关新闻（近3天）】
{stock_news_text}

【今日市场重要快讯】
{market_news_text}

请完成以下分析（每条≤40字，格式严格如下）：

驱动因素：[用一句话说明最可能的涨跌原因，必须引用具体新闻]
逻辑真实性：[基本面驱动/消息面驱动/情绪驱动/不明] + [一句判断理由]
建议动作：[无需操作/关注回调/等待数据验证/触发止损检查] + [原因]
注意事项：[一条最重要的风险或机会提示]"""


def analyze_anomaly_stocks(
    flagged_stocks: List[Dict],
    min_chg_pct: float = 5.0,
) -> List[Dict]:
    """
    对当日异动股票进行新闻联动分析。

    参数:
        flagged_stocks: 来自观察池的异动票列表，每条包含
                        symbol, name, chg, price 字段
        min_chg_pct: 触发分析的最小涨跌幅（默认5%）

    返回:
        每只异动股的分析结果列表
    """
    targets = [
        s for s in flagged_stocks
        if isinstance(s.get("chg"), (int, float)) and abs(s["chg"]) >= min_chg_pct
    ]

    if not targets:
        return []

    print(f"[anomaly_news] 触发分析: {len(targets)} 只异动股 (≥{min_chg_pct}%)")

    cls_news = _fetch_cls_flash()
    sina_news = _fetch_sina_flash()
    market_news = cls_news + sina_news
    print(f"[anomaly_news] 市场快讯: CLS {len(cls_news)} 条 + 新浪 {len(sina_news)} 条")

    results = []
    for stock in targets[:5]:
        symbol = stock.get("symbol", "")
        name = stock.get("name", symbol)
        chg = float(stock.get("chg", 0))
        price = float(stock.get("price", 0))

        print(f"  → 分析 {name}({symbol}) {chg:+.1f}%...")

        stock_news = _fetch_stock_news_ak(symbol, name)
        print(f"     个股新闻: {len(stock_news)} 条")

        llm_result = None
        if stock_news or market_news:
            prompt = _build_anomaly_prompt(name, symbol, chg, price, stock_news, market_news)
            llm_result = _call_llm_for_anomaly(prompt)

        results.append({
            "symbol": symbol,
            "name": name,
            "chg": chg,
            "price": price,
            "stock_news_count": len(stock_news),
            "llm_analysis": llm_result,
            "top_news": stock_news[:3],
            "analyzed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        })

        time.sleep(1)

    return results


def format_anomaly_analysis_for_report(results: List[Dict]) -> List[tuple]:
    """将分析结果转换为飞书文档行（供 run_daily.py 使用）"""
    if not results:
        return []

    lines = []
    lines.append(("bold", "🔍 今日异动解读（价格信号×新闻联动）"))

    for r in results:
        chg = r.get("chg", 0)
        arrow = "🔺" if chg > 0 else "🔻"
        header = f"{arrow} **{r['name']}**({r['symbol']}) {chg:+.1f}%"
        lines.append(("bullet", header))

        analysis = r.get("llm_analysis")
        if analysis:
            for line in analysis.strip().split("\n"):
                line = line.strip()
                if line:
                    lines.append(("bullet", f"  {line[:150]}"))
        else:
            top_news = r.get("top_news", [])
            if top_news:
                n = top_news[0]
                lines.append(("bullet",
                    f"  📰 {n['source']} [{n['time'][:10]}]: {n['title'][:100]}"))
            else:
                lines.append(("bullet", "  ℹ️ 暂未找到相关新闻，建议手动检索驱动因素"))

    return lines
