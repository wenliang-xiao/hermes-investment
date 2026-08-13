#!/usr/bin/env python3
"""
scripts/cron_watchdog.py — 因子扫描快照看门狗（cron no_agent 模式）

行为：
  检查最近 N 个交易日是否生成了 scan_snapshot_YYYY-MM-DD.json。
  - 全部正常 → 无 stdout（静默，cron no_agent 模式不投递）＝ watchdog pattern
  - 有缺失 → 打印缺失日期 + 最后好快照日期 + 建议动作 → 投递给用户

用法（配合 Hermes cron no_agent=True）：
  cd /home/admin/.hermes/investment_system && \
    /home/admin/.hermes/hermes-agent/venv/bin/python scripts/cron_watchdog.py
"""
import os, sys
from datetime import date, timedelta

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(_PROJECT_DIR, "data", "scan_snapshots")

# 检查最近多少个交易日（不含今天，因为扫描在 09:30，早于某时刻可能未跑完）
LOOKBACK_DAYS = 5
# 允许的快照滞后天数（比如今早还没跑，允许昨天的快照）
GRACE_TODAY = True


def _is_weekday(d: date) -> bool:
    return d.weekday() < 5  # 0-4 周一~周五


def main() -> int:
    if not os.path.isdir(SNAP_DIR):
        print(f"❌ [watchdog] 快照目录不存在: {SNAP_DIR}（因子扫描从未成功？）")
        return 0

    files = os.listdir(SNAP_DIR)
    have_dates = set()
    for f in files:
        if f.startswith("scan_snapshot_") and f.endswith(".json"):
            ds = f[len("scan_snapshot_"):-len(".json")]
            try:
                have_dates.add(date.fromisoformat(ds))
            except ValueError:
                pass

    # 收集最近 N 个工作日（不含今天，今天让 morning 扫描跑完）
    missing = []
    d = date.today()
    candidate = []
    while len(candidate) < LOOKBACK_DAYS:
        d = d - timedelta(days=1)
        if _is_weekday(d):
            candidate.append(d)

    latest_have = max(have_dates) if have_dates else None

    for cd in candidate:
        if cd not in have_dates:
            missing.append(cd)

    if not missing:
        return 0  # 静默——全正常

    # 有缺失 → 输出告警
    print(f"⚠️ [watchdog] 因子扫描快照缺失检测")
    print(f"最近 {LOOKBACK_DAYS} 个交易日内缺失 {len(missing)} 天快照:")
    for m in missing:
        print(f"  - {m.isoformat()}")
    print(f"最后可用快照: {latest_have.isoformat() if latest_have else '无'}")
    print("")
    print("建议动作:")
    print("  1. 检查 faceji-factor-daily-scan 盘前 cron 是否正常运行")
    print(f"  2. 手动补扫: cd {_PROJECT_DIR} && /home/admin/.hermes/hermes-agent/venv/bin/python scripts/daily_factor_scan.py")
    print("  3. 回测需累计 60+ 天快照，请勿忽略连续缺失")
    return 0


if __name__ == "__main__":
    sys.exit(main())
