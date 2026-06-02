"""
Data Layer — 统一数据获取
优先级：Tushare Pro（主力）→ baostock（免费安全网）→ AKShare（宏观月度兜底）

配置 Tushare：在 config.py 中设置 TUSHARE_TOKEN
或设置同名环境变量
"""
import baostock as bs
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timedelta
from investment_system import config
from investment_system.domain.stock_universe import ALL_CORE_STOCKS, INDEX_DATA

logger = logging.getLogger(__name__)

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
def _get_stock_daily_akshare(symbol: str, days: int) -> pd.DataFrame:
    """baostock不可达时的AKShare回退（无PE/PB，降级运行）"""
    try:
        import akshare as ak
        end_d = datetime.now().strftime("%Y%m%d")
        start_d = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=symbol.zfill(6),
            period="daily",
            start_date=start_d,
            end_date=end_d,
            adjust="qfq",
        )
        if df is None or df.empty:
            return pd.DataFrame()
        col_map = {
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
        }
        df = df.rename(columns=col_map)
        df["date"] = pd.to_datetime(df["date"])
        df["pe"] = None
        df["pb"] = None
        df["symbol"] = symbol
        return df[["date", "open", "high", "low", "close", "volume", "amount", "pe", "pb", "symbol"]]
    except Exception as e:
        print(f"[data] {symbol} AKShare回退失败: {e}")
        return pd.DataFrame()


def get_stock_daily(symbol: str, days: int = 365) -> pd.DataFrame:
    """获取个股日线数据（含PE/PB）。Tushare→baostock→AKShare。"""
    try:
        from investment_system.data.tushare_layer import get_stock_daily_ts
        df = get_stock_daily_ts(symbol, days)
        if not df.empty:
            return df
    except Exception:
        pass
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
            raise RuntimeError(f"baostock error_code={rs.error_code}")

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
            except Exception:
                continue

        if not rows:
            raise RuntimeError("baostock returned empty rows")
        df = pd.DataFrame(rows)
        df["symbol"] = symbol
        return df
    except Exception as e:
        print(f"[data] {symbol} baostock失败({e})，切AKShare回退")
        return _get_stock_daily_akshare(symbol, days)


# ═══════════════════════════════════════════
# 3. 基本面数据（baostock）
# ═══════════════════════════════════════════
def get_financial_report(symbol: str) -> dict:
    """获取财务指标：ROE, 营收增速, 利润增速, 毛利率。Tushare→baostock。"""
    try:
        from investment_system.data.tushare_layer import get_financial_report_ts
        result = get_financial_report_ts(symbol)
        if result:
            return result
    except Exception:
        pass
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


def get_financial_history(symbol: str, quarters: int = 8) -> list:
    """
    获取多季度财务历史：ROE趋势 + FCF 计算所需数据
    返回按时间倒序的季度列表，用于计算 ROE 趋势和 FCF
    Tushare→baostock
    """
    _bs_login()
    bs_code = _bs_code(symbol)
    history = []
    current_year = datetime.now().year

    for year_off in range(0, 3):
        year = current_year - year_off
        for quarter in [4, 3, 2, 1]:
            if len(history) >= quarters:
                break
            try:
                roe_val = None
                rs_d = bs.query_dupont_data(code=bs_code, year=year, quarter=quarter)
                if rs_d.error_code == "0":
                    while rs_d.next():
                        r = rs_d.get_row_data()
                        try:
                            roe_raw = r[5] if len(r) > 5 else ""
                            if roe_raw and str(roe_raw).strip():
                                roe_val = float(roe_raw) * 100
                        except Exception:
                            pass

                ocf = capex = None
                rs_cf = bs.query_cash_flow_data(code=bs_code, year=year, quarter=quarter)
                if rs_cf.error_code == "0":
                    fields = rs_cf.fields
                    while rs_cf.next():
                        r = rs_cf.get_row_data()
                        try:
                            row = dict(zip(fields, r))
                            ocf_raw = row.get("netCashFlowsFromOperatingActivities") or \
                                      row.get("netCashFlowsOperating", "")
                            inv_raw = row.get("cashFlowsFromInvestingActivities", "")
                            if ocf_raw and str(ocf_raw).strip():
                                ocf = float(ocf_raw)
                            if inv_raw and str(inv_raw).strip():
                                capex = float(inv_raw)
                        except Exception:
                            pass

                fcf = None
                if ocf is not None and capex is not None:
                    fcf = round(ocf + capex, 2)

                if roe_val is not None or fcf is not None:
                    history.append({
                        "year": year, "quarter": quarter,
                        "period": f"{year}Q{quarter}",
                        "roe": round(roe_val, 2) if roe_val is not None else None,
                        "ocf": round(ocf / 1e8, 2) if ocf is not None else None,
                        "fcf": round(fcf / 1e8, 2) if fcf is not None else None,
                    })
            except Exception:
                continue
        if len(history) >= quarters:
            break

    return history


def get_pe_history(symbol: str, years: int = 5) -> pd.Series:
    """
    获取个股 PE-TTM 历史序列，用于计算历史百分位。
    Tushare（5年完整）→ baostock（从日线重算）。
    返回 pd.Series，index=date，values=pe
    """
    try:
        from investment_system.data.tushare_layer import get_pe_history_ts
        s = get_pe_history_ts(symbol, years=years)
        if len(s) >= 60:
            return s
    except Exception:
        pass
    _bs_login()
    start = (datetime.now() - timedelta(days=years * 365 + 30)).strftime("%Y-%m-%d")
    end = datetime.now().strftime("%Y-%m-%d")
    try:
        rs = bs.query_history_k_data_plus(
            _bs_code(symbol),
            "date,peTTM",
            start_date=start, end_date=end,
            frequency="w", adjustflag="3",
        )
        if rs.error_code != "0":
            return pd.Series(dtype=float)
        rows = []
        while rs.next():
            r = rs.get_row_data()
            try:
                if r[1] and str(r[1]).strip():
                    pe = float(r[1])
                    if 0 < pe < 2000:
                        rows.append((r[0], pe))
            except Exception:
                continue
        if not rows:
            return pd.Series(dtype=float)
        s = pd.Series(dict(rows))
        s.index = pd.to_datetime(s.index)
        return s.dropna()
    except Exception as e:
        print(f"[data] {symbol} PE历史获取失败: {e}")
        return pd.Series(dtype=float)


def calc_pe_percentile(symbol: str, current_pe: float, years: int = 5) -> dict:
    """
    计算当前 PE 在历史中的百分位。
    返回 {"pe": float, "percentile": float, "level": str, "history_len": int}
    """
    hist = get_pe_history(symbol, years)
    if hist.empty or current_pe <= 0:
        return {"pe": current_pe, "percentile": None, "level": "数据不足", "history_len": 0}
    pct = float((hist < current_pe).sum() / len(hist) * 100)
    if pct <= 20:
        level = "🟢历史低位(<20%分位)"
    elif pct <= 40:
        level = "🟡偏低(20-40%分位)"
    elif pct <= 60:
        level = "⚪中性(40-60%分位)"
    elif pct <= 80:
        level = "🟠偏高(60-80%分位)"
    else:
        level = "🔴历史高位(>80%分位)"
    return {
        "pe": round(current_pe, 1),
        "percentile": round(pct, 1),
        "level": level,
        "history_len": len(hist),
    }


def get_volume_signal(symbol: str, window: int = 20) -> dict:
    """
    成交量放量/缩量分析：
    返回 {"ratio": float, "signal": str, "vol_20d_avg": float}
    """
    try:
        df = get_stock_daily(symbol, days=60)
        if df.empty or len(df) < window + 2:
            return {}
        vols = df["volume"].dropna()
        if len(vols) < window + 1:
            return {}
        ma = float(vols.iloc[-window - 1:-1].mean())
        curr = float(vols.iloc[-1])
        if ma <= 0:
            return {}
        ratio = round(curr / ma, 2)
        if ratio >= 2.0:
            signal = "🔥大幅放量(≥2倍)"
        elif ratio >= 1.5:
            signal = "📈温和放量(1.5-2倍)"
        elif ratio <= 0.5:
            signal = "❄️明显缩量(<0.5倍)"
        elif ratio <= 0.7:
            signal = "📉轻微缩量(0.5-0.7倍)"
        else:
            signal = "➖量能平稳"
        return {"ratio": ratio, "signal": signal, "vol_20d_avg": round(ma / 1e6, 1)}
    except Exception:
        return {}


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
    """获取宏观数据（CPI/PMI/M2/社融）。Tushare→AKShare→缓存兜底。"""
    try:
        from investment_system.data.tushare_layer import get_macro_data_ts
        ts_result = get_macro_data_ts()
        if ts_result.get("cpi") is not None and ts_result.get("pmi") is not None:
            return ts_result
    except Exception:
        pass
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
        "cpi":       1.5,    "cpi_trend": "flat", "cpi_prev": 1.5, "cpi_delta": 0.0, "cpi_momentum_3m": 0.0,
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
            result["cpi_prev"] = prev
            result["cpi_delta"] = round(result["cpi"] - prev, 2)
            result["cpi_trend"] = "up" if result["cpi_delta"] > 0.05 else ("down" if result["cpi_delta"] < -0.05 else "flat")
            result["cpi_date"] = str(cpi_row["日期"])
            # 3-month momentum: try iloc[-4] (3 months ago in monthly data)
            try:
                rows = cpi_df.dropna(subset=["今值"])
                if len(rows) >= 4:
                    cpi_3m = float(rows.iloc[-4]["今值"])
                    result["cpi_momentum_3m"] = round(result["cpi"] - cpi_3m, 2)
            except Exception:
                result["cpi_momentum_3m"] = result["cpi_delta"]  # fallback to 1-month
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

        try:
            sf = ak.macro_china_shrzgm()
            if not sf.empty:
                sf_row = sf.dropna().iloc[-1]
                sf_val = float(sf_row.iloc[2])
                sf_date = str(sf_row.iloc[0])
                if abs(sf_val) <= 100:
                    result["social_financing_growth"] = sf_val
                    result["social_financing_date"] = sf_date
                else:
                    result["social_financing_growth_abs_亿"] = sf_val
                    result["social_financing_date"] = sf_date
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
    获取北向资金净流入。Tushare（需2000积分）→ AKShare历史→ 缓存。
    2024-08-19起交易所停止每日披露，AKShare历史数据仅供参考。
    """
    try:
        from investment_system.data.tushare_layer import get_northbound_flow_ts
        ts_result = get_northbound_flow_ts()
        if ts_result.get("data_ok"):
            return ts_result
    except Exception:
        pass
    from investment_system import config as _cfg
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
        from datetime import date as _date

        # 2024-08-19起沪深交易所停止披露每日北向资金数据，改为月度汇总
        # 使用 stock_hsgt_hist_em 获取历史净流入（旧接口已全部移除）
        DATA_STOP_DATE = "2024-08-19"
        today_str = datetime.now().strftime("%Y-%m-%d")
        if today_str >= DATA_STOP_DATE:
            result["note"] = (
                f"⚠️ 交易所已于{DATA_STOP_DATE}停止披露每日北向资金数据，"
                "改为月度汇总。当前数据为最后可用历史值，不代表今日实际情况。"
            )

        hist_fn = getattr(ak, "stock_hsgt_hist_em", None)
        if hist_fn is None:
            raise AttributeError("AKShare stock_hsgt_hist_em 不存在，请升级akshare>=1.14")

        df_hist = None
        for attempt in range(3):
            try:
                df_hist = hist_fn(symbol="北向资金")
                if df_hist is not None and not df_hist.empty:
                    break
                time.sleep(1)
            except Exception as e:
                print(f"[data_layer] AKShare北向资金第{attempt+1}次失败: {str(e)[:60]}")
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                else:
                    raise
        if df_hist is None or df_hist.empty:
            result["note"] = "stock_hsgt_hist_em 返回空数据"
            return result

        date_col = df_hist.columns[0]
        flow_col = next(
            (c for c in df_hist.columns if "净买" in str(c) or "净流" in str(c) or "流入" in str(c)),
            df_hist.columns[1]
        )

        df_hist[flow_col] = pd.to_numeric(df_hist[flow_col], errors="coerce")
        df_hist = df_hist.dropna(subset=[flow_col]).tail(25)

        today_net = round(float(df_hist[flow_col].iloc[-1]), 2)
        flow_5d = round(float(df_hist[flow_col].tail(5).sum()), 2)
        flow_20d = round(float(df_hist[flow_col].tail(20).sum()), 2)

        # 以下字段替代原沪深股通分拆（因为历史函数已移除，合计即可）
        sh_mock = df_hist[[flow_col]].copy()
        sz_mock = sh_mock.copy()
        sh_mock.columns = ["value"]; sz_mock.columns = ["value"]
        sz_mock["value"] = 0  # 历史接口只有合计，split已无意义

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
