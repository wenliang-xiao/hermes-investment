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
    <a href="/dashboard">← 模拟盘</a>
    <span style="color:var(--text2)">｜</span>
    <a href="/comparison" style="color:var(--orange);font-weight:600">三方策略对比</a>
    <a href="https://bytedance.feishu.cn/docx/Q3ojdDMNPoiRMMx6eppc0Pzkn9U" target="_blank">日报v9</a>
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
                "symbol": sym, "name": sym,
                "entry_price": entry, "current_price": current,
                "quantity": qty, "cost": cost, "market_value": mkt_val,
                "pnl": round(pnl, 2), "pnl_pct": pnl_pct,
                "entry_date": pd.get("entry_date", ""),
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
    <a href="/dashboard" class="active">模拟盘</a>
    <a href="/comparison">回测对比</a>
    <a href="https://bytedance.feishu.cn/docx/Q3ojdDMNPoiRMMx6eppc0Pzkn9U" target="_blank">日报v9</a>
  </div>

  <h1>面基 · 三源融合模拟盘</h1>
  <div class="subtitle" id="runInfo">加载中...</div>

  <div class="grid-3" id="strategyPanels"></div>

  <div class="card" id="userSignals" style="display:none">
    <div class="card-header"><h3>执行建议（今日优先级）</h3></div>
    <div id="userSignalsBody"></div>
  </div>
</div>

<script>
async function load() {
  const r = await fetch('/api/simulated');
  const data = await r.json();
  if (data.error) {
    document.getElementById('strategyPanels').innerHTML = '<div class="card">数据不可用</div>';
    return;
  }

  document.getElementById('runInfo').textContent =
    data.date + ' | ' + data.generated_at + ' | 模拟交易 ' + data.simulated_trades + ' 笔';

  // 三大策略面板
  document.getElementById('strategyPanels').innerHTML =
    ['faceji','silverquant','tradingagents'].map(sname => {
      const p = data.portfolios[sname];
      if (!p) return '';
      const retCls = p.total_return >= 0 ? 'green' : 'red';
      const posRows = p.positions.map(pos => {
        const pnlCls = pos.pnl_pct >= 0 ? 'green' : 'red';
        return `<tr class="tr-hover">
          <td>${pos.symbol}</td>
          <td>${pos.quantity}</td>
          <td>${pos.entry_price.toFixed(2)}</td>
          <td class="${pnlCls}">${pos.current_price.toFixed(2)}</td>
          <td class="${pnlCls}">${fmtPct(pos.pnl_pct)}</td>
          <td style="font-size:11px;color:var(--text2)">${pos.entry_date}</td>
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
        <div style="margin-top:12px;font-size:12px;color:var(--text2)">持仓明细</div>
        <div class="scroll" style="max-height:180px">
          ${posRows || '<div class="empty">空仓</div>'}
        </div>
        <div style="margin-top:12px;font-size:12px;color:var(--text2)">今日信号</div>
        <div class="scroll" style="max-height:120px">
          ${sigRows || '<div class="empty">无信号</div>'}
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
}

function fmt(v) { return Math.round(v).toLocaleString(); }
function fmtPct(v) { return (v >= 0 ? '+' : '') + v.toFixed(2) + '%'; }
load();
setInterval(load, 120000);
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


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8686
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")