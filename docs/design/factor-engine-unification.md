# 因子引擎统一方案

> **状态**: 草案 | **日期**: 2026-07-03 | **作者**: 面基投研系统
>
> 本文档分析当前双引擎并存的现状、评估统一迁移的风险与收益，并给出分阶段实施方案。

---

## 目录

- [一、摘要](#一摘要)
- [二、双引擎现状](#二双引擎现状)
- [三、引擎对比详表](#三引擎对比详表)
- [四、影响分析](#四影响分析)
- [五、统一方案](#五统一方案)
- [六、推荐方案与理由](#六推荐方案与理由)
- [七、实施计划](#七实施计划)
- [八、迁移清单](#八迁移清单)
- [九、风险评估与回滚方案](#九风险评估与回滚方案)
- [十、测试策略](#十测试策略)

---

## 一、摘要

当前 Hermes 投资系统存在**两套并行的因子引擎**：

1. **旧引擎** `analysis/factor_scanner.py`（v3.1）：使用固定区间线性插值评分（如 ROE 0-30 → 1-10 分），产出 6 个风格因子。直接驱动每日日报管线（`run_daily.py`）和三策略建仓/清仓逻辑。

2. **新引擎** `analysis/factor_engine.py`（v4.0）：使用截面百分位排序（`scipy.rankdata`），产出 19 个子因子 → 7 个风格因子，评分范围 [0, 1]。具备 IC 滚动权重、贝叶斯收缩、宏观条件调整、三层票池管理等高级特性。**但仅用于独立脚本 `run_factor_daily.py`，与主管线完全割裂。**

这导致以下问题：

- 日报和三策略使用旧引擎，新引擎的能力完全未被利用；
- 两套引擎的评分范围（[1,10] vs [0,1]）、因子定义、权重机制互不兼容；
- `evaluator_fixed.py` 的 19 只核心票固定评分基于旧引擎范围；
- 无法在全系统统一因子评价口径，策略对比缺乏一致性基础。

**本文档提出三种统一方案，推荐"渐进迁移 + 适配层"方案，分三个里程碑实施，预计 4-6 周完成。**

---

## 二、双引擎现状

### 2.1 旧引擎（v3.1 — FactorScanner）

文件：`analysis/factor_scanner.py`（631 行）

**评分方式**：`_bounded_linear_score(value, (lo, hi))` —— 将因子原始值通过固定参考区间的线性插值映射到 [1, 10]。例如 ROE 0-30% 映射到 1-10 分。**不是真实截面百分位**，而是"硬编码经验区间"。

**6 个风格因子**：质量、价值、成长、低波、红利、动量。

**权重来源**：从 `MacroEngine` 获取，基于 `config.FACTOR_WEIGHTS` 中的固定宏观状态映射表。四个状态（复苏/扩张/过热/衰退）各有固定权重。

**额外修饰**：Perez 阶段乘数（0.55-1.15）、利润池评分、技术面加成（0-1 分）。

**使用方**：

| 调用方 | 调用方式 | 关键阈值 |
|--------|---------|---------|
| `scripts/run_daily.py` | `scanner.scan_market_batch()` | 评分≥6.0 进入日报展示 |
| `run_daily.py` 模拟盘 | `scan_results[i]["score"]` | 建仓≥5.0，清仓<4.0 |
| `strategies/faceji.py` | `score_map: dict[str, float]` (1-10) | 建仓≥5.0，清仓<4.5 |
| `strategies/silverquant.py` | `score_map: dict[str, float]` (1-10) | 建仓≥5.0 |
| `strategies/tradingagents.py` | `score_map: dict[str, float]` (1-10) | 辩论≥5.5，弱卖<5.0 |
| `evaluator_fixed.py` | `FIXED_SCORE_MAP`（19 只核心票） | 固定值 3.5-6.2 |

### 2.2 新引擎（v4.0 — FactorEngine）

文件：`analysis/factor_engine.py`（935 行）

**评分方式**：`standardize_cross_section()` —— 使用 `scipy.stats.rankdata` 对全截面标的做百分位排序，输出 [0, 1]。天然对异常值鲁棒，真实反映相对强弱。

**19 个子因子 → 7 个风格因子**：

| 风格因子 | 子因子数 | 子因子列表 |
|---------|---------|-----------|
| quality | 5 | ROE, 毛利率, 负债率, 每股经营现金流, 净利率 |
| value | 3 | PE 历史分位, PB, PE-TTM |
| growth | 3 | 营收增速, 净利增速, ROE 加速度 |
| momentum | 3 | 20 日动量, 60 日动量, 120 日动量 |
| low_vol | 2 | 20 日波动率, 60 日最大回撤 |
| sentiment | 2 | 量比, 换手率 |
| risk | 2 | PE 过高风险, 60 日波动风险 |

**权重来源**：三层融合 —— IC 滚动权重（过去 6 个月）+ 宏观条件调整乘数 + 贝叶斯收缩（James-Stein）。最终公式为 `0.7 * IC_base + 0.3 * conditional_weight`。

**附加能力**：PoolManager 三层动态票池（Watch/Monitor/Deep）。

**使用方**：

| 调用方 | 调用方式 | 说明 |
|--------|---------|------|
| `scripts/run_factor_daily.py` | `engine.score_batch()` + `pm.update_pools()` | 独立运行，不接入主管线 |

---

## 三、引擎对比详表

| 维度 | v3.1 (FactorScanner) | v4.0 (FactorEngine) |
|------|---------------------|---------------------|
| **文件** | `analysis/factor_scanner.py` | `analysis/factor_engine.py` |
| **代码行数** | 631 | 935 |
| **评分范围** | **[1, 10]** | **[0, 1]** |
| **评分方法** | 固定区间线性插值 | 截面百分位排序 (scipy.rankdata) |
| **异常值处理** | 手动截断（如 ROE 截断到 60） | 天然鲁棒（排序对异常值不敏感） |
| **风格因子数** | **6 个** | **7 个** |
| **子因子数** | 无显式子因子层 | **19 个** |
| **因子定义** | 质量/价值/成长/低波/红利/动量 | 质量/价值/成长/动量/低波/情绪/风险 |
| **因子差异** | 有红利, 无情绪/风险 | 有情绪/风险, 无红利 |
| **权重机制** | MacroEngine 固定权重（4 状态映射表） | IC 滚动(60%) + 贝叶斯收缩(10%) + 宏观调整(30%) |
| **权重自适应** | 手动切换宏观状态 | 每日自动滚动计算 |
| **额外修饰** | Perez 乘数 + 利润池评分 + 技术加成 | 无 |
| **票池管理** | 无独立池管理 | PoolManager 三层池 |
| **数据路由** | baostock/AKShare（旧 data_layer） | data_router（新统一层）+ yfinance fallback |
| **港股/美股支持** | 有限（仅 A 股路径） | 通过 data_router 多市场路由 |
| **单标评分** | `score_stock(symbol)` | `score_symbol(symbol)` / `score_batch(symbols)` |
| **批次扫描** | `scan_market_batch()`（支持跨 cron 续扫） | `score_batch()`（一次性） |
| **输出格式** | 单一综合分 + 6 因子分 + 技术面 | 7 因子分 + 19 子因子明细 + 权重 + 数据质量 |
| **主管线接入** | **是**（run_daily.py 日报+模拟盘） | **否**（仅 run_factor_daily.py） |
| **策略接入** | faceji / silverquant / tradingagents | 无 |
| **评估器接入** | evaluator_fixed.py 固定评分 | 无 |

---

## 四、影响分析

### 4.1 直接切换 v4.0 会破坏什么

若直接将 `run_daily.py` 的 `FactorScanner` 替换为 `FactorEngine`，**不做任何适配**，以下组件将全部失效：

#### 4.1.1 策略阈值全部失准

三个策略的决策阈值基于 [1,10] 范围：

| 策略 | 字段 | 旧阈值 [1,10] | 新引擎等效值 [0,1] | 若直接传入新值 |
|------|------|--------------|-------------------|---------------|
| faceji | `entry_threshold` | 5.0 | ~0.50 | **几乎不会建仓**（0.5 × 10 = 5，但实际分布中位数并非 0.5） |
| faceji | `exit_threshold` | 4.5 | ~0.45 | 同上 |
| faceji | `hard_stop_loss_pct` | -8% | 不变（价格维度） | ✅ 不受影响 |
| silverquant | `entry_threshold` | 5.0 | ~0.50 | 同上 |
| tradingagents | `debate_entry_threshold` | 5.5 | ~0.55 | 同上 |
| tradingagents | `debate_force_sell` | 4.0 | ~0.40 | 同上 |
| run_daily 模拟盘 | 建仓条件 | score ≥ 5.0 | ~0.50 | 同上 |
| run_daily 模拟盘 | 清仓条件 | score < 4.0 | ~0.40 | 同上 |

**根因**：v4.0 的截面百分位输出在大量标的时天然接近均匀分布（均值≈0.5），而 v3.1 的固定区间映射不保证分布均匀。同一只票在两套引擎下的相对位置可能完全不同。

#### 4.1.2 evaluator_fixed.py 固定评分失效

`evaluator_fixed.py` 中的 `FIXED_SCORE_MAP` 硬编码了 19 只核心票的评分（3.5-6.2 区间），这些值来自旧引擎的固定评分口径。切换到新引擎后，所有 Walk-Forward 回测的输入评分都不再匹配策略阈值。三类回测（faceji/silverquant/tradingagents）均无法产生有意义的建仓信号。

#### 4.1.3 日报展示语义混乱

`run_daily.py` 的日报中对扫描结果有多处基于 [1,10] 范围的判断逻辑：

- `scan_results[i].get("score", 0) >= 6.0` — 链外发现阈值
- `score_range < 1.5 and avg_score < 6.5` — 信号质量偏低
- `avg_score >= 6.5` — 信号质量良好
- 评分分布展示（如 `综合{score:.1f}分`）

若直接切换，这些判断全部失效。

#### 4.1.4 缺失因子影响

v4.0 **删除了红利因子**，但 `config.FACTOR_WEIGHTS` 的默认配置和四个宏观状态均包含红利。新引擎的权重计算不输出红利，而旧代码中红利在衰退期权重高达 0.22。

v4.0 **新增了情绪和风险因子**，但 v3.1 的下游（策略、日报）均未设计这两个维度的展示和使用逻辑。

#### 4.1.5 缺失 Perez 乘数和利润池评分

旧引擎的 `score_stock()` 在基础评分之上叠加：
- **Perez 阶段乘数**（0.55-1.15）：根据产业链所处的技术扩散阶段调整评分
- **利润池评分**：根据标的在产业链中的利润池位置调整（0.7×因子分 + 0.3×利润池分）

新引擎完全不包含这两层逻辑。直接切换会导致部分处于"导入期高赔率"产业链的标的评分**系统性偏低**。

#### 4.1.6 批量扫描能力差异

旧引擎的 `scan_market_batch()` 支持跨 cron 分批续扫——这对 `run_daily.py` 在 baostock 连接不稳定的生产环境下至关重要。新引擎的 `score_batch()` 是一次性批量处理，大扫描量可能超时或触发数据源限流。

### 4.2 新引擎的能力优势

尽管直接切换有风险，v4.0 的核心优势不可忽视：

1. **截面百分位排序**：`scipy.rankdata` 的统计意义上的百分位比固定区间线性映射更科学，自动适应全市场估值中枢的变化。例如 2024 年 PE 中位数从 30x 升至 45x 时，固定区间打分法会系统性高估所有票的价值得分，而截面法不受影响。

2. **IC 滚动权重**：过去 6 个月的因子有效性数据驱动权重调整，避免"衰退期机械降成长权重"的滞后性问题。宏观状态判定存在时间延迟，IC 滚动可以提前捕获因子有效性的变化。

3. **贝叶斯收缩**：样本不足时向等权收缩，防止小样本偏差放大。

4. **三层票池管理**：Watch → Monitor → Deep 的晋级机制比旧引擎的单一评分列表更利于长期跟踪。

5. **多市场数据路由**：`data_router` 统一支持 A 股、港股、美股的 PE/PB 获取和 fallback，旧引擎主要走 baostock。

6. **细粒度因子分解**：19 个子因子提供了更丰富的诊断信息（如可以区分"动量强但质量差"和"质量强但动量弱"）。

---

## 五、统一方案

### 方案 A：直接替换（激进）

**做法**：将 `run_daily.py` 中的 `FactorScanner` 全部替换为 `FactorEngine`，修改所有策略阈值从 [1,10] 到 [0,1]，删除 `factor_scanner.py`。

**优点**：彻底统一，无技术债。

**缺点**：
- 所有策略阈值需要重新标定——改动面极大且缺乏回测验证；
- `evaluator_fixed.py` 的 19 只固定评分需要全部重算，破坏了"固定评估口径"的约束；
- 缺失 Perez 乘数和利润池评分需要在新引擎中重新实现；
- 缺失红利因子需要在策略中做补偿；
- 批量跨 cron 扫描能力需要在新引擎中重建；
- 日报的全部展示阈值需要重新校准；
- **高概率导致策略停止建仓或误建仓**。

**风险等级**：🔴 高

---

### 方案 B：渐进迁移 + 适配层（推荐）

**做法**：在新引擎外包裹一个适配层（Adapter），将 v4.0 的 [0,1] 输出转换为 [1,10]，同时保留 Perez 乘数等旧引擎修饰逻辑。分阶段迁移：

1. **Phase 1**：建立 Adapter，使新引擎输出兼容现有下游（范围对齐）
2. **Phase 2**：将日报和策略逐步切换到 Adapter 输出
3. **Phase 3**：评估新引擎因子优于旧引擎后，逐步将阈值调优到新引擎原生范围
4. **Phase 4**：移除旧引擎，清理适配层

**优点**：
- 下游改动最小化——策略、日报、评估器无需立即修改阈值；
- 每一步都可以独立验证和回滚；
- 新旧引擎可以并行运行做对比验证；
- 降低生产事故风险。

**缺点**：
- 适配层本身是过渡性技术债，需要在 Phase 4 清理；
- 实施周期较长（4-6 周）；
- 范围映射不可避免地引入信息损失。

**风险等级**：🟡 中

---

### 方案 C：混合双引擎（保守）

**做法**：保持双引擎独立，明确职责分工：

- **FactorScanner（v3.1）**：继续用于日报、策略的评分和建仓/清仓决策
- **FactorEngine（v4.0）**：独立运行，仅用于票池管理（PoolManager）和补充性因子分析，不直接驱动交易决策

日报中增加"新引擎对比"面板，让两套评分同时展示供人工参考。

**优点**：
- 零风险——现有管线完全不受影响；
- 新引擎可以继续独立迭代和验证；
- 人工可以逐步建立对新引擎的信任。

**缺点**：
- **不是真正的统一**——双引擎长期并存增加维护负担；
- 策略决策仍基于旧引擎的固定区间法，无法享受截面法的优势；
- 两套评分在日报中并存可能造成使用者的认知混乱；
- 因子定义的差异（红利 vs 情绪/风险）无法调和。

**风险等级**：🟢 低

---

## 六、推荐方案与理由

**推荐方案 B：渐进迁移 + 适配层。**

理由如下：

1. **旧引擎的固定区间法在长期不可持续**：估值中枢变化时固定区间失真，这是结构性问题，不是参数调优能解决的。截面法才是正确的长期方向。

2. **方案 A 的"一刀切"在生产环境中风险不可接受**：策略阈值重新标定需要至少 3-6 个月的回测验证。当前系统在三策略并行的生产状态下，不允许策略长期停摆。

3. **方案 C 不是统一方案**：双引擎并存只是拖延问题。适配层的技术债是可接受的一次性成本，远小于长期维护两套引擎的成本。

4. **适配层提供了"安全网"**：在 Phase 1-3 期间，适配层保证了向下兼容。一旦发现新引擎评分与策略行为不匹配，可以立即回退到旧引擎，不触及生产。

---

## 七、实施计划

### 里程碑 M1：适配层 + 并行验证（Week 1-2）

**目标**：建立 `analysis/factor_adapter.py`，使新引擎输出通过适配层后能替代旧引擎输出。新旧引擎并行运行，对比评分差异。

**任务**：

1. **创建 `analysis/factor_adapter.py`**：
   - 实现 `FactorAdapter(FactorEngine)` 包装类
   - `score_stock_adapter(symbol) → dict`：返回旧格式（score 1-10, 6 factors）
   - `score_batch_adapter(symbols) → list[dict]`：批量评分 + 格式转换
   - 内部调用 `FactorEngine.score_batch()`，将 [0,1] composite 映射到 [1,10]
   - 映射策略：使用 `min-max` 缩放或 `percentile` 保持（视分布而定）

2. **因子映射处理**：
   - v4.0 的 7 风格因子 → v3.1 的 6 风格因子
   - sentiment + risk → 合并/忽略（Phase 1 先忽略，Phase 3 再引入）
   - v3.1 的 dividend → 从 v4.0 的 quality 中近似替代，或设为中性值 5.0
   - Perez 乘数和利润池评分 → 在适配层中重新计算

3. **并行对比脚本 `scripts/compare_engines.py`**：
   - 同时调用 `FactorScanner.score_stock()` 和 `FactorAdapter.score_stock_adapter()`
   - 对 WATCHLIST 全部标的做逐票对比
   - 计算评分相关性（Spearman ρ）、排名一致性（Kendall τ）
   - 输出差异报告（评分偏差 > 1.5 的标的）

4. **验收标准**：
   - 适配层输出格式与 `FactorScanner.score_stock()` 完全兼容（字段名、范围）
   - 并行对比报告显示 Spearman ρ > 0.6
   - 无明显系统性偏差（某个因子方向全市场偏高或偏低）

### 里程碑 M2：日报切换（Week 3-4）

**目标**：`run_daily.py` 的扫描部分使用适配层输出，旧引擎保留为 fallback。

**任务**：

1. **修改 `run_daily.py`**：
   - 导入 `FactorAdapter`
   - `scanner = FactorAdapter()` 替代 `FactorScanner()`
   - 保留 `FactorScanner` 作为 fallback（try/except + 环境变量开关）
   - 适配 `scan_market_batch` 的跨 cron 续扫逻辑（或简化）

2. **修改日报展示逻辑**：
   - 所有阈值判断改为适配层输出的 [1,10] 范围
   - 因子有效性部分（2.3）从旧格式改为适配层输出

3. **灰度发布**：
   - 通过环境变量 `FACTOR_ENGINE=adapter` 控制
   - 先在工作日 18:00 收盘简报中启用
   - 观察 3 个交易日无异常后推广到全部日报

4. **验收标准**：
   - 日报正常生成，飞书文档无格式异常
   - 扫描结果 TOP10 的标的与旧引擎重叠度 ≥ 60%
   - 模拟盘建仓/清仓行为无异常突变（3 个交易日内新建仓数 ≤ 旧引擎日均的 150%）

### 里程碑 M3：策略 + 评估器迁移（Week 5-6）

**目标**：策略和 `evaluator_fixed.py` 完全切换到适配层输出，旧引擎正式退役。

**任务**：

1. **策略阈值重新标定**：
   - 基于适配层输出运行 3-6 个月历史回测
   - 确定新引擎下的等效建仓/清仓阈值
   - 更新 `FacejiConfig`、`SilverQuantConfig`、`TradingAgentsConfig`

2. **更新 `evaluator_fixed.py`**：
   - 重新计算 19 只核心票在适配层下的固定评分
   - 更新 `FIXED_SCORE_MAP`
   - 运行全量 Walk-Forward 回测确认策略表现不退化

3. **引入新因子**：
   - 情绪因子（sentiment）和风险因子（risk）开始参与综合评分
   - 在策略中增加情绪/风险的独立判断逻辑（如 sentiment < 0.3 → 降权）
   - 更新 `FACTOR_WEIGHTS` 配置，将红利替换为情绪+风险

4. **清理**：
   - 移除 `run_daily.py` 中的环境变量开关和旧引擎 fallback
   - 标记 `factor_scanner.py` 为 deprecated
   - 删除适配层中的过渡映射逻辑，直接使用新引擎原始 [0,1] 输出
   - 更新所有文档

5. **验收标准**：
   - 三个策略的 Walk-Forward 回测 Sortino 不退化（允许 ±0.05 波动）
   - `run_daily.py` 只依赖 `factor_engine.py`
   - `factor_scanner.py` 标记 deprecated

---

## 八、迁移清单

### 需要修改的文件

| 文件 | 里程碑 | 改动内容 | 风险 |
|------|--------|---------|------|
| `analysis/factor_adapter.py` | M1 | **新建**。包装 FactorEngine，输出兼容旧格式 | 中 |
| `scripts/compare_engines.py` | M1 | **新建**。并行对比脚本 | 低 |
| `scripts/run_daily.py` | M2 | 替换 FactorScanner → FactorAdapter；调整阈值判断；添加 fallback | 高 |
| `scripts/run_factor_daily.py` | M2 | 可选择并入 run_daily.py，或保留独立 | 低 |
| `strategies/faceji.py` | M3 | 阈值重新标定；增加情绪/风险因子判断 | 中 |
| `strategies/silverquant.py` | M3 | 阈值重新标定 | 低 |
| `strategies/tradingagents.py` | M3 | 阈值重新标定；辩论模式适配新因子 | 中 |
| `strategies/base.py` | M3 | Config 参数更新 | 低 |
| `evaluator_fixed.py` | M3 | FIXED_SCORE_MAP 重算；增加新引擎回测模式 | 中 |
| `config.py` | M3 | FACTOR_WEIGHTS 更新（红利 → 情绪+风险）；新增 ADAPTER_CONFIG | 中 |
| `docs/ARCHITECTURE.md` | M3 | 更新因子引擎架构描述 | 低 |
| `docs/API.md` | M3 | 更新数据格式文档 | 低 |

### 不需要修改的文件（但需要确认兼容性）

| 文件 | 原因 |
|------|------|
| `output/report_v6.py` | 通过 run_daily.py 间接调用，格式不变 |
| `output/shadow_account.py` | 接收的 scores 格式不变（适配层保证） |
| `output/strategy4_portfolio.py` | 同上 |
| `analysis/factor_quality.py` | 需要在 M3 适配新引擎输出格式 |
| `dashboard/` | 前端展示阈值可能需要调整（M3） |

### 可废弃的文件

| 文件 | 废弃时间 | 说明 |
|------|---------|------|
| `analysis/factor_scanner.py` | M3 完成后 | 标记 deprecated，保留 1 个版本周期后删除 |
| `analysis/factor_adapter.py` | M3 Phase 4 完成后 | 适配层逻辑融入 FactorEngine 或移除 |
| `backup_20260525_115538/factor_scanner.py` | M3 完成后 | 旧备份 |

---

## 九、风险评估与回滚方案

### 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 新引擎评分排名与旧引擎差异过大 | 中 | 中 | M1 并行对比验证 + Spearman ρ 门禁 |
| 策略在新评分下误建仓/不建仓 | 中 | 高 | M2 灰度发布 + 模拟盘先行 + 人工监控 3 天 |
| 跨 cron 续扫逻辑在新引擎下不可用 | 低 | 中 | M2 简化扫描量或在新引擎中重建分批能力 |
| 数据路由兼容性问题（港股/美股） | 低 | 中 | M1 全 WATCHLIST 标的逐一验证 |
| 红利因子缺失导致衰退期策略偏差 | 中 | 中 | M2 在适配层中补充红利因子近似计算 |
| 评估器固定评分重算后回测结果退化 | 中 | 高 | M3 Walk-Forward 全量验证 + Sortino 门禁 |

### 回滚方案

每个里程碑都有独立的回滚路径：

**M1 回滚**：删除 `factor_adapter.py` 和 `compare_engines.py`，无其他改动。回滚成本为零。

**M2 回滚**：将 `run_daily.py` 中的 `FACTOR_ENGINE` 环境变量改为 `legacy`，或直接 git revert。日报和模拟盘立即恢复旧引擎。回滚时间 < 5 分钟。

**M3 回滚**：策略 Config 和评估器改动通过 git revert 恢复。如已删除旧引擎文件，从 git history 恢复。回滚时间 < 30 分钟。

**灾备原则**：`factor_scanner.py` 在所有 Phase 完成并稳定运行 2 周之前**不删除**，保留 `# deprecated` 标记即可。

---

## 十、测试策略

### 10.1 单元测试（M1）

```
test_factor_adapter.py
├── test_score_range()         # 验证输出在 [1,10]
├── test_output_format()       # 验证字段兼容 FactorScanner.score_stock()
├── test_batch_output()        # 验证批量输出排序正确
├── test_dividend_fallback()   # 验证红利因子 fallback 值合理
└── test_empty_input()         # 验证空输入不崩溃
```

### 10.2 对比测试（M1-M2）

```
compare_engines.py (每日运行)
├── 全 WATCHLIST 标的 Spearman ρ 计算
├── 排名 TOP10 重叠度
├── 单票评分偏差 > 1.5 的预警
└── 按产业链和宏观状态的子集对比
```

门禁标准：Spearman ρ ≥ 0.6，否则阻塞 M2 启动。

### 10.3 集成测试（M2）

- 在 staging 环境运行完整 `run_daily.py`（使用适配层），验证飞书文档正常生成
- 模拟盘回放：取历史 10 个交易日的价格，对比新旧引擎的模拟盘建仓/清仓行为
- 端到端时间：日报生成时间不超过旧引擎的 120%

### 10.4 回测验证（M3）

- 所有三个策略运行 Walk-Forward 回测（`evaluator_fixed.py --all --walk-forward --cycles 3`）
- 对比迁移前后的 Sortino 比率，允许 ±0.05 的波动
- 如果任一个策略 Sortino 退化 > 0.05，阻塞 M3 发布，返回调优阈值

### 10.5 生产监控（M2-M3）

- 日报中的"信号质量"指标（均分、区间宽度）与历史基线对比
- 模拟盘日度收益率与旧引擎时期的滚动对比
- 异常告警：单日新建仓 > 5 只 或 单日清仓 > 3 只（超过旧引擎 3σ 范围）

---

## 附录

### A. 因子映射速查

| v3.1 因子 | v4.0 因子 | 映射关系 |
|-----------|-----------|---------|
| 质量 | quality | 一一对应（v4.0 子因子更丰富） |
| 价值 | value | 一一对应 |
| 成长 | growth | 一一对应 |
| 低波 | low_vol | 一一对应 |
| 动量 | momentum | 一一对应 |
| 红利 | — | 无对应，适配层用 quality 子因子近似或设中性 |
| — | sentiment | 新增，M3 引入 |
| — | risk | 新增，M3 引入 |

### B. 阈值对照表

| 场景 | v3.1 阈值 [1,10] | v4.0 等效 [0,1] | 适配层 [1,10] |
|------|------------------|-----------------|--------------|
| faceji 建仓 | ≥ 5.0 | ≈ 0.50 | ≥ 5.0 |
| faceji 清仓 | < 4.5 | ≈ 0.45 | < 4.5 |
| faceji MA 趋势豁免 | ≥ 5.5 | ≈ 0.55 | ≥ 5.5 |
| silverquant 建仓 | ≥ 5.0 | ≈ 0.50 | ≥ 5.0 |
| tradingagents 辩论建仓 | ≥ 5.5 | ≈ 0.55 | ≥ 5.5 |
| tradingagents 强卖 | < 4.0 | ≈ 0.40 | < 4.0 |
| 模拟盘建仓 | ≥ 5.0 | ≈ 0.50 | ≥ 5.0 |
| 模拟盘清仓 | < 4.0 | ≈ 0.40 | < 4.0 |
| 日报链外发现 | ≥ 6.0 | ≈ 0.60 | ≥ 6.0 |
| 日报信号优良 | ≥ 6.5 | ≈ 0.65 | ≥ 6.5 |

> 注："v4.0 等效"是理想化的线性映射 0→1、10→10，实际分布取决于截面标的数。适配层会在 M1 中根据真实分布做非线性映射。

### C. 关键代码引用

| 组件 | 文件 | 行号 |
|------|------|------|
| FactorScanner 评分方法 | `analysis/factor_scanner.py` | `score_stock()` L226 |
| FactorScanner 固定区间映射 | `analysis/factor_scanner.py` | `_bounded_linear_score()` L38 |
| FactorScanner 批次扫描 | `analysis/factor_scanner.py` | `scan_market_batch()` L463 |
| FactorEngine 截面标准化 | `analysis/factor_engine.py` | `standardize_cross_section()` L99 |
| FactorEngine 批量评分 | `analysis/factor_engine.py` | `score_batch()` L703 |
| FactorEngine 权重计算 | `analysis/factor_engine.py` | `ICWeightSystem.get_weights()` L273 |
| ICWeightSystem 贝叶斯收缩 | `analysis/factor_engine.py` | `conditional_weight()` L254 |
| PoolManager 三层池 | `analysis/factor_engine.py` | `update_pools()` L814 |
| 宏观权重矩阵 | `config.py` | `FACTOR_WEIGHTS` L36 |
| 面基策略阈值 | `strategies/base.py` | `FacejiConfig` L65 |
| SilverQuant 阈值 | `strategies/base.py` | `SilverQuantConfig` L80 |
| TradingAgents 阈值 | `strategies/base.py` | `TradingAgentsConfig` L93 |
| 评估器固定评分 | `evaluator_fixed.py` | `FIXED_SCORE_MAP` L59 |
| 日报调用 FactorScanner | `scripts/run_daily.py` | L73, L390 |
| 日报模拟盘阈值 | `scripts/run_daily.py` | L695, L741 |
