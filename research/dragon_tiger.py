"""
龙虎榜数据分析引擎 v1.0
================================
每日龙虎榜数据采集、游资追踪、机构/游资对比、WATCHLIST交叉标注。

数据源: AKShare(东方财富龙虎榜单)
缓存: data/dragon_tiger.json
"""

import json
import os
import sys
import warnings
from datetime import datetime, timedelta
from typing import Optional

# Path setup
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

# Suppress akshare/urllib3 warnings
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*OpenSSL.*")

# ── 知名游资席位识别表 ──
FAMOUS_SEATS = {
    "章盟主":     ["国泰君安证券股份有限公司上海江苏路证券营业部",
                   "国元证券股份有限公司上海虹桥路证券营业部"],
    "赵老哥":     ["中国银河证券股份有限公司绍兴证券营业部",
                   "浙商证券股份有限公司绍兴解放北路证券营业部"],
    "方新侠":     ["中信证券股份有限公司西安朱雀大街证券营业部",
                   "兴业证券股份有限公司陕西分公司"],
    "炒股养家":   ["华鑫证券有限责任公司上海宛平南路证券营业部",
                   "华鑫证券有限责任公司上海茅台路证券营业部",
                   "华鑫证券有限责任公司上海淞滨路证券营业部"],
    "小鳄鱼":     ["南京证券股份有限公司南京大钟亭证券营业部",
                   "中国中金财富证券有限公司南京太平南路证券营业部"],
    "孙哥":       ["中信证券股份有限公司上海溧阳路证券营业部",
                   "中信证券股份有限公司上海古北路证券营业部"],
    "作手新一":   ["国泰君安证券股份有限公司南京太平南路证券营业部"],
    "上塘路":     ["财通证券股份有限公司杭州上塘路证券营业部"],
    "佛山系":     ["光大证券股份有限公司佛山绿景路证券营业部",
                   "长江证券股份有限公司佛山南海大道证券营业部"],
    "宁波桑田路": ["国盛证券有限责任公司宁波桑田路证券营业部"],
    "溧阳路":     ["中信证券股份有限公司上海溧阳路证券营业部"],
    "荣超":       ["华泰证券股份有限公司深圳益田路荣超商务中心证券营业部"],
    "欢乐海岸":   ["中泰证券股份有限公司深圳欢乐海岸证券营业部",
                   "华泰证券股份有限公司深圳海德三道证券营业部"],
    "成都系":     ["国泰君安证券股份有限公司成都北一环路证券营业部",
                   "华泰证券股份有限公司成都蜀金路证券营业部"],
    "湖州劳动路": ["华鑫证券有限责任公司深圳分公司"],
}

# ── 机构席位关键词 ──
_INSTITUTION_KEYWORDS = ["机构专用", "沪股通专用", "深股通专用", "中国国际金融", "中信证券股份有限公司总部"]


def _parse_amount(val) -> float:
    """安全解析金额，容错处理NaN/None/字符串"""
    try:
        v = float(val)
        if pd_val := float(val):
            if pd_val != pd_val:  # NaN check
                return 0.0
        return float(val) if val and val == val else 0.0
    except (ValueError, TypeError):
        return 0.0


def _detect_institution(seat_name: str) -> bool:
    """判断席位是否为机构"""
    if not seat_name:
        return False
    for kw in _INSTITUTION_KEYWORDS:
        if kw in str(seat_name):
            return True
    return False


def _detect_famous(seat_name: str) -> Optional[str]:
    """检测席位是否为知名游资, 返回游资名称或None"""
    if not seat_name:
        return None
    name = str(seat_name)
    for celebrity, seats in FAMOUS_SEATS.items():
        for s in seats:
            if s in name:
                return celebrity
    return None


def fetch_daily_dragon_tiger(date: Optional[str] = None) -> list[dict]:
    """
    获取单日(或最近一日)龙虎榜数据, 含席位明细。

    Args:
        date: 日期字符串 'YYYYMMDD', 不传则取最近交易日

    Returns:
        [{symbol, name, close, change_pct, net_buy, buy_amount, sell_amount,
          total_amount, market_amount, turnover, float_mv, reason, jiedu,
          buy_seats: [{name, amount, pct, is_institution, is_famous}],
          sell_seats: [{name, amount, pct, is_institution, is_famous}],
          institution_net_buy, retail_net_buy}, ...]
    """
    import akshare as ak

    if date is None:
        # 往前回溯最多5天找有数据的交易日
        for i in range(5):
            d = (datetime.now() - timedelta(days=i + 1)).strftime("%Y%m%d")
            try:
                df = ak.stock_lhb_detail_em(start_date=d, end_date=d)
                if len(df) > 0:
                    date = d
                    break
            except Exception:
                continue
        if date is None:
            date = datetime.now().strftime("%Y%m%d")

    # Fetch summary data
    df = ak.stock_lhb_detail_em(start_date=date, end_date=date)

    if df.empty:
        return []

    # Build base records
    records = []
    for _, row in df.iterrows():
        code = str(row.get("代码", "")).zfill(6)
        rec = {
            "symbol": code,
            "name": str(row.get("名称", "")),
            "date": str(row.get("上榜日", date)),
            "close": _parse_amount(row.get("收盘价")),
            "change_pct": _parse_amount(row.get("涨跌幅")),
            "net_buy": _parse_amount(row.get("龙虎榜净买额")),
            "buy_amount": _parse_amount(row.get("龙虎榜买入额")),
            "sell_amount": _parse_amount(row.get("龙虎榜卖出额")),
            "total_amount": _parse_amount(row.get("龙虎榜成交额")),
            "market_amount": _parse_amount(row.get("市场总成交额")),
            "net_buy_pct": _parse_amount(row.get("净买额占总成交比")),
            "total_pct": _parse_amount(row.get("成交额占总成交比")),
            "turnover": _parse_amount(row.get("换手率")),
            "float_mv": _parse_amount(row.get("流通市值")),
            "reason": str(row.get("上榜原因", "")),
            "jiedu": str(row.get("解读", "")),
            "post_1d": _parse_amount(row.get("上榜后1日")),
            "post_2d": _parse_amount(row.get("上榜后2日")),
            "post_5d": _parse_amount(row.get("上榜后5日")),
            "post_10d": _parse_amount(row.get("上榜后10日")),
            "buy_seats": [],
            "sell_seats": [],
            "institution_net_buy": 0.0,
            "retail_net_buy": 0.0,
            "famous_seats_buy": [],
            "famous_seats_sell": [],
        }
        records.append(rec)

    # Fetch seat-level detail for each stock
    _enrich_seat_details(records)

    # Calculate institution vs retail net buy
    for rec in records:
        inst_buy = sum(s.get("amount", 0) for s in rec["buy_seats"] if s.get("is_institution"))
        inst_sell = sum(s.get("amount", 0) for s in rec["sell_seats"] if s.get("is_institution"))
        rec["institution_net_buy"] = inst_buy - inst_sell
        rec["retail_net_buy"] = rec["net_buy"] - rec["institution_net_buy"]

    return records


def _enrich_seat_details(records: list[dict]):
    """为每条记录补充买卖席位明细 — 并发+超时, 避免逐股串行3分钟挂死"""
    import akshare as ak
    from concurrent.futures import ThreadPoolExecutor, as_completed

    def _enrich_one(rec: dict):
        code = rec["symbol"]
        date_str = str(rec["date"]).replace("-", "")
        try:
            # 获取该股票的龙虎榜日期列表
            dates_df = ak.stock_lhb_stock_detail_date_em(symbol=code)
            if dates_df is None or dates_df.empty:
                return

            target_date = None
            for _, dr in dates_df.iterrows():
                dt_val = dr.get("交易日")
                if dt_val is not None:
                    if isinstance(dt_val, str):
                        dt_fmt = dt_val.replace("-", "")
                    else:
                        dt_fmt = dt_val.strftime("%Y%m%d")
                    if dt_fmt == date_str:
                        target_date = dt_val
                        break

            if target_date is None:
                return

            if isinstance(target_date, str):
                api_date = target_date.replace("-", "")
            else:
                api_date = target_date.strftime("%Y%m%d")

            for flag, buy_key, pct_key, rec_key, famous_key in [
                ("买入", "买入金额", "买入金额-占总成交比例", "buy_seats", "famous_seats_buy"),
                ("卖出", "卖出金额", "卖出金额-占总成交比例", "sell_seats", "famous_seats_sell"),
            ]:
                try:
                    df = ak.stock_lhb_stock_detail_em(symbol=code, date=api_date, flag=flag)
                    if df is not None and not df.empty:
                        for _, sr in df.iterrows():
                            seat_name = str(sr.get("交易营业部名称", ""))
                            seat = {
                                "name": seat_name,
                                "amount": _parse_amount(sr.get(buy_key, 0)),
                                "pct": _parse_amount(sr.get(pct_key, 0)),
                                "is_institution": _detect_institution(seat_name),
                                "is_famous": _detect_famous(seat_name),
                                "celebrity": _detect_famous(seat_name),
                            }
                            rec[rec_key].append(seat)
                            if seat["is_famous"]:
                                rec[famous_key].append(seat)
                except Exception:
                    continue
        except Exception:
            return

    # 并发执行席位明细抓取 (限10并发防封, 每只独立超时)
    active = [rec for rec in records if rec.get("symbol")]
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_enrich_one, rec): rec for rec in active}
        for fut in as_completed(futs, timeout=45):
            try:
                fut.result()
            except Exception:
                continue


def analyze_top_stocks(records: list[dict], limit: int = 10) -> list[dict]:
    """
    按净买入额排名, 返回 Top N 标的。

    Returns:
        按净买额降序排列, 每条包含完整信息+排名
    """
    sorted_recs = sorted(records, key=lambda r: r.get("net_buy", 0), reverse=True)
    result = []
    for i, rec in enumerate(sorted_recs[:limit], 1):
        item = dict(rec)
        item["rank"] = i
        result.append(item)
    return result


def track_famous_seats(records: list[dict]) -> dict:
    """
    追踪今日活跃的知名游资。

    Returns:
        {
            active_celebrities: [
                {name: str, buy_count: int, sell_count: int, total_buy: float,
                 total_sell: float, stocks_bought: [...], stocks_sold: [...]}
            ],
            total_famous_buy: float,
            total_famous_sell: float,
        }
    """
    celeb_map: dict[str, dict] = {}

    for rec in records:
        for seat in rec.get("famous_seats_buy", []):
            celeb = seat.get("celebrity")
            if not celeb:
                continue
            if celeb not in celeb_map:
                celeb_map[celeb] = {
                    "name": celeb,
                    "buy_count": 0,
                    "sell_count": 0,
                    "total_buy": 0.0,
                    "total_sell": 0.0,
                    "stocks_bought": [],
                    "stocks_sold": [],
                }
            celeb_map[celeb]["buy_count"] += 1
            celeb_map[celeb]["total_buy"] += seat.get("amount", 0)
            stock_key = f"{rec['symbol']}({rec['name']})"
            if stock_key not in celeb_map[celeb]["stocks_bought"]:
                celeb_map[celeb]["stocks_bought"].append(stock_key)

        for seat in rec.get("famous_seats_sell", []):
            celeb = seat.get("celebrity")
            if not celeb:
                continue
            if celeb not in celeb_map:
                celeb_map[celeb] = {
                    "name": celeb,
                    "buy_count": 0,
                    "sell_count": 0,
                    "total_buy": 0.0,
                    "total_sell": 0.0,
                    "stocks_bought": [],
                    "stocks_sold": [],
                }
            celeb_map[celeb]["sell_count"] += 1
            celeb_map[celeb]["total_sell"] += seat.get("amount", 0)
            stock_key = f"{rec['symbol']}({rec['name']})"
            if stock_key not in celeb_map[celeb]["stocks_sold"]:
                celeb_map[celeb]["stocks_sold"].append(stock_key)

    active = sorted(celeb_map.values(), key=lambda x: x["total_buy"] + x["total_sell"], reverse=True)
    total_buy = sum(c["total_buy"] for c in active)
    total_sell = sum(c["total_sell"] for c in active)

    return {
        "active_celebrities": active,
        "total_famous_buy": total_buy,
        "total_famous_sell": total_sell,
    }


def compute_institution_vs_retail(records: list[dict]) -> dict:
    """
    汇总全市场机构 vs 游资/散户净买入。

    Returns:
        {net_buy_institution, net_buy_retail, total_stocks, inst_stock_count}
    """
    total_inst = 0.0
    total_retail = 0.0
    inst_stocks = 0

    for rec in records:
        total_inst += rec.get("institution_net_buy", 0)
        total_retail += rec.get("retail_net_buy", 0)
        if rec.get("institution_net_buy", 0) != 0:
            inst_stocks += 1

    return {
        "net_buy_institution": round(total_inst, 2),
        "net_buy_retail": round(total_retail, 2),
        "total_stocks": len(records),
        "inst_stock_count": inst_stocks,
    }


def find_watchlist_overlap(records: list[dict]) -> list[dict]:
    """
    检查龙虎榜上榜股票与 WATCHLIST 的交集。

    Returns:
        [{symbol, name, net_buy, in_watchlist: True, watch_info: {...}}, ...]
    """
    try:
        from config import WATCHLIST
    except ImportError:
        WATCHLIST = {}

    overlap = []
    for rec in records:
        sym = rec["symbol"]
        if sym in WATCHLIST:
            entry = {
                "symbol": sym,
                "name": rec["name"],
                "net_buy": rec["net_buy"],
                "change_pct": rec["change_pct"],
                "reason": rec["reason"],
                "jiedu": rec["jiedu"],
                "in_watchlist": True,
                "watch_info": WATCHLIST[sym] if isinstance(WATCHLIST[sym], dict) else {},
            }
            overlap.append(entry)

    return sorted(overlap, key=lambda x: x["net_buy"], reverse=True)


def build_full_report(date: Optional[str] = None) -> dict:
    """
    构建完整龙虎榜报告: 融合所有分析维度。

    Returns:
        {date, top_stocks, famous_seats, institution_vs_retail, watchlist_overlap,
         all_records, total_records, cache_timestamp}
    """
    records = fetch_daily_dragon_tiger(date=date)

    if not records:
        return {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "top_stocks": [],
            "famous_seats": {"active_celebrities": [], "total_famous_buy": 0, "total_famous_sell": 0},
            "institution_vs_retail": {"net_buy_institution": 0, "net_buy_retail": 0, "total_stocks": 0, "inst_stock_count": 0},
            "watchlist_overlap": [],
            "all_records": [],
            "total_records": 0,
            "cache_timestamp": datetime.now().isoformat(),
            "status": "empty",
        }

    top = analyze_top_stocks(records, limit=10)
    famous = track_famous_seats(records)
    inst_vs_retail = compute_institution_vs_retail(records)
    overlap = find_watchlist_overlap(records)

    # 对于 top_stocks, 精简席位信息供前端展示
    for item in top:
        item["buy_seats_summary"] = _summarize_seats(item.get("buy_seats", [])[:5])
        item["sell_seats_summary"] = _summarize_seats(item.get("sell_seats", [])[:5])

    report = {
        "date": records[0]["date"] if records else (date or ""),
        "top_stocks": top,
        "famous_seats": famous,
        "institution_vs_retail": inst_vs_retail,
        "watchlist_overlap": overlap,
        "all_records": records,
        "total_records": len(records),
        "cache_timestamp": datetime.now().isoformat(),
        "status": "ok",
    }

    # 缓存到磁盘
    cache_path = os.path.join(_PROJECT_DIR, "data", "dragon_tiger.json")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)

    return report


def load_cached_report() -> dict:
    """读取磁盘缓存的龙虎榜报告"""
    cache_path = os.path.join(_PROJECT_DIR, "data", "dragon_tiger.json")
    if not os.path.exists(cache_path):
        return {"status": "no_cache", "top_stocks": [], "total_records": 0}
    with open(cache_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _summarize_seats(seats: list[dict]) -> list[dict]:
    """精简席位信息供前端展示"""
    return [
        {
            "name": s.get("name", ""),
            "amount": s.get("amount", 0),
            "is_institution": s.get("is_institution", False),
            "is_famous": s.get("is_famous", False),
            "celebrity": s.get("celebrity"),
        }
        for s in seats
    ]


# ── CLI ──
if __name__ == "__main__":
    print("🐉 龙虎榜数据引擎 v1.0")
    print("=" * 60)
    report = build_full_report()
    print(f"日期: {report['date']}")
    print(f"上榜总数: {report['total_records']}")
    print(f"Top10 净买入:")
    for s in report["top_stocks"]:
        net_buy_str = f"{s['net_buy']/1e8:.2f}亿" if abs(s['net_buy']) >= 1e8 else f"{s['net_buy']/1e4:.0f}万"
        print(f"  {s['rank']:2d}. {s['symbol']} {s['name']:<6s} 净买{net_buy_str}  {s['reason'][:20]}")
    print(f"\n活跃游资: {len(report['famous_seats']['active_celebrities'])}位")
    for c in report["famous_seats"]["active_celebrities"]:
        print(f"  {c['name']}: 买{c['buy_count']}只 卖{c['sell_count']}只 净买{(c['total_buy']-c['total_sell'])/1e4:.0f}万")
    print(f"\n机构净买: {report['institution_vs_retail']['net_buy_institution']/1e8:.2f}亿")
    print(f"游资/散户净买: {report['institution_vs_retail']['net_buy_retail']/1e8:.2f}亿")
    print(f"WATCHLIST交集: {len(report['watchlist_overlap'])}只")
