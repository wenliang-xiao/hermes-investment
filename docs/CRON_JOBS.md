# 面基投资系统 · Cron 任务规范文档

> **本文档是 Hermes cron 任务的单一事实来源 (single source of truth)。**
> 所有 cron 任务的配置、命令、恢复方法都以本文档为准。
> 修改 cron 任务后必须同步更新本文档并 push 到 GitHub。

**Last verified:** 2026-08-13 · **查看实际运行状态:** 用 `hermes` cron list 或 `/cron list` 命令。

---

## 0. 管理原则（铁律）

1. **脚本是执行本体，cron prompt 只是"指路牌"** —— 所有复杂逻辑固化到 `scripts/*.py`，
   避免 LLM 每次运行重新推导命令、编造不存在的 flag。
2. **统一用 venv python 绝对路径** —— `/home/admin/.hermes/hermes-agent/venv/bin/python`。
   crontab/Hermes cron 环境的 PATH 不含 venv，裸 `python3` 会解析到 `/usr/bin/python3`
   (Py3.6.8，无 numpy/pandas/baostock/yfinance)，必然失败。
3. **每个任务必须有确定性的执行入口** —— 不依赖 agent 临场发挥。
4. **改完必须同步文档 + push GitHub** —— 本文档就是目录。
5. **故障要及时发现** —— 见 §5 主动监测。

---

## 1. 任务总览

共 **5 个** 常驻 cron 任务，全部在 `default` Hermes profile 下：

| Job ID | 名称 | Schedule | 频率 | 推送目标 | 工作目录 |
|---|---|---|---|---|---|
| `ec73ef6de848` | 面基日报·盘前简报 | `30 8 * * 1-5` | 工作日 08:30 | 飞书「知行合一」群 | investment_system |
| `233e3070a0b3` | 面基日报·盘后 | `0 18 * * 1-5` | 工作日 18:00 | 飞书「知行合一」群 | investment_system |
| `aa3d2e888cc7` | 面基周报 | `0 18 * * 0` | 周日 18:00 | 飞书「知行合一」群 | investment_system |
| `1f704ff45437` | faceji-factor-daily-scan | `30 9 * * 1-5` | 工作日 09:30 | origin（本对话） | investment_system |
| `64b330ed994e` | factor-snapshot-watchdog | `0 17 * * 1-5` | 工作日 17:00 | origin（本对话） | investment_system |

> **推送目标说明:**
> - 日报×2 + 周报 → 飞书群 `oc_4c9d6445fab7f3a2ada0c410f3aa7043`（知行合一）
> - faceji-factor-daily-scan → `origin`（创建时所在的对话/频道）
> - factor-snapshot-watchdog → `origin`（no_agent 看门狗，健康时静默，快照缺失时告警）

---

## 2. 任务详解

### 2.1 面基日报·盘前简报 (`ec73ef6de848`)

- **Schedule:** 工作日 08:30（开盘前 5 分钟读完）
- **Skill:** `devops/v10-trading-system-maintenance`
- **执行:** 运行面基三源融合日报 v10 盘前版并推送
- **关键:** 8 分钟同步仪表盘（DailyReport: 08:30 → dashboard）

### 2.2 面基日报·盘后 (`233e3070a0b3`)

- **Schedule:** 工作日 18:00
- **Skill:** `devops/v10-trading-system-maintenance`
- **执行:** 日报 v10 盘后版（全量扫描 + 模拟盘执行 + 飞书发布）

### 2.3 面基周报 (`aa3d2e888cc7`)

- **Schedule:** 周日 18:00
- **执行:** `cd ~/.hermes/investment_system && python3 scripts/run_weekly.py`

### 2.4 faceji-factor-daily-scan (`1f704ff45437`) ⭐ 回测数据累积

**用途:** 每天生成 `data/scan_snapshots/scan_snapshot_YYYY-MM-DD.json`，供
`strategy_comparison` 回测使用（**需要 60+ 天真实数据**）。

- **Schedule:** 工作日 09:30
- **模式:** `no_agent=True`（**确定性脚本，无 LLM 依赖**）——2026-08-13 从 agent-mode 改，根治 LLM 网关 502 致命化问题
- **执行:** `~/.hermes/scripts/factor_daily_scan.sh` → `scripts/daily_factor_scan.py`（单入口编排器）
- **完整命令:**
  ```bash
  cd /home/admin/.hermes/investment_system && \
    /home/admin/.hermes/hermes-agent/venv/bin/python scripts/daily_factor_scan.py
  ```

**为何改为 no_agent（2026-08-13 关键修复）:**
- 原 agent-mode 的 cron 依赖 LLM 网关 `https://api.spanagent.xyz`（Cloudflare 前端）。
  该网关频繁瞬时 502/timeout，一旦在 agent 首次响应阶段失败（`msgs=2 tokens=~6k`），
  **整个因子扫描一行都没执行**就整批失败。数据源自身（蜻蜓/baostock/yfinance）的 502 都
  已被吞掉或自动重试，**两者混淆导致误判成数据源故障**。
- no_agent 直接用脚本，扫描成功与否完全取决于数据源健康度，与 LLM 网关彻底解耦。

**`daily_factor_scan.py` 做什么（按序）:**
1. 清理跨天残留的批文件 `data/factor_daily_batch{N}.json`（昨天的 → 删掉）
2. A 股分批扫描：4 批 × 20 只（每批 ~15min），**同一天重跑会跳过已完成批次（续扫）**
3. 港美股扫描：批5（WATCHLIST 里 `.HK` 标的）
4. `merge_batches_today.py` → 合并票池 → 生成当日 scan snapshot
5. 记录日期到 `data/scan_snapshot_days.log`

**运行时长:** 全量 ~50-60 分钟。**必须 background 运行 + poll**，不要前台短超时跑。
**可续扫:** 超时/中断后重跑同一命令即从已完成的批次继续。

### 2.5 factor-snapshot-watchdog (`64b330ed994e`) 🐕 主动故障检测

**用途:** 主动监测因子扫描快照是否连续缺失，**及时发现问题**（用户核心诉求）。

- **Schedule:** 工作日 17:00（晚于 09:30 因子扫描，确认当天是否产出快照）
- **模式:** `no_agent=True` 看门狗（watchdog pattern）——健康时无 stdout（静默不打扰），
  快照缺失时输出告警并投递给用户。
- **执行脚本:** `~/.hermes/scripts/factor_snapshot_watchdog.sh` → `scripts/cron_watchdog.py`
- **检查逻辑:** 最近 5 个交易日（不含今天）是否有 `scan_snapshot_YYYY-MM-DD.json`，
  列出缺失日期 + 最后好快照 + 建议动作。

**为什么用 no_agent:** 无 LLM 参与，确定性执行；看门狗模式天然只在该报错时报错，
不会产生噪音消息。

---

## 3. 数据管线健康度

**当前回测快照累积状态:** 见 `data/scan_snapshots/` 目录文件数。
目标 = **60 天**（`strategy_comparison` 回测需要的真实数据量）。
检查命令:
```bash
ls /home/admin/.hermes/investment_system/data/scan_snapshots/ | wc -l
```

---

## 4. 故障排查速查表

| 症状 | 根因 | 处置 |
|---|---|---|
| cron 报 `Script timed out after 120s` | **Hermes cron 调度器对 no_agent 脚本的默认硬超时只有 120s**（`scheduler.py` `_DEFAULT_SCRIPT_TIMEOUT`），而 `daily_factor_scan.py` 内部预算是 1200s；120s 到点脚本被整杀，batch3/4/5 + merge + 快照全没做 | 已在 `~/.hermes/config.yaml` 设 `cron.script_timeout_seconds: 1800`（配置文件按 mtime 缓存，改完即生效，无需重启）。再犯时先 `grep script_timeout_seconds ~/.hermes/config.yaml` 确认还在 |
| cron 报 `ModuleNotFoundError: numpy` | cron 用了裸 `python3` = Py3.6.8 | 改用 venv 绝对路径 |
| cron 报 `RuntimeError: HTTP 502 (Cloudflare)` 且 `tokens=~6k` | **LLM 网关 `api.spanagent.xyz` 瞬时 502**（agent 首次响应即死，扫描未执行） | **不是数据源故障。** 已改为 no_agent 脚本免疫；老日志出现则重跑 `daily_factor_scan.py` |
| 扫描卡住无评分输出 8min+ | baostock/CSC 挂起 | `rm -f data/scanner_progress.json` + 重跑；连败2次→报陈旧数据 |
| `faceji-factor-daily-scan` 部分完成" | 时间预算/批失败 | 重跑同一命令续扫；快照用最大日期 |
| 日报推送空消息"今日无新信号" | push 脚本副本滞后 | 参考 `v10-trading-system-maintenance` skill §推送到飞书群 |

**统一恢复口诀:** 因子扫描失败 → 重跑 `daily_factor_scan.py`（可续扫）→ 仍失败则报告
最后一个好快照的日期，不要假装成功。

---

## 5. 主动故障检测

Hermes cron 会在任务失败时给用户投递错误通知（见本仓库 `docs/HERMES_SYSTEM_MANUAL.md`）。

**人工巡检节奏（建议）:**
- **每日:** 看一眼 `faceji-factor-daily-scan` 是否投递了 `✅`（工作日 09:30 后）
- **每周:** 检查 `data/scan_snapshots/` 数量是否在递增（周环比应 +5 天）

**半自动巡检（推荐，可 cron 化）:**
```bash
# 检查最近5天是否有快照缺失
for d in $(seq 0 5); do
  date=$(date -d "-$d day" +%F)
  [ -f /home/admin/.hermes/investment_system/data/scan_snapshots/scan_snapshot_$date.json ] \
    || echo "缺失快照: $date"
done
```

---

## 6. 变更记录

| 日期 | 变更 | 关联 |
|---|---|---|
| 2026-08-24 | **P0 修复**: Hermes cron 默认 120s 硬超时会杀掉仍在跑的 no_agent 脚本, 导致因子扫描连续 8 个交易日缺快照。已在 `~/.hermes/config.yaml` 设 `cron.script_timeout_seconds: 1800` | cron 规范化 |
| 2026-08-13 | 新增 `scripts/cron_watchdog.py` 看门狗 + cron job `factor-snapshot-watchdog`（主动故障检测） | cron 规范化 |
| 2026-08-13 | 新增 `scripts/daily_factor_scan.py` 单入口编排器，修复 `faceji-factor-daily-scan` 的陈旧/错误 prompt | 502 故障 + cron 规范化 |
| 2026-08-13 | `data/sources/yahoo_source.py` 增加 502/429/5xx 指数退避自动重试 | 502 故障修复 |
| 2026-08-13 | 本文档创建（替代并废弃旧 `HERMES_CRON_CONFIG.md`） | cron 规范化 |

---

## 7. 相关文档

- 运维手册: `docs/HERMES_SYSTEM_MANUAL.md`
- 因子引擎维护: skill `devops/v10-trading-system-maintenance`
- 跨 cron 分批续扫: skill `devops/cross-cron-batch-scan`
- 因子引擎 v4: skill `mlops/factor-engine-v4`
- Cron 管理 playbook: skill `devops/cron-jobs-ops`
