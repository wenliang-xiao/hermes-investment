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

共 **9 个** 常驻 cron 任务，全部在 `default` Hermes profile 下：

| Job ID | 名称 | Schedule | 频率 | 推送目标 | 工作目录 |
|---|---|---|---|---|---|
| `ec73ef6de848` | 面基日报·盘前简报 (no_agent) | `30 8 * * 1-5` | 工作日 08:30 | 飞书「知行合一」群 | investment_system |
| `233e3070a0b3` | 面基日报·盘后 (no_agent) | `0 18 * * 1-5` | 工作日 18:00 | 飞书「知行合一」群 | investment_system |
| `aa3d2e888cc7` | 面基周报 (no_agent) | `0 18 * * 0` | 周日 18:00 | 飞书「知行合一」群 | investment_system |
| `1f704ff45437` | faceji-factor-daily-scan | `30 9 * * 1-5` | 工作日 09:30 | origin（本对话） | investment_system |
| `64b330ed994e` | factor-snapshot-watchdog | `0 17 * * 1-5` | 工作日 17:00 | origin（本对话） | investment_system |
| `cbda6228d443` | event-risk-shadow | `0 8 * * 1-5` | 工作日 08:00 | 无（静默写文件） | investment_system |
| `8699718a1e8c` | collect-dragon-tiger | `20 17 * * 1-5` | 工作日 17:20 | origin（成功静默） | investment_system |
| `5ee6817c13a3` | collect-news | `15 */2 * * 1-5` | 工作日每2h 15分 | origin（成功静默） | investment_system |
| `bb363e122d0d` | collect-etf | `0 20 * * 1-5` | 工作日 20:00 | origin（成功静默） | investment_system |

> **推送目标说明:**
> - 日报×2 + 周报 → 飞书群 `oc_4c9d6445fab7f3a2ada0c410f3aa7043`（知行合一）
> - faceji-factor-daily-scan → `origin`（创建时所在的对话/频道）
> - factor-snapshot-watchdog → `origin`（no_agent 看门狗，健康时静默，快照缺失时告警）
> - **采集三件套（龙虎榜/新闻/ETF）→ `origin`，watchdog 模式：成功无 stdout 静默，失败输出告警**

---

## 2. 任务详解

### 2.1 面基日报·盘前简报 (`ec73ef6de848`)

- **Schedule:** 工作日 08:30（开盘前 5 分钟读完）
- **模式:** `no_agent=True`（确定性脚本，无 LLM 依赖）——**2026-09-02 从 agent-mode 改**
- **执行:** `~/.hermes/scripts/report_daily.sh` → `scripts/run_daily.py`
- **关键:** 8 分钟同步仪表盘（DailyReport: 08:30 → dashboard）；脚本自建飞书文档并打印 `✅`+`📄` 两行，stdout 原样投递到飞书群
- **为何改 no_agent:** agent-mode 的 cron 依赖 LLM 网关 `api.spanagent.xyz`，2026-08-31 起网关对 deepseek-v4-flash 持续 `503 No available channel` → 重试 → `429 限流`，**连续 3 天日报整个没跑**（`msgs=2 tokens=~23k`，脚本一行没执行）。脚本本身是确定性 Python，无任何 LLM 调用，改 no_agent 后与网关彻底解耦。

### 2.2 面基日报·盘后 (`233e3070a0b3`)

- **Schedule:** 工作日 18:00
- **模式:** `no_agent=True`（确定性脚本，无 LLM 依赖）——**2026-09-02 从 agent-mode 改**
- **执行:** `~/.hermes/scripts/report_daily.sh` → `scripts/run_daily.py`（脚本按当前时间自动区分盘前/盘后 session）
- **日报 v10 盘后版:** 全量扫描 + 模拟盘执行 + 飞书发布

### 2.3 面基周报 (`aa3d2e888cc7`)

- **Schedule:** 周日 18:00
- **模式:** `no_agent=True`（确定性脚本）——**2026-09-02 从 agent-mode 改**
- **执行:** `~/.hermes/scripts/report_weekly.sh` → `scripts/run_weekly.py`
- **完整命令:**
  ```bash
  cd /home/admin/.hermes/investment_system && \
    /home/admin/.hermes/hermes-agent/venv/bin/python scripts/run_weekly.py
  ```

### 2.4 faceji-factor-daily-scan (`1f704ff45437`) ⭐ 回测数据累积

**用途:** 每天生成 `data/scan_snapshots/scan_snapshot_YYYY-MM-DD.json`，供
`strategy_comparison` 回测使用（**需要 60+ 天真实数据**）。

- **Schedule:** 工作日 09:30
- **模式:** `no_agent=True`（**确定性脚本，无 LLM 依赖**）——2026-08-13 从 agent-mode 改，根治 LLM 网关 502 致命化问题
- **投递策略 (2026-09-02):** watchdog 模式——成功静默（不再每天发 9KB 摘要），部分完成/失败才输出告警；快照健康由 17:00 watchdog 兜底
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

### 2.6 event-risk-shadow (`cbda6228d443`) 🛡️ 事件风险影子运行

**用途:** 每日生成 `data/shadow_event_history.json`（事件避险脉冲 + 建议 + 持仓快照），
供 `run_daily` / `trading_engine` 的事件拦截使用 + 累积影子证据（判断何时上实盘）。

- **Schedule:** 工作日 08:00（早于盘前日报 08:30，保证日报能读到当天影子记录）
- **模式:** `no_agent=True`（确定性脚本，无 LLM 依赖）
- **投递策略 (2026-09-02):** watchdog 模式——仅 `level=high`（如 48h 内财报/降仓建议）才输出提醒给用户；低/中风险静默（不再每天发 JSON 全文）
- **执行:** `~/.hermes/scripts/event_shadow.sh` → `scripts/run_event_shadow.py`
- **完整命令:**
  ```bash
  cd /home/admin/.hermes/investment_system && \
    /home/admin/.hermes/hermes-agent/venv/bin/python scripts/run_event_shadow.py
  ```

**为何必须接 cron（2026-08-27 补齐）:**
- `run_daily` 的 dual_closed 叠加事件避险、`trading_engine` 的 BUY 拦截都依赖
  `shadow_event_history.json`（读最新一条，日期校验非当天返回 None）。
- 若影子脚本不跑，该文件不存在 → `event_blocks_buy` 返回 False → 事件拦截静默失效。
- 详见 `docs/plans/event-risk-switch-pre-launch-checklist.md`。

### 2.7 collect-dragon-tiger (`8699718a1e8c`) 🐉 龙虎榜每日采集

**用途:** 每日采集最新龙虎榜数据（上榜/净买入/席位）到 `data/dragon_tiger.json`，供证据链/日报使用。

- **Schedule:** 工作日 17:20（收盘后）
- **模式:** `no_agent=True`（watchdog 模式——成功无 stdout 静默，失败输出告警）
- **执行:** `~/.hermes/scripts/collect_dragon_tiger.sh` → `scripts/run_dragon_tiger.py --no-seats`
- **为何新建（2026-09-02）:** 该脚本从无 cron 调度，只能手动跑。数据文件上次更新 2026-08-12（20 天陈旧），评审暴露"龙虎榜 496h expired"。建成 cron 后每天自动刷新。

### 2.8 collect-news (`5ee6817c13a3`) 📰 新闻管线每日采集

**用途:** 每日多次刷新新闻缓存 `data/news_cache.json`（快讯/电报，quick 模式 2-5s），供日报新闻引擎使用。

- **Schedule:** 工作日每 2 小时 x:15（08:15 起）
- **模式:** `no_agent=True`（watchdog 模式）
- **执行:** `~/.hermes/scripts/collect_news.sh` → `scripts/run_news_pipeline.py --mode quick`
- **为何新建（2026-09-02）:** 原先无 cron 调度，缓存上次更新 2026-08-31（39h 陈旧），评审暴露"新闻缓存 39h expired"。每 2h 刷新后日报盘前 08:30 一定能读到当日新闻。

### 2.9 collect-etf (`bb363e122d0d`) 📦 ETF动态发现每日采集

**用途:** 每日扫描全量 A股 ETF（多因子评分）输出动态 ETF 池到 `data/etf_discovery.json`。

- **Schedule:** 工作日 20:00（夜间，全量扫描耗时长）
- **模式:** `no_agent=True`（watchdog 模式）
- **执行:** `~/.hermes/scripts/collect_etf.sh` → `scripts/run_etf_discovery.py --top-n 10 --per-category 2`
- **为何新建（2026-09-02）:** 原先无 cron 调度，文件上次更新 2026-07-08（55 天陈旧，评审暴露"ETF发现 1334h expired"）。注意全量扫描较慢（akshare `fund_etf_spot_em` 37s + 逐只评分），如单次超时由下次 cron 再跑，mtime 校验保证不虚报。

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
| cron 报 `Script timed out after 120s` | **Hermes cron 调度器对 no_agent 脚本的默认硬超时只有 120s**（`scheduler.py` `_DEFAULT_SCRIPT_TIMEOUT`），而 `daily_factor_scan.py` 内部预算是 1200s；120s 到点脚本被整杀，batch3/4/5 + merge + 快照全没做 | 已在 `~/.hermes/config.yaml` 设 `cron.script_timeout_seconds`（配置文件按 mtime 缓存，改完即生效，无需重启）。再犯时先 `grep script_timeout_seconds ~/.hermes/config.yaml` 确认还在 |
| cron 报 `Script timed out after 1800s`（因子日扫 batch1 后有、batch2+ 无） | **1800s(30min) 仍不够全量扫描**（50-60min），09-02 超时被杀只剩 batch1 | **2026-09-02 已提额 `5400s`(90min)** 覆盖全量+余量；确认: `grep script_timeout_seconds ~/.hermes/config.yaml` 应为 5400 |
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
| 2026-09-02 | **因子日扫/event-shadow 改 watchdog 静默**（成功不发摘要/JSON，仅失败或高危提醒）；**script_timeout 1800→5400s**（全量扫描 50-60min 需 90min 预算）；**collect-news 12:15 首跑静默验证通过** | 日报/自动消息降噪 + 因子日扫超时修复 |
| 2026-09-02 | **日报×2+周报 从 agent-mode 改 no_agent**（`report_daily.sh`/`report_weekly.sh`），脱离 spanagent LLM 网关（503/429 连续 3 天杀任务）；**新建采集三件套 cron**：龙虎榜 17:20、新闻每2h、ETF 20:00（此前均无调度，数据陈旧 20-55 天） | 数据管线可靠性 (2026-09-02 评审) |
| 2026-08-27 | 新增 `scripts/run_event_shadow.py` + cron job `event-risk-shadow`（事件风险影子运行，事件拦截的前置数据源） | 事件风险开关 |
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
