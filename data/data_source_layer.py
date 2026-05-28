"""
多源免费数据层 v1.0 — 每种数据类型有主源+备源+质量标注

数据源优先级矩阵：
  A股股票日线/财务  : baostock (primary) → AKShare (fallback)
  A股 ETF 行情     : AKShare fund_etf_hist_em (primary) → baostock (fallback)
  A股全市场快照    : AKShare stock_zh_a_spot_em (唯一，无备源)
  中国宏观数据     : AKShare (primary) → 本地缓存 (fallback)
  北向资金         : AKShare stock_em_hsgt_north_net_flow_in_em
  美股/港股日线    : yfinance (primary，无替代)
  商品/汇率/债券   : yfinance (primary，已有价格校验)
  公募基金净值     : AKShare fund_etf_hist_em / fund_open_fund_info_em

设计原则：
  1. 每个取数函数返回 DataResult(data, source, fetched_at, quality)
  2. 质量状态: "fresh" / "stale" / "fallback" / "failed"
  3. 失败时显式返回 quality="failed"，不静默返回假数据
  4. 调用方检查 quality 决定是否使用
"""

import time
import logging
import hashlib
import json
import os
import socket
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Optional, Any
import pandas as pd

socket.setdefaulttimeout(8)  # 全局socket超时8秒，防止外部API挂死不返回

logger = logging.getLogger(__name__)

# ─── 缓存目录 ───
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "data", "cache")
os.makedirs(_CACHE_DIR, exist_ok=True)


# ═══════════════════════════════════════════
# 数据质量标注结构
# ═══════════════════════════════════════════

@dataclass
class DataResult:
    data: Any
    source: str
    fetched_at: str
    quality: str          # "fresh" / "stale" / "fallback" / "failed"
    staleness_days: float = 0.0
    warning: str = ""

    @property
    def ok(self) -> bool:
        return self.quality in ("fresh", "stale", "fallback")

    @property
    def badge(self) -> str:
        icons = {"fresh": "✅", "stale": "⚠️", "fallback": "🔄", "failed": "❌"}
        return f"{icons.get(self.quality, '❓')} {self.source}({self.fetched_at[:10]})"

    @staticmethod
    def failed(source: str, reason: str) -> "DataResult":
        return DataResult(
            data=None, source=source,
            fetched_at=datetime.now().isoformat(),
            quality="failed", warning=reason,
        )


# ═══════════════════════════════════════════
# 通用工具
# ═══════════════════════════════════════════

_call_timestamps: dict = {}
_MIN_INTERVALS = {"akshare": 1.0, "yfinance": 0.5, "baostock": 0.3}

def _rate_limit(source: str):
    now = time.time()
    last = _call_timestamps.get(source, 0)
    gap = _MIN_INTERVALS.get(source, 0.5)
    if now - last < gap:
        time.sleep(gap - (now - last))
    _call_timestamps[source] = time.time()


def _is_connection_reset(e: Exception) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("connection aborted", "remote end closed", "remotedisconnected", "connection reset"))


def _retry(fn, max_attempts: int = 2, delay: float = 1.0, source: str = ""):
    """重试包装器，默认2次重试（无超时时容易挂死，少重试比多重试好）"""
    last_err = None
    for attempt in range(max_attempts):
        try:
            _rate_limit(source)
            return fn()
        except Exception as e:
            last_err = e
            if attempt < max_attempts - 1:
                wait = delay * (2 ** attempt)
                if _is_connection_reset(e):
                    wait = max(wait, 5.0)
                logger.debug("[retry] %s attempt %d/%d failed: %s, wait %.1fs",
                             source, attempt + 1, max_attempts, str(e)[:60], wait)
                time.sleep(wait)
    raise last_err


def _cache_key(prefix: str, *args) -> str:
    raw = f"{prefix}_{':'.join(str(a) for a in args)}"
    return hashlib.md5(raw.encode()).hexdigest()[:12]


def _read_cache(key: str, ttl_seconds: int) -> Optional[Any]:
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            cached = json.load(f)
        age = time.time() - cached.get("_ts", 0)
        if age <= ttl_seconds:
            return cached.get("data")
    except Exception:
        pass
    return None


def _write_cache(key: str, data: Any):
    path = os.path.join(_CACHE_DIR, f"{key}.json")
    try:
        with open(path, "w") as f:
            json.dump({"_ts": time.time(), "data": data}, f, ensure_ascii=False, default=str)
    except Exception as e:
        logger.debug("缓存写入失败: %s", e)


def _freshness(fetched_at: str) -> float:
    try:
        dt = datetime.fromisoformat(fetched_at)
        return (datetime.now() - dt).total_seconds() / 86400
    except Exception:
        return 999.0


# ═══════════════════════════════════════════
# 1. A股 ETF 行情  — AKShare 主力
# ═══════════════════════════════════════════

def _a_etf_bs_code(code: str) -> str:
    """
    将6位ETF代码转换为baostock格式（sh./sz.前缀）
    规则：
      6开头 → sh（上交所普通股/ETF）
      5开头 → sh（上交所ETF：510xxx/511xxx/512xxx/513xxx/515xxx/516xxx/518xxx）
      1开头 → sh（上交所基金：159xxx部分是深交所，但16xxxx/15xxxx需要判断）
      159xxx → sz（深交所ETF）
      其他1开头 → sh（上交所基金，如162xxx/164xxx/165xxx/166xxx等）
      0/2/3开头 → sz
    """
    c = str(code).zfill(6)
    if c.startswith("6") or c.startswith("5"):
        return f"sh.{c}"
    if c.startswith("159"):
        return f"sz.{c}"
    if c.startswith("1"):
        return f"sh.{c}"
    return f"sz.{c}"


def get_a_etf_hist(code: str, days: int = 60) -> DataResult:
    """
    获取 A 股 ETF 历史行情（日线）
    code: 6 位代码，如 "512890"（红利低波）
    返回 DataFrame，columns: date / open / close / high / low / volume / turnover
    """
    cache_key = _cache_key("a_etf_hist", code, days)
    cached = _read_cache(cache_key, ttl_seconds=3600)
    if cached is not None:
        df = pd.DataFrame(cached)
        if not df.empty:
            staleness = _freshness(str(df["date"].iloc[-1]))
            quality = "fresh" if staleness <= 2 else "stale"
            return DataResult(df, f"cache/{code}", df["date"].iloc[-1], quality, staleness)

    def _fetch_akshare():
        import akshare as ak
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
        df = ak.fund_etf_hist_em(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )
        if df is None or df.empty:
            raise ValueError(f"AKShare 返回空数据: {code}")
        df = df.rename(columns={"日期": "date", "开盘": "open", "收盘": "close",
                                  "最高": "high", "最低": "low", "成交量": "volume",
                                  "成交额": "turnover"})
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df[["date", "open", "close", "high", "low", "volume", "turnover"]].tail(days)

    def _fetch_baostock_fallback():
        import baostock as bs
        sym = _a_etf_bs_code(code)
        lg = bs.login()
        if lg.error_code != "0":
            raise ConnectionError("baostock login failed")
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y-%m-%d")
        rs = bs.query_history_k_data_plus(
            sym, "date,open,close,high,low,volume,amount",
            start_date=start, end_date=end, frequency="d", adjustflag="3",
        )
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        bs.logout()
        if not rows:
            raise ValueError(f"baostock 返回空: {code}")
        df = pd.DataFrame(rows, columns=["date", "open", "close", "high", "low", "volume", "turnover"])
        for col in ["open", "close", "high", "low", "volume", "turnover"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df.tail(days)

    try:
        df = _retry(_fetch_akshare, source="akshare")
        _write_cache(cache_key, df.to_dict("records"))
        staleness = _freshness(str(df["date"].iloc[-1]))
        return DataResult(df, f"akshare/fund_etf_hist_em({code})", df["date"].iloc[-1],
                          "fresh" if staleness <= 2 else "stale", staleness)
    except Exception as e1:
        logger.warning("[ETF] AKShare 失败 %s: %s，尝试 baostock", code, e1)
        try:
            df = _retry(_fetch_baostock_fallback, source="baostock")
            staleness = _freshness(str(df["date"].iloc[-1]))
            return DataResult(df, f"baostock({code})", df["date"].iloc[-1],
                              "fallback", staleness, warning=str(e1))
        except Exception as e2:
            logger.error("[ETF] 全部数据源失败 %s: baostock=%s", code, e2)
            return DataResult.failed(f"all_sources({code})", f"akshare={e1}; baostock={e2}")


def get_a_etf_realtime(codes: list) -> DataResult:
    """
    批量获取 A 股 ETF 实时行情（当日快照）
    返回 DataFrame，index=code，含 close/change_pct/volume 等
    """
    def _fetch():
        import akshare as ak
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            raise ValueError("fund_etf_spot_em 返回空")
        df = df.rename(columns={
            "代码": "code", "名称": "name", "最新价": "close",
            "涨跌幅": "change_pct", "涨跌额": "change_amt",
            "成交量": "volume", "成交额": "turnover",
        })
        df["code"] = df["code"].astype(str).str.zfill(6)
        df = df[df["code"].isin([str(c).zfill(6) for c in codes])]
        return df.set_index("code")

    try:
        df = _retry(_fetch, source="akshare")
        return DataResult(df, "akshare/fund_etf_spot_em", datetime.now().isoformat(), "fresh")
    except Exception as e:
        return DataResult.failed("akshare/fund_etf_spot_em", str(e))


# ═══════════════════════════════════════════
# 2. 公募基金净值 — AKShare
# ═══════════════════════════════════════════

def get_fund_nav_hist(fund_code: str, days: int = 90) -> DataResult:
    """
    获取公募基金历史净值（开放式基金）
    fund_code: 6 位基金代码，如 "110022"（易方达消费）
    返回 DataFrame: date / nav / acc_nav / change_pct
    """
    cache_key = _cache_key("fund_nav", fund_code, days)
    cached = _read_cache(cache_key, ttl_seconds=7200)
    if cached is not None:
        df = pd.DataFrame(cached)
        if not df.empty:
            return DataResult(df, f"cache/fund_nav({fund_code})", df["date"].iloc[-1], "fresh")

    def _fetch():
        import akshare as ak
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")
        df = ak.fund_open_fund_info_em(fund=fund_code, indicator="单位净值走势")
        if df is None or df.empty:
            raise ValueError(f"fund_open_fund_info_em 返回空: {fund_code}")
        df = df.rename(columns={"净值日期": "date", "单位净值": "nav", "日增长率": "change_pct"})
        df["acc_nav"] = df.get("累计净值", df["nav"])
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df["change_pct"] = pd.to_numeric(df["change_pct"], errors="coerce")
        df = df.sort_values("date").tail(days)
        return df[["date", "nav", "acc_nav", "change_pct"]]

    try:
        df = _retry(_fetch, source="akshare")
        _write_cache(cache_key, df.to_dict("records"))
        staleness = _freshness(str(df["date"].iloc[-1]))
        return DataResult(df, f"akshare/fund_nav({fund_code})", df["date"].iloc[-1],
                          "fresh" if staleness <= 2 else "stale", staleness)
    except Exception as e:
        return DataResult.failed(f"akshare/fund_nav({fund_code})", str(e))


def get_fund_basic_info(fund_code: str) -> DataResult:
    """获取基金基本信息：规模、成立日期、基金经理、类型等"""
    def _fetch():
        import akshare as ak
        df = ak.fund_individual_basic_info_xq(symbol=fund_code)
        if df is None or df.empty:
            raise ValueError(f"fund_individual_basic_info_xq 返回空: {fund_code}")
        info = {}
        for _, row in df.iterrows():
            info[row.iloc[0]] = row.iloc[1]
        return info

    try:
        info = _retry(_fetch, source="akshare")
        return DataResult(info, f"akshare/fund_basic({fund_code})", datetime.now().isoformat(), "fresh")
    except Exception as e:
        return DataResult.failed(f"akshare/fund_basic({fund_code})", str(e))


# ═══════════════════════════════════════════
# 3. A股全市场快照 — AKShare（动态筛选基础）
# ═══════════════════════════════════════════

_universe_cache: Optional[DataResult] = None
_universe_cache_time: float = 0
_UNIVERSE_TTL = 1800

def get_a_share_universe_snapshot() -> DataResult:
    """
    获取 A 股全市场实时快照（用于动态候选池筛选）
    数据源：AKShare stock_zh_a_spot_em（东方财富实时行情）
    包含：代码/名称/现价/涨跌幅/换手率/成交额/市值/PE/PB/市盈率动态
    """
    global _universe_cache, _universe_cache_time
    if _universe_cache and (time.time() - _universe_cache_time) < _UNIVERSE_TTL:
        return _universe_cache

    def _fetch():
        import akshare as ak
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            raise ValueError("stock_zh_a_spot_em 返回空")
        df = df.rename(columns={
            "代码": "code", "名称": "name", "最新价": "close",
            "涨跌幅": "change_pct", "涨跌额": "change_amt",
            "成交量": "volume", "成交额": "turnover_amount",
            "振幅": "amplitude", "最高": "high", "最低": "low",
            "今开": "open", "昨收": "prev_close",
            "量比": "volume_ratio", "换手率": "turnover_rate",
            "市盈率-动态": "pe_ttm", "市净率": "pb",
            "总市值": "total_mktcap", "流通市值": "float_mktcap",
        })
        df["code"] = df["code"].astype(str).str.zfill(6)
        for col in ["close", "change_pct", "turnover_amount", "turnover_rate",
                    "pe_ttm", "pb", "total_mktcap", "float_mktcap", "volume_ratio"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        return df

    try:
        df = _retry(_fetch, source="akshare")
        result = DataResult(df, "akshare/stock_zh_a_spot_em",
                            datetime.now().isoformat(), "fresh")
        _universe_cache = result
        _universe_cache_time = time.time()
        return result
    except Exception as e:
        logger.error("[Universe] 全市场快照失败: %s", e)
        return DataResult.failed("akshare/stock_zh_a_spot_em", str(e))


def build_candidate_universe(
    min_mktcap_yi: float = 30,
    max_mktcap_yi: float = 200,
    min_turnover_pct: float = 1.5,
    min_amount_wan: float = 3000,
    min_list_days: int = 120,
) -> DataResult:
    """
    从全市场快照筛选中小市值候选池
    返回过滤后的 DataFrame，用于多因子评分
    """
    snapshot = get_a_share_universe_snapshot()
    if not snapshot.ok or snapshot.data is None:
        return DataResult.failed("universe_builder", f"快照获取失败: {snapshot.warning}")

    df = snapshot.data.copy()
    total_before = len(df)

    df = df[~df["name"].str.contains("ST|退|B股|C|N", na=False)]
    df = df[df["close"] > 0]
    df = df[df["float_mktcap"].notna() & (df["float_mktcap"] >= min_mktcap_yi * 1e8)]
    df = df[df["float_mktcap"] <= max_mktcap_yi * 1e8]
    df = df[df["turnover_rate"].notna() & (df["turnover_rate"] >= min_turnover_pct)]
    df = df[df["turnover_amount"].notna() & (df["turnover_amount"] >= min_amount_wan * 1e4)]
    df = df[df["pe_ttm"].notna() & (df["pe_ttm"] > 0) & (df["pe_ttm"] < 300)]
    df = df[df["pb"].notna() & (df["pb"] > 0)]

    total_after = len(df)
    logger.info("[Universe] 全市场%d只 → 过滤后%d只候选", total_before, total_after)

    result = snapshot
    result.data = df.reset_index(drop=True)
    result.warning = f"筛选: {total_before}→{total_after}只"
    return result


# ═══════════════════════════════════════════
# 4. 宏观数据 — AKShare（增强版，多fallback）
# ═══════════════════════════════════════════

_MACRO_TTL = 86400 * 7

def get_macro_data_v2() -> DataResult:
    """
    获取中国宏观数据（CPI/PMI/M2/Shibor）
    TTL=7天（月度数据，无需频繁刷新）
    增加了列名容错处理（AKShare 不同版本列名可能不同）
    """
    cache_key = "macro_cn_v2"
    cached = _read_cache(cache_key, ttl_seconds=_MACRO_TTL)
    if cached is not None:
        staleness = _freshness(cached.get("fetched_at", ""))
        return DataResult(cached, "cache/macro_cn", cached.get("fetched_at", "")[:10],
                          "fresh" if staleness <= 7 else "stale", staleness)

    result = {
        "fetched_at": datetime.now().isoformat(),
        "cpi": None, "pmi": None, "m2_growth": None, "shibor": None,
        "cpi_date": None, "pmi_date": None, "data_ok": False,
    }
    warnings = []

    try:
        import akshare as ak

        # CPI — 容错多个列名版本
        try:
            df = ak.macro_china_cpi_monthly()
            value_col = next((c for c in df.columns if "今值" in str(c) or "current" in str(c).lower()), None)
            date_col = next((c for c in df.columns if "日期" in str(c) or "date" in str(c).lower()), None)
            prev_col = next((c for c in df.columns if "前值" in str(c) or "previous" in str(c).lower()), None)
            if value_col:
                row = df.dropna(subset=[value_col]).iloc[-1]
                result["cpi"] = float(row[value_col])
                if date_col:
                    result["cpi_date"] = str(row[date_col])
                if prev_col:
                    prev = float(row[prev_col]) if pd.notna(row[prev_col]) else result["cpi"]
                    result["cpi_trend"] = "up" if result["cpi"] > prev else ("down" if result["cpi"] < prev else "flat")
        except Exception as e:
            warnings.append(f"cpi={e}")

        # PMI
        try:
            df = ak.macro_china_pmi()
            idx_col = next((c for c in df.columns if "制造业" in str(c) and "指数" in str(c)), None)
            date_col = next((c for c in df.columns if "月份" in str(c) or "date" in str(c).lower()), None)
            if idx_col:
                row = df.dropna(subset=[idx_col]).iloc[0]
                result["pmi"] = float(row[idx_col])
                if date_col:
                    result["pmi_date"] = str(row[date_col])
        except Exception as e:
            warnings.append(f"pmi={e}")

        # Shibor 隔夜
        try:
            df = ak.rate_interbank(market="上海银行间同业拆放利率",
                                   symbol="Shibor人民币", indicator="隔夜")
            result["shibor"] = float(df.iloc[-1, 1])
        except Exception as e:
            warnings.append(f"shibor={e}")

        # M2
        try:
            df = ak.macro_china_m2_supply()
            row = df.dropna().iloc[-1]
            result["m2_growth"] = float(row.iloc[2])
            result["m2"] = float(row.iloc[1])
        except Exception as e:
            warnings.append(f"m2={e}")

        # 社融/信用增速（宽信用判断的替代指标）
        try:
            df = ak.macro_china_shrzgm()
            if not df.empty:
                result["social_financing_growth"] = float(df.iloc[-1, 2])
        except Exception:
            pass

        # 判断数据完整性
        critical = [result["cpi"], result["pmi"]]
        if any(v is not None for v in critical):
            result["data_ok"] = True

    except ImportError:
        return DataResult.failed("akshare", "akshare 未安装")
    except Exception as e:
        return DataResult.failed("akshare/macro", str(e))

    if warnings:
        result["partial_warnings"] = warnings

    _write_cache(cache_key, result)

    quality = "fresh" if result["data_ok"] else "failed"
    if not result["data_ok"]:
        return DataResult(result, "akshare/macro", result["fetched_at"][:10], "failed",
                          warning="; ".join(warnings))

    return DataResult(result, "akshare/macro", result["fetched_at"][:10], quality,
                      warning="; ".join(warnings) if warnings else "")


# ═══════════════════════════════════════════
# 5. 美股/港股/ETF — yfinance（增强重试+校验）
# ═══════════════════════════════════════════

PRICE_SANITY = {
    "GC=F": (1000, 4500), "CL=F": (20, 150), "HG=F": (2, 8),
    "SI=F": (10, 80), "NG=F": (1, 20), "DBA": (10, 40),
    "GLD": (100, 300), "USO": (50, 120), "SLV": (10, 50),
    "^TNX": (0, 20), "^TYX": (0, 20), "^VIX": (5, 100),
}

_FX_DIRECTION_CHECK = {
    "EURUSD=X": (0.8, 1.6),
    "CNY=X": (6.0, 8.5),
    "JPY=X": (100, 170),
}


def get_yf_price_hist(symbol: str, period: str = "6mo") -> DataResult:
    """
    获取美股/港股/ETF历史行情（带价格校验）
    """
    def _fetch():
        import yfinance as yf
        t = yf.Ticker(symbol)
        df = t.history(period=period)
        if df is None or df.empty:
            raise ValueError(f"yfinance 返回空: {symbol}")
        df = df.reset_index()
        df.columns = [c.lower() for c in df.columns]
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        return df

    try:
        df = _retry(_fetch, max_attempts=3, delay=0.8, source="yfinance")

        last_price = float(df["close"].iloc[-1]) if not df.empty else None
        warning = ""

        if last_price is not None and symbol in PRICE_SANITY:
            lo, hi = PRICE_SANITY[symbol]
            if not (lo <= last_price <= hi):
                return DataResult.failed(
                    f"yfinance/{symbol}",
                    f"价格异常: {last_price:.2f} 超出合理区间[{lo},{hi}]"
                )

        if symbol in _FX_DIRECTION_CHECK and last_price is not None:
            lo, hi = _FX_DIRECTION_CHECK[symbol]
            if not (lo <= last_price <= hi):
                return DataResult.failed(
                    f"yfinance/{symbol}",
                    f"汇率方向可能倒置: {last_price:.4f} 超出[{lo},{hi}]"
                )

        last_date = df["date"].iloc[-1] if not df.empty else ""
        staleness = _freshness(last_date)
        quality = "fresh" if staleness <= 3 else "stale"

        return DataResult(df, f"yfinance/{symbol}", last_date, quality, staleness, warning)

    except Exception as e:
        return DataResult.failed(f"yfinance/{symbol}", str(e))


def get_yf_current_price(symbol: str) -> DataResult:
    """获取最新价格（单点）"""
    def _fetch():
        import yfinance as yf
        t = yf.Ticker(symbol)
        info = t.fast_info
        price = info.get("lastPrice") or info.get("regularMarketPrice")
        if price is None:
            raise ValueError("fast_info 无价格数据")
        return float(price)

    try:
        price = _retry(_fetch, max_attempts=3, delay=0.8, source="yfinance")

        if symbol in PRICE_SANITY:
            lo, hi = PRICE_SANITY[symbol]
            if not (lo <= price <= hi):
                return DataResult.failed(f"yfinance/{symbol}",
                                         f"价格异常: {price:.4f} 超出[{lo},{hi}]")

        return DataResult(price, f"yfinance/{symbol}", datetime.now().isoformat(), "fresh")
    except Exception as e:
        return DataResult.failed(f"yfinance/{symbol}", str(e))


# ═══════════════════════════════════════════
# 6. LDS 全天候组合成分数据获取
# ═══════════════════════════════════════════

LDS_COMPONENTS = {
    "红利低波ETF": {
        "a_code": "512890",
        "us_code": None,
        "weight": 0.25,
        "asset_class": "A股策略ETF",
        "data_fn": "a_etf",
    },
    "纳指100ETF": {
        "a_code": "513100",
        "us_code": "QQQ",
        "weight": 0.30,
        "asset_class": "美股科技",
        "data_fn": "both",
    },
    "黄金ETF": {
        "a_code": "518880",
        "us_code": "GLD",
        "weight": 0.25,
        "asset_class": "商品贵金属",
        "data_fn": "both",
    },
    "豆粕ETF": {
        "a_code": "159985",
        "us_code": "DBA",
        "weight": 0.20,
        "asset_class": "商品农产品",
        "data_fn": "both",
    },
}


def get_lds_component(name: str, days: int = 60) -> DataResult:
    """
    获取单个 LDS 全天候成分数据
    优先取 A 股 ETF（AKShare），如果需要美股版本则 yfinance
    """
    cfg = LDS_COMPONENTS.get(name)
    if cfg is None:
        return DataResult.failed("lds_component", f"未知成分: {name}")

    result = get_a_etf_hist(cfg["a_code"], days=days)
    if result.ok:
        return result

    if cfg["us_code"]:
        logger.info("[LDS] %s A股ETF失败，改用美股: %s", name, cfg["us_code"])
        us_result = get_yf_price_hist(cfg["us_code"], period="6mo")
        if us_result.ok:
            us_result.quality = "fallback"
            us_result.warning = f"A股ETF({cfg['a_code']})失败，使用美股版本({cfg['us_code']})"
            return us_result

    return DataResult.failed(f"lds/{name}", f"A股ETF和美股版本均失败")


def get_all_lds_portfolio(days: int = 60) -> dict:
    """
    获取全部 LDS 全天候成分数据
    返回 {name: DataResult}
    """
    return {name: get_lds_component(name, days=days) for name in LDS_COMPONENTS}


# ═══════════════════════════════════════════
# 7. 数据质量汇总报告
# ═══════════════════════════════════════════

def summarize_data_quality(results: dict) -> dict:
    """
    输入: {name: DataResult}
    输出: 质量汇总，供日报展示
    """
    total = len(results)
    fresh = sum(1 for r in results.values() if r.quality == "fresh")
    stale = sum(1 for r in results.values() if r.quality == "stale")
    fallback = sum(1 for r in results.values() if r.quality == "fallback")
    failed = sum(1 for r in results.values() if r.quality == "failed")

    if failed == 0 and stale == 0:
        badge = "✅ 数据全部正常"
    elif failed == 0:
        badge = f"⚠️ {stale}个字段数据较旧"
    elif failed <= total * 0.2:
        badge = f"🟡 {failed}个字段获取失败（{total-failed}个正常）"
    else:
        badge = f"🔴 {failed}个字段获取失败，报告质量受影响"

    return {
        "total": total, "fresh": fresh, "stale": stale,
        "fallback": fallback, "failed": failed,
        "badge": badge,
        "details": {name: r.badge for name, r in results.items()},
        "failed_list": [name for name, r in results.items() if r.quality == "failed"],
    }
