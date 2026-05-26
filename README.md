# Hermes Investment — 面基·LDS·Vibe-Trading 三源融合量化投研系统

> 基于面基播客 154 期知识体系 × LDS 实战框架 × Vibe-Trading 量化工具，每日自动生成投资决策日报推送到飞书。

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

## 二、系统架构

```
hermes-investment/
│
├── 📊 数据层（Data）
│   ├── data_layer.py          主数据层：Tushare→JQData→baostock→AKShare 四层优先级
│   ├── tushare_layer.py        Tushare Pro：PE历史5年/社融/北向资金（最权威）
│   ├── jqdata_layer.py         JQData 聚宽：日线/财务/多季ROE/FCF
│   ├── yf_data_layer.py        Yahoo Finance：美股/港股/ETF/商品/汇率
│   ├── data_source_layer.py    AKShare ETF专用层：A股ETF行情/全市场快照
│   └── global_universe.py      全球资产标的池（美股9链/港股/ETF/商品/汇率）
│
├── 🧠 分析层（Analysis）
│   ├── macro_engine.py         宏观引擎：货币信用四象限/趋势温度/LDS双门/国运线
│   ├── factor_scanner.py       多因子扫描：6因子评分+PE历史分位+FCF+ROE趋势+成交量
│   ├── full_asset_scanner.py   全资产扫描：LDS全天候/ETF三维/商品/汇率/桥水四象限
│   ├── multi_asset_engine.py   多资产轮动引擎：风险平价×宏观匹配×动量评分（54只资产）
│   ├── universe_builder.py     动态选股宇宙：全市场A股快照→研究池/买入池/脱钩池
│   ├── news_engine.py          新闻引擎：12路RSS+时间窗口+情绪量化+LLM总结
│   └── concept_engine.py       面基概念引擎：Nick四问/凯利公式/DCF等27个概念可计算
│
├── ⚙️ 配置层（Config）
│   ├── config.py               全局配置：WATCHLIST(80只)/OPPORTUNITY_THEMES/宏观阈值/数据源账号
│   ├── stock_universe.py       A股选股宇宙：11个板块/157只/宏观→板块映射
│   └── fund_tracker.py         基金追踪：LDS全天候两个版本/ETF同类对比/公募基金
│
├── 📝 报告层（Report）
│   ├── report_v6.py            核心报告库：所有 build_* 板块函数
│   └── scripts/
│       ├── run_report_v8.py    🟢 主日报（5分钟决策版）—— 每日先跑
│       └── run_report_v7.py    🔵 详细研究版（全量分析）—— 每日后跑
│
└── 🔧 工具（Tools）
    ├── morning_brief.py        盘前简报（8:30 AM，全球隔夜市场）
    ├── stock_analyzer.py       个股深度分析（LDS产业链定位法）
    ├── deep_research.py        个股深度研报（8维框架：翻倍逻辑/DCF/贝叶斯/Nick四问）
    ├── shadow_account.py       Shadow Account（信号记录/模拟盘/纪律追踪）
    └── portfolio_monitor.py    持仓监控（偏离追踪/再平衡信号/止损检查）
```

---

## 三、日报体系

### 主日报（5分钟决策版）`scripts/run_report_v8.py`

每天早上最先推送，只看这一份就够做当日决策：

```
一、今日核心信号
  宏观双门状态 | 桥水象限 | 实际利率信号
  全球市场快照（指数/VIX/北向资金）| LDS全天候今日表现

二、观察池今日行情
  只展示今日有信号的标的（超买/超卖/放量/大涨大跌）
  每只票：价格+涨跌+技术分+RSI+产业链+核心逻辑

三、今日重要事件（最多5条）
  LLM提炼 + 产业链影响标注 + 市场情绪得分

四、操作纪律
  双门关闭→防御模式 | 双门开启→进攻板块
  8%止损 / 15%+30%止盈 / 2%仓位上限
```

### 详细研究版（全量分析）`scripts/run_report_v7.py`

深度阅读用，包含：
- 桥水四象限 + 多资产配置引擎（54只资产风险平价）
- LDS全天候 ETF 组合成分 + 再平衡信号
- ETF 动量-风险-费率三维排序
- 债券收益率曲线 + 大宗商品 + 外汇地缘折价
- **10链深度分析**：链内多因子排名 + A股利润池映射 + 翻倍逻辑 + 催化剂日历
- A股/港股/美股多因子新票发现（含PE历史分位/FCF/ROE趋势）
- 核心观察池（80只标的今日行情）+ 7大挖掘主题 + 国家队资金信号
- 政经要闻（12路RSS + 情绪量化 + LLM总结）

---

## 四、数据源架构

```
数据请求
  ↓
Tushare Pro（主力，配置后生效）
  PE历史5年 ✅  社融增速 ✅  ROE多季 ✅  FCF ✅  北向资金（需2000积分）
  ↓ 失败
JQData 聚宽（3个月试用已接入）
  日线行情 ✅  财务指标 ✅  PE历史12个月 ✅
  ↓ 失败
baostock（稳定免费安全网）
  基础日线 ✅
  ↓ 失败
AKShare（宏观月度数据兜底）
  CPI/PMI/M2 ✅  ETF实时快照 ✅

美股/港股/ETF/商品/汇率 → Yahoo Finance（独立通道）
```

在 `config.py` 配置账号（或设置同名环境变量）：

```python
JQDATA_USER = "手机号"        # 聚宽 JQData
JQDATA_PASS = "密码"
TUSHARE_TOKEN = ""            # tushare.pro 注册免费获取，120积分即可用
```

---

## 五、核心观察池（WATCHLIST，约80只）

| 类别 | 代表标的 | 核心逻辑 |
|------|---------|---------|
| AI算力链 | 新易盛/中际旭创/寒武纪 | 光模块800G→1.6T，AI算力互联瓶颈 |
| 半导体设备 | 中微/北方华创/华海清科 | CoWoS刻蚀设备，国产化率<20% |
| 机器人零部件 | 绿的谐波/汇川技术/埃斯顿 | 减速器/伺服是瓶颈，不赌整机 |
| 消费防守 | 贵州茅台/招商银行/长江电力 | 高ROE+高股息，防守压舱石 |
| 港股折价 | 腾讯/中芯/美团 | PE折价30-60%，地缘修复机会 |
| 美股AI链 | NVDA/TSM/MSFT/GOOGL | 各链龙头，研究用 |
| LDS底仓ETF | 512890/513100/518880/159985 | 全天候，不择时月度再平衡 |
| 债券/黄金 | TLT/511010/GLD | 象限4防御，实际利率驱动 |

---

## 六、LDS 投资铁律

| 规则 | 参数 |
|------|------|
| 硬止损 | -8%，到了就执行，不商量 |
| 第一止盈 | +15%，减半仓 |
| 第二止盈 | +30%，清仓 |
| 单票仓位 | ≤总资产2%（凯利/2） |
| 最大持仓数 | 8只 |
| 再平衡触发 | 偏离>5% |
| 总回撤清盘 | >25% |
| 宏观+趋势双关 | 空仓等信号 |

---

## 七、快速开始

```bash
# 安装依赖
pip install baostock akshare yfinance tushare jqdatasdk pandas numpy

# 运行主日报（生产环境）
cd /home/admin/.hermes
python investment_system/scripts/run_report_v8.py   # 主日报，约30秒
python investment_system/scripts/run_report_v7.py   # 详细版，约5分钟

# 盘前简报
python investment_system/morning_brief.py
```

推荐 cron 调度：
```cron
00 9 * * 1-5  cd /home/admin/.hermes && python investment_system/scripts/run_report_v8.py
05 9 * * 1-5  cd /home/admin/.hermes && python investment_system/scripts/run_report_v7.py
30 8 * * 1-5  cd /home/admin/.hermes && python investment_system/morning_brief.py
```

---

## 八、中美脱钩视角（核心主题）

- **给AI美国公司做制造**：NVDA/MSFT订单链 → 沪电股份(002463)/新易盛(300502)
- **技术封锁受益**：美国禁运 → 华大九天(688099) EDA / 中微(688012) 刻蚀设备
- **资本管制收紧**：富途/老虎被罚 → 中信证券(600030)/东方财富(300059)/港交所
- **国家队资金**：社保/汇金季报监控 → 招商银行/长江电力/北方华创

---

## 九、面基关键期数索引

| 期数 | 核心观点 | 代码体现 |
|------|---------|---------|
| E7/E84 | 中观四层次 | `_CHAIN_CONFIGS` profit_pool 字段 |
| E68/E124 | FCF两朵花/DCF | `data_layer.get_financial_history()` |
| E94/E98 | Perez五阶段/康波 | 每条链的 perez_stage 字段 |
| E119 | 桥水全天候/风险平价 | `multi_asset_engine.py` |
| E131 | 逆全球化/新宏观坐标 | `OPPORTUNITY_THEMES` 中美脱钩 |
| E153 | 复利+凯利公式 | `concept_engine.kelly_position()` |
| E155 | 五层蛋糕/Capex护城河 | 链分析⑤面基框架标注 |
| E81/E118 | Nick灵魂四问 | `concept_engine.nick_four_questions()` |

## 许可

内部研究用途
