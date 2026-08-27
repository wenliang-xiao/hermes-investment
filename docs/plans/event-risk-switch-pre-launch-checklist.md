# 事件风险开关 · 上线前 Checklist

> 2026-08-27 · 分支 `feat/event-risk-switch`（已 push origin）
>
> 本文档记录「事件风险开关（Event Risk Switch）」上线前需要补齐 / 验证的事项，
> 分为两类：**执行中发现的 backlog**（2 项）与**受本地环境限制的验证**（3 处）。

## 背景

事件风险开关已完成 WS0–WS5 + 3 处功能缺失补齐（接入决策层、A股映射链、避险版损益对比），
核心纯函数层有单测覆盖（148 passed + 2 skipped），但存在 2 项执行中发现的 backlog 和
3 处受本地环境限制未完成的验证。本文档作为上线前的 checklist。

---

## 一、执行中发现的 backlog（2 项）

### 1. akshare「预约披露时间」接口解析 bug

- **位置**：akshare `stock_yysj_em`（东财-预约披露时间）
- **问题**：
  - `stock_yysj_em(date='20260630')` 报 `ValueError: Length mismatch`（akshare 1.18.64 与东财页面列数不匹配）
  - `stock_yysj_em(date='20260930')`（未来三季报）返回 `None`（东财数据未生成）
- **影响**：无法获取 A 股「真·未来财报日程」，当前事件日历仅靠手工 json + yfinance earnings_dates
- **修复方向**：修 akshare 解析（对齐东财页面列数），或改用 `stock_report_disclosure`（巨潮预约披露，period 格式需确认）
- **优先级**：P2（解锁 A 股前瞻财报日程；手工 json 已兜底，不阻塞）

### 2. `get_market_moves` 的 yfinance 限频加固

- **位置**：`engine/event_risk_engine.py` 的 `get_market_moves()`
- **问题**：当前用裸 `try/except` 静默降级，遇到 `YFRateLimitError` 直接跳过，未复用 `yahoo_source.py` 的 `_with_retry`（指数退避 + 抖动）
- **影响**：生产环境批量调用时，黄金/纳指异动可能因瞬时限频而丢失（降级为空），导致事件脉冲漏报
- **修复方向**：复用 `data/sources/yahoo_source.py` 的 `_with_retry`
- **优先级**：P1（影响事件脉冲的数据可靠性，不阻塞但应尽快）

---

## 二、受本地环境限制的验证（3 处）

> 代码均已就位且有单测覆盖，但「真实环境端到端」这一环受本地环境限制未验证。

### 3. yfinance 真实返回验证

- **现状**：本地 IP 被 Yahoo 全站限频（yfinance 库调用 + 直连 `query1` API 均 403/429），
  只验证了「接口存在」（报 `YFRateLimitError` 而非 `AttributeError`），从未拿到真实财报日期/行情
- **需验证**（生产 ECS）：
  ```bash
  python3 -c "import yfinance as yf; print(yf.Ticker('NVDA').get_earnings_dates(limit=3))"
  ```
- **验证点**：`event_calendar._fetch_us_earnings` 成功路径、`get_market_moves` 的黄金/纳指成功路径
- **优先级**：P0（数据源可用性是前提，阻塞上线）

### 4. shadow_account 成功路径验证

- **现状**：本地缺 `investment_system` 包（生产 ECS 通过 `pip install` 才有），
  `shadow_account.py` 的 `from investment_system import config` 失败，走了降级分支（`actual_total_value=None`）
- **需验证**（生产 ECS）：跑 `run_event_shadow.py`，确认 `_load_actual_snapshot()` 读到真实
  `total_value` / `position_count` / `realized_pnl`
- **验证点**：影子记录的 `actual_*` 字段为真实数据而非 `None`
- **优先级**：P0（影子记录需要真实持仓数据，阻塞上线）

### 5. dashboard `/api/v2/execution/event-risk` 端点验证

- **现状**：只做了 `py_compile` + 读代码，未启动 server 实测
- **需验证**（生产 ECS）：
  ```bash
  python3 dashboard/server.py 8686
  curl http://localhost:8686/api/v2/execution/event-risk
  ```
- **验证点**：端点返回 `{status, event_risk}` 结构正确；前端「事件风险指示灯」正常渲染
  （level→颜色映射、triggered_by hover 透明展示）
- **优先级**：P1（展示层，不阻塞核心逻辑）

---

## 三、优先级汇总

| 项 | 优先级 | 阻塞上线？ | 说明 |
|---|---|---|---|
| 3. yfinance 真实返回 | P0 | ✅ 是 | 数据源可用性是前提 |
| 4. shadow_account 成功路径 | P0 | ✅ 是 | 影子记录需真实持仓数据 |
| 5. dashboard 端点 | P1 | ❌ 否 | 展示层 |
| 2. get_market_moves 限频加固 | P1 | ❌ 否 | 降级为空可接受，影响可靠性 |
| 1. akshare 预约披露 bug | P2 | ❌ 否 | 手工 json 已兜底 |

---

## 四、当前代码状态摘要（供分析参考）

- **分支**：`feat/event-risk-switch`，7 个 commit 已 push
- **核心模块**：
  - `engine/event_calendar.py` — 未来事件日历（手工 json + yfinance earnings_dates，三态契约）
  - `engine/event_risk_engine.py` — 事件脉冲 `calc_event_risk` + 建议 `build_event_advice` + 影子记录 `build_shadow_entry` + 事件拦截 `event_blocks_buy` / `load_latest_event_risk` + 异动 `get_market_moves`
  - `scripts/run_event_shadow.py` — 影子运行脚本（每日记录脉冲 + 建议 + 持仓快照）
  - `dashboard/api_execution.py` + `templates/dashboard_main.py` — 事件风险指示灯
- **接入决策层**：`run_daily.py` dual_closed 门叠加事件避险 + `trading_engine.run_daily` 双拦截点（自动执行 BUY 拦截 + 建议信号 BUY 过滤）
- **阈值（评审共识）**：黄金单日 >2% 或 5 日 >5%；跨市场共振 纳指 <-3% 且 A股映射链 <-2%；level ≥ high 禁用 BUY
- **接实盘口径（评审共识）**：影子记录 ≥3-5 个真实事件（财报/制裁/IPO 各 ≥1）+ 事件后 5/10/20 日窗口 delta 显著为正 + false positive 率，才考虑上实盘
