# 面基 Hermes Investment

> 一个面向 A 股 / 港股 / 美股的**专业多因子量化投资系统**：三策略并行模拟盘、时点正确（point-in-time）回测、实时 Dashboard、可审计的数据与决策链路。
>
> A professional multi-factor quantitative investment system for A-share, HK, and US markets — parallel paper-trading strategies, point-in-time backtesting, a live dashboard, and auditable data & decision pipelines.

[![Dashboard](https://img.shields.io/badge/Dashboard-live-3fb950)](http://47.85.161.255/dashboard)
[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)

---

## What（这是什么）

一个把「数据 → 因子 → 策略 → 模拟盘 → 回测 → 日报」串成闭环的量化投研系统。核心能力：

- **多市场统一**：A 股 + 港股 + 美股 + ETF，一套因子引擎覆盖。
- **多因子引擎**：Barra 风格截面标准化 + IC 滚动权重 + 产业链行业中性化，输出 9 风格 / 25+ 子因子的全维度评分（非单一综合分）。
- **三策略并行**：面基（评分+趋势+Kelly）、SilverQuant（槽位建仓）、TradingAgents（辩论制），独立模拟盘 + 回测。
- **时点正确回测**：消除前视偏差（`use_point_in_time=True`），T+1 成交 + 财务报告期滞后 + IC 权重 as_of 截断。
- **可审计**：每个持仓/信号带证据链（数据层→因子层→信号层→执行层）、数据质量评级、资金守恒校验。

## Why（为什么需要它）

个人量化最大的坑不是策略，是**数据不可信**和**回测自欺**：

- 免费数据源要么限流（yfinance）、要么字段错位（腾讯 PB 索引、baostock 财务字段）、要么有幸存者偏差（只回测"还活着的龙头"）。
- 回测用"今天的评分"回放过去，CAGR 60% 是前视失真的假象。

本系统把这两个问题当作**一等公民**来治理：数据源多路 fallback + 字段校准，回测强制时点正确 + 诚实标注幸存者偏差。

## 架构

```
        ┌───────────── 数据层 (data/) ─────────────┐
        │  财务:  蜻蜓CSC → 东财 → baostock          │
        │  行情:  腾讯(qt.gtimg/ifzq) → baostock     │
        │  港股:  腾讯(ifzq/qt.gtimg)                 │
        │  美股:  Finnhub(实时) → yfinance(兜底)     │
        │  资金流: 东财 push2                        │
        └───────────────┬───────────────────────────┘
                        ▼
        ┌───────────── 因子引擎 (engine/) ───────────┐
        │  Layer 3 数据映射 → Layer 2 截面标准化      │
        │  → Layer 1 风格聚合 + IC 滚动权重           │
        │  9 风格 / 25+ 子因子 / 数据质量追踪         │
        └───────────────┬───────────────────────────┘
                        ▼
        ┌───────────── 策略 (strategies/) ───────────┐
        │  面基 · SilverQuant · TradingAgents        │
        └───────────────┬───────────────────────────┘
                        ▼
        ┌───────────── 模拟盘 + 回测 + Dashboard ────┐
        │  PaperAccount (T+1 + 费用 + SQ风控)        │
        │  Point-in-time backtest (时点评分)         │
        │  FastAPI Dashboard (12路由/43端点)         │
        └────────────────────────────────────────────┘
```

## 数据源矩阵

| 数据源 | 覆盖 | 角色 | 零鉴权 | 备注 |
|--------|------|------|:---:|------|
| **蜻蜓CSC**（中信建投） | A股财报/行业排名/ETF | 财务主源 | ❌ key | 券商专业 API，T+2~3h |
| **东财**（push2/datacenter） | 财务 fallback/资金流/龙虎榜 | 财务兜底 + 资金流 | ✅ | 有 IP 风控，内置限流 |
| **腾讯**（qt.gtimg/ifzq） | A股+港股 实时+历史 | 行情主源 | ✅ | 港股字段布局与 A股不同，已单独校准 |
| **baostock** | A股历史日线/财务 | 历史主源 | ✅ | IP 限流（198只触发），不支持北交所 |
| **Finnhub** | 美股实时报价 | 美股实时 | ❌ key | 免费 60次/分钟；历史 K线需付费 |
| **yfinance** | 美股历史 | 美股历史兜底 | ✅ | 非官方，间歇限流 |
| **AKShare** | ETF/期货 | ETF/期货 | ✅ | 行情接口不稳定，仅 ETF |

**数据优先级链：**
```
财务:   蜻蜓CSC → 东财 → baostock
A股行情: 腾讯 → baostock
港股:   腾讯 (原生，替代 yfinance 消除限流不确定性)
美股:   Finnhub(实时) → yfinance(历史兜底)
资金流: 东财 push2 (低频补充，内置 em_get 限流防封)
```

## 因子引擎

9 风格因子（IC 滚动权重驱动）：

| 风格 | 权重 | 子因子 |
|:----|:----:|--------|
| 质量 | 0.18 | ROE, 毛利率, 负债率(逆), 经营现金流, 净利率 |
| 成长 | 0.17 | 营收增速, 净利增速, ROE加速度 |
| 动量 | 0.15 | 20日/60日/120日动量 |
| 价值 | 0.15 | PE历史百分位, PB, PE-TTM |
| 情绪/资金 | 0.12 | 量比, 换手率, 行业热度, **主力资金流** |
| 低波 | 0.12 | 20日波动率, 60日最大回撤 |
| 行业地位 | 0.10 | PE排名, ROE排名, 毛利率排名 |
| 风险 | 0.12 | PE过高风险, 60日波动风险 |
| 股息 | 0.07 | 股息率 |

**核心特性：** 真截面百分位排序 · IC 滚动权重 · 产业链行业中性化 · 宏观条件权重调整 · 数据质量追踪 · 证据链体系 · ATR 自适应止损。

## 回测可信性（诚实边界）

回测结果**不可直接对外引用为实盘预期**，除非满足以下条件：

- ✅ **前视偏差已消除**：时点评分（`run_backtest(use_point_in_time=True)`）、T+1 成交、财务报告期滞后、IC 权重 as_of 截断。
- ⚠️ **幸存者偏差未完全消除**：回测股票池默认 `FIXED_UNIVERSE`（19 只当前龙头），未纳入历史退市/剔除标的（退市股数据基础已备，完整补池待做）。
- ⚠️ **数据级验证待做**：时点评分链路已通过 29+ 单元测试，但 True vs False 的收益对比需在开发机器跑 `scripts/verify_point_in_time.py`。

> 这不是一个"自主生产交易控制器"。下单、资金划拨、最终决策权始终在人。系统只提供数据、评分、信号和可审计的证据链。

## 快速开始

```bash
# 1. 环境变量（财务数据需蜻蜓CSC，美股实时需Finnhub）
cp .env.example .env
# 填入 CSC_API_KEY（蜻蜓）、FINNHUB_API_KEY（Finnhub，可选）

# 2. 依赖
pip install -r requirements.txt  # 或按 pyproject.toml

# 3. Dashboard
python3 scripts/portfolio_server.py 8686
# → http://localhost:8686/dashboard

# 4. 因子引擎
from engine.factor_engine import FactorEngine
engine = FactorEngine()
results = engine.score_batch(["600519", "300750", "NVDA", "0700.HK"])
```

## 三策略

| 策略 | 建仓条件 | 仓位上限 | 风控 |
|:----|---------|:--------:|------|
| 面基 | 质量/价值/成长三因子 + MA过滤 + Kelly | 8% | 4层SQ + ATR止损 |
| SilverQuant | 综合分≥0.50 + 槽位建仓 | 3%（¥30K） | 4层SQ + ATR止损 |
| TradingAgents | 辩论制评分 + Kelly | 12% | 强卖/止损/弱持仓 |

## 项目结构

```
hermes-investment/
├── config.py                 # 唯一配置入口
├── data/                     # 数据层 + 数据源适配器
│   └── sources/              # qingting(蜻蜓)/baostock/akshare(腾讯)/yahoo/finnhub/eastmoney
├── engine/                   # 因子引擎v4/回测/宏观/IC权重/证据链
├── strategies/               # 策略纯函数（面基/SilverQuant/TradingAgents）
├── trading/                  # 模拟盘引擎（PaperAccount+T+1+费用+SQ风控）
├── dashboard/                # FastAPI 模块化服务器（12路由/43端点）
├── domain/                   # 领域模型（WATCHLIST/板块/新闻源）
├── docs/                     # 设计文档/评审/PRD/SOP
├── scripts/                  # 生产脚本（cron管线/数据预热/验证）
└── tests/                    # 单元测试（TDD，覆盖字段解析/时点评分/风控）
```

## 开发原则

详见 [AGENTS.md](AGENTS.md)：

1. **数据质量决定找票能力** — 券商专业 API 优先于爬虫，字段校准优先于"能用就行"。
2. **Fix > Feature** — 先修 bug 后加功能；`Fix` 优先于 `Feature`。
3. **TDD** — 数据源字段解析、时点评分、风控逻辑均有测试锁定。
4. **诚实边界** — 回测偏差、数据源限制在文档中显式披露，不用"漂亮数字"掩盖缺陷。

## 文档

| 文档 | 说明 |
|:----|------|
| [AGENTS.md](AGENTS.md) | 开发规范 + 数据源架构 |
| [数据源现状分析](docs/review/data-source-status-2026-09-02.md) | 7 数据源快准全新盘点 + 差距清单 |
| [P0 时点评分方案](docs/review/p0-point-in-time-design-2026-09-01.md) | 前视/幸存者偏差消除设计 |
| [策略框架](docs/STRATEGY.md) | 六层架构 / 三层漏斗 |

## License

[MIT](LICENSE)

---

*面基 Hermes Investment · 量化 + 价投双修 · 数据可信，回测诚实。*
