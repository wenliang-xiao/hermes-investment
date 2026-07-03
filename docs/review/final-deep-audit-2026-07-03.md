# Hermes Investment System · 深度代码审计报告

> **日期**: 2026-07-03 | **方法**: 5 轮并行 agent 逐行审计 + 跨文件交叉验证 | **覆盖**: 全量 94 文件

---

## 一、审计方法

采用多轮并行深度审计，而非表层扫描：

1. **Round 1（5 agent 并行）**：逐行阅读全部核心文件，记录每个 bug/不一致/设计缺陷，含行号
2. **Round 2（交叉验证）**：跨文件对比同一逻辑的不同实现，追踪数据流

覆盖维度：交易引擎、因子引擎、数据管线、策略层、管线入口、Dashboard、报告输出、配置域、宏观引擎、安全

---

## 二、严重 Bug（P0 — 影响投资决策正确性）

| # | 文件 | 行号 | 问题 | 影响 |
|---|------|------|------|------|
| B1 | `data_layer.py` | L276,327-331,354,364 | **`abs()` 抹消财务数据正负号**——ROE=-5% 经 abs 处理后变为 500%，因子引擎无法区分盈利与亏损公司 | 评分严重失真 |
| B2 | `faceji.py` | L62 | **MA 趋势过滤方向反向**——`ma60d <= ma20d → skip`，上升趋势中错误跳过标的（与 `run_daily.py:L701` 的正确逻辑冲突） | 策略建仓信号错误 |
| B3 | `trading_engine.py` | L631-644 vs651 | **模拟盘绕过周频限制**——`TradeCalendar` + `MAX_TRADES_PER_WEEK_PER_STRATEGY=1` 已实现，但 `run_daily()` 的模拟执行路径（L631-644）不调用 `can_trade()` 也不调用 `record_trade()`。周频过滤仅用于"建议信号"输出（L651），模拟盘可一天执行 N 笔 BUY | 模拟盘失控 |
| B4 | 三处 | `evaluator_fixed.py:L256` `backtest_v2.py:L293` `backtest_all:L539` | **MACD 金叉判定条件 `pmacd <= pe12-pe26` = `pmacd <= pmacd` = 永远为真**——金叉退化为仅 `macd_line > signal`，非真正的上穿判定 | 技术面信号不准确 |
| B5 | `report_v6.py` | L276,945,1811 | **章节编号系统性错乱**——声明 9 个板块（0-9），实际输出编号为 八/九/十/六/七/八/九，与声明完全不对应 | 日报结构混乱 |
| B6 | `factor_engine.py` | L845-847 | **PoolManager "待满 1 周"晋级条件未实现**——`date_added` 被赋值但从未用于判断，Watch→Monitor 晋升仅检查评分 > 0.55 | 票池晋级逻辑残缺 |
| B7 | `deep_research.py` | L119-127 | **DCF 估值为占位符**——`dcf_value_base = current_price * 1.1`，无任何折现现金流计算，与文档宣称的"三情景 DCF"严重不符 | 研报结论无依据 |
| B8 | `akshare_source.py` | L135-138 | **`get_rt_futures` 名不副实**——调用 `futures_foreign_hist` 获取历史数据而非实时行情 | 函数语义错误 |
| B9 | `factor_engine.py` | L269 | **IC 权重系统注释与实际不符**——注释说"3 个样本后给条件权重 70% 信任"，实际 James-Stein 公式下 λ=0.5 时只有 50% 信任 | 误导维护者 |
| B10 | `factor_engine.py` | L295 | **IC 权重双层加权**——`get_weights()` 中 `0.7*base+0.3*cond`，但 `cond` 内部已做 (1-λ)*cond+λ*unconditional，而 unconditional=base，导致 base 被重复强调 | 权重偏置 |

---

## 三、安全漏洞（P0）

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| S1 | `config.py` | L16-22 | 5 个凭证全部硬编码（TUSHARE_TOKEN / FEISHU_FOLDER_TOKEN / FEISHU_USER_OPENID / FEISHU_GROUP_CHAT / FEISHU_TOOL），无环境变量覆盖 |
| S2 | `run_report_v10.py` | L22-28 | 飞书 APP_ID / FOLDER_TOKEN / USER_OPENID 硬编码在源码中 |
| S3 | `run_report_v10.py` | L32-34 | `feishu_call()` 使用 `bash -c` + JSON 字符串拼接，存在 shell 注入风险 |
| S4 | `core/secrets.py` | L14-19 | 与 config.py 共享相同硬编码默认值。仅此处支持 `os.environ.get` 覆盖 |

---

## 四、架构层面关键问题

### 4.1 双引擎并行（已确认）

| 引擎 | 文件 | 输出范围 | 标准化方法 | 因子数 | 谁在用 |
|------|------|---------|-----------|--------|--------|
| v3.1 | `factor_scanner.py` | [1, 10] | 固定区间线性插值 | 6 因子 | `run_daily.py`（主日报管线） |
| v4.0 | `factor_engine.py` | [0, 1] | scipy.rankdata 截面分位数 | 19 子因子→7 风格 | `run_factor_daily.py`（独立脚本） |

两个引擎的输出不可直接比较，策略阈值（faceji entry=5.0）基于旧引擎 [1,10] 设置。

### 4.2 两套策略实现并存

| 实现 | 位置 | 特点 |
|------|------|------|
| 策略类 | `trading_engine.py` 中的 `FacejiStrategy`/`SilverQuantStrategy`/`TradingAgentsStrategy` | 有状态（持仓/现金）、模拟盘执行 |
| 纯函数 | `strategies/faceji.py`/`silverquant.py`/`tradingagents.py` | 无状态、仅生成 Signal 列表 |

两者同一策略的建仓/清仓逻辑不完全一致（如 `silverquant.py` 硬编码 `size_pct=3.0` 未使用 `cfg.slot_amount`）。

### 4.3 配置双重维护

| 文件 | 行数 | 状态 |
|------|------|------|
| `config.py` | 1035 | 最新，15 条产业链，完整 WATCHLIST（~92 只） |
| `domain/__init__.py` | 881 | **落后于 config.py**：CPI_STRATEGY_MAP 缺 2 key、WATCHLIST 截断、产业链缺"物理 AI 链" |

两个文件独立维护，无 `from config import *`。修改配置需同步两处。

### 4.4 三套数据层

| 文件 | 角色 | 缓存机制 | baostock 连接 |
|------|------|---------|-------------|
| `data_router.py` | 统一路由 + cachedio 装饰器 | pickle 文件，30 天 TTL | 委托给 source 模块 |
| `data_layer.py` | 旧主力（A 股财务/行情/宏观） | 进程内存 + 文件 | 持久连接 + signal.alarm |
| `data_source_layer.py` | 新层（DataResult 质量标注） | JSON 缓存 + 限流 | 每次 login/logout |

三套系统各自管理 baostock 会话，互不协调。

---

## 五、策略逻辑 Bug（P1）

| # | 文件 | 行号 | 问题 |
|---|------|------|------|
| P1 | `base.py` | L37-38 | `Signal.to_dict()` 中 `0.0 if self.pnl_pct else None`——pnl_pct=0.0 被当作 falsy 转为 None |
| P2 | `silverquant.py` | L47 | 硬编码 `size_pct=3.0`，未使用 `cfg.slot_amount=30000.0` |
| P3 | `tradingagents.py` | L27-28 | bull 主导时 bull 占 60%，bear 主导时 bear 仅占 50%——不对称 |
| P4 | `tradingagents.py` | L434-438 | bull=`sc*0.5+ts*0.5`（均值）vs bear=`sc-bp`（减法）——两种计算不在同一尺度 |
| P5 | `faceji.py` | L129 | MASeller 缺少 `continue`，可能产生重复 SELL 信号 |
| P6 | `portfolio_builder.py` | L74-77,448-461 | Signal 定义 4 层风控字段但 `_check_stop_loss` 只实现 2 层 |
| P7 | `portfolio_builder.py` | L425,438 | `score` 字段误存 `kelly_fraction` |

---

## 六、数据管线问题

| # | 问题 | 文件 | 行号 |
|---|------|------|------|
| D1 | `get_history` 30 天 TTL——新交易日数据可能不更新 | `data_router.py` | L114 |
| D2 | 社融阈值 `sf_growth > 9.0` 硬编码，未从配置读取 | `macro_engine.py` | L105 |
| D3 | 三个文件各自管理 baostock 连接，无统一会话池 | `data_layer.py` / `baostock_source.py` / `data_source_layer.py` | 多处 |
| D4 | `signal.alarm` 在 Windows/容器中不可用 | `data_layer.py` | L45 |
| D5 | `_compute_sector_pe_median` 只返回一个"默认"中位数，实际行业 PE 计算残缺 | `universe_builder.py` | L129-132 |
| D6 | `turnover_20d` 指标实际计算的是成交额，非换手率 | `factor_engine.py` | L568-570 |

---

## 七、WATCHLIST 统计

| 市场 | 数量 | 备注 |
|------|------|------|
| A 股个股 | 47 | AI 算力/半导体/机器人/物理 AI/新能源/军工/医药/消费/金融/公用/大宗/电网 |
| 港股 | 9 | 腾讯/阿里/中芯/紫金/美团/小米/移动/比亚迪/药明生物 |
| 美股 | 18 | NVDA/TSM/ANET/MU 等 AI 链 + MSFT/GOOGL/META 等科技 |
| A 股 ETF | 11 | 红利低波/纳指 100/黄金/豆粕/芯片/军工/国债/城投债/沪深 300/中证 500 |
| 美股 ETF | 6 | TLT/TIP/IEF/XLU/XLP/GDX |
| 贵金属/期货 | 5 | GLD/GC=F/SLV/HG=F/CL=F（GLD/HG=F/CL=F 重复） |
| 宏观追踪 | 4 | ^TNX/^FVX/CNY=X/DXY |
| **总计** | **~92** | 含重复条目 |

### WATCHLIST 重复条目
- **GLD**: L352 和 L404（tier/focus 完全一致）
- **HG=F**: L354 和 L406
- **CL=F**: L355 和 L407

---

## 八、INDUSTRY_CHAINS 对比

| 文件 | 链数量 | 缺失 |
|------|--------|------|
| `config.py` | 15 | — |
| `domain/__init__.py` | 14 | 缺"物理 AI 链" |

文档/日志宣称 10 条链，实际已扩展到 15 条。

---

## 九、回测系统问题

| # | 问题 | 文件 | 行号 |
|---|------|------|------|
| R1 | `_build_realistic_universe()` 已定义但从未被调用——幸存者偏差修正未启用 | `backtest.py` | L80-101 |
| R2 | 策略 4 存在两份独立实现（`run_macro_driven_allweather` vs `run_strategy4`），使用不同权重字典和不同成本模型 | `backtest.py` | L543-676 vs987-1279 |
| R3 | `run_allweather` 和 `run_macro_driven_allweather` 无交易成本计算——回测结果显著乐观 | `backtest.py` | L427-480,543-676 |
| R4 | `run_allweather` 偏离 5% 的再平衡阈值未实现——仅按日历月再平衡 | `backtest.py` | L432（注释）,461-463 |
| R5 | 基准不可用时静默生成全 NaN Series | `backtest.py` | L1385 |
| R6 | Evaluator 固定 19 只硬编码标的，与当前 46 只动态池不匹配 | `evaluator_fixed.py` | L38-58 |

---

## 十、Dashboard 问题

| # | 问题 | 文件 | 行号 |
|---|------|------|------|
| W1 | 三个 Dashboard 刷新间隔不统一：DASHBOARD_HTML 60s / COMPARISON_HTML 60s / UNIFIED 120s | `portfolio_server.py` | L660,377,1173 |
| W2 | `load()` 覆盖所有 innerHTML，120s 刷新时用户标签页状态丢失 | `portfolio_server.py` | L1173 |
| W3 | 实时价格实为最近一次因子扫描快照，非真正实时推送 | `shadow_account.py` | L79-89 |
| W4 | LDS 组件价格必然获取失败——通过 yfinance 获取 A 股 ETF 代码 `512890`（缺 `.SS` 后缀） | `report_v6.py` | L367-387 |
| W5 | 无 CORS 配置——同源部署没问题，但反向代理分离前后端即不可用 | `portfolio_server.py` | L50 |

---

## 十一、概念引擎统计

`concept_engine.py` 头部注释宣称"47+ 条面基播客概念"，实际只实现了 26 个方法。

| 类别 | 已实现 | 缺失 |
|------|--------|------|
| 估值类 | 4 | — |
| 产业链类 | 2 | — |
| 仓位风控 | 7 | — |
| 行为心理 | 1 | — |
| 宏观周期 | 3 | — |
| LDS 框架 | 3 | — |
| 综合决策 | 6 | — |
| 缺失 | — | E14/E15/E32/E39/E49/E51/E58/E71/E78/E88/E106/E110/E112/E113/E114/E115/E120/E121/E126/E127 等 |

---

## 十二、代码质量统计

| 指标 | 数值 |
|------|------|
| 总 Python 文件 | 94 |
| 测试文件 | 0 |
| 硬编码凭据 | 7 处 |
| 裸 `except: pass` | ~100 处 |
| 超大文件（>1000 行） | 6 个 |
| 最大文件 | `report_v6.py`（2575 行） |
| 类型提示覆盖率 | ~60% |
| Linter 配置 | 无 |
| CI/CD | 无 |

---

## 十三、优先级行动清单

| 优先级 | 行动 | 预估工时 |
|--------|------|---------|
| 🔴 P0 | 移除 `run_report_v10.py` + `config.py` 硬编码凭据 → 环境变量 | 0.5h |
| 🔴 P0 | 修复 `data_layer.py` 财务 `abs()` 问题（4 处） | 1h |
| 🔴 P0 | 修复 `trading_engine.py` 模拟盘周频过滤接线 | 0.5h |
| 🔴 P0 | 修复 MACD 金叉判定（`evaluator_fixed.py` / `backtest_v2.py` / `backtest_all.py` 三处） | 0.5h |
| 🔴 P0 | 修复 `faceji.py` L62 MA 趋势过滤方向 | 0.5h |
| 🟡 P1 | 修复 `report_v6.py` 章节编号 | 1h |
| 🟡 P1 | 决定配置主源（`config.py` vs `domain/__init__.py`）并消除重复 | 1h |
| 🟡 P1 | 统一双引擎评分体系 | 4h |
| 🟡 P1 | 修复 `deep_research.py` DCF 占位符 | 2h |
| 🟡 P1 | 修复 `base.py` L37-38 0.0→None 转换 | 0.5h |
| 🟡 P1 | 修复 `feature_engine.py` PoolManager 晋级逻辑 | 1h |
| 🟢 P2 | 整合三套数据层 | 8h |
| 🟢 P2 | 回测启用幸存者偏差修正 | 2h |
| 🟢 P2 | 删除 WATCHLIST 重复条目 | 0.5h |
| 🟢 P2 | Dashboard 刷新机制统一 | 1h |
| 🟢 P3 | 补充 `concept_engine.py` 缺失概念 | 按需 |
| 🟢 P3 | `cost_model.py` pickle→JSON 迁移 | 1h |

---

## 附录 A：审计覆盖文件清单

| 维度 | 审计文件 |
|------|---------|
| 交易引擎 | `trading_engine.py`(749), `backtest.py`(1682), `backtest_v2.py`(356), `backtest_all.py`(644), `strategy_comparison.py`(594), `evaluator_fixed.py`(878) |
| 因子引擎 | `factor_engine.py`(935), `factor_scanner.py`(631) |
| 数据管线 | `data_router.py`(195), `data_layer.py`(885), `data_source_layer.py`(720), `akshare_source.py`(193), `yahoo_source.py`(74), `baostock_source.py`(114) |
| 策略层 | `faceji.py`(131), `silverquant.py`(97), `tradingagents.py`(121), `base.py`(103) |
| 管线入口 | `run_daily.py`(982), `run_trading.py`(183), `run_factor_daily.py`(123), `portfolio_builder.py`(568) |
| Dashboard | `portfolio_server.py`(1469), `report_v6.py`(2575), `shadow_account.py`(388), `concept_engine.py`(881) |
| 报告 | `run_report_v10.py`(513), `auto_deep_research.py`(142), `deep_research.py`(335) |
| 配置 | `config.py`(1035), `domain/__init__.py`(881), `stock_universe.py`(368), `core/secrets.py`(19) |
| 分析 | `macro_engine.py`(394), `stop_list.py`(303), `cost_model.py`(166), `universe_builder.py`(213) |
