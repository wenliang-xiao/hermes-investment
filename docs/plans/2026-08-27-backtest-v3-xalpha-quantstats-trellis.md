# 回测引擎升级 v3 — xalpha + quantstats 专业框架迁移

> 2026-08-27 · 目标：完全用 xalpha(交易引擎) + quantstats(报告) 替换自研回测，产出一致化 HTML 报告。
> 背景：周一与 LDS 深度讨论策略能力和回测表现，需要专业框架级证据。
> 方法论：SDD 先定契约 → TDD 红绿实现 → 每 WS 原子 commit → 推送 main。

## 一、能力差距（自研 vs 专业框架）

| 能力 | 自研现状 | xalpha/quantstats | 差距 |
|---|---|---|---|
| 交易引擎 | evaluator_fixed 手写逐日循环 | xalpha trade 引擎(申购/赎回/分红/拆分建模) | 大 |
| 数据适配 | baostock 直读 | basicinfo 契约，需 AStockInfo 适配层 | 须自建 |
| 指标 | 手写6个(年化/夏普/索提诺/回撤/卡玛/胜率) | quantstats 50+ 指标 | 大 |
| 报告 | 前端指标卡 | quantstats HTML(月度热力图/滚动夏普/水下图/收益分布) | 无 |
| 基准 | 沪深300 单线 | benchmark 对比(alpha/beta/信息比) | 中 |
| 分红/拆股 | 未建模(前复权价近似) | specialdate/fenhongdate/zhesuandate 建模 | 大 |

## 二、xalpha 关键能力验证（spike 已过）

- ✅ `xalpha.policy`（buyandhold 等策略基类，status_gen 生成记账单）
- ✅ `xalpha.backtest.trade`（infoobj + status → 现金流水/持仓/净值）
- ✅ `basicinfo` 契约：code/name/rate/price(date,netvalue,comment) + shengou/shuhui + specialdate
- ✅ `xalpha.backtest.mul`（多标的组合）
- ✅ quantstats reports.html（pandas 3.0.3 兼容，370KB 报告）
- ⚠️ xalpha 数据源仅 jq(聚宽账号) → **数据必须走 baostock/蜻蜓适配**（已验证可行）
- ⚠️ xalpha 指标层针对基金价格表 → **指标统一走 quantstats**（NAV序列驱动）

## 三、SDD — 规格契约

### 契约 A：AStockInfo 适配层
```
class AStockInfo:  # 继承/模仿 xalpha.basicinfo 契约
  __init__(code, name, df, rate=0.0003, lot_size=100, enforce_lot=True)
  price: DataFrame[date, netvalue(close), comment(0)]
  shengou(value, date, fee) -> (realdate, -cash, +share)  # 整手或任意份额
  shuhui(share, date, rem)  -> (realdate, +cash, -share)  # 印花税0.05%卖出
  specialdate/fenhongdate/zhesuandate: 供分红/拆分建模
```

### 契约 B：策略桥（自研策略 → xalpha status）
```
build_status(strategy, price_data, capital) -> DataFrame[date, code, amount]
  # 把 faceji/silverquant/tradingagents 的 decide_fn 信号转成记账单:
  # BUY -> +金额(按 Kelly/评分仓位), SELL -> -份额比例
```

### 契约 C：回测编排器
```
engine/backtest_v3.py:
  run_backtest_v3(strategy, days, capital, benchmark=True) -> dict:
    {report_html: "data/reports/{strategy}_{ts}/report.html",
     nav: Series, metrics: quantstats.stats, trades, benchmark_nav,
     params, run_date}
```

### 契约 D：报告落盘 + API
- 每次运行落盘 `data/reports/{strategy}_{YYYYmmdd_HHMMSS}/report.html` + meta.json
- API `/api/v2/backtest/v3/report?run_id=...` 返回 HTML
- API `/api/v2/backtest/v3/list` 列出历史报告

## 四、WS 分解（TDD）

### WS0 可行性前置 ✅
- [x] 安装 xalpha 0.12.4 + quantstats 0.0.81（pandas 3.0.3 兼容）
- [x] spike: baostock→AStockInfo→trade→NAV→quantstats HTML ✅

### WS1 引擎适配层
- [ ] factory: baostock 数据 → AStockInfo（code/name/price 转换 + 整手控制）
- [ ] TDD: shengou/shuhui 金额-份额-现金流三向一致
- [ ] 分红/拆分: baostock 除权信息 → specialdate/comment

### WS2 策略桥
- [ ] 三策略 decide_fn → status 记账单（BUY金额/SELL份额）
- [ ] TDD: 记账单金额守恒(初始资金=Σ买入+现金结余)
- [ ] mul 组合净值（多标的合并）

### WS3 报告引擎（quantstats）
- [ ] NAV → quantstats metrics 全量
- [ ] HTML 报告(月度热力图/滚动/水下图/基准对比)落盘
- [ ] benchmarks: 沪深300 NAV 对齐

### WS4 API + Dashboard
- [ ] /api/v2/backtest/v3/run（跑+存报告）
- [ ] /api/v2/backtest/v3/list + report 查看
- [ ] Dashboard 回测面板 → v3 入口 + 报告链接

### WS5 周一材料
- [ ] 三策略 v3 报告各 1 份（109天真实数据）
- [ ] 与自研对比表：指标偏差说明
- [ ] 全量测试无回归

## 五、验收标准
- 周一前：faceji/silverquant/tradingagents 三份 quantstats 专业 HTML 报告
- 每份含：净值vs基准、月度热力图、水下图、滚动夏普、全指标表、交易统计
- 报告数据与自研引擎同源（同一 baostock 数据），指标口径可对比
- 全量测试通过，git push main