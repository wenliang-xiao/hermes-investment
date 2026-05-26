"""
基金追踪模块 v1.0

覆盖三类基金：
  1. LDS 全天候 ETF 组合（两个版本：A股版 + 美股版）
  2. 跨市场跨境 ETF（纳指/标普/恒生/黄金/债券）
  3. 同类对比：找当前动量/夏普最优的同类替代品
"""
import logging
import pandas as pd
import numpy as np
from datetime import datetime
from .data_source_layer import (
    get_a_etf_hist, get_yf_price_hist,
    get_all_lds_portfolio, DataResult, summarize_data_quality,
)

logger = logging.getLogger(__name__)


# ─── LDS 两个全天候版本 ───

LDS_PORTFOLIO_A = {
    "红利低波": {"code": "512890", "weight": 0.25, "type": "A股ETF", "role": "防守/红利"},
    "纳指100": {"code": "513100", "weight": 0.30, "type": "A股跨境ETF", "role": "成长/科技"},
    "黄金": {"code": "518880", "weight": 0.25, "type": "A股ETF", "role": "避险/通胀"},
    "豆粕": {"code": "159985", "weight": 0.20, "type": "A股ETF", "role": "商品/分散"},
}

LDS_PORTFOLIO_US = {
    "红利低波": {"code": "DVY", "weight": 0.25, "type": "US ETF", "role": "防守/红利"},
    "纳指100": {"code": "QQQ", "weight": 0.30, "type": "US ETF", "role": "成长/科技"},
    "黄金": {"code": "GLD", "weight": 0.25, "type": "US ETF", "role": "避险/通胀"},
    "豆粕": {"code": "DBA", "weight": 0.20, "type": "US ETF", "role": "商品/分散"},
}

# ─── 各类可比 ETF 对比池（找同类最优）───

ETF_PEER_GROUPS = {
    "A股宽基": [
        ("510050", "上证50ETF"), ("510300", "沪深300ETF"),
        ("510500", "中证500ETF"), ("159845", "中证1000ETF"),
        ("588000", "科创50ETF"), ("159915", "创业板ETF"),
    ],
    "A股主题科技": [
        ("512480", "半导体ETF"), ("512660", "军工ETF"),
        ("515000", "科技ETF"), ("159995", "芯片ETF"),
        ("515220", "数字经济ETF"), ("159819", "人工智能ETF"),
    ],
    "A股红利策略": [
        ("512890", "红利低波ETF"), ("510880", "红利ETF"),
        ("563020", "红利成长ETF"), ("159905", "央企红利ETF"),
    ],
    "跨境科技": [
        ("513100", "纳指100ETF"), ("513500", "标普500ETF"),
        ("513050", "中概互联ETF"), ("159632", "恒生科技ETF"),
    ],
    "商品对冲": [
        ("518880", "黄金ETF"), ("159985", "豆粕ETF"),
        ("162411", "华宝油气ETF"), ("159981", "能源化工ETF"),
    ],
    "债券防守": [
        ("511010", "国债ETF"), ("511520", "政金债ETF"),
        ("159926", "30年国债ETF"), ("511090", "10年国债ETF"),
    ],
    "US宽基": [
        ("SPY", "标普500"), ("QQQ", "纳斯达克100"),
        ("IWM", "罗素2000小盘"), ("VTI", "全市场"),
    ],
    "US科技主题": [
        ("SMH", "半导体"), ("SOXX", "费城半导体"),
        ("XLK", "科技板块"), ("IGV", "软件/SaaS"),
    ],
    "US防守/对冲": [
        ("GLD", "黄金"), ("TLT", "20年美债"),
        ("XLU", "公用事业"), ("XLP", "必需消费"),
    ],
}


def _compute_metrics(df: pd.DataFrame, name: str, weight: float) -> dict:
    """从价格序列计算关键指标"""
    if df is None or df.empty or "close" not in df.columns:
        return {"name": name, "weight": weight, "error": "无数据"}

    close = pd.to_numeric(df["close"], errors="coerce").dropna()
    if len(close) < 2:
        return {"name": name, "weight": weight, "error": "数据不足"}

    curr = float(close.iloc[-1])
    ret_1d = float((curr / close.iloc[-2] - 1) * 100) if len(close) >= 2 else None
    ret_20d = float((curr / close.iloc[-20] - 1) * 100) if len(close) >= 20 else None
    ret_60d = float((curr / close.iloc[-60] - 1) * 100) if len(close) >= 60 else None

    daily_ret = close.pct_change().dropna()
    vol_20d = float(daily_ret.tail(20).std() * np.sqrt(252) * 100) if len(daily_ret) >= 20 else None

    ytd = None
    if hasattr(df, "date") or "date" in df.columns:
        dates = pd.to_datetime(df["date"]) if "date" in df.columns else df.index
        this_year = dates.dt.year == datetime.now().year
        yr_start_idx = this_year.idxmax() if this_year.any() else None
        if yr_start_idx is not None:
            yr_start_price = float(close.loc[yr_start_idx])
            ytd = round((curr - yr_start_price) / yr_start_price * 100, 2)

    sharpe = None
    if vol_20d and vol_20d > 0 and ret_20d is not None:
        annualized_ret = ret_20d / 20 * 252
        sharpe = round(annualized_ret / vol_20d, 2)

    max_dd = None
    if len(close) >= 5:
        peak = close.expanding().max()
        dd = (close / peak - 1) * 100
        max_dd = round(float(dd.min()), 2)

    return {
        "name": name,
        "weight": weight,
        "price": round(curr, 3),
        "ret_1d": round(ret_1d, 2) if ret_1d is not None else None,
        "ret_20d": round(ret_20d, 2) if ret_20d is not None else None,
        "ret_60d": round(ret_60d, 2) if ret_60d is not None else None,
        "ytd": ytd,
        "vol_20d": round(vol_20d, 1) if vol_20d is not None else None,
        "sharpe_approx": sharpe,
        "max_dd": max_dd,
        "signal": _price_signal(ret_20d, vol_20d),
    }


def _price_signal(ret_20d: float, vol_20d: float) -> str:
    if ret_20d is None:
        return "⚪ 数据不足"
    if ret_20d > 5:
        return "🟢 强势"
    if ret_20d > 0:
        return "🟡 偏强"
    if ret_20d > -5:
        return "🟠 偏弱"
    return "🔴 弱势"


def track_lds_portfolio_v2(version: str = "A", bw_quadrant: str = "", dual_gate_open: bool = True) -> dict:
    """
    追踪 LDS 全天候组合（v2，使用 data_source_layer）
    version: "A"=A股版, "US"=美股版, "both"=两个版本对比
    bw_quadrant: 桥水象限，如 "Q4_增长↓_通胀↓"，用于再平衡建议
    dual_gate_open: LDS双门是否开启，关闭时暂缓再平衡
    """
    portfolio = LDS_PORTFOLIO_A if version in ("A", "both") else LDS_PORTFOLIO_US
    us_portfolio = LDS_PORTFOLIO_US if version == "both" else None

    components = []
    data_results = {}

    for name, cfg in portfolio.items():
        if cfg["type"].startswith("A"):
            result = get_a_etf_hist(cfg["code"], days=90)
        else:
            result = get_yf_price_hist(cfg["code"], period="6mo")

        data_results[name] = result
        metrics = {}
        if result.ok and result.data is not None:
            metrics = _compute_metrics(result.data, name, cfg["weight"])
        else:
            metrics = {"name": name, "weight": cfg["weight"], "error": result.warning}

        metrics.update({
            "code": cfg["code"],
            "type": cfg["type"],
            "role": cfg["role"],
            "data_badge": result.badge,
        })
        components.append(metrics)

    valid = [c for c in components if "ret_1d" in c and c["ret_1d"] is not None]
    portfolio_ret_1d = None
    portfolio_ytd = None

    if valid:
        portfolio_ret_1d = round(sum(c["ret_1d"] * c["weight"] for c in valid), 2)
        ytd_valid = [c for c in valid if c.get("ytd") is not None]
        if ytd_valid:
            portfolio_ytd = round(sum(c["ytd"] * c["weight"] for c in ytd_valid), 2)

    need_rebalance, rebalance_note = _check_rebalance(valid, bw_quadrant=bw_quadrant, dual_gate_open=dual_gate_open)
    quality_summary = summarize_data_quality(data_results)

    result_dict = {
        "version": f"LDS全天候{'A股版' if version == 'A' else '美股版'}",
        "portfolio_ret_1d": portfolio_ret_1d,
        "portfolio_ytd": portfolio_ytd,
        "need_rebalance": need_rebalance,
        "rebalance_note": rebalance_note,
        "components": components,
        "data_quality": quality_summary,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }

    if version == "both" and us_portfolio:
        result_dict["us_version"] = track_lds_portfolio_v2("US")

    return result_dict


def _check_rebalance(components: list, bw_quadrant: str = "", dual_gate_open: bool = True) -> tuple:
    rets = [c["ret_20d"] for c in components if c.get("ret_20d") is not None]
    if not rets or len(rets) < 2:
        return False, "数据不足，无法判断再平衡"
    spread = max(rets) - min(rets)

    if spread > 10:
        best = max(components, key=lambda c: c.get("ret_20d") or -999)
        worst_comp = min(components, key=lambda c: c.get("ret_20d") or 0)

        if not dual_gate_open:
            return False, (
                f"成分20日收益差={spread:.1f}%>10%，技术上应再平衡，"
                f"但双门关闭→底仓维持，等双门转绿再调仓"
            )

        q4_hint = ""
        if "Q4" in bw_quadrant or "增长↓" in bw_quadrant:
            q4_hint = "（象限4建议：增配长债/黄金，减商品）"

        return True, (
            f"成分20日收益差={spread:.1f}%>10%，"
            f"建议减{best['name']}补{worst_comp['name']}{q4_hint}"
        )

    return False, f"成分20日收益差={spread:.1f}%，未触发再平衡"


def scan_etf_peer_group(group_name: str, top_n: int = 5) -> list:
    """
    扫描同类 ETF 对比组，按动量+夏普排序，找出当前最优
    用于"找类似的"逻辑：在红利/纳指/黄金等大类里挑最好的
    """
    peers = ETF_PEER_GROUPS.get(group_name, [])
    if not peers:
        logger.warning("未知 ETF 分组: %s", group_name)
        return []

    results = []
    for code, name in peers:
        if code.isdigit() or (len(code) == 6 and code[0] in "0156"):
            result = get_a_etf_hist(code, days=60)
        else:
            result = get_yf_price_hist(code, period="3mo")

        if not result.ok or result.data is None:
            results.append({"code": code, "name": name, "error": result.warning})
            continue

        metrics = _compute_metrics(result.data, name, 1.0)
        metrics["code"] = code
        metrics["data_badge"] = result.badge
        results.append(metrics)

    valid = [r for r in results if "ret_20d" in r and r["ret_20d"] is not None]
    valid.sort(key=lambda x: (x.get("ret_20d") or -999), reverse=True)
    return valid[:top_n] + [r for r in results if "error" in r]


def scan_all_etf_groups(top_n: int = 3) -> dict:
    """
    扫描全部 ETF 分组，每组取前 top_n
    日报里展示"各类 ETF 当前最强选手"
    """
    return {
        group: scan_etf_peer_group(group, top_n=top_n)
        for group in ETF_PEER_GROUPS
    }


def get_fund_performance_summary(fund_code: str, fund_name: str = "") -> dict:
    """
    获取公募基金关键指标摘要（近1月/3月/6月/1年回报 + 最大回撤）
    用于日报的"主动基金追踪"板块
    """
    from .data_source_layer import get_fund_nav_hist

    result = get_fund_nav_hist(fund_code, days=365)
    if not result.ok or result.data is None:
        return {"code": fund_code, "name": fund_name or fund_code, "error": result.warning}

    df = result.data
    nav = pd.to_numeric(df["nav"], errors="coerce").dropna()

    def _ret(n_days: int) -> float:
        if len(nav) < n_days:
            return None
        return round(float((nav.iloc[-1] / nav.iloc[-n_days] - 1) * 100), 2)

    peak = nav.expanding().max()
    max_dd = round(float(((nav / peak) - 1).min() * 100), 2) if len(nav) >= 5 else None

    vol = None
    if len(nav) >= 20:
        daily_ret = nav.pct_change().dropna()
        vol = round(float(daily_ret.tail(60).std() * np.sqrt(252) * 100), 1)

    return {
        "code": fund_code,
        "name": fund_name or fund_code,
        "nav": round(float(nav.iloc[-1]), 4),
        "ret_1m": _ret(21),
        "ret_3m": _ret(63),
        "ret_6m": _ret(126),
        "ret_1y": _ret(252),
        "max_dd_1y": max_dd,
        "vol_60d": vol,
        "data_badge": result.badge,
    }
