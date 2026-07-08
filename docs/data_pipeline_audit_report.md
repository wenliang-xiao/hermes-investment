# 数据管线审计报告

**审计时间**: 2026-07-06 22:15  
**审计范围**: investment_system/data/ + scripts/news_pipeline.py + scripts/realtime_price.py  
**审计方式**: 静态代码分析 + 数据文件检查

---

## 1. data_router.py — 统一数据路由

### 架构

`data_router.py` 实现了一个 **前缀路由 (prefix-based dispatch)** 模式，灵感来源于 xalpha 的 `_get_daily()`。这是整个数据管线的**核心调度器**，提供两个主要入口函数：

| 入口 | 功能 | 缓存 |
|---|---|---|
| `get_history(symbol, days)` | 获取历史日线 | 带 TTL=720h(30天) 的 pickle 缓存 |
| `get_rt(symbol)` | 获取实时行情 | 无缓存 |
| `get_rt_safe(symbol)` | 双源交叉验证实时行情 | 内部调 get_rt |

### 路由规则

| 条件 | 路由目标 | 覆盖范围 |
|---|---|---|
| `.HK` 结尾 | yfinance | 港股 |
| `^` 开头 | yfinance | 指数/美债收益率 |
| `CL=/GC=/HG=` 含等号(排除CNY/USD) | AKShare 期货 | 外盘期货 |
| `51/15/16/159` 开头 | AKShare ETF | A股ETF(硬编码选择AKShare而非baostock) |
| 全数字6位 | baostock | A股 |
| 预定义 US 列表 | yfinance | 美股/美ETF |
| 其他 | yfinance (默认) | 其余全部→yfinance |

### 路由覆盖评分

- ✅ 支持 A 股(baostock)、港股/美股/指数(yfinance)、A股ETF(AKShare)、期货(AKShare)
- ✅ 优雅的 `cachedio` 装饰器 — 使用 pickle + 文件名哈希键 + TTL 控制
- ✅ `get_rt_safe` 对 A 股做东财+新浪交叉验证(偏差>0.5%告警)
- ⚠️ 期货仅硬编码 3 个品种(CL, GC, HG)，不可扩展
- ⚠️ `akshare_etf` 路由仅匹配 `51/15/16/159` 开头，遗漏 `56`/`58` 等代码
- ⚠️ 默认投 yfinance 对纯 yfinance 不可达标的标的无 fallback

**评分: 7.5/10**

---

## 2. data/sources/ 源模块分析

### 2.1 baostock_source.py (A股日线)

- **函数**: `get_history_a(symbol, days)`
- **数据获取**: baostock → pandas → 手动序列化为 dict
- **字段**: date, open, high, low, close, volume, amount, peTTM, pctChg
- **代码转换**: `_a_code()` 将 6 位代码转为 `sh.xxxxxx`/`sz.xxxxxx`
- **Fallback**: 当 baostock 无数据时尝试 AKShare `fund_etf_hist_em` 作为后备
- **异常处理**: 登录失败返回 None，数据解析异常跳过单行
- ⚠️ **硬编码日期**: AKShare ETF fallback 中 end_date 写死为 `"20260625"`（已过期）
- ⚠️ **重复登录**: 登录两次（行44和行15），后一次未 logout

### 2.2 akshare_source.py (AKShare 数据源)

提供 5 个函数：

| 函数 | 用途 | 数据源 |
|---|---|---|
| `get_rt_em` | A股实时行情 | 东财 stock_zh_a_spot_em |
| `get_rt_sina` | 新浪实时行行情(交叉验证) | 新浪 API |
| `get_history_futures` | 期货历史日线 | AKShare futures_foreign_hist |
| `get_rt_futures` | 期货实时行情 | 同上(取最后两行计算涨跌幅) |
| `get_history_etf` | ETF历史日线 | 东财 fund_etf_hist_em |

- ✅ A 股实时有东财+新浪双源
- ✅ 期货实时 = 基于历史数据计算，非真正实时
- ⚠️ `get_rt_em` 每次扫描全量 A 股列表再过滤单只，对高频调用效率低
- ⚠️ 期货映射仅 3 个品种（扩展需改源码）
- ⚠️ ETF 历史依赖东财，baostock_source 中也有 ETF fallback，存在重复逻辑

### 2.3 yahoo_source.py (港美股/指数)

- **函数**: `get_history_yahoo`, `get_rt_yahoo`
- **数据**: yfinance → pandas DataFrame → dict 格式
- ✅ 统一的 OHLCV 返回格式
- ✅ `get_rt_yahoo` 使用多个 fallback 字段(currentPrice→regularMarketPrice→previousClose)
- ⚠️ `amount` 字段使用 `close * volume` 估算（非真实成交额）
- ⚠️ `pct_chg` 仅填充 0（标记"on demand"，但无实际计算）
- ⚠️ 无超时控制，yfinance 网络请求可能长时间挂起

### 2.4 sources/__init__.py

仅一行 docstring，无包级导出。使用者需直接 import 子模块。

**评分: 7/10**

---

## 3. data/cache/ 缓存分析

### 统计

| 指标 | 值 |
|---|---|
| 文件总数 | 315 |
| 总大小 | 5.26 MB |
| 覆盖标的数 | 111 |
| 平均文件大小 | 17.1 KB |

### 时效性分布

| 时效区间 | 文件数 | 占比 |
|---|---|---|
| < 1 小时 | 0 | 0% |
| 1-6 小时 | 30 | 9.5% |
| 6-24 小时 | 0 | 0% |
| 1-7 天 | 186 | 59.0% |
| > 7 天 | 99 | 31.4% |

- **最新**: 4.1 小时前（今日运行的标的）
- **最旧**: 269.6 小时前（~11.2天）
- **中位年龄**: 103.8 小时（~4.3天）

### 天数分布

| 天数参数 | 缓存文件数 |
|---|---|
| 10 天 | 70 |
| 130 天 | 54 |
| 250 天 | 70 |
| 478 天 | 18 |
| 1200 天 | 14 |
| 其他 | 89 |

### 缓存机制 `cachedio`

- ✅ TTL=720h(30天) 对历史数据合理
- ⚠️ 缓存文件名基于 args 拼接，args 顺序变化 → 不同缓存键（重复缓存）
- ⚠️ 无 LRU/大小限制，无限累积
- ⚠️ 无缓存失效手动触发机制（主动刷新需删文件）
- ⚠️ `days=10` 的缓存在非交易日无新数据写入，TTL 浪费

**评分: 6/10**

---

## 4. data/etf_universe.py — ETF标的定义

### 结构

- **数据类**: `EtfDef(symbol, name, category, region, benchmark, fee_pct)`
- **分类**: `broad`(宽基) | `sector`(行业) | `commodity`(商品) | `bond`(债券) | `cross_border`(跨境) | `strategy`(策略)
- **查询函数**: `get_etf_universe(category, region)`

### 标的覆盖

| 地区 | 数量 | 详情 |
|---|---|---|
| CN (A股) | 12 只 | 宽基5 + 行业6 + 商品1 + 债券2 |
| US (美股) | 11 只 | 宽基3 + 行业3 + 商品2 + 债券3 |
| **合计** | **23 只** | |

- ✅ 结构清晰，dataclass + category literal type hints
- ✅ 支持按 category/region 过滤
- ⚠️ 缺少港股ETF
- ⚠️ `cross_border` 和 `strategy` 分类无实际标的
- ⚠️ 无自动更新机制，需手动维护

**评分: 8/10**

---

## 5. 脚本分析

### 5.1 news_pipeline.py — 新闻管线

**架构**: 三级管线

| Tier | 功能 | 实现 |
|---|---|---|
| Tier 1 | AKShare 个股新闻采集 | `ak.stock_news_em(symbol, limit=N)` 从 WATCHLIST 获取核心标的新闻 |
| Tier 2 | GLM-4-Flash 新闻分析 | 调用火山引擎 API 生成投资分析摘要 |
| Tier 3 | 新闻→评分偏移 | 基于关键词的情绪打分(利好/利空)，产出 `news_score_offset.json` |

**产出文件**: `news_events.json` + `news_summary.txt` + `news_score_offset.json`

#### ⚠️ 严重问题：管线 Tier 1 完全损坏

`news_events.json` 内容显示所有 41 只标的全部返回错误：
```
"error": "stock_news_em() got an unexpected keyword argument 'limit'"
```

原因：AKShare `stock_news_em` API 签名已变更，不再接受 `limit` 参数。这意味着：
- Tier 1 全部失败 → 无新闻数据
- Tier 2 无输入 → GLM 分析无实质内容
- Tier 3 无输入 → `news_score_offset.json` = `{}`（空）

目前 `news_score_offset.json` 确实为空文件(2 bytes)，数据流完全断裂。

- ✅ GLM API 调用封装良好，带超时+回退
- ✅ 情绪打分关键词列表较全面(40+中英文关键词)
- ⚠️ Tier 2 的 prompt 对中文基金名称理解不充分

**评分(当前状态): 3/10**（因 Tier 1 损坏导致全线故障）

### 5.2 realtime_price.py — 实时行情服务

**功能**: 聚合持仓+信号标的的实时行情

**数据流**:
1. 读取 `shadow_account.json` 持仓
2. 读取 `trading_signals.json` 信号标的
3. 对每个标的调用 `data_router.get_rt()`
4. 返回 `{symbol: {price, change_pct, volume, ...}}`

**关键实现**:
- ✅ 每请求间隔 1.5s 防限流保护
- ✅ 6 秒超时控制(ThreadPoolExecutor)
- ✅ 自动合并持仓+信号标的去重
- ✅ 支持额外自定义标的列表
- ⚠️ 串行获取(有 1.5s 延迟)，10+ 标的需要 15s+
- ⚠️ `get_holding_symbols` 对列表推导中嵌套 if 可优化
- ⚠️ 无限流错误率统计/告警
- ⚠️ 缺少 Cache 对实时数据意义不大，但可考虑短 TTL 缓存

**评分: 7/10**

---

## 6. 数据文件 Schema 与时效性

### 文件清单

| 文件 | 大小 | 时效 | 描述 |
|---|---|---|---|
| `scan_snapshot_latest.json` | 37.8 KB | 4.1h | ✅ 因子扫描快照，含31只标的的多维评分 |
| `strategy_states.json` | 17.5 KB | 4.1h | ✅ 三策略交易历史+持仓状态 |
| `trading_signals.json` | 1.5 KB | 4.1h | ✅ 当日交易信号(3条SELL) |
| `news_events.json` | 5.9 KB | 4.1h | ⚠️ 新数据但全部为 error |
| `weekly_chain_summary.json` | 5.3 KB | 27.8h | ✅ 每周产业链总结 |
| `factor_daily.json` | 10.0 KB | 100.3h | ⚠️ 4天前，因子分数可能过期 |
| `factor_daily_hk_us.json` | 5.4 KB | 100.7h | ⚠️ 4天前 |
| `etf_portfolio.json` | 3.5 KB | 103.0h | ⚠️ 4天前 |
| `daily_report_links.json` | 0.4 KB | 103.6h | ✅ 日报链接 |
| `chain_candidates_cache.json` | 5.3 KB | 363.6h | ⚠️ 15天前 |
| `backtest_comparison.json` | 92.9 KB | 317.2h | ⚠️ 13天前 |
| `macro_raw_cache.json` | 0.2 KB | 1021.6h | 🔴 42天前，宏观数据严重过期 |
| `macro_engine_cache.json` | 1.0 KB | 997.8h | 🔴 41天前 |
| `news_cache.json` | 18.3 KB | 1021.8h | 🔴 42天前 |
| `global_market_cache.json` | 5.7 KB | 1067.0h | 🔴 44天前 |
| `report_20260522.json` | 1.7 KB | 1081.6h | 🔴 45天前(历史报告，合理) |
| `shadow_account.json` | 0.2 KB | 301.4h | ⚠️ 12天前(模拟盘空仓状态) |
| `news_score_offset.json` | 0.0 KB | 102.8h | ⚠️ 空对象 |

### 时效性总结

| 状态 | 文件数 | 说明 |
|---|---|---|
| ✅ 新鲜(< 6h) | 5 | scan_snapshot, strategy_states, trading_signals, news_events, weekly_chain |
| ⚠️ 稍旧(6h-7d) | 5 | factor_daily×2, etf_portfolio, daily_report_links, news_score_offset |
| 🔴 过期(>7d) | 7 | macro_raw, macro_engine, news_cache, global_market, chain_candidates, backtest, shadow_account |

**评分: 5/10**（约 41% 文件超过 7 天未更新）

---

## 整体评分

| 维度 | 分数 | 说明 |
|---|---|---|
| **架构设计** | 7.5/10 | 路由模式合理，多源聚合设计好；但有硬编码和扩展性问题 |
| **代码质量** | 6.5/10 | 整体可读性好，但有重复登录、硬编码日期、API 签名不兼容等问题 |
| **测试覆盖** | 2/10 | 未发现单元测试或集成测试 |
| **数据质量** | 5/10 | 新数据时效性好，但约 41% JSON 文件过期；管线核心 Tier 1 损坏 |
| **错误处理** | 5/10 | 多数函数有 try/except，但静默失败较多，无告警机制 |
| **可维护性** | 6/10 | 模块分离清晰但缺少文档和配置化 |
| **时效性** | 5.5/10 | 高频(实时行情)无缓存合理；日级数据 3/5 是新鲜的 |
| **安全性** | 7/10 | 无敏感信息硬编码；pickle 反序列化(潜在风险风险，但仅本地使用) |

### 总分: 5.5/10

### 关键发现

1. **🔴 新闻管线完全断裂**: `akshare.stock_news_em()` API 签名变更导致 Tier 1 全部失败，连锁导致 Tier 2/3 失效
2. **🔴 宏观数据严重过期**: `macro_raw_cache.json`(42天) / `macro_engine_cache.json`(41天) 等关键宏观指标已完全无法反映当前市场状态
3. **⚠️ 缓存膨胀无控制**: 315个 pickle 文件(5.26MB)，无 LRU/大小限制策略
4. **⚠️ 硬编码值多处**: baostock_source.py 中 AKShare fallback 的 end_date 写死 `20260625`；akshare_source.py 中期货映射硬编码
5. **⚠️ 数据冗余**: `etf_universe.py` + `stock_names.py` 中 ETF 名称部分重复
6. **⚠️ 路由潜规则**: A股ETF 优先用 AKShare 而非 baostock 无显式配置化
7. **✅ 实时行情架构良好**: 防限流、超时、多源聚合、交叉验证设计合理

### 建议改进 (按优先级)

1. **修复新闻管线**: 移除 `limit` 参数或改用新 API
2. **刷新宏观数据**: 更新 macro_raw_cache.json + macro_engine_cache.json
3. **添加缓存清理策略**: 按 TTL 自动清理过期 pickle 文件
4. **参数配置化**: 将硬编码的期货映射、日期、路由规则提取到配置
5. **添加 E2E 或集成测试**: 至少覆盖 get_history + get_rt 的完整数据流
6. **统一数据版本**: ETF fallback 的日期参数应动态计算而非硬编码
