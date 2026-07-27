"""
IPO自动发现 v1 — 每日检测新上市公司并匹配投资主题
===================================================
双路径发现:
  路径A: baostock stock_basic 表 (IPO日期在窗口内, 有延迟)
  路径B: 实时数据 N前缀检测 (当日新股, 实时)

在 cron 中与 run_trading.py 联跑，发现新IPO后自动加入观察列表。
"""
import sys, os, json, time
from datetime import datetime, timedelta, date

_PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_DIR)

from utils.atomic_io import atomic_write_json
import functools
print = functools.partial(print, flush=True)

# 面基投资主题关键词 (与 config.CHAIN_ECONOMICS_WEIGHTS 对齐)
THEME_KEYWORDS = {
    "存储/HBM链":     ["存储", "DRAM", "NAND", "HBM", "内存", "闪存", "固态"],
    "半导体链":       ["半导体", "芯片", "晶圆", "IC设计", "封测", "EDA"],
    "英伟达算力链":    ["GPU", "算力", "光模块", "AI芯片", "HPC"],
    "台积电先进制程链": ["设备", "材料", "制程", "薄膜", "刻蚀", "CMP"],
    "物理AI链":       ["AI", "机器人", "视觉", "传感器", "智能"],
    "AI应用链":       ["AI应用", "大模型", "AIGC", "SaaS"],
    "新能源链":       ["新能源", "储能", "光伏", "锂电", "氢能"],
    "军工链":         ["军工", "航天", "航空", "雷达", "导弹"],
    "医药创新链":      ["医药", "生物", "创新药", "CXO", "医疗"],
    "机器人/自动化链": ["机器人", "自动化", "减速器", "伺服", "电机"],
    "金融链":         ["银行", "券商", "保险", "金融科技"],
    "消费链":         ["消费", "白酒", "食品", "家电", "汽车"],
}

SKIP_PREFIXES = ("sh.51", "sh.56", "sh.58", "sz.15", "sz.16", "sz.159")


def discover_new_listings(days_back=7) -> list[dict]:
    """路径A: 从 baostock 发现新上市公司"""
    import baostock as bs
    lg = bs.login()
    if lg.error_code != '0':
        print(f"  ❌ baostock login failed: {lg.error_msg}")
        return []

    cutoff = (date.today() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    new_stocks = []

    rs = bs.query_stock_basic()
    while rs.next():
        r = rs.get_row_data()
        code, name, ipo_date, status = r[0], r[1], r[2], r[3]
        if not code.startswith(("sh.6", "sz.0", "sz.3")):
            continue
        if code.startswith(SKIP_PREFIXES):
            continue
        if ipo_date and ipo_date >= cutoff:
            new_stocks.append({
                "code": code.replace("sh.", "").replace("sz.", ""),
                "name": name, "ipo_date": ipo_date, "status": status,
            })
    bs.logout()
    return new_stocks


def discover_n_prefix_stocks() -> list[dict]:
    """
    路径B: 从Tencent实时数据检测N前缀新股
    N前缀 = 当日/首日上市新股，baostock还没更新时也能发现
    """
    import urllib.request, json as _json
    new_stocks = []
    
    # 检查所有可能的N前缀股票 (使用科创板+创业板热门板块)
    # 实际生产: 从全市场扫描
    stocks_to_check = []
    
    # 从已知WATCHLIST和新股覆盖区扫描
    known_codes = []
    for prefix in [str(i) for i in range(688780, 688830)]:
        known_codes.append(prefix)
    # 再加创业板
    for prefix in [str(i) for i in range(301580, 301700)]:
        known_codes.append(prefix)
    # 主板新代码
    for prefix in ["001" + str(i).zfill(3) for i in range(200, 260)]:
        known_codes.append(prefix)
    
    # Tencent批量查询
    batch_size = 50
    for i in range(0, len(known_codes), batch_size):
        batch = known_codes[i:i+batch_size]
        market_codes = []
        for c in batch:
            if c.startswith("6"):
                market_codes.append(f"sh{c}")
            else:
                market_codes.append(f"sz{c}")
        
        url = "http://qt.gtimg.cn/q=" + ",".join(market_codes)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            resp = urllib.request.urlopen(req, timeout=5).read().decode("gbk")
            for line in resp.split(";"):
                if not line.strip() or "=" not in line:
                    continue
                data = line.split("=")[-1].strip()
                if data.startswith('"') and data.endswith('"'):
                    data = data[1:-1]
                parts = data.split("~")
                if len(parts) > 3:
                    name = parts[1]
                    code = parts[2]
                    price = parts[3]
                    # N前缀检测
                    if name.startswith("N") or name.startswith("N "):
                        # 检查是否已在WATCHLIST
                        new_stocks.append({
                            "code": code,
                            "name": name,
                            "price": float(price) if price.replace(".", "").isdigit() else 0,
                            "source": "n_prefix",
                        })
        except Exception as e:
            print(f"  ⚠️ Tencent batch error: {e}")
        time.sleep(1.5)
    
    return new_stocks


def match_theme(stock_name: str) -> list[tuple[str, str]]:
    """匹配主题"""
    matches = []
    for chain, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            if kw in stock_name:
                matches.append((chain, kw))
    return matches


def check_data_availability(symbol: str) -> dict:
    """检查数据源是否有该标的的实时数据"""
    try:
        from data.data_router import get_rt
        rt = get_rt(symbol)
        if rt and rt.get("price", 0) > 0:
            return {
                "available": True,
                "price": rt.get("price", 0),
                "pe": rt.get("pe"),
                "change_pct": rt.get("change_pct", 0),
                "name": rt.get("name", ""),
                "source": rt.get("source", "unknown"),
            }
    except Exception:
        pass
    return {"available": False}


def run():
    print("=" * 50)
    print("🔍 IPO自动发现 v1")
    print(f"   日期: {date.today()}")
    print("=" * 50)

    try:
        from config import WATCHLIST
        known = set(WATCHLIST.keys())
    except ImportError:
        known = set()

    all_new = []

    # 路径A: baostock
    print("\n📋 路径A: baostock 新股扫描...")
    new_a = discover_new_listings(days_back=30)
    for s in new_a:
        if s["code"] not in known:
            all_new.append(s)
    print(f"   发现 {len(all_new)} 只新标的 (已过滤已在WATCHLIST的)")

    # 路径B: N前缀检测 (实时)
    print("\n📋 路径B: N前缀新股检测...")
    new_b = discover_n_prefix_stocks()
    for s in new_b:
        if s["code"] not in known and s["code"] not in {x["code"] for x in all_new}:
            all_new.append(s)
    print(f"   N前缀发现 {len(new_b)} 只")

    if not all_new:
        print("   今日无新IPO")
        return {"new_found": 0, "new_matched": 0, "discoveries": []}

    # 主题匹配
    print(f"\n🎯 主题匹配...")
    discoveries = []
    for s in all_new:
        data = s if s.get("price") else check_data_availability(s["code"])
        matches = match_theme(s.get("name", data.get("name", "")))
        if matches:
            chain, kw = matches[0]
            rec = {
                "symbol": s["code"],
                "name": s.get("name", data.get("name", "")),
                "chain": chain,
                "matched_keyword": kw,
                "price": data.get("price", 0),
                "pe": data.get("pe"),
                "change_pct": data.get("change_pct", 0),
                "data_available": data.get("available", True),
            }
            discoveries.append(rec)
            print(f"   ✅ {s['code']} {rec['name']} → {chain} (匹配: {kw})")
        else:
            print(f"   ⏭️  {s['code']} {s.get('name', '?')} — 无主题匹配")

    if not discoveries:
        print("   无匹配主题的新IPO")
        return {"new_found": len(all_new), "new_matched": 0, "discoveries": []}

    # 保存
    print(f"\n💾 保存发现报告...")
    report_path = os.path.join(_PROJECT_DIR, "data", "ipo_discoveries.json")
    existing = []
    if os.path.exists(report_path):
        with open(report_path) as f:
            existing = json.load(f)

    # 去重
    existing_symbols = {d["symbol"] for d in existing}
    for d in discoveries:
        if d["symbol"] not in existing_symbols:
            existing.insert(0, d)

    atomic_write_json(report_path, existing)
    print(f"   ✅ 保存 {len(discoveries)} 条发现")

    print(f"\n📊 发现摘要:")
    print(f"   新发现: {len(all_new)} 只")
    print(f"   主题匹配: {len(discoveries)} 只")
    for d in discoveries:
        print(f"   [{d['chain']}] {d['symbol']} {d['name']} @{d['price']}")
    print(f"\n💡 提示: 运行 'python3 scripts/add_ipo_to_watchlist.py' 将发现加入WATCHLIST")

    return {
        "new_found": len(all_new),
        "new_matched": len(discoveries),
        "discoveries": discoveries,
    }


# ── 蜻蜓CSC IPO增强 ─────────────────────────────

def enrich_ipo_batch(ipo_list: list[dict]) -> list[dict]:
    """用蜻蜓CSC丰富IPO信息: 行业/PE排名/ROE排名"""
    try:
        from data.sources.qingting_source import QTSource
        qt = QTSource()
        if not qt.api_key:
            return ipo_list
    except Exception:
        return ipo_list
    for ipo in ipo_list:
        code = ipo.get("code", "")
        if not code or code.endswith(".HK"):
            continue
        clean = code.replace(".SH", "").replace(".SZ", "").zfill(6)
        try:
            prof = qt.get_company_profile(clean)
            if prof:
                ipo["industry"] = prof.get("industryName", "")
        except Exception:
            pass
        try:
            rank = qt.get_industry_rank(clean, metric="pe")
            if rank:
                ipo["pe_rank"] = rank.get("industryRank", "")
                ipo["pe_avg"] = rank.get("industryAvg")
        except Exception:
            pass
        try:
            rank_roe = qt.get_industry_rank(clean, metric="jzcsyl")
            if rank_roe:
                ipo["roe_rank"] = rank_roe.get("industryRank", "")
        except Exception:
            pass
    return ipo_list


if __name__ == "__main__":
    result = run()
    # 增强IPO信息
    if result and result.get("discoveries"):
        enriched = enrich_ipo_batch(result["discoveries"])
        for d in enriched[:5]:
            print(f"  [增强] {d.get('code','')} {d.get('name','')} "
                  f"行业={d.get('industry','?')} PE排名={d.get('pe_rank','?')}")
