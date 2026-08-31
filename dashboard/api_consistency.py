"""
数据一致性校验 API — /api/v2/data-consistency
=================================================
P00000 级别要求: 页面任何数字必须与底层数据互相印证, 不允许"改一下又冒出矛盾"。

交叉校验 (trading_signals.json × strategy_states.json × trade_log.json):
  1. 策略现金一致:    portfolios.cash == strategy_states.cash
  2. 持仓一致:        trading_signals.positions 与 strategy_states.positions 同标的同数量
  3. 资金守恒:        cash + Σ(entry_price×qty) ≈ capital (±1元)
  4. 总资产一致:      portfolios.total_value ≈ cash + Σ(current_price×qty)
  5. 今日成交计数:    header 的模拟交易数 == trade_history 中今日笔数
  6. 周频计数:        L6 per-strategy == trade_history 中本周(周一以来)笔数
  7. 交易日志一致:    trade_log.trades 笔数 == trade_history 总笔数
  8. 胜率口径:        win_trades+lose_trades == trade_history 中卖出笔数

返回 {consistent: bool, checks: [{name, ok, detail}], generated_at}
"""
import json
from datetime import date, timedelta
from fastapi import APIRouter
from pathlib import Path

router = APIRouter(tags=["consistency"])

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def _load(name: str) -> dict:
    p = DATA / name
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, KeyError):
        return {}


@router.get("/api/v2/data-consistency")
def data_consistency():
    ts = _load("trading_signals.json")
    st = _load("strategy_states.json")
    tl = _load("trade_log.json")

    checks = []

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    today = date.today().isoformat()
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    strategies = ["faceji", "silverquant", "tradingagents"]
    total_th_rows = 0
    th_by_strat = {}

    # ── 收集 trade_history 统计 ──
    th = ts.get("trade_history", {})
    for sname in strategies:
        txns = th.get(sname, []) or []
        total_th_rows += len(txns)
        th_by_strat[sname] = {
            "today": sum(1 for t in txns if str(t.get("date", ""))[:10] == today),
            "week": sum(1 for t in txns if str(t.get("date", ""))[:10] >= monday),
            "sells": sum(1 for t in txns if str(t.get("action", "")).startswith(("卖", "SELL"))),
        }

    for sname in strategies:
        pf = ts.get("portfolios", {}).get(sname, {})
        st_s = st.get(sname, {})
        ts_pos = ts.get("positions", {}).get(sname, {})
        st_pos = st_s.get("positions", {})
        capital = pf.get("capital", 1_000_000)

        # 1. 现金一致
        add(
            f"{sname}:现金一致",
            abs(pf.get("cash", 0) - st_s.get("cash", 0)) < 0.01,
            f"portfolios.cash={pf.get('cash')} vs states.cash={st_s.get('cash')}",
        )

        # 2. 持仓一致 (标的+数量)
        syms = sorted(set(ts_pos) | set(st_pos))
        mism = [s for s in syms
                if ts_pos.get(s, {}).get("quantity") != st_pos.get(s, {}).get("quantity")]
        add(
            f"{sname}:持仓一致",
            not mism,
            f"symbols={len(syms)} 数量不一致={mism or '无'}",
        )

        # 3. 资金守恒: capital = cash + Σ(未平仓entry×qty) − Σ(累计已实现卖出pnl)
        #    推导: capital = cash + Σ全部成本 − Σ卖出回款
        #          卖出回款 = 成本(已平) + 已实现盈亏 → capital = cash + Σ成本(未平) − 已实现盈亏
        cost = sum(p.get("entry_price", 0) * p.get("quantity", 0) for p in st_pos.values())
        realized = sum(h.get("pnl", 0) or 0 for h in st_s.get("history", [])
                       if str(h.get("action", "")).startswith("卖"))
        conserved = abs((st_s.get("cash", 0) or 0) + cost - realized - capital) < 1.0
        add(
            f"{sname}:资金守恒",
            conserved,
            f"cash({st_s.get('cash'):.2f})+Σ成本({cost:.2f})−已实现盈亏({realized:.2f})={st_s.get('cash',0)+cost-realized:.2f} vs capital({capital})",
        )

        # 4. 总资产一致
        mkt = sum(p.get("current_price", 0) * p.get("quantity", 0) for p in st_pos.values())
        tv = st_s.get("cash", 0) + mkt
        add(
            f"{sname}:总资产一致",
            abs(pf.get("total_value", 0) - tv) < 0.5,
            f"total_value={pf.get('total_value')} vs cash+Σ市值={tv:.2f}",
        )

    # 5-6 已移除 (2026-08-31, IA-P2): 原"今日成交计数一致""周频计数可复算"为恒 True 占位,
    #    并非真校验, 却虚增绿勾通过项数 — 移除避免"数据一致✓"给未经校验的字段背书。
    # 7. trade_log 与 trade_history 总笔数一致
    tl_trades = len(tl.get("trades", []))
    add(
        "交易日志一致",
        tl_trades == total_th_rows,
        f"trade_log.trades={tl_trades} vs trade_history总笔数={total_th_rows}",
    )

    # 8. 胜率口径: win+lose == 卖出笔数
    for sname in strategies:
        pf = ts.get("portfolios", {}).get(sname, {})
        wl = (pf.get("win_trades", 0) or 0) + (pf.get("lose_trades", 0) or 0)
        sells = th_by_strat[sname]["sells"]
        add(
            f"{sname}:胜率口径一致",
            wl == sells,
            f"win+lose({wl}) == 卖出笔数({sells})",
        )

    consistent = all(c["ok"] for c in checks)
    return {
        "status": "ok",
        "consistent": consistent,
        "checks": checks,
        "generated_at": date.today().isoformat(),
    }
