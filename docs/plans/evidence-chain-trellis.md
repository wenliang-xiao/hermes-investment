# Dashboard 证据链重构 — Trellis 执行计划

## S1: EvidencePacket + EvidenceBuilder + API证据嵌入 (P0)
- S1a: EvidencePacket dataclass + EvidenceBuilder (engine/evidence_builder.py)
- S1b: factor_engine.py score_batch 输出加 evidence 字段
- S1c: macro_engine.py to_dict 输出加 evidence 字段  
- S1d: api_evidence.py 新增 Nick四问 / chain-map 端点

## S2: ExecutionChecker + 执行决策 API (P0)
- S2a: ExecutionChecker — 建仓6查 + TrailStop计算
- S2b: api_execution.py — execution/board, build-checklist, trail-stop
- S2c: api_pool.py / api_portfolio.py 每个候选/持仓加 evidence 字段

## S3: LayerStatus + 六层横条 (P1)
- S3a: engine/layer_status.py — L1-L6 聚合
- S3b: api_layers.py — layers/status, layers/macro, layers/allocation

## S4: ChainEvidence + 前段证据展示 (P1)
- S4a: research/chain_evidence.py — 链定位 + Nick四问
- S4b: dashboard/templates/dashboard_main.py — 证据卡片渲染

## S5: SignalValidator + 历史验证 (P1)
- S5a: engine/signal_validator.py
- S5b: signal_accuracy 端点增强

## S6: MarketIntel + 市场情报 (P2)
- S6a: research/market_intel.py
- S6b: api_market.py
