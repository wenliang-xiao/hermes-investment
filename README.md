# 面基三源融合投资系统

> **版本**: v2026.07.27 | **状态**: 蜻蜓CSC数据源集成 + 行业排名/情绪因子上线
>
> A股+港股+美股+ETF 专业量化投资系统 | 三策略并行对比 | 六层架构决策框架 | 25因子9风格引擎

[![Dashboard](http://47.85.161.255/dashboard)](http://47.85.161.255/dashboard)
[![GitHub](https://img.shields.io/badge/GitHub-hermes--investment-blue)](https://github.com/wenliang-xiao/hermes-investment)

---

## 系统架构（六层决策框架）

```
L1 宏观     → macro_engine (复苏/扩张/过热/衰退四态)
L2 配置     → PoolManager (watch→monitor→deep)
L3 选股     → FactorEngine v4.0 (25子因子→9风格→IC加权)
L4 找票     → score_batch + scan_snapshot
L5 风控     → 4层SQ (止损/集中度/CPI/滑点)
L6 纪律     → 周频限制 + 手动执行
```

因子引擎核心架构（Barra 风格行业中性化）：

```
Layer 3 (数据映射): 蜻蜓CSC财报 → baostock日线 → Tencent实时 → yfinance
Layer 2 (标准化):   截面百分位排序 + 产业链内行业中性化
Layer 1 (聚合):     IC滚动权重 + 宏观条件调整 + 贝叶斯收缩
```

---

## 📁 项目结构

```
hermes-investment/
├── config.py                 # 唯一配置入口
├── engine/          (20)     # 因子引擎v4、回测、宏观、IC权重、证据链
├── dashboard/       (14)     # FastAPI 模块化服务器 (12路由/43端点)
├── trading/         (6)      # 模拟盘引擎 (PaperAccount+T+1+费用+SQ风控)
├── news/            (4)      # 新闻管线 (东财+财联社+巨潮+情感分析)
├── etf/             (6)      # ETF发现+组合+回测+六层过滤
├── research/        (10)     # 深度研报+龙虎榜+产业链+脱钩发现
├── strategies/               # 策略纯函数 (面基/SilverQuant/TradingAgents)
├── data/                     # 数据层 (蜻蜓CSC/baostock/yfinance/路由)
│   └── sources/              # 数据源适配器 (新增: qingting_source.py)
├── domain/                   # 领域模型 (WATCHLIST、板块、新闻源)
├── docs/                     # 设计文档/PRD/SOP/策略框架
└── scripts/                  # 生产脚本 (27个)
```

---

## 🔌 数据源矩阵

| 数据源 | 类型 | 稳定性 | 延迟 | 覆盖 | 接入方式 |
|--------|------|:------:|:----:|:----:|---------|
| **蜻蜓CSC** 财报透视 | A股财报 | ⭐⭐⭐⭐⭐ | T+2~3h | 5000+A股 | REST API (券商专业) |
| **蜻蜓CSC** 个股研判 | 行业排名/F10 | ⭐⭐⭐⭐⭐ | 日频 | 全行业对比 | REST API (券商专业) |
| **蜻蜓CSC** ETF筛选 | ETF/指数估值 | ⭐⭐⭐⭐⭐ | T+4h | 全ETF | REST API (券商专业) |
| Tencent qt.gtimg | 实时行情 | ⭐⭐⭐⭐ | 实时 | A+H | HTTP API |
| baostock | 历史日线/P/E | ⭐⭐⭐ | T+1 | A股 | TCP (单标~30s) |
| yfinance | 港股/美股 | ⭐⭐⭐⭐ | 15min延迟 | 全球 | Python SDK |
| AKShare (东财) | ETF++多源 | ⭐⭐ | T+1~3 | A股 | HTTP (部分不稳定) |

**数据优先级链 (2026-07-27更新):**
```
财务数据: 蜻蜓CSC → EM(东方财富) → baostock → 0.5(中位数)
行情数据: Tencent → baostock → yfinance
ETF数据: 蜻蜓CSC → AKShare
行业排名: 蜻蜓CSC (唯一来源)
```

---

## 🧩 因子引擎 v4.0（25子因子 | 9风格因子）

### 风格因子权重结构

| 风格 | 权重 | 子因子 |
|:----|:----:|--------|
| 质量 | 0.18 | ROE, 毛利率, 负债率(逆), 经营现金流, 净利率 |
| 成长 | 0.17 | 营收增速, 净利增速, ROE加速度 |
| 动量 | 0.15 | 20日/60日/120日动量 |
| 价值 | 0.15 | PE历史百分位, PB, PE-TTM |
| 情绪/资金 | 0.12 | 量比, 换手率, **行业热度**(新) |
| 低波 | 0.12 | 20日波动率, 60日最大回撤 |
| **行业地位** | **0.10** | **PE排名, ROE排名, 毛利率排名**(新) |
| 风险 | 0.12 | PE过高风险, 60日波动风险 |
| 股息 | 0.07 | 股息率 |

### 核心特性

- ✅ 真截面百分位排序（非固定区间映射）
- ✅ IC滚动权重（lookback=6期, 数据驱动）
- ✅ 产业链内行业中性化（链条分组Pearson百分位）
- ✅ 宏观条件权重调整（4种宏观态乘数）
- ✅ 25维评分输出（非单一综合分）
- ✅ 数据质量追踪（财务+价格时效性）
- ✅ 证据链体系（因子来源/信号形成/评分理由）
- ✅ **蜻蜓CSC行业排名因子**(2026-07-27)

---

## 📊 Dashboard 面板 (12路由/43端点)

| 面板 | 路由 | 内容 |
|:----|:----|------|
| 📊 模拟盘 | `api_portfolio` | 三策略收益率曲线/持仓详情/止损位 |
| 📈 回测对比 | `api_backtest` + `api_comparison` | 净值曲线/交易日志/3段进度条 |
| 🎯 票池 | `api_pool` | 三层票池/25子因子分解/加入理由 |
| 📦 ETF | `api_etf` | 动态扫描/六层过滤/行业分组 |
| 📰 新闻 | `api_news` | 多源实时/情感分析得分 |
| 🐉 龙虎榜 | `api_dragon_tiger` | 日净买入TOP10/游资追踪 |
| 📋 深度研报 | GLM-4-Flash 驱动 | 8段结构化研报 |
| 🔬 证据 | `api_evidence` | 因子来源链/信号形成/决策理由 |
| 🎯 执行 | `api_execution` | 信号生成→审核→冲突解析→执行 |
| 📊 分层 | `api_layers` | 六层框架每层状态指示 |
| 🔗 产业链 | `api_chain` | 链条分布/热点跟踪 |
| ⚠️ 风险 | `api_risk` | 止损结构/集中度/波动率 |

---

## ⚡ 快速启动

```bash
# Dashboard
python3 dashboard/server.py 8686
# → http://localhost:8686/dashboard

# 全管线（cron每天执行）
python3 scripts/run_factor_daily.py --top-n 30   # 因子日扫
python3 scripts/run_etf_discovery.py              # ETF发现
python3 scripts/run_news_pipeline.py              # 新闻管线
python3 scripts/run_dragon_tiger.py               # 龙虎榜
python3 scripts/run_deep_research.py              # 深度研报
python3 scripts/run_trading.py                    # 模拟盘交易

# Python API
from engine.factor_engine import FactorEngine, PoolManager
engine = FactorEngine()
results = engine.score_batch(["600519", "300750", "NVDA", "0700.HK"])
```

---

## 🧩 三策略说明

| 策略 | 建仓条件 | 仓位上限 | 风控 |
|:----|---------|:--------:|------|
| 面基 | 质量/价值/成长三因子≥0.50 + MA过滤 + Kelly | 8% | 4层SQ |
| SilverQuant | 综合分≥0.50 + 不为清单通过 | 3% (¥30K) | 4层SQ |
| TradingAgents | 辩论制评分≥0.55 + Kelly | 12% | 4层SQ |

---

## 🔗 产业链映射（13条链自动分类）

```
半导体 | AI算力 | 新能源 | 消费电子 | 食品饮料 | 医药医疗
金融地产 | 周期资源 | 消费零售 | 高端制造 | 传媒互联网
公用事业 | 地产基建
```

分类规则: WATCHLIST手工链优先 → 蜻蜓CSC行业名自动映射 → "其他"

---

## 📐 开发原则

详见 [AGENTS.md](AGENTS.md):

1. **数据质量决定找票能力** — 券商专业API优先于爬虫
2. **截面标准化** — 百分位排序, 非固定区间映射
3. **IC数据驱动** — 权重来自近期IC, 不回看模型
4. **多维输出** — 不单值, 全维度暴露
5. **Fix > Feature** — 先修Bug后加功能
6. **WS0先行** — 任何改动先验证系统状态

---

## 📚 文档索引

| 文档 | 说明 |
|:----|------|
| [AGENTS.md](AGENTS.md) | 开发规范 + 数据源架构全景 (2026-07-27) |
| [策略框架](docs/STRATEGY.md) | 六层架构 / 三层漏斗 / Nick四问 |
| [SOP](docs/SOP.md) | 操作流程 / 交易纪律 |
| [工作流](docs/WORKFLOW.md) | cron管线 / 日报流水线 |
| [学习笔记](docs/LEARNING.md) | 投资方法论积累 |

---

## 🚧 待改进

- 数据质量监控面板（数据源健康度/延迟/覆盖率）
- 因子IC衰减曲线/半衰期报告
- Barra标准行业分类替代手工chain
- 多期滚动回测（牛/熊/震荡分场景）
- 集中度压力测试（Monte Carlo）
- 交易流水审计（信号→决策→执行→结果）
- 蜻蜓CSC ETF Skill深度集成

---

*面基三源融合投资系统 · 量化+价投双修 · 2026-07-27*
