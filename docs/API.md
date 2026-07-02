# 面基投资系统 · API 端点参考

> 版本: v2026.07.02 | Base URL: `http://<host>:8686`

## 一、页面路由

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 自动重定向到 /dashboard |
| `/dashboard` | GET | 主数据面板（7 tab: 模拟盘/回测对比/票池/ETF/新闻/日报） |
| `/comparison` | GET | 三方对比独立页面（旧版，内嵌 tab 优先） |
| `/score_explanation` | GET | 7因子评分体系说明 |

## 二、数据 API

### 模拟盘 (`/api/simulated`)

三策略全方位数据：
```json
{
  "date": "2026-07-02",
  "generated_at": "2026-07-02 18:16:37",
  "simulated_trades": 8,
  "portfolios": {
    "faceji": {
      "label": "面基", "color": "#58a6ff",
      "style": "面基(评分+趋势+Kelly+SQ风控)",
      "cash": 970000.00, "invested": 30000.00,
      "total_value": 1000000.00, "total_return": -0.99,
      "position_count": 3,
      "positions": [
        {"symbol":"300502","name":"新易盛","entry_price":98.60,"current_price":99.20,"quantity":300,...}
      ],
      "signals": [...]
    },
    "silverquant": {...},
    "tradingagents": {...}
  },
  "user_signals": [...]
}
```

### 绩效指标 (`/api/metrics`)

```json
{
  "sharpe_ratio": 0.0000, "sortino_ratio": 0.0000,
  "max_drawdown_pct": 0.00, "total_return_pct": 0.00,
  "win_rate_pct": 0, "total_trades": 0,
  "max_win_streak": 0, "max_loss_streak": 0,
  "position_count": 0, "capital": 1000000, "total_value": 1000000
}
```

### 三方对比 (`/api/comparison`)

```json
{
  "run_date": "2026-07-02",
  "days_analyzed": 0,
  "note": "⚠️ 示例数据（未找到历史扫描快照）",
  "faceji": {
    "name": "faceji (面基)",
    "value": 1042000.00, "total_return_pct": 4.2,
    "total_trades": 12, "win_rate": 50.0,
    "trades": [{"date":"2026-07-01","symbol":"300750","action":"买入","price":185.50,...}],
    "daily_values": [{"date":"2026-06-02","value":1000000.00},...]
  },
  "silverquant": {...},
  "tradingagents": {...}
}
```

### 三层票池 (`/api/v2/pool`)

```json
{
  "watch": [{"symbol":"300502","name":"新易盛","score":0.607,"chain":"AI算力-光模块","scores":{...}},...],
  "monitor": [...],
  "deep": [...]
}
```

### ETF 组合 (`/api/v2/etf`)

```json
{
  "timestamp": "2026-07-02",
  "timing_portfolio": {"symbols": [...]},
  "non_timing_portfolio": {"symbols": [...]},
  "combined": [...]
}
```

### 新闻 (`/api/v2/news`)

```json
{
  "total": 24,
  "timestamp": "2026-05-25T08:31:15",
  "summary": "共抓取 20 条新闻 · 市场动态类10条...",
  "items": [
    {"category": "宏观政策", "content": "央行...", ...}
  ]
}
```

### 日报链接 (`/api/v2/reports`)

```json
[
  {"date": "2026-07-02", "title": "日报", "link": "https://..."}
]
```

## 三、数据文件

| 文件 | 路径 | 用途 |
|------|------|------|
| 模拟盘持仓 | `data/shadow_account.json` | 模拟盘账户数据 |
| 交易信号 | `data/trading_signals.json` | 三策略信号 + 模拟盘汇总 |
| 三层票池 | `data/pool/watch.json` | 发现层 |
| | `data/pool/monitor.json` | 盯住层 |
| | `data/pool/deep.json` | 深度层 |
| 因子快照 | `data/scan_snapshot_YYYY-MM-DD.json` | 每日因子扫描历史 |
| ETF组合 | `data/etf_portfolio.json` | ETF 推荐组合 |
| 新闻缓存 | `data/news_cache.json` | AKShare + GLM 新闻 |
| 日报链接 | `data/daily_report_links.json` | 日报链接列表 |

## 四、相关文档

- [ARCHITECTURE.md](ARCHITECTURE.md) — 系统架构
- [README.md](../README.md) — 项目入口
