# 面基投资系统 架构文档

> 版本: v2026.07.08 | 重构后架构，`dashboard/` 模块化拆分

## 一、系统定位

面基投资系统是一套**量化+价投双修**的个人投资决策辅助系统。核心使命：

1. **发现**：通过多因子扫描从 100+ 关注池中筛选出高评分标的
2. **盯住**：通过持续评分追踪，将高评分标的逐步提升至 Monitor/Deep 层
3. **深度**：通过 8 维深度研报框架（链定位/DCF/凯利/Nick 四问/贝叶斯/风险/面基引用）分析核心持仓

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                        用户交互层                             │
│  dashboard/     (FastAPI :8686, 模块化拆分)                  │
│  ├── server.py          主入口 + 静态路由                     │
│  ├── api_portfolio.py   模拟盘/信号 API                       │
│  ├── api_pool.py        票池/因子 API                        │
│  ├── api_etf.py         ETF 扫描/组合 API                    │
│  ├── api_news.py        新闻/情感 API                        │
│  ├── api_backtest.py    回测/对比 API                        │
│  └── api_risk.py        风险/指标 API                        │
│  飞书日报    GitHub                                          │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        数据管线层                             │
│  data/data_router.py ─── baostock (A股) ─── 76只×5年缓存    │
│                      ─── yfinance   (港美股)                  │
│                      ─── akshare    (新闻/ETF)               │
│  data/data_source_layer.py (带DataResult质量标注)            │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        因子引擎层                             │
│  analysis/factor_engine.py ─── 19子因子 → 7风格因子          │
│  scripts/run_factor_daily.py ─── 每日扫描 → pool/*.json      │
│  评分体系: 质量/价值/成长/动量/低波/情绪/股息/风险           │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        策略执行层                             │
│  strategies/    面基 · SilverQuant · TradingAgents (纯函数)  │
│  analysis/trading_engine.py ─── 三策略模拟盘调度              │
│  analysis/strategy_comparison.py ─── 三方对比                │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        评估回测层                             │
│  evaluator_fixed.py ─── 固定标尺 Train/Test/Walk-Forward     │
│  analysis/backtest.py ─── 多策略回测引擎 v2.0                │
└─────────────────────────────────────────────────────────────┘
```

## 三、核心模块清单

| 模块 | 路径 | 职责 |
|------|------|------|
| Dashboard 入口 | `dashboard/server.py` | FastAPI 主入口，路由注册 |
| Dashboard 模拟盘 | `dashboard/api_portfolio.py` | 模拟盘/信号/行为 API |
| Dashboard 票池 | `dashboard/api_pool.py` | 三层票池/因子说明 API |
| Dashboard ETF | `dashboard/api_etf.py` | ETF 扫描/组合/详情 API |
| Dashboard 新闻 | `dashboard/api_news.py` | 新闻/情感分析 API |
| Dashboard 回测 | `dashboard/api_backtest.py` | 回测/对比 API |
| Dashboard 风险 | `dashboard/api_risk.py` | 风险指标/实时行情 API |
| 因子引擎 | `analysis/factor_engine.py` | 19子因子 → 7风格因子 → 综合评分 |
| 数据管线 | `data/data_router.py` | 统一数据接入，多源缓存 |
| 策略 faceji | `strategies/faceji.py` | 基本面多因子评分驱动 |
| 策略 silverquant | `strategies/silverquant.py` | 规则驱动、组件化风控 |
| 策略 tradingagents | `strategies/tradingagents.py` | 辩论制多信号加权 |
| 模拟盘引擎 | `analysis/trading_engine.py` | 三策略模拟盘调度 |
| 回测对比 | `analysis/strategy_comparison.py` | 三方对比 + 净值曲线 |
| 固定评估器 | `evaluator_fixed.py` | 固定标尺 Train/Test/Walk-Forward |
| 新闻管线 | `scripts/news_pipeline.py` | AKShare + GLM 多源分级聚合 |
| 评分解读 | `docs/score_explanation.md` | 7因子体系说明 |

## 四、数据流

```
数据源(Yahoo/baostock/AKShare)
    → data/data_router.py (缓存 + 标准化)
    → analysis/factor_engine.py (因子计算 + 评分)
    → scripts/run_factor_daily.py (每日扫描)
        → data/pool/{watch,monitor,deep}.json (三层票池)
    → analysis/trading_engine.py (策略执行)
        → trading_signals.json (交易信号)
        → strategy_states.json (策略持仓状态)
    → dashboard/server.py (Dashboard 展示, 模块化API)
```

## 五、关键架构决策 (ADRs)

- **ADR-001**: 固定评估标尺，禁止为提分修改 — `evaluator_fixed.py`
- **ADR-002**: HL 循环只改 `strategies/` 下的策略文件
- **ADR-003**: GitHub 是唯一源码真理，本地修改必须立即 push
- **ADR-004**: 所有改动必须过飞书文档评审流程 (OpenSpec)
- **ADR-005**: 采用 Calendar Versioning (vYYYY.MM.DD)

## 六、相关文档

- [README](../README.md) — 项目入口
- [GLOSSARY.md](GLOSSARY.md) — 术语表
- [API.md](API.md) — API 端点参考
- [WORKFLOW.md](WORKFLOW.md) — 开发工作流
- [CHANGELOG.md](../CHANGELOG.md) — 变更日志
