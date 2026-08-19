# Trellis: 模拟盘页面 + 数据可靠性整体优化 (2026-08-19)

Goal: 消除数据告警假阳性 → 修复弹窗 → 执行决策区/信号日志按主流量化终端标准重设计（证据可追溯、点击深钻）→ 自测验收

## WS0: 状态验证 (0.5h) — ✅ 已执行
- 300458 今日双策略硬止损 (faceji -8.9% / SQ -8%) = **策略正确行为**，非数据错误
- 🚨 资金守恒 假阳性根因: 校验公式未计入**累计已实现盈亏**
  faceji: 994041.79 + 5958.21(realized) = 1,000,000 ✓ ; SQ: 997801.65 + 2198.35 = 1,000,000 ✓
- 🚨 今日成交计数 假阳性根因: 拿 raw 文件 `simulated_trades`(本次run,=0) 对比 trade_history(今日,=2)，
  header 实际显示的是按 trade_history 算的 2 —— 校验对象选错
- 交易弹窗「未找到该交易记录」根因: `showTradeModal` 用 `t.sname` 匹配，
  但 API 返回的交易行没有 sname 字段（sname 是外层 key）
- board 证据缺口: checker.check 未传 macro_state → 双门/宏观象限恒 False;
  entry 缺 scores/factor_breakdown/data_quality → 数据层证据 missing

## WS1: 一致性校验公式修正 (0.5天) — Fix
- 文件: `dashboard/api_consistency.py`
- 资金守恒: `capital ≈ cash + Σ(entry×qty 未平仓) + Σ(卖出已实现pnl)` (±1元)
- 今日成交计数: 校验口径改为「header 显示值(=executed_today) == trade_history 今日」；
  raw simulated_trades 与今日差仅为 info（早盘成交/晚盘未成交属正常）
- 验证: curl /api/v2/data-consistency → consistent=true, 17项全过

## WS2: 交易历史弹窗修复 (0.5天) — Fix
- 文件: `dashboard/templates/dashboard_main.py` showTradeModal
- 匹配逻辑: 用外层策略 key 作为 sname 匹配 (`sn === sname`)，不再依赖行内 t.sname
- 验证: node --check + 数据链路人工核对

## WS3: 执行决策区后端富集 (1天)
- 文件: `dashboard/api_execution.py`
- checker.check 传入 macro_state (读 macro_engine_cache.json) → 双门/宏观象限有真实值
- entry 增加: scores(7维) / factor_breakdown / data_quality(合成: 快照新鲜度+price>0+因子完整率)
- 数据层证据: scan item 带 data_quality → evidence chain[数据层] 从 missing → ok
- 验证: curl board → checklist.dual_gate_open detail 含"黄灯/黄灯", entry.scores 非空

## WS4: 前端执行决策区 + 信号日志重排重设计 (1.5天)
- 文件: `dashboard/templates/dashboard_main.py`
- 布局: 🎯执行决策(全宽) → ⚡信号日志(全宽,决策下方) → 📈净值 → 💼持仓 → 📋交易历史
- 决策区 (主流量化终端样式):
  - 顶部统计条: BUY x / SELL x / HOLD x / WAIT x + 数据质量 grade
  - 分组表格: 动作 | 标的(名称) | 评分bar | 置信度 | 关键因子(高/低) | 依据 | 详情
  - 点击行 → 弹窗: 评分构成(权重×因子) / 建仓检查6项(status+detail) /
    证据链(数据层→因子层→信号层→执行层, 每层 status+来源+rationale) / 拉高拖低 / TrailStop
- 信号日志: 表格加 评分/优先级/状态列; 点击弹窗与决策区一致(因子+证据);
  api_portfolio 给 all_signals 富集 factor_scores/factor_breakdown
- 验证: node --check + curl 全端点

## WS5: 自测验收 (0.5天)
- /api/v2/data-consistency → consistent=true
- /api/v2/execution/board → checklist 双门有值、entry.scores 存在、数据层 ok
- /api/v2/portfolio/detail → trade_history 行含 name/因子; all_signals 含因子
- 弹窗数据链路: 每行 onclick 参数与弹窗查找键一致 (sname=策略key/symbol/date)
- JS 语法: node --check; 全端点 HTTP 200
- git commit 逐个 WS 原子提交

依赖: WS3 → WS4 (前端要消费富集字段); WS1/WS2 独立可先行
