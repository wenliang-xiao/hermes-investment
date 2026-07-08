# 开发指南 — 目录分类规则与架构纪律

> 防止代码散落、目录混乱、架构再次失控。

## 目录分类决策树

新增 `.py` 文件时，按以下决策树放入正确目录：

```
问: 这个文件是做什么的？
│
├─ 因子计算/回测/宏观分析 → engine/
├─ Dashboard API 端点/前端模板 → dashboard/
├─ 策略纯函数（无状态/无IO）→ strategies/
├─ 数据获取/缓存/路由 → data/
├─ ETF 扫描/组合/回测/策略 → etf/
├─ 新闻抓取/情感分析/管线 → news/
├─ 龙虎榜/深度研报/产业链分析 → research/
├─ 模拟盘引擎(T+1/费用/撮合) → trading/
├─ 日报/周报输出 → output/
├─ 领域模型/WATCHLIST → domain/
├─ 入口脚本(直接运行) → scripts/
├─ 工具函数(atomic_io等) → utils/
├─ 测试 → tests/
├─ 废弃文件 → _archive/
└─ 不匹配上述任何一项 → 问自己：是否真的需要新文件？
```

## 禁止事项

### ❌ 绝对禁止

1. **禁止在根目录创建 `.py` 文件**（除 `config.py`、`__init__.py`、bridge）
2. **禁止在 `scripts/` 放业务逻辑**——scripts/ 只放入口脚本（< 150 行），业务逻辑必须在 engine/etf/news/trading/research/ 中
3. **禁止在 `analysis/` 创建新文件**——`analysis/` 现在只做 bridge re-export，所有新代码放入对应模块
4. **禁止删除 bridge 文件**——移动文件后必须在原路径保留 `from engine.X import *` 桥接
5. **禁止跨层循环引用**——data/ 不 import engine/，engine/ 不 import dashboard/

### ⚠️ 需要审批

6. **新增根目录文件**（如 `mcp_akshare_server.py`）需评审确认无更合适位置
7. **改动 `config.py`** 需评审（影响15个文件）
8. **改动 `domain/__init__.py`** 需评审（WATCHLIST 入口）

## 目录引用关系（合法依赖方向）

```
dashboard/ → engine/, etf/, news/, research/, trading/, data/, domain/
scripts/   → engine/, etf/, news/, research/, trading/, data/, output/
strategies/→ strategies/base.py（包内引用）
output/    → engine/, data/, domain/
data/      → data/sources/（包内引用）
engine/    → data/, domain/, strategies/, config.py
research/  → data/, domain/, config.py
etf/       → data/, config.py
news/      → （独立，仅依赖外部 API）
trading/   → data/, config.py
```

## 新增文件检查清单

每新增一个文件，必须确认：

- [ ] 放在正确的目录（按决策树）
- [ ] 没有在 `analysis/` 创建（应该放 `engine/` / `research/` / `etf/`）
- [ ] 没有在 `scripts/` 放超过 150 行的业务逻辑
- [ ] 移动旧文件后在原路径留了 bridge
- [ ] import 路径使用新路径（`from engine.X import` 而非 `from analysis.X import`）
- [ ] 没有破坏 `run_daily.py` / `run_factor_daily.py` 生产管线
- [ ] README.md 和 docs/ 已更新

## 清理检查清单

每季度运行一次：

```bash
# 检查根目录是否有散落文件
ls *.py *.md *.json *.txt 2>/dev/null

# 检查 analysis/ 是否有非 bridge 文件
grep -L "^# Bridge" analysis/*.py

# 检查是否有文件放错目录
find scripts/ -name "*.py" -exec wc -l {} \; | awk '$1>150{print $2, $1" lines"}'

# 检查废弃引用
grep -r "from analysis\." --include="*.py" -l | grep -v analysis/
```

## ECS 运行检查清单

部署到 ECS 前确认：

```bash
# 1. Dashboard 启动正常
python3 dashboard/server.py 8686 &

# 2. 日报管线正常
python3 scripts/run_daily.py

# 3. 因子日扫正常
python3 scripts/run_factor_daily.py --top-n 30

# 4. ETF 发现（首次运行需生成数据）
python3 scripts/run_etf_discovery.py

# 5. 新闻管线
python3 scripts/run_news_pipeline.py

# 6. 深度研报（需要 ARK_API_KEY）
python3 scripts/run_deep_research.py
```

## 版本约定

- **commit**: 中文，`feat:` / `fix:` / `refactor:` / `chore:` / `docs:` 前缀
- **tag**: `vYYYY.MM.DD`
- **PR**: 必须包含 docs/ 更新
