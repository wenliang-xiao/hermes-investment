"""scripts/run_behavior.py — 行为诊断定时运行器

读取 strategy_states.json + state_history.jsonl
输出: data/behavior_diagnosis.json + 日报行为板块摘要

用法:
    python3 scripts/run_behavior.py              # 完整分析
    python3 scripts/run_behavior.py --brief      # 仅输出摘要到 stdout
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_DIR)

from utils.atomic_io import atomic_write_json
from analysis.behavior import diagnose_all, load_strategy_states


def run_diagnosis() -> dict:
    """运行全诊断，写入 data/behavior_diagnosis.json"""
    states = load_strategy_states(os.path.join(_PROJECT_DIR, "data", "strategy_states.json"))
    results = diagnose_all(states)

    # 附加元数据
    output = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%Y-%m-%d"),
        "strategies": results,
    }

    out_path = os.path.join(_PROJECT_DIR, "data", "behavior_diagnosis.json")
    atomic_write_json(out_path, output)
    print(f"💾 行为诊断已保存: {out_path}")
    return output


def format_brief(output: dict) -> str:
    """生成简报文本"""
    lines = ["📊 行为诊断简报", "=" * 40]
    for sname in ["faceji", "silverquant", "tradingagents"]:
        r = output.get("strategies", {}).get(sname, {})
        if not r:
            continue
        lines.append(f"\n▸ {sname.upper()}")
        lines.append(f"  处置效应: {r.get('disposition_ratio',0):.2f} | 过度交易: {r.get('overtrading_index',0):.1f}x")
        lines.append(f"  追涨分数: {r.get('chasing_score',0):.1f} | 锚定指数: {r.get('anchoring_index',0):.4f}")
        lines.append(f"  胜率: {r.get('pnl_analysis',{}).get('win_rate',0):.0%} | 交易: {r.get('trade_count',0)}笔")
        actions = r.get("recommended_actions", [])
        if actions:
            lines.append(f"  建议: {actions[0][:60]}")

    # 组合级
    cr = output.get("strategies", {}).get("_combined", {})
    if cr:
        pnl = cr.get("pnl_analysis", {})
        lines.append(f"\n▸ 汇总")
        lines.append(f"  总交易: {cr.get('trade_count',0)}笔 | 胜率: {pnl.get('win_rate',0):.0%}")
        lines.append(f"  净盈亏: ¥{pnl.get('net_pnl',0):+.0f}")
        lines.append(f"  过度交易: {cr.get('overtrading_index',0):.1f}x | 追涨: {cr.get('chasing_score',0):.1f}")

    return "\n".join(lines)


def load_diagnosis() -> dict | None:
    """读取最近一次诊断结果"""
    path = os.path.join(_PROJECT_DIR, "data", "behavior_diagnosis.json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="行为诊断引擎")
    parser.add_argument("--brief", action="store_true", help="仅输出简报")
    args = parser.parse_args()

    output = run_diagnosis()

    if args.brief:
        print(format_brief(output))
    else:
        print(format_brief(output))
        # 也输出详细到文件
        brief_path = os.path.join(_PROJECT_DIR, "data", "behavior_brief.txt")
        with open(brief_path, "w") as f:
            f.write(format_brief(output))
        print(f"💾 简报已保存: {brief_path}")
