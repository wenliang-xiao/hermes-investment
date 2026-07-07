# Hermes Investment · 项目专属规则

> 通用工作流 + Skills 速查在全局 `~/.config/opencode/AGENTS.md`
> 本文件仅包含 Hermes 项目特有知识

运行项目 Python 脚本前请先 `source .opencode/env.sh`（设置 `HERMES_BASE`）。

---

## 项目架构（快速定位）

```
入口层:  run_daily.py (日报) / run_weekly.py (周报) / run_factor_daily.py (因子日扫)
数据层:  data_router.py (统一路由) / data_layer.py (旧A股) / data_source_layer.py (新层)
因子层:  factor_scanner.py (v3.1, [1,10]分) / factor_engine.py (v4.0, [0,1]分)
策略层:  strategies/*.py (纯函数) / trading_engine.py (类实现+模拟盘)
输出层:  report_v6.py (日报) / portfolio_server.py (Dashboard :8686)
配置层:  config.py (主) / domain/__init__.py (部分副本,需同步)
回测层:  backtest.py / backtest_v2.py / evaluator_fixed.py
```

## 评分引擎（核心差异）

| 引擎 | 输出范围 | 方法 | 因子数 | 使用者 |
|------|---------|------|--------|--------|
| factor_scanner v3.1 | [1,10] | 固定区间线性插值 | 6 | run_daily.py |
| factor_engine v4.0 | [0,1] | scipy截面分位数 | 19子→7风格 | run_factor_daily.py |

**策略阈值基于 v3.1 [1,10]**。两套评分不能混用。

## 策略实现（两套并存）

- `strategies/*.py`: 纯函数(无状态/无IO)→Signal列表，用于回测和独立调用
- `trading_engine.py`: 策略类(有状态)→模拟盘执行，用于日报管线和 Dashboard
- 修改策略逻辑时**两处都要同步**

## 已知严重 Bug（修复前不能改相关逻辑）

| Bug | 文件 | 行号 | 问题 |
|-----|------|------|------|
| 财务abs() | data_layer.py | L276,327-331,354,364 | abs()抹消正负号,ROE=-5%→500% |
| MA方向反向 | faceji.py | L62 | `ma60d <= ma20d → skip` 在上升趋势错误跳过 |
| 周频接线缺陷 | trading_engine.py | L631-644 | 模拟盘绕过TradeCalendar,周频过滤仅用于建议信号 |
| MACD判定恒真 | 三处 | evaluator_fixed.py:L256,backtest_v2.py:L293,backtest_all:L539 | `pmacd <= pe12-pe26` = `pmacd <= pmacd` |

完整清单: `docs/review/final-deep-audit-2026-07-03.md`

## 禁止事项

- ❌ 不要修改 `evaluator_fixed.py` 的 `FIXED_SCORE_MAP`（ADR-001 固定评估器）
- ❌ 不要对 `config.py` 和 `domain/__init__.py` 分别改动同一个值（双重维护,统一前用一个）
- ❌ 不要新增评分引擎或策略实现
- ❌ 不要用 `as any` / `@ts-ignore` / `@ts-expect-error`

## 配置详情

- WATCHLIST: ~92 只唯一标的（A股 47 + 港股 9 + 美股 18 + ETF 17 + 其他）
- 产业链: 15 条（config.py 最新，domain/__init__.py 缺"物理AI链"）
- WATCHLIST 重复条目: GLD/HG=F/CL=F（L352/404, L354/406, L355/407）
- 飞书凭据: config.py L16-22 硬编码，应改用环境变量

## 版本约定

- tag: `vYYYY.MM.DD`
- commit: 中文, `feat:` / `fix:` / `refactor:` / `docs:` 前缀
- 改动前先 `git fetch -p`
- 飞书方案文档默认 `wiki_space: "my_library"`

## 关键路径

- Dashboard: `python3 scripts/portfolio_server.py 8686` → http://47.85.161.255/dashboard
- 日报: ECS Cron 工作日 08:30 / 18:00 → run_daily.py → 飞书推送
- 因子日扫: run_factor_daily.py --top-n 30
- 数据预热: python3 scripts/pull_all_data.py
