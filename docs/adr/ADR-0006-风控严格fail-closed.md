# ADR-0006：风控严格 fail-closed

- 状态：Accepted
- 日期：2026-11-03
- 关联：ADR-0004、ADR-0007
- 代码：`engine/trading_engine.py`、`scripts/run_trading.py`、`scripts/run_daily.py`、`scripts/daily_factor_scan.py`

## 背景

审计发现多条"拿不到证据就当作没问题"的 fail-open 路径：

1. 事件影子文件缺失/非当天 → `load_latest_event_risk()` 返回 `None` → 当作"无风险"，继续买入。
2. 数据源自检 CRITICAL 或自检本身异常 → 扫描/交易继续跑，用残缺数据算因子。
3. 因子覆盖率 <50%（如 87/89 只动量因子 = 0.5）→ 照常评分、照常买入。
4. 宏观引擎异常 → 仓位乘数退回 `1.0`（满仓），把故障当利好。
5. 交易引擎因现金不足拒单 → 不打印原因，用户不知道信号为何没执行。

风控的核心原则应该是：**无法证明安全 = 不安全**。

## 决策

采用**严格 fail-closed**：

| 场景 | 行为 |
|------|------|
| 事件影子缺失 / 非当天 / 读取异常 | 禁用 **BUY**（SELL/止损照常） |
| 事件等级 `high` / `extreme` | 禁用 BUY；`high` 降仓、`extreme` 清仓 |
| 数据源自检 `status==2`（CRITICAL） | 禁用 BUY；`daily_factor_scan` 直接退出码 2 |
| 数据源自检**本身抛异常** | 同上，按 CRITICAL 处理 |
| 数据源 `status==1`（DEGRADED） | 允许研究/交易，但打印降级告警 |
| 任一子因子有效覆盖率 <50% | 禁用 BUY |
| 覆盖率指标不可用（无法证明） | 禁用 BUY |
| 宏观引擎异常 | 仓位乘数强制 `0.4` + 告警（不是 1.0） |
| 宏观双门红灯 / `strategy_switch=off` | 禁用 BUY |
| 现金不足 / 周频限制拒单 | 必须打印"需要多少、现有多少、原因" |

补充约定：

1. 所有拦截分支必须**打印明确原因**，并写入 `trading_signals.json` 的
   `risk_gates`（`event_level/event_data_missing/event_blocked/macro_blocked/
   macro_factor/upstream_block_reason`）。
2. 禁用 BUY 不影响 SELL/止损/清仓 —— 风控只收紧开仓，不阻止降风险。

## 后果

**收益**
- 数据故障/影子缺失不再伪装成"正常交易日"。
- 事后可复盘：当天为什么没买，`trading_signals.json` 里有原因。
- 残废因子不会进入票池/快照。

**代价/风险**
- **可能错过行情**：事件影子 cron 挂掉、数据源短暂不可用都会导致当天不开新仓。
  这是有意选择：宁可少赚，不可在不可信数据上开仓。
- 事件影子成为关键路径，`event-shadow` cron 必须可靠（见 `docs/CRON_JOBS.md`）。
- `daily_factor_scan` 在数据源 CRITICAL 时不再产出当日快照，快照天数可能中断。

**范围**
- 影响：`run_trading`、`run_daily`、`trading_engine`、`daily_factor_scan`。
- 不包含：卖出/止损的 fail-closed（保持"能卖就卖"）。

## 替代方案

| 方案 | 为什么没选 |
|------|-----------|
| 维持 fail-open + 告警 | 告警会被忽略，历史已证明会带病交易 |
| 仅数据源 fail-closed，其余告警 | 事件影子缺失同样导致无限开仓，风险等价 |
| 全部禁止交易（含卖出） | 故障时无法止损，风险更大 |

## 验证方式

离线断言：
- `event_risk=None` → `run_daily` 的 `dual_closed=True`，`trading_engine` BUY 全部拦截。
- 覆盖率 `{momentum: 0.4}` → `buy_block_reason` 非空。
- 数据源 `status=2` → `daily_factor_scan.main()` 返回 2 且不写批次。

生产核对：
```bash
python scripts/run_trading.py   # 观察 "⛔ 上游风控门 / 🛡️ 事件影子缺失 / 🌐 宏观引擎异常" 日志
python -c "import json;print(json.load(open('data/trading_signals.json'))['risk_gates'])"
```

## 回滚方式

回滚上述 4 个脚本/引擎到基线 `eb2128f`。注意：`daily_factor_scan` 的 fail-closed
会阻止"带病扫描"，回滚后需人工监控数据源健康。

---

## 修订：2026-11-05 — 覆盖率门的免费数据源兜底 + 面板口径对齐

### 背景

本机/生产环境**没有 `CSC_API_KEY`**（蜻蜓专业源不可用），导致 10 个子因子覆盖率恒为 0%：

```
dividend:yield, quality:debt_ratio, quality:net_margin, quality:ocf_per_share,
industry:pe_rank/roe_rank/margin_rank, sentiment:industry_heat,
value:pe_percentile, risk:pe_excessive
```

结果：覆盖率门**永久生效**，系统事实上只能卖不能买 —— 这是数据源缺陷，不是风控意图。

### 决策（不改变 fail-closed 原则，只补齐证据来源）

| 缺失项 | 兜底来源（免费、无需 key） | 说明 |
|---|---|---|
| 资产负债率 / 净利率 / 每股经营现金流 | akshare `stock_financial_analysis_indicator` | `data_layer._fill_fin_fallbacks()` 统一补齐，仅补缺失键 |
| 股息率 | akshare `stock_fhps_detail_em` | 取最近一期「实施分配」的股息率 ×100 |
| PE/PB 历史（`pe_hist_pct` / `pe_excessive` / `value:pb`） | akshare `stock_value_em` | `factor_engine._enrich_valuation()` 按日期对齐日线；**仅实盘**，回测 PIT 不注入 |
| 季频财务历史（ROE 加速度） | akshare `stock_financial_analysis_indicator` | baostock 并发登录失败时兜底；`as_of` 模式仍按披露截止日过滤 |
| 行业排名三因子 | 本批评分池横截面分位（PE / ROE / 毛利率） | 无专业源时的代理：**不是真实行业排名** |
| 行业热度 | 20 日动量分位（池内） | 与蜻蜓「量价热度」同向 |

### 关键约束

1. **回测不得使用兜底估值**：`as_of is not None` 时跳过 `_enrich_valuation()`，
   否则等于把"今天的 PE"注入历史时点（前视）。
2. **代理因子不得与源因子同序**：`industry:*_rank` 的兜底分直接作为标准化分，
   不再做链内二次标准化 —— 否则在同一个产业链内与 `value:pe_ttm` / `quality:roe`
   完全单调同序，等于给 PE/ROE 重复计权。
3. **覆盖率仍按真实取值统计**：兜底后覆盖率反映"该因子的输入数据确实取到了"，
   但 `industry/*` 是代理值，解释评分时应知道其含义弱于专业源。

### 面板口径对齐（同批修复）

- `dashboard/api_execution.py`：`ExecutionChecker` 判 BUY 但 `risk_gates` 有拦截时，
  不再显示为「建议买入」，改列 `blocked` 分组并给出 `blocked_by` 原因；
  响应新增 `snapshot{date,stale_days,stale}` 与 `buy_veto`。
- `engine/trading_engine.py`：`record_advice()` 移到 fail-closed 过滤**之后**。
  旧顺序下被门禁拦掉的 BUY 会占用本周唯一建议额度（`advice_week_count` 递增但最终信号为 0）。

### 日线数据源兜底（2026-11-06）

`data_layer.get_stock_daily()` 原来**只走 baostock，失败直接返回空**（注释写"不试 AKShare
以免挂死"，但 `_get_stock_daily_akshare` 从未被调用）。baostock flapping 时
`scripts/run_trading.py` Step 4 全池 0 只有历史数据 → `tech_map` 全部退化为默认值
（`ma20_dev/ma60_dev=0`、`rsi=50`），策略的 MA/RSI 判断静默失真。

- 兜底顺序：A股 → 新浪 `stock_zh_a_daily`（约 1.8s/只）→ 东财 `stock_zh_a_hist`；
  ETF → 新浪 `fund_etf_hist_sina` → 东财。
- 口径对齐：兜底也按 `days+10` 自然日窗口裁剪（新浪返回全量历史，直接 tail 会多给 30%+ K 线）。
- `FACTOR_A_AKSHARE_PRIMARY=1` 时新浪**先行**（本地 cron 已设），规避逐只 25s 超时。
- 兜底数据无 PE/PB，由 `factor_engine._enrich_valuation()` 在实盘补齐；回测 PIT 不注入。
