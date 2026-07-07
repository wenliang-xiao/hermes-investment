# Hermes 投资系统 · 完整体系手册

> 最后更新: 2026-07-07
> 读完本文你就能完全理解 Hermes 的每一块拼图：它从哪来、现在能做什么、差在哪、优先做什么。

---

## 一、基因溯源

Hermes 不是从零造的。它的设计 DNA 来自六个开源项目和三大投资哲学。

```
技术骨架:
  hl-quant    → 纯函数策略 + 固定评估器 + Walk-Forward
  xalpha      → @cachedio 缓存装饰器 + 数据源前缀路由
  OSkhQuant   → 绩效指标面板 + 7面板Dashboard布局
  OpenSpec    → 切片交付 + 先写方案再动手

策略内核:
  段永平      → 不为清单（10条规则）
  凯利公式    → 动态仓位
  面基154期   → 产业链认知+双门风控+概念引擎
  银城量化    → SilverQuant 固定槽位¥30K

工程方法:
  Superpowers → 阻塞bug→基建→增量的三步节奏
  Karpathy    → 编码纪律
  TDD         → 测试先行（88个测试）
```

---

## 二、当前架构全景

```
入口层
  run_daily.py ─── 每日日报主线（FactorScannerCompatV4→信号→模拟盘→飞书推送）
  run_factor_daily.py ─── 因子独立扫描（FactorEngine批量评分+PoolManager三层池）
  run_weekly.py ─── 周报（产业链深度+资产配置审视）

数据层（三套并存）
  data_router.py ─── 统一路由+cachedio装饰器（xalpha血统）
  data_layer.py ─── 旧A股主力（baostock+东方财富）⚠️ 财务abs()坑
  data_source_layer.py ─── 新层（DataResult质量标注+限流+重试）
  腾讯财经API ─── A股实时行情（最新最优，替代了东财+新浪）

因子层（v4.0统一）
  factor_engine.py ─── 8风格因子(含分红)×20子因子×截面分位×IC滚动×James-Stein收缩
  FactorScannerCompatV4 ─── 兼容层（自动输出转v3.1的[1,10]分）

宏观层
  macro_engine.py ─── 货币信用四象限×CPI策略开关×国运线趋势温度→仓位建议

策略层（两套并存——叠加不拆除）
  strategies/faceji.py ─── 纯函数：评分+MA趋势+Kelly（上限8%）+4层风控
  strategies/silverquant.py ─── 纯函数：评分≥5.0+不为清单，固定3%槽位+4层风控
  strategies/tradingagents.py ─── 纯函数：辩论分≥5.5+Kelly（上限12%）+3层风控
  trading_engine.py ─── 旧有状态类（保留运行，委托纯函数）

回测层
  evaluator_fixed.py ─── 固定评估器19只标的，Walk-Forward 252d+63d×3
  backtest.py ─── 4策略回测对比（含分层滑点+基准修正+幸存者偏差修正[未启用]）
  backtest_storage.py ─── 标准化回测存储

输出层
  report_v6.py ─── 9板块飞书日报（2575行）
  portfolio_server.py ─── Dashboard :8686，内嵌HTML 7面板+12 API端点
  shadow_account.py ─── 模拟盘追踪，4层止损，冷却期
  concept_engine.py ─── 26个面基投资概念封装为可调用函数
```

---

## 三、你独有的（不要丢的）

| 能力 | 为什么独特 | 对标情况 |
|------|-----------|---------|
| **LDS双门风控** | 货币信用四象限×国运线趋势温度，9种状态→仓位建议 | Vibe-Trading/TradingAgents/Bloomberg都无此设计 |
| **产业链深度** | 15链中观分析，含利润池+Perez周期+翻倍逻辑+催化剂 | 无开源项目有此层次 |
| **面基概念引擎** | 26个投资概念（DCF/Kelly/Bayesian/四重确认）封装为可调用函数 | Vibe-Trading有79个skill但偏量化，无价值投资导向 |
| **飞书日报推送** | 自动定时+飞书格式 | Vibe-Trading只有手动HTML/PDF，无人定时推送 |

---

## 四、每个子系统：来源 × 当前状态 × 优化方向

### 4.1 策略层

**来源**: hl-quant（纯函数）+银城量化（SilverQuant）+TradingAgents（辩论制）+凯利+段永平

**当前状态**(✅):
- faceji/silverquant/tradingagents三策略都是纯函数，输入→输出，零IO
- 4层共享风控（HardSeller -8% / FallSeller -12% / ScoreDrop <4.5 / MASeller）
- Kelly动态仓位（半凯利，上限8-12%）
- 88个测试覆盖

**当前缺陷**(⚠️):
- tradingagents.py不是真正的多Agent辩论——是纯数学公式近似，bull/bear不在同一尺度
- 三策略买的基本是同一组票（建仓标的重叠80-90%）
- 旧trading_engine.py的类实现仍存在（重复维护负担）

**优化方向**(借鉴Vibe-Trading):
- [P1] 三条策略方向差异化：大盘质量(慢速)/小盘动量(中速)/ETF跨资产
- [P2] 加行为反馈：shadow_account记录"策略建议了什么→你执行了什么→差异在哪"
- [P3] 保留tradingagents.py的数学近似（快速+零成本），作为基准；另外可选接TradingAgents LLM版本做对比

### 4.2 因子引擎

**来源**: hl-quant(固定评估器方法论) + Vibe-Trading(IC/IR分层思想) + James-Stein

**当前状态**(✅):
- v4.0已统一：8风格因子(含dividend)×20子因子×截面分位×IC滚动×贝叶斯收缩
- FactorScannerCompatV4兼容层输出[1,10]分给老管线
- v3.1退役标注

**当前缺陷**(⚠️):
- 无行业中性化——当前截面分位是全截面做，不是行业内分组
- 无因子衰减追踪——只看IC均值，不看半衰期
- 无因子拥挤度——不知道多少资金挤在同一因子上
- IC权重双层加权问题——base在conditional_weight中被利用两次

**优化方向**:
- [P1] 行业内百分位排序（借鉴Barra标准，2天工作量）
- [P1] IC_IR因子衰减追踪（借鉴Vibe-Trading，自动降权失效因子，2天）
- [P2] 因子质量报告（Alive/Reversed/Dead分类，借鉴Vibe-Trading Alpha Zoo的bench逻辑）

### 4.3 宏观引擎

**来源**: 面基154期播客（货币信用四象限）+ LDS实战框架（CPI策略开关+国运线）

**当前状态**(✅):
- 四象限判定（信用×货币→复苏/扩张/过热/衰退）
- CPI×PMI×社融策略开关→因子权重+仓位建议
- 国运线趋势温度（凉/平/温/热）

**当前缺陷**(⚠️):
- 社融阈值9.0硬编码在代码里，不是配置驱动
- 宏观数据缓存路径与data_router不一致
- 未有宏观情景分析（极端场景下的压力测试）

**优化方向**:
- [P1] 社融阈值移到MACRO_THRESHOLDS配置
- [P2] 全局缓存路径统一
- [P3] 宏观情景分析：给定CPI/PMI极端值→预估策略开关状态

### 4.4 数据管线

**来源**: xalpha(cachedio+路由) + Vibe-Trading(18源fallback) + 腾讯API(实时行情)

**当前状态**(✅):
- cachedio透明缓存（来自xalpha）
- 前缀路由数据源分发
- 腾讯财经实时行情（最优A股源）
- atomic_io.py原子写入
- 4源覆盖A/HK/US

**当前缺陷**(⚠️):
- 三套数据层并存（data_router+l_data+data_source_layer）各自管理baostock连接
- A股ETF纯数字代码用yfinance获取（必然失败）
- 30天cachedio TTL（新交易日数据可能不更新）
- 财务数据在旧data_layer中有abs()问题（新层已规避）

**优化方向**(借鉴Vibe-Trading):
- [P0] A股ETF数据源修复（用腾讯/akshare替代yfinance）
- [P1] 三套数据层收敛为一个统一入口
- [P1] 标准化fallback链（按IP封禁风险排序+共享限流HTTP网关）
- [P2] 数据质量告警（DataResult.failed→飞书通知）

### 4.5 回测系统

**来源**: hl-quant(Walk-Forward+HL循环) + xalpha + 自研(分层滑点+基准修正)

**当前状态**(✅):
- Walk-Forward 252d+63d×3
- 分层滑点模型（5级价格×成交额）
- 全收益基准修正（沪深300+2.5%年化股息）
- 幸存者偏差修正代码存在（但未启用）

**当前缺陷**(⚠️):
- Walk-Forward只用19只固定标的（跟不上当前46只动态池）
- 幸存者偏差修正写了但未调用
- 无双门宏观条件的回测验证
- 回测对比Dashboard显示"数据积累中"（无历史快照）

**优化方向**(借鉴Vibe-Trading + hl-quant):
- [P1] Walk-Forward pool扩展到46只动态标的
- [P1] 每日自动积累历史快照→回测对比面板真实数据
- [P2] 加基准对比面板：vs沪深300全收益/vs中证500/vs标普500
- [P3] 偷Vibe-Trading的归因分解（噪音/早卖/晚卖/过度交易/错失信号五维分解）

### 4.6 新闻引擎

**来源**: Google News RSS(基础) + 雪球热帖 + GLM-4-Flash(摘要)

**当前状态**(⚠️):
- 抓取Google News RSS + 雪球
- GLM-4-Flash摘要
- 6板块分类
- **无情感评分、无异动关联、无舆情趋势**

**对比Vibe-Trading**:
Vibe有18个读数据工具(RoBERTa情感评分+LLM推理+龙虎榜+北向+大宗交易+股东变化+限售解禁+SEC EDGAR+问财自然语言查询)

**优化方向**(借鉴Vibe-Trading):
- [P1] 加情感评分层：对每条新闻输出正面/负面+强度（可复用GLM做但需结构化输出）
- [P1] 加异动关联：这条新闻影响哪个产业链？哪只票？
- [P2] 加舆情趋势：市场整体情绪在变好还是变差？
- [P2] 加龙虎榜/北向资金/大宗交易数据工具
- [P3] 加问财自然语言查询

### 4.7 模拟盘 (Shadow Account)

**来源**: hl-quant + Vibe-Trading(Shadow Account思想) + 自研(4层止损)

**当前状态**(⚠️):
- 4层止损正确（寒武纪-8.91%触发HardSeller）
- 冷却期机制
- price=0清仓bug已修复（3层防线）
- **无行为诊断、无归因分解**

**对比Vibe-Trading Shadow Account完整流程**:
Vibe有五步：交易日记分析→行为诊断(4种)→规则提取(3-5条)→跨市场回测→delta-PnL归因→HTML/PDF报告

**优化方向**(借鉴Vibe-Trading):
- [P1] 行为诊断：处置效应/过度交易/追涨/锚定（2天，纯数据计算，不需要外部数据）
- [P1] delta-PnL归因：噪音交易/早卖/晚卖/过度交易/错失信号五维分解（1天）
- [P2] 规则提取：从shadow_account历史中提取你的3-5条交易规则（3天）
- [P2] HTML/PDF报告导出（2天）

### 4.8 Dashboard

**来源**: OSkhQuant(7面板+绩效指标) + 自研(Chart.js+FastAPI)

**当前状态**(⚠️):
- 7面板（模拟盘/回测/票池/ETF/新闻/日报/绩效）
- 12 REST API端点
- Chart.js图表+60s刷新
- HTML内嵌在portfolio_server.py 1469行（未解耦）
- 无导出/无告警推送/无响应式/无执行按钮

**优化方向**:
- [P1] HTML解耦（CSS/JS分离，<1天）
- [P1] 加行为诊断面板（处置效应/过度交易/追涨/锚定）
- [P1] 加风险仪表盘（波动率/集中度/VaR值）
- [P2] 数据导出（CSV/PDF）
- [P2] 移动端响应式
- [P3] 告警推送

### 4.9 日报

**来源**: 面基知识体系 + 自研（飞书集成）

**当前状态**(⚠️):
- 9板块（双门/全球市场/ETF/产业链/新票/新闻/追踪/调仓/概念）
- 飞书自动推送
- 80%是每日重复的静态产业链框架
- 章节编号系统错乱
- 链配置硬编码在源码中

**优化方向**:
- [P0] 日报加行为成本板块（你今天的行为成本是¥X）
- [P1] 静态产业链框架→链接到知识库文档，日报只写今日变化
- [P1] 章节编号修复
- [P2] 产业链配置YAML化（不硬编码在report_v6.py里）
- [P2] 加归因分解（本周亏损的5个原因拆分）

### 4.10 金融工具覆盖

**来源**: WATCHLIST + LDS ETF框架

**当前状态**:
A股47 / 港股9 / 美股18 / A股ETF 11 / 美股ETF 6 / 期货5 / 宏观4 = ~92只
**缺**: 债券、REITs、可转债、LOF

**优化方向**:
- [P1] A股ETF数据源修复（纯数字代码用腾讯/akshare替代yfinance）
- [P2] 债券ETF加入WATCHLIST
- [P2] ETF动态权重（偏离触发再平衡，替代当前纯日历月再平衡）

---

## 五、优化优先级总览

| # | 领域 | 内容 | 工时 | 效果 | 来源 |
|---|------|------|------|------|------|
| 1 | 日报 | 加行为成本板块（你今天亏了¥X因为...） | 1天 | 极高 | Vibe-Trading Shadow Account |
| 2 | ETF | A股ETF数据源修复（腾讯/akshare替代yfinance） | 0.5天 | 极高 | 自研bug修复 |
| 3 | 模拟盘 | 行为诊断4指标（处置效应/过度交易/追涨/锚定） | 2天 | 极高 | Vibe-Trading Trade Journal |
| 4 | 日报 | 静态产业链框架→知识库链接 | 2天 | 高 | 自研优化 |
| 5 | Dashboard | HTML解耦+风险面板（波动率/集中度/VaR） | 2天 | 高 | OSkhQuant+自研 |
| 6 | 因子 | 行业内百分位排序（行业中性化） | 2天 | 高 | Barra标准 |
| 7 | 因子 | IC_IR衰减追踪+自动降权失效因子 | 2天 | 高 | Vibe-Trading Alpha Zoo |
| 8 | 新闻 | 情感评分层（正面/负面+强度） | 1天 | 高 | Vibe-Trading RoBERTa |
| 9 | 模拟盘 | delta-PnL归因分解（噪音/早卖/晚卖/过度交易/错失） | 1天 | 高 | Vibe-Trading Shadow Account |
| 10 | 数据 | 三套数据层收敛为统一入口 | 3天 | 中高 | xalpha+自研 |
| 11 | 策略 | 三策略方向差异化（大盘质量/小盘动量/跨资产ETF） | 5天 | 中 | hl-quant+自研 |
| 12 | 回测 | Walk-Forward池扩展到46只+每日快照积累 | 3天 | 中 | hl-quant+自研 |
| 13 | 日报 | 产业链配置YAML化 | 2天 | 中 | 自研 |
| 14 | 回测 | 多基准对比面板（vs沪深300/vs中证500/vs标普500） | 2天 | 中 | QuantConnect标准 |
| 15 | 模拟盘 | HTML/PDF报告导出 | 2天 | 中 | Vibe-Trading |
| 16 | 新闻 | 龙虎榜+北向+大宗交易数据工具 | 2天 | 中 | Vibe-Trading 18工具 |
| 17 | 模拟盘 | 交易规则提取（从shadow_account历史中提炼3-5条规则） | 3天 | 中 | Vibe-Trading Shadow Account |
| 18 | 宏观 | 社融阈值配置化 | 0.5天 | 低 | 自研 |
| 19 | 新闻 | 问财自然语言查询集成 | 1天 | 低 | Vibe-Trading iwencai |
| 20 | 日报 | 章节编号修复 | 0.5天 | 低 | 自研 |

---

## 六、不做什么（以及为什么）

| 不做的 | 原因 |
|--------|------|
| Vibe-Trading的452 Alpha因子 | Hermes已有自己的19→8因子体系，不需要复制别人的 |
| Vibe-Trading的多agent投资委员会 | 29个swarm team是LLM密集的玩具级实现，不如Hermes的数学近似可靠 |
| Vibe-Trading的加密/期权/外汇模块 | 不在Hermes范围 |
| TradingAgents的LangGraph全Agent架构 | 每次决策5-8次LLM调用的成本不值得——保留数学近似版 |
| hl-quant的HL自动循环 | 手动HL循环更适合个人投资者 |
| Bloomberg式的实盘接口 | 需要2-3年工程+券商合作，不是P0-P2范围 |

---

## 七、快速启动：如果只做3件事

1. **日报加行为成本**（1天）：你打开日报第一眼就能看到"今天你的行为偏差让你亏了¥X"
2. **ETF数据源修复**（0.5天）：A股ETF价格不再是瞎的
3. **行为诊断4指标**（2天）：Dashboard上实时显示你现在有没有在处理效应、有没有在追涨

这三项3.5天完成，系统从"4分数据工具"跃迁到"6分决策辅助"。
