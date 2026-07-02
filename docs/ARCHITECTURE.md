# 面基投资系统 架构文档

> 版本: v2026.07.02 | 本文件是系统的唯一架构描述

## 一、系统定位

面基投资系统是一套**量化+价投双修**的个人投资决策辅助系统。核心使命：

1. **发现**：通过多因子扫描从 100+ 关注池中筛选出高评分标的
2. **盯住**：通过持续评分追踪，将高评分标的逐步提升至 Monitor/Deep 层
3. **深度**：通过 8 维深度研报框架（链定位/DCF/凯利/Nick 四问/贝叶斯/风险/面基引用）分析核心持仓

## 二、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户交互层                            │
│  Dashboard (FastAPI :8686)   飞书日报    GitHub              │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        数据管线层                            │
│  data_router.py ─── baostock (A股) ─── 76只×5年缓存         │
│                 ─── yfinance   (港美股)                      │
│                 ─── akshare    (新闻/ETF)                    │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        因子引擎层                            │
│  factor_engine.py ─── 19子因子 → 7风格因子                  │
│  run_factor_daily.py ─── 每日扫描 → scan_snapshot_*.json    │
│  评分体系: 质量/价值/成长/动量/低波/情绪/风险               │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        策略执行层                            │
│  面基 (基本面多因子)  SilverQuant (规则驱动)  TradingAgents  │
│  4层风控: HardSeller → FallSeller → ScoreDrop → MASeller    │
│  portfolio_builder.py → 模拟盘执行                           │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                        评估回测层                            │
│  evaluator_fixed.py ─── 固定标尺 Train/Test                 │
│  strategy_comparison.py ─── 三方对比                        │
└─────────────────────────────────────────────────────────────┘
```

## 三、核心模块清单

| 模块 | 路径 | 职责 |
|------|------|------|
| Dashboard | `scripts/portfolio_server.py` | 7面板数据面板 (FastAPI + 静态 HTML) |
| 因子引擎 | `factor_engine.py` | 19子因子 → 7风格因子 → 综合评分 |
| 数据管线 | `data/data_router.py` | 统一数据接入，多源缓存 |
| 策略 faceji | `strategies/faceji.py` | 基本面多因子评分驱动 |
| 策略 silverquant | `strategies/silverquant.py` | 规则驱动、组件化风控 |
| 策略 tradingagents | `strategies/tradingagents.py` | 辩论制多信号加权 |
| 模拟盘 | `scripts/portfolio_server.py` | `/api/simulated` 三策略数据 |
| 回测对比 | `analysis/strategy_comparison.py` | 三方对比 + 净值曲线 |
| 新闻管线 | `scripts/news_pipeline.py` | AKShare + GLM 多源分级聚合 |
| 评分解读 | `docs/score_explanation.md` | 7因子体系说明 |

## 四、数据流

```
数据源(Yahoo/baostock/AKShare)
    → data_router.py (缓存 + 标准化)
    → factor_engine.py (因子计算 + 评分)
    → run_factor_daily.py (每日扫描)
        → scan_snapshot_*.json (历史快照)
        → pool_live.json (三层票池: Watch/Monitor/Deep)
    → portfolio_builder.py (策略执行)
        → trading_signals.json (交易信号)
        → shadow_account.json (模拟盘持仓)
    → portfolio_server.py (Dashboard 展示)
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
