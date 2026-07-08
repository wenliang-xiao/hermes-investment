# 面基投资系统 · 技术参考手册

> **版本**: v2026.07.08 | **状态**: 从实际代码生成，可交叉验证
>
> 本文档是 Hermes Investment 系统的完整技术参考，涵盖所有模块、API 端点、数据流和配置。所有内容均可通过阅读对应源文件验证。

---

## 一、系统架构

### 1.1 目录树

```
hermes-investment/
├── config.py                 # 唯一配置入口 (1035行)
├── evaluator_fixed.py        # 固定评分映射 (顶层兼容)
│
├── engine/          (18)     # 因子引擎、回测、宏观、评估器
│   ├── factor_engine.py        # v4.0 多因子引擎 [0,1]分
│   ├── factor_scanner.py       # v3.1 旧引擎 [1,10]分 (已退役)
│   ├── factor_quality.py       # 数据质量追踪
│   ├── macro_engine.py         # 宏观气候引擎 (394行)
│   ├── backtest.py             # 回测核心
│   ├── backtest_types.py       # 统一回测结果 dataclass
│   ├── backtest_storage.py     # 回测结果持久化
│   ├── behavior.py             # 行为诊断 (处置效应/过度交易)
│   ├── cost_model.py           # 费用模型
│   ├── dsr_test.py             # DSR测试
│   ├── evaluator_fixed.py      # 固定评估器
│   ├── init_ic_data.py         # IC数据初始化
│   ├── portfolio_builder.py    # 组合构建器
│   ├── score_history.py        # 评分历史
│   ├── stop_list.py            # 止损清单
│   ├── strategy_comparison.py  # 策略三方对比
│   ├── trading_engine.py       # 旧版交易引擎 (兼容)
│   └── __init__.py
│
├── dashboard/       (12)     # FastAPI 服务器 + API端点
│   ├── server.py               # FastAPI app (79行)
│   ├── shared.py               # 共享工具/数据加载 (264行)
│   ├── api_portfolio.py        # 持仓/信号/模拟盘 (317行)
│   ├── api_pool.py             # 票池/因子说明 (206行)
│   ├── api_etf.py              # ETF扫描/组合 (246行)
│   ├── api_news.py             # 新闻/情绪分析 (290行)
│   ├── api_backtest.py         # 回测/三方对比 (178行)
│   ├── api_comparison.py       # /comparison 页面路由 (11行)
│   ├── api_risk.py             # 实时行情/绩效指标 (192行)
│   ├── api_dragon_tiger.py     # 龙虎榜 (79行)
│   ├── templates/              # HTML模板
│   └── __init__.py
│
├── strategies/      (5)      # 策略纯函数 (无IO/无状态)
│   ├── base.py                 # 类型定义 + 参数配置 (103行)
│   ├── faceji.py               # 面基策略 decide() (133行)
│   ├── silverquant.py          # SilverQuant 策略 (99行)
│   ├── tradingagents.py        # TradingAgents 辩论制 (123行)
│   └── __init__.py
│
├── trading/         (6)      # Paper Trader 模拟盘
│   ├── models.py               # PaperAccount/Position/Order (196行)
│   ├── engine.py               # PaperTradingEngine (549行)
│   ├── rules.py                # T+1/涨跌停/最小单位校验
│   ├── cost.py                 # 佣金/印花税/过户费/滑点
│   ├── bridge.py               # 新旧引擎桥接
│   └── __init__.py
│
├── data/            (27)     # 数据层 + 路由 + 持久化
│   ├── data_router.py          # 统一路由 (prefix-based dispatch)
│   ├── data_layer.py           # 旧A股数据层
│   ├── data_source_layer.py    # 新数据源层
│   ├── global_data.py          # 全球数据加载
│   ├── global_universe.py      # 全球标的池
│   ├── etf_universe.py         # ETF标的池定义
│   ├── stock_names.py          # 股票名称映射
│   ├── tushare_layer.py        # Tushare 数据源
│   ├── yf_data_layer.py        # Yahoo Finance 数据源
│   ├── pool/                   # 三层票池 JSON
│   ├── cache/                  # pickle 缓存文件
│   ├── backtest/               # 回测历史
│   ├── eval_cache/             # 评估缓存
│   ├── ic_cache/               # IC缓存
│   ├── hl_runs/                # 历史运行记录
│   ├── sources/                # 数据源配置
│   ├── news_cache.json         # 新闻缓存
│   ├── dragon_tiger.json       # 龙虎榜缓存
│   ├── etf_discovery.json      # ETF发现结果
│   ├── daily_report_links.json # 日报链接
│   ├── decoupling_map.json     # 脱钩映射
│   ├── chain_candidates_cache.json  # 产业链候选
│   ├── weekly_chain_summary.json    # 周度产业链总结
│   ├── news_summary.txt        # 新闻摘要
│   ├── report_20260522.json    # 报告存档
│   └── __init__.py
│
├── output/          (8)      # 日报/周报/概念引擎
│   ├── report_v6.py            # 日报 v6.1 (2638行)
│   ├── concept_engine.py       # 面基概念引擎 (881行)
│   ├── full_asset_scanner.py   # 全资产扫描 (1780行)
│   ├── fund_tracker.py         # 基金追踪 (317行)
│   ├── shadow_account.py       # 影子账户 (388行)
│   ├── strategy4_portfolio.py  # 策略4组合
│   └── __init__.py
│
├── domain/          (4)      # 领域模型 (re-export from config)
│   ├── __init__.py             # config.py re-export (65行)
│   ├── stock_universe.py       # 股票池定义
│   ├── etf_data.py             # ETF数据
│   ├── news_fetcher.py         # 新闻抓取
│
├── etf/             (6)      # ETF发现/组合/回测
│   ├── discovery.py            # 全市场ETF发现
│   ├── etf_portfolio.py        # ETF组合构建
│   ├── etf_backtest.py         # ETF回测
│   ├── allocation_strategies.py # 资产配置策略
│   ├── etf_bond_scorer.py      # ETF/债券评分
│   └── __init__.py
│
├── research/        (11)     # 深度研报/龙虎榜/产业链
│   ├── deep_research.py        # 深度研报入口
│   ├── deep_research_v2.py     # DeepResearch v2 (GLM-4-Flash)
│   ├── auto_deep_research.py   # 自动研报
│   ├── dragon_tiger.py         # 龙虎榜数据
│   ├── chain_scanner.py        # 产业链扫描
│   ├── decoupling_discovery.py # 中美脱钩发现
│   ├── research_report.py      # 研究报告
│   ├── anomaly_news.py         # 异常新闻
│   ├── knowledge_ref.py        # 知识引用
│   ├── deep_research_old.py    # 旧版研报 (保留)
│   └── __init__.py
│
├── news/            (4)      # 新闻管道
│   ├── pipeline.py             # 多源聚合管道
│   ├── fetcher.py              # 东财/财联社/巨潮
│   ├── sentiment.py            # cnsenti 情感分析
│   └── __init__.py
│
├── scripts/         (29)     # 生产入口脚本
├── analysis/        (34)     # bridge re-export (向后兼容)
├── tests/                     # 测试
├── core/                      # 核心工具 (secrets.py)
├── utils/                     # 原子 IO
├── docs/                      # 文档
└── _archive/                  # 废弃文件归档
```

### 1.2 模块依赖图

基于实际 import 链：

```
                    ┌────────────┐
                    │ config.py  │  (唯一配置事实源)
                    └──┬──┬──┬──┘
        ┌──────────────┼──┼──┼──────────────┐
        ▼              ▼  ▼  ▼              ▼
  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ engine/  │  │ domain/  │  │  data/   │
  │ 因子/回测 │  │ re-export│  │ 数据路由  │
  └────┬─────┘  └────┬─────┘  └────┬─────┘
       │              │              │
  ┌────┴──────────────┴──────────────┴────┐
  │                                       │
  ▼                  ▼                    ▼
┌───────────┐  ┌───────────┐  ┌───────────────────┐
│strategies/│  │ output/   │  │ dashboard/server  │
│ 纯决策函数 │  │ 日报/周报 │  │ FastAPI + API端点 │
└─────┬─────┘  └───────────┘  └────────┬──────────┘
      │                                 │
      ▼                                 ▼
┌───────────┐                   ┌──────────────┐
│ trading/  │ ←── bridge ────── │ data/ pool/  │
│PaperTrader│                   │ shadow.json  │
└───────────┘                   └──────────────┘
      │                                 │
      ▼                                 ▼
┌───────────┐  ┌───────────┐  ┌───────────┐  ┌──────────┐
│   etf/    │  │ research/ │  │  news/    │  │ scripts/ │
│ 发现/回测  │  │ 研报/龙虎 │  │ 聚合/情感  │  │ 生产入口  │
└───────────┘  └───────────┘  └───────────┘  └──────────┘
```

**依赖方向**: `config → data → engine → strategies → trading → dashboard`  
**关键规则**: strategies/ 纯函数零IO；config.py 是唯一配置事实源；domain/ 仅为 config 的 re-export。

### 1.3 数据流

```
[数据源]                     [处理引擎]                  [输出]
                                                          │
baostock/AKShare ──┐                                       │
                   ├──→ data_router.py ──→ factor_engine ──┼──→ data/pool/*.json
yfinance ──────────┘                    (19子因子→7风格)    │
                                                          │
东财/财联社/巨潮 ──→ news/pipeline.py ──→ news_cache.json ──┤──→ 飞书推送
                                                          │
AKShare 龙虎榜 ──→ research/dragon_tiger.py ──→ API ───────┤
                                                          │
AKShare ETF全量 ──→ etf/discovery.py ──→ etf_portfolio.json ┤
                                                          │
factor_engine ──→ strategies/faceji.py ──→ signals ────────┤
              ──→ strategies/silverquant.py ──→ signals ───┤
              ──→ strategies/tradingagents.py ──→ signals ─┤
                                                          │
trading/engine.py ←── signals ──→ shadow_account.json ─────┤
(PaperTrader: T+1+涨跌停+费用)                              │
                                                          ▼
                                          dashboard/server.py
                                          (FastAPI :8686)
```

---

## 二、模块详解

### 2.1 engine/ — 因子引擎与回测

| 文件 | 行数 | 职责 |
|------|------|------|
| `factor_engine.py` | 1357 | v4.0 多因子引擎，scipy 截面分位数 |
| `factor_scanner.py` | 634 | v3.1 旧引擎 (已退役，保留参考) |
| `factor_quality.py` | — | 数据质量追踪 |
| `macro_engine.py` | 394 | 宏观气候引擎 (货币/信用四象限) |
| `backtest.py` | — | 回测核心 |
| `backtest_types.py` | 107 | 统一回测结果 dataclass |
| `backtest_storage.py` | — | 回测结果持久化 |
| `evaluator_fixed.py` | — | 固定评估器 (ADR-001) |
| `behavior.py` | — | 行为诊断 |
| `cost_model.py` | — | 费用模型 |
| `portfolio_builder.py` | — | 组合构建 |
| `stop_list.py` | — | 止损清单 |
| `score_history.py` | — | 评分历史 |
| `init_ic_data.py` | — | IC 数据初始化 |
| `dsr_test.py` | — | DSR 测试 |
| `strategy_comparison.py` | — | 三方策略对比 |

#### FactorEngine (factor_engine.py)

核心类，v4.0 三层分离架构：

- **Layer 3 (数据映射)**: `SUB_FACTOR_DEFS` dict — 19 个子因子的数据源/公式/方向定义
- **Layer 2 (标准化)**: `standardize_cross_section()` — scipy.stats.rankdata 截面百分位→[0,1]
- **Layer 1 (风格聚合)**: `STYLE_FACTORS` dict — 19 子因子→8 风格因子，IC 加权+宏观调整+贝叶斯收缩

```python
class FactorEngine:
    def __init__(self, pool_manager=None)
    def score_batch(symbols: list[str]) -> list[dict]
    # 返回每标的: {symbol, composite, quality, value, growth, momentum, low_vol, sentiment, dividend, risk}
```

**19 子因子定义** (`SUB_FACTOR_DEFS`):

| 风格因子 | 子因子 key | 数据源 | 方向 |
|---------|-----------|--------|------|
| quality (质量) | `quality:roe` | fin_report.净资产收益率 | ↑ |
| | `quality:gross_margin` | fin_report.毛利率 | ↑ |
| | `quality:debt_ratio` | fin_report.资产负债率 | ↓ |
| | `quality:ocf_per_share` | fin_report.每股经营现金流 | ↑ |
| | `quality:net_margin` | fin_report.净利率 | ↑ |
| value (价值) | `value:pe_percentile` | derived.pe_hist_pct | ↓ |
| | `value:pb` | daily_row.pb | ↓ |
| | `value:pe_ttm` | daily_row.pe | ↓ |
| dividend (股息) | `dividend:yield` | fin_report.股息率 | ↑ |
| growth (成长) | `growth:rev_ttm` | fin_report.营业收入同比增长率 | ↑ |
| | `growth:profit_ttm` | fin_report.净利润同比增长率 | ↑ |
| | `growth:roe_trend` | derived.roe_acceleration | ↑ |
| momentum (动量) | `momentum:20d` | derived.ret_20d | ↑ |
| | `momentum:60d` | derived.ret_60d | ↑ |
| | `momentum:120d` | derived.ret_120d | ↑ |
| low_vol (低波) | `low_vol:20d_vol` | derived.vol_20d | ↓ |
| | `low_vol:max_dd_60d` | derived.max_dd_60d | ↓ |
| sentiment (情绪) | `sentiment:volume_ratio` | derived.vol_ratio_20d | ↑ |
| | `sentiment:turnover` | derived.turnover_20d | ↑ |

**风险因子** (`risk:pe_excessive`, `risk:volatility`) — 反向因子，用于扣分。

#### MacroEngine (macro_engine.py)

```python
class MacroEngine:
    def __init__(self)
    def refresh(force=False)  # 刷新宏观数据
    def determine_quadrant() -> str     # 货币/信用四象限
    def get_factor_weights() -> dict    # 动态因子权重
    def get_trend_temp() -> str         # 凉/平/温/热
    def get_strategy_switch() -> str    # on/limited/off
```

宏观判定逻辑基于 `MACRO_THRESHOLDS` (config.py L25-32):
- 货币: Shibor < 1.8% = 宽货币
- 信用: M2 > 8% = 宽信用
- 通胀: CPI > 2.5% 过热 / < 1.0% 通缩
- 景气: PMI > 52 扩张 / < 48 收缩

#### BacktestResult (backtest_types.py)

```python
@dataclass
class BacktestResult:
    strategy_name: str
    start_date: str; end_date: str
    initial_cash: float; final_value: float
    total_return_pct: float; annualized_return_pct: float
    sharpe_ratio: float; sortino_ratio: float
    max_drawdown_pct: float; calmar_ratio: float
    win_rate_pct: float; trade_count: int
    equity_curve: list[dict]    # [{date, value}]
    trades: list[dict]           # [{date, symbol, action, price, qty, pnl, reason}]
    benchmark: Optional[list[dict]]
```

### 2.2 strategies/ — 策略纯函数

| 文件 | 行数 | 职责 |
|------|------|------|
| `base.py` | 103 | Signal/PositionData/策略参数 dataclass |
| `faceji.py` | 133 | 面基策略 decide() |
| `silverquant.py` | 99 | SilverQuant 组件化策略 |
| `tradingagents.py` | 123 | TradingAgents 辩论制策略 |

**共享类型** (`base.py`):

```python
Action = Literal["BUY", "SELL", "HOLD"]
Priority = Literal["HIGH", "MED", "LOW"]

@dataclass
class Signal:
    symbol: str; action: Action; price: float
    reason: str; priority: Priority
    size_pct: float | None    # BUY仓位占比(%)
    pnl_pct: float | None     # SELL浮动盈亏(%)
    score: float | None

@dataclass
class PositionData:
    symbol: str; entry_price: float; quantity: int
    entry_date: str; peak: float | None
    current_price: float | None
```

**三策略对比**:

| 策略 | 建仓条件 | 卖出组件 | 仓位/风控 |
|------|---------|---------|----------|
| faceji | 评分≥5.0 + MA趋势过滤 + Kelly | HardSeller(-8%) / FallSeller(-12%) / ScoreDrop(<4.5) / MASeller(死叉) | Kelly动态, 上限8%, 最多8只 |
| silverquant | 评分≥5.0, 最多5候选 | HardSeller(-8%) / FallSeller(-12%) / MASeller / ScoreDrop(<4.5) | 固定¥30K/槽, 最多8只 |
| tradingagents | 辩论分≥5.5, TOP3候选 + Kelly | 辩论分<4.0 / 止损(-8%) / 弱持仓(<5.0+亏损) | Kelly动态, 上限12%, 最多6只 |

**策略参数默认值**:

| 参数 | faceji | silverquant | tradingagents |
|------|--------|-------------|---------------|
| `entry_threshold` | 5.0 | 5.0 | 5.5 (辩论) |
| `exit_threshold` | 4.5 | 4.5 (score_drop) | 4.0 (force_sell) |
| `max_positions` | 8 | 8 | 6 |
| `max_candidates` | 5 | 5 | 3 |
| `hard_stop_loss_pct` | -8.0 | -8.0 | -8.0 |
| `trailing_stop_pct` | -12.0 | -12.0 | — |
| `kelly_odds` | 2.0 | — | 1.8 |
| `kelly_fraction` | 0.5 | — | 0.5 |
| `max_position_pct` | 0.08 | — | 0.12 |

### 2.3 trading/ — 模拟盘引擎

| 文件 | 行数 | 职责 |
|------|------|------|
| `models.py` | 196 | PaperAccount / Position / Order dataclass |
| `engine.py` | 549 | PaperTradingEngine |
| `rules.py` | — | T+1 / 涨跌停 / 最小单位校验 |
| `cost.py` | — | 佣金/印花税/过户费/滑点 |
| `bridge.py` | — | 新旧引擎桥接 |

**核心数据模型**:

```python
@dataclass
class Position:
    symbol: str; name: str
    total_quantity: int       # 总持仓
    available_quantity: int   # 可用 (T+1解锁后)
    frozen_quantity: int      # 冻结 (卖出占用)
    cost_price: float         # 加权均价
    current_price: float
    buy_date: str; peak_price: float; entry_score: float
    # 计算属性: market_value, total_cost, unrealized_pnl, drawdown_from_peak

@dataclass
class Order:
    order_id: str; symbol: str
    direction: str            # "buy"/"sell"
    order_type: str           # "market"/"limit"
    price: float; quantity: int
    filled_quantity: int; filled_price: float
    status: str               # "pending"/"partial"/"filled"/"cancelled"/"rejected"
    commission: float; stamp_tax: float; transfer_fee: float; slippage_cost: float
    reason: str; reject_reason: str

@dataclass
class PaperAccount:
    account_id: str; initial_cash: float
    available_cash: float; frozen_cash: float
    positions: dict           # symbol → Position
    pending_orders: list; order_history: list
    realized_pnl: float; snapshots: list
    # 计算属性: cash, position_value, total_equity, total_pnl, return_pct
```

**PaperTradingEngine** 核心方法:

```python
class PaperTradingEngine:
    def __init__(self, initial_cash=1_000_000, account_id="")
    def submit_order(symbol, direction, price, quantity, order_type="market", reason="") -> Order
    def match_orders(market_prices: dict) -> list[Order]  # 价格撮合
    def update_prices(prices: dict)                       # 更新市价
    def get_account_summary() -> dict                     # 账户摘要
    def snapshot(date_str: str)                           # 每日快照
    def save_state(path: str) / load_state(path: str)     # 持久化
```

**交易规则** (rules.py):
- T+1: 当日买入次日可卖; `check_t1()`, `unlock_t1_positions()`
- 涨跌停: 主板±10%, 创业板/科创板±20%; `check_price_limit()`, `get_price_limit_range()`
- 板块识别: 代码首字符区分 `get_board()`: main/chinext/star
- 费用: 佣金万2.5 + 印花税千0.5(仅卖) + 过户费
- 滑点: ≥100元 8bp / ≥15元 15bp / <15元 30bp

### 2.4 dashboard/ — API 服务器

| 文件 | 行数 | 职责 |
|------|------|------|
| `server.py` | 79 | FastAPI app + 路由注册 |
| `shared.py` | 264 | 数据加载/摘要/图表数据/分类 |
| `api_portfolio.py` | 317 | 持仓/信号/模拟盘 |
| `api_pool.py` | 206 | 票池/因子说明 |
| `api_etf.py` | 246 | ETF 扫描/组合 |
| `api_news.py` | 290 | 新闻/情绪分析 |
| `api_backtest.py` | 178 | 回测/三方对比 |
| `api_comparison.py` | 11 | /comparison 页面 |
| `api_risk.py` | 192 | 实时行情/绩效 |
| `api_dragon_tiger.py` | 79 | 龙虎榜 |

**服务器启动**: `python3 dashboard/server.py 8686` → `uvicorn.run(app, host="0.0.0.0", port=8686)`

### 2.5 data/ — 数据层

| 文件 | 职责 |
|------|------|
| `data_router.py` | 统一路由: prefix-based dispatch → baostock/yfinance/AKShare |
| `data_layer.py` | 旧A股数据层 (get_stock_daily / get_financial_report 等) |
| `data_source_layer.py` | 新数据源层 |
| `global_data.py` | 全球数据加载 |
| `global_universe.py` | 全球标的池定义 |
| `etf_universe.py` | ETF标的池 (`ALL_ETF`, `ETF_BY_SYMBOL`) |
| `stock_names.py` | `STOCK_NAMES` / `ETF_NAMES` / `get_name()` |
| `tushare_layer.py` | Tushare 行情/PE历史/财务 |
| `yf_data_layer.py` | Yahoo Finance (港股/美股/指数/期货) |

**data_router.py 符号路由规则**:

| 代码模式 | 数据源 | 示例 |
|---------|--------|------|
| `.HK` 结尾 | yfinance | `0700.HK`, `9988.HK` |
| `^` 开头 | yfinance | `^GSPC`, `^HSI` |
| `=F` 结尾 (期货) | AKShare | `CL=F`, `GC=F`, `HG=F` |
| 6位纯数字 | baostock | `300502`, `600519`, `510050` |
| 已知美股短代码 | yfinance | `NVDA`, `AAPL`, `MSFT` |
| 其他 | yfinance (默认) | — |

**数据缓存** (`cachedio` 装饰器):
- 基于函数名+参数 hash 生成缓存 key
- TTL 可配置 (默认 24h)
- 存储为 pickle 文件于 `data/cache/`

### 2.6 output/ — 日报与报告

| 文件 | 行数 | 职责 |
|------|------|------|
| `report_v6.py` | 2638 | 日报 v6.1 — 全量信息·引用体系 |
| `concept_engine.py` | 881 | 面基概念引擎 (47+播客概念→分析函数) |
| `full_asset_scanner.py` | 1780 | 全资产扫描 (股债汇商+桥水四象限) |
| `fund_tracker.py` | 317 | 基金追踪 (LDS全天候+跨境ETF) |
| `shadow_account.py` | 388 | 影子账户 (模拟盘追踪) |
| `strategy4_portfolio.py` | — | 策略4组合 |

**report_v6 结构** (9 大板块):
0. LDS双门状态 (宏观门×趋势门→操作方向)
1. 全球市场全景 (股债汇商+VIX+国运线+CPI情景)
2. ETF全景 (A股35只+跨境+LDS参考组合)
3. 房价趋势
4. 产业链12链分析 (中观四层次×Perez×翻倍逻辑)
5. 多因子新票发现 (A股/美股/港股/ETF/中小市值)
6. 政经要闻与产业链影响
7. 重点票追踪
8. 调仓建议
9. 每日面基概念

**concept_engine 输入/输出**: 接受 `StockSnapshot` dataclass (PE/ROE/增速/价格等50+字段)，输出结构化 `dict` 分析结论，来源标注期数。

**full_asset_scanner 资产覆盖**:
1. LDS全天候 (红利低波25% + 纳指100 30% + 黄金25% + 豆粕20%)
2. ETF全景 (美股行业+跨境+A股，动量/波动率/费率)
3. 债券 (美债曲线+中美利差+曲线形态)
4. 商品 (黄金/原油/铜/豆粕)
5. 外汇 (美元指数+DXY/USDCNY/USDJPY/EURUSD)
6. 桥水四象限 (增长↑/↓ × 通胀↑/↓ → 资产推荐)

### 2.7 domain/ — 领域模型

| 文件 | 职责 |
|------|------|
| `__init__.py` | config.py 的完整 re-export (65行) |
| `stock_universe.py` | 股票池定义 |
| `etf_data.py` | ETF数据 |
| `news_fetcher.py` | 新闻抓取 |

**重要**: `domain/__init__.py` 已于 2026-07-07 改为纯 re-export，config.py 是唯一配置源。re-export 的符号包括: `WATCHLIST`, `INDUSTRY_CHAINS`, `CPI_STRATEGY_MAP`, `FACTOR_WEIGHTS`, `MACRO_THRESHOLDS` 等 23 个。

### 2.8 etf/ — ETF 引擎

| 文件 | 职责 |
|------|------|
| `discovery.py` | 全市场 ETF 发现 (AKShare 1537只) |
| `etf_portfolio.py` | ETF 组合构建 |
| `etf_backtest.py` | ETF 回测 |
| `allocation_strategies.py` | 资产配置策略 |
| `etf_bond_scorer.py` | ETF/债券评分 |

### 2.9 research/ — 深度研究

| 文件 | 职责 |
|------|------|
| `deep_research.py` | 深度研报入口 |
| `deep_research_v2.py` | DeepResearch v2 (GLM-4-Flash 生成8段研报) |
| `auto_deep_research.py` | 自动研报生成 |
| `dragon_tiger.py` | 龙虎榜 (`build_full_report()` / `load_cached_report()`) |
| `chain_scanner.py` | 产业链扫描 |
| `decoupling_discovery.py` | 中美脱钩比较优势发现 |
| `research_report.py` | 研究报告 |
| `anomaly_news.py` | 异常新闻检测 |
| `knowledge_ref.py` | 面基知识引用体系 |

### 2.10 news/ — 新闻管道

| 文件 | 职责 |
|------|------|
| `pipeline.py` | 多源聚合管道 |
| `fetcher.py` | 数据源: 东财个股新闻+7×24快讯+财联社电报+巨潮公告 |
| `sentiment.py` | cnsenti 中文金融情感词典 (40+关键词→sentiment/score) |

---

## 三、API 端点参考

> Base URL: `http://<host>:8686` | 所有端点返回 JSON (除页面路由)

### 3.1 页面路由

| 端点 | 方法 | 文件 | 说明 |
|------|------|------|------|
| `/` | GET | `server.py:48` | 重定向到 /dashboard |
| `/dashboard` | GET | `server.py:49` | 主 Dashboard HTML |
| `/comparison` | GET | `api_comparison.py:9` | 三方对比独立页 |
| `/score_explanation` | GET | `server.py:54` | 评分体系说明 (渲染 docs/score_explanation.md) |

总数: 40 端点 (36 API + 4 HTML)

### 3.2 模拟盘 API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/portfolio` | GET | `api_portfolio.py:14` | `data/shadow_account.json` |
| `/api/signals` | GET | `api_portfolio.py:39` | `data/trading_signals.json` |
| `/api/behavior` | GET | `api_portfolio.py:51` | `data/behavior_diagnosis.json` |
| `/api/simulated` | GET | `api_portfolio.py:61` | `data/trading_signals.json` |
| `/api/v2/portfolio/detail` | GET | `api_portfolio.py:147` | 各策略组合详细持仓 |
| `/api/v2/portfolio/netvalue` | GET | `api_portfolio.py:265` | 各策略净值曲线 |
| `/api/v2/reports` | GET | `api_portfolio.py:310` | `data/daily_report_links.json` (日报链接) |

**`/api/portfolio` 返回结构**:
```python
{
    "summary": {
        "capital": float, "cash": float, "total_value": float,
        "total_pnl": float, "total_pnl_pct": float, "realized_pnl": float,
        "positions": list[{
            "symbol", "name", "entry_price", "current_price", "quantity",
            "cost", "market_value", "pnl", "pnl_pct", "peak", "dd_from_peak",
            "hold_days", "entry_score"
        }]
    },
    "chart": list[{"date": str, "value": float}],
    "history": [...], "updated_at": str, "history_count": int
}
```

**`/api/simulated` 返回结构**:
```python
{
    "date": str, "generated_at": str,
    "portfolios": {
        "faceji": {
            "label": "面基", "color": "#58a6ff",
            "style": "面基(评分+趋势+Kelly+SQ风控)",
            "cash": float, "invested": float, "total_value": float,
            "total_return": float, "position_count": int,
            "positions": list[{"symbol","name","entry_price","current_price","quantity","pnl_pct","dd_from_peak"}],
            "signals": list[{"symbol","name","action","price","reason","priority","score"}]
        },
        "silverquant": {...}, "tradingagents": {...}
    },
    "user_signals": [...]
}
```

### 3.3 绩效与行情 API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/metrics` | GET | `api_risk.py:33` | `data/shadow_account.json` |
| `/api/realtime` | GET | `api_risk.py:13` | `scripts/realtime_price.py` |
| `/api/realtime/positions` | GET | `api_risk.py:23` | `scripts/realtime_price.py` |
| `/api/risk` | GET | `api_risk.py:116` | 综合风险分析 |

**`/api/metrics` 返回结构**:
```python
{
    "sharpe_ratio": float, "sortino_ratio": float,
    "max_drawdown_pct": float, "total_return_pct": float,
    "win_rate_pct": int, "total_trades": int,
    "max_win_streak": int, "max_loss_streak": int,
    "position_count": int, "capital": float, "total_value": float
}
```

### 3.4 票池 API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/v2/pool` | GET | `api_pool.py:11` | `data/pool/watch.json` / `monitor.json` / `deep.json` |
| `/api/v2/pool/by_market` | GET | `api_pool.py:33` | 同上 + `shared._classify_market()` |
| `/api/v2/factor_explain` | GET | `api_pool.py:60` | 内置因子定义 (硬编码) |
| `/api/v2/discovery/decoupling` | GET | `api_pool.py:129` | `data/decoupling_map.json` (脱钩发现) |
| `/api/v2/research/report/{symbol}` | GET | `api_pool.py:173` | 深度研报 (单标的) |
| `/api/v2/research/reports` | GET | `api_pool.py:192` | 深度研报列表 |

**`/api/v2/pool` 返回结构**:
```python
{
    "watch": list[{"symbol","name","chain","score","scores":{...}}],
    "monitor": [...],
    "deep": [...]
}
```

### 3.5 ETF API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/v2/etf` | GET | `api_etf.py:11` | `data/etf_portfolio.json` |
| `/api/v2/etf/universe` | GET | `api_etf.py:21` | `data/etf_universe.py` (ALL_ETF) |
| `/api/v2/etf/scan` | GET | `api_etf.py:38` | `data/etf_universe.py` + `data_router.get_history()` |
| `/api/v2/etf/detail/{symbol}` | GET | `api_etf.py:82` | `data_router.get_history()` |
| `/api/v2/etf/portfolio` | GET | `api_etf.py:155` | ETF组合配置数据 |
| `/api/v2/etf/discovery` | GET | `api_etf.py:173` | `data/etf_discovery.json` (发现结果) |
| `/api/v2/etf/scan_full` | GET | `api_etf.py:214` | 全量ETF扫描 (性能较重) |

**`/api/v2/etf/universe` 参数**: `category` (可选筛选) / `region` (可选筛选)

**`/api/v2/etf/scan` 返回**:
```python
{
    "total": int, "scan_date": str,
    "etfs": list[{
        "symbol","name","category","region","benchmark",
        "price","ma20","ma60","trend","trend_strength",
        "ret_20d","ret_60d","vol_20d",
        "is_timing","is_rp"
    }]
}
```

**`/api/v2/etf/detail/{symbol}` 返回**: 包含 MA5/10/20/60/120、历史回报、组合归属、ETF 元信息。

### 3.6 新闻 API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/v2/news` | GET | `api_news.py:89` | `data/news_cache.json` |
| `/api/v2/news/refresh` | GET | `api_news.py:159` | 强制刷新新闻缓存 |
| `/api/v2/news/sources` | GET | `api_news.py:177` | 新闻源元信息 |
| `/api/v2/news/sentiment` | GET | `api_news.py:217` | 情绪分析统计数据 |
| `/api/v2/news/status` | GET | `api_news.py:261` | 新闻管道状态 |

**`/api/v2/news` 参数**: `category` (可选筛选) / `sentiment` (可选筛选) / `limit` (默认20) / `offset`

**`/api/v2/news` 返回结构**:
```python
{
    "total": int, "timestamp": str, "freshness": "fresh"/"stale"/"expired",
    "days_stale": int,
    "categories": list[str],  # 可用新闻类别
    "sentiment_summary": dict,  # 情绪分析汇总
    "summary": str,
    "items": list[{
        "category","category_label","category_emoji",
        "title","content","link","source","published",
        "sentiment","score","keywords_found"
    }]
}
```

### 3.7 回测 API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/comparison` | GET | `api_backtest.py:53` | `engine/strategy_comparison.py` |
| `/api/v2/backtest` | GET | `api_backtest.py:70` | `engine/backtest_storage.py` |
| `/api/v2/backtest/strategies` | GET | `api_backtest.py:78` | 内置策略列表 |
| `/api/v2/backtest/custom` | GET | `api_backtest.py:95` | 自定义回测 (指定策略/标的/区间) |
| `/api/v2/backtest/{run_id}` | GET | `api_backtest.py:171` | 单次回测详情 |

**`/api/comparison` 参数**: `days` (默认60, 范围7-365)

### 3.8 龙虎榜 API

| 端点 | 方法 | 文件:行 | 数据源 |
|------|------|---------|--------|
| `/api/v2/dragon_tiger` | GET | `api_dragon_tiger.py:8` | `research/dragon_tiger.py` + `data/dragon_tiger.json` |

**参数**: `refresh` (true/false, 是否强制从 AKShare 拉取)

---

## 四、数据文件清单

### 4.1 运行时 JSON 文件

| 文件路径 | 格式 | 生产者 | 消费者 | 更新频率 |
|---------|------|--------|--------|---------|
| `data/shadow_account.json` | JSON | `output/shadow_account.py` | `/api/portfolio`, `/api/metrics` | 每笔交易 |
| `data/trading_signals.json` | JSON | `scripts/run_trading.py` | `/api/simulated`, `/api/signals` | 每日 |
| `data/behavior_diagnosis.json` | JSON | `engine/behavior.py` | `/api/behavior` | 每日 |
| `data/news_cache.json` | JSON | `news/pipeline.py` | `/api/v2/news` | 30分钟 |
| `data/dragon_tiger.json` | JSON | `research/dragon_tiger.py` | `/api/v2/dragon_tiger` | 每日 |
| `data/etf_portfolio.json` | JSON | `etf/etf_portfolio.py` | `/api/v2/etf` | 每日 |
| `data/etf_discovery.json` | JSON | `etf/discovery.py` | `/api/v2/etf/scan` | 每日 |
| `data/daily_report_links.json` | JSON | `scripts/push_daily_to_feishu.py` | `/api/v2/reports` | 每日 |
| `data/decoupling_map.json` | JSON | `research/decoupling_discovery.py` | Dashboard 脱钩面板 | 按需 |
| `data/chain_candidates_cache.json` | JSON | `research/chain_scanner.py` | 产业链分析 | 按需 |
| `data/weekly_chain_summary.json` | JSON | `scripts/run_weekly.py` | 周期报告 | 每周 |
| `data/macro_engine_cache.json` | JSON | `engine/macro_engine.py` | 宏观分析 | 7天 |
| `data/news_summary.txt` | TEXT | `news/pipeline.py` | 新闻摘要 | 每次运行 |
| `data/report_20260522.json` | JSON | `output/report_v6.py` | 历史报告存档 | 一次 |

### 4.2 三层票池

| 文件 | 内容 |
|------|------|
| `data/pool/watch.json` | 发现层票池 |
| `data/pool/monitor.json` | 盯住层票池 |
| `data/pool/deep.json` | 深度层票池 |

### 4.3 缓存目录

| 目录 | 格式 | 内容 |
|------|------|------|
| `data/cache/` | pickle | `data_router.cachedio` 数据缓存 |
| `data/backtest/` | JSON | 回测结果持久化 |
| `data/eval_cache/` | — | 评估缓存 |
| `data/ic_cache/` | — | IC 缓存 |
| `data/hl_runs/` | — | 历史运行记录 |
| `data/sources/` | — | 数据源配置 |

---

## 五、评分引擎

### 5.1 双引擎并存

| 引擎 | 文件 | 版本 | 输出范围 | 方法 | 使用场景 |
|------|------|------|---------|------|---------|
| `FactorEngine` | `engine/factor_engine.py` | v4.0 | [0,1] | scipy rankdata 截面分位数 | `run_factor_daily.py`, 新开发 |
| `FactorScanner` | `engine/factor_scanner.py` | v3.1 | [1,10] | 固定区间线性插值 | `run_daily.py` (兼容) |

### 5.2 FactorEngine v4.0 评分流程

```
原始数据 (fin_report / daily_row)
    │
    ▼
Layer 3: 数据映射 (SUB_FACTOR_DEFS)
    19 子因子原始值
    │
    ▼
Layer 2: 截面标准化 (standardize_cross_section)
    scipy.stats.rankdata → 百分位 → [0,1]
    │
    ▼
Layer 1: 风格聚合 (STYLE_FACTORS)
    19 子因子 → 8 风格因子 (等权平均子因子)
    IC 滚动权重 → 宏观条件调整 → 贝叶斯收缩
    │
    ▼
composite: [0,1] 综合分
    │
    ▼
score_to_signal(): BUY(≥0.48) / HOLD / SELL(<0.25)
```

### 5.3 权重系统

**默认风格权重** (`STYLE_FACTORS`):

| 风格因子 | 默认权重 | 子因子数 |
|---------|---------|---------|
| quality | 0.18 | 5 |
| growth | 0.17 | 3 |
| value | 0.15 | 3 |
| momentum | 0.15 | 3 |
| low_vol | 0.12 | 2 |
| risk | 0.12 | 2 |
| sentiment | 0.10 | 2 |
| dividend | 0.07 | 1 |

**宏观动态调整** (`MACRO_WEIGHT_ADJUST`):

| 宏观状态 | quality | growth | momentum | low_vol | value | dividend |
|---------|---------|--------|----------|---------|-------|----------|
| 复苏期 | ×1.3 | ×1.1 | ×0.8 | ×0.7 | ×1.2 | ×1.4 |
| 扩张期 | ×0.8 | ×1.4 | ×1.5 | ×0.6 | ×0.7 | ×0.6 |
| 过热期 | ×1.1 | ×0.7 | ×0.7 | ×1.2 | ×1.3 | ×1.2 |
| 衰退期 | ×1.4 | ×0.5 | ×0.5 | ×1.5 | ×0.7 | ×1.5 |

### 5.4 信号阈值

`score_to_signal()` (factor_engine.py L103-123):

| 综合分 | 信号 |
|--------|------|
| ≥ 0.63 | STRONGBUY 🟢强买入 |
| ≥ 0.48 | BUY 🟢买入 |
| ≥ 0.35 | HOLD ⚪持有 |
| ≥ 0.25 | SELL 🔴卖出 |
| < 0.25 | STRONGSELL 🔴强卖出 |

**评分区间转换**: `convert_v3_to_v4()`: v3 [1,10] → v4 [0,1] 线性映射; `convert_v4_to_v3()`: 反向映射。

---

## 六、策略详解

### 6.1 面基策略 (faceji.py)

**`decide(score_map, tech_map, price_map, positions, cash, config) → list[Signal]`**

建仓条件:
1. 不在持仓列表 (`s not in held`)
2. 评分≥5.0 (`cfg.entry_threshold`)
3. MA趋势过滤: `ma60d > ma20d` 或 `score ≥ 5.5` (豁免)
4. 排序取 TOP5 候选
5. Kelly 仓位: `kelly = max(0, (wp*kelly_odds - (1-wp)) / kelly_odds) * 0.5`

清仓 (4层风控，按优先级):
1. **HardSeller**: 浮动盈亏 ≤ -8%
2. **FallSeller**: 从峰值回落 ≥ 12%
3. **ScoreDropSeller**: 评分 < 4.5
4. **MASeller**: MA20 < MA60 死叉 + 评分<5.0 + 未深亏(> -5%)

### 6.2 SilverQuant 策略 (silverquant.py)

**`decide(score_map, tech_map, price_map, positions, cash, config) → list[Signal]`**

建仓条件:
1. 不在持仓
2. 评分≥5.0
3. 排序取 TOP5 候选
4. 固定¥30,000/槽位 (3%仓位)

清仓 (4层卖出组件，按优先级):
1. **HardSeller**: -8%
2. **FallSeller**: 峰值回落 -12%
3. **MASeller**: MA死叉 + 亏损未达 -5%豁免
4. **ScoreDropSeller**: 评分 < 4.5

### 6.3 TradingAgents 策略 (tradingagents.py)

**`decide(score_map, tech_map, price_map, positions, cash, config) → list[Signal]`**

辩论制评分 (`_debate_score()`):
```python
bull = sc*0.5 + ts*0.5           # 基本面+技术面
bear = sc - bp                    # MACD死叉 +1.0, RSI>70 +0.5
neut = sc
final = max(bull,bear,neut) → 加权平均
```

建仓条件:
1. 不在持仓
2. 辩论分 ≥ 5.5
3. 全市场 TOP3 候选
4. Kelly 仓位: `wp = min(ds/10, 0.8)`, odds=1.8, half-kelly

清仓条件:
1. 辩论分 < 4.0 (强卖)
2. 硬止损 -8%
3. 弱持仓: 辩论分 < 5.0 + 亏损中

---

## 七、配置参考

### 7.1 路径与凭据

```python
# config.py
BASE = Path(os.environ.get("HERMES_BASE", Path(__file__).parent))
DATA_DIR = BASE / "data"
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
FEISHU_FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")
FEISHU_USER_OPENID = os.environ.get("FEISHU_USER_OPENID", "")
FEISHU_GROUP_CHAT = os.environ.get("FEISHU_GROUP_CHAT", "")
```

### 7.2 风控参数

```python
RISK_PARAMS = {
    "stop_loss_pct": 0.08,             # 8%硬止损
    "take_profit_tier1": 0.15,         # 15%减半仓
    "take_profit_tier2": 0.30,         # 30%清仓
    "max_single_position": 0.02,       # 单笔最大2%
    "max_total_positions": 8,          # 最多8只
    "rebalance_threshold": 0.05,       # 偏离5%再平衡
    "max_drawdown_warn": 0.15,         # 回撤>15%警告
    "max_drawdown_liquidate": 0.25,    # 回撤>25%清盘线
}
```

### 7.3 宏观阈值

```python
MACRO_THRESHOLDS = {
    "shibor_loose": 1.8,           # Shibor < 1.8% = 宽货币
    "m2_loose": 8.0,               # M2 > 8% = 宽信用
    "cpi_hot": 2.5,                # CPI > 2.5% = 过热
    "cpi_cold": 1.0,               # CPI < 1.0% = 通缩
    "pmi_hot": 52,                 # PMI > 52 = 扩张
    "pmi_cold": 48,                # PMI < 48 = 收缩
}
```

### 7.4 宏观因子权重矩阵 (v3.1)

```python
FACTOR_WEIGHTS = {
    "复苏期": {"质量":0.23, "价值":0.18, "成长":0.20, "低波":0.12, "红利":0.15, "动量":0.12},
    "扩张期": {"质量":0.13, "价值":0.10, "成长":0.28, "低波":0.07, "红利":0.08, "动量":0.34},
    "过热期": {"质量":0.18, "价值":0.22, "成长":0.10, "低波":0.18, "红利":0.22, "动量":0.10},
    "衰退期": {"质量":0.28, "价值":0.08, "成长":0.05, "低波":0.32, "红利":0.22, "动量":0.05},
    "default":{"质量":0.23, "价值":0.17, "成长":0.17, "低波":0.17, "红利":0.17, "动量":0.09},
}
```

### 7.5 CPI驱动策略映射

```python
CPI_STRATEGY_MAP = {
    "cpi_falling_below1":       "limited"  (CPI<1%通缩, 50%仓位),
    "cpi_below1_improving":     "on"       (通缩改善, 60%),
    "cpi_1_to_2":               "on"       (温和通胀, 75%),
    "cpi_2_to_3":               "on"       (温和偏高, 65%),
    "cpi_2_to_3_accelerating":  "limited"  (通胀加速, 40%),
    "cpi_above3":               "limited"  (通货膨胀, 30%),
}
```

### 7.6 北向资金信号

```python
NORTHBOUND_CONFIG = {
    "strong_inflow_daily": 30,      # 单日>30亿=强流入
    "mild_inflow_daily": 5,         # 单日>5亿=温和
    "outflow_daily": -10,           # 单日>10亿流出=警示
    "strong_5d_cumulative": 100,    # 5日>100亿=趋势流入
    "weak_5d_cumulative": -50,      # 5日<-50亿=趋势流出
}
```

### 7.7 缓存TTL

```python
CACHE_TTL = {
    "macro_monthly": 86400 * 7,     # CPI/PMI: 7天
    "index_daily": 3600,            # 指数: 1小时
    "stock_daily": 1800,            # 个股: 30分钟
    "reference_data": 86400,        # 基础信息: 24小时
    "news": 1800,                   # 新闻: 30分钟
    "northbound": 3600,             # 北向: 1小时
}
```

### 7.8 WATCHLIST 结构

WATCHLIST (config.py L287-413) 包含 ~100 只标的，覆盖:
- A股龙头 (AI算力/半导体/机器人/医药/消费/金融/军工/电网)
- 港股 (腾讯/阿里/中芯国际/美团/小米等)
- 美股 (NVDA/TSM/MSFT/GOOGL/META/AVGO/LLY等)
- ETF (红利低波/纳指100/黄金/豆粕/半导体/军工/国债/债券)
- 贵金属/大宗 (GLD/GC=F/HG=F/CL=F)

每标的含: `name`, `chain` (产业链归属), `focus` (关注理由), `tier` (核心/关注/底仓/追踪)

**已知重复条目** (AGENTS.md 记录): GLD (L352/404), HG=F (L354/406), CL=F (L355/407)

### 7.9 产业链定义

15条产业链 (`INDUSTRY_CHAINS`, config.py L542-940):
1. 英伟达算力链 — 光模块/PCB/服务器/GPU
2. 台积电先进制程链 — 设备/材料/CoWoS
3. 存储/HBM链 — DRAM/NAND/封装基板
4. AI应用/Agent链 — SaaS/Agent平台
5. 新能源链 — 电池/逆变器/光伏/储能
6. 半导体链 — 全链 (设备/材料/设计/封测)
7. 国产替代/信创链 — OS/数据库/工业软件
8. 医药创新链 — 创新药/CXO/器械
9. 军工链 — 航空/导弹/雷达/无人机
10. 机器人/自动化链 — 减速器/伺服/传感器
11. 消费电子链 — AI手机/折叠屏/结构件
12. 数据/云计算链 — IDC/光通信/液冷
13. 苹果产业链 — iPhone供应链+AAPL
14. 新能源汽车链 — 整车+三电+智驾
15. 物理AI链 — 数字孪生→感知→决策全栈

每条链含: `keywords`, `high_margin_keywords`, `chain_position`, `symbols`, `description`, `perez_stage`, `meso_layer` (中观四层次), `lds_logic`, `nick_questions`, `edge`, `catalyst`, `risk_factors`

### 7.10 国产替代评分

`DOMESTIC_SUB_THEMES` (config.py L948-998): 7个子主题
- 半导体设备 (国产化率18%, 脱钩分9.5)
- 工业软件 (12%, 9.0)
- 机器人零部件 (25%, 8.5)
- AI基础设施 (15%, 8.0)
- 存储芯片 (8%, 8.5)
- 操作系统数据库 (20%, 7.5)
- 军工电子 (60%, 7.0)

`get_domestic_sub_score(company_keywords, sector) → float`: 关键词匹配 × 脱钩分 = [0,10] 分。

---

## 八、数据源

| 市场 | 数据源 | 符号规则 | 路由 |
|------|--------|---------|------|
| A股日线 | baostock | 6位纯数字 | `data_router._detect_source()` |
| A股财报/PE/MACD | AKShare (东财) + Tushare | 同上 | `data_layer.py` |
| A股ETF | baostock | 51/15/16/159开头 | 同上 |
| 港股 | yfinance | `.HK` 后缀 | `data_router` → yf |
| 美股 | yfinance | 字母代码 | `data_router` → yf |
| 美股ETF | yfinance | 短代码 (QQQ/SPY/TLT等) | yf |
| 全球指数 | yfinance | `^` 开头 (^GSPC/^HSI/^IXIC) | yf |
| 商品期货 | AKShare | `=F` 结尾 (CL=F/GC=F/HG=F) | `data_router` → akshare_futures |
| 汇率 | yfinance | CNY=X/DXY | yf |
| 美债收益率 | yfinance | ^TNX/^FVX | yf |
| 新闻 | 东财 + 财联社 + 巨潮 | HTTP API | `news/fetcher.py` |
| 龙虎榜 | AKShare | `stock_em_market_daily_lhb_detail_daily` | `research/dragon_tiger.py` |
| 北向资金 | AKShare | `stock_em_hsgt_north_net_flow_in_em` | `config.NORTHBOUND_CONFIG` |

---

## 九、生产脚本

| 脚本 | 入口 | 用途 |
|------|------|------|
| `run_daily.py` | Cron 08:30/18:00 | 日报生成+飞书推送 |
| `run_weekly.py` | Cron 每周 | 周报 (产业链总结) |
| `run_factor_daily.py` | Cron 每日 | 因子日扫 top-n |
| `run_etf_discovery.py` | 手动/Cron | ETF全市场发现 |
| `run_news_pipeline.py` | 手动/Cron | 新闻多源聚合 |
| `run_deep_research.py` | 手动 | 深度研报生成 |
| `run_dragon_tiger.py` | 手动 | 龙虎榜数据抓取 |
| `run_trading.py` | Cron 每日 | 模拟盘交易执行 |
| `run_backtest.py` | 手动 | 回测运行 |
| `run_behavior.py` | 手动 | 行为诊断 |
| `pull_all_data.py` | 手动 | 数据预热 |
| `portfolio_server.py` | 手动 | Dashboard 启动 (bridge) |

---

## 十、已知严重 Bug

参见 `.opencode/AGENTS.md` 和 `docs/review/final-deep-audit-2026-07-03.md`:

| Bug | 文件 | 行号 | 状态 |
|-----|------|------|------|
| 财务abs()抹消经营现金流正负号 | `engine/factor_scanner.py` | L60 | ✅ 已修 |
| MA方向反向 | `strategies/faceji.py` | L62 | ✅ 已修 |
| 模拟盘SELL不检查TradeCalendar | `engine/trading_engine.py` | L476-496 | ✅ 已修 |
| MACD判定恒真 | `scripts/run_trading.py` | L98 | ✅ 已修 |

---

## 十一、版本约定

- Tag: `vYYYY.MM.DD`
- Commit: 中文, `feat:` / `fix:` / `refactor:` / `docs:` 前缀
- Dashboard: `python3 dashboard/server.py 8686` → http://47.85.161.255/dashboard
- 飞书方案文档: 默认 `wiki_space: "my_library"`
