#!/usr/bin/env python3
"""
面基投资模拟盘 — Dashboard 服务器
===================================
FastAPI + 暗色 Dashboard，日报通过链接引用

启动:
  uvicorn scripts.portfolio_server:app --host 0.0.0.0 --port 8686
  uvicorn dashboard.server:app --host 0.0.0.0 --port 8686
  python3 dashboard/server.py 8686
"""

import sys
from pathlib import Path
from fastapi import FastAPI, responses

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

app = FastAPI(title="面基模拟盘 Dashboard", version="1.0.0")

# ─── 注册所有 API 路由 ─────────────────────────────

from dashboard.api_portfolio import router as portfolio_router
from dashboard.api_pool import router as pool_router
from dashboard.api_etf import router as etf_router
from dashboard.api_news import router as news_router
from dashboard.api_backtest import router as backtest_router
from dashboard.api_risk import router as risk_router
from dashboard.api_comparison import router as comparison_router
from dashboard.api_dragon_tiger import router as dragon_tiger_router
from dashboard.api_evidence import router as evidence_router

app.include_router(portfolio_router)
app.include_router(pool_router)
app.include_router(etf_router)
app.include_router(news_router)
app.include_router(backtest_router)
app.include_router(risk_router)
app.include_router(comparison_router)
app.include_router(dragon_tiger_router)
app.include_router(evidence_router)

# ─── HTML 模板 ─────────────────────────────────────

from dashboard.templates.dashboard_main import UNIFIED_DASHBOARD_HTML


@app.get("/")
@app.get("/dashboard")
def dashboard():
    return responses.HTMLResponse(UNIFIED_DASHBOARD_HTML)


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
