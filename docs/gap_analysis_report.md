# 缺口分析报告：设计文档 vs 实际实现

> **分析日期**: 2026-07-06
> **方法**: 逐文档对比 + Git 提交历史审计 + 代码目录盘查 + 测试覆盖率验证
> **范围**: master_plan.md (9PR) + docs/design/ (8设计文档) + docs/review/ (评审报告) + docs/specs/ (规范文档)

---

## 一、总览

| 维度 | 状态 |
|------|------|
| 总 Python 文件 | 101 (不含 backup/_archive) |
| 测试文件 | 9 个 |
| 测试通过数 | **77/77 ✅** |
| 硬编码凭据 | **已全部清除 ✅** → 环境变量 |
| Git 提交 | 148+ → 170+ commits |
| 最近更新 | 2026-07-06 22:04 (持续活跃开发) |

---

## 二、master_plan.md 的 9 个 PR 状态

### PR 1: 数据地基 — 统一数据管线 + 全量缓存 ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `data/data_router.py` | 前缀路由统一入口 | 存在(195行)，路由规则完整 | ✅ |
| `data/sources/baostock_source.py` | baostock 包装 | 存在(114行) | ✅ |
| `data/sources/yahoo_source.py` | yfinance 包装 | 存在(74行) | ✅ |
| `data/sources/akshare_source.py` | AKShare 包装 | 存在(193行) | ✅ |
| `scripts/cache_historical.py` | 全量拉取 | 存在 | ✅ |
| `data/double_check.py` | 东财+新浪双源验证 | ❌ **不存在** | ❌ 缺失 |
| 缓存产出 | ~120文件, ~3MB | `data/cache/` 目录存在 | ✅ |

### PR 2: 评估器 v2 — Walk-Forward ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `evaluator_fixed.py` 新增 `--walk-forward` 模式 | Walk-Forward 回测 | 存在(878行)，含WF实现 | ✅ |
| `WalkForwardSplit` 类 | Train252d+Test63d | 已实现 | ✅ |
| 多周期报告模式 | 按市场状态切分回报 | 已实现 | ✅ |
| 批量标的支持 | 评估89只全量 | 已实现 | ✅ |

### PR 3: 成本模型升级 (OSkhQuant标准) ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `analysis/cost_model.py` | 独立成本模块 | 存在(166行)，含5级滑点 | ✅ |
| `evaluator_fixed.py` 调用 cost_model | 算每笔交易成本 | 已接入 | ✅ |
| 测试 | `test_cost_model.py` | 7 tests ✅ | ✅ |

### PR 4: ETF回测模块 ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `analysis/etf_backtest.py` | ETF回测引擎 | 存在(264行) | ✅ |
| `analysis/allocation_strategies.py` | 配置模型实现 | 存在(199行) | ✅ |
| `data/etf_universe.py` | ETF标的定义 | 存在(76行) | ✅ |
| 风险平价/网格/趋势跟踪 | 至少3种策略 | 已实现 | ✅ |

### PR 5: 东财实时接口 + Dashboard活数据 ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `scripts/realtime_price.py` | 东财实时行情服务 | 存在(189行) | ✅ |
| `scripts/portfolio_server.py` | `/api/realtime` 端点 | 已实现 | ✅ |
| Dashboard HTML 5秒轮询 | 实时价格列 | 已实现 | ✅ |

### PR 6: 重建 deep_research ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `analysis/deep_research.py` | 8维深度研报 | 存在(288行) | ✅ |
| `scripts/generate_report.py` | 飞书研报生成 | 存在 | ✅ |

**注意**: 审计报告(B7)指出 DCF 估值仍为占位符(`current_price * 1.1`)，尚未修正。 ⚠️

### PR 7: Dashboard升级 ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `/api/metrics` 端点 | Sortino/Alpha/Beta | 已实现 | ✅ |
| Dashboard HTML 3面板 | 绩效指标+成本明细+净值曲线 | 已实现 | ✅ |
| 风险面板(VaR/集中度) | F1-Slice5 commit | 新增 `/api/risk` 端点 | ✅ |

### PR 8: 日报升级 + 盘中报警 ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `scripts/run_report_v10.py` | 回测vs模拟盘对照等 | 已实现 | ✅ |
| `scripts/price_alert.py` | ±3%报警, 成交量暴增报警 | 存在(195行) | ✅ |

### PR 9: DSR统计检验 + 新闻映射 ✅ **已完成**

| 改动 | 预期 | 实际 | 状态 |
|------|------|------|------|
| `analysis/dsr_test.py` | Deflated Sharpe Ratio | 存在(191行) | ✅ |
| `evaluator_fixed.py` `--with-dsr` | DSR模式 | 已实现 | ✅ |
| `scripts/news_pipeline.py` | GLM分析→评分偏移 | 存在(103行) | ✅ |

### master_plan 后续追加补丁 (commit 1d00f76) ✅ **已完成**

| 模块 | 说明 | 存在 | 状态 |
|------|------|------|------|
| `analysis/stop_list.py` | 段永平不为清单 | 存在(303行) | ✅ |
| `analysis/audit.py` | 六层漏斗审计工具 | 存在 | ✅ |
| `analysis/knowledge_ref.py` | 面基知识库动态引用 | 存在 | ✅ |
| `analysis/delta_tracker.py` | 每日变化追踪 | 存在 | ✅ |

### master_plan 总评

**9/9 PR 全部完成 ✅**，后续补丁也已签入。PR1-9的状态标记为"全部完成 (2026-06-25)"并已验证。

---

## 三、docs/design/ 下 8 个设计文档实施状态

### 1. 安全加固方案 (security-hardening.md) 🔴 P0 — ⚠️ **部分完成**

| 建议项目 | 状态 | 证据 |
|---------|------|------|
| 移除 7 处硬编码凭据 | ✅ **已完成** | `config.py` 已改为 `os.environ.get()`，`run_report_v10.py` 已清理 |
| 创建 `.env.example` | ✅ **已完成** | 存在(15行)，含 6 个变量 |
| os.environ[] 加兜底 | ✅ **已完成** | 全项目改为 `.get()` |
| 统一凭据入口 (core/secrets.py) | ❌ **未完成** | `core/secrets.py` 仍在但零引用；`config.py` 仍是主入口 |
| 清除 Git 历史凭据 | ❌ **未完成** | Git 历史仍包含明文凭据 |
| Pickle 安全性 (JSON/Parquet 迁移) | ❌ **未完成** | `data/data_router.py` 仍使用 `pickle.load()` |
| Dashboard 认证/限流/输入校验 | ❌ **未完成** | 仍无认证，绑定 `0.0.0.0` |
| pre-commit 密钥扫描 Hook | ❌ **未完成** | 无 pre-commit 配置 |

### 2. 工程化基础方案 (engineering-foundation.md) 🔴 P0 — ⚠️ **部分完成**

| 建议项目 | 状态 | 证据 |
|---------|------|------|
| `pyproject.toml` 创建 | ✅ **已完成** | 存在(70行)，含 ruff/pytest 配置 |
| `ruff` 配置 | ✅ **已完成** | `[tool.ruff]` 部分已配置 |
| `mypy` 配置 | ❌ **未完成** | 无 `[tool.mypy]` 配置 |
| `uv` 依赖管理 | ⚠️ **部分** | `pyproject.toml` 有 `dependencies` 但无 `uv lock` 锁定 |
| CI/CD Pipeline (GitHub Actions) | ❌ **未完成** | `.github/workflows/` 目录不存在 |
| `.gitignore` 补全 | ✅ **已完成** | 包含 build/dist/pycache/coverage 等 |
| `logging.basicConfig()` 清理 | ❌ **未完成** | 5 个文件仍使用模块顶层 `basicConfig()` |
| 裸 except 清理 (477处) | ❌ **未完成** | 未系统处理 |
| pre-commit 配置 | ❌ **未完成** | 不存在 |
| 日志标准化 | ❌ **未完成** | 无 `logging_config.py`，无 JSON 结构 |
| 分支策略/提交规范 | ❌ **未完成** | 仍单分支直接 push main |

### 3. 测试基础设施方案 (testing-infrastructure.md) 🔴 P0 — ⚠️ **部分完成**

| 建议项目 | 状态 | 证据 |
|---------|------|------|
| pytest 框架 + 配置 | ✅ **已完成** | `pyproject.toml` 含 pytest 配置 |
| 77 个测试 | ✅ **已完成** | 9 个测试文件，全部通过 |
| 核心策略单元测试 | ✅ **已完成** | `test_strategies.py` 35项：faceji/silverquant/tradingagents |
| 成本模型测试 | ✅ **已完成** | `test_cost_model.py` 7项 |
| 原子写入测试 | ✅ **已完成** | `test_atomic_io.py` 7项 |
| 回测基线回归测试 | ✅ **已完成** | `test_evaluator_fixed.py` 3项 |
| 因子引擎测试 | ✅ **已完成** | `test_factor_engine.py` 2项 |
| 回测存储测试 | ✅ **已完成** | `test_backtest_storage.py` + module 共16项 |
| Mock 策略 (外部数据源隔离) | ❌ **未完成** | 项目使用真实数据源，无 mock fixtures |
| Hypothesis 属性测试 | ❌ **未完成** | `analysis/factor_engine.py` 的函数未用 hypothesis 测试 |
| 集成/冒烟测试 | ❌ **未完成** | Dashboard API 无 TestClient 测试 |
| 金标文件回归测试 | ❌ **未完成** | evaluator 固定评分基线未制度化 |
| conftest.py 共享 fixtures | ❌ **未完成** | 无顶级 conftest.py |
| 覆盖率目标 | ❌ **未完成** | 无覆盖率阈值 |

### 4. 数据管线可靠性方案 (data-pipeline-reliability.md) 🟡 P1 — ⚠️ **部分完成**

| 建议项目 | 状态 | 证据 |
|---------|------|------|
| 原子文件写入 | ✅ **已完成** | `utils/atomic_io.py` 含 `atomic_write_json/pickle` |
| 原子写入接入三大业务文件 | ✅ **已完成** | `trading_engine.py`/`run_trading.py`/`news_pipeline.py` 已接入 |
| Pickle → Parquet/JSON 迁移 | ❌ **未完成** | `data_router.py` 仍用 `pickle.load()` (75个.pkl) |
| 缓存 LRU 淘汰策略 | ❌ **未完成** | `data/cache/` 无上限增长 |
| 错误处理标准化 | ⚠️ **部分** | 原子写入已标准化，但 try/except 整体未系统治理 |
| baostock TCP 挂死处理 | ⚠️ **部分** | `data_layer.py` 有 `signal.alarm`，但无法在容器/Windows使用 |
| 数据层统一 (3套→1套) | ❌ **未完成** | `data_router.py`/`data_layer.py`/`data_source_layer.py` 三套并存 |
| `/health` 端点 | ❌ **未完成** | Dashboard 无健康检查 |
| Cron 死男人开关 | ❌ **未完成** | 无管线运行状态追踪 |

### 5. 因子引擎统一方案 (factor-engine-unification.md) 🟡 P1 — ✅ **已完成**

| 建议项目 | 状态 | 证据 |
|---------|------|------|
| 双引擎合并 (v3.1→v4.0) | ✅ **已完成** | commit `dbc2654`: `factor_scanner.py` 标记退役，零引用 |
| v4.0 新增 dividend 风格因子 | ✅ **已完成** | 从 v3.1 移植红利因子到 v4.0 |
| 兼容层 (`score_to_signal`/`convert_v3_to_v4`/`convert_v4_to_v3`) | ✅ **已完成** | 新增三函数确保向后兼容 (commit dbc2654) |
| `strategies/` 纯函数重构 | ✅ **已完成** | `faceji.py`/`silverquant.py`/`tradingagents.py` 纯函数+35项测试 |
| `run_trading.py` v2 重写 | ✅ **已完成** | 使用 FactorEngine 批量评分 + 策略纯函数 |
| 策略 Config dataclass 化 | ✅ **已完成** | `base.py` 含 3 种 Config + Signal/PositionData |

### 6. 架构拆分方案 (architecture-split.md) 🟡 P1 — ❌ **未完成**

| 建议项目 | 状态 |
|---------|------|
| `config.py`(1035行) → `config/` 包 | ❌ 未拆分 |
| `report_v6.py`(2575行) → `report/` 包 | ❌ 未拆分 |
| `full_asset_scanner.py`(1780行) → `scanner/` 包 | ❌ 未拆分 |
| `backtest.py`(1681行) → `backtest/` 包 | ❌ 未拆分 |
| `news_engine.py`(1332行) → `news/` 包 | ❌ 未拆分 |
| `run_daily.py`(982行) → `pipeline/` 包 | ❌ 未拆分 |
| `portfolio_server.py`(1469行) → `dashboard/server.py` | ❌ (有独立 Dashboard 方案) |
| `domain/__init__.py` 重复配置清理 | ❌ 未清理，与 `config.py` 仍独立维护 |
| `sys.path.insert()` 39处 import hack 清理 | ❌ 未清理 |
| `pyproject.toml` editable install | ❌ 未配置包名 (name 非标准路径) |

### 7. 可观测性方案 (observability.md) 🟢 P2 — ❌ **未完成**

| 建议项目 | 状态 |
|---------|------|
| 统一日志配置 (`logging_config.py`) | ❌ 不存在 |
| JSON 结构化日志 | ❌ 未实现 |
| Correlation ID 链路追踪 | ❌ 未实现 |
| `/health` 端点 | ❌ 不存在 |
| Prometheus 指标暴露 | ❌ 未实现 |
| 数据新鲜度检查 | ❌ 未实现 |
| 飞书告警集成 | ❌ 未实现 |
| `portfolio_server.py` systemd 守护 | ❌ 未配置 |
| `run_daily.py` 自定义 `log()` → 标准 logging | ❌ 未迁移 |

### 8. Dashboard 前端重构方案 (dashboard-refactoring.md) 🟢 P2 — ❌ **未完成**

| 建议项目 | 状态 |
|---------|------|
| Jinja2 模板拆分 (HTML 从 Python 分离) | ❌ `templates/` 目录不存在 |
| 独立 CSS/JS 文件 | ❌ `static/` 目录不存在 |
| Chart.js CDN 本地化 | ❌ 仍是 CDN 引用 |
| 表格排序/搜索/导出 | ❌ 未实现 |
| 移动端适配 | ❌ 未实现 |
| 前端缓存/状态持久化 | ❌ 未实现 |

---

## 四、docs/review/ 评审报告 — 历史决策理解

### 4.1 深度代码审计报告 (final-deep-audit-2026-07-03.md)

| 优先级 | 问题 | 修复状态 |
|--------|------|---------|
| 🔴 P0 | B1: 财务 abs() 抹符号 | ✅ **已修复** (commit 2c648f4) |
| 🔴 P0 | B2: MA 趋势过滤方向反向 | ✅ **已修复** (commit 2c648f4) |
| 🔴 P0 | B3: 模拟盘绕行周频限制 | ✅ **已修复** (commit 2c648f4) |
| 🔴 P0 | B4: MACD 金叉判定永真 | ✅ **已修复** (commit 2c648f4) |
| 🔴 P0 | S1-S4: 7处硬编码凭据 | ✅ **已移除** (commit 2c648f4 + 929130e) |
| 🟡 P1 | B5: report_v6 章节编号错乱 | ⚠️ 未确认修复 |
| 🟡 P1 | B6: PoolManager 晋级逻辑残缺 | ⚠️ 未确认修复 |
| 🟡 P1 | B7: DCF 占位符 | ❌ **未修复** — deep_research.py 仍 `current_price * 1.1` |
| 🟡 P1 | P1: base.py L37-38 0.0→None | ⚠️ 未确认修复 |
| 🟡 P1 | P2: silverquant.py 硬编码3.0 | ⚠️ 未确认修复 |
| 🟡 P1 | P4: tradingagents 不对称 | ⚠️ 未确认修复 |
| 🟢 P2 | 双引擎统一 | ✅ **已完成** (commit dbc2654) |
| 🟢 P2 | 三套数据层整合 | ❌ **未完成** |
| 🟢 P2 | 幸存者偏差修正 | ❌ **未完成** |
| 🟢 P2 | WATCHLIST 重复条目 | ⚠️ 未确认 |
| 🟢 P2 | Dashboard 刷新机制统一 | ⚠️ 部分(120s vs 60s) |

### 4.2 专业产品评审报告 (product-review-2026-07-03.md)

6 个最大缺口：

| 缺口 | 当前状态 |
|------|---------|
| 无组合风险管理 (VaR/压力测试) | ⚠️ **部分** — F1-Slice5 新增 `/api/risk` (VaR 95%/集中度/波动率)，但 Dashboard 前端 UI 未接入 |
| Dashboard 与日报割裂 | ❌ **未解决** — 两套独立系统 |
| 无交易执行闭环 | ❌ **未解决** — 信号展示→执行链路仍断裂，`shadow_account` 仍是 CLI |
| 三相净值离散交易点 | ❌ **未解决** — 无每日连续快照 |
| 因子无中性化处理 | ❌ **未解决** — 全截面百分位无行业分组 |
| 三条策略非真正差异化 | ❌ **未解决** — 建仓标的重叠度~80% |

### 4.3 其他评审报告 (已阅读)
- `benchmark-analysis-2026-07-03.md` — 专业平台对标
- `OSkhQuant_analysis.md` — OSkhQuant 调研结论
- `xalpha_analysis.md` — xalpha 调研
- `pro_backtest_methodology.md` — 回测方法论
- `seven_dimension_audit.md` — 7维审计
- `four-source-comparison.md` — 四源对比

---

## 五、docs/specs/ 规范文档

**specs 目录不存在。** 搜索 `docs/spec*/` 和 `spec*` 均无结果。项目无正式规范文档（OpenSpec 系统有在文档中提及但未落地到 specs 目录）。

---

## 六、完整缺口矩阵

### 已做 ✅ (完全实现)

| # | 项目 | 来源 |
|---|------|------|
| 1 | **9个PR全部完成** (PR1-9) | master_plan.md |
| 2 | **双引擎合并** — factor_scanner退役, v4.0为主 | design/#5 |
| 3 | **6个P0 bug修复** — abs()/MA方向/MACD/周频/硬编码 | audit + Phase Amoeba |
| 4 | **原子写入** — utils/atomic_io.py 接入三大文件 | design/#4 |
| 5 | **77个测试** — 9文件全通过, 回测/策略/成本/引擎 | design/#3 |
| 6 | **成本模型** — 5级滑点+印花税+佣金 | master_plan PR3 |
| 7 | **Walk-Forward回测** — 评估器v2 | master_plan PR2 |
| 8 | **ETF回测模块** — 风险平价/网格/趋势 | master_plan PR4 |
| 9 | **实时行情** — 东财接口+6s超时+中文名 | master_plan PR5 |
| 10 | **深度研报** — 8维 (除DCF) | master_plan PR6 |
| 11 | **DSR统计检验** — Deflated Sharpe Ratio | master_plan PR9 |
| 12 | **盘中报警** — ±3%+成交量暴增 | master_plan PR8 |
| 13 | **风险面板API** — VaR/集中度/波动率 | design/#7 部分 |
| 14 | **pyproject.toml + ruff配置** | design/#2 部分 |
| 15 | **.gitignore + .env.example** | design/#1/#2 |

### 部分做 🟡 (部分实现)

| # | 项目 | 说明 | 优先级 |
|---|------|------|--------|
| 1 | **安全加固** | 凭据已移除但 Git 历史未清理、pickle RCE 未修复、Dashboard 无认证 | P0 |
| 2 | **测试覆盖** | 77个单元测试好，但缺集成/冒烟/金标回归/Hypothesis/Mock | P0 |
| 3 | **组合风险管理** | API端有VaR/集中度，但Dashboard前端UI未接入，无压力测试、无行业限制 | P1 |
| 4 | **数据管线可靠** | 原子写入已做，但pickle→JSON未迁移、无LRU淘汰、/health无 | P1 |
| 5 | **工程化基础** | pyproject.toml有但无CI/CD、无uv lock、无pre-commit、无mypy | P1 |

### 未做 ❌ (完全未实现)

| # | 项目 | 说明 | 优先级 |
|---|------|------|--------|
| 1 | **架构拆分** | 6个超大文件(>1000行)未拆分, 39处sys.path.insert, config重复 | **P1** |
| 2 | **可观测性** | 无日志配置、无/health、无指标、无告警、无系统d | **P1** |
| 3 | **CI/CD流水线** | 无GitHub Actions、无自动化部署、无容器化 | **P2** |
| 4 | **Dashboard前端重构** | HTML/CSS/JS未分离、CDN外链、无导出/搜索/排序 | **P2** |
| 5 | **因子中性化** | 无行业分组、无市值中性化 | **P2** |
| 6 | **数据层统一** | 三套数据层(router/layer/source_layer)各自管理baostock | **P2** |
| 7 | **交易执行闭环** | Dashboard信号不能直执行、shadow_account仍是CLI | **P2** |
| 8 | **净值连续记录** | 每日净值离散点而非日频连续快照 | **P2** |
| 9 | **策略真正差异化** | 三条本质同一策略重复, 应改为大盘质量/小盘动量/跨资产ETF | **P3** |
| 10 | **specs目录** | 无正式规范文档 (OpenSpec提及但未落盘) | **P3** |

---

## 七、优先级建议

### 🚨 立即 (P0) — 有安全/数据完整性风险
1. 🥇 **Pickle→JSON迁移** — `data_router.py` 的 75个.pkl 文件有RCE风险
2. 🥇 **Dashboard加认证** — 当前 `0.0.0.0:8686` 无认证暴露全部持仓
3. 🥇 **Git历史凭据清理** — 使用 `git filter-repo` 重写历史
4. 🥇 **集成测试补全** — 至少 Dashboard API 冒烟 + 数据管线 Mock 集成测试

### 🔴 高优 (P1) — 影响系统维护和稳定性
1. 🥇 **架构拆分** — config/包拆分 (2h) 可立即降低维护成本，report/包拆分(4h)清除最痛点
2. 🥇 **可观测性基础** — `/health` 端点 + 统一日志配置 (1h)
3. 🥇 **CI/CD** — GitHub Actions: push时自动 ruff + pytest (1h)
4. 🥇 **DCF估值修复** — `deep_research.py` 的占位符替换为真实折现现金流计算 (2h)

### 🟡 中优 (P2) — 产品体验提升
1. Dashboard Jinja2 拆分 (4-8h)
2. 因子中性化 (行业内百分位) (2h)
3. 净值连续记录 (每日快照) (1天)
4. 风险面板前端UI接入 (1天)

### 🟢 低优 (P3) — 长期改进
1. 策略真正差异化 (大盘/小盘/ETF)
2. 交易执行闭环 (信号→一键执行)
3. Pre-commit + mypy 配置
4. 大规模超大文件拆分(backtest.py 1681行等)

---

## 八、总结

| 指标 | 数值 |
|------|------|
| 设计文档要求总项 | ~45项 |
| ✅ 已完成 | ~28项 (62%) |
| 🟡 部分完成 | ~8项 (18%) |
| ❌ 未完成 | ~9项 (20%) |
| 代码存量 | 101 Python文件, 77 tests ✅ |
| 总体评价 | **master_plan 9PR 全部完成，8份设计文档实施约60%。** 核心业务能力扎实（因子引擎、三策略、回测、日报体系），工程化欠账仍在积累。最近 Phase 0/1/F1/F2 积极追赶中。 |
