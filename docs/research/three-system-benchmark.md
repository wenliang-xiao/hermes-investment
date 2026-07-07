# Hermes × Vibe-Trading × TradingAgents · 三方全面对标

> **日期**: 2026-07-07 | **目的**: 让你对当前系统的位置、竞品的能力、差距和改进方向有完整的画面

---

## 一、三系统简介

| 系统 | 作者 | GitHub | 定位 | 发布时间 |
|------|------|--------|------|---------|
| **Hermes** | 你 | wenliang-xiao/hermes-investment | 个人量化投资辅助（因子+产业链+双门） | 2025 |
| **Vibe-Trading** | HKUDS (港大数据实验室) | HKUDS/Vibe-Trading (18k★) | 开源投研工具箱（Shadow Account + Alpha Zoo） | 2026-04 |
| **TradingAgents** | Tauric Research | TauricResearch/TradingAgents (91k★) | 多Agent LLM交易框架（分析师团队+辩论+决策） | 2024-12 |
| **TradingAgents-CN** | hsliuping | hsliuping/TradingAgents-CN (27k★) | TradingAgents中文增强版（A股+国产LLM+报告导出） | 2025-06 |

---

## 二、新闻获取能力对标

### 2.1 Vibe-Trading 新闻引擎（业内最全面）

Vibe-Trading v0.1.10 有 **18个只读数据工具**，其中新闻相关覆盖：

| 工具 | 覆盖范围 | 能力 |
|------|---------|------|
| `get_stock_news` | A股(东方财富) + 美股 + 港股 | 公司+行业新闻标题，实时抓取 |
| `get_research_reports` | 卖方研报 | 深度研究报告（需key） |
| `get_sec_filings` | 美股 SEC EDGAR | 10-K/10-Q/8-K年报季报 |
| `web_search` | 全市场 | 多引擎网络搜索 |
| `iwencai` | A股 | 自然语言查询（问财） |
| `get_dragon_tiger` | A股 | 龙虎榜数据 |
| `get_northbound_flow` | A股 | 北向资金流向 |
| `get_block_trades` | A股 | 大宗交易 |
| `get_shareholder_count` | A股 | 股东人数变化 |
| `get_lockup_expiry` | A股 | 限售股解禁 |

**情感分析**：使用微调过的 RoBERTa 模型做情绪评分（正面/负面/中性 + 强度），不是简单的关键词匹配。

**三层数据流**：
```
市场数据(OHLCV)  +  新闻情感(RoBERTa)  +  链上数据(加密)
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
                    Signal Aggregator (LLaMA-3-8B微调)
                           ▼
                    Vibe Score [-1, +1]
                           ▼
                    Decision Engine (Kelly + 止损 + 组合约束)
```

### 2.2 TradingAgents-CN 新闻模块

TradingAgents-CN 在 v0.1.12 版本专门加了**智能新闻分析模块**：
- 多层次新闻过滤
- 新闻质量评估
- 统一新闻工具
- 专门的 News Analyst agent + Sentiment Analyst agent

**不同于 Vibe-Trading 的是**：TradingAgents 的新闻分析是 LLM Agent 驱动的——新闻分析师 Agent 读取新闻后做自然语言推理，而不是 RoBERTa 这种纯模型的分数。

### 2.3 Hermes 新闻引擎（当前）

| 能力 | Hermes 当前 | 差距 |
|------|-----------|------|
| 新闻源 | Google News RSS + 雪球热帖 | 没有东方财富新闻、SEC EDGAR、卖方研报 |
| 情感分析 | GLM-4-Flash 摘要 | 没有量化的情感评分（正面/负面 + 强度） |
| 异动关联 | ❌ 无 | 不知道某条新闻对哪只票影响最大 |
| 舆情趋势 | ❌ 无 | 不知道市场情绪在变好还是变差 |
| 龙虎榜 | ❌ 无 | 北向资金有但没有龙虎榜 |
| 自然语言查询 | ❌ 无 | Vibe-Trading有问财集成 |
| 研报 | ❌ 无 | 两系统都有卖方研报访问 |

**一句话**：Vibe-Trading 的新闻引擎是"深度覆盖"（18工具+RoBERTa+LLM），TradingAgents 是"LLM Agent推理"，Hermes 是"能看但不会分析"。

---

## 三、TradingAgents 的架构与 Hermes 的关系

### 3.1 TradingAgents 核心架构

```
                    ┌─────────────────────────────────┐
                    │       Analyst Team (分析师团队)    │
                    │  Fundamentals Analyst  (基本面)    │
                    │  Sentiment Analyst    (情绪面)     │
                    │  News Analyst         (消息面)     │
                    │  Technical Analyst    (技术面)     │
                    └──────────────┬──────────────────┘
                                   │ 各自产出分析报告
                                   ▼
                    ┌─────────────────────────────────┐
                    │    Researcher Team (研究员团队)    │
                    │  Bull Researcher (看涨)           │
                    │  Bear Researcher (看跌)           │
                    │  → 结构化辩论，正交验证              │
                    └──────────────┬──────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────┐
                    │       Trader Agent (交易员)       │
                    │  综合分析师+研究员报告 → 交易决策     │
                    └──────────────┬──────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────┐
                    │   Risk Management + PM (风控+经理) │
                    │  评估风险 → 批准/拒绝 → 模拟执行     │
                    └─────────────────────────────────┘
```

### 3.2 Hermes 的 tradingagents.py vs 真正的 TradingAgents

| 维度 | Hermes `tradingagents.py` | 真正的 TradingAgents |
|------|--------------------------|---------------------|
| 实现方式 | **一个函数 `_debate_score()`** | 多个 LLM Agent 真正对话辩论 |
| 分析师角色 | 无。只有 `sc*0.5 + ts*0.5`（评分+技术面） | 4个专职分析师（基本面/情绪/新闻/技术） |
| 看涨/看跌 | `bull = sc*0.5 + ts*0.5`, `bear = sc - bp` | 两个研究员Agent真正写看涨/看跌分析报告 |
| 辩论机制 | 一个公式 `final = bull*0.6 + neut*0.3 + bear*0.1` | LangGraph 多轮对话辩论 |
| 风控 | 3层止损（无独立风控Agent） | 独立风险评估Agent + PM批准/拒绝 |
| 历史记录 | 无。每次独立计算 | 会话上下文传递 |
| LLM调用 | 0（纯数学公式） | 每轮辩论5-8次LLM调用 |

**结论**：Hermes 的 `tradingagents.py` 是 TradingAgents 理念的**轻量化数学近似**——它把"多Agent辩论"抽象成一个加权公式，但没有真正的 LLM 推理。这让它极快且零成本，但同时失去了真正的多角度分析能力。

### 3.3 tradingagents.py 的加权公式解析

```python
# 牛市主导: bull占60%, 中性占30%, 熊市占10%
final = bull*0.6 + neut*0.3 + bear*0.1

# 熊市主导: bear占50%, 中性占30%, 牛市占20%
final = bear*0.5 + neut*0.3 + bull*0.2

# 平局: 纯中性评分
final = neut
```

**问题**：bull和bear的计算不在同一尺度——`bull = sc*0.5 + ts*0.5`（两个数的均值），`bear = sc - bp`（减法）。两者的直接比较在数学上不严谨。

---

## 四、Vibe-Trading 的 Swarm Teams vs Hermes 的策略层

### 4.1 Vibe-Trading 29个Swarm团队

| 预设 | 工作流 | Hermes 对应 |
|------|--------|------------|
| `investment_committee` | 牛熊辩论→风险审查→PM终审 | `tradingagents.py`（数学近似版） |
| `global_equities_desk` | A股+港股+美股→全球策略师 | Hermes无对应 |
| `quant_strategy_desk` | 筛选→因子研究→回测→风险审计 | **Hermes 核心管线就是这个** |
| `risk_committee` | 回撤/尾部风险/制度分析 | Hermes❌ 无（最大缺口） |
| `crypto_trading_desk` | 资金费率+清算+流动→风控 | Hermes❌ 不在范围 |
| `earnings_research_desk` | 基本面+修正+期权→策略师 | Hermes无对应 |

### 4.2 Swarm Team 的技术实现

每个Worker有独立工具集，包括本地的 `get_market_data` 工具（通过同一个标准化数据加载器）。这意味着：
- Worker不会因为幻觉而编造价格
- 每个Worker的输出是结构化JSON，不是自由文本
- 非有限浮点数序列化为null而非NaN
- 严格的JSON格式保证下游解析

**Hermes 可以借鉴的**：模拟盘信号生成已有，但缺少多角度验证。如果 faceji/silverquant/tradingagents 三策略各自独立给出信号后，再加一个"冲突仲裁"层来对标投资委员会，会更完整。

---

## 五、数据源覆盖对比

| 市场 | Hermes (4源) | Vibe-Trading (18源) | TradingAgents-CN |
|------|-------------|-------------------|-----------------|
| A股实时 | 腾讯财经 ✅ | 腾讯/东财/新浪/baostock | Tushare/AkShare/BaoStock |
| A股历史 | baostock | tushare/baostock/akshare/mootdx | Tushare/AkShare |
| 港股 | yfinance | yfinance/futu/tushare | Yahoo Finance |
| 美股 | yfinance | yfinance/stooq/yahoo/finnhub/alphavantage/tiingo/fmp | Yahoo Finance |
| ETF | ⚠️ yfinance(A股纯数字代码bug) | tushare ETF专用路由 | — |
| 加密 | ❌ | okx/ccxt(100+交易所) | ❌ |
| 期货 | ⚠️ 5个(akshare) | ✅ 深度覆盖 | ❌ |
| 宏观 | ✅ CPI/PMI/M2 | FRED macro | ❌ |

**Vibe-Trading的fallback链条**：按IP封禁风险排序（轻量级公共端点优先，需要key的REST靠后），共享限流HTTP网关，带per-host rate buckets + jitter + session重用。

**Hermes的fallback**：baostock→yfinance→akshare，有但不统一。三套数据层各自管理。

---

## 六、Vibe-Trading 的回测架构

| 维度 | Vibe-Trading | Hermes |
|------|-------------|--------|
| 引擎数 | 7 (中国A/全球股/加密/中国期货/全球期货/外汇/期权) | 1 (回测存储) |
| 基准对比 | 多基准对比面板 | 沪深300全收益 |
| PIT保障 | ✅ PIT-safe entry context | ❌ |
| Alpha bench | ✅ 一行CLI跑452个alpha + IC/IR分类 | ❌ |
| 因子纯度门 | ✅ AST纯度检查（无IO/无全局变量/无前视运算符） | ❌ |
| 随机对照 | ✅ run_bench_strict()加同宇宙随机对照+OOS split | ❌ |
| Walk-Forward | ❌ | ✅ evaluator_fixed.py |
| 幸存者偏差修正 | ❌ | ✅ _build_realistic_universe (但未启用) |
| 分层滑点 | ❌ | ✅ 5级滑点模型 |
| Shadow回测 | ✅ 从交易日记提取规则+跨市场回测 | ❌ |

**互补关系**：Hermes的回测在"现实性建模"方面（滑点/幸存者偏差/基准修正）做得更细，Vibe-Trading在"因子验证"（AST纯度/随机对照/OOS）和"行为回测"（Shadow Account）方面更强。

---

## 七、TradingAgents-CN 的独特价值（Hermes 可借鉴）

| 功能 | 说明 | Hermes 现状 |
|------|------|------------|
| **智能股票筛选** | 多维度指标筛选和排序 | ⚠️ PoolManager三层池 |
| **自选股管理** | 收藏/分组/跟踪 | ❌ |
| **个股详情页** | 完整信息展示+历史分析 | ❌ 只有评分+持仓 |
| **批量分析** | 多只股票同时分析 | ⚠️ score_batch但无UI |
| **模拟交易系统** | 虚拟交易环境验证策略 | ✅ shadow_account |
| **报告导出** | Markdown/Word/PDF | ❌ 只有飞书 |
| **实时通知** | SSE+WebSocket双通道 | ❌ 轮询 |
| **多LLM提供商** | OpenAI/Google/Anthropic/DeepSeek/Qwen/GLM/MiniMax | ❌ 只有GLM-4-Flash |

---

## 八、综合能力雷达图

```
                    找票能力
                      /|\
                     / | \
           新闻情绪  /  |  \  回测验证
                   /   |   \
                  /    |    \
                 /     |     \
        资产配置 ------+------ 风险控制
                 \     |     /
                  \    |    /
                   \   |   /
           日报质量  \  |  /  研究深度
                     \ | /
                      \|/
                    执行能力

        ─── Hermes (4.1/10)
        ─ ─ Vibe-Trading (7.5/10)
        ··· TradingAgents (研究型, 侧重新闻-研究-决策链)
```

| 维度 | Hermes | Vibe-Trading | 说明 |
|------|--------|-------------|------|
| 找票能力 | 7 | 8 | Vibe有452预训练alpha + AST纯度门 |
| 回测验证 | 5 | 8 | Vibe有7引擎+PIT+随机对照；Hermes有Walk-Forward但未启用幸存者修正 |
| 风险控制 | 2 | 7 | Vibe有VaR/CVaR+压力测试+独立的risk_committee |
| 执行能力 | 1 | 6 | Vibe有10券商接口+5层安全模型 |
| 研究深度 | 4 | 7 | Vibe有SEC EDGAR+财务报表+期权链 |
| 日报质量 | 6 | 4 | Hermes飞书推送好，Vibe只有手动HTML/PDF |
| 资产配置 | 3 | 6 | Vibe有ETF分析+资产配置skill |
| 新闻情绪 | 3 | 8 | Vibe有RoBERTa情感评分+LLM推理+18个数据工具 |
| **综合** | **3.9** | **6.8** | |

---

## 九、Hermes 当前处于什么位置

```
研究级平台 ──── Vibe-Trading (6.8) · TradingAgents-CN
                 ↑
                 │ 差距：新闻引擎+行为归因+风险模型+数据深度
                 │
个人工具 ──────── Hermes (3.9)
                 │
                 │ 独特优势：LDS双门+产业链深度+面基概念+飞书日报
                 │ 
基础脚本 ──────── （一年前的Hermes）
```

**你不是在研究级平台上竞争——你在个人工具的上限里做到最好。**

Vibe-Trading 的新闻引擎和 Shadow Account 是你可以借鉴的——不需要复制它的18个数据工具，只需要加一个行为诊断+情感评分层，就能把你的日报和 Dashboard 从"展示数据"升级到"帮你理解数据"。

**Hermes 独有的 Vibe-Trading 没有的**：
- LDS 双门风控（货币信用四象限+国运线）
- 15链产业链深度分析（利润池+Perez周期+翻倍逻辑）
- 飞书日报自动推送
- 面基概念引擎

**这些不要丢。** Vibe-Trading 补你的短板（行为分析+新闻深度），不要替换你的长板。
