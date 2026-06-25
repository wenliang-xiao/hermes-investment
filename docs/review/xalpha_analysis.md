# xalpha Backtesting Framework — Deep Analysis

> Project: https://github.com/refraction-ray/xalpha (v0.12.3)
> Cloned at: `/tmp/xalpha/`
> Analysis date: 2026-06-25

## 1. Project Overview

xalpha is a **Chinese ETF/fund investment backtesting engine** with universal market data fetching. Its primary focus is China-domiciled mutual funds (场外基金) and OTC fund portfolios, with secondary support for A-share indices, HK stocks, and US stocks. It does NOT support crypto or individual A-stock trading natively.

**Core strength**: The `get_daily` / `get_rt` universal data dispatch system — arguably the most comprehensive Chinese market data wrapper in open source, routing 27+ data source prefixes automatically.

---

## 2. What xalpha Does Well (Concrete Code Evidence)

### 2.1 Universal Data Fetcher (`universal.py`)

**File**: `/tmp/xalpha/xalpha/universal.py`

The `_get_daily()` function (lines 1012–1300) implements a **prefix-based code dispatch** system that routes ticker codes to the appropriate data source automatically:

```python
# Line 1113-1167: Auto-detect data source from code prefix
if (code.startswith("SH") or code.startswith("SZ")) and code[2:8].isdigit():
    _from = "xueqiu"                    # A-share stock/ETF -> Xueqiu
elif code.endswith("/CNY") or code.startswith("CNY/"):
    _from = "zjj"                       # FX rates -> Chinamoney
elif code[0] in ["F", "M", "T"] and code[1:].isdigit():
    _from = "ttjj"                      # Funds -> 天天基金 (EastMoney)
elif ... # 20+ other prefix handlers
```

Supported data sources include: Xueqiu (雪球), EastMoney (天天基金), Yahoo Finance, Investing.com, S&P, Bloomberg, FT, 中证指数, 国证指数, 华证指数, 标普, ycharts, chinamoney, Futunn, and more. **Each produces a normalized DataFrame with `date` and `close` columns** (lines 269-288 `prettify()`).

**Our system should adopt**: This dispatch pattern. Currently our `data_layer.py` uses a hardcoded priority chain (baostock→AKShare→Tushare). We should implement the same prefix-based routing.

### 2.2 Real-time Price with Dual-Source Cross-Validation

**File**: `/tmp/xalpha/xalpha/universal.py`, lines 1782–1883

`get_rt()` supports **double-check mode** where it fetches from both Xueqiu and Sina and validates:

```python
# Line 1831-1836: Double-check cross-validation
elif double_check and _from in ["xueqiu", "sina"]:
    r1 = get_xueqiu_rt(code)
    r2 = get_rt_from_sina(code)
    if abs(r1["current"] / r2["current"] - 1) > double_check_threhold:
        raise DataPossiblyWrong("realtime data unmatch for %s" % code)
    return r2
```

It also has a **graceful fallback chain**: Xueqiu → Sina → Investing.com (lines 1837-1862). Each function wraps exception handling to switch to backup sources.

**Relevance**: We're building EastMoney (AKShare) real-time data integration. We should implement this dual-source double-check pattern. When EastMoney returns a suspect tick price, cross-validate against Sina or Tencent.

### 2.3 Extensible Handler Hook System

**File**: `/tmp/xalpha/xalpha/universal.py`, lines 1001–1102

`set_handler()` allows custom hooks to override or augment `get_daily`, `get_rt`, or `get_bar`:

```python
# Line 1001-1009
def set_handler(method="daily", f=None):
    setattr(thismodule, "get_" + method + "_handler", f)

# Lines 1096-1102 inside _get_daily:
if handler:
    if getattr(thismodule, "get_daily_handler", None):
        f = getattr(thismodule, "get_daily_handler")
        fr = f(**args.locals)
        if fr is not None:
            return fr
```

**Our system should adopt**: We can use this to inject our EastMoney AKShare data source as a handler, without modifying xalpha's core dispatch.

### 2.4 Transparent Caching Decorator (`cachedio`)

**File**: `/tmp/xalpha/xalpha/universal.py`, lines 1964–2001+

```python
def cachedio(**ioconf):
    # Supports backend: csv / sql / memory
    # Supports refresh, prefix, path, form
    ...
```

Caches (code, start, end) → DataFrame results to CSV files, SQL databases, or in-memory dicts. Automatically appends new data by checking last cached date vs today. **This is exactly what our evaluation system needs** (currently eval_cache uses manual pickle management in `evaluator_fixed.py` lines 85-100).

### 2.5 Cashflow Trade Model (`trade.py`)

**File**: `/tmp/xalpha/xalpha/trade.py`, lines 305–500

The `trade` class implements a **dual-table accounting system**:

- **`cftable`** (cash flow table): date / cash / share — every cash inflow/outflow + corresponding share change
- **`remtable`** (remainder table): date / rem — nested list tracking which lots remain unsold (LIFO-based)

```python
# Line 305-344: trade class init
class trade:
    def __init__(self, infoobj, status, cftable=None, remtable=None):
        self.aim = infoobj
        ...
        self.cftable = cftable  # Cash flow tracking
        self.remtable = remtable  # Position lot tracking
```

The `_addrow()` method (lines 357–500) is a **state machine** that processes each buy/sell action by:
1. Looking up the next record date
2. Finding the correct net value on that date (handling holidays)
3. Computing shares for purchase (applying fees)
4. Computing cash for redemption (applying redemption fee schedule)
5. Updating lot-level remainder tracking

**Our system should adopt**: The lot-level tracking (`remtable`) for proper tax lot accounting. Our current `backtest_v2.py` uses simple price-based P&L without lot-level tracking.

### 2.6 Multi-Fund Portfolio Aggregation (`multiple.py`)

**File**: `/tmp/xalpha/xalpha/multiple.py`, lines 32–670

The `mul` class aggregates multiple `trade` objects into a single portfolio:

- **`combsummary()`** (lines 145–210): Joins daily reports from all funds into a single DataFrame with totals
- **`xirrrate()`** (lines 228–235): Proper XIRR computation across the entire portfolio
- **`get_stock_holdings()`** (lines 251–309): "Portfolio penetration" — traces through fund holdings to reveal underlying stock exposure
- **`get_portfolio()`** (lines 311–360): Asset allocation breakdown (stock/bond/cash)
- **`v_positions()` / `v_category_positions()`** (lines 421–496): Pyecharts pie charts for visual allocation

**Our system should adopt**: The `combsummary()` pattern. Our current `portfolio_server.py` manually computes portfolio stats in `build_summary()`. We should adopt a unified data model similar to `mul.dailyreport()`.

### 2.7 XIRR Calculation

**File**: `/tmp/xalpha/xalpha/trade.py`, lines 31–75

```python
def xirrcal(cftable, trades, date, startdate=None, guess=0.01):
    # Build cashflow list of (date, cash) tuples
    # Add virtual sell-all at the end to compute final value
    cashflow.append((date, rede))
    return xirr(cashflow, guess)
```

Computes **true money-weighted rate of return** by:
1. Collecting all buy/sell cash flows
2. Adding a virtual sell-all at the valuation date
3. Solving IRR iteratively

**Our system should adopt**: Our `backtest_v2.py` computes Sharpe using simple daily returns (line 79), but lacks proper XIRR. We should integrate xalpha's `xirr()`.

### 2.8 Backtest Environment Design (`backtest.py`)

**File**: `/tmp/xalpha/xalpha/backtest.py`, lines 22–243

The `BTE` class provides a clean OOP pattern:

```python
class BTE:
    def prepare(self): pass           # Initialize state
    def run(self, date): raise ...    # Daily logic (override)
    def backtest(self):               # Loop over dates
        self.prepare()
        for d in pd.bdate_range(self.start, self.end):
            if d in opendate_set:
                self.run(d)
```

Built-in strategy implementations:
- **`Scheduled`** (line 249): Fixed DCA
- **`AverageScheduled`** (line 264): Value averaging
- **`Tendency28`** (line 329): 28 trend rotation (沪深300/中证500 switching)
- **`Balance`** (line 401): Dynamic rebalancing
- **`Grid`** (line 446): Grid trading

---

## 3. What is NOT Applicable or Worse Than Our Approach

| Feature | xalpha | Our system | Verdict |
|---------|--------|------------|---------|
| **A-share stocks** | Limited (via Xueqiu crawl) | Full via baostock + AKShare | We're better |
| **Crypto** | None | Full (12 chains via DeFiLlama) | We're vastly better |
| **Real-time prices** | fundgz API (deprecated) | AKShare EastMoney planned | We'll be better |
| **Multi-strategy** | Manual subclassing | Full backtest_v2 + evaluator_fixed | We're better |
| **Walk-forward analysis** | None | Planned (this review) | Neither has it |
| **Web dashboard** | Static pyecharts HTML | FastAPI + Chart.js | We're better |
| **Data reliability** | BeautifulSoup crawling | baostock (official API) | We're better |
| **Live trading** | "Should not be used" | Simulated/forward-testing | We're better |
| **Order book / L2** | None | Planned (EastMoney) | Neither has it |
| **Transaction costs** | Only fund-level fees | Commission + stamp tax + slippage | We're slightly better |
| **Holding lot tracking** | Sophisticated (remtable) | Simple average cost | xalpha is better |

### 3.1 xalpha's Weaknesses

1. **Realtime module is deprecated** (`realtime.py` line 6-8):
   ```python
   # deprecated - 该模块与现在的主线进展关系不大，可用性不强
   ```
   The `rtdata` class (line 84) uses `fundgz.1234567.com.cn` which is a reverse-engineered internal API that frequently breaks.

2. **No individual A-stock backtesting**: The `BTE` class explicitly says "currently only fund is supported" (line 24). While you can use `vinfo()` for stocks (line 140), there's no stock-specific order matching, limit orders, or short selling.

3. **Crawl-based data is fragile**: Many data sources use `BeautifulSoup` to parse HTML pages (e.g., `get_cninvesting_rt` at line 1353 uses CSS selectors on live pages). This breaks when websites update their DOM.

4. **No portfolio server**: Output is limited to pyecharts HTML `<script>` tags for Jupyter notebooks. No REST API for programmatic access.

5. **No multi-asset cross-market support**: The `vinfo` class can fetch different markets, but the backtest environment doesn't handle different trading calendars (CN vs HK vs US holidays).

---

## 4. Specific Code-Level Recommendations for Integration

### 4.1 [HIGH] Adopt `cachedio` Decorator for Data Caching

**Target file**: `/home/admin/.hermes/investment_system/data/data_layer.py`

**Current problem**: Lines 85-100 of `evaluator_fixed.py` use manual pickle caching with stale-check logic. This is fragile and doesn't handle incremental updates.

**Recommendation**: Implement a decorator based on xalpha's `cachedio` (universal.py:1964-2001):

```python
from functools import wraps
from pathlib import Path
import pandas as pd

CACHE_DIR = Path(__file__).parent / "cache"

def cached_data(backend="csv", ttl_days=1):
    def decorator(func):
        @wraps(func)
        def wrapper(code, start=None, end=None, **kwargs):
            cache_path = CACHE_DIR / f"{code}.csv"
            if cache_path.exists():
                age_days = (datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)).days
                if age_days < ttl_days:
                    return pd.read_csv(cache_path, parse_dates=["date"])
            df = func(code, start=start, end=end, **kwargs)
            if df is not None:
                df.to_csv(cache_path, index=False)
            return df
        return wrapper
    return decorator
```

### 4.2 [HIGH] Implement Prefix-Based Data Source Routing

**Target file**: `/home/admin/.hermes/investment_system/data/data_source_layer.py`

**Model after**: xalpha `_get_daily()` (universal.py:1113-1167)

```python
# In our data_source_layer.py
SOURCE_ROUTING = {
    "6": "baostock",      # 600xxx/601xxx/603xxx → SH A-shares
    "0": "baostock",      # 000xxx/001xxx/002xxx → SZ A-shares
    "3": "baostock",      # 300xxx/301xxx → SZ ChiNext
    "4": "baostock",      # 400xxx → SZ three-board
    "5": "baostock",      # 500xxx/510xxx → SH ETF/LOF
    "1": "baostock",      # 159xxx → SZ ETF
    "HK": "yfinance",     # HK stocks
    "US": "yfinance",     # US stocks
    "F": "eastmoney",     # Chinese funds
    "CRYPTO": "defillama",# Crypto
}

def determine_source(symbol: str) -> str:
    for prefix, source in SOURCE_ROUTING.items():
        if symbol.startswith(prefix):
            return source
    return "baostock"
```

### 4.3 [MEDIUM] Add Lot-Level Position Tracking

**Target file**: `/home/admin/.hermes/investment_system/strategies/base.py`

**Model after**: xalpha `trade.remtable` (trade.py:305-344) and `rm.buy()` / `rm.sell()` pattern.

Our current `BaseStrategy` (backtest_v2.py:49-90) stores positions as `{symbol: {entry_price, quantity}}`. We should add lot tracking:

```python
class Lot:
    """Individual trade lot with entry date, price, quantity, peak"""
    def __init__(self, date, price, quantity):
        self.date = date
        self.price = price
        self.quantity = quantity
        self.peak = price

class Position:
    def __init__(self, symbol):
        self.symbol = symbol
        self.lots: List[Lot] = []
    
    @property
    def total_quantity(self): return sum(l.quantity for l in self.lots)
    
    @property
    def avg_cost(self):
        return sum(l.price * l.quantity for l in self.lots) / self.total_quantity if self.total_quantity else 0
    
    def sell_lifo(self, quantity, current_price):
        """Sell using LIFO (last in, first out) — matches xalpha's remtable approach"""
        remaining = quantity
        realized_pnl = 0
        while remaining > 0 and self.lots:
            lot = self.lots[-1]
            sell_qty = min(lot.quantity, remaining)
            realized_pnl += (current_price - lot.price) * sell_qty
            lot.quantity -= sell_qty
            remaining -= sell_qty
            if lot.quantity <= 0:
                self.lots.pop()
        return realized_pnl
```

### 4.4 [MEDIUM] Add Proper XIRR Calculation to Backtest Summary

**Target file**: `/home/admin/.hermes/investment_system/analysis/backtest_v2.py`

**Model after**: xalpha `xirrcal()` (trade.py:31-75)

Add to `BaseStrategy.get_summary()`:

```python
def compute_xirr(self):
    """Money-weighted rate of return"""
    # Build cash flow list from trade history
    cashflows = []
    for h in self.history:
        if h.get("action") == "买入":
            cashflows.append((h["date"], -h.get("cost", 0)))
        elif h.get("action") == "卖出":
            cashflows.append((h["date"], h.get("pnl", 0) + h.get("cost", 0)))
    # Add final portfolio value as virtual sell
    cashflows.append((datetime.now().strftime("%Y-%m-%d"), self.current_value({})))
    # Use xalpha's xirr function from cons.py
    from xalpha.cons import xirr
    return xirr(cashflows, guess=0.01) * 100
```

### 4.5 [LOW] Adopt SetHandler Pattern for Data Source Hooks

**Target file**: `/home/admin/.hermes/investment_system/data/global_data.py`

```python
# Register EastMoney AKShare as a custom handler for real-time prices
def eastmoney_rt_handler(code, **kwargs):
    import akshare as ak
    try:
        df = ak.stock_zh_a_spot_em(symbol=code)
        if df is not None and not df.empty:
            return {"current": df["最新价"].iloc[0], "name": df["名称"].iloc[0], ...}
    except:
        return None

# Register the handler (modeled after xalpha.universal.set_handler)
get_rt_handlers.append(eastmoney_rt_handler)
```

### 4.6 [LOW] Historical Data for A+H+US ETF Multi-Asset Support

**Target file**: `/home/admin/.hermes/investment_system/analysis/multi_asset_engine.py`

xalpha's universal.py supports:
- `SH000300` / `SZ399001` — A-share indices via Xueqiu
- `HKHSI` — HK index via Xueqiu
- `^GSPC` — US indices via Yahoo Finance
- `F000001` — Chinese funds via 天天基金
- `B-AA+.3` — Bond rates via Chinabond
- `USD/CNY` — FX rates via Chinamoney

We should build a unified multi-asset data fetcher that wraps these sources, modeled after xalpha's dispatch logic.

---

## 5. Summary

### Adopt directly:
1. `cachedio` data caching decorator pattern
2. Prefix-based data source routing
3. XIRR calculation methodology
4. Lot-level position tracking (remtable)

### Reference for design:
1. `mul.combsummary()` — unified portfolio aggregation
2. `get_rt()` double-check cross-validation
3. `set_handler()` hook pattern
4. `BTE.backtest()` date iteration pattern

### Skip entirely:
1. `realtime.py` — deprecated and unreliable
2. `policy.py` — our strategy patterns are more sophisticated
3. `evaluate.py` — our evaluator_fixed.py is better suited
4. `Grid` / `Tendency28` — built for funds, not stocks
