# 工程化基础方案

> 版本: v1.0 | 2026-07-03 | 状态: 提案阶段
>
> Hermes Investment System 工程基础设施从零建设方案，覆盖依赖管理、代码质量、CI/CD、分支策略、日志标准化等全部工程化维度。

---

## 目录

- [一、概述](#一概述)
- [二、现状诊断](#二现状诊断)
- [三、依赖管理](#三依赖管理)
- [四、代码质量工具链](#四代码质量工具链)
- [五、CI/CD 流水线](#五cicd-流水线)
- [六、分支策略与提交规范](#六分支策略与提交规范)
- [七、版本管理与 CHANGELOG](#七版本管理与-changelog)
- [八、Pre-commit 钩子](#八pre-commit-钩子)
- [九、日志标准化](#九日志标准化)
- [十、.gitignore 补全](#十gitignore-补全)
- [十一、安全加固](#十一安全加固)
- [十二、实施时间线](#十二实施时间线)

---

## 一、概述

### 1.1 项目背景

Hermes Investment System（面基三源融合投资系统）是一个覆盖 A 股 + 港股 + 美股的量化投资系统，包含 94 个 Python 源文件，部署在裸 ECS 上运行。系统当前功能完整、线上稳定，但工程基础设施几乎为零——没有依赖声明、没有代码质量工具、没有 CI/CD、没有容器化。

### 1.2 文档用途

本文档为系统建立完整的工程化基础，输出可落地执行的方案，不做理论探讨。读完本文后，读者可以：
- 理解当前工程现状的缺陷与风险
- 拿到可直接使用的配置文件模板
- 按时间线逐步推进工程化建设

### 1.3 文档结构

- **第二章**：逐项诊断当前工程缺失，量化问题规模
- **第三至十一章**：每个工程化维度的完整方案（选型、配置、实施步骤）
- **第十二章**：分阶段实施时间线，按优先级排列

---

## 二、现状诊断

### 2.1 依赖管理

| 现状 | 风险 |
|------|------|
| 无 `requirements.txt`、`setup.py`、`pyproject.toml`、`Pipfile` | 无法复现环境，新机器部署需手动试错 |
| 依赖散落于 94 个文件的 300+ 条 import 中 | 审计升级依赖无从下手 |
| 第三方库版本未锁定 | 不同时间安装结果不同，线上漂移风险 |

#### 完整依赖清单（跨 94 个源文件审计）

| 类别 | 库 | 用途 |
|------|-----|------|
| 数据获取 | `yfinance` | 港股/美股行情 + 财务数据 |
| 数据获取 | `baostock` | A 股日线 + 财报 + PE 历史 |
| 数据获取 | `requests` | HTTP 请求（部分数据源） |
| 数据获取 | `akshare` | A 股东财数据（README 提及） |
| 数据处理 | `numpy` | 数值计算 |
| 数据处理 | `pandas` | 数据框架 + CSV/JSON 读写 |
| 统计分析 | `scipy` | 统计检验（`scipy.stats`） |
| Web 服务 | `fastapi` | Dashboard HTTP API |
| Web 服务 | `uvicorn` | ASGI 服务器（FastAPI 依赖） |
| 配置 | `python-dotenv` | `.env` 环境变量加载 |
| 内部 | `feishu` | 飞书文档 API（自定义包，非 PyPI） |

### 2.2 代码质量工具链

| 工具 | 现状 |
|------|------|
| Linter | 无（无 `.flake8`、`.pylintrc`、`pyproject.toml [tool.ruff]`） |
| Formatter | 无（无 `black`、`isort`、`ruﬀ format` 配置） |
| Type Checker | 无配置。~60% 类型标注覆盖率，新代码高、旧代码低 |

### 2.3 CI/CD

| 维度 | 现状 |
|------|------|
| CI 流水线 | 无（`.github/workflows/` 不存在） |
| 部署方式 | 裸 ECS，手动 `python3 scripts/portfolio_server.py 8686` |
| 定时任务 | 无 CI cron，依赖手动或外部 cron 触发 |
| 容器化 | 无 Dockerfile |

### 2.4 安全与代码卫生

| 问题 | 量化 |
|------|------|
| 硬编码凭证 | `config.py:16` 包含 Tushare Token（明文） |
| 裸 `except:` / `except Exception:` | 477 处（跨 60 个文件），占比约 22.5% |
| `print()` 替代日志 | 827 处 `print()` / `logging` 调用，大部分是 `print()` |
| 日志非集中化 | 各模块独立 `logging.getLogger(__name__)`，无统一配置 |

### 2.5 版本管理

| 指标 | 现状 |
|------|------|
| 总提交数 | 148 |
| Tag 数 | 2 (`v1.0.0`, `v2026.07.02`) |
| 大提交频率 | 20+ commits 变更超过 1000 行 |
| 分支策略 | 单分支，直接 push 到 `main` |
| CHANGELOG | 存在但为手动维护 |

### 2.6 .gitignore 缺失项

- `.idea/` — JetBrains IDE 配置目录
- `backup_*` — 备份目录（如 `backup_20260525_115538/`）
- `.omo/` — OMO agent 工作目录
- `.sisyphus/` — Sisyphus 工作目录
- `config_backup_*.yaml` — 已有但覆盖不完整

---

## 三、依赖管理

### 3.1 工具选型

| 工具 | 优势 | 劣势 | 适合度 |
|------|------|------|--------|
| **uv** | 极快（Rust 实现），兼容 pip，内置 lock 文件，PEP 621 标准 | 相对新（2024+），生态仍在完善 | ★★★★★ |
| pip-tools | 成熟稳定，pip-compile + pip-sync 模式 | 慢，两个工具分开用 | ★★★ |
| Poetry | 全功能，依赖解析好 | 慢，非 PEP 621，有自己的 `[tool.poetry]` 格式 | ★★★ |
| Pipenv | 曾经主流 | 慢，维护不活跃 | ★★ |

**推荐 uv**。理由：
- Hermes 部署在 ECS，安装速度影响部署体验，uv 比 pip 快 10-100x
- uv 使用标准 `pyproject.toml [project]` 格式（PEP 621），未来迁移成本最低
- 内置 `uv lock` / `uv sync`，等价于 `pip-compile` + `pip-sync`，但一个命令搞定
- 同时管理 Python 版本（`uv python install 3.12`），减少宿主机依赖

### 3.2 pyproject.toml 结构

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "hermes-investment"
version = "3.3.0"
description = "面基三源融合 · 量化投资系统"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [
    {name = "wenliang-xiao"},
]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Financial and Insurance Industry",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = [
    "numpy>=1.24,<2",
    "pandas>=2.0,<3",
    "scipy>=1.10,<2",
    "yfinance>=0.2.40",
    "baostock>=0.8.8",
    "akshare>=1.12.0",
    "requests>=2.31,<3",
    "fastapi[standard]>=0.110,<1",
    "uvicorn[standard]>=0.29,<1",
    "python-dotenv>=1.0,<2",
    "python-json-logger>=2.0,<3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9",
    "pytest-cov>=5.0",
    "ruff>=0.5,<1",
    "mypy>=1.10,<2",
    "pre-commit>=3.7,<4",
]

[project.scripts]
hermes-server = "scripts.portfolio_server:main"
hermes-daily = "scripts.run_daily:main"
hermes-weekly = "scripts.run_weekly:main"

[tool.uv]
dev-dependencies = [
    "pytest>=8.0,<9",
    "pytest-cov>=5.0",
    "ruff>=0.5,<1",
    "mypy>=1.10,<2",
    "pre-commit>=3.7,<4",
]
```

### 3.3 实施步骤

```bash
# 1. 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 初始化项目
cd hermes-investment
uv init --no-readme  # 已有 README.md
# 编辑 pyproject.toml 填入上述依赖

# 3. 锁定依赖
uv lock

# 4. 同步安装
uv sync

# 5. 生成传统 requirements.txt（向后兼容）
uv export --format requirements-txt --no-hashes > requirements.txt
```

### 3.4 关于 feishu 内部包

`analysis/generate_backtest_report.py:11-14` 引用了 `feishu` 包（`build_report`, `auth`, `drive`, `block`），这不是 PyPI 公开包。当前它可能通过 `sys.path` hack 或手动安装到 site-packages。

**处理方案**：
1. 短期：在 `pyproject.toml` 中注明，用 `uv add --editable /path/to/feishu` 本地安装
2. 长期：将 feishu 包发布到内部 PyPI 仓库，在 `[tool.uv.sources]` 中配置

---

## 四、代码质量工具链

### 4.1 选型总览

| 维度 | 推荐工具 | 替代方案 | 决策理由 |
|------|---------|---------|---------|
| Linter | **ruff** | flake8 + isort + pyupgrade | 一个工具替代三个，10-100x 快 |
| Formatter | **ruff format** | black | 与 ruff 同源，一个工具链 |
| Type Checker | **mypy** | pyright | 社区更大、CI 集成成熟；pyright 更快但需 Node |

### 4.2 ruff 配置

追加到 `pyproject.toml`：

```toml
[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "SIM", # flake8-simplify
    "TCH", # flake8-type-checking (imports in TYPE_CHECKING blocks)
    "RUF", # ruff-specific rules
]
ignore = [
    "E501",  # 行长度由 formatter 处理，linter 不报
    "B008",  # 不在函数参数默认值中做函数调用——大量 config 用此模式
]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]   # 允许未使用的 import（包的 re-export）
"config.py" = ["E501"]     # 长行在配置文件中常见

[tool.ruff.format]
quote-style = "double"
indent-style = "space"
skip-magic-trailing-comma = false
line-ending = "auto"
```

### 4.3 mypy 配置

追加到 `pyproject.toml`：

```toml
[tool.mypy]
python_version = "3.10"
strict = false
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false       # 第一阶段关闭，先让存量代码通过
disallow_incomplete_defs = false    # 同上
check_untyped_defs = true
no_implicit_optional = true
warn_redundant_casts = true
warn_unused_ignores = true
show_error_codes = true

[[tool.mypy.overrides]]
# 老代码模块先排除，逐步纳管
module = [
    "analysis.ma60_crowding_analysis.*",
    "analysis.backtest.*",
    "evaluator_fixed",
    "temp_fix",
    "backup_*",
]
ignore_errors = true

[[tool.mypy.overrides]]
# 缺少 stub 的第三方库
module = [
    "baostock",
    "akshare",
    "yfinance",
]
ignore_missing_imports = true
```

### 4.4 渐进式类型覆盖策略

| 阶段 | 目标 | 配置 |
|------|------|------|
| **Phase 1**（本周） | CI 能运行，存量代码零修改通过 | `disallow_untyped_defs = false` |
| **Phase 2**（第 2-4 周） | 新代码强制类型标注 | 新模块 `disallow_untyped_defs = true` |
| **Phase 3**（第 2-3 月） | 老代码逐个文件补类型，每补一个就从 ignore 列表移除 | 逐文件升级 |
| **Phase 4**（第 4-6 月） | 全量严格模式就绪 | `strict = true` |

### 4.5 裸 except 清理策略

当前 477 处裸 `except:` / `except Exception:`，不能一次全改（容易引入新 bug）。

**清理顺序**：
1. 优先改 `data/` 和 `domain/`（数据层，影响面最大）
2. 然后 `analysis/`（计算层）
3. 最后 `scripts/`（入口脚本）

**替换规则**：
```python
# 之前
try:
    result = fetch_data()
except:
    result = None

# 之后
try:
    result = fetch_data()
except (ConnectionError, TimeoutError, ValueError) as e:
    logger.warning("数据获取失败", exc_info=e)
    result = None
```

---

## 五、CI/CD 流水线

### 5.1 流水线架构

```
PR 触发 ──► lint + type-check + test ──► ✅ / ❌
                                               │
main 合入 ──────────────────────────────────► deploy (ECS)
                                               │
Cron (每日) ───────────────────────────────► data-pipeline
```

### 5.2 GitHub Actions 配置

#### 5.2.1 PR 质量门禁

文件：`.github/workflows/ci.yml`

```yaml
name: CI

on:
  pull_request:
    branches: [main]
  push:
    branches: [main]

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true

      - name: Install Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --all-extras

      - name: Lint (ruff)
        run: uv run ruff check .

      - name: Format check (ruff)
        run: uv run ruff format --check .

      - name: Type check (mypy)
        run: uv run mypy .

      - name: Tests
        run: uv run pytest --cov=. --cov-report=xml --cov-report=term

      - name: Upload coverage
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
```

#### 5.2.2 定时数据管线

文件：`.github/workflows/data-pipeline.yml`

```yaml
name: Data Pipeline

on:
  schedule:
    - cron: "30 22 * * 1-5"    # 工作日 22:30 CST = 14:30 UTC
  workflow_dispatch:            # 手动触发

jobs:
  pipeline:
    runs-on: ubuntu-latest
    timeout-minutes: 45
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true

      - name: Run data pipeline
        run: uv run python scripts/run_daily.py
        env:
          TUSHARE_TOKEN: ${{ secrets.TUSHARE_TOKEN }}
          FEISHU_TOOL: ${{ secrets.FEISHU_TOOL }}
```

#### 5.2.3 部署流水线

文件：`.github/workflows/deploy.yml`

```yaml
name: Deploy

on:
  push:
    branches: [main]
    paths-ignore:
      - "docs/**"
      - "*.md"

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4

      - name: Deploy to ECS
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.ECS_HOST }}
          username: ${{ secrets.ECS_USER }}
          key: ${{ secrets.ECS_SSH_KEY }}
          script: |
            cd ~/.hermes/investment_system
            git pull origin main
            uv sync
            sudo systemctl restart hermes-server
```

### 5.3 GitHub Secrets 配置

需要在仓库 Settings → Secrets and variables → Actions 中配置：

| Secret 名称 | 说明 |
|-------------|------|
| `TUSHARE_TOKEN` | Tushare API Token |
| `ECS_HOST` | ECS 主机 IP |
| `ECS_USER` | SSH 用户 |
| `ECS_SSH_KEY` | SSH 私钥 |
| `FEISHU_TOOL` | 飞书工具路径/凭据 |

---

## 六、分支策略与提交规范

### 6.1 分支策略：Trunk-based Development

```
main ─────────────────────●─────●─────●─────●──►
                           \   /     /    /
feature/xxx ───────────────●──●     /    /
feature/yyy ───────────────────────●────●
```

**规则**：
- `main` 是唯一长期分支，始终保持可部署
- 所有修改通过 feature 分支提交，合并前必须通过 CI
- feature 分支生命周期不超过 3 天（小步快合）
- 禁止直接 push 到 `main`

```bash
# 分支命名规范
feature/factor-engine-refactor
fix/api-timeout-bug
chore/update-dependencies
docs/engineering-foundation
```

### 6.2 提交规范（扩展语义化提交）

基于已有的语义化风格，扩展为 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
<type>(<scope>): <subject>

[body]

[footer]
```

| type | 说明 | 示例 |
|------|------|------|
| `feat` | 新功能 | `feat(factor): 新增存货周转率因子` |
| `fix` | Bug 修复 | `fix(data): 修复港股停牌日取数异常` |
| `refactor` | 重构 | `refactor(engine): 提取因子归一化公共方法` |
| `perf` | 性能优化 | `perf(cache): 批量写入减少 I/O` |
| `docs` | 文档 | `docs(design): 新增工程化基础方案` |
| `chore` | 构建/工具 | `chore(deps): 升级 numpy 到 1.26` |
| `test` | 测试 | `test(backtest): 补回测收益计算测试` |
| `style` | 格式 | `style: ruff format 全量格式化` |
| `ci` | CI/CD | `ci: 新增 PR 质量门禁 workflow` |

**scope 建议**：`factor`, `data`, `engine`, `strategy`, `api`, `dashboard`, `news`, `etf`, `config`

### 6.3 GitHub 分支保护规则

在 Settings → Branches → Add rule 中配置：

- **Branch name pattern**: `main`
- **Require a pull request before merging**: ✅
- **Require status checks to pass before merging**: ✅
  - `quality (lint, type-check, test)`
- **Require conversation resolution before merging**: ✅
- **Do not allow bypassing the above settings**: ✅

---

## 七、版本管理与 CHANGELOG

### 7.1 语义化版本（SemVer）

采用 `MAJOR.MINOR.PATCH` 格式，替换当前的 `vYYYY.MM.DD` 日期版本：

| 版本号 | 触发条件 | 示例 |
|--------|---------|------|
| MAJOR | 不兼容的 API 变更、策略逻辑重大重构 | `4.0.0` |
| MINOR | 向后兼容的新功能、新因子、新面板 | `3.4.0` |
| PATCH | 向后兼容的 Bug 修复、数据源修复 | `3.3.1` |

**当前版本**：`3.3.0`（对应 `__init__.py:8` 中的 `__version__ = "3.3.0"`）

### 7.2 CHANGELOG 自动化

已有 `CHANGELOG.md`，引入 [git-cliff](https://github.com/orhun/git-cliff) 自动生成：

```bash
# 安装
uv tool install git-cliff
```

配置文件 `cliff.toml`：

```toml
[changelog]
header = "# Changelog\n\n"
body = """
## [{{ version }}] - {{ timestamp | date(format="%Y-%m-%d") }}

{% for group, commits in commits | group_by(attribute="group") %}
### {{ group | upper_first }}
{% for commit in commits %}
- {{ commit.message | split(pat="\n") | first | trim }}
{%- endfor %}
{% endfor %}
"""
trim = true
footer = ""

[git]
conventional_commits = true
filter_unconventional = false
commit_parsers = [
    { message = "^feat", group = "Features" },
    { message = "^fix", group = "Bug Fixes" },
    { message = "^refactor", group = "Refactoring" },
    { message = "^perf", group = "Performance" },
    { message = "^docs", group = "Documentation" },
    { message = "^chore", group = "Chores" },
    { message = "^test", group = "Testing" },
    { message = "^style", group = "Styling" },
    { message = "^ci", group = "CI/CD" },
]
```

**发版流程**：
```bash
# 1. 更新版本号
sed -i 's/__version__ = "3.3.0"/__version__ = "3.4.0"/' __init__.py

# 2. 生成 CHANGELOG
git cliff -o CHANGELOG.md --tag v3.4.0

# 3. 提交 + 打 tag
git add __init__.py CHANGELOG.md
git commit -m "chore(release): v3.4.0"
git tag -a v3.4.0 -m "v3.4.0 - 新增XXX功能"
git push --follow-tags
```

---

## 八、Pre-commit 钩子

### 8.1 配置文件

文件：`.pre-commit-config.yaml`

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: check-json
      - id: check-toml
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: detect-private-key          # 防止私钥提交
      - id: detect-aws-credentials      # 防止 AWS 凭据提交
      - id: check-added-large-files
        args: ["--maxkb=500"]

  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ["--baseline", ".secrets.baseline"]

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: ["--fix"]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0
    hooks:
      - id: mypy
        additional_dependencies: [numpy, pandas, types-requests]
        args: ["--ignore-missing-imports"]
```

### 8.2 初始化

```bash
# 安装 pre-commit
uv tool install pre-commit
# 或
uv sync --group dev

# 安装 git hooks
pre-commit install --install-hooks

# 首次运行全量检查
pre-commit run --all-files

# 生成 detect-secrets 基线
detect-secrets scan > .secrets.baseline
# 手动审查 .secrets.baseline，将 config.py 中的已知 token 标记为已审计
```

### 8.3 敏感信息基线处理

`config.py` 中的 Tushare Token 会被 `detect-secrets` 检出。按 11.1 节方案迁移到环境变量后，该告警自然消失。在此之前，将基线中的该条目标记为已审计：

```bash
detect-secrets audit .secrets.baseline
# 交互式操作：对 config.py 的 token 行，选择 [y] 标记为已知
```

---

## 九、日志标准化

### 9.1 现状与问题

当前有 827 处输出语句，大部分是 `print()`（69 个文件），只有少数模块用了 `logging`。问题：
- `print()` 无法区分级别（DEBUG / INFO / WARNING / ERROR）
- 无法重定向到文件
- 生产环境排查只能看终端输出
- 格式不统一，难以被日志采集系统（如 Loki / ELK）解析

### 9.2 方案：python-json-logger + 标准 logging

选择 `python-json-logger` 而非 `structlog` 的理由：
- structlog 功能强但概念多（bound logger、processor chain），对当前代码改动量大
- `python-json-logger` 只是标准 logging 的 JSON Formatter，对现有 `logging.getLogger()` 调用改动最小
- Hermes 不需要 structlog 的高级特性（上下文传播、异步支持），JSON 结构化输出已够用

### 9.3 统一日志配置

新建文件：`core/logging_config.py`

```python
import logging
import sys
from pythonjsonlogger import jsonlogger

def setup_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # 抑制外部库的噪音日志
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("yfinance").setLevel(logging.WARNING)
    logging.getLogger("baostock").setLevel(logging.WARNING)
```

### 9.4 迁移策略

| 文件类型 | print → logger 迁移方式 |
|---------|------------------------|
| 数据层、计算层（`data/`, `analysis/`） | 引入 `logger = logging.getLogger(__name__)`，`print()` → `logger.info()` |
| 入口脚本（`scripts/`） | 文件顶部调用 `setup_logging()`，`print()` → `logger.info()` |
| 调试输出 | `print(f"DEBUG: ...")` → `logger.debug(...)` |
| 用户可见输出（如报告） | 保留 `print()` 或改为专用输出函数 |

### 9.5 JSON 日志输出示例

```json
{
  "asctime": "2026-07-03T14:30:00",
  "name": "data.data_layer",
  "levelname": "INFO",
  "message": "A股日线数据获取完成",
  "stock_count": 245,
  "duration_ms": 3200
}
```

第 5 个字段由业务代码传入 `extra` 参数：

```python
logger.info("A股日线数据获取完成", extra={"stock_count": 245, "duration_ms": 3200})
```

---

## 十、.gitignore 补全

当前 `.gitignore` 已有 14 条规则，需要补充以下条目：

```gitignore
# IDE
.idea/

# Backup directories
backup_*/

# AI agent work directories
.omo/
.sisyphus/
.hermes/

# Environment variables (keep .env.example)
.env
.env.local
.env.*.local

# OS
.DS_Store
Thumbs.db

# Python cache (extend existing)
*.py[cod]
*.egg-info/
dist/
build/

# Coverage
.coverage
coverage.xml
htmlcov/
.pytest_cache/

# Secrets baseline (allowed: the audited baseline yes, raw scans no)
.secrets.baseline

# mypy
.mypy_cache/

# ruff
.ruff_cache/
```

**注意**：
- `*.json` 的黑名单规则（第 10 行）过于激进，会导致数据快照（`data/*.json`）被忽略。建议改为白名单模式或仅排除根目录下的特定 json。
- 当前 `!config.json` 白名单只能解救 `config.json`，但 `data/` 目录下的 JSON 文件也被排除，需要核查是否有必要。

### 建议的 .gitignore 完整版本

将以上新增条目追加到现有 `.gitignore` 末尾，同时调整第 10-11 行：

```diff
- *.json
- !config.json
+ # 排除非数据类的 JSON 文件
+ /_*.json
```

---

## 十一、安全加固

### 11.1 移除硬编码凭证

**当前问题**：`config.py:16` 和 `core/secrets.py:14` 中存在硬编码 Tushare Token（`a123a8e0...`），以及飞书 open_id、群聊 ID 等。

**方案**：

```bash
# 1. 创建 .env.example（模板，可提交）
cat > .env.example << 'EOF'
TUSHARE_TOKEN=your_token_here
FEISHU_FOLDER_TOKEN=your_folder_token
FEISHU_USER_OPENID=your_openid
FEISHU_GROUP_CHAT=your_group_chat
FEISHU_TOOL=/home/admin/.hermes/node_modules/.bin/feishu-tool
HERMES_BASE=/home/admin/.hermes/investment_system
EOF

# 2. 修改 config.py，从环境变量读取
# 已在 core/secrets.py 中实现，只需删除 config.py 中的硬编码值

# 3. 创建 .env（加入 .gitignore，不提交）
cp .env.example .env
# 编辑 .env 填入真实值

# 4. 生产环境：ECS 上通过 systemd EnvironmentFile 或 export 注入
```

修改 `config.py`，移除硬编码 token：

```python
# 之前
TUSHARE_TOKEN = "a123a8e0b24ac30890b65c6e83a8211a7309647066fd786b541873b3"

# 之后
import os
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
if not TUSHARE_TOKEN:
    raise RuntimeError("TUSHARE_TOKEN 环境变量未设置")
```

### 11.2 GitHub Secret Scanning

GitHub 会自动扫描仓库中的已知 token 格式。如果 Tushare token 已被推送到公开仓库，需要：
1. 立即在 Tushare 控制台吊销旧 token，生成新的
2. 用 `git filter-repo` 清除历史中的 token（或 `BFG Repo-Cleaner`）
3. 配置新 token 到 GitHub Secrets

---

## 十二、实施时间线

### Phase 1: 基础打底（第 1 周）

**目标**：依赖可复现，代码格式统一

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 创建 `pyproject.toml`，运行 `uv lock` / `uv sync` | 可复现的依赖环境 | P0 |
| 创建 `requirements.txt`（向后兼容） | 传统部署可用 | P0 |
| 配置 ruff，运行 `ruff check --fix && ruff format` | 统一代码风格 | P0 |
| 补全 `.gitignore` | 防止 IDE/AI 目录误提交 | P0 |
| 移除 `config.py` 中的硬编码凭证 | Token 安全 | P0 |

### Phase 2: 质量门禁（第 2 周）

**目标**：每次 PR 自动检查，main 分支受保护

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 创建 `.github/workflows/ci.yml` | PR lint + format + type check | P1 |
| 配置 mypy（Phase 1 宽松模式） | 类型检查运行 | P1 |
| 配置 `.pre-commit-config.yaml` | 提交前本地检查 | P1 |
| 设置 GitHub 分支保护规则 | main 分支受保护 | P1 |
| 创建 `.env.example` | 环境变量模板 | P1 |

### Phase 3: 部署与定时任务（第 3 周）

**目标**：自动化部署、定时数据管线运行

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 创建 `.github/workflows/deploy.yml` | 合入 main 自动部署 | P1 |
| 创建 `.github/workflows/data-pipeline.yml` | 工作日定时跑日报 | P2 |
| ECS 上配置 systemd service | 守护进程管理 | P2 |
| 创建 `Dockerfile` | 容器化部署选项 | P2 |

### Phase 4: 代码卫生（第 4-8 周）

**目标**：消灭技术债，提升代码可维护性

| 任务 | 产出 | 优先级 |
|------|------|--------|
| 逐文件替换 `print()` → `logger.*()` | 结构化日志 | P2 |
| 创建 `core/logging_config.py` | 统一日志配置 | P2 |
| 清理裸 `except:`（data/ → analysis/ → scripts/） | 精准异常处理 | P2 |
| mypy Phase 2：新模块强类型 | 类型覆盖率提升 | P3 |
| 生成 `.secrets.baseline` | detect-secrets 基线 | P3 |

### Phase 5: 长期治理（第 3-6 月）

| 任务 | 说明 |
|------|------|
| mypy Phase 3-4：全量严格模式 | 逐文件从 ignore 列表移除 |
| `git filter-repo` 清除历史中的 token | 安全彻底清理 |
| 引入 git-cliff 自动生成 CHANGELOG | 发版自动化 |
| 补测试用例（pytest） | `pytest-cov` 覆盖率 > 60% |
| feishu 包纳入 pyproject.toml 依赖管理 | 内部源配置 |

---

## 附录 A：完整 pyproject.toml 参考

将第三、四章的各配置段合并后的完整文件：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "hermes-investment"
version = "3.3.0"
description = "面基三源融合 · 量化投资系统"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "MIT"}
authors = [{name = "wenliang-xiao"}]
classifiers = [
    "Development Status :: 4 - Beta",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
dependencies = [
    "numpy>=1.24,<2",
    "pandas>=2.0,<3",
    "scipy>=1.10,<2",
    "yfinance>=0.2.40",
    "baostock>=0.8.8",
    "akshare>=1.12.0",
    "requests>=2.31,<3",
    "fastapi[standard]>=0.110,<1",
    "uvicorn[standard]>=0.29,<1",
    "python-dotenv>=1.0,<2",
    "python-json-logger>=2.0,<3",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0,<9",
    "pytest-cov>=5.0",
    "ruff>=0.5,<1",
    "mypy>=1.10,<2",
    "pre-commit>=3.7,<4",
]

[project.scripts]
hermes-server = "scripts.portfolio_server:main"
hermes-daily = "scripts.run_daily:main"

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.ruff.lint]
select = ["E", "W", "F", "I", "N", "UP", "B", "C4", "SIM", "TCH", "RUF"]
ignore = ["E501", "B008"]

[tool.ruff.lint.per-file-ignores]
"__init__.py" = ["F401"]
"config.py" = ["E501"]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.mypy]
python_version = "3.10"
strict = false
warn_return_any = true
warn_unused_configs = true
disallow_untyped_defs = false
check_untyped_defs = true
no_implicit_optional = true
show_error_codes = true

[[tool.mypy.overrides]]
module = [
    "analysis.ma60_crowding_analysis.*",
    "evaluator_fixed",
    "temp_fix",
]
ignore_errors = true

[[tool.mypy.overrides]]
module = ["baostock", "akshare", "yfinance"]
ignore_missing_imports = true

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```

## 附录 B：文件清单

工程化建设需要新建或修改的文件汇总：

| 文件 | 操作 | 说明 |
|------|------|------|
| `pyproject.toml` | **新建** | 项目元数据 + 依赖 + 工具配置 |
| `requirements.txt` | **新建** | 向后兼容的依赖列表（由 uv export 生成） |
| `.env.example` | **新建** | 环境变量模板 |
| `.github/workflows/ci.yml` | **新建** | PR 质量门禁 |
| `.github/workflows/deploy.yml` | **新建** | 自动部署 |
| `.github/workflows/data-pipeline.yml` | **新建** | 定时数据管线 |
| `.pre-commit-config.yaml` | **新建** | Git 提交前检查 |
| `cliff.toml` | **新建** | CHANGELOG 自动生成配置 |
| `core/logging_config.py` | **新建** | 统一日志配置 |
| `.secrets.baseline` | **新建** | detect-secrets 基线 |
| `.gitignore` | **修改** | 补全缺失条目 |
| `config.py` | **修改** | 移除硬编码凭证 |
