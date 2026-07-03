# Dashboard 前端重构方案

> 版本: v2026.07.03 | 状态: Draft | 作者: wenlix

## 文档结构

本文档从现状分析出发，梳理全部组件和数据依赖，对比三种技术方案，给出推荐架构、组件树设计、API 契约、功能补全计划、实施阶段和测试策略。适合需要理解 Dashboard 现状并制定升级路径的开发者阅读。

---

## 一、现状分析

### 1.1 当前架构

Dashboard 的全部代码集中在 `scripts/portfolio_server.py`（1470 行），结构如下：

```
portfolio_server.py
├── 数据层 (L54–178)
│   ├── load_shadow()      — 读取 shadow_account.json
│   ├── build_summary()    — 构建持仓汇总
│   ├── build_history()    — 构建交易记录
│   └── build_chart_data() — 构建净值曲线数据
├── API 路由层 (L182–938)
│   ├── GET /api/portfolio         — 模拟盘数据
│   ├── GET /api/comparison        — 三方策略对比
│   ├── GET /api/signals           — 今日实时信号
│   ├── GET /api/realtime          — 实时行情（全部）
│   ├── GET /api/realtime/positions— 持仓实时行情（轻量）
│   ├── GET /api/metrics           — 绩效指标
│   ├── GET /api/simulated         — 三策略模拟盘
│   ├── GET /api/v2/pool           — 三层票池
│   ├── GET /api/v2/etf            — ETF 组合
│   ├── GET /api/v2/news           — 板块新闻
│   └── GET /api/v2/reports        — 日报链接
├── HTML 页面 (L200–1428，Python 字符串常量)
│   ├── COMPARISON_HTML (L200–381)       — 三方对比独立页
│   ├── DASHBOARD_HTML (L385–664)        — 旧版仪表盘
│   └── UNIFIED_DASHBOARD_HTML (L941–1428)— 统一 7 面板仪表盘（SPA）
└── 页面路由 (L1431–1464)
    ├── GET /, /dashboard → UNIFIED_DASHBOARD_HTML
    ├── GET /comparison    → COMPARISON_HTML
    └── GET /score_explanation → 评分解读
```

三块 HTML 合计约 500 行，包含 CSS-in-`<style>`、内联 JS 和 CDN 引用的 Chart.js。

### 1.2 已具备的能力

| 维度 | 现状 |
|------|------|
| 后端框架 | FastAPI，异步就绪，已有 12 个 REST 端点 |
| UI 框架 | 纯 HTML + Chart.js CDN，无构建步骤 |
| 图表 | 净值曲线折线图、资产分布环形图、三策略对比折线图（共 4 个 Chart.js 实例） |
| 数据刷新 | 60s setInterval 自动刷新 `/api/simulated` |
| 面板 | 7 tab 全部可用：模拟盘、回测对比、票池、ETF、新闻、日报、绩效指标 |
| 暗色主题 | CSS 变量控制的暗色，色值规范 `#0d1117`/`#161b22`/`#30363d` |
| 响应式 | 有 `@media(max-width:900px)` 断点但仅处理栅格布局，未做移动端适配 |
| 交易记录 | 100 条历史记录，买入/卖出标记，盈亏着色 |
| 风控提示 | 止损价触发时显示 🚨 标记 |

### 1.3 核心问题

| 问题 | 严重程度 | 影响 |
|------|---------|------|
| **无关注点分离** | 高 | HTML/CSS/JS/Python 全部混在一个文件里，改 CSS 颜色需要编辑 Python 字符串 |
| **无构建工具链** | 高 | 无 npm/pip 依赖管理、无打包、无压缩、无 HMR |
| **HTML 是 Python 字符串** | 高 | IDE 零支持：无语法高亮、无自动补全、无 lint。`"""` 和变量插值难以维护 |
| **Chart.js CDN 外链** | 中 | 内网部署时不可用，无版本锁定（`@4.4.7` 已固定），但网络依赖仍是风险 |
| **无导出功能** | 中 | 用户无法导出 CSV/Excel/PDF，离线分析不成立 |
| **无交互式筛选** | 中 | 所有表格不可排序、不可搜索、不可分页。日期范围固定，无法指定回溯周期 |
| **无用户鉴权** | 低 | 任何能访问 `:8686` 的人都能看到全部数据 |
| **无告警规则配置** | 中 | 止损阈值硬编码 `entry*0.92`（10 日内）和 `peak*0.88`，无法通过 UI 调整 |
| **无移动端适配** | 中 | 仅有一个断点，手机上表格横向溢出，触摸交互未处理 |
| **Tab 切换不持久** | 低 | 切走再切回要重新 fetch 数据 |
| **无状态缓存层** | 低 | 每次 F5 重新拉全部 API，无前端级缓存 |

---

## 二、组件清单与数据依赖

### 2.1 面板 → API 映射

```
Dashboard 主页 (GET /, /dashboard)
├── [Panel 1] 模拟盘 Tab
│   ├── 三策略总览卡片      ← /api/simulated.portfolios.{faceji|silverquant|tradingagents}
│   ├── 持仓明细表          ← /api/simulated.portfolios.*.positions[]
│   ├── 交易信号表          ← /api/simulated.portfolios.*.signals[]
│   ├── 绩效指标面板        ← /api/metrics (独立加载)
│   └── 用户执行建议        ← /api/simulated.user_signals[]
├── [Panel 2] 回测对比 Tab
│   ├── 三策略对比卡片      ← /api/comparison.{faceji|silverquant|tradingagents}
│   ├── 净值曲线 (Chart.js) ← /api/comparison.*.daily_values[]
│   └── 交易日志表          ← /api/comparison.*.trades[]
├── [Panel 3] 票池 Tab      ← /api/v2/pool.{watch|monitor|deep}[]
│   ├── Watch/Monitor/Deep 三层分别渲染
│   ├── 7 因子评分列        ← items[*].scores.{quality|value|growth|momentum|low_vol|sentiment|risk}
│   └── 产业链标签          ← items[*].chain
├── [Panel 4] ETF Tab       ← /api/v2/etf
│   ├── 趋势跟随组合        ← .timing_portfolio.symbols[]
│   ├── 风险平价组合        ← .non_timing_portfolio.symbols[]
│   └── 合并建议            ← .combined[]
├── [Panel 5] 新闻 Tab      ← /api/v2/news
│   ├── 摘要行              ← .summary, .timestamp
│   └── 分类条目列表        ← .items[] (.category, .content)
├── [Panel 6] 日报 Tab      ← /api/v2/reports
│   └── 日报链接表          ← [].{date|title|link}
├── [Panel 7] 绩效指标 Tab  ← /api/metrics (已嵌入 Panel 1)
└── 实时行情刷新 (轻量)    ← /api/realtime/positions (当前未在 UI 中使用)
```

### 2.2 Chart.js 实例清单

| 图表 | 类型 | Canvas ID | 数据源 | 位置 |
|------|------|-----------|--------|------|
| 净值曲线 | Line | `equityChart` | `/api/portfolio.chart` | DASHBOARD_HTML 面板 |
| 资产分布 | Doughnut | `allocationChart` | `/api/portfolio.summary` | DASHBOARD_HTML 面板 |
| 三策略对比 | Line | `comparisonChart` | `/api/comparison.*.daily_values[]` | COMPARISON_HTML |
| （无 ID） | — | — | （UNIFIED_DASHBOARD_HTML 没有内嵌 Chart.js 图表） | — |

> **注**: UNIFIED_DASHBOARD_HTML 是当前 `/dashboard` 主路由使用的页面，但它移除了图表渲染（仅依赖 Tab 内联渲染表格和策略卡片）。旧 DASHBOARD_HTML 和 COMPARISON_HTML 未在主路由使用。

### 2.3 数据文件依赖

所有数据文件位于 `data/` 目录，通过 JSON 文件与 API 端点桥接：

| 文件 | 读/写 | 更新频率 | API 端点 |
|------|-------|----------|----------|
| `shadow_account.json` | R | 每笔交易后 | `/api/portfolio` |
| `trading_signals.json` | R | 每日收盘后 | `/api/simulated`, `/api/signals` |
| `pool/watch.json` | R | 每日因子扫描后 | `/api/v2/pool` |
| `pool/monitor.json` | R | 同上 | `/api/v2/pool` |
| `pool/deep.json` | R | 同上 | `/api/v2/pool` |
| `etf_portfolio.json` | R | 每次 ETF 计算后 | `/api/v2/etf` |
| `news_cache.json` | R | 新闻管线运行后 | `/api/v2/news` |
| `daily_report_links.json` | R | 日报生成后 | `/api/v2/reports` |

Dashboard 对这些文件只读，写入由后台管线（`run_factor_daily.py`, `portfolio_builder.py`, `news_pipeline.py`）负责。

---

## 三、架构方案对比

### 3.1 方案 A：轻量改进（Jinja2 + 独立静态文件）

**变更范围**：仅拆分 HTML 出 Python 文件，不引入前端框架。

```
portfolio_server.py               ← 只留 FastAPI 路由 + 数据层
templates/
├── base.html                     ← 公共 layout (暗色主题 CSS 变量, nav)
├── dashboard.html                ← 7 面板主页
├── comparison.html               ← 三方对比页
└── score_explanation.html        ← 评分说明（已有独立端点）
static/
├── css/style.css                 ← 从 <style> 提取，约 200 行
├── js/dashboard.js               ← Tab 切换 + 数据加载逻辑，约 400 行
├── js/comparison.js              ← 对比页 JS
└── vendor/chart.min.js           ← Chart.js 本地化，避免 CDN 依赖
```

**代价**：HTML 仍通过 Python 渲染输出，无前端热更新，无组件复用。  
**收益**：关注点分离（CSS/JS/Python 各自独立），IDE 原生支持 HTML/CSS/JS，改动成本极低（约 4h）。  
**适用场景**：只在当前功能集内提升可维护性，暂不增加新交互功能。

### 3.2 方案 B：前后端分离（React/Vue SPA + FastAPI）

**变更范围**：完全重写前端为 SPA，FastAPI 退化为纯数据 API。

```
前端 (React/Vue SPA)
├── src/
│   ├── pages/Dashboard.jsx       ← 7 面板路由
│   ├── components/
│   │   ├── SummaryCards.jsx      ← 总览指标卡
│   │   ├── PortfolioTable.jsx    ← 持仓表格（可排序/筛选）
│   │   ├── EquityChart.jsx       ← ECharts/Recharts 净值曲线
│   │   ├── AllocationChart.jsx   ← 资产分布
│   │   ├── ComparisonChart.jsx   ← 三策略对比
│   │   ├── PoolPanel.jsx         ← 票池三层
│   │   ├── ETFPanel.jsx          ← ETF 组合
│   │   ├── NewsPanel.jsx         ← 新闻列表
│   │   ├── ReportsPanel.jsx      ← 日报链接
│   │   ├── MetricsPanel.jsx      ← 绩效指标
│   │   └── AlertsConfig.jsx      ← 告警规则配置
│   ├── hooks/useApi.js           ← SWR/React Query 数据获取
│   ├── lib/api.js                ← API 客户端封装
│   └── styles/                   ← Tailwind/CSS Modules
├── vite.config.js
└── package.json
```

**代价**：引入 npm 工具链（Vite/Webpack），需要前端工程化知识。SPA 需要处理 CORS、路由、状态管理。  
**收益**：组件复用、热更新、TypeScript 类型安全、移动端响应式网格、导出 CSV/Excel/PDF 有成熟生态。图表库可选 ECharts（中文社区成熟）或 Recharts（React 原生）。  
**适用场景**：需要大量交互式功能，且团队有前端开发人员或愿意花时间学习。

### 3.3 方案 C：混合方案（Keep Python server, React islands）

**变更范围**：保持 FastAPI 不变，仅将交互性强的面板用 React 实现，其余部分沿用方案 A。

```
portfolio_server.py               ← 保持路由不变
templates/
├── base.html                     ← 传统 Jinja2 模板承载整体框架
├── dashboard.html                ← 嵌入 React mount point (<div id="react-root">)
└── static_panels/                ← 不改动的面板（HTML 渲染）
    ├── reports.html
    └── etf.html
frontend/
├── src/
│   ├── index.jsx                 ← React mount + Tab 路由
│   ├── panels/
│   │   ├── PortfolioPanel.jsx    ← 模拟盘 + 持仓表
│   │   ├── ComparisonPanel.jsx   ← 回测对比 + 图表
│   │   ├── PoolPanel.jsx         ← 票池
│   │   ├── NewsPanel.jsx         ← 新闻
│   │   └── MetricsPanel.jsx      ← 绩效指标
│   └── lib/api.js
├── vite.config.js (多入口或 library 模式)
```

**代价**：两套渲染体系共存（Jinja2 + React），打包配置复杂（Vite 需要 library mode 输出到 `static/`）。调试时需要 Python 服务器和 Vite dev server 同时运行。  
**收益**：渐进式迁移，改动量居中。适合"先改最痛的部分，不动其他地方"的思路。  
**适用场景**：有明确的高优先级交互面板需要升级（如持仓表格排序筛选、图表交互），但不想一次重写整个前端。

### 3.4 方案对比矩阵

| 维度 | A: Jinja2 拆分 | B: React/Vue SPA | C: Hybrid |
|------|:---:|:---:|:---:|
| **开发时间（预估）** | 4–8h | 40–80h | 20–40h |
| **前端工程化门槛** | 无 | 高（npm, Vite, JSX, 状态管理） | 中（Vite library mode） |
| **关注点分离** | ✅ 基础分离 | ✅ 完整组件化 | ⚠️ 两套体系 |
| **IDE 支持** | ✅ HTML/CSS/JS 原生 | ✅ JSX + TS 完整 | ⚠️ 混合开发体验 |
| **热更新** | ❌ | ✅ Vite HMR | ⚠️ 仅 React 部分 |
| **移动端适配** | 手动 CSS | ✅ 组件级响应式 | ⚠️ 手动 CSS + 部分组件 |
| **导出功能** | 实现较麻烦 | ✅ 生态成熟 | ✅ 可实现 |
| **CDN 离线化** | ✅ 本地 vendor/ | ✅ 打包内联 | ✅ 打包内联 |
| **团队适配** | ✅ 零学习成本 | 需学习 React 生态 | 需学习 React 基础 |

---

## 四、推荐方案：方案 A（Jinja2 拆分 + 渐进增强）

### 4.1 选择理由

综合团队现状（1 人、无前端开发背景、FastAPI 专家），方案 A 是最务实的选择：

1. **零新工具链**。不引入 npm/pip 新依赖。FastAPI 原生支持 Jinja2 和 StaticFiles，改动是"把已有代码搬到正确的文件里"而非重写。
2. **与现有架构一致**。整个系统已经是 Python 为主，Jinja2 在后端渲染 HTML 是 Python Web 开发的标准模式。
3. **可渐进增强**。拆分完成后，可以在独立 JS 文件中逐步加入交互功能（如表格排序、导出按钮），需要时再局部引入轻量库（如 HTMX、Alpine.js），不必一步跳到 React。
4. **风险最低**。改动是结构性的而非逻辑性的——CSS/JS/Python 各自独立后，功能回归测试只需确认页面渲染一致。

### 4.2 渐进增强路径

方案 A 不是终点，而是一个可持续演进的起点：

```
Phase 1 (本文档)          Phase 2 (后续)             Phase 3 (远期可选)
Jinja2 模板拆分     →     添加交互 JS 库        →    如有需要，按方案 C 局部迁移到 React
独立 CSS/JS 文件            (HTMX / Alpine.js /      (保持模板框架不变，
CDN 离线化                  vanilla JS 表格排序)      mount point 嵌入)
```

### 4.3 技术选型

| 组件 | 选型 | 理由 |
|------|------|------|
| 模板引擎 | Jinja2 | FastAPI 内置，零依赖 |
| CSS | 原始 CSS + CSS Variables | 已有一套可用的暗色变量体系，拆出成独立文件即可 |
| JS | Vanilla JS (ES6+) | 当前逻辑已经是 vanilla，拆出即可，无需引入框架 |
| 图表 | Chart.js (本地化) | 已有 4 个 Chart.js 实例，改为 `static/vendor/` 本地文件 |
| 静态文件 | FastAPI StaticFiles | `app.mount("/static", StaticFiles(directory="static"))` |
| 导出 | 前端 `Blob + URL.createObjectURL` 触发下载 | 纯前端实现，不依赖后端 |
| 表格交互 | SortableJS（可选轻量库） | 5KB gzipped，无框架依赖，支持点击表头排序 |

---

## 五、组件树设计

### 5.1 模板层级

```
templates/
├── base.html                           ← 根模板：<html>, <head>, CSS 引入, 页脚, JS 引入
│   └── (定义 Jinja2 block: title, head_extra, content, scripts_extra)
│
├── dashboard.html                      ← extends base.html (当前主路由 /dashboard)
│   ├── 顶部信息栏 (日期 + 模拟交易笔数)
│   ├── 三策略总览网格 (.grid-3)
│   │   ├── 面基策略卡片
│   │   │   ├── 收益率大数值
│   │   │   ├── 总资产/现金/已投/仓位 指标行
│   │   │   ├── 持仓明细表 (可滚动)
│   │   │   └── 今日信号表 (可滚动)
│   │   ├── SilverQuant 策略卡片   (同上结构)
│   │   └── TradingAgents 策略卡片  (同上结构)
│   ├── 绩效指标面板 (8 指标网格)
│   ├── 用户执行建议 (条件渲染)
│   ├── [Tab 面板: 回测对比/票池/ETF/新闻/日报]  ← 初始 display:none
│   └── Tab 切换导航 (.nav)
│
├── comparison.html                     ← extends base.html (路由 /comparison, 保留旧页面)
│   ├── 策略对比卡片 ×3
│   ├── 净值曲线对比图 <canvas id="comparisonChart">
│   └── 交易日志 ×3
│
└── score_explanation.html              ← extends base.html (路由 /score_explanation)
    └── 评分体系 Markdown 渲染在 <pre> 中
```

### 5.2 静态资源结构

```
static/
├── css/
│   └── dashboard.css                   ← 所有暗色主题变量 + 布局 + 组件样式
├── js/
│   ├── api.js                          ← API 客户端封装 (fetch wrapper + error handling)
│   ├── dashboard.js                    ← 主导面板: 策略卡片渲染 + Tab 切换 + 自动刷新
│   ├── comparison.js                   ← 对比页: 策略卡片 + Chart.js 三线图
│   ├── pool.js                         ← 票池面板数据加载
│   ├── etf.js                          ← ETF 面板数据加载
│   ├── news.js                         ← 新闻面板数据加载
│   ├── reports.js                      ← 日报面板数据加载
│   ├── metrics.js                      ← 绩效指标独立加载
│   ├── charts.js                       ← Chart.js 初始化 + 主题配置 (共享)
│   ├── export.js                       ← CSV/Excel 导出工具函数
│   └── utils.js                        ← fmt/fmtNum/fmtPct/日期格式化 等共享工具
└── vendor/
    └── chart.umd.min.js                ← Chart.js 4.4.7 UMD 构建，本地化
```

### 5.3 JS 模块职责

| 文件 | 导出/全局 | 职责 |
|------|-----------|------|
| `utils.js` | `fmt(val)`, `fmtNum(val)`, `fmtPct(val)`, `formatDate(str)` | 数字/百分比格式化 |
| `api.js` | `fetchJSON(url)`, `fetchWithRetry(url, retries)` | 统一 fetch 封装，错误处理，重试 |
| `charts.js` | `createLineChart(canvasId, config)`, `createDonutChart(...)`, `chartTheme` | Chart.js 封装，暗色主题默认值 |
| `dashboard.js` | `renderStrategyCards(data)`, `switchTab(tab)`, `startAutoRefresh(intervalMs)` | 主页入口逻辑 |
| `export.js` | `exportTableToCSV(tableEl, filename)`, `exportJSONToCSV(data, columns, filename)` | CSV 生成 + Blob 下载触发 |

---

## 六、API 契约文档

### 6.1 通用约定

- Base URL: `http://<host>:8686`
- 所有响应为 `application/json`，字符集 UTF-8
- 时间格式: `YYYY-MM-DD HH:MM:SS` 或 `YYYY-MM-DD`
- 金额单位: 人民币元，浮点数（保留 2 位小数）
- 错误响应格式: `{"error": "描述信息"}`
- 无分页（当前所有列表 < 200 条）。如需分页，增加 `?limit=N&offset=M` 参数

### 6.2 端点详细契约

#### `GET /api/simulated`

三策略模拟盘全方位数据。

**Response 200**:
```json
{
  "date": "2026-07-03",
  "generated_at": "2026-07-03 18:16:37",
  "simulated_trades": 8,
  "portfolios": {
    "faceji": {                               // 同结构 silverquant, tradingagents
      "label": "面基",
      "color": "#58a6ff",
      "style": "面基(评分+趋势+Kelly+SQ风控)",
      "cash": 970000.00,
      "invested": 30000.00,
      "total_value": 1000000.00,
      "total_pnl": 0.00,
      "total_return": 0.00,
      "position_count": 3,
      "history_count": 12,
      "positions": [{
        "symbol": "300502",                   // string, 股票代码
        "name": "新易盛",                     // string, 中文简称
        "entry_price": 98.60,                // number, 建仓价
        "current_price": 99.20,              // number, 最新价
        "quantity": 300,                     // number, 股数
        "cost": 29580.00,                    // number, 成本 = entry_price * quantity
        "market_value": 29760.00,            // number, 市值 = current_price * quantity
        "pnl": 180.00,                       // number, 浮动盈亏
        "pnl_pct": 0.61,                     // number, 盈亏百分比
        "entry_date": "2026-06-28",          // string, YYYY-MM-DD
        "reason": "建仓评分6.5分",            // string, 建仓理由
        "stop_loss": 90.70,                  // number, 止损价
        "peak_price": 101.50                 // number, 历史峰值
      }],
      "signals": [{                          // 今日生成的交易信号
        "action": "BUY",                     // "BUY" | "SELL" | "HOLD"
        "symbol": "300502",
        "price": 99.20,
        "reason": "评分0.61, 趋势向上, Kelly建议6%"
      }]
    }
  },
  "user_signals": [{                         // 高优先级执行建议
    "priority": "HIGH",                      // "HIGH" | "MED" | "LOW"
    "action": "BUY",
    "symbol": "300502",
    "name": "新易盛",
    "price": 99.20,
    "reason": "三策略共识买入"
  }]
}
```

#### `GET /api/portfolio`

个人模拟盘数据（旧版端点，包含旧 DASHBOARD_HTML 使用的 `chart` 和 `history`）。

**Response 200**:
```json
{
  "summary": {
    "capital": 1000000.00,                   // 初始本金
    "cash": 950000.00,                       // 可用现金
    "position_value": 50000.00,              // 持仓总市值
    "total_value": 1000000.00,               // 总资产 = cash + position_value
    "position_count": 2,                     // 持仓标的数
    "total_invested": 48000.00,              // 总投入成本
    "unrealized_pnl": 2000.00,               // 浮动盈亏
    "realized_pnl": 1500.00,                 // 已实现盈亏
    "total_pnl": 3500.00,                    // 总盈亏
    "total_return": 0.35,                    // 总收益率 (百分比)
    "cash_pct": 95.0,                        // 现金占比
    "position_pct": 5.0,                     // 持仓占比
    "positions": [{                          // 同 simulated 的 positions 结构
      "symbol": "...",
      "entry_price": 0, "current_price": 0, "quantity": 0,
      "pnl": 0, "pnl_pct": 0, "hold_days": 0,
      "entry_score": 6.5, "stop_loss": 0,
      "dd_from_peak": -1.2
    }]
  },
  "chart": {
    "labels": ["2026-06-01", "2026-06-02", ...],  // string[], 日期
    "values": [1000000, 1000500, ...],             // number[], 总资产
    "return_pct": 0.35                             // number, 总收益率
  },
  "history": [{                                    // 交易记录，倒序
    "time": "2026-06-28 14:35:00",                // string, 交易时间
    "symbol": "300502",
    "name": "新易盛",
    "action": "买入",                              // "买入" | "卖出" | "加仓"
    "price": 98.60,
    "quantity": 300,
    "reason": "建仓评分6.5分, 趋势向上",
    "cost": 29580.00,
    "pnl": null,                                   // number|null (买入时为 null)
    "pnl_str": "",                                 // string, 格式化盈亏
    "is_win": null                                 // boolean|null
  }],
  "updated_at": "2026-07-03 09:30",
  "history_count": 15
}
```

#### `GET /api/comparison`

三方策略回测对比。

**Response 200**:
```json
{
  "run_date": "2026-07-03",
  "days_analyzed": 60,
  "note": "⚠️ 示例数据",
  "faceji": {                                  // 同结构 silverquant, tradingagents
    "name": "faceji (面基)",
    "cash": 950000.00,
    "value": 1042000.00,
    "total_return_pct": 4.2,
    "realized_pnl": 15000.00,
    "unrealized_pnl": 27000.00,
    "positions": 5,
    "total_trades": 12,
    "win_rate": 58.3,
    "max_drawdown_pct": 3.5,
    "trades": [{
      "date": "2026-07-01",                    // string, YYYY-MM-DD
      "time": "2026-07-01 10:00:00",           // string (可选)
      "symbol": "300750",
      "action": "买入",
      "price": 185.50,
      "pnl": null,
      "reason": "..."
    }],
    "daily_values": [{                          // 净值序列数据
      "date": "2026-06-02",
      "value": 1000000.00
    }]
  }
}
```

#### `GET /api/metrics`

绩效指标。

**Response 200**:
```json
{
  "sharpe_ratio": 1.2345,
  "sortino_ratio": 2.1000,
  "max_drawdown_pct": 5.23,
  "total_return_pct": 3.45,
  "annualized_return_pct": 3.45,
  "win_rate_pct": 58.3,
  "total_trades": 12,
  "max_win_streak": 4,
  "max_loss_streak": 2,
  "position_count": 3,
  "capital": 1000000.00,
  "total_value": 1034500.00
}
```

#### `GET /api/v2/pool`

三层票池。

**Response 200**:
```json
{
  "watch": [{
    "symbol": "300502",
    "name": "新易盛",
    "score": 0.607,
    "chain": "AI算力-光模块",
    "scores": {
      "quality": 0.65, "value": 0.55, "growth": 0.72,
      "momentum": 0.58, "low_vol": 0.40, "sentiment": 0.62, "risk": 0.70
    },
    "date_added": "2026-06-28",
    "reason": "综合评分达标, 光模块产业链景气"
  }],
  "monitor": [ /* 同上结构，评分 > 0.55 且加入 ≥ 1 周 */ ],
  "deep": [    /* 同上结构，评分 > 0.60 且加入 ≥ 2 周 + 不为清单通过 */ ]
}
```

#### `GET /api/v2/etf`

ETF 组合建议。

**Response 200**:
```json
{
  "timestamp": "2026-07-03",
  "timing_portfolio": {
    "symbols": [{
      "etf_symbol": "510050",
      "name": "上证50ETF",
      "action": "BUY",
      "weight": 0.30,
      "signal_type": "MA20趋势跟随",
      "reason": "价格上穿 MA20, 均线多头排列"
    }]
  },
  "non_timing_portfolio": {
    "symbols": [ /* 同上结构，action 可能为 HOLD */ ]
  },
  "combined": [ /* 同上结构 */ ]
}
```

#### `GET /api/v2/news`

板块新闻。

**Response 200**:
```json
{
  "total": 24,
  "timestamp": "2026-07-03T08:31:15",
  "summary": "共抓取 20 条新闻 · 市场动态类10条 · 宏观政策类4条...",
  "items": [
    {"category": "宏观政策", "content": "央行宣布LPR下调10bp至3.45%..."},
    {"category": "市场动态", "content": "A股三大指数集体高开..."}
  ]
}
```

#### `GET /api/v2/reports`

日报链接列表。

**Response 200**:
```json
[
  {"date": "2026-07-03", "title": "面基日报", "link": "https://..."},
  {"date": "2026-07-02", "title": "面基日报", "link": "https://..."}
]
```

#### `GET /api/realtime/positions`

持仓实时行情（轻量，仅返回持仓标的）。

**Response 200**:
```json
{
  "realtime": {
    "300502": {"price": 99.20, "change_pct": 1.23, "name": "新易盛"},
    "NVDA":   {"price": 145.30, "change_pct": -0.50, "name": "NVIDIA"}
  },
  "updated_at": "2026-07-03 09:35:00"
}
```

---

## 七、功能补全计划

### 7.1 列表总览

| 功能 | 优先级 | 预估工时 | 依赖组件 |
|------|:---:|------|------|
| CSV/Excel 导出按钮 | P0 | 2h | `static/js/export.js` |
| 日期范围筛选（回测/历史） | P1 | 4h | `<input type="date">` + API 参数 |
| 移动端响应式布局 | P1 | 6h | CSS Grid 断点 + 触摸优化 |
| 暗色/亮色主题切换 | P2 | 3h | CSS Variables 切换 + localStorage |
| 告警规则配置面板 | P1 | 5h | 新页面 + `/api/alerts` 端点 |
| 表格排序（点击表头） | P2 | 2h | 引入 SortableJS 或 vanilla 实现 |
| Tab 状态缓存（切换不回源） | P2 | 2h | JS 内存缓存 |
| 前端级数据缓存 (SWR) | P2 | 3h | `sessionStorage` + 时间戳校验 |
| 用户鉴权 | P3 | 8h | FastAPI Auth middleware + Login 页 |
| PDF 报告导出 | P3 | 4h | 前端 html2canvas + jsPDF 或后端 WeasyPrint |

### 7.2 详细设计

#### 7.2.1 CSV/Excel 导出

**实现方案**：纯前端，不增加后端端点。

```javascript
// static/js/export.js
function exportTableToCSV(tableElement, filename) {
  const rows = tableElement.querySelectorAll('tr');
  const csv = Array.from(rows).map(row =>
    Array.from(row.querySelectorAll('th,td'))
      .map(cell => `"${cell.textContent.replace(/"/g, '""')}"`)
      .join(',')
  ).join('\n');
  const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' }); // BOM for Excel
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
```

在每个表格上方增加 `<button class="export-btn">↓ CSV</button>`，绑定 `onclick`。

#### 7.2.2 日期范围筛选

**API 扩展**：为 `/api/portfolio` 和 `/api/comparison` 增加可选查询参数。

```
GET /api/portfolio?start=2026-06-01&end=2026-07-03
GET /api/comparison?days=90                          ← 替代硬编码的 60 天
```

**前端实现**：在回测对比面板和时间线卡片上方增加 `<input type="date">` 起止日期控件，change 事件重新 fetch。

#### 7.2.3 告警规则配置

**新增端点**：`GET/PUT /api/alerts/config`

```json
{
  "rules": {
    "stop_loss_early": 0.92,          // 建仓 10 日内止损比例 (entry * 0.92)
    "stop_loss_late":  0.88,          // 建仓 10 日后止损比例 (peak * 0.88)
    "hard_sell_threshold": -8.0,      // 硬止损百分比
    "score_drop_threshold": -0.15,    // 评分下降触发阈值
    "ma_sell_window": 20,             // MA 均线卖出窗口
    "notification_enabled": false     // 是否启用通知（预留）
  }
}
```

配置文件路径: `data/alerts_config.json`。首次调用时自动创建默认值。  
前端：新增 `/alerts` 页面路由，表单 + 保存按钮。

#### 7.2.4 移动端响应式布局

关键改动：

```css
/* 基础断点 */
@media (max-width: 768px) {
  .grid-3, .grid-2 { grid-template-columns: 1fr; }
  .card { padding: 12px; }
  /* 表格横向滚动 */
  .table-wrapper { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  /* 指标大数值缩小 */
  .metric-value { font-size: 22px; }
  /* Tab 导航改为横向滚动 */
  .nav { overflow-x: auto; white-space: nowrap; flex-wrap: nowrap; }
}
```

策略卡片在手机上改为纵向堆叠。持仓明细表每行列数从 11 列压缩到核心 5 列（标的、现价、盈亏、收益率、止损），其余字段折叠到详情行（点击展开）。

#### 7.2.5 暗色/亮色主题切换

利用 CSS Variables 体系（已定义 `--bg`, `--card`, `--text` 等变量）。在 `<html>` 上 toggling `data-theme="light"`，CSS 覆盖变量：

```css
[data-theme="light"] {
  --bg: #ffffff;
  --card: #f6f8fa;
  --border: #d0d7de;
  --text: #1f2328;
  --text2: #656d76;
}
```

切换按钮放在右上角，状态存入 `localStorage`。

---

## 八、实施阶段与里程碑

### Phase 0: 基础设施准备 (2h)

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 创建 `templates/`, `static/` 目录结构 | 骨架目录 | `ls -R` 与设计的目录一致 |
| 安装 Jinja2（如未安装） | `pip install jinja2` | `import jinja2` 成功 |
| 下载 Chart.js 到 `static/vendor/` | `static/vendor/chart.umd.min.js` | 文件存在且 checksum 匹配 4.4.7 |
| 在 `portfolio_server.py` 中配置 `StaticFiles` | `app.mount("/static", ...)` | `GET /static/css/dashboard.css` 返回 200 |

### Phase 1: CSS 提取 (3h)

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 从 3 个 HTML 字符串中提取所有 `<style>` 内容 | `static/css/dashboard.css` | CSS 行数 ≈ 原有总和 |
| 去重 CSS 变量定义（目前 3 个 HTML 各自定义了一份） | 统一的 `:root` 块 | 仅一份 `:root` 定义 |
| 统一 class 命名冲突（部分 class 在不同 HTML 中定义不同） | 合并后无冲突 | 视觉回归测试通过 |
| 创建 `base.html` 模板 | `templates/base.html` | 包含 CSS 引入 + 公共 `<head>` + `{% block %}` |

### Phase 2: HTML → Jinja2 模板转换 (4h)

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 将 `UNIFIED_DASHBOARD_HTML` 转为 `dashboard.html` | `templates/dashboard.html` | 视觉与当前 `/dashboard` 完全一致 |
| 将 `COMPARISON_HTML` 转为 `comparison.html` | `templates/comparison.html` | 视觉与当前 `/comparison` 完全一致 |
| 修改路由返回 `TemplateResponse` | `return templates.TemplateResponse(...)` | 页面正常渲染 |
| 删除 Python 中的 HTML 字符串常量 | `portfolio_server.py` 行数从 1470 降至约 550 | 无残留 HTML 字符串 |

### Phase 3: JS 提取与模块化 (5h)

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| 提取工具函数到 `utils.js` | `fmt/fmtNum/fmtPct` | 浏览器 console 可调用 |
| 提取 API 封装到 `api.js` | `fetchJSON()` | 所有面板 fetch 改为调用该封装 |
| 提取图表逻辑到 `charts.js` | `createLineChart/createDonutChart` | Chart.js 图表正常渲染 |
| 拆分面板 JS 各自独立 | `pool.js/etf.js/news.js/reports.js` | Tab 切换时按需 `<script>` 动态加载或统一加载 |
| 主入口 JS `dashboard.js` | Tab 切换 + 自动刷新 | 60s 刷新正常，Tab 切换正常 |
| Chart.js CDN 引用改为本地 | `<script src="/static/vendor/chart.umd.min.js">` | 断网后页面图表仍渲染 |

### Phase 4: 功能补全 (16h)

| 任务 | 优先级 | 预估 |
|------|:---:|------|
| CSV 导出按钮（持仓表 + 交易记录表 + 票池表） | P0 | 2h |
| 日期范围筛选（回测面板 + 历史记录） | P1 | 4h |
| 告警规则配置面板 + `/api/alerts/config` 端点 | P1 | 5h |
| 移动端响应式优化 | P1 | 6h |
| 暗色/亮色主题切换 | P2 | 3h |
| 表格点击表头排序 | P2 | 2h |

### Phase 5: 测试与收尾 (4h)

| 任务 | 产出 | 验收标准 |
|------|------|----------|
| API 契约测试 | `tests/test_api.py` | 所有 12 个端点返回 200 且 schema 一致 |
| 视觉回归测试 | 截图前后对比 | 7 面板渲染无偏移/缺失 |
| 文档更新 | 更新 `docs/API.md` | 反映新增端点 |
| `CHANGELOG.md` 记录 | 变更条目 | Phase 1–5 完成标记 |

### 总工时预估

| Phase | 预估 | 累计 |
|-------|------|------|
| P0 基础设施 | 2h | 2h |
| P1 CSS 提取 | 3h | 5h |
| P2 Jinja2 转换 | 4h | 9h |
| P3 JS 模块化 | 5h | 14h |
| P4 功能补全 | 16h | 30h |
| P5 测试收尾 | 4h | 34h |
| **合计** | **34h** | — |

约 4–5 个工作日（按每日 7h 有效工时计算）。

---

## 九、测试策略

### 9.1 API 契约测试

测试框架: `pytest` + `httpx`（FastAPI 推荐）。目标: 12 个端点全部覆盖。

```python
# tests/test_api.py
import pytest
from httpx import AsyncClient
from scripts.portfolio_server import app

@pytest.mark.anyio
async def test_api_simulated():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/simulated")
        assert resp.status_code == 200
        data = resp.json()
        assert "portfolios" in data
        assert "faceji" in data["portfolios"]
        assert "total_value" in data["portfolios"]["faceji"]

@pytest.mark.anyio
async def test_api_pool():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/v2/pool")
        assert resp.status_code == 200
        data = resp.json()
        for tier in ("watch", "monitor", "deep"):
            assert tier in data
            assert isinstance(data[tier], list)

@pytest.mark.anyio
async def test_api_metrics():
    async with AsyncClient(app=app, base_url="http://test") as client:
        resp = await client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        required = ["sharpe_ratio", "sortino_ratio", "max_drawdown_pct",
                     "total_return_pct", "win_rate_pct", "total_trades"]
        for key in required:
            assert key in data
```

### 9.2 视觉回归测试

使用 Playwright 截图前后对比。在 Phase 5 执行：

```bash
# 启动服务器
uvicorn scripts.portfolio_server:app --port 8686 &

# 截图所有面板
npx playwright screenshot http://localhost:8686/dashboard dashboard-before.png
npx playwright screenshot http://localhost:8686/comparison comparison-before.png

# 部署重构后版本，重新截图，用 image-diff 对比
npx image-diff dashboard-before.png dashboard-after.png --threshold 0.01
```

> 如无 Playwright，也可手动在浏览器中截取 7 个面板，目视对比。重点验证：策略卡片颜色、暗色主题变量一致、表格数据正确、图表曲线形状一致。

### 9.3 功能测试清单

| 测试项 | 方法 | 预期 |
|--------|------|------|
| 策略卡片收益率颜色 | 正收益绿色，负收益红色 | UI 颜色符合 `var(--green)`/`var(--red)` |
| 60s 自动刷新 | 打开页面，等 60s，检查 Network tab | 再次 fetch `/api/simulated` |
| Tab 切换无刷新 | 切换 7 个 Tab | URL 不变，内容正确切换 |
| CSV 导出 | 点击导出按钮 | 浏览器下载 `.csv`，Excel 正确打开，中文不乱码 |
| 日期筛选 | 选择起止日期，点击应用 | 仅显示范围内的交易记录 |
| 移动端 | Chrome DevTools 切到 iPhone 14 | 无横向溢出，表格可滚动，Tab 导航可左右滑 |
| 暗色切换 | 点击主题按钮 | 页面切换亮色，刷新后保持 |
| 断网图表 | 关闭 CDN 访问 (或改 hosts 阻断 cdn.jsdelivr.net) | Chart.js 图表正常渲染（本地 vendor） |
| 止损告警 | 设置持仓现价低于止损价 | 🚨 标记显示 |

---

## 十、附录

### 10.1 当前文件行数统计

| 部分 | 行号范围 | 行数 |
|------|----------|------|
| 导入 + 数据映射 | L1–48 | 48 |
| FastAPI 初始化 | L50 | 1 |
| 数据层 | L54–178 | 125 |
| COMPARISON_HTML | L200–381 | 181 |
| DASHBOARD_HTML | L385–664 | 280 |
| API 路由 (Python) | L667–938 | 272 |
| UNIFIED_DASHBOARD_HTML | L941–1428 | 488 |
| 页面路由 | L1431–1464 | 34 |
| `__main__` | L1467–1470 | 4 |
| **总计** | — | **1470** |

重构后预期：`portfolio_server.py` ~550 行（纯 Python），`templates/` ~500 行（HTML），`static/css/` ~200 行，`static/js/` ~500 行。

### 10.2 相关文档

- [ARCHITECTURE.md](../ARCHITECTURE.md) — 系统架构总览
- [API.md](../API.md) — 当前 API 端点参考
- [README.md](../../README.md) — 项目入口
- [WORKFLOW.md](../WORKFLOW.md) — 开发工作流

### 10.3 参考资源

- [Jinja2 Template Designer Documentation](https://jinja.palletsprojects.com/en/stable/templates/) — 模板语法参考
- [Chart.js v4 Documentation](https://www.chartjs.org/docs/4.x/) — 当前使用的图表库文档
- [FastAPI Static Files](https://fastapi.tiangolo.com/tutorial/static-files/) — 静态文件挂载指南
- [FastAPI Templates](https://fastapi.tiangolo.com/advanced/templates/) — Jinja2 集成指南
