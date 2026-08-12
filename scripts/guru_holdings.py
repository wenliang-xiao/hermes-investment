#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
guru_holdings.py — 大师(顶级投资者)13F持仓数据爬虫  (仅美股, 不含 HKEx)

数据源优先级:
  1) aiyuan.ai/gurus             -> 21位顶级投资者持仓列表(股票/名称/市值-股数/季度变动)
  2) SEC EDGAR 官方API(data.sec.gov) -> 13F 持仓验证/补充(免费无 key)

输出: data/guru_holdings.json
  结构: {"as_of_date": "...", "source": ..., "gurus": [
           {"name": "...", "firm": "...", "cik": "...", "sec_period": "...",
            "holdings": [{"ticker":..,"name":..,"shares":..,"value_usd":..,"chg_pct":..,...}]}]}

用法:
  python guru_holdings.py --fetch                 # 全量抓取 + SEC 验证
  python guru_holdings.py --fetch --skip-sec      # 仅 aiyuan 抓取, 跳过 SEC
  python guru_holdings.py --fetch --guru warren-buffett   # 仅指定大师
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------
BASE_URL = "https://aiyuan.ai"
GURUS_URL = f"{BASE_URL}/gurus"
SEC_UA = "HermesInvestSys research contact=admin@example.com"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0 Safari/537.36"
RATE_LIMIT_S = 0.5          # 每次请求最小间隔
HTTP_TIMEOUT = 30

# 脚本目录
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
OUTPUT_PATH = PROJECT_ROOT / "data" / "guru_holdings.json"
TICKER_MAP_PATH = PROJECT_ROOT / "data" / "us_ticker_map.json"

log = logging.getLogger("guru_holdings")

# 懒加载缓存: ticker -> issuer 名映射 (见 scripts/build_us_ticker_map.py)
_US_TICKER_MAP: Optional[Dict[str, Dict[str, str]]] = None
_REVERSE_NORM: Optional[Dict[str, str]] = None


def _load_ticker_map() -> Dict[str, Dict[str, str]]:
    global _US_TICKER_MAP
    if _US_TICKER_MAP is None:
        if TICKER_MAP_PATH.exists():
            try:
                _US_TICKER_MAP = json.loads(TICKER_MAP_PATH.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("加载 ticker 映射失败 %s: %s, 忽略", TICKER_MAP_PATH, exc)
                _US_TICKER_MAP = {}
        else:
            log.warning("未找到 %s, 无法用 ticker 反查发行方名称 (请先运行 build_us_ticker_map.py)",
                        TICKER_MAP_PATH)
            _US_TICKER_MAP = {}
    return _US_TICKER_MAP


def _reverse_norm_map() -> Dict[str, str]:
    """规范化 issuer 名 -> ticker 的反查表 (供 SEC issuer -> ticker 匹配)。"""
    global _REVERSE_NORM
    if _REVERSE_NORM is None:
        rev: Dict[str, str] = {}
        for tk, info in _load_ticker_map().items():
            norm = info.get("norm") or _norm_issuer(info.get("name", ""))
            if norm:
                rev.setdefault(norm, tk)
        _REVERSE_NORM = rev
    return _REVERSE_NORM

# ---------------------------------------------------------------------------
# 大师 -> SEC CIK 映射 (经 data.sec.gov 全文本检索验证)
# slug 以 aiyuan.ai/gurus 链接为准
# ---------------------------------------------------------------------------
GURU_CIKS: Dict[str, str] = {
    "warren-buffett": "1067983",          # Berkshire Hathaway Inc
    "jim-simons": "1037389",              # Renaissance Technologies LLC
    "steve-cohen": "1603466",             # Point72 Asset Management L.P.
    "ken-griffin": "1423053",             # Citadel Advisors LLC
    "chase-coleman": "1167483",           # Tiger Global Management LLC
    "ray-dalio": "1350694",               # Bridgewater Associates LP
    "howard-marks": "949509",             # Oaktree Capital Management LP
    "bill-ackman": "1336528",             # Pershing Square Capital Management L.P.
    "cathie-wood": "1697748",             # ARK Investment Management LLC
    "carl-icahn": "1412093",              # Icahn Capital LP
    "george-soros": "1029160",            # Soros Fund Management LLC
    "david-tepper": "1006438",            # Appaloosa Management LP
    "seth-klarman": "1061768",            # Baupost Group LLC/MA
    "nelson-peltz": "1345471",            # Trian Fund Management L.P.
    "li-lu": "1709323",                   # Himalaya Capital Management LLC
    "stanley-druckenmiller": "1536411",   # Duquesne Family Office LLC
    "dan-loeb": "1040273",                # Third Point LLC
    "david-einhorn": "1040272",           # Greenlight Capital LLC (已停报13F)
    "mohnish-pabrai": "1173334",          # Pabrai Mohnish (个人, 2011年后未报)
    "terry-smith": "1569205",             # Fundsmith LLP
    "michael-burry": "1649339",           # Scion Asset Management, LLC
}

# SEC CIK 发现后查找历史信息的补充搜索词(主映射缺失时用于 efts 检索纠偏)
GURU_FIRM_SEARCH: Dict[str, str] = {
    "warren-buffett": "Berkshire Hathaway Inc",
    "jim-simons": "Renaissance Technologies",
    "steve-cohen": "Point72 Asset Management",
    "ken-griffin": "Citadel Advisors LLC",
    "chase-coleman": "Tiger Global Management",
    "ray-dalio": "Bridgewater Associates",
    "howard-marks": "Oaktree Capital Management",
    "bill-ackman": "Pershing Square Capital Management",
    "cathie-wood": "ARK Investment Management LLC",
    "carl-icahn": "Icahn Capital",
    "george-soros": "Soros Fund Management LLC",
    "david-tepper": "Appaloosa Management",
    "seth-klarman": "Baupost Group",
    "nelson-peltz": "Trian Fund Management",
    "li-lu": "Himalaya Capital Management LLC",
    "stanley-druckenmiller": "Duquesne Family Office",
    "dan-loeb": "Third Point LLC",
    "david-einhorn": "Greenlight Capital LLC",
    "mohnish-pabrai": "Pabrai Investment Funds",
    "terry-smith": "Fundsmith LLP",
    "michael-burry": "Scion Asset Management LLC",
}


@dataclass
class GuruMeta:
    slug: str
    cn_name: str
    en_name: str


@dataclass
class Holding:
    ticker: str
    name: str
    shares: Optional[float] = None
    value_usd: Optional[float] = None
    chg_pct: Optional[float] = None
    weight_pct: Optional[float] = None
    sector: Optional[str] = None
    security_type: Optional[str] = None
    sec_source: bool = False


# ---------------------------------------------------------------------------
# 网络层 (限频 + UA + 重试)
# ---------------------------------------------------------------------------
class _RateLimiter:
    def __init__(self, min_interval: float = RATE_LIMIT_S) -> None:
        self._min_interval = min_interval
        self._last = 0.0

    def wait(self) -> None:
        now = time.time()
        delta = now - self._last
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last = time.time()


_limiter = _RateLimiter()


def http_get(url: str, *, headers: Optional[Dict[str, str]] = None,
             timeout: int = HTTP_TIMEOUT, retries: int = 3,
             as_json: bool = False) -> Any:
    """带 UA / 限频 / 重试的 GET 请求。"""
    if headers is None:
        headers = {"User-Agent": USER_AGENT}
    for attempt in range(1, retries + 1):
        _limiter.wait()
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                log.warning("HTTP %s 于 %s (第 %d 次)", resp.status_code, url, attempt)
                time.sleep(1.0 * attempt)
                continue
            resp.raise_for_status()
            return resp.json() if as_json else resp.text
        except requests.exceptions.RequestException as exc:
            log.warning("请求失败 %s: %s (第 %d 次)", url, exc, attempt)
            time.sleep(1.0 * attempt)
    raise RuntimeError(f"无法获取 {url} (已重试 {retries} 次)")


# ---------------------------------------------------------------------------
# aiyuan.ai: 大师索引
# ---------------------------------------------------------------------------
def parse_guru_index(html: str) -> List[GuruMeta]:
    """从 /gurus 首页解析 21 位大师(slug / 中文名 / 英文名)。"""
    gurus: List[GuruMeta] = []
    pattern = re.compile(
        r'href="(/gurus/[a-z0-9-]+)"[^>]*>.*?<h3[^>]*>([^<]+)</h3><p[^>]*>([^<]*)</p>',
        re.S,
    )
    seen: set = set()
    for m in pattern.finditer(html):
        slug = m.group(1).replace("/gurus/", "")
        if slug in seen:
            continue
        seen.add(slug)
        gurus.append(GuruMeta(
            slug=slug,
            cn_name=m.group(2).strip(),
            en_name=m.group(3).strip(),
        ))
    return gurus


# ---------------------------------------------------------------------------
# aiyuan.ai: 大师详情页
#   - 持仓表(全部)通过服务端渲染 HTML
#   - 详细持仓(shares/valueUsd/changePct)存于 Next.js Flight 数据的转义 JSON 对象中
# ---------------------------------------------------------------------------
def _extract_flight_objects(html: str) -> List[Dict[str, Any]]:
    """从 Next.js Flight data 提取形如 {\"ticker\":\"...\"...} 的 JSON 对象。

    Flight 数据把 JSON 里的引号做了 `\\\"` 双重转义, 这里先按大括号配对截取,
    再移除反斜杠后 json 解析。
    """
    out: List[Dict[str, Any]] = []
    pat = '{\\\\\"ticker\\\\\":'
    idx = 0
    n = len(html)
    while True:
        i = html.find(pat, idx)
        if i == -1:
            break
        # 找配对右括号
        depth = 0
        j = i
        while j < n:
            c = html[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        raw = html[i:j + 1]
        try:
            obj = json.loads(raw.replace(chr(92), ""))
            if isinstance(obj, dict):
                out.append(obj)
        except (json.JSONDecodeError, ValueError):
            pass
        idx = j + 1
    return out


def parse_guru_detail(html: str) -> Tuple[List[Holding], str]:
    """解析大师详情页。返回 (持仓列表, firm 名称)。"""
    soup = BeautifulSoup(html, "html.parser")

    # firm 名称: 通常从 title 或 description 提取
    firm = ""
    fm = re.search(r'<title>([^<]*)</title>', html)
    if fm:
        t = fm.group(1)
        m2 = re.search(r'(Berkshire Hathaway|[A-Z][A-Za-z .&\'-]*(?:L\.?P\.?|LLC|Inc\.?|Management|Capital|Funds?|Co\.?))', t)
        if m2:
            firm = m2.group(1).strip().rstrip("持仓")

    holdings_by_ticker: Dict[str, Holding] = {}

    # --- 1) 全部持仓表 (服务端渲染) ---
    for tr in soup.select("tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue
        tick_el = tr.select_one("span.font-mono.font-bold")
        if tick_el is None:
            continue
        ticker = tick_el.get_text(strip=True)
        if not re.fullmatch(r"[A-Z][A-Z0-9.:-]*", ticker):
            continue
        # 名称: ticker 下方 p
        name = ""
        name_el = tr.select_one("td p.text-xs")
        if name_el:
            name = name_el.get_text(strip=True)
        # 类型
        stype = ""
        type_el = tr.select_one("td span.text-\\[10px\\]")
        if type_el:
            stype = type_el.get_text(strip=True)
        # 占比%: 最后一列含百分比
        weight = None
        wm = re.search(r'width:([\d.]+)%', tr.get_text())
        if wm:
            weight = float(wm.group(1))
        # 行业
        sector = ""
        sec_el = tr.select("td")
        if sec_el:
            sector = sec_el[-1].get_text(strip=True)
        holdings_by_ticker[ticker] = Holding(
            ticker=ticker, name=name, weight_pct=weight,
            security_type=stype or None, sector=sector or None,
        )

    # --- 2) 详细持仓 (Flight 数据: shares/valueUsd/changePct) ---
    for obj in _extract_flight_objects(html):
        tk = obj.get("ticker")
        if not isinstance(tk, str) or "shares" not in obj:
            continue
        h = holdings_by_ticker.get(tk)
        if h is None:
            h = Holding(ticker=tk, name=str(obj.get("companyName", "")))
            holdings_by_ticker[tk] = h
        h.shares = _num(obj.get("shares"))
        h.value_usd = _num(obj.get("valueUsd"))
        h.chg_pct = _num(obj.get("changePct")) if obj.get("changePct") is not None else None
        h.sector = str(obj.get("sector")) or h.sector
        if not h.name:
            h.name = str(obj.get("companyName", ""))

    holdings = sorted(holdings_by_ticker.values(),
                      key=lambda x: (x.value_usd is None, -(x.value_usd or 0)))
    return holdings, firm


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# SEC EDGAR: 13F 验证
# ---------------------------------------------------------------------------
SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCH = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{file}"


@dataclass
class SecRow:
    issuer: str
    cusip: str
    value_1000: float   # 单位: 千美元
    shares: float


def sec_latest_13f(cik: str) -> Optional[Tuple[Optional[str], List[SecRow]]]:
    """取某 CIK 最近一期 13F-HR 的 (period, 持仓行)。period=None 表示取不到(未报/停报)。"""
    data = http_get(SEC_SUBMISSIONS.format(cik=cik.zfill(10)),
                    headers={"User-Agent": SEC_UA}, as_json=True)
    recent = data["filings"]["recent"]
    forms = recent["form"]
    accns = recent["accessionNumber"]
    prim = recent.get("primaryDocument") or [""] * len(forms)
    reps = recent.get("reportDate") or [""] * len(forms)
    for i, fo in enumerate(forms):
        if fo == "13F-HR":
            accn = accns[i]
            period = reps[i] if i < len(reps) else None
            rows = _fetch_info_table(cik, accn)
            return period, rows
    return None  # 近一年无 13F


def _fetch_info_table(cik: str, accn: str) -> List[SecRow]:
    """根据 accession 找到 filing 目录, 下载 infoTable XML 并解析。"""
    accn_clean = accn.replace("-", "")
    idx_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn_clean}/index.json"
    idx = http_get(idx_url, headers={"User-Agent": SEC_UA}, as_json=True)
    info_name = None
    items = idx.get("directory", {}).get("item", []) if isinstance(idx, dict) else []
    for item in items:
        nm = item.get("name", "")
        # 优先: 命名为 infotable 的 XML 文件(大小写不敏感)
        if "infotable" in nm.lower() and nm.lower().endswith(".xml"):
            info_name = nm
            break
        # 其次: 纯数字命名的 XML(部分申报公司用)
        if re.fullmatch(r"\d+\.xml", nm):
            info_name = nm
            break
    # 注意: 不把 primary_doc.xml 作为 infoTable 源 — 那是申报封面, 无持仓数据
    if not info_name:
        return []
    url = SEC_ARCH.format(cik=int(cik), accn=accn_clean, file=info_name)
    xml_text = http_get(url, headers={"User-Agent": SEC_UA})
    rows = _parse_info_table(xml_text)
    # 若解析到 0 行, 尝试其他候选文件(某些申报 infoTable 在额外 XML 中)
    if not rows:
        for item in items:
            nm = item.get("name", "")
            if nm == info_name or not nm.lower().endswith(".xml"):
                continue
            if nm == "primary_doc.xml":
                continue
            try:
                cand_rows = _parse_info_table(http_get(
                    SEC_ARCH.format(cik=int(cik), accn=accn_clean, file=nm),
                    headers={"User-Agent": SEC_UA}))
                if cand_rows:
                    return cand_rows
            except Exception:
                continue
    return rows


def _parse_info_table(xml_text: str) -> List[SecRow]:
    rows: List[SecRow] = []
    soup = BeautifulSoup(xml_text, "xml")
    for it in soup.find_all("infoTable"):
        issuer = (it.find("nameOfIssuer").get_text(strip=True) if it.find("nameOfIssuer") else "")
        cusip = (it.find("cusip").get_text(strip=True) if it.find("cusip") else "")
        value = 0.0
        if it.find("value"):
            try:
                value = float(it.find("value").get_text(strip=True))
            except ValueError:
                value = 0.0
        shares = 0.0
        sh = it.find("sshPrnamt")
        if sh:
            try:
                shares = float(sh.get_text(strip=True))
            except ValueError:
                shares = 0.0
        if issuer:
            rows.append(SecRow(issuer=issuer.upper(), cusip=cusip,
                               value_1000=value, shares=shares))
    return rows


def aggregate_info_rows(rows: List[SecRow]) -> Dict[str, Dict[str, float]]:
    """同一发行人多行(多 discretion 块)按 issuer 聚合 shares / value。"""
    agg: Dict[str, Dict[str, float]] = {}
    for r in rows:
        a = agg.setdefault(r.issuer, {"shares": 0.0, "value": 0.0})
        a["shares"] += r.shares
        a["value"] += r.value_1000
    return agg


def _norm_issuer(name: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", (name or "").upper())
    # 常见后缀归一
    return s.replace("INC", "").replace("CORP", "").replace("CO", "") \
            .replace("FINL", "").replace("MTNBE", "").replace("SWITZ", "")


def match_sec_to_holdings(holdings: List[Holding], agg: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    """将 SEC 聚合行(按 issuer)匹配到 aiyuan 持仓(按 ticker/name) -> {ticker: {shares,value_usd}}。

    匹配策略 (按优先级):
      1) name 直接匹配 (aiyuan 有公司名时)
      2) 规范化 name 匹配 (去 INC/CORP/CO 等后缀)
      3) ticker 反查：SEC issuer 规范化名 -> us_ticker_map 反查表得到 ticker
         (解决 aiyuan 持仓 name 为空 或 名称与 SEC 不一致 的问题)
    """
    # aiyuan 持仓 ticker 集合
    ticker_set = {h.ticker for h in holdings}

    # 建立 name -> ticker 映射
    name_to_ticker: Dict[str, str] = {}
    norm_to_names: Dict[str, str] = {}
    for h in holdings:
        nm = _norm_issuer(h.name)
        if nm:
            norm_to_names.setdefault(nm, h.ticker)
        up = (h.name or "").upper()
        if up:
            name_to_ticker.setdefault(up, h.ticker)

    # SEC issuer 规范化名 -> ticker 反查表 (来自 us_ticker_map)
    reverse_norm = _reverse_norm_map()

    result: Dict[str, Dict[str, float]] = {}
    for issuer, a in agg.items():
        tk = name_to_ticker.get(issuer)
        if tk is None:
            tk = norm_to_names.get(_norm_issuer(issuer))
        # ticker 反查：SEC issuer 名 -> (us_ticker_map) -> ticker
        if tk is None:
            n_i = _norm_issuer(issuer)
            rev_tk = reverse_norm.get(n_i)
            if rev_tk and rev_tk in ticker_set:
                tk = rev_tk
        if tk:
            result[tk] = {
                "shares": a["shares"],
                "value_usd": a["value"],  # SEC value 字段已是美元, 不再 ×1000
            }
        else:
            # 常见: name 缩写, 尝试前缀匹配 (仅保留原逻辑)
            n_i = _norm_issuer(issuer)
            for h in holdings:
                if h.name and _norm_issuer(h.name).startswith(n_i[:6]) and len(n_i) >= 6:
                    result.setdefault(h.ticker, {"shares": a["shares"], "value_usd": a["value"]})
                    break
    return result


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def fetch_guru_detail(guru: GuruMeta, *, use_sec: bool,
                      prev_cache: Optional[Dict[str, Dict[str, float]]]) -> Dict[str, Any]:
    url = f"{BASE_URL}/gurus/{guru.slug}"
    html = http_get(url)
    holdings, firm = parse_guru_detail(html)
    log.info("  大师 %s(%s): %d 条持仓, firm=%s", guru.cn_name, guru.slug, len(holdings), firm or "?")

    cik = GURU_CIKS.get(guru.slug)
    sec_period: Optional[str] = None
    sec_matched: Dict[str, Dict[str, float]] = {}

    if use_sec and cik:
        try:
            got = sec_latest_13f(cik)
            if got is not None:
                period, rows = got
                sec_period = period
                agg = aggregate_info_rows(rows)
                sec_matched = match_sec_to_holdings(holdings, agg)
                if sec_matched:
                    log.info("    SEC 验证 %s: 匹配 %d 条持仓 (period=%s)", guru.slug, len(sec_matched), period)
                else:
                    log.info("    SEC %s: 匹配到 0 条", guru.slug)
            else:
                log.info("    SEC %s: 近一年无 13F 申报", guru.slug)
        except Exception as exc:  # noqa: BLE001
            log.warning("    SEC %s 失败: %s", guru.slug, exc)

    # 合并 aiyuan 与 SEC
    merged = []
    for h in holdings:
        hd = asdict(h)
        hd.pop("sec_source", None)
        if h.ticker in sec_matched:
            sm = sec_matched[h.ticker]
            hd["shares"] = sm["shares"] if hd.get("shares") is None else hd["shares"]
            hd["value_usd"] = sm["value_usd"] if hd.get("value_usd") is None else hd["value_usd"]
            hd["sec_source"] = True
        merged.append(hd)

    return {
        "name": guru.cn_name,
        "en_name": guru.en_name,
        "slug": guru.slug,
        "firm": firm or GURU_FIRM_SEARCH.get(guru.slug, ""),
        "cik": cik,
        "sec_period": sec_period,
        "holdings": merged,
    }


def run(slug_filter: Optional[str] = None, *, use_sec: bool = True) -> Dict[str, Any]:
    # 1) 抓取索引
    log.info("抓取大师索引 %s", GURUS_URL)
    index_html = http_get(GURUS_URL)
    gurus = parse_guru_index(index_html)
    log.info("解析到 %d 位大师", len(gurus))

    if slug_filter:
        gurus = [g for g in gurus if g.slug == slug_filter]
        if not gurus:
            raise SystemExit(f"未找到大师: {slug_filter}")

    # 2) 逐位抓取详情 + SEC 验证
    as_of_date = ""
    guru_list: List[Dict[str, Any]] = []
    for guru in gurus:
        g = fetch_guru_detail(guru, use_sec=use_sec, prev_cache=None)
        if g.get("sec_period") and g["sec_period"] > as_of_date:
            as_of_date = g["sec_period"]
        guru_list.append(g)

    if not as_of_date:
        as_of_date = time.strftime("%Y-%m-%d")

    output = {
        "as_of_date": as_of_date,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": [GURUS_URL, "https://data.sec.gov (13F validation)"],
        "guru_count": len(guru_list),
        "gurus": guru_list,
    }
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="大师13F持仓爬虫 (aiyuan + SEC EDGAR)")
    parser.add_argument("--fetch", action="store_true", help="执行抓取(默认仅打印说明)")
    parser.add_argument("--guru", type=str, default=None, help="仅抓取指定 slug")
    parser.add_argument("--skip-sec", action="store_true", help="跳过 SEC EDGAR 验证")
    parser.add_argument("--out", type=str, default=str(OUTPUT_PATH), help="输出 JSON 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    if not args.fetch:
        print("用法: python guru_holdings.py --fetch [--guru slug] [--skip-sec]")
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        data = run(args.guru, use_sec=not args.skip_sec)
    except Exception as exc:  # noqa: BLE001
        log.error("抓取失败: %s", exc)
        return 1

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    total = sum(len(g["holdings"]) for g in data["gurus"])
    log.info("完成: 写入 %s (%d 位大师, 共 %d 条持仓, as_of=%s)",
             out_path, len(data["gurus"]), total, data["as_of_date"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
