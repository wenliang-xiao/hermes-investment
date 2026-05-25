"""
Data Layer — 统一数据获取
主数据源: baostock（本地稳定，A股全量数据，不含HTTP依赖）
辅助: AKShare（重试机制+超时保护，用于补充数据）
"""
import baostock as bs
import pandas as pd
import numpy as np
import time
from datetime import datetime, timedelta
from . import config
from .stock_universe import ALL_CORE_STOCKS, INDEX_DATA

# ─── Baostock 连接管理 ───
_bs_logged_in = False

def _bs_login():
    global _bs_logged_in
    if not _bs_logged_in:
        lg = bs.login()
        if lg.error_code == "0":
            _bs_logged_in = True
        else:
            print(f"[data] baostock login failed: {lg.error_msg}")

def _bs_code(symbol: str) -> str:
    """转换为baostock代码: sz.300502 / sh.600519"""
    sym = symbol.zfill(6)
    if sym.startswith("6"):
        return f"sh.{sym}"
    elif sym.startswith("0") or sym.startswith("3"):
        return f"sz.{sym}"
    else:
        return f"sz.{sym}"


# ═══════════════════════════════════════════
# 1. 股票信息（baostock）
# ═══════════════════════════════════════════
def get_stock_info(symbol: str) -> dict:
    """获取个股基础信息：名称、上市日期等"""
    _bs_login()
    try:
        rs = bs.query_stock_basic(code=_bs_code(symbol))
        if rs.error_code == "0":
            while rs.next():
                r = rs.get_row_data()
                return {"name": r[1], "list_date": r[2], "status": r[4]}
    except:
        pass
    return {"name": symbol}


def get_all_stocks() -> dict:
    """获取预定义股票池名称"""
    result = {}
    for sym in ALL_CORE_STOCKS:
        try:
            info = get_stock_info(sym)
            result[sym] = info
        except:
            pass
    return result


def get_stock_codes() -> list:
    return ALL_CORE_STOCKS[:]


# ═══════════════════════════════════════════
# 2. 个股日线行情（baostock）
# ═══════════════════════════════════════════
def get_stock_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """获取个股日线数据，含PE/PB"""
    _bs_login()
    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")

    try:
        rs = bs.query_history_k_data_plus(
            _bs_code(symbol),
            "date,open,high,low,close,volume,amount,peTTM,pbMRQ",
            start_date=start, end_date=end,
            frequency="d", adjustflag="2")
        if rs.error_code != "0":
            return pd.DataFrame()

        rows = []
        while rs.next():
            r = rs.get_row_data()
            try:
                rows.append({
                    "date": pd.to_datetime(r[0]),
                    "open": float(r[1]), "high": float(r[2]),
                    "low": float(r[3]), "close": float(r[4]),
                    "volume": float(r[5]), "amount": float(r[6]),
                    "pe": float(r[7]) if r[7] and r[7] != "" else None,
                    "pb": float(r[8]) if r[8] and r[8] != "" else None,
                })
            except:
                continue

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["symbol"] = symbol
        return df
    except Exception as e:
        print(f"[data] {symbol} 行情错误: {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════
# 3. 基本面数据（baostock）
# ═══════════════════════════════════════════
def get_financial_report(symbol: str) -> dict:
    """获取财务指标：ROE, 营收增速, 利润增速, 毛利率, 净利率"""
    _bs_login()
    bs_code = _bs_code(symbol)
    result = {}

    # 增长数据（ROE、营收增速、利润增速 — 转换为百分比）
    for year_off in [1, 2]:
        for quarter in [4, 2]:
            try:
                rs = bs.query_growth_data(code=bs_code,
                    year=datetime.now().year - year_off, quarter=quarter)
                if rs.error_code != "0":
                    continue
                while rs.next():
                    r = rs.get_row_data()
                    for idx, key in [(3, "净资产收益率"), (4, "营业收入同比增长率"), (5, "净利润同比增长率")]:
                        try:
                            if len(r) > idx and r[idx] and str(r[idx]).strip() != "":
                                v = float(r[idx])
                                if not np.isnan(v) and key not in result:
                                    # baostock 返回十进制小数 (0.13=13%)，转换为百分比
                                    result[key] = abs(v) * 100
                        except:
                            pass
                if result:
                    break
            except:
                continue
        if result:
            break

    # 杜邦指标（毛利率、净利率、EPS经营现金流）
    for year_off in [1, 2]:
        for quarter in [4, 2]:
            try:
                rs = bs.query_dupont_data(code=bs_code,
                    year=datetime.now().year - year_off, quarter=quarter)
                if rs.error_code != "0":
                    continue
                while rs.next():
                    r = rs.get_row_data()
                    for idx, key in [(4, "毛利率"), (5, "净利率")]:
                        try:
                            if len(r) > idx and r[idx] and str(r[idx]).strip() != "":
                                v = float(r[idx])
                                if not np.isnan(v) and key not in result:
                                    result[key] = abs(v) * 100
                        except:
                            pass
                    # 每股经营现金流绝对值不乘100
                    try:
                        if len(r) > 7 and r[7] and str(r[7]).strip() != "":
                            ocps = float(r[7])
                            if not np.isnan(ocps) and "每股经营现金流" not in result:
                                result["每股经营现金流"] = abs(ocps)
                    except:
                        pass
                break
            except:
                continue

    return result


# ═══════════════════════════════════════════
# 4. 指数行情（baostock）
# ═══════════════════════════════════════════
def get_index_data(symbol="sh000001", days=120) -> pd.DataFrame:
    """获取指数数据"""
    _bs_login()

    bs_index_map = {"sh000001": "sh.000001", "sz399001": "sz.399001",
                    "sz399006": "sz.399006"}
    bs_code = bs_index_map.get(symbol, "sh.000001")

    end = datetime.now().strftime("%Y-%m-%d")
    start = (datetime.now() - timedelta(days=days + 10)).strftime("%Y-%m-%d")

    try:
        rs = bs.query_history_k_data_plus(
            bs_code, "date,close,volume",
            start_date=start, end_date=end, frequency="d", adjustflag="2")
        rows = []
        while rs.next():
            r = rs.get_row_data()
            try:
                rows.append({"date": pd.to_datetime(r[0]), "close": float(r[1]),
                             "volume": float(r[2]) if r[2] and r[2] != "" else 0})
            except:
                continue
        if rows:
            return pd.DataFrame(rows)
    except:
        pass
    return pd.DataFrame()


# ═══════════════════════════════════════════
# 5. 宏观经济数据（AKShare不可用时的默认值）
# ═══════════════════════════════════════════
def get_macro_data() -> dict:
    """获取宏观数据（默认值，AKShare补充作为可选升级）
    
    宏观数据（CPI/PMI/M2）月频更新，不影响日内决策。
    使用合理默认值，AKShare服务可用时会覆盖。
    """
    import json, os
    cache_file = os.path.join(os.path.dirname(__file__), "data", "macro_raw_cache.json")
    
    # 先尝试缓存
    if os.path.exists(cache_file):
        try:
            age = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_file))).total_seconds()
            if age < 86400:  # 24h缓存
                with open(cache_file) as f:
                    cached = json.load(f)
                # 兼容旧格式（被 macro_engine 污染的嵌套结构）
                if "macro_data" in cached and isinstance(cached.get("macro_data"), dict):
                    inner = cached["macro_data"]
                    if "cpi" in inner:
                        return cached  # 已经是 macro_engine 格式，继续用
                # 标准 flat 格式
                if "cpi" in cached:
                    return cached
        except: pass
    
    # 默认值
    result = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cpi":       1.5,    "cpi_trend": "flat",
        "pmi":       50.3,   "pmi_trend": "flat",
        "m2":        315.0,  "m2_growth": 7.2,
        "shibor":    1.75,   "shibor_10y": 2.85,
        "cny_usd":   7.25,
    }
    
    # 尝试获取AKShare真实数据
    try:
        import akshare as ak
        
        # CPI — col: 商品, 日期, 今值, 预测值, 前值
        try:
            cpi_df = ak.macro_china_cpi_monthly()
            cpi_row = cpi_df.dropna(subset=["今值"]).iloc[-1]
            result["cpi"] = float(cpi_row["今值"])
            prev = float(cpi_row.get("前值", 0) or 0)
            result["cpi_trend"] = "up" if result["cpi"] > prev else ("down" if result["cpi"] < prev else "flat")
            result["cpi_date"] = str(cpi_row["日期"])
        except Exception as e:
            print(f"  [cpi] {e}")
        
        # PMI — 制造业-指数 (latest at row 0)
        try:
            pmi_df = ak.macro_china_pmi()
            pmi_row = pmi_df.dropna(subset=["制造业-指数"]).iloc[0]
            result["pmi"] = float(pmi_row["制造业-指数"])
            result["pmi_date"] = str(pmi_row["月份"])
            if len(pmi_df) >= 2:
                prev_pmi = float(pmi_df.iloc[1]["制造业-指数"])
                result["pmi_trend"] = "up" if result["pmi"] > prev_pmi else ("down" if result["pmi"] < prev_pmi else "flat")
        except Exception as e:
            print(f"  [pmi] {e}")
        
        # Shibor
        try:
            sh = ak.rate_interbank(market="上海银行间同业拆放利率",
                                   symbol="Shibor人民币", indicator="隔夜")
            result["shibor"] = float(sh.iloc[-1, 1])
        except: pass
            
        # M2
        try:
            m2 = ak.macro_china_m2_supply()
            m2_row = m2.dropna().iloc[-1]
            result["m2_growth"] = float(m2_row.iloc[2])
            result["m2"] = float(m2_row.iloc[1])
        except: pass
            
    except ImportError:
        print("  AKShare未安装，使用默认宏观数据")
    except Exception as e:
        print(f"  AKShare数据获取失败: {e}")
    
    # 写缓存
    try:
        with open(cache_file, "w") as f:
            json.dump(result, f)
    except: pass
    
    return result


# ─── 市场概况（纯baostock，无AKShare依赖） ───
_market_cache = None
_market_cache_time = 0

def get_market_overview() -> dict:
    """市场概况（baostock指数数据）"""
    global _market_cache, _market_cache_time
    if _market_cache and (time.time() - _market_cache_time) < 600:
        return _market_cache

    result = {}
    try:
        idx = get_index_data("sh000001", 5)
        if not idx.empty and len(idx) >= 2:
            curr = float(idx.iloc[-1]["close"])
            prev = float(idx.iloc[-2]["close"])
            result["sh"] = curr
            result["sh_chg"] = round((curr - prev) / prev * 100, 2)
    except: pass
    try:
        sz = get_index_data("sz399001", 2)
        if not sz.empty:
            result["sz"] = float(sz.iloc[-1]["close"])
    except: pass
    try:
        cy = get_index_data("sz399006", 2)
        if not cy.empty:
            result["cy"] = float(cy.iloc[-1]["close"])
    except: pass

    _market_cache = result
    _market_cache_time = time.time()
    return result


# ═══════════════════════════════════════════
# 6. 板块热力（AKShare，重试保护）
# ═══════════════════════════════════════════
def get_sector_hotmap() -> pd.DataFrame:
    """行业板块热力图（需要AKShare环境）"""
    try:
        import akshare as ak
        df = ak.stock_board_industry_name_em()
        if not df.empty:
            df.columns = [str(c).strip() for c in df.columns]
            df = df.sort_values("涨跌幅", ascending=False).head(10)
            return df
    except:
        pass
    return pd.DataFrame()


def get_concept_hotmap() -> pd.DataFrame:
    """概念板块热力图（需要AKShare环境）"""
    try:
        import akshare as ak
        df = ak.stock_board_concept_name_em()
        if not df.empty:
            df.columns = [str(c).strip() for c in df.columns]
            df = df.sort_values("涨跌幅", ascending=False).head(10)
            return df
    except:
        pass
    return pd.DataFrame()


# ═══════════════════════════════════════════
# 7. 北向资金信号（AKShare，LDS双门第三门）
# ═══════════════════════════════════════════

_northbound_cache = None
_northbound_cache_time = 0
_NORTHBOUND_TTL = 3600

def get_northbound_flow() -> dict:
    """
    获取北向资金（沪股通+深股通）日度净流入数据
    返回今日净流入、5日累计、20日累计及信号判断
    数据源：AKShare stock_em_hsgt_north_net_flow_in_em
    """
    from . import config as _cfg
    global _northbound_cache, _northbound_cache_time

    if _northbound_cache and (time.time() - _northbound_cache_time) < _NORTHBOUND_TTL:
        return _northbound_cache

    result = {
        "today_net": None,
        "5d_cumulative": None,
        "20d_cumulative": None,
        "signal": "⚪ 数据不可用",
        "confirmation": "⚪ 未知",
        "data_ok": False,
        "note": "",
    }

    try:
        import akshare as ak

        sh = ak.stock_em_hsgt_north_net_flow_in_em(symbol="沪股通")
        sz = ak.stock_em_hsgt_north_net_flow_in_em(symbol="深股通")

        if sh.empty or sz.empty:
            result["note"] = "AKShare返回空数据"
            return result

        col = sh.columns[1]
        today_sh = float(sh.iloc[-1][col]) / 1e8
        today_sz = float(sz.iloc[-1][col]) / 1e8
        today_net = round(today_sh + today_sz, 2)

        flow_5d = round(
            sh[col].tail(5).astype(float).sum() / 1e8 +
            sz[col].tail(5).astype(float).sum() / 1e8,
            2
        )
        flow_20d = round(
            sh[col].tail(20).astype(float).sum() / 1e8 +
            sz[col].tail(20).astype(float).sum() / 1e8,
            2
        )

        cfg = _cfg.NORTHBOUND_CONFIG
        if today_net >= cfg["strong_inflow_daily"]:
            signal = "🟢 强力流入"
        elif today_net >= cfg["mild_inflow_daily"]:
            signal = "🟡 温和流入"
        elif today_net <= cfg["outflow_daily"]:
            signal = "🔴 明显流出"
        else:
            signal = "⚪ 中性"

        if flow_5d >= cfg["strong_5d_cumulative"]:
            confirmation = "✅ 5日趋势性流入，确认买入信号"
        elif flow_5d <= cfg["weak_5d_cumulative"]:
            confirmation = "❌ 5日趋势性流出，谨慎"
        else:
            confirmation = "⚪ 5日无明显趋势"

        result.update({
            "today_net": today_net,
            "5d_cumulative": flow_5d,
            "20d_cumulative": flow_20d,
            "signal": signal,
            "confirmation": confirmation,
            "data_ok": True,
        })

    except Exception as e:
        result["note"] = f"AKShare获取失败: {str(e)[:80]}"

    _northbound_cache = result
    _northbound_cache_time = time.time()
    return result
