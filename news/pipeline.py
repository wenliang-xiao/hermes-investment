"""
新闻管线 v3 — 多源聚合·情绪分析·缓存管理
取代 Google RSS (domain/news_fetcher.py) 和 AKShare (scripts/news_pipeline.py)

用法:
  python3 news/pipeline.py               # 全量运行
  python3 news/pipeline.py --mode quick  # 仅快讯+电报（不抓个股）

输出: data/news_cache.json
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# 确保项目根目录在 sys.path
_NEWS_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _NEWS_DIR.parent
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))

from news.fetcher import (
    fetch_eastmoney_flash,
    fetch_cls_telegraph,
    fetch_eastmoney_stock_news,
    fetch_cninfo_announcements,
)
from news.sentiment import analyze_batch, summarize_sentiments

DATA_DIR = _PROJECT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "news_cache.json"
CACHE_TTL = 30 * 60  # 30 分钟


def _get_core_symbols():
    """从 WATCHLIST 获取核心 A 股标的"""
    try:
        from config import WATCHLIST
    except ImportError:
        try:
            from domain import WATCHLIST as _wl
            WATCHLIST = _wl
        except ImportError:
            return []

    core_symbols = []
    for code, info in WATCHLIST.items():
        sym = str(code)
        # 仅取 A 股（6位纯数字）
        if sym.isdigit() and len(sym) == 6:
            tier = ""
            if isinstance(info, dict):
                tier = info.get("tier", "")
            if tier in ("核心", "底仓", "关注"):
                core_symbols.append(sym)

    return core_symbols


def _deduplicate(items: List[Dict]) -> List[Dict]:
    """按标题前 40 字符去重"""
    seen = set()
    result = []
    for item in items:
        key = (item.get("title") or item.get("content") or "")[:40]
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


class NewsPipeline:
    """新闻管线：多源抓取 → 去重 → 情绪分析 → 缓存"""

    def __init__(self, mode="full"):
        self.mode = mode
        self.start_time = datetime.now()

    def run(self) -> Dict:
        """
        运行完整管线

        Returns:
            与 data/news_cache.json 相同结构的数据
        """
        print(f"{'='*50}")
        print(f"📰 新闻管线 v3 · {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}")

        flash_items = []
        telegraph_items = []
        stock_news = []
        announcements = []

        # ── 7×24 快讯 ──
        print(f"\n📡 东方财富 7×24 快讯 ...")
        try:
            flash_items = fetch_eastmoney_flash()
            print(f"   ✅ {len(flash_items)} 条")
        except Exception as e:
            print(f"   ⚠️ 失败: {e}")

        # ── 财联社电报 ──
        print(f"\n📡 财联社电报 ...")
        try:
            telegraph_items = fetch_cls_telegraph(limit=30)
            print(f"   ✅ {len(telegraph_items)} 条")
        except Exception as e:
            print(f"   ⚠️ 失败: {e}")

        # ── 个股新闻 + 公告 (full mode) ──
        if self.mode != "quick":
            symbols = _get_core_symbols()
            print(f"\n📡 个股新闻 + 公告 ({len(symbols)} 只标的) ...")
            stock_count = 0
            ann_count = 0

            for i, sym in enumerate(symbols[:30]):
                try:
                    news = fetch_eastmoney_stock_news(sym, limit=5)
                    if news:
                        stock_news.extend(news)
                        stock_count += len(news)
                except Exception as e:
                    print(f"   ⚠️ {sym} 新闻失败: {e}")

                try:
                    ann = fetch_cninfo_announcements(sym, limit=3)
                    if ann:
                        announcements.extend(ann)
                        ann_count += len(ann)
                except Exception as e:
                    print(f"   ⚠️ {sym} 公告失败: {e}")

                time.sleep(0.5)  # 礼貌间隔

            print(f"   ✅ 个股新闻 {stock_count} 条 · 公告 {ann_count} 条")
        else:
            print(f"\n⏩ quick mode: 跳过个股新闻/公告")

        # ── 去重 ──
        flash_items = _deduplicate(flash_items)
        telegraph_items = _deduplicate(telegraph_items)
        stock_news = _deduplicate(stock_news)
        announcements = _deduplicate(announcements)

        # ── 情绪分析 ──
        print(f"\n🧠 情绪分析 ...")
        stock_news = analyze_batch(stock_news)
        flash_items = analyze_batch(flash_items)
        telegraph_items = analyze_batch(telegraph_items)
        announcements = analyze_batch(announcements)

        # 汇总统计
        all_items = flash_items + telegraph_items + stock_news + announcements
        sentiment_summary = summarize_sentiments(all_items)

        print(f"   🟢 利好 {sentiment_summary['positive']} "
              f"🔴 利空 {sentiment_summary['negative']} "
              f"⚪ 中性 {sentiment_summary['neutral']}")

        # ── 构建输出 ──
        result = {
            "timestamp": datetime.now().isoformat(),
            "sources": {
                "eastmoney_flash": {
                    "updated": datetime.now().isoformat(),
                    "count": len(flash_items),
                },
                "cls_telegraph": {
                    "updated": datetime.now().isoformat(),
                    "count": len(telegraph_items),
                },
                "eastmoney_stock_news": {
                    "updated": datetime.now().isoformat(),
                    "count": len(stock_news),
                },
                "cninfo_announcements": {
                    "updated": datetime.now().isoformat(),
                    "count": len(announcements),
                },
            },
            "categories": {
                "7×24快讯": flash_items,
                "电报快讯": telegraph_items,
                "个股新闻": stock_news,
                "公告": announcements,
            },
            "sentiment_summary": sentiment_summary,
            "total": len(all_items),
        }

        # ── 写入缓存 ──
        try:
            CACHE_FILE.write_text(
                json.dumps(result, ensure_ascii=False, indent=2)
            )
            print(f"\n💾 已保存: {CACHE_FILE} ({CACHE_FILE.stat().st_size} bytes)")
        except Exception as e:
            print(f"\n⚠️ 缓存写入失败: {e}")

        elapsed = (datetime.now() - self.start_time).total_seconds()
        print(f"\n✅ 完成 · 总计 {result['total']} 条 · 耗时 {elapsed:.1f}s")

        return result

    @staticmethod
    def load_cache() -> Optional[Dict]:
        """读取缓存的新闻数据（检查 TTL）"""
        if not CACHE_FILE.exists():
            return None
        try:
            data = json.loads(CACHE_FILE.read_text())
            ts = data.get("timestamp", "")
            if ts:
                try:
                    data_dt = datetime.fromisoformat(ts)
                    age = (datetime.now() - data_dt).total_seconds()
                    if age < CACHE_TTL:
                        return data
                except Exception:
                    pass
        except Exception:
            pass
        return None

    @staticmethod
    def get_cache_age() -> Optional[float]:
        """获取缓存年龄（秒），无缓存返回 None"""
        if not CACHE_FILE.exists():
            return None
        try:
            data = json.loads(CACHE_FILE.read_text())
            ts = data.get("timestamp", "")
            if ts:
                data_dt = datetime.fromisoformat(ts)
                return (datetime.now() - data_dt).total_seconds()
        except Exception:
            pass
        return None


# ════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="新闻管线 v3")
    parser.add_argument(
        "--mode", choices=["full", "quick"], default="full",
        help="full=全部源, quick=仅快讯/电报（不抓个股）"
    )
    parser.add_argument(
        "--cache-only", action="store_true",
        help="仅打印缓存状态"
    )
    args = parser.parse_args()

    if args.cache_only:
        data = NewsPipeline.load_cache()
        if data:
            print(f"✅ 缓存命中 · {data['timestamp'][:19]} · {data['total']} 条")
        else:
            print("❌ 缓存为空或已过期")
        sys.exit(0)

    pipeline = NewsPipeline(mode=args.mode)
    pipeline.run()
