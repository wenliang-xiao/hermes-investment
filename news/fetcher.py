"""
新闻多源抓取模块 v3 — 东方财富 + 财联社 + 巨潮
纯 urllib.request，无外部 HTTP 依赖

每个函数返回 List[Dict]，字段统一：
  {title, content, link, source, published, sentiment_hint}
"""

import json
import time
import urllib.request
import urllib.parse
import re
from datetime import datetime

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
REQUEST_DELAY = 1.0  # 请求间隔（秒）
TIMEOUT = 15
_LAST_REQUEST_TIME = 0.0


def _rate_limit():
    """保证连续调用之间有至少 1s 间隔"""
    global _LAST_REQUEST_TIME
    now = time.time()
    elapsed = now - _LAST_REQUEST_TIME
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)
    _LAST_REQUEST_TIME = time.time()


def _http_get(url, referer=None, timeout=TIMEOUT):
    """HTTP GET → 解码文本，失败返回 None"""
    _rate_limit()
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"_http_get failed: {url[:60]} — {e}")
        return None


def _extract_jsonp(text, callback_prefix="jQuery"):
    """从 JSONP 字符串中提取 JSON 部分"""
    if not text:
        return None
    # 匹配 callback( ... )
    m = re.search(rf'{re.escape(callback_prefix)}\w*\s*\(\s*(.+)\s*\)\s*$', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 尝试直接当作 JSON 解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ════════════════════════════════════════════════
# 东方财富 — 个股新闻
# ════════════════════════════════════════════════

def fetch_eastmoney_stock_news(symbol, limit=10):
    """
    东方财富个股新闻搜索
    API: search-api-web.eastmoney.com/search/jsonp

    Args:
        symbol: 股票代码 (如 "300502", "600519")
        limit: 最大返回条数

    Returns:
        [{title, content, link, source, published, sentiment_hint}]
    """
    param_dict = {
        "uid": "",
        "keyword": str(symbol),
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": min(limit, 20),
                "preTag": " ",
                "postTag": " ",
            }
        },
    }
    param_json = json.dumps(param_dict, ensure_ascii=False, separators=(",", ":"))
    encoded = urllib.parse.quote(param_json)
    url = (
        "https://search-api-web.eastmoney.com/search/jsonp"
        "?cb=jQuery&param=" + encoded
    )

    text = _http_get(
        url,
        referer=f"https://so.eastmoney.com/news/s?keyword={symbol}"
    )
    if not text:
        return []

    data = _extract_jsonp(text)
    if not data:
        return []

    results = []
    result_obj = data.get("result", {}) if isinstance(data, dict) else {}
    articles = result_obj.get("cmsArticleWebOld", [])
    if not isinstance(articles, list):
        articles = []

    for item in articles[:limit]:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": (item.get("title") or "").strip(),
            "content": (item.get("content") or "").strip()[:300],
            "link": item.get("url") or "",
            "source": "东方财富",
            "published": (item.get("date") or "")[:19],
            "sentiment_hint": "",
        })

    return results


# ════════════════════════════════════════════════
# 东方财富 — 7×24 快讯
# ════════════════════════════════════════════════

def fetch_eastmoney_flash():
    """
    东方财富 7×24 滚动快讯
    API: np-weblist.eastmoney.com/comm/web/getFastNewsList

    返回:
        [{title, content, link, source, published, sentiment_hint}]
    """
    import uuid

    req_trace = str(uuid.uuid4()).replace("-", "")
    url = (
        "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
        "?client=web&biz=web_724&fastColumn=102&pageSize=30&sortEnd=0"
        f"&req_trace={req_trace}"
    )
    text = _http_get(url, referer="https://kuaixun.eastmoney.com/")
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    results = []
    items = []

    if isinstance(data, dict):
        inner = data.get("data", {})
        if isinstance(inner, dict):
            items = inner.get("fastNewsList", [])

    for item in items[:30]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        summary = item.get("summary") or ""
        code = item.get("code") or ""
        show_time = item.get("showTime") or ""
        stock_list = item.get("stockList") or []

        # 链接: 东方财富快讯详情页
        link = ""
        if code:
            link = f"https://finance.eastmoney.com/a/{code}.html"

        # 关联股票标记
        stock_hint = ""
        if stock_list:
            stock_hint = ",".join(
                s.replace(".BK", "").replace("90.", "") for s in stock_list[:3]
            )

        content = summary if summary else title
        full_title = f"{title}" if not stock_hint else f"{title} [{stock_hint}]"

        results.append({
            "title": full_title.strip(),
            "content": content.strip()[:300],
            "link": link,
            "source": "东方财富7×24",
            "published": show_time,
            "sentiment_hint": "",
        })

    return results


# ════════════════════════════════════════════════
# 财联社 — 电报快讯
# ════════════════════════════════════════════════

def fetch_cls_telegraph(limit=30):
    """
    财联社电报快讯 (24小时滚动)
    API: www.cls.cn/api/cache?name=telegraph

    返回:
        [{title, content, link, source, published, sentiment_hint}]
    """
    url = (
        "https://www.cls.cn/api/cache"
        "?name=telegraph&app=CailianpressWeb&os=web&sv=8.7.9"
    )
    text = _http_get(url, referer="https://www.cls.cn/telegraph")
    if not text:
        return []

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    results = []
    items = []

    if isinstance(data, dict):
        inner = data.get("data", {})
        if isinstance(inner, dict):
            items = inner.get("roll_data", [])

    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        brief = item.get("brief") or ""
        content = item.get("content") or brief or title
        article_id = str(item.get("id") or "")
        ctime = item.get("ctime", 0)

        link = ""
        if article_id:
            link = f"https://www.cls.cn/detail/{article_id}"

        published = ""
        if ctime:
            try:
                published = datetime.fromtimestamp(int(ctime)).strftime(
                    "%Y-%m-%dT%H:%M:%S"
                )
            except (ValueError, OSError):
                published = str(ctime)

        if not title and not content:
            continue

        results.append({
            "title": str(title).strip()[:200],
            "content": str(content).strip()[:300],
            "link": link,
            "source": "财联社",
            "published": published,
            "sentiment_hint": "",
        })

    return results


# ════════════════════════════════════════════════
# 巨潮资讯 — 公告
# ════════════════════════════════════════════════

def fetch_cninfo_announcements(symbol, limit=5):
    """
    巨潮资讯网公告查询
    优先使用 eastmoney 搜索 API 的公告类型 (8196)
    cninfo.com.cn 需要 cookie 会话，不稳定时回退

    Args:
        symbol: 股票代码 (6位数字, 如 "600519")
        limit: 最大返回条数

    Returns:
        [{title, content, link, source, published, sentiment_hint}]
    """
    code = str(symbol).zfill(6)

    results = _fetch_eastmoney_announcements(symbol, limit)
    if results:
        return results

    return _fetch_cninfo_direct(code, limit)


def _fetch_eastmoney_announcements(symbol, limit=5):
    """使用东方财富搜索 API 获取公告（类型8196）"""
    param_dict = {
        "uid": "",
        "keyword": str(symbol),
        "type": ["8196"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "8196": {
                "searchScope": "default",
                "sort": "default",
                "pageIndex": 1,
                "pageSize": min(limit, 20),
                "preTag": " ",
                "postTag": " ",
            }
        },
    }
    param_json = json.dumps(param_dict, ensure_ascii=False, separators=(",", ":"))
    encoded = urllib.parse.quote(param_json)
    url = (
        "https://search-api-web.eastmoney.com/search/jsonp"
        "?cb=jQuery&param=" + encoded
    )
    text = _http_get(
        url,
        referer=f"https://so.eastmoney.com/news/s?keyword={symbol}"
    )
    if not text:
        return []

    data = _extract_jsonp(text)
    if not data:
        return []

    results = []
    result_obj = data.get("result", {}) if isinstance(data, dict) else {}
    articles = result_obj.get("8196", [])
    if not isinstance(articles, list):
        articles = []

    for item in articles[:limit]:
        if not isinstance(item, dict):
            continue
        results.append({
            "title": (item.get("title") or "").strip(),
            "content": (item.get("content") or "").strip()[:300],
            "link": item.get("url") or "",
            "source": "东方财富公告",
            "published": (item.get("date") or "")[:19],
            "sentiment_hint": "",
        })

    return results


def _fetch_cninfo_direct(code, limit=5):
    """直接请求巨潮资讯 API（需要 cookie 支持，可能不稳定）"""
    import http.cookiejar

    try:
        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar)
        )

        _rate_limit()
        base_headers = {
            "User-Agent": UA,
            "Referer": "https://www.cninfo.com.cn/",
        }
        base_req = urllib.request.Request(
            "https://www.cninfo.com.cn/", headers=base_headers
        )
        opener.open(base_req, timeout=TIMEOUT)

        _rate_limit()
        search_data = urllib.parse.urlencode({
            "pageNum": 1,
            "pageSize": limit,
            "column": "szse",
            "stock": code,
            "tabName": "fulltext",
            "category": "category_ndbg_szsh",
        }).encode()
        search_req = urllib.request.Request(
            "https://www.cninfo.com.cn/new/hisAnnouncement/query",
            data=search_data,
            headers={
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": "https://www.cninfo.com.cn/",
            },
            method="POST",
        )
        resp = opener.open(search_req, timeout=TIMEOUT)
        text = resp.read().decode("utf-8", errors="replace")

        data = json.loads(text)
        results = []
        announcements = data.get("announcements") or []

        for item in announcements[:limit]:
            if not isinstance(item, dict):
                continue
            title = item.get("announcementTitle") or item.get("shortTitle") or ""
            sec_name = item.get("secName") or ""
            ann_id = str(item.get("id") or item.get("announcementId") or "")
            date_str = str(
                item.get("announcementTime") or item.get("publishDate", "")
            )[:10]

            full_title = f"[{code} {sec_name}] {title}" if sec_name else title

            link = ""
            if ann_id:
                link = (
                    f"https://www.cninfo.com.cn/new/disclosure/detail"
                    f"?orgId={ann_id}&announcementId={ann_id}"
                    f"&announcementTime={date_str}"
                )

            results.append({
                "title": full_title.strip()[:200],
                "content": title.strip()[:300],
                "link": link,
                "source": "巨潮资讯",
                "published": date_str,
                "sentiment_hint": "",
            })

        return results
    except Exception:
        return []


# ════════════════════════════════════════════════
# 便捷聚合接口
# ════════════════════════════════════════════════

def fetch_all_sources(symbols=None, stock_limit=10, telegraph_limit=30, announcement_limit=5):
    """
    一次性从所有源抓取新闻，便于 pipeline 直接调用

    Args:
        symbols: 股票代码列表（None 则只抓快讯/电报）
        stock_limit: 每只个股最多新闻数
        telegraph_limit: 快讯最多条数
        announcement_limit: 每只个股最多公告数

    Returns:
        {
            "flash": [...],          # 7x24 快讯
            "telegraph": [...],      # 财联社电报
            "stock_news": [...],     # 个股新闻
            "announcements": [...],  # 公告
        }
    """
    result = {
        "flash": [],
        "telegraph": [],
        "stock_news": [],
        "announcements": [],
    }

    # 快讯 & 电报（不依赖 symbols）
    result["flash"] = fetch_eastmoney_flash()
    result["telegraph"] = fetch_cls_telegraph(limit=telegraph_limit)

    # 个股新闻 & 公告
    if symbols:
        for sym in symbols[:30]:  # 限制最多 30 只，避免请求过多
            news_items = fetch_eastmoney_stock_news(sym, limit=stock_limit)
            result["stock_news"].extend(news_items)
            time.sleep(0.5)  # 礼貌间隔

            ann_items = fetch_cninfo_announcements(sym, limit=announcement_limit)
            result["announcements"].extend(ann_items)
            time.sleep(0.5)

    return result


# ════════════════════════════════════════════════
# CLI 测试
# ════════════════════════════════════════════════

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)

    print("=== 东方财富 7×24 快讯 ===")
    flash = fetch_eastmoney_flash()
    for f in flash[:5]:
        print(f"  [{f['source']}] {f['content'][:80]}")

    print(f"\n=== 财联社电报 ===")
    teleg = fetch_cls_telegraph(limit=10)
    for t in teleg[:5]:
        print(f"  [{t['source']}] {t['title'][:80]}")

    print(f"\n=== 东方财富个股新闻 (300502 新易盛) ===")
    stock = fetch_eastmoney_stock_news("300502", limit=5)
    for s in stock[:5]:
        print(f"  [{s['source']}] {s['title'][:80]}")

    print(f"\n=== 巨潮公告 (600519 贵州茅台) ===")
    ann = fetch_cninfo_announcements("600519", limit=5)
    for a in ann[:5]:
        print(f"  [{a['source']}] {a['title'][:80]}")
