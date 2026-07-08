# 面基三源融合投资系统

> **版本**: v2026.07.08 | **状态**: 架构重构完成，Dashboard 模块化
>
> A股+港股+美股+ETF 量化投资系统，三策略并行对比，43 端点 Dashboard 实时监控。

[![Dashboard](http://47.85.161.255/dashboard)](http://47.85.161.255/dashboard)
[![GitHub](https://img.shields.io/badge/GitHub-hermes--investment-blue)](https://github.com/wenliang-xiao/hermes-investment)

---

## 📁 项目结构

```
hermes-investment/
├── config.py                 # 唯一配置入口
├── engine/          (17)     # 因子引擎、回测、宏观、评估器
├── dashboard/       (14)     # FastAPI 43端点模块化服务器
├── trading/         (6)      # 模拟盘引擎（PaperAccount+T+1+费用）
├── news/            (4)      # 新闻管道（东财+财联社+巨潮+情感分析）
├── etf/             (6)      # ETF 发现+组合+回测+六层过滤策略
├── research/        (10)     # 深度研报+龙虎榜+产业链+脱钩发现
├── strategies/               # 策略纯函数（面基/SilverQuant/TradingAgents）
├── data/                     # 数据层 + 路由
├── domain/                   # 领域模型（WATCHLIST、板块、新闻源）
├── output/                   # 日报/周报输出
├── scripts/         (27)     # 生产入口脚本
├── analysis/        (34)     # 向后兼容桥接（re-export 到新路径）
└── _archive/                 # 废弃文件归档
```

---

## 📊 Dashboard 面板

**地址**: [http://47.85.161.255/dashboard](http://47.85.161.255/dashboard)

| 面板 | 内容 | 新增能力 |
|------|------|---------|
| 📊 模拟盘 | 三策略收益率/持仓/信号 | PaperTradingEngine（T+1/涨跌停/费用） |
| 📈 回测对比 | 净值曲线/交易日志 | 统一 BacktestResult + 三阶段进度条 |
| 🎯 票池 | 三层票池 + 19子因子分解 | 加入理由自动生成 + 中美脱钩发现 |
| 📦 ETF | 动态扫描+六层过滤策略 | 全市场1537只ETF发现引擎 |
| 📰 新闻 | 多源实时新闻+情感分析 | 东财/财联社/巨潮，189条，cnsenti |
| 🐉 龙虎榜 | 每日净买入TOP10 | 游资追踪+WATCHLIST交集 |
| 📋 深度研报 | GLM-4-Flash驱动研报 | 8段结构化（基本面+技术面+资金面+政策面） |

---

## ⚡ 快速上手

```bash
# 启动 Dashboard
python3 dashboard/server.py 8686
# → http://localhost:8686/dashboard

# 全管线
python3 scripts/run_factor_daily.py --top-n 30       # 因子日扫
python3 scripts/run_etf_discovery.py                   # ETF发现
python3 scripts/run_news_pipeline.py                   # 新闻管线
python3 scripts/run_dragon_tiger.py                    # 龙虎榜
python3 scripts/run_deep_research.py                   # 深度研报
python3 scripts/run_trading.py                         # 模拟盘交易
```

### Python API

```python
# 新路径（推荐）
from engine.factor_engine import FactorEngine, PoolManager

engine = FactorEngine()
results = engine.score_batch(["300502", "NVDA", "0700.HK"])

# 旧路径仍可用（bridge）
from analysis.factor_engine import FactorEngine  # → 自动路由到 engine/
```

---

## 🧩 三策略说明

| 策略 | 建仓条件 | 仓位 | 风控 |
|------|---------|------|------|
| 面基 | 质量/价值/成长三因子≥0.50 + MA过滤 + Kelly | 上限8% | 4层SQ风控 |
| SilverQuant | 综合分≥0.50 + 不为清单通过 | 固定¥30K(3%) | 4层SQ风控 |
| TradingAgents | 辩论制评分≥0.55 + Kelly | 上限12% | 4层SQ风控 |

---

## 🌐 数据源

| 市场 | 数据源 | 备注 |
|------|--------|------|
| A股 | baostock + AKShare(东财) | 日线+财报+P/E+龙虎榜 |
| 港股 | yfinance | `.HK`后缀自动路由 |
| 美股 | yfinance | 字母代码自动路由 |
| ETF | AKShare 全市场扫描 | 1537只动态发现 + 六层过滤 |
| 新闻 | 东财 + 财联社 + 巨潮 | 多源实时，cnsenti情感分析 |

---

## 📐 开发原则

详见 [开发指南](docs/DEV_GUIDE.md) 和 [开发工作流](docs/WORKFLOW.md)：

- **目录纪律**：新文件必须按 `docs/DEV_GUIDE.md` 中的分类规则放入正确目录
- **飞书评审前置**：跨模块改动先过方案文档
- **bridge 兼容**：移动文件后原路径保留 re-export 桥接，标注 `# Bridge`
- **P0 红线**：硬编码凭证不移除 → 不过审

---

## 📚 文档

| 文档 | 说明 |
|------|------|
| [📖 快速开始](docs/README.md) | 文档索引 + 全部子文档入口 |
| [🏗️ 架构总览](docs/ARCHITECTURE.md) | 系统架构、模块清单、数据流 |
| [🔄 V2改造记录](docs/ARCHITECTURE_V2.md) | v2026.07.08 全面改造详情 |
| [📏 开发指南](docs/DEV_GUIDE.md) | 目录分类规则 + 防架构失控 |
| [📖 术语表](docs/GLOSSARY.md) | 面基/LDS/双门 核心概念 |
| [🔌 API 参考](docs/API.md) | 全部端点、结构、文件路径 |
