"""
蜻蜓数据源 --- 中信建投证券 Skill 广场 API 封装

CSC (China Securities / 中信建投) Skill Hub API Wrapper.

数据更新频率：财报数据 T+2~3h，行业排名日频
覆盖范围：A 股全量 ~5000 只
鉴权方式：X-API-Key + X-Calling-Skill-Id
"""
import os, json, time, logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# ── 默认配置 ──
# 支持: CSC_API_KEY (推荐) 或 DRAGONFLY_API_KEY (遗留)
# Try env vars first, then .env.dragonfly file
_CSC_API_KEY = os.environ.get("CSC_API_KEY") or os.environ.get("DRAGONFLY_API_KEY", "")
if not _CSC_API_KEY:
    _dragonfly_path = os.path.expanduser("~/.hermes/.env.dragonfly")
    if os.path.exists(_dragonfly_path):
        with open(_dragonfly_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("DRAGONFLY_API_KEY="):
                    val = line.split("=", 1)[1].strip().strip("'\"").strip()
                    if val and "..." not in val:  # skip corrupted keys
                        _CSC_API_KEY = val
                    break
_DEFAULT_BASE_URL = os.environ.get("CSC_BASE_URL", "https://skillhub.csc108.com/api/skillhub/v1")

# ── 字段映射表 ──
# data_layer.py 的 get_financial_report() 返回 dict 键名
# 这些键被 engine/factor_engine.py 的 SUB_FACTOR_DEFS 消费
FIN_FIELD_MAP = {
    "wgtAvgRoe":            "净资产收益率",
    "grossSellingRate":     "毛利率",
    "assetLiabRatio":       "资产负债率",
    "netSellingRate":       "净利率",
    "operateCashFlowPs":    "每股经营现金流",
    "basicEps":             "基本每股收益",
    "npPerShare":           "每股净资产",
    "totalRevenue":         "营业总收入",
    "revenueYoy":           "营业收入同比增长率",
    "netProfitAtsopc":      "归母净利润",
    "netProfitAtsopcYoy":   "净利润同比增长率",
    "op":                   "营业利润",
    "netInterestOfTotalAssets": "总资产净利率",
    "netCfPs":              "每股现金流量净额",
}


class QTSource:
    """蜻蜓数据源客户端"""

    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or _CSC_API_KEY
        self.base_url = (base_url or _DEFAULT_BASE_URL).rstrip("/")
        if not self.api_key:
            logger.warning(
                "[QTSource] CSC_API_KEY not set. "
                "Set CSC_API_KEY env var or pass api_key= to constructor."
            )
        self._session = requests.Session()
        self._session.headers.update({
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
        })
        self._fin_cache: dict = {}
        self._rank_cache: dict = {}
        self._profile_cache: dict = {}

    def _get(self, path: str, params: dict = None, skill_id: str = None) -> dict:
        """发送 GET 请求到蜻蜓 API"""
        url = f"{self.base_url}{path}"
        headers = {}
        if skill_id:
            headers["X-Calling-Skill-Id"] = skill_id
        try:
            resp = self._session.get(url, params=params, headers=headers, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.RequestException as e:
            logger.warning(f"[QTSource] GET {path} failed: {e}")
            return {}
        except json.JSONDecodeError:
            logger.warning(f"[QTSource] GET {path} non-JSON: {resp.text[:200]}")
            return {}

    def get_financial_report(self, stock_code: str) -> dict:
        """
        获取 A 股关键财务指标（单股票）
        对应接口: /info/f10/finance/more?ids=gjzb
        返回 dict 键名与 data_layer.get_financial_report() 兼容
        """
        stock_code = stock_code.replace(".SH", "").replace(".SZ", "").zfill(6)
        if stock_code in self._fin_cache:
            return self._fin_cache[stock_code]

        data = self._get(
            "/info/f10/finance/more",
            params={"stockCode": stock_code, "ids": "gjzb", "type": "combine",
                    "pageNum": 1, "pageSize": 1},
            skill_id="csc-stock-financial-query"
        )
        if not data or data.get("responseCode") != 0:
            logger.info(f"[QTSource] get_financial_report({stock_code}) failed: "
                        f"{data.get('responseDesc', 'no data')}")
            self._fin_cache[stock_code] = {}
            return {}

        rows = data.get("keyIndicatorList") or []
        if not rows:
            self._fin_cache[stock_code] = {}
            return {}

        latest = rows[0]
        result = {}
        for csc_key, local_key in FIN_FIELD_MAP.items():
            val = latest.get(csc_key)
            if val is not None and str(val).strip() not in ("", "--", "null"):
                try:
                    result[local_key] = float(val)
                except (ValueError, TypeError):
                    pass
        self._fin_cache[stock_code] = result
        return result

    def get_financial_reports_batch(self, stock_codes: list) -> dict:
        """批量获取财务数据（带休眠避免触发限频）"""
        results = {}
        for i, code in enumerate(stock_codes):
            if i > 0:
                time.sleep(0.3)
            fin = self.get_financial_report(code)
            if fin:
                results[code] = fin
        return results

    def get_financial_history(self, stock_code: str, quarters: int = 4) -> list:
        """获取多季度财务数据历史"""
        stock_code = stock_code.replace(".SH", "").replace(".SZ", "").zfill(6)
        data = self._get(
            "/info/f10/finance/more",
            params={"stockCode": stock_code, "ids": "gjzb", "type": "combine",
                    "pageNum": 1, "pageSize": str(quarters)},
            skill_id="csc-stock-financial-query"
        )
        if not data or data.get("responseCode") != 0:
            return []
        rows = data.get("keyIndicatorList") or []
        history = []
        report_type_map = {"1": 1, "2": 2, "3": 3, "4": 4}
        for r in rows:
            q = report_type_map.get(str(r.get("type", "")), 0)
            yr = r.get("year", 0)
            if not yr and r.get("reportDate"):
                try:
                    yr = int(str(r["reportDate"])[:4])
                except (ValueError, TypeError):
                    continue
            if not yr:
                continue
            entry = {"year": int(yr), "quarter": q, "period": f"{yr}Q{q}"}
            for csc_key, local_key in FIN_FIELD_MAP.items():
                val = r.get(csc_key)
                if val is not None and str(val).strip() not in ("", "--", "null"):
                    try:
                        entry[local_key] = float(val)
                    except (ValueError, TypeError):
                        pass
            if len(entry) > 3:
                history.append(entry)
        return history

    def get_industry_rank(self, stock_code: str, metric: str = "jzcsyl") -> dict:
        """获取股票在所属行业中的指标排名"""
        stock_code = stock_code.replace(".SH", "").replace(".SZ", "").zfill(6)
        cache_key = f"{stock_code}_{metric}"
        if cache_key in self._rank_cache:
            return self._rank_cache[cache_key]
        data = self._get(
            "/info/f10/finance/industryRank",
            params={"stockCode": stock_code, "metric": metric},
            skill_id="csc-listed-company-profile-industry-compare"
        )
        if data and data.get("responseCode") == 0:
            result = {
                "industryName": data.get("industryName"),
                "industryRank": data.get("industryRank"),
                "industryAvg": data.get("industryAvg"),
                "industryList": data.get("industryList") or [],
            }
            self._rank_cache[cache_key] = result
            return result
        return {}

    def get_company_profile(self, stock_code: str) -> dict:
        """获取上市公司基本资料"""
        stock_code = stock_code.replace(".SH", "").replace(".SZ", "").zfill(6)
        if stock_code in self._profile_cache:
            return self._profile_cache[stock_code]
        data = self._get(
            "/info/f10/menu/basicInfo",
            params={"stockCode": stock_code},
            skill_id="csc-listed-company-profile-industry-compare"
        )
        if data and data.get("responseCode") == 0:
            info = data.get("basicInfo") or {}
            self._profile_cache[stock_code] = {
                "secName": info.get("secName"),
                "industryName": info.get("industryName"),
                "mainOprBus": info.get("mainOprBus"),
                "listedDate": info.get("listedDate"),
                "staffNum": info.get("staffNum"),
            }
            return self._profile_cache[stock_code]
        return {}

    def clear_cache(self):
        self._fin_cache.clear()
        self._rank_cache.clear()
        self._profile_cache.clear()
