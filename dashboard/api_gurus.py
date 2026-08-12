"""大师(13F)持仓 API"""
import json

from fastapi import APIRouter
from dashboard.shared import ROOT

router = APIRouter()


def _load_guru_holdings():
    """读取 guru_holdings.json，文件不存在/解析失败时返回空结构。"""
    path = ROOT / "data" / "guru_holdings.json"
    if not path.exists():
        return {"as_of_date": "", "updated_at": "", "guru_count": 0, "gurus": []}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"as_of_date": "", "updated_at": "", "guru_count": 0, "gurus": []}


def _fmt_usd(value) -> str:
    """美元金额格式化: 万亿/亿 自适应。"""
    if value is None or value == 0:
        return "0"
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "0"
    abs_val = abs(value)
    sign = "-" if value < 0 else ""
    if abs_val >= 1e12:
        return f"{sign}{abs_val/1e12:.2f}万亿"
    elif abs_val >= 1e8:
        return f"{sign}{abs_val/1e8:.2f}亿"
    elif abs_val >= 1e4:
        return f"{sign}{abs_val/1e4:.0f}万"
    else:
        return f"{sign}{value:.0f}"


@router.get("/api/v2/gurus")
def api_v2_gurus():
    """返回全大师列表 + 每大师持仓数 + 总市值(亿美元 与 格式化)。"""
    data = _load_guru_holdings()
    gurus = []
    for g in data.get("gurus", []):
        holdings = g.get("holdings", []) or []
        # 过滤掉缺市值/缺名称的占位条目(仅 13F 有效持仓才有 sec_source/value_usd)
        valid = [h for h in holdings if h.get("value_usd") is not None]
        total_usd = sum(
            h.get("value_usd") or 0
            for h in holdings
            if isinstance(h.get("value_usd"), (int, float))
        )
        gurus.append({
            "name": g.get("name", ""),
            "en_name": g.get("en_name", ""),
            "slug": g.get("slug", ""),
            "firm": g.get("firm", ""),
            "cik": g.get("cik", ""),
            "sec_period": g.get("sec_period", ""),
            "holdings_count": len(holdings),
            "valid_count": len(valid),
            "total_usd": round(total_usd, 2),
            "total_usd_fmt": _fmt_usd(total_usd),
        })
    return {
        "as_of_date": data.get("as_of_date", ""),
        "updated_at": data.get("updated_at", ""),
        "guru_count": len(gurus),
        "gurus": sorted(gurus, key=lambda x: -x["total_usd"]),
    }


@router.get("/api/v2/gurus/{slug}")
def api_v2_guru_detail(slug: str):
    """返回单大师详情，持仓按 value_usd 降序，附 chg_pct / weight_pct。"""
    data = _load_guru_holdings()
    target = None
    for g in data.get("gurus", []):
        if g.get("slug") == slug:
            target = g
            break
    if target is None:
        return {"found": False, "slug": slug}
    holdings = [
        {
            "ticker": h.get("ticker", ""),
            "name": h.get("name", ""),
            "shares": h.get("shares"),
            "value_usd": h.get("value_usd"),
            "value_usd_fmt": _fmt_usd(h.get("value_usd")),
            "chg_pct": h.get("chg_pct"),
            "weight_pct": h.get("weight_pct"),
            "sector": h.get("sector", ""),
            "security_type": h.get("security_type"),
        }
        for h in (target.get("holdings", []) or [])
        # value_usd 为空的占位行排在最后
    ]
    holdings.sort(key=lambda x: -(x["value_usd"] or 0))
    total_usd = sum(h["value_usd"] or 0 for h in holdings if h["value_usd"])
    return {
        "found": True,
        "name": target.get("name", ""),
        "en_name": target.get("en_name", ""),
        "slug": target.get("slug", ""),
        "firm": target.get("firm", ""),
        "cik": target.get("cik", ""),
        "sec_period": target.get("sec_period", ""),
        "as_of_date": data.get("as_of_date", ""),
        "holdings_count": len(holdings),
        "total_usd": round(total_usd, 2),
        "total_usd_fmt": _fmt_usd(total_usd),
        "holdings": holdings,
    }
