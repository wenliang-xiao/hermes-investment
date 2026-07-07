# Hermes Investment 架构深度评审报告

> **评审日期**: 2026-07-07
> **评审范围**: 全项目代码（入口层 / 数据层 / 因子层 / 策略层 / 回测层 / 输出层 / 辅助模块）
> **评审方法**: 6 个 explore agent 并行代码扫描 + 2 个 librarian agent 业界调研，所有结论均有代码行号佐证
> **评审人**: Sisyphus (OhMyOpenCode)

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [项目全景](#2-项目全景)
3. [架构分层评审](#3-架构分层评审)
   - 3.1 [入口层与配置层](#31-入口层与配置层)
   - 3.2 [数据层](#32-数据层)
   - 3.3 [因子层](#33-因子层)
   - 3.4 [策略层与交易引擎](#34-策略层与交易引擎)
   - 3.5 [回测层](#35-回测层)
   - 3.6 [输出层与辅助模块](#36-输出层与辅助模块)
4. [已知 Bug 与风险清单](#4-已知-bug-与风险清单)
5. [业界开源系统对比](#5-业界开源系统对比)
6. [生产级差距分析](#6-生产级差距分析)
7. [重构建议](#7-重构建议)
8. [结论](#8-结论)

---

## 1. 执行摘要

Hermes Investment 是一个**个人级量化投资辅助系统**，覆盖 A 股 / 港股 / 美股 / ETF / 期货多资产，以"面基播客投资体系"为策略哲学核心，通过因子扫描 → 策略决策 → 模拟盘执行 → 飞书日报推送的管线运作。

**项目规模**: ~50 个 Python 模块，核心代码 ~15,000 行（不含配置数据），config.py 1,035 行 + domain/__init__.py 881 行构成庞大的配置层。

**借鉴谱系**: Hermes 不是从零造的。技术架构层借了 **hl-quant**（纯函数策略 + 固定评估器 + HL 循环）、**xalpha**（@cachedio 数据路由 + 缓存）、**OSkhQuant**（7 面板指标体系）、**Vibe-Trading**（IC/IR 因子分层验证方法论）；方法层借了 **OpenSpec**（切片交付）、**Superpowers**（三步工作流）、**Karpathy**（编码纪律）；策略层借了 **段永平**（不为清单）、**凯利**（仓位管理）、**面基播客**（产业认知）。Bloomberg/QuantConnect/Wind 是基准坐标——不是用来抄的，是用来知道目标在哪的。（详见 [2.4 参考来源与借鉴谱系](#24-参考来源与借鉴谱系)）

### 核心评价

| 维度 | 评级 | 一句话评价 |
|------|------|-----------|
| **策略哲学完整性** | ⭐⭐⭐⭐ | 面基播客 154 期知识体系被深度结构化（concept_engine 881 行），投资逻辑自洽 |
| **功能覆盖广度** | ⭐⭐⭐⭐ | 数据/因子/策略/回测/模拟盘/Dashboard/新闻/宏观/产业链全覆盖，远超个人项目平均水平 |
| **借鉴谱系清晰度** | ⭐⭐⭐⭐ | hl-quant/xalpha/OSkhQuant/Vibe-Trading 架构理念直接落地，方法论借鉴有据可查 |
| **代码架构质量** | ⭐⭐ | 多处重复实现（4-5 份策略副本）、配置双重维护已漂移、无抽象基类、无类型安全边界 |
| **工程质量** | ⭐⭐ | 回测逻辑零测试、Dashboard 无认证、无 CI/CD、无监控告警、凭据硬编码 |
| **生产级就绪度** | ⭐ | 无 point-in-time 数据、无幸存者偏差防护（代码写了未启用）、无执行成本模型接入、无事件溯源 |
| **可维护性** | ⭐⭐ | 修改一处策略需同步 4-5 处、两套评分引擎阈值不兼容、3 个回测版本未收敛 |

### 一句话总结

> **这是一个投资思考深度远超工程实现质量的系统**。策略哲学和领域建模是亮点，借鉴谱系清晰且方向正确（hl-quant 纯函数策略、xalpha 数据路由、Vibe-Trading IC/IR 分层），但代码架构已逼近可维护性极限——问题不是设计方向错误，而是**副本漂移导致正确的架构理念被 4-5 处 inline 实现覆盖**。亟需收敛而非重写。

---

## 2. 项目全景

### 2.1 项目定位

Hermes 是一个**研究 + 辅助决策系统**，而非自动交易系统。核心价值链：

```
面基播客知识体系 → 因子扫描 → 三策略决策 → 模拟盘执行 → 飞书日报 → 人工决策
                      ↓
               Dashboard 实时展示
```

系统不直接下单，而是通过日报和 Dashboard 为人工投资决策提供数据支撑。

### 2.2 模块全景图

```
┌──────────────────────────────────────────────────────────────────┐
│                         入口层                                    │
│  run_daily.py(1005行)  run_weekly.py(358行)  run_factor_daily.py │
│  run_trading.py  run_backtest.py  run_report_v10.py(废弃)        │
├──────────────────────────────────────────────────────────────────┤
│                         配置层                                    │
│  config.py(1035行) ←→ domain/__init__.py(881行)  [双重维护已漂移] │
│  core/secrets.py(19行)                                           │
├──────────────────────────────────────────────────────────────────┤
│                         数据层                                    │
│  data_router.py(统一路由)  data_layer.py(A股baostock+EM)         │
│  data_source_layer.py(新多源层)  yf_data_layer.py(港美股)        │
│  tushare_layer.py(宏观/北向)  global_data.py(全球市场)           │
│  sources/{akshare,baostock,yahoo}_source.py                     │
│  mcp_akshare_server.py(MCP Server, 11个工具)                    │
├──────────────────────────────────────────────────────────────────┤
│                         因子层                                    │
│  factor_scanner.py v3.1 [1,10] ← 6因子固定区间线性插值           │
│  factor_engine.py v4.0 [0,1]   ← 19子因子→7风格 截面分位数      │
│  factor_quality.py(IC/IR/衰减)  score_history.py  init_ic_data.py│
├──────────────────────────────────────────────────────────────────┤
│                         策略层                                    │
│  strategies/{base,faceji,silverquant,tradingagents}.py (纯函数)  │
│  analysis/trading_engine.py (模拟盘, 600行)                      │
│  analysis/strategy_comparison.py (独立副本, 已漂移)              │
│  analysis/backtest_v2.py (独立副本, 已漂移)                      │
│  analysis/{stop_list,allocation_strategies,multi_asset_engine}.py│
├──────────────────────────────────────────────────────────────────┤
│                         回测层                                    │
│  backtest.py v2.0(1682行)  backtest_v2.py(357行)                │
│  backtest_all_strategies.py(645行)  etf_backtest.py(264行)       │
│  evaluator_fixed.py(879行, ADR-001固定评估器)                    │
│  cost_model.py(166行, 独立但未被trading_engine引入)              │
│  backtest_storage.py(92行, JSON持久化)                           │
├──────────────────────────────────────────────────────────────────┤
│                         输出层                                    │
│  scripts/portfolio_server.py (FastAPI Dashboard :8686, 无认证)   │
│  output/report_v6.py (~1400行, 日报生成+飞书写入)                │
│  output/{concept_engine,fund_tracker,shadow_account,strategy4}.py│
│  scripts/{push_daily_to_feishu,push_report_to_group}.py          │
├──────────────────────────────────────────────────────────────────┤
│                         辅助分析                                  │
│  analysis/{news_engine,macro_engine,chain_scanner}.py            │
│  analysis/{delta_tracker,behavior,portfolio_builder}.py          │
│  analysis/{deep_research,research_report,knowledge_ref}.py       │
└──────────────────────────────────────────────────────────────────┘
```

### 2.3 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3 (无类型注解强制) |
| 数据源 | baostock / AKShare / yfinance / Tushare / 东方财富 DataCenter |
| Web | FastAPI + uvicorn (Dashboard) |
| 前端 | 原生 HTML + Chart.js CDN (无构建工具) |
| LLM | GLM-4-Flash (新闻摘要/异动分析) |
| 推送 | 飞书开放平台 API |
| 缓存 | pickle / JSON 文件 (无数据库) |
| 调度 | ECS Cron YAML |
| 测试 | pytest (仅覆盖存储模块和部分因子) |

### 2.4 参考来源与借鉴谱系

> **重要说明**: Hermes 不是从零造的。在评审"为什么这么做"之前，必须先厘清 Hermes 站在谁的肩膀上。以下是在整个开发过程中深度调研、借鉴、讨论过的全部项目和原则。

#### 2.4.1 直接借鉴的 GitHub 开源项目

| 项目 | 借鉴了什么 | 落地位置 |
|------|-----------|---------|
| **hl-quant** | ① 纯函数策略层（`strategies/` 零IO）② 固定评估器（`evaluator_fixed.py`，同一组19只标的永远评）③ HL 循环（Probe→Diagnose→Propose→Patch→Evaluate→Replay→Decide→Compress）④ Walk-Forward 多周期验证 | `strategies/faceji.py`, `strategies/silverquant.py`, `strategies/tradingagents.py`, `evaluator_fixed.py`, `data/hl_runs/` |
| **xalpha** | ① `@cachedio` 透明数据缓存装饰器（TTL 参数化 pickle 缓存）② 前缀路由数据源调度（`_detect_source` 自动识别代码来源） | `data/data_router.py` 的 `@cachedio` 和 `_detect_source()` |
| **OSkhQuant** | 绩效指标面板风格：Sharpe/Sortino/Alpha/Beta/连续盈亏/最大回撤/胜率，7 面板 Dashboard 布局 | `/api/metrics` 端点 + Dashboard 7面板设计 |
| **Vibe-Trading (HKUDS)** | ① Alpha 因子库架构哲学（452因子Zoo → 因子→风格→复合分层）② IC/IR 因子分层验证方法论 ③ 跨市场回测引擎思路（Composite→多策略并行）④ Shadow Account 行为诊断思路 | 启发了 `factor_engine.py` 的三层设计（19子因子→7风格→1复合）；影响了 IC 滚动权重 + James-Stein 收缩设计；启发了 `strategy_states.json` 历史记录 + 模拟盘追踪 |
| **OpenSpec** | 方法论层面：先写方案文档再动手、切片式交付（不一次性做大改）、TDD 三阶段（RED→GREEN→REFACTOR）、每片独立可验证 | 所有方案文档 `docs/plans/`、三个 workstream 拆分 |
| **Superpowers (SuperPower AI协同开发)** | 三步连推法（阻塞bug→工程基建→功能增量）、原子提交、每个切片独立可验证、修改前调研分析 | `three-workstream-execution` skill, 所有 P0/P1 执行流程 |
| **Karpathy 编码原则** | 编码前思考、简洁优先、精准修改、目标驱动执行 | `karpathy-guidelines` skill（全局 always 加载） |

**Vibe-Trading 的特殊说明**: 452 个 Alpha 因子全是加密期货因子（永续合约资金费率、订单簿失衡等），对 A 股/美股零意义，因此**没有直接移植因子**。Vibe-Trading 对 Hermes 的持久贡献是**因子验证方法论**（别只看 Alpha 数量，要看 IC/IR 分层筛选）和**回测架构思路**（Composite→多策略并行），这两个思想已融入 `factor_engine.py` 和 `backtest_storage.py`，但不是以直接 copy 代码的形式。

#### 2.4.2 基准级参考（拿来对比、知道差距在哪的）

| 项目/系统 | 对比维度 | 差距 |
|-----------|---------|------|
| **Bloomberg Terminal** | 条件单/一键执行/多屏联动/数据导出/新闻→情感→影响量化→实时推送 | Hermes 只有展示，没有操作和执行 |
| **QuantConnect** | 事件驱动架构 + 券商 API 集成 + 数据湖 + ML 模型 | 架构层面差异，2-3 年工程差距 |
| **Wind（万得）** | 中国金融终端标准：实时行情+深度研报+宏观数据+行业数据库 | 数据来源分散，缺少一站式深度数据 |
| **LDS 全天候** | 全天候组合（12.5%回报/-15.2%回撤/0.85 Sharpe） | 唯一的可信回测基准 |

#### 2.4.3 策略层借鉴的方法论

| 方法论 | 来源 | 使用位置 |
|--------|------|---------|
| **段永平「不为清单」** | 段永平投资哲学 | `stop_list.py` 10 条规则（ROE/负债率/毛利率/护城河/管理层/现金流/能力圈等），三层选股漏斗的第二层 |
| **凯利公式** (Kelly Criterion) | 信息论→赌博→仓位管理 | 三策略的 `_kelly_size()` 函数：Kelly 动态仓位上限 8-12% |
| **James-Stein 收缩 / 贝叶斯收缩** | 统计学 | `factor_engine.py` IC 权重计算，样本量不足时向等权收缩 |
| **Nick 四问** | Nick Sleep 投资框架 | `deep_research.py` 8 维框架维度 4 |
| **DCF 估值** | 经典价值投资 | `deep_research.py` 维度 3（当前是占位符 `price×1.1`） |
| **六层漏斗审计法** | Hermes 原创 | 系统审计方法论：宏观气候→资产配置→多因子引擎→找票→风控→纪律 |
| **面基播客知识体系** | 154 期播客内容 | 12 主题 13 篇飞书文档，产业链引用（当前未接入分析流程） |
| **银城量化 (SilverQuant)** | 用户带来的策略 | `strategies/silverquant.py`，固定槽位 ¥30K，全自动 |
| **交易代理 (TradingAgents)** | 用户带来的策略 | `strategies/tradingagents.py`，辩论分≥5.5 建仓，多 agent 辩论 |

#### 2.4.4 工程原则（自创并反复验证的）

| 原则 | 内容 | 来源 |
|------|------|------|
| **只叠加不拆除** | 新模块独立于旧生产管线，不修改现有代码 | OpenSpec 方法 |
| **原子写入** | tmpfile+rename 模式，防止写入中断留残篇 | `utils/atomic_io.py` |
| **4 阶段防残篇日报** | Phase1收集→Phase2分析→Phase3创建文档→Phase4推送，要么全好要么全不推 | `run_report_v10.py` |
| **数据缺失时 NOOP** | price=0 时不做任何交易决策，而非 panic sell | P0-EXTRA commit 教训 |
| **TDD 硬性要求** | 任何修复/新功能必须先写测试 RED→GREEN→全量回归 | 整个开发流程 |
| **Commit 即 Push** | GitHub 是唯一源码真相，修改后立即推送 | 用户硬性要求 |
| **验证前置** | curl 验证/API 端点确认后才 claim 完成，不靠"刷新看看" | 用户硬性要求 |
| **3 层防护** | 源头切断→策略加固→执行守卫，每层独立防止 price=0 事件 | P0-EXTRA |

#### 2.4.5 借鉴谱系对架构评审的影响

理解借鉴谱系后，评审的"为什么这么做"分析需要调整：

1. **纯函数策略层不是"缺少抽象基类"**，而是**有意借鉴 hl-quant 的零IO设计哲学**——策略纯函数化以便回测和独立调用。问题不是设计方向错误，而是**副本漂移导致纯函数被 4-5 处 inline 实现覆盖**。

2. **@cachedio 缓存不是"6层缓存不协调"**，而是**xalpha 的透明缓存装饰器被正确引入**——问题在于后续模块（data_source_layer、global_data）各自新增了独立缓存层，未统一到 @cachedio 模式。

3. **固定评估器不是"版本管理混乱"**，而是**hl-quant 的 ADR-001 核心设计**——禁止为提分而改评估器参数。问题在于 `backtest_v2.py` 和 `backtest_all_strategies.py` 是 hl-quant 引入前的遗留，未按 ADR-001 收敛。

4. **IC/IR 因子分层不是"硬编码不可扩展"**，而是**Vibe-Trading 的因子验证方法论落地**——用 IC/IR 筛选有效因子而非堆砌因子数量。问题在于因子定义硬编码而非 DSL，这是**下一步演进方向**而非设计缺陷。

5. **Shadow Account 不是"模拟盘无审计溯源"**，而是**Vibe-Trading 的行为诊断思路部分落地**——`strategy_states.json` + `behavior.py` 已实现，完整 Shadow 诊断管线未实现是**范围决策**而非遗漏。

---

## 3. 架构分层评审

### 3.1 入口层与配置层

#### 3.1.1 三入口架构

项目有三个核心入口，各自独立、共享代码有限：

| 入口 | 行数 | 评分引擎 | 策略路径 | 输出 |
|------|------|---------|---------|------|
| `run_daily.py` | 1005 | `FactorScannerCompatV4` (v4兼容层) | `shadow_account.py` + `report_v6.py` (不经过 strategies/) | 飞书文档 + JSON |
| `run_weekly.py` | 358 | `FactorScannerCompatV4` | 同上 | 飞书文档 + JSON |
| `run_factor_daily.py` | 123 | `FactorEngine` v4.0 原生 | 无策略执行 | JSON |

**关键发现**：`run_daily.py`（日报主管线）**不使用 `strategies/` 纯函数，也不使用 `trading_engine.py`**，而是走独立的 `shadow_account.py` 管线。这意味着日报的模拟盘与 Dashboard 的模拟盘是**两套独立实现**。

**sys.path 不一致**（可移植性问题）：
- `run_daily.py` L15: `sys.path.insert(0, '/home/admin/.hermes')` — 绝对路径，开发环境不可运行
- `run_trading.py` L12: `sys.path.insert(0, os.path.join(_PROJECT_DIR, ".."))` — 相对路径
- 不同入口使用不同策略，缺乏统一

#### 3.1.2 配置层双重维护

**`config.py`（1,035 行）与 `domain/__init__.py`（881 行）存在约 850 行完全重复的配置数据**，且已发生漂移：

| 配置项 | config.py | domain/__init__.py | 差异 |
|--------|-----------|---------------------|------|
| `CPI_STRATEGY_MAP` | L61-69 (9键) | L22-28 (7键) | domain 缺失 `cpi_below1_improving`, `cpi_2_to_3_accelerating` |
| `INDUSTRY_CHAINS` | L542-940 (15条) | L464-804 (14条) | domain 缺失"物理AI链" |
| `CHAIN_ECONOMICS_WEIGHTS` | L44-49 | ❌ 无 | domain 完全缺失 |
| `PROFIT_POOL_SCORES` | L51-58 | ❌ 无 | domain 完全缺失 |
| `get_domestic_sub_score()` | L1000-1012 | ❌ 无 | domain 完全缺失 |

**两个文件都在被不同入口使用**（非"一个废弃一个在用"）：
- `run_daily.py` L61 用 `config.py`，L91/L265 用 `domain`
- `run_trading.py` L19 用 `config.py`，L20 用 `domain`

**WATCHLIST 重复条目**：`config.py` 中 GLD（L352/404）、HG=F（L354/406）、CL=F（L355/407）各出现两次。

#### 3.1.3 凭据管理

| 凭据 | 位置 | 管理方式 | 合规性 |
|------|------|---------|--------|
| `FEISHU_TOOL` 路径 | `config.py` L19 | 硬编码 `"/home/admin/.hermes/..."` | ❌ 不可移植 |
| `TUSHARE_TOKEN` | `config.py` L16 / `secrets.py` L14 | 环境变量回退空字符串 | ✅ |
| 飞书凭据 | `config.py` L20-22 / `secrets.py` L16-19 | 环境变量 | ✅ |
| 飞书 App ID/Secret | `report_v6.py` L67-68 | `os.environ["FEISHU_APP_ID"]` (无回退，缺失则 KeyError) | ✅ |
| 飞书凭据 | `run_report_v10.py` L20-26 | 硬编码 + 环境变量回退（双重来源） | ⚠️ |

`core/secrets.py`（19 行）与 `config.py` 独立定义相同的环境变量名，是重复。`run_daily.py` L17-21 和 `run_weekly.py` L13-17 显式加载 `.env` 文件，但 `run_factor_daily.py`、`run_trading.py`、`run_backtest.py` **没有** `.env` 加载逻辑。

#### 3.1.4 Cron 调度

三个 cron 包装脚本不同步：
- `run_cron_daily.sh`（3 行）：无超时、无重试、无日志捕获
- `run_daily_cron.sh`（4 行）：多了 `echo "EXIT_CODE=$?"` 但仍无超时
- `run_daily_wrapper.sh`（15 行）：`nohup timeout 600` + 轮询，最完整但**未被任何文档引用**

根据 `HERMES_CRON_CONFIG.md`，ECS 直接用 YAML `command` 字段调用 `python3 scripts/run_daily.py`。

**调度健壮性**：
- ❌ 无失败重试
- ⚠️ 直接 cron 无超时保护
- ⚠️ 日志仅写 `/tmp/report_daily_log.txt`，cron 自身 stdout 未捕获
- ❌ 无健康检查、无成功/失败通知
- ⚠️ 幂等性部分（扫描未完成删除文档 exit(1)，但模拟盘操作非幂等）

#### 3.1.5 入口层评价

| 维度 | 评价 |
|------|------|
| 功能完整性 | ✅ 日报/周报/因子日扫三入口覆盖核心场景 |
| 一致性 | ❌ sys.path 策略不统一、.env 加载不统一、策略管线不统一 |
| 可移植性 | ❌ run_daily.py 硬编码 `/home/admin/.hermes` 绝对路径 |
| 健壮性 | ❌ 无重试、无监控、无告警 |
| 可维护性 | ❌ config.py + domain 双重维护已漂移 |

---

### 3.2 数据层

#### 3.2.1 数据源矩阵

| 资产类型 | 主力源 | 备源 | 限流 |
|---------|--------|------|------|
| A股日线 | baostock | AKShare (ETF) | 0.3s |
| A股财务 | 东方财富 DataCenter API | baostock → Tushare | 无限频 |
| A股实时 | 腾讯财经 API | 新浪 API | — |
| 港股/美股 | yfinance | 无 | 0.5s |
| 期货 | AKShare | 无 | 1.0s |
| 宏观 | AKShare | 本地缓存 | — |
| 北向资金 | Tushare (需2000积分) | AKShare | — |

**无数据源交叉验证**（A股东财+新浪偏差>0.5%告警除外），港美股无 fallback。

#### 3.2.2 缓存体系

项目有 **6 层独立缓存**，策略各异、互不协调：

| 缓存 | 格式 | TTL | 位置 |
|------|------|-----|------|
| data_router cachedio | pickle | 720h (30天) | data/cache/*.pkl |
| data_source_layer | JSON | 1h-7d | data/cache/*.json |
| global_data | JSON | 2h | data/global_market_cache.json |
| 宏观缓存 | JSON | 24h | data/macro_raw_cache.json |
| 进程缓存 | 内存 dict | 进程生命周期 | data_layer._FIN_CACHE |
| 实时缓存 | 内存 dict | 60s | akshare_source._rt_cache |

**审计发现**（`data_pipeline_audit_report.md`）：
- 🔴 `macro_raw_cache.json` 42 天未更新（严重过期）
- 🔴 `news_cache.json` 42 天未更新
- 🔴 `global_market_cache.json` 44 天未更新
- ⚠️ 315 个 pickle 文件（5.26MB），无 LRU、无大小限制、无手动失效
- ⚠️ `baostock_source.py` L67 `end_date="20260625"` 硬编码已过期

#### 3.2.3 多资产路由

`data_router.py` L74-105 基于代码前缀分发：

```
.HK 结尾      → yfinance
^ 开头        → yfinance
CL=/GC=/HG=   → akshare_futures (仅3硬编码品种)
6位数字       → baostock
预定义US列表   → yfinance
其他          → yfinance (兜底)
```

**问题**：
- 期货仅支持 3 个硬编码品种，不可扩展
- ETF 路由 `51/15/16/159` 前缀遗漏 `56/58` 等代码
- 路由规则散落在代码中，无配置化

#### 3.2.4 数据质量保证

| 维度 | 实现 | 评价 |
|------|------|------|
| 缺失值 | `float(r[7]) if r[7] and r[7] != "" else None` | ⚠️ 静默跳过，无告警 |
| PE 上限 | `0 < pe < 2000` (data_layer L469) | ✅ |
| 价格合理性 | `_SNAPSHOT_SANITY` 硬编码区间 (yf_data_layer L417-441) | ✅ |
| 汇率方向 | `_FX_DIRECTION_CHECK` (data_source_layer L543-547) | ✅ |
| ST/退市过滤 | `~df["name"].str.contains("ST\|退\|B股")` | ✅ |
| 复权 | baostock `adjustflag="2"` 前复权; yfinance 未显式复权 | ⚠️ 不一致 |
| 交易日对齐 | **无显式处理** | ❌ 跨资产对比存在隐式不一致 |
| Point-in-time | **无** | ❌ 严重缺失 |

#### 3.2.5 MCP Server

`mcp_akshare_server.py` 基于 FastMCP，暴露 11 个工具（搜索/行情/历史/财务/行业/因子评分/技术指标），支持 stdio + SSE 双模式。这是 Hermes 系统的 AI 接口层，供 LLM Agent 通过 MCP 协议调用投资数据工具。

#### 3.2.6 数据层评价

| 维度 | 评价 |
|------|------|
| 数据源覆盖 | ✅ 多源多资产，覆盖面广 |
| 缓存设计 | ❌ 6 层缓存不协调，无统一失效机制，多份严重过期 |
| 数据质量 | ⚠️ 有基本校验但无 point-in-time、无交易日对齐 |
| 可扩展性 | ❌ 路由规则硬编码、期货仅 3 品种 |
| 审计状态 | 🔴 审计报告评分 5.5/10，新闻管线断裂 |

---

### 3.3 因子层

#### 3.3.1 两套评分引擎并存

| 维度 | v3.1 (factor_scanner.py) | v4.0 (factor_engine.py) |
|------|-------------------------|-------------------------|
| 状态 | **已退役**（文件头标注） | **当前主力** |
| 评分范围 | [1, 10] | [0, 1] |
| 因子数 | 6 风格因子 | 19 子因子 → 7 风格 + 1 风险 |
| 归一化 | 固定区间线性插值（伪截面） | scipy rankdata 截面百分位（真截面） |
| 权重来源 | `config.FACTOR_WEIGHTS` 宏观状态映射 | `ICWeightSystem` 滚动IC/IR + 贝叶斯收缩 |
| 行业中性化 | 无 | 按产业链分组截面标准化 |
| 使用者 | run_daily.py (通过 FactorScannerCompatV4 兼容层) | run_factor_daily.py 原生 |

**兼容层的问题**：`run_daily.py` 使用的 `FactorScannerCompatV4` 调用的是 `score_symbol()`（单标的固定映射版），而非 `score_batch()`（真截面分位版）。意味着**日报用的其实是固定映射版的 v4.0，不是真正的截面分位**。

#### 3.3.2 v3.1 的 6 因子

| 因子 | 子成分 | 参考范围（硬编码） |
|------|--------|-------------------|
| 质量 | ROE(50%) + 营收增速(25%) + 现金流(25%) | ROE: (0,30), 营收: (0,50), 现金流: (0,5) |
| 价值 | PE百分位(60%) + PB(40%) | PE: (10,40)反转, PB: (0.8,5)反转 |
| 成长 | 营收增速(40%) + 净利增速(60%) | 营收: (0,60), 净利: (0,80) |
| 低波 | 20日年化波动率 | (15,60)反转 |
| 红利 | 股息率 | (0,5) |
| 动量 | 20日(40%)+60日(35%)+120日(25%) | 20d:(-20,30), 60d:(-30,50), 120d:(-40,80) |

#### 3.3.3 v4.0 的 19 子因子 → 7 风格

三层架构：
```
Layer 3 (数据映射): SUB_FACTOR_DEFS — 原始数据 → 子因子原始值
Layer 2 (标准化):   standardize_cross_section() — 原始值 → 截面分位数 [0,1]
Layer 1 (风格聚合): aggregate_style() → IC加权 → 综合分
```

**ICWeightSystem 三层权重融合**：
1. **IC/IR 信噪比**: 滚动6个月，半衰期 λ=0.35，`weight = max(0, IC_IR × mean(IC))`
2. **宏观条件调整**: `MACRO_WEIGHT_ADJUST` 矩阵（复苏/扩张/过热/衰退 × 8风格）
3. **贝叶斯收缩**: `w_final = (1-λ) × w_conditional + λ × w_unconditional`，shrink_target=3.0

最终融合：`final = 70% × rolling_IC_base + 30% × conditional_adjusted`

#### 3.3.4 因子定义全部硬编码

| 维度 | 状态 |
|------|------|
| 子因子定义 | ❌ 硬编码 `SUB_FACTOR_DEFS` dict |
| 风格映射 | ❌ 硬编码 `STYLE_FACTORS` dict |
| 参考范围 | ❌ 硬编码 `ref_ranges` dict |
| 宏观权重 | ❌ 硬编码 `MACRO_WEIGHT_ADJUST` dict |
| 扩展机制 | ❌ 无插件机制、无注册表模式 |

新增因子需修改 5 处源代码，不支持配置化扩展。

#### 3.3.5 因子质量评估

`factor_quality.py` 实现 IC/IR/衰减曲线/有效性判断：
- IC 阈值：>0.05 有效，>0.02 弱，<0.02 失效
- 衰减曲线：1/3/5/10/20 日 horizon
- 存储：`.hermes/factor_history.json`，最多 90 天

**关键问题**：`factor_quality.py` 的 `save_snapshot()` 读取的是 **v3.1 格式字段**（`s.get("score")`, `s.get("factors")`），而日常数据已切换到 v4.0。这意味着 **IC 统计在日常运行时是空的**。

#### 3.3.6 已知 Bug 纠正

AGENTS.md 记载 `data_layer.py L276,327-331,354,364` 有 `abs()` 抹消正负号 bug。**经代码核实，这四处实际无 `abs()` 调用**。真正的 `abs()` bug 在 `factor_scanner.py`：

| 行号 | 代码 | 问题 |
|------|------|------|
| L60 | `ocps = min(abs(fin.get("每股经营现金流", 0) or 0), 10)` | 负现金流被抹为正数 |
| L75 | `pe = abs(pe) if pe and pe > 0 else None` | 条件已保证正值，abs() 冗余 |
| L76 | `pb = abs(pb) if pb and pb > 0 else None` | 同上 |
| L138 | `div = abs(fin.get("股息率", 0) or 0)` | 股息率不可能为负，冗余 |

L60 的 `abs(每股经营现金流)` 是真正的数据质量 bug：负现金流被抹为正数，导致质量因子评分虚假偏高。

#### 3.3.7 因子层评价

| 维度 | 评价 |
|------|------|
| 因子设计 | ⭐⭐⭐ 19 子因子覆盖 7 风格，含 IC 权重系统 |
| 截面标准化 | ⭐⭐⭐ v4.0 真截面分位 + 产业链中性化 |
| 扩展性 | ❌ 全硬编码，无插件机制 |
| 质量评估 | ⚠️ 有 IC/IR/衰减但数据源格式不匹配（v3.1 vs v4.0） |
| 市值中性化 | ❌ 两套引擎均无 |
| 财报季节性 | ❌ v4.0 直接取最新值，无 TTM 滚动、无报告滞后处理（仅回测重建有 45 天滞后） |

---

### 3.4 策略层与交易引擎

#### 3.4.1 策略抽象严重缺失

`strategies/base.py`（103 行）只有数据类（`Signal`/`PositionData`/三个 `Config`），**没有 `Strategy` 抽象基类**。三策略的 `decide()` 签名完全靠约定一致，无编译器/类型系统保障。

#### 3.4.2 三策略概览

| 策略 | 文件 | 仓位算法 | 清仓层数 | MA 建仓过滤 |
|------|------|---------|---------|-------------|
| 面基 (faceji) | faceji.py (133行) | Kelly 半凯利 (上限8%) | 4层 (硬止损/回撤止盈/评分下滑/MA死叉) | ✅ (L62, **有bug**) |
| SilverQuant | silverquant.py (99行) | 固定¥30K/槽位 (3%) | 4层 (硬止损/回撤止盈/MA死叉/评分下滑) | ❌ |
| TradingAgents | tradingagents.py (123行) | Kelly 半凯利 (上限12%) | 3层 (辩论分强卖/硬止损/弱持仓) | ❌ |

**TradingAgents 不是 Multi-Agent**。名字带 "agents" 但实际是数学加权函数（bull/bear/neutral 三个公式 + 裁决逻辑），没有独立 agent 进程/线程/LLM 调用。

#### 3.4.3 L62 MA 方向 bug（已确认）

```python
# faceji.py L62（当前版，错误）
if ma60d >= ma20d and score < cfg.ma_trend_boost_threshold:
    continue  # 在上升趋势跳过建仓！

# backtest_v2.py L104（正确参考）
if (te.get("ma60_dev",0) or 0) <= (te.get("ma20_dev",0) or 0) and sc < 5.5:
    continue  # 在下降趋势才跳过
```

`maXX_dev = (price - MA_XX) / MA_XX * 100`（价格对均线的偏离百分比）。

| 场景 | ma20_dev | ma60_dev | faceji 行为 | 正确行为 |
|------|----------|----------|------------|---------|
| 上升趋势 (Price=110, MA20=100, MA60=90) | +10% | +22.2% | **跳过建仓 ❌** | 不应跳过 |
| 下降趋势 (Price=90, MA20=100, MA60=110) | -10% | -18.2% | **不跳过 ❌** | 应跳过 |

**不等式方向完全反了**。影响：面基策略在建仓环节**在上升趋势中错误跳过好标的，在下降趋势中错误建仓**。

#### 3.4.4 4-5 处独立策略逻辑副本

AGENTS.md 说"修改策略逻辑时两处都要同步"，但实际有 **4-5 处**：

| # | 位置 | 类型 | 用户 | 与 strategies/ 一致性 |
|---|------|------|------|----------------------|
| 1 | `strategies/faceji.py` | 纯函数 | trading_engine.py | — (源头) |
| 2 | `analysis/trading_engine.py` | 委托调用 | Dashboard | ✅ 委托 #1 |
| 3 | `analysis/strategy_comparison.py` L120-431 | **独立 inline 副本** | Dashboard 三方对比 | ❌ 仓位逻辑(固定¥30K)、清仓逻辑(2层)均不同 |
| 4 | `analysis/backtest_v2.py` L95-129 | **独立 inline 副本** | 回测 v2 | ❌ 同 #3 |
| 5 | `scripts/run_daily.py` | 完全独立管线 | 日报 | 使用 `shadow_account.py`，**不引用 strategies/** |

**已确认漂移**：`strategy_comparison.py` 和 `backtest_v2.py` 的 MA 过滤方向是正确的（`ma60d <= ma20d`），但 `strategies/faceji.py` 是反向的。这意味着**回测结果与实际模拟盘结果天然不一致**。

#### 3.4.5 模拟盘不支持交易成本

`trading_engine.py` 中 `grep "slippage|commission|fee|涨停|跌停"` → **无匹配**。`execute_buy()` (L182-203) 直接用 `signal.price` 成交（`cost = price * qty`），无任何成本加成。

独立的 `cost_model.py`（166 行）已实现完整的 A 股费率模型（佣金万1.5 + 印花税千1 + 过户费万0.2 + 5 级滑点），但**未被 `trading_engine.py` 引入**。

#### 3.4.6 周频过滤双路径不一致

模拟盘执行（L476-496）和建议信号路径（L498-503）有独立的周频过滤：
- **BUY**: 模拟盘通过 `can_trade()` 检查 + `record_trade()` 记录
- **SELL**: 模拟盘**完全绕过** TradeCalendar（不 `can_trade()`、不 `record_trade()`）
- **建议信号**: 独立做一次 `_filter_by_weekly_rule()`

后果：SELL 不计入每周交易次数上限，周频预算被暗中超过；两条路径的周频状态不同步。

#### 3.4.7 没有策略组合层

多策略融合仅在 `TradingEngine._resolve_conflicts()` (L403-444) 做信号级冲突仲裁（面基优先），无跨策略仓位分配/投票权重/融合逻辑。"三源融合"在 `create_v10_plan_doc.py` 中以计划存在但**未实现**。

#### 3.4.8 策略层评价

| 维度 | 评价 |
|------|------|
| 策略多样性 | ⭐⭐⭐ 三策略不同风控哲学 |
| 抽象质量 | ❌ 无 Strategy 基类、无事件驱动、无生命周期 |
| 代码一致性 | ❌ 4-5 处副本漂移严重 |
| 交易成本 | ❌ 模拟盘不支持，独立模型未接入 |
| 风控完整性 | ⚠️ 有止损/止盈但无 VaR/CVaR/压力测试 |
| 策略组合 | ❌ 无组合层，仅信号级仲裁 |

---

### 3.5 回测层

#### 3.5.1 三个 backtest 版本未收敛

| 版本 | 行数 | 特征 | 评价 |
|------|------|------|------|
| `backtest.py` v2.0 | 1682 | 四策略对比 + 滑点模型 + 基准修正 + 产业链动态选股 + 样本外验证 | 最全 |
| `backtest_v2.py` | 357 | 三方策略 + 内联策略实现 + 19只固定标的 + 无成本模型 | 应废弃 |
| `backtest_all_strategies.py` | 645 | 自带扫描器 + 内联策略实现 + 无成本模型 | 应废弃 |

`backtest_v2.py` 和 `backtest_all_strategies.py` 的策略逻辑与 `strategies/` 纯函数重复（审计评级 C，建议废弃），但废弃前需解决策略三处重复问题。

#### 3.5.2 evaluator_fixed.py — 固定评估器

**ADR-001 背景**：固定标尺，禁止为提分而修改评估器参数。`FIXED_SCORE_MAP` 预置 19 只核心 A 股的固定评分。

**评估指标**：Sortino（主评分）、年化收益、夏普、最大回撤、胜率、总收益、交易次数。不含卡玛比率、盈亏比、Calmar。

**Walk-Forward 支持**：`run_walk_forward()` (L471-694)，Train 252d + Test 63d，stride 63d，支持 DSR 统计检验。

#### 3.5.3 MACD bug 纠正

AGENTS.md 记载 `evaluator_fixed.py:L256`、`backtest_v2.py:L293`、`backtest_all_strategies:L539` 有 MACD 判定恒真 bug（`pmacd <= pe12-pe26` = `pmacd <= pmacd`）。

**经代码核实，这三处实际写的是 `pmacd <= psig`（或 `prev_macd <= prev_signal`），是正确的**。真正的 MACD 恒真 bug 在 `scripts/run_trading.py` L98：

```python
# run_trading.py L97-98 — 真正的 Bug
pmacd = pe12 - pe26                                          # L97
te["macd_signal"] = "🟢金叉" if macd > sig and pmacd <= pe12-pe26 else ...  # L98
# pmacd <= pe12-pe26 即 pmacd <= pmacd，恒为真
```

**AGENTS.md 的 bug 清单对三处回测文件的指控有误，真正的第 4 处在 run_trading.py:L98 未被记录。**

#### 3.5.4 幸存者偏差修正代码写了未启用

`backtest.py` 的 `_build_realistic_universe()` (L69-101) 定义了向回测池注入随机噪声股模拟非存活股票的函数，但**从未被调用**（审计确认）。`backtest_v2.py` 和 `evaluator_fixed.py` 无任何幸存者偏差修正。

#### 3.5.5 回测能力矩阵

| 功能 | 支持状态 |
|------|---------|
| 事件驱动 | ❌ 无（向量化 + 逐日循环） |
| Walk-Forward | ✅ evaluator_fixed + etf_backtest 两个独立实现 |
| 参数寻优 | ❌ 参数全硬编码 |
| 蒙特卡洛 | ❌ 无 |
| 基准对比 | ✅ 沪深300全收益修正 |
| Brinson 归因 | ❌ 无 |
| Look-ahead 防护 | ⚠️ Walk-Forward 天然防前视，但无 point-in-time 数据 |
| 幸存者偏差 | ❌ 代码写了未启用 |
| 测试覆盖 | ❌ **回测逻辑零测试**（仅存储模块有测试） |

#### 3.5.6 回测层评价

| 维度 | 评价 |
|------|------|
| 功能完整性 | ⚠️ 有 Walk-Forward + DSR，但无蒙特卡洛/参数寻优/归因 |
| 正确性 | ⚠️ 幸存者偏差修正未启用、无 point-in-time |
| 版本管理 | ❌ 3 个版本未收敛，策略逻辑 3 处重复 |
| 测试覆盖 | ❌ 回测逻辑零测试 |
| 成本模型 | ⚠️ evaluator_fixed 接入 cost_model，但 walk_forward 内联计算不一致 |

---

### 3.6 输出层与辅助模块

#### 3.6.1 Dashboard

`portfolio_server.py` 基于 FastAPI，1750+ 行，提供：
- 7 面板统一 Dashboard（模拟盘/回测对比/票池/ETF/新闻/日报）
- 15+ API 端点
- Chart.js 4.4.7 CDN 前端
- 60 秒自动刷新

**❌ 无认证**：所有 API 对公网开放。Dashboard 部署在 `http://47.85.161.255/dashboard`，任何人可访问持仓、信号、行为诊断等敏感数据。

#### 3.6.2 飞书推送

| 脚本 | 行数 | 重试 | 认证 |
|------|------|------|------|
| `push_daily_to_feishu.py` | 11 | ❌ | 硬编码 URL |
| `push_report_to_group.py` | 202 | ❌ | credentials.json |
| `report_v6.py` 内嵌 push_to_group | ~15 | ❌ | try/except 静默忽略 |

**所有飞书推送均无失败重试机制**。

#### 3.6.3 LLM 使用范围

LLM（GLM-4-Flash）仅用于 4 处：
- `news_engine.py`：新闻摘要
- `news_pipeline.py`：个股新闻分析
- `anomaly_news.py`：异动股联动分析
- `scripts/deep_research.py`：深度研报

其余模块（`concept_engine.py` 881 行、`macro_engine.py`、`chain_scanner.py`、`delta_tracker.py` 等）均为纯规则，无 LLM。

#### 3.6.4 产业链定义重复

- `chain_scanner.py`：12 条产业链（独立定义，WATCHLIST 映射硬编码）
- `report_v6.py` 内嵌：14 条链（8核心+2条件+4新增，含翻倍逻辑/Perez阶段/DCF-TV）
- `config.py` INDUSTRY_CHAINS：15 条链（含物理AI链）

三处定义不共享数据。

#### 3.6.5 输出层评价

| 维度 | 评价 |
|------|------|
| Dashboard 功能 | ⭐⭐⭐ 7面板15+API，功能丰富 |
| 安全性 | ❌ 无认证，公网开放 |
| 推送可靠性 | ❌ 无重试 |
| 报告质量 | ⭐⭐⭐⭐ 日报 9 板块 + 行为诊断 + 概念引用 |
| 模块重复 | ⚠️ 2 套报告生成器、3 处产业链定义 |

---

## 4. 已知 Bug 与风险清单

### 4.1 Bug 纠正与补充

本次评审对 AGENTS.md 记录的已知 Bug 进行了代码级核实，发现部分记录有误：

| Bug | AGENTS.md 记录 | 实际核实结果 |
|-----|---------------|-------------|
| 财务 abs() | `data_layer.py L276,327-331,354,364` | ❌ **记录有误**。data_layer.py 这四处无 abs()。真正 bug 在 `factor_scanner.py` L60（abs 抹消现金流正负号） |
| MA 方向反向 | `faceji.py L62` | ✅ **确认**。`ma60d >= ma20d` 应为 `ma60d <= ma20d`，在上升趋势错误跳过建仓 |
| 周频接线缺陷 | `trading_engine.py L631-644` | ⚠️ **行号过时**（当前文件仅600行）。当前缺陷在 L476-496：SELL 绕过 TradeCalendar |
| MACD 判定恒真 | `evaluator_fixed.py:L256, backtest_v2.py:L293, backtest_all:L539` | ❌ **记录有误**。这三处实际是 `pmacd <= psig`（正确）。真正 bug 在 `run_trading.py:L98`（`pmacd <= pe12-pe26` 恒真） |

### 4.2 完整风险清单

| 等级 | 风险 | 位置 | 影响 |
|------|------|------|------|
| 🔴 P0 | MA 方向反向 | faceji.py L62 | 上升趋势错误跳过建仓，下降趋势错误建仓 |
| 🔴 P0 | abs() 抹消现金流 | factor_scanner.py L60 | 负现金流被抹为正数，质量因子评分虚假偏高 |
| 🔴 P0 | MACD 恒真 | run_trading.py L98 | MACD 金叉判定永远为真，信号失真 |
| 🔴 P0 | Dashboard 无认证 | portfolio_server.py | 持仓/信号/行为诊断公网暴露 |
| 🟠 P1 | 4-5 处策略副本漂移 | strategy_comparison.py / backtest_v2.py / run_daily.py | 修改策略需同步多处，回测与模拟盘结果不一致 |
| 🟠 P1 | 配置双重维护已漂移 | config.py ↔ domain/__init__.py | CPI_STRATEGY_MAP 缺键、物理AI链缺失 |
| 🟠 P1 | 宏观缓存 42 天过期 | data/macro_raw_cache.json | 宏观判断基于过期数据 |
| 🟠 P1 | 模拟盘无交易成本 | trading_engine.py | 模拟盘 P&L 与实际偏差大 |
| 🟠 P1 | factor_quality 数据源不匹配 | factor_quality.py L53-56 | IC 统计在日常运行时为空 |
| 🟡 P2 | 幸存者偏差修正未启用 | backtest.py L69-101 | 回测结果偏乐观 |
| 🟡 P2 | SELL 绕过周频过滤 | trading_engine.py L490-491 | 周频预算被暗中超过 |
| 🟡 P2 | 新闻管线断裂 | akshare API 签名变更 | Tier 1 新闻全部失败 |
| 🟡 P2 | 回测逻辑零测试 | — | 回测正确性无保障 |
| 🟡 P2 | run_daily.py 不可移植 | L15 硬编码绝对路径 | 开发环境无法运行 |
| ⚪ P3 | WATCHLIST 重复条目 | config.py L352/404 等 | GLD/HG=F/CL=F 重复 |
| ⚪ P3 | 飞书推送无重试 | push_*.py | 推送失败静默丢失 |

---

## 5. 业界开源系统对比

### 5.1 横向对比表

| 维度 | Qlib | NautilusTrader | Zipline-R | Backtrader | VNPY | RQAlpha | bt | **Hermes** |
|------|------|---------------|-----------|------------|------|---------|----|-----------|
| **架构类型** | AI 研究平台 | Rust 事件驱动 | 回测+因子引擎 | 回测引擎 | 全栈交易平台 | 插件化回测 | 策略组合 | **脚本集合** |
| **回测模式** | 混合 | 事件驱动 | 事件驱动 | 事件驱动 | 事件驱动 | 事件驱动 | 向量化 | **向量化+逐日循环** |
| **实盘能力** | ❌ | ✅ 一等公民 | ⚠️ 有限 | ⚠️ 废弃 | ✅ 一等公民 | ✅ Mod桥接 | ❌ | **❌ 模拟盘** |
| **多资产** | ✅ 截面原生 | ✅ 多交易所 | ✅ Asset DB | ✅ 多DataFeed | ✅ 多Gateway | ✅ | ✅ 树形 | **⚠️ 前缀路由** |
| **因子引擎** | ✅ Expression(60+算子) | ⚠️ 手动 | ✅ Pipeline API | ❌ 手动 | ⚠️ 弱 | ❌ | ❌ | **⚠️ 硬编码19子因子** |
| **扩展性** | YAML配置式 | Adapter+Actor | Bundle+CustomFactor | 全覆写 | Gateway+App | Mod插件 | Algo+Node | **❌ 无扩展机制** |
| **文档质量** | ⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ | **⭐⭐⭐** |
| **活跃度** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | ❌ 废弃 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | **— (个人项目)** |

### 5.2 Star 数与活跃度

| 项目 | Stars | 最近 Release | 维护状态 |
|------|-------|-------------|---------|
| Qlib | ~44,838 | 2025-08 | ✅ 微软维护 |
| NautilusTrader | ~24,000 | v1.230.0 (2026-06) | ✅ 高频迭代 |
| VNPY | ~42,500 | v4.4.0 (2026-05) | ✅ 极活跃 |
| Backtrader | ~22,000 | 2019 后无更新 | ❌ 废弃 |
| Zipline-Reloaded | — | v3.05 | ⚠️ 被动维护 |
| RQAlpha | ~6,500 | v6.2.0 | ✅ 稳定 |
| bt | ~3,000 | v1.2.0 (2026-04) | ⚠️ 低频 |
| Pyfolio-Reloaded | ~591 | 维护中 | ⚠️ 小规模 |

### 5.3 Hermes 可借鉴之处

| 借鉴来源 | 核心启示 | 对 Hermes 的价值 |
|----------|----------|-----------------|
| **Qlib Expression Engine** | 算子化因子表达式 + DAG 延迟计算 | 将 factor_scanner/engine 的硬编码因子抽象为声明式 DSL |
| **Qlib DataHandlerLP** | 可学习的处理器管线（learn/infer/shared） | 解决 data_layer 财务字段处理不一致问题 |
| **NautilusTrader BacktestNode/LiveNode** | 回测与实盘完全一致的代码路径 | 解决 run_daily / trading_engine / backtest 三条独立策略管线问题 |
| **NautilusTrader Event Sourcing** | 状态变更全量记录、可重放、可验证 | 模拟盘无审计溯源能力，交易行为不可追溯 |
| **Zipline Pipeline API** | DAG 因子计算引擎，跨截面自动优化 | 从逐标的 MA 检查升级为声明式截面因子 |
| **VNPY App 架构** | MainEngine + 可插拔 App | 将因子扫描/日报/回测拆为独立 App |
| **VNPY Gateway 抽象** | 标准化交易所接口 | 统一 yfinance/akshare/baostock 数据源接口 |
| **RQAlpha Mod 系统** | 松耦合插件 + 细粒度事件钩子 | 将风控/数据校验/日志等关注点解耦为 Mod |
| **bt 策略树** | 组合策略树形结构，每个 Node 有自己的绩效 | 多账户/多子策略管理 |
| **pyfolio tearsheet** | 标准化绩效归因报告 | report_v6 可采用 pyfolio 风格的归因分析 |

### 5.4 Hermes 的独特定位

Hermes 与以上系统有一个本质区别：**它是"投资哲学驱动的"而非"技术架构驱动的"**。

- 面基播客 154 期知识体系被深度结构化（`concept_engine.py` 881 行，47+ 概念函数）
- 段永平"不为清单"10 条规则被编码为前置过滤（`stop_list.py`）
- LDS 双门系统（宏观门 + 趋势门）被集成到因子权重和策略开关
- 行为金融偏差被量化诊断（`behavior.py` 4 维指标）

这种"投资哲学代码化"的思路在上述开源系统中都不存在。**这是 Hermes 最大的差异化价值**。

### 5.5 Hermes 实际借鉴的项目谱系

> **重要澄清**: 5.1-5.3 的对比表列出的是"业界通用量化框架"（Qlib/NautilusTrader/VNPY 等），用于理解 Hermes 在整个量化开源生态中的位置。但 Hermes 的实际架构并非从零设计，而是**有明确借鉴谱系的**——在开发过程中深度调研并直接借鉴了以下项目。

#### 5.5.1 直接借鉴 vs 通用参考的区分

| 类别 | 项目 | 与 Hermes 的关系 |
|------|------|-----------------|
| **直接借鉴（代码级）** | hl-quant, xalpha, OSkhQuant, Vibe-Trading | 架构理念直接落地到 Hermes 代码中 |
| **方法论借鉴（实践级）** | OpenSpec, Superpowers, Karpathy 原则 | 开发流程和工程纪律的直接来源 |
| **通用参考（对比级）** | Qlib, NautilusTrader, VNPY, Zipline, RQAlpha, bt, backtrader | 知道业界标准在哪，知道差距有多大 |
| **基准坐标（目标级）** | Bloomberg, QuantConnect, Wind, LDS全天候 | 知道目标在哪，不是用来抄的 |

#### 5.5.2 直接借鉴项目的横向对比

| 能力 | hl-quant | xalpha | OSkhQuant | Vibe-Trading | **Hermes 落地** |
|------|----------|--------|-----------|-------------|----------------|
| 纯函数策略（零IO） | ✅ 核心 | ❌ | ❌ | ❌ | ✅ `strategies/*.py` |
| 固定评估器（防过拟合） | ✅ 核心 | ❌ | ❌ | ❌ | ✅ `evaluator_fixed.py` (ADR-001) |
| HL 循环 | ✅ 核心 | ❌ | ❌ | ❌ | ✅ `data/hl_runs/` |
| Walk-Forward 验证 | ✅ | ❌ | ❌ | ❌ | ✅ `evaluator_fixed.run_walk_forward()` |
| 透明缓存装饰器 | ❌ | ✅ `@cachedio` | ❌ | ❌ | ✅ `data_router.py @cachedio` |
| 前缀路由数据源 | ❌ | ✅ `_detect_source` | ❌ | ❌ | ✅ `data_router.py _detect_source()` |
| 绩效指标面板 | ❌ | ❌ | ✅ 7面板 | ❌ | ✅ Dashboard 7面板 + `/api/metrics` |
| IC/IR 因子分层验证 | ❌ | ❌ | ✅ | ✅ 452因子Zoo | ✅ `factor_engine.py` IC滚动权重 + 贝叶斯收缩 |
| 因子→风格→复合分层 | ❌ | ❌ | ❌ | ✅ | ✅ `factor_engine.py` 19子→7风格→1复合 |
| 跨市场回测 | ❌ | ❌ | ✅ | ✅ (加密+期货) | ✅ (A+H+US) `backtest_storage.py` |
| Shadow Account 行为诊断 | ❌ | ❌ | ❌ | ✅ 核心 | ⚠️ 部分 (`behavior.py` + `strategy_states.json`) |
| Broker API 实盘 | ❌ | ❌ | ❌ | ❌ | ❌ |

#### 5.5.3 借鉴方式说明

**hl-quant — 架构骨架级借鉴**：
- 纯函数策略层（`strategies/` 零IO）→ 解决策略可测试性和回测/实盘一致性
- 固定评估器（`evaluator_fixed.py` + ADR-001）→ 解决回测过拟合问题，同一组 19 只标的永远评
- HL 循环 → Probe→Diagnose→Propose→Patch→Evaluate→Replay→Decide→Compress 的策略迭代方法论
- Walk-Forward → 多周期验证，防止单窗口回测偏差

**xalpha — 数据基础设施级借鉴**：
- `@cachedio` 透明缓存装饰器 → TTL 参数化 pickle 缓存，调用方无感知
- `_detect_source` 前缀路由 → 6位数字→baostock、.HK→yfinance、=→akshare_futures
- **问题**: 后续模块（data_source_layer、global_data）各自新增了独立缓存层，未统一到 @cachedio 模式

**OSkhQuant — 输出层借鉴**：
- 绩效指标面板风格 → Sharpe/Sortino/Alpha/Beta/连续盈亏/最大回撤/胜率
- 7 面板 Dashboard 布局 → 直接影响了 `portfolio_server.py` 的统一 Dashboard 设计

**Vibe-Trading (HKUDS) — 因子验证方法论借鉴**：
- **没有直接移植 452 个 Alpha 因子**（全是加密期货因子，对 A 股零意义）
- **持久贡献是因子验证方法论**：别只看 Alpha 数量，要看 IC/IR 分层筛选
- **回测架构思路**：Composite→多策略并行，影响了 `backtest_storage.py` 的 schema 设计
- **Shadow Account 思路**：启发了 `strategy_states.json` 历史记录 + 模拟盘追踪，完整 Shadow 诊断管线未实现是范围决策

#### 5.5.4 借鉴谱系对重构建议的影响

理解借鉴谱系后，重构建议需要调整优先级：

1. **纯函数策略层是 hl-quant 的核心借鉴，方向正确**——重构不是"引入 Strategy 抽象基类"替代纯函数，而是**消除 inline 副本，让所有路径都委托 strategies/ 纯函数**。NautilusTrader 的 Strategy 基类可作为类型安全保障的参考，但不应替代 hl-quant 的纯函数哲学。

2. **@cachedio 是 xalpha 的正确借鉴，应统一而非废弃**——重构方向是让 data_source_layer、global_data 等后续模块的缓存统一到 @cachedio 模式，而非引入 Redis/数据库替代。

3. **固定评估器是 hl-quant 的 ADR-001 核心，不可废弃**——重构方向是让 backtest_v2.py 和 backtest_all_strategies.py 收敛到 evaluator_fixed，而非创建新评估器。

4. **IC/IR 因子分层是 Vibe-Trading 的方法论贡献，应深化而非替换**——重构方向是修复 factor_quality.py 的数据源格式不匹配问题（当前读 v3.1 格式但日常数据已是 v4.0），而非引入新的因子验证体系。

5. **因子表达式引擎（Qlib Expression Engine）是下一步演进方向，不是当前重构重点**——Hermes 当前 19 子因子的 IC/IR 分层验证已落地，DSL 化是 P3 长期演进。

---

## 6. 生产级差距分析

### 6.1 回测引擎类型与正确性

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 回测模式 | 两阶段 pipeline（向量化探索 + 事件驱动验证），同一策略代码 | 向量化 + 逐日循环，策略代码 3 处不同副本 | 🔴 严重 |
| Look-ahead 防护 | 事件驱动天然防前视 + point-in-time 数据 | Walk-Forward 天然防前视，但无 point-in-time 数据 | 🟠 中等 |
| Walk-Forward | ✅ evaluator_fixed 支持 | ✅ 已有 | ✅ 无差距 |
| Purged K-Fold / CPCV | López de Prado 标准，PBO < 0.25 | ❌ 无 | 🔴 严重 |
| 蒙特卡洛重采样 | 参数空间随机采样，分布推断 | ❌ 无 | 🟠 中等 |
| DSR | Bailey-López de Prado，DSR > 0.95 | ✅ evaluator_fixed 有 `compute_dsr()` | ✅ 无差距 |
| 幸存者偏差 | Point-in-time 成分股列表 | ❌ 代码写了未启用 | 🔴 严重 |

### 6.2 因子工程平台

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 因子表达式引擎 | WorldQuant Alpha101 / Qlib Expression（60+ 算子 DSL） | ❌ 硬编码 19 子因子，无 DSL | 🔴 严重 |
| 因子库管理 | 版本化（content hash）、衰减监控 | ⚠️ 有 IC/IR/衰减但数据源格式不匹配 | 🟠 中等 |
| 行业中性化 | 回归残差法 | ⚠️ v4.0 有产业链分组截面标准化 | 🟡 轻微 |
| 市值中性化 | 回归残差法 | ❌ 两套引擎均无 | 🟠 中等 |
| 因子正交化 | Gram-Schmidt / PCA | ❌ 无 | 🟠 中等 |
| A/B 因子实验 | 分层回测 + 边际 IR 贡献 | ❌ 无 | 🟠 中等 |
| 因子扩展机制 | 插件/注册表/YAML 配置 | ❌ 全硬编码，新增需改 5 处源码 | 🔴 严重 |

### 6.3 组合优化与风控

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 优化器 | MVO/BL/风险平价/HRP/NCO 多个并行 | ⚠️ 有风险平价（allocation_strategies.py），仅 ETF 用 | 🟠 中等 |
| 协方差去噪 | Ledoit-Wolf / Marchenko-Pastur | ❌ 无 | 🟠 中等 |
| 约束体系 | 行业偏离/单标的/换手率/追踪误差 | ⚠️ portfolio_builder.py 有基本约束（最大8只/单标≤15%） | 🟡 轻微 |
| VaR / CVaR | 95%/99% 置信度 | ⚠️ Dashboard API 有 VaR(95%) 计算（portfolio_server L1131-1207） | 🟡 轻微 |
| 压力测试 | 历史场景回放 + 协方差应力 | ❌ 无 | 🟠 中等 |
| 实时风控 | 回撤熔断 + 敞口限制 + Kill-switch | ⚠️ 有止损/止盈但无梯度熔断 | 🟠 中等 |

### 6.4 执行层

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 订单类型 | TWAP/VWAP/POV/IS | ❌ 无（直接市价全量成交） | 🔴 严重 |
| 滑点模型 | Almgren-Chriss 线性 / 平方根 / Walk-the-book | ⚠️ cost_model.py 有 5 级滑点但**未接入** trading_engine | 🟠 中等 |
| 拆单与智能路由 | 父订单→子订单 + 多交易所路由 | ❌ 无 | 🔴 严重 |
| 模拟盘→实盘统一接口 | Ports & Adapters（六边形架构） | ❌ 4-5 处独立策略实现 | 🔴 严重 |
| 涨跌停限制 | — | ❌ 无 | 🟠 中等 |

### 6.5 数据治理

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 数据架构 | Lakehouse + Event Bus（Kafka + Iceberg） | ❌ 文件存储（pickle/JSON），无数据库 | 🔴 严重 |
| Point-in-time 数据 | 每次回测使用该时刻可见的数据快照 | ❌ 无 | 🔴 严重 |
| 数据血缘 | OpenLineage + Marquez 自动追踪 | ❌ 无 | 🟠 中等 |
| 数据质量监控 | 异常检测 + 缺失告警 + 延迟 SLO | ⚠️ 有基本校验（价格区间/汇率方向）但无监控告警 | 🟠 中等 |
| 时序数据库 | kdb+ / DolphinDB / TimescaleDB | ❌ pickle 文件 + 内存 dict | 🔴 严重 |
| 缓存一致性 | 统一缓存层 + TTL + LRU | ❌ 6 层独立缓存不协调，多份严重过期 | 🔴 严重 |

### 6.6 可观测性与运维

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 监控指标 | Prometheus + Grafana（PnL/订单/信号/数据/系统） | ❌ 无监控 | 🔴 严重 |
| 告警 | Alertmanager + Telegram/PagerDuty | ❌ 无告警 | 🔴 严重 |
| 回测可复现性 | run_manifest（git SHA + 配置 + 数据 hash + 种子） | ❌ 无 | 🔴 严重 |
| A/B 策略对比 | Shadow → Paper → Live 五阶段晋升 | ❌ 无 | 🟠 中等 |
| 日志 | 统一日志框架 + 结构化日志 | ❌ 各写各的 `/tmp/*.txt` | 🔴 严重 |
| CI/CD | GitHub Actions + ruff + pytest + integration | ❌ 无 CI/CD | 🔴 严重 |

### 6.7 机器学习集成

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 特征工程 Pipeline | 结构化模板 + content hash + schema enforce | ❌ 无 | 🔴 严重 |
| 模型版本化 | MLflow Registry + production pointer | ❌ 无 | 🟠 中等 |
| 在线/离线一致性 | 同一特征计算代码 + norm cache | ❌ 无 | 🟠 中等 |
| 模型监控 | KS 检验 + PSI + drift severity | ❌ 无 | 🟠 中等 |
| AutoML | Optuna + PurgedKFold | ❌ 无 | 🟡 轻微 |

> **注**：Hermes 定位为规则驱动系统而非 ML 驱动，ML 集成差距的严重程度取决于未来是否计划引入 ML。

### 6.8 工程基础设施

| 维度 | 业界标准 | Hermes 现状 | 差距等级 |
|------|---------|------------|---------|
| 配置管理 | Hydra / OmegaConf / Pydantic Settings | ❌ config.py 1035行硬编码 + domain 双重维护 | 🔴 严重 |
| 任务编排 | Airflow / Prefect / Dagster | ❌ ECS Cron YAML 无重试无监控 | 🔴 严重 |
| 持久化 | PostgreSQL + 时序 DB + 对象存储 | ❌ JSON/pickle 文件 | 🔴 严重 |
| 测试 | Unit + Integration + Property-based + Regression | ❌ 仅存储模块和部分因子有测试，回测逻辑零覆盖 | 🔴 严重 |
| CI/CD 与回滚 | GitHub Actions + manifest 驱动 promotion | ❌ 无 | 🔴 严重 |
| 类型安全 | mypy / pyright strict | ❌ 无类型注解强制 | 🟠 中等 |

### 6.9 差距汇总

| 差距等级 | 数量 | 占比 |
|---------|------|------|
| 🔴 严重 | 22 | 44% |
| 🟠 中等 | 19 | 38% |
| 🟡 轻微 | 6 | 12% |
| ✅ 无差距 | 3 | 6% |

**结论**：Hermes 在生产级就绪度上与业界标准存在显著差距，44% 的维度为严重差距。但这些差距需要结合 Hermes 的定位来理解——**它是一个个人研究+辅助决策系统，不是生产级交易系统**。如果目标始终是辅助人工决策，部分差距（如实盘执行、TWAP/VWAP）可以忽略；但如果目标是向自动化交易演进，则基础设施层面的差距必须优先填补。

---

## 7. 重构建议

### 7.1 是否需要重构？

**需要，且 urgently。**

理由：
1. **策略副本漂移已造成实际 Bug**（faceji.py L62 MA 方向 bug 在其他副本中是正确的，说明修改时未同步）
2. **配置双重维护已产生实际数据丢失**（domain 缺物理AI链、CPI_STRATEGY_MAP 缺键）
3. **回测与模拟盘结果天然不一致**（4-5 处独立策略实现），导致回测结论不可信
4. **无扩展机制**，新增因子/策略/数据源需修改多处源码，维护成本随功能增长指数上升
5. **无测试保障**，任何修改都可能引入无声回归

### 7.2 重构优先级

#### P0 — 立即修复（不重构，仅修 Bug）

| # | 修复项 | 文件 | 预计工时 |
|---|--------|------|---------|
| 1 | MA 方向 bug | faceji.py L62: `>=` → `<=` | 5 分钟 |
| 2 | abs() 抹消现金流 | factor_scanner.py L60: 移除 abs() | 5 分钟 |
| 3 | MACD 恒真 | run_trading.py L98: `pe12-pe26` → `psig` | 5 分钟 |
| 4 | Dashboard 加认证 | portfolio_server.py: 添加 API Key / Basic Auth | 1 小时 |
| 5 | 清理过期缓存 | macro_raw_cache.json 等 | 30 分钟 |

#### P1 — 短期统一（1-2 周）

| # | 统一项 | 方案 | 预期收益 |
|---|--------|------|---------|
| 1 | 配置单源化 | config.py 为事实源，domain/__init__.py 改为 `from config import *` | 消除 850 行重复 |
| 2 | 策略副本收敛 | strategy_comparison.py 和 backtest_v2.py 委托 strategies/ 纯函数 | 消除 3 处副本 |
| 3 | 回测版本收敛 | 废弃 backtest_v2.py 和 backtest_all_strategies.py，统一走 evaluator_fixed | 消除 2 个版本 |
| 4 | 接入 cost_model | trading_engine.py 引入 cost_model.py | 模拟盘 P&L 更真实 |
| 5 | 统一 .env 加载 | 所有入口用 `python-dotenv` | 开发环境可运行 |
| 6 | 统一 sys.path | 所有入口用相对路径 | 可移植性 |
| 7 | 清理死代码 | 删除 run_report_v10.py, run_daily_continue.py.disabled, run_cron_daily.sh/run_daily_cron.sh 二选一 | 减少认知负担 |

#### P2 — 中期架构改进（1-2 月）

| # | 改进项 | 参考来源 | 预期收益 |
|---|--------|---------|---------|
| 1 | 引入 Strategy 抽象基类 | NautilusTrader / VNPY CtaTemplate | 类型安全 + 统一生命周期 |
| 2 | 统一策略管线 | run_daily.py 改用 strategies/ + trading_engine.py | 消除 shadow_account 独立管线 |
| 3 | 配置分层 | Pydantic Settings / Hydra | 策略参数与系统参数分离 |
| 4 | 数据源统一接口 | VNPY Gateway / Qlib DataHandler | 统一 baostock/akshare/yfinance 接口 |
| 5 | 引入数据库 | SQLite（轻量）或 PostgreSQL | 替代 JSON/pickle 文件存储 |
| 6 | 补充测试 | 回测逻辑 + 策略逻辑 + 因子计算 | 防止无声回归 |
| 7 | 因子配置化 | YAML/JSON 因子定义 + 注册表 | 无需改源码即可新增因子 |
| 8 | 监控告警 | Prometheus + Grafana 或最简方案（飞书告警） | 缓存过期/管线失败可感知 |

#### P3 — 长期演进（3-6 月，视需求）

| # | 演进项 | 前提条件 |
|---|--------|---------|
| 1 | 因子表达式引擎 | 参考 Qlib Expression Engine |
| 2 | 事件驱动回测 | 参考 NautilusTrader / RQAlpha |
| 3 | Point-in-time 数据 | 需数据库支持 |
| 4 | Walk-Forward + CPCV | 参考 López de Prado |
| 5 | CI/CD | GitHub Actions + ruff + pytest |
| 6 | 策略组合层 | 参考 bt 策略树 |

### 7.3 重构原则

1. **保留投资哲学代码化**：`concept_engine.py`、`stop_list.py`、`behavior.py`、`macro_engine.py` 是 Hermes 的核心价值，重构应保留而非重写
2. **保留已借鉴的架构哲学**：纯函数策略层（hl-quant）、@cachedio 缓存（xalpha）、固定评估器（hl-quant ADR-001）、IC/IR 因子分层（Vibe-Trading）、7面板 Dashboard（OSkhQuant）——这些是经过深度调研后的正确设计决策，重构方向是**统一和深化**而非替代：
   - 纯函数策略：消除 inline 副本，让所有路径委托 `strategies/`，而非引入 NautilusTrader 式 Strategy 基类替代
   - @cachedio 缓存：让后续模块的独立缓存层统一到 @cachedio 模式，而非引入 Redis 替代
   - 固定评估器：让 backtest_v2/backtest_all 收敛到 evaluator_fixed，而非创建新评估器
   - IC/IR 因子分层：修复 factor_quality.py 数据源格式不匹配，而非引入新验证体系
   - 因子表达式 DSL（Qlib Expression Engine）是 P3 长期演进，不是当前重构重点
3. **先统一再优化**：先消除副本和双重维护，再考虑架构升级
4. **测试先行**：在重构前先补充关键路径的测试（策略逻辑、回测正确性），确保重构不引入回归
5. **渐进式重构**：不要一次性重写，按 P0→P1→P2→P3 优先级逐步推进
6. **保持可运行**：每个重构步骤后系统必须可运行，不允许"大爆炸"式重构

---

## 8. 结论

### 8.1 Hermes 是什么

Hermes Investment 是一个**投资哲学深度代码化的个人量化辅助决策系统**。它不是、也不应该是 NautilusTrader 或 VNPY 的复制品。它的核心价值在于：

- 将面基播客 154 期投资体系结构化为可执行的代码（`concept_engine.py` 881 行）
- 将段永平"不为清单"编码为前置过滤（`stop_list.py`）
- 将行为金融偏差量化为诊断指标（`behavior.py`）
- 将宏观周期映射到因子权重和策略开关（`macro_engine.py` + `FACTOR_WEIGHTS`）

这种"投资哲学代码化"的思路在业界开源系统中是**独一无二的**。

### 8.2 Hermes 的问题

但代码实现在以下方面已逼近可维护性极限：

1. **副本泛滥**：4-5 处策略副本、3 个回测版本、2 份配置、3 处产业链定义，修改需同步多处
2. **无抽象基类**：策略靠约定一致，无类型保障
3. **无测试保障**：回测逻辑零覆盖，任何修改都可能引入无声回归
4. **配置漂移**：config.py ↔ domain 已产生实际数据丢失
5. **无扩展机制**：新增因子/策略/数据源需改多处源码

### 8.3 建议路线

```
当前状态 ──P0(1天)──→ Bug修复 ──P1(2周)──→ 副本收敛 ──P2(2月)──→ 架构改进 ──P3(6月)──→ 生产级
   ↑                    ↑                   ↑                  ↑
  可用但危险          可用且正确          可维护              可扩展
```

**最紧迫的不是架构升级，而是消除副本和修复已知 Bug**。在副本消除之前，任何功能扩展都会加剧维护负担。

### 8.4 一句话评价

> Hermes 的投资思考深度值得 8/10 分，借鉴谱系清晰度 8/10 分（hl-quant/xalpha/OSkhQuant/Vibe-Trading 架构理念正确落地），但代码架构质量只有 4/10 分——问题不是设计方向错误，而是副本漂移导致正确的架构理念被覆盖。先用 1 天修 Bug，再用 2 周收敛副本（让所有路径回归 hl-quant 纯函数 + xalpha @cachedio + 固定评估器的正确设计），然后再谈架构升级。

---

## 附录 A：调研方法

本报告基于 8 个并行调研任务 + 用户提供的借鉴谱系补充：
- 6 个 explore agent 扫描项目各层（入口/数据/因子/策略/回测/输出），所有结论有代码行号佐证
- 2 个 librarian agent 调研 8 个通用开源量化系统架构 + 8 维度生产级特性
- 用户提供 Hermes 开发过程中深度调研并直接借鉴的项目谱系（hl-quant / xalpha / OSkhQuant / Vibe-Trading / OpenSpec / Superpowers / Karpathy），补充了"为什么这么做"的架构决策背景

调研覆盖 ~50 个 Python 模块、~15,000 行核心代码。

## 附录 B：AGENTS.md Bug 清单纠正

| AGENTS.md 记录 | 核实结果 | 建议更新 |
|---------------|---------|---------|
| 财务 abs() — data_layer.py L276,327-331,354,364 | ❌ data_layer.py 这四处无 abs() | 改为 factor_scanner.py L60 |
| MA 方向反向 — faceji.py L62 | ✅ 确认 | 无需更新 |
| 周频接线缺陷 — trading_engine.py L631-644 | ⚠️ 行号过时 | 改为 L476-496 |
| MACD 判定恒真 — evaluator_fixed.py:L256, backtest_v2.py:L293, backtest_all:L539 | ❌ 这三处实际是 `pmacd <= psig`（正确） | 改为 run_trading.py:L98 |

---

*报告结束*
