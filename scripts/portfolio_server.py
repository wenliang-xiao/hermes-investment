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


@app.get("/")
@app.get("/dashboard")
def dashboard():
    return responses.HTMLResponse(DASHBOARD_HTML)


if __name__ == "__main__":
    import uvicorn
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8686
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")