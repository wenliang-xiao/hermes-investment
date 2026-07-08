"""
每日三策略执行器补充 — 创建空白 `trading_signals.json` 证据层模板
"""
import sys, os, json
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

from utils.atomic_io import atomic_write_json

# 创建空的 trading_signals.json（如果不存在）—— 确保 API 端点有数据可读
path = os.path.join(_PROJECT_DIR, "data", "trading_signals.json")
if not os.path.exists(path):
    template = {
        "date": "",
        "generated_at": "",
        "total_raw_signals": 0,
        "after_conflict_resolution": 0,
        "after_weekly_filter": 0,
        "simulated_trades": 0,
        "portfolios": {},
        "positions": {},
        "trade_history": {},
        "signals": [],
        "all_signals": []
    }
    atomic_write_json(path, template)
    print(f"✅ 创建 trading_signals.json 模板 ({path})")

# 创建空的 strategy_states.json
path = os.path.join(_PROJECT_DIR, "data", "strategy_states.json")
if not os.path.exists(path):
    template = {
        "faceji": {"cash": 1000000, "positions": {}, "history": []},
        "silverquant": {"cash": 1000000, "positions": {}, "history": []},
        "tradingagents": {"cash": 1000000, "positions": {}, "history": []}
    }
    atomic_write_json(path, template)
    print(f"✅ 创建 strategy_states.json 模板 ({path})")

# 创建空的 signal_accuracy_history.json
path = os.path.join(_PROJECT_DIR, "data", "signal_accuracy_history.json")
if not os.path.exists(path):
    template = {
        "last_30d": {
            "by_score_band": {},
            "hit_rate": 0,
            "mse": 0,
            "total_signals": 0
        },
        "history": []
    }
    atomic_write_json(path, template)
    print(f"✅ 创建 signal_accuracy_history.json 模板 ({path})")

# 创建空的 etf_discovery.json（ETF面板不卡死）
path = os.path.join(_PROJECT_DIR, "data", "etf_discovery.json")
if not os.path.exists(path):
    template = {
        "total": 0,
        "scan_date": "",
        "etfs": [],
        "momentum": [],
        "error": "no_data_yet",
        "message": "请先在 ECS 运行 scripts/run_etf_discovery.py"
    }
    atomic_write_json(path, template)
    print(f"✅ 创建 etf_discovery.json 模板 ({path})")