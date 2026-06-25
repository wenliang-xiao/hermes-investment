# 面基投资系统 · 完整进化蓝图

> 编制日期：2026-06-25
> 对齐依据：全部历史对话 + 7维审计 + 4项目调研(hl-quant/SQ/TA/xalpha/OSkhQuant) + 专业回测方法论
> 原则：不推翻现有架构，只叠加进化

---

## 现状总览（目前我们有什么）

```
investment_system/
├── analysis/
│   ├── trading_engine.py      # 三策略调度器 (Faceji/SQ/TA)
│   ├── chain_scanner.py       # 12产业链利润池扫描
│   ├── factor_scanner.py      # 6因子 + LDS自适应权重
│   └── backtest_v2.py         # 旧回测 (将被替换)
├── strategies/                 # [新] 纯策略层 (hl-quant制度)
│   ├── base.py
│   ├── faceji.py              # 纯decide() ✅ 已验证与daily_step一致
│   ├── silverquant.py
│   └── tradingagents.py
├── evaluator_fixed.py          # [新] 固定评估器 (82天×19只基线已记录)
├── scripts/
│   ├── run_trading.py          # 每日信号生成+模拟盘执行 ✅ 线上9笔交易
│   ├── run_report_v10.py       # 4阶段日报 ✅ 防残篇
│   ├── manual_trade.py         # 手动交易记录
│   ├── portfolio_server.py     # FastAPI Dashboard ✅ 8686端口
│   ├── news_pipeline.py        # AKShare+GLM 新闻管线
│   ├── cache_historical.py     # [新] 数据缓存
│   └── harness.sh              # [新] 基线门禁
├── data/
│   ├── cache/                  # 32只A股×120/250天缓存 ✅
│   ├── eval_cache/             # 19只评估缓存 ✅
│   └── hl_runs/                # 实验账本
├── docs/
│   └── review/                 # 6份调研文档 ✅
├── nginx → 已修复根路由 ✅
└── cron → 盘前盘后已更新 ✅
```

**当前能力评级**：
```
找票 A-    ETF配置 F    深度分析 F    新闻解读 C+
盯盘 C     交易纪律 A-   日报 B
```

---

## 完整改造清单（12项，分组为9个PR）

### PR 1：数据地基 — 统一数据管线 + 全量缓存
**投入**：~2h | **依赖**：无（从0开始） | **风险**：低

| 改动 | 说明 |
|------|------|
| 新增 `data/data_router.py` | 前缀路由统一入口，参考 xalpha `_get_daily()` |
| 新增 `data/sources/baostock_source.py` | 现有 baostock 包装 |
| 新增 `data/sources/yahoo_source.py` | yfinance 包装（港美股） |
| 新增 `data/sources/akshare_source.py` | AKShare 包装（ETF历史+实时） |
| 修改 `scripts/cache_historical.py` | 全量拉取89只×5年，存统一格式 |
| 新增 `data/double_check.py` | 东财+新浪双源实时验证 |

**验证标准**：
```
python -c "from data.data_router import get_history; df = get_history('300502', 1200); print(len(df), 'days')"
# 输出 ≥ 1000 days  → ✅

python -c "from data.double_check import get_rt_safe; r = get_rt_safe('300502'); print(r['price'], r['volume'], r['source'])"
# 输出 价格+成交量  → ✅
```

**缓存产出**：
```
data/cache/{symbol}_{days}d.pkl
- 90+ A股 × 1200天 (baostock, 2018-2026)
- 13 美股 × 1200天 (yfinance)
- 9 港股 × 1200天 (yfinance)
- 8 ETF × 1200天 (AKShare/baostock)
总计 ~120文件，~3MB
```

---

### PR 2：评估器 v2 — Walk-Forward + 多周期 + 多标的
**投入**：~3h | **依赖**：PR 1 | **风险**：中

| 改动 | 说明 |
|------|------|
| 修改 `evaluator_fixed.py` | 新增 `--walk-forward` 模式 |
| 新增 `WalkForwardSplit` 类 | Train{252d} + Test{63d}，滚动3次 |
| 新增多周期报告模式 | 按市场状态切分回报 |
| 新增批量标的支持 | 单个命令评估89只全量 |

**Walk-Forward 设计**：
```
2021-01-01                         2026-06-01
    |                                |
    ├── Train[0:252] → Test[252:315] │ 滚动1
    │        ├── Train[63:315] → Test[315:378] │ 滚动2
    │               ├── Train[126:378] → Test[378:441]  │ 滚动3
    │                      └── ...
```

**验证标准**：
```
python evaluator_fixed.py faceji --walk-forward --cycles 3
# 输出:
#   WalkForward 1: 2021-03→2022-02 Train, 2022-02→2022-04 Test  Sortino=...
#   WalkForward 2: 2021-06→2023-05 Train, 2023-05→2023-07 Test  Sortino=...
#   WalkForward 3: 2021-09→2024-08 Train, 2024-08→2024-10 Test  Sortino=...
#   MASTER: 平均Sortino = X.XX, 最大回撤=Y.YY%
```

---

### PR 3：成本模型升级（OSkhQuant标准）
**投入**：~1h | **依赖**：无 | **风险**：低

| 改动 | 说明 |
|------|------|
| 新增 `analysis/cost_model.py` | 独立成本模块，可配置 |
| 修改 `evaluator_fixed.py` | 调用 cost_model 算每笔交易成本 |

**成本模型参数**：
```python
COMMISSION_RATE = 0.00015    # 万1.5佣金
MIN_COMMISSION = 5.0         # 最低佣金5元
STAMP_TAX_RATE = 0.001       # 千1印花税(卖出)
TRANSFER_FEE_RATE = 0.00002  # 万0.2过户费
FLOW_FEE = 0.1               # 每笔0.1元规费
SLIPPAGE_TIERS = {
    "L1": {"min_adv": 50e8, "slippage": 0.0005},    # 巨量(>50亿成交额)
    "L2": {"min_adv": 5e8, "slippage": 0.001},       # 大市(>5亿)
    "L3": {"min_adv": 1e8, "slippage": 0.003},       # 中等(>1亿)
    "L4": {"min_adv": 0, "slippage": 0.01},           # 小票(<1亿)
}
```

**验证标准**：
```
python -c "from analysis.cost_model import calc_trade_cost; print(calc_trade_cost(price=100, qty=1000, direction='buy', symbol='300502'))"
# 输出: {"slippage": X, "commission": Y, "stamp_tax": 0, "transfer_fee": Z, "flow_fee": 0.1, "total": X+Y+Z+0.1}
```

---

### PR 4：ETF回测模块（填补最大空白 F→B）
**投入**：~4h | **依赖**：PR 1 | **风险**：中

| 改动 | 说明 |
|------|------|
| 新增 `analysis/etf_allocation.py` | 资产配置模型入口 |
| 新增 `analysis/etf_backtest.py` | ETF回测引擎 |
| 新增 `analysis/allocation_strategies.py` | 多种配置模型实现 |
| 新增 `data/etf_universe.py` | ETF标的定义+分类 |

**ETF配置策略实现**（至少3种+可扩展）：
```
1. 固定比例（60/40, 50/50）         — 最简单基准
2. 风险平价（波动率倒数的协方差优化） — 最经典
3. 网格再平衡（±5%偏离触发）         — 最实用
4. [可扩展] 趋势跟踪（ma20/ma60）    — 择时版
```

**验证标准**：
```
python evaluator_fixed.py etf_60_40 --walk-forward --cycles 3
# 输出: ETF固定比例组合 5年Walk-Forward ... Sortino=...

python evaluator_fixed.py etf_risk_parity --walk-forward --cycles 3
# 输出: 风险平价组合 5年Walk-Forward ... Sortino=...

# 然后比较: 哪种配置在熊市中回撤最小？哪种在牛市中跟得上？
```

---

### PR 5：东财实时接口 + Dashboard活数据
**投入**：~2h | **依赖**：PR 1 的 double_check | **风险**：低

| 改动 | 说明 |
|------|------|
| 新增 `scripts/realtime_price.py` | 东财实时行情服务（可独立运行/被调用） |
| 修改 `scripts/portfolio_server.py` | `/api/realtime` 端点，返回全持仓实时价 |
| 修改 Dashboard HTML | 实时价格列，自动刷新（5秒轮询） |

**验证标准**：
```
curl http://localhost:8686/api/realtime
# 输出: [{"symbol":"300502","price":552.00,"change_pct":1.23,"volume":123456,"turnover_rate":2.1}]
```

---

### PR 6：重建 deep_research（8维深度研报）
**投入**：~3h | **依赖**：PR 1（需要历史数据） | **风险**：中

| 改动 | 说明 |
|------|------|
| 重建 `analysis/deep_research.py` | 8维框架：链定位/翻倍逻辑/DCF/凯利/Nick四问/贝叶斯/风险/面基引用 |
| 新增 `scripts/generate_report.py` | 对任意标的生成飞书文档研报 |

**验证标准**：
```
python scripts/generate_report.py --symbol 603259 --name 药明康德
# 输出: 飞书文档URL，8个维度全部填写
```

---

### PR 7：Dashboard升级（OSkhQuant风格指标）
**投入**：~2h | **依赖**：PR 2（新评估结果） | **风险**：低

| 改动 | 说明 |
|------|------|
| 修改 `scripts/portfolio_server.py` | 新增 /api/metrics 端点：Sortino/Alpha/Beta/连续盈亏 |
| 修改 Dashboard HTML | 3面板 + 绩效指标表 + 成本明细 + 净值曲线对比 |

**参考OSkhQuant**：每日统计表、分策略业绩卡、逐笔持仓明细

---

### PR 8：日报升级 + 盘中报警
**投入**：~3h | **依赖**：PR 4+5+6 | **风险**：中

| 改动 | 说明 |
|------|------|
| 修改 `scripts/run_report_v10.py` | 新增「回测vs模拟盘」对照；新增「上周信号回顾」；新增「因子贡献分解」 |
| 新增 `scripts/price_alert.py` | 盘中价格±3%报警，成交量同比暴增500%报警 |

---

### PR 9：DSR统计检验 + 新闻→信号映射
**投入**：~2h | **依赖**：PR 2 | **风险**：低

| 改动 | 说明 |
|------|------|
| 新增 `analysis/dsr_test.py` | Deflated Sharpe Ratio 计算 |
| 修改 `evaluator_fixed.py` | `--with-dsr` 模式 |
| 修改 `scripts/news_pipeline.py` | GLM分析结果影响评分偏移（+0.5/-0.5） |

---

## 依赖关系图

```
PR 1 (数据管线) ─┬─→ PR 2 (Walk-Forward) ─┬─→ PR 9 (DSR)
                 │                        │
                 ├─→ PR 4 (ETF回测) ───────┤
                 │                         │
                 ├─→ PR 5 (东财实时) ──→ PR 7 (Dashboard升级)
                 │                         │
                 └─→ PR 6 (深度研报) ─→ PR 8 (日报升级)
                                            │
                                            └→ PR 3 (成本模型) ← 可独立做
```

## 总工时估算

| PR | 内容 | 估时 | 建议开始 |
|----|------|------|---------|
| 1 | 📊 数据管线 + 全量缓存 | ~2h | **立即** |
| 2 | 🎯 评估器 v2 (Walk-Forward) | ~3h | PR1完成后 |
| 3 | 💰 成本模型 | ~1h | 可并行 |
| 4 | 📈 ETF回测模块 | ~4h | PR1完成后 |
| 5 | 🔴 东财实时接口 | ~2h | PR1完成后 |
| 6 | 📝 深度研报重建 | ~3h | PR1完成后 |
| 7 | 🖥️ Dashboard升级 | ~2h | PR2+5完成后 |
| 8 | 📰 日报升级+盘中报警 | ~3h | PR4+5+6完成后 |
| 9 | 📊 DSR+新闻映射 | ~2h | PR2完成后 |
| | **总计** | **~22h** | |

## 不做的（经过调研后的决策）

| 项目 | 不做的原因 |
|------|-----------|
| 退市股PIT数据库 | Wind Level 3 才支持，成本高，数据不可得 |
| Qlib跨市场对接 | 日历系统重写工程太大，对单人有用的部分不多 |
| PyQt5桌面GUI | 我们的FastAPI+Chart.js更好（浏览器访问） |
| 天天基金模块 | xalpha的，我们不做场外基金回测 |
| QMT券商协议 | OSkhQuant的，私有协议对我们无用 |
| 实时停复牌模拟 | 需要交易所直连 |

---

## 验证哲学

每一个PR交付时，必须满足：

**1. 代码验证**
```bash
python -c "import ..."           # 导入无错
python evaluator_fixed.py ...     # 输出可理解的结果
curl http://localhost:8686/api/   # API 返回200
```

**2. 结果验证（拿数据和事实说话）**
```
# 改造前：evaluator_fixed faceji → Sortino=6.84 (82天, 19只)
# 改造后：evaluator_fixed faceji --walk-forward --cycles 3 → 平均Sortino=?
# 如果改造后Sortino大幅下降，说明旧结果是信息泄露/过拟合
# 如果稳定，说明策略真正有alpha —— 这才是评估的意义
```

**3. 不破坏验证**
```
bash scripts/harness.sh     # 门禁通过
# scripts/run_trading.py 仍能成功
# scripts/portfolio_server.py 仍能访问
```

---

*计划状态：🔥 待你审阅确认后开始执行 PR 1*
