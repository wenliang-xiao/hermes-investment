# 面基三源融合投资系统 · 全面审计与改造蓝图

> 编制日期: 2026-07-06 | 版本: v3.3.0 | 状态: 原型级 → 生产化进行中
> 
> 本文档基于对约 100 个 Python 模块（约 43,000 行代码）、15 个 Dashboard API 端点、8 份设计文档的全维度审计。

---

## 目录

- [一、系统架构全景](#一系统架构全景)
- [二、已做到 vs 未做到的](#二已做到-vs-未做到的)
- [三、七维能力评分](#三七维能力评分)
- [四、策略体系详解](#四策略体系详解)
- [五、Dashboard 逐功能专业评审](#五dashboard-逐功能专业评审)
- [六、技术负债与缺口矩阵](#六技术负债与缺口矩阵)
- [七、下一轮 OpenSpec 改造路线图](#七下一轮-openspec-改造路线图)

---

## 一、系统架构全景

当前系统采用三层架构：**策略层（纯函数） → 引擎层（TradingEngine） → 展示层（FastAPI Dashboard）**。

### 数据层
- `data/data_router.py` — 前缀路由自动分发（baostock/A股, yfinance/港美股, AKShare/ETF/期货）
- `data/sources/` — 3 个源模块（baostock 40行, akshare 193行, yahoo 76行）
- `data/cache/` — 5.26MB, 315 个 pickle 文件, 111 只标的 ×5 年日线

### 引擎层
- `analysis/trading_engine.py` — 三策略调度器（Faceji/SilverQuant/TradingAgents），Strategy 模式委托 strategies/ 纯函数
- `analysis/factor_engine.py` — v4.0 19子因子 → 7风格因子，截面百分位排序，IC滚动权重+贝叶斯收缩+宏观条件调整
- `analysis/factor_scanner.py` — v3.1 旧引擎，标注退役但仍被引用

### 策略层（hl-quant 范式）
- `strategies/` — 4 个纯函数模块（faceji/silverquant/tradingagents/base），零IO，一致 `decide()` 接口
- `evaluator_fixed.py` — 固定评估器，Sortino 主评分，Walk-Forward（Train252+Test63×3轮），DSR 统计检验

### 展示层
- `scripts/portfolio_server.py` — FastAPI @8686，15 个 API 端点，三大 HTML 内嵌 Python 字符串（~600行）
- Chart.js 4.4.7 CDN，暗色 GitHub 风格 CSS，7 面板 Tab 切换
- 77 个 pytest 测试通过，3 个 GitHub commits 今日推送

### 管线层
- `scripts/run_trading.py` — 日频 FactorEngine 评分 + TradingEngine 三策略模拟盘执行
- `scripts/run_report_v10.py` — 4 阶段日报管线（Phase1扫描 → Phase2链 → Phase3新闻 → Phase4发布）
- `scripts/news_pipeline.py` — AKShare Tier1 + GLM-4-Flash Tier2 + 评分偏移 Tier3

### 核心架构图

```
[数据入] data_router ─→ FactorEngine ─→ TradingEngine ─→ strategies/(纯函数)
                                                │
[策略出] trading_signals.json ←─── strategy_states.json
                                                │
[Dashboard] portfolio_server.py ──→ 15 API endpoints ──→ Chart.js UI
```

---

## 二、已做到 vs 未做到的

### ✅ 已做到（9个PR全部完成）

| PR | 内容 | 完成 |
|----|------|------|
| PR1 | 统一数据管线：前缀路由 + 全量缓存（111只×5年）+ 双源验证 | ✅ |
| PR2 | 评估器 v2：Walk-Forward + 多周期 + 成本模型 | ✅ |
| PR3 | 成本模型：5项费用（佣金/印花/过户/规费/滑点）×5级流动性 | ✅ |
| PR4 | ETF回测：FixedMix / RiskParity / Grid / Trend 4种 | ✅ |
| PR5 | 东财实时接口 + Dashboard 活数据 | ✅ |
| PR6 | 深度研报：8维框架（链定位/DCF/凯利/Nick/贝叶斯/风险/面基） | ✅ |
| PR7 | Dashboard 升级：OSkhQuant 指标面板 + `/api/metrics` | ✅ |
| PR8 | 日报升级：回测对照 + 因子分解 + 盘中报警 `/price_alert` | ✅ |
| PR9 | DSR 统计检验 + 新闻→评分偏移 | ✅ |

### ✅ 已做到（Phase 0 工程化）
- `pyproject.toml` + ruff + pytest（77 tests）
- 安全加固：硬编码凭据清除, `.env.example`, 原子写入（6处）
- `price=0` cascading bug 修复（`execute_sell/buy` guard + 价格降级）
- F2 回测存储：`analysis/backtest_storage.py` + CLI + Dashboard API

### 🟡 部分做到的
| 方面 | 进度 | 说明 |
|------|------|------|
| 安全加固 | 70% | 原子写入完成, 硬编码清除, 但 CI/CD 未上线（`.github/` 因 token scope 被拒）|
| 工程化 | 50% | pyproject.toml + ruff + 77 tests, 无 CI pipeline 运行 |
| 数据管线 | 40% | 原子写入完成, 但 news Tier1 损坏（akshare API 不兼容）|

### ❌ 未做到的
| 缺口 | 影响 | 优先级 |
|------|------|--------|
| `config.py` ↔ `domain/__init__.py` 22个常量完全重复 | DRY 违反, 同步风险 | P0 |
| `realtime` API 完全瘫痪 | 实时行情不可用 | P0 |
| 新闻管线 Tier1 损坏（akshare API 不兼容） | 新闻 42 天过期 | P0 |
| `metrics` 数据源不对齐（用 shadow_account 而非 strategy_states） | 全部为 0 | P0 |
| 净值曲线计算 Bug（`build_chart_data` 卖出逻辑错误）| 图表出现负值 | P0 |
| 回测 `run_id` 双重前缀 Bug | 永远 404 | P1 |
| 测试覆盖 < 5% | 92源模块仅5个有测试 | P1 |
| 新闻数据 42 天过期 | 全场最陈旧 | P1 |
| 宏观数据 41 天过期 | 决策依据过时 | P1 |
| 可观测性 | 无结构化日志 / 无 `/health` 端点 / 无监控告警 | P2 |
| Dashboard 前端重构 | HTML 仍内嵌 Python 字符串 | P2 |
| 双引擎仍并存 | `factor_scanner` v3.1 未退役仍被引用 | P2 |
| DCF 占位符 | `deep_research` 维度3 为占位 | P2 |
| CI/CD 未上线 | token 无 workflow scope | P2 |

---

## 三、七维能力评分

| 维度 | 评分 | 关键依据 |
|------|------|----------|
| **找票** | **B+** | 因子引擎 v4.0 架构优秀（19→7因子+IC滚动+贝叶斯收缩），但双引擎并存导致口径不一致 |
| **ETF配置** | **C** | 4种回测策略完成，Dashboard 权重有矛盾（国债ETF=SELL但权重25%），日报引用为空 |
| **深度分析** | **C+** | 8维框架完成，DCF 占位符未实现，面基知识库 13 篇文档未接入分析流程 |
| **新闻解读** | **C+** | Tier1 API 损坏，新闻 42 天过期，GLM 分析无有效输出，`news_score_offset` 为空文件 |
| **盯盘** | **C** | `realtime` API 完全无响应，实时行情全线瘫痪 |
| **交易纪律** | **A-** | 4层风控+Kelly+周频过滤有效，但 `price=0` 暴露数据层脆弱 |
| **日报** | **B** | 4阶段防残篇设计好，但新闻引用为空，新鲜度不足 |

### 附加工程评分

| 维度 | 评分 | 说明 |
|------|------|------|
| 代码健康度 | **C-** | 17个 >600行文件，最大2575行，config/domain 22常量重复 |
| 测试覆盖 | **E** | < 5%，77 tests / 92 源模块 |
| 数据质量 | **D+** | realtime 宕 / 新闻42d过期 / macro 41d过期 |
| Dashboard | **C-** | 15端点覆盖面广，多处数据源不对齐 + Bug |
| **综合** | **C+** | 功能覆盖 B-，工程实现 D，数据质量 D+，UI B |

---

## 四、策略体系详解

### 4.1 三层选股漏斗

```
因子扫描 → 31只核心池 + 7维度19子因子评分（百分位排序 [0,1], 非线性插值）
    ↓
不为清单过滤 → 10条Stop List规则（ROE/负债率/毛利率/护城河/管理层/现金流/能力圈）
    ↓
深度研报 → 8维框架（链定位/翻倍逻辑/DCF/凯利/Nick四问/贝叶斯/风险/面基）
```

### 4.2 三策略对比

| 策略 | 建仓条件 | 仓位管理 | 风控机制 | 模拟盘 |
|------|---------|---------|---------|--------|
| **Faceji（面基）** | 评分≥5.0 + MA60>MA20 趋势 | Kelly动态（上限8%） | 4层SQ风控（Hard/Fall/ScoreDrop/MA） | 建议信号，手动执行 |
| **SilverQuant** | 评分≥5.0 | 固定¥30K槽位 | 4层风控同上 | 全自动 |
| **TradingAgents** | 辩论分≥5.5 | Kelly动态（上限12%） | 强卖 < 5.0 + 硬止损 | 全自动 |

### 4.3 回测基线（最新）

| 策略 | Sortino | 总收益 | 最大回撤 | 交易笔数 |
|------|---------|--------|---------|---------|
| Faceji | 6.84 | +22.12% | -4.46% | 11 |
| SilverQuant | 3.71 | +6.22% | -3.07% | 198 |
| TradingAgents | 5.95 | +9.33% | -2.02% | 4 |

### 4.4 评估方法
- **固定评估器**（`evaluator_fixed.py`）：19只固定标的 × 120天窗口，Sortino 主评分
- **Walk-Forward**：Train 252d + Test 63d，滚动 3 轮，覆盖多市场周期
- **DSR**：Deflated Sharpe Ratio，修正多重比较偏差
- **成本模型**：佣金万1.5 + 印花税千1 + 过户费万0.1 + 规费0.1元 + 5级滑点
- **实验账本**：`data/hl_runs/` 记录每次候选，HL 循环（Probe→Diagnose→Propose→Patch→Evaluate→Replay→Decide→Compress）

### 4.5 与主流量化框架对比

| 能力 | 面基 v3.3 | hl-quant | OSkhQuant | xalpha |
|------|-----------|----------|-----------|--------|
| 纯函数策略层 | ✅ strategies/ | ✅ 核心设计 | ❌ 混合 | ❌ 过程式 |
| Walk-Forward | ✅ 252+63×3 | ✅ 标准 | ✅ 标准 | ❌ |
| 成本模型 5 级 | ✅ 5项 | ❌ 简化 | ✅ 完整 | ✅ A股特有 |
| ETF 回测 4 种 | ✅ 有 | ❌ | ✅ 多种 | ✅ 基金为主 |
| 多因子 19→7 | ✅ IC滚动+贝叶斯 | ❌ 只评分 | ✅ 完整 | ❌ |
| Dashboard | ⚠️ C- | ❌ 无 | ✅ A | ❌ 无 |
| 实时行情 | ❌ 瘫痪 | ❌ | ✅ WebSocket | ❌ |
| Brinson 归因 | ❌ 缺失 | ❌ | ✅ 有 | ❌ |
| CI/CD | ❌ 无 | ❌ | ❌ | ❌ |
| 测试覆盖 | < 5% | ~20% | ~15% | ~30% |

**结论**: 面基在策略设计理念上领先（纯函数+固定评估器借鉴 hl-quant）。在数据管线稳定性和 Dashboard 工程化上与"专业"框架差距显著。核心差距在于"能做"但"不耐用"——功能全但数据断层、测试缺失、无 CI 保证。

---

## 五、Dashboard 逐功能专业评审

> 基于实际 API 调用验证（15端点逐个 curl），截止 2026-07-06 22:00 CST

### 5.1 `/api/portfolio` — 组合概况 [C+]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | B | 覆盖总资产/现金/持仓/盈亏/净值曲线，覆盖面好 |
| 数据正确性 | **C-** | **严重 Bug**: chart.values 出现负值（-469,444），`build_chart_data` 卖出逻辑错误 |
| 时效性 | A | 更新时间精确到分钟 |
| 策略体现度 | B- | 含止损价、评分，但缺今日盈亏快速 |
| 数据源 | — | `shadow_account.json` → 空仓回退 `strategy_states.json` 聚合，但 `/metrics` 不对齐 |

### 5.2 `/api/comparison` — 三方对比 [D+]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | B- | 框架完整（三策略卡片+净值曲线+交易记录） |
| 数据正确性 | **D** | 全部为零占位：`total_return_pct=0`, `daily_values=[]`, `trades=[]`, `note="数据积累中…"` |
| 数据源 | — | `analysis/strategy_comparison.run_comparison(days=60)` + `trading_signals.json` |

### 5.3 `/api/signals` — 今日信号 [B-]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | A- | 3条SELL含策略/优先级/理由，结构完整 |
| 数据正确性 | C | `price=0` 是遗留坏数据（硬止损-100%） |
| 时效性 | A | `generated_at: 2026-07-06 18:15:19` |

### 5.4 `/api/realtime` — 实时行情 [F]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | **F** | 完全无响应（HTTP 200但 body 空） |
| 根因 | — | `realtime_price` 模块 `data_router` 导入失败，可量化行情链路断裂 |

### 5.5 `/api/realtime/positions` — 持仓实时 [F]

同上，完全不可用。

### 5.6 `/api/metrics` — 绩效指标 [D]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | B | 框架设计专业：Sharpe/Sortino/回撤/胜率/连续盈亏/年化，OSkhQuant 风格 |
| 数据正确性 | **D** | 全部为 0 — **数据源用 `shadow_account.json` 而非 `strategy_states.json`**，与 `/api/portfolio` 不对齐 |
| 策略体现度 | B | 指标选取专业 |

### 5.7 `/api/simulated` — 三策略模拟盘 [B+] ⭐ 最佳

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | A- | 三策略面板完整：现金/收益/持仓/信号 |
| 数据正确性 | B | 面基-8.25% / SQ-6.99% / TA-13.04% 真实收益 |
| 时效性 | A | 今日数据 |
| 策略体现度 | B+ | 各策略标签/评分/趋势/Kelly 类型说明 |

### 5.8 `/api/v2/pool` — 三层票池 [A-] ⭐ 最佳

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | A | 31watch/10monitor/2deep 完整，7因子评分+产业链+不为清单 |
| 数据正确性 | A | 数据完整一致 |
| 数据源 | — | `data/pool/` + `stock_names.py` |

### 5.9 `/api/v2/etf` — ETF 组合 [B+]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | A- | 趋势跟随+风险平价+合并建议三部分 |
| 数据正确性 | B+ | 合理但国债ETF=SELL+权重25%矛盾 |

### 5.10 `/api/v2/news` — 板块新闻 [C-]

| 维度 | 评分 | 说明 |
|------|------|------|
| 功能完整度 | B+ | 分类/摘要/新鲜度标签完整 |
| 数据正确性 | C+ | 有效但**42天过期**，`freshness="expired"` |
| 时效性 | **F** | 新闻是 5月25日的，`news_score_offset.json` 为空文件 |

### 5.11 `/api/v2/reports` — 日报链接 [C]

仅 2 条链接（7/1 和 7/2），无摘要无关键结论提取。

### 5.12 `/api/v2/backtest` — 回测列表 [D]

3条记录全是空壳：`run_id=null`, `symbols=[]`, `avg_sortino=null`。

### 5.13 `/api/v2/backtest/{id}` — 回测详情 [F]

**严重 Bug**: `load_result` 构造文件名时加 `bt_` 前缀，但文件名已有 `bt_`，导致双重前缀 → 永远 404。

### 5.14 `/api/risk` — 组合风险 [C+]

VaR/年化波动率/集中度指标设计合理，但样本不足全部 `null`。

### 5.15 Dashboard 工程质量

| 方面 | 评分 | 说明 |
|------|------|------|
| HTML 内嵌字符串 | **D+** | 三大块 600+ 行 Python `r"""..."""`，不可调试/不可 lint |
| Chart.js 使用 | B | 正确使用 4.4.7，含渐变填充/甜甜圈图/多线图，但加载两次 CDN |
| 数据刷新机制 | C | `setInterval` 轮询（60s/120s），无 WebSocket/SSE，无定时清理 |
| 错误处理 | **C-** | try/catch 但静默吞异常 `catch(e){}`，无重试 |
| 安全性 | **D** | 全部 `innerHTML` 拼接，XSS 风险（理由/名称字段未转义）|
| 响应式 | B+ | CSS Grid + `@media(max-width:900px)` 单列 |

### Dashboard 端点总结

| 端点 | 评分 | 一句话 |
|------|------|--------|
| `/api/portfolio` | C+ | 覆盖面广但图表数据有负值 Bug |
| `/api/comparison` | D+ | 框架完整但数据全部为零占位 |
| `/api/signals` | B- | 信号有效但 price=0 异常 |
| `/api/realtime` | **F** | 完全无响应 |
| `/api/realtime/positions` | **F** | 完全无响应 |
| `/api/metrics` | D | 框架专业但数据源不对齐 |
| `/api/simulated` | **B+** | 三策略真实收益，最佳数据端点 |
| `/api/v2/pool` | **A-** | 最佳端点，31只票完整 |
| `/api/v2/etf` | B+ | 策略清晰展现 |
| `/api/v2/news` | C- | 数据完整但42天过期 |
| `/api/v2/reports` | C | 仅2条链接 |
| `/api/v2/backtest` | D | 3条空壳 |
| `/api/v2/backtest/{id}` | **F** | 双重前缀 404 |
| `/api/risk` | C+ | 设计好但无样本 |

> **Dashboard 总评分: C-** (功能覆盖 B-，数据正确性 D+，时效性 D，工程质量 D)

---

## 六、技术负债与缺口矩阵

| 优先级 | 问题 | 描述 | 预估工时 |
|--------|------|------|---------|
| **P0** | `config.py` / `domain/__init__.py` 重复 | 22常量完全重复，不同模块导入不同源 | 1天 |
| **P0** | `realtime` API 完全瘫痪 | `data_router` 导入失败，行情链路断裂 | 0.5天 |
| **P0** | 新闻管线 Tier1 损坏 | `akshare` API 不兼容新版，41只标的全 error | 1天 |
| **P0** | `metrics` 数据源不对齐 | 用 `shadow_account` 而非 `strategy_states`，全部为 0 | 0.5天 |
| **P0** | 净值曲线计算 Bug | `build_chart_data` 卖出逻辑错误 | 0.5天 |
| **P1** | 新闻数据 42 天过期 | 全系统最陈旧数据源，无自动刷新机制 | 0.5天 |
| **P1** | 回测 `run_id` 双重前缀 | `load_result` 文件名构造错误 | 0.25天 |
| **P1** | 宏观数据 41 天过期 | `macro_raw/macro_engine_cache` 过期 | 1天 |
| **P1** | 测试覆盖 < 5% | 仅 77 tests 覆盖 5 个模块 | 3天 |
| **P2** | CI/CD 未上线 | GitHub token 缺 `workflow` scope | 0.25天 |
| **P2** | 17 个 >600 行文件 | 最大 2575 行（`report_v6.py`） | 5天 |
| **P2** | DCF 占位符未实现 | `deep_research` 维度3 | 1天 |
| **P2** | 双引擎仍并存 | `factor_scanner` v3.1 标注退役但仍被引用 | 0.5天 |
| **P2** | `baostock` 硬编码端日期 | `src/data/sources/` 中 `'20260625'` | 0.25天 |
| **P3** | Brinson 归因分析 | 模块化归因引擎 | 2天 |
| **P3** | WebSocket 实时推送 | 替代 polling | 2天 |
| **P3** | 回测参数网格搜索 | 超参优化的敏感度分析 | 2天 |
| **P3** | 日报面基知识引用 | 13篇飞书文档的产业链引用 | 2天 |

---

## 七、下一轮 OpenSpec 改造路线图

基于全面审计结论，按 TDD + 切片式交付执行。**优先修复瘫痪管线，再上工程化**。

### Phase P0 — 修复瘫痪管线（预估 2.5 天）

```
PS1: 修 realtime API                    — 修复 data_router 导入
PS2: 修 news_pipeline Tier1             — 适配 akshare 新版 API
PS3: 修 metrics 数据源                  — 改为 strategy_states 聚合
PS4: 修净值曲线 Bug                     — 修复 build_chart_data 逻辑
PS5: 修回测 run_id Bug                  — 修复 load_result 双重前缀
```

**验证标准**: `/api/realtime` 返回实时价格 > 0, `/api/metrics` 返回非零值, 净值曲线无负值, `/api/v2/backtest/{id}` 返回 200

### Phase P1 — 数据质量 + 测试覆盖（预估 4 天）

```
PS6: 重构 config.py / domain/__init__    — 消除 22 重复常量
PS7: 添加 P0 模块回归测试               — data_router/trading_engine/macro_engine
PS8: 新闻自动刷新机制                   — 定时任务 + 新鲜度 SLA
PS9: 宏观数据刷新                       — 缓存生命周期管理
```

**验证标准**: 无重复导入警告, `pytest tests/` ≥ 100 tests, 新闻新鲜度 < 7天

### Phase P2 — 工程化 + 架构（预估 5 天）

```
PS10: CI/CD 上线                        — 更新 token scope, 推 .github/workflows/ci.yml
PS11: 拆分超大文件                       — portfolio_server/report_v6/backtest
PS12: Dashboard 前端重构                 — HTML 从 Python 分离, 引入 Vite
PS13: 因子引擎统一                       — 移除 factor_scanner v3.1, 全量迁移至 v4.0
```

**验证标准**: GitHub Actions 自动运行 ruff + pytest, 17 个大文件减至 ≤ 10 个, Dashboard 代码独立部署

### Phase P3 — 功能增强（持续性）

```
PS14: Brinson 归因分析                   — 模块化归因引擎
PS15: WebSocket 实时推送                 — 替代 polling
PS16: 回测参数优化                       — 网格搜索 + 敏感度分析
PS17: 日报面基知识引用                    — 13 篇飞书文档产业链引用
```

---

*文档结束。基于全面审计结果，下一轮 OpenSpec 改造将从 Phase P0 开始，TDD + 切片式交付。*
