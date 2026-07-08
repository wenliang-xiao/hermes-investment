#!/usr/bin/env python3
"""
多源新闻引擎 v1.0 — Google News RSS + 雪球 + LLM总结 + 链影响标注
================================================================
数据源:
  1. Google News RSS 四路（全球财经、中美关系、科技/AI、中文财经）
  2. 雪球热帖（公开API，category=6 热门）
  3. 财新RSS（备选，付费订阅可用API）
  
功能:
  - fetch_news() → 多源抓取+去重+排序，返回新闻列表
  - summarize_news(news_list) → LLM 3-5段结构化总结（含链影响方向）
  - classify_impact(news_list) → 每条新闻标注影响的链+方向

链影响标注覆盖10大链：
  GPU/AI芯片、先进制程+封装、存储/HBM、AI电力、AI网络+云计算、
  AI应用/Agent、网络安全/国产替代、机器人、新能源、消费电子

环境变量:
  ARK_API_KEY 或 OPENAI_API_KEY — LLM调用密钥（可选）
"""

import os
import re
import json
import time
import hashlib
import signal
import socket
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from typing import Dict, List, Optional, Tuple

socket.setdefaulttimeout(8)  # 全局socket超时8秒，防止外部API挂死

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

# ═══════════════════════════════════════════════════════════════
# 基础配置
# ═══════════════════════════════════════════════════════════════

BASE_DIR = Path(__file__).parent.parent
CACHE_DIR = BASE_DIR / "investment_system" / "data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

CACHE_FILE = CACHE_DIR / "news_engine_cache.json"
CACHE_TTL = 1800  # 30分钟缓存

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

# 每条源的抓取上限和全局上限
MAX_PER_SOURCE = 15       # 每源最多15条
MAX_TOTAL = 60            # 全局原始上限（过滤前）
MAX_FINAL = 60            # 过滤去重后最终返回数量（覆盖30天）

# 新闻时间窗口（天）
NEWS_WINDOW_DAYS = 30     # 周度视角+月度复盘，当天新闻不一定最重要

# 投资相关性关键词白名单（必须命中至少1个才算有效新闻）
_RELEVANCE_KEYWORDS = {
    "zh": [
        "股", "市值", "A股", "港股", "美股", "基金", "ETF", "债券", "汇率",
        "利率", "通胀", "CPI", "PMI", "GDP", "央行", "美联储",
        "芯片", "半导体", "AI", "人工智能", "算力", "机器人", "光模块",
        "新能源", "储能", "电力", "光伏", "风电", "锂电",
        "黄金", "原油", "铜", "贵金属", "大宗商品",
        "制裁", "出口管制", "关税", "脱钩", "国产替代", "信创",
        "减速器", "伺服", "HBM", "存储", "CoWoS",
        "美元", "人民币", "日元", "欧元", "美债",
        "上涨", "下跌", "涨停", "跌停", "突破", "创新高", "新低",
        "财报", "业绩", "营收", "利润", "订单", "产能", "扩产",
        "IPO", "增发", "回购", "分红",
    ],
    "en": [
        "stock", "market", "shares", "equity", "fund", "etf", "bond", "yield",
        "fed", "rate", "inflation", "gdp", "central bank",
        "chip", "semiconductor", "ai", "nvidia", "tsmc", "gpu", "hbm",
        "robot", "humanoid", "optical", "laser",
        "energy", "solar", "battery", "lithium", "power",
        "gold", "oil", "copper", "commodity",
        "sanction", "tariff", "export control", "decoupling",
        "earnings", "revenue", "profit", "ipo", "acquisition",
        "dollar", "yuan", "yen", "euro",
        "rally", "selloff", "surge", "plunge", "breakout",
    ],
}

# ═══════════════════════════════════════════════════════════════
# Google News RSS 搜索源配置
# ═══════════════════════════════════════════════════════════════

RSS_SOURCES = [
    {
        "name": "A股政策监管",
        "url": "https://news.google.com/rss/search?q=证监会+上交所+深交所+A股+新规+政策&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "lang": "zh", "default_category": "政策监管", "weight": 1.5, "max": 12,
    },
    {
        "name": "国产替代半导体",
        "url": "https://news.google.com/rss/search?q=国产替代+半导体设备+自主可控+信创+芯片+光刻&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "lang": "zh", "default_category": "国产替代", "weight": 1.4, "max": 12,
    },
    {
        "name": "中美脱钩制裁",
        "url": "https://news.google.com/rss/search?q=US+China+tariff+sanction+semiconductor+export+controls+decoupling&hl=en-US&gl=US&ceid=US:en",
        "lang": "en", "default_category": "地缘政治", "weight": 1.4, "max": 12,
    },
    {
        "name": "证券时报",
        "url": "https://news.google.com/rss/search?q=site:stcn.com+股票+行业+业绩&hl=zh-CN&gl=CN",
        "lang": "zh", "default_category": "政策监管", "weight": 1.3, "max": 10,
    },
    {
        "name": "AI芯片光模块",
        "url": "https://news.google.com/rss/search?q=NVIDIA+TSMC+AI+chip+optical+module+800G+CoWoS&hl=en-US&gl=US&ceid=US:en",
        "lang": "en", "default_category": "科技产业", "weight": 1.3, "max": 12,
    },
    {
        "name": "机器人新能源",
        "url": "https://news.google.com/rss/search?q=humanoid+robot+Optimus+减速器+伺服电机+人形机器人&hl=zh-CN&gl=CN",
        "lang": "zh", "default_category": "科技产业", "weight": 1.3, "max": 10,
    },
    {
        "name": "东方财富A股",
        "url": "https://feed.eastmoney.com/toutiaolm.xml",
        "lang": "zh", "default_category": "A股市场", "weight": 1.2, "max": 15,
    },
    {
        "name": "存储HBM电力",
        "url": "https://news.google.com/rss/search?q=HBM+memory+storage+data+center+power+electricity+AI&hl=en-US&gl=US&ceid=US:en",
        "lang": "en", "default_category": "科技产业", "weight": 1.2, "max": 10,
    },
    {
        "name": "中文财经宏观",
        "url": "https://news.google.com/rss/search?q=中国+经济+宏观+利率+CPI+PMI+货币政策&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "lang": "zh", "default_category": "中国市场", "weight": 1.1, "max": 10,
    },
    {
        "name": "全球宏观市场",
        "url": "https://news.google.com/rss/search?q=fed+rate+inflation+stock+market+earnings+GDP&hl=en-US&gl=US&ceid=US:en",
        "lang": "en", "default_category": "全球宏观", "weight": 1.0, "max": 10,
    },
    {
        "name": "港股大宗商品",
        "url": "https://news.google.com/rss/search?q=港股+恒生+黄金+原油+铜+大宗商品+汇率&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "lang": "zh", "default_category": "全球宏观", "weight": 1.0, "max": 10,
    },
    {
        "name": "美股科技财报",
        "url": "https://news.google.com/rss/search?q=earnings+revenue+guidance+NVDA+MSFT+GOOGL+META+AAPL&hl=en-US&gl=US&ceid=US:en",
        "lang": "en", "default_category": "美股", "weight": 1.1, "max": 10,
    },
]

# ═══════════════════════════════════════════════════════════════
# 链影响关键词映射 — 扩展至10大链
# ═══════════════════════════════════════════════════════════════

_CHAIN_IMPACT_KEYWORDS = {
    "GPU/AI芯片": {
        "keywords": [
            "GPU", "英伟达", "NVIDIA", "AI芯片", "算力芯片", "推理芯片",
            "AMD", "MI300", "MI400", "B200", "B100", "H200", "H100",
            "Blackwell", "Hopper", "Rubin", "AI accelerator", "TPU",
            "寒武纪", "海光信息", "GPU出货", "算力卡",
        ],
        "up": [
            "GPU出货超预期", "算力需求暴增", "AI芯片供不应求",
            "英伟达业绩超预期", "新架构发布", "算力补贴",
        ],
        "down": [
            "GPU出口管制", "芯片禁运", "算力过剩", "英伟达业绩miss",
            "AI芯片需求放缓", "竞争加剧", "替代方案成熟",
        ],
    },
    "先进制程+封装": {
        "keywords": [
            "先进制程", "3nm", "5nm", "2nm", "CoWoS", "先进封装",
            "台积电", "TSMC", "三星", "Intel", "光刻机", "EUV",
            "晶圆代工", "foundry", "chiplet", "3D封装",
            "中芯国际", "SMIC", "ASML", "半导体设备",
        ],
        "up": [
            "先进制程良率提升", "CoWoS扩产", "台积电资本开支上调",
            "先进封装需求暴增", "国产设备突破", "新建晶圆厂",
        ],
        "down": [
            "制程延期", "良率问题", "台积电下调指引", "设备出口管制",
            "地缘风险", "产能过剩", "晶圆代工降价",
        ],
    },
    "存储/HBM": {
        "keywords": [
            "HBM", "HBM3", "HBM3E", "HBM4", "DRAM", "NAND",
            "存储芯片", "三星", "SK海力士", "美光", "Micron",
            "高带宽内存", "封装基板", "IC载板", "存储涨价",
            "长江存储", "兆易创新", "北京君正",
        ],
        "up": [
            "HBM供不应求", "存储涨价", "SK海力士扩产",
            "HBM4标准发布", "AI拉动内存需求", "存储周期上行",
        ],
        "down": [
            "存储降价", "HBM产能过剩", "需求放缓",
            "存储周期见顶", "技术替代", "库存积压",
        ],
    },
    "AI电力": {
        "keywords": [
            "数据中心电力", "AI电力", "核电", "SMR", "小型核反应堆",
            "液冷", "散热", "电力供应", "电网", "变压器",
            "电力设备", "UPS", "备用电源", "燃气轮机",
            "可再生能源", "光伏+储能", "电力短缺",
        ],
        "up": [
            "数据中心电力需求暴增", "核电重启", "SMR获批",
            "液冷渗透率提升", "电力设备订单大增", "电价上涨",
        ],
        "down": [
            "电力供应充足", "核电事故", "液冷技术路线不明",
            "数据中心能效提升", "电力成本下降",
        ],
    },
    "AI网络+云计算": {
        "keywords": [
            "光模块", "光通信", "800G", "1.6T", "数据中心",
            "IDC", "云计算", "云服务", "AWS", "Azure", "GCP",
            "阿里云", "腾讯云", "CSP", "资本开支", "capex",
            "服务器", "交换机", "InfiniBand", "Spectrum",
            "中际旭创", "新易盛", "天孚通信",
        ],
        "up": [
            "CSP资本开支上调", "光模块升级加速", "1.6T量产",
            "云服务收入超预期", "数据中心建设加速", "AI推理需求暴增",
        ],
        "down": [
            "CSP削减资本开支", "光模块降价", "云服务增速放缓",
            "数据中心过剩", "技术迭代不及预期",
        ],
    },
    "AI应用/Agent": {
        "keywords": [
            "AI应用", "Agent", "大模型", "LLM", "ChatGPT",
            "Anthropic", "Claude", "OpenAI", "DeepSeek",
            "AI搜索", "AI编程", "Cursor", "Copilot",
            "AI+SaaS", "AI办公", "AI教育", "AI医疗",
            "Token消耗", "ARR", "AI收入",
            "金山办公", "万兴科技", "科大讯飞",
        ],
        "up": [
            "AI应用ARR暴增", "Token消耗月环比+30%", "Agent落地",
            "企业AI预算上调", "AI应用付费率提升", "开源模型突破",
        ],
        "down": [
            "AI泡沫破裂", "AI应用变现困难", "Token消耗增速放缓",
            "大模型公司直接做应用", "监管收紧", "ROI不达预期",
        ],
    },
    "网络安全/国产替代": {
        "keywords": [
            "网络安全", "信息安全", "信创", "国产替代", "自主可控",
            "操作系统", "数据库", "ERP", "工业软件", "CAD",
            "数据安全", "网络攻击", "黑客", "勒索软件",
            "CrowdStrike", "Palo Alto", "深信服", "奇安信",
            "达梦数据库", "中望软件", "用友网络",
        ],
        "up": [
            "重大网络攻击", "信创招标超预期", "国产替代政策加码",
            "安全支出预算上调", "国产数据库突破", "数据安全立法",
        ],
        "down": [
            "安全事件平息", "信创预算削减", "国产替代进度缓慢",
            "外资产品重新进入", "安全支出缩减",
        ],
    },
    "机器人": {
        "keywords": [
            "机器人", "人形机器人", "Optimus", "Figure", "宇树",
            "智元", "伺服电机", "减速器", "谐波减速器",
            "传感器", "机器视觉", "自动化", "智能工厂",
            "特斯拉机器人", "波士顿动力", "绿的谐波", "拓斯达",
        ],
        "up": [
            "人形机器人量产", "特斯拉Optimus里程碑", "机器人政策支持",
            "核心零部件突破", "机器人订单大增", "AI+机器人结合",
        ],
        "down": [
            "量产延期", "成本下降不及预期", "炒作退潮",
            "技术路线失败", "安全事故", "需求不达预期",
        ],
    },
    "新能源": {
        "keywords": [
            "光伏", "风电", "储能", "锂电池", "固态电池",
            "逆变器", "新能源汽车", "电动车", "充电桩",
            "宁德时代", "比亚迪", "隆基绿能", "阳光电源",
            "光伏组件", "多晶硅", "碳酸锂",
        ],
        "up": [
            "光伏装机超预期", "储能订单暴增", "固态电池突破",
            "锂价触底反弹", "新能源政策利好", "海外市场打开",
        ],
        "down": [
            "产能过剩", "价格战", "光伏组件降价", "锂价下跌",
            "补贴退坡", "欧美关税", "新能源车增速放缓",
        ],
    },
    "消费电子": {
        "keywords": [
            "AI手机", "AI PC", "iPhone", "华为手机", "小米",
            "折叠屏", "MR", "Vision Pro", "智能穿戴",
            "换机周期", "消费电子", "手机出货",
            "立讯精密", "歌尔股份", "舜宇光学",
        ],
        "up": [
            "AI手机换机潮", "折叠屏渗透加速", "手机出货超预期",
            "AI PC需求爆发", "苹果新品超预期", "消费电子复苏",
        ],
        "down": [
            "换机意愿低迷", "手机出货下滑", "消费降级",
            "AI功能无杀手应用", "硬件创新停滞", "供应链转移",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# 第1部分：多源新闻抓取
# ═══════════════════════════════════════════════════════════════

def _safe_encode_url(url: str) -> str:
    """安全编码URL（保留中文等非ASCII字符的正确编码，保留+=&等查询字符）"""
    parsed = list(urllib.parse.urlsplit(url))
    parsed[2] = urllib.parse.quote(parsed[2], safe="/:?=&+%")
    if parsed[3]:
        parsed[3] = urllib.parse.quote(parsed[3], safe="+=&")
    return urllib.parse.urlunsplit(parsed)


def _fetch_rss(url: str, timeout: int = 15) -> Optional[str]:
    """抓取RSS源原始XML"""
    try:
        safe_url = _safe_encode_url(url)
        req = urllib.request.Request(safe_url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            # 尝试UTF-8解码，失败则用替代字符
            return raw.decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  [RSS] 获取失败: {url[:80]}... — {e}")
        return None


def _parse_rss_items(xml_text: str, source_name: str = "", max_items: int = MAX_PER_SOURCE) -> List[Dict]:
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.findall(".//item")[:max_items]:
            title = _xml_text(item, "title")
            link = _xml_text(item, "link")
            pub_date = _xml_text(item, "pubDate")
            desc = _xml_text(item, "description")
            # 清理HTML标签
            desc = _strip_html(desc)[:300]
            source_tag = _xml_text(item, "source")
            if title:
                items.append({
                    "title": _clean_title(title),
                    "link": link,
                    "pub_date": pub_date,
                    "description": desc,
                    "source": source_tag or source_name,
                    "source_name": source_name,
                    "fetched_at": datetime.now().isoformat(),
                })
    except ET.ParseError as e:
        print(f"  [RSS] XML解析失败: {e}")
    return items


def _xml_text(parent, tag: str) -> str:
    """安全提取XML子元素文本"""
    el = parent.find(tag)
    if el is not None and el.text:
        return el.text.strip()
    return ""


def _strip_html(text: str) -> str:
    """去除HTML标签"""
    if not text:
        return ""
    return re.sub(r"<[^>]+>", " ", text).strip()


def _clean_title(title: str) -> str:
    """清理RSS标题（去掉来源后缀，如 ' - Reuters', ' | BBC'）"""
    # Google News RSS标题格式: "Title - Source"
    for sep in [" - ", " – ", " — ", " | "]:
        if sep in title:
            # 只在末尾存在分隔符时才拆分
            parts = title.rsplit(sep, 1)
            if len(parts) == 2 and len(parts[1]) < 40:
                title = parts[0]
    return title.strip()


def _fetch_google_news_rss() -> List[Dict]:
    all_items = []
    for src in RSS_SOURCES:
        print(f"  [RSS] 抓取: {src['name']}...")
        xml_text = _fetch_rss(src["url"])
        if xml_text:
            src_max = src.get("max", MAX_PER_SOURCE)
            items = _parse_rss_items(xml_text, src["name"], max_items=src_max)
            for item in items:
                item["category"] = src["default_category"]
                item["lang"] = src["lang"]
                item["source_weight"] = src.get("weight", 1.0)
            all_items.extend(items)
            print(f"    → {len(items)} 条")
        else:
            print(f"    → 0 条（获取失败）")
        time.sleep(0.3)
    return all_items


# ═══════════════════════════════════════════════════════════════
# 雪球热帖抓取
# ═══════════════════════════════════════════════════════════════

XUEQIU_API = (
    "https://xueqiu.com/v4/statuses/public_timeline_by_category.json"
    "?category=6"  # category=6 为热门
)


def _fetch_xueqiu_hot(token: Optional[str] = None) -> List[Dict]:
    """
    抓取雪球热帖。
    
    公开API不需要token，但可能被限流。
    如有token（xueqiu cookie），可设置环境变量 XUEQIU_COOKIE 提升频率。
    """
    items = []
    cookie = token or os.environ.get("XUEQIU_COOKIE", "")
    
    try:
        headers = {
            "User-Agent": UA,
            "Accept": "application/json",
        }
        if cookie:
            headers["Cookie"] = cookie
        
        req = urllib.request.Request(XUEQIU_API, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        
        # 雪球API结构: {"list": [...]} 或直接是列表
        post_list = data if isinstance(data, list) else data.get("list", [])
        if not post_list:
            # 备选字段名
            for key in ["statuses", "data", "items"]:
                if key in data:
                    post_list = data[key]
                    break
        
        for post in post_list[:MAX_PER_SOURCE]:
            # 雪球帖子可能用data或直接包含字段
            if isinstance(post, dict):
                data_block = post.get("data", post)
                title = data_block.get("title", "") or data_block.get("text", "") or data_block.get("description", "")
                title = _strip_html(title)[:200]
                if title:
                    items.append({
                        "title": title,
                        "link": f"https://xueqiu.com{data_block.get('target', '')}",
                        "pub_date": _ts_to_str(data_block.get("created_at", 0)),
                        "description": _strip_html(data_block.get("text", "") or data_block.get("description", ""))[:300],
                        "source": "雪球",
                        "source_name": "雪球热帖",
                        "category": "市场讨论",
                        "lang": "zh",
                        "fetched_at": datetime.now().isoformat(),
                    })
    except Exception as e:
        print(f"  [雪球] 获取失败: {e}")
    
    print(f"  [雪球] → {len(items)} 条")
    return items


def _ts_to_str(ts: int) -> str:
    """时间戳转字符串"""
    if not ts or ts < 1000000000:
        return ""
    try:
        return datetime.fromtimestamp(ts / 1000 if ts > 10000000000 else ts).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
# 财新RSS（备选）
# ═══════════════════════════════════════════════════════════════

CAIXIN_RSS_URL = "https://www.caixin.com/rss/caixin.xml"


def _fetch_caixin_rss() -> List[Dict]:
    """抓取财新RSS（通过RSSHub，免费但可能限流）"""
    items = []
    try:
        xml_text = _fetch_rss(CAIXIN_RSS_URL, timeout=15)
        if xml_text:
            parsed = _parse_rss_items(xml_text, "财新")
            for item in parsed:
                item["category"] = "中国宏观"
                item["lang"] = "zh"
            items = parsed
            print(f"  [财新] → {len(items)} 条")
    except Exception as e:
        print(f"  [财新] 获取失败: {e}")
    return items


def _fetch_cls_flash() -> List[Dict]:
    try:
        import akshare as ak
        df = _timeout_call(15, ak.stock_info_global_cls, symbol="重点")
        if df is None or df.empty:
            return []
        items = []
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        for _, row in df.iterrows():
            title = str(row.get("标题", "") or row.get("内容", ""))
            content = str(row.get("内容", ""))
            if not title or len(title) < 5:
                continue
            pub = str(row.get("发布时间", "") or row.get("发布日期", "") or now_str)
            items.append({
                "title": _clean_title(title),
                "description": content[:300],
                "url": "",
                "pub_date": pub,
                "source_name": "财联社",
                "category": "中国市场",
                "lang": "zh",
                "hotness": 2,
            })
        print(f"  [财联社] → {len(items)} 条")
        return items
    except Exception as e:
        print(f"  [财联社] 获取失败: {e}")
        return []


def _fetch_sina_flash() -> List[Dict]:
    try:
        import akshare as ak
        df = _timeout_call(15, ak.stock_info_global_sina)
        if df is None or df.empty:
            return []
        items = []
        now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")
        for _, row in df.iterrows():
            content = str(row.get("内容", "") or row.get("标题", ""))
            if not content or len(content) < 10:
                continue
            pub = str(row.get("时间", now_str))
            items.append({
                "title": _clean_title(content[:150]),
                "description": content[:300],
                "url": "",
                "pub_date": pub,
                "source_name": "新浪财经",
                "category": "全球宏观",
                "lang": "zh",
                "hotness": 1,
            })
        print(f"  [新浪财经] → {len(items)} 条")
        return items
    except Exception as e:
        print(f"  [新浪财经] 获取失败: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# 第2部分：去重+排序
# ═══════════════════════════════════════════════════════════════

def _title_similarity(t1: str, t2: str) -> float:
    """
    计算两个标题的相似度（基于公共子串的Jaccard系数）。
    用于去重判断。
    """
    if not t1 or not t2:
        return 0.0
    
    # 快速检查：如果一个标题完全包含另一个，直接判定为重复
    t1_lower = t1.lower()
    t2_lower = t2.lower()
    if t1_lower in t2_lower or t2_lower in t1_lower:
        return 1.0
    
    # 简单方法：提取中文字符/英文单词，比较公共子串比例
    def _tokens(s: str) -> set:
        s = s.lower()
        # 提取英文单词（3字符以上更有区分度）
        result = set()
        result.update(re.findall(r"[a-z]{3,}", s))
        # 中文双字
        zh_chars = re.findall(r"[\u4e00-\u9fff]", s)
        for i in range(len(zh_chars) - 1):
            result.add(zh_chars[i] + zh_chars[i + 1])
        return result
    
    tok1 = _tokens(t1)
    tok2 = _tokens(t2)
    
    if not tok1 or not tok2:
        return 0.0
    
    intersection = len(tok1 & tok2)
    union = len(tok1 | tok2)
    jaccard = intersection / union if union > 0 else 0.0
    
    # 额外检查：重叠token占较小集合的比例
    overlap_ratio = intersection / min(len(tok1), len(tok2)) if min(len(tok1), len(tok2)) > 0 else 0.0
    
    # 取Jaccard和overlap_ratio的最大值
    return max(jaccard, overlap_ratio * 0.7)


def _deduplicate(items: List[Dict], threshold: float = 0.40) -> List[Dict]:
    """
    标题相似度去重。
    相似度 > threshold 视为重复，保留先出现的（或来源更优的）。
    """
    if not items:
        return []
    
    result = []
    for item in items:
        title = item.get("title", "")
        is_dup = False
        for existing in result:
            sim = _title_similarity(title, existing.get("title", ""))
            if sim > threshold:
                is_dup = True
                break
        if not is_dup:
            result.append(item)
    
    return result


def _sort_by_time_and_hotness(items: List[Dict]) -> List[Dict]:
    """
    按时间倒序+热度排序。
    优先：有时间戳的排前面 → 同时间按来源质量（中文优先）
    """
    def _sort_key(item: Dict) -> Tuple[int, int, int]:
        # 时间越新越好
        pub = item.get("pub_date", "")
        ts = 0
        try:
            # 尝试解析多种时间格式
            for fmt in [
                "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%d",
            ]:
                try:
                    ts = int(datetime.strptime(pub, fmt).timestamp())
                    break
                except ValueError:
                    continue
        except Exception:
            pass
        
        # 来源质量：中文源 > 英文源
        lang_priority = 1 if item.get("lang") == "zh" else 0
        
        # 返回 (时间倒序, 语言优先级, 标题长度作为热度proxy)
        return (-ts, -lang_priority, -len(item.get("title", "")))
    
    return sorted(items, key=_sort_key)


# ═══════════════════════════════════════════════════════════════
# 第3部分：链影响标注
# ═══════════════════════════════════════════════════════════════

# ── 通用中文情绪词（回退检测，当链专用方向词未命中时使用）──
_BULLISH_WORDS = [
    "利好", "突破", "大涨", "飙升", "创新高", "超预期", "增长", "加速",
    "扩产", "缺货", "供不应求", "政策支持", "补贴", "放水", "降息",
    "核准", "通过认证", "获批", "中标", "订单大增", "需求暴增",
    "业绩预增", "业绩超预期", "盈利上调", "上调评级", "增持",
    "涨停", "拉升", "回暖", "复苏", "拐点", "底部",
]
_BEARISH_WORDS = [
    "利空", "暴跌", "大跌", "崩盘", "新低", "低于预期", "下滑", "放缓",
    "过剩", "降价", "抛售", "制裁", "管制", "调查", "处罚", "罚款",
    "贸易战", "脱钩", "封锁", "断供", "加税", "加息", "收紧",
    "暴雷", "违约", "亏损", "预亏", "下调评级", "减持",
    "跌停", "退潮", "衰退", "滞胀", "风险",
]


def _detect_general_sentiment(text: str) -> int:
    """通用中文情绪检测：1=偏多, -1=偏空, 0=中性。
    当链专用关键词未命中时作为回退信号。"""
    text_lower = text.lower()
    bullish_hits = sum(1 for w in _BULLISH_WORDS if w in text_lower)
    bearish_hits = sum(1 for w in _BEARISH_WORDS if w in text_lower)
    if bullish_hits > bearish_hits:
        return 1
    elif bearish_hits > bullish_hits:
        return -1
    return 0


def classify_impact(news_list: List[Dict]) -> List[Dict]:
    """
    为每条新闻标注影响的产业链及方向。
    
    返回: 添加了 'impacts' 字段的新闻列表。
    impacts 格式: [{"chain": "GPU/AI芯片", "direction": "↑利好", "reason": "关键词匹配"}]
    """
    for item in news_list:
        text = (item.get("title", "") + " " + item.get("description", "")).lower()
        impacts = []
        
        for chain_name, chain_cfg in _CHAIN_IMPACT_KEYWORDS.items():
            matched_keywords = []
            for kw in chain_cfg.get("keywords", []):
                if kw.lower() in text:
                    matched_keywords.append(kw)
            
            if not matched_keywords:
                continue
            
            # 判断方向：先检查向上关键词，再检查向下，默认中性
            direction = "→中性"
            for up_kw in chain_cfg.get("up", []):
                if up_kw.lower() in text:
                    direction = "↑利好"
                    break
            for down_kw in chain_cfg.get("down", []):
                if down_kw.lower() in text:
                    direction = "↓利空"
                    break
            
            # 通用回退：若链关键词匹配但方向未定，用通用中文情绪词推断
            if direction == "→中性":
                _signal = _detect_general_sentiment(text)
                if _signal == 1:
                    direction = "↑利好"
                elif _signal == -1:
                    direction = "↓利空"
            
            impacts.append({
                "chain": chain_name,
                "direction": direction,
                "reason": f"匹配关键词: {', '.join(matched_keywords[:5])}",
            })
        
        item["impacts"] = impacts
        if not impacts:
            _signal = _detect_general_sentiment(text)
            if _signal == 1:
                item["general_sentiment"] = "↑利好"
            elif _signal == -1:
                item["general_sentiment"] = "↓利空"
            else:
                item["general_sentiment"] = "→中性"
    
    return news_list


def _format_impact_brief(impacts: List[Dict]) -> str:
    """格式化链影响简要信息"""
    if not impacts:
        return ""
    parts = []
    for imp in impacts[:3]:
        parts.append(f"[{imp['chain']}] {imp['direction']}")
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════
# 第4部分：LLM总结
# ═══════════════════════════════════════════════════════════════

def _get_hermes_llm_config() -> tuple:
    """从 Hermes config.yaml 读取 LLM 配置（当前使用的 API）"""
    try:
        import yaml
        config_path = os.path.expanduser("~/.hermes/config.yaml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
            model_cfg = cfg.get("model", {})
            base_url = model_cfg.get("base_url", "")
            api_key = model_cfg.get("api_key", "")
            model = model_cfg.get("default", "")
            if base_url and api_key and model:
                return base_url, api_key, model
    except Exception:
        pass
    return "", "", ""


def _get_llm_api_key() -> Optional[str]:
    """获取LLM API密钥（优先ARK，其次OPENAI，最后Hermes自身配置）"""
    for key_name in ["ARK_API_KEY", "OPENAI_API_KEY"]:
        key = os.environ.get(key_name, "")
        if key:
            return key
    _, hermes_key, _ = _get_hermes_llm_config()
    return hermes_key or None


def _call_llm(prompt: str, system_prompt: str = "") -> Optional[str]:
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
        hermes_url, hermes_key, hermes_model = _get_hermes_llm_config()
        if not hermes_key:
            print("  [LLM] 无可用API密钥（ARK_API_KEY/OPENAI_API_KEY/Hermes均未配置）")
            return None
        api_url = hermes_url + "/chat/completions"
        model = hermes_model
        api_key = hermes_key

    default_system = (
        "你是一名专业投资研究助理，专注于A股/港股/美股市场分析。"
        "你的输出将用于辅助投资决策，请提供客观、具体、可操作的分析。"
        "严格按照用户要求的格式输出，不要添加免责声明。"
    )
    messages = [
        {"role": "system", "content": system_prompt or default_system},
        {"role": "user", "content": prompt},
    ]

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 2000,
    }).encode("utf-8")

    try:
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
        req = urllib.request.Request(api_url, data=payload, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            content = result["choices"][0]["message"]["content"]
            if not content or not content.strip():
                print(f"  [LLM] 模型返回空内容 (model={model})")
                return None
            print(f"  [LLM] 成功 (model={model}, chars={len(content)})")
            return content
    except Exception as e:
        print(f"  [LLM] 调用失败 (model={model}): {e}")
        return None


def _build_llm_prompt(news_items: List[Dict],
                      stock_context: Optional[List[Dict]] = None) -> str:
    items_text = "\n".join(
        f"{i+1}. [{item.get('source_name','?')}][{item.get('pub_date','')[:10]}] {item.get('title','')}"
        + (f" — {item.get('description','')[:150]}" if item.get('description') else "")
        for i, item in enumerate(news_items)
    )
    chains = "算力芯片、半导体制造、半导体国产替代、存储/HBM、AI应用/Agent、AI网络+数据中心、机器人/自动化、军工、医药创新、AI电力、新能源、消费电子、苹果产业链、新能源汽车、全球宏观、中国政策、地缘政治"

    stock_section = ""
    if stock_context:
        lines = ["【当日观察池关键信号（优先分析这些票）】"]
        for s in stock_context:
            code = s.get("code", "")
            name = s.get("name", "")
            chg = s.get("chg")
            signal = s.get("signal", "")
            news_titles = s.get("recent_news", [])
            line = f"- {name}({code})"
            if chg is not None:
                line += f" 今日{chg:+.1f}%"
            if signal:
                line += f" 信号:{signal}"
            if news_titles:
                line += f" | 个股新闻: {'; '.join(news_titles[:2])}"
            lines.append(line)
        stock_section = "\n".join(lines) + "\n\n"

    return f"""你是一名投资研究助理，不是新闻编辑。你的唯一目标是：识别哪些事件会改变资产定价，而不是总结发生了什么。

{stock_section}

过去30天新闻（共{len(news_items)}条，已去重排序）：
{items_text}

你需要完成以下任务，严格按格式输出：

【A. 本期最重要的3个变化】（每条≤60字，格式：变化点 | 影响变量 | 受影响资产）
① 
② 
③ 

【B. 关键事件影响分析】（只保留真正改变定价/预期的事件，每条格式如下）
[事件] [自拟简洁标题]
- 新增事实：一句话，只写事实，不写评论
- 影响变量：利率/信用/需求/成本/监管/风险偏好（选一个最主要的）
- 影响链路：[产业链名] → 方向[↑利好/↓利空/→中性] → 时间维度[短期1-5日/中期1-8周]
- 受影响标的：列出具体A股/港股/美股代码或名称
- 需要动作：无 / 关注价格变化 / 重新评估逻辑 / 等待数据确认
- 置信度：高/中/低

（重复事件只写一次，同类事件合并，最多写5个）

【C. 产业链情绪变化】（只写有实质变化的链，无变化不写）
[链名]：[↑升温/↓降温/→平稳] | 原因：[引用具体事件，一句话]

【D. 宏观信号变化】
- 利率方向：[↑/↓/→] 理由：
- 风险偏好：[↑/↓/→] 理由：
- 中国政策取向：[宽松/收紧/中性] 证据：

【E. 可以忽略的内容】
以下新闻属于噪音，无需关注（简要说明为什么）：
- 

产业链范围：{chains}

严格中文输出，分析要犀利具体，不要泛泛而谈。没有新增事实的事件一律归入E类噪音。"""


def _calc_sentiment_score(news_list: List[Dict]) -> dict:
    bullish, bearish, neutral = 0, 0, 0
    chain_sentiment: Dict[str, Dict] = {}

    for item in news_list:
        item_bullish = item_bearish = False
        for imp in item.get("impacts", []):
            chain = imp["chain"]
            d = imp["direction"]
            if chain not in chain_sentiment:
                chain_sentiment[chain] = {"up": 0, "down": 0, "neutral": 0}
            if "利好" in d or "↑" in d:
                chain_sentiment[chain]["up"] += 1
                item_bullish = True
            elif "利空" in d or "↓" in d:
                chain_sentiment[chain]["down"] += 1
                item_bearish = True
            else:
                chain_sentiment[chain]["neutral"] += 1
        if item_bullish and not item_bearish:
            bullish += 1
        elif item_bearish and not item_bullish:
            bearish += 1
        else:
            gs = item.get("general_sentiment", "→中性")
            if "↑" in gs:
                bullish += 1
            elif "↓" in gs:
                bearish += 1
            else:
                neutral += 1

    total = bullish + bearish + neutral or 1
    if bullish > bearish * 1.5:
        overall = "🟢 偏多"
    elif bearish > bullish * 1.5:
        overall = "🔴 偏空"
    else:
        overall = "🟡 中性"

    return {
        "overall": overall,
        "bullish": bullish,
        "bearish": bearish,
        "neutral": neutral,
        "score": round((bullish - bearish) / total * 100, 0),
        "chain_sentiment": chain_sentiment,
    }


def _build_keyword_summary(news_list: List[Dict]) -> str:
    sentiment = _calc_sentiment_score(news_list)
    chain_groups: Dict[str, List[Dict]] = {}
    uncategorized = []

    for item in news_list:
        impacts = item.get("impacts", [])
        if impacts:
            for imp in impacts:
                chain_groups.setdefault(imp["chain"], []).append((item, imp))
        else:
            uncategorized.append(item)

    lines = ["## 📰 本周市场要闻与情绪\n"]

    lines.append(
        f"**市场情绪**: {sentiment['overall']} "
        f"| 利好{sentiment['bullish']}条 / 利空{sentiment['bearish']}条 / 中性{sentiment['neutral']}条 "
        f"| 情绪得分{sentiment['score']:+.0f}\n"
    )

    if chain_groups:
        lines.append("### 🔗 产业链影响新闻\n")
        for chain, items_imps in sorted(chain_groups.items(),
                                        key=lambda x: len(x[1]), reverse=True)[:8]:
            cs = sentiment["chain_sentiment"].get(chain, {})
            up, down = cs.get("up", 0), cs.get("down", 0)
            trend = "↑升温" if up > down else ("↓降温" if down > up else "→平稳")
            lines.append(f"\n**{chain}**（{len(items_imps)}条, {trend}）")
            seen = set()
            for item, imp in items_imps[:3]:
                title = item.get("title", "")[:80]
                if title in seen:
                    continue
                seen.add(title)
                link = item.get("link", "")
                direction = imp["direction"]
                src = item.get("source_name", "")
                line = f"  • {direction} [{title}]({link})" if link else f"  • {direction} {title}"
                if src:
                    line += f" [{src}]"
                lines.append(line)

    lines.append("\n### **链影响分布**")
    for chain, items_imps in sorted(chain_groups.items(), key=lambda x: len(x[1]), reverse=True):
        cs = sentiment["chain_sentiment"].get(chain, {})
        up, down = cs.get("up", 0), cs.get("down", 0)
        dir_str = "↑利好" if up > down else ("↓利空" if down > up else "→中性")
        lines.append(f"- {chain}: {len(items_imps)}条新闻 | 方向: {dir_str}")

    lines.append("\n### **关键事件 Top 5**")
    seen_kw = set()
    shown = 0
    for item in sorted(news_list, key=lambda x: len(x.get("impacts", [])), reverse=True):
        if shown >= 5:
            break
        title = item.get("title", "")
        if not title or title in seen_kw:
            continue
        seen_kw.add(title)
        shown += 1
        impacts = item.get("impacts", [])
        imp_str = " → ".join(f"[{i['chain']}]{i['direction']}" for i in impacts[:2])
        lines.append(f"- {title[:100]}  {imp_str}" if imp_str else f"- {title[:100]}")

    return "\n".join(lines)


def summarize_news(news_list: List[Dict], use_llm: bool = True,
                   stock_context: Optional[List[Dict]] = None) -> str:
    if not news_list and not stock_context:
        return "📰 今日无重大新闻信号"

    news_list = classify_impact(news_list)

    if use_llm:
        system_prompt = "你是一位专业的A股/港股/美股投资分析师，熟悉面基播客的产业链分析框架和LDS实战体系。请用中文回复，格式严谨，观点犀利。"
        prompt = _build_llm_prompt(news_list[:25], stock_context=stock_context)
        summary = _call_llm(prompt, system_prompt)
        if summary:
            sentiment = _calc_sentiment_score(news_list)
            header = (
                f"## 📰 今日市场情报（AI分析）\n\n"
                f"> 情绪得分 {sentiment['score']:+.0f} | "
                f"利好{sentiment['bullish']} / 利空{sentiment['bearish']} / 中性{sentiment['neutral']}\n\n"
            )
            return header + summary.strip()

    return _build_keyword_summary(news_list)



# ═══════════════════════════════════════════════════════════════
# 第5部分：主导出函数
# ═══════════════════════════════════════════════════════════════

def _is_relevant(item: Dict) -> bool:
    """
    ★ v5.3 宽松模式：RSS源本身已是金融类，过滤从"关键词白名单"降为"标题长度+简单有效性校验"
    因为 RSS_SOURCES 里的搜索关键词已经是投资相关（如 "AI chip NVIDIA"、"证监会" 等），
    返回的标题天然就是金融/产业类，无需再用严格白名单过滤。
    只排除：空标题、纯噪音标题
    """
    title = (item.get("title", "") or "").strip()
    if not title or len(title) < 5:
        return False
    # 排除明显的非新闻噪音条目
    noise_patterns = ["subscribe", "sign up", "privacy policy", "terms of service",
                      "cookie", "advertisement", "sponsored"]
    title_lower = title.lower()
    for p in noise_patterns:
        if p in title_lower:
            return False
    return True


def _is_within_window(item: Dict, days: int = NEWS_WINDOW_DAYS) -> bool:
    pub = item.get("pub_date", "")
    if not pub:
        return True
    cutoff = datetime.now().timestamp() - days * 86400
    for fmt in [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S +0000",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ]:
        try:
            ts = datetime.strptime(pub.strip(), fmt).timestamp()
            return ts >= cutoff
        except ValueError:
            continue
    return True


def fetch_news(
    sources: Optional[List[str]] = None,
    max_total: int = MAX_FINAL,
    window_days: int = NEWS_WINDOW_DAYS,
) -> List[Dict]:
    if sources is None:
        sources = ["google", "xueqiu", "caixin", "cls", "sina"]

    source_funcs = {
        "google":  _fetch_google_news_rss,
        "xueqiu":  _fetch_xueqiu_hot,
        "caixin":  _fetch_caixin_rss,
        "cls":     _fetch_cls_flash,
        "sina":    _fetch_sina_flash,
    }
    active = {k: v for k, v in source_funcs.items() if k in sources}

    all_items = []
    print(f"[新闻引擎] 并行抓取 {len(active)} 个源...")
    with ThreadPoolExecutor(max_workers=len(active)) as pool:
        futures = {pool.submit(fn): name for name, fn in active.items()}
        for fut in as_completed(futures, timeout=60):
            name = futures[fut]
            try:
                items = fut.result(timeout=30)
                all_items.extend(items)
                print(f"  {name}: {len(items)} 条")
            except FuturesTimeout:
                print(f"  {name}: 超时跳过")
            except Exception as e:
                print(f"  {name}: 失败({e})")

    print(f"[新闻引擎] 原始抓取: {len(all_items)} 条")

    before_time = len(all_items)
    all_items = [x for x in all_items if _is_within_window(x, window_days)]
    print(f"[新闻引擎] 时间窗口({window_days}天)过滤: {before_time} → {len(all_items)} 条")

    before_rel = len(all_items)
    all_items = [x for x in all_items if _is_relevant(x)]
    print(f"[新闻引擎] 投资相关性过滤: {before_rel} → {len(all_items)} 条")

    all_items = _deduplicate(all_items, threshold=0.5)
    print(f"[新闻引擎] 去重后: {len(all_items)} 条")

    all_items = _sort_by_time_and_hotness(all_items)

    result = all_items[:max_total]
    print(f"[新闻引擎] 最终返回: {len(result)} 条")

    _save_cache(result)
    return result


def _save_cache(items: List[Dict]) -> None:
    """保存新闻缓存到文件"""
    try:
        cache_data = {
            "timestamp": datetime.now().isoformat(),
            "count": len(items),
            "items": items,
        }
        CACHE_FILE.write_text(json.dumps(cache_data, ensure_ascii=False, indent=2))
    except Exception:
        pass


def load_cached_news(max_age: int = CACHE_TTL) -> Optional[List[Dict]]:
    """读取缓存的新闻（指定最大秒数内有效）"""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text())
        ts = data.get("timestamp", "")
        if ts:
            age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
            if age < max_age:
                return data.get("items", [])
    except Exception:
        pass
    return None


def get_news_with_impact(
    use_cache: bool = True,
    use_llm: bool = True,
    window_days: int = 1,
    stock_context: Optional[List[Dict]] = None,
) -> Tuple[List[Dict], str]:
    if use_cache and window_days == NEWS_WINDOW_DAYS:
        cached = load_cached_news()
        if cached:
            print("[新闻引擎] 使用缓存（{} 条）".format(len(cached)))
            news_list = classify_impact(cached)
            summary = summarize_news(cached, use_llm=use_llm, stock_context=stock_context)
            return news_list, summary

    news_list = fetch_news(window_days=window_days)
    if not news_list and not stock_context:
        return [], "📰 今日无重大新闻信号"

    news_list = classify_impact(news_list)
    summary = summarize_news(news_list, use_llm=use_llm, stock_context=stock_context)
    return news_list, summary


# ═══════════════════════════════════════════════════════════════
# CLI测试入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    
    print("=" * 60)
    print("  多源新闻引擎 — 测试运行")
    print("=" * 60)
    print()
    
    # 检查环境变量
    api_key = _get_llm_api_key()
    if api_key:
        print(f"✅ LLM API密钥已配置 ({'ARK' if os.environ.get('ARK_API_KEY') else 'OpenAI'})")
    else:
        print("⚠️  未配置 LLM API密钥（ARK_API_KEY 或 OPENAI_API_KEY）")
        print("   将使用关键词匹配降级方案")
    print()
    
    # 命令行参数
    use_cache = "--no-cache" not in sys.argv
    use_llm = "--no-llm" not in sys.argv
    sources_arg = None
    for arg in sys.argv[1:]:
        if arg.startswith("--sources="):
            sources_arg = arg.split("=", 1)[1].split(",")
    
    if "--cache-only" in sys.argv:
        cached = load_cached_news()
        if cached:
            print(f"📋 缓存新闻 ({len(cached)} 条):")
            for item in cached[:10]:
                print(f"  • {item.get('title', '')[:100]}")
        else:
            print("⚠️ 无缓存数据")
        sys.exit(0)
    
    # 抓取新闻
    news_list, summary = get_news_with_impact(
        use_cache=use_cache,
        use_llm=use_llm,
    )
    
    print()
    print(summary)
    print()
    print("-" * 60)
    print(f"📊 统计: 共 {len(news_list)} 条新闻")
    
    # 链影响分布
    chain_counts = {}
    for item in news_list:
        for imp in item.get("impacts", []):
            chain = imp["chain"]
            chain_counts[chain] = chain_counts.get(chain, 0) + 1
    
    if chain_counts:
        print("🔗 链影响分布:")
        for chain, count in sorted(chain_counts.items(), key=lambda x: -x[1]):
            print(f"  {chain}: {count}条")
    
    print(f"\n🕒 时间: {datetime.now().isoformat()}")
