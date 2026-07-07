# 交易引擎与策略体系 — 审计评估报告

> 审计时间: 2026-07-06
> 项目根目录: `/home/admin/.hermes/investment_system`

---

## 1. analysis/trading_engine.py — 交易引擎

### 类层次

```
Signal                          # 交易信号数据类
TradeCalendar                   # 交易日历 + 周频规则检查
BaseStrategy                    # 策略基类
  ├── FacejiStrategy            # 委托 strategies/faceji.decide()
  ├── SilverQuantStrategy       # 委托 strategies/silverquant.decide()
  └── TradingAgentsStrategy     # 委托 strategies/tradingagents.decide()
TradingEngine                   # 主调度器
```

### 核心方法

| 类 | 方法 | 职责 |
|---|---|---|
| `Signal` | `__init__`, `to_dict` | 信号封装/序列化 |
| `TradeCalendar` | `can_trade`, `record_trade`, `is_black_swan` | 周频规则(1次/策略/周, 3次/总/周), 冷却, 黑天鹅 |
| `BaseStrategy` | `execute_buy`, `execute_sell`, `load_state`, `save_state` | 通用交易执行, 状态持久化 |
| `FacejiStrategy` | `daily_step` → _faceji_pure.decide() | 面基策略代理 |
| `SilverQuantStrategy` | `daily_step` → _sq_pure.decide() | SilverQuant代理 |
| `TradingAgentsStrategy` | `daily_step` → _ta_pure.decide() | TradingAgents代理 |
| `TradingEngine` | `run_daily`, `_resolve_conflicts`, `_filter_by_weekly_rule`, `execute_signal` | 调度3策略, 冲突解决(面基优先), 周频过滤, 模拟盘执行 |

### 评级: **A**

**优势:**
- ✅ 清晰的三层分离: 引擎(调度) → 策略(代理) → 纯函数(策略逻辑)
- ✅ 冲突解决机制完善: 同一标的多策略冲突时面基优先
- ✅ 交易纪律内置: 周频限制、冷却期、黑天鹅豁免
- ✅ 模拟盘自动执行 + 状态持久化
- ✅ 输出结构完整: 信号+模拟盘+持仓+组合快照

**不足:**
- ⚠️ `_positions_to_pd()` 在三策略中重复实现(可以提升到基类)
- ⚠️ 黑天鹅检测过于简化(仅依赖宏观看跌)
- ⚠️ `_get_name()` 三策略重复

---

## 2. strategies/ 纯函数层

### 文件结构

```
strategies/
├── __init__.py          # 包导出
├── base.py              # 纯数据类型: Signal, PositionData, FacejiConfig, SilverQuantConfig, TradingAgentsConfig
├── faceji.py            # 面基纯决策函数 decide()
├── silverquant.py       # SilverQuant纯决策函数 decide()
└── tradingagents.py     # TradingAgents纯决策函数 decide()
```

### 统一接口

所有策略遵循同一签名:
```python
def decide(score_map, tech_map, price_map, positions, cash, config) -> list[Signal]
```

### 各策略决策逻辑

| 策略 | 建仓逻辑 | 清仓逻辑 | 仓位管理 |
|---|---|---|---|
| **faceji** | 评分≥5.0 + MA趋势过滤 + 候选TOP5 | 4层: 硬止损(-8%) → 回落止盈(-12%) → 评分下滑(<4.5) → MA死叉+评分<5 | 半凯利(odds=2.0, fraction=0.5) |
| **silverquant** | 评分≥5.0 + 候选TOP5 | 4层: 硬止损(-8%) → 回落止盈(-12%) → MA死叉+亏损> -5% → 评分下滑(<4.5) | 固定¥30K/槽位 |
| **tradingagents** | 辩论分≥5.5 + 候选TOP3 | 3层: 辩论强卖(<4.0) → 硬止损(-8%) → 弱持仓(<5.0+亏损) | 半凯利(odds=1.8, fraction=0.5) |

### 评级: **A**

**优势:**
- ✅ **纯函数**: 零IO、零全局修改、零外部API调用 — 完全可测试
- ✅ 一致接口: 所有策略同签名, 可互换
- ✅ Config dataclass: 参数化, 无需硬编码
- ✅ 多层风控: 每策略3-4层独立卖出组件
- ✅ 良好文档: 纯函数职责清晰

**不足:**
- ⚠️ 三个策略的评分输入相同, 区分度不够大(依赖相同`score_map`)
- ⚠️ 无单元测试文件在strategies/目录下
- ⚠️ `faceji.py` 的 `_kelly_size` 与 `tradingagents.py` 的Kelly计算略有重复

---

## 3. evaluator_fixed.py — 固定评估器

### 评估方法

| 组件 | 职责 |
|---|---|
| `WalkForwardSplit` | Train{252d} + Test{63d}, stride=63, cycles=N |
| `load_price_history` | 数据加载+pickle缓存 |
| `compute_technicals` | MA20/60偏离, RSI14, MACD |
| `run_backtest` | 逐日模拟: 独立策略+组合净值 |
| `_compute_metrics` | 主评分=Sortino, +Sharpe, 最大回撤, 胜率, 年化收益 |
| `run_walk_forward` | Walk-Forward多窗+汇总 |
| `save_to_run_log` | 实验账本(data/hl_runs/) |

### 固定口径(不可为提分修改)

- 固定标的池: 19只核心标的(来自backtest_v2)
- 固定评分: 预置FIXED_SCORE_MAP
- 固定参数: 120天窗口, ¥1M本金, 万1.5佣金+千1印花税+千1滑点
- 主评分: **Sortino比率**

### 评级: **A**

**优势:**
- ✅ **固定评估标准**: 明确声明"禁止为提分修改" — 防止过拟合
- ✅ Walk-Forward支持: 滚动训练/测试, 防未来策略
- ✅ 完整成本模型: 佣金+印花税+滑点+最低佣金
- ✅ Sortino为主评分(优于Sharpe, 只考虑下行风险)
- ✅ 实验账本: 每次运行保存到data/hl_runs/
- ✅ DSR统计检验支持
- ✅ 直接调用strategies/纯函数 — 与引擎层解耦

**不足:**
- ⚠️ `run_backtest` 与 `run_walk_forward` 有大量代码重复(相同的逐日循环复制了两次)
- ⚠️ 成本计算在run_backtest和run_walk_forward中使用不同方式(一个用cost_model, 一个直接计算)
- ⚠️ 固定评分不太现实 — 实际交易中评分会变化

---

## 4. backtest_v2.py 与 evaluator_fixed 的关系

### 关系图谱

```
backtest_v2.py (旧版/内联)
│
├── 定义了 19只评分标的 ←── evaluator_fixed.py 继承
├── 内联策略实现(非strategies/纯函数)
├── 简单回测(无WF, 简单成本)
└── 单一指标(总收益+Sharpe)
        │
        ▼ 演化方向
evaluator_fixed.py (新版/固定标准)
│
├── 使用 strategies/ 纯函数 (通过 importlib 动态导入)
├── Walk-Forward 评估
├── 完整成本模型
├── Sortino主评分
└── 实验账本+DSR检验
```

### 关键差异

| 维度 | backtest_v2.py | evaluator_fixed.py |
|---|---|---|
| 策略实现 | 内联(duplicate of strategies/) | 动态导入strategies/纯函数 |
| 回测方式 | 全窗口一次回测 | 标准回测 + Walk-Forward |
| 主指标 | 总收益率% + Sharpe | **Sortino比率** |
| 成本模型 | 无 | 佣金+印花税+滑点+最低佣金 |
| 实验记录 | 保存JSON | 保存+实验账本 |
| 评估严谨性 | 低 | 高(FIXED标准) |
| 代码复用 | 有(与strategies/重复) | 无重复(直接调用) |

### 评级: **C** (backtest_v2.py)

**结论:** `backtest_v2.py` 是**遗留代码**, 其策略逻辑与 `strategies/` 纯函数重复, 评估方法不如 `evaluator_fixed.py` 严谨。**建议废弃**, 所有评估应走 `evaluator_fixed.py`。

---

## 5. factor_engine.py vs factor_scanner.py — 双引擎并存

### 对比总览

| 维度 | factor_scanner.py (v3.1) | factor_engine.py (v4.0) |
|---|---|---|
| **状态** | "已退役"(header标注) | 当前引擎 |
| **评分范围** | 1-10 (固定区间线性映射) | [0,1] (真截面百分位) |
| **标准化方法** | `_bounded_linear_score`(固定区间) | `standardize_cross_section`(百分位) |
| **权重系统** | `config.FACTOR_WEIGHTS`(固定) | `ICWeightSystem`(滚动IC+宏观调整+贝叶斯收缩) |
| **子因子** | ~6个风格因子(内联计算) | 22个子因子, 8风格因子(声明式定义) |
| **业务层** | 无 | `PoolManager`(三层动态票池) |
| **兼容层** | 无 | `FactorScannerCompatV4`(v3.1 API兼容) |
| **代码行** | 634行 | 1174行 |
| **多标评分** | 逐只评分(无截面) | `score_batch()`(真截面百分位) |

### 双引擎并存问题

- `factor_scanner.py` 标注"已退役"但仍完整可用
- `audit.py` (第162行) 仍直接 `from analysis.factor_scanner import FactorScanner`
- v4.0 有 `FactorScannerCompatV4` 提供v3.1兼容API, 但v3.1的 `_get_perez_multiplier` / `_get_profit_pool_score` 未移植到v4
- 两个引擎可能产生不同评分, 导致下游不一致

### 评级: **B**

**优势(factor_engine.py):**
- ✅ 三层分离架构(数据→标准化→聚合)
- ✅ 真截面百分位标准化
- ✅ IC滚动权重 + 宏观条件调整 + 贝叶斯收缩
- ✅ 批量评分支持真截面
- ✅ PoolManager三层动态票池
- ✅ v3.1兼容层(平滑迁移)

**不足(双引擎):**
- ❌ `factor_scanner.py` 标注退役但未删除, 仍被引用
- ⚠️ v3.1的 `_get_perez_multiplier`(Perez阶段乘数) 和 `_get_profit_pool_score`(利润池评分) 未移植到v4
- ⚠️ 单标评分时(`score_symbol`)无法做截面标准化, 退化为固定映射
- ⚠️ 1174行代码偏大, 建议拆分
- ⚠️ `ICWeightSystem` 的IC数据需要定期更新, 否则权重退化

---

## 6. chain_scanner.py / stop_list.py / audit.py

### chain_scanner.py — 产业链分析

- 12条产业链定义(英伟达算力链、台积电先进制程、机器人、半导体等)
- 静态知识框架: 利润池↔瓶颈↔方向性偏好
- 评分: 利润池厚度(0-5) + 位置权重(0-3) + 瓶颈度(0-2)
- 支持WATCHLIST映射

**评级: B** — 好的知识框架, 但纯静态声明式, 无动态数据, 链→标的映射需手动维护

### stop_list.py — 不为清单过滤

- 段永平10条不为清单规则
- `StopListRule` + `StopListFilter` 框架
- `apply()`: 逐条检查 → 一票否决(high) / 警告(medium)
- `filter_candidates()`: 批量过滤 + 分数调整(-2.0 ~ 0.0)
- 分数调整: high失败 -0.5, medium -0.2

**评级: A** — 实现优雅, 结构清晰, 可测试, 框架支持自定义规则扩展

### audit.py — 六层漏斗审计

- 6层: 宏观气候→资产配置→多因子引擎→找票执行→风控监控→交易纪律
- 每层: 审计函数 → 发现项 + 覆盖率% + A-F评级
- 依赖JSON文件: `macro_engine_cache.json`, `scan_snapshot_latest.json`, `trading_signals.json`, `shadow_account.json`
- 内建 `rating()`: ≥90%=A, ≥70%=B, ≥50%=C, ≥30%=D, <30%=F

**评级: B** — 概念优秀(6层漏斗), 结构清晰, 但依赖文件系统且引用旧版`factor_scanner`(第162行)

---

## 汇总评级表

| 模块 | 评级 | 关键理由 |
|---|---|---|
| **trading_engine.py** | **A** | 三层分离, 委托纯函数, 冲突解决, 交易纪律, 状态持久化 |
| **strategies/ 纯函数层** | **A** | 统一接口, 纯函数, 可测试, 多层风控, Config参数化 |
| **evaluator_fixed.py** | **A** | 固定标准(FIXED), Walk-Forward, Sortino主评分, 成本模型, 实验账本 |
| **backtest_v2.py** | **C** | 遗留代码, 策略逻辑重复, 评估不严谨, 建议废弃 |
| **factor_engine.py** | **B** | v4架构优秀(三层+IC权重+百分位), 但双引擎并存+单标无截面 |
| **factor_scanner.py** | **D** | 标注退役但仍被引用, 固定区间映射, 应移除 |
| **chain_scanner.py** | **B** | 知识框架完整, 但纯静态+手动映射 |
| **stop_list.py** | **A** | 实现优雅, 框架可扩展, 可测试 |
| **audit.py** | **B** | 概念优秀, 但依赖文件系统且引用旧版引擎 |

### 总体评估: **B+**

### 建议行动项

1. **高优先级**: 删除 `factor_scanner.py` (或将 `_get_perez_multiplier` / `_get_profit_pool_score` 移植到v4)
2. **高优先级**: `audit.py` 第162行改为引用 `FactorScannerCompatV4`
3. **中优先级**: 废弃 `backtest_v2.py`, 所有评估统一走 `evaluator_fixed.py`
4. **中优先级**: 抽取三策略中重复的 `_positions_to_pd()` / `_get_name()` 到 `BaseStrategy`
5. **中优先级**: `evaluator_fixed.py` 的 `run_backtest` 和 `run_walk_forward` 去重
6. **低优先级**: 为 `strategies/` 添加单元测试
7. **低优先级**: `factor_engine.py` 拆分到多个文件(当前1174行)
