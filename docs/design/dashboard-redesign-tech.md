# 面基三源融合 · Dashboard 重构 — 技术设计文档

> 本文档是设计方案的**技术实现细节**。配套文档：`docs/design/dashboard-redesign-v1.md`（产品设计）

---

## 铁律：快准全新

| 维度 | 要求 | 实现方式 |
|------|------|---------|
| 快 | 首页渲染<1s，证据包<500ms（lazy） | 证据包按需加载（展开才请求），首页只用聚合指标 |
| 准 | 数据零错误 | price=0过滤已实现；缓存TTL过期检测+降权；双源验证（已有） |
| 全 | 不遗漏必要维度 | 每条证据链必须完整（不能跳步），缺数据时标注NOT_AVAILABLE而非忽略 |
| 新 | 数据新鲜>80% | 数据质量API标记过期数据；过期数据在Dashboard上自动降级/灰显 |

---

## 一、EvidencePacket 统一数据结构

所有证据链共享的 dataclass。`engine/evidence_builder.py`

```python
@dataclass
class EvidencePacket:
    """统一证据包 — 每个评分/信号/决策共享"""
    
    # ─ 结论（核心输出）
    claim: str                    # 自然语言结论
    confidence: float             # [0,1] 置信度（基于历史准确率+数据新鲜度）
    
    # ─ 推理链（可展开，按时间/逻辑顺序排列）
    chain: list[EvidenceStep]
    # EvidenceStep = {order: int, label: str, data: dict, rationale: str, source: str}
    # 例：order=1, label="因子评分", data={composite:0.72}, rationale="质量因子拉高", source="FactorEngine"
    
    # ─ 为什么高 & 为什么低
    why_high: list[str]           # 如["ROE 28%(行业前10)", "毛利率91%(冠军)"]
    why_low: list[str]            # 如["PE百分位89%(偏贵)", "动量20d落后同行"]
    
    # ─ 考虑了但排除了什么（展现决策空间）
    alternatives: list[dict]      # [{symbol, score, rejected_reason}, ...]
    rejected_candidates: list[str]  # 被质量门控或风险检查排除的
    
    # ─ 诚实标记的未知领域
    unknowns: list[str]           # 如["该标的2025年报尚未发布", "北向资金数据延迟2天"]
    
    # ─ 验证计划
    verify_plan: str              # "5天后回查价格↑/↓方向"
    
    # ─ 数据质量
    data_quality: float           # 所用数据源的新鲜度综合评分 [0,1]
    data_dependency: list[dict]   # [{source: "baostock", freshness: "fresh", last_update: "2026-07-08 08:00"}]
```

### 分层证据链（chain 字段的典型顺序）

```
① 数据层：price来自哪、财务数据来自哪、新鲜不新鲜
② 因子层：19个子因子原始值→截面百分位→8风格因子→加权综合分
③ 信号层：score_to_signal转换→阈值对比→信号判定
④ 策略层：三策略各自decide→冲突解决→优先级
⑤ 执行层：双门状态→建仓6查→TrailStop检查→月平衡
⑥ 验证层：过去类似信号的历史准确率
⑦ 归因层：如果这是持仓，收益/亏损的因子分解
```

---

## 二、模块细化

### 2.1 ExecutionChecker (新增)

`engine/execution_checker.py`

功能：计算每个候选/持仓的执行状态

输入：因子评分 + 双门状态 + TrailingStop 参数 + 建仓条件

输出：
```python
{
  "symbol": "600519",
  "action": "BUY" | "SELL" | "HOLD" | "WAIT",
  "action_confidence": 0.85,
  
  # 建仓6项检查（如果是候选）
  "build_checklist": {
    "dual_gate_open": {"status": True, "detail": "绿灯+黄灯=谨慎操作"},
    "macro_ok": {"status": True, "detail": "象限=扩张期"},
    "technical_ok": {"status": True, "detail": "price>MA60, MA20>MA60"},
    "quality_gate": {"status": True, "detail": "ROE 28%>0, 营收+15%>-30%"},
    "position_limit": {"status": True, "detail": "A股当前22%<上限25%"},
    "single_stock_limit": {"status": True, "detail": "2%上限=¥20K, 建议1%=¥10K"}
  },
  
  # TrailStop 状态（如果是持仓）
  "trail_stop": {
    "status": "safe" | "warning" | "critical",
    "distance_pct": 10.5,          # 当前距止损线的%
    "bucket": "盈利10-30%",        # <10天/盈利>30%/盈利10-30%/其它
    "stop_price": 162.8,           # 当前止损价
    "peak_price": 185.0,
    "current_price": 182.0,
    "rule_description": "盈利≥30%(+37.5%) → 峰值×0.88=¥162.8"
  },
  
  # 替代方案（仅BUY信号）
  "alternatives": [
    {"symbol": "000858", "score": 6.2, "chain": "消费-白酒", "rejected": "链内选茅台更好"},
    {"symbol": "002304", "score": 5.8, "chain": "消费-白酒", "rejected": "评分低0.4"}
  ],
  
  # 验证历史
  "historical_accuracy": {
    "n_similar_signals_30d": 4,
    "hit_rate": 0.75,              # 3/4
    "avg_return_5d": "+2.1%",
    "by_score_band": {"6-7": {"n": 3, "hit": 2}, "7-8": {"n": 1, "hit": 1}}
  }
}
```

### 2.2 ChainEvidence (新增)

`research/chain_evidence.py`

功能：给定标的 → 链定位 + 利润池评分 + 尼克四问

```python
def build_chain_evidence(symbol: str, score_data: dict) -> dict:
    """
    输出示例:
    {
      "chain": "消费-白酒",
      "chain_position": "消费-白酒-高端",
      "profit_pool_score": 9.0,    # 0-10, 利润池最厚
      "perez_stage": "展开期",
      "perez_multiplier": 1.15,    # 从config.INDUSTRY_CHAINS获取
      "meso_layer": "L4-公司壁垒",
      "self_reliant_rate": ">60%", # 国产化率（非必要但重要）
      "nick_q4": {
        "q1_why_now": {"answer": "消费复苏+茅台供需缺口持续", "evidence": ["CPI稳定1.2%", "高端白酒库存下降"]},
        "q2_why_company": {"answer": "白酒链利润池顶端(毛利率91%)", "evidence": ["ROE加速3年>0", "品牌护城河=最宽"]},
        "q3_why_price_ok": {"answer": "PEG=1.8有确定性溢价", "evidence": ["PE=30,历史中位数32", "DCF支撑¥160-200"]},
        "q4_why_wrong": {"answer": "宏观衰退或消费降级", "evidence": ["止损线¥160(-12%)", "最大亏损=¥7,500"]},
        "rating": "A",
        "rating_rationale": "四问全过+估值合理+右侧确认"
      }
    }
"""
```

数据来源：`config.INDUSTRY_CHAINS`（15条链定义）+ `config.WATCHLIST`（标的归属）+ `data_router`（财务数据）+ `research/deep_research_v2.py`（LLM分析）

### 2.3 SignalValidator (新增)

`engine/signal_validator.py`

功能：定期检查历史信号的方向正确性

```python
def validate_signals(lookback_days=30) -> dict:
    """从 signal_accuracy_history.json 统计"""
    return {
        "by_score_band": {
            "8-10": {"n": 5, "correct": 5, "hit_rate": 1.0, "avg_return_5d": "+4.2%"},
            "6-8": {"n": 12, "correct": 9, "hit_rate": 0.75, "avg_return_5d": "+2.1%"},
            "4-6": {"n": 8, "correct": 4, "hit_rate": 0.50, "avg_return_5d": "-0.8%"},
            "0-4": {"n": 3, "correct": 0, "hit_rate": 0.0, "avg_return_5d": "-3.5%"}
        },
        "overall": {"n": 28, "hit_rate": 0.64},
        "recommendation": "分数>6的信号可信度较高(75%), <4的信号不可信"
    }
```

验证流程：
1. `run_trading.py` 每次运行时，读 `trading_signals.json` 中前N天的信号
2. 查这些标的的今日价格 vs 信号日的价格
3. 方向正确（BUY后涨 / SELL后跌）→ correct=True
4. 写入 `signal_accuracy_history.json`

### 2.4 LayerStatus聚合器 (新增)

`engine/layer_status.py`

功能：聚合 L1-L6 各层的当前状态，供给 Dashboard 横条

```python
def get_all_layer_status() -> dict:
    return {
        "l1_macro": {
            "dual_gate": {"macro": "绿", "trend": "黄"},
            "quadrant": "扩张期",
            "trend_temp": "温(+8%)",
            "cpi": {"value": 1.2, "momentum": "+0.1%/月"},
        },
        "l2_allocation": {
            "target": {"A股": 25, "ETF": 20, "债券": 10, "黄金": 15, "商品": 15, "美股": 20, "港股": 10},
            "actual": {"A股": 22, "ETF": 18, "债券": 12, ...},
            "rebalance_needed": False,
            "days_to_month_end": 12,
        },
        "l3_l4_stock_picking": {
            "candidates": {"total": 12, "new_today": 2, "nick_passed": 8},
            "chains_active": ["算力链", "机器人", "白酒"],
            "top_candidates": [
                {"symbol": "600519", "score": 7.2, "nick_rating": "A"},
                {"symbol": "300502", "score": 6.8, "nick_rating": "B"}
            ]
        },
        "l5_risk": {
            "status": "normal",
            "triggered_stops": 0,
            "max_drawdown": -3.2,
            "max_drawdown_limit": -15.0,
        },
        "l6_discipline": {
            "weekly_trades": 1, "weekly_limit": 3,
            "rebalance_done": True,
        }
    }
```

### 2.5 MarketIntel (新增，P2)

`research/market_intel.py`

功能：聚合市场参与者的信息

```python
def get_market_intel() -> dict:
    return {
        "institutional": {
            "northbound_net_flow": 12.5,      # 亿
            "northbound_trend": "inflow_3d",    # 3日趋势
            "etf_flow": {"沪深300ETF": "+50亿", "科创50ETF": "+12亿"}
        },
        "retail_sentiment": {
            "dragon_tiger_inst_vs_retail": {"inst_net_buy": 13.93, "retail_net_buy": 17.08},
            "retail_participation": "增温"       # 龙虎榜上榜标的数
        },
        "chain_activity": {
            "active_chains": ["算力链", "机器人"],
            "chain_signals": [
                {"chain": "光模块", "signal": "利润池扩张(毛利率环比+2%)", "impact": "利好300502"}
            ]
        }
    }
```

数据源：`research/dragon_tiger.py` + `news/pipeline.py`（情绪） + 北向资金AKShare API + `config.NORTHBOUND_CONFIG`

### 2.6 证据包组装器 (EvidenceBuilder)

`engine/evidence_builder.py`

功能：接收多个模块的输出 → 组装成统一的 EvidencePacket

```python
class EvidenceBuilder:
    def __init__(self):
        self.chain_evidence = ChainEvidence()
        self.execution_checker = ExecutionChecker()
        self.signal_validator = SignalValidator()
    
    def build(self, symbol: str, score_data: dict, position: dict = None, 
              macro_state: dict = None, chain_data: dict = None) -> EvidencePacket:
        """
        组装单个标的的完整证据包
        输入: 因子数据 + 双门状态 + 链定位 + 执行状态
        输出: EvidencePacket（统一格式）
        """
        evidence_chain = []
        evidence_chain.append(self._data_quality_step(symbol))
        evidence_chain.append(self._factor_step(symbol, score_data))
        evidence_chain.append(self._signal_step(symbol, score_data))
        
        if macro_state:
            evidence_chain.append(self._macro_step(macro_state))
        
        if chain_data:
            evidence_chain.append(self._chain_step(chain_data))
        
        if position:
            evidence_chain.append(self._trail_stop_step(position))
        
        evidence_chain.append(self._verification_step(symbol))
        
        return EvidencePacket(
            claim=self._build_claim(symbol, evidence_chain),
            confidence=self._calc_confidence(evidence_chain),
            chain=evidence_chain,
            why_high=self._extract_high_evidence(evidence_chain),
            why_low=self._extract_low_evidence(evidence_chain),
            alternatives=score_data.get("alternatives", []),
            unknowns=self._detect_unknowns(symbol),
            verify_plan=self._build_verify_plan(symbol),
            data_quality=self._calc_data_quality(evidence_chain),
            data_dependency=self._extract_sources(evidence_chain)
        )
```

---

## 三、API 改造

### 3.1 新增端点

| 方法 | 端点 | 功能 | 新增文件 |
|------|------|------|---------|
| GET | `/api/v2/execution/board` | 执行决策区核心数据 | `api_execution.py` |
| GET | `/api/v2/execution/build-checklist/{symbol}` | 单个标的建仓6查 | `api_execution.py` |
| GET | `/api/v2/execution/trail-stop/{symbol}` | 单个持仓TrailStop状态 | `api_execution.py` |
| GET | `/api/v2/layers/status` | 六层指标行数据 | `api_layers.py` |
| GET | `/api/v2/layers/macro` | L1宏观详情 | `api_layers.py` |
| GET | `/api/v2/layers/allocation` | L2配置详情 | `api_layers.py` |
| GET | `/api/v2/evidence/nick-four/{symbol}` | Nick四问 | `api_evidence.py` |
| GET | `/api/v2/evidence/chain-map/{symbol}` | 链映射+利润池 | `api_evidence.py` |
| GET | `/api/v2/market/intel` | 市场情报聚合 | `api_market.py` |

### 3.2 现有端点改造

| 端点 | 新增字段 |
|------|---------|
| `/api/v2/pool` | 每只候选加 `evidence.why_high, evidence.why_low, evidence.build_checklist` |
| `/api/v2/portfolio/detail` | 每个持仓加 `evidence.trail_stop, evidence.attribution, evidence.build_history` |
| `/api/v2/evidence/signal-accuracy` | 按分数段/策略分解命中率 |

### 3.3 快准全新实现

**快** — Lazy Loading：
```
首页渲染 → 只加载 /api/v2/layers/status（6个聚合值，<1KB）
          + /api/v2/execution/board（决策卡片索引，<2KB）
点击展开 → 加载 /api/v2/evidence/factor-breakdown/{symbol}（详细证据包）
```

**准** — 双源验证 + price=0过滤（已有）+ 过期降权：
```
data_quality >= 0.8 → 证据包正常显示
data_quality 0.5-0.8 → 证据包带⚠️标记
data_quality < 0.5 → 证据包灰显，标注"数据过期，仅供参考"
```

**全** — 强制完整性检查：
```
证据链至少 4/7 步完整才能展示
不足4步 → 标注"数据不足，请手动调研"
缺失项必须显式标注（NOT_AVAILABLE），不能跳步
```

**新** — 自动过期检测 + 缓存TTL：
```
每个证据包带 data_dependency（数据源+更新时间）
前台按最老数据源的时间决定包整体新鲜度
过期 >3x TTL → 包整体降级
```

---

## 四、前端改造

### 4.1 HTML 结构变化

当前（8个Tab平铺，模拟盘默认）：
```html
<div class="nav">
  <a>模拟盘</a> <a>回测对比</a> <a>票池</a> <a>ETF</a>
  <a>龙虎榜</a> <a>新闻</a> <a>日报</a> <a>证据</a>
</div>
<div id="tab-dashboard">...</div>  <!-- 默认显示 -->
```

新布局（六层横条+执行决策区置顶+6个Tab）：
```html
<div id="six-layer-bar">
  <!-- L1-L6 紧凑横条，每个可点击展开详情 -->
  <div class="layer l1">双门:绿+黄 | CPI 1.2% | 温度:温</div>
  <div class="layer l2">A股25% | ETF20% | 债券10% | ...</div>
  <div class="layer l3-l4">候选3只 | Nick⭐⭐.⭐ | 链2条活跃</div>
  <div class="layer l5">🚨止损0 | 距上限12%</div>
  <div class="layer l6">本周1/3次 | 月平衡✅</div>
</div>

<div id="execution-board">
  <!-- 每日执行决策区（首页默认） -->
  <div class="signal-card buy">...</div>    <!-- TO BUY -->
  <div class="signal-card sell">...</div>   <!-- TO SELL -->
  <div class="signal-card hold">...</div>   <!-- TO HOLD -->
  <div class="signal-card wait">...</div>   <!-- TO WAIT -->
</div>

<div class="nav">
  <a class="active">📊 今日决策</a>   <!-- 新首页 -->
  <a>📈 回测对比</a>
  <a>🎯 票池</a>
  <a>📦 ETF</a>
  <a>📰 新闻</a>
  <a>📋 日报</a>
</div>
```

### 4.2 执行决策卡片渲染

每个信号卡片格式：
```
┌─────────────────────────────────────────────┐
│ 🟢 BUY   600519 茅台     ¥172-182          │ ← 顶部：动作+代码+价格区间
│ 置信度: 0.85 | 建仓6查: 5/6 ✅              │ ← 置信度+检查进度
├─────────────────────────────────────────────┤
│ 证据链                                        │
│ ① 因子：评分7.2(★★★★☆)   │ 双门:绿+黄 ✅  │
│ ② 链：消费-白酒 · 利润池顶端 · Perez防御期    │
│ ③ Nick:⭐⭐⭐⭐ · A级                      │
│ ④ 候补：000858(6.1分), 002304(5.8分)        │
│ ⑤ 历史验证: 同类信号75%命中率               │
│ ⑥ 未知: 2025年报未出 ⚠️                    │
├─────────────────────────────────────────────┤
│ 📊 展开因子证据    📋 展开链分析             │ ← 可点击展开
└─────────────────────────────────────────────┘
```

点击「展开因子证据」→ 浮层显示完整因子分解（19子因子→8风格→综合分，每层可看）

### 4.3 数据质量 Badge（全局可见）

页面左上角：
```
🟢 数据质量 A (0.92) | 7/12数据源最新
🟡 数据质量 C (0.62) | ⚠️5/12数据源过期
🔴 数据质量 D (0.35) | ❌今日大部分数据不可信
```

Badge 依据 `/api/v2/evidence/data-quality` 的 `grade` 字段。

---

## 五、实施计划（7 切片）

| 切片 | 内容 | 预估 | 依赖 |
|------|------|------|------|
| S1 | EvidencePacket + EvidenceBuilder + API改造 | 4h | — |
| S2 | ExecutionChecker + execution board API + 前端决策卡片 | 4h | S1 |
| S3 | LayerStatus聚合器 + 六层横条前端 | 3h | S1,S2 |
| S4 | ChainEvidence + Nick四问 + 前端链证据 | 3h | S1,S3 |
| S5 | 持仓透明化（TrailStop可视化+归因） | 3h | S1,S2 |
| S6 | SignalValidator + 历史验证 | 2h | S1 |
| S7 | MarketIntel + 市场情报面板（P2） | 3h | S1,S4 |

## 六、文件清单

### 新增文件
| 文件 | 行数预估 | 用途 |
|------|---------|------|
| `engine/evidence_builder.py` | 200 | 证据包组装器 |
| `engine/execution_checker.py` | 250 | 建仓6查+TrailStop+执行状态 |
| `engine/layer_status.py` | 150 | L1-L6聚合器 |
| `engine/signal_validator.py` | 100 | 信号验证统计 |
| `research/chain_evidence.py` | 200 | 链证据+Nick四问 |
| `research/market_intel.py` | 150 | 市场情报聚合 |
| `dashboard/api_execution.py` | 100 | 执行决策API |
| `dashboard/api_layers.py` | 80 | 六层指标API |
| `dashboard/api_market.py` | 80 | 市场情报API |

### 修改文件
| 文件 | 改动 |
|------|------|
| `dashboard/server.py` | 注册3个新router |
| `dashboard/templates/dashboard_main.py` | 大规模重构（新首页+六层横条+执行卡片+证据展开） |
| `dashboard/api_portfolio.py` | 每个持仓加evidence字段 |
| `dashboard/api_pool.py` | 每个候选加evidence字段 |
| `dashboard/api_evidence.py` | 新增Nick四问+链映射端点 |
| `scripts/run_trading.py` | SignalValidator调用 |
