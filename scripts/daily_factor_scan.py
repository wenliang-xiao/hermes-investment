#!/usr/bin/env python3
"""
scripts/daily_factor_scan.py — 面基因子日扫·单入口编排器（cron 专用）

README
======
这是 faceji-factor-daily-scan cron job 的确定性执行入口（no_agent 模式）。
它把原本分散、易被 LLM 误解的多步骤流水线（A股分批扫 + 港美股扫 + 合并 +
票池更新 + 扫描快照 + 日期累计）固化成单个可重复运行的脚本，避免依赖 agent
每日重新推导命令。

用法:
    cd /home/admin/.hermes/investment_system && \\
        /home/admin/.hermes/hermes-agent/venv/bin/python scripts/daily_factor_scan.py

行为:
  - 跨批续扫: 复用 data/factor_daily_batch{N}.json 作为已完成的批标记。
    同一天内重跑会跳过已完成批次 -> 天然支持"被超时打断后重跑续扫"。
  - 时间预算: 默认 per-run 预算 20 分钟(time_budget_seconds)。超时会停止
    启动新批, 但会先 merge 已完成的批 + 生成当前快照, 避免数据全丢。
  - 输出: stdout 打印人类可读摘要, 供 cron no_agent 原样投递。

退出码:
  0  全量扫描完成
  1  部分完成(有时间预算/批失败) —— 但仍生成快照
  2  完全失败(无可合并批次产物)
"""
import sys, os, json, logging, time, subprocess
from datetime import date

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ── 配置 ──────────────────────────────────────────────
DEFAULT_TIME_BUDGET = int(os.environ.get("FACTOR_SCAN_TIME_BUDGET", "1200"))  # 秒
# 跑几个批(每批约 20 只A股, ~15min)。全量=4批 + 第5批港美股。
A_BATCHES = 4
A_BATCH_SIZE = 20
HK_US_BATCH_INDEX = 5
SNAP_LOG = os.path.join(_PROJECT_DIR, "data", "scan_snapshot_days.log")


def _batch_files() -> list[str]:
    return [os.path.join(_PROJECT_DIR, "data", f"factor_daily_batch{i}.json")
            for i in range(1, A_BATCHES + 2)]  # 1..5


def _fresh_batch_files_today() -> list[str]:
    """仅保留今天生成的 batch 文件(避免跨天复用昨日的过期批次)。"""
    today = date.today().isoformat()
    fresh = []
    for bf in _batch_files():
        if os.path.exists(bf):
            try:
                d = json.load(open(bf))
                if d.get("date") == today:
                    fresh.append(bf)
            except Exception:
                pass
    return fresh


def _snapshot_count() -> int:
    snap_dir = os.path.join(_PROJECT_DIR, "data", "scan_snapshots")
    if not os.path.isdir(snap_dir):
        return 0
    return len([f for f in os.listdir(snap_dir)
                if f.startswith("scan_snapshot_20") and f.endswith(".json")])


def _clean_old_batches():
    today = date.today().isoformat()
    for bf in _batch_files():
        if not os.path.exists(bf):
            continue
        try:
            d = json.load(open(bf))
            if d.get("date") != today:
                os.remove(bf)
                logger.info(f"清理过期批次: {os.path.basename(bf)}")
        except Exception:
            os.remove(bf)


def main() -> int:
    budget = DEFAULT_TIME_BUDGET
    start_wall = time.time()
    logger.info(f"{'='*60}")
    logger.info(f"📊 面基因子日扫编排器 | {date.today().isoformat()} | 时间预算 {budget}s")

    # 跨天清理: 本日若是全新的一天, 清掉昨日残留批文件, 从零开始
    _clean_old_batches()

    from domain.stock_universe import ALL_CORE_STOCKS, LDS_SECTORS

    # ── 1. 构建 A 股扫描池 ──
    all_syms = set()
    for sec_syms in LDS_SECTORS.values():
        for s in sec_syms:
            if len(str(s)) == 6:
                all_syms.add(str(s))
    a_symbols = [str(s) for s in ALL_CORE_STOCKS if len(str(s)) == 6]
    for s in all_syms:
        if s not in a_symbols:
            a_symbols.append(s)
    logger.info(f"[scan] A股池: {len(a_symbols)} 只, 分 {A_BATCHES} 批(每批~{A_BATCH_SIZE})")

    batches = [a_symbols[i:i + A_BATCH_SIZE]
               for i in range(0, len(a_symbols), A_BATCH_SIZE)][:A_BATCHES]

    from engine.factor_engine import FactorEngine

    completed_batches = set()
    ok_all = True

    # 已完成的批(今天已有产物)直接跳过
    fresh = _fresh_batch_files_today()
    for bf in fresh:
        # 排除 HK/US (第5批)
        if bf.endswith(f"batch{HK_US_BATCH_INDEX}.json"):
            continue
        try:
            idx = int(os.path.basename(bf).replace("factor_daily_batch", "").replace(".json", ""))
            if 1 <= idx <= A_BATCHES:
                completed_batches.add(idx)
        except Exception:
            pass
    if completed_batches:
        logger.info(f"[scan] 今天已完成批次(跳过): {sorted(completed_batches)}")

    # ── 2. 逐批扫描(尊重时间预算) ──
    for bi in range(1, A_BATCHES + 1):
        if bi in completed_batches:
            continue
        if time.time() - start_wall > budget:
            logger.warning(f"[scan] 时间预算用尽, 停止启动新批(Batch#{bi})")
            ok_all = False
            break
        batch = batches[bi - 1]
        logger.info(f"[scan] ⏳ Batch#{bi}: {len(batch)} 只 starting...")
        engine = FactorEngine()
        b_start = time.time()
        try:
            scored = engine.score_batch(batch, macro_state="扩张期")
            elapsed = time.time() - b_start
            top = scored[:30]
            out = {
                "date": date.today().isoformat(),
                "macro_state": "扩张期",
                "total_scored": len(scored),
                "top_n": len(top),
                "batch_index": bi,
                "elapsed_seconds": round(elapsed, 1),
                "weights_used": scored[0]["weights_used"] if scored else {},
                "top_results": [{
                    "rank": i + 1, "symbol": r["symbol"], "composite": r["composite"],
                    "scores": r["scores"], "macro_state": r["macro_state"],
                } for i, r in enumerate(top)],
            }
            path = os.path.join(_PROJECT_DIR, "data", f"factor_daily_batch{bi}.json")
            with open(path, "w") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            logger.info(f"[scan] ✅ Batch#{bi}: {len(scored)} scored, {elapsed:.0f}s")
            if scored:
                logger.info(f"[scan]    Top: {scored[0]['symbol']} composite={scored[0]['composite']:.4f}")
        except Exception as e:
            logger.error(f"[scan] ❌ Batch#{bi} failed: {e}")
            ok_all = False
        # 内存释放 (2026-08-24 OOM 修复): 本机 1.8GB 无 swap, 每批的 engine 缓存
        # (250天日线 DataFrame + 财报) 不显式释放会跨批累积 → OOM kill。
        finally:
            try:
                engine.clear_cache()
            except Exception:
                pass
            del engine
            import gc
            gc.collect()
        # 批次间 3s 间隔避免限频
        if bi < A_BATCHES:
            time.sleep(3)

    # ── 3. 港美股扫描(作为批5, 若时间允许) ──
    hk_batch_exists = os.path.exists(_batch_files()[HK_US_BATCH_INDEX - 1])
    if time.time() - start_wall <= budget:
        if not hk_batch_exists:
            try:
                from config import WATCHLIST
                hk = [k for k in WATCHLIST if ".HK" in str(k).upper()]
            except Exception:
                hk = ["0700.HK", "9988.HK", "0981.HK", "2899.HK", "6181.HK",
                      "3690.HK", "1810.HK", "0941.HK", "1211.HK"]
            if hk:
                logger.info(f"[scan] 🌏 HK/US: {len(hk)} 只")
                try:
                    engine = FactorEngine()
                    scored = engine.score_batch(hk, macro_state="扩张期")
                    top = scored[:30]
                    out = {
                        "date": date.today().isoformat(), "macro_state": "扩张期",
                        "total_scored": len(scored), "top_n": len(top),
                        "batch_index": HK_US_BATCH_INDEX,
                        "elapsed_seconds": 0.0,
                        "weights_used": scored[0]["weights_used"] if scored else {},
                        "top_results": [{"rank": i + 1, "symbol": r["symbol"],
                                         "composite": r["composite"], "scores": r["scores"],
                                         "macro_state": r["macro_state"]} for i, r in enumerate(top)],
                    }
                    path = os.path.join(_PROJECT_DIR, "data", f"factor_daily_batch{HK_US_BATCH_INDEX}.json")
                    with open(path, "w") as f:
                        json.dump(out, f, ensure_ascii=False, indent=2)
                    logger.info(f"[scan] ✅ HK/US: {len(scored)} scored")
                except Exception as e:
                    logger.error(f"[scan] ❌ HK/US failed: {e}")
                finally:
                    try:
                        engine.clear_cache()
                    except Exception:
                        pass
                    del engine
                    import gc
                    gc.collect()
        else:
            logger.info("[scan] 🌏 HK/US 已有今日产物, 跳过")
    else:
        logger.warning("[scan] 时间预算用尽, 跳过 HK/US")

    # ── 4. 合并 + 快照 ──
    fresh = _fresh_batch_files_today()
    if not fresh:
        logger.error("[scan] ❌ 无可合并的今日批次产物 —— 扫描完全失败")
        return 2

    logger.info("[scan] 🔗 运行 merge_batches_today.py ...")
    r = subprocess.run(
        [sys.executable, os.path.join(_SCRIPT_DIR, "merge_batches_today.py")],
        cwd=_PROJECT_DIR, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        logger.error(f"[scan] ❌ 合并失败: {r.stderr[:500]}")
        ok_all = False
    else:
        for line in r.stdout.strip().split("\n"):
            logger.info(f"  {line}")

    # ── 5. 摘要 ──
    snaps = _snapshot_count()
    done_now = len(_fresh_batch_files_today())  # 本次完成后今日已产出的批数(1..5)
    total_batches = A_BATCHES + 1  # A股4批 + 港美股1批
    full_ok = (done_now >= total_batches) and ok_all
    logger.info("=" * 60)
    logger.info(f"📊 面基因子日扫 完成 | {date.today().isoformat()}")
    if full_ok:
        status = "✅ 全量成功"
    elif done_now > 0:
        status = f"⚠️ 部分完成 ({done_now}/{total_batches} 批)"
    else:
        status = "❌ 失败(无批次产物)"
    logger.info(f"   状态: {status} | 今日批次: {done_now}/{total_batches} | 累计快照: {snaps} 天 (目标60+)")
    logger.info(f"   耗时: {time.time()-start_wall:.0f}s")
    logger.info("=" * 60)
    return 0 if full_ok else (1 if done_now > 0 else 2)


if __name__ == "__main__":
    sys.exit(main())
