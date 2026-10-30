"""日报选股宇宙 — 用 v4 因子引擎全池 + 板块配额替代 v3.1 的 18 只硬截断

背景 (2026-10-30)
──────────────
旧实现 run_daily.py:399 `scanner.MAX_SCAN = 18`, 且 factor_scanner 按宏观象限硬分配名额:
复苏期 → 消费4/金融4/汽车4/地产4 + 科技2 = 18, 半导体/AI算力/新能源/军工/医药 名额为 0。
后果: 连续多日 TOP10 是同一批 12 只票, 半导体在任何情况下都进不了榜。

新实现原则
─────────
1. 不排名不淘汰: 全池 89 只 (v4 factor_daily.json) 都进候选, 不再硬截断
2. 板块覆盖: sector_leaders() 每板块取前 N 只做"板块代表榜", 防止消费/金融垄断
3. 口径唯一: 分数 = v4 composite × 10, 与 Dashboard /api/v2/pool 同一引擎
4. 行情补充: 名称/价格/涨跌幅/PE 从腾讯实时行情补, 补不到不阻塞 (降级为裸代码)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Callable

logger = logging.getLogger(__name__)

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SECTOR_MIN_QUOTA = 3      # 板块代表榜每板块取前 N 只 (默认 3)
SCORE_SCALE = 10.0        # composite(0-1) → 日报 0-10 分制


# ═══════════════════════════════════════════
# 板块映射 (纯函数, 不依赖 IO)
# ═══════════════════════════════════════════
def _sector_map() -> dict[str, str]:
    """symbol → LDS 板块名。延迟导入避免循环依赖。"""
    try:
        from domain.stock_universe import LDS_SECTORS
    except Exception:  # noqa: BLE001 - 板块表缺失不应阻断日报
        return {}
    out: dict[str, str] = {}
    for sec, syms in LDS_SECTORS.items():
        for s in syms:
            out.setdefault(str(s), sec)
    return out


def filter_market(rows: list[dict], market: str = "A") -> list[dict]:
    """按市场过滤 (主榜/板块代表榜只放 A 股, 港美股另列)。纯函数。"""
    return [r for r in rows if str(r.get("market")) == market]


def is_a_share(symbol: str) -> bool:
    s = str(symbol or "")
    return len(s) == 6 and s.isdigit()


def market_of(symbol: str) -> str:
    s = str(symbol or "")
    if is_a_share(s):
        return "A"
    if s.endswith(".HK"):
        return "HK"
    return "US"


def round_robin_universe(sections: dict[str, list[str]], core: list[str] | None = None,
                         limit: int = 80) -> list[str]:
    """按板块轮转构建扫描宇宙 — 保证每个板块都有名额, 不被"核心池前后顺序"饿死。

    旧实现直接切 ALL_CORE_STOCKS + 板块并集的前 N 只 → 排在后面的地产/汽车整块丢失。
    轮转: 每轮从每个板块各取 1 只, 直到填满 limit。纯函数。
    """
    pools: list[list[str]] = []
    for sec in sections:
        syms = [str(x) for x in sections[sec] if str(x).isdigit() and len(str(x)) == 6]
        if syms:
            pools.append(syms)

    out: list[str] = []
    seen: set[str] = set()
    # 核心池只占 1/8 (留 7/8 给板块轮转, 避免核心池的消费/金融挤掉小板块)
    if core:
        core_syms = [str(x) for x in core if str(x).isdigit() and len(str(x)) == 6]
        for x in core_syms[:max(0, limit // 8)]:
            if x not in seen:
                out.append(x); seen.add(x)
    idx = 0
    while len(out) < limit:
        added = False
        for pool in pools:
            if idx < len(pool):
                sym = pool[idx]
                if sym not in seen:
                    out.append(sym); seen.add(sym); added = True
                    if len(out) >= limit:
                        break
        idx += 1
        if not added:
            break
    return out


# ═══════════════════════════════════════════
# 载入 + 配额
# ═══════════════════════════════════════════
def load_v4_pool(path: str | None = None) -> list[dict]:
    """读取 v4 因子日扫结果 → 统一记录 (不含行情, 纯文件解析)。"""
    path = path or os.path.join(_PROJECT_DIR, "data", "factor_daily.json")
    if not os.path.exists(path):
        logger.warning("[daily_universe] %s 不存在", path)
        return []
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:  # noqa: BLE001 - 文件损坏时降级为空池
        logger.error("[daily_universe] 读取失败: %s", e)
        return []

    rows = payload.get("top_results") or payload.get("results") or []
    smap = _sector_map()
    try:  # 名称兜底: 静态表优先, 实时行情随后覆盖
        from data.stock_names import STOCK_NAMES as _NAMES
    except Exception:  # noqa: BLE001
        _NAMES = {}
    out: list[dict] = []
    for r in rows:
        sym = str(r.get("symbol") or "")
        if not sym:
            continue
        composite = r.get("composite")
        if composite is None:
            continue
        out.append({
            "symbol": sym,
            "name": _NAMES.get(sym, sym),
            "market": market_of(sym),
            "sector": smap.get(sym, "其他"),
            "composite": round(float(composite), 4),
            "score": round(float(composite) * SCORE_SCALE, 2),
            "scores": r.get("scores") or {},
            "date": payload.get("date"),
            "source": "factor_v4",
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


def sector_leaders(rows: list[dict], per_sector: int = 1) -> list[dict]:
    """每个板块取前 per_sector 名 → 板块代表榜 (按分数降序)。"""
    by_sector: dict[str, list[dict]] = {}
    for r in rows:
        by_sector.setdefault(str(r.get("sector") or "其他"), []).append(r)
    leaders: list[dict] = []
    for _sec, items in by_sector.items():
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
        leaders.extend(items[:per_sector])
    leaders.sort(key=lambda x: x.get("score", 0), reverse=True)
    return leaders


# ═══════════════════════════════════════════
# 行情补充 (批量腾讯 qt.gtimg: 一次请求多只, ~1s/50只)
# ═══════════════════════════════════════════
def parse_qt_response(text: str) -> dict[str, dict]:
    """解析腾讯 qt.gtimg 返回文本 → {symbol: {name, price, change_pct, pe}}。纯函数。"""
    out: dict[str, dict] = {}
    for line in (text or "").split(";"):
        if '="' not in line:
            continue
        try:
            fields = line.split('"')[1].split("~")
            if len(fields) < 40:
                continue
            sym = str(fields[2])
            price = float(fields[3]) if fields[3] else 0.0
            if price <= 0:
                continue
            out[sym] = {
                "name": str(fields[1]).replace(" ", ""),
                "price": price,
                "change_pct": round(float(fields[32]) if fields[32] else 0.0, 2),
                "pe": float(fields[39]) if len(fields) > 39 and fields[39] else None,
            }
        except Exception:  # noqa: BLE001 - 单行脏数据跳过
            continue
    return out


def batch_quotes(symbols: list[str], chunk: int = 50) -> dict[str, dict]:
    """A股批量实时行情。失败返回空 dict (不阻塞日报)。"""
    a_codes = [s for s in symbols if is_a_share(s)]
    if not a_codes:
        return {}
    try:
        import requests
    except Exception:  # noqa: BLE001
        return {}

    out: dict[str, dict] = {}
    for i in range(0, len(a_codes), chunk):
        part = a_codes[i:i + chunk]
        prefixed = [("sh" if c.startswith(("60", "68", "51", "58", "56")) else "sz") + c for c in part]
        try:
            r = requests.get("https://qt.gtimg.cn/q=" + ",".join(prefixed), timeout=8)
            r.encoding = "gbk"
            out.update(parse_qt_response(r.text))
        except Exception as e:  # noqa: BLE001 - 行情失败降级为裸代码
            logger.warning("[daily_universe] batch quote failed: %s", str(e)[:80])
    return out


def apply_quotes(rows: list[dict], quotes: dict[str, dict]) -> list[dict]:
    """把行情贴到记录上。补不到保留原值 (裸代码), 不写 None。纯函数。"""
    out: list[dict] = []
    for r in rows:
        rec = dict(r)
        q = quotes.get(rec["symbol"]) or {}
        if q.get("name"):
            rec["name"] = q["name"]
        if q.get("price") is not None:
            rec["price"] = q["price"]
        if q.get("change_pct") is not None:
            rec["change_pct"] = q["change_pct"]
        if q.get("pe") is not None:
            rec["pe"] = q["pe"]
            subs = rec.get("scores") if isinstance(rec.get("scores"), dict) else {}
            if subs.get("value") is not None:
                rec["pe_percentile"] = round(float(subs["value"]) * 100, 1)
        out.append(rec)
    return out


def build_daily_universe(quote_fn: Callable[[str], dict | None] | None = None,
                         path: str | None = None,
                         with_quotes: bool = True) -> tuple[list[dict], str]:
    """日报入口: v4 全池 (纯分数排序) + 批量行情补充。

    Args:
        quote_fn: 可选, 单只行情函数 (测试注入); 为 None 时走批量腾讯接口
        path: factor_daily.json 路径
        with_quotes: False 时不做行情 IO (单测/离线用)

    Returns:
        (records, status) — status "missing" 时调用方降级到 v3.1
    """
    rows = load_v4_pool(path)
    if not rows:
        return [], "missing"
    if not with_quotes:
        return rows, "complete"
    if quote_fn is not None:
        quotes = {}
        for r in rows:
            try:
                q = quote_fn(r["symbol"]) or {}
                if q:
                    quotes[r["symbol"]] = q
            except Exception:  # noqa: BLE001 - 单只失败忽略
                continue
        return apply_quotes(rows, quotes), "complete"
    return apply_quotes(rows, batch_quotes([r["symbol"] for r in rows])), "complete"
