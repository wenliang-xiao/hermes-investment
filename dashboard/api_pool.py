"""票池 / 因子说明 / 深度研报 API"""

import json
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from dashboard.shared import ROOT, get_name, _guess_chain, _classify_market

router = APIRouter()


@router.get("/api/v2/pool")
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


@router.get("/api/v2/pool/by_market")
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


@router.get("/api/v2/factor_explain")
def api_v2_factor_explain():
    """因子评分体系说明 — 7因子定义+计算方法+参考范围+子因子明细"""
    sub_factor_map = {
        "quality":     ["quality:roe", "quality:gross_margin", "quality:debt_ratio",
                        "quality:operating_cf", "quality:net_margin"],
        "value":       ["value:pe_percentile", "value:pb", "value:pe_ttm"],
        "growth":      ["growth:rev_growth_ttm", "growth:profit_growth_ttm", "growth:roe_acceleration"],
        "momentum":    ["momentum:ret_20d", "momentum:ret_60d", "momentum:ret_120d"],
        "low_vol":     ["low_vol:ann_vol_20d", "low_vol:max_dd_60d"],
        "sentiment":   ["sentiment:vol_ratio_20d", "sentiment:turnover_rate_20d"],
        "dividend":    ["dividend:dividend_yield"],
        "risk":        ["risk:pe_risk", "risk:vol_60d"],
    }
    return {
        "engine": "factor_engine v4.0",
        "range": "[0, 1]",
        "method": "scipy rankdata 截面百分位 + 产业链中性化",
        "factors": [
            {"key": "quality", "label": "质量", "weight": 0.18,
             "subs": ["ROE", "毛利率", "资产负债率(反向)", "每股经营现金流", "净利率"],
             "sub_keys": sub_factor_map["quality"],
             "desc": "盈利能力强、财务健康的公司"},
            {"key": "value", "label": "价值", "weight": 0.15,
             "subs": ["PE历史百分位(反向)", "PB(反向)", "PE_TTM(反向)"],
             "sub_keys": sub_factor_map["value"],
             "desc": "估值低于历史和同行的公司"},
            {"key": "growth", "label": "成长", "weight": 0.17,
             "subs": ["营收增速TTM", "净利增速TTM", "ROE加速度"],
             "sub_keys": sub_factor_map["growth"],
             "desc": "营收和利润持续高增长的公司"},
            {"key": "momentum", "label": "动量", "weight": 0.15,
             "subs": ["20日回报", "60日回报", "120日回报"],
             "sub_keys": sub_factor_map["momentum"],
             "desc": "近期价格表现强势的公司"},
            {"key": "low_vol", "label": "低波", "weight": 0.12,
             "subs": ["20日年化波动率(反向)", "60日最大回撤(反向)"],
             "sub_keys": sub_factor_map["low_vol"],
             "desc": "价格波动小、回撤小的公司"},
            {"key": "sentiment", "label": "情绪/资金", "weight": 0.10,
             "subs": ["20日成交量比", "20日换手率"],
             "sub_keys": sub_factor_map["sentiment"],
             "desc": "市场关注度和技术信号"},
            {"key": "dividend", "label": "股息", "weight": 0.07,
             "subs": ["股息率"],
             "sub_keys": sub_factor_map["dividend"],
             "desc": "现金分红回报高的公司"},
            {"key": "risk", "label": "风险", "weight": 0.12,
             "subs": ["PE过高风险", "60日波动率"],
             "sub_keys": sub_factor_map["risk"],
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


@router.get("/api/v2/discovery/decoupling")
def api_v2_decoupling_discovery(
    min_confidence: str = Query("medium", description="最低置信度: high/medium/low"),
    top_n: int = Query(30, description="返回前N只标的", ge=1, le=100),
):
    """
    中美脱钩·比较优势发现 API

    返回完整比较优势地图 + 基于结构性优势发现的标的列表。
    评估逻辑: 每只标的按其所在产业链领域的中国竞争优势与置信度打分。
    """
    from analysis.decoupling_discovery import (
        get_discovered_stocks,
        get_comparative_advantage_map,
        get_domain_summary,
    )

    stocks = get_discovered_stocks(min_confidence=min_confidence)
    full_map = get_comparative_advantage_map()
    domain_summary = get_domain_summary()

    for s in stocks:
        s["name"] = get_name(s["symbol"])
        s["chain"] = _guess_chain(s["symbol"])
        s["market"] = _classify_market(s["symbol"])

    return {
        "engine": "decoupling_discovery v1.0",
        "description": full_map.get("description", ""),
        "methodology": full_map.get("methodology", {}),
        "total_domains": len(full_map.get("domains", [])),
        "total_discovered": len(stocks),
        "top_n": min(top_n, len(stocks)),
        "domain_summary": domain_summary,
        "domains": full_map.get("domains", []),
        "discovered_stocks": stocks[:top_n],
    }


# ═══════════════════════════════════════════
# 深度研报 API (deep_research_v2)
# ═══════════════════════════════════════════


@router.get("/api/v2/research/report/{symbol}")
def api_v2_research_report(symbol: str):
    """获取指定标的的最新深度研报"""
    try:
        from analysis.deep_research_v2 import get_latest_report
        report = get_latest_report(symbol)
        if report is None:
            return JSONResponse(
                content={"error": f"暂无 {symbol} 的研报，请先运行 scripts/run_deep_research.py"},
                status_code=404,
            )
        return report
    except Exception as e:
        return JSONResponse(
            content={"error": f"获取研报失败: {e}"},
            status_code=500,
        )


@router.get("/api/v2/research/reports")
def api_v2_research_reports():
    """列出所有已生成的深度研报索引"""
    try:
        from analysis.deep_research_v2 import list_all_reports
        reports = list_all_reports()
        return {
            "total": len(reports),
            "reports": reports,
        }
    except Exception as e:
        return JSONResponse(
            content={"error": f"获取研报列表失败: {e}"},
            status_code=500,
        )
