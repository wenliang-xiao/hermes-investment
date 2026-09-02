"""data/sources/eastmoney_source.py — 东财资金流/板块资金流数据源

补"情绪/资金流"因子缺失。依据 a-stock-data(Simon林) 实测：百度 PAE 资金流/板块归属
已失效(ResultCode 10003)，东财 push2 是零鉴权替代。内置 em_get 限流防封
(东财 push2 有 IP 级风控：每秒>5次/并发>=10 会封 20+ 小时)。
"""
from __future__ import annotations

import time
import random
import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

EM_MIN_INTERVAL = 1.0  # 两次东财请求最小间隔(秒)，批量可调大
_em_last_call = [0.0]
_EM_SESSION = requests.Session()
_EM_SESSION.headers.update({"User-Agent": UA})


def _em_get(url: str, params: dict | None = None, headers: dict | None = None,
            timeout: int = 15):
    """东财统一请求入口：串行限流(最小间隔+随机抖动) + 会话复用，防 IP 封禁。"""
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    try:
        return _EM_SESSION.get(url, params=params, headers=headers, timeout=timeout)
    finally:
        _em_last_call[0] = time.time()


def _em_secid(code: str) -> str:
    """东财 push2 的 secid，如 1.600519 / 0.300750。"""
    market = "1" if code.startswith(("6", "5", "9")) else "0"
    return f"{market}.{code}"


_BOARD_FS = {"industry": "m:90+t:2", "concept": "m:90+t:3", "region": "m:90+t:1"}
# 周期 → (排序fid, 主力净额, 主力净占比, 涨跌幅, 领涨股name)；四档明细仅今日
_BOARD_PERIOD = {
    "today": ("f62", "f62", "f184", "f3", "f204"),
    "5d": ("f164", "f164", "f165", "f109", "f257"),
    "10d": ("f174", "f174", "f175", "f160", None),
}


def get_board_fund_flow(board_type: str = "industry", period: str = "today",
                        top_n: int = 20) -> dict:
    """板块资金流向排名(按主力净流入降序)。

    board_type: industry(行业) / concept(概念) / region(地域)
    period: today(今日) / 5d / 10d
    返回: {board_type, period, total, rows:[{rank,name,code,change_pct,
           main_net(主力净额,元), main_pct(主力净占比,%), leader,
           super_large_net/large_net/medium_net/small_net(仅today)]}
    """
    if board_type not in _BOARD_FS:
        raise ValueError(f"board_type 须为 {list(_BOARD_FS)}")
    if period not in _BOARD_PERIOD:
        raise ValueError(f"period 须为 {list(_BOARD_PERIOD)}")
    fid, f_main, f_pct, f_chg, f_leader = _BOARD_PERIOD[period]

    fields = ["f12", "f14", f_chg, f_main, f_pct]
    if f_leader:
        fields.append(f_leader)
    if period == "today":
        fields += ["f66", "f72", "f78", "f84"]  # 超大/大/中/小单净额

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    base = {
        "pz": "200", "po": "1", "np": "1", "fltt": "2", "invt": "2",
        "fid": fid, "fs": _BOARD_FS[board_type],
        "fields": ",".join(dict.fromkeys(fields)),
    }

    def _page(pn: int):
        r = _em_get(url, params={**base, "pn": str(pn)},
                    headers={"User-Agent": UA}, timeout=15)
        d = r.json().get("data") or {}
        return (d.get("diff") or []), int(d.get("total") or 0)

    items, total = _page(1)
    rows = []
    for i, it in enumerate(items[:top_n]):
        row = {
            "rank": i + 1, "name": it.get("f14", ""), "code": it.get("f12", ""),
            "change_pct": it.get(f_chg, 0),
            "main_net": it.get(f_main, 0),
            "main_pct": it.get(f_pct, 0),
            "leader": it.get(f_leader, "") if f_leader else "",
        }
        if period == "today":
            row.update({
                "super_large_net": it.get("f66", 0),
                "large_net": it.get("f72", 0),
                "medium_net": it.get("f78", 0),
                "small_net": it.get("f84", 0),
            })
        rows.append(row)

    return {"board_type": board_type, "period": period,
            "total": total, "rows": rows}


def get_stock_fund_flow_minute(code: str) -> list[dict]:
    """个股资金流向(分钟级, 当日盘中)。

    返回: [{time, main_net, small_net, mid_net, large_net, super_net}, ...] 单位元。
    main_net=主力净流入, 正=流入(看多), 负=流出(看空)。
    """
    secid = _em_secid(code)
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    try:
        r = _em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except Exception:
        return []

    rows = []
    for line in (d.get("data") or {}).get("klines") or []:
        parts = line.split(",")
        if len(parts) >= 6:
            rows.append({
                "time": parts[0],
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "large_net": float(parts[4]),
                "super_net": float(parts[5]),
            })
    return rows


def get_stock_fund_flow_today(code: str) -> float:
    """个股当日主力净流入(元)，分钟级累计。无数据返回 0。"""
    rows = get_stock_fund_flow_minute(code)
    if not rows:
        return 0.0
    return sum(r["main_net"] for r in rows)
