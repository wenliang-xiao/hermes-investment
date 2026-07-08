"""
analysis/init_ic_data.py — 首次IC快照生成

从 data_router.get_history() 获取最近 120 天数据，
计算每个标的的 7 个风格因子原始值，然后计算 Spearman IC。
输出到 data/ic_cache/ic_2026-07-02.json

用法:
    python3 analysis/init_ic_data.py
"""

import sys, os, json, logging, math
from datetime import datetime, date, timedelta
from pathlib import Path

# Path setup
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import numpy as np
import scipy.stats as st

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# 7个风格因子及其子因子定义
STYLE_FACTOR_SUBS = {
    "quality":   ["quality:roe", "quality:gross_margin", "quality:debt_ratio",
                  "quality:ocf_per_share", "quality:net_margin"],
    "value":     ["value:pe_percentile", "value:pb", "value:pe_ttm"],
    "growth":    ["growth:rev_ttm", "growth:profit_ttm", "growth:roe_trend"],
    "momentum":  ["momentum:20d", "momentum:60d", "momentum:120d"],
    "low_vol":   ["low_vol:20d_vol", "low_vol:max_dd_60d"],
    "sentiment": ["sentiment:volume_ratio", "sentiment:turnover"],
    "risk":      ["risk:pe_excessive", "risk:volatility"],
}


def get_symbols() -> list[str]:
    """获取标的池 — 优先用 watch 层和核心 A 股"""
    symbols = []
    # 从 watch 池取
    watch_path = os.path.join(_PROJECT_ROOT, "data", "pool", "watch.json")
    try:
        with open(watch_path) as f:
            watch = json.load(f)
        symbols.extend([item["symbol"] for item in watch])
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 补充核心 A 股
    if len(symbols) < 30:
        try:
            from domain.stock_universe import ALL_CORE_STOCKS
            extras = [s for s in ALL_CORE_STOCKS if len(str(s)) == 6 and s not in symbols]
            symbols.extend(extras[:max(0, 40 - len(symbols))])
        except ImportError:
            extras = ["300502", "688041", "688008", "002371", "603259",
                      "688256", "600519", "000858", "300750", "002594",
                      "000333", "002415", "300124", "002230", "688111",
                      "600036", "601318", "000002", "600887", "300760",
                      "002475", "300274", "002920", "601899", "600809",
                      "300760", "002714", "603986", "688012", "002129"]
            symbols.extend([s for s in extras if s not in symbols])

    return symbols[:50]  # 最多 50 只，保证速度


def compute_sub_factor_raw(hist: dict, sub_key: str) -> float | None:
    """计算单个子因子的原始值（简化版）"""
    if not hist or "close" not in hist or not hist["close"]:
        return None
    close = np.array(hist["close"], dtype=float)

    if sub_key == "momentum:20d":
        if len(close) < 21:
            return None
        return float(close[-1] / close[-21] - 1)
    elif sub_key == "momentum:60d":
        if len(close) < 61:
            return None
        return float(close[-1] / close[-61] - 1)
    elif sub_key == "momentum:120d":
        if len(close) < 121:
            return None
        return float(close[-1] / close[-121] - 1)
    elif sub_key == "low_vol:20d_vol":
        if len(close) < 20:
            return None
        rets = np.diff(close[-21:]) / close[-21:-1]
        if len(rets) < 5:
            return None
        return float(np.std(rets) * math.sqrt(252))
    elif sub_key == "low_vol:max_dd_60d":
        if len(close) < 60:
            return None
        window = close[-60:]
        peak = np.maximum.accumulate(window)
        dd = (window - peak) / peak
        return float(np.min(dd))
    elif sub_key == "risk:pe_excessive":
        pe_arr = hist.get("pe", [])
        if pe_arr and len(pe_arr) > 20:
            pe_vals = [float(p) for p in pe_arr if p is not None and float(p) > 0]
            if len(pe_vals) > 20:
                current_pe = pe_vals[-1]
                mean_pe = np.mean(pe_vals)
                if mean_pe > 0:
                    return float(current_pe / mean_pe)
        return None
    elif sub_key == "risk:volatility":
        if len(close) < 60:
            return None
        rets = np.diff(close[-61:]) / close[-61:-1]
        if len(rets) < 10:
            return None
        return float(np.std(rets) * math.sqrt(252))
    elif sub_key == "sentiment:volume_ratio":
        vol = hist.get("volume", [])
        if len(vol) < 40:
            return None
        vol = np.array(vol, dtype=float)
        avg_20 = np.mean(vol[-20:])
        avg_40 = np.mean(vol[-40:-20]) if len(vol) >= 40 else avg_20
        return float(avg_20 / avg_40) if avg_40 > 0 else None
    elif sub_key == "sentiment:turnover":
        amount = hist.get("amount", [])
        if len(amount) < 20:
            return None
        return float(np.mean(amount[-20:]))
    elif sub_key == "value:pe_ttm":
        pe_arr = hist.get("pe", [None])
        if pe_arr and pe_arr[-1] is not None:
            v = float(pe_arr[-1])
            return v if v > 0 else None
        return None
    elif sub_key == "value:pb":
        pb_arr = hist.get("pb", [None])
        if pb_arr and pb_arr[-1] is not None:
            v = float(pb_arr[-1])
            return v if v > 0 else None
        # baostock 无 pb，跳过
        return None
    elif sub_key == "value:pe_percentile":
        pe_arr = hist.get("pe", [])
        if pe_arr and len(pe_arr) > 20:
            pe_vals = [float(p) for p in pe_arr if p is not None and float(p) > 0]
            if len(pe_vals) > 20:
                pct = st.percentileofscore(pe_vals, pe_vals[-1]) / 100.0
                return float(pct)
        return None
    elif sub_key == "growth:roe_trend":
        if len(close) >= 120:
            mom_20 = close[-1] / close[-21] - 1
            mom_60 = close[-1] / close[-61] - 1
            return float(mom_20 - mom_60)
        return None
    elif sub_key in ("quality:roe", "quality:gross_margin", "quality:debt_ratio",
                     "quality:ocf_per_share", "quality:net_margin",
                     "growth:rev_ttm", "growth:profit_ttm"):
        # 财务类子因子 — 从日线数据近似推算
        if sub_key == "quality:roe":
            pe_arr = hist.get("pe", [])
            if pe_arr:
                pe_vals = [float(p) for p in pe_arr if p is not None and float(p) > 0]
                if pe_vals:
                    return min(50.0, 100.0 / pe_vals[-1])  # 1/PE * 100 近似 ROE
            return None
        elif sub_key == "growth:rev_ttm" or sub_key == "growth:profit_ttm":
            # 用60日动量近似增长率
            if len(close) >= 61:
                momentum = float(close[-1] / close[-61] - 1)
                return max(-50.0, min(100.0, momentum * 100))
            return None
        else:
            # gross_margin, debt_ratio, ocf_per_share, net_margin 无法从日线推算
            return None
    return None


def compute_5d_forward_return(hist: dict) -> float | None:
    """计算5日涨幅（用 close[-1]/close[-6] - 1）"""
    if not hist or "close" not in hist:
        return None
    close = hist["close"]
    if len(close) < 7:
        return None
    return float(close[-1] / close[-6] - 1)


def main():
    logger.info("=" * 60)
    logger.info("IC 快照生成 — 7个风格因子 Spearman IC")
    logger.info("=" * 60)

    today = date.today().isoformat()
    symbols = get_symbols()
    logger.info(f"标的数量: {len(symbols)}")

    from data.data_router import get_history

    # 1. 收集数据
    hist_data = {}
    fail_count = 0
    for i, sym in enumerate(symbols):
        try:
            df = get_history(sym, days=130)
            if df and df.get("close") and len(df["close"]) > 60:
                hist_data[sym] = df
            else:
                fail_count += 1
        except Exception as e:
            fail_count += 1
            if fail_count <= 3:
                logger.debug(f"  {sym} 获取失败: {e}")
        if (i + 1) % 20 == 0:
            logger.info(f"  进度: {i+1}/{len(symbols)}, 成功={len(hist_data)}")

    logger.info(f"成功获取: {len(hist_data)}, 失败: {fail_count}")
    if len(hist_data) < 10:
        logger.error("有效标的不够")
        return

    # 2. 计算因子截面值
    factor_raws = {}
    for style_name, sub_keys in STYLE_FACTOR_SUBS.items():
        factor_raws[style_name] = {}
        for sym, hist in hist_data.items():
            sub_vals = []
            for sk in sub_keys:
                v = compute_sub_factor_raw(hist, sk)
                if v is not None:
                    sub_vals.append(v)
            if sub_vals:
                factor_raws[style_name][sym] = float(np.mean(sub_vals))

    # 3. 计算5日 forward return
    forward_returns = {}
    for sym, hist in hist_data.items():
        fr = compute_5d_forward_return(hist)
        if fr is not None and abs(fr) < 1.0:  # 过滤异常值
            forward_returns[sym] = fr

    logger.info(f"有 forward return 的标的: {len(forward_returns)}")

    # 4. 计算 Spearman IC
    ics = {}
    for style_name in STYLE_FACTOR_SUBS:
        fv = factor_raws.get(style_name, {})
        common = [s for s in fv if s in forward_returns and forward_returns[s] is not None]
        n_valid = sum(1 for s in common if fv[s] is not None)
        if n_valid < 10:
            logger.info(f"  {style_name}: 样本不足 ({n_valid}), IC=0.0")
            ics[style_name] = 0.0
            continue
        f_vals = [fv[s] for s in common]
        r_vals = [forward_returns[s] for s in common]
        try:
            rho, _ = st.spearmanr(f_vals, r_vals)
            ic_val = round(float(rho) if not np.isnan(rho) else 0.0, 4)
            ics[style_name] = ic_val
            logger.info(f"  {style_name}: IC={ic_val:.4f} (n={n_valid})")
        except Exception as e:
            logger.warning(f"  {style_name}: 计算失败: {e}")
            ics[style_name] = 0.0

    # 5. 保存
    cache_dir = os.path.join(_PROJECT_ROOT, "data", "ic_cache")
    os.makedirs(cache_dir, exist_ok=True)
    output_path = os.path.join(cache_dir, f"ic_{today}.json")
    with open(output_path, "w") as f:
        json.dump(ics, f, ensure_ascii=False, indent=2)
    logger.info(f"IC 快照已保存: {output_path}")

    # 验证
    with open(output_path) as f:
        loaded = json.load(f)
    expected_factors = list(STYLE_FACTOR_SUBS.keys())
    missing = [k for k in expected_factors if k not in loaded]
    if missing:
        logger.warning(f"缺少因子: {missing}")
    else:
        logger.info("✅ 7个因子全部覆盖")
    print(f"\n📊 IC 快照 ({today}):")
    for k in expected_factors:
        print(f"    {k}: {loaded.get(k, 0.0)}")


if __name__ == "__main__":
    main()
