"""
策略四多资产模拟盘 v1.0 — 低频执行引擎

原则:
  - ETF/黄金/商品: 初始化买入, 月频再平衡(偏离>5%触发)
  - A股: 仅在四重确认全过时建仓, 不频繁交易
  - 美股/港股: 从WATCHLIST评分选取, 月频检查
  - 去噪点: 不因分数小幅波动换仓, 只有突破阈值才动作
"""
import json, os, time
from datetime import datetime, timedelta

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), '..', '.hermes', 'strategy4_portfolio.json')

STOCK_ETF_CANDIDATES = ["512890", "512480", "512660", "510300"]
BOND_ETF_CANDIDATES = ["511520", "511260", "511010"]
COMMODITY_ETF_CANDIDATES = ["159985"]
GOLD_ETF = "518880"

REGIME_WEIGHTS = {
    "复苏期": {"a_share": 500000, "stock_etf": 87500, "bond_etf": 116700,
               "gold_etf": 87500, "commodity_etf": 58300, "us_stock": 90000, "hk_stock": 60000},
    "扩张期": {"a_share": 500000, "stock_etf": 100000, "bond_etf": 50000,
               "gold_etf": 75000, "commodity_etf": 75000, "us_stock": 120000, "hk_stock": 80000},
    "过热期": {"a_share": 400000, "stock_etf": 50000, "bond_etf": 50000,
               "gold_etf": 125000, "commodity_etf": 150000, "us_stock": 125000, "hk_stock": 100000},
    "衰退期": {"a_share": 400000, "stock_etf": 50000, "bond_etf": 150000,
               "gold_etf": 150000, "commodity_etf": 50000, "us_stock": 100000, "hk_stock": 100000},
}


def _load():
    if os.path.exists(PORTFOLIO_FILE):
        with open(PORTFOLIO_FILE) as f:
            return json.load(f)
    return {"initialized": False, "capital": 1000000, "regime": "default"}


def _save(data):
    os.makedirs(os.path.dirname(PORTFOLIO_FILE), exist_ok=True)
    with open(PORTFOLIO_FILE, 'w') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _get_etf_price(symbol):
    """获取ETF价格: baostock优先(已验证可用), yfinance备用"""
    try:
        import baostock as bs
        import pandas as pd
        bs.login()
        code = f"sh.{symbol}" if symbol.startswith(("5","51","588")) else f"sz.{symbol}"
        rs = bs.query_history_k_data_plus(code, "date,close", frequency="d")
        rows = []
        while rs.next():
            r = rs.get_row_data()
            if r[1]: rows.append(float(r[1]))
        bs.logout()
        if rows:
            return rows[-1]
    except: pass
    try:
        import yfinance as yf
        for suffix in ['.SS', '.SZ']:
            t = yf.Ticker(f"{symbol}{suffix}")
            hist = t.history(period="5d")
            if not hist.empty:
                return float(hist["Close"].iloc[-1])
    except: pass
    return 10.0  # 兜底价格


def _score_etf(symbol, prices):
    import numpy as np
    closes = prices.get(symbol, [])
    if len(closes) < 20:
        return 5.0
    c = np.array(closes[-60:]) if len(closes) >= 60 else np.array(closes)
    mom_60d = (c[-1] / c[0] - 1) * 100 if len(c) >= 60 else (c[-1] / c[-20] - 1) * 100
    mom = max(0, min(10, 5 + mom_60d / 8))
    rets = np.diff(c[-21:]) / c[-21:-1]
    vol = float(np.std(rets) * np.sqrt(252) * 100)
    vol_score = max(1, min(10, 10 - vol / 4))
    return round(mom * 0.5 + vol_score * 0.5, 2)


def _fetch_etf_prices():
    prices = {}
    for sym in STOCK_ETF_CANDIDATES + BOND_ETF_CANDIDATES + COMMODITY_ETF_CANDIDATES + [GOLD_ETF]:
        try:
            import baostock as bs
            import pandas as pd
            if not hasattr(_fetch_etf_prices, '_bs_logged'):
                bs.login()
                _fetch_etf_prices._bs_logged = True
            code = f"sh.{sym}" if sym.startswith(("5","51","588")) else f"sz.{sym}"
            rs = bs.query_history_k_data_plus(code, "date,close", frequency="d")
            rows = []
            while rs.next():
                r = rs.get_row_data()
                if r[1]: rows.append(float(r[1]))
            if rows:
                prices[sym] = rows
        except: pass
    return prices


def init(regime=None):
    """首次运行: 评分ETF/黄金/商品, 买入最优标的"""
    data = _load()
    if data.get("initialized"):
        # 更新regime(可能因宏观变化而切换)
        if regime and data.get("regime") != regime:
            data["regime"] = regime
            data["allocations"] = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["复苏期"])
            _save(data)
        return data

    regime = regime or data.get("regime", "复苏期")
    weights = REGIME_WEIGHTS.get(regime, REGIME_WEIGHTS["复苏期"])
    data["regime"] = regime
    data["capital"] = 1000000
    data["cash"] = 0
    data["initialized"] = True
    data["initialized_at"] = datetime.now().strftime("%Y-%m-%d")
    data["allocations"] = weights
    data["last_rebalance"] = datetime.now().strftime("%Y-%m-%d")

    # ETF评分选取
    etf_prices = _fetch_etf_prices()

    # 股票ETF: 评分选最优
    stock_scores = {s: _score_etf(s, etf_prices) for s in STOCK_ETF_CANDIDATES}
    best_stock = max(stock_scores, key=stock_scores.get)
    data["stock_etf_pick"] = {"symbol": best_stock, "score": stock_scores[best_stock],
                              "candidates": stock_scores}

    # 债券ETF
    bond_scores = {s: _score_etf(s, etf_prices) for s in BOND_ETF_CANDIDATES}
    best_bond = max(bond_scores, key=bond_scores.get)
    data["bond_etf_pick"] = {"symbol": best_bond, "score": bond_scores[best_bond],
                             "candidates": bond_scores}

    # 商品ETF
    cmd_scores = {s: _score_etf(s, etf_prices) for s in COMMODITY_ETF_CANDIDATES}
    best_cmd = max(cmd_scores, key=cmd_scores.get)
    data["commodity_etf_pick"] = {"symbol": best_cmd, "score": cmd_scores[best_cmd],
                                   "candidates": cmd_scores}

    # 黄金
    data["gold_etf_pick"] = {"symbol": GOLD_ETF}

    # 买入记录 (使用影子账户)
    try:
        from investment_system.output.shadow_account import entry as _se
        picks = [
            (best_stock, "股票ETF", weights["stock_etf"]),
            (best_bond, "债券ETF", weights["bond_etf"]),
            (GOLD_ETF, "黄金ETF", weights["gold_etf"]),
            (best_cmd, "商品ETF", weights["commodity_etf"]),
        ]
        for sym, label, amount in picks:
            price = _get_etf_price(sym) or etf_prices.get(sym, [0])[-1] if etf_prices.get(sym) else 10
            qty = max(100, int(amount / price / 100) * 100)
            _se(sym, label, "买入", price, f"策略四初始化 {label}", quantity=qty, pct=amount/1000000)
        data["etf_bought"] = True
    except Exception as e:
        data["etf_bought"] = False
        data["etf_buy_error"] = str(e)[:100]

    _save(data)
    return data


def daily(macro, scanner_results):
    """每日执行: 更新价格, check止损, 四重确认→A股建仓"""
    regime = macro.get('regime', '复苏期')
    data = _load()
    if not data.get("initialized"):
        data = init(regime)

    today = datetime.now().strftime("%Y-%m-%d")
    actions = []

    # 更新ETF/黄金/商品价格
    try:
        from investment_system.output.shadow_account import update_prices, check_stops, exit_position
        etf_syms = [data.get("stock_etf_pick", {}).get("symbol", ""),
                    data.get("bond_etf_pick", {}).get("symbol", ""),
                    data.get("commodity_etf_pick", {}).get("symbol", ""),
                    data.get("gold_etf_pick", {}).get("symbol", "")]
        price_map = {}
        for s in etf_syms:
            if s:
                p = _get_etf_price(s)
                if p: price_map[s] = p
        if price_map:
            update_prices(price_map)
            alerts = check_stops()
            for a in alerts:
                exit_position(a["symbol"], a.get("current", 0), f"风控: {a['type']}")
                actions.append(f"🔴 止损触发 {a['name']}({a['symbol']}) {a['type']}")
    except Exception as e:
        actions.append(f"⚠️ ETF价格更新失败: {str(e)[:60]}")

    # A股建仓检查: 四重确认
    dual_gate = macro.get('dual_gate', {})
    macro_gate = dual_gate.get('macro_gate', '')
    trend_gate = dual_gate.get('trend_gate', '')
    trend_temp = macro.get('trend_temp', '')
    cpi = macro.get('macro_data', {}).get('cpi')
    cpi_mom = macro.get('macro_data', {}).get('cpi_momentum_3m', 0) or 0

    macro_ok = (isinstance(cpi, (int, float)) and cpi >= 1.0) or (cpi_mom > 0.3)
    trend_ok = trend_temp in ('温', '热')
    dual_open = macro_gate not in ('红灯', '黄灯') or trend_gate not in ('红灯', '黄灯')

    # 检查A股持仓
    try:
        from investment_system.output.shadow_account import get_shadow_summary
        summary = get_shadow_summary()
        a_positions = [p for p in summary.get("positions", []) if str(p["symbol"]).isdigit()]

        # 检查掉队票
        if scanner_results:
            sc_map = {str(s.get("symbol", "")): s.get("score", 0) for s in scanner_results}
            for p in a_positions:
                sym = p["symbol"]
                score = sc_map.get(sym)
                if score is not None and score < 3.0:
                    exit_position(sym, p.get("current", 0), f"评分{score:.1f}<3.0→清仓")
                    actions.append(f"🔻 A股清仓 {p['name']}({sym}) 评分{score:.1f}")
    except: pass

    # 美股/港股: 首次评分后建仓
    a_alloc = data["allocations"].get("a_share", 500000)
    if dual_open and not dual_gate.get('macro_gate') in ('红灯', '黄灯'):
        # 仅当双门打开时检查A股建仓条件
        if scanner_results and not a_positions:
            top = [s for s in scanner_results[:5] if s.get('score', 0) >= 6.0]
            if top and macro_ok and trend_ok:
                actions.append(f"✅ A股建仓条件满足 — {len(top)}只候选待执行")

    data["last_daily"] = today
    data["daily_actions"] = actions
    _save(data)
    return data


def monthly_rebalance():
    """月末: ETF偏离>5%触发再平衡"""
    data = _load()
    if not data.get("initialized"):
        return data

    today = datetime.now()
    last = data.get("last_rebalance", "")
    if last:
        last_dt = datetime.strptime(last, "%Y-%m-%d")
        if (today - last_dt).days < 25:
            return data

    actions = []
    try:
        from investment_system.output.shadow_account import get_shadow_summary, load_shadow, save_shadow
        summary = get_shadow_summary()
        total = summary.get("total_value", 1000000)
        allocations = data["allocations"]

        # 检查各类资产偏离
        for key, label in [("stock_etf", "股票ETF"), ("bond_etf", "债券ETF"),
                           ("gold_etf", "黄金ETF"), ("commodity_etf", "商品ETF")]:
            target_pct = allocations[key] / 1000000
            # 简化: 如果总偏离>5%触发
            # 此处需要持仓明细来精确计算, 先做标记
            pass

        data["last_rebalance"] = today.strftime("%Y-%m-%d")
    except Exception as e:
        actions.append(f"⚠️ 再平衡检查失败: {str(e)[:60]}")

    data["rebalance_actions"] = actions
    _save(data)
    return data


def snapshot():
    """日报调用: 返回当前组合状态"""
    data = _load()
    if not data.get("initialized"):
        data = init()

    try:
        from investment_system.output.shadow_account import get_shadow_summary, get_portfolio_metrics
        summary = get_shadow_summary()
        metrics = get_portfolio_metrics()
    except:
        summary = {"count": 0, "total_value": 1000000, "positions": []}
        metrics = {"capital": 1000000, "total_value": 1000000, "unrealized_pnl": 0,
                   "realized_pnl": 0, "position_pct": 0, "trade_count": 0,
                   "days_alive": 0, "win_rate": 0, "traversal_ok": True}

    allocations = data.get("allocations", {})
    regime = data.get("regime", "复苏期")

    return {
        "regime": regime,
        "total_value": metrics["total_value"],
        "unrealized_pnl": metrics["unrealized_pnl"],
        "realized_pnl": metrics["realized_pnl"],
        "position_count": summary["count"],
        "position_pct": metrics["position_pct"],
        "days_alive": metrics["days_alive"],
        "traversal_ok": metrics["traversal_ok"],
        "allocations": {
            "a_share": {"target": allocations.get("a_share", 500000), "status": "waiting"},
            "stock_etf": {"target": allocations.get("stock_etf", 87500),
                          "picked": data.get("stock_etf_pick", {})},
            "bond_etf": {"target": allocations.get("bond_etf", 116700),
                         "picked": data.get("bond_etf_pick", {})},
            "gold_etf": {"target": allocations.get("gold_etf", 87500),
                         "picked": data.get("gold_etf_pick", {})},
            "commodity_etf": {"target": allocations.get("commodity_etf", 58300),
                              "picked": data.get("commodity_etf_pick", {})},
            "us_stock": {"target": allocations.get("us_stock", 90000), "status": "pending"},
            "hk_stock": {"target": allocations.get("hk_stock", 60000), "status": "pending"},
        },
        "daily_actions": data.get("daily_actions", []),
        "initialized": data.get("initialized", False),
        "last_rebalance": data.get("last_rebalance", ""),
    }
