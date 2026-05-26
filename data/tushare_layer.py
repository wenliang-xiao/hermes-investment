"""
Tushare Pro 数据层
优先级：Tushare Pro（主力数据源）

配置 Token：
  config.py: TUSHARE_TOKEN = "your_token"
  或环境变量: TUSHARE_TOKEN=your_token

积分要求：
  - 基础行情/财务：120积分（注册即送）
  - 社融/宏观：120积分
  - 北向资金：2000积分
  - 全量财报：5000积分

Tushare 股票代码格式：600519.SH / 000001.SZ（6位+市场后缀）
"""

import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_ts_api = None


def _ts_init():
    global _ts_api
    if _ts_api is not None:
        return _ts_api
    try:
        import tushare as ts
        token = os.environ.get("TUSHARE_TOKEN", "")
        if not token:
            try:
                from investment_system import config as _cfg
                token = getattr(_cfg, "TUSHARE_TOKEN", "")
            except Exception:
                pass
        if not token:
            logger.warning("[Tushare] 未配置 TUSHARE_TOKEN，跳过Tushare。"
                           "在 config.py 设置 TUSHARE_TOKEN='your_token' 或设置同名环境变量")
            return None
        ts.set_token(token)
        _ts_api = ts.pro_api()
        logger.info("[Tushare] 初始化成功")
        return _ts_api
    except Exception as e:
        logger.warning("[Tushare] 初始化失败: %s", e)
        return None


def to_ts_code(symbol: str) -> str:
    s = str(symbol).zfill(6)
    if s.startswith("6") or s.startswith("5"):
        return f"{s}.SH"
    return f"{s}.SZ"


def get_stock_daily_ts(symbol: str, days: int = 365) -> pd.DataFrame:
    """获取个股日线（含PE/PB）。返回与 baostock 相同格式。"""
    pro = _ts_init()
    if pro is None:
        return pd.DataFrame()
    try:
        ts_code = to_ts_code(symbol)
        end_d = datetime.now().strftime("%Y%m%d")
        start_d = (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")

        df_price = pro.daily(ts_code=ts_code, start_date=start_d, end_date=end_d,
                             fields="ts_code,trade_date,open,high,low,close,vol,amount")
        df_basic = pro.daily_basic(ts_code=ts_code, start_date=start_d, end_date=end_d,
                                   fields="ts_code,trade_date,pe,pb,turnover_rate,volume_ratio,circ_mv")

        if df_price is None or df_price.empty:
            return pd.DataFrame()

        df_price = df_price.sort_values("trade_date")
        df_price["date"] = pd.to_datetime(df_price["trade_date"])
        df_price = df_price.rename(columns={"vol": "volume"})

        if df_basic is not None and not df_basic.empty:
            df_basic = df_basic.sort_values("trade_date")
            df_price = df_price.merge(
                df_basic[["trade_date", "pe", "pb", "turnover_rate", "circ_mv"]],
                on="trade_date", how="left"
            )
        else:
            df_price["pe"] = None
            df_price["pb"] = None

        df_price["symbol"] = symbol
        cols = ["date", "open", "high", "low", "close", "volume", "amount", "pe", "pb", "symbol"]
        return df_price[[c for c in cols if c in df_price.columns]]
    except Exception as e:
        logger.warning("[Tushare] get_stock_daily_ts %s 失败: %s", symbol, e)
        return pd.DataFrame()


def get_pe_history_ts(symbol: str, years: int = 5) -> pd.Series:
    """
    获取个股历史 PE-TTM（最多5年），用于百分位计算。
    Tushare daily_basic 返回完整历史PE。
    返回 pd.Series，index=date，values=pe
    """
    pro = _ts_init()
    if pro is None:
        return pd.Series(dtype=float)
    try:
        ts_code = to_ts_code(symbol)
        start_d = (datetime.now() - timedelta(days=years * 365 + 30)).strftime("%Y%m%d")
        end_d = datetime.now().strftime("%Y%m%d")
        df = pro.daily_basic(ts_code=ts_code, start_date=start_d, end_date=end_d,
                             fields="trade_date,pe")
        if df is None or df.empty:
            return pd.Series(dtype=float)
        df = df.dropna(subset=["pe"])
        df = df[df["pe"] > 0]
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        s = pd.Series(df["pe"].values, index=df["trade_date"])
        return s.sort_index()
    except Exception as e:
        logger.warning("[Tushare] get_pe_history_ts %s 失败: %s", symbol, e)
        return pd.Series(dtype=float)


def get_financial_report_ts(symbol: str) -> dict:
    """
    获取最新季度财务指标（ROE/营收增速/净利润增速/毛利率）。
    返回与 baostock get_financial_report 相同格式。
    """
    pro = _ts_init()
    if pro is None:
        return {}
    try:
        ts_code = to_ts_code(symbol)
        df = pro.fina_indicator(ts_code=ts_code,
                                fields="ts_code,end_date,roe,netprofit_margin,"
                                       "grossprofit_margin,revenue_yoy,netprofit_yoy")
        if df is None or df.empty:
            return {}
        df = df.sort_values("end_date", ascending=False)
        row = df.iloc[0]
        result = {}
        mapping = {
            "roe": "净资产收益率",
            "revenue_yoy": "营业收入同比增长率",
            "netprofit_yoy": "净利润同比增长率",
            "grossprofit_margin": "毛利率",
            "netprofit_margin": "净利率",
        }
        for ts_field, key in mapping.items():
            v = row.get(ts_field)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                result[key] = round(float(v), 2)
        return result
    except Exception as e:
        logger.warning("[Tushare] get_financial_report_ts %s 失败: %s", symbol, e)
        return {}


def get_financial_history_ts(symbol: str, quarters: int = 8) -> list:
    """
    获取多季度 ROE 趋势 + FCF（自由现金流）。
    FCF = 经营活动现金流净额 - 购建固定资产等资本支出。
    返回与 data_layer.get_financial_history 相同格式。
    """
    pro = _ts_init()
    if pro is None:
        return []
    try:
        ts_code = to_ts_code(symbol)
        df_ind = pro.fina_indicator(ts_code=ts_code,
                                    fields="ts_code,end_date,roe,roa,netprofit_margin")
        df_cf = pro.cashflow(ts_code=ts_code,
                             fields="ts_code,end_date,n_cashflow_act,c_pay_acq_const_fiolta")
        history = []
        if df_ind is not None and not df_ind.empty:
            df_ind = df_ind.sort_values("end_date", ascending=False).head(quarters)
            cf_dict = {}
            if df_cf is not None and not df_cf.empty:
                for _, r in df_cf.iterrows():
                    cf_dict[r["end_date"]] = r
            for _, row in df_ind.iterrows():
                ed = str(row.get("end_date", ""))
                roe_v = row.get("roe")
                entry = {
                    "period": ed,
                    "year": int(ed[:4]) if len(ed) >= 4 else None,
                    "quarter": {3: 1, 6: 2, 9: 3, 12: 4}.get(int(ed[4:6]) if len(ed) >= 6 else 12, 4),
                    "roe": round(float(roe_v), 2) if roe_v is not None and not (isinstance(roe_v, float) and np.isnan(roe_v)) else None,
                    "ocf": None, "fcf": None,
                }
                cf_row = cf_dict.get(ed)
                if cf_row is not None:
                    ocf = cf_row.get("n_cashflow_act")
                    capex = cf_row.get("c_pay_acq_const_fiolta")
                    if ocf is not None and not (isinstance(ocf, float) and np.isnan(ocf)):
                        entry["ocf"] = round(float(ocf) / 1e8, 2)
                        if capex is not None and not (isinstance(capex, float) and np.isnan(capex)):
                            entry["fcf"] = round((float(ocf) - float(capex)) / 1e8, 2)
                        else:
                            entry["fcf"] = entry["ocf"]
                history.append(entry)
        return history
    except Exception as e:
        logger.warning("[Tushare] get_financial_history_ts %s 失败: %s", symbol, e)
        return []


def get_macro_data_ts() -> dict:
    """
    获取宏观数据（CPI/PMI/M2/社融）。
    社融数据：Tushare sf_month 是最权威的免费来源。
    返回与 data_layer.get_macro_data 相同格式。
    """
    pro = _ts_init()
    if pro is None:
        return {}
    result = {}
    try:
        now = datetime.now()
        start_m = (now - timedelta(days=90)).strftime("%Y%m")
        end_m = now.strftime("%Y%m")

        try:
            df_sf = pro.sf_month(start_m=start_m, end_m=end_m,
                                 fields="month,inc_month,inc_cumval,stk_endval")
            if df_sf is not None and not df_sf.empty:
                df_sf = df_sf.sort_values("month", ascending=False)
                inc = df_sf["inc_month"].iloc[0]
                if inc is not None and not (isinstance(inc, float) and np.isnan(inc)):
                    result["social_financing_growth_abs"] = round(float(inc), 2)
        except Exception as e:
            logger.debug("[Tushare] sf_month 失败（可能需要更高积分）: %s", e)

        try:
            df_cpi = pro.cn_cpi(start_m=start_m, end_m=end_m,
                                fields="month,nt_val,nt_yoy")
            if df_cpi is not None and not df_cpi.empty:
                df_cpi = df_cpi.sort_values("month", ascending=False)
                cpi_yoy = df_cpi["nt_yoy"].iloc[0]
                if cpi_yoy is not None and not (isinstance(cpi_yoy, float) and np.isnan(cpi_yoy)):
                    result["cpi"] = round(float(cpi_yoy), 2)
        except Exception as e:
            logger.debug("[Tushare] cn_cpi 失败: %s", e)

        try:
            df_pmi = pro.cn_pmi(start_m=start_m, end_m=end_m,
                                fields="month,mfg_pmi")
            if df_pmi is not None and not df_pmi.empty:
                df_pmi = df_pmi.sort_values("month", ascending=False)
                pmi = df_pmi["mfg_pmi"].iloc[0]
                if pmi is not None and not (isinstance(pmi, float) and np.isnan(pmi)):
                    result["pmi"] = round(float(pmi), 2)
        except Exception as e:
            logger.debug("[Tushare] cn_pmi 失败: %s", e)

        try:
            df_m2 = pro.cn_m(start_m=start_m, end_m=end_m,
                             fields="month,m2,m2_yoy")
            if df_m2 is not None and not df_m2.empty:
                df_m2 = df_m2.sort_values("month", ascending=False)
                m2_yoy = df_m2["m2_yoy"].iloc[0]
                if m2_yoy is not None and not (isinstance(m2_yoy, float) and np.isnan(m2_yoy)):
                    result["m2_growth"] = round(float(m2_yoy), 2)
        except Exception as e:
            logger.debug("[Tushare] cn_m 失败: %s", e)

    except Exception as e:
        logger.warning("[Tushare] get_macro_data_ts 失败: %s", e)
    return result


def get_northbound_flow_ts() -> dict:
    """
    获取北向资金净流入（日度）。
    需要 2000 积分。基础积分仅返回空或报错，正常降级处理。
    返回与 data_layer.get_northbound_flow 相同格式。
    """
    pro = _ts_init()
    if pro is None:
        return {}
    try:
        start_d = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
        end_d = datetime.now().strftime("%Y%m%d")
        df = pro.moneyflow_hsgt(start_date=start_d, end_date=end_d,
                                fields="trade_date,hgt,sgt,north_money,south_money")
        if df is None or df.empty:
            return {}
        df = df.sort_values("trade_date", ascending=False)
        today_net = df["north_money"].iloc[0]
        flow_5d = df["north_money"].head(5).sum()
        flow_20d = df["north_money"].head(20).sum()

        from investment_system import config as _cfg
        cfg = _cfg.NORTHBOUND_CONFIG
        if today_net >= cfg["strong_inflow_daily"]:
            signal = "🟢 强力流入"
        elif today_net >= cfg["mild_inflow_daily"]:
            signal = "🟡 温和流入"
        elif today_net <= cfg["outflow_daily"]:
            signal = "🔴 明显流出"
        else:
            signal = "⚪ 中性"

        return {
            "today_net": round(float(today_net), 2),
            "5d_cumulative": round(float(flow_5d), 2),
            "20d_cumulative": round(float(flow_20d), 2),
            "signal": signal,
            "confirmation": "📊 Tushare历史数据",
            "data_ok": True,
            "note": "来源：Tushare moneyflow_hsgt（需2000积分）",
        }
    except Exception as e:
        logger.debug("[Tushare] get_northbound_flow_ts 失败（可能积分不足）: %s", e)
        return {}
