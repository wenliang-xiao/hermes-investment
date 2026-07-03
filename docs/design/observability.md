# 可观测性方案

> **适用版本**: v2026.07.02+
> **仓库地址**: <https://github.com/wenliang-xiao/hermes-investment>（公开仓库）
> **编写日期**: 2026-07-03
> **状态**: 待实施
> **优先级**: 🟢 P2

---

## 一、概述

Hermes Investment（面基三源融合投资系统）已在生产环境（ECS）稳定运行，通过四组 cron 任务驱动日报生成、因子扫描、ETF 组合构建和 Dashboard 数据更新。但在工程化的语境下，系统的可观测性处于**近乎空白**的状态——日志分散、无健康检查、无指标、无告警。

### 1.1 当前状况

| 维度 | 现状 | 问题 |
|------|------|------|
| 日志 | 14 个文件使用 `logging.getLogger(__name__)`，5 个文件在模块顶层调用 `logging.basicConfig()` | 每次 import 覆盖日志配置，多个模块的配置互相打架 |
| 日志 | `run_daily.py` 用自定义 `log()` 函数直接写 `/tmp/report_daily_log.txt` | 无轮转、无结构化、无级别控制，与标准 logging 体系割裂 |
| 日志 | 无 JSON 结构化格式 | 无法被日志采集系统解析和检索 |
| 日志 | 无关联 ID | 从数据获取到日报生成的跨阶段调用无法串联追踪 |
| 健康检查 | Dashboard 无 `/health` 端点 | 负载均衡或外部监控脚本无法判断服务是否存活 |
| 指标 | 零暴露 | 管线耗时、API 延迟、缓存命中率、错误计数等完全不可见 |
| 告警 | 零规则 | 唯一的"通知"是每日飞书报告推送——但如果 cron 静默挂了，不会有任何人知道 |
| 崩溃恢复 | 无 | `portfolio_server.py` 没有 systemd 管理；日报管线无断点续跑能力 |

### 1.2 可观测性成熟度评估

```
Level 0: 混沌      ← 当前状态
  · 无集中式日志收集
  · 无指标暴露
  · 无健康检查
  · 无告警

Level 1: 基础       ← Phase 1 目标
  · 结构化日志，统一配置
  · /health 端点
  · 基本指标暴露（Prometheus endpoint）
  · Cron 死男人开关

Level 2: 生产       ← Phase 2 目标
  · Grafana Dashboard
  · 管线追踪（关联 ID）
  · 飞书告警集成
  · 优雅降级

Level 3: 成熟       ← 远期愿景
  · 分布式追踪（OpenTelemetry）
  · SLO/SLI 监控
  · 预测性告警
  · 自动恢复
```

### 1.3 文档结构

- **第二章（日志方案）**——统一配置中心、结构化格式、关联 ID 传播、关键日志事件
- **第三章（健康检查）**——`/health` 端点设计、组件状态、数据新鲜度
- **第四章（指标框架）**——Prometheus 指标定义、关键指标清单、Grafana Dashboard 方案
- **第五章（告警）**——死男人开关、飞书告警集成、数据陈旧告警、错误率尖峰告警
- **第六章（崩溃恢复与守护）**——`portfolio_server.py` systemd 化、Cron 包装器
- **第七章（工具选型）**——`structlog`、`prometheus_client`、Grafana、Sentry
- **第八章（实施路线图）**——分三个阶段的渐进式落地计划

---

## 二、日志方案

### 2.1 当前问题详细分析

#### 2.1.1 `logging.basicConfig()` 竞态问题

以下 5 个文件在模块顶层（import 时执行）调用了 `logging.basicConfig()`：

| 文件 | 配置 | 副作用 |
|------|------|--------|
| `scripts/run_factor_daily.py:23` | `INFO, "%(asctime)s [%(levelname)s] %(message)s"` | 首个 import 的配置是“赢家” |
| `analysis/auto_deep_research.py:23` | `INFO, 同上格式` | 如果先 import，覆盖因子扫描的配置 |
| `analysis/factor_engine.py:900` | `INFO`（无格式） | 模块顶层代码，`import factor_engine` 即触发 |
| `analysis/portfolio_builder.py:544` | `INFO, "%(message)s"` | 又一种格式，进一步扰乱 |
| `analysis/init_ic_data.py:26` | `INFO, 同第一种格式` | 第五个"赢家"候选人 |

Python 的 `logging.basicConfig()` 只在**第一次调用时**生效，后续调用是空操作。这意味着具体哪个模块的配置最终生效，取决于 import 顺序——这是一个非确定性行为。

#### 2.1.2 `run_daily.py` 的自定义 log 函数

```python
LF = '/tmp/report_daily_log.txt'
with open(LF, 'w') as f: f.write('')

def log(msg):
    with open(LF, 'a') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
```

问题清单：
- **无轮转**：日志文件无限增长（虽然 `'w'` 模式在每次运行时清空，但如果同一天运行两次则覆盖）
- **无级别**：所有消息一视同仁，无法区分 INFO/WARN/ERROR
- **无结构化**：纯文本，无法被 grep/ELK/Loki 高效查询
- **与标准 logging 体系割裂**：管线内其他模块用 `logger.info()`，日报脚本自己写文件——同一个请求的日志散落在两个世界

### 2.2 统一日志架构

#### 2.2.1 配置层：单例 `logging_config.py`

新建文件 `investment_system/logging_config.py`，作为全局唯一的日志配置入口：

```python
"""
Hermes 日志统一配置
所有模块通过 from investment_system.logging_config import get_logger 获取 logger
禁止在任何模块顶层调用 logging.basicConfig()
"""
import logging
import logging.handlers
import os
import sys
from pathlib import Path

_LOG_INITIALIZED = False

def init_logging(
    level: str = "INFO",
    log_dir: str = "/var/log/hermes",
    json_format: bool = True,
    console: bool = True,
) -> None:
    global _LOG_INITIALIZED
    if _LOG_INITIALIZED:
        return

    Path(log_dir).mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 清除已有的 handler（防止 basicConfig 残留）
    root.handlers.clear()

    if json_format:
        try:
            from pythonjsonlogger import jsonlogger
            formatter = jsonlogger.JsonFormatter(
                "%(asctime)s %(name)s %(levelname)s %(message)s",
                timestamp=True,
            )
        except ImportError:
            formatter = logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            )
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

    # 文件 handler：按天轮转，保留 30 天
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=os.path.join(log_dir, "hermes.log"),
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # 控制台 handler
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(console_handler)

    _LOG_INITIALIZED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
```

**设计决策**：

| 决策 | 理由 |
|------|------|
| 全局 `root` logger 配置，而非逐模块 | 避免另一轮 basicConfig 竞态；14 个模块的 `logging.getLogger(__name__)` 自动继承 root 配置 |
| `pythonjsonlogger` 可选依赖 | 有则输出 JSON，无则降级为文本；不硬依赖第三方库 |
| 按天轮转 + 30 天保留 | 平衡磁盘占用（日报管线每天 2 次，因子扫描每天 1 次，日志量不大） |
| 保留控制台输出 | 便于 ECS `docker logs` / `podman logs` 直接查看 |

#### 2.2.2 入口脚本初始化模式

每个 CLI 入口脚本在 `main()` 或模块顶层调用一次 `init_logging()`：

```python
# scripts/run_daily.py（改造后）
from investment_system.logging_config import init_logging, get_logger

init_logging(level="INFO", log_dir="/var/log/hermes")
logger = get_logger(__name__)
```

**迁移 `run_daily.py` 的自定义 `log()` 函数**：将所有 `log("...")` 调用替换为 `logger.info("...")`，删除 `/tmp/report_daily_log.txt` 的手动文件操作。日志会统一进入 `/var/log/hermes/hermes.log`。

#### 2.2.3 禁止 basicConfig

在 CI 或 pre-commit hook 中增加 ruff 规则，禁止模块顶层调用 `logging.basicConfig()`：

```toml
# ruff 配置
[tool.ruff.lint]
select = ["E", "F", "I", "N"]

[tool.ruff.lint.flake8-logging]
# 禁止 basicConfig
banned-modules = {"logging": ["basicConfig"]}
```

### 2.3 结构化日志格式

使用 `python-json-logger`（`JsonFormatter`）时的输出示例：

```json
{
  "asctime": "2026-07-03 08:30:15,234",
  "name": "investment_system.scripts.run_daily",
  "levelname": "INFO",
  "message": "=== 日报 开盘前 START ===",
  "correlation_id": "daily-20260703-0830",
  "pipeline_stage": "init"
}
```

要求每条日志携带的固定字段：

| 字段 | 来源 | 说明 |
|------|------|------|
| `correlation_id` | 入口脚本生成 | 一次完整管线运行的唯一标识 |
| `pipeline_stage` | 各阶段设置 | init / macro / scanner / report / push |
| `name` | `logging` 自动 | 模块名，对应 `__name__` |
| `levelname` | `logging` 自动 | INFO / WARNING / ERROR |

### 2.4 关联 ID（Correlation ID）设计

日报管线的一次运行跨越多个模块：

```
run_daily.py (入口)
  → MacroEngine.refresh()
  → determine_bridgewater_quadrant()
  → FactorScanner.scan_market_batch()
  → FeishuWriter.create_doc() / write()
  → shadow_account 建仓/清仓
```

为所有日志打上同一个 `correlation_id`，需要传播机制。考虑到系统是单进程同步执行（无异步框架），最简单的方案是 **上下文变量（contextvars）**：

```python
# investment_system/logging_config.py 中扩展
import contextvars

_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default=""
)
_pipeline_stage: contextvars.ContextVar[str] = contextvars.ContextVar(
    "pipeline_stage", default=""
)


class CorrelationFilter(logging.Filter):
    def filter(self, record):
        record.correlation_id = _correlation_id.get()
        record.pipeline_stage = _pipeline_stage.get()
        return True


def set_correlation_id(cid: str):
    _correlation_id.set(cid)


def set_pipeline_stage(stage: str):
    _pipeline_stage.set(stage)
```

入口脚本用法：

```python
# run_daily.py
from investment_system.logging_config import set_correlation_id, set_pipeline_stage

cid = f"daily-{time.strftime('%Y%m%d-%H%M')}"
set_correlation_id(cid)

logger.info("管线启动")
set_pipeline_stage("macro")
# ... 宏观引擎运行 ...
set_pipeline_stage("scanner")
# ... 因子扫描 ...
set_pipeline_stage("report")
# ... 日报生成 ...
```

### 2.5 关键日志事件定义

梳理每个管线阶段应当记录的日志事件：

| pipeline_stage | 事件 | 级别 | 内容 |
|----------------|------|------|------|
| `init` | 管线启动 | INFO | correlation_id, session, 启动参数 |
| `macro` | 宏观数据刷新 | INFO | regime, CPI, cpi_momentum, trend_temp |
| `macro` | 双门状态判定 | INFO | macro_gate, trend_gate, dual_closed |
| `scanner` | 扫描开始 | INFO | batch_size, top_n, 股票池规模 |
| `scanner` | 扫描进度 | INFO | 完成批次, 已扫描数量 |
| `scanner` | 扫描完成/异常 | INFO/ERROR | 完成状态, 结果数量, top1 score |
| `shadow` | 建仓 | INFO | symbol, name, price, score, kelly_pct |
| `shadow` | 清仓/止损 | WARNING | symbol, name, price, reason |
| `shadow` | 冷却期跳过 | INFO | symbol, 剩余冷却天数 |
| `report` | 文档创建 | INFO | doc_id, label |
| `report` | 飞书推送完成 | INFO | doc_url |
| `report` | 部分文档删除 | WARNING | doc_id, 中止原因 |
| `*` | 数据源异常 | WARNING | 数据源名称, 异常消息, 是否为致命 |
| `*` | 致命错误 | ERROR | 异常类型, 消息, traceback（截断） |
| `*` | 管线完成 | INFO | 总耗时, 是否成功 |

### 2.6 日志级别规范

| 级别 | 使用场景 | 示例 |
|------|---------|------|
| `DEBUG` | 开发调试细节：API 原始响应、缓存命中/未命中、因子中间值 | `cache MISS for 000300` |
| `INFO` | 管线关键节点：启动、阶段完成、正常操作结果 | `Scanner done: 10 stocks scored` |
| `WARNING` | 非致命异常：数据源超时回退、部分扫描失败、飞书推送重试 | `baostock timeout, fallback to AKShare` |
| `ERROR` | 致命错误：管线中止、文档推送失败且无法重试 | `Document push failed after 3 retries` |

---

## 三、健康检查

### 3.1 `/health` 端点

Dashboard 当前运行在 FastAPI 上（`portfolio_server.py`），但没有任何健康检查端点。外部监控脚本（或 ECS 的 `HEALTHCHECK` 指令）无法判断服务是否存活。

在 `portfolio_server.py` 中增加端点：

```python
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.now().isoformat()}
```

如果需要容器健康检查，可通过 ECS 的 `HEALTHCHECK` 指令（或 K8s `livenessProbe`）定期 `curl` 此端点。

### 3.2 组件状态健康检查

`/health` 可以扩展为深度检查——验证 Dashboard 依赖的数据文件和外部服务是否正常：

```python
@app.get("/health")
def health():
    checks = {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "components": {},
    }

    # 1. 核心数据文件可读性
    data_files = {
        "shadow_account": ROOT / "data" / "shadow_account.json",
        "watchlist": ROOT / "config" / "watchlist_v2.json" if (ROOT / "config" / "watchlist_v2.json").exists() else None,
        "pool_watch": ROOT / "data" / "pool" / "watch.json",
    }
    for name, path in data_files.items():
        if path and path.exists():
            try:
                with open(path) as f:
                    json.load(f)
                checks["components"][name] = "ok"
            except Exception as e:
                checks["components"][name] = f"degraded: {e}"
        else:
            checks["components"][name] = "missing"

    # 2. 内部 API 自检
    try:
        build_summary(load_shadow())
        checks["components"]["portfolio_calc"] = "ok"
    except Exception as e:
        checks["components"]["portfolio_calc"] = f"error: {e}"

    # 综合判定
    has_error = any(
        v != "ok" and not v.startswith("degraded")
        for v in checks["components"].values()
    )
    if has_error:
        checks["status"] = "degraded"

    return checks
```

响应示例：

```json
{
  "status": "ok",
  "timestamp": "2026-07-03T08:30:00",
  "components": {
    "shadow_account": "ok",
    "watchlist": "ok",
    "pool_watch": "ok",
    "portfolio_calc": "ok"
  }
}
```

### 3.3 数据新鲜度检查

金融数据系统的核心健康指标是**数据有多旧**。每个数据源都应有 `last_update` 时间戳。

#### 3.3.1 数据新鲜度端点

```python
@app.get("/health/data-freshness")
def data_freshness():
    now = datetime.now()
    freshness = {}

    checks = [
        ("shadow_account", ROOT / "data" / "shadow_account.json"),
        ("daily_scan", Path("/tmp/hermes_scan_snapshot.json")),
        ("factor_snapshot", ROOT / "data" / "factor_snapshot.json"),
        ("etf_portfolio", ROOT / "data" / "etf_portfolio.json"),
        ("news_cache", ROOT / "data" / "news_cache.json"),
    ]

    for name, path in checks:
        if path.exists():
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            age_hours = (now - mtime).total_seconds() / 3600
            freshness[name] = {
                "last_update": mtime.isoformat(),
                "age_hours": round(age_hours, 1),
                "status": "ok" if age_hours < 24 else "stale",
            }
        else:
            freshness[name] = {"status": "missing"}

    return freshness
```

#### 3.3.2 新鲜度阈值

| 数据 | 预期更新频率 | 警告阈值 | 致命阈值 |
|------|------------|---------|---------|
| `shadow_account` | 每日（cron 日盘/收盘后） | > 24 小时 | > 72 小时 |
| `daily_scan` | 每日 | > 24 小时 | > 48 小时 |
| `factor_snapshot` | 每日 | > 24 小时 | > 48 小时 |
| `etf_portfolio` | 每日 | > 24 小时 | > 72 小时 |
| `news_cache` | 日内（多次） | > 6 小时 | > 12 小时 |

### 3.4 管线运行状态追踪

日报管线（`run_daily.py`）当前运行完成后不留痕迹（除了飞书文档和 `/tmp` 下的临时文件）。需要持久化每次运行状态：

```python
# 在管线结束时写入
import json
from datetime import datetime

RUN_LOG_PATH = Path("/var/log/hermes/pipeline_runs.jsonl")

def record_pipeline_run(correlation_id: str, session: str, success: bool,
                        duration_seconds: float, error: str | None = None):
    entry = {
        "correlation_id": correlation_id,
        "session": session,
        "timestamp": datetime.now().isoformat(),
        "success": success,
        "duration_seconds": round(duration_seconds, 1),
        "error": error,
    }
    RUN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG_PATH, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

配合 `/health/pipeline-history` 端点，外部脚本可以检查最近一次运行状态：

```python
@app.get("/health/pipeline-history")
def pipeline_history(hours: int = 24):
    path = Path("/var/log/hermes/pipeline_runs.jsonl")
    if not path.exists():
        return {"runs": [], "message": "no history"}

    cutoff = datetime.now() - timedelta(hours=hours)
    runs = []
    with open(path) as f:
        for line in f:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["timestamp"])
            if ts >= cutoff:
                runs.append(entry)

    last_success = next(
        (r for r in reversed(runs) if r["success"]), None
    )
    return {
        "total_runs": len(runs),
        "last_run": runs[-1] if runs else None,
        "last_success": last_success,
        "is_healthy": runs[-1]["success"] if runs else None,
    }
```

---

## 四、指标框架

### 4.1 Prometheus 指标暴露

利用 `prometheus_client` 库在 Dashboard 上暴露 `/metrics` 端点，由 Prometheus（或兼容采集器）定期抓取。

```python
# investment_system/metrics.py
from prometheus_client import Counter, Gauge, Histogram, generate_latest
from fastapi import Response

# --- 管线指标 ---
pipeline_runs = Counter(
    "hermes_pipeline_runs_total",
    "管线总运行次数",
    ["pipeline", "status"],  # status: success / failure
)
pipeline_duration = Histogram(
    "hermes_pipeline_duration_seconds",
    "管线耗时",
    ["pipeline"],
    buckets=[30, 60, 120, 300, 600, 900, 1800],
)

# --- API 调用指标 ---
api_calls = Counter(
    "hermes_api_calls_total",
    "外部 API 调用次数",
    ["source", "status"],  # source: baostock/akshare/yfinance/feishu
)
api_latency = Histogram(
    "hermes_api_latency_seconds",
    "外部 API 调用延迟",
    ["source"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30],
)

# --- 数据指标 ---
data_staleness = Gauge(
    "hermes_data_staleness_hours",
    "数据陈旧度（小时）",
    ["source"],
)
cache_hits = Counter(
    "hermes_cache_hits_total",
    "缓存命中/未命中",
    ["source", "result"],  # result: hit / miss
)
data_errors = Counter(
    "hermes_data_errors_total",
    "数据源错误次数",
    ["source", "error_type"],
)

# --- 扫描指标 ---
scanner_stocks_scored = Gauge(
    "hermes_scanner_stocks_scored",
    "本次扫描评分的股票数量",
)
scanner_top_score = Gauge(
    "hermes_scanner_top_score",
    "本次扫描最高分",
)

# --- Dashboard 服务指标 ---
dashboard_requests = Counter(
    "hermes_dashboard_requests_total",
    "Dashboard HTTP 请求总数",
    ["endpoint", "status_code"],
)
dashboard_request_latency = Histogram(
    "hermes_dashboard_request_latency_seconds",
    "Dashboard 请求延迟",
    ["endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1, 2],
)


def get_metrics_response() -> Response:
    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
```

在 `portfolio_server.py` 中注册端点：

```python
from investment_system.metrics import get_metrics_response

@app.get("/metrics")
def metrics():
    return get_metrics_response()
```

### 4.2 关键指标与基线阈值

| 指标 | 类型 | 正常范围 | 告警阈值 | 说明 |
|------|------|---------|---------|------|
| `pipeline_duration` | Histogram | < 300s (5min) | > 600s | 日报管线超时 |
| `pipeline_runs{status="failure"}` | Counter | 0 | > 0（连续 2 次） | 管线失败 |
| `api_latency{source="baostock"}` | Histogram | < 5s | > 30s（P95） | baostock 延迟尖峰是宕机前兆 |
| `api_latency{source="yfinance"}` | Histogram | < 3s | > 10s（P95） | yfinance 限流或网络问题 |
| `data_staleness` (shadow_account) | Gauge | < 24h | > 48h | 超过两天未更新，管线可能挂了 |
| `data_errors` | Counter | 散发性 | 1 小时内 > 10 | 数据源大面积异常 |
| `cache_hits{result="miss"} / total` | 衍生（>50%） | < 20% | > 50% 且持续 | 缓存策略可能失效 |

### 4.3 Grafana Dashboard 模板（可选）

如果环境中已有 Prometheus + Grafana 基础设施，建议创建一个 Hermes 专用 Dashboard，包含以下面板：

```
┌─────────────────────────────────────────────────────────┐
│  Row 1: 管线概览                                          │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌──────────┐ │
│  │ 今日运行   │ │ 最近成功   │ │ 平均耗时   │ │ 成功率    │ │
│  │ 2 次       │ │ 08:30      │ │ 245s      │ │ 98.5%    │ │
│  └───────────┘ └───────────┘ └───────────┘ └──────────┘ │
├─────────────────────────────────────────────────────────┤
│  Row 2: 管线耗时趋势（时间序列折线图）                       │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  ▂▃▅▂▃▄▂▃▅█▃▂▃▄▂▃▅▃▂▃▄▂▃▅▃▂▃▄           (30天)       │ │
│  └─────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  Row 3: 数据源指标                                        │
│  ┌────────────────────┐ ┌────────────────────┐          │
│  │ API 调用延迟 (热图)  │ │ 数据错误率          │          │
│  │ baostock  ██░░     │ │ baostock  12 errors │          │
│  │ akshare   █░░░     │ │ yfinance   3 errors │          │
│  │ yfinance  █░░░     │ │ feishu     0 errors │          │
│  └────────────────────┘ └────────────────────┘          │
├─────────────────────────────────────────────────────────┤
│  Row 4: 数据新鲜度                                        │
│  ┌────────────────────┐ ┌────────────────────┐          │
│  │ 各源新鲜度 (Gauge)   │ │ 缓存命中率          │          │
│  └────────────────────┘ └────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

### 4.4 轻量替代方案：自建 HTML 指标页

如果不具备 Prometheus 基础设施，可以在 Dashboard 上增加一个 `/metrics-dashboard` HTML 页面，从 `/health/data-freshness` 和 `/health/pipeline-history` 拉取数据，用 Chart.js 渲染简单的状态面板。这样零外部依赖，单人即可完成。

---

## 五、告警

### 5.1 死男人开关（Dead Man's Switch）

对于 cron 驱动的工作负载，最核心的告警需求是**知道它还在跑**。死男人开关的原理是：cron 任务每次成功运行时更新一个心跳文件/端点，外部监控定期检查这个心跳——如果超过 N 小时没有更新，触发告警。

#### 方案 A：文件心跳 + ECS 外部监控（推荐，最简单）

日报管线每次运行结束时写入心跳文件：

```python
# run_daily.py 改造后
import time
HEARTBEAT_PATH = Path("/tmp/hermes_heartbeat.txt")

# 管线末尾
HEARTBEAT_PATH.write_text(str(time.time()))
```

ECS 或外部 cron 定期检查：

```bash
#!/bin/bash
# /home/admin/hermes_healthcheck.sh — 每 30 分钟运行一次
HEARTBEAT=$(cat /tmp/hermes_heartbeat.txt 2>/dev/null)
NOW=$(date +%s)
AGE=$(( (NOW - HEARTBEAT) / 3600 ))

if [ -z "$HEARTBEAT" ] || [ $AGE -gt 12 ]; then
  echo "❌ Hermes 日报管线超过 ${AGE} 小时未更新心跳"
  # 触发告警：写标记文件供飞书告警脚本抓取
  echo "dead" > /tmp/hermes_alert_status.txt
else
  echo "✅ Hermes 心跳正常 (${AGE}h ago)"
  rm -f /tmp/hermes_alert_status.txt
fi
```

#### 方案 B：HTTP 心跳（配合 Dashboard）

扩展 `/health/pipeline-history`，让外部 HTTP 监控（如 UptimeRobot、Healthchecks.io）直接轮询：

```
GET /health/pipeline-history?hours=12
→ 检查 is_healthy == true
→ 如 false，触发 HTTP 回调告警
```

### 5.2 飞书告警

当前系统唯一的"通知机制"是 `FeishuWriter` 推送日报文档——但这只在管线成功运行时才触发。需要独立的告警通道。

#### 5.2.1 告警飞书 Bot

复用现有的飞书 Bot 凭据（已通过 `.env` 管理），新增告警能力。关键设计原则：

- **告警走独立的飞书群或单独的消息卡片**，不与日报文档混在一起
- **告警有去重机制**：同一类告警在冷却期内不重复发送

```python
# investment_system/alerting.py
import json
import time
import hashlib
import requests
from pathlib import Path
from dataclasses import dataclass, field

ALERT_COOLDOWN_SECONDS = 1800  # 同类告警 30 分钟内不重复
ALERT_STATE_PATH = Path("/tmp/hermes_alert_state.json")


@dataclass
class AlertManager:
    webhook_url: str
    cooldown: int = ALERT_COOLDOWN_SECONDS

    def send(self, title: str, content: str, level: str = "warning") -> bool:
        """发送飞书告警卡片。同类告警在冷却期内去重。"""
        dedup_key = hashlib.md5(f"{level}:{title}".encode()).hexdigest()

        state = self._load_state()
        last_sent = state.get(dedup_key, 0)
        if time.time() - last_sent < self.cooldown:
            return False  # 冷却中，跳过

        level_colors = {"info": "blue", "warning": "yellow", "critical": "red"}
        color = level_colors.get(level, "yellow")

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": f"⚠️ Hermes Alert"},
                    "template": color,
                },
                "elements": [
                    {"tag": "markdown", "content": f"**{title}**\n\n{content}"},
                    {"tag": "note", "elements": [
                        {"tag": "plain_text", "content": f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}"}
                    ]},
                ],
            },
        }

        try:
            resp = requests.post(self.webhook_url, json=payload, timeout=10)
            if resp.status_code == 200:
                state[dedup_key] = time.time()
                self._save_state(state)
                return True
        except Exception:
            pass
        return False

    def _load_state(self) -> dict:
        if ALERT_STATE_PATH.exists():
            try:
                return json.loads(ALERT_STATE_PATH.read_text())
            except Exception:
                pass
        return {}

    def _save_state(self, state: dict):
        ALERT_STATE_PATH.write_text(json.dumps(state))


# 全局单例
alert = AlertManager(webhook_url=os.getenv("FEISHU_ALERT_WEBHOOK", ""))
```

#### 5.2.2 告警场景与规则

| 场景 | 级别 | 条件 | 飞书消息内容 |
|------|------|------|-------------|
| 管线失败 | `critical` | `run_daily.py` 任意异常导致退出 | "日报管线执行失败\n会话: 开盘前\n错误: baostock.login() timeout after 3 retries\n日志: /var/log/hermes/hermes.log" |
| 管线超时 | `warning` | 总耗时 > 600s | "日报管线超时\n会话: 收盘后\n耗时: 782s\ncorrelation_id: daily-20260703-1800" |
| 扫描不完整 | `warning` | `scan_status != "complete"` 且连续 3 次 | "因子扫描不完整\n当前状态: partial:45/100\n已连续 3 次未完成，可能 baostock 不稳定" |
| 数据陈旧 | `warning` | 任一数据源 `age_hours > 48` | "数据陈旧告警\nshadow_account: 72.5h 未更新\n来源: cron 管线可能挂起" |
| cron 心跳缺失 | `critical` | 心跳文件 > 12h 未更新 | "Dead Man's Switch 触发\n日报管线超过 12 小时无心跳\n最后心跳: 2026-07-02 08:31:15" |
| 数据源错误尖峰 | `warning` | 1h 内 API 错误 > 10 次 | "数据源异常\nbaostock 最近 1h: 15 次超时\n当前状态: 管线可能降级运行" |

### 5.3 告警配置环境变量

飞书告警 webhook URL 与日报推送的 Bot 区分开（可以是同一个 Bot 发到不同群）：

```bash
# .env
FEISHU_APP_ID=xxx              # 日报推送用（已有）
FEISHU_APP_SECRET=xxx           # 日报推送用（已有）
FEISHU_ALERT_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx  # 告警推送用
```

### 5.4 告警路线图总结

```
cron 心跳检查脚本 (每 30 分钟)
    │
    ├── 心跳正常 → 无操作
    ├── 心跳缺失 > 12h → /tmp/hermes_alert_status.txt = "dead"
    │       │
    │       └── 飞书 Bot 告警消息
    │
管线运行状态 → /var/log/hermes/pipeline_runs.jsonl
    │
    ├── 每次运行间隙 → 检查 last_run.success
    │       ├── False → alert.send("管线失败", ...)
    │       └── duration > 10min → alert.send("管线超时", ...)
    │
数据新鲜度 (cron 每小时)
    │
    └── /health/data-freshness → age_hours > threshold
            └── alert.send("数据陈旧", ...)
```

---

## 六、崩溃恢复与守护

### 6.1 `portfolio_server.py` systemd 化

当前 `portfolio_server.py` 是通过命令行手动启动的（`python3 scripts/portfolio_server.py 8686`），如果进程崩溃或 ECS 重启，服务不会自动恢复。

#### 6.1.1 systemd service 文件

```ini
# /etc/systemd/system/hermes-dashboard.service
[Unit]
Description=Hermes Investment Dashboard
After=network.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/.hermes/investment_system
EnvironmentFile=/home/admin/.hermes/.env
ExecStart=/usr/bin/python3 scripts/portfolio_server.py 8686
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

# 安全加固
NoNewPrivileges=yes
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable hermes-dashboard
sudo systemctl start hermes-dashboard
sudo systemctl status hermes-dashboard
```

#### 6.1.2 ECS 容器环境替代方案

如果 ECS 环境中没有 systemd，可以用 supervisor 或直接在容器启动脚本中循环守护：

```bash
#!/bin/bash
# /home/admin/hermes_dashboard_daemon.sh
while true; do
    python3 /home/admin/.hermes/investment_system/scripts/portfolio_server.py 8686
    echo "[$(date)] Dashboard crashed, restarting in 10s..."
    sleep 10
done
```

### 6.2 Cron 包装器

当前 cron 任务直接调用 Python 脚本，无任何失败通知：

```
30 8 * * 1-5 python /home/admin/.hermes/investment_system/scripts/run_daily.py
```

改造为包装 shell 脚本，捕获退出码，记录状态，失败时触发告警：

```bash
#!/bin/bash
# /home/admin/hermes_daily_morning.sh
set -euo pipefail

SCRIPT_DIR="/home/admin/.hermes/investment_system"
LOG_DIR="/var/log/hermes"
HEARTBEAT_FILE="/tmp/hermes_heartbeat.txt"

cd "$SCRIPT_DIR"
mkdir -p "$LOG_DIR"

START_TIME=$(date +%s)

if python scripts/run_daily.py >> "$LOG_DIR/daily_morning.log" 2>&1; then
    DURATION=$(( $(date +%s) - START_TIME ))
    echo "$(date +%s)" > "$HEARTBEAT_FILE"
    echo "[$(date)] ✅ Daily morning completed in ${DURATION}s"
else
    EXIT_CODE=$?
    echo "[$(date)] ❌ Daily morning FAILED with exit code $EXIT_CODE"
    # 写失败标记供后续告警脚本抓取
    echo "FAILED:$EXIT_CODE:$(date +%s)" >> "$LOG_DIR/pipeline_failures.log"
    exit $EXIT_CODE
fi
```

crontab 更新为：

```
30 8 * * 1-5 /home/admin/hermes_daily_morning.sh
0 18 * * 1-5 /home/admin/hermes_daily_evening.sh
```

### 6.3 优雅降级策略

当前管线在任一数据源失败时可能全局崩溃（`run_daily.py:56-132` 顶层 `try/except` 只能兜底，不能选择性降级）。建议为每个数据源增加超时回退：

```python
import signal
from contextlib import contextmanager

@contextmanager
def timeout(seconds: int):
    """为同步代码块增加超时保护"""
    def _handler(signum, frame):
        raise TimeoutError(f"Operation timed out after {seconds}s")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# 使用：数据源支持降级
try:
    with timeout(30):
        macro = macro_engine.refresh()
except TimeoutError:
    logger.warning("宏观引擎刷新超时，使用缓存数据")
    macro = macro_engine.load_cached()  # 需额外实现
```

### 6.4 断点续跑（可选，低优先级）

日报管线当前是全量运行模式——如果扫描 50% 时网络中断，所有进度丢失。由于管线总耗时 < 5 分钟，断点续跑的收益/复杂度比不高。**建议先用超时重试解决短期问题，断点续跑推迟到 Phase 3**。

如果日后管线扩展到更大规模，可以基于 `/tmp/hermes_scan_snapshot.json`（已存在）作为 checkpoint：

```python
# 伪代码
if os.path.exists(SNAP_FILE):
    completed_symbols = load_completed_symbols(SNAP_FILE)
    remaining = all_symbols - completed_symbols
    logger.info(f"Resuming scan: {len(completed_symbols)} done, {len(remaining)} remaining")
else:
    remaining = all_symbols
```

---

## 七、工具选型

### 7.1 推荐工具栈

| 工具 | 用途 | 成熟度 | 依赖 | 适用阶段 |
|------|------|--------|------|---------|
| **structlog** | 结构化日志 | 极高（12k+ stars） | 纯 Python，可选依赖 | Phase 1 |
| **python-json-logger** | JSON 格式输出（structlog 的替代/互补） | 高（1.5k+ stars） | 极轻 | Phase 1 |
| **prometheus_client** | 指标暴露 | 极高（4k+ stars） | 纯 Python | Phase 1 |
| **Grafana** | 指标可视化 | 极高 | Prometheus 数据源 | Phase 2 |
| **Sentry** | 错误追踪（self-hosted 或 SaaS） | 极高 | sentry-sdk | Phase 2（可选） |
| **Healthchecks.io** | 外部 cron 监控（免费层支持 20 个 check） | 高 | HTTP ping | Phase 1（可选替代心跳脚本） |

### 7.2 选型理由

#### structlog vs python-json-logger

`structlog` 更强大但学习成本高。推荐分步走：

- **Phase 1**：用 `python-json-logger` 的 `JsonFormatter` 配合标准 `logging`，零学习成本，立即可用
- **Phase 2**：如果日后需要绑定上下文（如自动注入 correlation_id），迁移到 `structlog`

#### prometheus_client

无替代品——Python 生态中唯一的事实标准 Prometheus 客户端库。`pip install prometheus_client` 一行依赖。

#### Grafana

仅在已有 Prometheus 基础设施的环境下使用。如果没有（单人 ECS 环境），Phase 1 直接用 Dashboard 内置的 HTML 指标页面即可。

#### Sentry

适用于需要精细错误追踪和聚合的场景（如"baostock 超时在最近 7 天的趋势"）。如果已有 Sentry 实例（self-hosted 或 SaaS），接入成本极低：`pip install sentry-sdk` + 3 行初始化代码。

```python
import sentry_sdk
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment="production",
    traces_sample_rate=0.1,
)
```

---

## 八、实施路线图

### Phase 1：基础可观测（1-2 天）

目标：**让系统"看得见"** ——日志可查、服务可检测、cron 挂了能知道。

| 任务 | 说明 | 文件 |
|------|------|------|
| 1.1 创建 `logging_config.py` | 全局日志配置：轮转、JSON 格式、关联 ID 支持 | `investment_system/logging_config.py` |
| 1.2 迁移 `run_daily.py` 日志 | 替换自定义 `log()` 为 `logger.info()`，初始化日志配置 | `scripts/run_daily.py` |
| 1.3 清理模块顶层 `basicConfig` | 移除 5 个文件中的 `logging.basicConfig()` 调用，改为依赖根 logger | `analysis/factor_engine.py` 等 |
| 1.4 添加 `/health` 端点 | 基础存活探测 | `scripts/portfolio_server.py` |
| 1.5 添加管线心跳 | 日报结束时写入 `/tmp/hermes_heartbeat.txt` | `scripts/run_daily.py` |
| 1.6 添加 cron 心跳检查脚本 | 每 30 分钟检查心跳，超 12h 写标记文件 | `scripts/hermes_healthcheck.sh` |
| 1.7 创建 cron 包装脚本 | 捕获退出码、写失败日志、更新心跳 | `scripts/hermes_daily_morning.sh` |

**Phase 1 产出物**：

- 所有模块日志统一配置，按天轮转，保留 30 天
- Dashboard 有 `/health` 端点
- cron 失败能通过心跳检查脚本发现（手动查看标记文件）
- 日志可被 `grep` / `jq` 高效检索（如启用 JSON 格式）

### Phase 2：监控与告警（2-3 天）

目标：**让系统"会说话"** ——指标可视化、异常主动通知。

| 任务 | 说明 | 文件 |
|------|------|------|
| 2.1 创建 `metrics.py` | Prometheus 指标定义与 `/metrics` 端点 | `investment_system/metrics.py` |
| 2.2 埋点关键路径 | 管线耗时、API 延迟、缓存命中率 | 分散在各模块 |
| 2.3 创建 `alerting.py` | 飞书告警管理器，支持去重冷却 | `investment_system/alerting.py` |
| 2.4 集成告警到管线 | 管线失败/超时时触发飞书告警 | `scripts/run_daily.py` |
| 2.5 添加数据新鲜度端点 | `/health/data-freshness` | `scripts/portfolio_server.py` |
| 2.6 添加管线运行历史 | JSONL 记录每次运行状态 | `scripts/run_daily.py` |
| 2.7 配置数据陈旧告警 | 定时检查新鲜度，超阈值飞书告警 | `scripts/hermes_data_freshness_check.sh` |
| 2.8 创建 Dashboard systemd service | `portfolio_server.py` 崩溃自动重启 | `/etc/systemd/system/hermes-dashboard.service` |
| 2.9 （可选）Grafana Dashboard 模板 | 预配置 JSON 模板，可一键导入 | `docs/grafana-dashboard.json` |

**Phase 2 产出物**：

- Prometheus 指标端点（`/metrics`）
- 飞书告警：管线失败、心跳缺失、数据陈旧
- `/health/data-freshness` + `/health/pipeline-history` 端点
- `portfolio_server.py` 有 systemd 守护（崩溃自动重启）

### Phase 3：精细化运营（按需推进）

目标：**让系统"越来越聪明"** ——深入追踪、SLO 定义、预测性告警。

| 任务 | 说明 |
|------|------|
| 3.1 关联 ID 全管线传播 | 从日报入口到底层 API 调用全部打上 correlation_id |
| 3.2 优雅降级实现 | 数据源超时回退缓存、部分扫描失败不阻塞其他模块 |
| 3.3 Sentry 接入 | 错误聚合、趋势追踪 |
| 3.4 SLO 定义 | 日报推送成功率 > 99%、早晨 08:35 前送达率 > 95% |
| 3.5 管线断点续跑 | 大规模扫描场景下的 checkpoint/resume |
| 3.6 预测性告警 | 基于历史数据源的故障模式预测（如 baostock 每月结算日不稳定的规律） |

### 路线图总览

```
Phase 1                 Phase 2                 Phase 3
   │                       │                       │
   ├─ 统一日志              ├─ Prometheus 指标        ├─ 关联 ID 全链路
   ├─ /health 端点          ├─ 飞书告警               ├─ 优雅降级
   ├─ cron 心跳             ├─ 数据新鲜度监控          ├─ Sentry 集成
   ├─ 清理 basicConfig       ├─ systemd 守护           ├─ SLO 定义
   └─ cron 包装脚本          ├─ Grafana（可选）         ├─ 断点续跑
   (1-2 天)                 └─ 管线运行历史            └─ 预测性告警
                           (2-3 天)                  (Phase 3 后按需)
```

---

## 九、附录

### A. 新增文件清单

| 文件 | 用途 |
|------|------|
| `investment_system/logging_config.py` | 全局日志配置、关联 ID 管理 |
| `investment_system/metrics.py` | Prometheus 指标定义 |
| `investment_system/alerting.py` | 飞书告警管理器 |
| `scripts/hermes_healthcheck.sh` | cron 心跳检查脚本 |
| `scripts/hermes_daily_morning.sh` | 日报盘前包装脚本 |
| `scripts/hermes_daily_evening.sh` | 日报收盘包装脚本 |
| `/etc/systemd/system/hermes-dashboard.service` | Dashboard systemd 配置 |
| `docs/grafana-dashboard.json` | Grafana Dashboard 模板（可选） |

### B. 依赖变更

| 依赖 | 版本 | 用途 | 阶段 |
|------|------|------|------|
| `python-json-logger` | `>= 2.0` | JSON 格式日志输出 | Phase 1 |
| `prometheus_client` | `>= 0.18` | Prometheus 指标暴露 | Phase 2 |
| `structlog` | `>= 23.0` | 结构化日志（可选，替代 python-json-logger） | Phase 2+ |
| `sentry-sdk` | `>= 1.40` | 错误追踪（可选） | Phase 3 |

### C. 环境变量新增

| 变量 | 说明 | 默认值 | 阶段 |
|------|------|--------|------|
| `HERMES_LOG_LEVEL` | 日志级别 | `INFO` | Phase 1 |
| `HERMES_LOG_DIR` | 日志目录 | `/var/log/hermes` | Phase 1 |
| `HERMES_LOG_JSON` | 是否 JSON 格式 | `true` | Phase 1 |
| `FEISHU_ALERT_WEBHOOK` | 飞书告警 Webhook URL | 空（不告警） | Phase 2 |
| `SENTRY_DSN` | Sentry DSN（可选） | 空（不启用） | Phase 3 |

---

*文档结束。方案设计阶段，所有代码示例为伪代码，具体实现以 PR 为准。*
