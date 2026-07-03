# Hermes Investment · AGENTS.md

> 本文件在每次 session 启动时注入 Sisyphus 的系统提示。
> 定义工作流规则 + 项目专属知识 + 质量标准。

---

## 一、工作流 v4 — 双入口，按范围选工具

```
你的需求
   │
   ├─ 复杂项目(跨模块/架构/多方案) → OpenSpec 飞书评审
   │   Agent读代码 → 写飞书方案文档 → 你评论批注 → 迭代共识 → Trellis执行
   │
   └─ 中小改动(单模块/<50行/方向已定) → grill-me 快车道
       Agent追问选择题(A/B) → 你拍板 → Trellis执行
```

### 选择指南

| 判断标准 | 飞书评审 | grill-me |
|----------|---------|----------|
| 跨模块改动 | ✅ | ❌ |
| 多个方案需比较 | ✅ | ❌ |
| 方向已定只有细节 | ❌ | ✅ |
| 需要深度架构思考 | ✅ | ❌ |
| 改动量 < 50 行 | ❌ | ✅ |
| 拿不准 | ✅ | ❌ |

### 飞书评审流程
1. Agent 读代码 → 创建飞书文档（`feishu-mcp create-doc wiki_space="my_library"`）
2. 你对文档加评论批注
3. Agent 读评论(`feishu-mcp get-comments`) → 修改方案
4. 你说"开干" → Trellis 执行

### grill-me 快车道
Agent 加载 `grill-me` skill，就改动方案问 3-5 个选择题，你选 A/B，共识后直接 Trellis。

## 二、Trellis 执行

1. Agent 拆为 3-5 个纵向切片（每个端到端可独立验证，标注 AFK/HITL）
2. 你审核拆分方案（2 分钟）
3. TDD 逐个执行：测试→失败→实现→通过→commit
4. 事后补 docs/ + 打 tag

## 三、质量标准

| P | 规则 |
|---|------|
| P0 | 硬编码凭据 → 环境变量 |
| P0 | strategies/ 纯函数必须有测试 |
| P1 | docs/ 事后补 |

## 四、项目专属知识

### 评分引擎
- `factor_scanner.py` (v3.1): 输出 [1,10] 分，固定区间线性插值，6 因子。被 `run_daily.py` 使用
- `factor_engine.py` (v4.0): 输出 [0,1] 分，scipy 截面分位数，19 子因子→7 风格。被 `run_factor_daily.py` 使用
- **两套不兼容。** 策略阈值基于 v3.1 [1,10] 设置。统一前不要混用

### 策略实现
- `strategies/*.py`: 纯函数（无状态，无 IO），生成 Signal 列表
- `trading_engine.py`: 策略类（有状态，模拟盘执行），内含 `FacejiStrategy`/`SilverQuantStrategy`/`TradingAgentsStrategy`
- **同一个策略有两套实现。** 修改时需同步两处

### 已知严重 Bug（修复前不要碰相关逻辑）
- `data_layer.py` L276,327-331,354,364: `abs()` 抹消财务数据正负号
- `faceji.py` L62: MA 趋势过滤方向反向
- `trading_engine.py` L631-644: 模拟盘绕过周频限制
- MACD 金叉判定: `pmacd <= pe12-pe26` 恒为真（三处）
- 详见 `docs/review/final-deep-audit-2026-07-03.md`

### 禁止事项
- ❌ 不要直接修改 `evaluator_fixed.py` 的 `FIXED_SCORE_MAP`（ADR-001）
- ❌ 不要新增评分引擎或策略实现，先统一现有
- ❌ 不要改 `config.py` 和 `domain/__init__.py` 中的同一个值（两个文件是重复维护）

## 五、MCP 工具

| 工具 | 用途 |
|------|------|
| `feishu-mcp` | 创建/更新/读取飞书文档、搜索用户、评论 |
| `elasticsearch` | 查线上日志（按 requestId/时间范围） |
| `context7` | 查最新库文档 |

## 六、Skills 速查

| Skill | 触发 |
|-------|------|
| `deep-research` | 深度调研 |
| `techdoc` | 写技术文档 |
| `humanizer` | 去 AI 味润色 |
| `grill-me` | 中小改动选择题模式 |
| `to-prd` | 生成飞书方案文档 |
| `tdd` | TDD 开发 |
| `implement` | 直接实现 |
| `diagnosing-bugs` | 系统调试 |
| `code-review` | 代码 review |
| `domain-modeling` | 领域建模 |
| `review-work` | 实现后多 Oracle 评审 |
| `security-research` | 安全审计（3 漏洞猎手 + 2 PoC） |

## 七、版本约定

- tag: `vYYYY.MM.DD`
- commit: 中文，`feat:` / `fix:` / `refactor:` / `docs:` 前缀
- 改动前先 `git fetch -p`
