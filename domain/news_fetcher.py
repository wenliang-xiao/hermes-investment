"""
政经新闻抓取模块 — RSS新闻源聚合 v5.3
升级：总分结构 + 源链接 + 产业链关联分类
面基全市场调研：同等权重关注政经新闻、宏观政策、市场动态、产业消息
"""

import json
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List, Optional

from config import NEWS_SOURCES, DATA_DIR, INDUSTRY_CHAINS

CACHE_FILE = DATA_DIR / "news_cache.json"
CACHE_TTL = 1800  # 30分钟
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MAX_ITEMS_PER_SOURCE = 8
MAX_TOTAL = 20

# ════════════════════════════════════════════
# RSS 新闻抓取
# ════════════════════════════════════════════

def _fetch_rss(url: str, timeout: int = 10) -> Optional[str]:
    """获取RSS源原始XML（支持中文未编码URL）"""
    try:
        # 安全编码URL中的非ASCII字符，保留+号（Google搜索用+表示空格）
        parsed = list(urllib.request.urlsplit(url))
        parsed[2] = urllib.parse.quote(parsed[2], safe="/")
        # 查询串中保留 +=& 三个字符
        parsed[3] = urllib.parse.quote(parsed[3], safe="+=&")
        safe_url = urllib.parse.urlunsplit(parsed)
        
        req = urllib.request.Request(safe_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return None


def _parse_rss_items(xml_text: str) -> List[Dict]:
    """解析RSS XML，提取新闻条目"""
    items = []
    try:
        root = ET.fromstring(xml_text)
        # RSS 2.0: /rss/channel/item
        for item in root.findall(".//item")[:MAX_ITEMS_PER_SOURCE]:
            title = _get_text(item, "title", "")
            link = _get_text(item, "link", "")
            pub_date = _get_text(item, "pubDate", "")
            desc = _get_text(item, "description", "")
            source = _get_text(item, "source", "")
            if title:
                items.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "pub_date": pub_date.strip(),
                    "description": desc.strip()[:200],
                    "source": source.strip(),
                })
    except ET.ParseError:
        pass
    return items


def _get_text(parent, tag: str, default: str = "") -> str:
    """安全提取XML子元素文本"""
    el = parent.find(tag)
    return el.text if el is not None and el.text else default


def _clean_title(title: str) -> str:
    """清理RSS标题（去掉来源后缀）"""
    for sep in [" - ", " – ", " — ", "|"]:
        if sep in title:
            title = title.rsplit(sep, 1)[0]
    return title.strip()


# ════════════════════════════════════════════
# 新闻分类 — 关键词匹配 + 产业链关联 (v5.3)
# ════════════════════════════════════════════

def _categorize(title: str, desc: str, default_cat: str) -> str:
    """基于标题关键词分类（宏观政策 > 大宗商品 > 市场 > 产业, 带产业链标签）"""
    text = (title + " " + desc).lower()
    if any(k in text for k in ["美联储", "央行", "利率", "cpi", "通胀", "加息", "降息", "货币政策", "国务院", "政治局", "中央"]):
        return "宏观政策"
    if any(k in text for k in ["黄金", "原油", "期货", "大宗商品", "铜", "铝", "煤炭"]):
        return "大宗商品"
    if any(k in text for k in ["a股", "港股", "美股", "股市", "上证", "创业板", "科创板", "行情", "涨停", "跌停"]):
        return "市场动态"
    if any(k in text for k in ["ai", "人工智能", "芯片", "半导体", "新能源", "光伏", "电车", "华为"]):
        return "产业趋势"
    return default_cat


def _map_to_chain(title: str, desc: str) -> str:
    """将新闻映射到对应产业链（返回链名或空字符串）"""
    text = (title + " " + desc).lower()
    for chain_name, chain_cfg in INDUSTRY_CHAINS.items():
        for kw in chain_cfg.get("keywords", []):
            if kw.lower() in text:
                return chain_name
    return ""


def _generate_summary(items: List[Dict]) -> str:
    """生成总分结构的总述段落"""
    if not items:
        return "暂未抓取到新闻数据"
    # 按分类统计
    from collections import Counter
    cats = Counter(item.get("category", "综合") for item in items)
    chains = Counter(item.get("chain", "") for item in items if item.get("chain"))

    parts = []
    parts.append(f"共抓取 {len(items)} 条新闻")
    if cats:
        top_cats = cats.most_common(3)
        parts.append(", ".join(f"{c}类{cnt}条" for c, cnt in top_cats))

    if chains:
        top_chains = chains.most_common(2)
        parts.append(f"\n产业链相关: {', '.join(f'{ch}({cnt}条)' for ch, cnt in top_chains)}")

    return " · ".join(parts)


def _deduplicate(items: List[Dict]) -> List[Dict]:
    """去重（按标题关键词）"""
    seen = set()
    result = []
    for item in items:
        key = item["title"][:30]
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


# ════════════════════════════════════════════
# 主函数
# ════════════════════════════════════════════

def fetch_news() -> Dict[str, List[Dict]]:
    """抓取所有新闻源，分类返回"""
    all_items = []
    
    for src_name, src_config in NEWS_SOURCES.items():
        url = src_config["url"]
        default_cat = src_config.get("category", "综合")
        xml_text = _fetch_rss(url)
        if xml_text:
            items = _parse_rss_items(xml_text)
            for item in items:
                item["title"] = _clean_title(item["title"])
                item["category"] = _categorize(item["title"], item.get("description", ""), default_cat)
                item["source_name"] = src_name
            all_items.extend(items)
        time.sleep(0.5)  # 礼貌性间隔

    # 去重
    all_items = _deduplicate(all_items)

    # 按分类聚合
    categorized = {
        "宏观政策": [],
        "市场动态": [],
        "大宗商品": [],
        "产业趋势": [],
        "综合": [],
    }
    for item in all_items[:MAX_TOTAL]:
        cat = item.get("category", "综合")
        if cat not in categorized:
            cat = "综合"
        # 产业链关联映射
        chain = _map_to_chain(item.get("title", ""), item.get("description", ""))
        if chain:
            item["chain"] = chain
            # 也加入"产业链"分类
            if "产业消息" not in categorized:
                categorized["产业消息"] = []
            if len(categorized["产业消息"]) < 10:
                categorized["产业消息"].append(item)
        categorized[cat].append(item)

    # 生成总述
    summary = _generate_summary(all_items[:MAX_TOTAL])

    # 保存缓存
    result = {
        "timestamp": datetime.now().isoformat(),
        "categories": categorized,
        "summary": summary,
        "total": sum(len(v) for v in categorized.values()),
    }
    try:
        CACHE_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception:
        pass

    return result


def load_cached_news() -> Optional[Dict]:
    """读取缓存"""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            ts = data.get("timestamp", "")
            if ts:
                age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
                if age < CACHE_TTL:
                    return data
        except Exception:
            pass
    return None


# ════════════════════════════════════════════
# 格式化输出（供report_builder调用）
# ════════════════════════════════════════════

def format_news_section(data: Optional[Dict] = None) -> str:
    """格式化新闻段落 — 总分结构+源链接 v5.3"""
    if data is None:
        data = load_cached_news()
    if data is None:
        try:
            data = fetch_news()
        except Exception as e:
            return f"📰 **政经新闻**\n  ⚠ 获取失败: {e}"

    total = data.get("total", 0)
    summary = data.get("summary", f"共{total}条新闻")

    lines = ["📰 **政经新闻速览**"]
    # 总述（总分结构的总）
    lines.append(f"> {summary}\n")

    cats = data.get("categories", {})
    priority = [("宏观政策", "🏛"), ("市场动态", "📈"),
                ("大宗商品", "🛢"), ("产业消息", "🏭"), ("产业趋势", "🔬"), ("综合", "📋")]

    for cat, emoji in priority:
        items = cats.get(cat, [])
        if not items:
            continue
        lines.append(f"### {emoji} {cat}（{len(items)}条）")
        for item in items[:5]:
            title = item.get("title", "")
            link = item.get("link", "")
            chain = item.get("chain", "")
            # 用飞书 markdown 链接格式
            if link:
                lines.append(f"  • [{title}]({link}){'  🔗'+chain if chain else ''}")
            else:
                lines.append(f"  • {title}{'  🔗'+chain if chain else ''}")
        lines.append("")

    lines.append(f"> 🕒 更新时间：{data.get('timestamp', '')[:19]}")
    lines.append("> 📡 数据源：Google News RSS")

    return "\n".join(lines)


# ════════════════════════════════════════════
# CLI 测试
# ════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "cache":
        data = load_cached_news()
        if data:
            print("✅ 缓存命中")
        else:
            print("🔄 未命中，重新获取")
            data = fetch_news()
    else:
        data = fetch_news()

    print(format_news_section(data))
    print(f"\n🕒 {data.get('timestamp', '')}")
