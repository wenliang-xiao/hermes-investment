# 回测对比页面重构 — SDD + TDD Trellis 执行计划

> 2026-08-27 · 目标：修复「运行回测」崩溃 + 借鉴 xalpha 等专业框架，系统性重做回测对比页面所有能力。
> 方法论：SDD(规格驱动设计) 先定契约 → TDD(红绿重构) 逐步实现。每个 WS 一个原子 commit。

## 一、Bug 根因（已定位）

**崩溃**：点「运行回测」默认 `strategy=all&days=60` → 走 `run_comparison()`（对比引擎）→ 
`strategy_comparison.py:304 for r in results: r.get("symbol")` — `r` 是字符串。

**根因链**：
1. `data/scan_snapshot_2026-07-20.json` 是 **dict 形态且无 `results` 字段**
2. `load_score_history()`：`data.get("results", data)` 无 results 时 fallback 返回**整个 dict**
3. `run_comparison()` 遍历详dict → 它 dict 的 keys（str `date`/`macro_state`/...）→ `.get()` 崩

**数据不足**（更根本）：datasnapshot 只有 4 个文件（7-09/7-14/7-20/latest），且 7-20 是坏形态。有效 `results` 仅 3 天 → 对比曲线无意义。需换用 `data/scan_snapshot_latest.json` 或真实回测引擎。

## 一、对比参考：专业回测框架摄取（xalpha 等）

**https://github.com/refraction-ray/xalpha** 核心能力（对标到我们页面）：

| xalpha 能力 | 我们要实现 | 优先级 |
|---|---|---|
| 费率/分红/拆股透明建模 | cost_model 已含滑点+印花税，需统一到对比 | P1 |
| `backtest` 净值曲线+回撤+基准对比 | 三策略净值 vs 沪深300 基准 | P0 |
| 指标: 年化/夏普/索提诺/最大回撤/卡玛/胜率 | 已部分有，需统一口径+展示 | P0 |
| 多标的/多策略对比 | 三策略并跑+同图表 | P0 |
| 交易记录明细 t-table | 每笔买卖盈亏/理由 | P1 |
| 滚动窗口/样本外 walk-forward | walk_forward 已有，接页面 | P2 |

其他借鉴（quantstats/backtrader）：
- **基准对比**：基准线(沪深300/纳指)叠加净值曲线
- **水下图(underwater)**：回撤随时间可视化
- **月度收益热力图**：量化终端标配
- **参数敏感性**：days/标的 影响
- **异常数据容错**：任何脏数据不崩，明确报"数据缺失"

## SDD — 规格契约（先行写死）

### 契约 A：对比引擎输出（统一格式）
`run_comparison(days) -> {"benchmark": {...}, "strategies": {"faceji|silverquant|tradingagents": {name, value, total_return_pct, sharpe, sortino, max_drawdown, calmar, win_rate, trades, daily_values[], trades[]}}, "days_analyzed", "data_status"}`

**data_status**：`ok / insufficient(<14天) / missing(0快照)` — 页面据此显示真实状态，不假全零。

### 契约 B：数据加载防御
- `load_score_history` 只接受 list-of-dict；dict 形态 / 无 results → 跳过该天，记 warning
- 至少需要 N 天有效才有曲线；不足返回 `degraded` + 提示需积累

### 契约 C：前端展示（量化终端风格）
- 三策略净值 vs 基准 多线图
- **水下图** 回撤可视化
- 指标卡(收益/夏普/索提诺/回撤/卡玛/胜率) 每策略一张
- 交易明细表(复用现有弹窗方式)
- 数据不足时明确提示"仅X天有效数据，需积累"

## WS 分解（TDD，每个先写失败测试）

### WS0 验证前置
- [ ] 修复根因的最小改动：`load_score_history` 过滤非 list；`run_comparison` 跳过非 dict
- [ ] 写 RED 测试复现崩溃 → 修 → GREEN
- [ ] Git 基线 clean，建分支 `feat/backtest-comparison-v2`

### WS1 数据健壮性（契约B）
- [ ] TDD: `load_score_history` 遇 dict 形态不崩、返回仅合法 list 快照
- [ ] TDD: `scan_snapshot` 缺失天数 → status=degraded/missing
- [ ] 兼容 latest 快照

### WS2 对比引擎重构（契约A）
- [ ] TDD: `run_comparison` 对脏数据不抛异常，返回统一 status
- [ ] 加入基准线（沪深300）数据源（yfinance/baostock 已有）
- [ ] metrics 补全（年化/夏普/索提诺/回撤/卡玛/胜率 已统一)

### WS3 前端重构（契约C）✅
- [x] 净值曲线多线 + 基准叠加（归一化首日=1.0, 沪深300虚线, 窗口对齐_benchmark_window_days）
- [x] 水下图(回撤) ✅ 新 underwaterChart canvas
- [x] 指标卡（量化终端风格）✅ 超额α vs基准
- [x] 数据不足状态展示 ✅ 基准缺失提示 / strategies[0].note
- [x] 交易明细弹窗(复用)
- [x] 附加: 胜率口径修正(盈利卖出/卖出数) silverquant 23.8%→49%

### WS4 walk-forward + 交互增强（P1）✅
- [x] WF 对比开关（前端 checkbox + 周期数下拉, 后端 walk_forward/cycles/test_days 透传）
- [x] 参数(周期/标的)可调后对比（周期数 2/3/5 可选, 标的/日期已可调）

### WS5 自测 + 端点验证 + 提交

## 验收标准
- 点「运行回测」不再报错，任意脏数据/缺失均显示明确状态
- 三策略净值+基准 + 回撤水下图 + 指标卡 全呈现
- TDD: 每个 WS 先失败测试后实现
- 全量测试 219+ passed 无回归

## 风险
- 快照数据不足(4个) → WS1 兼容 latest + WS4 walk-forward 用真实回测数据兜底
- yfinance 限频 → 基准用已缓存指数(baostock^或本地)