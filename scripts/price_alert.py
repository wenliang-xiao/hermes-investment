"""
scripts/price_alert.py — 盘中价格报警服务

检测规则:
1. 价格 ±3% 报警（相对建仓价）
2. 成交量同比暴增 500% 报警（相对 20 日均值）

用法:
    python scripts/price_alert.py                    # 检查所有持仓
    python scripts/price_alert.py --symbol 300502    # 检查单个标的
    python scripts/price_alert.py --daemon           # 持续运行（每5分钟）
"""
from __future__ import annotations

import json, sys, os, time
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# ── 报警阈值 ──
PRICE_DROP_THRESHOLD = -0.03     # -3%
PRICE_RISE_THRESHOLD = 0.03      # +3%
VOLUME_SPIKE_THRESHOLD = 5.0     # 500% 暴增


def load_history_volume(symbol: str, days: int = 20) -> list[float]:
    """加载历史成交量"""
    try:
        sys.path.insert(0, str(ROOT.parent))
        from data.data_router import get_history
        hist = get_history(symbol, days=days * 2)
        if hist and hist.get("volume"):
            volumes = [v for v in hist["volume"] if v and v > 0]
            return volumes[-days:]
    except Exception:
        pass
    return []


def check_price_alert(symbol: str, entry_price: float, current_price: float) -> Optional[str]:
    """检查价格报警"""
    if entry_price <= 0 or current_price <= 0:
        return None

    change_pct = current_price / entry_price - 1

    if change_pct <= PRICE_DROP_THRESHOLD:
        return f"⚠️ 价格报警 {symbol}: 跌{abs(change_pct)*100:.1f}% (建仓¥{entry_price:.2f}→现¥{current_price:.2f})"
    elif change_pct >= PRICE_RISE_THRESHOLD:
        return f"🔔 价格提醒 {symbol}: 涨{change_pct*100:.1f}% (建仓¥{entry_price:.2f}→现¥{current_price:.2f})"

    return None


def check_volume_alert(symbol: str, current_volume: float) -> Optional[str]:
    """检查成交量报警"""
    if current_volume <= 0:
        return None

    hist_volumes = load_history_volume(symbol)
    if len(hist_volumes) < 5:
        return None

    avg_volume = sum(hist_volumes) / len(hist_volumes)
    if avg_volume <= 0:
        return None

    ratio = current_volume / avg_volume
    if ratio >= VOLUME_SPIKE_THRESHOLD:
        return f"📊 量能异动 {symbol}: 成交量暴增{ratio:.1f}倍 (20日均值{avg_volume:.0f}→当前{current_volume:.0f})"

    return None


def check_all_alerts() -> list[dict]:
    """检查所有持仓报警"""
    alerts = []

    # 从模拟盘读取持仓
    shadow_path = DATA_DIR / "shadow_account.json"
    if not shadow_path.exists():
        return []

    with open(shadow_path) as f:
        book = json.load(f)

    positions = book.get("positions", {})
    if not positions:
        return []

    sys.path.insert(0, str(ROOT.parent))
    from data.data_router import get_rt

    for sym, pos in positions.items():
        entry_price = pos.get("entry_price", 0)
        name = pos.get("name", sym)

        try:
            rt = get_rt(sym)
        except Exception:
            continue

        if not rt:
            continue

        current_price = rt.get("price", 0)
        current_volume = rt.get("volume", 0)

        # 价格报警
        price_alert = check_price_alert(sym, entry_price, current_price)
        if price_alert:
            alerts.append({
                "type": "price",
                "symbol": sym,
                "name": name,
                "message": price_alert,
                "severity": "high" if abs(current_price / entry_price - 1) > 0.05 else "medium",
                "time": datetime.now().strftime("%H:%M:%S"),
            })

        # 成交量报警
        vol_alert = check_volume_alert(sym, current_volume)
        if vol_alert:
            alerts.append({
                "type": "volume",
                "symbol": sym,
                "name": name,
                "message": vol_alert,
                "severity": "medium",
                "time": datetime.now().strftime("%H:%M:%S"),
            })

        time.sleep(1.5)  # 防限流

    return alerts


def run_daemon(interval_seconds: int = 300):
    """持续运行报警检查"""
    print(f"🔔 价格报警守护启动, 每{interval_seconds}s检查一次")
    print(f"   价格阈值: ±3% | 成交量: 500% 暴增")
    print(f"   Ctrl+C 停止\n")

    while True:
        try:
            alerts = check_all_alerts()
            if alerts:
                print(f"\n{'='*50}")
                print(f"🔔 {len(alerts)} 条报警 | {datetime.now().strftime('%H:%M:%S')}")
                print(f"{'='*50}")
                for a in alerts:
                    sev = "🔴" if a["severity"] == "high" else "🟡"
                    print(f"  {sev} [{a['time']}] {a['message']}")
            else:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"  [{now}] ✅ 无报警")
        except KeyboardInterrupt:
            print("\n停止守护")
            break
        except Exception as e:
            print(f"  ❌ 检查失败: {e}")

        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="价格报警服务")
    parser.add_argument("--symbol", help="单个标的")
    parser.add_argument("--daemon", action="store_true", help="持续运行模式")
    args = parser.parse_args()

    if args.daemon:
        run_daemon()
    elif args.symbol:
        alerts = check_all_alerts()
        for a in alerts:
            if a["symbol"] == args.symbol:
                print(a["message"])
        if not alerts:
            print(f"{args.symbol}: 无报警")
    else:
        alerts = check_all_alerts()
        if alerts:
            print(f"\n🔔 {len(alerts)} 条报警:")
            for a in alerts:
                print(f"  {a['message']}")
        else:
            print("✅ 无报警")
