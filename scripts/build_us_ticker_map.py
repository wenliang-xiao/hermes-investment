#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_us_ticker_map.py — 构建 US 股票 ticker -> 发行方名称 映射文件。

数据源: SEC EDGAR company_tickers.json
  https://www.sec.gov/files/company_tickers.json
该文件的 `title` 字段与 13F infoTable 的 nameOfIssuer 同源(SEC 发行人注册名),
因此用同一套 `_norm_issuer` 规范化后可直接互相匹配。

输出: data/us_ticker_map.json
  结构: {"TICKER": {"name": "发行方原始名", "norm": "规范化名"}, ...}

用法:
  python scripts/build_us_ticker_map.py [--out data/us_ticker_map.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict

import requests

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_UA = "HermesInvestSys research contact=admin@example.com"
HTTP_TIMEOUT = 30
RATE_LIMIT_S = 0.5

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DEFAULT_OUT = PROJECT_ROOT / "data" / "us_ticker_map.json"

log = logging.getLogger("build_us_ticker_map")


def _norm_issuer(name: str) -> str:
    """与 guru_holdings.py 中完全一致的规范化逻辑(去 INC/CORP/CO 等后缀)。"""
    s = re.sub(r"[^A-Z0-9]", "", (name or "").upper())
    return s.replace("INC", "").replace("CORP", "").replace("CO", "") \
            .replace("FINL", "").replace("MTNBE", "").replace("SWITZ", "")


def fetch_tickers() -> Dict[str, Dict[str, str]]:
    """下载 SEC company_tickers.json, 返回 {ticker: {name, norm}}。"""
    log.info("下载 %s", SEC_TICKERS_URL)
    headers = {"User-Agent": SEC_UA}
    for attempt in range(1, 4):
        try:
            resp = requests.get(SEC_TICKERS_URL, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code in (429, 500, 502, 503, 504):
                log.warning("HTTP %s (第 %d 次)", resp.status_code, attempt)
                time.sleep(1.0 * attempt)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        except requests.exceptions.RequestException as exc:
            log.warning("请求失败 (第 %d 次): %s", attempt, exc)
            time.sleep(1.0 * attempt)
    else:
        raise RuntimeError(f"无法获取 {SEC_TICKERS_URL}")

    result: Dict[str, Dict[str, str]] = {}
    for row in data.values():
        ticker = str(row.get("ticker", "")).strip().upper()
        title = str(row.get("title", "")).strip()
        if not ticker or not re.fullmatch(r"[A-Z][A-Z0-9.\-]*", ticker):
            continue
        norm = _norm_issuer(title)
        if not norm:
            continue
        # 同名(规范化)多次出现时保留较长/规范的 title
        prev = result.get(ticker)
        if prev is None or len(norm) > len(prev["norm"]):
            result[ticker] = {"name": title, "norm": norm}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 US ticker -> issuer 名映射")
    parser.add_argument("--out", type=str, default=str(DEFAULT_OUT),
                        help="输出 JSON 路径")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)

    tickers = fetch_tickers()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(tickers, f, ensure_ascii=False, indent=2, sort_keys=True)

    log.info("完成: 写入 %s (%d 条 ticker 映射)", out_path, len(tickers))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
