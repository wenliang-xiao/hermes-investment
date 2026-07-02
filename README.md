# 面基三源融合投资系统

面基(LDS)多因子量化投资系统 — 覆盖A股+港股+美股+ETF，支持三策略并行对比。

> **最新架构**: OpenSpec v4.0 (三层因子引擎 + 组合构建器 + 执行引擎)

---

## 架构概览

```
数据层 (data_router.py) ── 前缀路由: baostock(A股) + yfinance(港美股) + AKShare(ETF/实时)
                            ↓
Layer 3 ── 数据映射层 (factor_engine.py)
             19个子因子×7个风格因子 (质量/价值/成长/动量/低波/情绪/风险)
                            ↓
Layer 2 ── 截面分位数标准化 (scipy.stats.rankdata → [0,1])
                            ↓
Layer 1 ── 风格因子聚合 + IC动态权重 + 贝叶斯收缩
             输出: 多维分数矩阵 (非单一值)
                            ↓
               ┌───────┴───────┐
               ↓               ↓
   portfolio_builder.py   PoolManager
   三策略组合构建器          三层动态票池
   · faceji (质量+价值+成长)  Watch → Monitor → Deep
   · SilverQuant (固定槽位)   每日更新
   · TradingAgents (辩论制)   自动触发深度研报
               ↓               ↓
               └───────┬───────┘
                       ↓
   ExecutionAgent — 信号生成 + 4层SQ风控 + 纪律检查 + 不为清单
                       ↓
   ┌───────────────────┼───────────────────┐
   ↓                   ↓                   ↓
ETF Portfolio     Dashboard 7面板     Traded Signals
(择时+非择时)       @8686              run_trading.py
etf_portfolio.py   /api/v2/*           (旧版并行)
```

## 核心模块

### 代码文件

| 文件 | 功能 |
|------|------|
| `analysis/factor_engine.py` | 三层因子引擎 + ICWeightSystem + PoolManager |
| `analysis/portfolio_builder.py` | 三策略组合构建器 + ExecutionAgent |
| `analysis/etf_portfolio.py` | ETF组合 (TrendFollowing择时 + RiskParity非择时) |
| `analysis/init_ic_data.py` | IC快照生成脚本 |
| `analysis/auto_deep_research.py` | 深度研报自动触发 |
| `analysis/stop_list.py` | 不为清单 (10条硬否决规则) |
| `analysis/deep_research.py` | 8维深度研报 (框架) |
| `data/data_router.py` | 统一数据路由 (@cachedio缓存) |
| `data/stock_names.py` | 股票名称映射表 |
| `scripts/run_factor_daily.py` | 因子日扫入口 |
| `scripts/run_trading.py` | 旧版交易引擎 (并行) |
| `scripts/run_report_v10.py` | 日报生成 (并行) |
| `scripts/portfolio_server.py` | Dashboard 7面板服务器 |
| `strategies/faceji.py` | 面基策略纯函数 (hl-quant范式) |
| `strategies/silverquant.py` | SilverQuant策略纯函数 |
| `strategies/tradingagents.py` | TradingAgents策略纯函数 |

## 使用方式

### 全管线一键运行

```bash
cd ~/.hermes/investment_system

# 1. 因子日扫 (全量30+)
python3 scripts/run_factor_daily.py --top-n 30

# 2. ETF组合生成
python3 analysis/etf_portfolio.py

# 3. 新闻管线
python3 scripts/news_pipeline.py

# 4. 深度研报自动触发
python3 analysis/auto_deep_research.py

# 5. IC快照 (每日一次)
python3 analysis/init_ic_data.py
```

### 因子评分

```python
from analysis.factor_engine import FactorEngine, PoolManager

engine = FactorEngine()
results = engine.score_batch(symbols)       # 批量 (截面标准化)
result = engine.score_symbol("NVDA")        # 单标 (含港股美股)

pm = PoolManager()
pools = pm.update_pools(results)            # 更新三层票池
watch = pm.load_pool("watch")               # 读取发现层
```

### 组合构建

```python
from analysis.portfolio_builder import run_full_pipeline

pipeline = run_full_pipeline(
    symbols=["300502", "688041", "NVDA"],
    strategy="faceji",           # faceji / silverquant / tradingagents
    macro_state="扩张期",
)
```

### Dashboard

```bash
# 启动服务器 (crontab @reboot自启)
python3 scripts/portfolio_server.py 8686

# 访问
http://47.85.161.255/dashboard   # 统一7面板
http://47.85.161.255/api/v2/pool # 三层票池API
http://47.85.161.255/api/v2/etf  # ETF组合API
```

## 三策略说明

| 策略 | 建仓条件 | 仓位 | 风控 | 模拟盘 |
|------|---------|------|------|--------|
| 面基 | 质量/价值/成长三因子上Score≥0.50 + MA过滤 + Kelly | 上限8% | 4层SQ风控 | 手动(富途) |
| SilverQuant | 综合分≥0.50 + 不为清单通过 | 固定¥30K(3%) | 4层SQ风控 | 全自动 |
| TradingAgents | 辩论制评分≥0.55 + Kelly | 上限12% | 4层SQ风控 | 全自动 |

## 交易纪律

- 每周最多1次交易 (高质量信号可突破软限制)
- 4层风控: HardSeller(-8%) → FallSeller(-12%) → ScoreDrop(<4.5) → MASeller(死叉)
- 不为清单: 不做空 / 不买不懂的 / 不买有硬伤的 / 地缘政治否决
- 黑天鹅豁免: 单日跌>6%

## 评分体系

详见 [docs/score_explanation.md](docs/score_explanation.md)

## 数据源

| 市场 | 数据源 | 备注 |
|------|--------|------|
| A股 | baostock + 东财(AKShare) | 日线+财报+P/E |
| 港股 | yfinance | `.HK`后缀自动路由 |
| 美股 | yfinance | 字母代码自动路由 |
| ETF | AKShare + baostock | 51/15/16前缀 |
| 宏观 | baostock + 东财 | Shibor/M2/CPI/PMI |

## 旧版兼容

旧版系统 (`factor_scanner.py` / `trading_engine.py` / `run_trading.py`) 与新系统并行运行，互不干扰。新系统输出格式不同 (多维分数 vs 单一分数)，通过Dashboard统一展示。

## Dashboard

- **http://47.85.161.255/dashboard** — 6面板: 模拟盘/回测对比/票池/ETF/新闻/日报
- 7个API端点: `/api/portfolio`, `/api/simulated`, `/api/signals`, `/api/metrics`, `/api/v2/pool`, `/api/v2/etf`, `/api/v2/news`, `/api/v2/reports`

## GitHub

```bash
git remote add origin https://github.com/wenliang-xiao/hermes-investment.git
```
