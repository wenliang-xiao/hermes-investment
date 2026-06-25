# 四源融合深度分析：面基 × SilverQuant × TradingAgents × hl-quant

> 目标：吸收四个项目精华，让面基策略架构最优秀，且有模拟盘+专业日报的竞争优势
> 原则：不推翻现有系统，只进化

---

## 一、四个项目的核心贡献

### 1. 面基（现有系统）—— 多维因子 + 产业链 + 日报

| 能力 | 优势 | 不足 |
|------|------|------|
| **六因子评分**（FactorScanner） | 覆盖质量/价值/成长/低波/股息/动量 | 评分更新慢（baostock限速），缺乏动态IC跟踪 |
| **产业链分析**（chain_scanner） | 12条链利润池+瓶颈度，独有 | 尚未深度融入策略决策 |
| **三策略并行**（trading_engine） | 面基+SQ+TA同台对比 | 策略逻辑与IO/状态混在一起，diff困难 |
| **模拟盘**（strategy_states.json） | 三个独立¥100万模拟盘 | 无基线回归检查 |
| **日报系统**（飞书发布） | 信号驱动+链+新闻，完整闭环 | 缺少失败归因记录 |
| **新闻管线**（GLM-4-Flash） | 免费，无金融内容过滤 | 时效性一般 |

**核心竞争力**: 产业链视角（12条链利润池） + 自动化日报 + 三策略同台

### 2. SilverQuant —— 组件化风控

| 能力 | 核心价值 | 我们已采纳 |
|------|---------|-----------|
| **HardSeller** (-8%) | 硬止损，锁定单笔最大亏损 | ✅ 已融入FacejiStrategy |
| **FallSeller** (-12% peak) | 峰值回落止盈，保护浮盈 | ✅ 已融入 |
| **ScoreDropSeller** (<4.5) | 基本面恶化即卖 | ✅ 已融入（收紧到4.5） |
| **MASeller** (死叉+亏损<5%豁免) | 技术恶化+亏损不深才卖 | ✅ 已融入 |
| **固定¥30K槽位** | 简单等权，无需计算 | 我们改用Kelly（更优） |

**最大价值**: 4层卖出的优先级设计（硬止损>回落>评分>均线），层次清晰

### 3. TradingAgents —— 辩论制 + Kelly仓位

| 能力 | 核心价值 | 我们已采纳 |
|------|---------|-----------|
| **辩论裁决** (bull/bear/neutral) | 多维度信号融合 | 独立运行，未与面基融合 |
| **Kelly动态仓位** | 置信度越高仓位越大 | ✅ 已融入FacejiStrategy |
| **辩论分强卖** (<4.0) | 完全看空卖出 | ❌ 未采纳（面基用评分<4.5替代） |
| **弱持仓** (<5.0 + 亏损) | 不看好的亏损持仓及时止损 | 等价于面基ScoreDrop |

**最大价值**: Kelly公式与置信度挂钩（高评分=高仓位），辩论制思路可作为辅助信号

### 4. hl-quant —— 固定评估器 + HL循环

| 能力 | 核心价值 | 我们的差距 |
|------|---------|-----------|
| **固定评估器** | 评估口径锁定，候选策略严格可比 | ❌ 无——策略在3个文件里复制，无统一评估 |
| **单一可编辑程序** | 只改strategy.py，不改评估器 | ❌ 策略逻辑与执行/IO/状态混在一起 |
| **HL 8步循环** (Probe→Diagnose→Propose→Patch→Evaluate→Replay→Decide→Compress) | 结构化策略优化流程 | ❌ 无——想到什么改什么 |
| **Sortino单一评分** | 只惩罚下行波动，可排序 | ❌ 多指标并行但无权重决策 |
| **反过拟合纪律** | 经济含义门槛+禁止窄坑+训练/验证切分 | ❌ 无制度化纪律 |
| **实验账本** (trials.jsonl) | 跨轮次记录教训 | ❌ 无 |
| **失败归因** | 可解释的失败分析 | ❌ 日报只展示结果 |
| **基线不退化** (harness.sh) | 新候选不输旧基线 | ❌ 无回归测试 |
| **压缩历史** | 删除无效/重叠规则 | ❌ 策略只叠加不清理 |
| **AGENTS.md 工作契约** | 制度化持续学习 | 我们靠Memory+Skills，已部分对齐 |
| **common-pitfalls.md** | 踩坑沉淀 | ❌ 无统一承载文件 |

---

## 二、核心洞见对比：固定评估器

### hl-quant 的推理链

```
问题：如何确保策略优化不是假优化？

hl-quant 答案：
  ┌──────────────────────────────────────────┐
  │ 让评估口径绝对固定                       │
  │  → 候选之间唯一差异 = strategy.py 的变化  │
  │  → 分数变化 = 策略本身的变化              │
  │  → 严格更好才算数                         │
  └──────────────────────────────────────────┘

传统量化的死亡螺旋（hl-quant 防止的）：
  改策略 → 改评估口径 → score变高 → "优化了" → 实盘崩
```

### 我们当前的问题

```python
# 三个不同评估口径，无法直接比较
backtest_v2.py:          19只固定评分 + 60天窗口 → Sharpe
backtest_all_strategies.py: 因子扫描 + 120天窗口 → 多指标
run_trading.py（每日）:    实时31只评分 → 信号优先级
```

同一策略改动在这三个口径下的表现可能不一致——你不知道改的是策略本身，还是评估口径差异。

### 我们的优势可以补充hl-quant

hl-quant 只跑单一标的（上证指数）、只有一个均线策略。我们有：
- **三策略并行**：可以比较同一个评估口径下三种策略的表现
- **多标的**：31只核心池可以评估策略在全市场的泛化能力
- **实时模拟盘**：可以从回测到模拟盘形成闭环

---

## 三、融合方案：不推翻的进化路径

### 核心思路

```
hl-quant 的固定评估器        → 我们的 evaluator_fixed.py（新增）
hl-quant 的单一可编辑程序     → 我们的 strategies/faceji.py（提取纯函数）
hl-quant 的 HL 循环          → 我们的策略改进流程（制度化）
hl-quant 的反过拟合纪律+账本  → 我们的 data/hl_runs/ + docs/guide/pitfalls.md
SilverQuant 的4层风控         → 已融入
TradingAgents 的 Kelly+辩论  → 已融入（辩论可作为辅助信号）
面基的产业链+日报+模拟盘      → 不变
```

### 只新增，不改现有

```
# 新增模块（不触动现有代码）
investment_system/
├── evaluator_fixed.py       # [新增] 固定评估器，唯一入口
├── strategies/              # [新增] 纯策略层
│   ├── faceji.py            #   faceji_decide() 纯函数
│   ├── silverquant.py       #   silverquant_decide() 纯函数
│   ├── tradingagents.py     #   tradingagents_decide() 纯函数
│   └── base.py              #   共享类型
├── data/hl_runs/            # [新增] 实验账本
├── docs/guide/pitfalls.md   # [新增] 踩坑沉淀
└── scripts/harness.sh       # [新增] 基线门禁
```

现有文件**完全不动**——`trading_engine.py`、`run_trading.py`、`run_report_v10.py`、`portfolio_server.py` 全部保持原样。

新增的 `strategies/` 只是从现有策略里提取纯逻辑，不改变行为。`evaluator_fixed.py` 是一个独立工具，不影响日报和模拟盘管线。

---

## 四、具体怎么融合（渐进式）

### Layer 1: 提取纯策略层（不破坏现有）

```python
# strategies/faceji.py —— 纯函数，不依赖任何外部状态
def decide(score_map, tech_map, price_map, positions, cash, config=None):
    """纯逻辑层——从 trading_engine.py 的 daily_step() 提取"""

# trading_engine.py 不改——但可以新增一个调用：
# from strategies.faceji import decide as faceji_decide
# 可选：用纯函数验证 daily_step() 的输出是否一致
```

**验证方式**: 对同一组输入数据，新旧两条路径输出完全相同的信号。

### Layer 2: 固定评估器（独立工具）

```python
# evaluator_fixed.py
# 固定数据源、固定标的池、固定区间、固定成本、固定评分公式
# 三个策略都可用它打分
# 不依赖任何生产代码

python evaluator_fixed.py --strategy faceji     # → Sortino score
python evaluator_fixed.py --strategy silverquant # → Sortino score
```

第一天就能对三个策略打出一个可比较的 baseline score。

### Layer 3: HL 循环实验（可选流程）

只在需要「系统性地改进策略」时才走 HL 循环：
1. 跑 evaluator_fixed 得 baseline
2. 在 strategies/faceji.py 提假设
3. 跑 evaluator_fixed 验证
4. 严格更好才接受
5. 记录到 data/hl_runs/

不影响日报、模拟盘、Dashboard 的日常运行。

---

## 五、关键权衡与决策点

| 决策 | hl-quant 方案 | 我们的选择 | 理由 |
|------|-------------|-----------|------|
| 评估用 Sortino 还是多指标？ | Sortino 单一分数 | **Sortino 主指标 + 多指标门槛** | 既要有排序维度也要有安全性检查 |
| 固定标的池还是全市场？ | 上证指数单一 | **固定31只核心池** | 标的越多噪声越大，31只足够评估策略 |
| 纯策略函数是否取代 daily_step？ | 是 | **并存** | daily_step 不改，新增 pure_decide 做验证和评估 |
| 策略改进走 HL 循环还是自由改？ | 强制HL | **可选HL** | 日常修 bug 不改策略逻辑的不需要HL，系统性优化时才走 |
| 实验账本记到什么粒度？ | 每轮trial | **每次策略参数改动、每次回测结果** | 记录但不过度负担 |
| 基线回归检查自动化？ | harness.sh | **evaluator_fixed --check-baseline** | 无需额外脚本 |

---

## 六、收益预估

| 改进 | 工作量 | 收益 |
|------|--------|------|
| **提取 strategies/ 纯函数** | 2-3h | 策略可diff、可评估、可回放 |
| **创建 evaluator_fixed.py** | 1-2h | 候选策略可排序、基线可追踪 |
| **建立 data/hl_runs/ 账本** | 0.5h | 跨轮次学习、失败归因记录 |
| **创建 docs/guide/pitfalls.md** | 0.3h | 踩坑沉淀 |
| **创建 scripts/harness.sh** | 0.2h | 基线不退化检查 |

**总计**: ~5小时新增，**零破坏现有代码**。

---

## 七、不要从 hl-quant 搬的

| hl-quant 做法 | 为什么不搬 |
|-------------|-----------|
| 单标的回测 | 我们需要跨标的泛化评估 |
| 满仓/空仓（非此即彼） | 我们有分档信号(BUY/SELL/HOLD)和仓位百分比 |
| 聚宽 JQData 数据源 | 我们有 EastMoney+baostock 管线，更便宜 |
| Worktree 隔离开发 | 单人项目不需要 this level of ceremony |
| 16步 Agent 工作流 | 大部分已经在 AGENTS.md 里了 |
| 只改 strategy.py 的严格限制 | 我们有时需要改数据层（加新因子），这不算是"作弊" |
