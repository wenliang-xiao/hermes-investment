# Vibe-Trading 深度调研 × Hermes 对标分析

> **日期**: 2026-07-07 | **来源**: GitHub HKUDS/Vibe-Trading 源码+文档+PR | **对比基准**: Hermes 当前最新代码

---

## 一、Vibe-Trading 是什么

HKUDS (香港大学数据科学实验室) 开发的开源量化投研工具。**18k+ GitHub Stars**，Apache 2.0 协议。

核心定位：**"从你的交易记录中提炼策略，再跨市场回测它"**——不是帮你做策略，是帮你发现自己已经有的好策略，并量化"如果不犯错会多赚多少"。

| 维度 | Vibe-Trading | Hermes |
|------|-------------|--------|
| 定位 | 投研工具箱 (research workspace) | 投资辅助系统 (decision support) |
| 核心循环 | Shadow Account (交易日记→规则提取→回测→报告) | 因子扫描→策略信号→日报推送 |
| 数据源 | 18 源 (tushare/yfinance/akshare/baostock/tencent/mootdx/futu/okx/ccxt/sina/eastmoney/stooq/yahoo+可选finnhub/alphavantage/tiingo/fmp) | 4 源 (baostock/yfinance/akshare/tencent) |
| 资产覆盖 | A股+港股+美股+加密+期货+外汇+期权 | A股+港股+美股+ETF |
| 策略来源 | **从用户自己的交易记录中提取** | 预定义的3个策略 |
| 报告格式 | HTML/PDF (可下载) | 飞书文档 |

---

## 二、Shadow Account 完整流程（Hermes 最该借鉴的）

```
你的券商交割单 (CSV)
    │
    ▼
analyze_trade_journal()──────┐
  - 交易画像 (持仓天数/胜率/盈亏比)   │
  - 行为诊断 (4种偏差)              │
  > disposition effect (处置效应)   │  这是Hermes完全没有的能力
  > overtrading (过度交易)          │
  > chasing (追涨)                 │
  > anchoring (锚定)               │
    │                              │
    ▼                              │
extract_shadow_strategy()─────┘
  - KMeans聚类盈利交易
  - 提取3-5条 if-then 规则
  - 如: "A股早盘10-11点买入，持仓3-7天，盈利>5%卖出"
    │
    ▼
run_shadow_backtest()
  - 用提取的规则跨市场回测
  - delta-PnL (你买 vs 规则买 差多少)
  - 归因分解 (噪音交易/早卖/晚卖/过度交易/错失信号)
    │
    ▼
render_shadow_report()
  - 8段HTML/PDF报告
  - 带图表
  - 今日匹配信号扫描
```

### 归因分解（delta-PnL分解）

这是最精彩的设计。Shadow Account 不是简单告诉你"你亏了 X，规则能赚 Y"，而是**把差距分解为5个可行动的原因**：

```
噪音交易亏损   = -Σ 你做了但规则不会做的交易盈亏
早卖亏损       = +Σ 你卖太早少赚的部分
晚卖亏损       = +Σ 你卖太晚多亏的部分
过度交易亏损   = -Σ 超出规则预期交易频率的额外交易
错失信号亏损   = 残差（规则能赚但你不能解释的部分）
```

Hermes 的 shadow_account.py 只能追踪持仓盈亏，没有归因分析能力。

---

## 三、Dashboard 功能对标

| 功能 | Vibe-Trading | Hermes | 建议借鉴 |
|------|-------------|--------|---------|
| 策略回测面板 | 7引擎+基准对比 | 1引擎(回测存储刚修好) | ✅ 多引擎对比 |
| Shadow报告 | 8段HTML/PDF+图表 | 无 | ⭐ 最该借 |
| 交易日记分析 | 4种行为诊断 | 无 | ⭐ 最该借 |
| Alpha因子库 | 452个预训练因子,一键bench | 20个子因子(手动) | ✅ 因子bench |
| 绩效指标 | Sharpe/Sortino/Alpha/Beta/DD | Sharpe/Sortino/DD | ✅ 加Alpha/Beta |
| 多agent投资委员会 | 29个swarm团队 | 1个辩论制(tradingagents) | ✅ 投资委员会 |
| 技术形态识别 | 蜡烛图/艾略特/一目均衡/SMC | MACD/RSI/MA | ❌ 过度工程 |
| 期权分析 | BS/Greeks/多腿策略 | 无 | ❌ 不在范围内 |
| 加密交易台 | 资金费率/清算热力图 | 无 | ❌ 不在范围内 |

---

## 四、日报/周报内容对标

| 板块 | Hermes 当前 | Vibe-Trading 可借鉴 |
|------|-----------|-------------------|
| **行为反思**（新增） | ❌ 无 | 交易日记分析结果（你今天是不是过度交易了？是不是追涨了？锚定了哪些票？）|
| **影子对比**（新增） | ❌ 无 | "你的规则建议买 X，但你买了 Y，delta = -¥3,200" |
| **归因分解**（新增） | ❌ 无 | 本周亏损的5个原因拆分 |
| **产业链分析** | ✅ 15链（Hermes独有） | Vibe-Trading没有这个 |
| **双门风控** | ✅ LDS双门（Hermes独有） | Vibe-Trading没有这个 |
| **宏观象限** | ✅ 货币信用四象限 | Vibe-Trading有宏观分析skill |
| **Alpha评估** | ⚠️ IC均值 | ✅ IC/IR+衰减追踪+Alive/Reversed/Dead分类 |
| **ETF配置** | ⚠️ 4ETF(数据源有bug) | Vibe-Trading有ETF分析skill |

---

## 五、数据获取对标

| 数据源 | Hermes | Vibe-Trading | 差距 |
|--------|--------|-------------|------|
| A股实时 | 腾讯财经 ✅ | 腾讯/东财/新浪/baostock | Vibe多源但腾讯已是最优 |
| A股历史 | baostock | tushare/baostock/akshare | tushare质量更高 |
| 港股 | yfinance | yfinance/futu/tushare | 少了futu(富途)直连 |
| 美股 | yfinance | yfinance/stooq/yahoo | 相当 |
| ETF | ⚠️ yfinance(纯数字代码兼容差) | tushare ETF路由 | 借鉴ETF数据源路由 |
| 债券 | ❌ 无 | 无 | 双方都缺 |
| 加密 | ❌ | okx/ccxt | 不在Hermes范围 |
| 回退链 | ⚠️ 有但不统一 | ✅ 18源自动有序fallback | 借鉴标准化fallback |

---

## 六、回测能力对标

| 能力 | Hermes | Vibe-Trading | 建议 |
|------|--------|-------------|------|
| 引擎数量 | 1(回测存储) | 7(中国A/全球股/加密/中国期货/全球期货/外汇/期权) | Hermes加1个ETF引擎即可 |
| 基准对比 | 沪深300全收益 | 多基准对比面板 | ✅ 加多基准 |
| PIT数据 | ❌ | ✅ PIT-safe entry context | 借鉴PIT保障 |
| 行为回测 | ❌ | ✅ Shadow Account回测 | ⭐ 最该借 |
| Alpha bench | ❌ | ✅ 一行CLI跑452个alpha | 可借鉴但优先级低 |
| 归因分解 | ❌ | ✅ delta-PnL五维分解 | ⭐ 最该借 |

---

## 七、金融工具覆盖对标

| 工具类别 | Hermes | Vibe-Trading | 建议 |
|---------|--------|-------------|------|
| A股个股 | ✅ 47只 (Watch+策略) | ✅ 全市场 | 保持 |
| 港股 | ✅ 9只 | ✅ 全市场 | 扩展WATCHLIST |
| 美股 | ✅ 18只 | ✅ 全市场 | 保持 |
| A股ETF | ⚠️ 11只(数据源bug) | ✅ tushare专用ETF路由 | 修数据源 |
| 美股ETF | ✅ 6只 | ✅ yfinance | 保持 |
| 债券 | ❌ | ❌ | 双方都缺，但不急 |
| 期货 | ⚠️ 5个(GC=F/CL=F等) | ✅ OKX/CCXT | Hermes够用 |
| 外汇 | ⚠️ DXY/CNY=X | ✅ 18源覆盖 | Hermes够用 |
| 期权 | ❌ | ✅ BS/Greeks | Hermes范围外 |
| 加密 | ❌ | ✅ 深度覆盖 | Hermes范围外 |

---

## 八、优先级建议：该借的和不该借的

### ⭐ 立即该借的（P0-P1，1-3天各）

| 借鉴内容 | 对应Hermes模块 | 预估工时 | 理由 |
|---------|---------------|---------|------|
| **Shadow Account归因分解** | `shadow_account.py`扩展 | 3天 | 这是Vibe-Trading最独特的价值，帮你量化"不犯错能多赚多少" |
| **交易日记行为诊断** | 新增`analysis/behavior.py` | 2天 | 处置效应/过度交易/追涨/锚定——四个指标能极大改善你的交易纪律 |
| **delta-PnL日报板块** | `report_v6.py`加Section | 1天 | 日报里加一行"你今天的行为成本是¥X"，比80%的重复静态内容有价值100倍 |

### ✅ 应该借的（P1，1-3天各）

| 借鉴内容 | 说明 |
|---------|------|
| **ETF数据源路由** | tushare的ETF→fund_daily()模式，解决Hermes ETF纯数字代码获取失败问题 |
| **多基准回测对比** | 在回测面板加沪深300/中证500/标普500多个基准 |
| **IC/IR因子衰减追踪** | 不止看IC均值，看IC_IR和衰减曲线，自动降权失效因子 |

### ❌ 不该借的

| 不借 | 原因 |
|------|------|
| 452 Alpha因子库 | Hermes的19→7因子体系是自己的，不需要复制别人的因子 |
| 加密交易台 | 完全不在Hermes范围 |
| 期权定价 | 不在范围 |
| 艾略特/一目均衡 | 个人投资者不需要18种技术形态 |
| 多agent投资委员会 | 29个swarm team是LLM密集的玩具级实现，不是真正的量化团队 |
| Alpha Zoo CLI bench | Hermes不需要bench别人的因子 |

---

## 九、Hermes vs Vibe-Trading：你的独特优势（别丢掉）

Vibe-Trading 没有的，Hermes 独有的：

| Hermes独有能力 | 价值 |
|---------------|------|
| **LDS双门风控** | 货币信用四象限+国运线趋势温度，9种状态→仓位建议。这是你从面基播客体系提炼的，任何开源工具都没有 |
| **产业链深度分析** | 15链中观分析含利润池位置、Perez阶段、翻倍逻辑、催化剂——Vibe-Trading没有这个层次 |
| **面基概念引擎** | 26个投资概念封装为可调用分析函数（DCF/Kelly/Bayesian更新/四重确认） |
| **飞书日报推送** | 自动定时推送到飞书——Vibe-Trading只有手动生成的HTML/PDF |

Vibe-Trading 适合**借用它来补你的行为分析短板**，不是替代你的独特优势。

---

## 十、最终建议

**如果你只做一件事：把 Shadow Account 的归因分解 + 行为诊断加到日报里。**

```
日报新增板块「你的行为成本」：

📊 今日行为诊断
  处置效应: ⚠️ 中 — 亏损股平均持仓11.2天 vs 盈利股5.1天。你倾向持有亏损
  追涨倾向: ✅ 低 — 最近5笔买入都没有追涨
  过度交易: ⚠️ 高 — 本周交易8次(超过策略建议的3次)

💰 行为成本（本周）
  噪音交易: -¥4,200 (做了规则不会做的4笔交易)
  早卖少赚: +¥1,800 (3笔交易卖太早)
  合计: 本周多亏了 ¥2,400
```

**这个比现在日报里 80% 的静态产业链框架重复输出有价值 10 倍**——因为它是关于你的，每天都不一样，直接告诉你该怎么改。
