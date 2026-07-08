"""
engine/ — Core Factor & Backtest Engines

Contains:
  - factor_engine.py   — v4.0截面分位因子引擎 (19子→7风格)
  - factor_scanner.py  — v3.1固定区间评分 (deprecated)
  - factor_quality.py  — 因子质量 & 快照
  - backtest.py        — 回测引擎 v2.0 (deprecated)
  - backtest_types.py  — BacktestResult dataclass
  - backtest_storage.py — 回测结果存储
  - strategy_comparison.py — 三方策略对比
  - evaluator_fixed.py — 固定评估器 (ADR-001)
  - macro_engine.py    — 宏观引擎
  - portfolio_builder.py — 组合构建
  - cost_model.py      — 成本模型 (older version, see also trading/cost.py)
  - score_history.py   — 评分历史
  - dsr_test.py        — DSR统计检验
  - behavior.py        — 行为诊断
  - stop_list.py       — 黑名单
  - init_ic_data.py    — IC数据初始化
"""
