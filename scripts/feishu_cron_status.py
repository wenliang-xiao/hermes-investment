#!/usr/bin/env python3
"""
scripts/feishu_cron_status.py — 把 9 个 Hermes cron 运行状态推成飞书富文本卡片
================================================================================
用法:
    /home/admin/.hermes/hermes-agent/venv/bin/python scripts/feishu_cron_status.py
    # → 把 cron 健康状态卡片推到「知行合一」群 (美观富文本 post, 非纯文本)

作用: 用户想直观看到 cron 全貌(谁在跑/谁失败了/数据新不新), 而非每次告警才打扰。
本脚本把 cron_health_check 的结论整理成好看的分节卡片:
  ┌──────────────────────────────┐
  │ 🔔 面基系统运行状态 09-04     │
  │ ─────────────────────────    │
  │ ✅ 因子扫描 07:00 正常        │
  │ ⚠️ 周报 08-30 失败            │
  │ ...                          │
  │ 📊 数据新鲜度 全绿           │
  └──────────────────────────────┘
"""
import json, os, sys, subprocess, urllib.request
from datetime import datetime
from pathlib import Path

PROJECT = Path("/home/admin/.hermes/investment_system")
CRON_STATE = Path.home() / ".hermes" / "cron" / "cron_jobs.json"
GROUP_ID = "oc_4c9d6445fab7f3a2ada0c410f3aa7043"  # 知行合一群

# 任务可读名 + 期望状态 (用于判断正常/异常)
JOB_LABEL = {
    "1f704ff4": "因子日扫",
    "ec73ef6d": "日报·盘前",
    "233e3070": "日报·盘后",
    "aa3d2e88": "周报",
    "64b330ed": "快照看门狗",
    "cbda6228": "事件影子",
    "8699718a": "龙虎榜",
    "5ee6817c": "新闻采集",
    "bb363e12": "ETF采集",
    "02e08bfc": "健康巡检",
}


def get_tenant_token():
    """从 feishu 凭证文件读取 app_id/secret 换 token (可靠路径, 非截断的 .env)"""
    try:
        creds_path = Path("/home/admin/.feishu-user-plugin/credentials.json")
        if creds_path.exists():
            creds = json.loads(open(creds_path).read())
            app_id = creds["profiles"]["default"]["LARK_APP_ID"]
            secret = creds["profiles"]["default"]["LARK_APP_SECRET"]
        else:
            from dotenv import load_dotenv
            load_dotenv(os.path.join(str(Path.home()), ".hermes", ".env"))
            app_id = os.environ.get("FEISHU_APP_ID", "")
            secret = os.environ.get("FEISHU_APP_SECRET", "")
        req = urllib.request.Request(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json.dumps({"app_id": app_id, "app_secret": secret}).encode(),
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
        return resp.get("tenant_access_token", "")
    except Exception as e:
        print(f"[err] token: {e}")
        return ""


def load_cron_jobs():
    """复用 cron_health_check 的状态读取: 解析 hermes cron list"""
    try:
        out = subprocess.run(["hermes", "cron", "list"], capture_output=True,
                             text=True, timeout=30).stdout
    except Exception:
        return []
    jobs = []
    cur = None
    for line in out.splitlines():
        s = line.strip()
        if s and s[0].isalnum() and len(s.split()[0]) == 12 and "[" in s:
            if cur:
                jobs.append(cur)
            cur = {"job_id": s.split()[0], "name": "", "schedule": "",
                   "last_run_at": "", "last_status": "unknown"}
            continue
        if cur is None:
            continue
        for key, label in (("name", "Name:"), ("schedule", "Schedule:")):
            if label in s:
                cur[key] = s.split(label, 1)[1].strip()
        if "Last run:" in s:
            rest = s.split("Last run:", 1)[1].strip()
            parts = rest.split("  ", 1)
            cur["last_run_at"] = parts[0]
            if len(parts) > 1:
                cur["last_status"] = parts[1].split(":", 1)[0].strip()
    if cur:
        jobs.append(cur)
    return jobs


def build_post_content(jobs):
    """构建飞书富文本 post 消息 (分节 + emoji 状态灯 + 粗体)"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    # 时间戳
    rows = [[{"tag": "text", "text": f"🔔 面基系统运行状态  |  {now}", "style": ["bold"]}]]

    # 1. Cron 任务状态区
    rows.append([{"tag": "text", "text": ""}])
    rows.append([{"tag": "text", "text": "📋 Cron 任务", "style": ["bold"]}])
    healthy = 0
    total = len(jobs)
    for j in sorted(jobs, key=lambda x: x.get("job_id", "")):
        jid = j.get("job_id", "")[:8]
        name = JOB_LABEL.get(jid, j.get("name", "?")[:10])
        status = j.get("last_status", "unknown")
        sched = j.get("schedule", "")
        # 状态灯
        if status in ("ok", "silent"):
            icon = "✅"
            healthy += 1
        elif status in ("error", "failed", "timeout"):
            icon = "❌"
        elif status == "running":
            icon = "🔄"
        else:
            icon = "❔"
        rows.append([{"tag": "text",
                      "text": f"{icon} {name}  [{sched}]  {status}",
                      "style": []}])

    # 2. 数据新鲜度摘要 (简版)
    rows.append([{"tag": "text", "text": ""}])
    rows.append([{"tag": "text", "text": "📊 汇总", "style": ["bold"]}])
    rows.append([{"tag": "text",
                  "text": f"{healthy}/{total} 个任务正常 · 详见 docs/CRON_JOBS.md",
                  "style": []}])

    return {"zh_cn": {"title": "🔔 面基系统运行状态", "content": rows}}


def send_post(token, content):
    payload = json.dumps({
        "receive_id": GROUP_ID,
        "msg_type": "post",
        "content": json.dumps(content, ensure_ascii=False),
    }, ensure_ascii=False)
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        payload.encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method="POST")
    resp = json.loads(urllib.request.urlopen(req, timeout=15).read())
    return resp.get("code") == 0, resp.get("msg", "")


if __name__ == "__main__":
    jobs = load_cron_jobs()
    if not jobs:
        print("⚠️ 未读到 cron 任务, 卡片未发送 (hermes cron list 无输出?)")
        sys.exit(1)
    content = build_post_content(jobs)
    token = get_tenant_token()
    if not token:
        print("❌ 无法获取飞书 token")
        sys.exit(1)
    ok, msg = send_post(token, content)
    print(f"{'✅' if ok else '❌'} 飞书 cron 状态卡片已{'发送' if ok else '失败'}: {msg}")
    sys.exit(0 if ok else 1)
