# 数据管线可靠性方案

> **状态**: 草案 | **日期**: 2026-07-03 | **作者**: 面基投研系统
>
> 本文档诊断当前数据管线的 10 项可靠性缺陷，给出逐项修复方案，并制定分阶段实施计划。

---

## 目录

- [一、摘要](#一摘要)
- [二、当前数据流](#二当前数据流)
- [三、故障模式分析](#三故障模式分析)
- [四、原子文件写入](#四原子文件写入)
- [五、Pickle 迁移](#五pickle-迁移)
- [六、缓存管理](#六缓存管理)
- [七、错误处理标准化](#七错误处理标准化)
- [八、数据层统一](#八数据层统一)
- [九、健康监控](#九健康监控)
- [十、Cron 可靠性](#十cron-可靠性)
- [十一、数据校验](#十一数据校验)
- [十二、实施计划](#十二实施计划)

---

## 一、摘要

Hermes 投资系统的数据管线承担"从多源数据到策略信号"的关键链路。当前管线存在 10 项可靠性缺陷，覆盖数据写入、反序列化安全、缓存膨胀、静默吞异常、连接管理、定时任务监控等多个维度。这些缺陷在单日运行时不易暴露，但在长期无人值守的 ECS Cron 环境中，任何一次静默失败都可能导致日报缺失、模拟盘持仓数据不同步、或因子评分用的数据已过期数日而未察觉。

**本文档对每个缺陷给出根因分析、修复方案、代码示例，并制定分 4 个阶段、按风险等级排序的实施计划，预计总工期 4-6 周。**

### 10 项缺陷总览

| 编号 | 缺陷 | 严重程度 | 影响范围 |
|------|------|---------|---------|
| D1 | JSON 文件直接写入，崩溃时数据损坏 | 🔴 高 | `shadow_account.json`, `trading_signals.json`, `scan_snapshot_latest.json`, 所有缓存 |
| D2 | `pickle.load()` 反序列化任意代码执行风险 | 🔴 高 | `data_router.cachedio` 装饰器，75 个 `.pkl` 缓存文件 |
| D3 | 缓存目录 75 个 `.pkl` 文件无上限增长 | 🟡 中 | `data/cache/` 目录，磁盘空间 + 性能退化 |
| D4 | `try-except: pass` 静默吞异常，数据失败返回默认值 | 🟡 中 | `data_layer.py` 多处，`run_daily.py` 多处 |
| D5 | baostock TCP 协议挂死风险 | 🟡 中 | `baostock_source.py`, `data_layer.py` |
| D6 | 双数据层并存，功能重叠 | 🟡 中 | `data_layer.py`（旧）vs `data_source_layer.py`（新） |
| D7 | 无 `/health` 端点，无法检查数据新鲜度 | 🟡 中 | Dashboard / ECS Cron |
| D8 | Cron 任务静默失败无感知 | 🟡 中 | ECS `run_daily.py` 定时任务 |
| D9 | 全局 socket timeout 冲突（30s vs 8s） | 🟢 低 | `run_daily.py` vs `data_source_layer.py` |
| D10 | baostock login/logout 配对不完整 | 🟢 低 | `data_layer.py`, `baostock_source.py`, `data_source_layer.py` |

---

## 二、当前数据流

### 2.1 完整数据管线

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              数据源层                                      │
│                                                                          │
│  baostock          yfinance          AKShare          EastMoney           │
│  (A股日线/财报)     (港美股/商品/汇率)  (ETF/期货/新闻)   (财务数据中心)       │
│     │                  │                │                 │              │
│     │                  │                │                 │              │
│  ┌──┴──────────────────┴────────────────┴─────────────────┴──┐           │
│  │                    数据接入层                                │           │
│  │                                                            │           │
│  │  ┌─────────────────┐   ┌──────────────────────────────┐   │           │
│  │  │ data_router.py   │   │ data_source_layer.py (新)     │   │           │
│  │  │  • cachedio 装饰器 │   │  • DataResult 质量标注        │   │           │
│  │  │  • pickle 缓存    │   │  • JSON 缓存                  │   │           │
│  │  │  • 符号自动路由    │   │  • _retry 重试包装            │   │           │
│  │  │  • get_history()  │   │  • 价格校验 (PRICE_SANITY)     │   │           │
│  │  │  • get_rt()       │   │  • 全市场快照                  │   │           │
│  │  └────────┬──────────┘   └──────────────┬───────────────┘   │           │
│  │           │                              │                   │           │
│  │  ┌────────┴──────────────────────────────┴───────────────┐   │           │
│  │  │ data_layer.py (旧)                                     │   │           │
│  │  │  • baostock 直连 + signal.alarm 超时保护                 │   │           │
│  │  │  • EastMoney DataCenter 财务数据                         │   │           │
│  │  │  • 进程内 _FIN_CACHE 内存缓存                            │   │           │
│  │  │  • get_stock_daily() / get_financial_report()           │   │           │
│  │  └────────────────────────┬───────────────────────────────┘   │           │
│  └───────────────────────────┼───────────────────────────────────┘           │
│                              │                                               │
│                    ┌─────────┴─────────┐                                     │
│                    │   4 层缓存架构     │                                     │
│                    │                   │                                     │
│                    │  内存缓存 (dict)   │  ← _FIN_CACHE, _universe_cache      │
│                    │       ↓           │                                     │
│                    │  pickle 缓存      │  ← data/cache/*.pkl (75个)          │
│                    │       ↓           │                                     │
│                    │  JSON 缓存        │  ← data/cache/*.json               │
│                    │       ↓           │                                     │
│                    │  业务文件          │  ← shadow_account.json, signals    │
│                    └─────────┬─────────┘                                     │
└──────────────────────────────┼───────────────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
       因子引擎层          策略执行层          输出层
    factor_scanner.py   faceji/silverquant   run_daily.py
    factor_engine.py    tradingagents        portfolio_server.py
```

### 2.2 关键数据文件

| 文件 | 写入方式 | 写入者 | 风险 |
|------|---------|--------|------|
| `shadow_account.json` | `json.dump()` 直接写入 | `shadow_account.py` | D1: 崩溃损毁 |
| `trading_signals.json` | `json.dump()` 直接写入 | `portfolio_builder.py` | D1: 崩溃损毁 |
| `scan_snapshot_latest.json` | `json.dump()` 直接写入 | `factor_engine.py` | D1: 崩溃损毁 |
| `/tmp/hermes_scan_snapshot.json` | `json.dump()` 直接写入 | `run_daily.py:429` | D1: 崩溃损毁 |
| `/tmp/hermes_top_priority.json` | `json.dump()` 直接写入 | `run_daily.py:606` | D1: 崩溃损毁 |
| `data/cache/*.pkl` | `pickle.dump()` | `data_router.cachedio` | D1+D2 |
| `data/cache/*.json` | `json.dump()` 直接写入 | `data_source_layer._write_cache` | D1: 崩溃损毁 |

### 2.3 数据消费者路径

```
run_daily.py (Cron 08:30 & 18:00)
  ├── MacroEngine.refresh()       → 宏观数据 → 双门判断
  ├── FactorScanner.scan_market_batch() → 因子评分 → 日报TOP10
  ├── get_news_with_impact()      → 新闻 → 异动情报
  ├── shadow_account entry/exit   → 模拟盘建仓/清仓
  └── FeishuWriter.create_doc()    → 飞书日报

portfolio_server.py (常驻 :8686)
  ├── /api/simulated     → 读取 shadow_account.json
  ├── /api/comparison    → 读取 trading_signals.json
  ├── /api/v2/pool       → 读取 pool_live.json
  └── /api/metrics       → 读取扫描快照
```

---

## 三、故障模式分析

### 3.1 按组件分解

#### data_router.cachedio（pickle 缓存装饰器）

| 故障模式 | 触发条件 | 后果 | 当前检测 |
|---------|---------|------|---------|
| 缓存文件写一半崩掉 | 进程在 `pickle.dump()` 过程中被 kill | 缓存文件损坏，下次 `pickle.load()` 抛异常 | 无 |
| 任意代码执行 | 攻击者替换 `data/cache/*.pkl` 为恶意 pickle | RCE，获取 shell 权限 | 无 |
| 缓存永不过期 | TTL=720小时（30天），期间即使数据源更新也不刷新 | 使用过期数据 | 无 |
| 缓存无上限 | 符号组合无限增长，`data/cache/` 目录不断膨胀 | 磁盘占满 | 仅 `get_cache_info()` 可查询，无人调用 |

#### data_layer.py（旧层 — baostock 主力）

| 故障模式 | 触发条件 | 后果 | 当前检测 |
|---------|---------|------|---------|
| baostock TCP 挂死 | 网络闪断后 socket 进入半开状态 | `signal.alarm(25)` 超时 → `_bs_logout()` 重置 | 部分：`_BSTimeoutError` |
| 静默吞异常返回默认值 | `try: ... except: pass` (如 `get_stock_info:120`) | 调用方收到 `{"name": symbol}` 假数据 | 无 |
| 连接未正确 logout | 异常路径漏掉 `_bs_logout()` | baostock 服务端资源泄漏 | 部分：`get_stock_daily:234` |
| EastMoney API 失败静默 | `try: ... except Exception: return {}` | 财务数据为空，且无日志 | 无 |

#### data_source_layer.py（新层 — DataResult 质量标注）

| 故障模式 | 触发条件 | 后果 | 当前检测 |
|---------|---------|------|---------|
| JSON 缓存写崩 | `_write_cache` 直接 `json.dump()` | 缓存损坏 | 无 |
| 全市场快照过期 | `_UNIVERSE_TTL=1800s` 过期后重试失败 | `build_candidate_universe` 返回 failed | ✅ `result.ok` 检查 |
| 价格校验误杀 | 价格超出 `PRICE_SANITY` 区间（极端行情） | 真实行情被标记为 failed | ✅ 返回 DataResult.failed |

#### baostock_source.py（数据路由底层）

| 故障模式 | 触发条件 | 后果 | 当前检测 |
|---------|---------|------|---------|
| `rs.next()` 无限挂死 | baostock TCP 响应不完整 | 整个管线阻塞 | 无（`data_router` 调用此文件，无 alarm 保护） |
| login/logout 不配对 | 异常路径未 logout | 连接泄漏 | 无 |

#### run_daily.py（Cron 管线）

| 故障模式 | 触发条件 | 后果 | 当前检测 |
|---------|---------|------|---------|
| 全管线崩溃 | 任何未捕获异常 | 飞书文档删除，当日无日报，无通知 | 仅日志写 `/tmp/report_daily_log.txt` |
| 扫描未完成 | `scan_status != "complete"` | 文档删除，`sys.exit(1)` — Cron 静默 | 无外部告警 |
| JSON 快照写崩 | 磁盘满 / 权限不足 | 下次无法对比排名变化 | `try: except: pass` 静默 |
| baostock 残留状态干扰 | 前次 `_fetch_watchlist_prices` 残留 logout | `_reset_bs()` 有调用（`run_daily.py:386`），但不保证所有路径 | 部分 |

### 3.2 故障传播链分析

```
网络闪断
  → baostock TCP 半开
    → _bs_query_with_timeout 25s 超时 → _bs_logout() → 连接重置
      → 但 data_router.cachedio 在超时前已缓存了旧数据的 pickle
        → 下次调用走缓存，返回过期数据
          → 因子评分基于过期数据
            → 日报展示错误排名
              → 模拟盘基于错误排名建仓
                → 实际交易决策错误
```

**关键洞察**：最危险的故障不是崩溃，而是"静默返回错误数据"。缓存机制在正常情况下提升性能，但在异常时可能固化错误数据。

---

## 四、原子文件写入

### 4.1 问题分析

当前所有 JSON/JSONL 文件的写入方式均为：

```python
# 当前写法 (data_source_layer.py:135-136)
with open(path, "w") as f:
    json.dump(data, f, ensure_ascii=False, default=str)
```

如果进程在 `json.dump()` 或 `f.write()` 过程中崩溃（OOM killer、ECS 重启、磁盘满等），文件将处于中间状态——可能缺少后半部分 JSON 数据，或文件为 0 字节。下次读取时 `json.load()` 会抛出 `JSONDecodeError`，导致 Dashboard 无法展示持仓、模拟盘无法执行止损、日报无法对比排名变化。

**受影响文件清单**：

| 文件 | 写入位置 | 读取方 | 损坏后果 |
|------|---------|--------|---------|
| `shadow_account.json` | `shadow_account.py` | Dashboard `/api/simulated`, 日报 | 持仓数据丢失，模拟盘状态不可信 |
| `trading_signals.json` | `portfolio_builder.py` | Dashboard `/api/comparison` | 回测对比面板空白 |
| `scan_snapshot_latest.json` | `factor_engine.py` | 日报排名、下次对比 | 多日排名趋势中断 |
| 所有 `data/cache/*.json` | `data_source_layer._write_cache` | 各数据获取函数 | 缓存失效，需重新请求外部 API |
| `/tmp/hermes_scan_snapshot.json` | `run_daily.py:429` | 下次日报对比 | 排名变化标注丢失 |
| `/tmp/hermes_top_priority.json` | `run_daily.py:606` | 明日日报优先票 | 优先票信息丢失 |

### 4.2 修复方案：Write-Temp-Then-Rename

标准 POSIX 原子写入模式：先将数据写入临时文件，`fsync` 确保落盘，再 `os.rename`（原子操作）覆盖目标文件。

```python
# data/atomic_write.py — 新增模块

import os
import json
import tempfile
from pathlib import Path
from typing import Any
import logging

logger = logging.getLogger(__name__)


def atomic_write_json(path: str, data: Any, **json_kwargs) -> None:
    """原子写入 JSON 文件：写临时文件 → fsync → rename。

    在任何崩溃点恢复后，目标文件要么是完整的旧版本，
    要么是完整的新版本，不会是半截文件。
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix=f".{target.name}.",
        dir=str(target.parent),
        delete=False,
    )
    try:
        json.dump(data, tmp, **json_kwargs)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.rename(tmp.name, str(target))
    except Exception:
        tmp.close()
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def atomic_read_json(path: str, default: Any = None) -> Any:
    """读取 JSON 文件，损坏时自动回退到 .bak 或返回 default。"""
    target = Path(path)
    if not target.exists():
        return default

    try:
        with open(target, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("JSON 文件损坏: %s, 错误: %s", path, e)
        bak = target.with_suffix(".json.bak")
        if bak.exists():
            try:
                with open(bak, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return default


def atomic_write_with_backup(path: str, data: Any, **json_kwargs) -> None:
    """写入前自动备份旧文件为 .bak。"""
    target = Path(path)
    if target.exists():
        bak = target.with_suffix(".json.bak")
        try:
            import shutil
            shutil.copy2(str(target), str(bak))
        except OSError:
            pass
    atomic_write_json(path, data, **json_kwargs)
```

### 4.3 迁移策略

提供 `AtomicFileContext` 上下文管理器，统一替换现有的裸 `json.dump()` 写入：

```python
# 迁移示例: shadow_account.py 改造前后对比

# 改造前
with open(SHADOW_FILE, "w") as f:
    json.dump(self.book, f, ensure_ascii=False, indent=2)

# 改造后
from data.atomic_write import atomic_write_with_backup
atomic_write_with_backup(SHADOW_FILE, self.book, ensure_ascii=False, indent=2)
```

**搜索并替换**：全项目搜索 `json.dump` 和 `open(.*"w")` 模式，逐一替换为原子写入。预计涉及约 8-10 处写入点。

---

## 五、Pickle 迁移

### 5.1 风险分析

`data_router.cachedio` 装饰器（`data_router.py:29-60`）对所有 `get_history()` 调用的结果使用 `pickle.dump()/pickle.load()` 做缓存持久化。当前 `data/cache/` 目录下有 75 个 `.pkl` 文件。

**攻击面**：

1. 如果 ECS 服务器被入侵（即使权限很低），攻击者可以把恶意 pickle 文件放入 `data/cache/`，当 `cachedio` 装饰器调用 `pickle.load()` 时即执行任意代码
2. 如果有任何其他进程/用户写入 `data/cache/`（比如共享目录权限过宽），同样可触发 RCE
3. `pickle.load()` 没有签名校验，无法区分正常缓存和被篡改的缓存

### 5.2 替代方案评估

| 方案 | 安全性 | 性能 | Pandas 兼容性 | 可读性 | 迁移难度 |
|------|--------|------|-------------|--------|---------|
| **JSON** | ✅ 纯数据 | 中等 | ❌ DataFrame 需 `to_dict('records')` | ✅ 人类可读 | 低 |
| **msgpack** | ✅ 纯数据 | 高 | ❌ 同 JSON，需序列化 | 🟡 二进制 | 中 |
| **Parquet** | ✅ 纯数据 | 高（列式压缩） | ✅ 原生 DataFrame 支持 | 🟡 二进制 | 中 |
| **pickle（现状）** | ❌ RCE 风险 | 高 | ✅ 原生 Python 对象 | ❌ 二进制 | — |

### 5.3 推荐方案：Parquet + JSON 双层

**核心策略**：按数据类型选择序列化格式，不追求单一方案。

| 数据类型 | 当前格式 | 推荐格式 | 理由 |
|---------|---------|---------|------|
| DataFrame（历史行情） | pickle | **Parquet** | 列式存储压缩率高，Pandas 原生 `read_parquet/to_parquet` |
| dict/基本类型（价格快照） | pickle | **JSON** | 人类可读，Dashboard 可直接消费 |
| 复杂嵌套对象 | pickle | **JSON + 类型标注** | 定义清晰的数据契约 |

### 5.4 Parquet 实现

```python
# data/parquet_cache.py — 新增模块

import os
from pathlib import Path
from typing import Optional
import pandas as pd
import time

from data.atomic_write import atomic_write_json

_PARQUET_DIR = Path(__file__).parent.parent / "data" / "cache"
_PARQUET_DIR.mkdir(parents=True, exist_ok=True)


def read_cache_parquet(key: str, ttl_hours: int) -> Optional[pd.DataFrame]:
    path = _PARQUET_DIR / f"{key}.parquet"
    meta_path = _PARQUET_DIR / f"{key}.meta.json"
    if not path.exists():
        return None
    try:
        if meta_path.exists():
            import json
            with open(meta_path) as f:
                meta = json.load(f)
            age = time.time() - meta.get("_ts", 0)
            if age > ttl_hours * 3600:
                return None
        return pd.read_parquet(path)
    except Exception:
        return None


def write_cache_parquet(key: str, df: pd.DataFrame):
    from data.atomic_write import atomic_write_json
    path = _PARQUET_DIR / f"{key}.parquet"
    tmp = str(path) + ".tmp"
    df.to_parquet(tmp, index=False)
    os.rename(tmp, str(path))
    atomic_write_json(
        str(_PARQUET_DIR / f"{key}.meta.json"),
        {"_ts": time.time(), "rows": len(df), "columns": list(df.columns)},
    )
```

### 5.5 向后兼容迁移计划

```
Phase A: 双写（同时写 pickle + Parquet/JSON），读取优先新格式
  ├── cachedio 装饰器改造: 写 pickle 的同时写 Parquet/JSON
  ├── 读取时优先读 Parquet/JSON，失败回退 pickle
  └── 运行 1-2 周，验证新格式数据完整性

Phase B: 切换为主（仅写新格式，保留 pickle 读取兼容）
  ├── 停止写 pickle
  ├── 读取仍兼容 pickle（旧缓存文件还在）
  └── 新增 `_write_cache_json` 替换裸 `json.dump()`

Phase C: 清理（删除 pickle 读取逻辑，清理旧文件）
  ├── 删除 `data/cache/*.pkl`
  ├── 移除 cachedio 中的 pickle 读写代码
  └── 移除 `import pickle`（如无其他地方使用）
```

### 5.6 cachedio 改造示意

```python
# 改造后的 cachedio 装饰器核心逻辑
def cachedio_v2(ttl_hours: int = 24):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key_parts = [func.__name__] + [str(a) for a in args] + \
                        [f"{k}={v}" for k, v in sorted(kwargs.items())]
            cache_name = "_".join(key_parts).replace(".", "_").replace("=", "_")[:200]

            # 优先读 Parquet（DataFrame 数据）
            parquet_path = _DATA_DIR / f"{cache_name}.parquet"
            if parquet_path.exists():
                age = time.time() - parquet_path.stat().st_mtime
                if age < ttl_hours * 3600:
                    return pd.read_parquet(parquet_path)

            # 回退读旧 pickle（Phase A 过渡期）
            pkl_path = _DATA_DIR / f"{cache_name}.pkl"
            if pkl_path.exists():
                age = time.time() - pkl_path.stat().st_mtime
                if age < ttl_hours * 3600:
                    with open(pkl_path, "rb") as f:
                        return pickle.load(f)  # Phase C 删除此行

            result = func(*args, **kwargs)
            if result is not None:
                if isinstance(result, pd.DataFrame):
                    result.to_parquet(parquet_path, index=False)
                elif isinstance(result, dict):
                    from data.atomic_write import atomic_write_json
                    atomic_write_json(
                        str(_DATA_DIR / f"{cache_name}.json"),
                        result, ensure_ascii=False, default=str,
                    )
            return result
        return wrapper
    return decorator
```

---

## 六、缓存管理

### 6.1 问题分析

`data/cache/` 目录当前有 75 个 `.pkl` 文件，增长来源于 `cachedio` 装饰器：每次调用 `get_history("新代码", days)` 生成一个新的 `.pkl` 文件。缓存键是由函数名 + 参数拼接的字符串哈希（`data_router.py:43`），没有数量上限、没有淘汰策略、没有定期清理。

**增长推算**：

- 当前观察池约 100 个代码
- 每天扫描新增候选池约 300 个代码
- 每条 `get_history(sym, days)` 产生 1 个缓存文件
- 按 Parquet 压缩后约 50KB/文件
- 一个月累计：约 300 × 50KB = 15MB，尚可接受
- 但按 pickle 未压缩：约 200KB/文件，一个月 60MB，且持续增长

### 6.2 三层缓存策略

```
┌─────────────────────────────────────────────┐
│  L1: 内存缓存 (dict)                         │
│  TTL: 进程生命周期                            │
│  用途: 高频读取的全市场快照                     │
│  示例: _FIN_CACHE, _universe_cache           │
├─────────────────────────────────────────────┤
│  L2: 本地文件缓存 (Parquet/JSON)              │
│  TTL: 按数据类型 1h-720h                     │
│  限制: 最多 200 个文件，总大小 < 100MB         │
│  LRU 淘汰: 访问时间最旧的优先删除              │
├─────────────────────────────────────────────┤
│  L3: 远程 API (baostock/yfinance/AKShare)     │
│  频率控制: _rate_limit() 防止限流              │
│  重试: _retry() 指数退避                       │
└─────────────────────────────────────────────┘
```

### 6.3 LRU 淘汰实现

```python
# data/cache_manager.py — 新增模块

import os
import time
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)

_DEFAULT_MAX_FILES = 200
_DEFAULT_MAX_SIZE_MB = 100


class CacheManager:
    def __init__(
        self,
        cache_dir: str,
        max_files: int = _DEFAULT_MAX_FILES,
        max_size_mb: int = _DEFAULT_MAX_SIZE_MB,
        auto_cleanup: bool = True,
    ):
        self.cache_dir = Path(cache_dir)
        self.max_files = max_files
        self.max_size_mb = max_size_mb
        self.auto_cleanup = auto_cleanup
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _collect_stats(self) -> dict:
        """收集缓存目录统计信息"""
        files = []
        total_size = 0
        for f in self.cache_dir.glob("*"):
            if f.is_file():
                stat = f.stat()
                size = stat.st_size
                files.append({
                    "path": f,
                    "size": size,
                    "mtime": stat.st_mtime,
                    "atime": stat.st_atime,
                })
                total_size += size
        return {
            "file_count": len(files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
            "files": sorted(files, key=lambda x: x["atime"]),  # LRU 排序
        }

    def cleanup_if_needed(self) -> int:
        """如果超过限制，按 LRU 淘汰最旧文件。返回删除的文件数。"""
        stats = self._collect_stats()
        files = stats["files"]
        total_mb = stats["total_size_mb"]

        to_delete = 0
        # 文件数超限
        if len(files) > self.max_files:
            to_delete = len(files) - self.max_files
        # 总大小超限
        if total_mb > self.max_size_mb:
            size_to_free = total_mb - self.max_size_mb
            size_deleted = 0
            for f_info in files:
                if size_deleted >= size_to_free * 1024 * 1024:
                    break
                size_deleted += f_info["size"]
                to_delete = max(to_delete, files.index(f_info) + 1)

        deleted = 0
        for f_info in files[:to_delete]:
            try:
                f_info["path"].unlink()
                deleted += 1
            except OSError as e:
                logger.debug("删除缓存文件失败: %s: %s", f_info["path"], e)

        if deleted > 0:
            logger.info(
                "缓存清理: 删除 %d 个文件, 剩余 %d 个, %.1fMB",
                deleted, len(files) - deleted,
                (total_mb - sum(f["size"] for f in files[:deleted]) / 1024 / 1024),
            )
        return deleted

    def get_stats(self) -> dict:
        stats = self._collect_stats()
        return {
            "cache_dir": str(self.cache_dir),
            "file_count": stats["file_count"],
            "total_size_mb": stats["total_size_mb"],
            "max_files": self.max_files,
            "max_size_mb": self.max_size_mb,
            "oldest_file_age_hours": round(
                (time.time() - stats["files"][0]["mtime"]) / 3600, 1
            ) if stats["files"] else None,
            "newest_file_age_hours": round(
                (time.time() - stats["files"][-1]["mtime"]) / 3600, 1
            ) if stats["files"] else None,
        }

    def validate_cache(self, max_age_hours: int = 72) -> dict:
        """验证缓存新鲜度。返回过期的文件列表。"""
        stats = self._collect_stats()
        stale = []
        now = time.time()
        for f_info in stats["files"]:
            age_hours = (now - f_info["mtime"]) / 3600
            if age_hours > max_age_hours:
                stale.append({
                    "file": f_info["path"].name,
                    "age_hours": round(age_hours, 1),
                    "size_kb": round(f_info["size"] / 1024, 1),
                })
        return {
            "total_files": stats["file_count"],
            "stale_files": len(stale),
            "stale_details": stale[:10],
        }
```

### 6.4 集成点

在 `cachedio_v2` 装饰器中，每次写入新缓存后调用 `cache_manager.cleanup_if_needed()`。同时提供一个 `_daily_cleanup()` 函数，在 `run_daily.py` 末尾调用，作为 Cron 任务的一部分确保缓存不膨胀。

```python
# 在 run_daily.py 末尾添加
from data.cache_manager import CacheManager

_cache_mgr = CacheManager(
    cache_dir="/home/admin/.hermes/investment_system/data/cache",
    max_files=200,
    max_size_mb=100,
)
_cache_mgr.cleanup_if_needed()
```

---

## 七、错误处理标准化

### 7.1 问题清单

**裸 `except: pass`（最严重）**：

| 位置 | 代码 | 后果 |
|------|------|------|
| `data_layer.py:120` | `except: pass` | `get_stock_info` 失败返回 `{"name": symbol}` 假数据 |
| `data_layer.py:133` | `except: pass` | `get_all_stocks` 缺数据无感知 |
| `data_router.py:181` | `except Exception: pass` | 双源交叉验证失败静默 |
| `data_source_layer.py:127` | `except Exception: pass` | 缓存读取失败静默 |
| `data_source_layer.py:505` | `except Exception: pass` | 社融数据缺失静默 |
| `run_daily.py` 多处 | `except: pass` / `except Exception: pass` | 日报板块静默缺失 |

**无结构化日志**：当前使用 `print()` 输出，无时间戳、无级别、无上下文，无法被日志系统收集。

### 7.2 修复方案

#### 7.2.1 异常处理层级标准

```
Level 0: 可恢复 — 记录 WARNING 日志，返回 fallback 值
  例: 单个数据源失败 → 尝试备源

Level 1: 降级运行 — 记录 ERROR 日志，返回降级结果
  例: 全部数据源失败 → 使用缓存旧数据，标记 quality="stale"

Level 2: 致命错误 — 记录 CRITICAL 日志，触发告警
  例: shadow_account.json 损坏且无备份
```

#### 7.2.2 结构化错误日志

```python
# data/error_handler.py — 新增模块

import logging
import traceback
from functools import wraps
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger("hermes.data")


@dataclass
class DataError:
    source: str
    symbol: str = ""
    error_type: str = ""
    message: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    recoverable: bool = True


class DataPipelineError(Exception):
    def __init__(self, source: str, message: str, recoverable: bool = True):
        self.source = source
        self.recoverable = recoverable
        super().__init__(f"[{source}] {message}")


def safe_data_fetch(
    source: str,
    fallback: Any = None,
    log_level: str = "warning",
) -> Callable:
    """数据获取安全包装器。

    用法:
        @safe_data_fetch(source="baostock", fallback={})
        def get_stock_info(symbol):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        def wrapper(*args, **kwargs):
            symbol = args[0] if args else kwargs.get("symbol", "?")
            try:
                return func(*args, **kwargs)
            except DataPipelineError as e:
                if log_level == "critical":
                    logger.critical(
                        "数据获取失败 [%s] %s: %s", source, symbol, e.message,
                        extra={"source": source, "symbol": symbol, "error": str(e)},
                    )
                else:
                    logger.warning(
                        "数据获取失败 [%s] %s: %s", source, symbol, str(e)[:120],
                        extra={"source": source, "symbol": symbol},
                    )
                return fallback
            except Exception as e:
                logger.error(
                    "数据获取异常 [%s] %s: %s\n%s",
                    source, symbol, str(e)[:200],
                    traceback.format_exc()[-500:],
                    extra={"source": source, "symbol": symbol},
                )
                return fallback
        return wrapper
    return decorator
```

#### 7.2.3 熔断器模式（Circuit Breaker）

针对 baostock 的不稳定性，引入熔断器：连续失败 N 次后，在一定时间内不再尝试，直接返回缓存或 fallback，避免级联超时。

```python
# data/circuit_breaker.py — 新增模块

import time
import threading
from enum import Enum


class CircuitState(Enum):
    CLOSED = "closed"         # 正常通行
    OPEN = "open"             # 熔断，拒绝请求
    HALF_OPEN = "half_open"   # 探测恢复


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 300.0,  # 5 分钟
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._half_open_calls = 0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
            return self._state

    def allow_request(self) -> bool:
        s = self.state
        if s == CircuitState.CLOSED:
            return True
        if s == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls < self.half_open_max_calls:
                    self._half_open_calls += 1
                    return True
            return False
        return False

    def record_success(self):
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    def record_failure(self):
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN


# 全局熔断器实例
baostock_breaker = CircuitBreaker(
    name="baostock",
    failure_threshold=3,
    recovery_timeout=300,
)
yfinance_breaker = CircuitBreaker(
    name="yfinance",
    failure_threshold=5,
    recovery_timeout=120,
)
akshare_breaker = CircuitBreaker(
    name="akshare",
    failure_threshold=3,
    recovery_timeout=180,
)
```

#### 7.2.4 改造示例

```python
# data_layer.py 改造前后对比

# 改造前 (L120-122)
def get_stock_info(symbol: str) -> dict:
    _bs_login()
    try:
        ...
    except:
        pass
    return {"name": symbol}

# 改造后
def get_stock_info(symbol: str) -> dict:
    if not baostock_breaker.allow_request():
        logger.warning("baostock 熔断中，get_stock_info(%s) 返回降级数据", symbol)
        return {"name": symbol, "_degraded": True}

    _bs_login()
    try:
        rs = _bs_query_with_timeout(bs.query_stock_basic, code=_bs_code(symbol))
        if rs.error_code == "0":
            rows = _bs_iter_results(rs, timeout=15)
            if rows:
                baostock_breaker.record_success()
                r = rows[0]
                return {"name": r[1], "list_date": r[2], "status": r[4]}
    except _BSTimeoutError as e:
        logger.warning("baostock 超时: get_stock_info(%s): %s", symbol, e)
        baostock_breaker.record_failure()
    except Exception as e:
        logger.error("get_stock_info(%s) 异常: %s", symbol, e)
        baostock_breaker.record_failure()

    return {"name": symbol, "_degraded": True}
```

---

## 八、数据层统一

### 8.1 双数据层现状

系统存在两个并行但功能重叠的数据接入层：

**data_layer.py（旧层 ~885 行）**：

- baostock 作为主力，直接管理 login/logout
- 使用 `signal.alarm` 做超时保护（但 `baostock_source.py` 没有）
- `DataResult` 质量标注缺失，返回原始 dict/pd.DataFrame 或空值
- 大量 `try: ... except: pass` 静默吞异常
- 调用方：`run_daily.py`, `factor_scanner.py`, 三策略引擎
- 进程内 `_FIN_CACHE` 字典缓存

**data_source_layer.py（新层 ~720 行）**：

- `DataResult` 质量标注结构，调用方需检查 `result.ok`
- `_retry` 重试包装器 + `_rate_limit` 频率控制
- JSON 缓存（带 TTL）
- PRICE_SANITY 价格校验
- 仅被新功能使用（LDS 全天候组合、全市场快照）
- 代码更规范，错误处理更完善

### 8.2 统一策略

**以 data_source_layer.py 的风格和 DataResult 结构为基础，逐步吸收 data_layer.py 的功能。**

```
统一后的数据层结构：

data/
├── atomic_write.py           # 原子文件写入
├── cache_manager.py          # 缓存管理 (LRU + 统计)
├── circuit_breaker.py        # 熔断器
├── error_handler.py          # 错误处理 + 结构化日志
├── quality.py                # DataResult 数据质量标注
├── retry.py                  # _retry + _rate_limit
├── parquet_cache.py          # Parquet 读写
│
├── data_router.py            # 统一数据路由 + 符号分发
├── data_access.py            # (新) 统一数据获取 API
│
├── sources/
│   ├── __init__.py
│   ├── baostock_source.py    # A 股日线/财报
│   ├── yahoo_source.py       # 港美股/商品/汇率
│   ├── akshare_source.py     # ETF/新闻/全市场快照
│   └── eastmoney_source.py   # EastMoney 财务数据中心
│
└── cache/                    # 缓存目录 (Parquet + JSON)
```

### 8.3 data_access.py 统一 API

```python
# data/data_access.py — 统一数据获取入口

from dataclasses import dataclass
from typing import Optional, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class DataResult:
    """统一的数据结果结构（从 data_source_layer.py 提取）"""
    data: Any
    source: str
    fetched_at: str
    quality: str       # "fresh" | "stale" | "fallback" | "failed"
    staleness_days: float = 0.0
    warning: str = ""

    @property
    def ok(self) -> bool:
        return self.quality in ("fresh", "stale", "fallback")

    @staticmethod
    def failed(source: str, reason: str) -> "DataResult":
        from datetime import datetime
        return DataResult(
            data=None, source=source,
            fetched_at=datetime.now().isoformat(),
            quality="failed", warning=reason,
        )


def get_history(symbol: str, days: int = 1200) -> DataResult:
    """获取历史日线（统一入口，返回 DataResult）"""
    from data.data_router import get_history as _old_get_history
    from datetime import datetime

    try:
        result = _old_get_history(symbol, days)
        if result is None:
            return DataResult.failed("data_router", f"{symbol} 无数据")
        staleness = 0  # cachedio 已处理 TTL
        return DataResult(
            data=result, source="data_router",
            fetched_at=datetime.now().isoformat(),
            quality="fresh", staleness_days=staleness,
        )
    except Exception as e:
        return DataResult.failed("data_router", str(e))


# 逐步将 data_layer.py 的函数迁移到此，统一返回 DataResult
```

### 8.4 迁移路线

1. 提取 `DataResult` 到 `data/quality.py`，两个旧层同时 import
2. 将 `_retry`, `_rate_limit` 提取到 `data/retry.py`
3. `data_layer.py` 每个函数加 `DataResult` 包装，不改变内部逻辑
4. 调用方逐步从直接取 `dict['key']` 改为检查 `result.ok` 后取 `result.data['key']`
5. 最后合并到 `data_access.py`，删除 `data_layer.py`

---

## 九、健康监控

### 9.1 /health 端点

在 `portfolio_server.py` (FastAPI) 中新增 `/health` 端点，返回数据管线各环节的健康状态。

```python
# 在 portfolio_server.py 中添加

from fastapi import APIRouter
from datetime import datetime, timedelta
import os

health_router = APIRouter()

# 数据新鲜度阈值
STALENESS_THRESHOLDS = {
    "scan_snapshot": 8,       # 扫描快照超过 8 小时 → 过期
    "shadow_account": 1,      # 模拟盘持仓超过 1 小时 → 需关注
    "trading_signals": 8,     # 交易信号超过 8 小时 → 过期
    "macro_cache": 168,       # 宏观数据超过 7 天 → 过期
}


@health_router.get("/health")
def health_check():
    now = datetime.now()
    checks = {}

    # 扫描快照
    snap_files = sorted(
        [f for f in os.listdir(".") if f.startswith("scan_snapshot_") and f.endswith(".json")],
        reverse=True,
    )
    snap_ok = False
    snap_age_hours = None
    if snap_files:
        try:
            snap_mtime = datetime.fromtimestamp(os.path.getmtime(snap_files[0]))
            snap_age_hours = round((now - snap_mtime).total_seconds() / 3600, 1)
            snap_ok = snap_age_hours <= STALENESS_THRESHOLDS["scan_snapshot"]
        except OSError:
            pass
    checks["scan_snapshot"] = {
        "status": "ok" if snap_ok else "stale",
        "latest_file": snap_files[0] if snap_files else None,
        "age_hours": snap_age_hours,
        "threshold_hours": STALENESS_THRESHOLDS["scan_snapshot"],
    }

    # 模拟盘数据
    sa_file = "shadow_account.json"
    sa_ok = False
    sa_age_hours = None
    if os.path.exists(sa_file):
        try:
            sa_mtime = datetime.fromtimestamp(os.path.getmtime(sa_file))
            sa_age_hours = round((now - sa_mtime).total_seconds() / 3600, 1)
            sa_ok = sa_age_hours <= STALENESS_THRESHOLDS["shadow_account"]
        except OSError:
            pass
    checks["shadow_account"] = {
        "status": "ok" if sa_ok else "stale",
        "age_hours": sa_age_hours,
        "threshold_hours": STALENESS_THRESHOLDS["shadow_account"],
    }

    # 缓存目录统计
    cache_dir = "data/cache"
    cache_stats = {"file_count": 0, "total_size_mb": 0}
    if os.path.isdir(cache_dir):
        files = [f for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
        total_size = sum(
            os.path.getsize(os.path.join(cache_dir, f)) for f in files
        )
        cache_stats = {
            "file_count": len(files),
            "total_size_mb": round(total_size / 1024 / 1024, 2),
        }
    checks["cache"] = cache_stats

    # 整体状态
    all_ok = all(
        c.get("status") == "ok"
        for name, c in checks.items()
        if isinstance(c, dict) and "status" in c
    )

    return {
        "status": "healthy" if all_ok else "degraded",
        "timestamp": now.isoformat(),
        "checks": checks,
    }
```

### 9.2 数据新鲜度告警

在 `run_daily.py` 执行前，检查关键文件的新鲜度。如果扫描快照超过 8 小时未更新（说明前次 Cron 失败），通过飞书 Bot 发送告警消息。

```python
# 在 run_daily.py 开头添加预检查

def preflight_check() -> list[str]:
    """管线执行前检查，返回告警列表"""
    warnings = []
    now = time.time()

    snap_files = sorted(
        [f for f in os.listdir(".") if f.startswith("scan_snapshot_") and f.endswith(".json")],
        reverse=True,
    )
    if snap_files:
        snap_age = (now - os.path.getmtime(snap_files[0])) / 3600
        if snap_age > 8:
            warnings.append(f"扫描快照过期 {snap_age:.1f}h，上次扫描可能未完成")

    sa_file = "shadow_account.json"
    if os.path.exists(sa_file):
        sa_age = (now - os.path.getmtime(sa_file)) / 3600
        if sa_age > 24:
            warnings.append(f"模拟盘持仓 {sa_age:.1f}h 未更新")

    return warnings
```

---

## 十、Cron 可靠性

### 10.1 当前问题

`run_daily.py` 通过 ECS Cron 定时执行（工作日 08:30 和 18:00）。当前唯一的失败检测机制是：

1. `scan_status != "complete"` → 删除飞书文档 → `sys.exit(1)`
2. 全管线崩溃 → 日志写 `/tmp/report_daily_log.txt` → 无人读取

**缺失**：

- 飞书通知：Cron 失败时无人知道
- 重试逻辑：失败后没有自动重试
- Dead Man's Switch：如果 Cron 完全没触发（ECS 宕机），无人察觉

### 10.2 修复方案

#### 10.2.1 失败告警到飞书

```python
# scripts/cron_notify.py — 新增模块

import os
import json
import requests
from datetime import datetime


def send_feishu_alert(title: str, content: str, webhook_url: str = None):
    """通过飞书 Webhook 发送告警消息"""
    if webhook_url is None:
        webhook_url = os.environ.get("FEISHU_ALERT_WEBHOOK", "")
    if not webhook_url:
        return

    payload = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"⚠️ Hermes: {title}"},
                "template": "red",
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}},
                {
                    "tag": "note",
                    "elements": [
                        {"tag": "plain_text", "content": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
                    ],
                },
            ],
        },
    }
    try:
        requests.post(webhook_url, json=payload, timeout=5)
    except Exception:
        pass
```

#### 10.2.2 run_daily.py 改造

```python
# run_daily.py 关键改动

from scripts.cron_notify import send_feishu_alert

# 1. 预检查
warnings = preflight_check()
if warnings:
    log(f"Preflight warnings: {warnings}")

# 2. 主逻辑包装（保留原有结构）
try:
    # ... 原有逻辑 ...
    log("=== 日报 SUCCESS ===")

except Exception as e:
    log(f"FATAL: {e}")
    import traceback
    log(traceback.format_exc())

    # 发送飞书告警
    send_feishu_alert(
        title="日报管线失败",
        content=(
            f"**会话**: {session}\n"
            f"**错误**: {str(e)[:200]}\n"
            f"**日志**: `/tmp/report_daily_log.txt`\n"
            f"**时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        ),
    )

    # 删除残留文档（保留原有逻辑）
    if doc_created and doc_id:
        try:
            w._api(f"/docx/v1/documents/{doc_id}", "DELETE")
        except Exception:
            pass
    sys.exit(1)
```

#### 10.2.3 Dead Man's Switch

在 Dashboard 的 `/health` 端点中增加"最后成功日报时间"字段。配合外部监控（如 UptimeRobot 或飞书 Bot 定时检查），如果超过 12 小时没有成功日报，触发告警：

```python
# /health 端点增加字段
checks["last_successful_report"] = {
    "status": "ok" if last_report_age_hours < 12 else "stale",
    "file": "/tmp/report_daily_log.txt",
    "age_hours": last_report_age_hours,
    "threshold_hours": 12,
}
```

#### 10.2.4 重试逻辑

当前 `run_daily.py` 在扫描不完整时直接 `sys.exit(1)`。改为：扫描不完整但有部分结果时，保留部分结果并在 30 分钟后重试一次（Cron 间隔足够）。如果重试后仍不完整，再发送告警。

```python
MAX_RETRY_ATTEMPTS = 1  # Cron 间隔内最多重试 1 次

if scan_status != "complete":
    if retry_count < MAX_RETRY_ATTEMPTS:
        log(f"扫描未完成 ({scan_status})，等待 30 分钟后重试 ({retry_count+1}/{MAX_RETRY_ATTEMPTS})")
        time.sleep(1800)
        retry_count += 1
        # 重新扫描剩余批次...
    else:
        log("扫描重试次数耗尽，发送告警")
        send_feishu_alert(
            title="日报扫描未完成",
            content=f"扫描状态: {scan_status}\n重试次数: {retry_count}\n已获取 {len(scan_results)} 条部分结果",
        )
        sys.exit(1)
```

---

## 十一、数据校验

### 11.1 行情数据校验

当前 `data_source_layer.py` 已实现部分价格校验（`PRICE_SANITY` 期货/汇率区间），但 **A 股日线数据没有任何校验**。baostock 返回异常数据（如价格为 0、成交量暴涨 100 倍、前复权价格除权错误）会直接进入因子引擎，影响评分。

#### 校验规则

| 校验项 | 规则 | 失败动作 |
|--------|------|---------|
| 价格范围 | `0.01 < close < 10000` | 丢弃该行 |
| 单日涨跌幅 | `abs(pct_chg) < 15%` (A股涨跌停±10%，留余量) | WARNING 日志，保留数据 |
| 成交量 | `volume > 0`（非停牌日必须） | WARNING 日志 |
| OHLC 一致性 | `low <= open/close/high <= high` | 丢弃该行 |
| 数据行数 | `len(dates) >= days * 0.5`（至少一半交易日有数据） | 标记 quality="stale" |
| 日期连续性 | 最近交易日距今天 ≤ 2 个自然日 | 标记 quality="stale"（非交易日前一天正常） |

#### 实现

```python
# data/validation.py — 新增模块

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def validate_ohlcv(data: dict, symbol: str, expected_min_rows: int = 100) -> dict:
    """校验 OHLCV 数据，返回清洗后的数据 + 校验报告。

    对每一行数据执行范围检查、一致性检查和完整性检查。
    """
    report = {
        "symbol": symbol,
        "total_rows": len(data.get("dates", [])),
        "valid_rows": 0,
        "dropped_price_range": 0,
        "dropped_ohlc_inconsistency": 0,
        "warnings": [],
    }

    if not data or not data.get("dates"):
        report["warnings"].append("空数据")
        return data, report

    dates = data["dates"]
    opens = data.get("open", [])
    highs = data.get("high", [])
    lows = data.get("low", [])
    closes = data.get("close", [])
    volumes = data.get("volume", [])
    pct_chgs = data.get("pct_chg", [])

    valid_indices = []
    for i in range(len(dates)):
        o, h, l, c = opens[i] if i < len(opens) else 0, \
                      highs[i] if i < len(highs) else 0, \
                      lows[i] if i < len(lows) else 0, \
                      closes[i] if i < len(closes) else 0

        # 价格范围
        if not (0.01 < c < 10000):
            report["dropped_price_range"] += 1
            continue

        # OHLC 一致性
        if not (l <= min(o, c) and max(o, c) <= h and l <= h):
            report["dropped_ohlc_inconsistency"] += 1
            continue

        valid_indices.append(i)

    report["valid_rows"] = len(valid_indices)

    # 数据不足告警
    if report["valid_rows"] < expected_min_rows:
        report["warnings"].append(
            f"有效行数 {report['valid_rows']} < 预期 {expected_min_rows}"
        )

    if report["dropped_price_range"] > 0:
        logger.warning(
            "[校验] %s: 丢弃 %d 行价格异常",
            symbol, report["dropped_price_range"],
        )
    if report["dropped_ohlc_inconsistency"] > 0:
        logger.warning(
            "[校验] %s: 丢弃 %d 行 OHLC 不一致",
            symbol, report["dropped_ohlc_inconsistency"],
        )

    # 过滤出有效行
    if len(valid_indices) < len(dates):
        for key in ["dates", "open", "high", "low", "close", "volume"]:
            if key in data and len(data[key]) == len(dates):
                data[key] = [data[key][j] for j in valid_indices]

    return data, report
```

### 11.2 缓存完整性校验

```python
def validate_cache_integrity(cache_dir: str) -> dict:
    """遍历缓存目录，检查每个文件是否可正常读取。"""
    import json
    from pathlib import Path

    corrupt_files = []
    total = 0

    for f in Path(cache_dir).glob("*"):
        total += 1
        suffix = f.suffix.lower()
        try:
            if suffix == ".json":
                with open(f) as fh:
                    json.load(fh)
            elif suffix == ".parquet":
                import pandas as pd
                pd.read_parquet(f)
        except Exception as e:
            corrupt_files.append({"file": f.name, "error": str(e)[:100]})

    return {
        "total": total,
        "corrupt": len(corrupt_files),
        "details": corrupt_files,
    }
```

---

## 十二、实施计划

### 12.1 总体路线

```
Phase 0 (立即 — 本周) · 止血
  D1: 原子文件写入          4-6h   ████████
  D4: 错误处理标准化          4-6h   ████████
  D10: baostock 连接管理     2-3h   ████

Phase 1 (本月) · 加固
  D3: 缓存管理               3-4h   ██████
  D5: baostock 稳定性增强    3-4h   ██████
  D7: /health 端点            2-3h   ████
  D9: socket timeout 统一    1h     ██

Phase 2 (下月) · 升级
  D2: Pickle 迁移 Phase A    6-8h   ████████████
  D8: Cron 可靠性             4-6h   ████████
  D11: 数据校验               4-6h   ████████

Phase 3 (持续) · 收敛
  D6: 数据层统一              8-12h  ████████████████████
  D2: Pickle 迁移 Phase B+C  4-6h   ████████
```

### 12.2 Phase 0 详细任务（止血）

| 任务 | 文件 | 改动 | 预估时间 | 验证方式 |
|------|------|------|---------|---------|
| 1.1 实现 `atomic_write.py` | `data/atomic_write.py`（新增） | 写入 `atomic_write_json`, `atomic_write_with_backup` | 1h | 单元测试：kill -9 后检查文件完整性 |
| 1.2 替换所有 JSON 写入点 | `shadow_account.py`, `portfolio_builder.py`, `factor_engine.py`, `run_daily.py` | 约 8 处 `json.dump` → `atomic_write_with_backup` | 2-3h | 运行日报管线，检查文件正常生成 |
| 1.3 实现 `error_handler.py` | `data/error_handler.py`（新增） | `DataPipelineError`, `safe_data_fetch` 装饰器 | 1h | 单元测试 |
| 1.4 修复 `data_layer.py` 裸 except | `data_layer.py` | 5 处 `except: pass` → 具体异常 + 日志 | 2h | 运行日报管线，检查日志无异常 |
| 1.5 修复 `data_router.py` 裸 except | `data_router.py:176-183` | `except Exception: pass` → logger.warning | 30min | 代码审查 |
| 1.6 baostock login/logout 配对 | `baostock_source.py` | `get_history_a` 加 try/finally logout | 1h | 连续运行 10 次扫描，无连接泄漏 |
| 1.7 添加结构化日志 | 全局 | `logger = logging.getLogger("hermes.xxx")` 替换裸 `print()` | 1h | 检查日志输出格式 |

### 12.3 Phase 1 详细任务（加固）

| 任务 | 文件 | 改动 | 预估时间 |
|------|------|------|---------|
| 2.1 实现 `cache_manager.py` | `data/cache_manager.py`（新增） | `CacheManager` 类，LRU 淘汰，统计 | 3-4h |
| 2.2 集成缓存清理到 `run_daily.py` | `run_daily.py` | 日报末尾调用 `cleanup_if_needed` | 30min |
| 2.3 实现 `circuit_breaker.py` | `data/circuit_breaker.py`（新增） | `CircuitBreaker` 类，3 个全局实例 | 2h |
| 2.4 baostock 源集成熔断器 | `baostock_source.py`, `data_layer.py` | 每次调用前后 `allow_request` / `record_*` | 1-2h |
| 2.5 实现 `/health` 端点 | `portfolio_server.py` | 新增 `health_router` + 数据新鲜度检查 | 2-3h |
| 2.6 统一 socket timeout | `data_source_layer.py`, `run_daily.py` | 删除 `data_source_layer.py` 的全局 `setdefaulttimeout(8)`，改为每个请求独立设置 | 1h |

### 12.4 Phase 2 详细任务（升级）

| 任务 | 文件 | 改动 | 预估时间 |
|------|------|------|---------|
| 3.1 实现 `parquet_cache.py` | `data/parquet_cache.py`（新增） | Parquet 读写 + 元数据管理 | 2h |
| 3.2 cachedio 双写改造 | `data_router.py` | 写 pickle 同时写 Parquet/JSON | 2h |
| 3.3 读取端优先新格式 | `data_router.py` | 读取优先 Parquet/JSON，失败回退 pickle | 2h |
| 3.4 实现 `cron_notify.py` | `scripts/cron_notify.py`（新增） | `send_feishu_alert` | 1h |
| 3.5 run_daily 出错告警 | `run_daily.py` | 异常 catch 中调用 `send_feishu_alert` | 1h |
| 3.6 run_daily 预检查 | `run_daily.py` | `preflight_check` + 重试逻辑 | 2h |
| 3.7 实现 `validation.py` | `data/validation.py`（新增） | `validate_ohlcv`, `validate_cache_integrity` | 2h |
| 3.8 各数据源集成校验 | `baostock_source.py`, `yahoo_source.py` | 每个数据获取后调用 `validate_ohlcv` | 2-3h |

### 12.5 Phase 3 详细任务（收敛）

| 任务 | 文件 | 改动 | 预估时间 |
|------|------|------|---------|
| 4.1 提取 DataResult 到独立模块 | `data/quality.py`（新增）, `data_layer.py`, `data_source_layer.py` | 统一 `DataResult` 定义 | 2h |
| 4.2 提取 retry 工具到独立模块 | `data/retry.py`（新增） | `_retry`, `_rate_limit` 独立 | 1h |
| 4.3 实现 `data_access.py` | `data/data_access.py`（新增） | 统一数据获取入口，所有函数返回 `DataResult` | 3-4h |
| 4.4 data_layer.py 函数包装 | `data_layer.py` | 每个函数加 `DataResult` 包装 | 2-3h |
| 4.5 调用方迁移 | `run_daily.py`, `factor_scanner.py`, 三策略 | `result = get_xxx(); if result.ok: data = result.data` | 2-3h |
| 4.6 删除 pickle 读逻辑 | `data_router.py` | 移除 `pickle.load` | 1h |
| 4.7 清理旧 pickle 文件 | `data/cache/` | 删除 `*.pkl` | 30min |

### 12.6 回滚策略

每个 Phase 的改动都是独立且向后兼容的。回滚策略：

- **Phase 0**：`atomic_write.py` 替换不影响读取逻辑，回滚直接还原文件即可。旧 JSON 文件不受影响。
- **Phase 1**：`CacheManager` 关闭 `auto_cleanup` 即停止清理；`CircuitBreaker` 关闭阈值设为极大值即永不开路。
- **Phase 2**：双写模式保证 pickle 缓存仍在，删除 Parquet 目录即可回退；飞书告警失败不影响管线执行。
- **Phase 3**：`data_access.py` 作为外观层，内部仍调用旧函数，删除新文件即可回退。

### 12.7 测试策略

| 测试类型 | 覆盖范围 | 方法 |
|---------|---------|------|
| 单元测试 | `atomic_write.py`, `cache_manager.py`, `circuit_breaker.py`, `error_handler.py`, `validation.py` | 标准 pytest |
| 集成测试 | 模拟数据源失败场景：baostock timeout, yfinance 空返回, JSON 损坏 | Mock 外部 API + 本地 fixture |
| 端到端测试 | 运行完整日报管线，验证文件原子写入、缓存清理、告警发送 | ECS 测试环境 `run_daily.py` |
| 故障注入 | kill -9 进程中检查文件完整性；强制磁盘满模拟；网络断连模拟 | 本地 Docker + chaos 工具 |

---

## 附录 A：受影响的文件清单

| 文件 | 改动类型 | 受影响 Phase |
|------|---------|-------------|
| `data/atomic_write.py` | 新增 | Phase 0 |
| `data/error_handler.py` | 新增 | Phase 0 |
| `data/cache_manager.py` | 新增 | Phase 1 |
| `data/circuit_breaker.py` | 新增 | Phase 1 |
| `data/parquet_cache.py` | 新增 | Phase 2 |
| `data/validation.py` | 新增 | Phase 2 |
| `data/retry.py` | 新增 | Phase 3 |
| `data/quality.py` | 新增 | Phase 3 |
| `data/data_access.py` | 新增 | Phase 3 |
| `data/data_router.py` | 修改 | Phase 0,2,3 |
| `data/data_layer.py` | 修改 | Phase 0,3 |
| `data/data_source_layer.py` | 修改 | Phase 1,3 |
| `data/sources/baostock_source.py` | 修改 | Phase 0,1,2 |
| `data/sources/yahoo_source.py` | 修改 | Phase 2 |
| `scripts/run_daily.py` | 修改 | Phase 0,1,2 |
| `scripts/cron_notify.py` | 新增 | Phase 2 |
| `scripts/portfolio_server.py` | 修改 | Phase 1 |

## 附录 B：新增依赖

| 依赖 | 用途 | Phase |
|------|------|-------|
| `pandas` | DataFrame 处理 + Parquet 读写 | Phase 2 (已有依赖) |
| `pyarrow` 或 `fastparquet` | Parquet 后端 | Phase 2 (新增) |
| `requests` | 飞书 Webhook 告警 | Phase 2 (已有依赖) |

---

## 附录 C：全局 socket timeout 冲突处理

`run_daily.py:13` 设置 `socket.setdefaulttimeout(30)`，而 `data_source_layer.py:32` 再次设置 `socket.setdefaulttimeout(8)`。由于 Python 的 `import` 顺序取决于调用链，后 import 的模块会覆盖前者的全局设置，导致行为不确定。

**修复**：删除两个文件中的全局 `socket.setdefaulttimeout`，改为在各自需要 Socket 超时的地方使用 `requests.get(url, timeout=N)` 或上下文管理器。对于 baostock（它不使用标准 socket），继续使用 `signal.alarm` 保护；对于 `yfinance`/`AKShare`，在 `_retry` 中通过参数传递 timeout。
