# 面基三源融合 · Dashboard 重构设计方案 v1

> 本文档是 OpenSpec 飞书评审的蓝图。请阅读后评论批注。

---

## 背景

当前 Dashboard 有 8 个面板（模拟盘/回测对比/票池/ETF/龙虎榜/新闻/日报/证据），展示了大量数据，但缺少一个核心能力：**让使用者看到每个决策的完整推理链，从而产生信任**。

核心问题：
- 展示了"评分是多少"，但没展示"为什么是这个分"
- 展示了"信号是BUY/HOLD/SELL"，但没展示"为什么是这个信号"
- 展示了"持仓和收益"，但没展示"钱从哪里赚/亏的"
- 没有展示"六层架构"如何从L1宏观→L2配置→L3选股→L4找票→L5风控→L6纪律逐层作用

---

## 设计原则

1. **每一条输出必须附证据链**：任何分数/信号/建议都必须可以从源数据→因子→评分→决策逐级展开验证
2. **六层架构是组织方式**：L1-L6 逐层展示，不是 8 个平铺标签页
3. **找票→深研→盯票→执行是核心工作流**：每个候选票/持仓附带完整证据包
4. **变化优先**（Delta tracking）：只展示"今天和昨天不一样的东西"，静态快照归周报
5. **诚实可信**：数据质量 A/B/C/D 评级透明，过期数据自动降权

---

## 新 Dashboard 设计

### 总体布局

```
┌─────────────────────────────────────────────────────┐
│  🟢 🟡 🔴 双门 Badge | 今日操作建议 | 数据质量等级  │ ← 顶栏状态
├─────────────────────────────────────────────────────┤
│  📊 L1 宏观气候 │ 📋 L2 配置  │ 🔍 L3-L4 找票     │ ← 六层指标行
│  CPI 1.2%       │ A股 25%     │ 候选 3只(2新)      │
│  双门: 绿+黄     │ ETF 20%    │ Nick⭐⭐⭐ ·⭐⭐· ⭐   │
│  温度: 温(+8%)  │ 债券 10%   │ 链: 算力/机器人    │
│                 │ 黄金 15%   │                    │
├─────────────────────────────────────────────────────┤
│  🎯 今日执行决策（最重要 — 置顶核心）                │
│  ┌─────────────────────────┐  ┌──────────────────┐ │
│  │ 信号 1: 600519 BUY      │  │ 信号 2: 300502 HOLD│ │
│  │ 证据:评分6.2(6>候补)    │  │ 证据:评分5.8但已     │ │
│  │     双门绿+黄=可操作    │  │     持有11天、盈利    │ │
│  │     链:消费-白酒(推进)  │  │     +4.3%在Trailing  │ │
│  │     Nick Q1-Q4:⭐⭐⭐⭐  │  │     保护范围内        │ │
│  │     建仓6查: 5/6 ✅      │  │     ⚠️MA60偏离开    │ │
│  │     候补:000858(4.8分)  │  │     始收窄=需关注   │ │
│  └─────────────────────────┘  └──────────────────┘  │
│  📊 持仓风控    止损状态    持有天    盈利   动作     │
│  600519 茅台    ✅安全      32天    +8.3%  —        │
│  300502 新易盛  ⚠️接近     11天    +4.3%  关注      │
├─────────────────────────────────────────────────────┤
│  🔎 因子证据链（可展开——每个候选/持仓点击查看）      │
│  ┌── 600519 茅台 ────────────────────────────────┐  │
│  │  ✓ 质量=0.82:  ROE 28%(前10%) · 毛利率91%(冠军)│  │
│  │  ✓ 动量=0.65:  20d+3.2%(前30%) · 60d+8.1%(前25%)│  │
│  │  ⚠️ 价值=0.32: PE百分位89%(贵,但有DCF支撑)     │  │
│  │  👑 结论:质量顶尖,动量一般,估值贵但有链逻辑支撑   │  │
│  │  📊 历史验证: 过去类似评分(>7分)的票5天涨跌+2.1%  │  │
│  └───────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│  📰 市场温度                                              │
│  机构:ETF净流入50亿(沪深300) | 游资:龙虎榜91只上榜       │
│  散户:情绪指标中性偏乐观 | 北向:净流入12亿                │
│  链跟踪:光模块环节出现利润池扩张信号                      │
└─────────────────────────────────────────────────────┘
```

### 四大核心板块

#### 板块A: 执行决策区（置顶 — 最重要）

这是新 Dashboard 的心脏。每天打开第一眼看这个。

显示内容（按优先级排序）：
1. **TO BUY 信号**（今日可以买入的候选 + 完整证据包）
2. **TO SELL 信号**（触发止损或应卖出的持仓）
3. **TO HOLD 信号**（建议持有的 + 需要关注的风险）
4. **TO WAIT 信号**（条件未满足的候选 + 缺哪一项）

每个信号必须附带 **证据包**：

```
{
  "signal": {"action": "BUY", "symbol": "600519", "size": "2%"}
  "evidence": {
    "factor_score": {"composite": 0.72, "v3": 7.2, "signal": "BUY"},
    "factor_breakdown": {
      "quality": {"score": 0.82, "why": "ROE 28%(前10%), 毛利率91%(冠军)"},
      "value": {"score": 0.32, "why": "PE百分位89%(偏贵)"},
      "momentum": {"score": 0.65, "why": "20d+3.2%(前30%)"},
      ...
    },
    "dual_gate": {"macro": "绿灯(CPI1.2%)", "trend": "黄灯(+8%)", "verdict": "谨慎操作"},
    "chain": {"name": "消费-白酒", "perez": "防御期", "profit_pool": "顶端(毛利率91%)"},
    "nick_q4": {
      "q1_now": "消费复苏+茅台供需缺口持续",
      "q2_company": "白酒利润池顶端,ROE加速度持续3年>0",
      "q3_price": "PEG=1.8偏贵但有确定性溢价,历史PE中位数附近",
      "q4_wrong": "宏观衰退或消费降级加速,止损线¥160"
    },
    "build_checklist": {
      "dual_gate": true,
      "macro_ok": true,
      "technical_ok": true,
      "quality_gate": true,
      "position_limit": true,
      "single_stock_limit": true
    },
    "alternatives": [
      {"symbol": "000858", "score": 6.1, "reason": "评分低但估值更合理"},
      {"symbol": "002304", "score": 5.8, "reason": "ROE加速中但链位置不优"}
    ],
    "historical_accuracy": {
      "similar_signals_30d": "3/4=75% correct",
      "avg_return_5d": "+2.1%",
      "mse": 0.08
    }
  }
}
```

**数据来源**：FactorEngine 评分 + ChainScanner 链定位 + MacroEngine 双门 + DeepResearch Nick四问 + SignalAccuracy 历史验证

#### 板块B: 六层指标行（紧凑横条）

**L1 宏观气候**：
- 双门状态：绿/黄/红 + 一句话结论（"今日可操作" / "谨慎操作" / "不开新仓"）
- 宏观象限：扩张/复苏/过热/衰退
- 趋势温度：凉/平/温/热 + MA60偏离%
- CPI 值 + 驱动开关状态
- 环比变化：↑↓标记

**L2 资产配置**：
- 策略四目标配比 vs 实际配比
- 偏离 > 5% 的类别标红
- 月度再平衡倒计时

**L3-L4 选股找票**：
- 候选池统计：今日新发现/总候选/通过Nick四问的
- 三层漏斗进度：L1链数→L2候选数→L3合格数
- 产业链活跃度：哪些链有新的利润池信号

**L5 风控**：
- 整体风控状态：Normal/Warning/Critical
- 触发止损的持仓数
- 组合最大回撤距警戒线

**L6 纪律**：
- 本周交易次数/上限
- 本月再平衡完成度

#### 板块C: 持仓+交易历史（比现有更透明）

每个持仓卡片显示：
- ⭐ TrailStop 动态状态（4种色彩标记）
- 🛡️ 当前距离止损线的百分比
- 📈 盈利阶段（<10天/盈利>30%/盈利10-30%/其它）
- 🔗 链定位+利润池位置
- 📊 因子分解（可展开）
- 📋 建仓时的证据包引用（构建这个决策的历史记录）

#### 板块D: 市场情报（新）

- **机构动向**：ETF 资金流、北向净买入、公募重仓变化（数据源待确认接入）
- **游资/散户**：龙虎榜分析（机构vs游资vs散户）
- **链监控**：每条产业链的异动/利润池变化/新催化剂
- **情绪指标**：新闻情绪汇总（已有）、龙虎榜散户参与度

---

## 技术架构

### 数据流

```
[Data Sources]                    [Evidence Builders]                    [Dashboard]
baostock ────┐                                                            
AKShare ────┤──→ data_router.py ──→ FactorEngine ──→ score + evidence     │
yfinance ───┤                                                             │
              │                                                            │
              ├──→ MacroEngine ──→ dual_gate + evidence                     ├──→ Dashboard API
              │                                                            │   (FastAPI)
              ├──→ ChainScanner ──→ chain_data + evidence                   │
              │                                                            │
              ├──→ DeepResearch ──→ nick_q4 + evidence                      │
              │                                                            │
              ├──→ SignalValidator ──→ historical_accuracy + evidence      │
              │                                                            │
              └──→ MarketIntel ──→ institutional + retail + evidence        │
                                                                           │
[EvidencePackets] ──────────────────────────────────────────────────────────┘
  每个模块返回 evidence 字段（结构化推理链）
```

### EvidencePackets 核心数据结构

```python
# 统一证据包格式 — 每个决策/评分/信号共享
@dataclass
class EvidencePacket:
    claim: str                    # 结论：如"BUY 600519 2%仓位"
    confidence: float             # [0,1] 置信度
    supporting_chain: list[dict]  # 支持推理链： [{step, data, rationale}, ...]
    why_high: list[str]           # 拉高分的理由
    why_low: list[str]            # 拖低分的理由
    alternatives: list[dict]      # 考虑了哪些替代方案
    considered_and_rejected: list[str]  # 排除了什么
    unknowns: list[str]           # 还不知道什么
    verify_plan: str              # "5天后回查价格方向"
    data_quality: float           # 所用数据的新鲜度评分 [0,1]
```

### API 增强

每个现有 API 端点加 `evidence` 字段：

| 端点 | 当前返回 | 增加 |
|------|---------|------|
| `/api/v2/pool` | scores | `evidence.why_high`, `evidence.why_low`, `evidence.chain`, `evidence.alternatives` |
| `/api/v2/portfolio/detail` | portfolios | `evidence.attribution`, `evidence.trail_stop_status`, `evidence.build_history` |
| `/api/v2/evidence/factor-breakdown/{symbol}` | scores | `evidence.nick_q4`, `evidence.alternatives`, `evidence.verify_history` |
| `/api/v2/news` | items | `evidence.chain_impact`, `evidence.sentiment_trend`, `evidence.inst_relevance` |
| `/api/v2/dragon_tiger` | data | `evidence.inst_vs_retail`, `evidence.capital_flow` |

### 新增模块

| 模块 | 文件 | 功能 |
|------|------|------|
| EvidenceBuilder | `engine/evidence_builder.py` | 统一的EvidencePacket组装器，带结构化推理链 |
| ChainEvidence | `research/chain_evidence.py` | 链定位→利润池→尼克四问 |
| SignalValidator | `engine/signal_validator.py` | 历史信号回查+准确率+置信度 |
| MarketIntel | `research/market_intel.py` | 基金持仓+北向+游资+情绪聚合 |
| ExecutionChecker | `engine/execution_checker.py` | 建仓6查+TrailStop状态计算+月度平衡计算 |

---

## 优先级与切片

### 切片1: 证据数据结构 + 后端API改造（P0, 4h）

1a. EvidencePacket dataclass 定义
1b. FactorEngine 输出加 evidence 字段
1c. MacroEngine 输出加 evidence 字段
1d. ChainScanner 证据输出
1e. 现有 API 端点改造（/pool, /portfolio/detail, /evidence/）

### 切片2: 执行决策区（P0, 4h）

2a. ExecutionChecker — 建仓6查、TrailStop状态计算
2b. DecisionBoard API — 聚合信号+证据包+状态
2c. 前端执行决策卡片渲染

### 切片3: 六层指标行（P1, 3h）

3a. LayerStatus聚合API
3b. 前端紧凑横条渲染

### 切片4: 持仓透明化（P1, 3h）

4a. 持仓卡片加证据包展示
4b. TrailStop状态可视化
4c. 因子分解可展开

### 切片5: 市场情报（P2, 3h）

5a. MarketIntel 数据源接入（北向/龙虎榜/新闻）
5b. 前端市场温度板块

### 切片6: Nick四问+研究证据（P2, 2h）

6a. DeepResearch 输出加 Quartet 四问结构
6b. 前端展示

---

## 完全重构vs增量改造

### 方案A（建议）：增量改造
- 保留现有8个Tab
- **执行决策区改为首页替代"模拟盘"**（因为它是最重要的）
- 六层指标行改为全局横条（在所有Tab上方）
- 持仓透明化改造现有持仓卡片
- 其余板块逐步添加

### 方案B：推倒重来
- 重新设计所有面板
- 周期长、风险高、可能丢失现有功能

---

## 风险与依赖

| 风险 | 影响 | 缓解 |
|------|------|------|
| FactorEngine 100s/3标的性能瓶颈 | 无法实时评分→证据包无法实时生成 | 先批处理+缓存 |
| Nick四问需要人工/LLM生成 | 依赖DeepResearch管线 | 先用模板+规则，再LLM增强 |
| 机构/散户数据源 | 依赖AKShare特定API | 不可用时报降级 |
| 5层证据链增加API开销 | 页面加载变慢 | evidence采用lazy loading，点击展开才加载 |
