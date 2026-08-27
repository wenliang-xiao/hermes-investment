# 事件风险开关（Event-driven Risk Switch）— Trellis 执行计划

> 2026-08-19 · 响应 LDS"今晚清仓/避险"观察
> 目标：把「事件驱动风险偏好状态机」落地为**影子运行**的一层，不接实盘。
> 核心方法论：**事件驱动不可历史回测（是 Bayes 在线更新，不是 offline 因子）→ 用 shadow-run 前验累积证据**，杜绝用历史回测自欺。
> 状态：**已过飞书评审（探索 agent 逐条核验），本文件已按评审共识修订。**

## ⚠️ 评审共识修订（2026-08-19，按探索 agent 逐条代码核验采纳）

### 修订背景
评审确认问题方向+方法论正确，但指出对现有代码 3 处认知错误 + 低估 2 个缺口。以下全部经本人逐条回溯代码验证通过，已采纳。

### 采纳的修正（替换原 WS 中对应内容）
1. **不看 `suggested_position`（主链路死字段）** —— 只写 cache，run_trading/run_daily/shadow/strategy4 均不读（仅 stock_analyzer/portfolio_monitor 触碰）。WS3 落点改为二选一：
   - **`run_daily.py:167,204` 的 `dual_closed` 门**（最小样板，已生效：双门红/黄→"只研究不开仓"）
   - **`trading_engine.run_daily`（模拟盘自动执行 L518-542）**，且要在 **自动执行 和 建议信号(L544-549) 两处都拦截**
2. **`black_swan` 系列是死代码** —— `_check_black_swan`（trading_engine.py:435）import 不存在的 `get_macro_status`，裸 except 吞掉后 fallback `is_black_swan()`→False；`is_black_swan` 仅透传 `market_crash` 布尔，不计算单日大跌。**不把这当现有能力，新建事件触发时不依赖它**（可顺手修）。
3. **`_check_stop_loss` 在 `ExecutionAgent`**（portfolio_builder.py:355,448），非 `PortfolioBuilder`。修正文档引用。
4. **CPI 策略开关无 `off` 值**（仅 on/limited），"on/off/limited"表述是错的。off 从不触发。事件开关的"极值清仓"是**新增语义**，不能套用现有开关映射。
5. **`suggested_position` 不作为部署点**（见 1）。
6. **跨市场"缺数据"更正**：纳指/黄金/白银数据**已在**（WATCHLIST + yf_data_layer.get_global_market_snapshot 日报已拉），缺的是**共振分析逻辑**，非数据管线。
7. **必修真数据 bug**：`data_router.py:88` 把含 `=` 的 GC=F/SI=F 错误路由到 `akshare_futures`（中国期货API）→ 需排除 COMEX 代码走 yfinance；且 SI=F 不在全球快照商品列表。

### 补齐的两个缺口（WS3 新增）
8. **「避险资产无语义」** —— GLD/SLV/GC=F 在 WATCHLIST 是"贵金属链普通股票"，会像股票一样被因子评分 BUY/SELL，系统不区分"股票 vs 避险资产"。**WS3 必须明确：改 strategy4 加事件钩子，还是新建事件避险通道**（评审点名这是核心缺口）。
9. **切黄金/白银无事件钩子** —— 唯一通道是 strategy4 `REGIME_WEIGHTS`（月度 regime 驱动，无事件触发）。需新增事件钩子或在事件开关里独立建"避险通道"。

### 接实盘口径修订
- ❌ 原提案"shadow ≥14 天"太短且计量维度错（事件低频稀疏，14 天可能 0 样本）
- ✅ 改为**以事件样本数计量**：
  - ≥3-5 个真实事件触发（财报/制裁/IPO 各至少 1 个）
  - shadow delta 按事件后窗口（5/10/20 日）统计显著为正
  - 同时记录**避险动作 false positive 率**作为第二指标（避免空仓隐性成本被 Sortino 低估）
- shadow 对比基准 = 「假设避险损益 vs 模拟盘实际持仓损益」，注意模拟盘满仓不避险会带来幸存者偏差，故补 false positive 率。

### 数据源取舍共识
- **优先 akshare + yfinance**（已装已用，零新增依赖）：akshare 业绩预告/快报/解禁/交易日历 + yfinance NVDA.get_earnings_dates()/.calendar（美股财报）
- 蜻蜓 CSC 作增强（F10 业绩披露日程，未验证，不依赖）
- 降级手工 json + `data_age` 字段；验收标准保留"无数据报缺失而非假全零"
- ⚠️ 接受的天然上限：yfinance 15min 延迟，美股财报**时点盘后波动**捕捉不到（WS0 明确接受）

### 事件脉冲阈值共识
- **黄金急拉**：单日 >2% 或 5日累计 >5%（黄金低波资产，正常月波动 1-2%；LDS"一月14%"折算日均约0.6%）
- **跨市场共振**：同日 NVDA/纳指跌幅 >3% 且 A股映射链(光模块/算力)跌幅 >2% 才触发；一期先做同日异动门，相关系数二期
- 阈值保守 + shadow 记 false positive（避免过度敏感频繁清仓）

---

## 背景与差距

LDS 本轮清仓不是"因子选股"，而是**事件驱动的风险偏好状态机**：
- 未来事件日历（英伟达财报今晚、美国制裁裁决、IPO 排期）
- 跨市场共振（A股 300458 <8%> 美股 NVDA、黄金单月 +14%）
- 一票否决式清仓 → 转黄金/白银避险

**系统当前已有（底层件 OK）：**
- `MacroEngine._calc_dual_gate` — 双门(宏观×趋势)→9 组合动作（含"清仓观望"）
- `MacroEngine._calc_strategy_switch` — CPI 驱动 on/off/limited
- `TradeCalendar.is_black_swan` / `_check_black_swan` — 单日大跌检测
- `PortfolioBuilder._check_stop_loss` — SQ 四层风控 hard_sell(-8%)/fall_sell(-12%)
- `ExecutionChecker._calc_trail_stop` — 分级 TrailingStop
- `news/pipeline.py` — 东方财富 7×24 + 财联社电报 + 个股新闻 + 情绪分析

**系统当前缺失（本 Trellis 补齐）：**
1. **未来事件日历**：新闻只拉"过去"，没有"未来 48h 财报/制裁裁决/IPO 排期"触发
2. **事件→仓位触发闭环**：news 到 sentiment 就停，没有"事件避险脉冲→降仓/切黄金"
3. **跨市场共振**：只到上证，没有纳指/NVDA/黄金异动同步
4. **白银/避险切换路径**：只有资产配置加权，无脉冲切金/银
5. **影子运行记录**：无"如果当时避险会怎样"的前向证据积累

## 方法论

**为什么回测做不到 LDS 的表现：**
- event + 叙事 = 在线 Bayet 更新，历史价格回测无法覆盖"当时新闻时点"
- 我们的目标函数（年化/回撤/夏普）默认全仓，惩罚空仓机会成本 → 天然锁死满仓思路
- 固定周期调仓器把"瞬时清仓"平滑掉了，没有事件触发路径

→ **对策：shadow-run 前向验证**。规则写好后每日影子记录"若当时避险的损益 vs 实际持仓损益"，累积 1-3 个月，用真实 delta 做证据，再决定是否上实盘。这是记忆里"渐进式上线(已验证先部署，新层 shadow run)"原则的直接应用。

## WS 分解

### WS0 验证前置（铁律）
- [ ] 确认可用的"未来事件日历"数据源（东财 Acquirer/财报日历 API、蜻蜓券商日历、cninfo 预披露）
- [ ] Git 基线 clean，建独立分支 `feat/event-risk-switch`
- [ ] 确认 macro_engine `summarize()` 已暴露 dual_gate（✓ 已存在）
- [ ] 新增 `event_risk_engine.py` 单测骨架（test 先 FAIL）

### WS1 事件风险日历适配器
- 新增 `engine/event_calendar.py`
- 数据源：优先财报/IPO/央行日历 API；降级手工维护 `data/event_calendar.json`
- 输出：`{date, symbol/market, type(earnings/ipo/rate_sanction), title, risk_level(high/med/low)}` 未来 7 天窗口
- 限频：批量调用 time.sleep 间隔；异常 try/except + fallback

### WS2 事件避险脉冲（event_risk_engine.py）
- 输入：event_calendar 未来 48h high 事件 + 黄金/纳指/白银 异动 + 跨市场共振(跌幅/美股)
- 输出 `event_risk`: `{level: none/moderate/high/extreme, triggered_by: [...], halflife}` 
- 规则：high 事件(财报/制裁) 或 黄金急拉>N% / 跨市场同日大跌 → level 提升
- 纯规则 + 可读 triggered_by（透明，符合记忆"因子方法彻底透明"）

### WS3 接入决策层（MacroEngine 叠加）
- [ ] `strategy_switch` 叠加事件避险脉冲：extreme → off/清仓建议、high → 仓位降到 0.3 + 禁用 BUY 只允许 SELL
- [ ] 黄金/白银切换路径：事件避险时建议买入避险资产
- [ ] 双门 detail 增加"事件脉冲"说明
- 不接实盘 → 只改变 `suggested_position` + 信号 SELL 授权 / BUY 拦截

### WS4 影子运行（shadow-run）
- [ ] `scripts/run_event_shadow.py`：每日收盘记录「避险版仓位损益 vs 实际持仓损益」追加 `data/shadow_event_history.json`
- [ ] cron 挂 to no_agent 或日报 Phase 后调用，累计数据
- [ ] 周报展示 shadow delta 累积曲线（debug：确认有数据再谈反映）

### WS5 自测 + 前端
- [ ] 语法检查 / 重启 / 端点验证
- [ ] dashboard 执行决策区新增"事件风险"指示灯（transparent: 谁触发/为什么）
- [ ] 提交（每个 WS 一个 commit）+ push

## 验收标准
- 事件日历 / 事件风险 / 影子日志 三端点在无数据时有明确「数据缺失」而非假全零
- shadow 连续运行 ≥14 天且 delta 记录可查后，才讨论是否接实盘
- 不宣称已修但实际未修（铁律）

## 风险
- 未来日历数据源可能不稳定 → 降级手工 json + 明确「数据年龄」
- 事件脉冲过度敏感导致频繁清仓 → 阈值先用保守值 + shadow 记录false positive