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
    """Build portfolio value over time from history

    从每笔交易的 pnl 推算每日净值变化。
    策略初始资本 ×3 = ¥3,000,000（面基/SQ/TA 各 ¥1,000,000）。
    每日净值 = 初始总资本 + 截至该日的累计已实现 PnL。
    因为持仓字段可能不可靠，所以只从已平仓 pnl 推算。
    """
    capital = book.get("capital", 3000000)  # 三策略初始总资本
    history = book.get("history", [])
    # 历史最可能是倒序（newest first），但 pnl 累计不分方向
    # 按日期累积：daily_cumulative_pnl[t] = 该日及之前所有 pnl 之和
    daily_pnl = {}  # date -> sum of pnl for that date
    for h in history:
        pnl = h.get("pnl")
        time_str = h.get("time", "")
        date_part = time_str[:10] if time_str else ""
        if pnl is not None and date_part:
            daily_pnl[date_part] = daily_pnl.get(date_part, 0) + pnl

    # 累计净值序列
    sorted_dates = sorted(daily_pnl.keys())
    cumulative = capital
    points = []
    if sorted_dates:
        points.append({"date": sorted_dates[0], "value": capital})
    for d in sorted_dates:
        cumulative += daily_pnl[d]
        points.append({"date": d, "value": cumulative})

    # 加当前总值（可能含未平仓浮盈）
    summary = build_summary(book)
    final_val = summary.get("total_value", capital)
    points.append({"date": datetime.now().strftime("%Y-%m-%d"), "value": final_val})

    # 去重（同日期保留最后一条）
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


def _aggregate_strategy_portfolios():
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
        "capital": 3000000,  # 三策略各 ¥1,000,000 初始资本
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

  <!-- 行为诊断卡片 -->
  <div class="card behavior-section" id="behaviorCard" style="display:none;">
    <div class="card-header"><h3>🧠 行为诊断</h3><span class="updated-small" id="behaviorUpdated"></span></div>
    <div class="grid grid-4" id="behaviorMetrics" style="margin-top:12px;"></div>
    <div id="behaviorActions" style="margin-top:8px;padding:8px 12px;background:rgba(187,128,9,0.1);border-radius:6px;border-left:3px solid var(--yellow);"></div>
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

  // 🧠 Behavior diagnosis
  try {
    const br = await fetch('/api/behavior');
    if (br.ok) {
      const bd = await br.json();
      renderBehavior(bd);
    }
  } catch(e) { /* behavior card stays hidden */ }
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

function renderBehavior(bd) {
  const combined = bd.strategies?._combined;
  if (!combined) return;
  document.getElementById('behaviorCard').style.display = 'block';
  document.getElementById('behaviorUpdated').textContent = bd.generated_at || '';

  const metrics = [
    { label: '过度交易', value: combined.overtrading_index + 'x', detail: (combined.overtrading_detail||'').slice(0,30), color: combined.overtrading_index > 3 ? 'var(--red)' : combined.overtrading_index > 1.5 ? 'var(--yellow)' : 'var(--green)' },
    { label: '追涨分数', value: combined.chasing_score.toFixed(1), detail: (combined.chasing_detail||'').slice(0,30), color: combined.chasing_score > 5 ? 'var(--red)' : combined.chasing_score > 2 ? 'var(--yellow)' : 'var(--green)' },
    { label: '处置效应', value: combined.disposition_ratio.toFixed(2), detail: (combined.disposition_detail||'').slice(0,30), color: combined.disposition_ratio > 1.5 ? 'var(--red)' : 'var(--green)' },
    { label: '锚定指数', value: combined.anchoring_index.toFixed(2), detail: (combined.anchoring_detail||'').slice(0,30), color: combined.anchoring_index > 0.8 ? 'var(--red)' : 'var(--green)' },
  ];

  document.getElementById('behaviorMetrics').innerHTML = metrics.map(m =>
    '<div class="card metric" style="padding:12px;">' +
      '<span class="metric-label" style="font-size:13px;">' + m.label + '</span>' +
      '<span class="metric-value" style="color:' + m.color + ';font-size:22px;">' + m.value + '</span>' +
      '<span class="metric-sub" style="font-size:11px;color:var(--text2)">' + m.detail + '</span>' +
    '</div>'
  ).join('');

  const actions = combined.recommended_actions || [];
  if (actions.length > 0) {
    document.getElementById('behaviorActions').innerHTML =
      '<strong style="font-size:13px;">🎯 改善建议</strong><div style="margin-top:4px;font-size:12px;color:var(--text);">' +
      actions.slice(0, 3).map(a => '<div style="padding:2px 0;">• ' + a.slice(0, 80) + '</div>').join('') +
      '</div>';
  }
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
def get_comparison(days: int = 60):
    """三方策略对比数据 — 支持自定义天数"""
    try:
        from analysis.strategy_comparison import run_comparison
        result = run_comparison(days=min(max(days, 7), 365))
        sig_path = ROOT / "data" / "trading_signals.json"
        if sig_path.exists():
            with open(sig_path) as f:
                live = json.load(f)
            live["signals"], _dropped = _clean_signals(live.get("signals", []), "comparison")
            result["live_signals"] = live
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/signals")
def api_signals():
    """今日实时信号（第三层防护：过滤 price≤0）"""
    sig_path = ROOT / "data" / "trading_signals.json"
    if sig_path.exists():
        with open(sig_path) as f:
            data = json.load(f)
        data["signals"], _dropped = _clean_signals(data.get("signals", []), "api_signals")
        return data
    return {"error": "no signals yet today", "signals": []}


@app.get("/api/behavior")
def api_behavior():
    """行为诊断（四维度：处置效应/过度交易/追涨/锚定）"""
    path = ROOT / "data" / "behavior_diagnosis.json"
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"error": "no behavior diagnosis data yet", "strategies": {}}


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

        # shadow_account 为空时，从三策略模拟盘聚合（与 /api/portfolio 一致）
        if not book.get("positions") and book.get("cash", 0) >= 1000000:
            try:
                aggr = _aggregate_strategy_portfolios()
                if aggr:
                    book = aggr
            except Exception:
                pass
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


def _clean_signals(signals, context="signal"):
    """第三层防护：读路径过滤 price≤0 的毒信号"""
    if not signals:
        return signals, 0
    filtered = []
    dropped = 0
    for s in signals:
        p = s.get("price", 0)
        if p is None or p <= 0:
            dropped += 1
            continue
        filtered.append(s)
    if dropped:
        print(f"  🛡️ _clean_signals({context}): 过滤 {dropped}/{len(signals)} 条 price≤0 信号", flush=True)
    return filtered, dropped

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
    signals, _dropped = _clean_signals(data.get("signals", []), "api_simulated")

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

        # 每个策略的信号也要做 price=0 过滤
        s_sigs = []
        for s in signals:
            if s.get("strategy", "") == sname:
                s_sigs.append(s)
        # 再过滤一遍标的位置中 price=0 的（持仓中已平的无效标的）
        pos_list = [p for p in pos_list if p.get("current_price", 0) > 0]

        result[sname] = {
            "label": label.get("name", sname),
            "color": label.get("color", "#fff"),
            "style": label.get("style", ""),
            "cash": round(cash, 2),
            "invested": round(invested, 2),
            "total_value": round(total_value, 2),
            "total_pnl": round(total_pnl, 2),
            "total_return": round(total_return, 2),
            "position_count": sum(1 for p in pos_list if p.get("current_price", 0) > 0),
            "history_count": pf.get("history_count", 0),
            "positions": pos_list,
            "signals": s_sigs,
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
                categories = cache_data.get("categories", {})
                summary = cache_data.get("summary", "")
                ts = cache_data.get("timestamp", "")
                # 计算数据新鲜度
                days_stale = 999
                try:
                    from datetime import datetime as _dt
                    data_dt = _dt.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S") if "T" in ts else _dt.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
                    days_stale = (_dt.now() - data_dt).days
                except Exception:
                    pass
                freshness = "fresh" if days_stale < 1 else ("stale" if days_stale < 3 else "expired")
                items = []
                for cat_name, cat_entries in categories.items():
                    if isinstance(cat_entries, list):
                        for entry in cat_entries:
                            items.append({"category": cat_name, "content": str(entry)[:200]})
                return {
                    "total": cache_data.get("total", 0),
                    "timestamp": ts,
                    "days_stale": days_stale,
                    "freshness": freshness,
                    "summary": summary,
                    "items": items[:50],
                }
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


# ─── 风险分析 API ─────────────────────────────────


@app.get("/api/v2/backtest")
def api_v2_backtest():
    """回测历史列表"""
    from analysis.backtest_storage import list_results
    results = list_results()
    return {"count": len(results), "results": results}


@app.get("/api/v2/backtest/strategies")
def api_v2_backtest_strategies():
    """可用的回测策略列表"""
    return {
        "strategies": [
            {"key": "faceji", "label": "面基策略", "desc": "评分驱动+MA趋势+Kelly仓位+4层风控"},
            {"key": "silverquant", "label": "SilverQuant", "desc": "固定¥30K槽位+不为清单+4层风控"},
            {"key": "tradingagents", "label": "TradingAgents", "desc": "辩论制评分+Kelly仓位+3层风控"},
            {"key": "all", "label": "三策略对比", "desc": "同时运行三个策略对比"},
        ],
        "defaults": {
            "capital": 1000000,
            "days_range": [7, 30, 60, 90, 180, 365],
        }
    }


@app.get("/api/v2/backtest/custom")
def api_v2_backtest_custom(
    strategy: str = "faceji",
    start_date: str = "",
    end_date: str = "",
    symbols: str = "",
    capital: float = 1000000,
):
    """自定义回测 — 指定策略/时间范围/股票池

    参数:
        strategy: faceji / silverquant / tradingagents / all
        start_date: YYYY-MM-DD
        end_date: YYYY-MM-DD
        symbols: 逗号分隔的标的代码（空=WATCHLIST A股）
        capital: 初始资金
    """
    try:
        from analysis.strategy_comparison import run_comparison

        days = 60
        if start_date and end_date:
            try:
                from datetime import datetime as _dt
                d1 = _dt.strptime(start_date, "%Y-%m-%d")
                d2 = _dt.strptime(end_date, "%Y-%m-%d")
                days = max(7, (d2 - d1).days)
            except Exception:
                pass

        result = run_comparison(days=min(days, 365))

        if symbols:
            sym_list = [s.strip() for s in symbols.split(",") if s.strip()]
            if sym_list:
                result["custom_symbols"] = sym_list

        if strategy != "all":
            single = {}
            key = strategy if strategy in result else f"{strategy} (面基)"
            if key in result:
                single = result[key]
            elif strategy == "faceji":
                for k in result:
                    if "faceji" in k.lower():
                        single = result[k]
                        break
            elif strategy == "silverquant":
                for k in result:
                    if "silver" in k.lower():
                        single = result[k]
                        break
            elif strategy == "tradingagents":
                for k in result:
                    if "trading" in k.lower() or "agent" in k.lower():
                        single = result[k]
                        break
            if single:
                result["focused_strategy"] = single

        result["params"] = {
            "strategy": strategy,
            "start_date": start_date,
            "end_date": end_date,
            "symbols": symbols,
            "capital": capital,
            "days": days,
        }
        return result
    except Exception as e:
        return {"error": str(e)}


@app.get("/api/v2/backtest/{run_id}")
def api_v2_backtest_detail(run_id: str):
    """回测详情"""
    from analysis.backtest_storage import load_result
    result = load_result(run_id)
    if result is None:
        return {"error": f"run_id '{run_id}' not found"}
    return result


@app.get("/api/v2/portfolio/detail")
def api_v2_portfolio_detail():
    """模拟盘完整详情 — 持仓+交易历史+信号日志+因子分解"""
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"error": "no data", "date": "", "portfolios": {}, "trade_history": {}, "all_signals": []}

    with open(ts_path) as f:
        data = json.load(f)

    result = {
        "date": data.get("date", ""),
        "generated_at": data.get("generated_at", ""),
        "total_raw_signals": data.get("total_raw_signals", 0),
        "after_conflict_resolution": data.get("after_conflict_resolution", 0),
        "after_weekly_filter": data.get("after_weekly_filter", 0),
        "simulated_trades": data.get("simulated_trades", 0),
        "portfolios": data.get("portfolios", {}),
        "positions": data.get("positions", {}),
        "trade_history": data.get("trade_history", {}),
        "final_signals": data.get("signals", []),
        "all_signals": data.get("all_signals", []),
    }

    for strat_name, positions in result["positions"].items():
        for sym, pos in positions.items():
            pos["name"] = get_name(sym)

    return result


@app.get("/api/v2/portfolio/netvalue")
def api_v2_portfolio_netvalue():
    """净值曲线 — 从交易历史推算 + 沪深300基准"""
    ts_path = ROOT / "data" / "trading_signals.json"
    if not ts_path.exists():
        return {"error": "no data", "labels": [], "series": []}

    with open(ts_path) as f:
        data = json.load(f)

    portfolios = data.get("portfolios", {})
    trade_history = data.get("trade_history", {})

    series = []
    for strat_name, strat_data in portfolios.items():
        history = trade_history.get(strat_name, [])
        capital = strat_data.get("capital", 1000000)
        labels = []
        values = []
        current_value = capital
        for trade in history:
            trade_date = trade.get("date", "")
            if trade_date:
                labels.append(trade_date)
                pnl = trade.get("pnl", 0)
                if trade.get("action") == "卖出":
                    current_value += pnl
                values.append(round(current_value, 2))
        if labels:
            labels.append(datetime.now().strftime("%Y-%m-%d"))
            total_value = strat_data.get("total_value", capital)
            values.append(round(total_value, 2))

        series.append({
            "label": strat_data.get("label", strat_name),
            "name": strat_name,
            "labels": labels,
            "values": values,
            "total_return": strat_data.get("total_return", 0),
            "color": {"faceji": "#58a6ff", "silverquant": "#f0883e", "tradingagents": "#bc8cff"}.get(strat_name, "#7ee787"),
        })

    return {"labels": series[0]["labels"] if series else [], "series": series}


@app.get("/api/v2/pool/by_market")
def api_v2_pool_by_market():
    """票池按市场分组 — A股/港股/美股/ETF"""
    pool_dir = ROOT / "data" / "pool"
    result = {"a_share": {"watch": [], "monitor": [], "deep": []},
              "hk": {"watch": [], "monitor": [], "deep": []},
              "us": {"watch": [], "monitor": [], "deep": []},
              "etf": {"watch": [], "monitor": [], "deep": []}}

    for tier in ("watch", "monitor", "deep"):
        path = pool_dir / f"{tier}.json"
        if not path.exists():
            continue
        with open(path) as f:
            raw = f.read().strip()
            items = json.loads(raw) if raw else []
        for item in items:
            sym = item.get("symbol", "")
            item["name"] = get_name(sym)
            item["chain"] = _guess_chain(sym)
            market = _classify_market(sym)
            if market in result:
                result[market][tier].append(item)

    return result


@app.get("/api/v2/factor_explain")
def api_v2_factor_explain():
    """因子评分体系说明 — 7因子定义+计算方法+参考范围"""
    return {
        "engine": "factor_engine v4.0",
        "range": "[0, 1]",
        "method": "scipy rankdata 截面百分位 + 产业链中性化",
        "factors": [
            {"key": "quality", "label": "质量", "weight": 0.18,
             "subs": ["ROE", "毛利率", "资产负债率(反向)", "每股经营现金流", "净利率"],
             "desc": "盈利能力强、财务健康的公司"},
            {"key": "value", "label": "价值", "weight": 0.15,
             "subs": ["PE历史百分位(反向)", "PB(反向)", "PE_TTM(反向)"],
             "desc": "估值低于历史和同行的公司"},
            {"key": "growth", "label": "成长", "weight": 0.17,
             "subs": ["营收增速TTM", "净利增速TTM", "ROE加速度"],
             "desc": "营收和利润持续高增长的公司"},
            {"key": "momentum", "label": "动量", "weight": 0.15,
             "subs": ["20日回报", "60日回报", "120日回报"],
             "desc": "近期价格表现强势的公司"},
            {"key": "low_vol", "label": "低波", "weight": 0.12,
             "subs": ["20日年化波动率(反向)", "60日最大回撤(反向)"],
             "desc": "价格波动小、回撤小的公司"},
            {"key": "sentiment", "label": "情绪/资金", "weight": 0.10,
             "subs": ["20日成交量比", "20日换手率"],
             "desc": "市场关注度和技术信号"},
            {"key": "dividend", "label": "股息", "weight": 0.07,
             "subs": ["股息率"],
             "desc": "现金分红回报高的公司"},
            {"key": "risk", "label": "风险", "weight": 0.12,
             "subs": ["PE过高风险", "60日波动率"],
             "desc": "风险标记因子(仅用于信息输出，不参与综合分)"},
        ],
        "weight_system": {
            "method": "ICWeightSystem 三层融合",
            "layer1": "滚动IC/IR信噪比 (6个月窗口, 半衰期0.35)",
            "layer2": "宏观条件调整 (复苏/扩张/过热/衰退 × 8风格)",
            "layer3": "贝叶斯收缩 (shrink_target=3.0)",
            "final": "70% rolling_IC_base + 30% conditional_adjusted",
        },
        "signal_thresholds": {
            "STRONGBUY": ">= 0.63",
            "BUY": ">= 0.48",
            "HOLD": ">= 0.35",
            "SELL": ">= 0.25",
            "STRONGSELL": "< 0.25",
        },
    }


def _classify_market(symbol):
    """根据代码分类市场"""
    sym = str(symbol)
    if sym.endswith(".HK"):
        return "hk"
    if sym.endswith(".US") or sym in ("GOOGL", "AAPL", "AMZN", "MSFT", "NVDA", "META", "TSLA",
                                       "GOOG", "NFLX", "JPM", "V", "JNJ", "WMT", "PG", "MA",
                                       "HD", "DIS", "BAC", "XOM", "KO", "PEP", "PFE", "MRK",
                                       "INTC", "CSCO", "VZ", "T", "ABT", "CVX", "MU", "QQQ",
                                       "SPY", "TLT", "GLD", "SLV", "USO", "XLF", "XLK", "VST"):
        return "us"
    if sym.startswith("=") or sym in ("CL=F", "GC=F", "HG=F"):
        return "us"
    if sym.isdigit() and len(sym) == 6:
        if sym.startswith(("51", "15", "16", "56", "58", "159")):
            return "etf"
        return "a_share"
    if sym.startswith("^"):
        return "us"
    return "us"


@app.get("/api/risk")
def api_risk():
    """组合风险指标 — VaR/集中度/波动率"""
    from datetime import datetime as _dt, timedelta as _td
    import numpy as _np

    # 读取策略状态
    st_path = ROOT / "data" / "strategy_states.json"
    if not st_path.exists():
        return {"error": "no strategy data", "var_95": None, "concentration": {}, "volatility": None}

    with open(st_path) as f:
        states = json.load(f)

    # 1. 从交易历史计算日收益率序列
    daily_returns = {}
    all_positions = {}
    for sname, state in states.items():
        for h in state.get("history", []):
            pnl = h.get("pnl")
            cost = h.get("cost")
            if pnl is not None and cost:
                ret = pnl / cost
                date = h.get("date", "")[:10]
                if date not in daily_returns:
                    daily_returns[date] = []
                daily_returns[date].append(ret)
        for sym, pos in state.get("positions", {}).items():
            if sym not in all_positions:
                all_positions[sym] = {
                    "entry_price": pos.get("entry_price", 0),
                    "quantity": pos.get("quantity", 0),
                    "current_price": pos.get("current_price", pos.get("entry_price", 0)),
                    "strategy": sname,
                }

    # 2. 年化波动率 (从日频PnL率推算)
    rets = []
    for date, rlist in daily_returns.items():
        if rlist:
            rets.append(sum(rlist) / len(rlist))
    vol = None
    if len(rets) >= 5:
        vol = round(float(_np.std(rets) * _np.sqrt(252) * 100), 2)

    # 3. VaR(95%) 历史模拟法
    var_95 = None
    if len(rets) >= 20:
        sorted_rets = sorted(rets)
        idx = max(0, int(len(sorted_rets) * 0.05) - 1)
        var_95 = round(float(sorted_rets[idx]) * 100, 2)

    # 4. 集中度 — 标的维度
    total_value = sum(
        p["current_price"] * p["quantity"] for p in all_positions.values()
    ) if all_positions else 1
    concentration = {}
    for sym, p in all_positions.items():
        mkt_val = p["current_price"] * p["quantity"]
        pct = round(mkt_val / total_value * 100, 1) if total_value > 0 else 0
        name = get_name(sym)
        concentration[sym] = {"name": name, "pct": pct, "value": round(mkt_val, 2)}

    # 按占比降序
    sorted_conc = sorted(concentration.items(), key=lambda x: x[1]["pct"], reverse=True)
    top_conc = [{"symbol": s, **v} for s, v in sorted_conc[:5]]
    max_conc = top_conc[0]["pct"] if top_conc else 0

    return {
        "volatility_annual_pct": vol,
        "var_95_daily_pct": var_95,
        "max_concentration_pct": max_conc,
        "top_positions": top_conc,
        "total_positions": len(all_positions),
        "total_trades_history": sum(len(state.get("history", [])) for state in states.values()),
        "updated_at": _dt.now().strftime("%Y-%m-%d %H:%M"),
    }


UNIFIED_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>面基·三源融合模拟盘</title>
<script src="https://cdn.tailwindcss.com"></script>
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

/* Keep old styles for old tabs */
.card { background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px; margin-bottom:16px; }
.card-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }
.card-header h3 { font-size:15px; }
.metric { margin:4px 0; display:flex; justify-content:space-between; }
.metric-l { color:var(--text2); font-size:12px; }
.metric-v { font-size:14px; font-weight:600; }
.green { color:var(--green); } .red { color:var(--red); }
table { width:100%; border-collapse:collapse; font-size:12px; }
th { text-align:left; padding:6px 4px; color:var(--text2); border-bottom:1px solid var(--border); font-weight:500; }
td { padding:5px 4px; border-bottom:1px solid var(--border); }
.tr-hover:hover { background:var(--card2); }
.badge { display:inline-block; padding:1px 6px; border-radius:3px; font-size:11px; }
.badge-buy { background:#1a3a2a; color:var(--green); }
.badge-sell { background:#3a1a1a; color:var(--red); }
.empty { color:var(--text2); padding:20px; text-align:center; }

/* Custom Scrollbar for new panels */
.custom-scrollbar::-webkit-scrollbar { width: 6px; height: 6px; }
.custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
.custom-scrollbar::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
.custom-scrollbar::-webkit-scrollbar-thumb:hover { background: #4b5563; }
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

  <!-- ======== 模拟盘 V2 ======== -->
  <div id="tab-dashboard" class="space-y-6">
    <div id="v2-portfolio-overview" class="grid grid-cols-1 md:grid-cols-3 gap-4"></div>
    
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <!-- Net value curve -->
        <div class="xl:col-span-2 bg-gray-800 border border-gray-700 rounded-xl p-4">
            <h3 class="text-gray-100 font-semibold mb-4">📈 组合净值曲线</h3>
            <div class="h-64"><canvas id="netValueChart"></canvas></div>
        </div>
        
        <!-- Signal Log -->
        <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 flex flex-col h-[330px]">
            <h3 class="text-gray-100 font-semibold mb-4">⚡ 策略信号日志</h3>
            <div id="v2-signal-stats" class="text-xs text-gray-400 mb-2"></div>
            <div class="flex-1 overflow-y-auto pr-2 custom-scrollbar">
                <table class="w-full text-xs text-left" style="border:none">
                    <thead class="text-gray-400 sticky top-0 bg-gray-800" style="border:none">
                        <tr><th class="pb-2 font-medium border-0">方向</th><th class="pb-2 font-medium border-0">标的</th><th class="pb-2 font-medium border-0">策略</th><th class="pb-2 font-medium border-0">备注</th></tr>
                    </thead>
                    <tbody id="v2-signals-table" class="divide-y divide-gray-700">
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <div>
        <h3 class="text-gray-100 font-semibold mb-4">💼 当前持仓</h3>
        <div id="v2-positions-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4"></div>
    </div>

    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 class="text-gray-100 font-semibold mb-4">📋 交易历史</h3>
        <div class="overflow-x-auto overflow-y-auto max-h-[300px] custom-scrollbar">
            <table class="w-full text-xs text-left whitespace-nowrap" style="border:none">
                <thead class="text-gray-400 sticky top-0 bg-gray-800 z-10" style="border:none">
                    <tr>
                        <th class="px-3 py-2 font-medium border-0">日期</th>
                        <th class="px-3 py-2 font-medium border-0">标的</th>
                        <th class="px-3 py-2 font-medium border-0">方向</th>
                        <th class="px-3 py-2 font-medium border-0">价格</th>
                        <th class="px-3 py-2 font-medium border-0">数量</th>
                        <th class="px-3 py-2 font-medium border-0">盈亏</th>
                        <th class="px-3 py-2 font-medium border-0">持有天数</th>
                        <th class="px-3 py-2 font-medium border-0">理由</th>
                    </tr>
                </thead>
                <tbody id="v2-trade-history" class="divide-y divide-gray-700">
                </tbody>
            </table>
        </div>
    </div>
  </div>

  <!-- ======== 票池面板 V2 ======== -->
  <div id="tab-pool" style="display:none" class="space-y-6">
    <div class="flex flex-col md:flex-row gap-6">
       <div class="flex-1 space-y-4">
           <div class="flex gap-2 border-b border-gray-700 pb-2" id="v2-pool-market-tabs"></div>
           <div id="v2-pool-content" class="space-y-4"></div>
       </div>
       <div class="w-full md:w-80 bg-gray-800 border border-gray-700 rounded-xl p-4 h-fit sticky top-4">
          <h3 class="text-gray-100 font-semibold mb-4">📖 因子评分说明</h3>
          <div id="v2-factor-explain" class="space-y-3 text-xs text-gray-300">
             <div class="empty">加载中...</div>
          </div>
       </div>
    </div>
  </div>

  <!-- ======== 回测对比面板 ======== -->
  <div class="card" id="tab-comparison" style="display:none">
    <div class="card-header"><h3>📈 三方策略回测对比</h3></div>
    <div id="comparisonBody" style="font-size:13px;"><div class="empty">加载中...</div></div>
    <div id="comparisonControls" style="margin-bottom:16px;">
      <div class="bg-gray-800/50 rounded-xl p-4 mb-4 flex flex-wrap gap-4 items-end">
        <div>
          <label class="block text-xs text-gray-400 mb-1">策略</label>
          <select id="btStrategy" class="bg-gray-700 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-600">
            <option value="all">三策略对比</option>
            <option value="faceji">面基策略</option>
            <option value="silverquant">SilverQuant</option>
            <option value="tradingagents">TradingAgents</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">开始日期</label>
          <input type="date" id="btStartDate" class="bg-gray-700 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-600" />
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">结束日期</label>
          <input type="date" id="btEndDate" class="bg-gray-700 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-600" />
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">快速选择</label>
          <select id="btQuickDays" class="bg-gray-700 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-600" onchange="applyQuickDays(this.value)">
            <option value="30">最近30天</option>
            <option value="60" selected>最近60天</option>
            <option value="90">最近90天</option>
            <option value="180">最近180天</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-gray-400 mb-1">股票池(逗号分隔,空=默认)</label>
          <input type="text" id="btSymbols" placeholder="如: 000001,600519,0700.HK" class="bg-gray-700 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-600 w-64" />
        </div>
        <button onclick="runCustomBacktest()" class="bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">▶ 运行回测</button>
      </div>
      <div id="comparisonContent"></div>
    </div>
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
let netValueChartInstance = null;
function fmt(v) { return Math.round(v).toLocaleString(); }

async function loadDashboardV2() {
  try {
    const [detailRes, nvRes] = await Promise.all([
      fetch('/api/v2/portfolio/detail').then(r => r.json()),
      fetch('/api/v2/portfolio/netvalue').then(r => r.json())
    ]);

    if (detailRes.error) {
      document.getElementById('tab-dashboard').innerHTML = `<div class="bg-gray-800 p-4 rounded text-red-400">❌ ${detailRes.error}</div>`;
      return;
    }

    document.getElementById('runInfo').textContent = 
      `${detailRes.date} | ${detailRes.generated_at} | 模拟交易 ${detailRes.simulated_trades} 笔`;

    // Overview
    const stratColors = { 'faceji': 'border-blue-500', 'silverquant': 'border-green-500', 'tradingagents': 'border-purple-500' };
    const stratBg = { 'faceji': 'bg-blue-500/10', 'silverquant': 'bg-green-500/10', 'tradingagents': 'bg-purple-500/10' };
    
    let overviewHtml = '';
    for (const [sname, p] of Object.entries(detailRes.portfolios || {})) {
      const isPos = p.total_return >= 0;
      overviewHtml += `
      <div class="bg-gray-800 border border-gray-700 border-t-4 ${stratColors[sname] || 'border-gray-500'} rounded-xl p-4">
          <div class="flex justify-between items-center mb-2">
              <h4 class="font-semibold text-gray-200">${p.label || sname}</h4>
              <span class="px-2 py-0.5 rounded text-[10px] ${stratBg[sname] || 'bg-gray-700'} text-gray-300">${p.style || sname}</span>
          </div>
          <div class="text-2xl font-bold ${isPos ? 'text-green-500' : 'text-red-500'} mb-3">
              ${isPos ? '+' : ''}${p.total_return.toFixed(2)}%
          </div>
          <div class="space-y-1 text-xs">
              <div class="flex justify-between"><span class="text-gray-400">总资产</span><span class="font-mono">¥${Math.round(p.total_value).toLocaleString()}</span></div>
              <div class="flex justify-between"><span class="text-gray-400">现金</span><span class="font-mono">¥${Math.round(p.cash).toLocaleString()}</span></div>
              <div class="flex justify-between"><span class="text-gray-400">已投</span><span class="font-mono">¥${Math.round(p.invested).toLocaleString()}</span></div>
              <div class="flex justify-between"><span class="text-gray-400">仓位</span><span class="font-mono">${p.position_count} 只</span></div>
              <div class="flex justify-between"><span class="text-gray-400">胜率</span><span class="font-mono">${p.win_rate != null ? p.win_rate.toFixed(1) + '%' : '—'}</span></div>
          </div>
      </div>`;
    }
    document.getElementById('v2-portfolio-overview').innerHTML = overviewHtml || '<div class="text-gray-400">暂无策略数据</div>';

    // Positions Grid
    let posHtml = '';
    let canvasIndex = 0;
    const radarDataList = [];
    
    for (const [sname, positions] of Object.entries(detailRes.positions || {})) {
      for (const [sym, pos] of Object.entries(positions)) {
        const isPos = pos.pnl_pct >= 0;
        const color = isPos ? 'text-green-500' : 'text-red-500';
        const stopLoss = pos.stop_loss || pos.entry_price * 0.92;
        const nearStop = pos.current_price <= stopLoss * 1.05;
        
        let scoreArrow = '';
        if (pos.current_score && pos.entry_score) {
           if (pos.current_score > pos.entry_score) scoreArrow = '<span class="text-green-500">↑</span>';
           else if (pos.current_score < pos.entry_score) scoreArrow = '<span class="text-red-500">↓</span>';
        }

        const cid = `radar-${canvasIndex++}`;
        if (pos.factor_scores) radarDataList.push({ id: cid, scores: pos.factor_scores });

        posHtml += `
        <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 flex flex-col hover:border-gray-500 transition-colors">
            <div class="flex justify-between items-start mb-3">
                <div>
                    <div class="flex items-center gap-2">
                        <span class="font-bold text-gray-100 text-lg">${sym}</span>
                        <span class="text-sm text-gray-400">${pos.name || sym}</span>
                    </div>
                    <div class="text-xs px-2 py-0.5 rounded mt-1 inline-block ${stratBg[sname] || 'bg-gray-700'} text-gray-300">
                        ${sname}
                    </div>
                </div>
                <div class="text-right">
                    <div class="text-lg font-bold font-mono ${color}">${isPos?'+':''}${pos.pnl_pct.toFixed(2)}%</div>
                    <div class="text-xs ${color} font-mono">${isPos?'+':''}¥${Math.round(pos.pnl).toLocaleString()}</div>
                </div>
            </div>
            
            <div class="grid grid-cols-2 gap-x-4 gap-y-2 text-xs mb-3">
                <div class="flex justify-between"><span class="text-gray-400">买入/现价</span><span class="font-mono">${pos.entry_price.toFixed(2)} / ${pos.current_price.toFixed(2)}</span></div>
                <div class="flex justify-between"><span class="text-gray-400">持有天数</span><span class="font-mono">${pos.hold_days} 天</span></div>
                <div class="flex justify-between"><span class="text-gray-400">回撤(峰值/买入)</span><span class="font-mono text-red-400">${pos.drawdown_from_peak?.toFixed(2)||0}% / ${pos.drawdown_from_entry?.toFixed(2)||0}%</span></div>
                <div class="flex justify-between"><span class="text-gray-400">仓位占比</span><span class="font-mono">${pos.pct?.toFixed(1)||0}%</span></div>
                <div class="flex justify-between"><span class="text-gray-400">止损线</span><span class="font-mono ${nearStop?'text-red-500 font-bold':''}">${stopLoss.toFixed(2)}</span></div>
                <div class="flex justify-between"><span class="text-gray-400">评分变化</span><span class="font-mono">${pos.entry_score?.toFixed(2)||'-'} ${scoreArrow} ${pos.current_score?.toFixed(2)||'-'}</span></div>
            </div>
            
            <div class="text-xs text-gray-400 bg-gray-900 rounded p-2 mb-3 line-clamp-2" title="${pos.reason||''}">${pos.reason||'无理由'}</div>
            
            <div class="h-32 w-full mt-auto relative pt-2">
                ${pos.factor_scores ? `<canvas id="${cid}"></canvas>` : '<div class="absolute inset-0 flex items-center justify-center text-gray-600 text-xs">无因子数据</div>'}
            </div>
        </div>`;
      }
    }
    document.getElementById('v2-positions-grid').innerHTML = posHtml || '<div class="text-gray-400 col-span-full py-4 text-center">空仓</div>';

    // Radars
    radarDataList.forEach(item => renderRadarChart(item.id, item.scores));

    // Trade History
    let allTrades = [];
    for (const [sname, trades] of Object.entries(detailRes.trade_history || {})) {
        trades.forEach(t => allTrades.push({...t, sname}));
    }
    allTrades.sort((a,b) => ((b.date||b.time||'') > (a.date||a.time||'') ? 1 : -1));
    allTrades = allTrades.slice(0, 50);

    let tradeHtml = '';
    allTrades.forEach(tx => {
        const isBuy = tx.action === '买入' || tx.action === 'BUY';
        const pnlStr = tx.pnl != null ? (tx.pnl>0?'+':'') + '¥'+Math.round(tx.pnl).toLocaleString() : '—';
        const pnlCls = tx.pnl > 0 ? 'text-green-500 font-medium' : (tx.pnl < 0 ? 'text-red-500' : 'text-gray-400');
        const actCls = isBuy ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400';
        const rowBg = isBuy ? 'bg-green-900/10 hover:bg-green-900/20' : 'bg-red-900/10 hover:bg-red-900/20';
        const rowFont = tx.pnl > 0 ? 'font-bold text-white' : 'text-gray-300';
        tradeHtml += `
        <tr class="${rowBg} ${rowFont} transition-colors border-b border-gray-800">
            <td class="px-3 py-2 text-gray-400 border-0">${(tx.date||tx.time||'').substring(0,10)}</td>
            <td class="px-3 py-2 border-0"><span class="font-bold text-gray-200">${tx.symbol}</span> <span class="text-[10px] ${stratBg[tx.sname]||'bg-gray-700'} px-1 rounded text-gray-300 ml-1">${tx.sname}</span></td>
            <td class="px-3 py-2 border-0"><span class="px-1.5 py-0.5 rounded text-[10px] ${actCls}">${tx.action}</span></td>
            <td class="px-3 py-2 font-mono border-0">¥${(tx.price||0).toFixed(2)}</td>
            <td class="px-3 py-2 font-mono border-0">${(tx.quantity||0).toLocaleString()}</td>
            <td class="px-3 py-2 font-mono border-0 ${pnlCls}">${pnlStr}</td>
            <td class="px-3 py-2 font-mono text-gray-400 border-0">${tx.hold_days!=null?tx.hold_days+'天':'—'}</td>
            <td class="px-3 py-2 text-gray-400 truncate max-w-[200px] border-0" title="${tx.reason||''}">${tx.reason||''}</td>
        </tr>`;
    });
    document.getElementById('v2-trade-history').innerHTML = tradeHtml || '<tr><td colspan="8" class="text-center py-4 text-gray-500 border-0">暂无交易历史</td></tr>';

    // Signals
    document.getElementById('v2-signal-stats').innerHTML = 
        `原始信号: <span class="text-gray-200">${detailRes.total_raw_signals}</span> → 冲突解决: <span class="text-gray-200">${detailRes.after_conflict_resolution}</span> → 周频过滤: <span class="text-gray-200">${detailRes.after_weekly_filter}</span> → 执行: <span class="text-gray-200">${detailRes.simulated_trades}</span>`;

    let sigHtml = '';
    (detailRes.all_signals || []).forEach(s => {
        const isBuy = s.action === 'BUY' || s.action === '买入';
        const actCls = isBuy ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400';
        let statusTag = '';
        if (s.filtered_by_weekly) statusTag = '<span class="text-[10px] bg-yellow-900/40 text-yellow-500 px-1 rounded ml-1">周频过滤</span>';
        else if (s.executed) statusTag = '<span class="text-[10px] bg-blue-900/40 text-blue-400 px-1 rounded ml-1">已执行</span>';
        
        sigHtml += `
        <tr class="hover:bg-gray-700/50 transition-colors border-b border-gray-700/50">
            <td class="py-2 pr-2 border-0"><span class="px-1.5 py-0.5 rounded text-[10px] ${actCls}">${s.action}</span></td>
            <td class="py-2 pr-2 font-mono text-gray-200 border-0">${s.symbol}</td>
            <td class="py-2 pr-2 text-gray-400 border-0">${s.strategy||'—'}</td>
            <td class="py-2 text-gray-400 text-[10px] truncate max-w-[150px] border-0" title="${s.reason||''}">${s.reason||''} ${statusTag}</td>
        </tr>`;
    });
    document.getElementById('v2-signals-table').innerHTML = sigHtml || '<tr><td colspan="4" class="text-center py-4 text-gray-500 border-0">今日无信号</td></tr>';

    // Chart
    if (!nvRes.error && nvRes.series && nvRes.series.length > 0) {
        renderNetValueChart(nvRes.labels, nvRes.series);
    }
  } catch(e) { console.error(e); }
}

function renderRadarChart(canvasId, factorScores) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    const factorLabels = { 'quality': '质量', 'value': '价值', 'growth': '成长', 'momentum': '动量', 'low_vol': '低波', 'sentiment': '情绪', 'dividend': '分红' };
    const labels = [], data = [];
    for (const [k, v] of Object.entries(factorScores)) {
        if (k === 'risk') continue;
        labels.push(factorLabels[k] || k); data.push(v);
    }
    new Chart(ctx, {
        type: 'radar',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: 'rgba(59, 130, 246, 0.2)',
                borderColor: 'rgba(59, 130, 246, 0.8)',
                pointBackgroundColor: 'rgba(59, 130, 246, 1)',
                pointRadius: 1, borderWidth: 1
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            scales: { r: { min: 0, max: 1, ticks: { display: false }, grid: { color: 'rgba(255, 255, 255, 0.1)' }, angleLines: { color: 'rgba(255, 255, 255, 0.1)' }, pointLabels: { color: 'rgba(156, 163, 175, 1)', font: { size: 9 } } } },
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: function(ctx) { return ctx.raw.toFixed(2); } } } }
        }
    });
}

function renderNetValueChart(labels, series) {
    const ctx = document.getElementById('netValueChart');
    if (!ctx) return;
    if (netValueChartInstance) netValueChartInstance.destroy();
    const colors = ['#58a6ff', '#3fb950', '#bc8cff', '#d29922', '#f85149'];
    const datasets = series.map((s, i) => ({
        label: s.name, data: s.data, borderColor: colors[i % colors.length], backgroundColor: colors[i % colors.length] + '20',
        borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.1
    }));
    netValueChartInstance = new Chart(ctx, {
        type: 'line', data: { labels: labels, datasets: datasets },
        options: {
            responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
            scales: { x: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: 'rgba(156, 163, 175, 1)', maxTicksLimit: 10 } }, y: { grid: { color: 'rgba(255, 255, 255, 0.05)' }, ticks: { color: 'rgba(156, 163, 175, 1)' } } },
            plugins: { legend: { position: 'top', labels: { color: 'rgba(229, 231, 235, 1)', boxWidth: 12 } }, tooltip: { backgroundColor: 'rgba(17, 24, 39, 0.9)', titleColor: '#fff', bodyColor: '#fff', borderColor: 'rgba(75, 85, 99, 1)', borderWidth: 1 } }
        }
    });
}

async function loadPoolV2() {
    try {
        const [poolRes, explainRes] = await Promise.all([
            fetch('/api/v2/pool/by_market').then(r => r.json()),
            fetch('/api/v2/factor_explain').then(r => r.json())
        ]);
        if (!explainRes.error && explainRes.factors) {
            let expHtml = `<div class="mb-3 text-gray-400">引擎: <span class="text-gray-200">${explainRes.engine}</span><br/>方法: ${explainRes.method}</div>`;
            explainRes.factors.forEach(f => {
                expHtml += `
                <div class="mb-2">
                    <div class="flex justify-between items-center cursor-pointer hover:text-white" onclick="this.nextElementSibling.classList.toggle('hidden')">
                        <span class="font-bold text-gray-200">${f.label} (${f.key})</span>
                        <span class="text-blue-400 font-mono">${(f.weight*100).toFixed(0)}% ▾</span>
                    </div>
                    <div class="hidden mt-1 pl-2 border-l-2 border-gray-600 text-[10px] space-y-1">
                        <div class="text-gray-400">${f.desc}</div>
                        <div class="text-gray-500">包含: ${(f.subs||[]).join(', ')}</div>
                    </div>
                </div>`;
            });
            document.getElementById('v2-factor-explain').innerHTML = expHtml;
        }
        window.poolDataCache = poolRes;
        const markets = [{ id: 'a_share', label: 'A股' }, { id: 'hk', label: '港股' }, { id: 'us', label: '美股' }, { id: 'etf', label: 'ETF' }];
        let tabsHtml = '';
        markets.forEach((m, idx) => {
            const count = ((poolRes[m.id]?.watch?.length||0) + (poolRes[m.id]?.monitor?.length||0) + (poolRes[m.id]?.deep?.length||0));
            tabsHtml += `<button onclick="renderPoolMarket('${m.id}')" id="pool-tab-${m.id}" class="pool-tab-btn px-4 py-2 rounded-t-lg font-medium text-sm transition-colors ${idx === 0 ? 'bg-gray-800 text-blue-400 border-t-2 border-blue-500' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800/50'}">${m.label} <span class="text-xs opacity-60 ml-1">(${count})</span></button>`;
        });
        document.getElementById('v2-pool-market-tabs').innerHTML = tabsHtml;
        renderPoolMarket('a_share');
    } catch(e) { console.error(e); }
}

function renderPoolMarket(marketId) {
    document.querySelectorAll('.pool-tab-btn').forEach(btn => btn.className = 'pool-tab-btn px-4 py-2 rounded-t-lg font-medium text-sm transition-colors text-gray-400 hover:text-gray-200 hover:bg-gray-800/50');
    const activeBtn = document.getElementById(`pool-tab-${marketId}`);
    if (activeBtn) activeBtn.className = 'pool-tab-btn px-4 py-2 rounded-t-lg font-medium text-sm transition-colors bg-gray-800 text-blue-400 border-t-2 border-blue-500';
    const data = window.poolDataCache?.[marketId] || { watch: [], monitor: [], deep: [] };
    const tierDefs = [
        { id: 'deep', label: '🧠 深度层 (Deep)', color: 'text-green-500', desc: '评分>0.6 ≥2周 + 不为清单通过' },
        { id: 'monitor', label: '👀 盯住层 (Monitor)', color: 'text-yellow-500', desc: '评分>0.55 ≥1周' },
        { id: 'watch', label: '🔍 发现层 (Watch)', color: 'text-blue-500', desc: '评分>0.50' }
    ];
    let contentHtml = '';
    tierDefs.forEach(t => {
        const items = data[t.id] || [];
        let rowsHtml = '';
        items.forEach(i => {
            const sc = i.scores || {};
            let sColor = 'text-red-500';
            if (i.score >= 0.63) sColor = 'text-green-500 font-bold';
            else if (i.score >= 0.48) sColor = 'text-green-400';
            else if (i.score >= 0.35) sColor = 'text-yellow-500';
            
            const factorKeys = ['quality', 'value', 'growth', 'momentum', 'low_vol', 'sentiment', 'dividend'];
            const factorLabels = ['质', '价', '长', '动', '波', '情', '息'];
            let barsHtml = '<div class="flex gap-1 items-end h-8">';
            factorKeys.forEach((fk, idx) => {
                const val = sc[fk] || 0;
                const h = Math.max(10, val * 100) + '%';
                let bColor = 'bg-gray-600';
                if (val >= 0.7) bColor = 'bg-green-500';
                else if (val >= 0.5) bColor = 'bg-blue-500';
                else if (val < 0.3) bColor = 'bg-red-500';
                barsHtml += `<div class="flex flex-col items-center justify-end w-4 group relative" title="${factorLabels[idx]}: ${val.toFixed(2)}"><div class="w-full ${bColor} rounded-t-sm opacity-80 group-hover:opacity-100 transition-opacity" style="height: ${h}"></div><div class="text-[8px] text-gray-500 mt-0.5">${factorLabels[idx]}</div></div>`;
            });
            barsHtml += '</div>';
            
            rowsHtml += `
            <div class="bg-gray-800/50 hover:bg-gray-700/50 transition-colors border border-gray-700 rounded-lg p-3 flex flex-wrap gap-4 items-center">
                <div class="w-32">
                    <div class="font-bold text-gray-200 text-base">${i.symbol}</div>
                    <div class="text-xs text-gray-400 truncate" title="${i.name}">${i.name}</div>
                    ${i.chain ? `<div class="text-[10px] bg-yellow-900/30 text-yellow-500 px-1.5 py-0.5 rounded inline-block mt-1 truncate max-w-full">${i.chain}</div>` : ''}
                </div>
                <div class="w-20 text-center">
                    <div class="text-xs text-gray-500 mb-1">综合评分</div>
                    <div class="text-xl font-mono ${sColor}">${(i.score||0).toFixed(3)}</div>
                </div>
                <div class="w-36 hidden sm:block">${barsHtml}</div>
                <div class="flex-1 min-w-[200px] border-l border-gray-700 pl-4">
                    <div class="text-xs text-gray-400 mb-1 flex items-center gap-2"><span>加入: ${i.date_added||'—'}</span></div>
                    <div class="text-xs text-gray-300 line-clamp-2" title="${i.reason||''}">${i.reason||'无理由'}</div>
                </div>
            </div>`;
        });
        if (items.length === 0) rowsHtml = `<div class="text-sm text-gray-500 italic p-4 text-center border border-gray-800 border-dashed rounded">此层级暂无标的</div>`;
        
        contentHtml += `
        <div class="mb-6">
            <div class="flex items-center gap-2 mb-3 cursor-pointer" onclick="document.getElementById('tier-${t.id}').classList.toggle('hidden')">
                <h4 class="font-bold text-base ${t.color}">${t.label}</h4>
                <span class="text-xs text-gray-400 ml-2">${t.desc}</span>
                <span class="bg-gray-800 text-gray-300 text-xs px-2 py-0.5 rounded-full ml-auto">${items.length}</span>
            </div>
            <div id="tier-${t.id}" class="space-y-2">${rowsHtml}</div>
        </div>`;
    });
    document.getElementById('v2-pool-content').innerHTML = contentHtml;
}

function switchTab(ev, tab) {
  if (ev) ev.preventDefault();
  document.querySelectorAll('.nav a').forEach(a => a.classList.remove('active'));
  if (ev) ev.currentTarget.classList.add('active');

  const sections = ['tab-dashboard', 'tab-pool', 'tab-etf', 'tab-news', 'tab-reports', 'tab-comparison'];
  sections.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
  });

  const panel = document.getElementById('tab-'+tab);
  if (panel) panel.style.display = '';

  if (tab === 'dashboard') loadDashboardV2();
  else if (tab === 'pool') loadPoolV2();
  else if (tab === 'etf') loadEtf();
  else if (tab === 'news') loadNews();
  else if (tab === 'reports') loadReports();
  else if (tab === 'comparison') loadComparison();
  return false;
}

window.onload = () => { loadDashboardV2(); };
setInterval(loadDashboardV2, 120000);

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

let comparisonChartInstance = null;

function applyQuickDays(days) {
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400000);
  document.getElementById('btStartDate').value = start.toISOString().split('T')[0];
  document.getElementById('btEndDate').value = end.toISOString().split('T')[0];
}

async function loadComparison() {
  const el = document.getElementById('comparisonContent');
  el.innerHTML = '<div class="text-gray-400 p-4">⏳ 加载中...</div>';
  await runCustomBacktest();
}

async function runCustomBacktest() {
  const el = document.getElementById('comparisonContent');
  const strategy = document.getElementById('btStrategy')?.value || 'all';
  const startDate = document.getElementById('btStartDate')?.value || '';
  const endDate = document.getElementById('btEndDate')?.value || '';
  const symbols = document.getElementById('btSymbols')?.value || '';

  let days = 60;
  if (startDate && endDate) {
    try {
      const d1 = new Date(startDate);
      const d2 = new Date(endDate);
      days = Math.max(7, Math.round((d2 - d1) / 86400000));
    } catch(e) {}
  }

  el.innerHTML = '<div class="text-gray-400 p-4">⏳ 运行回测中...</div>';

  try {
    let url = `/api/v2/backtest/custom?strategy=${strategy}&days=${days}`;
    if (startDate) url += `&start_date=${startDate}`;
    if (endDate) url += `&end_date=${endDate}`;
    if (symbols) url += `&symbols=${encodeURIComponent(symbols)}`;

    const r = await fetch(url);
    const data = await r.json();

    if (data.error) {
      el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ ${data.error}</div>`;
      return;
    }

    const strategies = [data.faceji, data.silverquant, data.tradingagents].filter(Boolean);
    const colors = {'faceji (面基)': '#58a6ff', 'silverquant (组件化)': '#3fb950', 'tradingagents (辩论制)': '#bc8cff'};
    const params = data.params || {};

    let html = `
      <div class="bg-gray-800/50 rounded-lg p-3 mb-4 flex flex-wrap gap-4 text-xs text-gray-400">
        <span>📊 策略: <strong class="text-gray-200">${params.strategy || strategy}</strong></span>
        <span>📅 周期: <strong class="text-gray-200">${data.days_analyzed || days}天</strong></span>
        ${params.start_date ? `<span>从 <strong class="text-gray-200">${params.start_date}</strong></span>` : ''}
        ${params.end_date ? `<span>到 <strong class="text-gray-200">${params.end_date}</strong></span>` : ''}
        ${params.symbols ? `<span>标的: <strong class="text-gray-200">${params.symbols}</strong></span>` : ''}
        <span>更新: <strong class="text-gray-200">${data.run_date || ''}</strong></span>
      </div>`;

    if (strategies.length === 0 || (strategies[0] && strategies[0].note)) {
      html += `<div class="bg-yellow-900/30 text-yellow-400 p-4 rounded-lg">
        ⚠️ ${strategies[0]?.note || '暂无回测数据，需先运行日报管线积累扫描快照（约60个交易日后有真实对比曲线）'}
      </div>`;
      el.innerHTML = html;
      return;
    }

    html += '<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">';
    strategies.forEach(s => {
      const retCls = s.total_return_pct >= 0 ? 'text-green-500' : 'text-red-500';
      const borderColor = colors[s.name] || '#6b7280';
      html += `
      <div class="bg-gray-800 border border-gray-700 border-t-4 rounded-xl p-4" style="border-top-color:${borderColor}">
        <div class="font-semibold text-gray-200 mb-2">${s.name}</div>
        <div class="text-3xl font-bold ${retCls} mb-3">${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%</div>
        <div class="space-y-1 text-xs text-gray-400">
          <div class="flex justify-between"><span>总资产</span><span class="font-mono text-gray-200">¥${fmt(s.value||0)}</span></div>
          <div class="flex justify-between"><span>已实现盈亏</span><span class="font-mono ${s.realized_pnl>=0?'text-green-500':'text-red-500'}">${s.realized_pnl>=0?'+':''}¥${fmt(s.realized_pnl||0)}</span></div>
          <div class="flex justify-between"><span>浮盈</span><span class="font-mono ${(s.unrealized_pnl||0)>=0?'text-green-500':'text-red-500'}">${(s.unrealized_pnl||0)>=0?'+':''}¥${fmt(s.unrealized_pnl||0)}</span></div>
          <div class="flex justify-between"><span>持仓</span><span class="font-mono text-gray-200">${s.positions||0} 只</span></div>
          <div class="flex justify-between"><span>交易次数</span><span class="font-mono text-gray-200">${s.total_trades||0} 笔</span></div>
          <div class="flex justify-between"><span>胜率</span><span class="font-mono text-gray-200">${s.win_rate||0}%</span></div>
          <div class="flex justify-between"><span>最大回撤</span><span class="font-mono text-red-400">-${s.max_drawdown_pct||0}%</span></div>
        </div>
      </div>`;
    });
    html += '</div>';

    if (strategies.some(s => s.daily_values && s.daily_values.length > 0)) {
      html += '<div class="bg-gray-800 rounded-xl p-4 mb-6"><h4 class="text-sm font-semibold text-gray-300 mb-3">📉 净值曲线</h4><canvas id="comparisonChart" height="300"></canvas></div>';
    }

    html += '<div class="bg-gray-800 rounded-xl p-4"><h4 class="text-sm font-semibold text-gray-300 mb-3">📋 交易明细</h4>';
    strategies.forEach(s => {
      const trades = (s.trades || []).slice(-20).reverse();
      if (trades.length === 0) return;
      html += `<div class="mb-4">
        <div class="text-xs font-medium mb-2" style="color:${colors[s.name]||'#fff'}">● ${s.name} (${trades.length}笔)</div>
        <table class="w-full text-xs">
          <thead class="text-gray-400 border-b border-gray-700"><tr>
            <th class="py-2 text-left">日期</th><th class="text-left">代码</th><th class="text-left">操作</th>
            <th class="text-right">价格</th><th class="text-right">盈亏</th><th class="text-left">原因</th>
          </tr></thead><tbody>`;
      trades.forEach(tx => {
        const isBuy = tx.action === '买入' || tx.action === 'BUY';
        const pnlCls = tx.pnl > 0 ? 'text-green-500 font-semibold' : (tx.pnl < 0 ? 'text-red-500' : 'text-gray-400');
        html += `<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
          <td class="py-1.5 text-gray-400">${tx.date||tx.time||''}</td>
          <td class="font-mono">${tx.symbol||''}</td>
          <td><span class="px-1.5 py-0.5 rounded text-[10px] ${isBuy?'bg-green-900/40 text-green-400':'bg-red-900/40 text-red-400'}">${tx.action}</span></td>
          <td class="text-right font-mono">¥${(tx.price||0).toFixed(2)}</td>
          <td class="text-right font-mono ${pnlCls}">${tx.pnl!=null ? (tx.pnl>0?'+':'')+'¥'+fmt(tx.pnl) : '—'}</td>
          <td class="text-gray-400 text-[11px]">${(tx.reason||'').substring(0,30)}</td>
        </tr>`;
      });
      html += '</tbody></table></div>';
    });
    html += '</div>';

    el.innerHTML = html;

    if (strategies.some(s => s.daily_values && s.daily_values.length > 0)) {
      const ctx = document.getElementById('comparisonChart');
      if (ctx) {
        if (comparisonChartInstance) comparisonChartInstance.destroy();
        const datasets = strategies.filter(s => s.daily_values && s.daily_values.length > 0).map(s => ({
          label: `${s.name} (${s.total_return_pct>=0?'+':''}${s.total_return_pct}%)`,
          data: s.daily_values.map(d => ({x: d.date, y: d.value})),
          borderColor: colors[s.name] || '#7ee787',
          backgroundColor: (colors[s.name] || '#7ee787') + '15',
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.3,
          fill: false,
        }));
        comparisonChartInstance = new Chart(ctx, {
          type: 'line',
          data: { datasets },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { labels: { color: '#c9d1d9', font: { size: 11 } } } },
            scales: {
              x: { ticks: { color: '#8b949e', font: { size: 10 } }, grid: { color: '#21262d' } },
              y: { ticks: { color: '#8b949e', font: { size: 10 }, callback: v => '¥'+(v/10000).toFixed(0)+'w' }, grid: { color: '#21262d' } },
            }
          }
        });
      }
    }
  } catch(e) {
    el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ 加载失败: ${e.message}</div>`;
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
    let html = `<div style="font-size:11px;color:var(--text2);margin-bottom:8px;">📡 ${data.summary || ''} · 更新: ${data.timestamp || ''}`;
    // 数据新鲜度标记
    if (data.freshness) {
      const freshnessColors = {fresh:'var(--green)',stale:'var(--yellow)',expired:'var(--red)'};
      const freshnessLabels = {fresh:'新鲜',stale:'超过3天',expired:'超过7天'};
      const fc = freshnessColors[data.freshness] || 'var(--text2)';
      html += ` <span class="badge" style="background:${fc}22;color:${fc};font-size:10px;margin-left:4px;">${data.days_stale}d ${freshnessLabels[data.freshness] || ''}</span>`;
    }
    html += `</div>`;
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