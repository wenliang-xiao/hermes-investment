"""模拟盘/持仓/信号 API"""

import json
from datetime import datetime
from fastapi import APIRouter
from dashboard.shared import (
    ROOT, get_name, load_shadow, build_summary, build_chart_data,
    build_history, _clean_signals, _aggregate_strategy_portfolios,
)
from engine.execution_checker import ExecutionChecker
from engine.evidence_builder import EvidenceBuilder

router = APIRouter()

_checker = ExecutionChecker()
_builder = EvidenceBuilder()


def _calc_stop_loss(entry_price, peak_price=None):
    """P0-7: 止损线 = max(固定止损 entry*0.92, 峰值回落 peak*0.88).

    peak_price 缺省用 entry（无峰值数据时退化为固定止损）。
    返回 round 后的 float。
    """
    base = entry_price * 0.92
    peak = peak_price or entry_price
    trail = peak * 0.88
    return round(max(base, trail), 2)


def _load_scan_score_map() -> dict:
    """scan_snapshot_latest.json → {symbol: score_item} (含 7 维风格分, 供持仓因子雷达)"""
    path = ROOT / "data" / "scan_snapshot_latest.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = json.load(f)
        return {r.get("symbol", ""): r for r in data.get("results", []) if r.get("symbol")}
    except (json.JSONDecodeError, KeyError):
        return {}


def _annotate_signals(all_signals, final_signals, trade_history, today_str, scan_map=None):
    """给原始信号打状态: executed(今日已执行) / filtered(冲突或周频过滤) / pending
    并富集因子数据 (scores/factor_breakdown) 供信号弹窗深度分析"""
    def norm(a):
        a = str(a or "")
        if a.upper().startswith("BUY") or a.startswith("买"):
            return "BUY"
        if a.upper().startswith("SELL") or a.startswith("卖"):
            return "SELL"
        return a.upper()

    executed = set()
    for sname, txns in trade_history.items():
        for t in (txns or []):
            if str(t.get("date", ""))[:10] == today_str:
                executed.add((sname, t.get("symbol"), norm(t.get("action"))))
    final_keys = {(s.get("strategy"), s.get("symbol"), norm(s.get("action")))
                  for s in final_signals}
    scan_map = scan_map or {}
    for s in all_signals:
        k = (s.get("strategy"), s.get("symbol"), norm(s.get("action")))
        if k in executed:
            s["status"] = "executed"
        elif k not in final_keys:
            s["status"] = "filtered"
        else:
            s["status"] = "pending"
        # 因子富集
        fs = scan_map.get(s.get("symbol"), {})
        if fs:
            if not s.get("factor_scores"):
                s["factor_scores"] = fs.get("scores")
            if not s.get("factor_breakdown"):
                s["factor_breakdown"] = fs.get("factor_breakdown")
    return all_signals


@router.get("/api/portfolio")
def api_portfolio():
    book = load_shadow()

    # shadow_account 为空时，从三策略模拟盘聚合真实数据
    if not book.get("positions") and book.get("cash", 0) >= 1000000:
        try:
            aggr = _aggregate_strategy_portfolios()
            if aggr:
                book = aggr
        except Exception:
            pass

    summary = build_summary(book)
    chart = build_chart_data(book)
    history = build_history(book)
    return {
        "summary": summary,
        "chart": chart,
        "history": history[:100],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "history_count": len(book.get("history", [])),
    }


@router.get("/api/signals")
def api_signals():
    """今日实时信号（第三层防护：过滤 price≤0）"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if sig_path.exists():
        with open(sig_path) as f:
            data = json.load(f)
        data["signals"], _dropped = _clean_signals(data.get("signals", []), "api_signals")
        return data
    return {"error": "no signals yet today", "signals": []}


def _load_snapshot_by_date(date_str: str) -> dict:
    """按日期加载扫描快照因子数据 → {symbol: result} (优先当日, 回退最新)"""
    candidates = [
        ROOT / "data" / f"scan_snapshot_{date_str}.json",
        ROOT / "data" / "scan_snapshots" / f"scan_snapshot_{date_str}.json",
        ROOT / "data" / "scan_snapshot_latest.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                with open(p) as f:
                    d = json.load(f)
                return {r.get("symbol", ""): r for r in d.get("results", []) if r.get("symbol")}
            except (json.JSONDecodeError, KeyError):
                continue
    return {}


@router.get("/api/v2/signals/history")
def api_v2_signals_history(date: str = ""):
    """历史信号日志 — 按日期查看, 附因子分解 (signal_accuracy_history.json)"""
    path = ROOT / "data" / "signal_accuracy_history.json"
    if not path.exists():
        return {"dates": [], "date": "", "signals": [], "count": 0}
    with open(path) as f:
        data = json.load(f)
    history = data.get("history", [])
    dates = sorted({str(h.get("date", "")) for h in history if h.get("date")})
    if date:
        sel = [h for h in history if str(h.get("date", "")) == date]
        sigs = sel[0].get("signals", []) if sel else []
        snap = _load_snapshot_by_date(date)
        enriched = []
        for s in sigs:
            row = dict(s)
            fb = snap.get(s.get("symbol", ""), {}).get("factor_breakdown") if snap else None
            sc = snap.get(s.get("symbol", ""), {}).get("scores") if snap else None
            if fb:
                row["factor_breakdown"] = fb
            if sc:
                row["factor_scores"] = sc
            enriched.append(row)
        return {"dates": dates, "date": date, "signals": enriched, "count": len(enriched)}
    return {"dates": dates, "date": "", "signals": [], "count": 0}


@router.get("/api/behavior")
def api_behavior():
    """行为诊断（四维度：处置效应/过度交易/追涨/锚定）"""
    path = ROOT / "data" / "behavior_diagnosis.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"error": "no behavior diagnosis data yet", "strategies": {}}


@router.get("/api/simulated")
def api_simulated():
    """三个策略模拟盘全方位数据"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if not sig_path.exists():
        return {"error": "no simulated data yet", "portfolios": {}}

    with open(sig_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    positions = data.get("positions", {})
    signals, _dropped = _clean_signals(data.get("signals", []), "api_simulated")

    # 模拟交易 = 今日 trade_history 真实成交笔数 (而非本次 run 内的 simulated_trades, 避免漏掉当日早盘已成交)
    today_str = data.get("date", "")
    trade_history = data.get("trade_history", {})
    executed_today = sum(
        1 for sname, txns in trade_history.items()
        for t in (txns or [])
        if str(t.get("date", ""))[:10] == today_str
    )

    # 各策略汇总
    result = {}
    strategy_labels = {
        "faceji": {"name": "面基", "color": "#58a6ff", "style": "面基(评分+趋势+Kelly+SQ风控)"},
        "silverquant": {"name": "SilverQuant", "color": "#3fb950", "style": "组件化(评分建仓+4层风控)"},
        "tradingagents": {"name": "TradingAgents", "color": "#bc8cff", "style": "辩论制(Kelly动态+技术融合)"},
    }

    for sname in ["faceji", "silverquant", "tradingagents"]:
        pf = portfolios.get(sname, {})
        pos = positions.get(sname, {})
        s_sigs = [s for s in signals if s["strategy"] == sname]
        label = strategy_labels.get(sname, {})

        cash = pf.get("cash", 1000000)
        invested = pf.get("total_invested", 0)
        # 总资产 = 现金 + 持仓市值 (优先用生成方算好的 total_value, 兜底用市值重算)
        total_value = pf.get("total_value")
        if total_value is None:
            total_value = cash + sum(
                (pd.get("current_price") or 0) * (pd.get("quantity") or 0)
                for pd in pos.values()
            )
        total_pnl = total_value - 1000000
        total_return = total_pnl / 1000000 * 100

        pos_list = []
        for sym, pd in pos.items():
            entry = pd.get("entry_price", 0)
            current = pd.get("current_price", entry)
            qty = pd.get("quantity", 0)
            cost = entry * qty
            mkt_val = current * qty
            pnl = mkt_val - cost
            pnl_pct = pd.get("pnl_pct", 0)
            pos_list.append({
                "symbol": sym, "name": get_name(sym),
                "entry_price": entry, "current_price": current,
                "quantity": qty, "cost": cost, "market_value": mkt_val,
                "pnl": round(pnl, 2), "pnl_pct": pnl_pct,
                "entry_date": pd.get("entry_date", ""),
                "reason": pd.get("reason", f"建仓评分{pd.get('entry_score','?')}分"),
                "stop_loss": _calc_stop_loss(entry, pd.get("peak_price")),
                "peak_price": pd.get("peak_price", entry),
            })

        # 每个策略的信号也要做 price=0 过滤
        s_sigs = []
        for s in signals:
            if s.get("strategy", "") == sname:
                s_sigs.append(s)
        # 再过滤一遍标的位置中 price=0 的（持仓中已平的无效标的）
        pos_list = [p for p in pos_list if p.get("current_price", 0) > 0]

        result[sname] = {
            "label": label.get("name", sname),
            "color": label.get("color", "#fff"),
            "style": label.get("style", ""),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": sum(1 for p in pos_list if p.get("current_price", 0) > 0),
            "history_count": pf.get("history_count", 0),
            "positions": pos_list,
            "signals": s_sigs,
        }

    ts_mtime = ""
    try:
        _m = (ROOT / "data" / "trading_signals.json").stat().st_mtime
        ts_mtime = datetime.fromtimestamp(_m).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    return {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "signal_file_mtime": ts_mtime,   # 数据文件实际更新时间 (盘前/盘后区分依据)
        "simulated_trades": executed_today,
        "portfolios": result,
        "user_signals": signals,
    }


@router.get("/api/v2/portfolio/detail")
def api_v2_portfolio_detail():
    """模拟盘完整详情 — 持仓+交易历史+信号日志+因子分解"""
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"error": "no data", "date": "", "portfolios": {}, "trade_history": {}, "all_signals": []}

    with open(ts_path) as f:
        data = json.load(f)

    raw_portfolios = data.get("portfolios", {})
    raw_positions = data.get("positions", {})
    raw_signals = data.get("signals", [])
    trade_history = data.get("trade_history", {})
    scan_map = _load_scan_score_map()

    # ── 补充统计字段 (匹配 JS loadDashboardV2 的期望) ──
    strategy_labels = {
        "faceji": {"name": "面基", "color": "#58a6ff", "style": "面基(评分+趋势+Kelly+SQ风控)"},
        "silverquant": {"name": "SilverQuant", "color": "#3fb950", "style": "组件化(评分建仓+4层风控)"},
        "tradingagents": {"name": "TradingAgents", "color": "#bc8cff", "style": "辩论制(Kelly动态+技术融合)"},
    }
    CAPITAL = 1_000_000

    enriched_portfolios = {}
    for sname in ["faceji", "silverquant", "tradingagents"]:
        pf = raw_portfolios.get(sname, {})
        cash = pf.get("cash", CAPITAL)
        invested = pf.get("total_invested", 0)
        # 总资产 = 现金 + 持仓市值 (优先用生成方算好的 total_value, 兜底用市值重算)
        total_value = pf.get("total_value")
        if total_value is None:
            syms = raw_positions.get(sname, {})
            total_value = cash + sum(
                (p.get("current_price") or 0) * (p.get("quantity") or 0)
                for p in syms.values()
            )
        total_pnl = total_value - CAPITAL
        total_return = total_pnl / CAPITAL * 100 if CAPITAL else 0

        # 胜率: 只统计已平仓(卖出)且有盈亏记录的交易; 无平仓 → None(前端显示 —)
        txns = trade_history.get(sname, [])
        closed = [t for t in txns
                  if str(t.get("action", "")).startswith(("卖", "SELL", "sell"))
                  and t.get("pnl") is not None]
        wins = sum(1 for t in closed if t.get("pnl", 0) > 0)
        win_rate = round(wins / len(closed) * 100, 1) if closed else None

        label = strategy_labels.get(sname, {})
        enriched_portfolios[sname] = {
            "label": label.get("name", sname),
            "color": label.get("color", "#fff"),
            "style": label.get("style", ""),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": pf.get("position_count", 0),
            "history_count": pf.get("history_count", 0),
            "win_rate": win_rate,
            # P0-9 (2026-08-31): 胜率口径透明化 — 前端显示 "平仓N / 胜M", N<10 显示样本不足
            "closed_count": len(closed),
            "win_trades": wins,
        }

    # ── 补充持仓字段 ──
    enriched_positions = {}
    for sname in ["faceji", "silverquant", "tradingagents"]:
        syms = raw_positions.get(sname, {})
        pf = raw_portfolios.get(sname, {})
        pf_cash = pf.get("cash", CAPITAL)
        pos_list = {}
        for sym, pos in syms.items():
            entry = pos.get("entry_price", 0)
            current = pos.get("current_price", entry)
            qty = pos.get("quantity", 0)
            cost = entry * qty
            mkt_val = current * qty
            pnl = mkt_val - cost
            pnl_pct = round((current - entry) / entry * 100, 2) if entry else 0
            hold_days = 0
            if pos.get("entry_date"):
                try:
                    ed = datetime.strptime(pos["entry_date"], "%Y-%m-%d")
                    hold_days = (datetime.now() - ed).days
                except ValueError:
                    pass

            # 仓位占比
            total_assets = pf_cash + sum(p.get("current_price", 0) * p.get("quantity", 0) for p in syms.values())
            pct = round(mkt_val / total_assets * 100, 2) if total_assets else 0

            pos_list[sym] = {
                "symbol": sym,
                "name": get_name(sym),
                "entry_price": entry,
                "current_price": current,
                "quantity": qty,
                "pnl": round(pnl, 2),
                "pnl_pct": pnl_pct,
                "hold_days": hold_days,
                "entry_date": pos.get("entry_date", ""),
                "reason": pos.get("reason", f"建仓评分{pos.get('entry_score', '?')}分") if pos.get("reason") else "无理由（需run_trading生成）",
                "stop_loss": _calc_stop_loss(entry, pos.get("peak_price")),
                "pct": pct,
                "peak_price": pos.get("peak_price", entry),
                "drawdown_from_peak": pos.get("drawdown_from_peak", 0),
                "drawdown_from_entry": pos.get("drawdown_from_entry", 0),
                "entry_score": pos.get("entry_score"),
                "current_score": pos.get("current_score"),
                # 无持仓因子数据时, 从当日扫描快照富集 7 维风格分 (修复"无因子数据")
                "factor_scores": pos.get("factor_scores")
                                  or scan_map.get(sym, {}).get("scores"),
                "is_delisted": not current or current <= 0,
                "evidence": _build_position_evidence(
                    sym, current, qty, entry, pnl,
                    {**pos, "factor_scores": pos.get("factor_scores") or scan_map.get(sym, {}).get("scores")},
                    sname),
            }
        enriched_positions[sname] = pos_list

    final_sigs = _clean_signals(raw_signals, "v2_detail")[0]
    all_sigs = data.get("all_signals", [])
    _annotate_signals(all_sigs, final_sigs, trade_history, data.get("date", ""), scan_map)

    # ── 富集交易历史: 股票名/买入行浮盈亏+持有天数/因子分解(供弹窗深度解析) ──
    enriched_th = {}
    for sname, txns in trade_history.items():
        rows = []
        for t in (txns or []):
            sym = t.get("symbol", "")
            row = dict(t)
            row["name"] = get_name(sym) or t.get("name", "")
            pos = enriched_positions.get(sname, {}).get(sym)
            if str(t.get("action", "")).startswith("买"):
                # 买入行: 若仍在持仓 → 浮盈亏 + 持仓至今; 否则 — 
                if pos:
                    row["current_price"] = pos.get("current_price")
                    row["hold_days"] = pos.get("hold_days")
                    row["unrealized_pnl"] = pos.get("pnl")
                    row["unrealized_pnl_pct"] = pos.get("pnl_pct")
                else:
                    row["unrealized_pnl"] = None
                    row["unrealized_pnl_pct"] = None
            # 深度数据: 因子分解 + 7维风格分 (供买入/卖出逻辑弹窗)
            fs = scan_map.get(sym)
            if fs:
                row["factor_scores"] = fs.get("scores")
                row["factor_breakdown"] = fs.get("factor_breakdown")
                if not row.get("score") and fs.get("score"):
                    row["score"] = fs.get("score")
            rows.append(row)
        enriched_th[sname] = rows

    # 模拟交易 = 今日 trade_history 真实成交笔数 (本次 run 的 simulated_trades 只计本轮, 会漏早盘成交)
    today_str = data.get("date", "")
    executed_today = sum(
        1 for sname, txns in trade_history.items()
        for t in (txns or [])
        if str(t.get("date", ""))[:10] == today_str
    )

    ts_mtime = ""
    try:
        _m = (ROOT / "data" / "trading_signals.json").stat().st_mtime
        ts_mtime = datetime.fromtimestamp(_m).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    result = {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "signal_file_mtime": ts_mtime,   # 数据文件实际更新时间 (盘前/盘后区分依据)
        "total_raw_signals": data.get("total_raw_signals", 0),
        "after_conflict_resolution": data.get("after_conflict_resolution", 0),
        "after_weekly_filter": data.get("after_weekly_filter", 0),
        "simulated_trades": executed_today,
        "portfolios": enriched_portfolios,
        "positions": enriched_positions,
        "trade_history": enriched_th,
        "final_signals": final_sigs,
        "all_signals": all_sigs,
    }

    return result


def _build_position_evidence(sym, current, qty, entry, pnl, pos, strategy):
    """为持仓构建TrailStop证据包"""
    position_data = {"entry_price": entry, "current_price": current,
                     "quantity": qty, "pnl": pnl, "_peak_price": pos.get("peak_price", current)}
    # P0-8 (2026-08-31): 证据链与因子分自洽 — 旧实现只传 position, EvidenceBuilder 的
    # factor 层从 score_data 读因子, 从不传 → 永远"无因子数据"。这里把持仓携带的
    # factor_scores/factor_breakdown 组装成 score_data 传入。
    factor_scores = pos.get("factor_scores") or {}
    factor_breakdown = pos.get("factor_breakdown") or {}
    if factor_scores or factor_breakdown:
        score_data = {
            "symbol": sym,
            "factor_scores": factor_scores,
            "factor_breakdown": factor_breakdown,
            "score": factor_scores.get("composite") or pos.get("current_score") or pos.get("entry_score"),
        }
    else:
        score_data = None
    check = _checker.check(sym, position=position_data)
    packet = _builder.build(sym, score_data=score_data, position=position_data)
    return {"trail_stop": check.get("trail_stop", {}), "evidence_packet": packet.to_dict()}


def _build_price_snapshot_map(trade_history_by_strat: dict, lookback_days: int = 250) -> dict:
    """为净曲线构建 {symbol: {date: close}} 快照价映射 (供中间点 mark-to-market)。

    P1 (2026-08-31): 旧实现中间点用 entry_price(成本价) 计算持仓市值 → 浮盈
    不随市价变化(平台), 只有末点被 total_value 校准。修复: 逐日重建时用当日
    快照价 (forward-fill 最近可得价)。

    只拉 trade_history 出现过的 symbol (模拟盘持仓少, 快); 拉取失败返回空映射
    → 调用方降级回 entry_price (不崩溃)。
    """
    symbols = sorted({
        str(t.get("symbol", ""))
        for hist in trade_history_by_strat.values()
        for t in hist if t.get("symbol")
    })
    if not symbols:
        return {}
    # 行情窗口: 最早交易日前推 (覆盖首笔交易日), 取最近 lookback_days
    all_dates = [str(t.get("date", "")) for hist in trade_history_by_strat.values()
                 for t in hist if t.get("date")]
    min_date = min(all_dates) if all_dates else None

    snap: dict[str, dict[str, float]] = {}
    for sym in symbols:
        try:
            from data.data_router import get_history
            r = get_history(sym, days=lookback_days)
            if not r or not r.get("dates") or not r.get("close"):
                continue
            dates = [str(d)[:10] for d in r["dates"]]
            closes = [float(c) if c else None for c in r["close"]]
            m: dict[str, float] = {}
            for d, c in zip(dates, closes):
                if c is not None and c > 0:
                    m[d] = c
            if min_date:
                # 只保留覆盖窗口内的日期 (最早交易日前 ~5 天)
                from datetime import datetime as _dt, timedelta as _td
                try:
                    cutoff = (_dt.strptime(min_date, "%Y-%m-%d") - _td(days=5)).strftime("%Y-%m-%d")
                    m = {d: c for d, c in m.items() if d >= cutoff}
                except ValueError:
                    pass
            if m:
                snap[sym] = m
        except Exception:
            continue
    return snap


def _snapshot_price(snap: dict, sym: str, day: str) -> float | None:
    """查询 sym 在 day 的快照价 (无当日价时向前找最近价 forward-fill)。"""
    m = snap.get(sym)
    if not m:
        return None
    if day in m:
        return m[day]
    # 向前找最近可得价 (工作日错位/停牌)
    for i in range(1, 10):
        from datetime import datetime as _dt, timedelta as _td
        try:
            prev = (_dt.strptime(day, "%Y-%m-%d") - _td(days=i)).strftime("%Y-%m-%d")
        except ValueError:
            return None
        if prev in m:
            return m[prev]
    return None


@router.get("/api/v2/portfolio/netvalue")
def api_v2_portfolio_netvalue():
    """净值曲线 — 每日 mark-to-market (P0-6 修复)

    旧实现只在"卖出"日累加已实现盈亏, 持仓浮盈不进曲线, 且同日多笔交易产生
    重复日期点。新实现:
      - 把 trade_history 按日期排序, 逐日重建持仓 (买入进仓/卖出平仓)
      - 每日净值 = 初始资金 + 已实现盈亏累计 + 未平仓浮盈 (用当日快照 current_price)
      - 同日多笔交易聚合为 1 个点 (自然日去重)
      - 末点用生成方 total_value 校准 (现金+持仓市值)
    """
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"error": "no data", "labels": [], "series": []}

    with open(ts_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    trade_history = data.get("trade_history", {})
    raw_positions = data.get("positions", {})
    capital_default = 1_000_000

    # P1 (2026-08-31): 中间点 mark-to-market — 预构建快照价映射
    snap = _build_price_snapshot_map(trade_history)

    series = []
    for strat_name, strat_data in portfolios.items():
        history = sorted(
            [t for t in trade_history.get(strat_name, []) if t.get("date")],
            key=lambda t: t["date"],
        )
        capital = strat_data.get("capital", capital_default)
        # 逐日重建: {symbol: {"qty": int, "entry_price": float, "pnl_cum": 累计已实现}}
        holdings: dict[str, dict] = {}
        realized_pnl = 0.0
        day_map: dict[str, float] = {}  # date -> 当日净值

        for trade in history:
            d = trade["date"]
            sym = trade.get("symbol", "")
            action = str(trade.get("action", ""))
            qty = float(trade.get("quantity", 0) or 0)
            price = float(trade.get("price", 0) or 0)
            pnl = float(trade.get("pnl", 0) or 0)

            if action.startswith(("买", "BUY", "buy")):
                if sym not in holdings:
                    holdings[sym] = {"qty": 0.0, "entry_price": price}
                holdings[sym]["qty"] += qty
                holdings[sym]["entry_price"] = price
            elif action.startswith(("卖", "SELL", "sell")):
                realized_pnl += pnl
                if sym in holdings:
                    holdings[sym]["qty"] = max(0.0, holdings[sym]["qty"] - qty)
                    if holdings[sym]["qty"] <= 0:
                        del holdings[sym]

            # 当日市值 = 现金 + Σ持仓市值 (当日快照价, 无行情时降级成本价)
            pos_mv = 0.0
            for sym, h in holdings.items():
                if h["qty"] > 0:
                    snap_price = _snapshot_price(snap, sym, d)
                    val_price = snap_price or h["entry_price"] or price
                    pos_mv += h["qty"] * val_price
            day_map[d] = round(capital + realized_pnl + (pos_mv - 0), 2)

        if not day_map:
            # P2 (2026-09-01): 0 笔交易策略(如 TradingAgents)不整条消失, 输出平直基准线。
            # 用其他策略的日期范围对齐(若有), 否则用生成日单点。
            total_value = round(strat_data.get("total_value", capital), 2)
            all_dates = sorted({
                str(t.get("date", ""))
                for hist in trade_history.values()
                for t in hist if t.get("date")
            })
            # P2 (2026-08-31): 0笔策略归一化到 1.0 平线 — 与其他策略/基准同尺度
            values = [1.0] * max(len(all_dates), 1)
            if len(all_dates) >= 2:
                labels = all_dates
            else:
                d = data.get("date") or datetime.now().strftime("%Y-%m-%d")
                labels = [d]
            series.append({
                "label": strat_data.get("label", strat_name),
                "name": strat_name,
                "labels": labels,
                "values": values,
                "total_return": strat_data.get("total_return", 0),
                "color": {"faceji": "#58a6ff", "silverquant": "#f0883e", "tradingagents": "#bc8cff"}.get(strat_name, "#7ee787"),
            })
            continue

        # 末点校准: 用生成方 total_value (现金+当前持仓市值)
        days_sorted = sorted(day_map.keys())
        total_value = strat_data.get("total_value", capital + realized_pnl)
        day_map[days_sorted[-1]] = round(total_value, 2)

        labels = days_sorted
        # P2 (2026-08-31): 归一化到首日=1.0 — 与沪深300基准同尺度可叠加 (相对收益曲线)
        base_val = day_map[labels[0]] if labels else None
        if base_val and base_val > 0:
            values = [round(day_map[d] / base_val, 4) for d in labels]
        else:
            values = [day_map[d] for d in labels]

        series.append({
            "label": strat_data.get("label", strat_name),
            "name": strat_name,
            "labels": labels,
            "values": values,
            "total_return": strat_data.get("total_return", 0),
            "color": {"faceji": "#58a6ff", "silverquant": "#f0883e", "tradingagents": "#bc8cff"}.get(strat_name, "#7ee787"),
        })

    # ── P2 (2026-08-31): 沪深300基准叠加 (归一化到首日=1.0, 与策略同尺度) ──
    # 对齐 series[0].labels (Chart.js 所有 datasets 共享 x 轴 labels)
    if series:
        bm_labels = series[0].get("labels") or []
        if len(bm_labels) >= 2:
            try:
                from data.data_router import get_history as _gh
                hs300 = _gh("sh.000300", days=500)
                if hs300 and hs300.get("dates") and hs300.get("close"):
                    hs_map = {}
                    for d, c in zip(
                        [str(x)[:10] for x in hs300["dates"]],
                        [float(x) if x else None for x in hs300["close"]],
                    ):
                        if c and c > 0:
                            hs_map[d] = c
                    bm_vals = []
                    last_v = None
                    from datetime import timedelta as _td
                    for d in bm_labels:
                        v = None
                        for i in range(0, 15):  # forward-fill 最近可得日
                            cand = d if i == 0 else (
                                (datetime.strptime(d, "%Y-%m-%d") - _td(days=i)).strftime("%Y-%m-%d")
                            )
                            if cand in hs_map:
                                v = hs_map[cand]
                                break
                        if v is not None:
                            last_v = v
                        bm_vals.append(last_v)
                    bm_vals = [v for v in bm_vals if v]
                    if len(bm_vals) == len(bm_labels) and bm_vals[0] and bm_vals[0] > 0:
                        b_base = bm_vals[0]
                        series.append({
                            "label": "沪深300",
                            "name": "沪深300",
                            "labels": bm_labels,
                            "values": [round(v / b_base, 4) for v in bm_vals],
                            "total_return": round((bm_vals[-1] / b_base - 1) * 100, 2),
                            "color": "#e3b341",
                            "benchmark": True,
                        })
            except Exception as e:
                print(f"[netvalue] 沪深300基准获取失败: {e}")

    return {"labels": series[0]["labels"] if series else [], "series": series}


@router.get("/api/v2/reports")
def api_v2_reports():
    """日报链接列表"""
    path = ROOT / "data" / "daily_report_links.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []
