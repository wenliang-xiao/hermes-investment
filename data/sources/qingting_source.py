"""
蜻蜓数据源 --- 中信建投证券 Skill 广场 API 封装

CSC (China Securities / 中信建投) Skill Hub API Wrapper.

数据更新频率：财报数据 T+2~3h，行业排名日频
覆盖范围：A 股全量 ~5000 只
鉴权方式：X-API-Key + X-Calling-Skill-Id

P0 加固 (2026-08-18):
  - 蜻蜓 API 偶发 TCP 连接挂死 (urllib3 create_connection 卡住, timeout=15 兜不住)
    → run_trading cron 卡死在批量评分, 模拟盘数据停滞
  - 修复: ①显式 (connect, read) 双超时 ②SIGALRM 进程级硬超时包住整个请求
    ③行业排名/财务磁盘缓存跨进程复用 (蜻蜓日频数据, 当日缓存有效)
"""
import os, json, time, logging, signal, threading
from typing import Optional
from pathlib import Path
from datetime import date
import requests

logger = logging.getLogger(__name__)

# ── P0 超时防护 ──
QT_CONNECT_TIMEOUT = 5     # TCP 建连超时
QT_READ_TIMEOUT = 15       # 读响应超时
QT_HARD_TIMEOUT = 25       # 整个请求硬超时 (SIGALRM)
_QT_CACHE_DIR = Path(__file__).parent.parent.parent / "data" / "cache" / "qingting"
_QT_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class QTTimeoutError(TimeoutError):
    """蜻蜓 API 请求挂死超时"""


def _qt_hard_timeout_guard(seconds: float = QT_HARD_TIMEOUT):
    """SIGALRM 进程级硬超时 — 包住 requests 全流程(含 DNS/TCP 建连挂死)。

    urllib3 create_connection 在特定网络状态下可能无视 timeout 参数无限阻塞,
    用 SIGALRM 强制打断 (已验证可打断 C 层 socket 操作)。
    """
    from contextlib import contextmanager

    @contextmanager
    def _guard():
        if seconds <= 0 or threading.current_thread() is not threading.main_thread():
            # 并发安全 (2026-08-18): SIGALRM 仅主线程可用 —
            # worker 线程依赖 requests (connect, read) 双超时兜底
            yield
            return

        def _handler(signum, frame):
            raise QTTimeoutError(f"蜻蜓API请求超时(>{seconds:.0f}s)")

        old = signal.signal(signal.SIGALRM, _handler)
        signal.setitimer(signal.ITIMER_REAL, seconds)
        try:
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old)
    return _guard()

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
        # 并发安全 (2026-08-18): score_batch 线程池并发采集 —
        # session 替换/缓存读改写/磁盘缓存写 全部加锁
        self._lock = threading.RLock()
        self._disk_lock = threading.Lock()

    def _get(self, path: str, params: dict = None, skill_id: str = None) -> dict:
        """发送 GET 请求到蜻蜓 API（带连接重建重试 + P0超时防护）"""
        url = f"{self.base_url}{path}"
        headers = {}
        if skill_id:
            headers["X-Calling-Skill-Id"] = skill_id
        last_err: Exception | None = None
        for attempt in range(3):  # 最多3次尝试
            try:
                # 取 session 引用 (替换由 _reconnect 在锁内完成; 引用获取锁保护)
                with self._lock:
                    session = self._session
                with _qt_hard_timeout_guard():
                    resp = session.get(
                        url, params=params, headers=headers,
                        timeout=(QT_CONNECT_TIMEOUT, QT_READ_TIMEOUT),
                    )
                resp.raise_for_status()
                return resp.json()
            except QTTimeoutError as e:
                # P0: SIGALRM 硬超时 — 服务器挂死(建连卡住/无响应)
                logger.warning(f"[QTSource] GET {path} 硬超时 (attempt {attempt+1}): {e} — 重建连接")
                last_err = e
                self._reconnect()
            except requests.exceptions.ConnectionError as e:
                # 连接重建: errno 9 (Bad file descriptor) / stale keep-alive
                logger.warning(f"[QTSource] GET {path} conn err (attempt {attempt+1}): {e} — 重建连接")
                last_err = e
                self._reconnect()
            except requests.exceptions.Timeout as e:
                logger.warning(f"[QTSource] GET {path} timeout (attempt {attempt+1}): {e}")
                last_err = e
                time.sleep(0.5 * (attempt + 1))
            except requests.exceptions.RequestException as e:
                logger.warning(f"[QTSource] GET {path} failed: {e}")
                return {}
            except json.JSONDecodeError:
                logger.warning(f"[QTSource] GET {path} non-JSON: {resp.text[:200]}")
                return {}
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
        logger.warning(f"[QTSource] GET {path} failed after retries: {last_err}")
        return {}

    def _reconnect(self) -> None:
        """销毁旧会话, 建立全新连接池（解决长扫描中 keep-alive 连接过期问题）"""
        with self._lock:  # 并发安全: 防止 worker 线程同时重建 session
            try:
                self._session.close()
            except Exception:
                pass
            import time as _t
            _t.sleep(0.3)
            self._session = requests.Session()
            self._session.headers.update({
                "X-API-Key": self.api_key,
                "Content-Type": "application/json",
            })

    def get_financial_report(self, stock_code: str) -> dict:
        """
        获取 A 股关键财务指标（单股票）
        对应接口: /info/f10/finance/more?ids=gjzb
        返回 dict 键名与 data_layer.get_financial_report() 兼容
        """
        stock_code = stock_code.replace(".SH", "").replace(".SZ", "").zfill(6)
        with self._lock:  # 双检锁: 避免并发重复请求
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
            with self._lock:
                self._fin_cache[stock_code] = {}
            return {}

        rows = data.get("keyIndicatorList") or []
        if not rows:
            with self._lock:
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
        with self._lock:
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
        """获取股票在所属行业中的指标排名（内存缓存 + 当日磁盘缓存跨进程复用）"""
        stock_code = stock_code.replace(".SH", "").replace(".SZ", "").zfill(6)
        cache_key = f"{stock_code}_{metric}"
        with self._lock:  # 双检锁: 避免并发重复请求
            if cache_key in self._rank_cache:
                return self._rank_cache[cache_key]

        # P0性能: 蜻蜓API单次~10s, 52标×3指标=26min → 当日磁盘缓存跨进程复用
        today = date.today().isoformat() if not hasattr(self, "_today") else self._today
        disk_path = _QT_CACHE_DIR / f"rank_{today}.json"
        with self._disk_lock:  # 磁盘缓存读改写锁: 防止多线程并发丢写
            disk_cache: dict = {}
            try:
                if disk_path.exists():
                    with open(disk_path) as f:
                        disk_cache = json.load(f)
                    if cache_key in disk_cache:
                        with self._lock:
                            self._rank_cache[cache_key] = disk_cache[cache_key]
                        return disk_cache[cache_key]
            except (OSError, json.JSONDecodeError):
                disk_cache = {}

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
            with self._lock:
                self._rank_cache[cache_key] = result
            # 写当日磁盘缓存
            try:
                with self._disk_lock:
                    disk_cache = {}
                    if disk_path.exists():
                        try:
                            with open(disk_path) as f:
                                disk_cache = json.load(f)
                        except (OSError, json.JSONDecodeError):
                            disk_cache = {}
                    disk_cache[cache_key] = result
                    tmp_path = disk_path.with_suffix(".tmp")
                    with open(tmp_path, "w") as f:
                        json.dump(disk_cache, f, ensure_ascii=False, default=str)
                    os.replace(tmp_path, disk_path)
            except (OSError, TypeError):
                pass
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

    def get_company_profile_batch(self, symbols: list[str]) -> dict[str, dict]:
        """批量获取公司资料（带限频保护）"""
        results = {}
        for i, sym in enumerate(symbols):
            if i > 0:
                time.sleep(0.3)
            prof = self.get_company_profile(sym)
            if prof:
                results[sym] = prof
        return results

    def get_industry_ranks_for_symbols(self, symbols: list[str],
                                        metric: str = "jzcsyl") -> dict[str, dict]:
        """
        批量获取行业排名 — 按行业分组，避免重复API调用。
        先获取公司资料确定各标的行业，再每行业调用一次 industryRank 提取所有标的排名。
        返回 {symbol: {industryName, rank, total, value, industryAvg, normalized}}
        """
        # 1. 获取所有标的的行业
        sym_industries: dict[str, str] = {}
        for sym in symbols:
            sym_clean = sym.replace(".SH", "").replace(".SZ", "").zfill(6)
            prof = self.get_company_profile(sym_clean)
            if prof and prof.get("industryName"):
                sym_industries[sym] = prof["industryName"]

        # 2. 按行业分组
        industry_groups: dict[str, list[str]] = {}
        for sym, ind in sym_industries.items():
            if ind not in industry_groups:
                industry_groups[ind] = []
            industry_groups[ind].append(sym)

        # 3. 每行业调用一次，提取所有同行业标的排名
        results: dict[str, dict] = {}
        for ind, syms_in_ind in industry_groups.items():
            first_sym = syms_in_ind[0].replace(".SH", "").replace(".SZ", "").zfill(6)
            rank_data = self.get_industry_rank(first_sym, metric=metric)
            if not rank_data:
                continue
            industry_list = rank_data.get("industryList", [])
            for sym in syms_in_ind:
                sym_clean = sym.replace(".SH", "").replace(".SZ", "").zfill(6)
                for item in industry_list:
                    if item.get("secCode", "").zfill(6) == sym_clean:
                        try:
                            rank_str = str(item.get("rank", ""))
                            total_str = str(rank_data.get("industryRank", ""))
                            rank_parts = total_str.split("/")
                            rank_num = int(rank_str) if rank_str.isdigit() else None
                            total = int(rank_parts[1]) if len(rank_parts) > 1 else None
                            avg_val = rank_data.get("industryAvg")
                            val = item.get("value")
                            norm = (total - rank_num) / total if (rank_num is not None and total) else 0.5
                            results[sym] = {
                                "industryName": ind,
                                "rank": rank_num,
                                "total": total,
                                "value": float(val) if val else None,
                                "industryAvg": float(avg_val) if avg_val else None,
                                "normalized": norm,
                            }
                        except (ValueError, IndexError):
                            pass
                        break
                if sym not in results:
                    results[sym] = {"industryName": ind, "rank": None, "total": None,
                                    "value": None, "industryAvg": None, "normalized": 0.5}
        return results

    def clear_cache(self):
        self._fin_cache.clear()
        self._rank_cache.clear()
        self._profile_cache.clear()
