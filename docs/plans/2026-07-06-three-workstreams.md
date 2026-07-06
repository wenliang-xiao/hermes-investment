# Phase 0.5 → 1 → F2 实施方案

> 三步连推：price=0 bug修复 → 工程化Phase1 → F2回测系统
> 方法论：OpenSpec (spec→TDD→verify) + Superpowers (plan→subagent→review)

---

## Workstream A: 修 price=0 持久化bug

**优先级**: 🔴 阻塞级 — 模拟盘数据不可信则后续工作全无效

- A1: 定位根因 — price=0 是数据文件问题还是 Dashboard 加载问题
- A2: 修数据源 — fastapi 端点直接从 strategy_states.json 聚合，不依赖 snapshot
- A3: 加稳定性 — 启动时数据校验，发现异常值自动告警/回退
- **验证**: `/api/simulated` 返回的持仓价格 > 0

## Workstream B: 工程化 Phase 1

- B1: GitHub Actions CI — push 时自动 ruff + pytest
- B2: 核心模块回归测试 — `evaluator_fixed.py` 基线验证, `factor_engine.py` 关键路径
- B3: 架构拆分 — `config.py` 拆分为 `config/` 包(api.py + trading.py + feishu.py)
- B4: 数据管线错误处理标准化 — 所有 data/ 模块统一 try/except 模式

## Workstream C: F2 回测系统

- C1: 本地回测存储 — `data/backtest/` 目录 + 结果序列化 schema
- C2: 自定义日期范围 — CLI 参数支持 2000-01-01 至今
- C3: xalpha 参考实现 — 多标的并行回测引擎
- C4: Dashboard 回测面板 — 回测结果展示 + 策略对比

→ **执行顺序: A → B → C，每个模块 TDD**
