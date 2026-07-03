# 📚 面基投资系统 · 文档索引

> 版本: v2026.07.02 | 本页是 docs/ 目录的入口

## 审计报告 (`review/`)

| 文档 | 说明 | 最后更新 |
|------|------|---------|
| [final-deep-audit-2026-07-03.md](review/final-deep-audit-2026-07-03.md) | 深度代码审计：5 轮 agent 逐行审计，10 个 P0 Bug + 安全漏洞 + 架构问题 | 2026-07-03 |

## 核心文档

| 文档 | 说明 | 最后更新 |
|------|------|---------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构总览 — 模块/数据流/ADRs | 2026-07-02 |
| [GLOSSARY.md](GLOSSARY.md) | 术语表 — 面基/LDS/双门/20+核心概念 | 2026-07-02 |
| [API.md](API.md) | API 端点参考 — 所有路由和数据结构 | 2026-07-02 |
| [WORKFLOW.md](WORKFLOW.md) | 开发工作流 — 5阶段流程/质量标准 | 2026-07-02 |
| [score_explanation.md](score_explanation.md) | 7因子评分体系说明 | 2026-07-02 |
| [CHANGELOG.md](../CHANGELOG.md) | 完整变更日志（根目录） | — |

## 生产化设计方案 (`design/`)

| 文档 | 说明 | 优先级 |
|------|------|--------|
| [README](design/README.md) | 设计方案总览与路线图 | — |
| [security-hardening.md](design/security-hardening.md) | 安全加固：凭据管理、pickle 安全、API 认证 | 🔴 P0 |
| [engineering-foundation.md](design/engineering-foundation.md) | 工程化基础：依赖管理、CI/CD、代码规范 | 🔴 P0 |
| [testing-infrastructure.md](design/testing-infrastructure.md) | 测试基础设施：从零到覆盖关键路径 | 🔴 P0 |
| [data-pipeline-reliability.md](design/data-pipeline-reliability.md) | 数据管线可靠性：原子写入、缓存、容错 | 🟡 P1 |
| [factor-engine-unification.md](design/factor-engine-unification.md) | 因子引擎统一：v3.1 × v4.0 合并方案 | 🟡 P1 |
| [architecture-split.md](design/architecture-split.md) | 架构拆分：超大文件分解 + 配置去重 | 🟡 P1 |
| [observability.md](design/observability.md) | 可观测性：日志、健康检查、告警 | 🟢 P2 |
| [dashboard-refactoring.md](design/dashboard-refactoring.md) | Dashboard 重构：前后端分离 + 交互增强 | 🟢 P2 |

## 实施计划 (`plans/`)

| 文件 | 说明 | 状态 |
|------|------|------|
| [template.md](plans/template.md) | 计划模板 | ✅ |
| — | 下一个计划的占位 | — |

## 规范 (`specs/`)

| 文件 | 说明 | 状态 |
|------|------|------|
| — | Dashboard v1 规范（待编写） | 📋 |

## 外部链接

- [飞书工作流 v4（四合一）](https://www.feishu.cn/docx/AYSadQ7QhoexZ3x64oaczthhnNh) — 当前有效（v3已废弃）
- [飞书问题追溯表](https://www.feishu.cn/docx/S9A6dzJFbo7wWqxJ12Uc7K7Fn8y)（Dashboard 修复追踪）
- [GitHub 仓库](https://github.com/wenliang-xiao/hermes-investment)
- [Dashboard](http://47.85.161.255/dashboard)
