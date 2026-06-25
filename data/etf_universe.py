"""
data/etf_universe.py — ETF 标的定义+分类

面基系统覆盖的 ETF 标的池。
分类参考: 宽基/行业/商品/债券/跨境
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

EtfCategory = Literal["broad", "sector", "commodity", "bond", "cross_border", "strategy"]


@dataclass
class EtfDef:
    """ETF 定义"""
    symbol: str
    name: str
    category: EtfCategory
    region: str = "CN"           # CN / US / HK
    benchmark: str = ""           # 跟踪指数
    fee_pct: float = 0.005        # 管理费+托管费


# ─── A股 ETF ───
CN_ETF: list[EtfDef] = [
    # 宽基
    EtfDef("510050", "上证50ETF", "broad", benchmark="上证50"),
    EtfDef("510300", "沪深300ETF", "broad", benchmark="沪深300"),
    EtfDef("510500", "中证500ETF", "broad", benchmark="中证500"),
    EtfDef("588000", "科创50ETF", "broad", benchmark="科创50"),
    EtfDef("159915", "创业板ETF", "broad", benchmark="创业板指"),

    # 行业
    EtfDef("512880", "证券ETF", "sector", benchmark="证券公司"),
    EtfDef("159865", "养殖ETF", "sector", benchmark="中证畜牧"),
    EtfDef("515790", "光伏ETF", "sector", benchmark="中证光伏"),
    EtfDef("512480", "半导体ETF", "sector", benchmark="中证半导体"),
    EtfDef("159766", "旅游ETF", "sector", benchmark="中证旅游"),
    EtfDef("515220", "煤炭ETF", "sector", benchmark="中证煤炭"),

    # 商品
    EtfDef("159937", "黄金ETF", "commodity", benchmark="AU99.99"),

    # 债券
    EtfDef("511010", "国债ETF", "bond", benchmark="国债指数"),
    EtfDef("511880", "银华日利", "bond", benchmark="货币基金"),
]

# ─── 美股 ETF ───
US_ETF: list[EtfDef] = [
    EtfDef("SPY", "SPY标普500", "broad", region="US", benchmark="标普500"),
    EtfDef("QQQ", "QQQ纳指100", "broad", region="US", benchmark="纳斯达克100"),
    EtfDef("IWM", "罗素2000", "broad", region="US", benchmark="罗素2000"),
    EtfDef("GLD", "黄金ETF", "commodity", region="US", benchmark="黄金"),
    EtfDef("SLV", "白银ETF", "commodity", region="US", benchmark="白银"),
    EtfDef("TLT", "长债ETF", "bond", region="US", benchmark="20年+美债"),
    EtfDef("IEF", "中债ETF", "bond", region="US", benchmark="7-10年美债"),
    EtfDef("TIP", "抗通胀债", "bond", region="US", benchmark="TIPS"),
    EtfDef("XLU", "公用事业", "sector", region="US", benchmark="公用事业"),
    EtfDef("XLP", "必需消费", "sector", region="US", benchmark="必需消费"),
    EtfDef("GDX", "金矿股", "sector", region="US", benchmark="金矿股"),
]

ALL_ETF = CN_ETF + US_ETF
ETF_BY_SYMBOL = {e.symbol: e for e in ALL_ETF}


def get_etf_universe(category: EtfCategory | None = None, region: str | None = None) -> list[EtfDef]:
    """获取 ETF 列表，支持按类别/地区过滤"""
    result = ALL_ETF
    if category:
        result = [e for e in result if e.category == category]
    if region:
        result = [e for e in result if e.region == region]
    return result
