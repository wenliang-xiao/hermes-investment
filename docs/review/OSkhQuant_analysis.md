# OSkhQuant Dashboard & Framework — Deep Analysis

> Project: https://github.com/OSkhQuant/OSkhQuant (open-source quantitative framework)
> Cloned at: `/tmp/OSkhQuant/`
> Analysis date: 2026-06-25

## 1. Project Overview

OSkhQuant is an **A-share quantitative trading framework** built around 迅投QMT (XtQuant) broker integration, featuring a PyQt5 GUI dashboard, backtesting engine, and live trading capabilities. Its core design centers on connecting to 券商 quant platforms for real data and order execution.

**Core strength**: The transaction cost model and backtest result visualization dashboard — professional-grade A-stock trading analytics with comprehensive metric display.

---

## 2. What OSkhQuant Does Well (Concrete Code Evidence)

### 2.1 Professional-Grade Transaction Cost Model (`khTrade.py`)

**File**: `/tmp/OSkhQuant/khTrade.py`, lines 1–196

The `KhTradeManager` class implements a **full A-stock transaction cost engine**:

```python
# Lines 24-37: Configurable cost parameters
self.min_commission = trade_cost.get("min_commission", 5.0)     # 最低佣金5元
self.commission_rate = trade_cost.get("commission_rate", 0.0003) # 佣金万3
self.stamp_tax_rate = trade_cost.get("stamp_tax_rate", 0.001)   # 印花税千1 (卖出)
self.flow_fee = trade_cost.get("flow_fee", 0.1)                  # 流量费0.1元/笔
```

**Dual slippage mode support** (lines 29-37):

```python
self.slippage = trade_cost.get("slippage", {
    "type": "ratio",        # or "tick"
    "tick_size": 0.01,      # A股最小变动价
    "tick_count": 2,        # 跳数
    "ratio": 0.001          # 滑点比例0.1%
})
```

**Comprehensive cost breakdown** (lines 161-196):

```python
def calculate_trade_cost(self, price, volume, direction, stock_code):
    actual_price = self.calculate_slippage(price, direction)  # Apply slippage first
    commission = self.calculate_commission(actual_price, volume)
    stamp_tax = self.calculate_stamp_tax(actual_price, volume, direction)
    transfer_fee = self.calculate_transfer_fee(stock_code, actual_price, volume)
    flow_fee = self.calculate_flow_fee()
    total_cost = commission + stamp_tax + transfer_fee + flow_fee
    return actual_price, total_cost
```

Note the **沪市 transfer fee** (lines 138-155):

```python
def calculate_transfer_fee(self, stock_code, price, volume):
    if stock_code.startswith("sh."):
        return price * volume * 0.00001  # 成交金额的0.001%
    return 0.0
```

**Our system should adopt**: This entire cost model. Our `evaluator_fixed.py` only has basic commission + stamp tax + slippage (lines 65-68). We should add:
- Min commission (5 RMB)
- Transfer fee (沪市 only)
- Flow fee
- Tick-based slippage mode (currently we only have ratio mode)

### 2.2 ETF/Stock Type Detection (`khQTTools.py`)

**File**: `/tmp/OSkhQuant/khQTTools.py`, lines 81–131

**Precise ETF detection by code prefix** (lines 81-103):

```python
def is_etf(stock_code: str) -> bool:
    code = stock_code.split('.')[0]
    sh_etf_prefixes = ('51', '52', '53', '55', '56', '58')  # SH ETF prefixes
    sz_etf_prefix = '159'                                     # SZ ETF prefix
    return code.startswith(sh_etf_prefixes) or code.startswith(sz_etf_prefix)
```

**Pool type detection** (lines 105-131):

```python
def determine_pool_type(stock_list):
    has_stock = any(not is_etf(code) for code in stock_list)
    has_etf = any(is_etf(code) for code in stock_list)
    if has_stock and not has_etf: return ('stock_only', 2)   # 2 decimal places
    elif has_etf and not has_stock: return ('etf_only', 3)    # 3 decimal places
    else: return ('mixed', 3)
```

**Our system should adopt**: Stock type classification for proper price formatting and fee handling. ETFs use 3 decimal places; stocks use 2.

### 2.3 T+0 Detection for ETFs (`khQTTools.py`)

**File**: `/tmp/OSkhQuant/khQTTools.py`, lines 132–200

```python
def load_t0_etf_list() -> set:
    # Load from data/T0型ETF.csv
    t0_file = os.path.join(current_dir, 'data', 'T0型ETF.csv')
    with open(t0_file, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            _t0_etf_cache.add(row[0].strip())
    return _t0_etf_cache

def check_t0_support(stock_list):
    t0_list = load_t0_etf_list()
    t0_count = sum(1 for code in stock_list if code in t0_list)
    # Returns: ('all_t0' | 'mixed' | 'no_t0', is_t0_mode)
```

**Our system should adopt**: T+0 status tracking for proper backtest ordering rules (T+0 for crypto/ETFs, T+1 for A-shares).

### 2.4 Comprehensive Backtest Result Dashboard (`backtest_result_window.py`)

**File**: `/tmp/OSkhQuant/backtest_result_window.py`, lines 36–3182

This is a **professional-grade backtest analytics window** with:

**Metric dashboard** (lines 278-282):
```python
info_items = ["策略名称", "回测区间", "初始资金", "最终资金", 
             "总收益率", "年化收益率", "基准收益率", "基准年化收益率", "最大回撤", 
             "夏普比率", "索提诺比率", "阿尔法", "贝塔",
             "胜率", "盈亏比", "日均交易次数", "最大连续盈利",
             "最大连续亏损", "最大单笔盈利", "最大单笔亏损", "年化波动率"]
```

These include **risk-adjusted metrics** that our system currently lacks:
- **Sortino Ratio** (downside deviation instead of total volatility)
- **Alpha/Beta** (CAPM regression against benchmark)
- **Calmar Ratio** (return / max drawdown)
- **盈亏比** (average win / average loss)
- **最大连续盈利/亏损** (consecutive wins/losses)

**Tabbed layout** (lines 394-500):
- Tab 1: Trade Records (交易记录) — time, symbol, direction, price, volume, amount, commission
- Tab 2: Daily Stats (日收益) — date, total asset, position value, cash, daily return
- Tab 3: Performance Evaluation (绩效评估) — equity curve, drawdown, monthly returns
- Tab 4: Position Analysis (持仓分析)

**Dark theme** (lines 121-224) — professional dark UI with QSS stylesheets, scrollable metric grid.

**Cross-validation chart** — equity curve with buy/sell markers.

**Our system should adopt**: The metric taxonomy (especially Sortino, Alpha/Beta, consecutive win/loss tracking). Our current portfolio_server.html only shows basic metrics.

### 2.5 Trigger Framework (`khFrame.py`)

**File**: `/tmp/OSkhQuant/khFrame.py`, lines 52–275

A clean **strategy trigger pattern** with three implementations:

```python
class TriggerBase:
    def should_trigger(self, timestamp, data): return False
    def get_data_period(self): return "tick"

class TickTrigger(TriggerBase):     # Every tick
    def should_trigger(self, ts, data): return True

class KLineTrigger(TriggerBase):    # Bar completion
    def __init__(self, framework, period):  # "1m", "5m", "1d"
    def should_trigger(self, ts, data):
        # Check if minute/hour/day boundary

class CustomTimeTrigger(TriggerBase):  # Specific times
    def __init__(self, framework, custom_times):  # ["09:30:00", "14:50:00"]
```

**Our system should adopt**: The trigger pattern for our real-time trading engine. Currently our `scripts/run_trading.py` runs on a fixed cron schedule. We should implement Tick/KLine/CustomTime triggers for more granular trading decisions.

### 2.6 Async Multi-Process Data Download (`GUI.py`)

**File**: `/tmp/OSkhQuant/GUI.py`, lines 123–323

Implements a **multi-process data download pattern** with Qt signals:

```python
# Worker runs in separate process (no GIL)
def download_data_worker(params, progress_queue, result_queue, stop_event):
    download_and_store_data(...)

# Thread monitors process communication
class DownloadThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)
    error = pyqtSignal(str)
    status_update = pyqtSignal(str)
```

Features: progress callback throttling (1s interval), interrupt/stop capability via `stop_event`, error propagation from subprocess to GUI.

**Our system should adopt**: The multiprocess + progress callback pattern for our batch data downloads (e.g., daily fetch of all 19 scored stocks' history, 12-chain data, etc.).

### 2.7 Dynamic Strategy Loading (`khFrame.py`)

**File**: `/tmp/OSkhQuant/khFrame.py`, lines 604-649

```python
def load_strategy(self, strategy_file):
    module_name = os.path.splitext(os.path.basename(strategy_file))[0]
    spec = importlib.util.spec_from_file_location(module_name, strategy_file)
    strategy_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = strategy_module  # Enable VSCode debugger
    spec.loader.exec_module(strategy_module)
    return strategy_module
```

Dynamic module loading with debugger support. **Our system should adopt**: This would let us hot-load strategies without import path hacks (our `backtest_v2.py` currently hardcodes 3 strategy classes).

### 2.8 JSON-based Config Management (`khConfig.py`)

**File**: `/tmp/OSkhQuant/khConfig.py`, lines 1–104

Clean separation of config into domains:
- `system` → run_mode, userdata_path, check_interval
- `account` → account_id, account_type
- `backtest` → start_time, end_time, init_capital, benchmark, trade_cost, trigger
- `data` → kline_period, stock_list
- `risk` → position_limit, order_limit, loss_limit

```python
class KhConfig:
    def __init__(self, config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config_dict = json.load(f)
        # Auto-calculate derived values with defaults
        self.init_capital = backtest_config.get("init_capital", 1000000)
```

**Our system should adopt**: The domain-separated JSON config pattern. Our current `config.py` uses flat env variables and a few dicts.

---

## 3. What is NOT Applicable or Worse Than Our Approach

| Feature | OSkhQuant | Our system | Verdict |
|---------|-----------|------------|---------|
| **Web deployment** | PyQt5 desktop only | FastAPI + Chart.js web | We're vastly better |
| **Crypto** | None (A-stock only) | 12 chains + DeFiLlama | We're vastly better |
| **Headless/server use** | Requires display | Pure web API | We're vastly better |
| **Data sources** | XtQuant proprietary | baostock + AKShare + open | We're better |
| **Multi-market** | A-share only | A+H+US+ETF+Crypto | We're better |
| **Strategy complexity** | Simple MA crossover | Multi-factor + debate + scoring | We're better |
| **Easy setup** | Requires QMT + xquant | pip install | We're better |
| **Real-time WebSocket** | XtQuant push | Planned (EastMoney WS) | Neither mature |
| **Chain scanner** | None | 12 chains | We have it |
| **News pipeline** | None | AKShare + GLM | We have it |
| **Factor scanner** | None | 6 factors + LDS + technicals | We have it |

### 3.1 OSkhQuant's Weaknesses

1. **QMT-dependent**: Requires 迅投QMT client installed (券商软件). The import chain `xtquant.xtdata` → `xtquant.xttrader` is proprietary and only available to Chinese broker clients. Our system runs standalone.

2. **PyQt5 desktop GUI**: The entire UI (GUI.py, 3892 lines) is built for PyQt5, which requires a display server and can't be deployed as a web service. Our FastAPI + Chart.js architecture is far more deployable.

3. **No multi-asset support**: All code assumes A-share stocks/ETFs. No Hong Kong, US, or crypto markets.

4. **Risk manager is a stub** (`khRisk.py` lines 1-50):
   ```python
   def _check_position(self) -> bool: return True  # Stub!
   def _check_order(self) -> bool: return True     # Stub!
   def _check_loss(self, data) -> bool: return True # Stub!
   ```
   All risk checks return True (no actual enforcement).

5. **No factor/alpha system**: The framework provides technical indicators via `MyTT.py` (MA, RSI, etc.) but has no fundamental factor scoring, news analysis, or ML-based signals.

6. **No historical backfill for multiple assets**: The `download_and_store_data()` function works stock-by-stock, no batch/multi-asset optimization.

---

## 4. Specific Code-Level Recommendations for Integration

### 4.1 [HIGH] Integrate OSkhQuant's Transaction Cost Model

**Target file**: `/home/admin/.hermes/investment_system/evaluator_fixed.py`

**Current state** (lines 65-68):
```python
COMMISSION_RATE = 0.00015
STAMP_TAX_RATE = 0.001
SLIPPAGE = 0.001
MIN_COMMISSION = 5.0
```

**Replace with OSkhQuant's full cost calculator**:

```python
class TransactionCost:
    """A-share transaction cost calculator (from OSkhQuant khTrade.py)"""
    
    def __init__(self, config: dict = None):
        cfg = config or {}
        self.min_commission = cfg.get("min_commission", 5.0)
        self.commission_rate = cfg.get("commission_rate", 0.00015)
        self.stamp_tax_rate = cfg.get("stamp_tax_rate", 0.001)
        self.flow_fee = cfg.get("flow_fee", 0.1)
        self.slippage = cfg.get("slippage", {"type": "ratio", "ratio": 0.001})
    
    def calculate(self, price, volume, direction, stock_code):
        """
        direction: 'buy' or 'sell'
        Returns: (actual_price, total_cost)
        """
        actual_price = self._apply_slippage(price, direction)
        commission = max(price * volume * self.commission_rate, self.min_commission) if volume > 0 else 0
        stamp_tax = price * volume * self.stamp_tax_rate if direction == "sell" and volume > 0 else 0
        transfer_fee = price * volume * 0.00001 if stock_code.startswith(("6", "sh")) and volume > 0 else 0
        flow_fee = self.flow_fee if volume > 0 else 0
        total_cost = commission + stamp_tax + transfer_fee + flow_fee
        return actual_price, total_cost
    
    def _apply_slippage(self, price, direction):
        if self.slippage["type"] == "tick":
            tick = self.slippage.get("tick_size", 0.01)
            count = self.slippage.get("tick_count", 2)
            return price + (tick * count if direction == "buy" else -tick * count)
        else:
            ratio = self.slippage["ratio"] / 2
            return price * (1 + ratio if direction == "buy" else 1 - ratio)
```

### 4.2 [HIGH] Add Sortino Ratio, Alpha/Beta to Metrics

**Target file**: `/home/admin/.hermes/investment_system/analysis/backtest_v2.py`

**Model after**: OSkhQuant `backtest_result_window.py` metric set (lines 278-282)

Add to `BaseStrategy.get_summary()`:

```python
def compute_sortino(self, daily_returns, risk_free=0.03):
    """Sortino ratio: uses downside deviation instead of total std"""
    excess = np.array(daily_returns) - risk_free / 252
    downside = np.std(excess[excess < 0])  # Only negative deviations
    return np.mean(excess) / (downside + 1e-10) * np.sqrt(252) if downside > 0 else 0

def compute_alpha_beta(self, daily_returns, benchmark_returns):
    """CAPM regression: returns = alpha + beta * benchmark_return"""
    X = np.array(benchmark_returns).reshape(-1, 1)
    y = np.array(daily_returns)
    X = np.concatenate([np.ones_like(X), X], axis=1)  # Add intercept
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    alpha = beta[0] * 252  # Annualized
    beta_coef = beta[1]
    return alpha, beta_coef

def compute_consecutive_stats(self, closed_trades):
    """Max consecutive wins/losses"""
    wins, losses = 0, 0
    max_win_streak, max_loss_streak = 0, 0
    for t in closed_trades:
        if t.get("pnl", 0) > 0:
            wins += 1; losses = 0
            max_win_streak = max(max_win_streak, wins)
        else:
            losses += 1; wins = 0
            max_loss_streak = max(max_loss_streak, losses)
    return max_win_streak, max_loss_streak
```

### 4.3 [MEDIUM] Implement Trigger Framework for Real-Time Trading

**Target file**: `/home/admin/.hermes/investment_system/scripts/run_trading.py`

**Model after**: OSkhQuant `khFrame.py` TriggerBase pattern (lines 52-275)

```python
class TriggerBase:
    def should_trigger(self, timestamp, data): return False

class TimeTrigger(TriggerBase):
    def __init__(self, times: list):
        self.times = [t if isinstance(t, str) else t.strftime("%H:%M") for t in times]
    def should_trigger(self, ts, data):
        return ts.strftime("%H:%M") in self.times

class PriceTrigger(TriggerBase):
    """Trigger on price crossing a level"""
    def __init__(self, symbol, level, direction="above"):
        self.symbol = symbol
        self.level = level
        self.direction = direction
    def should_trigger(self, ts, data):
        price = data.get(self.symbol, {}).get("current", 0)
        if self.direction == "above":
            return price > self.level and self._prev <= self.level
        else:
            return price < self.level and self._prev >= self.level

class TradingEngine:
    def __init__(self):
        self.triggers = []
    
    def add_trigger(self, trigger):
        self.triggers.append(trigger)
    
    def tick(self, data):
        """Called on each price update"""
        ts = datetime.now()
        for trigger in self.triggers:
            if trigger.should_trigger(ts, data):
                self.execute(trigger, data)
```

### 4.4 [MEDIUM] Add ETF/Stock Type Classification to Portfolio

**Target file**: `/home/admin/.hermes/investment_system/domain/stock_universe.py`

**Model after**: OSkhQuant `khQTTools.py` `is_etf()` (lines 81-103)

```python
# A-share code classification
SH_ETF_PREFIXES = ('51', '52', '53', '55', '56', '58')
SZ_ETF_PREFIX   = '159'
SZ_GEM_PREFIXES = ('300', '301')      # 创业板
SH_MAIN_PREFIXES = ('600', '601', '603', '605')
SZ_MAIN_PREFIXES = ('000', '001', '002')
STAR_PREFIXES    = ('688', '689')     # 科创板
BEI_PREFIXES     = ('8', '4')         # 北交所/新三板

def classify_stock(symbol: str) -> dict:
    sym = symbol.zfill(6)
    if sym.startswith(SH_ETF_PREFIXES) or sym.startswith(SZ_ETF_PREFIX):
        return {"type": "ETF", "exchange": "SH" if sym.startswith(('5', '6')) else "SZ"}
    elif sym.startswith(STAR_PREFIXES):
        return {"type": "STAR", "exchange": "SH", "t0": False}
    elif sym.startswith(SH_MAIN_PREFIXES):
        return {"type": "STOCK", "exchange": "SH", "t0": False}
    elif sym.startswith(SZ_GEM_PREFIXES):
        return {"type": "GEM", "exchange": "SZ", "t0": False}
    elif sym.startswith(SZ_MAIN_PREFIXES):
        return {"type": "STOCK", "exchange": "SZ", "t0": False}
    return {"type": "UNKNOWN", "exchange": "?"}
```

### 4.5 [MEDIUM] Add Daily Performance Stats Table

**Target file**: `/home/admin/.hermes/investment_system/scripts/portfolio_server.py`

**Model after**: OSkhQuant `backtest_result_window.py` daily stats tab (lines 463-496)

Our current API returns portfolio summary + trade history. Add a `/api/daily_stats` endpoint:

```python
@app.get("/api/daily_stats")
def api_daily_stats():
    """Daily portfolio value, position value, cash, daily return"""
    book = load_shadow()
    history = book.get("history", [])
    
    # Reconstruct daily snapshots
    daily = {}
    for h in history:
        date = h.get("time", "")[:10]
        if date:
            if date not in daily:
                daily[date] = {"cash": 0, "position_value": 0, "total_value": 0}
            if h.get("action") == "买入":
                daily[date]["position_value"] += h.get("cost", 0)
                daily[date]["cash"] -= h.get("cost", 0)
            elif h.get("action") == "卖出":
                daily[date]["cash"] += h.get("cost", 0) + (h.get("pnl", 0) or 0)
                daily[date]["position_value"] -= h.get("cost", 0)
    
    # Build time series
    dates = sorted(daily.keys())
    if dates:
        capital = book.get("capital", 1000000)
        running = capital
        series = []
        for d in dates:
            running += daily[d]["cash"] + daily[d]["position_value"]
            series.append({"date": d, "total_value": round(running, 2)})
        
        # Add daily return %
        for i in range(len(series)):
            if i == 0:
                series[i]["daily_return"] = 0
            else:
                prev = series[i-1]["total_value"]
                series[i]["daily_return"] = round((series[i]["total_value"] - prev) / prev * 100, 4)
    
    return {"daily_stats": series}
```

### 4.6 [LOW] Add Sortino Ratio to Portfolio Dashboard

**Target file**: `/home/admin/.hermes/investment_system/scripts/portfolio_server.py`

Add to `build_summary()`:

```python
def compute_sortino_from_history(book):
    """Compute Sortino ratio from daily history"""
    history = book.get("history", [])
    if len(history) < 2:
        return 0
    capital = book.get("capital", 1000000)
    daily_values = [capital]
    for h in history:
        pnl = h.get("pnl")
        cost = h.get("cost")
        action = h.get("action", "")
        if action == "买入" and cost:
            daily_values.append(daily_values[-1] - cost)
        elif action == "卖出" and pnl is not None:
            daily_values.append(daily_values[-1] + pnl)
    
    returns = [(daily_values[i] - daily_values[i-1]) / daily_values[i-1] for i in range(1, len(daily_values))]
    if not returns:
        return 0
    excess = np.array(returns) - 0.03 / 252
    downside = np.std(excess[excess < 0])
    return round(np.mean(excess) / (downside + 1e-10) * np.sqrt(252), 3) if downside > 0 else 0
```

### 4.7 [LOW] Multiple Data Source Real-Time Validation

**Target file**: `/home/admin/.hermes/investment_system/data/data_layer.py`

**Model after**: xalpha `get_rt()` double-check (universal.py:1831-1836) + OSkhQuant's XtQuant data tools

```python
import akshare as ak

def get_realtime_price(symbol: str, sources=None) -> dict:
    """
    Fetch real-time price from multiple sources, return consensus.
    Sources tried in order: ['eastmoney', 'sina', 'tencent']
    """
    sources = sources or ['eastmoney', 'sina']
    results = []
    
    for source in sources:
        try:
            if source == 'eastmoney':
                df = ak.stock_zh_a_spot_em()
                row = df[df['代码'] == symbol.zfill(6)]
                if not row.empty:
                    results.append({
                        'source': 'eastmoney',
                        'current': float(row['最新价'].iloc[0]),
                        'volume': float(row['成交量'].iloc[0]),
                        'amount': float(row['成交额'].iloc[0]),
                        'high': float(row['最高'].iloc[0]),
                        'low': float(row['最低'].iloc[0]),
                        'open': float(row['今开'].iloc[0]),
                        'pre_close': float(row['昨收'].iloc[0]),
                    })
            elif source == 'sina':
                import requests
                r = requests.get(f'https://hq.sinajs.cn/list=sh{symbol}' if symbol.startswith('6') else f'https://hq.sinajs.cn/list=sz{symbol}')
                # Parse Sina CSV format
                ...
        except Exception as e:
            logger.warning(f"Source {source} failed: {e}")
    
    if len(results) >= 2:
        # Cross-validate (within 0.5%)
        prices = [r['current'] for r in results]
        if max(prices) / min(prices) - 1 > 0.005:
            logger.warning(f"Price mismatch: {results}")
    
    return results[0] if results else None
```

### 4.8 [LOW] Adopt OSkhQuant Config Layout

**Target file**: `/home/admin/.hermes/investment_system/config.py`

```python
# New domain-separated config structure (inspired by khConfig.py)
DEFAULT_CONFIG = {
    "system": {
        "run_mode": "backtest",      # backtest | paper | live
        "check_interval": 60,        # seconds
        "data_dir": "data/",
    },
    "account": {
        "initial_capital": 1000000,
        "currency": "CNY",
    },
    "backtest": {
        "start_date": "2026-01-01",
        "end_date": "2026-06-25",
        "benchmark": "000300.SH",    # 沪深300
        "trade_cost": {
            "commission_rate": 0.00015,
            "min_commission": 5.0,
            "stamp_tax_rate": 0.001,
            "transfer_fee_rate": 0.00001,
            "flow_fee": 0.1,
            "slippage": {"type": "ratio", "ratio": 0.001},
        }
    },
    "data": {
        "primary_source": "baostock",
        "backup_sources": ["akshare", "tushare"],
        "cache_ttl_hours": 24,
    },
    "risk": {
        "max_position_size": 0.2,      # 20% per position
        "max_leverage": 1.0,
        "stop_loss": 0.08,             # 8% hard stop
        "max_drawdown": 0.15,          # 15% portfolio drawdown
        "daily_loss_limit": 0.03,      # 3% daily loss
    },
    "strategies": {
        "faceji": {"enabled": True, "entry_threshold": 5.0, "exit_threshold": 4.0},
        "silverquant": {"enabled": True, "entry_threshold": 5.0},
        "tradingagents": {"enabled": True, "max_positions": 6},
    }
}
```

---

## 5. Summary

### Adopt directly:
1. Full transaction cost model (commission + stamp tax + transfer fee + flow fee + dual-mode slippage)
2. ETF/Stock type classification by code prefix
3. T+0 stock detection
4. Sortino Ratio, Alpha/Beta, consecutive win/loss metrics
5. Daily performance stats table

### Reference for design:
1. Trigger framework (Tick/KLine/CustomTime) for real-time trading engine
2. Dynamic strategy loading pattern
3. Domain-separated JSON config structure
4. Multi-process data download with progress reporting

### Skip entirely:
1. PyQt5 GUI (replaced by FastAPI + Chart.js)
2. XtQuant/QMT integration (proprietary broker dependency)
3. `khRisk.py` risk manager (stub implementation)
4. `MyTT.py` technical indicators (we have superior ones)
5. `miniQMT_data_parser.py` / `miniQMT_data_viewer.py` (QMT-specific)
