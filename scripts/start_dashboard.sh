#!/usr/bin/env bash
# 面板启动脚本 — 唯一推荐入口。
#
# 为什么不能直接 `python dashboard/server.py 8686`:
#   面板点回测(/api/v2/backtest/custom、/v3/run)会走 data_router → baostock 批量取数,
#   baostock C 层在多线程/批量场景下会崩 `corrupted double-linked list` /
#   `double free or corruption`: 进程还在(PID 在), 但事件循环已死,
#   所有 HTTP 请求 10s 超时, 只能 kill -9 重启。
#   带 FACTOR_A_AKSHARE_PRIMARY=1 后 A股日线主源改走新浪(stock_zh_a_daily),
#   baostock 仅作降级 —— 同一回测请求 1m44s 正常返回。
#
# 用法:
#   ./scripts/start_dashboard.sh            # 前台, 端口 8686
#   ./scripts/start_dashboard.sh 8687       # 指定端口
#   nohup ./scripts/start_dashboard.sh 8686 > /tmp/hermes_dashboard.log 2>&1 &   # 后台
#
# 解释器可用 HERMES_PY 覆盖 (默认本机 py310 绝对路径; cron/非登录 shell 的
# PATH 里没有 py3.10, 所以必须写绝对路径)。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${HERMES_PY:-/home/work/hongkexin/software/python/py310-langchain-faq/bin/python}"
PORT="${1:-8686}"

cd "$ROOT"
export FACTOR_A_AKSHARE_PRIMARY="${FACTOR_A_AKSHARE_PRIMARY:-1}"
echo "[start_dashboard] root=$ROOT port=$PORT py=$PY FACTOR_A_AKSHARE_PRIMARY=$FACTOR_A_AKSHARE_PRIMARY"
exec "$PY" dashboard/server.py "$PORT"
