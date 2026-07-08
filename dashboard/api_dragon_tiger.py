"""龙虎榜 API"""
from fastapi import APIRouter, Query
from dashboard.shared import ROOT, get_name, _guess_chain, _classify_market

router = APIRouter()


@router.get("/api/v2/dragon_tiger")
def api_v2_dragon_tiger(
    refresh: str = Query("false", description="是否强制刷新: true/false"),
):
    """
    龙虎榜面板 API — 返回 Top10净买入 + 游资动向 + 机构vs游资对比 + WATCHLIST高亮。

    Query params:
        refresh: 是否强制从AKShare拉取最新数据("true"即刷新)
    """
    from research.dragon_tiger import build_full_report, load_cached_report

    if refresh.lower() == "true":
        report = build_full_report()
    else:
        report = load_cached_report()
        if report.get("status") == "no_cache":
            report = build_full_report()

    # 富化: 加名称映射和产业链
    for item in report.get("top_stocks", []):
        item["display_name"] = get_name(item.get("symbol", ""))
        item["chain"] = _guess_chain(item.get("symbol", ""))

    for item in report.get("watchlist_overlap", []):
        item["display_name"] = get_name(item.get("symbol", ""))
        item["chain"] = _guess_chain(item.get("symbol", ""))

    # 添加上榜股票市场分类统计
    markets = {"a_share": 0, "hk": 0, "us": 0, "etf": 0}
    for rec in report.get("all_records", []):
        try:
            m = _classify_market(rec.get("symbol", ""))
            if m in markets:
                markets[m] += 1
        except Exception:
            pass
    report["market_stats"] = markets

    # 格式化金额字段
    for item in report.get("top_stocks", []):
        item["net_buy_fmt"] = _fmt_amount(item.get("net_buy", 0))
        item["buy_amount_fmt"] = _fmt_amount(item.get("buy_amount", 0))
        item["sell_amount_fmt"] = _fmt_amount(item.get("sell_amount", 0))
        item["total_amount_fmt"] = _fmt_amount(item.get("total_amount", 0))
        item["market_amount_fmt"] = _fmt_amount(item.get("market_amount", 0))
        item["institution_net_buy_fmt"] = _fmt_amount(item.get("institution_net_buy", 0))
        item["retail_net_buy_fmt"] = _fmt_amount(item.get("retail_net_buy", 0))

    for item in report.get("watchlist_overlap", []):
        item["net_buy_fmt"] = _fmt_amount(item.get("net_buy", 0))

    report["institution_vs_retail"]["net_buy_institution_fmt"] = _fmt_amount(
        report["institution_vs_retail"].get("net_buy_institution", 0))
    report["institution_vs_retail"]["net_buy_retail_fmt"] = _fmt_amount(
        report["institution_vs_retail"].get("net_buy_retail", 0))

    return report


def _fmt_amount(amount: float) -> str:
    """金额格式化: 亿/万 自适应"""
    if amount is None or amount == 0:
        return "0"
    abs_val = abs(amount)
    sign = "-" if amount < 0 else ""
    if abs_val >= 1e8:
        return f"{sign}{abs_val/1e8:.2f}亿"
    elif abs_val >= 1e4:
        return f"{sign}{abs_val/1e4:.0f}万"
    else:
        return f"{sign}{amount:.0f}"
