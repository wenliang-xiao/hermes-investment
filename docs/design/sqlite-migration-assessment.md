# SQLite 替代 JSON/pickle 可行性评估

> **日期**: 2026-07-07
> **背景**: 评审文档建议引入数据库替代 JSON/pickle 文件存储，用户要求评估 SQLite（免费）可行性

## 1. 现状

当前数据存储方式：

| 数据类型 | 格式 | 位置 | 读频率 | 写频率 |
|---------|------|------|--------|--------|
| 日线缓存 | pickle | data/cache/*.pkl | 高(每次扫描) | 低(每日预热) |
| 因子评分快照 | JSON | data/scan_snapshot_*.json | 中(日报) | 每日 |
| 模拟盘状态 | JSON | data/strategy_states.json | 高(Dashboard) | 每日 |
| 交易日志 | JSON | data/trade_log.json | 中 | 每次交易 |
| 回测结果 | JSON | data/backtest_results/ | 低 | 每次回测 |
| 票池 | JSON | data/pool/{watch,monitor,deep}.json | 中 | 每日 |
| 新闻缓存 | JSON | data/news_cache.json | 高 | 30分钟 |
| 宏观缓存 | JSON | data/macro_raw_cache.json | 中 | 24小时 |
| 行为诊断 | JSON | data/behavior_diagnosis.json | 低(Dashboard) | 每日 |

**问题**:
- 6 层缓存不协调，无统一失效机制
- pickle 文件无查询能力，全量加载
- JSON 文件并发写入风险（虽有 atomic_write_json 缓解）
- 无数据血缘、无 schema 约束

## 2. SQLite 评估

### 2.1 优势

| 维度 | JSON/pickle | SQLite |
|------|-------------|--------|
| 查询能力 | 全量加载后过滤 | SQL 索引查询 |
| 并发安全 | atomic_write_json（单写） | WAL 模式多读单写 |
| Schema 约束 | 无 | CHECK/FOREIGN KEY |
| 数据完整性 | 文件可能损坏 | ACID 事务 |
| 追加写入 | 全量重写 | INSERT 语句 |
| 历史查询 | 加载所有文件 | WHERE 时间范围 |
| 文件大小 | JSON 冗余大 | 压缩存储 |
| 零配置 | ✅ | ✅（Python 内置） |
| 免费 | ✅ | ✅ |

### 2.2 劣势

| 维度 | 影响 |
|------|------|
| 迁移成本 | ~20 个读写点需重构 |
| pickle 兼容 | DataFrame 无法直接存 SQLite（需拆列或用 BLOB） |
| 开发调试 | 不能直接 cat 查看内容 |
| 备份 | 需 sqlite3 .dump 或文件复制 |

### 2.3 适用场景判断

| 数据类型 | 适合 SQLite? | 理由 |
|---------|-------------|------|
| 因子评分快照 | ✅ 很适合 | 时间序列查询、历史对比 |
| 模拟盘状态 | ⚠️ 可选 | 单行 JSON 即可，SQLite 过重 |
| 交易日志 | ✅ 很适合 | 追加写入、历史查询 |
| 回测结果 | ✅ 适合 | 结构化存储、版本对比 |
| 票池 | ⚠️ 可选 | 单文件 JSON 足够 |
| 新闻缓存 | ⚠️ 可选 | TTL 短，JSON 足够 |
| 宏观缓存 | ❌ 不适合 | TTL 短、结构不固定 |
| 日线缓存 | ❌ 不适合 | DataFrame 格式，pickle 更高效 |

### 2.4 推荐方案

**分阶段迁移**，不是全量替换：

#### 阶段1（P2，1周）: 交易日志 + 因子评分快照
```
hermes.db
├── trade_log          (交易日志, 替代 trade_log.json)
├── factor_scores      (因子评分快照, 替代 scan_snapshot_*.json)
└── backtest_results   (回测结果, 替代 backtest_results/*.json)
```

开发量：~4小时（3 个表 schema + 读写函数 + 迁移脚本）

#### 阶段2（P2，1周）: 模拟盘状态 + 票池
```
├── strategy_states    (模拟盘状态, 替代 strategy_states.json)
├── pools              (票池, 替代 pool/*.json)
```

开发量：~2小时

#### 不迁移（保持文件）
- 日线缓存（pickle，DataFrame 高效）
- 新闻/宏观缓存（TTL 短，JSON 足够）
- 回测缓存（eval_cache）

### 2.5 成本估算

| 项目 | 成本 |
|------|------|
| SQLite | 免费（Python 内置 `sqlite3` 模块） |
| ECS 资源 | 零增量（SQLite 嵌入式，无独立进程） |
| 开发量 | 阶段1+2 约 6 小时 |
| 迁移风险 | 低（保留 JSON fallback，双写过渡） |

### 2.6 阿里云 ECS 适配

SQLite 在阿里云 ECS 上的运行注意事项：
- **WAL 模式**: `PRAGMA journal_mode=WAL` 提高并发读写
- **文件路径**: 使用 `HERMES_BASE` 环境变量定位 db 文件
- **备份**: `sqlite3 hermes.db ".dump" > backup.sql` 或直接复制 db 文件
- **监控**: `PRAGMA integrity_check` 定期校验

## 3. 结论

**推荐分阶段迁移 SQLite**，优先迁移交易日志和因子评分快照（时间序列查询需求最强）。日线缓存保持 pickle（DataFrame 高效），短 TTL 缓存保持 JSON。

SQLite 免费、零配置、Python 内置，是当前阶段最合适的数据库选择。不需要引入 PostgreSQL/MySQL 等独立数据库服务。
