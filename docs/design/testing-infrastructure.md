# 测试基础设施方案

> 版本: v1.0 | 日期: 2026-07-03 | 作者: Hermes Investment Team
>
> 从零构建 Hermes 投资系统的测试基础设施，覆盖 94 个 Python 文件的单元测试、集成测试、回归测试与 CI 管线。

## 文档结构

- **第一章 现状评估**：描述当前零测试覆盖的背景与可测试资产
- **第二章 分层测试策略**：按单元→集成→回归→冒烟四层逐层规划
- **第三章 测试框架选型与配置**：pytest 生态选型、插件选择、配置方案
- **第四章 Fixture 设计**：关键测试夹具的定义与复用策略
- **第五章 Mock 策略**：外部数据源（baostock/yfinance/AKShare）的隔离方案
- **第六章 基于属性的测试**：factor_engine 的 hypothesis 属性测试设计
- **第七章 覆盖率目标**：按模块的阶段性覆盖率规划
- **第八章 测试数据管理**：样本数据、金标文件、缓存策略
- **第九章 CI 集成**：GitHub Actions 工作流设计与检查门禁
- **第十章 命名与组织规范**：目录结构、文件命名、测试命名约定
- **第十一章 实施路线图**：四周分阶段推进计划

---

## 一、现状评估

### 1.1 零测试覆盖

当前项目共有 94 个 Python 源文件，零个测试文件，零个 CI 配置。代码直接从开发环境部署到生产服务器，没有任何自动化验证手段。

这带来的风险包括：

- **回归风险**：每次改动无法验证是否破坏已有功能，evaluator_fixed.py 的 19 只标的评分基线依赖人工比对。
- **重构风险**：strategies/ 下的纯函数提取（如 faceji.decide 从 trading_engine 剥离）之后缺少自动化验证，后续改动可能破坏接口契约。
- **上线信心不足**：每次部署依赖人工检查 Dashboard，缺乏量化质量指标。

### 1.2 可测试资产分析

尽管项目整体缺乏测试，但部分模块具备良好的可测试性：

| 模块 | 可测试函数 | 测试类型 | 可测试原因 |
|------|-----------|---------|-----------|
| `strategies/faceji.py` | `_kelly_size()`, `decide()` | 单元测试 | 纯函数，输入→输出，无 IO，无状态 |
| `strategies/silverquant.py` | `decide()` | 单元测试 | 纯函数，无 IO，无状态 |
| `strategies/tradingagents.py` | `_debate_score()`, `decide()` | 单元测试 | 纯函数，无 IO，无状态 |
| `strategies/base.py` | `Signal.to_dict()`, `PositionData.pnl_pct/drawdown_from_peak` | 单元测试 | 纯数据 + 计算属性 |
| `analysis/cost_model.py` | `calc_trade_cost()`, `calc_adjusted_price()`, `get_slippage_rate()` | 单元测试 | 纯计算函数，输入→输出 |
| `analysis/factor_engine.py` | `standardize_cross_section()`, `aggregate_style()` | 单元+属性测试 | 数学函数，适合 hypothesis |
| `data/data_router.py` | `_detect_source()`, `_resolve_symbol()` | 单元测试 | 纯函数，字符串→字符串映射 |
| `evaluator_fixed.py` | `compute_technicals()`, `analyze_market_regime()`, `WalkForwardSplit.split()`, `_compute_metrics()` | 单元+回归测试 | 给定输入→确定输出，19 只标的固定评分 |

**核心挑战**：

1. **外部数据源依赖重**：baostock、yfinance、AKShare 三个数据源遍布 data/ 和 analysis/，需要 mock 隔离。
2. **大文件混合关注点**：evaluator_fixed.py（878 行）同时包含数据加载、技术指标、回测引擎、Walk-Forward 评估和 CLI，测试前需要部分重构。
3. **无测试基础设施**：零配置、零惯例、零依赖，需要从零搭建。
4. **单人团队，时间有限**：需要渐进式推进，首周聚焦最高价值模块。

---

## 二、分层测试策略

采用标准的测试金字塔模型，从底层纯函数向顶层端到端逐步构建：

```
        ╱ 冒烟测试 ╲        ← 服务启动、配置加载、API 响应
      ╱  回归测试    ╲      ← evaluator_fixed 基线对比
    ╱    集成测试      ╲    ← 数据管线的 mock 测试
  ╱ ──── 单元测试 ────  ╲  ← 纯函数、策略决策、成本计算
```

### 2.1 单元测试（最高优先级）

**目标**：覆盖所有纯函数，验证输入→输出的正确性。

| 优先级 | 模块 | 被测函数 | 测试要点 |
|--------|------|---------|---------|
| P0 | `strategies/faceji.py` | `_kelly_size()` | Kelly 公式计算，边界值（score=0, score=10） |
| P0 | `strategies/faceji.py` | `decide()` | 建仓信号（评分过滤、MA 趋势、仓位计算）、清仓信号（4 层风控：HardSeller -8%、FallSeller -12% 回落、ScoreDrop <4.5、MA 死叉） |
| P0 | `strategies/silverquant.py` | `decide()` | 固定槽位建仓、4 层卖出组件优先级 |
| P0 | `strategies/tradingagents.py` | `_debate_score()` | 辩论制三角色加权逻辑、MACD 死叉/RSI 超买的 bear 加成 |
| P0 | `strategies/tradingagents.py` | `decide()` | 辩论分建仓（≥5.5）、Kelly 仓位、强卖（<4.0）、弱持仓卖出 |
| P1 | `strategies/base.py` | `Signal.to_dict()` | 字段序列化正确性、None 值处理 |
| P1 | `strategies/base.py` | `PositionData` 属性 | pnl_pct 计算、drawdown_from_peak |
| P0 | `analysis/cost_model.py` | `calc_trade_cost()` | 买入/卖出成本拆分、印花税仅卖出、最低佣金 5 元 |
| P0 | `analysis/cost_model.py` | `calc_adjusted_price()` | 调整后价格计算、买入加成本/卖出减成本 |
| P1 | `analysis/cost_model.py` | `get_slippage_rate()` | 5 级滑点分级映射 |
| P0 | `analysis/factor_engine.py` | `standardize_cross_section()` | 截面分位数、异常值鲁棒、全相同值边界 |
| P0 | `analysis/factor_engine.py` | `aggregate_style()` | 子因子加权平均、缺失值处理 |
| P1 | `analysis/factor_engine.py` | `ICWeightSystem` 纯方法 | rolling_ic_weights、conditional_weight、get_weights |
| P0 | `data/data_router.py` | `_detect_source()` | 各市场代码识别（A 股 6 位数字、港股 .HK、美股字母、ETF 前缀、期货 =号） |
| P1 | `data/data_router.py` | `_resolve_symbol()` | BRK.B→BRK-B、DXY→DX-Y.NYB 映射 |
| P1 | `evaluator_fixed.py` | `compute_technicals()` | MA20/MA60 偏离、RSI14、MACD 金叉/死叉信号 |
| P1 | `evaluator_fixed.py` | `analyze_market_regime()` | 牛市/熊市/震荡分类逻辑 |
| P1 | `evaluator_fixed.py` | `WalkForwardSplit.split()` | 滚动窗口分割、边界 cycle 数限制 |
| P2 | `evaluator_fixed.py` | `_compute_metrics()` | Sharpe、Sortino、最大回撤、年化收益率计算 |

#### 策略函数测试示例

```python
# tests/unit/strategies/test_faceji.py

from strategies.faceji import decide, _kelly_size
from strategies.base import PositionData, FacejiConfig, Signal

class TestKellySize:
    def test_score_zero(self):
        assert _kelly_size(0, FacejiConfig()) == 0

    def test_max_position_cap(self):
        cfg = FacejiConfig(max_position_pct=0.08, kelly_fraction=0.5, kelly_odds=2.0)
        result = _kelly_size(10, cfg)
        assert result <= 0.08

    def test_half_kelly_at_baseline(self):
        # score=5, wp=0.5, kelly=(0.5*2-0.5)/2=0.25, half=0.125
        cfg = FacejiConfig(kelly_odds=2.0, kelly_fraction=0.5, max_position_pct=0.08)
        assert _kelly_size(5.0, cfg) == pytest.approx(0.08, abs=0.01)  # capped

class TestFacejiDecide:
    def test_buy_signal_generated(self, sample_score_map, sample_tech_map,
                                   sample_price_map):
        signals = decide(sample_score_map, sample_tech_map,
                         sample_price_map, {}, 500000)
        buy_signals = [s for s in signals if s.action == "BUY"]
        assert len(buy_signals) > 0

    def test_hard_stop_loss_triggers(self, held_position_with_loss):
        positions = {"300502": held_position_with_loss}  # -9% loss
        score_map = {"300502": 5.0}
        tech_map = {"300502": {}}
        price_map = {"300502": held_position_with_loss.entry_price * 0.91}
        signals = decide(score_map, tech_map, price_map, positions, 500000)
        sell = [s for s in signals if s.action == "SELL"]
        assert len(sell) == 1
        assert sell[0].reason.startswith("硬止损")

    def test_no_buy_when_score_below_threshold(self, sample_tech_map,
                                                sample_price_map):
        score_map = {"300502": 4.0}  # below entry_threshold=5.0
        signals = decide(score_map, sample_tech_map, sample_price_map, {}, 500000)
        assert len(signals) == 0

    def test_max_positions_respected(self, sample_score_map, sample_tech_map,
                                      sample_price_map):
        cfg = FacejiConfig(max_positions=2, max_candidates=5)
        positions = {"existing_1": PositionData("existing_1", 100, 100)}
        signals = decide(sample_score_map, sample_tech_map,
                         sample_price_map, positions, 500000, cfg)
        buy = [s for s in signals if s.action == "BUY"]
        assert len(buy) <= 1  # max 2 total minus 1 existing
```

### 2.2 集成测试（第二优先级）

**目标**：验证数据管线在 mock 外部数据源的情况下正常工作。

| 模块 | 测试点 | Mock 对象 |
|------|--------|-----------|
| `data/data_router.py` | `get_history()` 路由到正确数据源 | `baostock_source.get_history_a`、`yahoo_source.get_history_yahoo` |
| `data/data_router.py` | `cachedio` 缓存读取/写入/过期 | 临时目录替换 `_DATA_DIR` |
| `analysis/factor_engine.py` | `FactorEngine.score_batch()` 完整流程 | `data_router.get_history`、`data_layer.get_financial_report` |
| `analysis/cost_model.py` | `estimate_slippage_tier()` 缓存查找 | pickle 文件读写的临时缓存目录 |

```python
# tests/integration/test_data_router.py

class TestDataRouterIntegration:
    def test_get_history_routes_to_baostock(self, mocker):
        mock_bs = mocker.patch("data.sources.baostock_source.get_history_a")
        mock_bs.return_value = {"close": [10, 11, 12], "dates": ["2026-01-01", ...]}
        from data.data_router import get_history
        result = get_history("300502", days=120)
        assert result is not None
        assert "close" in result

    def test_cachedio_reads_from_cache(self, tmp_path, mocker):
        mocker.patch("data.data_router._DATA_DIR", tmp_path)
        import pickle
        cache_file = tmp_path / "test_key.pkl"
        with open(cache_file, "wb") as f:
            pickle.dump({"cached": True}, f)
        # ... verify cached value returned without calling source
```

### 2.3 回归测试（第三优先级）

**目标**：锁定 evaluator_fixed.py 对 19 只固定标的的评分输出，防止回测结果意外变化。

**核心思想**：evaluator_fixed.py 使用 `FIXED_SCORE_MAP`（19 只标的固定评分）作为输入。在给定相同输入数据的情况下，回测输出（Sharpe、Sortino、最大回撤、总收益等）应该是确定性的。将一组历史输出保存为"金标文件"（golden file），每次跑测试时对比。

```python
# tests/regression/test_evaluator_baseline.py

class TestEvaluatorBaseline:
    GOLDEN_FILE = Path("tests/data/golden/baseline_evaluator.json")

    def test_faceji_backtest_matches_baseline(self, mock_price_data):
        from evaluator_fixed import run_backtest
        from strategies.faceji import decide

        result = run_backtest(mock_price_data, decide, "faceji")

        with open(self.GOLDEN_FILE) as f:
            golden = json.load(f)

        faceji_golden = golden["faceji"]
        tolerance = {"sortino_ratio": 0.001, "max_drawdown_pct": 0.1,
                     "total_return_pct": 0.1, "sharpe_ratio": 0.001}

        for key, tol in tolerance.items():
            assert result[key] == pytest.approx(faceji_golden[key], abs=tol), \
                f"{key} mismatch: {result[key]} vs {faceji_golden[key]}"

    def test_walk_forward_split_consistency(self):
        from evaluator_fixed import WalkForwardSplit
        wf = WalkForwardSplit(total_days=500, train_days=252, test_days=63, cycles=3)
        windows = wf.split()
        assert len(windows) == 3
        assert windows[0].train_start == 0
        assert windows[0].train_end == 252
        assert windows[0].test_start == 252
        assert windows[0].test_end == 315
```

**金标文件生成**：

```bash
# 首次/更新基线时运行
python scripts/generate_golden.py --strategy faceji --output tests/data/golden/baseline_evaluator.json
```

### 2.4 冒烟测试（第四优先级）

**目标**：验证系统关键入口点能正常启动和响应。

| 测试点 | 验证内容 |
|--------|---------|
| 配置加载 | `config.py` 能正确加载所有必需的环境变量/配置文件 |
| API 端点 | `portfolio_server.py` 的 `/api/simulated`、`/api/comparison`、`/api/v2/pool` 返回 200 |
| 策略导入 | `importlib.import_module` 能成功加载三个策略的 `decide` 函数 |
| 缓存目录 | `data/cache/`、`data/eval_cache/` 目录存在或可自动创建 |

```python
# tests/smoke/test_api_smoke.py
import pytest
from fastapi.testclient import TestClient

class TestAPISmoke:
    @pytest.fixture
    def client(self):
        from scripts.portfolio_server import app
        return TestClient(app)

    def test_dashboard_accessible(self, client):
        response = client.get("/dashboard")
        assert response.status_code == 200

    def test_simulated_endpoint_returns_json(self, client):
        response = client.get("/api/simulated")
        assert response.status_code == 200
        assert "application/json" in response.headers["content-type"]
```

---

## 三、测试框架选型与配置

### 3.1 框架选型

| 组件 | 选择 | 原因 |
|------|------|------|
| 测试运行器 | **pytest** | Python 生态标准，94 个文件均为纯 Python |
| 覆盖率 | **pytest-cov** | 与 pytest 深度集成，支持按模块配置阈值 |
| Mock | **pytest-mock** | `mocker` fixture 的 monkeypatch 风格，简洁易用 |
| 并行执行 | **pytest-xdist** | 后续扩展用，初期可不安装 |
| 属性测试 | **hypothesis** | 用于 factor_engine 的数学函数验证 |
| 时间控制 | **freezegun** | 冻结时间，验证带时间戳的逻辑（如缓存 TTL） |

### 3.2 依赖声明

在 `requirements-dev.txt` 中声明测试依赖：

```
# 测试依赖
pytest>=8.0
pytest-cov>=5.0
pytest-mock>=3.12
hypothesis>=6.100
freezegun>=1.4
```

### 3.3 pytest 配置

在项目根目录创建 `pyproject.toml`（或 `pytest.ini`）中的 pytest 配置：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
    "--cov=strategies",
    "--cov=analysis/cost_model.py",
    "--cov=analysis/factor_engine.py",
    "--cov=data/data_router.py",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-fail-under=0",
]
markers = [
    "unit: 单元测试，不依赖外部资源",
    "integration: 集成测试，需要 mock 外部数据源",
    "regression: 回归测试，与金标文件对比",
    "smoke: 冒烟测试，验证系统可启动",
    "slow: 运行较慢的测试",
]
```

### 3.4 conftest.py 顶层配置

```python
# tests/conftest.py
import pytest
from pathlib import Path

@pytest.fixture(scope="session")
def project_root():
    return Path(__file__).parent.parent

@pytest.fixture(scope="session")
def tests_data_dir(project_root):
    d = project_root / "tests" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d
```

---

## 四、Fixture 设计

### 4.1 核心 Fixture 层级

```
session 级：
  ├── project_root          → 项目根目录
  ├── tests_data_dir        → 测试数据目录
  └── sample_price_data    → 模拟日线数据（20 天 OHLCV）

module 级：
  ├── faceji_default_config → FacejiConfig 默认参数
  ├── sample_score_map       → 3-5 只标的的模拟评分
  ├── sample_tech_map        → 模拟技术指标（MA 偏离、RSI、MACD）
  └── sample_price_map       → 模拟当前价格

function 级：
  ├── empty_positions        → 空持仓 dict
  ├── held_position_with_profit → 盈利持仓 PositionData
  └── held_position_with_loss   → 亏损持仓 PositionData
```

### 4.2 关键 Fixture 实现

```python
# tests/conftest.py (部分)

import pytest
from strategies.base import PositionData, FacejiConfig, SilverQuantConfig, TradingAgentsConfig

# ── 策略配置 ──

@pytest.fixture
def faceji_default_config():
    return FacejiConfig()

@pytest.fixture
def silverquant_default_config():
    return SilverQuantConfig()

@pytest.fixture
def tradingagents_default_config():
    return TradingAgentsConfig()

# ── 市场数据 ──

@pytest.fixture
def sample_score_map():
    return {
        "300502": 6.5,
        "688041": 5.8,
        "688256": 4.8,
        "603259": 4.2,
        "NVDA":   7.0,
    }

@pytest.fixture
def sample_tech_map():
    return {
        "300502": {"ma20_dev": 3.5, "ma60_dev": 1.2, "rsi": 55, "total_tech_score": 6.0},
        "688041": {"ma20_dev": 2.1, "ma60_dev": -0.5, "rsi": 45, "total_tech_score": 5.5},
        "688256": {"ma20_dev": -2.0, "ma60_dev": 1.0, "rsi": 40, "macd_signal": "死叉"},
        "603259": {"ma20_dev": -5.0, "ma60_dev": -3.0, "rsi": 30, "macd_signal": "死叉"},
        "NVDA":   {"ma20_dev": 5.0, "ma60_dev": 8.0, "rsi": 65, "total_tech_score": 7.0},
    }

@pytest.fixture
def sample_price_map():
    return {
        "300502": 120.0,
        "688041": 85.0,
        "688256": 320.0,
        "603259": 52.0,
        "NVDA":   140.0,
    }

# ── 持仓数据 ──

@pytest.fixture
def empty_positions():
    return {}

@pytest.fixture
def held_position_with_loss():
    return PositionData(
        symbol="300502", entry_price=120.0, quantity=1000,
        peak=125.0, current_price=109.2,  # -9% from entry
    )

@pytest.fixture
def held_position_with_profit():
    return PositionData(
        symbol="NVDA", entry_price=100.0, quantity=500,
        peak=150.0, current_price=140.0,
    )

# ── 模拟日线数据（20 天） ──

@pytest.fixture
def sample_close_prices():
    import numpy as np
    np.random.seed(42)
    base = 100.0
    returns = np.random.normal(0.001, 0.02, 120)
    return (base * np.cumprod(1 + returns)).tolist()

@pytest.fixture
def mock_price_data(sample_close_prices):
    """模拟 evaluator_fixed 格式的价格数据"""
    return {
        "300502": sample_close_prices[-100:],
        "688041": [p * 0.8 for p in sample_close_prices[-100:]],
        "688256": [p * 3.0 for p in sample_close_prices[-100:]],
    }
```

---

## 五、Mock 策略

### 5.1 外部数据源隔离原则

项目依赖三个外部数据源，统一隔离策略：

- **baostock**：`data/sources/baostock_source.py` 中的 `get_history_a()` —— mock 返回标准化的 dict。
- **yfinance**：`data/sources/yahoo_source.py` 中的 `get_history_yahoo()` —— mock 返回标准化的 dict。
- **AKShare**：`data/sources/akshare_source.py` 中的多个函数 —— 按需 mock。

**黄金法则**：单元测试从不调用真实 API，集成测试通过 monkeypatch 替换数据源模块的顶层函数。

### 5.2 Mock 层级选择

| 场景 | Mock 位置 | 原因 |
|------|----------|------|
| 测试 `_detect_source()` | 不 mock | 纯函数，无外部调用 |
| 测试策略 `decide()` | 不 mock | 纯函数，接收 dict 输入 |
| 测试 `data_router.get_history()` | mock `baostock_source.get_history_a` 等 | 防止实际网络调用 |
| 测试 `FactorEngine.score_batch()` | mock `data_router.get_history` | 隔离数据获取，测试计算逻辑 |
| 测试 `evaluator_fixed.run_backtest()` | 传入 fixture 构造的 `price_data` | evaluator 支持直接传入预加载数据 |

### 5.3 标准化 Mock 返回值

```python
# tests/mock_data.py — 集中管理 mock 返回值模板

def make_mock_history(symbol: str, days: int = 120) -> dict:
    """生成标准化 mock 日线数据"""
    import numpy as np
    np.random.seed(hash(symbol) % 2**31)
    base = 100.0
    returns = np.random.normal(0.0005, 0.015, days)
    close = (base * np.cumprod(1 + returns)).tolist()
    return {
        "dates": [f"2026-{m:02d}-{d:02d}" for m in range(1, 5) for d in range(1, min(31, days+1))][:days],
        "open": [c * 0.99 for c in close],
        "high": [c * 1.02 for c in close],
        "low": [c * 0.98 for c in close],
        "close": close,
        "volume": [int(abs(c * 1e6)) for c in close],
    }

def make_mock_rt(symbol: str) -> dict:
    """生成标准化 mock 实时行情"""
    return {
        "symbol": symbol,
        "name": f"Mock_{symbol}",
        "price": 100.0,
        "change_pct": 1.5,
        "volume": 1e7,
        "amount": 1e9,
        "turnover_rate": 3.0,
        "pe": 25.0,
    }
```

### 5.4 cost_model 的 IO 隔离

`estimate_slippage_tier()` 读取磁盘 pickle 缓存文件，需要特殊处理：

```python
class TestEstimateSlippageTier:
    def test_returns_default_for_unknown_symbol(self, mocker):
        mocker.patch("pathlib.Path.glob", return_value=[])
        from analysis.cost_model import estimate_slippage_tier
        result = estimate_slippage_tier("UNKNOWN")
        assert result == "L4-小盘"

    def test_respects_override_slippage(self):
        from analysis.cost_model import calc_trade_cost
        cost = calc_trade_cost(100, 1000, "buy", override_slippage=0.001)
        assert cost["slippage_rate"] == 0.001
```

---

## 六、基于属性的测试

### 6.1 适用场景

`analysis/factor_engine.py` 中的 `standardize_cross_section()` 和 `aggregate_style()` 是数学函数，天然适合属性测试——用 hypothesis 生成大量随机输入，验证函数的数学不变量。

### 6.2 属性设计要求

| 函数 | 不变量 | 说明 |
|------|--------|------|
| `standardize_cross_section()` | 输出值 ∈ [0, 1] | 分位数标准化后所有值在 0 到 1 之间 |
| `standardize_cross_section()` | 单调性保持 | 若 A > B，标准化后 p(A) ≥ p(B)（当 higher_is_better=True） |
| `standardize_cross_section()` | None 值默认 0.5 | 输入为 None 的标的得到中位数 0.5 |
| `standardize_cross_section()` | 最小值=0，最大值=1 | 有效值中 min 对应 0.0，max 对应 1.0 |
| `aggregate_style()` | 输出 ∈ [0, 1] | 子因子加权平均后仍在 0 到 1 之间 |

### 6.3 实现示例

```python
# tests/unit/analysis/test_factor_engine_property.py

from hypothesis import given, strategies as st, assume
from analysis.factor_engine import standardize_cross_section, aggregate_style

class TestStandardizeCrossSectionProperty:
    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=6),
            values=st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False)),
            min_size=2, max_size=30,
        )
    )
    def test_output_in_01_range(self, raw_values):
        result = standardize_cross_section(raw_values, higher_is_better=True)
        for v in result.values():
            assert 0.0 <= v <= 1.0

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=6),
            values=st.none(),
            min_size=1, max_size=5,
        )
    )
    def test_all_none_returns_midpoint(self, raw_values):
        result = standardize_cross_section(raw_values, higher_is_better=True)
        for v in result.values():
            assert v == 0.5

    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=6),
            values=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
            min_size=3, max_size=20,
        )
    )
    def test_min_max_boundaries(self, raw_values):
        result = standardize_cross_section(raw_values, higher_is_better=True)
        valid = {s: v for s, v in raw_values.items() if v is not None}
        if len(valid) > 1:
            min_sym = min(valid, key=valid.get)
            max_sym = max(valid, key=valid.get)
            assert result[min_sym] == 0.0
            assert result[max_sym] == 1.0

class TestAggregateStyleProperty:
    @given(
        st.dictionaries(
            keys=st.sampled_from([
                "quality:roe", "quality:gross_margin", "quality:debt_ratio",
                "quality:ocf_per_share", "quality:net_margin",
            ]),
            values=st.floats(min_value=0, max_value=1),
            min_size=1, max_size=5,
        )
    )
    def test_output_in_01_range(self, sub_scores):
        result = aggregate_style("quality", sub_scores)
        assert 0.0 <= result <= 1.0
```

---

## 七、覆盖率目标

### 7.1 阶段性目标

覆盖率不代表测试质量，但提供量化基线。按模块的"可测试性"和"业务重要性"设定差异化目标：

| 阶段 | 时间 | 目标模块 | 行覆盖率 | 说明 |
|------|------|---------|---------|------|
| Phase 1 | 第 1 周 | `strategies/base.py`、`strategies/faceji.py`、`strategies/silverquant.py`、`strategies/tradingagents.py` | **≥95%** | 纯函数，覆盖全部代码路径 |
| Phase 2 | 第 2 周 | `analysis/cost_model.py`、`data/data_router.py`（detect_source/resolve_symbol） | **≥90%** | cost_model 加上 estimate_slippage_tier 的 mock 覆盖 |
| Phase 3 | 第 3 周 | `analysis/factor_engine.py`（pure functions + property tests） | **≥85%** | `standardize_cross_section`、`aggregate_style`、IC 计算 |
| Phase 4 | 第 4 周 | `evaluator_fixed.py`（回归测试 + compute_technicals + WalkForwardSplit） | **≥70%** | 跳过 data 加载部分，聚焦计算逻辑 |
| 长期 | 2 月+ | 全局 | **≥60%** | 逐步覆盖 analysis/ 和 data/ 的集成测试 |

### 7.2 不纳入覆盖率的代码

以下代码类型排除在覆盖率统计之外，避免虚假的"高覆盖率"或逼迫对不适合测试的代码写测试：

| 排除类型 | 配置方式 | 示例 |
|----------|---------|------|
| `if __name__ == "__main__"` 块 | `[tool.coverage.report] exclude_also` | CLI 入口逻辑 |
| `backup_*/` 目录 | `[tool.coverage.run] omit` | 历史备份文件 |
| `_archive/` 目录 | `[tool.coverage.run] omit` | 归档文件 |
| FFI / 平台特定代码 | `# pragma: no cover` | 部分数据源的特殊处理 |

---

## 八、测试数据管理

### 8.1 数据分类

| 数据类型 | 目录 | 用途 | 版本控制 |
|----------|------|------|---------|
| Fixture 数据 | `tests/data/fixtures/` | 单元测试的标准输入数据 | ✅ Git |
| Mock 模板 | `tests/data/mocks/` | 模拟外部数据源返回 | ✅ Git |
| 金标文件 | `tests/data/golden/` | 回归测试的期望输出 | ✅ Git |
| 缓存数据 | `tests/data/.cache/` | 集成测试的临时缓存 | ❌ .gitignore |
| 覆盖率报告 | `htmlcov/` | pytest-cov HTML 输出 | ❌ .gitignore |

### 8.2 金标文件管理

```json
// tests/data/golden/baseline_evaluator.json — 示例结构
{
  "generated_at": "2026-07-03T10:00:00",
  "commit": "abc1234",
  "strategies": {
    "faceji": {
      "score": 1.2345,
      "total_return_pct": 12.34,
      "annualized_return_pct": 28.56,
      "sharpe_ratio": 1.5678,
      "sortino_ratio": 2.0123,
      "max_drawdown_pct": 8.76,
      "win_rate_pct": 55.5,
      "trade_count": 42
    }
  }
}
```

金标文件的更新必须走显式流程：

```bash
# 1. 修改策略后运行完整回测
python evaluator_fixed.py faceji

# 2. 确认结果符合预期后更新金标
python scripts/generate_golden.py --strategy faceji --output tests/data/golden/baseline_evaluator.json

# 3. 提交金标文件与代码一起 review
git add tests/data/golden/baseline_evaluator.json
```

### 8.3 样本数据生成脚本

```bash
# scripts/generate_test_data.py
# 生成可复现的测试样本数据（不依赖外部 API）
python scripts/generate_test_data.py --symbols 300502,688041,603259 --days 120
```

---

## 九、CI 集成

### 9.1 GitHub Actions 工作流

```yaml
# .github/workflows/test.yml
name: Test

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: "pip"

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-dev.txt

      - name: Lint check
        run: |
          pip install ruff
          ruff check strategies/ analysis/ data/ evaluator_fixed.py

      - name: Run tests
        run: |
          pytest tests/unit/ -v --cov --cov-report=xml --junitxml=junit.xml

      - name: Upload coverage to Codecov (optional)
        uses: codecov/codecov-action@v4
        with:
          file: ./coverage.xml
          flags: unittests

      - name: Regression check
        run: |
          pytest tests/regression/ -v

      - name: Smoke check
        run: |
          pytest tests/smoke/ -v
```

### 9.2 门禁规则

| 检查项 | 触发条件 | 通过标准 |
|--------|---------|---------|
| Lint（ruff） | 每个 PR | 零错误 |
| 单元测试 | 每个 PR | 全部通过，覆盖率不降 |
| 回归测试 | 修改 strategies/ 或 evaluator_fixed.py 的 PR | 全部通过 |
| 冒烟测试 | 每个 PR | 全部通过 |

### 9.3 Pre-Commit Hook（可选）

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: pytest-unit
        name: pytest-unit
        entry: pytest tests/unit/ -x --tb=short
        language: system
        pass_filenames: false
        stages: [pre-commit]
```

---

## 十、命名与组织规范

### 10.1 目录结构

```
tests/
├── __init__.py                      # 空文件
├── conftest.py                      # 顶层 fixtures（session/module 级）
├── mock_data.py                     # 集中 mock 数据生成函数
│
├── unit/                            # 单元测试（无外部依赖）
│   ├── __init__.py
│   ├── conftest.py                  # 单元测试专用 fixtures（function 级）
│   ├── strategies/
│   │   ├── test_base.py             # Signal.to_dict(), PositionData 属性
│   │   ├── test_faceji.py           # _kelly_size(), decide()
│   │   ├── test_silverquant.py      # decide()
│   │   └── test_tradingagents.py    # _debate_score(), decide()
│   ├── analysis/
│   │   ├── test_cost_model.py       # calc_trade_cost(), calc_adjusted_price()
│   │   ├── test_factor_engine.py    # standardize_cross_section(), aggregate_style()
│   │   └── test_factor_engine_property.py  # hypothesis 属性测试
│   ├── data/
│   │   └── test_data_router.py      # _detect_source(), _resolve_symbol()
│   └── evaluator/
│       └── test_evaluator_pure.py   # compute_technicals(), WalkForwardSplit, analyze_market_regime()
│
├── integration/                     # 集成测试（mock 外部数据源）
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_data_router.py          # get_history() 路由 + cachedio
│   ├── test_factor_engine_batch.py  # score_batch() 完整流程
│   └── test_cost_model_cache.py     # estimate_slippage_tier() 缓存逻辑
│
├── regression/                      # 回归测试（金标文件对比）
│   ├── __init__.py
│   └── test_evaluator_baseline.py   # run_backtest() 输出对比金标
│
├── smoke/                           # 冒烟测试（系统启动验证）
│   ├── __init__.py
│   ├── test_config.py               # 配置加载
│   └── test_api.py                  # API 端点可达性
│
└── data/                            # 测试数据
    ├── fixtures/                     # Fixture 使用的数据文件
    │   ├── sample_positions.json
    │   └── sample_daily_120.csv
    ├── mocks/                        # Mock 返回值模板
    │   ├── mock_baostock_history.pkl
    │   └── mock_yfinance_rt.json
    ├── golden/                       # 金标文件
    │   └── baseline_evaluator.json
    └── .cache/                       # 集成测试临时缓存（gitignore）
```

### 10.2 命名约定

| 约定 | 示例 | 说明 |
|------|------|------|
| 测试文件 | `test_<module>.py` | 与被测模块名对应 |
| 测试类 | `Test<Feature>` | 描述被测试的功能，非模块名 |
| 测试方法 | `test_<scenario>_<expected_behavior>` | 三段式：场景_期望行为 |
| Fixture 函数 | `sample_<data_type>` | 样本数据 fixtures |
| Fixture 函数 | `mock_<source>_<data>` | mock 数据 fixtures |
| Fixture 函数 | `held_position_with_<state>` | 持仓状态 fixtures |

**测试方法命名示例**：

```python
def test_buy_signal_generated_when_score_above_threshold(self): ...
def test_hard_stop_loss_triggers_at_minus_8_percent(self): ...
def test_no_trade_when_cash_insufficient(self): ...
def test_returns_empty_list_for_empty_score_map(self): ...
```

### 10.3 组织原则

1. **一个测试类对应一个函数/方法的行为族**：如 `TestKellySize` 包含所有 `_kelly_size()` 的测试。
2. **测试类命名使用被测试的概念，而非类名**：`TestBuySignals` 而非 `TestDecide`。
3. **每个测试方法只验证一个行为**：`test_ma_death_cross_triggers_sell` 只验证 MA 死叉卖出，不混入止损逻辑。
4. **使用 Arrange-Act-Assert 结构**，必要时加空行分隔三段。

---

## 十一、实施路线图

### 第 1 周：基础设施 + 纯函数单元测试

**目标**：搭建测试框架，覆盖最高价值的纯函数模块。

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-2 | 安装 pytest + 依赖，创建 `tests/` 目录结构、`conftest.py`、`pyproject.toml` 配置 | 可运行的空测试套件 |
| Day 3-4 | 编写 `strategies/base.py` 的测试（`Signal.to_dict()`、`PositionData` 属性） | 10-15 个测试用例 |
| Day 4-5 | 编写 `strategies/faceji.py` 的测试（`_kelly_size()` 边界、`decide()` 建仓/清仓全路径） | 20-30 个测试用例 |
| Day 5-7 | 编写 `strategies/silverquant.py` 和 `strategies/tradingagents.py` 的测试 | 15-25 个测试用例 |

**第 1 周验收标准**：
- `pytest tests/unit/strategies/` 全部通过
- `strategies/` 模块覆盖率 ≥95%
- `strategies/base.py` 覆盖率 = 100%

**预估测试用例数**：60-80 个

### 第 2 周：分析模块 + 数据路由

**目标**：覆盖 cost_model 和 data_router 的纯函数，搭建集成测试骨架。

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-3 | 编写 `analysis/cost_model.py` 的测试（`calc_trade_cost()` 买入/卖出/边界，`calc_adjusted_price()`，`get_slippage_rate()`） | 15-20 个测试用例 |
| Day 3-4 | 编写 `data/data_router.py` 的纯函数测试（`_detect_source()` 19 个测试场景，`_resolve_symbol()` 映射） | 10-15 个测试用例 |
| Day 5-6 | 编写 `data_router` 集成测试（`get_history()` mock 路由，`cachedio` 缓存行为） | 5-10 个测试用例 |
| Day 7 | 编写 `analysis/factor_engine.py` 的 `standardize_cross_section()` 和 `aggregate_style()` 单元测试 | 10-15 个测试用例 |

**第 2 周验收标准**：
- `cost_model.py` 纯函数覆盖率 ≥90%
- `_detect_source()` 覆盖所有路由规则
- 集成测试能验证 `get_history()` mock 路由

**预估测试用例数**：40-60 个

### 第 3 周：属性测试 + 回归测试 + 金标文件

**目标**：用 hypothesis 验证 factor_engine 数学函数，建立 evaluator 回归基线。

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-3 | 编写 hypothesis 属性测试（`standardize_cross_section`、`aggregate_style` 的数学不变量） | 5-10 个属性测试 |
| Day 3-4 | 编写 `WalkForwardSplit` 边界测试（0 cycle、超长数据、负数 total_days） | 5-8 个测试用例 |
| Day 3-4 | 编写 `compute_technicals()` 测试（给定已知数组，验证 MA20、RSI、MACD 输出） | 8-12 个测试用例 |
| Day 5-6 | 编写 `evaluator_fixed` 回归测试框架 + 生成首版金标文件 | 3-5 个回归测试 |
| Day 6-7 | 编写 `analyze_market_regime()` 测试 + `_compute_metrics()` 测试 | 5-10 个测试用例 |

**第 3 周验收标准**：
- 属性测试覆盖 `standardize_cross_section` 的 5 个不变量
- 回归测试能与首版金标文件对比
- `evaluator_fixed.py` 纯计算函数覆盖率 ≥70%

**预估测试用例数**：25-45 个

### 第 4 周：CI + 冒烟测试 + 收尾

**目标**：搭建 GitHub Actions，编写冒烟测试，整理文档，全员可运行。

| 天数 | 任务 | 产出 |
|------|------|------|
| Day 1-2 | 编写冒烟测试（配置加载、API 端点可达、策略导入） | 5-10 个冒烟测试 |
| Day 2-3 | 编写 GitHub Actions 工作流 `.github/workflows/test.yml` | CI 配置 |
| Day 3-4 | 运行全局覆盖率报告，调整 `[tool.coverage]` 排除项 | 覆盖率配置优化 |
| Day 4-5 | 补充 `ICWeightSystem` 纯计算方法的测试 | 5-10 个测试用例 |
| Day 5-7 | 编写 README 测试章节、运行全域测试验证、修 bug | 测试文档 |

**第 4 周验收标准**：
- GitHub Actions 能在 PR 时自动运行测试
- `pytest` 全量运行通过
- 测试可在 CI 环境复现（无本地路径依赖）
- 总测试用例数 ≥150 个

**预估测试用例数**：25-35 个（本周新增）

### 总结

| 指标 | 第 1 周 | 第 2 周 | 第 3 周 | 第 4 周 | 总计 |
|------|--------|--------|--------|--------|------|
| 新增测试用例 | 60-80 | 40-60 | 25-45 | 25-35 | **150-220** |
| 覆盖模块 | strategies | cost_model + data_router | factor_engine + evaluator | CI + smoke | — |
| 覆盖率（累计） | ~30% | ~45% | ~55% | ~60% | **≥60%** |

---

## 附录 A：快速参考命令

```bash
# 运行所有测试
pytest

# 只运行单元测试
pytest tests/unit/ -v

# 运行并生成覆盖率报告
pytest --cov --cov-report=html && open htmlcov/index.html

# 运行单个文件
pytest tests/unit/strategies/test_faceji.py -v

# 运行单个测试
pytest tests/unit/strategies/test_faceji.py::TestKellySize::test_score_zero -v

# 跳过慢速测试
pytest -m "not slow"

# 只运行属性测试
pytest tests/unit/analysis/test_factor_engine_property.py -v

# 生成金标文件
python scripts/generate_golden.py --strategy faceji

# 运行 lint
ruff check .
```

## 附录 B：已知限制与后续工作

1. **FactorEngine 的 `score_symbol()` 和 `score_batch()` 依赖实时数据**：当前通过 mock `get_history` 和 `get_financial_report` 来测试，但 `_map_raw_to_01` 的固定参考区间可能需要定期校准。
2. **evaluator_fixed.py 的 `load_price_history()` 和 `preload_all_data()` 依赖真实 API**：允许直接从 fixture 构造的 `price_data` 传入，跳过数据加载层。
3. **`analysis/trading_engine.py` 混入 IO**：当前不在 Phase 1 测试范围，需后续重构为纯函数后加入。
4. **Dashboard 端到端测试**：Playwright 前端冒烟测试留待 Phase 5（月 2+）。
5. **性能/基准测试**：pytest-benchmark 可后续引入，用于交易成本计算和回测引擎的性能回归。
