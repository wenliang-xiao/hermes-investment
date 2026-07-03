# 安全加固方案

> **适用版本**: v2026.07.02+
> **仓库地址**: <https://github.com/wenliang-xiao/hermes-investment>（公开仓库）
> **编写日期**: 2026-07-03
> **状态**: 待实施

---

## 一、概述

Hermes Investment（面基三源融合投资系统）是一个 A 股 + 港股 + 美股量化投资系统，包含 FastAPI Dashboard 服务器、多源数据路由、飞书报告推送等功能。系统已上线运行，通过 `scripts/portfolio_server.py` 在 `0.0.0.0:8686` 对外提供 Web 服务。

安全审计发现以下**需立即修复**的问题：

| 优先级 | 数量 | 典型问题 |
|--------|------|---------|
| 🔴 致命 | 2 | API Token 硬编码在源码中并已推送到公开 GitHub 仓库；`pickle.load()` 反序列化任意代码执行风险 |
| 🟠 高 | 3 | 飞书 Bot Token 以硬编码默认值泄露；`os.environ[]` 读取环境变量无兜底导致 KeyError 运行时崩溃 |
| 🟡 中 | 4 | Dashboard 无认证/无限流/无输入校验；`.gitignore` 规则不完整；缺少 `.env.example` |
| 🟢 低 | 1 | 缺少 pre-commit 密钥扫描 Hook |

### 文档结构

- **第二章（威胁模型）**——谁可能攻击、攻击面有哪些
- **第三章（凭据清单）**——逐一列出所有凭据的定义位置和当前保护等级
- **第四章（逐项修复方案）**——每个凭据的迁移步骤和验证方法
- **第五章（密钥管理架构）**——环境变量 vs Vault vs 云密钥服务的方案对比
- **第六章（Pickle 安全性）**——风险分析、替代方案选型
- **第七章（API 安全）**——输入校验、CORS、限流、认证
- **第八章（Git 卫生）**——`.gitignore` 更新、pre-commit 密钥扫描
- **第九章（实施清单）**——按优先级排序的可执行步骤
- **第十章（审计与验证）**——修复后的验证流程和定期审计机制

---

## 二、威胁模型

### 2.1 攻击者画像

| 角色 | 动机 | 能力 |
|------|------|------|
| **路人/脚本小子** | 扫描 GitHub 公开仓库寻找泄露的 API Token | 自动化扫描工具（如 GitLeaks、TruffleHog），能批量探测公网 IP 的开放端口 |
| **恶意内部人员** | 获取 Tushare/飞书 API 权限以窃取数据或发送伪造消息 | 已知系统内部结构，可能修改缓存文件 |
| **供应链攻击者** | 通过污染依赖或缓存文件执行任意代码 | 篡改 pickle 缓存文件或 PyPI 包 |

### 2.2 攻击面

```
┌──────────────────────────────────────────────────────────────┐
│                        攻击面拓扑                              │
├──────────────┬──────────────┬──────────────┬─────────────────┤
│   Git 历史   │  Dashboard   │  本地缓存    │   依赖/环境      │
│              │  (8686端口)  │              │                 │
├──────────────┼──────────────┼──────────────┼─────────────────┤
│ • 硬编码TOKEN│ • 无认证     │ • pickle RCE │ • 缺少.env.     │
│   在公开仓库 │ • 无限流     │ • 缓存文件   │   example       │
│ • commit     │ • 无输入校验 │   无完整性   │ • os.environ[]  │
│   历史中残留 │ • 暴露内网IP │   验证       │   无兜底崩溃    │
│ • .gitignore │ • 错误信息   │              │                 │
│   不全       │   泄露路径   │              │                 │
└──────────────┴──────────────┴──────────────┴─────────────────┘
```

#### 攻击面 1：Git 历史泄露

`TUSHARE_TOKEN` 和三个飞书凭据（`FEISHU_FOLDER_TOKEN`、`FEISHU_USER_OPENID`、`FEISHU_GROUP_CHAT`）以明文硬编码形式存在于 `config.py` 和 `core/secrets.py` 中，并且这些文件已被提交到**公开** GitHub 仓库。即使从当前代码中删除，Git 历史中仍然保留这些凭据。

**影响**：
- Tushare Token：攻击者可使用 token 无限量调用 Tushare Pro API，消耗接口配额、获取行情数据，甚至可能窃取同账号下的个人信息。如果账号升级到更高积分等级，损失更大。
- 飞书凭据：攻击者可向指定飞书群发送任意消息（钓鱼、虚假交易信号），或读取/修改飞书文档。

#### 攻击面 2：Dashboard API（`0.0.0.0:8686`）

`scripts/portfolio_server.py` 绑定了 `0.0.0.0`，所有网络接口均可访问。Dashboard 未实施任何认证机制，任何能访问该端口的人都可以：
- 查看所有持仓明细、交易记录和历史盈亏
- 调用 `/api/metrics` 获取绩效指标
- 查看票池、ETF 组合和新闻数据

虽然有 `*.json` 的 `.gitignore` 规则（排除了大部分数据文件），但 `shadow_account.json` 和 `trading_signals.json` 等敏感交易数据文件仍然可能被读取。

#### 攻击面 3：Pickle 反序列化

`data/data_router.py` 的 `cachedio` 装饰器使用 `pickle.load()` 读取缓存文件。`pickle` 模块在反序列化时可以执行任意 Python 代码，如果缓存文件被篡改（本地提权或供应链投毒），攻击者可以获得与 Python 进程相同权限的代码执行能力。

#### 攻击面 4：环境变量缺失导致运行时崩溃

`output/report_v6.py:66-68` 和 `scripts/deep_research.py:44-45` 使用 `os.environ["FEISHU_APP_ID"]` 和 `os.environ["FEISHU_APP_SECRET"]`（方括号语法），如果环境变量未设置，会抛出 `KeyError` 导致程序崩溃，且无法给出友好的错误提示。

---

## 三、凭据清单

### 3.1 完整清单

| # | 凭据名称 | 定义位置（文件:行号） | 当前保护方式 | 风险等级 |
|---|---------|---------------------|-------------|---------|
| 1 | `TUSHARE_TOKEN` | `config.py:16` | **硬编码明文**（无环境变量回退） | 🔴 致命 |
| 2 | `TUSHARE_TOKEN`（第二副本） | `core/secrets.py:14` | `os.environ.get()` 但**默认值暴露明文** | 🔴 致命 |
| 3 | `FEISHU_FOLDER_TOKEN` | `config.py:20` | **硬编码明文** | 🟠 高 |
| 4 | `FEISHU_FOLDER_TOKEN`（第二副本） | `core/secrets.py:17` | `os.environ.get()` 但**默认值暴露明文** | 🟠 高 |
| 5 | `FEISHU_USER_OPENID` | `config.py:21` | **硬编码明文** | 🟠 高 |
| 6 | `FEISHU_USER_OPENID`（第二副本） | `core/secrets.py:18` | `os.environ.get()` 但**默认值暴露明文** | 🟠 高 |
| 7 | `FEISHU_GROUP_CHAT` | `config.py:22` | **硬编码明文** | 🟠 高 |
| 8 | `FEISHU_GROUP_CHAT`（第二副本） | `core/secrets.py:19` | `os.environ.get()` 但**默认值暴露明文** | 🟠 高 |
| 9 | `FEISHU_APP_ID` | `output/report_v6.py:67`<br>`scripts/deep_research.py:44` | `os.environ["KEY"]`（无兜底，KeyError 崩溃） | 🟠 高 |
| 10 | `FEISHU_APP_SECRET` | `output/report_v6.py:68`<br>`scripts/deep_research.py:45` | `os.environ["KEY"]`（无兜底，KeyError 崩溃） | 🟠 高 |
| 11 | `JQDATA_USER` | `core/secrets.py:11` | `os.environ.get()` → 空字符串 | 🟢 低 |
| 12 | `JQDATA_PASS` | `core/secrets.py:12` | `os.environ.get()` → 空字符串 | 🟢 低 |

### 3.2 重复定义问题

凭据 #1-#8 在两个文件中重复定义（`config.py` 和 `core/secrets.py`），存在以下问题：

- **维护困难**：修改凭据需要改两个文件
- **不一致风险**：两个文件可能引用不同版本的 Token
- **实际使用路径**：`config.py` 的凭据被各模块通过 `from investment_system import config as cfg` 引用；`core/secrets.py` 的凭据使用 `os.environ.get()` 模式，但默认值就是硬编码明文

### 3.3 当前使用模式分析

```
config.py (硬编码) ──→ output/report_v6.py (cfg.FEISHU_*)
                   ──→ scripts/deep_research.py (?)
                   ──→ 其他模块 (cfg.TUSHARE_TOKEN)

core/secrets.py     ──→ （可能被其他模块引用）
(env.get + 硬编码默认)

report_v6.py        ──→ os.environ["FEISHU_APP_ID"]  ← KeyError 风险
deep_research.py    ──→ os.environ["FEISHU_APP_SECRET"] ← KeyError 风险
```

---

## 四、逐项修复方案

### 4.1 Tushare Token（凭据 #1, #2）

**当前状态**：`config.py:16` 硬编码明文 `"a123a8e0b24ac30890b65c6e83a8211a7309647066fd786b541873b3"`

**修复步骤**：

1. **立即轮换**：登录 [tushare.pro](https://tushare.pro) → 个人中心 → 接口 TOKEN → 点击"重置 Token"，获取新 Token。旧的已泄露 Token 会立即失效。

2. **移除硬编码**（`config.py:16`）：
   ```python
   # 修改前
   TUSHARE_TOKEN = "a123a8e0b24ac30890b65c6e83a8211a7309647066fd786b541873b3"

   # 修改后
   TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
   ```

3. **修改 `core/secrets.py:14`**——移除默认值中的明文：
   ```python
   # 修改前
   TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "a123...")

   # 修改后
   TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
   if not TUSHARE_TOKEN:
       raise RuntimeError("TUSHARE_TOKEN 环境变量未设置")
   ```

4. **统一入口**：决定以哪个文件为唯一凭据来源。建议——所有模块统一通过 `core/secrets.py` 读取凭据，`config.py` 中删除重复定义，改为 `from core.secrets import TUSHARE_TOKEN`。

5. **清除 Git 历史**（见 4.6）。

### 4.2 飞书凭据（凭据 #3-#8）

**当前状态**：`config.py:20-22` 和 `core/secrets.py:17-19` 中硬编码以下值：

| 变量 | 泄露值（部分） |
|------|--------------|
| `FEISHU_FOLDER_TOKEN` | `QhIOfB63...` |
| `FEISHU_USER_OPENID` | `ou_e03d56...` |
| `FEISHU_GROUP_CHAT` | `oc_4c9d64...` |

**修复步骤**：

1. **轮换飞书凭据**：
   - 在飞书开放平台重新生成 `FOLDER_TOKEN`
   - `USER_OPENID` 是用户唯一标识，不可轮换，但确认其未滥用即可
   - 如有必要，重新创建飞书群获取新的 `GROUP_CHAT` ID

2. **修改 `config.py:19-22`**：
   ```python
   FEISHU_FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")
   FEISHU_USER_OPENID = os.environ.get("FEISHU_USER_OPENID", "")
   FEISHU_GROUP_CHAT = os.environ.get("FEISHU_GROUP_CHAT", "")
   ```

3. **修改 `core/secrets.py:17-19`**——同样移除默认值明文，统一加启动校验。

4. **调用方校验**：在 `output/report_v6.py` 和其他引用这些变量的模块中，在使用前校验非空：
   ```python
   import os
   FEISHU_FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")
   if not FEISHU_FOLDER_TOKEN:
       raise RuntimeError("FEISHU_FOLDER_TOKEN 环境变量未设置，无法写入飞书文档")
   ```

### 4.3 FEISHU_APP_ID / FEISHU_APP_SECRET（凭据 #9, #10）

**当前状态**：`output/report_v6.py:66-68` 和 `scripts/deep_research.py:44-45` 使用 `os.environ["FEISHU_APP_ID"]`——无方括号兜底，变量缺失时抛出 `KeyError`。

**修复步骤**：

在 `output/report_v6.py` 和 `scripts/deep_research.py` 中，**统一的飞书 Token 获取逻辑**应该抽取为一个函数，避免在两处重复：

```python
def _get_feishu_tenant_token():
    app_id = os.environ.get("FEISHU_APP_ID")
    app_secret = os.environ.get("FEISHU_APP_SECRET")
    if not app_id or not app_secret:
        raise RuntimeError(
            "FEISHU_APP_ID 和 FEISHU_APP_SECRET 环境变量未设置。"
            "请复制 .env.example 为 .env 并填入实际值。"
        )
    data = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=data, headers={"Content-Type": "application/json"}
    )
    return json.loads(urllib.request.urlopen(req).read())["tenant_access_token"]
```

### 4.4 创建 .env.example 文件

在项目根目录创建 `.env.example`，列出所有需要的环境变量及占位值：

```bash
# Hermes Investment 环境变量配置
# 复制此文件为 .env 并填入实际值:
#   cp .env.example .env

# Tushare Pro API Token
# 获取: https://tushare.pro → 个人中心 → 接口TOKEN
TUSHARE_TOKEN=your_tushare_token_here

# 飞书开放平台应用凭据
# 获取: https://open.feishu.cn → 应用 → 凭证与基础信息
FEISHU_APP_ID=cli_xxxxxxxxxxxx
FEISHU_APP_SECRET=your_app_secret_here

# 飞书文档/群聊配置
FEISHU_FOLDER_TOKEN=your_folder_token_here
FEISHU_USER_OPENID=ou_xxxxxxxxxxxx
FEISHU_GROUP_CHAT=oc_xxxxxxxxxxxx

# 飞书工具路径（可选，默认使用全局安装）
FEISHU_TOOL=/home/admin/.hermes/node_modules/.bin/feishu-tool

# JoinQuant 数据源（可选）
JQDATA_USER=
JQDATA_PASS=

# Hermes 数据根目录（可选，默认 /home/admin/.hermes/investment_system）
HERMES_BASE=/home/admin/.hermes/investment_system
```

### 4.5 运行时环境变量加载

在项目入口点（`config.py` 或新建 `core/env.py`）中，使用 `python-dotenv` 自动加载 `.env` 文件：

```python
# core/env.py
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv 未安装，依赖系统环境变量
```

在 `requirements.txt` 中添加 `python-dotenv` 依赖。

### 4.6 清除 Git 历史中的凭据

即使从当前代码中删除硬编码凭据，它们仍然存在于 Git 提交历史中。需要使用 `git filter-branch` 或 `BFG Repo-Cleaner` 重写历史。

**推荐方案**——使用 `git filter-repo`：

```bash
# 1. 安装 git-filter-repo
pip install git-filter-repo

# 2. 创建替换文件 replacements.txt
#    格式: 旧值==>新值
echo 'a123a8e0b24ac30890b65c6e83a8211a7309647066fd786b541873b3==>REDACTED_TUSHARE_TOKEN' > /tmp/replacements.txt
echo 'QhIOfB63Sl6Kqmd81fycjR6jnDd==>REDACTED_FEISHU_FOLDER_TOKEN' >> /tmp/replacements.txt
echo 'ou_e03d56632de9b44263adfc018f9d6e4d==>REDACTED_FEISHU_USER_OPENID' >> /tmp/replacements.txt
echo 'oc_4c9d6445fab7f3a2ada0c410f3aa7043==>REDACTED_FEISHU_GROUP_CHAT' >> /tmp/replacements.txt

# 3. 执行替换（⚠️ 会重写所有历史）
git filter-repo --replace-text /tmp/replacements.txt --force

# 4. 强制推送到 GitHub（需仓库管理员权限）
git push origin --force --all
git push origin --force --tags
```

> **⚠️ 重要警告**：`git filter-repo` 会重写整个仓库的提交历史。执行前：
> - 备份仓库（`cp -r .git /tmp/git-backup`）
> - 通知所有协作者，强制推送后他们需要重新 clone
> - 确认所有分支和 tag 都已推送

---

## 五、密钥管理架构

### 5.1 方案对比

| 维度 | 环境变量 (.env) | HashiCorp Vault | 云密钥服务 (AWS SSM/Secrets Manager) |
|------|----------------|----------------|--------------------------------------|
| **复杂度** | 极低 | 高（需部署 Vault 服务） | 中（需云账号 + SDK） |
| **安全性** | 中等（文件权限控制） | 高（动态密钥、审计日志） | 高（IAM 权限控制、自动轮换） |
| **运维成本** | 无 | 需维护 Vault 集群 | 按 API 调用计费 |
| **适用场景** | 个人项目、小团队 | 企业级、多服务 | 云原生架构 |
| **密钥轮换** | 手动 | 自动 | 自动（需配置） |
| **版本控制友好** | ✅ `.env` 不入库 | ✅ | ✅ |

### 5.2 推荐方案：环境变量 + .env 文件

对于 Hermes Investment 的规模（单人开发、单机部署），**环境变量方案**是最务实的选择：

```
┌─────────────────────────────────────────────────────┐
│                    密钥管理流程                        │
├─────────────────────────────────────────────────────┤
│                                                       │
│   .env.example ──(cp)──→ .env (不入库，gitignore)     │
│                              │                        │
│                              ▼                        │
│   python-dotenv ──→ os.environ ──→ core/secrets.py   │
│                                          │            │
│                            ┌─────────────┼──────┐    │
│                            ▼             ▼      ▼    │
│                      config.py    report_v6  deep_   │
│                                    .py       research│
│                                                     │
│   服务器部署时：                                       │
│   systemd EnvironmentFile=/opt/hermes/.env            │
│   或 docker run --env-file .env                       │
│                                                       │
└─────────────────────────────────────────────────────┘
```

**实施要点**：

1. `.env` 文件权限设为 `600`（仅 owner 可读写）
2. 生产服务器上不直接放 `.env` 文件，而是通过 systemd `EnvironmentFile` 或容器编排注入
3. `core/secrets.py` 增加启动时校验——必填变量缺失时抛出明确错误而非静默失败

### 5.3 统一凭据入口

重构后，所有凭据由 `core/secrets.py` 统一导出，消除 `config.py` 中的重复定义：

```python
# core/secrets.py — 唯一凭据入口
import os

# 尝试加载 .env
try:
    from dotenv import load_dotenv
    from pathlib import Path
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass

# ─── API Tokens ───
TUSHARE_TOKEN = os.environ.get("TUSHARE_TOKEN", "")
JQDATA_USER = os.environ.get("JQDATA_USER", "")
JQDATA_PASS = os.environ.get("JQDATA_PASS", "")

# ─── 飞书 ───
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_FOLDER_TOKEN = os.environ.get("FEISHU_FOLDER_TOKEN", "")
FEISHU_USER_OPENID = os.environ.get("FEISHU_USER_OPENID", "")
FEISHU_GROUP_CHAT = os.environ.get("FEISHU_GROUP_CHAT", "")
FEISHU_TOOL = os.environ.get("FEISHU_TOOL", "/home/admin/.hermes/node_modules/.bin/feishu-tool")

# ─── 启动校验 ───
_REQUIRED = {
    "TUSHARE_TOKEN": TUSHARE_TOKEN,
}
_MISSING = [k for k, v in _REQUIRED.items() if not v]
if _MISSING:
    raise RuntimeError(
        f"缺少必需环境变量: {', '.join(_MISSING)}\n"
        "请复制 .env.example 为 .env 并填入实际值"
    )
```

---

## 六、Pickle 安全性

### 6.1 风险分析

`data/data_router.py:29-60` 的 `cachedio` 装饰器使用 `pickle` 做数据缓存。`pickle` 不是单纯的数据序列化格式——反序列化时可以执行任意 Python 代码：

```python
# data/data_router.py:50-51
with open(cache_path, "rb") as f:
    return pickle.load(f)  # ⚠️ 任意代码执行风险
```

**攻击场景**：

1. **本地提权**：如果服务器上有低权限用户能写入 `data/cache/` 目录，可放置恶意 pickle 文件，当 Python 进程读取该文件时执行任意代码
2. **供应链投毒**：如果缓存文件来源于不受信任的来源（如共享文件系统、被入侵的备份）
3. **开发环境污染**：开发者本地被植入恶意缓存文件

当前缓存目录为 `data/cache/`，该目录已在 `.gitignore` 中排除（`data/cache/`），但不排除运行时被篡改的可能。

### 6.2 替代方案

| 方案 | 安全性 | 性能 | 迁移成本 | 推荐度 |
|------|-------|------|---------|--------|
| **JSON** | ✅ 无代码执行 | 中等 | 低（需处理 datetime/bytes） | ⭐⭐⭐⭐⭐ |
| **msgpack** | ✅ 无代码执行 | 高（二进制） | 中（需 `msgpack` 库） | ⭐⭐⭐⭐ |
| **parquet** | ✅ 无代码执行 | 最高（列存） | 高（依赖 pandas/pyarrow） | ⭐⭐⭐ |
| **safetensors** | ✅ 专为安全设计 | 高 | 高（主要面向 ML 场景） | ⭐⭐ |
| **pickle + HMAC** | ✅ 防篡改 | 与 pickle 相同 | 低 | ⭐⭐⭐ |

### 6.3 推荐方案：JSON（优先）+ msgpack（备选）

**JSON 方案**——迁移成本最低，兼容性最好：

```python
# data/data_router.py — cachedio 安全版本
import json
import hashlib
import time
import os
from pathlib import Path

_CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
_CACHE_DIR.mkdir(parents=True, exist_ok=True)

def secure_cachedio(ttl_hours: int = 24):
    """安全的缓存装饰器——使用 JSON 序列化，支持基本类型"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key_parts = [func.__name__] + [str(a) for a in args] \
                + [f"{k}={v}" for k, v in sorted(kwargs.items())]
            cache_name = "_".join(key_parts).replace(".", "_").replace("=", "_")[:200]
            cache_path = _CACHE_DIR / f"{cache_name}.json"

            # 检查缓存
            if cache_path.exists():
                age = time.time() - cache_path.stat().st_mtime
                if age < ttl_hours * 3600:
                    try:
                        with open(cache_path, "r") as f:
                            return json.load(f)
                    except (json.JSONDecodeError, ValueError):
                        pass  # 缓存损坏，重新获取

            # 获取数据
            result = func(*args, **kwargs)
            if result is not None:
                with open(cache_path, "w") as f:
                    json.dump(result, f, default=str)  # default=str 处理非标准类型
            return result
        return wrapper
    return decorator
```

**迁移注意事项**：

- JSON 不支持 `datetime`、`bytes`、`None` 键等 Python 特有类型——需要用 `default=str` 或自定义 encoder 处理
- `data/data_router.py` 中 `get_history()` 返回的是 `dict`，JSON 可完全兼容
- `analysis/cost_model.py:52` 中也有 `pickle.load()` 调用，需一并替换

### 6.4 pickle + HMAC 兼容方案（保留 pickle 时的加固）

如果暂时不能替换 pickle，至少加完整性校验防止篡改：

```python
import hmac
import hashlib

_SECRET = os.environ.get("CACHE_HMAC_KEY", "change-me-in-production").encode()

def _sign(data: bytes) -> bytes:
    return hmac.digest(_SECRET, data, hashlib.sha256)

# 写入时
with open(cache_path, "wb") as f:
    payload = pickle.dumps(result)
    f.write(_sign(payload))
    f.write(payload)

# 读取时
with open(cache_path, "rb") as f:
    sig = f.read(32)  # SHA256 HMAC = 32 bytes
    payload = f.read()
    if not hmac.compare_digest(sig, _sign(payload)):
        raise ValueError("缓存文件被篡改")
    return pickle.loads(payload)
```

---

## 七、API 安全

### 7.1 当前状态

`scripts/portfolio_server.py` 暴露以下端点，所有端点均无认证、无限流、无输入校验：

| 端点 | 方法 | 用途 |
|------|------|------|
| `/dashboard` | GET | 主 Dashboard HTML |
| `/comparison` | GET | 三方策略对比 HTML |
| `/api/portfolio` | GET | 模拟盘组合数据 |
| `/api/comparison` | GET | 三方策略对比 JSON |
| `/api/signals` | GET | 实时交易信号 |
| `/api/realtime` | GET | 实时行情 |
| `/api/realtime/positions` | GET | 持仓实时行情 |
| `/api/metrics` | GET | 绩效指标 |
| `/api/simulated` | GET | 三策略模拟盘 |
| `/api/v2/pool` | GET | 三层票池 |
| `/api/v2/etf` | GET | ETF 组合 |
| `/api/v2/news` | GET | 板块新闻 |
| `/api/v2/reports` | GET | 日报链接 |
| `/score_explanation` | GET | 评分体系说明 |

### 7.2 修复方案

#### 7.2.1 输入校验

当前暂无带参数的用户输入端点（全部为 GET 无参或路径参数），但以下端点存在间接风险：

- `/api/v2/pool` 读取文件系统路径——如果未来支持参数化路径，需校验
- `/api/realtime` 和 `/api/realtime/positions` 调用外部数据源——需加超时和错误处理

**基础校验代码**——对所有文件读取端点加路径遍历防护：

```python
from pathlib import Path

SAFE_ROOTS = {ROOT / "data", ROOT / "docs", ROOT / "output"}

def safe_read_json(relative_path: str) -> dict:
    """安全读取 JSON 文件——防止路径遍历攻击"""
    full_path = (ROOT / relative_path).resolve()
    if not any(str(full_path).startswith(str(sr)) for sr in SAFE_ROOTS):
        raise ValueError(f"不允许读取路径: {relative_path}")
    if not full_path.exists():
        return {}
    with open(full_path) as f:
        return json.load(f)
```

#### 7.2.2 CORS 配置

当前无 CORS 头。如果 Dashboard 仅供同源访问（内网 IP 直接访问），可配置严格的 CORS 策略：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://47.85.161.255:8686", "http://localhost:8686"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

#### 7.2.3 限流保护

使用 `slowapi` 对 API 端点实施限流：

```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(429, _rate_limit_exceeded_handler)

@app.get("/api/portfolio")
@limiter.limit("30/minute")
def api_portfolio():
    ...
```

建议的限流策略：

| 端点类别 | 限制 | 说明 |
|---------|------|------|
| Dashboard 页面 | 60/minute | 正常浏览 |
| 实时行情 API | 30/minute | 防止滥用数据源 |
| 组合/信号 API | 30/minute | 正常刷新 |

#### 7.2.4 Dashboard 认证

根据系统使用场景选择合适的认证策略：

**方案 A：简单 Token 认证**（推荐——最小侵入）

```python
from fastapi import HTTPException, Header

API_TOKEN = os.environ.get("DASHBOARD_TOKEN", "")

def verify_token(authorization: str = Header(None)):
    if API_TOKEN and (not authorization or authorization != f"Bearer {API_TOKEN}"):
        raise HTTPException(status_code=401, detail="未授权访问")

@app.get("/api/portfolio")
def api_portfolio(auth=Depends(verify_token)):
    ...
```

前端在 fetch 请求中添加：
```javascript
fetch('/api/portfolio', {
    headers: { 'Authorization': 'Bearer ' + DASHBOARD_TOKEN }
})
```

**方案 B：HTTP Basic Auth**——简单但需 HTTPS

```python
from fastapi.security import HTTPBasic, HTTPBasicCredentials

security = HTTPBasic()

def verify_basic(credentials: HTTPBasicCredentials = Depends(security)):
    correct_user = os.environ.get("DASHBOARD_USER", "admin")
    correct_pass = os.environ.get("DASHBOARD_PASS", "")
    if not (secrets.compare_digest(credentials.username, correct_user) and
            secrets.compare_digest(credentials.password, correct_pass)):
        raise HTTPException(status_code=401)
```

**方案 C：无认证但绑定 localhost**（仅本机访问时适用）

```python
# uvicorn 启动时改为仅绑定 127.0.0.1
uvicorn.run(app, host="127.0.0.1", port=8686)
```

如果 Dashboard 必须暴露在公网（当前 `0.0.0.0:8686`），则推荐方案 A（Token 认证）或方案 B。如果仅本机使用，改为绑定 `127.0.0.1` 并通过 SSH 隧道或 nginx 反向代理访问。

#### 7.2.5 错误信息安全

当前 API 在异常时直接返回 `{"error": str(e)}`，可能会泄露文件系统路径和内部堆栈。应区分生产/开发环境：

```python
import os

DEBUG = os.environ.get("HERMES_DEBUG", "").lower() == "1"

def safe_error(e: Exception) -> dict:
    if DEBUG:
        return {"error": str(e)}
    return {"error": "服务器内部错误，请稍后重试"}
```

---

## 八、Git 卫生

### 8.1 .gitignore 更新

当前 `.gitignore` 缺少以下规则：

```gitignore
# IDE 和编辑器
.idea/
.vscode/
*.swp
*.swo
*~

# 备份文件
backup_*
*.bak
*.backup

# opencode / AI 辅助工具
.omo/
.sisyphus/

# 操作系统
.DS_Store
Thumbs.db

# 凭据（已有 .env，再加一层保护）
*.pem
*.key
```

### 8.2 Pre-commit 密钥扫描

使用 `detect-secrets` 或 `git-secrets` 作为 pre-commit hook，防止新的凭据被意外提交。

**方案：detect-secrets**

```bash
# 安装
pip install detect-secrets

# 初始化（在项目根目录执行）
detect-secrets scan --update .secrets.baseline

# 添加 pre-commit hook (.pre-commit-config.yaml)
cat > .pre-commit-config.yaml << 'EOF'
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.5.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
        exclude: package-lock.json
EOF

# 安装 hook
pre-commit install
```

**方案：git-secrets**

```bash
# 安装 (macOS)
brew install git-secrets

# 在仓库中配置
cd /path/to/hermes-investment
git secrets --install
git secrets --register-aws  # 注册 AWS 模式
# 添加自定义模式
git secrets --add 'TUSHARE_TOKEN\s*=\s*"[a-f0-9]{40,}"'
git secrets --add 'FEISHU_.*\s*=\s*"[A-Za-z0-9_]{15,}"'
git secrets --add 'os\.environ\[\"FEISHU'
```

### 8.3 提交前检查清单

每次提交前执行：

```bash
# 1. 扫描暂存区是否有密钥
git diff --cached | grep -E '(token|secret|password|api.?key|TUSHARE|FEISHU)'

# 2. 运行 detect-secrets
detect-secrets-hook --baseline .secrets.baseline $(git diff --cached --name-only)

# 3. 确认 .env 不在暂存区
git diff --cached --name-only | grep -E '\.env$' && echo "WARNING: .env staged!" && exit 1
```

---

## 九、实施清单

**优先级说明**：
- 🔴 **P0**——立即修复，已有历史泄露
- 🟠 **P1**——本周内完成
- 🟡 **P2**——本月内完成
- 🟢 **P3**——持续优化

| # | 任务 | 优先级 | 预计耗时 | 依赖 |
|---|------|-------|---------|------|
| 1 | **轮换 Tushare Token**——登录 tushare.pro 重置 Token，旧 Token 立即失效 | 🔴 P0 | 5 min | — |
| 2 | **轮换飞书凭据**——重新生成 FOLDER_TOKEN，确认其他凭据未滥用 | 🔴 P0 | 15 min | — |
| 3 | **修改 `config.py`**——移除所有硬编码凭据，改为 `os.environ.get()` | 🔴 P0 | 10 min | #1, #2 |
| 4 | **修改 `core/secrets.py`**——移除硬编码默认值，加启动校验，统一为唯一凭据入口 | 🔴 P0 | 15 min | #1, #2 |
| 5 | **修改 `report_v6.py` 和 `deep_research.py`**——`os.environ[]` 改为 `os.environ.get()` 加错误提示 | 🔴 P0 | 10 min | — |
| 6 | **创建 `.env.example`**——列出所有环境变量及说明 | 🟠 P1 | 10 min | — |
| 7 | **创建 `core/env.py`**——使用 `python-dotenv` 自动加载 `.env` | 🟠 P1 | 10 min | #6 |
| 8 | **清除 Git 历史**——使用 `git filter-repo` 从所有提交历史中删除凭据 | 🔴 P0 | 30 min | #1-#5 |
| 9 | **替换 pickle 为 JSON**——修改 `data_router.py` 的 `cachedio` 装饰器 | 🟠 P1 | 30 min | — |
| 10 | **替换 `cost_model.py` 中的 pickle.load()**——使用 JSON 或 joblib | 🟠 P1 | 15 min | — |
| 11 | **统一凭据入口**——`config.py` 中删除重复定义，改为 `from core.secrets import ...` | 🟠 P1 | 20 min | #3, #4 |
| 12 | **更新 `.gitignore`**——添加 `.idea/`、`backup_*`、`.omo/`、`.sisyphus/` 等规则 | 🟡 P2 | 5 min | — |
| 13 | **添加 pre-commit 密钥扫描**——配置 `detect-secrets` 或 `git-secrets` | 🟡 P2 | 15 min | — |
| 14 | **CORS 配置**——限制 API 访问来源 | 🟡 P2 | 10 min | — |
| 15 | **API 错误信息安全**——区分 DEBUG/PROD 模式的错误信息返回 | 🟡 P2 | 15 min | — |
| 16 | **添加 slowapi 限流**——对 API 端点实施速率限制 | 🟡 P2 | 30 min | — |
| 17 | **Dashboard 认证**——添加 Token 或 Basic Auth | 🟡 P2 | 30 min | — |
| 18 | **生产服务器部署检查**——确认 `.env` 已部署、凭据已轮换、权限为 600 | 🟠 P1 | 15 min | #1-#8 |
| 19 | **定期审计**——每季度检查凭据状态、扫描 Git 历史、更新依赖 | 🟢 P3 | 持续 | — |

---

## 十、审计与验证

### 10.1 修复后验证清单

完成实施后，逐一验证以下项目：

```bash
# 1. 确认 Git 历史中无泄露凭据
git log -p | grep -E 'a123a8e0|QhIOfB63|oc_4c9d' | wc -l
# 预期输出: 0

# 2. 确认 .env 被 .gitignore 排除
git check-ignore .env
# 预期输出: .env

# 3. 确认当前代码中无硬编码 Token
grep -rn '= "[a-f0-9]\{40,\}"' config.py core/secrets.py
# 预期: 无输出

grep -rn 'os\.environ\["' scripts/ output/ --include="*.py"
# 预期: 无输出（所有 os.environ 都使用 .get() 方法）

# 4. 确认 pickle.load 已替换
grep -rn 'pickle\.load' data/ analysis/ --include="*.py"
# 预期: 无输出

# 5. 确认 .env.example 存在且内容正确
cat .env.example | grep -c 'your_.*_here'
# 预期: ≥ 5

# 6. 启动测试——缺少环境变量时应有友好错误而非崩溃
(unset TUSHARE_TOKEN && python3 -c "from core.secrets import TUSHARE_TOKEN" 2>&1) | grep -c "环境变量未设置"
# 预期: 报错信息包含 "环境变量未设置"

# 7. 启动测试——环境变量正常时系统启动
TUSHARE_TOKEN="test" python3 -c "from core.secrets import TUSHARE_TOKEN; print('OK')"
# 预期: OK
```

### 10.2 定期审计流程

建议每季度执行以下审计：

1. **凭据轮换检查**：Tushare Token 和飞书 App Secret 是否超过 90 天未轮换？
2. **Git 历史扫描**：`git log --all | grep -E '(token|secret|password)'` 检查是否有新泄露
3. **依赖安全检查**：`pip-audit` 或 `safety check` 扫描 Python 依赖漏洞
4. **端口扫描**：确认 Dashboard 端口的访问权限是否符合预期
5. **`.gitignore` 审计**：确认新增的敏感文件路径已被排除

### 10.3 应急响应

如发现新的凭据泄露：

1. **立即轮换**——登录对应平台重置 Token（Tushare：5 分钟；飞书：即时生效）
2. **从代码中移除**——修改源文件并提交
3. **清除 Git 历史**——使用 `git filter-repo` 
4. **审查泄露窗口内的异常活动**——检查 Tushare API 调用量、飞书群消息记录

---

> **修订记录**
> - 2026-07-03：初稿。编写威胁模型、凭据清单、修复方案、实施清单
