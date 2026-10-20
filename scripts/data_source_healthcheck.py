#!/usr/bin/env python3
"""
scripts/data_source_healthcheck.py — 数据源健康自检 (扫描前置守卫)

背景 (2026-10-20): 因子引擎曾在数据源整体断链时静默产出残废因子
(87/89 只 momentum 降级为中性 0.5)。根因是"有防护的假象"——
baostock 全站 TCP 不可达 + A股降级源缺失, 但引擎不报错, 只静默降级。

本脚本在每日扫描前探测各数据源 TCP 可达性 + 实际取数能力,
不可用则**明确告警**(非零退出), 让 cron 能发现"今天因子不可信",
而不是静默产出。

用法:
  python3 scripts/data_source_healthcheck.py          # 人类可读
  python3 scripts/data_source_healthcheck.py --json   # 机器可读
  python3 scripts/data_source_healthcheck.py --quiet  # 仅异常时输出

退出码: 0=全部健康  1=有降级(部分源不可用)  2=关键源全挂
"""
from __future__ import annotations
import argparse
import json
import socket
import sys
import time
from pathlib import Path

_PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_DIR))

# (名称, host, port, 是否关键) — 关键源不可用则整体不可信
ENDPOINTS = [
    ("baostock", "baostock.com", 10030, False),   # A股主源(可降级)
    ("sina_hist", "finance.sina.com.cn", 443, True),  # A股降级源(关键)
    ("eastmoney", "push2.eastmoney.com", 443, False),  # ETF/实时(可降级)
    ("tencent_rt", "qt.gtimg.cn", 80, False),     # 实时行情
]


def _tcp_probe(host: str, port: int, timeout: float = 6.0) -> tuple[bool, float]:
    """TCP 可达性探测。返回 (ok, 耗时秒)"""
    t0 = time.time()
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True, time.time() - t0
    except Exception:
        return False, time.time() - t0


def _functional_probe() -> dict:
    """实际取数探测: 对 A股样本走 get_history, 验证能拿到当日数据。

    独立于 TCP 探测 — TCP 通不代表能取到数(如接口改版/返回空)。
    """
    result = {"symbol": "600030", "rows": 0, "last_date": None, "source_ok": False, "elapsed": 0.0}
    t0 = time.time()
    try:
        from data.data_router import get_history
        h = get_history("600030", days=250)
        if h and h.get("dates"):
            result["rows"] = len(h["dates"])
            result["last_date"] = h["dates"][-1]
            # 数据新鲜度: 最近 7 个自然日内视为新鲜
            from datetime import datetime, timedelta
            try:
                last = datetime.strptime(h["dates"][-1][:10], "%Y-%m-%d")
                result["source_ok"] = (datetime.now() - last) <= timedelta(days=7)
            except Exception:
                result["source_ok"] = result["rows"] > 0
    except Exception as e:
        result["error"] = str(e)
    result["elapsed"] = round(time.time() - t0, 1)
    return result


def run_checks() -> dict:
    checks = []
    for name, host, port, critical in ENDPOINTS:
        ok, dt = _tcp_probe(host, port)
        checks.append({
            "name": name, "host": f"{host}:{port}", "ok": ok,
            "critical": critical, "elapsed": round(dt, 2),
        })

    func = _functional_probe()

    any_critical_down = any((not c["ok"]) and c["critical"] for c in checks)
    # A股链是否可用: baostock 或 sina 任一 + 功能探测成功
    a_share_ok = func["source_ok"]
    degraded = any(not c["ok"] for c in checks)

    if any_critical_down or not a_share_ok:
        status = 2 if not a_share_ok else 1
    elif degraded:
        status = 1
    else:
        status = 0

    return {
        "status": status,
        "status_label": {0: "healthy", 1: "degraded", 2: "critical"}[status],
        "a_share_ok": a_share_ok,
        "endpoints": checks,
        "functional": func,
        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    ap.add_argument("--quiet", action="store_true", help="仅异常时输出")
    args = ap.parse_args()

    r = run_checks()

    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.quiet:
        if r["status"] != 0:
            print(f"⚠️ 数据源 {r['status_label']}: "
                  f"A股链={'OK' if r['a_share_ok'] else 'DOWN'}, "
                  f"详情见 --json")
    else:
        icon = {0: "✅", 1: "⚠️", 2: "🔴"}[r["status"]]
        print(f"{icon} 数据源健康: {r['status_label'].upper()} @ {r['checked_at']}")
        for c in r["endpoints"]:
            tag = "关键" if c["critical"] else "    "
            mark = "OK " if c["ok"] else "DOWN"
            print(f"  [{mark}] {tag} {c['name']:12s} {c['host']:28s} {c['elapsed']:.2f}s")
        f = r["functional"]
        print(f"  功能探测: {f['symbol']} → {f['rows']} 行, 最新 {f['last_date']}, "
              f"{'新鲜' if f['source_ok'] else '⚠️陈旧/失败'}, {f['elapsed']}s")
        if r["status"] == 2:
            print("  🔴 关键源不可用 — 今日因子不可信, 请勿据此选股!")
        elif r["status"] == 1:
            print("  ⚠️ 部分源降级 — 因子可能走降级源, 精度下降")

    sys.exit(r["status"])


if __name__ == "__main__":
    main()
