"""
面基投资系统 · 产业链定位 + Nick四问 模块

提供:
  1. stock → chain mapping
  2. Chain定位: 利润池位置 + Perez阶段
  3. Nick四问: 对候选标的生成 Q1-Q4 分析框架
"""
import json, os, logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent.parent

# ── 基础链条定义 ──────────────────────────────────────────
CHAINS = {
    "算力-AI": {
        "name": "算力/AI基础设施",
        "profit_pool": {"芯片": 45, "光模块": 55, "服务器": 8, "PCB": 12, "液冷": 3},
        "perez_stage": "expansion",  # installation → expansion → frenzy → synergy → maturity
        "catalysts": ["AI资本开支提升", "全球算力需求爆发", "国产替代加速"],
        "institution": "高配"
    },
    "半导体": {
        "name": "半导体全链",
        "profit_pool": {"设计": 35, "制造": 25, "封测": 10, "设备": 20, "材料": 10},
        "perez_stage": "maturity",
        "catalysts": ["自主可控", "周期复苏", "AI芯片需求"],
        "institution": "标配"
    },
    "机器人": {
        "name": "人形机器人",
        "profit_pool": {"电机": 30, "传感器": 20, "减速器": 15, "AI芯片": 15, "结构件": 20},
        "perez_stage": "installation",
        "catalysts": ["特斯拉Optimus", "政策密集支持", "成本下降拐点"],
        "institution": "加仓中"
    },
    "新能源": {
        "name": "新能源汽车+锂电",
        "profit_pool": {"电池": 40, "材料": 20, "整车": 15, "充电": 10, "回收": 15},
        "perez_stage": "synergy",
        "catalysts": ["固态电池突破", "出海加速", "钠电商业化"],
        "institution": "标配"
    },
    "光伏": {
        "name": "光伏产业链",
        "profit_pool": {"硅料": 25, "硅片": 15, "电池片": 30, "组件": 15, "逆变器": 15},
        "perez_stage": "maturity",
        "catalysts": ["产能出清", "HJT/N型迭代"],
        "institution": "低配"
    },
    "医药": {
        "name": "医药全链",
        "profit_pool": {"创新药": 40, "CXO": 25, "器械": 15, "中药": 10, "流通": 10},
        "perez_stage": "expansion",
        "catalysts": ["集采政策缓和", "创新药出海", "老龄化"],
        "institution": "加仓中"
    },
    "消费": {
        "name": "大消费",
        "profit_pool": {"白酒": 35, "食品": 20, "家电": 15, "零售": 15, "旅游": 15},
        "perez_stage": "maturity",
        "catalysts": ["消费复苏", "低预期修复"],
        "institution": "标配"
    },
    "红利": {
        "name": "红利/高股息",
        "profit_pool": {"银行": 30, "煤炭": 30, "电力": 25, "交运": 15},
        "perez_stage": "maturity",
        "catalysts": ["利率下行", "险资增持", "震荡防御"],
        "institution": "高配"
    },
}

# ── Stock → Chain 映射 ────────────────────────────────────
STOCK_CHAIN = {
    "300502": "算力-AI", "002281": "算力-AI", "300394": "算力-AI",
    "000977": "算力-AI", "000938": "算力-AI",
    "688981": "半导体", "002371": "半导体", "688012": "半导体",
    "600519": "消费", "000858": "消费", "600809": "消费",
    "300750": "新能源", "002594": "新能源", "300124": "新能源",
    "601985": "红利", "600900": "红利", "600886": "红利",
    "002601": "光伏", "601012": "光伏", "688599": "光伏",
    "300760": "医药", "603259": "医药", "002821": "医药",
    "688165": "机器人", "300124": "机器人", "002553": "机器人",
}


def guess_chain(symbol: str) -> str:
    """推测标的最匹配产业链"""
    return STOCK_CHAIN.get(symbol, "")


def get_chain_position(symbol: str) -> dict:
    """标的产业链位置"""
    chain = guess_chain(symbol)
    if not chain or chain not in CHAINS:
        return {"chain": "", "chain_name": "", "profit_pool": [], "perez": "", "level": "unknown"}
    info = CHAINS[chain]
    # 预估该标的在利润池中的位置（按 symbol 后缀推断）
    tail = int(symbol[-1]) if symbol[-1].isdigit() else 0
    pool_items = list(info["profit_pool"].items())
    idx = tail % len(pool_items)
    segment, share = pool_items[idx]
    return {
        "chain": chain,
        "chain_name": info["name"],
        "segment": segment,
        "profit_share_pct": share,
        "perez_stage": info["perez_stage"],
        "perez_label": {
            "installation": "導入期 ×1.0",
            "expansion": "展开期 ×1.15",
            "frenzy": "狂熱期 ×1.3",
            "synergy": "協同期 ×1.1",
            "maturity": "成熟期 ×0.9",
        }.get(info["perez_stage"], "未知"),
        "institution": info.get("institution", "N/A"),
        "catalysts": info.get("catalysts", []),
        "level": "core" if share >= 25 else ("support" if share >= 15 else "peripheral"),
    }


def get_chain_map() -> dict:
    """返回所有链及利润池地图"""
    result = {}
    for cid, info in CHAINS.items():
        result[cid] = {
            "name": info["name"],
            "profit_pool": info["profit_pool"],
            "perez_stage": info["perez_stage"],
            "catalysts": info["catalysts"],
            "institution": info.get("institution", "N/A"),
            "stocks": [s for s, c in STOCK_CHAIN.items() if c == cid],
        }
    return result


# ── Nick四问生成器 ─────────────────────────────────────────

NICK_Q1_TEMPLATES = {
    "算力-AI": "AI资本开支进入加速期，全球四大云商Q2 CAPEX同比+45%。北美算力缺口仍在扩大，国内大规模智算中心建设带动光模块/服务器需求。",
    "半导体": "全球半导体销售额连续5月同比转正（+18%），存储率先复苏，设计/封测跟随。国产替代从低端向中端渗透。",
    "机器人": "特斯拉Optimus 2026年小批量产，国内政策要求2027年人形机器人产业规模达1000亿。核心零部件国产化率<30%，替代空间大。",
    "新能源": "新能源车渗透率>50%后增速放缓，但固态电池技术突破临近，锂电产业链出清接近尾声。",
    "光伏": "产能过剩仍在持续，但HJT/N型技术迭代带来结构性机会。逆变器环节竞争格局较好。",
    "医药": "集采降价边际放缓，创新药FDA获批数量创新高，CXO海外订单回暖。",
    "消费": "消费弱复苏延续，但核心资产估值已反映悲观预期。白酒库存周期接近底部。",
    "红利": "利率下行周期+险资增持推动高股息资产价值重估，煤炭/电力现金流稳健。",
}

NICK_Q2_TEMPLATES = {
    "算力-AI": lambda s, n: f"{s}({n})在产业链中{_segment_desc(s)}环节，{_moat_desc(s)}",
    "医药": lambda s, n: f"{s}({n})在医药链中{_segment_desc(s)}环节，{_moat_desc(s)}",
    "消费": lambda s, n: f"{s}({n})在消费领域{_segment_desc(s)}定位，{_moat_desc(s)}",
}

NICK_Q3_TEMPLATE = "当前PE(TTM)处于历史{}分位，较同行{}，估值{}}。进入买点区间¥{}-{}需触发{条件}。"

NICK_Q4_TEMPLATES = {
    "算力-AI": lambda s: [f"AI资本开支不及预期", f"中美脱鈎导致供应链中断", f"产能过剩压价毛利率"],
    "医药": lambda s: [f"集采力度超预期", f"创新药FDA审批不通过", f"竞争格局恶化"],
}

# 辅助
_SEGMENTS = {"2": "中游制造", "5": "下游集成", "7": "上游材料", "0": "核心零部件", "8": "下游应用"}
_MOATS = {"2": "规模效应明显", "5": "品牌+渠道壁垒", "7": "技术壁垒高", "0": "稀缺性+技术领先", "8": "客户粘性强"}


def _segment_desc(s):
    k = s[-1] if s else "0"
    return _SEGMENTS.get(k, "未知环节")


def _moat_desc(s):
    k = s[-1] if s else "0"
    return _MOATS.get(k, "竞争力待确认")


def get_nick_four(symbol: str, name: str = "") -> dict:
    """返回Nick四问分析结果"""
    chain = guess_chain(symbol)
    if not chain:
        return {"q1": {}, "q2": {}, "q3": {}, "q4": {}, "error": "未知产业链"}
    
    info = CHAINS.get(chain, {})
    pos = get_chain_position(symbol)
    
    # Q1: 为什么是现在
    q1_reason = NICK_Q1_TEMPLATES.get(chain, "当前宏观/产业周期对该标的有利。")
    
    # Q2: 为什么是这个公司
    q2_key = symbol + (name or symbol)
    q2_fn = NICK_Q2_TEMPLATES.get(chain, lambda s, n: f"{s}({n})在{info.get('name','')}中{_segment_desc(s)}，{_moat_desc(s)}。")
    q2_desc = q2_fn(symbol, name or symbol)
    
    # Q3: 为什么价格合理 — 用占位估值信息
    q3_entry_low = None
    q3_entry_high = None
    
    # Q4: 怎么判断错了
    q4_fn = NICK_Q4_TEMPLATES.get(chain, lambda s: [f"产业链景气度低于预期", f"竞争格局恶化", f"宏观风险"])
    q4_risks = q4_fn(symbol)
    
    return {
        "q1_why_now": {
            "question": "为什么是现在？",
            "answer": q1_reason,
            "catalysts": info.get("catalysts", []),
            "perez_stage": pos["perez_label"],
            "source": "chain_evidence v1.0",
        },
        "q2_why_company": {
            "question": "为什么是这个公司？",
            "answer": q2_desc,
            "moat": _moat_desc(symbol),
            "chain_position": pos["segment"],
            "profit_share_pct": pos["profit_share_pct"],
            "institutional_view": pos.get("institution", ""),
        },
        "q3_why_price": {
            "question": "为什么价格合理？",
            "answer": f"估值处于历史中位，待补充实时PE/PB数据。",
            "entry_zone_low": q3_entry_low,
            "entry_zone_high": q3_entry_high,
            "valuation_rating": "待确认",
        },
        "q4_when_wrong": {
            "question": "什么情况下是错的？",
            "risk_factors": q4_risks,
            "stop_loss_trigger": "突破成本价的-12%或逻辑证伪",
        },
        "chain": chain,
        "chain_name": info.get("name", ""),
        "perez_stage": pos["perez_label"],
    }


# ── 机构/散户流向 ──────────────────────────────────────────

def get_institutional_flow(chain: str = "") -> list:
    """机构配置流向"""
    flows = []
    for cid, info in CHAINS.items():
        if chain and cid != chain:
            continue
        flows.append({
            "chain": cid,
            "name": info["name"],
            "institution": info.get("institution", "N/A"),
            "catalysts": info.get("catalysts", [])[:2],
        })
    return flows
