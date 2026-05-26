"""
JQData 数据层 — 聚宽 JQData API 封装
优先级：JQData（主）→ baostock（备）→ AKShare（兜底）

配置：在环境变量或 config.py 中设置：
  JQDATA_USER = "18813017039"
  JQDATA_PASS = "your_password"

注意（试用账号限制）：
  - 历史数据范围：前15个月~前3个月（正式账号才有05年至今）
  - 每日流量：100万条
  - 连接数：1个
"""

import os
import logging
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_jq_authed = False


def _jq_auth() -> bool:
    global _jq_authed
    if _jq_authed:
        return True
    try:
        from jqdatasdk import auth
        user = os.environ.get("JQDATA_USER", "")
        pwd = os.environ.get("JQDATA_PASS", "")
        if not user or not pwd:
            try:
                from investment_system import config as _cfg
                user = getattr(_cfg, "JQDATA_USER", "")
                pwd = getattr(_cfg, "JQDATA_PASS", "")
            except Exception:
                pass
        if not user or not pwd:
            logger.warning("[JQData] 未配置账号密码，跳过JQData。设置环境变量 JQDATA_USER / JQDATA_PASS")
            return False
        auth(user, pwd)
        _jq_authed = True
        logger.info("[JQData] 登录成功")
        return True
    except Exception as e:
        logger.warning("[JQData] 登录失败: %s", e)
        return False


def get_stock_daily_jq(symbol: str, days: int = 365) -> pd.DataFrame:
    """
    用 JQData 获取个股日线（含PE/PB）。
    返回与 baostock 版本相同格式的 DataFrame。
    """
    if not _jq_auth():
        return pd.DataFrame()
    try:
        from jqdatasdk import get_price, get_fundamentals, query, valuation
        jq_code = _to_jq_code(symbol)
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=days + 10)

        df_price = get_price(
            jq_code,
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            frequency="daily",
            fields=["open", "high", "low", "close", "volume", "money"],
        )
        if df_price is None or df_price.empty:
            return pd.DataFrame()
        df_price = df_price.reset_index()
        df_price.columns = [c.lower() for c in df_price.columns]
        df_price = df_price.rename(columns={"index": "date", "money": "amount"})

        df_val = get_fundamentals(
            query(valuation.code, valuation.day, valuation.pe_ratio, valuation.pb_ratio).filter(
                valuation.code == jq_code
            ),
            date=end_dt.strftime("%Y-%m-%d"),
        )
        if df_val is not None and not df_val.empty:
            last_pe = float(df_val["pe_ratio"].iloc[-1]) if "pe_ratio" in df_val.columns else None
            last_pb = float(df_val["pb_ratio"].iloc[-1]) if "pb_ratio" in df_val.columns else None
        else:
            last_pe = last_pb = None

        df_price["pe"] = last_pe
        df_price["pb"] = last_pb
        df_price["symbol"] = symbol
        df_price["date"] = pd.to_datetime(df_price["date"])
        return df_price[["date", "open", "high", "low", "close", "volume", "amount", "pe", "pb", "symbol"]]
    except Exception as e:
        logger.warning("[JQData] get_stock_daily_jq %s 失败: %s", symbol, e)
        return pd.DataFrame()


def get_pe_history_jq(symbol: str, days: int = 400) -> pd.Series:
    """
    用 JQData 获取历史 PE-TTM，用于百分位计算。
    试用账号限制：只有近15个月数据。
    返回 pd.Series，index=date，values=pe。
    """
    if not _jq_auth():
        return pd.Series(dtype=float)
    try:
        from jqdatasdk import get_fundamentals_continuously, query, valuation
        jq_code = _to_jq_code(symbol)
        end_dt = datetime.now() - timedelta(days=92)
        start_dt = end_dt - timedelta(days=min(days, 400))

        df = get_fundamentals_continuously(
            query(valuation.code, valuation.pe_ratio),
            start_date=start_dt.strftime("%Y-%m-%d"),
            end_date=end_dt.strftime("%Y-%m-%d"),
            panel=False,
        )
        if df is None or df.empty:
            return pd.Series(dtype=float)
        df = df[df["code"] == jq_code]
        df = df.dropna(subset=["pe_ratio"])
        df = df[df["pe_ratio"] > 0]
        s = pd.Series(df["pe_ratio"].values, index=pd.to_datetime(df.index if "date" not in df.columns else df["day"]))
        return s
    except Exception as e:
        logger.warning("[JQData] get_pe_history_jq %s 失败: %s", symbol, e)
        return pd.Series(dtype=float)


def get_financial_report_jq(symbol: str) -> dict:
    """
    用 JQData 获取最新季度财务指标（ROE/营收增速/利润增速/毛利率）。
    返回与 baostock get_financial_report 相同格式的 dict。
    """
    if not _jq_auth():
        return {}
    try:
        from jqdatasdk import get_fundamentals, query, indicator, income
        jq_code = _to_jq_code(symbol)
        df = get_fundamentals(
            query(
                indicator.code,
                indicator.roe,
                indicator.inc_revenue_year_on_year,
                indicator.inc_net_profit_year_on_year,
                indicator.gross_profit_margin,
                indicator.net_profit_margin,
                indicator.ocf_to_operating_profit,
            ).filter(indicator.code == jq_code),
        )
        if df is None or df.empty:
            return {}
        row = df.iloc[-1]
        result = {}

        def _safe(key, col, mult=1.0):
            v = row.get(col)
            if v is not None and not (isinstance(v, float) and np.isnan(v)):
                result[key] = round(float(v) * mult, 2)

        _safe("净资产收益率", "roe")
        _safe("营业收入同比增长率", "inc_revenue_year_on_year")
        _safe("净利润同比增长率", "inc_net_profit_year_on_year")
        _safe("毛利率", "gross_profit_margin")
        _safe("净利率", "net_profit_margin")
        return result
    except Exception as e:
        logger.warning("[JQData] get_financial_report_jq %s 失败: %s", symbol, e)
        return {}


def get_financial_history_jq(symbol: str, quarters: int = 8) -> list:
    """
    用 JQData 获取多季度 ROE 趋势 + FCF。
    返回与 data_layer.get_financial_history 相同格式的 list。
    """
    if not _jq_auth():
        return []
    try:
        from jqdatasdk import get_fundamentals, query, indicator, cash_flow
        jq_code = _to_jq_code(symbol)

        df_ind = get_fundamentals(
            query(indicator.code, indicator.roe).filter(indicator.code == jq_code),
            statDate="all",
        )
        df_cf = get_fundamentals(
            query(
                cash_flow.code,
                cash_flow.statDate,
                cash_flow.net_operate_cash_flow,
                cash_flow.goods_sale_and_service_render_cash,
            ).filter(cash_flow.code == jq_code),
            statDate="all",
        )
        history = []
        if df_ind is not None and not df_ind.empty:
            df_ind = df_ind.sort_values("statDate", ascending=False).head(quarters)
            for _, row in df_ind.iterrows():
                stat = str(row.get("statDate", ""))
                roe_val = row.get("roe")
                entry = {
                    "period": stat,
                    "year": int(stat[:4]) if len(stat) >= 4 else None,
                    "quarter": _stat_to_quarter(stat),
                    "roe": round(float(roe_val), 2) if roe_val and not np.isnan(float(roe_val)) else None,
                    "ocf": None, "fcf": None,
                }
                if df_cf is not None and not df_cf.empty:
                    cf_row = df_cf[df_cf["statDate"] == stat]
                    if not cf_row.empty:
                        ocf = cf_row["net_operate_cash_flow"].iloc[0]
                        if ocf is not None and not np.isnan(float(ocf)):
                            entry["ocf"] = round(float(ocf) / 1e8, 2)
                            entry["fcf"] = entry["ocf"]
                history.append(entry)
        return history
    except Exception as e:
        logger.warning("[JQData] get_financial_history_jq %s 失败: %s", symbol, e)
        return []


def get_social_financing_jq() -> Optional[float]:
    """
    用 JQData 获取最新月度社融增速（同比），用于信用判断。
    返回浮点数（如 8.5 表示同比增长8.5%）。
    """
    if not _jq_auth():
        return None
    try:
        from jqdatasdk import macro
        df = macro.MAC_CHINA_MONEY_SUPPLY()
        if df is None or df.empty:
            return None
        df = df.sort_values("stat_month", ascending=False)
        val = df["m2_rate_of_growth"].iloc[0]
        if val is not None and not (isinstance(val, float) and np.isnan(val)):
            return round(float(val), 2)
        return None
    except Exception as e:
        logger.warning("[JQData] get_social_financing_jq 失败: %s", e)
        return None


def get_macro_data_jq() -> dict:
    """
    用 JQData 获取完整宏观数据（CPI/PMI/M2/社融）。
    返回与 data_layer.get_macro_data 相同格式的 dict。
    """
    if not _jq_auth():
        return {}
    result = {}
    try:
        from jqdatasdk import macro

        cpi_df = macro.MAC_CHINA_CPI_YEARLY()
        if cpi_df is not None and not cpi_df.empty:
            cpi_df = cpi_df.sort_values("date", ascending=False)
            v = cpi_df["value"].iloc[0]
            if v is not None:
                result["cpi"] = round(float(v) - 100, 2)

        pmi_df = macro.MAC_CHINA_PMI_MANU()
        if pmi_df is not None and not pmi_df.empty:
            pmi_df = pmi_df.sort_values("date", ascending=False)
            v = pmi_df["pmi"].iloc[0]
            if v is not None:
                result["pmi"] = round(float(v), 2)

        m2_df = macro.MAC_CHINA_MONEY_SUPPLY()
        if m2_df is not None and not m2_df.empty:
            m2_df = m2_df.sort_values("stat_month", ascending=False)
            m2_rate = m2_df["m2_rate_of_growth"].iloc[0]
            sf_rate = m2_df.get("social_financing_rate_of_growth", pd.Series()).iloc[0] if "social_financing_rate_of_growth" in m2_df.columns else None
            if m2_rate is not None:
                result["m2_growth"] = round(float(m2_rate), 2)
            if sf_rate is not None and not (isinstance(sf_rate, float) and np.isnan(sf_rate)):
                result["social_financing_growth"] = round(float(sf_rate), 2)
    except Exception as e:
        logger.warning("[JQData] get_macro_data_jq 失败: %s", e)
    return result


def _to_jq_code(symbol: str) -> str:
    s = str(symbol).zfill(6)
    if s.startswith("6"):
        return f"{s}.XSHG"
    elif s.startswith(("0", "3")):
        return f"{s}.XSHE"
    elif s.startswith("5"):
        return f"{s}.XSHG"
    elif s.startswith("1"):
        return f"{s}.XSHE"
    return f"{s}.XSHG"


def _stat_to_quarter(stat: str) -> int:
    if not stat or len(stat) < 6:
        return 4
    month = int(stat[4:6]) if len(stat) >= 6 else 12
    return {3: 1, 6: 2, 9: 3, 12: 4}.get(month, 4)
