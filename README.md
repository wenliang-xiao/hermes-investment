# 面基三源融合投资系统

> **版本**: v2026.07.02 | **状态**: 线上稳定运行
>
> A股+港股+美股+ETF 量化投资系统，三策略并行对比，7面板 Dashboard 实时监控。

[![Dashboard](http://47.85.161.255/dashboard)](http://47.85.161.255/dashboard)
[![GitHub](https://img.shields.io/badge/GitHub-hermes--investment-blue)](https://github.com/wenliang-xiao/hermes-investment)

---

## 📚 文档导航

| 文档 | 说明 |
|------|------|
| [📖 快速开始](docs/README.md) | 文档索引 + 全部子文档入口 |
| [🏗️ 架构总览](docs/ARCHITECTURE.md) | 系统架构、模块清单、数据流、ADRs |
| [📖 术语表](docs/GLOSSARY.md) | 面基/LDS/双门/不为清单 等核心概念 |
| [🔌 API 参考](docs/API.md) | 全部端点、数据结构、数据文件路径 |
| [🛠️ 开发工作流](docs/WORKFLOW.md) | 飞书评审流程、质量标准、版本约定 |
| [📋 变更日志](CHANGELOG.md) | 完整版本历史 |

## 📊 Dashboard

**地址**: [http://47.85.161.255/dashboard](http://47.85.161.255/dashboard)

7 面板统一视图：

| 面板 | 内容 | 数据源 |
|------|------|--------|
| 📊 模拟盘 | 三策略收益率/持仓明细/信号 | `/api/simulated` |
| 📈 回测对比 | 三方对比/交易日志/净值曲线 | `/api/comparison` |
| 🎯 票池 | Watch/Monitor/Deep 三层+7因子评分 | `/api/v2/pool` |
| 📦 ETF | 趋势跟随+风险平价组合 | `/api/v2/etf` |
| 📰 新闻 | 多分类板块新闻 | `/api/v2/news` |
| 📋 日报 | 历史日报链接 | `/api/v2/reports` |

## ⚡ 快速上手

### 启动服务器

```bash
cd ~/.hermes/investment_system

# 方式1: 通过桥接脚本（兼容旧版）
python3 scripts/portfolio_server.py 8686

# 方式2: 直接运行 dashboard 模块
python3 dashboard/server.py 8686

# 方式3: 通过 uvicorn
uvicorn scripts.portfolio_server:app --host 0.0.0.0 --port 8686
uvicorn dashboard.server:app --host 0.0.0.0 --port 8686
# → http://localhost:8686/dashboard
```

### 全管线运行

```bash
# 1. 因子日扫
python3 scripts/run_factor_daily.py --top-n 30

# 2. ETF组合
python3 analysis/etf_portfolio.py

# 3. 新闻管线
python3 scripts/news_pipeline.py

# 4. Dashboard
python3 scripts/portfolio_server.py 8686
```

### Python API

```python
from analysis.factor_engine import FactorEngine, PoolManager

engine = FactorEngine()
results = engine.score_batch(["300502", "NVDA", "0700.HK"])  # 批量评分

pm = PoolManager()
pool = pm.update_pools(results)                # 更新三层票池
watch = pm.load_pool("watch")                   # 读取发现层
```

## 🧩 三策略说明

| 策略 | 建仓条件 | 仓位 | 风控 |
|------|---------|------|------|
| 面基 | 质量/价值/成长三因子≥0.50 + MA过滤 + Kelly | 上限8% | 4层SQ风控 |
| SilverQuant | 综合分≥0.50 + 不为清单通过 | 固定¥30K(3%) | 4层SQ风控 |
| TradingAgents | 辩论制评分≥0.55 + Kelly | 上限12% | 4层SQ风控 |

## 🌐 数据源

| 市场 | 数据源 | 备注 |
|------|--------|------|
| A股 | baostock + AKShare(东财) | 日线+财报+P/E |
| 港股 | yfinance | `.HK`后缀自动路由 |
| 美股 | yfinance | 字母代码自动路由 |
| ETF | AKShare + baostock | 趋势跟随+风险平价 |
| 新闻 | AKShare + GLM-4-Flash | 多源分级聚合 |

## 📐 开发原则

详见 [开发工作流](docs/WORKFLOW.md)：

- **飞书评审前置**：所有改动必须先过飞书蓝图→评论→共识流程
- **文档同步**：每次 PR 必须更新对应 `docs/` 文档
- **版本锁定**：验收通过后打 tag (`vYYYY.MM.DD`)
- **P0 红线**：硬编码凭证不移除/零测试 → 不过审

## 🔗 相关链接

- [GitHub 仓库](https://github.com/wenliang-xiao/hermes-investment)
- [飞书工作流 v4（四合一）](https://www.feishu.cn/docx/AYSadQ7QhoexZ3x64oaczthhnNh)
- [飞书问题追溯表](https://www.feishu.cn/docx/S9A6dzJFbo7wWqxJ12Uc7K7Fn8y)
- [Dashboard](http://47.85.161.255/dashboard)
