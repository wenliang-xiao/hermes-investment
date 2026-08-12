#!/usr/bin/env python3
"""
面基因子日扫 v2 — 分批包装，解决蜻蜓CSC单只~37s的耗时问题。
分批扫描 → 磁盘持久化 → 合并 → 生成 scan_snapshot。

用法：
    python3 scripts/run_factor_daily_batched.py

依赖：
    scripts/merge_batches_today.py  (已存在，处理最终合并+快照)
"""
import sys, os, json, logging, time
from datetime import date

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 配置 ──
BATCH_SIZE = 20        # 每批 ≈ 20只 × 37s = ~740s ≈ 12min
BATCH_COUNT = 4        # 4批 × 20 = 80只（覆盖核心池）
SAVE_DIR = os.path.join(_PROJECT_DIR, "data")


def get_a_share_universe() -> list[str]:
    """获取A股扫描池（与 run_factor_daily.py 一致）"""
    try:
        from domain.stock_universe import ALL_CORE_STOCKS, LDS_SECTORS
        all_syms = set()
        for sec_syms in LDS_SECTORS.values():
            for s in sec_syms:
                if len(str(s)) == 6:
                    all_syms.add(str(s))
        symbols = [str(s) for s in ALL_CORE_STOCKS if len(str(s)) == 6]
        for s in all_syms:
            if s not in symbols:
                symbols.append(s)
        logger.info(f"[batched] A股全量池: {len(symbols)} 只")
        return symbols
    except ImportError:
        logger.warning("[batched] 无法导入domain.stock_universe，使用默认池")
        return ["300502", "688041", "688008", "002371", "603259",
                "688256", "600519", "000858", "300750", "002594",
                "000333", "002415", "000651", "002304", "600585"]


def get_hk_us_universe() -> list[str]:
    """获取港美股扫描池"""
    try:
        from config import WATCHLIST
        hk_syms = [s for s in WATCHLIST if '.HK' in str(s).upper() and isinstance(WATCHLIST[s], dict)]
        logger.info(f"[batched] 港美股池: {len(hk_syms)} 只")
        return hk_syms
    except ImportError:
        logger.warning("[batched] 无法导入config.WATCHLIST，使用默认港美股")
        return ["0700.HK", "9988.HK", "0981.HK", "2899.HK", "6181.HK",
                "3690.HK", "1810.HK", "0941.HK", "1211.HK"]


def run_batch(symbols: list[str], batch_index: int, macro_state: str = "扩张期") -> bool:
    """运行一批扫描，保存到 factor_daily_batch{N}.json"""
    from engine.factor_engine import FactorEngine

    logger.info(f"[batched] ⏳ Batch #{batch_index}: {len(symbols)} 只标的 starting...")
    engine = FactorEngine()
    
    try:
        start = time.time()
        scored = engine.score_batch(symbols, macro_state=macro_state)
        elapsed = time.time() - start
        
        # 取TOP N
        top_n = min(30, len(scored))
        top_results = scored[:top_n]
        
        # 组装输出
        output = {
            "date": date.today().isoformat(),
            "macro_state": macro_state,
            "total_scored": len(scored),
            "top_n": top_n,
            "batch_index": batch_index,
            "elapsed_seconds": round(elapsed, 1),
            "weights_used": scored[0]["weights_used"] if scored else {},
            "top_results": [
                {
                    "rank": i + 1,
                    "symbol": r["symbol"],
                    "composite": r["composite"],
                    "scores": r["scores"],
                    "macro_state": r["macro_state"],
                }
                for i, r in enumerate(top_results)
            ],
        }
        
        out_path = os.path.join(SAVE_DIR, f"factor_daily_batch{batch_index}.json")
        with open(out_path, "w") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[batched] ✅ Batch #{batch_index}: {len(scored)} scored, "
                    f"{elapsed:.0f}s -> {out_path}")
        if scored:
            logger.info(f"[batched]    Top: {scored[0]['symbol']} composite={scored[0]['composite']:.4f}")
        return True
    except Exception as e:
        logger.error(f"[batched] ❌ Batch #{batch_index} failed: {e}")
        return False


def main():
    logger.info("=" * 60)
    logger.info("📊 面基因子日扫 v2 (分批包装)")
    logger.info("=" * 60)

    # 清理旧的batch文件（避免残留干扰）
    for i in range(1, 5):
        old = os.path.join(SAVE_DIR, f"factor_daily_batch{i}.json")
        if os.path.exists(old):
            os.remove(old)
            logger.info(f"[batched] 清理旧batch: factor_daily_batch{i}.json")

    # ── 1. A股分批扫描 ──
    a_symbols = get_a_share_universe()
    logger.info(f"\n[batched] 🏗️  A股扫描: {len(a_symbols)} 只, 分 {BATCH_COUNT} 批 (每批~{BATCH_SIZE}只)")

    batches = [a_symbols[i:i + BATCH_SIZE] for i in range(0, len(a_symbols), BATCH_SIZE)]
    # 只跑设定的 BATCH_COUNT 批
    batches = batches[:BATCH_COUNT]

    all_ok = True
    for bi, batch in enumerate(batches, start=1):
        ok = run_batch(batch, bi)
        if not ok:
            all_ok = False
            logger.error(f"[batched] ❌ Batch #{bi} 失败，继续下一批")
        # 批次间短暂休眠，避免API限频累积
        if bi < len(batches):
            logger.info(f"[batched]   批次间休眠 3s...")
            time.sleep(3)

    # ── 2. 港美股扫描（作为batch5） ──
    hk_us = get_hk_us_universe()
    if hk_us:
        logger.info(f"\n[batched] 🌏 港美股扫描: {len(hk_us)} 只")
        run_batch(hk_us, 5)
    else:
        logger.info("[batched] 🌏 无港美股标的，跳过")

    # ── 3. 合并+快照 ──
    logger.info(f"\n[batched] 🔗 运行 merge_batches_today.py...")
    import subprocess
    try:
        result = subprocess.run(
            [sys.executable, os.path.join(_SCRIPT_DIR, "merge_batches_today.py")],
            cwd=_PROJECT_DIR, capture_output=True, text=True, timeout=60
        )
        if result.returncode == 0:
            logger.info("[batched] ✅ 合并+快照完成")
            for line in result.stdout.strip().split("\n"):
                logger.info(f"  {line}")
        else:
            logger.error(f"[batched] ❌ 合并失败 (exit={result.returncode})")
            logger.error(f"  stderr: {result.stderr[:500]}")
            all_ok = False
    except Exception as e:
        logger.error(f"[batched] ❌ 合并异常: {e}")
        all_ok = False

    # ── 4. 摘要 ──
    snap_dir = os.path.join(SAVE_DIR, "scan_snapshots")
    snapshots = sorted([
        f for f in os.listdir(snap_dir)
        if f.startswith("scan_snapshot_20") and f.endswith(".json")
    ]) if os.path.exists(snap_dir) else []
    
    logger.info("=" * 60)
    logger.info(f"📊 面基因子日扫 完成 | {date.today().isoformat()}")
    logger.info(f"   状态: {'✅ 成功' if all_ok else '⚠️ 部分失败'}")
    logger.info(f"   总快照: {len(snapshots)} 天 (需要60+天)")
    logger.info(f"   批次: {BATCH_COUNT}批A股 + 1批港美股")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
