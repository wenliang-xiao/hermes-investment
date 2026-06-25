#!/usr/bin/env bash
# scripts/harness.sh —— 验证门禁
# 策略改动提交前，运行本脚本确认基本质量不退化
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[harness] 1. git diff --check"
git diff --check || echo "  (仅提示，不阻断)"

echo "[harness] 2. Python import check"
python3 -c "
from strategies.faceji import decide as f
from strategies.silverquant import decide as s
from strategies.tradingagents import decide as t
print('  strategies/* 导入 OK')
from evaluator_fixed import FIXED_SCORE_MAP, FIXED_UNIVERSE
print(f'  evaluator_fixed 导入 OK ({len(FIXED_UNIVERSE)}只标的)')
"

echo "[harness] 3. 基础语法检查"
python3 -m py_compile strategies/base.py
python3 -m py_compile strategies/faceji.py
python3 -m py_compile strategies/silverquant.py
python3 -m py_compile strategies/tradingagents.py
python3 -m py_compile evaluator_fixed.py
echo "  语法 OK"

echo ""
echo "[harness] OK — 已通过验证门禁"