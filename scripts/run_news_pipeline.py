#!/usr/bin/env python3
"""
新闻管线每日运行脚本 v3
可被 cron 调用，运行完整新闻抓取管线

用法:
  python3 scripts/run_news_pipeline.py               # 全量运行
  python3 scripts/run_news_pipeline.py --mode quick  # 仅快讯/电报
  python3 scripts/run_news_pipeline.py --cache-only  # 仅查看缓存状态

Cron 示例 (每 30 分钟):
  */30 * * * * cd ~/.hermes/investment_system && python3 scripts/run_news_pipeline.py >> logs/news_pipeline.log 2>&1
"""

import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_PROJECT_DIR))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="新闻管线每日运行 v3")
    parser.add_argument(
        "--mode", choices=["full", "quick"], default="full",
        help="full=全部源, quick=仅快讯/电报"
    )
    parser.add_argument(
        "--cache-only", action="store_true",
        help="仅打印缓存状态"
    )
    args = parser.parse_args()

    # 加载环境变量
    env_file = _PROJECT_DIR / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file)
        except ImportError:
            pass

    from news.pipeline import NewsPipeline

    if args.cache_only:
        data = NewsPipeline.load_cache()
        if data:
            print(f"✅ 缓存命中 · {data['timestamp'][:19]} · {data['total']} 条")
        else:
            print("❌ 缓存为空或已过期")
        sys.exit(0)

    pipeline = NewsPipeline(mode=args.mode)
    result = pipeline.run()
    print(f"\n完成: {result['total']} 条新闻, 时间: {result['timestamp'][:19]}")
