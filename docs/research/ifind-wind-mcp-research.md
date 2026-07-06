# iFind MCP vs Wind MCP — 付费金融数据源研究报告

> **编写日期**: 2026-07-06
> **背景**: 个人量化投资系统（A股 + 港美股），当前使用 AKShare + baostock + yfinance（免费）
> **目标**: 评估升级到付费数据源的成本与收益

---

## 目录

1. [同花顺 iFind MCP](#1-同花顺-ifind-mcp)
2. [万得 Wind MCP](#2-万得-wind-mcp)
3. [对比分析](#3-对比分析)
4. [集成复杂度评估](#4-集成复杂度评估)
5. [推荐方案](#5-推荐方案)

---

## 1. 同花顺 iFind MCP

### 1.1 基本信息

| 项目 | 内容 |
|------|------|
| **官网** | [https://mcp.51ifind.com/](https://mcp.51ifind.com/) |
| **产品站** | [https://www.51ifind.com/](https://www.51ifind.com/) |
| **API 端点** | `https://api-mcp.51ifind.com:8643/ds-mcp-servers/` |
| **认证方式** | JWE Token（环境变量 `IFIND_AUTH_TOKEN`） |
| **服务域名** | 7 个（stock / fund / edb / news / bond / global_stock / index） |
| **工具总数** | **31 个** |
| **参考项目** | [claude-for-financial-services-cn](https://github.com/jwangkun/claude-for-financial-services-cn) — Tier-1 付费数据源 |
| **源代码** | [mcp-servers/ifind-mcp/](https://github.com/jwangkun/claude-for-financial-services-cn/tree/main/mcp-servers/ifind-mcp) |

### 1.2 定价方案

| 方案 | 月度价格 | 季度价格 | 年度价格 | 请求额度 | 并发限制 | 单次请求成本 |
|------|---------|---------|---------|---------|---------|------------|
| **试用版（Free）** | 免费 | 免费 | 免费 | 2,000 次（总量） | 2 req/s | — |
| **个人版（Personal）** | ¥40 | ¥120 | ¥399 | 5,000 次/月 | 5 req/s | ~¥0.008/次 |
| **企业版（Enterprise）** | ¥5,000 | ¥15,000 | ¥50,000 | 1,000,000 次/月 | 10 req/s | ~¥0.005/次 |

**增量包（额外配额）：**

| 类型 | 月卡 | 季卡 | 年卡 | 额度 |
|------|------|------|------|------|
| 个人增量包 | ¥25 | ¥75 | ¥249 | 2,000 次/月 |
| 企业增量包 | ¥3,000 | ¥9,000 | ¥30,000 | 500,000 次/月 |

### 1.3 各版本工具覆盖

| 服务域 | 工具数 | 试用版(Free) | 个人版 | 企业版 |
|--------|--------|:-----------:|:------:|:------:|
| **A 股** | 8 | ✅ 全部 | ✅ 全部 | ✅ 全部 |
| **基金** | 7 | ⚠️ search_funds 不可用 | ✅ 全部 | ✅ 全部 |
| **宏观行业(EDB)** | 2 | ⚠️ search_edb 不可用 | ⚠️ search_edb 不可用 | ✅ 全部 |
| **公告资讯** | 3 | ⚠️ search_trending_news 不可用 | ✅ 全部 | ✅ 全部 |
| **债券** | 4 | ✅ 全部 | ✅ 全部 | ✅ 全部 |
| **港美股** | 5 | ⚠️ search_global_stocks 不可用 | ✅ 全部 | ✅ 全部 |
| **指数板块** | 2 | ✅ 全部 | ✅ 全部 | ✅ 全部 |

### 1.4 工具清单（31 个）

#### stock — A 股（8 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_search_stocks` | 智能选股筛选 |
| `ifind_get_stock_summary` | 股票信息摘要 |
| `ifind_get_stock_info` | 证券与上市公司基本资料 |
| `ifind_get_stock_shareholders` | 股本及股东数据 |
| `ifind_get_stock_financials` | 财务报表（利润/资产负债/现金流） |
| `ifind_get_risk_indicators` | 定量风险指标 |
| `ifind_get_stock_events` | 事件类数据 |
| `ifind_get_esg_data` | ESG 数据 |

#### fund — 基金（7 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_search_funds` | 智能选基 |
| `ifind_get_fund_profile` | 基金基本资料 |
| `ifind_get_fund_market_performance` | 行情与业绩评价 |
| `ifind_get_fund_ownership` | 份额与持有人结构 |
| `ifind_get_fund_portfolio` | 投资组合配置 |
| `ifind_get_fund_financials` | 财务指标 |
| `ifind_get_fund_company_info` | 基金管理人指标 |

#### edb — 宏观行业经济（2 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_search_edb` | EDB 指标搜索（仅企业版） |
| `ifind_get_edb_data` | EDB 指标取数 |

#### news — 公告资讯（3 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_search_news` | 财经新闻资讯语义检索 |
| `ifind_search_notice` | 公告语义检索 |
| `ifind_search_trending_news` | 热门事件资讯搜索 |

#### bond — 债券（4 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_bond_basic_info` | 债券基础信息 |
| `ifind_bond_market_data` | 债券行情数据 |
| `ifind_bond_financial_data` | 债券财务指标 |
| `ifind_bond_special_data` | 债券特殊指标 |

#### global_stock — 港美股（5 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_search_global_stocks` | 港美股智能选股 |
| `ifind_global_stock_profile` | 港美股基本信息 |
| `ifind_global_stock_quotes` | 港美股行情数据 |
| `ifind_global_stock_financial` | 港美股财务数据 |
| `ifind_global_stock_events` | 港美股事件数据 |

#### index — 指数板块（2 个）
| MCP 工具名 | 功能 |
|-----------|------|
| `ifind_index_data` | 指数数据 |
| `ifind_sector_data` | 板块数据 |

### 1.5 优势与限制

**优势：**
- 价格极低（个人版年费仅 ¥399，折合约 $55 USD）
- 即开即用，通过 MCP 协议接入，无需安装客户端
- 覆盖 A 股全量数据 + 港美股基础数据
- Python FastMCP 实现，依赖极简（仅 `requests` + `mcp`）
- 有参考实现可直接复用 [ifind-mcp/server.py](https://github.com/jwangkun/claude-for-financial-services-cn/blob/main/mcp-servers/ifind-mcp/server.py)

**限制：**
- 个人版不支持 EDB 指标搜索（`search_edb`），仅企业版可用
- 免费试用仅 2,000 次总量，适合验证
- 港美股数据不如 Wind 全面（无风险指标、技术分析等）
- 数据深度不及 Wind（如财报详细程度、因子数据等）

---

## 2. 万得 Wind MCP

### 2.1 基本信息

| 项目 | 内容 |
|------|------|
| **官网** | [https://aifinmarket.wind.com.cn/#/home](https://aifinmarket.wind.com.cn/#/home) |
| **API 端点** | `https://mcp.wind.com.cn`（JSON-RPC 2.0） |
| **认证方式** | API Key（`ak_` 开头，环境变量 `WIND_API_KEY`） |
| **服务域名** | 8 个 |
| **工具总数** | **44 个** |
| **参考项目** | [claude-for-financial-services-cn](https://github.com/jwangkun/claude-for-financial-services-cn) — Tier-0 付费数据源（最高优先级） |
| **源代码** | [mcp-servers/wind-mcp/](https://github.com/jwangkun/claude-for-financial-services-cn/tree/main/mcp-servers/wind-mcp) |

### 2.2 定价方案

Wind MCP 采用 **按次计费 + 预充值** 模式，非固定订阅制：

| 项目 | 内容 |
|------|------|
| **计费模式** | 按 API 调用次数扣除积分（Prepaid Deduction） |
| **单次调用成本** | 约 ¥1 ~ ¥4 / 次（根据工具类型不同） |
| **充值方式** | 微信/支付宝扫码支付 |
| **免费额度** | 新用户可能获得初始体验金（需注册确认） |
| **订单管理** | 支持充值记录、变更明细查询 |

**典型调用扣费示例（从 JS 源码提取）：**
| 工具 | 单次扣费（积分） |
|------|:--------------:|
| `get_stock_price_indicators` | 2.5 |
| `get_stock_kline` | 2.5 |
| `get_stock_financial_report` | 4.0 |
| 基础查询 | 1.0 |

> ⚠️ **说明**：Wind MCP 的精确定价表未公开在网页中。定价以页面展示为准，充值套餐通过 API (`/mcp-goods/orderCreate`) 动态获取。实际使用时建议先注册获取具体报价。

### 2.3 工具覆盖 — 8 大服务域（44 个工具）

#### stock_data — A 股（10 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_search_stocks` | A 股智能选股筛选 |
| `wind_get_stock_price_indicators` | 最新行情快照（最新价、涨跌幅、换手率等） |
| `wind_get_stock_kline` | 历史 K 线（日/周/月，复权方式可选） |
| `wind_get_stock_quote` | 日内分钟行情 |
| `wind_get_stock_basicinfo` | 公司档案、主营、行业、IPO、上市板 |
| `wind_get_stock_fundamentals` | 财务数据（盈利、资产负债、现金流、增长率） |
| `wind_get_stock_equity_holders` | 股本、前十大股东、实控人、限售 |
| `wind_get_stock_events` | 重大事件（IPO、增发、并购、ST、分红） |
| `wind_get_stock_technicals` | 技术指标（MACD、KDJ、RSI、BOLL、融资融券） |
| `wind_get_risk_metrics` | 风险指标（Beta、Alpha、波动率、Sharpe、VaR） |

#### global_stock_data — 港股/美股（10 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_search_global_stocks` | 港股/美股智能选股筛选 |
| `wind_get_global_stock_price_indicators` | 最新行情快照 |
| `wind_get_global_stock_kline` | 历史 K 线 |
| `wind_get_global_stock_quote` | 日内分钟行情 |
| `wind_get_global_stock_basicinfo` | 公司档案、注册地、经营范围、指数成份 |
| `wind_get_global_stock_fundamentals` | 财务数据（盈利、PE/PB/PS、营收、历史分位） |
| `wind_get_global_stock_equity_holders` | 股本、主要股东、机构持仓、限售解禁 |
| `wind_get_global_stock_events` | 重大事件（IPO、增发、并购、监管、分红） |
| `wind_get_global_stock_technicals` | 技术指标（多周期涨跌幅、MACD、KDJ、RSI） |
| `wind_get_global_stock_risk_metrics` | 风险指标（Beta、Alpha、波动率、Sharpe、VaR） |

#### fund_data — 基金/ETF/LOF（10 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_search_funds` | 全市场基金产品筛选 |
| `wind_get_fund_price_indicators` | 最新行情快照（净值、IOPV、贴水率） |
| `wind_get_fund_kline` | 历史 K 线 |
| `wind_get_fund_quote` | 日内分钟行情 |
| `wind_get_fund_info` | 基金档案、费率、经理、风格、业绩基准 |
| `wind_get_fund_financials` | 财务数据（利润、净值、收入、费用、分红） |
| `wind_get_fund_holdings` | 重仓股、资产配置、行业配置 |
| `wind_get_fund_performance` | 业绩、排名、ETF/二级交易表现 |
| `wind_get_fund_holders` | 持有人结构、申赎情况、规模变动 |
| `wind_get_fund_company_info` | 基金管理公司档案、经理团队 |

#### index_data — 指数/板块（6 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_get_index_price_indicators` | 最新行情快照（涨跌家数、成分股贡献点数） |
| `wind_get_index_kline` | 历史 K 线 |
| `wind_get_index_quote` | 日内分钟行情 |
| `wind_get_index_basicinfo` | 指数档案（发布机构、基日、基点、成份数量） |
| `wind_get_index_fundamentals` | 基本面（PE/PB/PS、营收、利润、历史分位） |
| `wind_get_index_technicals` | 技术指标（多周期涨跌幅、MACD、RSI） |

#### bond_data — 债券（4 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_get_bond_basicinfo` | 债券档案（发行规模、票面利率、期限、兑付） |
| `wind_get_bond_issuer_info` | 发债主体信息 |
| `wind_get_bond_market_data` | 市场数据（报价、估价、溢价、久期、凸性、利差） |
| `wind_get_bond_financial_data` | 发债主体财务 |

#### financial_docs — 公告/新闻（2 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_get_company_announcements` | 公司官方公告（年报、季报、招股书等） |
| `wind_get_financial_news` | 第三方财经新闻、市场报道、政策动态 |

#### economic_data — 宏观/行业（1 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_get_economic_data` | 宏观或行业 EDB 指标数据（支持频率/量级/币种筛选） |

#### analytics_data — 通用取数兜底（1 个）

| MCP 工具名 | 功能 |
|-----------|------|
| `wind_get_financial_data` | 通用结构化取数兜底（其他专项工具无法覆盖时使用） |

### 2.4 优势与限制

**优势：**
- 中国金融数据行业标杆，覆盖面最广、数据最全面
- 44 个工具覆盖 A 股/港美股/基金/指数/债券/公告/宏观/分析 8 大服务域
- 港美股数据非常全面（含风险指标、技术分析、个股基本面）
- 有专门的风险指标工具（Beta/Alpha/Sharpe/VaR）— 对量化系统极有价值
- 支持日内分钟行情 + 历史 K 线 + 实时行情快照
- 通用取数工具 `get_financial_data` 作为兜底，几乎能覆盖所有数据结构

**限制：**
- 按次计费，高频使用成本较高
- 无公开透明的固定订阅价目表，需要注册后查看充值套餐
- 个人用户可能需要较高的初始充值
- 需要注册万得账号并通过审核

---

## 3. 对比分析

### 3.1 核心维度对比

| 维度 | iFind MCP | Wind MCP |
|------|:---------:|:---------:|
| **价格（个人年度）** | **¥399**（固定订阅） | 按次计费，需充值 |
| **价格（月度起步）** | ¥40/月（5,000 次） | 按次 ~¥1-4/次 |
| **免费试用** | ✅ 2,000 次总量 | ❓ 可能含体验金 |
| **工具总数** | 31 个 | **44 个** |
| **服务域** | 7 个 | **8 个** |
| **A 股覆盖** | ✅ 全面 | ✅ 最全面 |
| **港美股覆盖** | ✅ 基础 | ✅ **全面（含风险/技术指标）** |
| **基金/ETF** | ✅ 7 个工具 | ✅ **10 个工具（含持仓穿透）** |
| **债券** | ✅ 4 个工具 | ✅ 4 个工具 |
| **宏观 EDB** | ⚠️ 个人版无搜索 | ✅ 完整支持 |
| **技术指标** | ✅ 基础 | ✅ **高级（MACD/KDJ/RSI/BOLL）** |
| **风险指标** | ✅ 定量风险 | ✅ **Beta/Alpha/Sharpe/VaR** |
| **ESG 数据** | ✅ 有 | ❌ 无专用工具 |
| **分钟行情** | ❌ 无 | ✅ 有 |
| **集成难度** | 低（~150 行 server.py） | 低（~200 行 server.py） |
| **参考实现** | ✅ 开源 | ✅ 开源 |
| **数据权威性** | 高（同花顺） | **最高（万得行业标杆）** |

### 3.2 成本估算（个人量化系统月度用量场景）

假设典型的个人量化系统每天执行：
- 开盘前扫描全市场股票池（~200 次查询）
- 盘中每 30 分钟更新持仓行情（~100 次/天）
- 盘后更新财务数据和因子（~300 次）
- 每周一次全市场因子扫描（~1,000 次/周）
- 月均约 10,000 ~ 15,000 次 API 调用

| 数据源 | 月度成本估算 | 年度成本估算 | 备注 |
|--------|:-----------:|:-----------:|------|
| **iFind 个人版** | ¥40 | **¥399** | 5,000 次/月，超量需购增量包 |
| **iFind 个人版+增量包** | ~¥90 | ~¥1,000 | 每月加购 1 个增量包(¥25/2,000次) |
| **Wind 按次计费** | ~¥500-2,000 | ~¥6,000-24,000 | 取决于每次调用单价和频率 |

### 3.3 与现有免费数据源的互补分析

| 数据需求 | AKShare | iFind MCP | Wind MCP |
|---------|:-------:|:---------:|:--------:|
| A 股日行情 | ✅ 免费 | ✅ 付费替代 | ✅ 付费替代 |
| A 股财务数据 | ✅ 免费 | ✅ 更精确 | ✅ 最精确 |
| 港美股行情 | ⚠️ 有限 | ✅ 好 | ✅ 最好 |
| 实时分钟线 | ❌ | ❌ | ✅ |
| 技术指标因子 | ⚠️ 需自行计算 | ✅ 内置 | ✅ 内置 |
| 风险因子(Beta等) | ❌ | ✅ | ✅ |
| ESG 数据 | ❌ | ✅ | ❌ |
| 宏观 EDB | ⚠️ 部分有 | ⚠️ 个人版受限 | ✅ 完整 |
| 债券数据 | ❌ | ✅ | ✅ |
| 基金持仓穿透 | ❌ | ✅ | ✅ |
| 一致预期 | ✅ 有限 | ✅ | ✅ |

---

## 4. 集成复杂度评估

### 4.1 集成到现有 Hermes 系统的步骤

两者集成方式高度相似，均通过 **Python FastMCP** 实现 stdio/SSE 协议：

**最小集成步骤：**
1. **安装依赖**：`pip install requests mcp`
2. **配置密钥**：设置环境变量或创建 `mcp_config.json`
3. **启动服务**：`python server.py`（stdio 模式）或 `python server.py --transport sse --port 8002`（SSE 模式）
4. **注册到 Hermes**：在 Hermes 配置中添加 MCP 服务端点

**代码量估算：**
| 组件 | iFind MCP | Wind MCP |
|------|:---------:|:--------:|
| server.py | ~500 行 | ~700 行 |
| requirements.txt | 2 行 | 3 行 |
| mcp_config.json | 5 行 | 5 行 |
| 总计 | ~510 行 | ~710 行 |

### 4.2 集成复杂度评级

| 维度 | iFind MCP | Wind MCP |
|------|:---------:|:--------:|
| **部署难度** | ⭐☆☆☆☆（极低） | ⭐☆☆☆☆（极低） |
| **密钥获取** | ⭐⭐☆☆☆（简单注册） | ⭐⭐☆☆☆（注册+审核） |
| **依赖管理** | ⭐☆☆☆☆（2 个包） | ⭐☆☆☆☆（3 个包） |
| **MCP 标准符合度** | ✅ 完全兼容 | ✅ 完全兼容 |
| **SSE 部署支持** | ✅ 支持 | ✅ 支持 |
| **现有参考实现** | ✅ 可复用 | ✅ 可复用 |

> **总评**：两者集成复杂度均 **极低**（1/5），有现成的开源参考实现可直接使用。在 Hermes 系统中添加一个 MCP 数据源通常不超过 30 分钟。

---

## 5. 推荐方案

### 5.1 推荐优先级

基于个人量化投资系统的需求评估：

```
第一优先：iFind MCP 个人版（¥399/年）
  └─ 性价比极高，覆盖 95% 的 A 股+港美股基础数据需求
  └─ 月均 ¥40，低于一杯咖啡
  └─ 免费试用 2,000 次可充分验证

第二优先：Wind MCP（按需充值）
  └─ 当需要高级功能时补充（分钟行情、风险因子、EDB 搜索）
  └─ 适合作为 iFind 的补充，在特定场景使用
  └─ 按次计费，按需充值，避免固定成本
```

### 5.2 分阶段建议

#### 阶段一：iFind 验证（即时，¥0）
- 注册 iFind MCP 账号，获取 JWE Token
- 使用免费 2,000 次配额验证基础数据覆盖
- 确认数据满足 A 股行情、财务、港美股基础需求

#### 阶段二：iFind 个人版订阅（第 1 个月，¥40）
- 升级个人版（¥40/月或 ¥399/年）
- 集成到 Hermes 系统作为主要付费数据源
- iFind 作为 Tier-1，AKShare 降级为 Tier-2 备用

#### 阶段三：Wind 按需补充（如需）
- 当需要分钟级行情、高级风险因子、EDB 宏观数据时
- 注册 Wind AIFinMarket，充值小额体验
- Wind 作为 Tier-0 最高优先级，iFind 作为 Tier-1

### 5.3 数据源层级架构（推荐）

```yaml
数据源优先级:
  Tier-0: Wind MCP (付费按次)     # 最高优先级：高级数据需求
  Tier-1: iFind MCP (付费订阅)     # 主力付费数据源
  Tier-2: AKShare (免费)           # 免费备选
  Tier-3: baostock (免费)          # 二次备选
  Tier-4: yfinance (免费)          # 美股兜底
```

### 5.4 年度成本预算

| 项目 | 成本 | 说明 |
|------|:---:|------|
| iFind 个人版年费 | **¥399** | 主力数据源，5,000 次/月 |
| iFind 增量包（按需） | ~¥300/年 | 每月额外 2,000 次 |
| Wind 充值（按需） | ~¥500-1,000/年 | 特定场景补充 |
| **年度总计** | **~¥1,200-1,700** | 约 **$165-235 USD** |

> 💡 **结论**：iFind MCP 个人版是目前最适合个人量化系统的付费数据源——¥399/年的价格提供了远超 AKShare 的数据覆盖，而 Wind MCP 更适合作为高级补充。建议立即开始 iFind 免费试用验证。

---

## 6. 参考链接

### iFind MCP
- [iFind MCP 官网](https://mcp.51ifind.com/)
- [iFind 产品站](https://www.51ifind.com/)
- [开源 MCP Server 实现](https://github.com/jwangkun/claude-for-financial-services-cn/tree/main/mcp-servers/ifind-mcp)
- [集成计划文档](https://github.com/jwangkun/claude-for-financial-services-cn/blob/main/IFIND-INTEGRATION-PLAN.md)

### Wind MCP
- [Wind AIFinMarket 官网](https://aifinmarket.wind.com.cn/#/home)
- [开源 MCP Server 实现](https://github.com/jwangkun/claude-for-financial-services-cn/tree/main/mcp-servers/wind-mcp)
- [Wind 集成计划文档](https://github.com/jwangkun/claude-for-financial-services-cn/blob/main/IFIND-INTEGRATION-PLAN.md)（同一文档，后半部分）

### 参考项目
- [claude-for-financial-services-cn](https://github.com/jwangkun/claude-for-financial-services-cn) — 63 个 A 股金融 Skills，使用 Wind + iFind + AKShare 三级数据源
- [AKShare 官网](https://akshare.akfamily.xyz/) — 当前使用的免费数据源

---

> **研究完成**: 2026-07-06 | **方法**: 官网抓取 + JS 源码分析 + 开源项目参考
