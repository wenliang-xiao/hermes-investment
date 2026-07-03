# 架构拆分方案

> 版本: v2026.07.03 | 状态: Draft | 作者: wenlix
>
> 解决 12 个超大文件（6 个超 1000 行）、配置重复和 import hack 三大工程化债务。

## 文档结构

本文档首先盘点现状（超大文件与配置债务），然后逐个文件给出拆分前后模块映射和详细拆分计划，接着处理配置去重和 import 路径标准化，最后给出依赖图、迁移顺序、风险矩阵和验证清单。适合需要理解拆分方案并制定实施计划的开发者阅读。

---

## 一、现状盘点

### 1.1 超大文件清单

| 文件 | 行数 | 成因 | 职责混乱程度 |
|------|------|------|------------|
| `output/report_v6.py` | 2575 | 飞书 API + 文档构建 + 全部日报板块 + LLM 调用全塞一个文件 | 🔴 极高 |
| `output/full_asset_scanner.py` | 1780 | 大宗商品 + 外汇 + 债券 + 桥水象限四种资产扫描混写 | 🔴 极高 |
| `analysis/backtest.py` | 1681 | 四策略 v2.0 回测引擎：引擎 + 策略 + 指标 + 成本全耦合 | 🔴 极高 |
| `scripts/portfolio_server.py` | 1469 | FastAPI + HTML + CSS + JS + 12 个 API 端点三语言混合 | 🔴 极高 |
| `analysis/news_engine.py` | 1332 | Google News RSS 4 路 + 雪球 + LLM 摘要全耦合 | 🔴 高 |
| `config.py` | 1035 | 全部系统参数不加分类塞一个文件 | 🔴 高 |
| `scripts/run_daily.py` | 982 | 日报管线编排：宏观→因子→交易→写报告四阶段混合 | 🟡 中高 |
| `analysis/factor_engine.py` | 935 | 19 子因子→7 风格因子 + PoolManager 分级管理 | 🟡 中 |
| `data/data_layer.py` | 885 | 多源数据接入混写 | 🟡 中 |
| `evaluator_fixed.py` | 878 | 固定标尺回测评估 | 🟡 中 |

> **统计分析**：12 个文件超 600 行，6 个文件超 1000 行。最长文件 `report_v6.py`（2575 行）超出合理上限（~500 行）5 倍。

### 1.2 配置重复

`config.py` 和 `domain/__init__.py` 存在大范围重复：WATCHLIST、INDUSTRY_CHAINS、OPPORTUNITY_THEMES、MACRO_THRESHOLDS、FACTOR_WEIGHTS、CPI_STRATEGY_MAP、TREND_TEMP、FX_PAIRS、BOND_MARKETS、GLOBAL_INDICES、HK_WATCHLIST、US_WATCHLIST、COMMODITIES、MACRO_SECTOR_ROTATION、NEWS_SOURCES、RISK_PARAMS、LDS_STOCK_FILTERS 共 **18 个变量**完全镜像。影响：

- 修改一个配置需在两个文件中同步，极易遗忘
- `domain/__init__.py` 缺失 `config.py` 中的 `CHAIN_ECONOMICS_WEIGHTS`、`PROFIT_POOL_SCORES`、`REAL_ESTATE_WATCHLIST`、`A_SHARE_ETF_WATCHLIST`，说明两份数据已开始分叉

### 1.3 Import Hack 问题

39 个文件使用 `sys.path.insert(0, ...)` 实现双模式导入（脚本直接运行 vs 包导入）。做法：

```python
sys.path.insert(0, str(Path(__file__).parent.parent))
from investment_system import config as cfg
```

根本原因：项目缺少 `pyproject.toml` / `setup.py` 做 editable install，没有标准的包声明。

---

## 二、拆分前后模块映射

### 总览

```
拆分前（扁平）                          拆分后（分层包）
─────────────────────────────────────  ─────────────────────────────────
ouput/report_v6.py         (2575行)  → report/__init__.py
                                     → report/feishu_client.py
                                     → report/sections/gate.py
                                     → report/sections/global_market.py
                                     → report/sections/etf.py
                                     → report/sections/real_estate.py
                                     → report/sections/chains.py
                                     → report/sections/factor_stocks.py
                                     → report/sections/news.py
                                     → report/sections/watchlist.py
                                     → report/sections/rebalance.py
                                     → report/sections/concept.py

output/full_asset_scanner.py (1780行) → scanner/__init__.py
                                     → scanner/commodities.py
                                     → scanner/fx.py
                                     → scanner/bonds.py
                                     → scanner/bridgewater.py

analysis/backtest.py        (1681行) → backtest/__init__.py
                                     → backtest/engine.py
                                     → backtest/strategies.py
                                     → backtest/metrics.py
                                     → backtest/cost.py

scripts/portfolio_server.py (1469行) → （参见 dashboard-refactoring.md）

analysis/news_engine.py     (1332行) → news/__init__.py
                                     → news/sources.py
                                     → news/summarizer.py
                                     → news/chain_tagger.py

config.py                   (1035行) → config/__init__.py
  + domain/__init__.py      (615行)  → config/market.py
                                     → config/strategies.py
                                     → config/risk.py
                                     → config/chains.py
                                     → config/watchlist.py

scripts/run_daily.py        (982行)  → pipeline/__init__.py
                                     → pipeline/daily.py
                                     → pipeline/reporting.py
```

---

## 三、各文件详细拆分计划

### 3.1 `report_v6.py` → `report/` 包

**现状**：2575 行，飞书 API 客户端 + 10 个日报板块 + 工具函数 + LLM 调用全在一个文件。

**拆分目标**：

```
report/
├── __init__.py              # 公开 API：build_report(), push_report()
├── feishu_client.py         # FeishuWriter 类（token 管理、doc CRUD、群推送）
├── sections/
│   ├── __init__.py
│   ├── gate.py              # 板块零：LDS 双门状态 + CPI 情景
│   ├── global_market.py     # 板块一：全球市场全景（股债汇商+VIX+国运线）
│   ├── etf.py               # 板块二：ETF 全景
│   ├── real_estate.py       # 板块三：房价趋势
│   ├── chains.py            # 板块四：产业链 12 链分析
│   ├── factor_stocks.py     # 板块五：多因子新票发现
│   ├── news.py              # 板块六：政经要闻与产业链影响
│   ├── watchlist.py         # 板块七：重点票追踪
│   ├── rebalance.py         # 板块八：调仓建议
│   └── concept.py           # 板块九：每日面基概念
└── helpers.py               # fmt_pct(), fmt_usd() 等工具函数
```

**各模块职责**：

| 模块 | 从原文件提取 | 预估行数 | 依赖 |
|------|-------------|---------|------|
| `feishu_client.py` | `FeishuWriter` 类 + `push_to_group()` | ~150 | 无 |
| `helpers.py` | `fmt_pct()`, `fmt_usd()`, `_WRITE_COUNT` | ~30 | 无 |
| `sections/gate.py` | `build_gate_section()` | ~120 | feishu_client, helpers |
| `sections/global_market.py` | `build_global_market_section()` | ~350 | feishu_client, helpers, yf_data_layer |
| `sections/etf.py` | `build_etf_section()` | ~250 | feishu_client, helpers |
| `sections/real_estate.py` | `build_real_estate_section()` | ~80 | feishu_client |
| `sections/chains.py` | `build_chains_section()` + LLM 链分析 | ~500 | feishu_client, helpers, data_layer |
| `sections/factor_stocks.py` | `build_factor_section()` | ~300 | feishu_client, factor_scanner |
| `sections/news.py` | `build_news_section()` + LLM 摘要 | ~250 | feishu_client, news_engine |
| `sections/watchlist.py` | `build_watchlist_section()` | ~200 | feishu_client, data_layer |
| `sections/rebalance.py` | `build_rebalance_section()` | ~150 | feishu_client |
| `sections/concept.py` | `build_concept_section()` | ~100 | feishu_client |
| `__init__.py` | `build_report()`, `push_report()`，组装各板块 | ~100 | 所有 sections |

**关键决策**：
- `FeishuWriter` 从日报文件剥离为独立客户端，后续其他飞书集成也可以复用（如告警推送）
- LLM 调用从板块构建逻辑中分离：每个需要 LLM 的板块通过依赖注入传入 LLM 摘要结果，不在 section 内部做 LLM 调用
- 常量（`FOLDER_TOKEN`、`GROUP_CHAT`、`KNOWLEDGE_DOC_URL` 等）移到 `config/__init__.py` 统一管理

### 3.2 `full_asset_scanner.py` → `scanner/` 包

**现状**：1780 行，大宗商品、外汇、债券、桥水四象限四种资产类型的扫描逻辑混在同一个文件中，共享大量重复的数据拉取和格式化代码。

**拆分目标**：

```
scanner/
├── __init__.py              # scan_all() 入口，聚合四种扫描结果
├── commodities.py           # 大宗商品期货扫描（黄金/原油/铜/农产品等 11 种）
├── fx.py                    # 外汇对扫描（USD/CNY, EUR/CNY, JPY/CNY 等 6 对）
├── bonds.py                 # 债券市场扫描（US10Y, CN10Y 利率分析）
├── bridgewater.py           # 桥水全天候四象限判定（增长×通胀矩阵）
└── base.py                  # 共享工具：价格拉取、格式化、信号生成
```

**各模块职责**：

| 模块 | 职责 | 预估行数 | 依赖 |
|------|------|---------|------|
| `base.py` | `get_price_safe()`, `fmt_change()`, `generate_signal()` | ~80 | yf_data_layer |
| `commodities.py` | 11 种大宗商品价格 + 变动 + 信号 | ~400 | base, config.commodities |
| `fx.py` | 6 种外汇对扫描 + 汇率趋势信号 | ~350 | base, config.fx_pairs |
| `bonds.py` | 中美利差 + 收益率曲线 + 债券信号 | ~350 | base, config.bonds |
| `bridgewater.py` | 四象限判定 + 资产配置建议 | ~400 | base, bonds, commodities |
| `__init__.py` | `scan_all()`, `scan_commodities()`, `scan_fx()` 等公开 API | ~100 | 所有子模块 |

### 3.3 `backtest.py` → `backtest/` 包

**现状**：1681 行，四策略 v2.0 回测引擎，引擎循环 + 策略逻辑 + 绩效指标 + 交易成本模型全部耦合。

**拆分目标**：

```
backtest/
├── __init__.py              # run_backtest(strategy_name, pool, dates)
├── engine.py                # 主循环：逐日推进 + 信号→交易 + 仓位管理
├── strategies.py            # 四策略买入/卖出信号逻辑
├── metrics.py               # Sharpe/最大回撤/年化收益/胜率/盈亏比
└── cost.py                  # 手续费 + 滑点 + 印花税 成本模型
```

**各模块职责**：

| 模块 | 职责 | 预估行数 | 依赖 |
|------|------|---------|------|
| `cost.py` | 三类成本计算函数（A股/港股/美股费率不同） | ~100 | 无 |
| `strategies.py` | 面基/SilverQuant/TradingAgents/基准 四策略信号生成 | ~500 | config.strategies, cost |
| `metrics.py` | 净值计算 + 绩效指标 + 回撤序列 | ~350 | 无 |
| `engine.py` | 主循环：日期推进→取价→信号→模拟成交→记录 | ~500 | strategies, metrics, cost, data_layer |
| `__init__.py` | `run_backtest()` 入口 + 结果汇总 | ~100 | engine, metrics |

**关键决策**：
- 策略逻辑从引擎中解耦，每个策略是一个独立函数：`signal = strategy_fn(date, pool, positions) -> list[Order]`
- 成本模型参数化，方便调整费率做敏感性测试
- 引擎对策略的接口统一为 `Order` dataclass（symbol, side, quantity, price, reason），新增策略只需实现同一个接口

### 3.4 `portfolio_server.py`

Dashboard 后端（1469 行）已在 [Dashboard 前端重构方案](./dashboard-refactoring.md) 中详细覆盖。本方案仅记录交叉引用，不重复设计。

拆分方向：`portfolio_server.py` → `dashboard/server.py` + `dashboard/api/*.py` + `frontend/`（独立前端项目）。

### 3.5 `news_engine.py` → `news/` 包

**现状**：1332 行，Google News RSS 4 路 + 雪球热帖 + LLM 摘要 + 链标签全耦合。

**拆分目标**：

```
news/
├── __init__.py              # fetch_all_news(), get_news_by_chain()
├── sources.py               # Google News RSS 4 路 + 雪球 API 拉取
├── summarizer.py            # LLM 摘要生成（GLM-4-Flash）
└── chain_tagger.py          # 基于关键词的产业链自动标记
```

**各模块职责**：

| 模块 | 职责 | 预估行数 | 依赖 |
|------|------|---------|------|
| `sources.py` | RSS 解析 + 雪球 API + 去重 + 合并 | ~400 | config.news_sources |
| `summarizer.py` | GLM-4-Flash LLM 调用 + 摘要生成 + 重试 | ~300 | LLM client |
| `chain_tagger.py` | 关键词匹配 → 产业链标记（12 链） | ~200 | config.chains |
| `__init__.py` | `fetch_all_news()` 编排 + `get_by_chain()` 查询 | ~150 | sources, summarizer, chain_tagger |

### 3.6 `config.py` + `domain/__init__.py` → `config/` 包（含去重）

**现状**：`config.py`（1035 行）+ `domain/__init__.py`（615 行）共享 18 个同名变量，且 `domain/__init__.py` 已缺失 4 个变量。

**去重策略**：以 `config.py` 为 **唯一真相源（Single Source of Truth）**，`domain/__init__.py` 改为从 `config` 包导入再导出。

**拆分目标**：

```
config/
├── __init__.py              # 聚合导出：from config.market import *
├── market.py                # 宏观阈值 + 汇率 + 债券 + 全球指数 + CPI 策略 + 趋势温度
├── strategies.py            # 因子权重矩阵 + 产业链经济权重 + 利润池评分
├── risk.py                  # 风控参数 + LDS 选股标准
├── chains.py                # 产业链定义（INDUSTRY_CHAINS）+ 板块轮动映射
├── watchlist.py             # WATCHLIST + HK/US/A股观测池 + 商品期货 + 机会主题 + 新闻源
└── paths.py                 # BASE/DATA_DIR + FEISHU_TOOL/TOKEN 等路径和凭据引用
```

> **注意**：`paths.py` 中的真正凭据（TUSHARE_TOKEN 等）已在 [安全加固方案](./security-hardening.md) 中规划移除，此处仅为归类阶段。

**各模块职责**：

| 模块 | 包含变量 | 预估行数 |
|------|---------|---------|
| `paths.py` | `BASE`, `DATA_DIR`, `FEISHU_TOOL`, `FEISHU_FOLDER_TOKEN`, `FEISHU_USER_OPENID`, `FEISHU_GROUP_CHAT` | ~30 |
| `market.py` | `MACRO_THRESHOLDS`, `CPI_STRATEGY_MAP`, `TREND_TEMP`, `FX_PAIRS`, `BOND_MARKETS`, `GLOBAL_INDICES`, `MACRO_SECTOR_ROTATION`, `NEWS_SOURCES` | ~200 |
| `strategies.py` | `FACTOR_WEIGHTS`, `CHAIN_ECONOMICS_WEIGHTS`, `PROFIT_POOL_SCORES` | ~100 |
| `risk.py` | `RISK_PARAMS`, `LDS_STOCK_FILTERS` | ~50 |
| `chains.py` | `INDUSTRY_CHAINS`（12 条链的完整定义 + 中观四层次 + Perez 阶段 + Nick 四问） | ~350 |
| `watchlist.py` | `WATCHLIST`, `HK_WATCHLIST`, `US_WATCHLIST`, `A_SHARE_ETF_WATCHLIST`, `REAL_ESTATE_WATCHLIST`, `COMMODITIES`, `OPPORTUNITY_THEMES` | ~350 |
| `__init__.py` | 聚合导入，保持 `from config import WATCHLIST` 向后兼容 | ~30 |

**`domain/__init__.py` 迁移**：改为纯 re-export 代理：

```python
# domain/__init__.py  → 迁移后仅保留 re-export
from config.market import (
    MACRO_THRESHOLDS, FACTOR_WEIGHTS, CPI_STRATEGY_MAP, TREND_TEMP,
    FX_PAIRS, BOND_MARKETS, GLOBAL_INDICES, MACRO_SECTOR_ROTATION, NEWS_SOURCES,
)
from config.risk import RISK_PARAMS, LDS_STOCK_FILTERS
from config.chains import INDUSTRY_CHAINS
from config.watchlist import (
    WATCHLIST, HK_WATCHLIST, US_WATCHLIST, A_SHARE_ETF_WATCHLIST,
    REAL_ESTATE_WATCHLIST, COMMODITIES, OPPORTUNITY_THEMES,
)
```

后续所有 `from domain import ...` 的调用逐步改为 `from config import ...`，待全部迁移完成后移除 `domain/__init__.py`。

### 3.7 `run_daily.py` → `pipeline/` 包

**现状**：982 行，日报管线编排器，宏观→因子→交易→写报告四阶段逻辑混合。

**拆分目标**：

```
pipeline/
├── __init__.py              # run_full_pipeline() 编排入口
├── daily.py                 # 每日管线编排：macro→factor→trading→report 四阶段
└── reporting.py             # 报告生成编排：调用 report/ 包 + 推送飞书
```

**各模块职责**：

| 模块 | 职责 | 预估行数 | 依赖 |
|------|------|---------|------|
| `daily.py` | 四阶段编排：macro_engine→factor_scanner→信号生成→写报告 | ~400 | macro_engine, factor_engine, strategies |
| `reporting.py` | 报告生成 + 飞书推送 + 结果汇总 | ~300 | report/, feishu_client |
| `__init__.py` | `run_full_pipeline()`, `run_quick_scan()` 等入口 | ~80 | daily, reporting |

---

## 四、Import 路径标准化

### 4.1 问题

39 个文件使用 `sys.path.insert(0, ...)` hack。每次脚本执行都要手动计算路径，且在不同工作目录下行为不一致。

### 4.2 方案

**新增 `pyproject.toml` 声明包结构（此改动属于 [工程化基础方案](./engineering-foundation.md) 的依赖）**：

```toml
[project]
name = "hermes-investment"
version = "2026.07.02"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = [
    "config*", "domain*", "data*", "analysis*",
    "output*", "report*", "scanner*", "backtest*",
    "news*", "pipeline*", "strategies*", "scripts*", "core*",
]
```

安装为 editable：

```bash
pip install -e .
```

### 4.3 迁移步骤

1. **第一批**（与 `config/` 拆分同步）：新增 `pyproject.toml`，执行 `pip install -e .`
2. **逐文件替换**：每拆分一个包，将对应调用方的 `sys.path.insert` 替换为标准 `from hermes_investment.xxx import ...`
3. **验证标准**：`python -c "from hermes_investment.config import WATCHLIST; print(len(WATCHLIST))"` 不报错
4. **最终清理**：全部迁移完成后，全局搜索 `sys.path.insert` 确认清零

### 4.4 备选方案

如果暂时不想引入 `pyproject.toml`，可以沿用 `sys.path.insert` 但统一为单一模式：

```python
# 统一写法，消除所有变体
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
```

但这是过渡方案，最终目标仍是 editable install。

---

## 五、依赖关系图

拆分后的模块间依赖（箭头 = "依赖"）：

```
                    ┌──────────────────────┐
                    │    config/ 包         │
                    │ (market/strategies/   │
                    │  risk/chains/watchlist)│
                    └──────┬───────────────┘
                           │ 被几乎所有模块依赖
          ┌────────────────┼────────────────────┐
          ▼                ▼                     ▼
   ┌──────────────┐  ┌───────────┐      ┌──────────────┐
   │  data/ 层     │  │ report/   │      │  pipeline/   │
   │ data_layer   │  │ feishu_   │      │  daily.py    │
   │ yf_data_layer│  │ client    │      │  reporting   │
   └──────┬───────┘  └─────┬─────┘      └──────┬───────┘
          │                │                    │
    ┌─────┼────────┐       │                    │
    ▼     ▼         ▼      │                    │
┌────────┐ ┌──────────┐    │                    │
│scanner/│ │analysis/ │    │                    │
│commod  │ │factor_   │    │                    │
│fx      │ │engine    │    │                    │
│bonds   │ │macro_    │    │                    │
│bridge  │ │engine    │    │                    │
│water   │ │news/     │    │                    │
└────────┘ └────┬─────┘    │                    │
                 │          │                    │
          ┌──────┼──────────┼────────────────────┘
          │      ▼          ▼
          │  ┌────────┐  ┌──────────┐
          │  │backtest│  │strategies│
          │  │engine  │  │faceji    │
          │  │metrics │  │silverq   │
          │  │cost    │  │tagents   │
          │  └────────┘  └──────────┘
          │
          └─────→ 用户接口层
                  ├── dashboard/ (FastAPI)
                  └── 飞书日报
```

**关键依赖链**：

1. `config/` 是零依赖叶子节点，无上游依赖——应最先拆分
2. `scanner/` 仅依赖 `config/` + `data/`——第二优先
3. `backtest/` 依赖 `config/` + `data/` + `strategies/`——需等 `strategies/` 稳定
4. `report/` 依赖 `config/` + `data/` + `scanner/` + `analysis/`——依赖最广，最后拆分
5. `pipeline/` 是顶层编排器，依赖几乎所有下层模块——最后迁移

---

## 六、向后兼容策略

### 6.1 `__init__.py` Re-export 模式

每个拆分后的新包在 `__init__.py` 中重新导出旧路径的所有公开符号，让现有调用方不做任何修改即可继续工作。

示例——`report/__init__.py`：

```python
# 向后兼容：所有旧调用方可以继续 from output.report_v6 import build_report
from report.sections.gate import build_gate_section
from report.sections.global_market import build_global_market_section
# ... 其他板块
from report.feishu_client import FeishuWriter

def build_report(macro, scanner_results, news_data):
    """旧接口兼容 wrapper"""
    # 内部调用拆分后的模块
    ...
```

### 6.2 旧文件保留为兼容代理

拆分完成后，原 `output/report_v6.py` 改为 thin wrapper：

```python
# output/report_v6.py — 向后兼容代理，逐步废弃
from report import build_report, FeishuWriter, push_report
__all__ = ["build_report", "FeishuWriter", "push_report"]
```

打印 deprecation warning 引导调用方迁移：

```python
import warnings
warnings.warn("output.report_v6 is deprecated, use report instead", DeprecationWarning)
```

### 6.3 `config/` 聚合导出

```python
# config/__init__.py
from config.market import *
from config.strategies import *
from config.risk import *
from config.chains import *
from config.watchlist import *
from config.paths import *

# 保持 from config import WATCHLIST 写法不变
__all__ = [
    "WATCHLIST", "INDUSTRY_CHAINS", "OPPORTUNITY_THEMES",
    "MACRO_THRESHOLDS", "FACTOR_WEIGHTS", "CPI_STRATEGY_MAP",
    # ... 全部导出
]
```

---

## 七、迁移顺序

按照依赖从少到多的原则，建议分 4 个阶段执行：

### Phase 1：基础设施（无上游依赖）

| 顺序 | 任务 | 预计耗时 | 前提 |
|------|------|---------|------|
| 1.1 | `config.py` + `domain/__init__.py` → `config/` 包 | 4h | 无 |
| 1.2 | 新增 `pyproject.toml` + `pip install -e .` | 0.5h | 1.1 |
| 1.3 | 更新所有 `from config import` / `from domain import` 调用 | 2h | 1.1 |

**Phase 1 完成后**：配置去重完成，import 路径标准化，所有模块可以通过 `from hermes_investment.config import WATCHLIST` 导入。

### Phase 2：低依赖模块

| 顺序 | 任务 | 预计耗时 | 前提 |
|------|------|---------|------|
| 2.1 | `full_asset_scanner.py` → `scanner/` 包 | 3h | Phase 1 |
| 2.2 | `news_engine.py` → `news/` 包 | 2.5h | Phase 1 |
| 2.3 | `backtest.py` → `backtest/` 包 | 3h | Phase 1 |

**Phase 2 完成后**：scanner、news、backtest 三个重灾区完成模块化。

### Phase 3：高依赖模块

| 顺序 | 任务 | 预计耗时 | 前提 |
|------|------|---------|------|
| 3.1 | `run_daily.py` → `pipeline/` 包 | 2h | Phase 1 + Phase 2 |
| 3.2 | `report_v6.py` → `report/` 包 | 5h | Phase 1 + Phase 2 + scanner + news |

**Phase 3 完成后**：日报生成链路完成模块化。

### Phase 4：收尾

| 顺序 | 任务 | 预计耗时 | 前提 |
|------|------|---------|------|
| 4.1 | 清理旧 import hack 文件（39 个 `sys.path.insert`） | 3h | Phase 1-3 |
| 4.2 | 废弃 `domain/__init__.py`（全部调用已迁到 `config/`） | 0.5h | 4.1 |
| 4.3 | 移除旧的薄 wrapper（`output/report_v6.py` 等），仅保留 `__init__.py` re-export | 1h | 4.1 |
| 4.4 | 全局 `sys.path.insert` 清零验证 | 0.5h | 4.1 |

**总计估算**：约 27 小时（3-4 个工作日，单人力）。

---

## 八、风险矩阵

| 风险 | 影响模块 | 概率 | 影响 | 缓解措施 |
|------|---------|------|------|---------|
| **config 拆分后引用断裂** | 全部 | 中 | 高 | `config/__init__.py` 聚合导出保持旧 import 写法不变；先跑通 `import config` 的冒烟测试再改其他模块 |
| **report 拆分后日报内容缺失** | report/ | 中 | 高 | 拆分前后运行一次日报生成，diff 输出内容，确保 10 个板块无遗漏 |
| **scanner 拆分后扫描结果不一致** | scanner/ | 低 | 中 | 拆分后运行 `scan_all()` 对比 JSON 输出 |
| **backtest 拆分后回测结果偏差** | backtest/ | 中 | 高 | 用 `evaluator_fixed.py` 的固定标尺跑拆分前后对比，浮点误差 < 0.001 |
| **`sys.path.insert` 清理引入循环导入** | 全局 | 中 | 中 | 逐文件替换，每改一个就跑一次 `python -c "from hermes_investment.xxx import ..."` |
| **`pyproject.toml` 与现有目录结构不兼容** | 全局 | 低 | 中 | 先在分支上验证 editable install 能正常 import 所有模块再合并 |
| **`domain/__init__.py` 移除后遗漏引用** | 全局 | 低 | 低 | `grep -r "from domain import"` 全量搜索确认清零 |
| **月度数据更新期间锁表/数据丢失** | data/ | 低 | 高 | 所有拆分操作在读缓存目录下进行，不动 `DATA_DIR/` 原始缓存文件 |

---

## 九、验证方案

每完成一个 Phase，按以下清单逐项验证：

### Phase 1 验证

- [ ] `python -c "from config import WATCHLIST, INDUSTRY_CHAINS, RISK_PARAMS; print(len(WATCHLIST))"` 输出正确
- [ ] `python -c "from domain import WATCHLIST"` 无 ImportError（re-export 生效）
- [ ] `python -c "from hermes_investment.config import FACTOR_WEIGHTS"` 无 ImportError（editable install 生效）
- [ ] 运行 `python scripts/run_daily.py --dry-run` 不报 import 错误

### Phase 2 验证

- [ ] `from scanner import scan_all; result = scan_all()` 返回完整四种资产数据
- [ ] `from news import fetch_all_news; articles = fetch_all_news()` 返回去重后的新闻列表
- [ ] `from backtest import run_backtest; result = run_backtest("faceji", pool, dates)` 返回与拆分前一致的绩效指标（浮点误差 < 0.001）

### Phase 3 验证

- [ ] `from pipeline import run_full_pipeline; run_full_pipeline(dry_run=True)` 完成四阶段不报错
- [ ] `from report import build_report; doc_id = build_report(macro, scanner, news)` 生成的飞书文档包含全部 10 个板块
- [ ] 拆分前后的日报内容完全一致（含表格、引用链接）

### Phase 4 验证

- [ ] `grep -r "sys.path.insert" . --include="*.py" | wc -l` 输出 0
- [ ] `grep -r "from domain import" . --include="*.py" | wc -l` 输出 0
- [ ] Dashboard 启动正常：`python scripts/portfolio_server.py 8686` → `curl http://localhost:8686/api/simulated | jq .success` 返回 `true`
- [ ] 全管线运行：`python scripts/run_daily.py` 无报错，飞书群收到日报推送

### 回归验证（所有 Phase 完成后）

- [ ] `python analysis/backtest.py` 四策略回测结果与拆分前一致
- [ ] `python scripts/run_factor_daily.py --top-n 30` 评分输出与拆分前一致
- [ ] `python analysis/etf_portfolio.py` ETF 组合与拆分前一致
- [ ] `python scripts/news_pipeline.py` 新闻管线产出与拆分前一致

---

## 十、与其他设计文档的交叉引用

| 关联文档 | 交叉点 |
|---------|--------|
| [工程化基础方案](./engineering-foundation.md) | `pyproject.toml` 的创建属于该文档范围，本文档依赖该产物 |
| [安全加固方案](./security-hardening.md) | `config/paths.py` 中的凭据后续由安全方案接管移除 |
| [Dashboard 重构方案](./dashboard-refactoring.md) | `portfolio_server.py` 的拆分在该文档中详细设计，本文仅做交叉引用 |
| [因子引擎统一方案](./factor-engine-unification.md) | 因子引擎统一后，`report/sections/factor_stocks.py` 的调用方式会简化 |
| [测试基础设施方案](./testing-infrastructure.md) | 每个 Phase 的验证都依赖测试方案提供的冒烟测试框架 |

---

## 附录 A：超大文件行数统计命令

```bash
# 统计所有超过 600 行的 Python 文件
find . -name "*.py" -not -path "./_archive/*" -not -path "./backup_*" \
  -exec wc -l {} \; | sort -rn | awk '$1 > 600 {print $1, $2}'
```

## 附录 B：`sys.path.insert` 文件清单

```bash
# 列出所有使用 import hack 的文件
grep -rl "sys\.path\.insert" --include="*.py" . \
  | grep -v "_archive" | grep -v "backup_"
```

## 附录 C：配置重复验证命令

```bash
# 比较 config.py 和 domain/__init__.py 的顶层变量名差异
python3 -c "
import config as c
import domain as d
c_vars = {k for k in dir(c) if k.isupper() and not k.startswith('_')}
d_vars = {k for k in dir(d) if k.isupper() and not k.startswith('_')}
print('config 独有:', sorted(c_vars - d_vars))
print('domain 独有:', sorted(d_vars - c_vars))
print('共有:', sorted(c_vars & d_vars))
"
```
