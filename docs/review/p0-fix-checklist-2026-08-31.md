# Dashboard P0 修复清单（阻塞上线）

> 日期：2026-08-31
> 配套：`lookahead-bias-experiment-2026-08-31.md`（量化证据）、`ia-redesign-2026-08-31.md`（信息架构）
> 定位原则：每项落到 `文件:行号` + 证据（线上实测 / 实验结果），分「临时止血（不改代码）」与「最终方案（代码修复）」两档。

---

## 修复进度（2026-09-01 核查）

> 面基助手已完成 3 个 batch 重构（fb6163a / ad2fb2b / 26ccbc0），以下为**逐项验证后的修复状态**。✅=已修复且线上验证通过；🟡=部分修复（临时止血已做，最终方案未做）；❌=未修复。

| batch | 覆盖项 | 验证 |
|-------|--------|------|
| batch1（fb6163a） | P0-3/4/10/13/13b + JS 语法炸弹 + 前端止血 | ✅ 全部生效 |
| batch2（ad2fb2b） | P0-5/6/7/8 | ✅ 生效（P0-8 见下"残留"） |
| batch3a（26ccbc0） | P0-9/11 + ETF 数据更新 | ✅ 生效 |
| batch4（ba7fc5a） | ETF 过期检测+自动重算 + action 真实推导 + alert→toast | ✅ 生效 |
| batch5a/5b（269a810/5d9c6df） | 信息架构（导航分组/六层用户语言/结论条/信号折叠/文案） | ✅ 生效 |
| 时点评分修复（c2b1362/3d542cf/151b7dc/a862862） | baostock线程安全 + pe越界 + 净值基准 + use_point_in_time透传 | ✅ 生效 |
| **本轮修复（44ec4f5/69e381a/d67b75f/cb7be61）** | TradingAgents辩论制bug + 结论条冲突 + 六层五卡 + 日期重复 + 负零 + ATR止损 + 财务因子as_of | ✅ 27→28测试全过 |

## 总览

| # | 问题 | 严重度 | 类别 | 状态 |
|---|------|:------:|------|:------:|
| P0-1 | 回测使用固定评分 FIXED_SCORE_MAP（前视偏差） | 🔴 致命 | 回测可信性 | 🟡 仅告警 |
| P0-2 | 回测股票池 FIXED_UNIVERSE 幸存者偏差 | 🔴 致命 | 回测可信性 | 🟡 仅告警 |
| P0-3 | 信号当日收盘价成交，无 T+1 | 🔴 高 | 回测可信性 | ✅ 已修 |
| P0-4 | v3 引擎 `_decide_loop` 卖出无成本模型 | 🔴 高 | 回测可信性 | ✅ 已修 |
| P0-5 | `/api/comparison` 脏数据（卖价=买价、pnl=0） | 🔴 高 | 数据正确性 | ✅ 已下线 |
| P0-6 | 净值曲线日期重复 + 非每日市值 | 🔴 高 | 数据正确性 | ✅ 已修 |
| P0-7 | 止损线假数（峰值追踪未生效） | 🔴 高 | 数据正确性 | ✅ 已修 |
| P0-8 | 证据链与因子分自相矛盾 | 🟠 中 | 数据正确性 | 🟡 证据链修/因子数据源未修 |
| P0-9 | 胜率口径三套并存 | 🟠 中 | 口径一致性 | ✅ 已修 |
| P0-10 | sortino 缺失时 fallback 到 score | 🟠 中 | 指标正确性 | ✅ 已修 |
| P0-11 | 假进度条 | 🟠 中 | 产品化 | ✅ 已修 |
| P0-12 | `alert()`/`window.open()` 脚本级交互 | 🟡 低 | 产品化 | ✅ 已修 |
| P0-13 | 120 天报告滚动指标图空 + x 轴日期损坏（窗口短） | 🔴 高 | 回测可信性 | ✅ 已修（需重跑报告） |
| P0-13b | compare 报告净值对比图缺失（svg=0） | 🔴 高 | 回测可信性 | ✅ 代码已修（需重跑报告） |
| P0-14 | 前端宣传图表口径（1000 天齐全 / 120 天残缺 / VaR 无独立图） | 🟠 中 | 产品化 | 🟡 仅改文案 |
| P0-15 | 图表裁切（所有报告）+ deepseek-vision 精度局限 | 🟡 低 | 产品化 | ❌ 未修 |

---

## P0-1 回测固定评分（前视偏差）

- **证据**：`engine/evaluator_fixed.py:40-61` 定义 `FIXED_UNIVERSE`（19 只硬编码评分）；`:383` `run_backtest` 内 `score_map = dict(FIXED_SCORE_MAP)` 全程不变；`engine/backtest_v3.py:161` 同。
- **量化**：实验显示 faceji 固定评分 +14.97% < 中性评分 +36.05%，静态评分让策略**少赚 21pp**（失真而非虚增）；且跑输等权买入持有 +34.77%。
- **临时止血**：在 dashboard 回测 Tab 顶部加显著告警条——「⚠️ 回测使用固定评分（point-in-time 未实现），结果不可作为实盘依据」；v3 报告页同样标注。
- **最终方案**：废弃 `FIXED_SCORE_MAP`，改为**时点正确（point-in-time）动态因子计算**——回测到 T 日只能用 T 日及以前的数据算分。可复用 `engine/factor_engine.py` 的截面百分位逻辑，但评分输入必须是 `as-of` 快照而非当前值。

## P0-2 幸存者偏差

- **证据**：`FIXED_UNIVERSE` 19 只全是当下热点龙头，无历史剔除/退市标的。实验：等权持有 +34.77% vs 沪深300 −2.3%（37pp 超额全部来自选对池子）。
- **量化**：v3 报告 `lds_faceji_1000d CAGR 60.19%`、`lds_tradingagents_1000d CAGR 62.48%` 绝大部分是幸存者偏差，非策略能力。
- **临时止血**：回测结果卡片的「年化收益」旁加脚注「含幸存者偏差，未剔除历史退市标的」。
- **最终方案**：重建回测股票池——纳入"历史某时点入选、后被剔除/退市"的标的，用 point-in-time 成分股列表（蜻蜓 CSC 历史成分或 baostock 历史退市名单）。

## P0-3 无 T+1，当日收盘价成交

- **证据**：`evaluator_fixed.py:419/445` `exec_price = price_map.get(sig.symbol, sig.price)`，信号日当天用当日收盘价成交。
- **临时止血**：无法止血，属回测口径错误，只能重跑。
- **最终方案**：信号 T 日收盘生成 → **T+1 开盘价成交**（`get_history` 增加 `open` 列，回测循环把成交时点错位一天）。

## P0-4 v3 引擎 `_decide_loop` 卖出无成本模型

- **证据**：`engine/backtest_v3.py:226-234` 卖出直接 `total_cash += qty * price`，无印花税/佣金/滑点；而 `run_backtest`（`:416-442`）有完整成本模型。两条路径口径不一致。
- **临时止血**：无。
- **最终方案**：`_decide_loop` 的 SELL 分支接入与 `run_backtest` 一致的 `engine.cost_model.calc_adjusted_price`。

## P0-5 `/api/comparison` 脏数据

- **证据**：线上实测 `/api/comparison`，faceji 交易 `2026-07-09 买 600900@27.83 → 07-14 卖 @27.83 pnl=0.0 reason="评分下滑0.0"`（卖价=买价、评分下滑了 0.0 分）；silverquant `total_trades:0` 但 trades 列表有 5 笔买入。
- **临时止血**：下线 `/comparison` 页面与 `/api/comparison` 路由（`dashboard/api_comparison.py`、`dashboard/api_backtest.py:192-206`），主导航已无入口，属孤儿页面。
- **最终方案**：删除旧 `engine/strategy_comparison.run_comparison` 依赖，回测对比统一走 evaluator_fixed 引擎。

## P0-6 净值曲线日期重复 + 非每日市值

- **证据**：`dashboard/api_portfolio.py:446-488` 只在"有交易记录"日 push 点，导致线上 `netvalue` labels 出现 `2026-08-18 ×3、2026-08-24 ×3`；且只在"卖出"时累加已实现盈亏，持仓浮盈不进入曲线。
- **临时止血**：前端曲线图标题改为「已实现盈亏累计」（避免误导），并去重 labels。
- **最终方案**：`netvalue` 改为每日 mark-to-market——从 `trading_signals.json` 的持仓 `current_price` 快照 + 现金，重建每日净值序列；日期按自然交易日去重。

## P0-7 止损线假数（峰值追踪未生效）

- **证据**：线上实测持仓 `300750` 的 `trail_stop.rule_description = "盈利-7.0%→亏损:峰值396.4472×0.92=364.73"`，但 `peak_price == entry_price == 396.4472`——峰值从未更新；`shared.py:116`、`api_portfolio.py:227/364` 硬编码 `entry*0.92`，与前端 `STRAT_RULES`（`dashboard_main.py:458`）的"硬止损-8%/回落-12%"两套口径冲突。
- **临时止血**：前端止损列去掉"峰值回落"相关描述，明确只显示"固定止损 = 入场价×0.92"。
- **最终方案**：峰值追踪接入真实 `peak_price`（持仓快照中已有字段），止损价 = `max(entry*0.92, peak*0.88)` 并同步两处硬编码为单一配置源。

## P0-8 证据链与因子分自相矛盾

- **证据**：线上实测持仓 `300750` 的 `evidence_packet.chain[0]` 返回 `{"status":"missing","rationale":"无评分数据","warning":"无因子数据"}`，但同一持仓 `factor_scores = {quality:0.9, momentum:1.0, ...}` 有值。
- **临时止血**：持仓弹窗的证据链区块，当 `factor_scores` 非空时隐藏"无因子数据"告警。
- **最终方案**：`api_portfolio.py:_build_position_evidence`（:437-443）在构建证据包时把 `factor_scores`/`factor_breakdown` 一并传入 `EvidenceBuilder`，修复数据层缺失判定。

## P0-9 胜率口径三套并存

- **证据**：模拟盘 detail 面基 win_rate=0.0%（2 卖 0 赢）vs v3 回测 51.08% vs 120d 约 52%；`api_portfolio.py:303-309` 只统计"卖出且 pnl 非 None"。
- **临时止血**：胜率显示改为「平仓 N 笔 / 胜 M 笔」，N<10 时显示"样本不足"而非百分比；回测卡片胜率旁标注口径。
- **最终方案**：统一 `win_rate` 定义为"已平仓交易中 pnl>0 占比"，三处数据源共用同一计算函数；文档化口径差异（回测 vs 实盘模拟）。

## P0-10 sortino fallback 到 score

- **证据**：`evaluator_fixed.py:524` `sortino_ratio=metrics.get("sortino_ratio", metrics.get("score", 0.0))`——索提诺缺失时返回"评分"。
- **临时止血**：无（需代码修复）。
- **最终方案**：删除 fallback，sortino 缺失时返回 `None`，前端显示"—"。

## P0-11 假进度条

- **证据**：`dashboard_main.py:1551-1564` `progress += Math.random()*12+5` 随机推进，与真实回测进度无关。
- **临时止血**：删掉进度条，改文案「运行中（约 10s~2min）」。
- **最终方案**：若保留进度条，接入后端真实阶段回调（数据加载/回测/报告生成三阶段）。

## P0-12 `alert()`/`window.open()`

- **证据**：`dashboard_main.py:1922-1928`（runV3Backtest）、`:1435/1480`（loadEtfDetail）用原生 `alert()` + `window.open`。
- **临时止血**：保留功能但去 `window.open`（浏览器可能拦截），改页内提示条。
- **最终方案**：回测结果改为页内结果卡片 + iframe 内嵌 quantstats 报告，取消弹窗。

## P0-13 120 天报告滚动指标图空 + x 轴日期损坏（窗口太短，仅短窗口成立）

- **证据**（视觉验证）：**仅 120 天（109 天）报告**的 `Rolling Beta`、`Rolling Volatility (6-Months)`、`Rolling Sharpe (6-Months)` 三个子图只渲染 0 线，数据曲线没画；Volatility/Sharpe 图 x 轴显示 `01-01-00`（年份 epoch 零值）。**1000 天报告滚动图有完整数据、日期正常**。
- **根因**：120 交易日 ≈ 3.5 个月，rolling 6-month 指标需 ≥6 个月数据，数据不足导致曲线空、日期损坏。与 P0 报告中"3.5 个月数据标成 3Y/5Y/10Y 年化"是同一根因。
- **临时止血**：v3 报告生成处（`engine/backtest_v3.py:generate_report`）对窗口 < 6 个月的 run，关闭 rolling 指标图（或改为 rolling 3-month），避免输出空图/坏日期。
- **最终方案**：按回测窗口长度自适应 quantstat 指标窗口（`rolling` 参数随数据长度降级）；或默认回测窗口提升到 ≥250 交易日，使 6-month rolling 有意义。

## P0-13b compare 报告净值对比图缺失（svg=0）🔴

- **证据**（视觉验证）：`lds_compare_1000d`（"多策略专业对比报告"，note "LDS 周一深度讨论"）是自研格式，含"净值对比(首日=1.0)"和"核心指标对比"两个 section，但 **svg_count=0，"净值对比"的三策略净值曲线图没有渲染出来**，只有"核心指标对比"表格有数据。列表里它显示"0 天 0 笔"也是 meta 字段未填对（实际是 1000 天三策略对比）。
- **临时止血**：无（需代码修复）。
- **最终方案**：修复 `engine/backtest_v3.py:generate_compare_report` 的净值对比图生成逻辑（可能是 chart 数据未写入或前端未渲染），并补全 meta 的 n_days/n_trades 字段。

## P0-14 前端宣传图表口径：1000 天报告齐全，120 天残缺，VaR 无独立图

- **证据**：`dashboard_main.py:282` 宣传"月度热力图/滚动夏普/水下图/VaR"。逐报告核实：**1000 天报告这些图表都存在**（热力图 4 年行、滚动夏普有数据、水下图完整）；**120 天报告因窗口短残缺**（见 P0-13）；**VaR 在所有报告里都以表格指标存在**（"Daily Value-at-Risk"、"Expected Shortfall cVaR"），无独立 VaR 图。
- **临时止血**：修正前端文案，把"VaR"改为"VaR 指标（表格）"；对 120 天报告提示"窗口过短，滚动指标不可用"。
- **最终方案**：若确需独立 VaR 图，确认 quantstats 是否支持并启用；否则按实际情况更新文案，消除宣传与实物的落差。

## P0-15 图表裁切（所有报告普遍存在）+ deepseek-vision 精度局限

- **证据**（视觉验证）：quantstat 报告的水下图、收益分位数箱线图（Return Quantiles）、滚动 Sharpe 图在**所有报告里都有底部裁切**，与窗口长短无关；deepseek-vision-exp 读图会编造细节（总资产读成"¥787 万"、11 个 Tab 读成"5 个"），需配合 accessibility tree 交叉验证。
- **临时止血**：无（裁切属 quantstats 渲染；vision 精度局限通过交叉验证规避）。
- **最终方案**：裁切问题排查 quantstats 报告模板的图表高度配置；视觉 QA 若需高精度，考虑保留 gpt-5.5 作为 vision fallback（`oh-my-openagent.json` 的 multimodal-looker 可配多模型）。

---

## 修复顺序建议

```
第一批（回测可信性，做完才允许对外宣称任何回测数字）:
  P0-1 → P0-2 → P0-3 → P0-4 → P0-13 → P0-13b

第二批（数据正确性）:
  P0-5 → P0-6 → P0-7 → P0-8 → P0-10

第三批（口径 + 产品化）:
  P0-9 → P0-11 → P0-12 → P0-14 → P0-15
```

> **红线**：在 P0-1、P0-2 完成前，dashboard 上任何回测收益数字（CAGR/Sharpe/超额α）都应视为不可对外引用。

---

## 还欠缺的内容（2026-09-01 二次核查，反映最新修复状态）

### 🔴 P0 级（致命，阻塞对外宣称回测数字）

**P0-1 时点评分 ✅ 已实现**（面基助手 + 本轮共同完成）——as_of 机制 + 价格注入 + 降频重算 + IC 权重 as_of + 财务因子 as_of + 价格字段扩展，全链路已闭环。**仍需数据级验证**（`use_point_in_time=True` vs `False` 对比，需在开发机器跑 `scripts/verify_point_in_time.py`）。

**P0-2 幸存者偏差 🟡 数据基础已备**——`get_delisted_stocks` 退市股名单 + `BacktestResult.extra` 的 survivorship_bias 标注已完成。但**完整退市股补池（历史 point-in-time 股票池）未做**，19 只龙头池子的幸存者偏差仍存在。

### 🟠 P1 级（重要，数据正确性/体验）

**财务因子完整 as_of** ⚠️ 部分——ROE/毛利率/净利率/负债率/净利增速已 point-in-time，但**营收增速/股息率/每股经营现金流仍用当前财报**（历史源缺失）。

**P0-15 图表裁切未处理**——1000 天报告的水下图/收益分位数图/滚动 Sharpe 仍被裁切。

**P0-14 口径** 🟡 部分——文案改了，但 VaR 无独立图、短窗口滚动图缺失的实质未解决。

**交易弹窗"规则标签 vs 实际浮亏"区分不清**——"HardSeller(-8%)"是规则标签，实际触发时可能已浮亏 -10.3%（T+1 滞后 + 开盘跳空），UI 未区分。

### 🟡 P2 级（次要，产品化）

**黑话 tooltip 未做**——双门/宽货币·紧信用/链/面基/SQ 等术语对普通用户不可读。

**旧回测报告未重新生成**——`lds_compare_1000d`（0 svg）、120 天报告（空滚动图）是旧代码产物，需重新运行回测体现修复效果。

### 本轮已修复（44ec4f5 → cb7be61）

- ✅ TradingAgents 辩论制 bug（bear 反向 + bear 恒 ≤ neut）
- ✅ ATR 自适应止损（silverquant 胜率 42.9% → 54%）
- ✅ 结论条冲突解析（事件风险高时压制买入）
- ✅ 六层五卡（"选股"→"选股·找票"）
- ✅ 日期重复、负零
- ✅ 财务因子 as_of（ROE/毛利率/净利率/负债率/净利增速）

---

## 下一步建议顺序

```
剩余 P0（硬骨头）:
  P0-2 完整退市股补池（历史 point-in-time 股票池） + 数据级验证时点评分

剩余 P1:
  财务因子完整 as_of（营收增速/股息率/每股现金流）→ P0-15 裁切 → 交易弹窗口径

剩余 P2:
  黑话 tooltip → 旧报告重跑
```
