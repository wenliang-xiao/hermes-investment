COMPARISON_HTML = """<!DOCTYPE html>
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
