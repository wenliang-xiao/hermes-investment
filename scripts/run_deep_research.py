#!/usr/bin/env python3
"""
scripts/run_deep_research.py — 深度研报日度生成脚本

从 data/pool/deep.json 读取深度层标的，
对每个标的调用 LLM (GLM-4-Flash) 生成结构化研报，
输出到 data/research_reports/。

用法:
    python3 scripts/run_deep_research.py                    # 增量运行（跳过<7天已有报告）
    python3 scripts/run_deep_research.py --force            # 强制全部重新生成
    python3 scripts/run_deep_research.py --max 3            # 限制数量
    python3 scripts/run_deep_research.py --symbol 300502    # 只生成指定标的

环境变量:
    ARK_API_KEY — GLM-4-Flash API 密钥（必需）
"""

import sys, os, logging

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    force = "--force" in sys.argv or "-f" in sys.argv
    max_stocks = 5

    # 解析 --max
    for i, arg in enumerate(sys.argv):
        if arg == "--max" and i + 1 < len(sys.argv):
            try:
                max_stocks = int(sys.argv[i + 1])
            except ValueError:
                pass

    # 解析 --symbol
    single_symbol = None
    for i, arg in enumerate(sys.argv):
        if arg == "--symbol" and i + 1 < len(sys.argv):
            single_symbol = sys.argv[i + 1]

    logger.info("=" * 60)
    logger.info("深度研报日度生成 — run_deep_research")
    logger.info(f"force={force}, max={max_stocks}, symbol={single_symbol or 'all'}")
    logger.info("=" * 60)

    from research.deep_research_v2 import DeepResearchGenerator

    gen = DeepResearchGenerator()

    if single_symbol:
        # 单只标的研究
        logger.info(f"生成 {single_symbol} 研报...")
        try:
            report = gen.generate_report(single_symbol)
            filepath = gen.save_report(single_symbol, report)
            logger.info(f"✅ 成功: {filepath}")
            logger.info(f"  signal={report.get('signal')}, score={report.get('score', 0):.4f}")
            
            # 打印关键信息
            sections = report.get("sections", {})
            for sec_name, content in sections.items():
                preview = content[:80] + "..." if len(content) > 80 else content
                logger.info(f"  [{sec_name}] {preview}")
        except Exception as e:
            logger.error(f"❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)
    else:
        # 批量运行
        results = gen.run_batch(max_stocks=max_stocks, force=force)

        # 打印汇总
        print("\n" + "=" * 60)
        print("📊 深度研报生成 — 汇总")
        print("=" * 60)
        print(f"成功: {results['success']}, 跳过(已有): {results['skipped']}, 失败: {results['failed']}")

        for detail in results.get("details", []):
            if detail["status"] == "success":
                print(f"  ✅ {detail['symbol']}: {detail['signal']} (评分 {detail['score']:.4f})")
            else:
                print(f"  ❌ {detail['symbol']}: {detail.get('error', '未知')}")

        # 保存汇总
        from datetime import datetime
        summary_path = os.path.join(
            _PROJECT_ROOT, "data", "research_reports",
            f"_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
        )
        os.makedirs(os.path.dirname(summary_path), exist_ok=True)
        import json
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"汇总保存: {summary_path}")


if __name__ == "__main__":
    main()
