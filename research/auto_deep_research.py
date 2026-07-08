"""
analysis/auto_deep_research.py — 深度研报自动触发

从 data/pool/deep.json 读取深度层标的，
对每个标的调用 deep_research.py 的 ResearchReport，
输出到 data/deep_research_output/ 目录。

用法:
    python3 analysis/auto_deep_research.py
"""

import sys, os, json, logging
from datetime import datetime
from pathlib import Path

# Path setup
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def load_deep_pool() -> list[dict]:
    """读取深度层标的池"""
    pool_path = os.path.join(_PROJECT_ROOT, "data", "pool", "deep.json")
    try:
        with open(pool_path) as f:
            data = json.load(f)
        logger.info(f"从 {pool_path} 读取深度层标的: {len(data)} 只")
        return data
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning(f"深度层文件不存在或格式错误: {e}")
        return []


def run_deep_research(symbol: str, name: str = "") -> dict:
    """对单个标的运行深度研报"""
    from research.deep_research import ResearchReport
    report = ResearchReport(symbol=symbol, name=name)
    return report.run()


def save_report(symbol: str, report: dict):
    """将研报保存到 data/deep_research_output/"""
    output_dir = os.path.join(_PROJECT_ROOT, "data", "deep_research_output")
    os.makedirs(output_dir, exist_ok=True)
    safe_symbol = symbol.replace(".", "_").replace(":", "_")
    filename = f"{safe_symbol}_{datetime.now().strftime('%Y%m%d')}.json"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"研报已保存: {filepath}")
    return filepath


def main():
    logger.info("=" * 60)
    logger.info("深度研报自动触发 — auto_deep_research")
    logger.info("=" * 60)

    # 读取深度层
    deep_pool = load_deep_pool()
    if not deep_pool:
        logger.info("深度层为空，使用 watch 层作为备选")
        # fallback: use watch layer
        watch_pool = []
        watch_path = os.path.join(_PROJECT_ROOT, "data", "pool", "watch.json")
        try:
            with open(watch_path) as f:
                watch_pool = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        if watch_pool:
            # 取前 3 只作为演示
            deep_pool = watch_pool[:3]
            logger.info(f"从 watch 层取前 {len(deep_pool)} 只作为演示")
        else:
            # 硬编码演示标的
            deep_pool = [
                {"symbol": "300502", "score": 0.0, "name": "新易盛"},
                {"symbol": "688041", "score": 0.0, "name": "海光信息"},
                {"symbol": "600519", "score": 0.0, "name": "贵州茅台"},
            ]
            logger.info("使用硬编码演示标的")

    logger.info(f"将处理 {len(deep_pool)} 只标的")
    results = {}

    for i, item in enumerate(deep_pool):
        symbol = item.get("symbol", "")
        name = item.get("name", item.get("symbol", ""))
        score = item.get("score", 0)
        logger.info(f"[{i+1}/{len(deep_pool)}] {symbol} ({name}) — 综合分={score}")

        if not symbol:
            logger.warning(f"  ⚠️ 跳过: 无 symbol")
            continue

        try:
            report = run_deep_research(symbol, name)
            filepath = save_report(symbol, report)
            results[symbol] = {
                "status": "success",
                "file": filepath,
                "score": report.get("overall_score", 0),
                "verdict": report.get("verdict", ""),
            }
            logger.info(f"  ✅ {symbol}: 综合评分 {report.get('overall_score', 'N/A')}")
        except Exception as e:
            logger.error(f"  ❌ {symbol}: 失败 — {e}")
            import traceback
            traceback.print_exc()
            results[symbol] = {"status": "error", "error": str(e)}

    # 汇总
    print("\n" + "=" * 60)
    print("📊 深度研报自动触发 — 汇总")
    print("=" * 60)
    success = sum(1 for r in results.values() if r["status"] == "success")
    failed = sum(1 for r in results.values() if r["status"] == "error")
    print(f"总标的: {len(results)}, 成功: {success}, 失败: {failed}")
    for symbol, res in results.items():
        if res["status"] == "success":
            print(f"  ✅ {symbol}: {res['verdict']} (评分 {res['score']})")
        else:
            print(f"  ❌ {symbol}: {res.get('error', '未知错误')}")

    # 保存汇总
    summary_path = os.path.join(
        _PROJECT_ROOT, "data", "deep_research_output",
        f"_summary_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    )
    with open(summary_path, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"汇总已保存: {summary_path}")


if __name__ == "__main__":
    main()
