# 架构改造记录 — v2026.07.08

> 从单文件 Dashboard 到模块化投资系统，一次完整的架构升级。

## 改造动因

改造前系统存在五大问题：

1. **代码混成一团**：`scripts/portfolio_server.py` 2777 行包含所有 API + 3 个 HTML 模板，`analysis/` 40 个文件从因子引擎到 ETF 回测到死代码混在一起
2. **Dashboard 能力空洞**：模拟盘无独立引擎、回测显示"数据积累中"、票池看不到因子明细、新闻全是过期 RSS
3. **没有发现机制**：ETF 只用固定 8 只、票池只看 WATCHLIST，没有全市场扫描、龙虎榜、中美脱钩比较优势
4. **目录混乱**：根目录散落 `.md` 和 `.py`，`backup_*/`、`_archive/`、`plans/`、`report/` 到处堆放
5. **没有架构纪律**：新增代码随意放置，没有目录分类规则，未来必然再次失控

## 改造内容

### 1. 模块化拆分

| 模块 | 文件数 | 来源 | 职责 |
|------|--------|------|------|
| `dashboard/` | 14 | `portfolio_server.py` 拆分 | FastAPI 43 端点，7 个 `api_*.py` |
| `engine/` | 17 | 从 `analysis/` 提取 | 因子引擎 + 回测 + 宏观 + 评估器 |
| `etf/` | 6 | 新建 + 从 `analysis/` 提取 | ETF 全市场扫描 + 多因子评分 + 六层过滤 |
| `research/` | 10 | 新建 + 从 `analysis/` 提取 | 深度研报 + 龙虎榜 + 产业链 + 脱钩发现 |
| `trading/` | 6 | 新建 | PaperTradingEngine（PaperAccount + T+1 + 费用） |
| `news/` | 4 | 新建 | 多源新闻管道（东财/财联社/巨潮 + cnsenti） |
| `analysis/` | 34 | 保留（桥接） | thin re-export 向后兼容 |
| `_archive/` | 16 | 从各处收集 | 废弃文件归档 |

### 2. 新增能力

**票池 + ETF 发现引擎**：
- ETF：AKShare 全市场 1537 只扫描，按动量/趋势/流动性/波动率/费率 5 因子评分，6 层过滤（消融分析验证年化 15.62%），跨类别动态池构建 + 全空避险（国债 511010）
- 美股/港股 ETF 池供跨境对冲
- 19 子因子分解（quality:roe/gross_margin/debt_ratio 等）从 PoolManager 输出到 Dashboard 雷达图
- 中美脱钩比较优势：15 个技术域映射，中国优势/追赶/美国优势自动发现受益标的

**新闻管道**：
- Google RSS → 东方财富个股新闻 + 7×24 快讯 + 财联社电报
- cnsenti 中文金融情感词典（40+ 关键词）→ sentiment/score
- 缓存 30 分钟，189 条/次，4 源覆盖

**回测统一**：
- `BacktestResult` dataclass 统一 3 套引擎输出
- Dashboard 净值曲线（Chart.js）+ 三阶段进度条 + 6 指标卡片

**模拟盘引擎**：
- `PaperAccount` + `Position`（total/available/frozen_quantity）+ `Order`
- T+1 约束 + 涨跌停 ±10%/±20% + 佣金万 2.5 + 印花税千 0.5 + 过户费
- 按价格分层滑点（≥100 元 8bp / ≥15 元 15bp / <15 元 30bp）

**龙虎榜**：
- AKShare 每日 91 条上榜数据 + 席位明细
- 14 位知名游资追踪（章盟主/赵老哥/方新侠/炒股养家/小鳄鱼/孙哥 等）
- WATCHLIST 交集高亮

**深度研报**：
- `DeepResearchGenerator`：聚合 120 天价格/MA/RSI/MACD + 因子评分 + 新闻情绪
- GLM-4-Flash 生成 8 段结构化研报（公司概况/财务/估值/技术/资金/情绪/风险/建议）
- Dashboard Modal 展示

### 3. 根目录清理

| 操作 | 文件/目录 |
|------|----------|
| 移入 `docs/` | `gap_analysis_report.md`, `data_pipeline_audit_report.md`, `HERMES_CRON_CONFIG.md`, `MIGRATION.md` |
| 移入 `.agents/` | `skills-lock.json` |
| 移入 `_archive/` | `plans/`, `report/` |
| 删除 | `temp_fix.py`, `backup_20260525_115538/`, `investment_system/` |

### 4. 向后兼容

所有从 `analysis/` 移出的文件在原路径保留 **bridge re-export**：
```python
# Bridge — this module has moved to engine/X.py
from engine.X import *
```

外部导入（`scripts/run_daily.py`、`output/report_v6.py` 等）更新到新路径，但旧路径通过 bridge 仍可用。

## 改造统计

| 指标 | 改造前 | 改造后 |
|------|--------|--------|
| 总文件数 | ~100 | 158 |
| 新文件 | — | 34 |
| 修改文件 | — | 17 |
| 删除/归档 | — | 19 |
| Dashboard 端点 | 36 | 43 |
| 最大单文件 | 2777 行 | 1019 行 |
| 废弃文件 | 散落各处 | 集中于 `_archive/` |

## 已知需 ECS 配置项

以下模块代码已完成，需在 ECS 服务器上运行一次数据生成脚本：

| 模块 | 脚本 | 依赖 |
|------|------|------|
| ETF 发现 | `python3 scripts/run_etf_discovery.py` | baostock/yfinance |
| 深度研报 | `python3 scripts/run_deep_research.py` | `ARK_API_KEY` 环境变量 |
| 龙虎榜 | `python3 scripts/run_dragon_tiger.py` | AKShare（本地已验证） |
| 新闻管道 | `python3 scripts/run_news_pipeline.py` | 无额外依赖（本地已验证） |
