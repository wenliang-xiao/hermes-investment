#!/usr/bin/env python3
"""
面基投资模拟盘 — 专业数据面板服务器
====================================
FastAPI + 暗色Dashboard，日报通过链接引用

启动:  uvicorn scripts.portfolio_server:app --host 0.0.0.0 --port 8686
"""

import json, os, sys
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, responses
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(ROOT.parent))

# Stock name mapping
sys.path.insert(0, str(ROOT))
try:
    from data.stock_names import STOCK_NAMES, ETF_NAMES, get_name
except ImportError:
    STOCK_NAMES = {}
    ETF_NAMES = {}
    def get_name(code): return code

# 产业链映射
_CHAIN_NAMES = {
    "300502": "AI算力-光模块", "688041": "AI算力-处理器", "688008": "半导体-接口",
    "688256": "AI算力-处理器", "600519": "消费-白酒", "000858": "消费-白酒",
    "300750": "新能源-动力电池", "002594": "新能源-整车", "000333": "消费-家电",
    "300059": "金融-券商", "603259": "医药-CXO", "002371": "半导体-设备",
    "600030": "金融-券商", "601318": "金融-保险", "600036": "金融-银行",
    "002415": "AI算力-视觉", "300124": "新能源-工控", "688012": "半导体-设备",
    "300274": "新能源-逆变器", "601012": "新能源-光伏", "300014": "新能源-电池",
    "002304": "消费-白酒", "600585": "基建-建材", "000651": "消费-家电",
    "300136": "消费电子-射频", "002475": "消费电子-连接器", "002129": "半导体-材料",
    "002460": "新能源-锂资源", "002230": "AI算力-语音", "002129": "半导体-材料",
    "NVDA": "AI算力-GPU", "AMD": "AI算力-GPU", "MU": "半导体-存储",
    "TSM": "半导体-代工", "VST": "AI算力-电力", "CEG": "AI算力-电力",
    "GEV": "AI算力-电力", "0700.HK": "互联网-平台", "9988.HK": "互联网-平台",
    "BABA": "互联网-平台", "MSFT": "AI算力-软件", "META": "互联网-社交",
    "AAPL": "消费电子-手机", "AMZN": "互联网-电商",
}
def _guess_chain(symbol):
    return _CHAIN_NAMES.get(symbol, "其他")

app = FastAPI(title="面基模拟盘 Dashboard", version="1.0.0")


# ─── 数据层 ─────────────────────────────────────────
def load_shadow():
    path = ROOT / "data" / "shadow_account.json"
    if not path.exists():
        return {"capital": 1000000, "cash": 1000000, "positions": {}, "history": [], "realized_pnl": 0}
    with open(path) as f:
        return json.load(f)


def build_summary(book):
    total_pnl = book.get("realized_pnl", 0)
    positions = []
    for sym, pos in book.get("positions", {}).items():
        entry = pos.get("entry_price", 0)
        current = pos.get("current_price", entry)
        qty = pos.get("quantity", 0)
        cost = pos.get("cost", entry * qty)
        mkt_val = current * qty
        pnl = mkt_val - cost
        pnl_pct = (current - entry) / entry * 100 if entry else 0
        peak = pos.get("peak_price", entry)
        dd = (current - peak) / peak * 100 if peak else 0
        try:
            entry_dt = datetime.strptime(pos.get("entry_date", ""), "%Y-%m-%d")
            hold = (datetime.now() - entry_dt).days
        except:
            hold = 0
        positions.append({
            "symbol": sym, "name": pos.get("name", sym),
            "entry_price": round(entry, 4), "current_price": round(current, 4),
            "quantity": qty, "cost": round(cost, 2), "market_value": round(mkt_val, 2),
            "pnl": round(pnl, 2), "pnl_pct": round(pnl_pct, 2),
            "peak": round(peak, 4), "dd_from_peak": round(dd, 1),
            "hold_days": hold,
            "entry_score": pos.get("entry_score"),
            "pct": pos.get("pct", 0),
            "stop_loss": round(entry * 0.92, 4) if hold < 10 else round(peak * 0.88, 4),
        })

    cash = book.get("cash", 0)
    position_value = sum(p["market_value"] for p in positions)
    total_value = cash + position_value
    total_invested = sum(p["cost"] for p in positions)
    unrealized = position_value - total_invested
    realized = book.get("realized_pnl", 0)
    capital = book.get("capital", 1000000)

    return {
        "capital": round(capital, 2),
        "cash": round(cash, 2),
        "position_value": round(position_value, 2),
        "total_value": round(total_value, 2),
        "position_count": len(positions),
        "total_invested": round(total_invested, 2),
        "unrealized_pnl": round(unrealized, 2),
        "realized_pnl": round(realized, 2),
        "total_pnl": round(unrealized + realized, 2),
        "total_return": round((unrealized + realized) / capital * 100, 2) if capital else 0,
        "cash_pct": round(cash / total_value * 100, 1) if total_value else 100,
        "position_pct": round(position_value / total_value * 100, 1) if total_value else 0,
        "positions": sorted(positions, key=lambda p: -abs(p["pnl"])),
    }


def build_history(book):
    history = book.get("history", [])
    trades = []
    for h in history:
        pnl = h.get("pnl")
        trades.append({
            "time": h.get("time", ""),
            "symbol": h.get("symbol", ""),
            "name": h.get("name", ""),
            "action": h.get("action", ""),
            "price": h.get("price", 0),
            "quantity": h.get("quantity", 0),
            "reason": h.get("reason", ""),
            "cost": h.get("cost", 0),
            "pnl": pnl,
            "pnl_str": f"{pnl:+.0f}" if pnl is not None else "",
            "is_win": pnl > 0 if pnl is not None else None,
        })
    # Build PnL history for chart (daily PnL from history records)
    return trades[::-1]  # newest first


def build_chart_data(book):
    """Build portfolio value over time from history"""
    capital = book.get("capital", 1000000)
    history = book.get("history", [])

    # Simulate portfolio value trajectory
    # Start with initial capital
    points = [{"date": book.get("created_at", datetime.now().strftime("%Y-%m-%d")), "value": capital}]
    running_value = capital
    for h in history:
        pnl = h.get("pnl")
        cost = h.get("cost")
        action = h.get("action", "")
        time_str = h.get("time", "")
        date_part = time_str[:10] if time_str else ""

        if action == "买入" and cost:
            running_value -= cost
            points.append({"date": date_part, "value": running_value, "type": "buy"})
        elif action == "卖出" and pnl is not None:
            running_value += pnl
            points.append({"date": date_part, "value": running_value, "type": "sell"})

    # Add current total value as last point
    summary = build_summary(book)
    points.append({"date": datetime.now().strftime("%Y-%m-%d"), "value": summary["total_value"]})

    # Deduplicate by date, keep last value per day
    by_date = {}
    for p in points:
        if p["date"]:
            by_date[p["date"]] = p["value"]
    sorted_dates = sorted(by_date.keys())

    return {
        "labels": sorted_dates,
        "values": [by_date[d] for d in sorted_dates],
        "return_pct": summary.get("total_return", 0),
    }


# ─── API 路由 ──────────────────────────────────────


@app.get("/api/portfolio")
def api_portfolio():
    book = load_shadow()
    
    # shadow_account 为空时，从三策略模拟盘聚合真实数据
    if not book.get("positions") and book.get("cash", 0) >= 1000000:
        try:
            aggr = _aggregate_strategy_portfolios()
            if aggr:
                book = aggr
        except Exception:
            pass
    
    summary = build_summary(book)
    chart = build_chart_data(book)
    history = build_history(book)
    return {
        "summary": summary,
        "chart": chart,
        "history": history[:100],
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "history_count": len(book.get("history", [])),
    }


def _aggregate_strategy_portfolios() -> dict | None:
    """从策略状态文件聚合真实持仓和交易历史"""
    st_path = ROOT / "data" / "strategy_states.json"
    if not st_path.exists():
        return None
    with open(st_path) as f:
        states = json.load(f)
    
    total_cash = 0
    all_positions = {}
    all_history = []
    
    for sname, state in states.items():
        total_cash += state.get("cash", 0)
        for h in state.get("history", []):
            entry = {
                "time": h.get("date", ""),
                "symbol": h.get("symbol", ""),
                "action": "买入" if h.get("action") == "买入" else "卖出",
                "price": h.get("price", 0),
                "quantity": h.get("quantity", 0),
                "cost": h.get("cost", 0),
                "pnl": h.get("pnl"),
                "reason": h.get("reason", ""),
                "strategy": sname,
            }
            all_history.append(entry)
        for sym, pos in state.get("positions", {}).items():
            if sym not in all_positions:
                all_positions[sym] = {
                    "symbol": sym,
                    "entry_price": pos.get("entry_price", 0),
                    "quantity": pos.get("quantity", 0),
                    "entry_date": pos.get("entry_date", ""),
                    "current_price": pos.get("current_price", pos.get("entry_price", 0)),
                    "name": get_name(sym),
                }
    
    total_invested = sum(p["entry_price"] * p["quantity"] for p in all_positions.values())
    return {
        "capital": total_cash + total_invested,
        "cash": total_cash,
        "positions": all_positions,
        "history": sorted(all_history, key=lambda x: x.get("time", ""), reverse=True),
        "created_at": "2026-06-24",
        "realized_pnl": sum(h.get("pnl", 0) for h in all_history if h.get("pnl")),
    }


# ─── 三方对比 Dashboard HTML ──────────────────────────

COMPARISON_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>面基·三方策略对比</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
:root {
  --bg: #0d1117; --card: #161b22; --card2: #1c2333;
  --text: #e6edf3; --text2: #8b949e; --border: #30363d;
  --green: #3fb950; --red: #f85149; --yellow: #d29922; --blue: #58a6ff;
  --orange: #d9600e; --purple: #bc8cff;
}
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       background: var(--bg); color: var(--text); padding: 20px; }
.container { max-width: 1400px; margin: 0 auto; }
h1 { font-size: 24px; margin-bottom: 8px; }
h2 { font-size: 18px; margin: 24px 0 12px; color: var(--text); }
.subtitle { color: var(--text2); font-size: 13px; margin-bottom: 20px; }
.card { background: var(--card); border: 1px solid var(--border);
        border-radius: 8px; padding: 16px; margin-bottom: 16px; }
.card-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
.strategy-card { background: var(--card); border: 1px solid var(--border);
  border-radius: 8px; padding: 16px; position: relative; }
.strategy-card .name { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.strategy-card .return { font-size: 28px; font-weight: 700; margin: 8px 0; }
.strategy-card .return.green { color: var(--green); }
.strategy-card .return.red { color: var(--red); }
.strategy-card .return.yellow { color: var(--yellow); }
.stat-row { display: flex; justify-content: space-between; padding: 4px 0;
            font-size: 13px; border-bottom: 1px solid var(--border); }
.stat-row:last-child { border: none; }
.stat-label { color: var(--text2); }
.stat-value { color: var(--text); font-weight: 500; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px;
         font-size: 11px; font-weight: 600; }
.badge-buy { background: #1a3a2a; color: var(--green); }
.badge-sell { background: #3a1a1a; color: var(--red); }
.badge-win { background: #1a3a2a; color: var(--green); }
.badge-loss { background: #3a1a1a; color: var(--red); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; padding: 8px 6px; color: var(--text2);
     border-bottom: 1px solid var(--border); font-weight: 500; }
td { padding: 6px; border-bottom: 1px solid var(--border); }
.tr-hover:hover { background: var(--card2); }
.nav { display: flex; gap: 16px; margin-bottom: 20px; }
.nav a { color: var(--blue); text-decoration: none; font-size: 14px; }
.nav a:hover { text-decoration: underline; }
.trade-log { max-height: 400px; overflow-y: auto; }
.empty { color: var(--text2); text-align: center; padding: 20px; }
</style>
</head>
<body>
<div class="container">
  <div class="nav">
    <a href="/dashboard" style="color:var(--orange);font-weight:600">← 返回Dashboard</a>
  </div>

  <h1>📊 三方策略对比</h1>
  <div class="subtitle" id="runInfo">加载中...</div>

  <div class="card-grid" id="strategyCards"></div>

  <h2>📈 净值曲线对比</h2>
  <div class="card"><canvas id="comparisonChart" height="120"></canvas></div>

  <h2>📋 交易记录对比</h2>
  <div class="card-grid" id="tradeLogs"></div>
</div>

<script>
async function load() {
  const resp = await fetch('/api/comparison');
  const data = await resp.json();

  if (data.error) {
    document.getElementById('strategyCards').innerHTML = '<div class="card" style="grid-column:1/-1">❌ ' + data.error + '</div>';
    return;
  }

  document.getElementById('runInfo').textContent =
    '最后更新: ' + data.run_date + ' | 分析周期: ' + data.days_analyzed + '天' +
    (data.note ? ' | ' + data.note : '');

  // Strategy cards
  const strategies = [data.faceji, data.silverquant, data.tradingagents];
  const colors = { 'faceji (面基)': '#58a6ff', 'silverquant (组件化)': '#3fb950', 'tradingagents (辩论制)': '#bc8cff' };

  document.getElementById('strategyCards').innerHTML = strategies.map(s => {
    const retClass = s.total_return_pct >= 0 ? 'green' : 'red';
    return `<div class="strategy-card">
      <div class="name"><span style="color:${colors[s.name] || '#fff'}">●</span> ${s.name}</div>
      <div class="return ${retClass}">${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%</div>
      <div class="stat-row"><span class="stat-label">总资产</span><span class="stat-value">¥${fmt(s.value)}</span></div>
      <div class="stat-row"><span class="stat-label">现金</span><span class="stat-value">¥${fmt(s.cash)}</span></div>
      <div class="stat-row"><span class="stat-label">持仓数</span><span class="stat-value">${s.positions} 只</span></div>
      <div class="stat-row"><span class="stat-label">已实现盈亏</span><span class="stat-value" style="color:${s.realized_pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${s.realized_pnl >= 0 ? '+' : ''}¥${fmt(s.realized_pnl)}</span></div>
      <div class="stat-row"><span class="stat-label">浮盈</span><span class="stat-value" style="color:${s.unrealized_pnl >= 0 ? 'var(--green)' : 'var(--red)'}">${s.unrealized_pnl >= 0 ? '+' : ''}¥${fmt(s.unrealized_pnl)}</span></div>
      <div class="stat-row"><span class="stat-label">交易次数</span><span class="stat-value">${s.total_trades} 笔</span></div>
      <div class="stat-row"><span class="stat-label">胜率</span><span class="stat-value">${s.win_rate}%</span></div>
      <div class="stat-row"><span class="stat-label">最大回撤</span><span class="stat-value" style="color:var(--red)">-${s.max_drawdown_pct}%</span></div>
    </div>`;
  }).join('');

  // Chart
  renderComparisonChart(strategies);

  // Trade logs
  document.getElementById('tradeLogs').innerHTML = strategies.map(s => {
    const t = s.trades && s.trades.length > 0 ? s.trades : [];
    return `<div class="card" style="grid-column:1">
      <h3 style="font-size:14px;margin-bottom:8px;color:${colors[s.name]}">${s.name} — 最近交易</h3>
      <div class="trade-log">
        <table>
          <tr><th>日期</th><th>代码</th><th>操作</th><th>价格</th><th>盈亏</th><th>原因</th></tr>
          ${t.length === 0 ? '<tr><td colspan="6" class="empty">暂无交易</td></tr>' :
            t.slice(-10).reverse().map(tx => {
              const isBuy = tx.action === '买入';
              return `<tr class="tr-hover">
                <td style="font-size:11px;color:var(--text2)">${tx.date || tx.time || ''}</td>
                <td>${tx.symbol || ''}</td>
                <td><span class="badge ${isBuy ? 'badge-buy' : 'badge-sell'}">${tx.action}</span></td>
                <td>¥${(tx.price || 0).toFixed(2)}</td>
                <td class="${tx.pnl > 0 ? 'green' : (tx.pnl < 0 ? 'red' : '')}">${tx.pnl != null ? (tx.pnl > 0 ? '+' : '') + '¥' + fmt(tx.pnl) : '—'}</td>
                <td style="font-size:11px;color:var(--text2)">${(tx.reason || '').slice(0,25)}</td>
              </tr>`;
            }).join('')}
        </table>
      </div>
    </div>`;
  }).join('');
}

let chartInstance = null;
function renderComparisonChart(strategies) {
  if (chartInstance) chartInstance.destroy();
  const ctx = document.getElementById('comparisonChart').getContext('2d');
  const colors = { 'faceji (面基)': '#58a6ff', 'silverquant (组件化)': '#3fb950', 'tradingagents (辩论制)': '#bc8cff' };
  
  const datasets = strategies.filter(s => s.daily_values && s.daily_values.length > 0).map(s => ({
    label: s.name,
    data: s.daily_values.map(d => d.value),
    borderColor: colors[s.name] || '#fff',
    backgroundColor: colors[s.name] + '22',
    fill: false,
    tension: 0.3,
    pointRadius: 0,
    borderWidth: 2,
  }));

  const labels = strategies[0].daily_values.map(d => d.date);

  chartInstance = new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { intersect: false, mode: 'index' },
      plugins: {
        legend: { labels: { color: '#8b949e', font: { size: 11 } } },
      },
      scales: {
        x: { ticks: { color: '#8b949e', maxTicksLimit: 10, font: { size: 10 } },
             grid: { color: '#30363d' } },
        y: { ticks: { color: '#8b949e', font: { size: 10 },
                      callback: v => '¥' + Math.round(v).toLocaleString() },
             grid: { color: '#30363d' } },
      },
    },
  });
}

function fmt(v) { return Math.round(v).toLocaleString(); }
load();
setInterval(load, 60000);
</script>
</body>
</html>
"""

# ─── HTML Dashboard ────────────────────────────────

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>面基·模拟盘 Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --text2: #8b949e; --green: #3fb950; --red: #f85149;
    --blue: #58a6ff; --yellow: #d29922; --accent: #2f81f7;
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: -apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:var(--bg); color:var(--text); padding:24px; }
  .container { max-width:1400px; margin:0 auto; }
  h1 { font-size:24px; font-weight:600; margin-bottom:4px; display:flex; align-items:center; gap:12px; }
  h1 span { font-size:14px; color:var(--text2); font-weight:400; }
  .updated { font-size:13px; color:var(--text2); margin-bottom:24px; }
  .grid { display:grid; gap:16px; }
  .grid-4 { grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); }
  .grid-2 { grid-template-columns:1fr 1fr; }
  .grid-3 { grid-template-columns:1fr 1fr 1fr; }
  @media(max-width:900px) { .grid-2,.grid-3 { grid-template-columns:1fr; } }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:20px; }
  .metric { display:flex; flex-direction:column; }
  .metric-label { font-size:13px; color:var(--text2); margin-bottom:4px; }
  .metric-value { font-size:28px; font-weight:700; }
  .metric-sub { font-size:13px; margin-top:2px; }
  .green { color:var(--green); } .red { color:var(--red); } .blue { color:var(--blue); } .yellow { color:var(--yellow); }
  .card-header { display:flex; justify-content:space-between; align-items:center;
                 margin-bottom:16px; padding-bottom:12px; border-bottom:1px solid var(--border); }
  .card-header h3 { font-size:16px; font-weight:600; }
  table { width:100%; border-collapse:collapse; font-size:14px; }
  th { text-align:left; padding:8px 6px; color:var(--text2); font-weight:500;
       border-bottom:1px solid var(--border); }
  td { padding:8px 6px; border-bottom:1px solid var(--border); }
  .tr-hover:hover { background:rgba(255,255,255,0.03); }
  .badge { display:inline-block; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:500; }
  .badge-buy { background:rgba(63,185,80,0.15); color:var(--green); }
  .badge-sell { background:rgba(248,81,73,0.15); color:var(--red); }
  .badge-win { background:rgba(63,185,80,0.2); color:var(--green); }
  .badge-loss { background:rgba(248,81,73,0.2); color:var(--red); }
  .chart-container { position:relative; height:280px; }
  .chart-container canvas { width:100% !important; height:100% !important; }
  .empty { text-align:center; padding:40px; color:var(--text2); }
  .positions-section { margin-top:24px; }
  .history-section { margin-top:24px; }
  .history-table { max-height:400px; overflow-y:auto; }
  .history-table::-webkit-scrollbar { width:6px; }
  .history-table::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }
  a { color:var(--accent); text-decoration:none; }
  a:hover { text-decoration:underline; }
  .mini-chart { width:80px; height:30px; display:inline-block; }
  .text-right { text-align:right; }
</style>
</head>
<body>
<div class="container">
  <h1>📊 面基·模拟盘 <span>Forward‑Testing</span></h1>
  <div class="updated" id="updatedAt"></div>

  <div class="grid grid-4" id="summaryCards"></div>

  <div class="grid grid-2" style="margin-top:24px;">
    <div class="card">
      <div class="card-header"><h3>📈 净值曲线</h3><span id="totalReturn" class="blue"></span></div>
      <div class="chart-container"><canvas id="equityChart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-header"><h3>🏛️ 资产分布</h3></div>
      <div class="chart-container"><canvas id="allocationChart"></canvas></div>
    </div>
  </div>

  <div class="card positions-section">
    <div class="card-header"><h3>📋 持仓明细</h3><span id="positionCount"></span></div>
    <div class="table-wrapper" style="overflow-x:auto;"><table>
      <thead><tr>
        <th>标的</th><th>名称</th><th>数量</th><th>成本</th><th>现价</th><th>市值</th>
        <th>盈亏</th><th>收益率</th><th>持仓</th><th>止损价</th><th>建仓评分</th>
      </tr></thead>
      <tbody id="positionsBody"></tbody>
    </table></div>
    <div class="empty" id="positionsEmpty" style="display:none;">暂无持仓 — 等待建仓信号</div>
  </div>

  <div class="card history-section">
    <div class="card-header"><h3>📜 交易记录</h3><span id="historyCount"></span></div>
    <div class="history-table"><table>
      <thead><tr><th>时间</th><th>标的</th><th>名称</th><th>操作</th><th>价格</th><th>数量</th><th>盈亏</th><th>原因</th></tr></thead>
      <tbody id="historyBody"></tbody>
    </table></div>
  </div>
</div>

<script>
let equityChartInstance = null;
let allocationChartInstance = null;

async function load() {
  try {
    const r = await fetch('/api/portfolio');
    const data = await r.json();
    render(data);
  } catch(e) {
    document.body.innerHTML = `<div class="container"><p style="padding:40px;color:var(--red);">⚠️ 数据加载失败: ${e.message}</p></div>`;
  }
}

function render(data) {
  const s = data.summary;
  document.getElementById('updatedAt').textContent = `最近更新: ${data.updated_at} · 累计交易 ${data.history_count} 笔`;

  // Summary cards
  document.getElementById('summaryCards').innerHTML = `
    <div class="card metric">
      <span class="metric-label">总资产 (NAV)</span>
      <span class="metric-value">¥${fmt(s.total_value)}</span>
      <span class="metric-sub ${s.total_return >= 0 ? 'green' : 'red'}">${fmtPct(s.total_return)}</span>
    </div>
    <div class="card metric">
      <span class="metric-label">现金</span>
      <span class="metric-value" style="font-size:22px;">¥${fmt(s.cash)}</span>
      <span class="metric-sub">占比 ${s.cash_pct}%</span>
    </div>
    <div class="card metric">
      <span class="metric-label">持仓市值</span>
      <span class="metric-value" style="font-size:22px;">¥${fmt(s.position_value)}</span>
      <span class="metric-sub">${s.position_count} 只 · 仓位 ${s.position_pct}%</span>
    </div>
    <div class="card metric">
      <span class="metric-label">累计盈亏</span>
      <span class="metric-value ${s.total_pnl >= 0 ? 'green' : 'red'}">${s.total_pnl >= 0 ? '+' : ''}¥${fmt(s.total_pnl)}</span>
      <span class="metric-sub">已实现: ${s.realized_pnl >= 0 ? '+' : ''}¥${fmt(s.realized_pnl)} | 浮动: ${s.unrealized_pnl >= 0 ? '+' : ''}¥${fmt(s.unrealized_pnl)}</span>
    </div>
  `;

  // Return
  document.getElementById('totalReturn').textContent = `${s.total_return >= 0 ? '+' : ''}${s.total_return.toFixed(2)}%`;

  // Equity chart
  renderEquityChart(data.chart);

  // Allocation chart
  renderAllocationChart(s);

  // Positions
  document.getElementById('positionCount').textContent = `${s.positions.length} 只`;
  if (s.positions.length === 0) {
    document.getElementById('positionsBody').innerHTML = '';
    document.getElementById('positionsEmpty').style.display = 'block';
  } else {
    document.getElementById('positionsEmpty').style.display = 'none';
    const rows = s.positions.map(p => {
      const stopP = p.stop_loss || p.entry_price * 0.92;
      const warn = p.current_price <= stopP;
      return `<tr class="tr-hover">
        <td><strong>${p.symbol}</strong></td>
        <td>${p.name}</td>
        <td>${fmtNum(p.quantity)}</td>
        <td>¥${p.entry_price.toFixed(2)}</td>
        <td style="color:${p.pnl_pct >= 0 ? 'var(--green)' : 'var(--red)'}">¥${p.current_price.toFixed(2)}</td>
        <td>¥${fmt(p.market_value)}</td>
        <td class="${p.pnl >= 0 ? 'green' : 'red'}">${p.pnl >= 0 ? '+' : ''}¥${fmt(p.pnl)}</td>
        <td class="${p.pnl_pct >= 0 ? 'green' : 'red'}">${fmtPct(p.pnl_pct)}</td>
        <td>${p.hold_days}d</td>
        <td${warn ? ' style="color:var(--red);font-weight:600;"' : ''}>¥${stopP.toFixed(2)}${warn ? ' 🚨' : ''}</td>
        <td>${p.entry_score != null ? p.entry_score.toFixed(1) + '分' : '—'}</td>
      </tr>`;
    }).join('');
    document.getElementById('positionsBody').innerHTML = rows;
  }

  // History
  const h = data.history;
  document.getElementById('historyCount').textContent = `${data.history_count} 笔`;
  if (h.length === 0) {
    document.getElementById('historyBody').innerHTML = '<tr><td colspan="8" class="empty">暂无交易记录</td></tr>';
  } else {
    const rows = h.slice(0, 200).map(t => {
      const isBuy = t.action === '买入' || t.action === '加仓';
      const badgeClass = isBuy ? 'badge-buy' : (t.is_win === true ? 'badge-win' : (t.is_win === false ? 'badge-loss' : 'badge-sell'));
      return `<tr class="tr-hover">
        <td style="font-size:12px;color:var(--text2)">${t.time.slice(0, 16)}</td>
        <td>${t.symbol}</td>
        <td>${t.name}</td>
        <td><span class="badge ${badgeClass}">${t.action}</span></td>
        <td>${t.price ? '¥' + t.price.toFixed(2) : '—'}</td>
        <td>${fmtNum(t.quantity)}</td>
        <td class="${t.pnl > 0 ? 'green' : (t.pnl < 0 ? 'red' : '')}">${t.pnl_str}</td>
        <td style="font-size:12px;color:var(--text2)">${(t.reason || '').slice(0, 30)}</td>
      </tr>`;
    }).join('');
    document.getElementById('historyBody').innerHTML = rows;
  }
}

function renderEquityChart(chartData) {
  if (equityChartInstance) equityChartInstance.destroy();
  const ctx = document.getElementById('equityChart').getContext('2d');

  if (!chartData || !chartData.labels || !chartData.values || chartData.labels.length === 0) {
    chartData = { labels: ['启动'], values: [1000000] };
  }

  equityChartInstance = new Chart(ctx, {
    type: 'line', data: {
      labels: chartData.labels,
      datasets: [{
        label: '总资产',
        data: chartData.values,
        borderColor: '#2f81f7',
        backgroundColor: (ctx) => {
          const g = ctx.chart.ctx.createLinearGradient(0, 0, 0, 280);
          g.addColorStop(0, 'rgba(47,129,247,0.15)');
          g.addColorStop(1, 'rgba(47,129,247,0)');
          return g;
        },
        fill: true, tension: 0.3, pointRadius: 2, borderWidth: 2,
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        x: { grid: { color: 'rgba(48,54,61,0.3)' }, ticks: { color: '#8b949e', maxTicksLimit: 12, font: { size: 11 } } },
        y: { grid: { color: 'rgba(48,54,61,0.3)' }, ticks: { color: '#8b949e', callback: v => '¥' + v.toLocaleString(), font: { size: 11 } } },
      },
      interaction: { mode: 'nearest', intersect: false },
    }
  });
}

function renderAllocationChart(s) {
  if (allocationChartInstance) allocationChartInstance.destroy();
  const ctx = document.getElementById('allocationChart').getContext('2d');

  const labels = ['现金', '持仓'];
  const values = [s.cash, s.position_value];
  const colors = ['#58a6ff', '#3fb950'];

  allocationChartInstance = new Chart(ctx, {
    type: 'doughnut', data: {
      labels,
      datasets: [{ data: values, backgroundColor: colors, borderWidth: 0, hoverOffset: 8 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      cutout: '60%',
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#8b949e', padding: 16, font: { size: 12 }, usePointStyle: true, pointStyle: 'circle' },
        },
        tooltip: {
          callbacks: {
            label: ctx => {
              const total = ctx.dataset.data.reduce((a, b) => a + b, 0);
              return ` ${ctx.label}: ¥${ctx.raw.toLocaleString()} (${(ctx.raw / total * 100).toFixed(1)}%)`;
            },
          },
        },
      },
    },
  });
}

function fmt(v) { return Math.round(v).toLocaleString(); }
function fmtNum(v) { return (v || 0).toLocaleString(); }
function fmtPct(v) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }

load();
// Auto refresh every 60 seconds
setInterval(load, 60000);
</script>
</body>
</html>
"""


@app.get("/api/comparison")
def get_comparison():
    """三方策略对比数据"""
    try:
        from investment_system.analysis.strategy_comparison import run_comparison
        result = run_comparison(days=60)
        # 附加实时信号
        sig_path = ROOT / "data" / "trading_signals.json"
        if sig_path.exists():
            with open(sig_path) as f:
                result["live_signals"] = json.load(f)
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/signals")
def api_signals():
    """今日实时信号"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if sig_path.exists():
        with open(sig_path) as f:
            data = json.load(f)
        return data
    return {"error": "no signals yet today", "signals": []}


@app.get("/api/realtime")
def api_realtime():
    """实时行情（东财+A股+yfinance港美股）"""
    try:
        from scripts.realtime_price import get_realtime_summary
        return get_realtime_summary()
    except Exception as e:
        return {"error": str(e), "realtime": {}}


@app.get("/api/realtime/positions")
def api_realtime_positions():
    """仅返回持仓实时行情（轻量）"""
    try:
        from scripts.realtime_price import get_all_realtime
        return {"realtime": get_all_realtime(), "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/metrics")
def api_metrics():
    """绩效指标 (OSkhQuant风格：Sortino/Alpha/Beta/连续盈亏)"""
    try:
        book = load_shadow()
        summary = build_summary(book)
        history = book.get("history", [])

        # 计算绩效指标
        import numpy as np

        # 净值序列
        capital = book.get("capital", 1000000)
        equity_values = [capital]
        for h in history:
            if h.get("action") == "卖出" and h.get("pnl") is not None:
                equity_values.append(equity_values[-1] + h["pnl"])
        final_value = summary["total_value"]
        equity_values.append(final_value)

        equity_arr = np.array(equity_values, dtype=float)
        n_periods = len(equity_arr) - 1

        if n_periods >= 2:
            returns = (equity_arr[1:] / equity_arr[:-1]) - 1
            # Sharpe (0% RF)
            sharpe = float(np.mean(returns)) / float(np.std(returns)) * np.sqrt(252) if float(np.std(returns)) > 0 else 0
            # Sortino
            downside = returns[returns < 0]
            dstd = float(np.std(downside)) if len(downside) > 0 else 0.001
            sortino = float(np.mean(returns)) / dstd * np.sqrt(252) if dstd > 0 else 0
            # 最大回撤
            running_max = np.maximum.accumulate(equity_arr)
            drawdowns = (equity_arr - running_max) / running_max
            max_dd = float(-np.min(drawdowns))
            # 连续盈亏
            win_streak = 0
            loss_streak = 0
            max_win_streak = 0
            max_loss_streak = 0
            for r in returns:
                if r > 0:
                    win_streak += 1
                    loss_streak = 0
                    max_win_streak = max(max_win_streak, win_streak)
                else:
                    loss_streak += 1
                    win_streak = 0
                    max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            sharpe = sortino = max_dd = max_win_streak = max_loss_streak = 0

        # 标的数
        total_trades = len([h for h in history if h.get("action") == "卖出"])
        wins = len([h for h in history if h.get("pnl") is not None and h["pnl"] > 0])

        return {
            "sharpe_ratio": round(sharpe, 4),
            "sortino_ratio": round(sortino, 4),
            "max_drawdown_pct": round(max_dd * 100, 2),
            "total_return_pct": summary["total_return"],
            "annualized_return_pct": summary["total_return"],  # simplified
            "win_rate_pct": round(wins / total_trades * 100, 1) if total_trades > 0 else 0,
            "total_trades": total_trades,
            "max_win_streak": max_win_streak,
            "max_loss_streak": max_loss_streak,
            "position_count": summary["position_count"],
            "capital": summary["capital"],
            "total_value": summary["total_value"],
        }
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/simulated")
def api_simulated():
    """三个策略模拟盘全方位数据"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if not sig_path.exists():
        return {"error": "no simulated data yet", "portfolios": {}}

    with open(sig_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    positions = data.get("positions", {})
    signals = data.get("signals", [])

    # 各策略汇总
    result = {}
    strategy_labels = {
        "faceji": {"name": "面基", "color": "#58a6ff", "style": "面基(评分+趋势+Kelly+SQ风控)"},
        "silverquant": {"name": "SilverQuant", "color": "#3fb950", "style": "组件化(评分建仓+4层风控)"},
        "tradingagents": {"name": "TradingAgents", "color": "#bc8cff", "style": "辩论制(Kelly动态+技术融合)"},
    }

    for sname in ["faceji", "silverquant", "tradingagents"]:
        pf = portfolios.get(sname, {})
        pos = positions.get(sname, {})
        s_sigs = [s for s in signals if s["strategy"] == sname]
        label = strategy_labels.get(sname, {})

        cash = pf.get("cash", 1000000)
        invested = pf.get("total_invested", 0)
        total_value = cash + invested
        total_pnl = total_value - 1000000
        total_return = total_pnl / 1000000 * 100

        pos_list = []
        for sym, pd in pos.items():
            entry = pd.get("entry_price", 0)
            current = pd.get("current_price", entry)
            qty = pd.get("quantity", 0)
            cost = entry * qty
            mkt_val = current * qty
            pnl = mkt_val - cost
            pnl_pct = pd.get("pnl_pct", 0)
            pos_list.append({
                "symbol": sym, "name": get_name(sym),
                "entry_price": entry, "current_price": current,
                "quantity": qty, "cost": cost, "market_value": mkt_val,
                "pnl": round(pnl, 2), "pnl_pct": pnl_pct,
                "entry_date": pd.get("entry_date", ""),
                "reason": pd.get("reason", f"建仓评分{pd.get('entry_score','?')}分"),
                "stop_loss": round(entry * 0.92, 2),
                "peak_price": pd.get("peak_price", entry),
            })

        result[sname] = {
            "label": label.get("name", sname),
            "color": label.get("color", "#fff"),
            "style": label.get("style", ""),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": len(pos),
            "history_count": pf.get("history_count", 0),
            "positions": pos_list,
            "signals": [s for s in signals if s["strategy"] == sname],
        }

    return {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "simulated_trades": data.get("simulated_trades", 0),
        "portfolios": result,
        "user_signals": signals,
    }


# ─── V2 API 扩展 (Dashboard 7面板) ──────────────────


@app.get("/api/v2/pool")
def api_v2_pool():
    """三层票池数据 (watch/monitor/deep) + 名称+产业链映射"""
    pool_dir = ROOT / "data" / "pool"
    result = {}
    for tier in ("watch", "monitor", "deep"):
        path = pool_dir / f"{tier}.json"
        if path.exists():
            with open(path) as f:
                raw = f.read().strip()
                items = json.loads(raw) if raw else []
        else:
            items = []
        # 加名称和产业链
        for item in items:
            sym = item.get("symbol", "")
            item["name"] = get_name(sym)
            item["chain"] = _guess_chain(sym)
        result[tier] = items
    return result


@app.get("/api/v2/etf")
def api_v2_etf():
    """ETF组合建议"""
    path = ROOT / "data" / "etf_portfolio.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


@app.get("/api/v2/news")
def api_v2_news():
    """板块新闻 — 优先 news_cache.json，回退 news_score_offset.json"""
    cache_path = ROOT / "data" / "news_cache.json"
    if cache_path.exists():
        with open(cache_path) as f:
            cache_data = json.load(f)
            if cache_data and cache_data.get("categories"):
                # 格式化为面板友好结构
                categories = cache_data.get("categories", {})
                summary = cache_data.get("summary", "")
                items = []
                for cat_name, cat_entries in categories.items():
                    if isinstance(cat_entries, list):
                        for entry in cat_entries:
                            items.append({"category": cat_name, "content": str(entry)[:200]})
                return {
                    "total": cache_data.get("total", 0),
                    "timestamp": cache_data.get("timestamp", ""),
                    "summary": summary,
                    "items": items[:50],
                }
    # 回退
    fallback_path = ROOT / "data" / "news_score_offset.json"
    if fallback_path.exists():
        with open(fallback_path) as f:
            return json.load(f)
    return {}


@app.get("/api/v2/reports")
def api_v2_reports():
    """日报链接列表"""
    path = ROOT / "data" / "daily_report_links.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


UNIFIED_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>面基·三源融合模拟盘</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.7/dist/chart.umd.min.js"></script>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
:root { --bg:#0d1117; --card:#161b22; --card2:#1c2333; --border:#30363d;
        --text:#e6edf3; --text2:#8b949e; --green:#3fb950; --red:#f85149;
        --blue:#58a6ff; --yellow:#d29922; --orange:#d9600e; --purple:#bc8cff; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:var(--bg); color:var(--text); padding:20px; }
.container { max-width:1500px; margin:0 auto; }
h1 { font-size:22px; margin-bottom:4px; }
.subtitle { color:var(--text2); font-size:13px; margin-bottom:20px; }
.nav { display:flex; gap:12px; margin-bottom:20px; font-size:13px; }
.nav a { color:var(--blue); text-decoration:none; padding:4px 12px;
         border:1px solid var(--border); border-radius:6px; }
.nav a:hover { background:var(--card2); }
.nav a.active { background:var(--blue); color:#fff; border-color:var(--blue); }
.grid-3 { display:grid; grid-template-columns:repeat(3,1fr); gap:16px; }
@media(max-width:900px){ .grid-3 { grid-template-columns:1fr; } }
.card { background:var(--card); border:1px solid var(--border);
        border-radius:10px; padding:16px; margin-bottom:16px; }
.card-header { display:flex; justify-content:space-between; align-items:center;
               margin-bottom:12px; }
.card-header h3 { font-size:15px; }
.strategy-panel { border-top:3px solid transparent; }
.metric { margin:4px 0; display:flex; justify-content:space-between; }
.metric-l { color:var(--text2); font-size:12px; }
.metric-v { font-size:14px; font-weight:600; }
.metric-big { font-size:26px; font-weight:700; margin:8px 0; }
.green { color:var(--green); } .red { color:var(--red); }
.chart-container { height:200px; margin:12px 0; }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { text-align:left; padding:6px 4px; color:var(--text2);
     border-bottom:1px solid var(--border); font-weight:500; }
td { padding:5px 4px; border-bottom:1px solid var(--border); }
.tr-hover:hover { background:var(--card2); }
.badge { display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; }
.badge-buy { background:#1a3a2a; color:var(--green); }
.badge-sell { background:#3a1a1a; color:var(--red); }
.badge-win { background:#1a3a2a; color:var(--green); }
.badge-loss { background:#3a1a1a; color:var(--red); }
.empty { color:var(--text2); padding:20px; text-align:center; }
.scroll { max-height:300px; overflow-y:auto; }
.tag { display:inline-block; padding:2px 8px; border-radius:4px;
        font-size:10px; font-weight:500; margin-left:6px; }
</style>
</head>
<body>
<div class="container">
  <div class="nav">
    <a href="#" class="active" onclick="return switchTab(event,'dashboard')">📊 模拟盘</a>
    <a href="#" onclick="return switchTab(event,'comparison')">📈 回测对比</a>
    <a href="#" onclick="return switchTab(event,'pool')">🎯 票池</a>
    <a href="#" onclick="return switchTab(event,'etf')">📦 ETF</a>
    <a href="#" onclick="return switchTab(event,'news')">📰 新闻</a>
    <a href="#" onclick="return switchTab(event,'reports')">📋 日报</a>
  </div>

  <h1>面基 · 三源融合模拟盘</h1>
  <div class="subtitle" id="runInfo">加载中...</div>

  <div class="grid-3" id="strategyPanels"></div>

  <div class="card" id="metricsPanel" style="margin-bottom:16px">
    <div class="card-header"><h3>📊 绩效指标 (OSkhQuant)</h3></div>
    <div id="metricsBody" class="grid-3" style="display:grid;gap:12px;padding:8px 0"></div>
  </div>

  <div class="card" id="userSignals" style="display:none">
    <div class="card-header"><h3>执行建议（今日优先级）</h3></div>
    <div id="userSignalsBody"></div>
  </div>

  <!-- ======== 回测对比面板 ======== -->
  <div class="card" id="tab-comparison" style="display:none">
    <div class="card-header"><h3>📈 三方策略回测对比</h3></div>
    <div id="comparisonBody" style="font-size:13px;">
      <div class="empty">加载中...</div>
    </div>
  </div>

  <!-- ======== 票池面板 ======== -->
  <div class="card" id="tab-pool" style="display:none">
    <div class="card-header"><h3>🎯 三层票池</h3></div>
    <div id="poolBody" style="font-size:13px;"></div>
  </div>

  <!-- ======== ETF面板 ======== -->
  <div class="card" id="tab-etf" style="display:none">
    <div class="card-header"><h3>📦 ETF组合建议</h3></div>
    <div id="etfBody" style="font-size:13px;"></div>
  </div>

  <!-- ======== 新闻面板 ======== -->
  <div class="card" id="tab-news" style="display:none">
    <div class="card-header"><h3>📰 板块新闻</h3></div>
    <div id="newsBody" style="font-size:13px;"></div>
  </div>

  <!-- ======== 日报面板 ======== -->
  <div class="card" id="tab-reports" style="display:none">
    <div class="card-header"><h3>📋 日报链接</h3></div>
    <div id="reportsBody" style="font-size:13px;"></div>
  </div>
</div>

<script>
async function load() {
  try {
    const r = await fetch('/api/simulated');
    const data = await r.json();
    if (data.error) {
      document.getElementById('strategyPanels').innerHTML = '<div class="card">❌ ' + data.error + '</div>';
      return;
    }

    // 加载绩效指标
    loadMetrics();

    document.getElementById('runInfo').textContent =
      data.date + ' | ' + data.generated_at + ' | 模拟交易 ' + data.simulated_trades + ' 笔';

    // 三大策略面板
    document.getElementById('strategyPanels').innerHTML =
      ['faceji','silverquant','tradingagents'].map(sname => {
        const p = data.portfolios && data.portfolios[sname];
        if (!p) return '<div class="card">' + sname + ' 暂无数据</div>';
      const retCls = p.total_return >= 0 ? 'green' : 'red';
      const posRows = p.positions.map(pos => {
        const pnlCls = pos.pnl_pct >= 0 ? 'green' : 'red';
        const stopLoss = pos.stop_loss || pos.entry_price * 0.92;
        const nearStop = pos.current_price <= stopLoss * 1.05;
        return `<tr class="tr-hover">
          <td><strong>${pos.symbol}</strong></td>
          <td style="color:var(--text2)">${pos.name||pos.symbol}</td>
          <td>${fmtNum(pos.quantity)}</td>
          <td>${pos.entry_price.toFixed(2)}</td>
          <td class="${pnlCls}">${pos.current_price.toFixed(2)}</td>
          <td class="${pnlCls}">${fmtPct(pos.pnl_pct)}</td>
          <td>${pos.entry_date||'—'}</td>
          <td style="font-size:11px;color:var(--text2)" title="${pos.reason||''}">${(pos.reason||'').slice(0,20)}</td>
          <td style="font-size:11px;${nearStop?'color:var(--red);font-weight:600':''}">${stopLoss.toFixed(2)}${nearStop?' 🚨':''}</td>
        </tr>`;
      }).join('');

      const sigRows = p.signals.map(s =>
        `<tr class="tr-hover"><td><span class="badge ${s.action==='BUY'?'badge-buy':'badge-sell'}">${s.action}</span></td>
         <td>${s.symbol}</td><td>${s.price.toFixed(2)}</td><td style="font-size:11px;color:var(--text2)">${s.reason}</td></tr>`
      ).join('');

      return `<div class="card strategy-panel" style="border-top-color:${p.color}">
        <div class="card-header">
          <h3><span style="color:${p.color}">●</span> ${p.label}</h3>
          <span style="font-size:11px;color:var(--text2)">${p.style}</span>
        </div>
        <div class="metric-big ${retCls}">${p.total_return >= 0 ? '+':''}${p.total_return.toFixed(2)}%</div>
        <div class="metric"><span class="metric-l">总资产</span><span class="metric-v">¥${fmt(p.total_value)}</span></div>
        <div class="metric"><span class="metric-l">现金</span><span class="metric-v">¥${fmt(p.cash)}</span></div>
        <div class="metric"><span class="metric-l">已投</span><span class="metric-v">¥${fmt(p.invested)}</span></div>
        <div class="metric"><span class="metric-l">仓位</span><span class="metric-v">${p.position_count} 只</span></div>
        <div style="margin-top:12px;font-size:12px;color:var(--text2)">📋 持仓明细</div>
        <div class="scroll" style="max-height:220px">
          <table>
            <tr><th>代码</th><th>名称</th><th>数量</th><th>成本</th><th>现价</th><th>收益</th><th>持仓</th><th>理由</th><th>止损</th></tr>
            ${posRows || '<tr><td colspan="9" class="empty">空仓</td></tr>'}
          </table>
        </div>
        <div style="margin-top:12px;font-size:12px;color:var(--text2)">🔔 今日信号</div>
        <div class="scroll" style="max-height:120px">
          <table>
            <tr><th>操作</th><th>代码</th><th>价格</th><th>理由</th></tr>
            ${sigRows || '<tr><td colspan="4" class="empty">无信号</td></tr>'}
          </table>
        </div>
      </div>`;
    }).join('');

  // 用户建议信号
  if (data.user_signals && data.user_signals.length > 0) {
    document.getElementById('userSignals').style.display = 'block';
    const rows = data.user_signals.map(s => {
      const pct = s.priority === 'HIGH' ? '🔴' : (s.priority === 'MED' ? '🟡' : '⚪');
      return `<tr class="tr-hover">
        <td>${pct} ${s.priority}</td>
        <td><span class="badge ${s.action==='BUY'?'badge-buy':'badge-sell'}">${s.action}</span></td>
        <td>${s.symbol}</td>
        <td>${s.name}</td>
        <td>¥${s.price.toFixed(2)}</td>
        <td style="font-size:11px;color:var(--text2)">${s.reason}</td>
      </tr>`;
    }).join('');
    document.getElementById('userSignalsBody').innerHTML =
      `<table><tr><th>优先级</th><th>操作</th><th>代码</th><th>名称</th><th>价格</th><th>理由</th></tr>${rows}</table>`;
  }
  } catch(e) {
    document.getElementById('strategyPanels').innerHTML = '<div class="card" style="color:var(--red)">⚠️ ' + e.message + '</div>';
  }
}

function fmt(v) { return Math.round(v).toLocaleString(); }
function fmtNum(v) { return (v || 0).toLocaleString(); }
function fmtPct(v) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
load();
async function loadMetrics() {
  try {
    const r = await fetch('/api/metrics');
    const m = await r.json();
    if (m.error) return;
    const metrics = [
      {label:'Sharpe',val:m.sharpe_ratio.toFixed(2),color:m.sharpe_ratio>=1?'var(--green)':m.sharpe_ratio>=0?'var(--yellow)':'var(--red)'},
      {label:'Sortino',val:m.sortino_ratio.toFixed(2),color:m.sortino_ratio>=1?'var(--green)':m.sortino_ratio>=0?'var(--yellow)':'var(--red)'},
      {label:'最大回撤',val:'-'+m.max_drawdown_pct.toFixed(2)+'%',color:'var(--red)'},
      {label:'总收益',val:(m.total_return_pct>=0?'+':'')+m.total_return_pct.toFixed(2)+'%',color:m.total_return_pct>=0?'var(--green)':'var(--red)'},
      {label:'胜率',val:m.win_rate_pct+'% ('+m.total_trades+'笔)',color:'var(--text)'},
      {label:'连胜/连败',val:m.max_win_streak+'/'+m.max_loss_streak,color:'var(--text)'},
      {label:'持仓数',val:m.position_count+'只',color:'var(--text)'},
      {label:'总资产',val:'¥'+Math.round(m.total_value).toLocaleString(),color:'var(--text)'},
    ];
    document.getElementById('metricsBody').innerHTML = metrics.map(m =>
      '<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:8px 12px;text-align:center">'+
        '<div style="font-size:11px;color:var(--text2);margin-bottom:4px">'+m.label+'</div>'+
        '<div style="font-size:18px;font-weight:700;color:'+m.color+'">'+m.val+'</div>'+
      '</div>'
    ).join('');
  } catch(e) {}
}
loadMetrics();
setInterval(load, 120000);

// ─── 7面板 Tab 切换 ─────────────────────────
function switchTab(ev, tab) {
  ev.preventDefault();
  // 更新 nav active 状态
  document.querySelectorAll('.nav a').forEach(a => a.classList.remove('active'));
  ev.currentTarget.classList.add('active');

  // 显示/隐藏面板
  const sections = ['tab-pool','tab-etf','tab-news','tab-reports','tab-comparison'];
  const mainEls = [
    document.getElementById('strategyPanels'),
    document.getElementById('metricsPanel'),
    document.getElementById('userSignals'),
  ];
  sections.forEach(id => document.getElementById(id).style.display = 'none');
  mainEls.forEach(el => { if(el) el.style.display = 'none'; });

  if (tab === 'dashboard') {
    mainEls.forEach(el => { if(el) el.style.display = ''; });
    return;
  }

  const panel = document.getElementById('tab-'+tab);
  if (panel) panel.style.display = '';

  // 加载数据
  if (tab === 'pool') loadPool();
  else if (tab === 'etf') loadEtf();
  else if (tab === 'news') loadNews();
  else if (tab === 'reports') loadReports();
  else if (tab === 'comparison') loadComparison();
  return false;
}

async function loadPool() {
  const el = document.getElementById('poolBody');
  el.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const r = await fetch('/api/v2/pool');
    const data = await r.json();
    const tierNames = {'watch':'🔍 发现层 (评分>0.50)','monitor':'👀 盯住层 (评分>0.55 ≥1周)','deep':'🧠 深度层 (评分>0.6 ≥2周+不为清单通过)'};
    const tierColors = {'watch':'var(--blue)','monitor':'var(--yellow)','deep':'var(--green)'};
    let html = '';
    for (const tier of ['watch','monitor','deep']) {
      const items = data[tier] || [];
      html += `<div style="margin-bottom:20px;">
        <strong style="color:${tierColors[tier]};font-size:15px;">${tierNames[tier]||tier.toUpperCase()}</strong>
        <span style="color:var(--text2);font-size:12px;"> ${items.length} 只</span>`;
      if (items.length === 0) {
        html += '<div class="empty" style="padding:8px">暂无数据 — 需积累评分历史</div></div>';
        continue;
      }
      html += '<table><tr><th>代码</th><th>名称</th><th>链/行业</th><th>综合评分</th><th>质量</th><th>价值</th><th>成长</th><th>动量</th><th>低波</th><th>情绪</th><th>风险</th><th>加入日期</th><th>理由</th></tr>';
      items.forEach(i => {
        const sc = i.scores || {};
        const scoreDoc = '/score_explanation';
        html += `<tr class="tr-hover"><td><strong>${i.symbol}</strong></td>
          <td style="color:var(--text2)">${i.name||i.symbol}</td>
          <td style="font-size:11px;color:var(--yellow)">${i.chain||'—'}</td>
          <td style="color:${i.score>=0.5?'var(--green)':'var(--yellow)'}"><a href="${scoreDoc}" target="_blank" style="color:inherit;text-decoration:underline;text-decoration-style:dotted;" title="点击查看评分体系">${(i.score||0).toFixed(3)}</a></td>
          <td>${(sc.quality||0).toFixed(2)}</td><td>${(sc.value||0).toFixed(2)}</td>
          <td>${(sc.growth||0).toFixed(2)}</td><td>${(sc.momentum||0).toFixed(2)}</td>
          <td>${(sc.low_vol||0).toFixed(2)}</td><td>${(sc.sentiment||0).toFixed(2)}</td>
          <td>${(sc.risk||0).toFixed(2)}</td>
          <td style="font-size:11px;color:var(--text2)">${i.date_added||''}</td>
          <td style="font-size:11px;color:var(--text2)">${i.reason||''}</td></tr>`;
      });
      html += '</table></div>';
    }
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
  }
}

async function loadEtf() {
  const el = document.getElementById('etfBody');
  el.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const r = await fetch('/api/v2/etf');
    const data = await r.json();
    if (!data || Object.keys(data).length === 0) {
      el.innerHTML = '<div class="empty">暂无ETF组合数据</div>';
      return;
    }
    let html = '';
    // timing_portfolio
    if (data.timing_portfolio) {
      const tp = data.timing_portfolio;
      html += `<div style="margin-bottom:16px;"><strong style="color:var(--blue);font-size:15px;">▸ 趋势跟随组合 (MA20/MA60)</strong></div>`;
      html += buildEtfTable(tp.symbols || []);
    }
    // non_timing_portfolio
    if (data.non_timing_portfolio) {
      const nt = data.non_timing_portfolio;
      html += `<div style="margin-bottom:16px;"><strong style="color:var(--blue);font-size:15px;">▸ 风险平价组合 (季度再平衡)</strong></div>`;
      html += buildEtfTable(nt.symbols || []);
    }
    // combined
    if (data.combined && data.combined.length > 0) {
      html += `<div style="margin-bottom:16px;"><strong style="color:var(--green);font-size:15px;">▸ 合并建议</strong></div>`;
      html += buildEtfTable(data.combined);
    }
    if (data.timestamp) {
      html += `<div style="font-size:11px;color:var(--text2);text-align:right;">更新时间: ${data.timestamp}</div>`;
    }
    el.innerHTML = html || '<div class="empty">暂无ETF组合数据</div>';
  } catch(e) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
  }
}

function buildEtfTable(symbols) {
  if (!symbols || symbols.length === 0) return '<div class="empty">暂无数据</div>';
  const actionLabel = {BUY:'买入','SELL':'卖出',HOLD:'持有'};
  return '<table><tr><th>代码</th><th>名称</th><th>操作</th><th>权重</th><th>类型</th><th>理由</th></tr>' +
    symbols.map(s => {
      const act = s.action || 'HOLD';
      const cls = act==='BUY'?'badge-buy':(act==='SELL'?'badge-sell':'');
      return `<tr class="tr-hover"><td><strong>${s.etf_symbol}</strong></td>
        <td>${s.name||''}</td>
        <td><span class="badge ${cls}">${actionLabel[act]||act}</span></td>
        <td>${((s.weight||0)*100).toFixed(1)}%</td>
        <td style="font-size:11px;color:var(--text2)">${s.signal_type||''}</td>
        <td style="font-size:11px;color:var(--text2)">${s.reason||''}</td></tr>`;
    }).join('') + '</table>';
}

async function loadComparison() {
  const el = document.getElementById('comparisonBody');
  el.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const r = await fetch('/api/comparison');
    const data = await r.json();
    if (data.error) {
      el.innerHTML = `<div class="empty" style="color:var(--red)">❌ ${data.error}</div>`;
      return;
    }
    let html = `<div style="font-size:11px;color:var(--text2);margin-bottom:16px;">最后更新: ${data.run_date||''} | 分析周期: <strong>${data.days_analyzed||0}天</strong>`;
    if (data.note) {
      html += ` | <span style="color:var(--yellow)">${data.note}</span>`;
    }
    html += '</div>';
    html += '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;">';
    const strategies = [data.faceji, data.silverquant, data.tradingagents].filter(Boolean);
    const colors = {'faceji (面基)':'#58a6ff','silverquant (组件化)':'#3fb950','tradingagents (辩论制)':'#bc8cff'};
    strategies.forEach(s => {
      const retCls = s.total_return_pct >= 0 ? 'green' : 'red';
      html += `<div style="background:var(--card);border:1px solid var(--border);border-radius:8px;padding:16px;">
        <div style="font-size:15px;font-weight:600;margin-bottom:8px;"><span style="color:${colors[s.name]||'#fff'}">●</span> ${s.name}</div>
        <div style="font-size:28px;font-weight:700;margin:8px 0;color:${retCls==='green'?'var(--green)':'var(--red)'}">${s.total_return_pct>=0?'+':''}${s.total_return_pct}%</div>
        <div class="metric"><span class="metric-l">总资产</span><span class="metric-v">¥${fmt(s.value||0)}</span></div>
        <div class="metric"><span class="metric-l">已实现盈亏</span><span class="metric-v" style="color:${s.realized_pnl>=0?'var(--green)':'var(--red)'}">${s.realized_pnl>=0?'+':''}¥${fmt(s.realized_pnl||0)}</span></div>
        <div class="metric"><span class="metric-l">浮盈</span><span class="metric-v" style="color:${(s.unrealized_pnl||0)>=0?'var(--green)':'var(--red)'}">${(s.unrealized_pnl||0)>=0?'+':''}¥${fmt(s.unrealized_pnl||0)}</span></div>
        <div class="metric"><span class="metric-l">持仓</span><span class="metric-v">${s.positions||0} 只</span></div>
        <div class="metric"><span class="metric-l">交易次数</span><span class="metric-v">${s.total_trades||0} 笔</span></div>
        <div class="metric"><span class="metric-l">胜率</span><span class="metric-v">${s.win_rate||0}%</span></div>
        <div class="metric"><span class="metric-l">最大回撤</span><span class="metric-v" style="color:var(--red)">-${s.max_drawdown_pct||0}%</span></div>
      </div>`;
    });
    html += '</div>';

    // Trade history
    html += '<div style="margin-top:16px;"><h3 style="font-size:14px;margin-bottom:8px;">📋 最近交易</h3></div>';
    strategies.forEach(s => {
      const trades = (s.trades || []).slice(-10).reverse();
      html += `<div style="margin-bottom:12px;">
        <div style="font-size:13px;font-weight:500;margin-bottom:4px;color:${colors[s.name]||'#fff'}">${s.name}</div>
        <table><tr><th>日期</th><th>代码</th><th>操作</th><th>价格</th><th>盈亏</th></tr>`;
      if (trades.length === 0) {
        html += '<tr><td colspan="5" class="empty">暂无交易</td></tr>';
      } else {
        trades.forEach(tx => {
          const isBuy = tx.action === '买入' || tx.action === 'BUY';
          html += `<tr class="tr-hover">
            <td style="font-size:11px;color:var(--text2)">${tx.date||tx.time||''}</td>
            <td>${tx.symbol||''}</td>
            <td><span class="badge ${isBuy?'badge-buy':'badge-sell'}">${tx.action}</span></td>
            <td>¥${(tx.price||0).toFixed(2)}</td>
            <td class="${tx.pnl>0?'green':'red'}">${tx.pnl!=null ? (tx.pnl>0?'+':'')+'¥'+fmt(tx.pnl) : '—'}</td>
          </tr>`;
        });
      }
      html += '</table></div>';
    });
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
  }
}

async function loadNews() {
  const el = document.getElementById('newsBody');
  el.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const r = await fetch('/api/v2/news');
    const data = await r.json();
    if (!data || Object.keys(data).length === 0 || (data.total === 0 && !data.summary)) {
      el.innerHTML = '<div class="empty">暂无板块新闻数据 — 今日无显著新闻</div>';
      return;
    }
    let html = `<div style="font-size:11px;color:var(--text2);margin-bottom:8px;">📡 ${data.summary || ''} · 更新: ${data.timestamp || ''}</div>`;
    if (data.items && data.items.length > 0) {
      const catColors = {'宏观政策':'var(--blue)','市场动态':'var(--green)','大宗商品':'var(--yellow)','产业趋势':'var(--purple)','综合':'var(--text2)','产业消息':'var(--orange)'};
      html += data.items.map(item => {
        const catColor = catColors[item.category] || 'var(--text2)';
        return `<div style="padding:6px 0;border-bottom:1px solid var(--border);font-size:12px;">
          <span class="badge" style="background:${catColor}22;color:${catColor};font-size:10px;">${item.category}</span>
          <span style="margin-left:6px;">${item.content}</span>
        </div>`;
      }).join('');
    } else {
      html += '<div class="empty">暂无分类新闻条目</div>';
    }
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
  }
}

async function loadReports() {
  const el = document.getElementById('reportsBody');
  el.innerHTML = '<div class="empty">加载中...</div>';
  try {
    const r = await fetch('/api/v2/reports');
    const data = await r.json();
    if (!data || (Array.isArray(data) && data.length === 0) || (typeof data === 'object' && Object.keys(data).length === 0)) {
      el.innerHTML = '<div class="empty">暂无日报链接</div>';
      return;
    }
    let html = '';
    const items = Array.isArray(data) ? data : (data.links || data.items || [data]);
    if (items.length === 0) {
      el.innerHTML = '<div class="empty">暂无日报链接</div>';
      return;
    }
    html = '<table><tr><th>日期</th><th>标题</th><th>链接</th></tr>' +
      items.map(item => {
        const date = item.date || item.time || item.timestamp || '';
        const title = item.title || item.name || '日报';
        const link = item.link || item.url || item.href || '#';
        return `<tr class="tr-hover"><td style="font-size:12px;color:var(--text2)">${date}</td>
          <td>${title}</td>
          <td><a href="${link}" target="_blank" style="color:var(--blue)">📄 查看</a></td></tr>`;
      }).join('') + '</table>';
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">❌ 加载失败: ${e.message}</div>`;
  }
}
</script>
</body>
</html>
"""


@app.get("/")
@app.get("/dashboard")
def dashboard():
    return responses.HTMLResponse(UNIFIED_DASHBOARD_HTML)


@app.get("/comparison")
def comparison_page():
    return responses.HTMLResponse(COMPARISON_HTML)


# ─── 评分说明文档 ──────────────────────────────────


@app.get("/score_explanation")
def score_explanation():
    path = ROOT / "docs" / "score_explanation.md"
    if path.exists():
        content = path.read_text(encoding="utf-8")
        # Remove Python docstring markers
        content = content.replace('"""', '').strip()
        # Raw markdown in pre
        import html as _h
        escaped = _h.escape(content)
        html_page = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>面基·评分体系说明</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:monospace; background:#0d1117; color:#e6edf3; padding:20px; }}
pre {{ white-space:pre-wrap; word-break:break-word; font-size:13px; line-height:1.6; }}</style></head>
<body><pre>{escaped}</pre></body></html>"""
        return responses.HTMLResponse(html_page)
    return responses.HTMLResponse("<h1>文档未生成</h1><p>请先运行 python3 scripts/run_factor_daily.py</p>")


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8686
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")