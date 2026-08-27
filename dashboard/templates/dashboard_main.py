UNIFIED_DASHBOARD_HTML = """<!DOCTYPE html>
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

/* Layer Bar */
.layer-card { transition: all 0.15s; }
.layer-card:hover { border-color: var(--accent); }
.layer-l1 .badge { background: #1a3a2a; color: var(--green); }
.layer-l2 .badge { background: #1a2a3a; color: #58a6ff; }
.layer-l3 .badge { background: #2a1a3a; color: #bc8cff; }
.layer-l5 .badge { background: #2a2a1a; color: #d29922; }
.layer-l6 .badge { background: #1a1a2a; color: #79c0ff; }
.layer-detail { display: none; }
.layer-detail.open { display: block; }

/* Execution Board */
.signal-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 8px; }
.signal-card.buy { border-left: 3px solid var(--green); }
.signal-card.sell { border-left: 3px solid var(--red); }
.signal-card.hold { border-left: 3px solid #d29922; }
.signal-card.wait { border-left: 3px solid var(--text2); }
.evidence-line { font-size: 12px; color: var(--text2); padding: 2px 0; }
.evidence-line .label { color: var(--text1); font-weight: 600; }
.evidence-toggle { cursor: pointer; color: var(--accent); font-size: 12px; }
.evidence-toggle:hover { text-decoration: underline; }
</style>
</head>
<body>
<div class="container">
  <div class="nav">
    <a href="#" class="active" onclick="return switchTab(event,'dashboard')">📊 模拟盘</a>
    <a href="#" onclick="return switchTab(event,'comparison')">📈 回测对比</a>
    <a href="#" onclick="return switchTab(event,'pool')">🎯 票池</a>
    <a href="#" onclick="return switchTab(event,'etf')">📦 ETF</a>
    <a href="#" onclick="return switchTab(event,'dragon_tiger')">🐉 龙虎榜</a>
    <a href="#" onclick="return switchTab(event,'news')">📰 新闻</a>
    <a href="#" onclick="return switchTab(event,'reports')">📋 日报</a>
    <a href="#" onclick="return switchTab(event,'evidence')">🔬 证据</a>
    <a href="#" onclick="return switchTab(event,'gurus')">🏆 大师持仓</a>
    <a href="#" onclick="return switchTab(event,'insights')">💡 观点</a>
  </div>

  <!-- ======== 六层横条 ======== -->
  <div id="layer-bar" class="grid grid-cols-5 gap-2 mb-2 text-xs">
    <div class="layer-card layer-l1 bg-gray-800 border border-gray-700 rounded-lg p-2 cursor-pointer hover:bg-gray-750" onclick="toggleLayerDetail('l1')">
      <div class="flex justify-between items-center">
        <span class="font-semibold text-gray-300">L1 宏观</span>
        <span id="l1-status" class="badge">-</span>
      </div>
      <div id="l1-content" class="text-gray-400 mt-1"></div>
    </div>
    <div class="layer-card layer-l2 bg-gray-800 border border-gray-700 rounded-lg p-2 cursor-pointer hover:bg-gray-750" onclick="toggleLayerDetail('l2')">
      <div class="flex justify-between items-center">
        <span class="font-semibold text-gray-300">L2 配置</span>
        <span id="l2-status" class="badge">-</span>
      </div>
      <div id="l2-content" class="text-gray-400 mt-1"></div>
    </div>
    <div class="layer-card layer-l3 bg-gray-800 border border-gray-700 rounded-lg p-2 cursor-pointer hover:bg-gray-750" onclick="toggleLayerDetail('l3')">
      <div class="flex justify-between items-center">
        <span class="font-semibold text-gray-300">L3-L4 选股</span>
        <span id="l3-status" class="badge">-</span>
      </div>
      <div id="l3-content" class="text-gray-400 mt-1"></div>
    </div>
    <div class="layer-card layer-l5 bg-gray-800 border border-gray-700 rounded-lg p-2 cursor-pointer hover:bg-gray-750" onclick="toggleLayerDetail('l5')">
      <div class="flex justify-between items-center">
        <span class="font-semibold text-gray-300">L5 风控</span>
        <span id="l5-status" class="badge">-</span>
      </div>
      <div id="l5-content" class="text-gray-400 mt-1"></div>
    </div>
    <div class="layer-card layer-l6 bg-gray-800 border border-gray-700 rounded-lg p-2 cursor-pointer hover:bg-gray-750" onclick="toggleLayerDetail('l6')">
      <div class="flex justify-between items-center">
        <span class="font-semibold text-gray-300">L6 纪律</span>
        <span id="l6-status" class="badge">-</span>
      </div>
      <div id="l6-content" class="text-gray-400 mt-1"></div>
    </div>
  </div>

  <h1>面基 · 三源融合模拟盘</h1>
  <div class="subtitle" id="runInfo">加载中...</div>
  <div id="consistency-bar" class="text-xs mt-1"></div>

  <!-- ======== 模拟盘 V2 ======== -->
  <div id="tab-dashboard" class="space-y-6">
    <!-- ======== 执行决策区（置顶） ======== -->
    <div id="execution-board" class="bg-gray-800 border border-gray-700 rounded-xl p-4">
      <div class="flex justify-between items-center mb-4">
        <h3 class="text-gray-100 font-semibold">🎯 今日执行决策</h3>
        <div id="board-data-quality" class="text-xs text-gray-400">数据质量: —</div>
      </div>
      <div id="board-content">
        <div class="text-gray-400 text-sm">加载中...</div>
      </div>
    </div>
    <div id="v2-portfolio-overview" class="grid grid-cols-1 md:grid-cols-3 gap-4"></div>
    
    <!-- ======== 策略信号日志 (执行决策下方, 全宽) ======== -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <div class="flex items-center justify-between mb-2">
            <h3 class="text-gray-100 font-semibold">⚡ 策略信号日志</h3>
            <select id="v2-signal-date" class="bg-gray-700 text-gray-200 rounded-lg px-2 py-1 text-xs border border-gray-600" onchange="loadSignalHistory(this.value)">
                <option value="">今日信号</option>
            </select>
        </div>
        <div id="v2-signal-stats" class="text-xs text-gray-400 mb-2"></div>
        <div class="overflow-x-auto max-h-[300px] custom-scrollbar">
            <table class="w-full text-xs text-left whitespace-nowrap" style="border:none">
                <thead class="text-gray-400 sticky top-0 bg-gray-800 z-10" style="border:none">
                    <tr>
                        <th class="px-2 py-2 font-medium border-0">方向</th>
                        <th class="px-2 py-2 font-medium border-0">标的</th>
                        <th class="px-2 py-2 font-medium border-0">策略</th>
                        <th class="px-2 py-2 font-medium border-0">评分</th>
                        <th class="px-2 py-2 font-medium border-0">优先级</th>
                        <th class="px-2 py-2 font-medium border-0">状态</th>
                        <th class="px-2 py-2 font-medium border-0">备注</th>
                        <th class="px-2 py-2 font-medium border-0"></th>
                    </tr>
                </thead>
                <tbody id="v2-signals-table" class="divide-y divide-gray-700">
                </tbody>
            </table>
        </div>
    </div>

    <!-- ======== 组合净值曲线 (全宽) ======== -->
    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 class="text-gray-100 font-semibold mb-4">📈 组合净值曲线</h3>
        <div class="h-64"><canvas id="netValueChart"></canvas></div>
    </div>

    <div>
        <div class="flex items-center justify-between mb-4">
            <h3 class="text-gray-100 font-semibold">💼 当前持仓</h3>
            <div class="flex gap-2" id="v2-position-tabs">
                <button class="pos-tab px-3 py-1 rounded-lg text-xs border border-gray-600 text-gray-300 hover:border-gray-400" data-strat="all" onclick="setPosTab('all')">全部</button>
                <button class="pos-tab px-3 py-1 rounded-lg text-xs border border-gray-600 text-gray-300 hover:border-gray-400" data-strat="faceji" onclick="setPosTab('faceji')">面基</button>
                <button class="pos-tab px-3 py-1 rounded-lg text-xs border border-gray-600 text-gray-300 hover:border-gray-400" data-strat="silverquant" onclick="setPosTab('silverquant')">SilverQuant</button>
                <button class="pos-tab px-3 py-1 rounded-lg text-xs border border-gray-600 text-gray-300 hover:border-gray-400" data-strat="tradingagents" onclick="setPosTab('tradingagents')">TradingAgents</button>
            </div>
        </div>
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
        <div class="flex items-center gap-2 pb-1">
          <label class="flex items-center gap-2 cursor-pointer select-none">
            <input type="checkbox" id="btWF" class="w-4 h-4 accent-blue-500" />
            <span class="text-xs text-gray-300" title="Walk-Forward 样本外滚动评估: 训练窗口前移, 逐期测试 out-of-sample">🧪 Walk-Forward 样本外</span>
          </label>
          <select id="btWFCycles" class="bg-gray-700 text-gray-100 rounded-lg px-2 py-1.5 text-xs border border-gray-600">
            <option value="3">3 周期</option>
            <option value="5">5 周期</option>
            <option value="2">2 周期</option>
          </select>
        </div>
        <button onclick="runCustomBacktest()" class="bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium transition-colors">▶ 运行回测</button>
      </div>
      <div id="comparisonContent"></div>
    </div>
  </div>

  <!-- ======== ETF面板 ======== -->
  <div class="card" id="tab-etf" style="display:none">
    <div class="card-header"><h3>📦 ETF 找票 · 分析 · 趋势 · 组合配置</h3></div>
    <div id="etfBody" class="space-y-6 p-4"></div>
  </div>

  <!-- ======== 龙虎榜面板 ======== -->
  <div id="tab-dragon_tiger" style="display:none" class="space-y-4">
    <div class="flex items-center justify-between mb-2">
      <div class="flex items-center gap-4">
        <span id="dt-date" class="text-gray-400 text-sm">加载中...</span>
        <span id="dt-total" class="text-gray-500 text-xs"></span>
      </div>
      <button onclick="refreshDragonTiger()" id="dt-refresh-btn" class="bg-blue-600 hover:bg-blue-500 text-white rounded px-3 py-1.5 text-xs transition-colors">🔄 刷新</button>
    </div>

    <!-- 机构vs游资概览 -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3" id="dt-overview"></div>

    <!-- WATCHLIST 高亮 -->
    <div id="dt-watchlist" class="bg-gray-800 border border-yellow-600/30 rounded-xl p-4 hidden">
      <h4 class="text-yellow-400 font-semibold text-sm mb-3">⭐ WATCHLIST 交集 — 上榜即关注</h4>
      <div id="dt-watchlist-content" class="space-y-2"></div>
    </div>

    <!-- 双栏: Top10净买入 + 活跃游资 -->
    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <!-- Top10净买入 -->
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h4 class="text-gray-100 font-semibold text-sm mb-3">🏆 Top10 净买入</h4>
        <div class="overflow-x-auto">
          <table class="w-full text-xs text-left" style="border:none">
            <thead class="text-gray-400 border-b border-gray-700">
              <tr>
                <th class="py-2 pr-2 font-medium border-0">#</th>
                <th class="py-2 pr-2 font-medium border-0">代码</th>
                <th class="py-2 pr-2 font-medium border-0">名称</th>
                <th class="py-2 pr-2 font-medium border-0 text-right">净买额</th>
                <th class="py-2 pr-2 font-medium border-0 text-right">买入占比</th>
                <th class="py-2 font-medium border-0">上榜原因</th>
              </tr>
            </thead>
            <tbody id="dt-top10-table" class="divide-y divide-gray-700"></tbody>
          </table>
        </div>
      </div>

      <!-- 活跃游资 -->
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h4 class="text-gray-100 font-semibold text-sm mb-3">🦈 活跃游资动向</h4>
        <div id="dt-famous-seats" class="space-y-2"></div>
      </div>
    </div>

    <!-- 机构vs游资买卖对比 -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h4 class="text-gray-100 font-semibold text-sm mb-3">📊 机构 vs 游资/散户对比</h4>
        <div class="h-48"><canvas id="dtInstRetailChart"></canvas></div>
      </div>
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h4 class="text-gray-100 font-semibold text-sm mb-3">📋 席位解读</h4>
        <div id="dt-jiedu" class="text-xs text-gray-400 space-y-1 max-h-48 overflow-y-auto custom-scrollbar"></div>
      </div>
    </div>
  </div>

  <!-- ======== 新闻面板 ======== -->
  <div class="card" id="tab-news" style="display:none">
    <div class="card-header"><h3>📰 多源新闻 · 情绪分析</h3></div>
    <div id="newsBody" class="space-y-4 p-4"></div>
  </div>

  <!-- ======== 日报面板 ======== -->
  <div class="card" id="tab-reports" style="display:none">
    <div class="card-header"><h3>📋 日报链接</h3></div>
    <div id="reportsBody" style="font-size:13px;"></div>
  </div>
  <!-- ======== 证据面板 ======== -->
  <div id="tab-evidence" style="display:none" class="space-y-6">
    <div class="grid grid-cols-1 xl:grid-cols-3 gap-4" id="evidence-grade-card">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 xl:col-span-3">
        <div class="flex items-center justify-between">
          <h3 class="text-gray-100 font-semibold">🔬 数据证据链</h3>
          <div id="evidence-grade-badge" class="text-xs px-3 py-1 rounded-full">加载中...</div>
        </div>
        <div id="evidence-grade-text" class="text-sm text-gray-400 mt-2">加载中...</div>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 class="text-gray-100 font-semibold text-sm mb-4">📊 数据质量 — 每个数据源是否可信</h3>
        <div id="evidence-data-quality" class="space-y-2 text-xs"><div class="text-gray-400">加载中...</div></div>
      </div>
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 class="text-gray-100 font-semibold text-sm mb-4">🎯 信号验证 — 过去预测的准确率</h3>
        <div id="evidence-signal-accuracy" class="space-y-2 text-xs"><div class="text-gray-400">加载中...</div></div>
      </div>
    </div>

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 class="text-gray-100 font-semibold text-sm mb-4">📈 业绩归因 — 收益/亏损从哪里来</h3>
        <div id="evidence-attribution" class="space-y-3 text-xs"><div class="text-gray-400">加载中...</div></div>
      </div>
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
        <h3 class="text-gray-100 font-semibold text-sm mb-4">🧩 因子查询 — 输入代码看评分依据</h3>
        <div class="flex gap-2 mb-3">
          <input type="text" id="evidence-symbol-input" placeholder="输入代码如 600519" class="bg-gray-700 text-gray-100 rounded-lg px-3 py-2 text-sm border border-gray-600 w-full" onkeydown="if(event.key==='Enter')loadFactorEvidence()" />
          <button onclick="loadFactorEvidence()" class="bg-blue-600 hover:bg-blue-500 text-white rounded-lg px-4 py-2 text-sm font-medium">查询</button>
        </div>
        <div id="evidence-factor" class="space-y-3 text-xs"><div class="text-gray-400">输入代码后点击查询</div></div>
      </div>
    </div>

    <div class="bg-gray-800 border border-gray-700 rounded-xl p-4">
      <h3 class="text-gray-100 font-semibold text-sm mb-4">💡 使用说明</h3>
      <div class="text-xs text-gray-400 space-y-1">
        <p>📌 <b>数据质量</b> — 每个数据源的新鲜度评分（A级=可信，C级=部分数据过期，D级=不可用）。</p>
        <p>📌 <b>信号验证</b> — 系统发出BUY/SELL信号后N天验证方向正确率。首次运行 run_trading.py 后积累数据。</p>
        <p>📌 <b>业绩归因</b> — Brinson式分解：收益来自选股/行业/因子暴露/交易时机。</p>
        <p>📌 <b>因子查询</b> — 输入个股代码，看每个子因子原始值、排名、方向、评分依据。</p>
      </div>
    </div>
  </div>

  <!-- ======== 大师持仓面板 ======== -->
  <div id="tab-gurus" style="display:none" class="space-y-6">
    <div id="gurus-content"></div>
  </div>

  <!-- ======== 观点库面板 ======== -->
  <div id="tab-insights" style="display:none" class="space-y-6">
    <div id="insights-content"></div>
  </div>
</div>

<script>
let netValueChartInstance = null;
function fmt(v) { return Math.round(v).toLocaleString(); }

// ═══════════ 全局状态 ═══════════
let posTab = 'all';                 // 持仓 tab 过滤
let _v2Detail = null;               // 最近一次 detail 数据 (供 tab/弹窗复用)
const stratBg = { 'faceji': 'bg-blue-500/10', 'silverquant': 'bg-green-500/10', 'tradingagents': 'bg-purple-500/10' };
const stratColors = { 'faceji': 'border-blue-500', 'silverquant': 'border-green-500', 'tradingagents': 'border-purple-500' };
const FACTOR_LABELS = { 'quality': '质量', 'value': '价值', 'growth': '成长', 'momentum': '动量', 'low_vol': '低波', 'sentiment': '情绪', 'industry': '行业', 'dividend': '分红', 'risk': '风险' };
const STRAT_RULES = {
  faceji: { buy: '评分≥5.0 + MA20>MA60(趋势ok, 评分≥5.5可豁免) + 半Kelly仓位(上限8%)', sell: '硬止损-8% / 峰值回落-12% / 评分<4.5 / MA死叉+评分<5' },
  silverquant: { buy: '评分≥5.0 槽位建仓, 固定¥30K/槽, 纯因子无MA过滤', sell: '硬止损-8% / 峰值回落-12% / MA死叉(亏损≥5%豁免) / 评分<4.5' },
  tradingagents: { buy: '辩论分≥5.5 (Bull/Bear均值) + Kelly(上限12%)', sell: '辩论分<4强卖 / <5弱卖 / 硬止损-8%' },
};

// ═══════════ 持仓渲染 (tab 过滤) ═══════════
function setPosTab(s) {
  posTab = s;
  document.querySelectorAll('.pos-tab').forEach(btn => {
    const active = btn.dataset.strat === s;
    btn.className = 'pos-tab px-3 py-1 rounded-lg text-xs border ' +
      (active ? 'bg-blue-600/30 border-blue-500 text-blue-200' : 'border-gray-600 text-gray-300 hover:border-gray-400');
  });
  if (_v2Detail) renderPositionsGrid(_v2Detail);
}

function renderPositionsGrid(detailRes) {
  let posHtml = '';
  let canvasIndex = 0;
  const radarDataList = [];
  for (const [sname, positions] of Object.entries(detailRes.positions || {})) {
    if (posTab !== 'all' && sname !== posTab) continue;
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
      <div class="bg-gray-800 border border-gray-700 rounded-xl p-4 flex flex-col hover:border-gray-500 transition-colors cursor-pointer" onclick="showPositionModal('${sname}','${sym}')">
          <div class="flex justify-between items-start mb-3">
              <div>
                  <div class="flex items-center gap-2">
                      <span class="font-bold text-gray-100 text-lg">${sym}</span>
                      <span class="text-sm text-gray-400">${pos.name || sym}</span>
                  </div>
                  <div class="text-xs px-2 py-0.5 rounded mt-1 inline-block ${stratBg[sname] || 'bg-gray-700'} text-gray-300">${sname}</div>
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
  radarDataList.forEach(item => renderRadarChart(item.id, item.scores));
}

// ═══════════ 交易历史渲染 ═══════════
function renderTradeHistory(detailRes) {
  let allTrades = [];
  for (const [sname, trades] of Object.entries(detailRes.trade_history || {})) {
    trades.forEach(t => allTrades.push({...t, sname}));
  }
  allTrades.sort((a,b) => ((b.date||b.time||'') > (a.date||a.time||'') ? 1 : -1));
  allTrades = allTrades.slice(0, 50);

  let tradeHtml = '';
  allTrades.forEach(tx => {
    const isBuy = tx.action === '买入' || tx.action === 'BUY';
    // 买入行优先显示未实现盈亏; 卖出行显示已实现盈亏
    const pnlVal = tx.unrealized_pnl != null ? tx.unrealized_pnl : tx.pnl;
    const pnlStr = pnlVal != null ? (pnlVal>0?'+':'') + '¥'+Math.round(pnlVal).toLocaleString() : '—';
    const pnlCls = pnlVal > 0 ? 'text-green-500 font-medium' : (pnlVal < 0 ? 'text-red-500' : 'text-gray-400');
    const actCls = isBuy ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400';
    const rowBg = isBuy ? 'bg-green-900/10 hover:bg-green-900/20' : 'bg-red-900/10 hover:bg-red-900/20';
    const rowFont = pnlVal > 0 ? 'font-bold text-white' : 'text-gray-300';
    const holdTxt = tx.hold_days != null ? tx.hold_days + '天' : '—';
    tradeHtml += `
    <tr class="${rowBg} ${rowFont} transition-colors border-b border-gray-800 cursor-pointer" onclick="showTradeModal('${tx.sname}','${tx.symbol}','${(tx.date||tx.time||'').substring(0,10)}')">
        <td class="px-3 py-2 text-gray-400 border-0">${(tx.date||tx.time||'').substring(0,10)}</td>
        <td class="px-3 py-2 border-0"><span class="font-bold text-gray-200">${tx.symbol}</span> <span class="text-[10px] text-gray-500 ml-1">${tx.name||''}</span> <span class="text-[10px] ${stratBg[tx.sname]||'bg-gray-700'} px-1 rounded text-gray-300 ml-1">${tx.sname}</span></td>
        <td class="px-3 py-2 border-0"><span class="px-1.5 py-0.5 rounded text-[10px] ${actCls}">${tx.action}</span></td>
        <td class="px-3 py-2 font-mono border-0">¥${(tx.price||0).toFixed(2)}</td>
        <td class="px-3 py-2 font-mono border-0">${(tx.quantity||0).toLocaleString()}</td>
        <td class="px-3 py-2 font-mono border-0 ${pnlCls}">${pnlStr}</td>
        <td class="px-3 py-2 font-mono text-gray-400 border-0">${holdTxt}</td>
        <td class="px-3 py-2 text-gray-400 truncate max-w-[200px] border-0" title="${tx.reason||''}">${tx.reason||''}</td>
    </tr>`;
  });
  document.getElementById('v2-trade-history').innerHTML = tradeHtml || '<tr><td colspan="8" class="text-center py-4 text-gray-500 border-0">暂无交易历史</td></tr>';
}

// ═══════════ 信号日志渲染 + 历史查看 ═══════════
let _sigList = [];   // 当前信号列表 (今日或所选历史日, 供弹窗取数)
function renderSignalLog(detailRes, dateLabel) {
  _sigList = detailRes.all_signals || [];
  document.getElementById('v2-signal-stats').innerHTML =
    dateLabel ? dateLabel : 
    `原始信号: <span class="text-gray-200">${detailRes.total_raw_signals}</span> → 冲突解决: <span class="text-gray-200">${detailRes.after_conflict_resolution}</span> → 周频过滤: <span class="text-gray-200">${detailRes.after_weekly_filter}</span> → 执行: <span class="text-gray-200">${detailRes.simulated_trades}</span>`;

  let sigHtml = '';
  (detailRes.all_signals || []).forEach(s => {
    const isBuy = s.action === 'BUY' || s.action === '买入';
    const actCls = isBuy ? 'bg-green-900/40 text-green-400' : 'bg-red-900/40 text-red-400';
    const priCls = s.priority === 'HIGH' ? 'text-red-400' : s.priority === 'MED' ? 'text-yellow-400' : 'text-gray-400';
    let statusTag = '';
    if (s.status === 'executed') statusTag = '<span class="text-[10px] bg-blue-900/40 text-blue-400 px-1 rounded ml-1">已执行</span>';
    else if (s.status === 'filtered') statusTag = '<span class="text-[10px] bg-yellow-900/40 text-yellow-500 px-1 rounded ml-1">未执行(冲突/周频)</span>';
    else if (s.status === 'pending') statusTag = '<span class="text-[10px] bg-green-900/40 text-green-400 px-1 rounded ml-1">待执行</span>';
    sigHtml += `
    <tr class="hover:bg-gray-700/50 transition-colors border-b border-gray-700/50 cursor-pointer" onclick="showSignalModal('${s.strategy||''}','${s.symbol}')">
        <td class="px-2 py-2 border-0"><span class="px-1.5 py-0.5 rounded text-[10px] ${actCls}">${s.action}</span></td>
        <td class="px-2 py-2 border-0"><span class="font-mono font-bold text-gray-200">${s.symbol}</span> <span class="text-[10px] text-gray-500">${s.name||''}</span></td>
        <td class="px-2 py-2 border-0 text-gray-400">${s.strategy||'—'}</td>
        <td class="px-2 py-2 border-0 font-mono text-gray-300">${s.score!=null?s.score:'—'}</td>
        <td class="px-2 py-2 border-0 font-mono ${priCls}">${s.priority||'—'}</td>
        <td class="px-2 py-2 border-0">${statusTag||'<span class="text-gray-600">—</span>'}</td>
        <td class="px-2 py-2 border-0 text-gray-400 truncate max-w-[220px]" title="${s.reason||''}">${s.reason||''}</td>
        <td class="px-2 py-2 border-0 text-right"><span class="text-[10px] text-blue-400">🔍 详情</span></td>
    </tr>`;
  });
  document.getElementById('v2-signals-table').innerHTML = sigHtml || '<tr><td colspan="8" class="text-center py-4 text-gray-500 border-0">该日无信号</td></tr>';
}

async function loadSignalHistory(date) {
  if (!date) { if (_v2Detail) renderSignalLog(_v2Detail, ''); return; }
  try {
    const res = await fetch(`/api/v2/signals/history?date=${date}`);
    const d = await res.json();
    const labeled = Object.assign({ all_signals: d.signals || [], total_raw_signals: d.count, after_conflict_resolution: 0, after_weekly_filter: 0, simulated_trades: 0 }, _v2Detail || {});
    renderSignalLog(labeled, `📅 ${date} 信号 (${d.count} 条) — 点击行查看深度分析`);
  } catch(e) { console.error(e); }
}

async function loadSignalDates() {
  try {
    const res = await fetch('/api/v2/signals/history');
    const d = await res.json();
    const sel = document.getElementById('v2-signal-date');
    if (!sel) return;
    const cur = sel.value;
    sel.innerHTML = '<option value="">今日信号</option>' +
      (d.dates || []).slice().reverse().map(x => `<option value="${x}">${x}</option>`).join('');
    if (cur) sel.value = cur;
  } catch(e) {}
}

// ═══════════ 数据一致性校验 ═══════════
async function loadDataConsistency() {
  const el = document.getElementById('consistency-bar');
  if (!el) return;
  try {
    const res = await fetch('/api/v2/data-consistency');
    const d = await res.json();
    if (d.consistent) {
      el.innerHTML = `<span class="text-green-500">🛡️ 数据一致 ✓ (${d.checks.length} 项校验全部通过)</span>`;
    } else {
      const bad = (d.checks || []).filter(c => !c.ok).map(c => `${c.name}: ${c.detail}`).join('; ');
      el.innerHTML = `<span class="text-red-500 font-semibold">🚨 数据不一致: ${bad}</span>`;
    }
  } catch(e) {
    el.innerHTML = '<span class="text-gray-500">数据一致性校验不可用</span>';
  }
}

// ═══════════ 深度分析弹窗 ═══════════
function openModal(html) {
  document.getElementById('modal-content').innerHTML = html;
  const ov = document.getElementById('modal-overlay');
  ov.classList.remove('hidden');
  ov.classList.add('flex');
}
function closeModal() {
  const ov = document.getElementById('modal-overlay');
  ov.classList.add('hidden');
  ov.classList.remove('flex');
}

function factorBarsHtml(scores) {
  if (!scores) return '<div class="text-gray-500 text-xs">无因子数据</div>';
  let html = '<div class="space-y-1.5">';
  for (const [k, v] of Object.entries(scores)) {
    const label = FACTOR_LABELS[k] || k;
    const pct = Math.max(0, Math.min(100, (v || 0) * 100));
    const color = v >= 0.7 ? 'bg-green-500' : v >= 0.45 ? 'bg-yellow-500' : 'bg-red-500';
    html += `<div class="flex items-center gap-2 text-xs">
        <span class="w-8 text-gray-400">${label}</span>
        <div class="flex-1 h-1.5 bg-gray-700 rounded"><div class="h-full ${color} rounded" style="width:${pct}%"></div></div>
        <span class="w-12 text-right font-mono text-gray-300">${(v||0).toFixed(2)}</span>
    </div>`;
  }
  return html + '</div>';
}

function factorTableHtml(fb) {
  if (!fb) return '';
  let rows = '';
  for (const [k, v] of Object.entries(fb)) {
    rows += `<tr class="border-b border-gray-800"><td class="py-1 text-gray-400">${k}</td><td class="py-1 font-mono text-right">${typeof v === 'number' ? v.toFixed(3) : v}</td></tr>`;
  }
  return `<div class="mt-3"><h4 class="text-xs text-gray-400 font-medium mb-1">📐 子因子明细</h4>
    <table class="w-full text-xs"><tbody>${rows || '<tr><td class="text-gray-500">无</td></tr>'}</tbody></table></div>`;
}

function showTradeModal(sname, sym, date) {
  const detail = _v2Detail || {};
  let tx = null;
  for (const [sn, trades] of Object.entries(detail.trade_history || {})) {
    // 匹配: 外层策略 key === sname (API 行内无 sname 字段)
    const hit = (trades || []).find(t =>
      sn === sname && t.symbol === sym &&
      (!date || (t.date||t.time||'').substring(0,10) === date));
    if (hit) { tx = {...hit, sname: sn}; break; }
  }
  if (!tx) { openModal('<div class="text-gray-300">未找到该交易记录</div>'); return; }
  const isBuy = tx.action === '买入' || tx.action === 'BUY';
  const pnlVal = tx.unrealized_pnl != null ? tx.unrealized_pnl : tx.pnl;
  const rule = STRAT_RULES[sname] || {};
  openModal(`
    <div class="flex justify-between items-start mb-4">
      <div>
        <div class="text-lg font-bold text-gray-100">${sym} ${tx.name||''} <span class="text-sm font-normal text-gray-400">${sname}</span></div>
        <div class="text-xs text-gray-500 mt-1">${(tx.date||'').substring(0,10)} · ${tx.action} @ ¥${(tx.price||0).toFixed(2)} × ${(tx.quantity||0).toLocaleString()}</div>
      </div>
      <div class="text-right">
        <div class="text-sm font-mono ${pnlVal>0?'text-green-500':pnlVal<0?'text-red-500':'text-gray-400'}">${pnlVal!=null ? (pnlVal>0?'+':'')+'¥'+Math.round(pnlVal).toLocaleString() : '—'}</div>
        ${tx.unrealized_pnl_pct!=null ? `<div class="text-xs font-mono ${tx.unrealized_pnl_pct>=0?'text-green-500':'text-red-500'}">${tx.unrealized_pnl_pct>=0?'+':''}${tx.unrealized_pnl_pct.toFixed(2)}%</div>` : ''}
        <div class="text-xs text-gray-500 mt-1">${tx.hold_days!=null ? '持有 '+tx.hold_days+' 天' : ''}</div>
      </div>
    </div>
    <div class="grid grid-cols-2 gap-4 mb-4">
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">🎯 ${isBuy ? '买入逻辑' : '卖出逻辑'}</div>
        <div class="text-sm text-gray-200 leading-relaxed">${tx.reason || '—'}</div>
        <div class="text-xs text-gray-500 mt-2 leading-relaxed">${isBuy ? '建仓规则: ' + (rule.buy || '—') : '清仓规则: ' + (rule.sell || '—')}</div>
        ${tx.score ? `<div class="text-xs text-gray-400 mt-2">信号评分: <span class="font-mono text-gray-200">${tx.score}</span></div>` : ''}
      </div>
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">📊 因子视角 (当前扫描)</div>
        ${factorBarsHtml(tx.factor_scores)}
      </div>
    </div>
    ${factorTableHtml(tx.factor_breakdown)}
    <div class="mt-4 text-right"><button onclick="closeModal()" class="px-4 py-1.5 rounded-lg text-xs bg-gray-700 hover:bg-gray-600 text-gray-200">关闭</button></div>
  `);
}

function showPositionModal(sname, sym) {
  const detail = _v2Detail || {};
  const pos = (detail.positions || {})[sname]?.[sym];
  if (!pos) return;
  const rule = STRAT_RULES[sname] || {};
  openModal(`
    <div class="flex justify-between items-start mb-4">
      <div>
        <div class="text-lg font-bold text-gray-100">${sym} ${pos.name||''} <span class="text-sm font-normal text-gray-400">${sname}</span></div>
        <div class="text-xs text-gray-500 mt-1">${pos.entry_date} 买入 · ${pos.hold_days} 天 · 仓位 ${pos.pct}%</div>
      </div>
      <div class="text-right">
        <div class="text-lg font-bold font-mono ${pos.pnl>=0?'text-green-500':'text-red-500'}">${pos.pnl>=0?'+':''}${pos.pnl_pct.toFixed(2)}%</div>
        <div class="text-xs font-mono ${pos.pnl>=0?'text-green-500':'text-red-500'}">${pos.pnl>=0?'+':''}¥${Math.round(pos.pnl).toLocaleString()}</div>
      </div>
    </div>
    <div class="grid grid-cols-2 gap-4 mb-4">
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">🎯 持有逻辑</div>
        <div class="text-sm text-gray-200 leading-relaxed">${pos.reason || '—'}</div>
        <div class="text-xs text-gray-500 mt-2 leading-relaxed">清仓规则: ${rule.sell || '—'}</div>
        <div class="grid grid-cols-2 gap-2 text-xs mt-3">
          <div><span class="text-gray-500">买入价</span><br><span class="font-mono">¥${pos.entry_price.toFixed(2)}</span></div>
          <div><span class="text-gray-500">现价</span><br><span class="font-mono">¥${pos.current_price.toFixed(2)}</span></div>
          <div><span class="text-gray-500">止损线</span><br><span class="font-mono">¥${(pos.stop_loss||0).toFixed(2)}</span></div>
          <div><span class="text-gray-500">评分 ${pos.entry_score?.toFixed(2)||'-'}→${pos.current_score?.toFixed(2)||'-'}</span><br><span class="font-mono text-gray-300">回撤 ${pos.drawdown_from_entry?.toFixed(2)||0}%</span></div>
        </div>
      </div>
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">📊 因子视角</div>
        ${factorBarsHtml(pos.factor_scores)}
      </div>
    </div>
    <div class="mt-4 text-right"><button onclick="closeModal()" class="px-4 py-1.5 rounded-lg text-xs bg-gray-700 hover:bg-gray-600 text-gray-200">关闭</button></div>
  `);
}

function showSignalModal(strategy, sym) {
  const sig = _sigList.find(s => s.strategy === strategy && s.symbol === sym);
  if (!sig) { openModal('<div class="text-gray-300">未找到信号详情</div>'); return; }
  const rule = STRAT_RULES[strategy] || {};
  const isBuy = sig.action === 'BUY' || sig.action === '买入';
  const statusMap = { executed: '✅ 已执行', filtered: '⛔ 未执行(冲突/周频过滤)', pending: '⏳ 待执行' };
  openModal(`
    <div class="flex justify-between items-start mb-4">
      <div>
        <div class="text-lg font-bold text-gray-100">${sym} ${sig.name||''} <span class="text-sm font-normal text-gray-400">${strategy}</span></div>
        <div class="text-xs text-gray-500 mt-1">信号价 ¥${(sig.price||0).toFixed(2)} · ${statusMap[sig.status] || sig.status || ''} · 优先级 ${sig.priority||'—'}</div>
      </div>
      <div class="text-right">
        <div class="text-lg font-bold ${isBuy?'text-green-500':'text-red-500'}">${isBuy ? 'BUY' : 'SELL'}</div>
        <div class="text-xs text-gray-400">评分 <span class="font-mono">${sig.score!=null?sig.score:'—'}</span></div>
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">🎯 信号逻辑</div>
        <div class="text-sm text-gray-200 leading-relaxed">${sig.reason || '—'}</div>
        <div class="text-xs text-gray-500 mt-2 leading-relaxed">${isBuy ? '建仓规则: ' + (rule.buy || '—') : '清仓规则: ' + (rule.sell || '—')}</div>
        <div class="text-xs text-gray-400 mt-2">建议仓位: <span class="font-mono text-gray-200">${sig.size_pct!=null ? sig.size_pct + '%' : '—'}</span></div>
      </div>
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">📊 因子视角 (当日扫描)</div>
        ${factorBarsHtml(sig.factor_scores || (detail.positions||{})[strategy]?.[sym]?.factor_scores)}
      </div>
    </div>
    ${factorTableHtml(sig.factor_breakdown)}
    <div class="mt-4 text-right"><button onclick="closeModal()" class="px-4 py-1.5 rounded-lg text-xs bg-gray-700 hover:bg-gray-600 text-gray-200">关闭</button></div>
  `);
}

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
    _v2Detail = detailRes;

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

    // Positions Grid (tab 过滤) + Radars
    renderPositionsGrid(detailRes);

    // Trade History (点击行 → 深度分析弹窗)
    renderTradeHistory(detailRes);

    // Signals (今日) + 历史日期下拉
    renderSignalLog(detailRes, '');
    loadSignalDates();

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
            window.factorExplainCache = explainRes.factors;
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
            const fb = i.factor_breakdown || {};
            const explainMap = {};
            if (window.factorExplainCache) {
                window.factorExplainCache.forEach(f => {
                    if (f.sub_keys) explainMap[f.key] = f.sub_keys;
                });
            }
            let barsHtml = '<div class="flex gap-1 items-end h-8">';
            factorKeys.forEach((fk, idx) => {
                const val = sc[fk] || 0;
                const h = Math.max(10, val * 100) + '%';
                let bColor = 'bg-gray-600';
                if (val >= 0.7) bColor = 'bg-green-500';
                else if (val >= 0.5) bColor = 'bg-blue-500';
                else if (val < 0.3) bColor = 'bg-red-500';
                const subKeys = explainMap[fk] || [];
                const subLines = subKeys.length > 0
                    ? subKeys.map(sk => { const sv = fb[sk]; return sv !== undefined ? `${sk.split(':')[1]}=${sv.toFixed(2)}` : ''; }).filter(Boolean).join('\\n')
                    : '';
                const tooltip = subLines ? `${factorLabels[idx]}: ${val.toFixed(2)}\n${subLines}` : `${factorLabels[idx]}: ${val.toFixed(2)}`;
                barsHtml += `<div class="flex flex-col items-center justify-end w-4 group relative" title="${tooltip.replace(/"/g, '&quot;')}"><div class="w-full ${bColor} rounded-t-sm opacity-80 group-hover:opacity-100 transition-opacity" style="height: ${h}"></div><div class="text-[8px] text-gray-500 mt-0.5">${factorLabels[idx]}</div></div>`;
            });
            barsHtml += '</div>';
            
            const deepBtn = t.id === 'deep' ? `<button onclick="event.stopPropagation();loadResearchReport('${i.symbol}')" title="查看研报" class="text-xs bg-purple-900/40 hover:bg-purple-800/60 text-purple-300 px-2 py-1 rounded transition-colors flex-shrink-0">📋研报</button>` : '';
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
                ${deepBtn}
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

  const sections = ['tab-dashboard', 'tab-pool', 'tab-etf', 'tab-news', 'tab-reports', 'tab-comparison', 'tab-dragon_tiger', 'tab-evidence', 'tab-gurus', 'tab-insights'];
  sections.forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = 'none';
  });

  const panel = document.getElementById('tab-'+tab);
  if (panel) panel.style.display = '';

  if (tab === 'dashboard') { loadDashboardV2(); loadExecutionBoard(); }
  else if (tab === 'pool') loadPoolV2();
  else if (tab === 'etf') loadEtf();
  else if (tab === 'news') loadNews();
  else if (tab === 'reports') loadReports();
  else if (tab === 'comparison') loadComparison();
  else if (tab === 'dragon_tiger') loadDragonTiger();
  else if (tab === 'evidence') loadEvidence();
  else if (tab === 'gurus') loadGurusTab();
  else if (tab === 'insights') loadInsightsTab();
  return false;
}

// ═══════════════════════════════════════════
// 六层横条
// ═══════════════════════════════════════════
async function loadLayerBar() {
  try {
    const res = await fetch('/api/v2/layers/status');
    if (!res.ok) return;
    const data = await res.json();
    const layers = data.layers || {};
    
    // L1: 宏观
    const l1 = layers.l1_macro || {};
    const dg = l1.dual_gate || {};
    document.getElementById('l1-content').textContent = 
      `双门:${dg.macro||'?'}/${dg.trend||'?'} · ${l1.quadrant||'?'} · ${l1.trend_temp||'平'}`;
    document.getElementById('l1-status').textContent = l1.strategy_switch === 'on' ? '🟢' : l1.strategy_switch === 'off' ? '🔴' : '🟡';
    
    // L2: 配置
    const l2 = layers.l2_allocation || {};
    const a = l2.actual || {};
    const fmtPct = (v) => (v != null ? v + '%' : '?');
    document.getElementById('l2-content').textContent = 
      `A股${fmtPct(a['A股'])} · ETF${fmtPct(a['ETF'])} · 债券${fmtPct(a['债券'])} · 黄金${fmtPct(a['黄金'])}`;
    const devs = Object.entries(l2.deviations || {}).filter(([k,v]) => Math.abs(v) > 5);
    document.getElementById('l2-status').textContent = devs.length > 0 ? `⚠️${devs.length}` : '✅';
    
    // L3-L4: 选股
    const l34 = layers.l3_l4_stock_picking || {};
    const chainTxt = l34.active_chains != null ? `${l34.active_chains.length}条` : '?';
    document.getElementById('l3-content').textContent = 
      `候选${l34.total_candidates||0}只 · 链${chainTxt}活跃`;
    document.getElementById('l3-status').textContent = (l34.new_today||0) > 0 ? `🆕+${l34.new_today}` : `${l34.total_candidates||0}只`;
    
    // L5: 风控
    const l5 = layers.l5_risk || {};
    const l5status = l5.status || 'normal';
    document.getElementById('l5-content').textContent = 
      `止损${l5.triggered_stops||0}只 · 回撤${l5.max_drawdown||0}%`;
    const statusIcon = l5status === 'critical' ? '🔴' : l5status === 'warning' ? '🟡' : '🟢';
    document.getElementById('l5-status').textContent = `${statusIcon} ${l5status}`;
    
    // L6: 纪律 (按策略周频, 避免把"策略数"当"交易数")
    const l6 = layers.l6_discipline || {};
    const lim = l6.weekly_limit || 3;
    const per = l6.per_strategy || {};
    const labelMap = { faceji: '面基', silverquant: 'SQ', tradingagents: 'TA' };
    const parts = Object.entries(per).map(([s, c]) => {
      const over = c > lim;
      return `${labelMap[s]||s}${c}/${lim}${over ? '⚠️' : ''}`;
    });
    const l6txt = parts.length > 0 ? `本周${parts.join(' · ')}次` : `本周0/${lim}次`;
    document.getElementById('l6-content').textContent = l6txt;
    document.getElementById('l6-status').textContent = l6.over_limit ? '🔴超限' : '✅';
  } catch(e) {
    console.error('LayerBar error:', e);
  }
}

function toggleLayerDetail(layer) {
  // Future: expand detailed view for each layer
}

// ═══════════════════════════════════════════
// 执行决策区
// ═══════════════════════════════════════════
async function loadExecutionBoard() {
  const boardEl = document.getElementById('board-content');
  const dqEl = document.getElementById('board-data-quality');
  if (!boardEl) return;
  boardEl.innerHTML = '<div class="text-gray-400 text-sm">⏳ 加载执行决策...</div>';
  
  // 超时兜底：8 秒还没加载完就显示降级信息 (AbortController 真正中断请求, 防止永久加载)
  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    boardEl.innerHTML = '<div class="text-gray-400 text-sm">⏱️ 执行决策加载超时—数据管线可能正在刷新，请2分钟后刷新查看</div><div class="text-xs text-gray-500 mt-1">提示：执行决策需要 run_trading.py 生成评分数据</div>';
    if (dqEl) dqEl.textContent = '数据质量: ⏳ 超时';
  }, 8000);
  const ctrl = new AbortController();
  const abortTimer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const res = await fetch('/api/v2/execution/board', { signal: ctrl.signal });
    clearTimeout(abortTimer);
    if (!res.ok) { boardEl.innerHTML = '<div class="text-gray-400 text-sm">暂无决策数据</div>'; return; }
    const data = await res.json();
    if (data.status !== 'ok' || !data.board) {
      boardEl.innerHTML = '<div class="text-gray-400 text-sm">暂无决策数据（需运行run_trading.py生成）</div>';
      return;
    }
    
    // 数据质量 (带6s超时, 失败/超时给出可视反馈而非永久"—")
    try {
      const dqRes = await Promise.race([
        fetch('/api/v2/evidence/data-quality'),
        new Promise((_, rej) => setTimeout(() => rej(new Error('dq-timeout')), 6000))
      ]);
      const dqData = await dqRes.json();
      if (dqEl) dqEl.textContent = `数据质量: ${dqData.grade || '?'} (${(dqData.overall_score || 0).toFixed(2)})`;
    } catch(e) {
      if (dqEl) dqEl.textContent = '数据质量: ⏳ 暂无';
    }

    // 事件风险 (带6s超时)
    let eventRiskHtml = '<span class="px-2.5 py-1 rounded-lg bg-gray-800 text-gray-500 border border-gray-700">事件风险: 暂无</span>';
    try {
      const erRes = await Promise.race([
        fetch('/api/v2/execution/event-risk'),
        new Promise((_, rej) => setTimeout(() => rej(new Error('er-timeout')), 6000))
      ]);
      if (erRes.ok) {
        const erData = await erRes.json();
        if (erData.status === 'ok' && erData.event_risk) {
          const er = erData.event_risk;
          const level = er.level;
          const triggeredBy = (er.triggered_by || []).join('; ');
          const hoverText = triggeredBy ? ` title="触发原因: ${triggeredBy}"` : '';
          
          if (level === 'none') {
            eventRiskHtml = `<span class="px-2.5 py-1 rounded-lg bg-gray-800 text-green-400 border border-gray-700 cursor-help"${hoverText}>🟢 事件风险: 无</span>`;
          } else if (level === 'moderate') {
            eventRiskHtml = `<span class="px-2.5 py-1 rounded-lg bg-yellow-900/40 text-yellow-400 border border-yellow-700/50 cursor-help"${hoverText}>🟡 事件风险: 控制仓位</span>`;
          } else if (level === 'high') {
            eventRiskHtml = `<span class="px-2.5 py-1 rounded-lg bg-orange-900/40 text-orange-400 border border-orange-700/50 cursor-help"${hoverText}>🟠 事件风险: 降仓建议</span>`;
          } else if (level === 'extreme') {
            eventRiskHtml = `<span class="px-2.5 py-1 rounded-lg bg-red-900/40 text-red-400 border border-red-700/50 cursor-help"${hoverText}>🔴 事件风险: 清仓建议</span>`;
          }
        }
      }
    } catch(e) {
      // 保持暂无
    }
    
    const board = data.board;
    window._boardData = data;   // 供弹窗深钻
    const m = data.macro || {};
    const dg = m.dual_gate || {};
    const counts = { buy: (board.buy||[]).length, sell: (board.sell||[]).length, hold: (board.hold||[]).length, wait: (board.wait||[]).length, excluded: (board.excluded||[]).length };
    const total = counts.buy + counts.sell + counts.hold + counts.wait;

    let html = '';
    // ── 统计条 ──
    html += `<div class="flex flex-wrap gap-2 mb-4 text-xs">
      <span class="px-2.5 py-1 rounded-lg bg-green-900/40 text-green-400">🟢 买入 ${counts.buy}</span>
      <span class="px-2.5 py-1 rounded-lg bg-red-900/40 text-red-400">🔴 卖出 ${counts.sell}</span>
      <span class="px-2.5 py-1 rounded-lg bg-yellow-900/40 text-yellow-400">🟡 持有 ${counts.hold}</span>
      <span class="px-2.5 py-1 rounded-lg bg-gray-700 text-gray-300">◻️ 等待 ${counts.wait}</span>
      ${counts.excluded ? `<span class="px-2.5 py-1 rounded-lg bg-gray-800 text-gray-500 border border-gray-700">⛔ 禁反手 ${counts.excluded}</span>` : ''}
      <span class="px-2.5 py-1 rounded-lg bg-gray-800 text-gray-400 border border-gray-700">🌐 ${m.quadrant||'?'} · 双门 ${dg.macro_gate||dg.macro||'?'}/${dg.trend_gate||dg.trend||'?'}</span>
      ${eventRiskHtml}
      ${total === 0 ? '<span class="text-gray-500 self-center">今日无待处理信号</span>' : ''}
    </div>`;

    // ── 分组决策表 ──
    const groups = [
      ['buy', '🟢 建议买入', 'text-green-400'],
      ['sell', '🔴 建议卖出', 'text-red-400'],
      ['hold', '🟡 继续持有', 'text-yellow-400'],
      ['wait', '◻️ 等待/未达建仓', 'text-gray-400'],
      ['excluded', '⛔ 今日已止损·禁止反手', 'text-gray-500'],
    ];
    groups.forEach(([key, title, tcls]) => {
      const items = board[key] || [];
      if (items.length === 0) return;
      html += `<div class="mb-4"><h4 class="${tcls} font-medium mb-2">${title} <span class="text-gray-500">(${items.length})</span></h4>`;
      html += `<table class="w-full text-xs text-left whitespace-nowrap" style="border:none">
        <thead class="text-gray-500" style="border:none"><tr>
          <th class="px-2 py-1.5 font-medium border-0">标的</th>
          <th class="px-2 py-1.5 font-medium border-0">评分</th>
          <th class="px-2 py-1.5 font-medium border-0">置信度</th>
          <th class="px-2 py-1.5 font-medium border-0">关键因子</th>
          <th class="px-2 py-1.5 font-medium border-0">依据</th>
          <th class="px-2 py-1.5 font-medium border-0"></th>
        </tr></thead><tbody>`;
      items.forEach(s => {
        const e = s.evidence || {};
        const w = (e.why_high || []).slice(0, 2);
        const l = (e.why_low || []).slice(0, 1);
        const pct = Math.max(0, Math.min(100, (s.composite || 0) * 100));
        const compColor = s.composite >= 0.7 ? 'bg-green-500' : s.composite >= 0.45 ? 'bg-yellow-500' : 'bg-red-500';
        const keyF = [...w.map(x => '▲' + x), ...l.map(x => '▼' + x)].join(' ') || '—';
        html += `<tr class="hover:bg-gray-700/40 transition-colors cursor-pointer border-b border-gray-800" onclick="showBoardModal('${s.symbol}')">
          <td class="px-2 py-2 border-0"><span class="font-bold text-gray-200">${s.symbol}</span> <span class="text-[10px] text-gray-500">${s.name||''}</span></td>
          <td class="px-2 py-2 border-0"><div class="flex items-center gap-1.5"><div class="w-16 h-1.5 bg-gray-700 rounded"><div class="h-full ${compColor} rounded" style="width:${pct}%"></div></div><span class="font-mono text-gray-300">${(s.composite||0).toFixed(2)}</span></div></td>
          <td class="px-2 py-2 border-0 font-mono text-gray-400">${((s.action_confidence||0)*100).toFixed(0)}%</td>
          <td class="px-2 py-2 border-0 text-gray-400">${keyF}</td>
          <td class="px-2 py-2 border-0 text-gray-400 truncate max-w-[220px]" title="${s.action_reason||''}">${s.action_reason||''}</td>
          <td class="px-2 py-2 border-0 text-right"><span class="text-[10px] text-blue-400">🔍 详情</span></td>
        </tr>`;
      });
      html += `</tbody></table></div>`;
    });

    if (!html) html = '<div class="text-gray-400 text-sm">今日无待处理信号</div>';
    if (!timedOut) {
      boardEl.innerHTML = html;
      clearTimeout(timeoutId);
    }
  } catch(e) {
    if (!timedOut) {
      boardEl.innerHTML = '<div class="text-gray-400 text-sm">执行决策暂不可用</div>';
      clearTimeout(timeoutId);
    }
    console.error('Execution board error:', e);
  }
}

// ── 执行决策弹窗: 评分构成 + 建仓检查 + 证据链 + 拉高/拖低 + TrailStop ──
function showBoardModal(sym) {
  const bd = window._boardData || {};
  const board = bd.board || {};
  let entry = null;
  for (const k of ['buy', 'sell', 'hold', 'wait']) {
    const hit = (board[k] || []).find(x => x.symbol === sym);
    if (hit) { entry = hit; break; }
  }
  if (!entry) { openModal('<div class="text-gray-300">未找到决策详情</div>'); return; }

  const e = entry.evidence || {};
  const dq = entry.data_quality || {};
  const cl = entry.build_checklist || {};
  const clPassed = Object.values(cl).filter(v => v.status === true).length;
  const clTotal = Object.keys(cl).length;
  const actionMap = { buy: '🟢 建议买入', sell: '🔴 建议卖出', hold: '🟡 继续持有', wait: '◻️ 等待', excluded: '⛔ 禁反手' };
  const actionKey = (['buy','sell','hold','wait','excluded']).find(k => (board[k]||[]).some(x => x.symbol === sym)) || 'hold';

  // 建仓检查 6 项
  const clLabels = { dual_gate_open: '双门开启', macro_ok: '宏观象限', technical_ok: '技术确认(动量)', quality_gate: '质量门控', position_limit: '仓位上限', single_stock_limit: '单一标的限制' };
  let clHtml = '';
  for (const [k, v] of Object.entries(cl)) {
    const ok = v.status === true;
    clHtml += `<div class="flex items-start gap-2 py-1.5 border-b border-gray-800">
      <span class="${ok ? 'text-green-500' : 'text-red-500'} w-4">${ok ? '✅' : '❌'}</span>
      <span class="w-28 text-gray-300">${clLabels[k] || k}</span>
      <span class="text-gray-500 flex-1">${v.detail || ''}</span>
    </div>`;
  }

  // 证据链 5 层
  let chainHtml = '';
  (e.chain || []).forEach(c => {
    const icon = c.status === 'missing' ? '⬜' : c.status === 'warning' ? '⚠️' : '✅';
    const src = c.source && c.source !== 'N/A' ? ` <span class="text-gray-600">[${c.source}]</span>` : '';
    chainHtml += `<div class="py-1.5 border-b border-gray-800">
      <div><span>${icon}</span> <span class="text-gray-200">${c.label}</span>${src}</div>
      <div class="text-gray-500 text-xs mt-0.5">${c.rationale || ''}${c.warning ? ' ⚠️ ' + c.warning : ''}</div>
    </div>`;
  });

  const w = (e.why_high || []).map(x => `<span class="px-2 py-0.5 rounded bg-green-900/40 text-green-400 text-xs mr-1">${x}</span>`).join('');
  const l = (e.why_low || []).map(x => `<span class="px-2 py-0.5 rounded bg-red-900/40 text-red-400 text-xs mr-1">${x}</span>`).join('');
  const ts = entry.trail_stop || {};

  openModal(`
    <div class="flex justify-between items-start mb-4">
      <div>
        <div class="text-lg font-bold text-gray-100">${sym} ${entry.name||''} <span class="text-sm font-normal text-gray-400">${actionMap[actionKey]}</span></div>
        <div class="text-xs text-gray-500 mt-1">${e.claim || ''} · 置信度 ${((entry.action_confidence||0)*100).toFixed(0)}%</div>
      </div>
      <div class="text-right">
        <div class="text-2xl font-bold font-mono ${entry.composite>=0.7?'text-green-500':entry.composite>=0.45?'text-yellow-500':'text-red-500'}">${(entry.composite||0).toFixed(2)}</div>
        <div class="text-xs text-gray-500">综合评分</div>
        <div class="text-[10px] text-gray-600 mt-1">数据质量 ${dq.grade||'?'} · 子因子 ${dq.factor_count||0}项</div>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">📊 因子视角 (7维风格分)</div>
        ${factorBarsHtml(entry.scores)}
      </div>
      <div class="bg-gray-800 rounded-xl p-3">
        <div class="text-xs text-gray-400 mb-2">🧾 建仓检查 ${clPassed}/${clTotal}</div>
        ${clHtml || '<div class="text-gray-500 text-xs">非候选(持仓中)</div>'}
      </div>
    </div>

    <div class="bg-gray-800 rounded-xl p-3 mb-4">
      <div class="text-xs text-gray-400 mb-2">🔗 证据链 (数据层→因子层→信号层→执行层)</div>
      ${chainHtml}
    </div>

    <div class="flex flex-wrap gap-2 mb-3">
      ${w ? `<div class="text-xs"><span class="text-gray-500 mr-1">📈 拉高:</span>${w}</div>` : ''}
      ${l ? `<div class="text-xs"><span class="text-gray-500 mr-1">📉 拖低:</span>${l}</div>` : ''}
    </div>

    ${Object.keys(ts).length ? `<div class="bg-gray-800 rounded-xl p-3 mb-4">
      <div class="text-xs text-gray-400 mb-1">🛡️ TrailStop</div>
      <div class="text-sm text-gray-200">${ts.status || '—'} ${ts.distance_pct != null ? `· 距止损 ${ts.distance_pct.toFixed(1)}%` : ''} ${ts.stop_price ? `· 止损价 ¥${ts.stop_price}` : ''}</div>
    </div>` : ''}

    ${factorTableHtml(entry.factor_breakdown)}

    <div class="mt-4 text-right"><button onclick="closeModal()" class="px-4 py-1.5 rounded-lg text-xs bg-gray-700 hover:bg-gray-600 text-gray-200">关闭</button></div>
  `);
}

function toggleEvidence(symbol) {
  const el = document.getElementById('ev-' + symbol);
  if (el) el.style.display = el.style.display === 'none' ? 'block' : 'none';
}

window.onload = () => { loadLayerBar(); loadDashboardV2(); loadExecutionBoard(); loadDataConsistency(); };
setInterval(() => { loadLayerBar(); loadDashboardV2(); loadExecutionBoard(); loadDataConsistency(); }, 120000);

async function loadEtf() {
  const el = document.getElementById('etfBody');
  el.innerHTML = '<div class="text-gray-400 p-4">⏳ 加载中...</div>';
  try {
    const [scanRes, portfolioRes] = await Promise.all([
      fetch('/api/v2/etf/scan').then(r => r.json()).catch(() => ({})),
      fetch('/api/v2/etf/portfolio').then(r => r.json()).catch(() => ({}))
    ]);

    let html = '';

    // ── 组合配置 ──
    if (portfolioRes && !portfolioRes.error && portfolioRes.combined) {
      html += '<div class="bg-gray-800 rounded-xl p-4 mb-4">';
      html += '<h4 class="text-sm font-semibold text-gray-300 mb-3">📊 组合配置建议</h4>';
      const tp = portfolioRes.timing_portfolio;
      const nt = portfolioRes.non_timing_portfolio;
      if (tp) {
        html += `<div class="mb-3"><span class="text-blue-400 font-medium text-sm">▸ 择时组合 (${tp.strategy || 'TrendFollowing'})</span>`;
        html += buildEtfTableV2(tp.symbols || []);
        html += '</div>';
      }
      if (nt) {
        html += `<div class="mb-3"><span class="text-green-400 font-medium text-sm">▸ 非择时组合 (${nt.strategy || 'RiskParity'})</span>`;
        html += buildEtfTableV2(nt.symbols || []);
        html += '</div>';
      }
      if (portfolioRes.combined && portfolioRes.combined.length > 0) {
        html += '<div class="mb-1"><span class="text-purple-400 font-medium text-sm">▸ 合并建议</span>';
        html += buildEtfTableV2(portfolioRes.combined);
        html += '</div>';
      }
      html += `<div class="text-xs text-gray-500 mt-2">更新: ${portfolioRes.timestamp || ''} | 价格日期: ${portfolioRes.price_date || ''}</div>`;
      html += '</div>';
    }

    // ── ETF 扫描结果 ──
    if (scanRes && !scanRes.error && scanRes.etfs) {
      const etfs = scanRes.etfs;
      const categories = {};
      etfs.forEach(e => {
        const cat = e.category || 'other';
        if (!categories[cat]) categories[cat] = [];
        categories[cat].push(e);
      });

      const catLabels = {broad:'宽基', sector:'行业', commodity:'商品', bond:'债券', cross_border:'跨境', strategy:'策略'};
      html += '<div class="bg-gray-800 rounded-xl p-4">';
      html += `<h4 class="text-sm font-semibold text-gray-300 mb-3">🔍 ETF 扫描 (${etfs.length}只) <span class="text-xs text-gray-500 ml-2">${scanRes.scan_date || ''}</span></h4>`;

      for (const [cat, list] of Object.entries(categories)) {
        html += `<div class="mb-4"><div class="text-xs font-medium text-gray-400 mb-2">${catLabels[cat] || cat} (${list.length})</div>`;
        html += '<div class="overflow-x-auto"><table class="w-full text-xs"><thead class="text-gray-400 border-b border-gray-700"><tr>';
        html += '<th class="py-2 text-left">代码</th><th class="text-left">名称</th><th class="text-right">现价</th><th class="text-center">趋势</th><th class="text-right">20D</th><th class="text-right">60D</th><th class="text-right">波动率</th><th class="text-center">组合</th>';
        html += '</tr></thead><tbody>';
        list.forEach(e => {
          const trendColor = e.trend === '↑' ? 'text-green-500' : 'text-red-500';
          const ret20Color = e.ret_20d >= 0 ? 'text-green-500' : 'text-red-500';
          const ret60Color = e.ret_60d >= 0 ? 'text-green-500' : 'text-red-500';
          const role = [e.is_timing ? '择时' : '', e.is_rp ? '平价' : ''].filter(Boolean).join('/');
          html += `<tr class="border-b border-gray-700/50 hover:bg-gray-700/30 cursor-pointer" onclick="loadEtfDetail('${e.symbol}')">
            <td class="py-1.5 font-mono text-blue-400">${e.symbol}</td>
            <td class="text-gray-200">${e.name}</td>
            <td class="text-right font-mono text-gray-200">${e.price || '—'}</td>
            <td class="text-center ${trendColor} font-bold">${e.trend || '—'}</td>
            <td class="text-right font-mono ${ret20Color}">${e.ret_20d >= 0 ? '+' : ''}${e.ret_20d || 0}%</td>
            <td class="text-right font-mono ${ret60Color}">${e.ret_60d >= 0 ? '+' : ''}${e.ret_60d || 0}%</td>
            <td class="text-right font-mono text-gray-400">${e.vol_20d || 0}%</td>
            <td class="text-center text-[10px] text-gray-500">${role || '—'}</td>
          </tr>`;
        });
        html += '</tbody></table></div></div>';
      }
      html += '</div>';
    }

    if (!html) {
      html = '<div class="bg-yellow-900/30 text-yellow-400 p-4 rounded-lg">⚠️ 暂无ETF数据，需先运行 python3 analysis/etf_portfolio.py</div>';
    }

    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ 加载失败: ${e.message}</div>`;
  }
}

async function loadEtfDetail(symbol) {
  try {
    const r = await fetch(`/api/v2/etf/detail/${symbol}`);
    const data = await r.json();
    if (data.error) { alert(data.error); return; }

    const etf = data.etf || {};
    const price = data.price || {};
    const returns = data.returns || {};
    const signals = data.trend_signals || [];
    const role = data.portfolio_role || [];

    let html = `<div class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onclick="this.remove()">`;
    html += `<div class="bg-gray-800 border border-gray-600 rounded-xl p-6 max-w-lg w-full" onclick="event.stopPropagation()">`;
    html += `<div class="flex justify-between items-center mb-4"><h3 class="text-lg font-bold text-gray-100">${etf.name || symbol} (${etf.symbol || symbol})</h3>`;
    html += `<button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-200">✕</button></div>`;

    if (etf.benchmark) html += `<div class="text-xs text-gray-400 mb-3">跟踪: ${etf.benchmark} | 费率: ${(etf.fee_pct*100).toFixed(3)}% | ${etf.category} | ${etf.region}</div>`;

    html += '<div class="grid grid-cols-2 gap-3 mb-4">';
    html += `<div class="bg-gray-700/50 rounded p-2"><div class="text-xs text-gray-400">现价</div><div class="font-mono text-lg text-gray-100">${price.current || '—'}</div></div>`;
    html += `<div class="bg-gray-700/50 rounded p-2"><div class="text-xs text-gray-400">MA20/MA60</div><div class="font-mono text-sm ${price.ma20 >= price.ma60 ? 'text-green-500' : 'text-red-500'}">${price.ma20 || '—'} / ${price.ma60 || '—'}</div></div>`;
    html += '</div>';

    html += '<div class="mb-4"><div class="text-xs text-gray-400 mb-1">历史回报</div><div class="flex gap-2 flex-wrap">';
    for (const [label, val] of Object.entries(returns)) {
      const cls = val >= 0 ? 'text-green-500' : 'text-red-500';
      html += `<span class="bg-gray-700 rounded px-2 py-1 text-xs"><span class="text-gray-400">${label}:</span> <span class="font-mono ${cls}">${val >= 0 ? '+' : ''}${val}%</span></span>`;
    }
    html += '</div></div>';

    if (signals.length) {
      html += '<div class="mb-4"><div class="text-xs text-gray-400 mb-1">趋势信号</div>';
      signals.forEach(s => { html += `<div class="text-xs text-gray-300">• ${s}</div>`; });
      html += '</div>';
    }

    if (data.volatility) {
      html += `<div class="text-xs text-gray-400">20日年化波动率: <span class="font-mono text-gray-200">${data.volatility.annualized_20d || 0}%</span>`;
      html += ` | 60日最大回撤: <span class="font-mono text-red-400">${data.max_drawdown_60d || 0}%</span></div>`;
    }

    if (role.length) {
      html += `<div class="mt-3 text-xs"><span class="text-gray-400">组合归属:</span> ${role.map(r => `<span class="bg-blue-900/40 text-blue-400 rounded px-2 py-0.5 ml-1">${r}</span>`).join('')}</div>`;
    }

    html += '</div></div>';
    document.body.insertAdjacentHTML('beforeend', html);
  } catch(e) {
    alert('加载失败: ' + e.message);
  }
}

function buildEtfTableV2(symbols) {
  if (!symbols || symbols.length === 0) return '<div class="text-gray-500 text-xs py-2">暂无数据</div>';
  const actionLabel = {BUY:'买入', SELL:'卖出', HOLD:'持有'};
  const actionColor = {BUY:'bg-green-900/40 text-green-400', SELL:'bg-red-900/40 text-red-400', HOLD:'bg-gray-700 text-gray-400'};
  return '<table class="w-full text-xs mt-2"><thead class="text-gray-400 border-b border-gray-700"><tr><th class="py-1.5 text-left">代码</th><th class="text-left">名称</th><th class="text-center">操作</th><th class="text-right">权重</th><th class="text-left">理由</th></tr></thead><tbody>' +
    symbols.map(s => {
      const act = s.action || 'HOLD';
      return `<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
        <td class="py-1.5 font-mono text-blue-400">${s.etf_symbol || s.symbol || ''}</td>
        <td class="text-gray-200">${s.name || ''}</td>
        <td class="text-center"><span class="px-1.5 py-0.5 rounded text-[10px] ${actionColor[act] || ''}">${actionLabel[act] || act}</span></td>
        <td class="text-right font-mono text-gray-200">${((s.weight||0)*100).toFixed(1)}%</td>
        <td class="text-gray-400 text-[11px]">${(s.reason || '').substring(0,40)}</td>
      </tr>`;
    }).join('') + '</tbody></table>';
}

let comparisonChartInstance = null;
let underwaterChartInstance = null;

function applyQuickDays(days) {
  const end = new Date();
  const start = new Date(end.getTime() - days * 86400000);
  document.getElementById('btStartDate').value = start.toISOString().split('T')[0];
  document.getElementById('btEndDate').value = end.toISOString().split('T')[0];
}

async function loadComparison() {
  const el = document.getElementById('comparisonContent');
  el.innerHTML = `
    <div class="text-gray-400 p-4 text-center">
      <div class="text-lg mb-2">📊 策略回测对比</div>
      <div class="text-sm">选择参数后点击「运行回测」开始</div>
    </div>`;
}

async function runCustomBacktest() {
  const el = document.getElementById('comparisonContent');
  const strategy = document.getElementById('btStrategy')?.value || 'all';
  const startDate = document.getElementById('btStartDate')?.value || '';
  const endDate = document.getElementById('btEndDate')?.value || '';
  const symbols = document.getElementById('btSymbols')?.value || '';
  const wf = document.getElementById('btWF')?.checked || false;
  const wfCycles = parseInt(document.getElementById('btWFCycles')?.value || '3', 10) || 3;

  let days = 60;
  if (startDate && endDate) {
    try {
      const d1 = new Date(startDate);
      const d2 = new Date(endDate);
      days = Math.max(7, Math.round((d2 - d1) / 86400000));
    } catch(e) {}
  }

  // ─── Stage 1: 数据准备中 ───
  el.innerHTML = `
    <div class="bg-gray-800 rounded-xl p-6 text-center">
      <div class="text-2xl mb-3">📡</div>
      <div class="text-lg text-gray-200 font-semibold mb-2">数据准备中...</div>
      <div class="text-sm text-gray-400 mb-4">正在拉取日线数据</div>
      <div class="bg-gray-700 rounded-full h-2 overflow-hidden w-64 mx-auto">
        <div id="btProgressBar" class="bg-blue-500 h-full rounded-full transition-all duration-1000" style="width:15%"></div>
      </div>
      <div class="text-xs text-gray-500 mt-2" id="btProgressText">初始化数据源...</div>
    </div>`;

  let progress = 15;
  const progressInterval = setInterval(() => {
    if (progress < 85) {
      progress += Math.random() * 12 + 5;
      if (progress > 85) progress = 85;
      const bar = document.getElementById('btProgressBar');
      if (bar) bar.style.width = progress + '%';
      const txt = document.getElementById('btProgressText');
      if (txt) {
        if (progress < 40) txt.textContent = '拉取日线数据...';
        else if (progress < 70) txt.textContent = '计算技术指标...';
        else txt.textContent = '准备策略参数...';
      }
    }
  }, 800);

  // ─── Stage 2: 回测运行中 (after 2.5s) ───
  setTimeout(() => {
    const bar = document.getElementById('btProgressBar');
    if (bar) bar.style.width = '88%';
    const txt = document.getElementById('btProgressText');
    if (txt) txt.textContent = '🔄 回测运行中... 逐日模拟交易';
    const header = el.querySelector('.text-lg');
    if (header) header.textContent = '回测运行中...';
    const emoji = el.querySelector('.text-2xl');
    if (emoji) emoji.textContent = '🔄';
  }, 2500);

  try {
    let url = `/api/v2/backtest/custom?strategy=${strategy}&days=${days}`;
    if (startDate) url += `&start_date=${startDate}`;
    if (endDate) url += `&end_date=${endDate}`;
    if (symbols) url += `&symbols=${encodeURIComponent(symbols)}`;
    if (wf) url += `&walk_forward=true&cycles=${wfCycles}`;

    const r = await fetch(url);
    clearInterval(progressInterval);
    const data = await r.json();

    if (data.error) {
      el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ ${data.error}</div>`;
      return;
    }

    // ─── Stage 3: 展示结果 ───
    const strategies = [data.faceji, data.silverquant, data.tradingagents].filter(Boolean);
    const colors = {
      'faceji (面基)': { line: '#58a6ff', bg: 'bg-blue-900/20' },
      'silverquant (组件化)': { line: '#3fb950', bg: 'bg-green-900/20' },
      'tradingagents (辩论制)': { line: '#bc8cff', bg: 'bg-purple-900/20' },
    };
    const params = data.params || {};
    const hasEquityCurve = strategies.some(s => s.daily_values && s.daily_values.length > 0);
    const bm = data.benchmark && (data.benchmark.values||[]).length ? data.benchmark : null;
    const bmPct = bm && bm.pct_change != null ? bm.pct_change : null;

    let html = '';

    // ── 参数信息条 ──
    html += `<div class="bg-gray-800/50 rounded-lg p-3 mb-4 flex flex-wrap gap-4 text-xs text-gray-400">
      <span>📊 策略: <strong class="text-gray-200">${params.strategy || strategy}</strong></span>
      <span>📅 周期: <strong class="text-gray-200">${data.days_analyzed || days}天</strong></span>
      ${params.start_date ? `<span>从 <strong class="text-gray-200">${params.start_date}</strong></span>` : ''}
      ${params.end_date ? `<span>到 <strong class="text-gray-200">${params.end_date}</strong></span>` : ''}
      ${params.symbols ? `<span>标的: <strong class="text-gray-200">${params.symbols}</strong></span>` : ''}
      <span>更新: <strong class="text-gray-200">${data.run_date || ''}</strong></span>
      ${params.walk_forward ? `<span class="bg-purple-900/40 text-purple-300 px-2 py-0.5 rounded text-[10px]">🧪 Walk-Forward 样本外评估 (${params.cycles||3}周期)</span>` : ''}
    </div>`;

    // ── Walk-Forward 周期明细表 ──
    if (params.walk_forward) {
      html += `<div class="bg-gray-800 rounded-xl p-4 mb-6">
        <h4 class="text-sm font-semibold text-gray-300 mb-3">🧪 Walk-Forward 逐期样本外结果 <span class="text-gray-500 text-[10px] font-normal">(训练窗口前移, 每周期只用样本外做测试)</span></h4>`;
      strategies.forEach(s => {
        const details = ((s.extra||{}).cycle_details) || [];
        if (!details.length) return;
        const c = colors[s.name] || { line: '#fff' };
        html += `<div class="mb-3">
          <div class="text-xs font-medium mb-1.5" style="color:${c.line}">● ${s.name} <span class="text-gray-500">— 平均收益 ${(s.total_return_pct||0)>=0?'+':''}${(s.total_return_pct||0)}% · 平均夏普 ${((s.sharpe_ratio)||0).toFixed(2)} · 平均回撤 -${(s.max_drawdown_pct||0)}%</span></div>
          <div class="overflow-x-auto"><table class="w-full text-xs">
            <thead class="text-gray-400 border-b border-gray-700"><tr>
              <th class="py-1.5 pr-2 text-left">周期</th><th class="pr-2 text-right">样本外天数</th>
              <th class="pr-2 text-right">收益率</th><th class="pr-2 text-right">夏普</th>
              <th class="pr-2 text-right">索提诺</th><th class="pr-2 text-right">最大回撤</th>
              <th class="text-right">交易/胜</th>
            </tr></thead><tbody>`;
        details.forEach(cd => {
          const retCls = cd.return_pct >= 0 ? 'text-green-400' : 'text-red-400';
          html += `<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
            <td class="py-1.5 pr-2 text-gray-300">W${cd.cycle}</td>
            <td class="pr-2 text-right font-mono text-gray-400">${cd.test_days||'-'}</td>
            <td class="pr-2 text-right font-mono ${retCls}">${cd.return_pct>=0?'+':''}${cd.return_pct}%</td>
            <td class="pr-2 text-right font-mono text-gray-200">${cd.sharpe!=null?cd.sharpe.toFixed(2):'-'}</td>
            <td class="pr-2 text-right font-mono text-gray-200">${cd.sortino!=null?cd.sortino.toFixed(2):'-'}</td>
            <td class="pr-2 text-right font-mono text-red-400">-${cd.max_drawdown_pct||0}%</td>
            <td class="text-right font-mono text-gray-400">${cd.trade_count||0}/${cd.win_count||0}</td>
          </tr>`;
        });
        html += '</tbody></table></div></div>';
      });
      html += '</div>';
    }

    // ── 策略指标卡片 ──
    if (strategies.length > 0 && !strategies[0].note) {
      html += '<div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-6">';
      strategies.forEach(s => {
        const retCls = s.total_return_pct >= 0 ? 'text-green-500' : 'text-red-500';
        const c = colors[s.name] || { line: '#6b7280', bg: 'bg-gray-800' };
        html += `
        <div class="bg-gray-800 border border-gray-700 border-t-4 rounded-xl p-4" style="border-top-color:${c.line}">
          <div class="font-semibold text-gray-200 mb-2 text-sm">${s.name}</div>
          <div class="text-3xl font-bold ${retCls} mb-3">${s.total_return_pct >= 0 ? '+' : ''}${s.total_return_pct}%</div>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div class="bg-gray-700/50 rounded p-2">
              <div class="text-gray-400">年化收益</div>
              <div class="font-mono ${(s.annualized_return_pct||0)>=0?'text-green-400':'text-red-400'}">${(s.annualized_return_pct||0)>=0?'+':''}${(s.annualized_return_pct||0).toFixed(1)}%</div>
            </div>
            <div class="bg-gray-700/50 rounded p-2">
              <div class="text-gray-400">夏普比率</div>
              <div class="font-mono text-gray-200">${(s.sharpe_ratio||0).toFixed(2)}</div>
            </div>
            <div class="bg-gray-700/50 rounded p-2">
              <div class="text-gray-400">索提诺</div>
              <div class="font-mono text-gray-200">${(s.sortino_ratio||0).toFixed(2)}</div>
            </div>
            <div class="bg-gray-700/50 rounded p-2">
              <div class="text-gray-400">最大回撤</div>
              <div class="font-mono text-red-400">-${(s.max_drawdown_pct||0).toFixed(1)}%</div>
            </div>
            <div class="bg-gray-700/50 rounded p-2">
              <div class="text-gray-400">卡玛比率</div>
              <div class="font-mono text-gray-200">${(s.calmar_ratio||0).toFixed(2)}</div>
            </div>
            <div class="bg-gray-700/50 rounded p-2">
              <div class="text-gray-400">胜率/交易</div>
              <div class="font-mono text-gray-200">${(s.win_rate||0).toFixed(0)}% / ${s.total_trades||0}笔</div>
            </div>
            <div class="bg-gray-700/50 rounded p-2 col-span-2 ${bmPct==null?'opacity-50':''}">
              <div class="text-gray-400">超额α (${bm?bm.name:'沪深300'})</div>
              <div class="font-mono ${bmPct==null?'text-gray-500':(s.total_return_pct - bmPct >= 0 ? 'text-green-400' : 'text-red-400')}">
                ${bmPct==null ? '— 无基准' : (s.total_return_pct - bmPct >= 0 ? '+' : '') + (s.total_return_pct - bmPct).toFixed(2) + '%'}
                ${bmPct!=null ? `<span class="text-gray-500 text-[10px]">(基准 ${bmPct>=0?'+':''}${bmPct}%)</span>` : ''}
              </div>
            </div>
          </div>
        </div>`;
      });
      html += '</div>';
    } else if (strategies[0]?.note) {
      html += `<div class="bg-yellow-900/30 text-yellow-400 p-4 rounded-lg mb-4">⚠️ ${strategies[0].note}</div>`;
    }

    // ── 净值曲线 + 基准 + 水下图 ──
    if (hasEquityCurve) {
      const bmBadge = bm ? `<span class="ml-2 px-1.5 py-0.5 rounded bg-gray-700 text-gray-300 text-[10px]">${bm.name} ${bmPct>=0?'+':''}${bmPct}%</span>` : '';
      html += `
      <div class="bg-gray-800 rounded-xl p-4 mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-sm font-semibold text-gray-300">📉 策略净值曲线 <span class="text-gray-500 text-[10px] font-normal">(归一化: 首日=1.0)</span></h4>
          <div class="text-xs text-gray-400">基准: 沪深300${bmBadge}</div>
        </div>
        <div style="height:300px"><canvas id="comparisonChart"></canvas></div>
        ${!bm ? `<div class="text-yellow-500 text-xs mt-2">⚠️ 基准线数据不可用(数据源未响应)，仅展示策略净值。超额α按无基准处理。</div>` : ''}
      </div>
      <div class="bg-gray-800 rounded-xl p-4 mb-6">
        <div class="flex items-center justify-between mb-3">
          <h4 class="text-sm font-semibold text-gray-300">🌊 回撤水下图</h4>
          <div class="text-xs text-gray-500">各策略自峰值回撤 (%, 下探为亏损)</div>
        </div>
        <div style="height:200px"><canvas id="underwaterChart"></canvas></div>
      </div>`;
    }

    // ── 交易明细 ──
    html += '<div class="bg-gray-800 rounded-xl p-4"><h4 class="text-sm font-semibold text-gray-300 mb-3">📋 交易明细</h4>';
    let hasTrades = false;
    strategies.forEach(s => {
      const trades = (s.trades || []).slice(-30).reverse();
      if (trades.length === 0) return;
      hasTrades = true;
      html += `<div class="mb-4">
        <div class="text-xs font-medium mb-2" style="color:${(colors[s.name]||{}).line||'#fff'}">● ${s.name} (${trades.length}笔)</div>
        <div class="overflow-x-auto"><table class="w-full text-xs">
          <thead class="text-gray-400 border-b border-gray-700"><tr>
            <th class="py-2 pr-2 text-left">日期</th><th class="pr-2 text-left">代码</th><th class="pr-2 text-left">操作</th>
            <th class="pr-2 text-right">价格</th><th class="pr-2 text-right">数量</th><th class="pr-2 text-right">盈亏</th><th class="text-left">原因</th>
          </tr></thead><tbody>`;
      trades.forEach(tx => {
        const isBuy = (tx.action||'').includes('买入') || tx.action === 'BUY';
        const pnlCls = tx.pnl > 0 ? 'text-green-500 font-semibold' : (tx.pnl < 0 ? 'text-red-500' : 'text-gray-400');
        html += `<tr class="border-b border-gray-700/50 hover:bg-gray-700/30">
          <td class="py-1.5 pr-2 text-gray-400">${tx.date||tx.time||''}</td>
          <td class="pr-2 font-mono">${tx.symbol||''}</td>
          <td class="pr-2"><span class="px-1.5 py-0.5 rounded text-[10px] ${isBuy?'bg-green-900/40 text-green-400':'bg-red-900/40 text-red-400'}">${tx.action}</span></td>
          <td class="pr-2 text-right font-mono">¥${(tx.price||0).toFixed(2)}</td>
          <td class="pr-2 text-right font-mono">${(tx.qty||tx.quantity||0).toLocaleString()}</td>
          <td class="pr-2 text-right font-mono ${pnlCls}">${tx.pnl!=null ? (tx.pnl>0?'+':'')+'¥'+fmt(tx.pnl) : '—'}</td>
          <td class="text-gray-400 text-[11px] truncate max-w-[200px]">${(tx.reason||'').substring(0,40)}</td>
        </tr>`;
      });
      html += '</tbody></table></div></div>';
    });
    if (!hasTrades) {
      html += '<div class="text-gray-500 text-xs py-4 text-center">暂无交易记录</div>';
    }
    html += '</div>';

    el.innerHTML = html;

    // ── 渲染净值曲线图(叠加基准) + 回撤水下图 ──
    if (hasEquityCurve) {
      setTimeout(() => {
        const bmColor = '#e3b341';
        // 归一化策略净值到首日=1.0, 与基准同座标可叠加
        const normSeries = strategies
          .filter(s => s.daily_values && s.daily_values.length > 1)
          .map(s => {
            const base = s.daily_values[0].value;
            const norm = s.daily_values.map(d => ({ date: d.date, y: base > 0 ? +(d.value / base) : d.value }));
            return { s, norm };
          });
        const seriesForChart = normSeries.length ? normSeries :
          strategies.filter(s => s.daily_values && s.daily_values.length).map(s => ({ s, norm: (s.daily_values||[]).map(d => ({x: d.date, y: 1.0})) }));

        const cmpCtx = document.getElementById('comparisonChart');
        if (cmpCtx) {
          if (comparisonChartInstance) comparisonChartInstance.destroy();
          const datasets = seriesForChart.map(({s, norm}) => ({
            label: `${s.name} (${(s.total_return_pct||0)>=0?'+':''}${(s.total_return_pct||0).toFixed(1)}%)`,
            data: norm.map(d => ({x: d.x, y: d.y})),
            borderColor: (colors[s.name] || {line:'#7ee787'}).line,
            backgroundColor: (colors[s.name] || {line:'#7ee787'}).line + '15',
            borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.2, fill: false,
          }));
          // 基准线叠加(虚线)
          if (bm) {
            const bmData = bm.dates.map((d, i) => ({x: d, y: bm.values[i]}));
            datasets.push({
              label: `${bm.name} 基准 (${bmPct>=0?'+':''}${bmPct}%)`,
              data: bmData, borderColor: bmColor, borderDash: [6,4],
              backgroundColor: bmColor + '15', borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.2, fill: false,
            });
          }
          comparisonChartInstance = new Chart(cmpCtx, {
            type: 'line',
            data: { datasets },
            options: {
              responsive: true, maintainAspectRatio: false,
              interaction: { mode: 'index', intersect: false },
              plugins: {
                legend: { position: 'top', labels: { color: '#c9d1d9', font: { size: 10 }, usePointStyle: true } },
                tooltip: {
                  backgroundColor: 'rgba(17, 24, 39, 0.95)',
                  titleColor: '#fff', bodyColor: '#fff',
                  borderColor: 'rgba(75, 85, 99, 1)', borderWidth: 1,
                  callbacks: {
                    label: function(ctx) {
                      const v = ctx.raw.y;
                      return (ctx.dataset.label||'').split(' (')[0] + ': ' + (v>=1?'+':'') + ((v-1)*100).toFixed(2) + '%';
                    }
                  }
                }
              },
              scales: {
                x: { type: 'time', time: { unit: 'day', tooltipFormat: 'yyyy-MM-dd', displayFormats: { day: 'MM-dd' } },
                     ticks: { color: '#8b949e', font: { size: 10 }, maxTicksLimit: 15 },
                     grid: { color: '#21262d' } },
                y: { ticks: { color: '#8b949e', font: { size: 10 }, callback: v => (v>=1?'+':'') + ((v-1)*100).toFixed(1) + '%' },
                     grid: { color: '#21262d' }, beginAtZero: false }
              }
            }
          });
        }

        // ── 回撤水下图: 每策略自峰值回撤% ──
        const uwCtx = document.getElementById('underwaterChart');
        if (uwCtx) {
          if (underwaterChartInstance) underwaterChartInstance.destroy();
          const uwDatasets = seriesForChart.map(({s, norm}) => {
            let peak = -Infinity;
            const dd = norm.map(d => {
              peak = Math.max(peak, d.y);
              const pct = peak > 0 ? (d.y / peak - 1) * 100 : 0;
              return {x: d.x, y: +(pct.toFixed(2))};
            });
            return {
              label: s.name,
              data: dd, borderColor: (colors[s.name] || {line:'#7ee787'}).line,
              backgroundColor: (colors[s.name] || {line:'#7ee787'}).line + '22',
              borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 4, tension: 0.2, fill: true,
            };
          });
          underwaterChartInstance = new Chart(uwCtx, {
            type: 'line',
            data: { datasets: uwDatasets },
            options: {
              responsive: true, maintainAspectRatio: false,
              interaction: { mode: 'index', intersect: false },
              plugins: {
                legend: { position: 'top', labels: { color: '#c9d1d9', font: { size: 10 }, usePointStyle: true } },
                tooltip: { backgroundColor: 'rgba(17,24,39,0.95)', titleColor: '#fff', bodyColor: '#fff',
                           borderColor: 'rgba(75,85,99,1)', borderWidth: 1,
                           callbacks: { label: c => `${c.dataset.label}: ${c.raw.y}%` } }
              },
              scales: {
                x: { type: 'time', time: { unit: 'day', tooltipFormat: 'yyyy-MM-dd', displayFormats: { day: 'MM-dd' } },
                     ticks: { color: '#8b949e', font: { size: 9 }, maxTicksLimit: 12 }, grid: { color: '#21262d' } },
                y: { ticks: { color: '#8b949e', font: { size: 9 }, callback: v => v + '%' },
                     grid: { color: '#21262d' } }
              }
            }
          });
        }
      }, 100);
    }

  } catch(e) {
    clearInterval(progressInterval);
    el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ 加载失败: ${e.message}</div>`;
  }
}

async function loadNews() {
  const el = document.getElementById('newsBody');
  el.innerHTML = '<div class="text-gray-400 p-4">⏳ 加载中...</div>';
  try {
    const [newsRes, sentimentRes] = await Promise.all([
      fetch('/api/v2/news?limit=200').then(r => r.json()).catch(() => ({})),
      fetch('/api/v2/news/sentiment').then(r => r.json()).catch(() => ({}))
    ]);

    let html = '';
    const items = newsRes.items || [];
    const categories = newsRes.categories || [];
    const ts = newsRes.timestamp || '';
    const daysStale = newsRes.days_stale || 0;
    const freshness = newsRes.freshness || 'unknown';
    const sentimentSummary = newsRes.sentiment_summary || sentimentRes.summary || {};

    // ── 情绪分析概览 ──
    if (sentimentSummary && (sentimentSummary.positive > 0 || sentimentSummary.negative > 0 || sentimentSummary.neutral > 0)) {
      const total = sentimentSummary.total || (sentimentSummary.positive + sentimentSummary.negative + sentimentSummary.neutral) || 0;
      const pos = sentimentSummary.positive || 0;
      const neg = sentimentSummary.negative || 0;
      const neu = sentimentSummary.neutral || 0;
      html += '<div class="bg-gray-800 rounded-xl p-4 mb-4">';
      html += '<h4 class="text-sm font-semibold text-gray-300 mb-3">🧠 情绪分析概览</h4>';
      html += '<div class="grid grid-cols-4 gap-3 mb-3">';
      html += `<div class="bg-gray-700/50 rounded-lg p-2 text-center"><div class="text-xs text-gray-400">总数</div><div class="text-xl font-bold text-gray-100">${total}</div></div>`;
      html += `<div class="bg-green-900/30 rounded-lg p-2 text-center"><div class="text-xs text-green-400">🟢 利好</div><div class="text-xl font-bold text-green-500">${pos}</div></div>`;
      html += `<div class="bg-red-900/30 rounded-lg p-2 text-center"><div class="text-xs text-red-400">🔴 利空</div><div class="text-xl font-bold text-red-500">${neg}</div></div>`;
      html += `<div class="bg-gray-700/50 rounded-lg p-2 text-center"><div class="text-xs text-gray-400">⚪ 中性</div><div class="text-xl font-bold text-gray-300">${neu}</div></div>`;
      html += '</div></div>';
    }

    // ── 新闻面板 v3: 分类标签 + 情绪徽章 ──
    if (items.length > 0) {
      // 源徽章样式映射
      const sourceBadges = {
        '东方财富':     'bg-blue-900/40 text-blue-400',
        '东方财富7×24': 'bg-orange-900/40 text-orange-400',
        '财联社':       'bg-purple-900/40 text-purple-400',
        '巨潮资讯':     'bg-yellow-900/40 text-yellow-400',
      };

      // 分类标签映射（优先使用新格式，兼容旧格式）
      const tabMap = {
        '个股新闻': { label: '📊 个股',    icon: '📊' },
        '7×24快讯': { label: '⚡ 快讯',    icon: '⚡' },
        '电报快讯': { label: '📡 电报',    icon: '📡' },
        '公告':     { label: '📋 公告',    icon: '📋' },
        '宏观政策': { label: '🏛 宏观',    icon: '🏛' },
        '市场动态': { label: '📈 市场',    icon: '📈' },
        '大宗商品': { label: '🛢 商品',    icon: '🛢' },
        '产业趋势': { label: '🔬 产业',    icon: '🔬' },
        '产业消息': { label: '🏭 产业',    icon: '🏭' },
        '综合':     { label: '📋 综合',    icon: '📋' },
      };

      html += '<div class="bg-gray-800 rounded-xl p-4">';
      // ── Header: 标题 + 新鲜度 + 刷新按钮 ──
      html += '<div class="flex items-center justify-between mb-3">';
      html += `<h4 class="text-sm font-semibold text-gray-300">📰 实时新闻 (${items.length}条)</h4>`;
      html += '<div class="flex items-center gap-2">';
      const freshColors = {fresh: 'text-green-400', stale: 'text-yellow-400', expired: 'text-red-400'};
      const freshLabels = {fresh: '新鲜', stale: '超过3天', expired: '超过7天'};
      html += `<span class="text-xs ${freshColors[freshness] || 'text-gray-400'}">${daysStale}d ${freshLabels[freshness] || ''}</span>`;
      html += `<button onclick="refreshNews()" class="bg-blue-600 hover:bg-blue-500 text-white rounded px-2 py-1 text-xs">🔄 刷新</button>`;
      html += '</div></div>';
      html += `<div class="text-xs text-gray-500 mb-3">数据源: 东方财富 · 财联社 · 巨潮资讯 | 更新: ${ts.substring(0,19)}</div>`;

      // ── 分类标签: 全部 / 个股 / 快讯 / 电报 / 公告 ──
      if (categories.length > 0) {
        html += '<div class="flex gap-2 mb-3 flex-wrap" id="newsCategoryTabs">';
        html += '<button class="news-cat-btn bg-blue-600 text-white rounded px-3 py-1 text-xs font-medium" data-cat="" onclick="filterNewsV3()">全部</button>';
        categories.forEach(cat => {
                const tabInfo = tabMap[cat] || { label: cat, icon: '' };
                html += `<button class="news-cat-btn bg-gray-700 text-gray-300 rounded px-3 py-1 text-xs hover:bg-gray-600" data-cat="${cat}" onclick="filterNewsV3(this.dataset.cat)">${tabInfo.label}</button>`;
              });
        html += '</div>';
      }

      // ── 新闻列表 ──
      html += '<div class="space-y-2 custom-scrollbar" style="max-height: 600px; overflow-y: auto;" id="newsItemsV3">';
      items.forEach((item, idx) => {
        const cat = item.category || '';
        const title = item.title || item.content || '';
        const link = item.link || '';
        const source = item.source || '';
        const published = item.published || '';
        const sentiment = item.sentiment || 'neutral';

        // 源徽章
        const srcCls = sourceBadges[source] || 'bg-gray-700 text-gray-400';

        // 情绪徽章
        let sentBadge = '';
        if (sentiment === 'positive') {
          sentBadge = '<span class="px-1.5 py-0.5 rounded text-[10px] bg-green-900/40 text-green-400">🟢 利好</span>';
        } else if (sentiment === 'negative') {
          sentBadge = '<span class="px-1.5 py-0.5 rounded text-[10px] bg-red-900/40 text-red-400">🔴 利空</span>';
        } else {
          sentBadge = '<span class="px-1.5 py-0.5 rounded text-[10px] bg-gray-700 text-gray-400">⚪ 中性</span>';
        }

        // 时间戳截取
        const timeDisplay = published.substring(0, 10) === ts.substring(0, 10)
          ? (published.includes('T') ? published.substring(11, 16) : published.substring(11, 16))
          : published.substring(0, 10);

        html += `<div class="border-b border-gray-700/50 pb-2 news-item-v3" data-category="${cat.replace(/"/g, '&quot;')}">
          <div class="flex items-center gap-1.5 mb-1 flex-wrap">
            <span class="px-1.5 py-0.5 rounded text-[10px] ${srcCls}">${source}</span>
            ${sentBadge}
            ${published ? `<span class="text-[10px] text-gray-500 ml-auto">${timeDisplay}</span>` : ''}
          </div>
          <div class="text-xs text-gray-200 leading-relaxed">
            ${link ? `<a href="${link}" target="_blank" class="hover:text-blue-400 transition-colors">${title.substring(0, 200)}${title.length > 200 ? '...' : ''}</a>` : title.substring(0, 200) + (title.length > 200 ? '...' : '')}
          </div>
        </div>`;
      });
      html += '</div>';
      html += '</div>';
    }

    if (!html) {
      html = '<div class="bg-yellow-900/30 text-yellow-400 p-4 rounded-lg">⚠️ 暂无新闻数据。点击刷新获取最新新闻。<button onclick="refreshNews()" class="ml-3 bg-blue-600 text-white rounded px-2 py-1 text-xs">🔄 立即刷新</button></div>';
    }

    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ 加载失败: ${e.message}</div>`;
  }
}

function filterNewsV3(category) {
  // 更新标签按钮样式
  document.querySelectorAll('#newsCategoryTabs .news-cat-btn').forEach(btn => {
    if (!category && btn.textContent.trim() === '全部') {
      btn.className = 'news-cat-btn bg-blue-600 text-white rounded px-3 py-1 text-xs font-medium';
    } else if (category && btn.textContent.trim().includes(category.replace(/^[^ ]* /, ''))) {
      btn.className = 'news-cat-btn bg-blue-600 text-white rounded px-3 py-1 text-xs font-medium';
    } else {
      btn.className = 'news-cat-btn bg-gray-700 text-gray-300 rounded px-3 py-1 text-xs hover:bg-gray-600';
    }
  });
  // 过滤新闻项
  document.querySelectorAll('.news-item-v3').forEach(item => {
    if (!category || item.dataset.category === category) {
      item.style.display = '';
    } else {
      item.style.display = 'none';
    }
  });
}

// 兼容旧版 filterNews
function filterNews(category) {
  document.querySelectorAll('.news-item').forEach(item => {
    if (!category || item.dataset.category === category) {
      item.style.display = '';
    } else {
      item.style.display = 'none';
    }
  });
}

async function refreshNews() {
  const el = document.getElementById('newsBody');
  el.innerHTML = '<div class="text-blue-400 p-4">🔄 正在刷新新闻...</div>';
  try {
    const r = await fetch('/api/v2/news/refresh');
    const data = await r.json();
    if (data.status === 'ok') {
      await loadNews();
    } else {
      el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ 刷新失败: ${data.message || '未知错误'}<br/><button onclick="loadNews()" class="mt-2 bg-blue-600 text-white rounded px-2 py-1 text-xs">🔄 重试</button></div>`;
    }
  } catch(e) {
    el.innerHTML = `<div class="bg-red-900/30 text-red-400 p-4 rounded-lg">❌ 刷新失败: ${e.message}<br/><button onclick="loadNews()" class="mt-2 bg-blue-600 text-white rounded px-2 py-1 text-xs">🔄 重试</button></div>`;
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

async function loadEvidence() {
  const el = document.getElementById('tab-evidence');
  el.style.display = '';
  try {
    // 1. 数据质量
    const dqRes = await fetch('/api/v2/evidence/data-quality').then(r => r.json()).catch(() => ({}));
    const gradeColors = {A:'text-green-400 bg-green-900/40', B:'text-yellow-400 bg-yellow-900/40', C:'text-orange-400 bg-orange-900/40', D:'text-red-400 bg-red-900/40'};
    const gradeCls = gradeColors[dqRes.grade] || 'text-gray-400 bg-gray-700';
    document.getElementById('evidence-grade-badge').innerHTML = `<span class="${gradeCls} px-3 py-1 rounded-full font-bold">${dqRes.grade || '?'}</span>`;
    document.getElementById('evidence-grade-text').innerHTML = dqRes.grade_text || dqRes.evidence || '加载中...';

    let dqHtml = '';
    if (dqRes.entries) {
      dqHtml = '<div class="divide-y divide-gray-700">';
      dqRes.entries.forEach(e => {
        const icon = e.freshness === 'fresh' ? '🟢' : e.freshness === 'stale' ? '🟡' : e.freshness === 'expired' ? '🔴' : '⚫';
        const age = typeof e.age_hours === 'number' ? `${e.age_hours.toFixed(1)}h` : '?';
        dqHtml += `<div class="flex justify-between py-1.5"><span>${icon} ${e.label}</span><span class="text-gray-400">${age} ${e.freshness}</span></div>`;
      });
      dqHtml += '</div>';
    } else {
      dqHtml = '<div class="text-gray-400">暂无数据质量信息</div>';
    }
    document.getElementById('evidence-data-quality').innerHTML = dqHtml;

    // 2. 信号验证
    const saRes = await fetch('/api/v2/evidence/signal-accuracy').then(r => r.json()).catch(() => ({}));
    let saHtml = '';
    if (saRes.data) {
      const d = saRes.data.overall || {};
      saHtml = `
        <div class="bg-gray-700/40 rounded-lg p-3 mb-3">
          <div class="grid grid-cols-2 gap-2 text-xs">
            <div><span class="text-gray-400">交易日:</span> <span class="text-gray-200">${d.total_days || 0}</span></div>
            <div><span class="text-gray-400">总信号:</span> <span class="text-gray-200">${d.total_signals || 0}</span></div>
            <div><span class="text-gray-400">有效价格:</span> <span class="text-gray-200">${d.price_valid || 0}</span></div>
            <div><span class="text-gray-400">跳过(price=0):</span> <span class="text-gray-200">${d.price_zero_skipped || 0}</span></div>
          </div>
        </div>`;
      if (d.total_signals === 0) {
        saHtml += '<div class="bg-yellow-900/30 text-yellow-400 p-3 rounded-lg text-xs">⚠️ 尚无信号验证数据。cron 将在下一个交易日 08:00 自动运行 run_trading.py。</div>';
      }
    } else {
      saHtml = '<div class="bg-yellow-900/30 text-yellow-400 p-3 rounded-lg text-xs">⚠️ 尚未收集信号验证数据</div>';
    }
    document.getElementById('evidence-signal-accuracy').innerHTML = saHtml;

    // 3. 业绩归因
    const attrRes = await fetch('/api/v2/evidence/portfolio-attribution').then(r => r.json()).catch(() => ({}));
    let attrHtml = '';
    if (attrRes.attribution) {
      for (const [sname, a] of Object.entries(attrRes.attribution)) {
        const icon = sname === 'faceji' ? '🧑‍🌾' : sname === 'silverquant' ? '🥈' : '🤖';
        const isPos = (a.total_return || 0) >= 0;
        attrHtml += `<div class="bg-gray-700/40 rounded-lg p-3">
          <div class="flex justify-between items-center mb-1">
            <span class="font-medium text-gray-200">${icon} ${sname}</span>
            <span class="font-mono ${isPos ? 'text-green-500' : 'text-red-500'}">${a.total_return >= 0 ? '+' : ''}${a.total_return.toFixed(2)}%</span>
          </div>
          <div class="text-xs text-gray-400">${a.evidence || ''}</div>
        </div>`;
      }
    }
    document.getElementById('evidence-attribution').innerHTML = attrHtml || '<div class="text-gray-400">暂无归因数据</div>';
  } catch(e) {
    document.getElementById('evidence-data-quality').innerHTML = `<div class="text-red-400">❌ 加载失败: ${e.message}</div>`;
  }
}

async function loadFactorEvidence() {
  const sym = document.getElementById('evidence-symbol-input').value.trim();
  if (!sym) { document.getElementById('evidence-factor').innerHTML = '<div class="text-yellow-400 text-xs">请输入代码</div>'; return; }
  const el = document.getElementById('evidence-factor');
  el.innerHTML = '<div class="text-blue-400">🔍 查询中...</div>';
  try {
    const r = await fetch(`/api/v2/evidence/factor-breakdown/${sym}`).then(r => r.json());
    if (r.status === 'no_data' || r.status === 'not_found') {
      el.innerHTML = `<div class="bg-yellow-900/30 text-yellow-400 p-3 rounded-lg text-xs">⚠️ ${r.message || '未找到'}</div>`;
      return;
    }
    let html = `<div class="bg-gray-700/40 rounded-lg p-3 mb-2">
      <div class="flex justify-between items-center mb-2">
        <div><span class="text-gray-200 font-medium">${r.symbol}</span> <span class="text-gray-400">${r.name || ''}</span></div>
        <div><span class="text-sm font-bold ${r.signal === 'BUY' || r.signal === 'STRONGBUY' ? 'text-green-500' : r.signal === 'SELL' || r.signal === 'STRONGSELL' ? 'text-red-500' : 'text-yellow-400'}">${r.signal || 'HOLD'}</span></div>
      </div>
      <div class="flex justify-between text-xs"><span class="text-gray-400">综合分:</span><span class="font-mono">${(r.composite || 0).toFixed(4)}</span></div>
      <div class="flex justify-between text-xs"><span class="text-gray-400">v3评分:</span><span class="font-mono">${r.composite_v3 || 0}</span></div>
      <div class="flex justify-between text-xs"><span class="text-gray-400">价格:</span><span class="font-mono">${r.price || 0}</span></div>
    </div>`;

    // 因子分解
    if (r.evidence_chain) {
      for (const [fname, fdata] of Object.entries(r.evidence_chain)) {
        const isHigh = fdata.score >= 0.65;
        const isLow = fdata.score <= 0.35;
        const color = isHigh ? 'text-green-400' : isLow ? 'text-red-400' : 'text-gray-300';
        html += `<div class="bg-gray-700/30 rounded-lg p-2 mb-1">
          <div class="flex justify-between text-xs"><span class="text-gray-400">${fname}</span><span class="${color} font-mono">${fdata.score.toFixed(2)}</span></div>
          <div class="text-[10px] text-gray-500 truncate" title="${JSON.stringify(fdata.sub_factors)}">驱动: ${fdata.top_driver || '—'}</div>
        </div>`;
      }
    }
    el.innerHTML = html;
  } catch(e) {
    el.innerHTML = `<div class="text-red-400 text-xs">❌ 查询失败: ${e.message}</div>`;
  }
}

async function loadResearchReport(symbol) {
  try {
    const r = await fetch(`/api/v2/research/report/${symbol}`);
    if (!r.ok) {
      alert('暂无该标的的深度研报。请先运行 scripts/run_deep_research.py 生成研报。');
      return;
    }
    const data = await r.json();
    if (data.error) { alert(data.error); return; }

    const signalColors = { STRONGBUY: 'text-green-400 bg-green-900/40', BUY: 'text-green-300 bg-green-900/30', HOLD: 'text-yellow-400 bg-yellow-900/30', SELL: 'text-red-400 bg-red-900/30' };
    const signalCls = signalColors[data.signal] || 'text-gray-400 bg-gray-700';

    let sectionsHtml = '';
    const sectionOrder = ['公司概况', '财务健康度', '估值分析', '技术面信号', '资金面', '新闻情绪', '风险提示', '操作建议'];
    const secs = data.sections || {};
    sectionOrder.forEach(secName => {
      const content = secs[secName];
      if (content) {
        const iconMap = { '公司概况': '🏢', '财务健康度': '💰', '估值分析': '📊', '技术面信号': '📈', '资金面': '💵', '新闻情绪': '📰', '风险提示': '⚠️', '操作建议': '🎯' };
        sectionsHtml += `
        <div class="bg-gray-700/50 rounded-lg p-3 mb-2">
          <div class="text-xs font-semibold text-gray-300 mb-1">${iconMap[secName]||'📌'} ${secName}</div>
          <div class="text-xs text-gray-400 leading-relaxed">${content}</div>
        </div>`;
      }
    });

    let html = `<div class="fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4" onclick="this.remove()">`;
    html += `<div class="bg-gray-800 border border-gray-600 rounded-xl p-6 max-w-2xl w-full max-h-[85vh] overflow-y-auto custom-scrollbar" onclick="event.stopPropagation()">`;
    html += `<div class="flex justify-between items-center mb-4 sticky top-0 bg-gray-800 z-10 pb-2 border-b border-gray-700">`;
    html += `<div><h3 class="text-lg font-bold text-gray-100">📋 ${data.name || symbol} 深度研报</h3>`;
    html += `<div class="text-xs text-gray-500 mt-0.5">${data.chain||''} · 生成: ${data.generated_at||''}</div></div>`;
    html += `<button onclick="this.closest('.fixed').remove()" class="text-gray-400 hover:text-gray-200 text-xl">✕</button></div>`;

    html += `<div class="flex items-center gap-3 mb-4 flex-wrap">`;
    html += `<span class="px-2 py-1 rounded text-sm font-mono ${signalCls}">${data.signal||'HOLD'}</span>`;
    html += `<span class="text-sm text-gray-400">综合评分: <span class="font-mono text-gray-200">${(data.score||0).toFixed(4)}</span></span>`;
    html += `</div>`;

    if (sectionsHtml) {
      html += sectionsHtml;
    } else if (data.raw_llm_response) {
      html += `<div class="bg-yellow-900/30 text-yellow-400 p-3 rounded text-xs">⚠️ LLM返回解析失败，原始响应:<br/><pre class="mt-2 whitespace-pre-wrap text-[10px]">${data.raw_llm_response.substring(0,500)}</pre></div>`;
    }

    html += '</div></div>';
    document.body.insertAdjacentHTML('beforeend', html);
  } catch(e) {
    alert('加载研报失败: ' + e.message);
  }
}

// ═══════════════════════════════════════════════════
// 🐉 龙虎榜面板
// ═══════════════════════════════════════════════════

let dtChartInstance = null;

async function loadDragonTiger(refresh = false) {
  const url = refresh ? '/api/v2/dragon_tiger?refresh=true' : '/api/v2/dragon_tiger';
  try {
    const r = await fetch(url);
    const data = await r.json();

    if (!data || data.status === 'no_cache') {
      if (!refresh) { loadDragonTiger(true); return; }
      document.getElementById('tab-dragon_tiger').innerHTML =
        '<div class="bg-gray-800 p-4 rounded text-yellow-400 text-sm">⚠️ 暂无龙虎榜数据，今日无上榜标的或数据源不可用</div>';
      return;
    }

    document.getElementById('dt-date').textContent = '📅 ' + (data.date || '—');
    document.getElementById('dt-total').textContent = '上榜 ' + (data.total_records || 0) + ' 只标的';
    if (data.cache_timestamp) {
      document.getElementById('dt-total').textContent += ' | 缓存: ' + data.cache_timestamp.substring(11, 19);
    }

    const ms = data.market_stats || {};
    let msHtml = '';
    if (ms.a_share) msHtml += '<span class="bg-blue-900/40 text-blue-400 px-2 py-0.5 rounded text-[10px]">A股 ' + ms.a_share + '</span> ';
    if (ms.hk) msHtml += '<span class="bg-green-900/40 text-green-400 px-2 py-0.5 rounded text-[10px]">港股 ' + ms.hk + '</span> ';
    if (ms.etf) msHtml += '<span class="bg-purple-900/40 text-purple-400 px-2 py-0.5 rounded text-[10px]">ETF ' + ms.etf + '</span> ';
    document.getElementById('dt-total').innerHTML = msHtml + document.getElementById('dt-total').textContent;

    const ivr = data.institution_vs_retail || {};
    const instCls = ivr.net_buy_institution >= 0 ? 'text-green-500' : 'text-red-500';
    const retailCls = ivr.net_buy_retail >= 0 ? 'text-green-500' : 'text-red-500';
    document.getElementById('dt-overview').innerHTML =
      '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3">' +
        '<div class="text-xs text-gray-400 mb-1">机构净买入</div>' +
        '<div class="text-lg font-bold font-mono '+instCls+'">' + (ivr.net_buy_institution_fmt||'0') + '</div>' +
        '<div class="text-[10px] text-gray-500">' + (ivr.inst_stock_count||0) + '只机构参与股</div>' +
      '</div>' +
      '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3">' +
        '<div class="text-xs text-gray-400 mb-1">游资/散户净买入</div>' +
        '<div class="text-lg font-bold font-mono '+retailCls+'">' + (ivr.net_buy_retail_fmt||'0') + '</div>' +
        '<div class="text-[10px] text-gray-500">' + (ivr.total_stocks||0) + '只总上榜</div>' +
      '</div>' +
      '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3">' +
        '<div class="text-xs text-gray-400 mb-1">活跃游资</div>' +
        '<div class="text-lg font-bold text-yellow-400">' + ((data.famous_seats&&data.famous_seats.active_celebrities)?data.famous_seats.active_celebrities.length:0) + '</div>' +
        '<div class="text-[10px] text-gray-500">位知名游资上榜</div>' +
      '</div>' +
      '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3">' +
        '<div class="text-xs text-gray-400 mb-1">WATCHLIST交集</div>' +
        '<div class="text-lg font-bold text-blue-400">' + (data.watchlist_overlap||[]).length + '</div>' +
        '<div class="text-[10px] text-gray-500">只关注标的上榜</div>' +
      '</div>';

    let topHtml = '';
    const overlapSyms = new Set((data.watchlist_overlap||[]).map(function(w){return w.symbol;}));
    (data.top_stocks || []).forEach(function(s) {
      const isWl = overlapSyms.has(s.symbol);
      topHtml +=
      '<tr class="hover:bg-gray-700/30 border-b border-gray-700/50' + (isWl ? ' bg-yellow-900/10' : '') + '">' +
        '<td class="py-1.5 pr-2 border-0 text-gray-500">' + s.rank + '</td>' +
        '<td class="py-1.5 pr-2 font-mono text-blue-400 border-0">' + s.symbol +
          (isWl ? '<span class="text-yellow-500 text-[10px] ml-1" title="WATCHLIST">⭐</span>' : '') + '</td>' +
        '<td class="py-1.5 pr-2 text-gray-200 border-0">' + (s.display_name||s.name||'') +
          (s.chain && s.chain !== '其他' ? '<span class="text-[10px] bg-gray-700 text-gray-400 px-1 rounded ml-1">' + s.chain + '</span>' : '') + '</td>' +
        '<td class="py-1.5 pr-2 text-right font-mono border-0 ' + (s.net_buy >= 0 ? 'text-green-500' : 'text-red-500') + '">' + (s.net_buy_fmt||'0') + '</td>' +
        '<td class="py-1.5 pr-2 text-right font-mono text-gray-300 border-0">' + (s.net_buy_pct ? s.net_buy_pct.toFixed(2) + '%' : '—') + '</td>' +
        '<td class="py-1.5 text-gray-400 text-[10px] truncate max-w-[160px] border-0" title="' + (s.reason||'') + '">' + ((s.reason||'').substring(0,30)) + '</td>' +
      '</tr>';
    });
    document.getElementById('dt-top10-table').innerHTML = topHtml || '<tr><td colspan="6" class="text-center py-4 text-gray-500 border-0">暂无上榜数据</td></tr>';

    const celebs = (data.famous_seats&&data.famous_seats.active_celebrities)?data.famous_seats.active_celebrities:[];
    let celebHtml = '';
    if (celebs.length === 0) {
      celebHtml = '<div class="text-gray-500 text-xs py-4 text-center">今日无知名游资上榜</div>';
    } else {
      celebs.forEach(function(c) {
        const net = c.total_buy - c.total_sell;
        const netCls = net >= 0 ? 'text-green-500' : 'text-red-500';
        celebHtml +=
        '<div class="bg-gray-700/50 rounded-lg p-2.5 border border-gray-600/30">' +
          '<div class="flex justify-between items-center mb-1.5">' +
            '<span class="text-sm font-bold text-yellow-400">' + c.name + '</span>' +
            '<span class="text-xs font-mono ' + netCls + '">净' + (net >= 0 ? '+' : '') + (net/1e4).toFixed(0) + '万</span>' +
          '</div>' +
          '<div class="flex gap-4 text-[10px] text-gray-400">' +
            '<span>买 <span class="text-green-400">' + c.buy_count + '</span> 只 <span class="text-green-400">' + (c.total_buy/1e4).toFixed(0) + '万</span></span>' +
            '<span>卖 <span class="text-red-400">' + c.sell_count + '</span> 只 <span class="text-red-400">' + (c.total_sell/1e4).toFixed(0) + '万</span></span>' +
          '</div>' +
          (c.stocks_bought.length ? '<div class="text-[10px] text-gray-500 mt-1">📈买入: ' + c.stocks_bought.join(', ') + '</div>' : '') +
          (c.stocks_sold.length ? '<div class="text-[10px] text-gray-500">📉卖出: ' + c.stocks_sold.join(', ') + '</div>' : '') +
        '</div>';
      });
    }
    document.getElementById('dt-famous-seats').innerHTML = celebHtml;

    if (ivr.net_buy_institution || ivr.net_buy_retail) {
      renderDtInstRetailChart(ivr.net_buy_institution, ivr.net_buy_retail);
    }

    let jdHtml = '';
    (data.top_stocks || []).slice(0, 8).forEach(function(s) {
      if (s.jiedu) {
        jdHtml += '<div class="flex gap-2"><span class="text-blue-400 font-mono w-14 shrink-0">' + s.symbol + '</span><span class="text-gray-300">' + s.jiedu + '</span></div>';
      }
    });
    document.getElementById('dt-jiedu').innerHTML = jdHtml || '<div class="text-gray-500">暂无解读</div>';

    const overlap = data.watchlist_overlap || [];
    const wlDiv = document.getElementById('dt-watchlist');
    if (overlap.length > 0) {
      wlDiv.classList.remove('hidden');
      let wlHtml = '';
      overlap.forEach(function(w) {
        const chgCls = w.change_pct >= 0 ? 'text-green-500' : 'text-red-500';
        const info = w.watch_info || {};
        wlHtml +=
        '<div class="flex items-center gap-3 bg-gray-700/30 rounded-lg p-2.5 border border-yellow-600/20 hover:border-yellow-500/50 transition-colors">' +
          '<span class="font-mono text-blue-400 text-sm w-16">' + w.symbol + '</span>' +
          '<span class="text-gray-200 text-sm flex-1">' + (w.display_name||w.name) +
            (info.chain ? '<span class="text-[10px] bg-gray-700 text-gray-400 px-1 rounded ml-1">' + info.chain + '</span>' : '') +
            (info.tier ? '<span class="text-[10px] bg-yellow-900/40 text-yellow-500 px-1 rounded ml-1">' + info.tier + '</span>' : '') + '</span>' +
          '<span class="font-mono text-sm ' + (w.net_buy >= 0 ? 'text-green-500' : 'text-red-500') + '">' + (w.net_buy_fmt||'0') + '</span>' +
          '<span class="font-mono text-sm ' + chgCls + ' w-14 text-right">' + (w.change_pct >= 0 ? '+' : '') + ((w.change_pct||0).toFixed(1)) + '%</span>' +
          '<span class="text-[10px] text-gray-500 truncate max-w-[140px]" title="' + (w.reason||'') + '">' + ((w.reason||'').substring(0,20)) + '</span>' +
        '</div>';
      });
      document.getElementById('dt-watchlist-content').innerHTML = wlHtml;
    } else {
      wlDiv.classList.add('hidden');
    }
  } catch(e) {
    console.error('龙虎榜加载失败:', e);
    document.getElementById('tab-dragon_tiger').innerHTML =
      '<div class="bg-red-900/30 text-red-400 p-4 rounded-lg text-sm">❌ 加载失败: ' + e.message + '</div>';
  }
}

function renderDtInstRetailChart(instVal, retailVal) {
  const ctx = document.getElementById('dtInstRetailChart');
  if (!ctx) return;
  if (dtChartInstance) dtChartInstance.destroy();
  const instAbs = Math.abs(instVal || 0);
  const retailAbs = Math.abs(retailVal || 0);
  const instLabel = (instVal || 0) >= 0 ? '机构净买入' : '机构净卖出';
  const retailLabel = (retailVal || 0) >= 0 ? '游资/散户净买入' : '游资/散户净卖出';
  dtChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: [instLabel, retailLabel],
      datasets: [{
        data: [instAbs, retailAbs],
        backgroundColor: ['rgba(59, 130, 246, 0.7)', 'rgba(234, 179, 8, 0.7)'],
        borderColor: ['rgba(59, 130, 246, 1)', 'rgba(234, 179, 8, 1)'],
        borderWidth: 1, borderRadius: 4,
      }]
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: '#8b949e', font: { size: 10 },
            callback: function(v) { return v >= 1e8 ? (v/1e8).toFixed(1) + '亿' : (v/1e4).toFixed(0) + '万'; } },
          grid: { color: '#21262d' }
        },
        y: { ticks: { color: '#c9d1d9', font: { size: 11 } }, grid: { display: false } }
      }
    }
  });
}

async function refreshDragonTiger() {
  const btn = document.getElementById('dt-refresh-btn');
  btn.textContent = '⏳ 刷新中...';
  btn.disabled = true;
  await loadDragonTiger(true);
  btn.textContent = '🔄 刷新';
  btn.disabled = false;
}

// ═══════════════════════════════════════════
// 大师持仓
// ═══════════════════════════════════════════
function escHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function(c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

async function loadGurusTab() {
  const el = document.getElementById('gurus-content');
  if (!el) return;
  el.innerHTML = '<div class="text-gray-400 text-sm">⏳ 加载大师持仓...</div>';
  try {
    const res = await fetch('/api/v2/gurus');
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const gurus = Array.isArray(data) ? data : (data.gurus || data.data || []);
    if (gurus.length === 0) {
      el.innerHTML = '<div class="text-gray-500 italic p-4 text-center border border-gray-800 border-dashed rounded">暂无大师数据</div>';
      return;
    }
    let rows = '';
    gurus.forEach(function(g) {
      const slug = g.slug || '';
      const name = g.name || g.display_name || slug;
      const cnt = (g.holdings_count != null) ? g.holdings_count : (g.count || 0);
      rows +=
        '<tr class="hover:bg-gray-700/30 border-b border-gray-700/50">' +
          '<td class="py-2 pr-2 border-0 font-medium text-blue-400 cursor-pointer" onclick="loadGuruDetail(\\'' + escHtml(slug) + '\\')">' + escHtml(name) +
            ' <span class="text-gray-500 text-xs">›</span></td>' +
          '<td class="py-2 pr-2 text-right font-mono text-gray-200 border-0">' + (cnt || 0) + '</td>' +
          '<td class="py-2 pr-2 text-right font-mono text-green-500 border-0">' + escHtml(g.total_usd_fmt || '—') + '</td>' +
        '</tr>';
    });
    el.innerHTML =
      '<div class="card">' +
        '<div class="card-header"><h3>🏆 大师持仓</h3></div>' +
        '<div class="overflow-x-auto"><table class="w-full text-sm">' +
          '<thead><tr class="text-left text-xs text-gray-400">' +
            '<th class="py-2 pr-2 border-0">大师</th>' +
            '<th class="py-2 pr-2 text-right border-0">持仓数</th>' +
            '<th class="py-2 pr-2 text-right border-0">总市值</th>' +
          '</tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
        '</table></div>' +
      '</div>';
  } catch (e) {
    console.error('大师持仓列表加载失败:', e);
    el.innerHTML = '<div class="bg-red-900/30 text-red-400 p-4 rounded-lg text-sm">❌ 大师持仓加载失败: ' + escHtml(e.message) + '</div>';
  }
}

async function loadGuruDetail(slug) {
  const el = document.getElementById('gurus-content');
  if (!el) return;
  el.innerHTML = '<div class="text-gray-400 text-sm">⏳ 加载持仓明细...</div>';
  try {
    const res = await fetch('/api/v2/gurus/' + encodeURIComponent(slug));
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    const holdings = Array.isArray(data) ? data : (data.holdings || data.data || []);
    const guruName = data.name || data.display_name || slug;
    let rows = '';
    (holdings || []).forEach(function(h) {
      const chg = h.chg_pct;
      const chgCls = chg >= 0 ? 'text-green-500' : 'text-red-500';
      rows +=
        '<tr class="hover:bg-gray-700/30 border-b border-gray-700/50">' +
          '<td class="py-1.5 pr-2 border-0 font-mono text-blue-400">' + escHtml(h.ticker || h.symbol || '') + '</td>' +
          '<td class="py-1.5 pr-2 text-gray-200 border-0">' + escHtml(h.name || '') + '</td>' +
          '<td class="py-1.5 pr-2 text-right font-mono text-gray-300 border-0">' + escHtml(h.shares != null ? h.shares.toLocaleString() : '—') + '</td>' +
          '<td class="py-1.5 pr-2 text-right font-mono text-green-500 border-0">' + escHtml(h.value_usd_fmt || '—') + '</td>' +
          '<td class="py-1.5 pr-2 text-right font-mono ' + chgCls + ' border-0">' + (chg != null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '—') + '</td>' +
          '<td class="py-1.5 pr-2 text-right font-mono text-gray-300 border-0">' + (h.weight_pct != null ? h.weight_pct.toFixed(2) + '%' : '—') + '</td>' +
        '</tr>';
    });
    el.innerHTML =
      '<div class="flex items-center justify-between mb-3">' +
        '<button onclick="loadGurusTab()" class="bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm px-3 py-1.5 rounded-lg border border-gray-700">‹ 返回大师列表</button>' +
        '<h3 class="font-bold text-base">🏆 ' + escHtml(guruName) + ' 持仓明细' + '</h3>' +
      '</div>' +
      '<div class="card">' +
        '<div class="overflow-x-auto"><table class="w-full text-sm">' +
          '<thead><tr class="text-left text-xs text-gray-400">' +
            '<th class="py-2 pr-2 border-0">代码</th>' +
            '<th class="py-2 pr-2 border-0">名称</th>' +
            '<th class="py-2 pr-2 text-right border-0">股数</th>' +
            '<th class="py-2 pr-2 text-right border-0">市值</th>' +
            '<th class="py-2 pr-2 text-right border-0">当日涨跌</th>' +
            '<th class="py-2 pr-2 text-right border-0">权重</th>' +
          '</tr></thead>' +
          '<tbody>' + (rows || '<tr><td colspan="6" class="text-center py-4 text-gray-500 border-0">暂无持仓数据</td></tr>') + '</tbody>' +
        '</table></div>' +
      '</div>';
  } catch (e) {
    console.error('大师持仓明细加载失败:', e);
    el.innerHTML =
      '<div class="flex items-center mb-3"><button onclick="loadGurusTab()" class="bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm px-3 py-1.5 rounded-lg border border-gray-700">‹ 返回</button></div>' +
      '<div class="bg-red-900/30 text-red-400 p-4 rounded-lg text-sm">❌ 持仓明细加载失败: ' + escHtml(e.message) + '</div>';
  }
}

// ═══════════════════════════════════════════
// 观点库
// ═══════════════════════════════════════════
async function loadInsightsTab() {
  const el = document.getElementById('insights-content');
  if (!el) return;
  el.innerHTML = '<div class="text-gray-400 text-sm">⏳ 加载观点库...</div>';
  try {
    const [insRes, sumRes] = await Promise.all([
      fetch('/api/v2/insights'),
      fetch('/api/v2/insights/summary')
    ]);
    if (!insRes.ok) throw new Error('insights HTTP ' + insRes.status);
    const insData = await insRes.json();
    const insights = Array.isArray(insData) ? insData : (insData.insights || insData.data || []);

    let summary = null;
    if (sumRes.ok) { summary = await sumRes.json(); }

    // 未成交标的顶部名细表
    const top = (insights || []).slice(0, 20);
    let topRows = '';
    top.forEach(function(i) {
      const chg = i.chg_pct;
      const chgCls = (chg == null) ? 'text-gray-400' : (chg >= 0 ? 'text-green-500' : 'text-red-500');
      topRows +=
        '<tr class="hover:bg-gray-700/30 border-b border-gray-700/50">' +
          '<td class="py-1.5 pr-2 border-0 font-mono text-blue-400">' + escHtml(i.ticker || i.symbol || '') + '</td>' +
          '<td class="py-1.5 pr-2 text-gray-200 border-0">' + escHtml(i.name || '') + '</td>' +
          '<td class="py-1.5 pr-2 text-gray-300 border-0">' + escHtml(i.reason || i.view || '') + '</td>' +
          '<td class="py-1.5 pr-2 font-mono text-right border-0 ' + chgCls + '">' + (chg != null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '—') + '</td>' +
        '</tr>';
    });

    // 原因分布
    let distRows = '';
    let distData = [];
    if (summary) {
      distData = summary.reason_distribution || summary.distribution || summary.by_reason || [];
      if (!Array.isArray(distData)) distData = Object.keys(distData).map(function(k) { return { reason: k, count: distData[k] }; });
    }
    if (distData.length === 0) {
      // 从明细里统计兜底
      const m = {};
      (insights || []).forEach(function(i) { const r = (i.reason || '其他'); m[r] = (m[r] || 0) + 1; });
      distData = Object.keys(m).map(function(k) { return { reason: k, count: m[k] }; });
    }
    distData.forEach(function(d) {
      distRows +=
        '<tr class="hover:bg-gray-700/30 border-b border-gray-700/50">' +
          '<td class="py-1.5 pr-2 border-0 text-gray-200">' + escHtml(d.reason || d.name || '其他') + '</td>' +
          '<td class="py-1.5 pr-2 text-right font-mono text-gray-300 border-0">' + (d.count || 0) + '</td>' +
        '</tr>';
    });

    let summaryCards = '';
    if (summary) {
      const total = summary.total != null ? summary.total : (insights || []).length;
      const unfilled = summary.unfilled != null ? summary.unfilled : total;
      summaryCards =
        '<div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">' +
          '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3"><div class="text-xs text-gray-400 mb-1">观点总数</div><div class="text-lg font-bold font-mono">' + (total || 0) + '</div></div>' +
          '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3"><div class="text-xs text-gray-400 mb-1">未成交</div><div class="text-lg font-bold font-mono">' + (unfilled || 0) + '</div></div>' +
          '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3"><div class="text-xs text-gray-400 mb-1">今日新增</div><div class="text-lg font-bold font-mono text-green-400">' + (summary.new_today || (summary.today || 0)) + '</div></div>' +
          '<div class="bg-gray-800 border border-gray-700 rounded-xl p-3"><div class="text-xs text-gray-400 mb-1">已成交</div><div class="text-lg font-bold font-mono text-blue-400">' + (summary.filled || 0) + '</div></div>' +
        '</div>';
    }

    el.innerHTML =
      (summaryCards || '') +
      '<div class="card">' +
        '<div class="card-header"><h3>💡 未成交观点 · 标的</h3></div>' +
        '<div class="overflow-x-auto"><table class="w-full text-sm">' +
          '<thead><tr class="text-left text-xs text-gray-400">' +
            '<th class="py-2 pr-2 border-0">代码</th>' +
            '<th class="py-2 pr-2 border-0">名称</th>' +
            '<th class="py-2 pr-2 border-0">观点/理由</th>' +
            '<th class="py-2 pr-2 text-right border-0">涨跌</th>' +
          '</tr></thead>' +
          '<tbody>' + (topRows || '<tr><td colspan="4" class="text-center py-4 text-gray-500 border-0">暂无观点数据</td></tr>') + '</tbody>' +
        '</table></div>' +
      '</div>' +
      '<div class="card">' +
        '<div class="card-header"><h3>📊 原因分布</h3></div>' +
        '<div class="overflow-x-auto"><table class="w-full text-sm">' +
          '<thead><tr class="text-left text-xs text-gray-400">' +
            '<th class="py-2 pr-2 border-0">原因</th>' +
            '<th class="py-2 pr-2 text-right border-0">条数</th>' +
          '</tr></thead>' +
          '<tbody>' + (distRows || '<tr><td colspan="2" class="text-center py-4 text-gray-500 border-0">暂无分布数据</td></tr>') + '</tbody>' +
        '</table></div>' +
      '</div>';
  } catch (e) {
    console.error('观点库加载失败:', e);
    el.innerHTML = '<div class="bg-red-900/30 text-red-400 p-4 rounded-lg text-sm">❌ 观点库加载失败: ' + escHtml(e.message) + '</div>';
  }
}

</script>
  <!-- ======== 深度分析弹窗 (通用) ======== -->
  <div id="modal-overlay" class="fixed inset-0 bg-black/70 z-50 hidden items-center justify-center p-4" onclick="closeModal()">
    <div class="bg-gray-900 border border-gray-700 rounded-2xl max-w-2xl w-full max-h-[85vh] overflow-y-auto custom-scrollbar p-5" onclick="event.stopPropagation()">
      <div id="modal-content"></div>
    </div>
  </div>

</body>
</html>
"""
