# Hermes Investment — 面基·LDS·桥水 三源融合量化投研系统

> 基于面基播客知识体系 × LDS 实战框架 × 桥水全天候原理，每日自动生成投资决策报告推送到飞书，并提供经过 2018−2026 回测验证的多策略量化引擎。

**策略四 v17 回测结果（2018−2024）：年化 23.1% / 最大回撤 −14.5% / 夏普 1.29 / 卡玛 1.60**

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [docs/STRATEGY.md](docs/STRATEGY.md) | 策略体系专业文档：方法论 / 六层架构 / 宏观判断 / 策略四原理 / 回测依据 |
| [docs/SOP.md](docs/SOP.md) | 操作手册：如何读报告 / 找票漏斗 / 建仓买卖清仓 / trailing stop |
| [MIGRATION.md](MIGRATION.md) | 代码迁移说明（文件移动记录） |
| [HERMES_CRON_CONFIG.md](HERMES_CRON_CONFIG.md) | ECS 定时任务配置 |

---

## 核心理念

```
宏观定方向 → 象限定配比 → 漏斗定标的 → 动量定排名 → trailing 定出场 → 凯利定仓位
```

**三源融合**：
- **面基播客**：六因子排序分位法 / Perez 五阶段 / 产业链利润池 / Nick 四问 / 凯利公式
- **LDS 框架**：CPI 驱动双门 / 趋势温度（凉→平→温→热）/ 国运线 / 右侧入场
- **桥水全天候**：货币信用四象限 / 五类资产风险平价 / 负相关对冲

---

## 系统架构

```
hermes-investment/
│
├── config.py                全局配置：WATCHLIST（83只）/ 14条链 / FACTOR_WEIGHTS / 风控参数
│
├── analysis/                分析引擎层
│   ├── macro_engine.py      宏观四象限 / LDS 双门 / 趋势温度 / 国运线
│   ├── factor_scanner.py    六因子评分（生产实时）+ PE 百分位 + 利润池 + Perez
│   ├── score_history.py     历史因子分重建（回测用）+ PE 历史序列拉取
│   ├── backtest.py          四策略回测引擎（含策略四 run_strategy4）
│   ├── chain_scanner.py     链内候选扫描：四段筛选 + 双轨评分
│   ├── news_engine.py       新闻引擎：财联社 + 新浪 + GLM-4-Flash 影响分析
│   └── anomaly_news.py      异动联动：≥5% 异动 → 自动搜索驱动因素
│
├── output/                  报告生成层
│   ├── report_v6.py         飞书报告生成器（日报 + 周报所有板块）
│   ├── full_asset_scanner.py 全资产扫描：ETF / 商品 / 汇率 / 桥水象限
│   ├── fund_tracker.py      LDS 全天候组合追踪
│   └── shadow_account.py    模拟盘持仓追踪（trailing stop 实时检查）
│
├── data/                    数据获取层
│   ├── data_layer.py        主数据层：Tushare Pro → baostock → AKShare
│   ├── tushare_layer.py     PE 历史 5 年 / 社融 / 北向资金
│   └── yf_data_layer.py     Yahoo Finance：美股 / 港股 / ETF / 商品 / 汇率
│
├── scripts/                 可执行入口
│   ├── run_daily.py         每日 08:30 + 18:00（主入口）
│   ├── run_weekly.py        每周日 18:00
│   └── verify_stock_codes.py 股票代码完整性验证
│
├── domain/                  纯数据层
│   └── __init__.py          所有静态数据：WATCHLIST / INDUSTRY_CHAINS（14条）
│
└── docs/                    文档层
    ├── STRATEGY.md          策略体系专业文档
    └── SOP.md               操作手册
```

---

## 日报 / 周报体系

### 每日决策简报 `scripts/run_daily.py`

工作日 **08:30（开盘前）** + **18:00（收盘后）** 自动生成，推送至飞书。6 个板块，5 分钟读完：

| 板块 | 内容 | 用途 |
|------|------|------|
| 一、决策面板 | 双门状态 / 宏观象限 / 策略四当期配比 / VIX / 北向 / 凯利开关 | 30 秒决策 |
| 二、持仓风控 | Trailing stop 实时状态 / 峰值 / 止损线 / 🚨触发标记 | 每日必查 |
| 三、观察池信号 | 全量 WATCHLIST 行情 + MA20/MA60 买点 + RSI/偏离信号 | 发现机会 |
| 四、链路摘要 | 引用最新周报链状态 + 候选票 | 链景气概览 |
| 五、今日情报 | 异动驱动因素 AI 分析 + 市场情报 | 过滤噪音 |
| 六、调仓建议 | 当期配比 + 交易纪律（trailing stop 规则） | 操作指导 |

### 周度深度研究 `scripts/run_weekly.py`

每**周日 18:00** 自动生成，15 个章节：

| 章节 | 内容 |
|------|------|
| 一、LDS 双门 | 完整双门 + 国运线 + 债券黄金信号 |
| 二、桥水四象限 | 当前经济象限判断 |
| 三−四、全天候组合 | ETF 净值 / 再平衡信号 / 多资产配置建议 |
| 五−七、债券/商品/外汇 | 利率曲线 / 大宗商品 / 主要汇率对 |
| 八、全球市场快照 | 主要指数 / 美债 / VIX |
| **九、15 链深度研究** | **每链：Perez 阶段 / 利润池 / 催化剂 / 核心标的** |
| **十、选股漏斗** | **L1 宏观门控 + L2 链内候选 + L3 多因子扫描** |
| 十一、本周情报 | 30 天视角政经要闻 + 链影响 |
| 十二、催化剂日历 | 下周重要事件预告 |
| 十三、持仓追踪 + 调仓 | 持仓风控 + 周度调仓建议 |
| **十四、链内候选** | **动态扫描：评分 / 买点 / 触发条件 / 失效条件** |
| 十五、Shadow Run | 六因子 vs D-lite 重叠率（因子收敛监控） |

---

## 策略四：核心策略

### 回测结果（2018−2024）

| 版本 | 年化 | 最大回撤 | 夏普 | 卡玛 |
|------|------|---------|------|------|
| v14（基准） | 19.9% | −14.5% | 1.30 | 1.37 |
| v16（六因子）| 19.0% | −15.3% | 1.20 | 1.24 |
| **v17（当前）** | **23.1%** | **−14.5%** | **1.29** | **1.60** |

v17 核心改进：**Two-Stage 选股**（质量门控 + 动量排名）+ **Trailing Stop**（替代固定止盈止损）

### 资产配置矩阵

| 象限 | A股 | 股票ETF | 债券ETF | 黄金 | 商品 | 美股 | 港股 |
|------|-----|--------|--------|------|------|------|------|
| 扩张期 | 25% | 20% | 10% | 15% | 15% | 20% | 10% |
| 复苏期 | 30% | 15% | 20% | 15% | 10% | 15% | 10% |
| 过热期 | 15% | 10% | 10% | 25% | 30% | 20% | 15% |
| 衰退期 | 20% | 10% | 30% | 30% | 10% | 15% | 15% |

**双门仓位乘数**：CPI 0−1%（中国常态）→ 0.80x（不空仓）；CPI 1−2% → 1.0x；MA60 ≤ −5% → 额外 × 0.60

---

## 14 条产业链

| 链名 | 类型 | 核心标的（已验证代码） |
|------|------|---------------------|
| 英伟达算力链 | 核心 | 300308 中际旭创 / 300502 新易盛 |
| 台积电先进制程链 | 核心 | 688012 中微公司 / 688120 华海清科 / 002371 北方华创 |
| 存储/HBM 链 | 核心 | 688008 澜起科技 |
| AI 应用/Agent 链 | 核心 | — |
| 机器人/自动化链 | 核心 | 688017 绿的谐波 / 300124 汇川技术 / 002747 埃斯顿 / 002472 双环传动 |
| 物理 AI 链 | 核心 | 688083 中望软件 / 301269 华大九天 / 688322 奥比中光 |
| 半导体链 | 核心 | 688041 海光信息 / 603501 韦尔股份 |
| 国产替代/信创链 | 核心 | — |
| 医药创新链 | 核心 | 603259 药明康德 / 300760 迈瑞医疗 |
| 军工链 | 核心 | 600760 中航沈飞 / 002179 中航光电 |
| 新能源链 | 核心 | 300750 宁德时代 / 601012 隆基绿能 |
| 消费电子链 | 条件触发 | — |
| 苹果产业链 | 条件触发 | — |
| 新能源汽车链 | 条件触发 | 300750 宁德 / 002594 比亚迪 |

> 所有代码已经 baostock 逐码验证（20260528，commit 6a41bcf）

---

## 回测引擎

```bash
# 运行四策略回测（end_date 自动取 baostock 最新交易日）
python3 -m investment_system.analysis.backtest

# 输出完整投资者报告
python3 -m investment_system.analysis.backtest --investor-report /tmp/report.txt
```

---

## Hermes Cron 配置

```yaml
# 工作日 08:30 开盘前日报
- command: python /home/admin/.hermes/investment_system/scripts/run_daily.py
  schedule: "30 8 * * 1-5"

# 工作日 18:00 收盘后日报
- command: python /home/admin/.hermes/investment_system/scripts/run_daily.py
  schedule: "0 18 * * 1-5"

# 周日 18:00 周报
- command: python /home/admin/.hermes/investment_system/scripts/run_weekly.py
  schedule: "0 18 * * 0"
```

详细配置见 [HERMES_CRON_CONFIG.md](HERMES_CRON_CONFIG.md)

---

## 环境变量

```bash
# 飞书机器人（必填）
export FEISHU_APP_ID="xxx"
export FEISHU_APP_SECRET="xxx"

# LLM 新闻分析（GLM-4-Flash 永久免费）
export ARK_API_KEY="your_zhipu_key"
export ARK_MODEL="glm-4-flash"
export ARK_API_BASE="https://open.bigmodel.cn/api/paas/v4/chat/completions"

# 数据源（Tushare 120 积分以上，免费注册）
export TUSHARE_TOKEN="your_token"
```

---

## 数据源

| 数据源 | 覆盖内容 | 费用 |
|-------|---------|------|
| baostock | A 股日线 / 财务季报 / 指数 / PE 历史 | 免费 |
| Tushare Pro | PE 历史 5 年 / 社融 / 北向资金 | 120 积分（免费注册） |
| Yahoo Finance | 美股 / 港股 / ETF / 商品 / 汇率 | 免费 |
| AKShare | 宏观 CPI / PMI / 财联社电报 | 免费 |
| Zhipu GLM-4-Flash | 新闻影响分析 LLM | 永久免费 |

---

## 交易纪律（速查）

```
建仓：双门开启 + 象限非衰退/过热 + 价格>MA60 + MA20>MA60
      单票 ≤ 总资产 2% | 分两批建仓（各 50%）

止损（Trailing Stop v17）：
  持仓 < 10天  → 成本 × 0.92（−8% 硬止损）
  盈利 ≥ 30%  → 峰值 × 0.88（−12%）
  盈利 10−30% → 峰值 × 0.85（−15%）
  其余情况    → 峰值 × 0.80（−20%）

换仓：新票分数 > 最弱持仓 × 120% 才换 | 衰退/过热期不开新 A 股仓
再平衡：月末，偏离 > 5% 触发
```

---

## 面基期数索引

| 期数 | 核心概念 | 系统对应 |
|------|---------|---------|
| E7/E84 | 中观四层次 / 产业链 | `analysis/chain_scanner.py` |
| E68/E124 | FCF 两朵花 / DCF | `analysis/factor_scanner.py` |
| E94/E98 | Perez 五阶段 / 康波 | `config.py` INDUSTRY_CHAINS |
| E119 | 桥水全天候 / 风险平价 | `output/fund_tracker.py` |
| E153 | 复利 + 凯利公式 | `analysis/backtest.py` |
| E155 | 五层蛋糕 / Capex / HALO | `output/concept_engine.py` |
| E81/E118 | Nick 灵魂四问 / 趋势 | `docs/SOP.md` §七 |
| E131 | 新宏观坐标 / 逆全球化 | `config.py` DOMESTIC_SUB_THEMES |
| E126 | 三周期嵌套 | `analysis/macro_engine.py` |

---

## 版本说明

| 版本 | 时间 | 主要内容 |
|------|------|---------|
| v1.0−v3.x | 2025 | 初始框架，扁平结构 |
| v4.0 | 2026-05-26 | 插件化分层架构重构，六层模块化 |
| v5.0 | 2026-05-27 | 物理 AI 链 (#15) + 代码修正 |
| **v5.5** | **2026-05-28** | **策略四 v17 + docs/ + 报告与策略四对齐** |

生产路径：`/home/admin/.hermes/investment_system/`  
包名：`investment_system`（本地仓库名 `hermes-investment`）
