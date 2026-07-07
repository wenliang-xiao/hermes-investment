# Phase P0 执行计划 — 修复瘫痪管线

> 基于全面审计缺口矩阵，5项紧急修复，预估 2.75 天
> OpenSpec 模式: 每个子项目 TDD (RED→GREEN) + 原子提交

## 执行顺序

```
PS1 (realtime) → PS2 (news) → PS3 (metrics) → PS4 (净值曲线) → PS5 (回测run_id)
```

依赖关系: 无硬依赖，但从影响面从小到大排列，先修核心链路。

## PS1: 修复 realtime API

- **问题**: /api/realtime 和 /api/realtime/positions 完全无响应 (HTTP 200 but empty body)
- **根因调查**: realtime_price 模块中 data_router 导入失败
- **方案**: 
  1. 定位导入失败的精确位置和原因
  2. 修复导入路径或模块引用
  3. TDD: 写 realtime 单元测试 (mock data_router)
  4. 验证: curl /api/realtime 返回 > 0 价格
- **预估**: 0.5天

## PS2: 修复 news_pipeline Tier1

- **问题**: 新闻管线 Tier1 (AKShare) API 不兼容新版，41只标的全 error
- **根因调查**: akshare.stock_news_em 或其他 API 在新版 akshare 中变更
- **方案**:
  1. 确定损坏的 API 调用和正确的新版调用方式
  2. 修复或降级 akshare 版本
  3. TDD: 写新闻获取单元测试
  4. 验证: news_pipeline 能获取至少 1 条有效新闻
- **预估**: 1天

## PS3: 修复 metrics 数据源

- **问题**: /api/metrics 全部为 0，数据用 shadow_account.json 而非 strategy_states.json
- **根因调查**: portfolio_server.py 中 metrics 端点读取错误的数据文件
- **方案**:
  1. 修改 metrics 端点为 strategy_states 聚合数据
  2. 与 /api/portfolio 使用相同的数据源
  3. TDD: 写 metrics 计算单元测试
  4. 验证: /api/metrics 返回非零值
- **预估**: 0.5天

## PS4: 修复净值曲线 Bug

- **问题**: chart.values 出现负值 (-469,444)，build_chart_data 卖出逻辑错误
- **根因调查**: trading_engine.py 中 build_chart_data 的 cash 结算方式错误
- **方案**:
  1. 审查 build_chart_data 中卖出时 cash 增加逻辑
  2. 修复错误计算
  3. TDD: 写净值曲线计算测试
  4. 验证: 净值曲线无负值
- **预估**: 0.5天

## PS5: 修复回测 run_id 双重前缀

- **问题**: load_result 构造文件名时加 'bt_' 前缀，但文件名已有 'bt_'，导致 404
- **根因调查**: backtest_storage.py 中 load_result 方法
- **方案**:
  1. 移除 load_result 中的额外前缀
  2. 统一前缀策略
  3. TDD: 写 run_id 解析测试
  4. 验证: /api/v2/backtest/{id} 返回 200
- **预估**: 0.25天

## 验证标准

| 验证项 | 标准 | 关联 |
|--------|------|------|
| `pytest tests/ -q` | ≥ 82 tests, 全绿 | 每项后 |
| `/api/realtime` | 返回 JSON + 价格 > 0 | PS1 |
| `/api/metrics` | 返回非零值 | PS3 |
| 净值曲线无负值 | chart.values min ≥ 0 | PS4 |
| `/api/v2/backtest/{id}` | 返回 200 | PS5 |
| Dashboard 刷新 | 三面板正常 | 全部 |

## 提交策略

每个 PS 独立 commit，commit message 格式:
```
PS<N>: <简短描述>

- <修复内容>
- TDD: <测试说明>
- <验证结果>
```