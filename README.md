# Hermes Investment — 面基·LDS·Vibe-Trading 三源融合量化投研系统

> 基于面基播客 154 期知识体系 × LDS 实战框架 × Vibe-Trading 量化工具，每日自动生成投资决策日报推送到飞书，并提供多策略回测引擎。

---

## 一、核心理念

```
宏观定开关 → 趋势定温度 → 因子定配比 → 产业链定标的 → 风控定仓位 → 纪律定生死
```

三源融合：
- **面基播客**：货币-信用四象限 / Perez 五阶段 / 中观四层次 / 凯利公式 / DCF / 桥水全天候
- **LDS 框架**：CPI→加息预期→趋势温度（凉→平→温→热）/ 双门系统 / 国运线 / 8% 止损铁律
- **Vibe-Trading**：多因子 IC/IR / 产业链扩散理论 / Shadow Account

---

## 二、系统架构（v4.0 插件化分层架构）

```
hermes-investment/
│
├── config.py                   全局配置：WATCHLIST(83只)/INDUSTRY_CHAINS(14条链)/
│                               FACTOR_WEIGHTS/MACRO_THRESHOLDS/风控参数
├── __init__.py                 包入口（version: 3.3.0）
│
├── core/                       基础契约层
│   ├── __init__.py             数据模型：AssetSnapshot/MacroState/ResearchContext
│   └── secrets.py              凭据管理（优先读环境变量）
│
├── data/                       数据获取层
│   ├── data_layer.py           主数据层：Tushare→baostock→AKShare 三层优先级
│   ├── tushare_layer.py        Tushare Pro：PE历史5年/社融/北向资金
│   ├── yf_data_layer.py        Yahoo Finance：美股/港股/ETF/商品/汇率
│   ├── data_source_layer.py    AKShare ETF 专用层
│   ├── global_universe.py      全球资产标的池
│   └── global_data.py          全球市场数据采集
│
├── analysis/                   分析引擎层
│   ├── macro_engine.py         宏观引擎：货币信用四象限/趋势温度/LDS双门/国运线
│   ├── factor_scanner.py       多因子扫描：6因子+PE历史分位+FCF+ROE趋势+利润池
│   ├── multi_asset_engine.py   多资产轮动引擎：风险平价×宏观匹配×动量
│   ├── universe_builder.py     动态选股宇宙
│   ├── news_engine.py          新闻引擎：多路RSS+财联社+新浪+LLM影响分析
│   ├── anomaly_news.py         异动股新闻联动：≥5%异动→自动搜索驱动因素
│   ├── chain_scanner.py        链内候选扫描：四段筛选+双轨评分
│   ├── etf_bond_scorer.py      ETF/债券评分器：宏观匹配×动量×低波×技术
│   ├── score_history.py        因子分历史数据库：快照持久化/D-lite重建
│   └── backtest.py             回测引擎：三策略对比/月频再平衡/趋势止损
│
├── output/                     输出层（报告生成+飞书写入）
│   ├── report_v6.py            核心报告库：所有 build_* 板块函数
│   ├── full_asset_scanner.py   全资产扫描：ETF三维/商品/汇率/桥水象限
│   ├── fund_tracker.py         基金追踪：LDS全天候/再平衡信号
│   ├── concept_engine.py       面基概念引擎：Nick四问/凯利/DCF
│   └── shadow_account.py       模拟盘追踪
│
├── domain/                     纯数据层（无业务逻辑）
│   ├── __init__.py             所有静态数据：WATCHLIST/INDUSTRY_CHAINS(14条)等
│   ├── stock_universe.py       A股选股宇宙
│   ├── news_fetcher.py         RSS新闻拉取
│   └── etf_data.py             ETF静态数据
│
├── scripts/                    可执行入口
│   ├── run_daily.py            每日决策简报（08:30+18:00）← 主要入口
│   ├── run_weekly.py           周度链研究（周日18:00）
│   ├── run_research.py         按需个股深度研报
│   ├── run_brief.py            兼容入口 → run_report_v8.py
│   ├── run_detail.py           兼容入口 → run_report_v7.py
│   ├── run_report_v7.py        全量日报（含15链深度分析）
│   ├── run_report_v8.py        精简日报（5分钟决策版）
│   ├── deep_research.py        CLI深度研报
│   ├── morning_brief.py        盘前简报
│   ├── stock_analyzer.py       个股分析
│   ├── portfolio_monitor.py    持仓监控
│   └── verify_stock_codes.py   股票代码完整性验证（需baostock）
│
└── _archive/                   已停用（保留备查）
    └── jqdata_layer.py         JQData（试用账号数据不足，已停用）
```

---

## 三、14条产业链（INDUSTRY_CHAINS）

| 链名 | 类型 | 核心标的 | 核心逻辑 |
|---|---|---|---|
| 英伟达算力链 | 核心 | 300308中际旭创/300502新易盛 | GPU/光模块/PCB，AI算力基础设施 |
| 台积电先进制程链 | 核心 | 688041北方华创/688328华海清科 | CoWoS/先进封装/设备，物理瓶颈 |
| 存储/HBM链 | 核心 | 688008澜起科技/603986兆易创新 | HBM供给缺口>30% |
| AI应用/Agent链 | 核心 | — | Token消耗×渗透率<5%，肥美期 |
| 新能源链 | 核心 | 300750宁德/601012阳光电源 | 储能/逆变器，产能出清中 |
| 半导体链 | 核心 | 688012中微/688041北方华创 | 国产替代，设备国产化15%→35% |
| 国产替代/信创链 | 核心 | — | 2027央企信创DDL |
| 医药创新链 | 核心 | 603259药明/300760迈瑞 | CXO回暖，GLP-1出海 |
| 军工链 | 核心 | 600760沈飞/002179中航光电 | 军费稳增+军贸出口 |
| 机器人/自动化链 | 核心 | 300665绿的谐波/300274汇川 | Optimus量产预期，核心零部件 |
| 消费电子链 | 条件触发 | — | AI手机换机，CPI>1.5%激活 |
| 数据/云计算链 | 核心 | — | IDC/液冷，AI算力物理底座 |
| 苹果产业链 | 条件触发 | — | AI手机换机+A股供应商 |
| 新能源汽车链 | 条件触发 | 300750宁德/002594比亚迪 | 智驾爆发，整车出海 |

---

## 四、日报/周报体系

### 每日决策简报 `scripts/run_daily.py`

每天 **08:30（开盘前）** + **18:00（收盘后）** 触发，6个板块：

```
一、决策面板：双门状态 | 桥水象限 | VIX/北向/美债10Y/DXY/CPI | 凯利开关
二、持仓风控：浮盈% | 止损价 | 触发状态（有持仓才显示）
三、观察池信号：MA20/MA60买点 | 超买/超卖/异动解读（≥5%联动新闻搜索）
四、链路摘要：引用上次周报结论
五、今日情报：GLM影响分析（事实+影响路径+受影响标的+建议动作）
六、调仓建议：宏观基调+纪律检查
```

### 周度链研究 `scripts/run_weekly.py`

每**周日 18:00** 触发，含15链深度分析+链内候选扫描+因子分快照保存。

---

## 五、回测引擎 `analysis/backtest.py`

三策略对比（2018-至今，end_date自动取baostock最新交易日）：

| 策略 | 宇宙 | 关键规则 |
|---|---|---|
| 多因子选股 | WATCHLIST∩链内（当前17只） | 月频再平衡/换仓门槛15%/趋势止损 |
| LDS全天候ETF | 红利25%+纳指30%+黄金25%+豆粕20% | 月底再平衡 |
| 多因子+双门 | 同策略一 | CPI<1%或>3% OR MA60<-5% → 空仓 |

因子评分构成（D-lite+）：
- 利润池位置 25%（面基核心：买利润率最高环节）
- ROE质量 20%
- Perez阶段乘数（展开期×1.15，导入期×1.10，成熟期×0.88）
- 动量 20%、低波 15%、技术 10%、营收增速 10%

```bash
python3 -m investment_system.analysis.backtest \
  --start 2018-01-01 \
  --investor-report /tmp/report.txt
```

---

## 六、Hermes Cron

```yaml
command: python /home/admin/.hermes/investment_system/scripts/run_daily.py
schedule: "30 8 * * 1-5"   # 工作日08:30

command: python /home/admin/.hermes/investment_system/scripts/run_daily.py
schedule: "0 18 * * 1-5"   # 工作日18:00

command: python /home/admin/.hermes/investment_system/scripts/run_weekly.py
schedule: "0 18 * * 0"     # 周日18:00
```

---

## 七、环境变量

```bash
export FEISHU_APP_ID="xxx"
export FEISHU_APP_SECRET="xxx"
export ARK_API_KEY="your_zhipu_key"       # Zhipu GLM-4-Flash，永久免费
export ARK_MODEL="glm-4-flash"
export ARK_API_BASE="https://open.bigmodel.cn/api/paas/v4/chat/completions"
export TUSHARE_TOKEN="your_token"         # 120积分以上
```

---

## 八、风控纪律

```
止损：单票买入后立即设止损 = 成本 × 0.92（-8%）
止盈：成功持仓（涨>15%后）改用趋势止损（从峰值回撤20%才卖）
仓位：单票 ≤ 总资产 2%（凯利/2约束）
持仓：最多 8 只
再平衡：月度检查，偏离5%触发
清盘线：总回撤 > 25% 全清
```

---

## 九、数据源

| 数据源 | 覆盖范围 | 费用 |
|---|---|---|
| baostock | A股日线/财务季报/指数 | 免费 |
| Tushare Pro | PE历史5年/社融/北向 | 120积分（免费注册） |
| Yahoo Finance | 美股/港股/ETF/商品/汇率 | 免费 |
| AKShare | 宏观CPI/PMI/财联社电报 | 免费 |
| Zhipu GLM-4-Flash | 新闻分析LLM | 永久免费 |

JQData 已停用（见 `_archive/jqdata_layer.py`，试用账号近3个月数据不足回测需求）。

---

## 十、面基期数索引

| 期数 | 核心概念 | 系统对应 |
|---|---|---|
| E7/E84 | 中观四层次 | analysis/chain_scanner.py |
| E68/E124 | FCF两朵花/DCF | analysis/factor_scanner.py |
| E94/E98 | Perez五阶段/康波 | config.py INDUSTRY_CHAINS |
| E119 | 桥水全天候/风险平价 | output/fund_tracker.py |
| E153 | 复利+凯利公式 | analysis/backtest.py |
| E155 | 五层蛋糕/Capex/HALO | output/concept_engine.py |
| E81/E118 | Nick灵魂四问/趋势 | analysis/factor_scanner.py |
| E131 | 新宏观坐标/逆全球化 | config.py DOMESTIC_SUB_THEMES |
| E126 | 三周期嵌套 | analysis/macro_engine.py |
