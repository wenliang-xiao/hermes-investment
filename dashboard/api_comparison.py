"""三方对比 — 独立的 /comparison 页面 + 对比 API"""

from fastapi import APIRouter, responses
from dashboard.templates.comparison_page import COMPARISON_HTML

router = APIRouter()


@router.get("/comparison")
def comparison_page():
    return responses.HTMLResponse(COMPARISON_HTML)
