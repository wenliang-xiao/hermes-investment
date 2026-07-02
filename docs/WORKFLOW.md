# 面基投资系统 · 开发工作流

> 版本: v2026.07.02 | 本文件与飞书文档「开发工作流 v1」同步
> 飞书: https://www.feishu.cn/docx/Xz3ydbzjmomnyCxLIlycPfTMn0p

## 一、核心理念

- **所有改动必须过飞书文档评审流程** — 不允许直接改代码
- 评审流程：创建蓝图 → 拉取评论 → 共识 → 开发 → 生成 MD → 更新 README
- README 是入口，docs/ 是知识库，飞书是协作层（评审+共识）
- 代码是真理源（GitHub），文档是辅助（README + docs/）

## 二、5 阶段工作流

### Phase 1: 需求 → 飞书蓝图

1. 需求来源：用户指令 / 飞书评论 / 审计报告 / 回测结果
2. 在飞书「面基播客知识体系」文件夹创建蓝图文档
3. 蓝图中须包含：背景、目标、方案选项（≥2个）、影响范围、验收标准

### Phase 2: 评审 → 共识

1. 用户（或受邀评审者）在飞书文档上添加评论
2. Agent 读取所有评论，逐个回复/修改方案
3. 共识达成的标志：用户说"开干"或"按这个做"

### Phase 3: 开发 → 拆任务

1. 基于共识的蓝图，拆分为 bite-sized tasks（每个 2-5 分钟）
2. 任务拆分写入 `docs/plans/` 下的 MD 文件
3. 每个任务遵循 TDD 原则：写测试 → 验证失败 → 实现 → 验证通过 → commit

### Phase 4: 交付 → 文档同步

1. 代码变更提交至 GitHub
2. 对每个变更生成/更新对应 MD 文档到 `docs/`
3. 更新 `README.md` 中的链接
4. 如有必要更新 `CHANGELOG.md`

### Phase 5: 验收 → 锁版本

1. 用户验证通过后，打 tag 锁版本（Calendar Versioning: vYYYY.MM.DD）
2. tag 信息包含该版本所有变更摘要
3. 紧急修复需事后补文档

## 三、文档体系

```
docs/
├── README.md          ← 文档索引（根 README 链接到此）
├── ARCHITECTURE.md    ← 系统架构总览
├── GLOSSARY.md        ← 术语表
├── CHANGELOG.md       ← 变更日志
├── API.md             ← API 端点参考
├── WORKFLOW.md        ← 本工作流说明
├── plans/             ← 实施计划
│   ├── template.md
│   └── YYYY-MM-DD-feature-name.md
└── specs/             ← OpenSpec 规范
    └── dashboard-v1.md
```

## 四、质量标准

| 优先级 | 规则 | 不通过后果 |
|--------|------|-----------|
| P0 | 硬编码凭证不移除 | 不过审 |
| P0 | strategies/ 纯函数不测试 | 任务不算完成 |
| P1 | 每次 PR 不更新文档 | 不合并 |
| P2 | 数据源重复（config vs domain） | 后续清理 |

## 五、版本约定

- **Calendar Versioning**: `vYYYY.MM.DD`
- 示例：`v2026.07.02`、`v2026.07.02-hotfix1`
- 系统中其他版本号（config.py v5.5 等）全部废弃

## 六、相关文档

- [README.md](../README.md) — 项目入口
- [ARCHITECTURE.md](ARCHITECTURE.md) — 系统架构
- [GLOSSARY.md](GLOSSARY.md) — 术语表
- [API.md](API.md) — API 端点参考
