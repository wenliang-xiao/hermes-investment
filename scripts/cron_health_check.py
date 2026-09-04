#!/usr/bin/env python3
"""
scripts/cron_health_check.py — 面基投资系统 Cron 统一健康检查入口
==================================================================
任何助手（面基助手 / opencode / Claude / 人工）一条命令即可看清:
  1. 全部 Hermes cron 任务清单 + 调度 + 最近状态
  2. 关键数据文件新鲜度（数据管线是否活着）
  3. 回测快照累积进度（60 天目标）
  4. 已知故障/告警（今日失败、陈旧数据、缺快照）

用法:
    /home/admin/.hermes/hermes-agent/venv/bin/python scripts/cron_health_check.py
    # 或 hermes 任意会话里 terminal 运行

输出: 退出码 0=健康, 1=有告警（陈旧数据/今日失败/缺快照）— 可 cron 化巡检。

依赖: 仅 stdlib + 读 ~/.hermes/cron 状态 + data 目录 mtime, 无网络调用。
"""
import json
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = Path("/home/admin/.hermes/investment_system")
CRON_DIR = Path.home() / ".hermes" / "cron" / "output"
SNAPSHOT_DIR = PROJECT / "data" / "scan_snapshots"

# 关键数据文件 → 可接受最大新鲜度(小时)
DATA_FILES = {
    "data/factor_daily.json": 30,          # 因子日扫合并产物 (07:00 cron, 全量~90min)
    "data/scan_snapshots/": 30,            # 快照目录 (看目录内最新文件)
    "data/etf_discovery.json": 26,         # ETF 每日 20:00
    "data/dragon_tiger.json": 26,          # 龙虎榜 17:20
    "data/news_cache.json": 4,             # 新闻每2h快速刷新
    "data/shadow_event_history.json": 26,  # 事件影子 08:00
}

# 实时 cron 状态 (从 Hermes cron 状态文件读取, 兼容 hermes cron list)
CRON_STATE = Path.home() / ".hermes" / "cron" / "cron_jobs.json"


def _age_hours(path: Path) -> float | None:
    if not path.exists():
        return None
    return (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600.0


def _latest_snapshot() -> Path | None:
    if not SNAPSHOT_DIR.exists():
        return None
    snaps = sorted(SNAPSHOT_DIR.glob("scan_snapshot_*.json"))
    return snaps[-1] if snaps else None


def _load_cron_jobs() -> list[dict]:
    """解析 `hermes cron list` 文本输出为任务列表。"""
    try:
        out = subprocess.run(
            ["hermes", "cron", "list"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception as e:
        print(f"[warn] hermes cron list 失败: {e}")
        return []
    jobs: list[dict] = []
    cur: dict | None = None
    for line in out.splitlines():
        s = line.strip()
        # 新任务块: '  ec73ef6de848 [active]'
        if s and s[0].isalnum() and len(s.split()[0]) == 12 and "[" in s:
            if cur:
                jobs.append(cur)
            cur = {"job_id": s.split()[0], "name": "", "schedule": "",
                   "last_run_at": "", "last_status": ""}
            continue
        if cur is None:
            continue
        for key, label in (("name", "Name:"), ("schedule", "Schedule:"),
                           ("last_run_at", "Last run:")):
            if label in s:
                cur[key] = s.split(label, 1)[1].strip()
        # Last run 行同时带状态: '2026-09-02T08:30...  error: msg'
        if "Last run:" in s:
            rest = s.split("Last run:", 1)[1].strip()
            parts = rest.split("  ", 1)
            cur["last_run_at"] = parts[0]
            if len(parts) > 1:
                cur["last_status"] = parts[1].split(":", 1)[0].strip()
    if cur:
        jobs.append(cur)
    return jobs


def main() -> int:
    issues: list[str] = []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"# 📋 面基 Cron 健康检查  |  {now}\n")

    # ── 1. Cron 任务清单 ──────────────────────────────
    jobs = _load_cron_jobs()
    if not jobs:
        issues.append("无法读取 cron 任务清单 (cron_jobs.json 不存在且 hermes cron list 失败)")
        print("**⚠️ Cron 状态不可读**")
    else:
        print("## 1. Cron 任务清单")
        print("| Job | 名称 | 调度 | 上次运行 | 状态 |")
        print("|---|---|---|---|---|")
        today = datetime.now().date().isoformat()
        for j in sorted(jobs, key=lambda x: x.get("schedule", "")):
            jid = j.get("job_id", "?")[:8]
            name = (j.get("name") or "")[:26]
            sched = j.get("schedule", "?")
            last = (j.get("last_run_at") or "never")[:16].replace("T", " ")
            status = j.get("last_status") or "never"
            icon = {"ok": "✅", "error": "❌"}.get(status, "⚪")
            # 今日失败标红
            if status == "error" and last.startswith(today):
                issues.append(f"cron 今日失败: {name} ({jid})")
            print(f"| {jid} | {name} | {sched} | {last} | {icon} {status} |")
        print()

    # ── 2. 数据文件新鲜度 ──────────────────────────────
    print("## 2. 数据文件新鲜度")
    print("| 文件 | 距今 | 上限 | 状态 |")
    print("|---|---|---|---|")
    for rel, max_h in DATA_FILES.items():
        p = PROJECT / rel
        if rel.endswith("/"):
            p = _latest_snapshot() or p
            rel = "scan_snapshots/(最新)"
        age = _age_hours(p)
        if age is None:
            print(f"| {rel} | 不存在 | {max_h}h | ❌ 缺失 |")
            issues.append(f"数据文件缺失: {rel}")
        else:
            ok = age <= max_h
            if not ok:
                issues.append(f"数据陈旧: {rel} ({age:.0f}h > {max_h}h)")
            print(f"| {rel} | {age:.1f}h | {max_h}h | {'✅' if ok else '❌ 陈旧'} |")
    print()

    # ── 3. 回测快照累积 ────────────────────────────────
    if SNAPSHOT_DIR.exists():
        count = len(list(SNAPSHOT_DIR.glob("scan_snapshot_*.json")))
        latest = _latest_snapshot()
        latest_date = latest.stem.replace("scan_snapshot_", "") if latest else "无"
        pct = min(100, count / 60 * 100)
        flag = "✅" if count >= 1 else "❌"
        if latest and (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).days > 2:
            issues.append(f"快照 >2 天未更新 (最新 {latest_date})")
        print(f"## 3. 回测快照累积: {count}/60 天 ({pct:.0f}%) {flag}")
        print(f"最新快照: {latest_date}")
        if count < 60:
            print(f"> ⏳ 目标 60 天, 当前 {count} 天 (每日 +1, 还需 {60-count} 天)")
        print()

    # ── 4. 汇总 ────────────────────────────────────────
    if issues:
        print("## ⚠️ 告警")
        for i in issues:
            print(f"- {i}")
        print("\n**结论: 有告警, 需人工确认 (见 docs/CRON_JOBS.md §4 故障速查)**")
        return 1
    print("## ✅ 全部健康")
    print("\n**结论: 数据管线正常运行**")
    return 0


if __name__ == "__main__":
    import argparse
    _ap = argparse.ArgumentParser(description="面基投资系统 Cron 健康检查")
    _ap.add_argument("--notify", action="store_true",
                     help="有告警时发送飞书群通知 (无告警则静默)")
    _args = _ap.parse_args()
    _rc = main()
    if _args.notify and _rc != 0:
        # 告警 → 飞书群推送 (复用 FEISHU_APP_ID 应用消息, 与日报同通道)
        try:
            from dotenv import load_dotenv
            _env = os.environ.get("HERMES_ENV", os.path.join(str(Path.home()), ".hermes", ".env"))
            if os.path.exists(_env):
                load_dotenv(_env)

            import urllib.request
            _app_id = os.environ.get("FEISHU_APP_ID", "")
            _app_secret = os.environ.get("FEISHU_APP_SECRET", "")
            # 1. 换 tenant_access_token
            _req = urllib.request.Request(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                data=json.dumps({"app_id": _app_id, "app_secret": _app_secret}).encode(),
                headers={"Content-Type": "application/json"})
            _tok = json.loads(urllib.request.urlopen(_req, timeout=15).read())
            _token = _tok.get("tenant_access_token")
            if _token:
                # 2. 发消息到知行合一群 (oc_4c9d6445fab7f3a2ada0c410f3aa7043)
                _body = {
                    "receive_id": "oc_4c9d6445fab7f3a2ada0c410f3aa7043",
                    "msg_type": "text",
                    "content": json.dumps({"text": "🔔 面基系统 Cron 健康告警\n" + os.popen(
                        f"{sys.executable} {os.path.abspath(__file__)} 2>/dev/null | tail -25").read()[:1800]}),
                }
                _req2 = urllib.request.Request(
                    "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                    data=json.dumps(_body).encode(),
                    headers={"Content-Type": "application/json",
                             "Authorization": f"Bearer {_token}"})
                urllib.request.urlopen(_req2, timeout=15).read()
        except Exception:
            pass  # 通知失败不影响退出码 (健康检查本身的结果已打印)
    sys.exit(_rc)