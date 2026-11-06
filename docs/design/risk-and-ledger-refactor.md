# 交易系统加固设计（SDD）

- 日期：2026-11-03
- 状态：Implemented（代码已落地，待部署机验证）
- 关联 ADR：0001–0008
- 影响范围：`strategies/`、`engine/`、`scripts/`、`output/`、`config.py`、`docs/`

## 1. 输入

### 1.1 审计发现（2026-11）

| # | 问题 | 后果 |
|---|------|------|
| A | 加载状态时丢弃 `current_price<=0` 的持仓 | 持仓永久消失、现金不回流 |
| B | 缺评分被当作 0 分参与卖出判断 | 数据缺失触发误卖 |
| C | 聚合账本丢失 peak | 四档 Trailing 失效，只剩 -8% 硬止损 |
| D | `run_trading` 与 `run_daily` 同写 `shadow_account.json` | 两套账本互相覆盖 |
| E | 风控数值散落 6+ 处且不一致 | 文档/回测/实盘三套口径 |
| F | 事件影子缺失、数据源 CRITICAL、覆盖率不足、宏观异常均 fail-open | 故障日仍开仓 |
| G | `--from/--to` 不生效、默认固定评分、策略四不计成本、IC 时间戳前视 | 对外回测数字不可复现 |
| H | 现金不足/周频拒单不打印原因 | 用户无法判断信号为何没执行 |

### 1.2 约束（来自需求方）

1. 账本收权采用**拆分文件 + 迁移旧账**，不整库迁移。
2. fail-open 一律改为**严格 fail-closed**。
3. **必须有备份，方便回滚**。
4. 用 **ADR** 记录决策，用 **SDD** 记录架构/设计/输入/决策，新概念进 **GLOSSARY**。

## 2. 目标与非目标

**目标**

- 不再因数据故障丢持仓、误卖、丢峰值。
- 每本账只有一个写者；旧账可迁移。
- 风控数值只有一个来源，文档与代码一致。
- 无法证明安全时不开新仓，且原因可查。
- 回测对外数字可复现、带口径元数据。

**非目标（Out of scope）**

- 换仓 20% 阈值、衰退期禁开仓、CPI 五档统一、TradingAgents 真辩论（见 ADR-0008）。
- 数据源历史复权质量、退市股全量补池、ETF 再平衡成本。
- 飞书日报推送（需求方明确暂缓）。

## 3. 方案总览

### 3.1 分四步落地

```
Step 1 止血 ──► Step 2 对齐 ──► Step 3 fail-closed ──► Step 4 回测可信度
(数据不丢)      (口径唯一)        (故障不开仓)          (数字可复现)
```

### 3.2 账本拓扑（改造后）

```
strategy_states.json          (三策略内部状态, TradingEngine 独占)
        │ aggregate
        ▼
shadow_account.json           (主账, run_trading / trading.bridge 独占写, owner=run_trading)
shadow_strategy4.json         (策略四账, output.shadow_account 独占写, owner=strategy4)
        ▲
        │ 一次性迁移（旧 shadow_account 无 owner 且有数据时）
```

读取方约定：

| 读取方 | 读哪本 |
|--------|--------|
| Dashboard 总览 / 三策略 | `shadow_account.json` |
| run_daily / 策略四 / 事件影子快照 | `shadow_strategy4.json` / `shadow_account.json`（快照读主账） |
| 价格告警 / 实时价格 | 两本都读 |

### 3.3 风控门（BUY 路径）

```
事件影子 ──缺失/非当天/异常──────────────┐
事件等级 high/extreme ──────────────────┤
数据源自检 CRITICAL 或异常 ─────────────┼──► 禁用 BUY（SELL 不受影响）
因子覆盖率 <50% 或不可用 ────────────────┤
宏观引擎异常 → 仓位乘数 0.4 + 告警 ──────┤
宏观双门红灯 / strategy_switch=off ──────┘
                                            │
                                            ▼
                         trading_signals.json.risk_gates 记录全部原因
```

### 3.4 四档 Trailing（单一函数 `trailing_stop_threshold`）

| 条件 | 阈值 | 标签 |
|------|------|------|
| 持仓 < 10 天 | 成本价 -8% 硬止损 | — |
| 浮盈 ≥30% | 峰值 -12% | T3 |
| 浮盈 10~30% | 峰值 -15% | T2 |
| 其余 | 峰值 -20% | T1 |

`hold_days()` 日期缺失返回 `None` → 按已满 10 天走 trailing（不放宽）。

### 3.5 回测口径

```
--from/--to ──► 按真实交易日裁剪 close/date ──► 默认时点评分 ──► 策略四扣成本
                                                              │
                   meta.json（actual_date_range/scoring_mode/  │
                   survivorship_bias/cost_model）◄──────────────┘
IC 快照时间戳 = 收益实现日（不是评分日）
```

## 4. 关键决策与取舍

| 决策 | 选择 | 代价 | ADR |
|------|------|------|-----|
| 账本收权 | 拆文件 + 迁移 | 读取方要分清账本 | 0004 |
| 丢持仓 | 保留并用建仓价兜底 | 当日风控偏保守 | 0002 |
| 丢峰值 | 聚合保留并取大 | schema 增字段 | 0003 |
| 参数来源 | `config` 单一来源 | 改行为需同步文档 | 0005 |
| 故障策略 | 严格 fail-closed | 可能错过行情 | 0006 |
| 回测默认 | 时点 + 成本 | 慢 10x、数字变差 | 0007 |

## 5. 数据迁移

1. 首次调用 `output.shadow_account.load_shadow()`：
   - 无 `shadow_strategy4.json`；
   - 有 `shadow_account.json`；
   - 其 `owner != "run_trading"` 且含 `positions`/`history`；
   → 复制为 `shadow_strategy4.json`，写 `migrated_from`/`migrated_at`。
2. 旧文件**不删除**，继续作为主账使用。
3. 迁移只发生一次；新账本存在即跳过。
4. 注意：`trading/bridge.py` 导出的主账已补 `owner=run_trading`，不会被误迁移。

## 6. 验证计划

### 6.1 本地离线（已执行）

| 项 | 结果 |
|----|------|
| 缺评分不误卖 | 通过 |
| 7 持仓 + 5 候选 → 只买 1 只 | 通过 |
| SilverQuant 固定槽位 3%/10% | 通过 |
| T3/T2/T1 阈值、持仓 <10 天禁用 trailing | 通过 |
| `shadow_account` 迁移 / 不误迁移主账 / 不清空持仓 | 通过 |
| 回测区间裁剪 | 通过 |
| 策略四成本扣减（成本版净值更低） | 通过 |
| IC 以收益实现日入库 | 通过 |
| 回测 `meta.json` 旁挂 | 通过 |

> 本机缺 `baostock`/`pytest`，`engine.trading_engine` 无法集成运行，只做了 `py_compile` 与纯函数断言。

### 6.2 部署机（待执行）

```bash
# 1) 全链路跑一次
python scripts/run_trading.py
python scripts/run_daily.py
python scripts/daily_factor_scan.py

# 2) 核对风控门
python -c "import json;print(json.load(open('data/trading_signals.json'))['risk_gates'])"

# 3) 核对账本属主
python -c "import json;print(json.load(open('data/shadow_account.json'))['owner'])"
python -c "import json;print(json.load(open('data/shadow_strategy4.json'))['owner'])"

# 4) 重跑回测（会较慢）
python scripts/run_backtest.py faceji --from 2020-01-01 --to 2024-12-31
cat data/backtest/bt_*.meta.json
```

## 7. 回滚

- 代码基线：git `eb2128f`（437 files，克隆时的快照）。
- 文档：本目录与 `docs/adr/` 为新增，删除即回滚。
- 数据：
  - 旧 `shadow_account.json` 从未删除；
  - 如需恢复旧账本行为，把 `shadow_strategy4.json` 复制回 `shadow_account.json`；
  - 回测 `*.meta.json` 可直接删除。
- 回滚顺序建议：先停 cron → 回滚代码 → 核对账本 → 再启 cron。

## 8. 后续路线

见 [ADR-0008](../adr/ADR-0008-暂缓项与后续路线.md)。启动任何暂缓项前必须新增 ADR。
