"""
全球资产选票池 v1.0 — 美股·港股·ETF·大宗商品·汇率·债券
按产业链组织，与A股LDS板块互补
原则：抓大放小，只覆盖关键产业链节点 + 高流动性标的
"""
from typing import Dict, List

# ════════════════════════════════════════════
# 一、美股 — 按产业链组织
# ════════════════════════════════════════════

# 1. 英伟达算力链（美股核心）
NVDA_CHAIN_US = {
    "NVDA":  {"name": "英伟达",       "sector": "GPU/AI芯片",  "chain_pos": "核心"},
    "AMD":   {"name": "AMD",          "sector": "GPU/CPU",     "chain_pos": "核心"},
    "AVGO":  {"name": "博通",         "sector": "网络芯片/AI ASIC", "chain_pos": "核心"},
    "MRVL":  {"name": "Marvell",      "sector": "数据中心芯片", "chain_pos": "配套"},
    "SMCI":  {"name": "超微电脑",     "sector": "AI服务器",     "chain_pos": "配套"},
    "DELL":  {"name": "戴尔",         "sector": "企业服务器",   "chain_pos": "配套"},
    "ARM":   {"name": "Arm Holdings", "sector": "芯片架构",    "chain_pos": "上游"},
}

# 2. 台积电先进制程链 + 半导体设备
SEMI_CHAIN_US = {
    "TSM":   {"name": "台积电",       "sector": "晶圆代工",    "chain_pos": "核心"},
    "ASML":  {"name": "阿斯麦",       "sector": "光刻设备",    "chain_pos": "上游"},
    "AMAT":  {"name": "应用材料",     "sector": "半导体设备",  "chain_pos": "上游"},
    "LRCX":  {"name": "泛林",         "sector": "刻蚀设备",    "chain_pos": "上游"},
    "KLAC":  {"name": "科磊",         "sector": "检测设备",    "chain_pos": "上游"},
    "INTC":  {"name": "英特尔",       "sector": "IDM/代工",    "chain_pos": "中游"},
    "MU":    {"name": "美光",         "sector": "存储/HBM",    "chain_pos": "中游"},
}

# 3. AI应用/云计算/SaaS
AI_SAAS_US = {
    "MSFT":  {"name": "微软",         "sector": "云/AI平台",   "chain_pos": "平台"},
    "AMZN":  {"name": "亚马逊",       "sector": "云/电商",     "chain_pos": "平台"},
    "GOOGL": {"name": "谷歌",         "sector": "云/AI",       "chain_pos": "平台"},
    "META":  {"name": "Meta",         "sector": "AI/社交",     "chain_pos": "应用"},
    "CRM":   {"name": "Salesforce",   "sector": "企业SaaS",    "chain_pos": "应用"},
    "NOW":   {"name": "ServiceNow",   "sector": "企业自动化",  "chain_pos": "应用"},
    "SNOW":  {"name": "Snowflake",    "sector": "数据云",      "chain_pos": "应用"},
    "PLTR":  {"name": "Palantir",     "sector": "AI数据分析",  "chain_pos": "应用"},
}

# 4. AI电力链 — 数据中心电力基础设施（★ 用户重点）
AI_POWER_US = {
    "VST":   {"name": "Vistra",       "sector": "独立电力(核电)",  "chain_pos": "发电"},
    "CEG":   {"name": "Constellation","sector": "独立电力(核电)",  "chain_pos": "发电"},
    "TLN":   {"name": "Talen Energy", "sector": "独立电力(核电)",  "chain_pos": "发电"},
    "GEV":   {"name": "GE Vernova",   "sector": "电力设备/燃气",   "chain_pos": "设备"},
    "PEG":   {"name": "公共服务电力", "sector": "电力公用事业",    "chain_pos": "电网"},
    "EXC":   {"name": "Exelon",       "sector": "电力公用(核电)",  "chain_pos": "电网"},
}

# 5. 数据中心REITs
DATA_CENTER_REIT_US = {
    "EQIX":  {"name": "Equinix",      "sector": "数据中心REIT",   "chain_pos": "基础设施"},
    "DLR":   {"name": "Digital Realty","sector": "数据中心REIT",  "chain_pos": "基础设施"},
    "AMT":   {"name": "American Tower","sector": "通信塔REIT",    "chain_pos": "基础设施"},
}

# 6. 消费/品牌（跨市场对标）
CONSUMER_US = {
    "AAPL":  {"name": "苹果",         "sector": "消费电子",      "chain_pos": "品牌终端"},
    "TSLA":  {"name": "特斯拉",       "sector": "电动车/AI",     "chain_pos": "整车"},
    "NKE":   {"name": "耐克",         "sector": "运动品牌",      "chain_pos": "品牌"},
    "SBUX":  {"name": "星巴克",       "sector": "餐饮品牌",      "chain_pos": "品牌"},
}

# 7. 网络安全（★ 新增：脱钩核心受益 + AI安全）
CYBERSEC_US = {
    "CRWD":  {"name": "CrowdStrike",  "sector": "AI安全/端点",    "chain_pos": "核心"},
    "PANW":  {"name": "Palo Alto",    "sector": "网络安全平台",   "chain_pos": "核心"},
    "ZS":    {"name": "Zscaler",      "sector": "零信任/云安全",   "chain_pos": "配套"},
    "FTNT":  {"name": "Fortinet",     "sector": "网络安全硬件",    "chain_pos": "配套"},
    "S":     {"name": "SentinelOne",  "sector": "AI安全/端点",     "chain_pos": "配套"},
    "CHKP":  {"name": "Check Point",  "sector": "网络安全",        "chain_pos": "配套"},
}

# 8. AI网络设备（★ 新增：交换机/光模块）
AI_NETWORK_US = {
    "ANET":  {"name": "Arista",       "sector": "AI网络交换机",    "chain_pos": "核心"},
    "COHR":  {"name": "Coherent",     "sector": "光模块/激光器",   "chain_pos": "核心"},
    "LITE":  {"name": "Lumentum",     "sector": "光模块/激光器",   "chain_pos": "核心"},
    "CIEN":  {"name": "Ciena",        "sector": "光网络设备",      "chain_pos": "配套"},
    "JNPR":  {"name": "Juniper",      "sector": "网络设备",        "chain_pos": "配套"},
}

# 9. 金融
FINANCIAL_US = {
    "JPM":   {"name": "摩根大通",     "sector": "银行",          "chain_pos": "核心"},
    "GS":    {"name": "高盛",         "sector": "投行",          "chain_pos": "核心"},
    "BLK":   {"name": "贝莱德",       "sector": "资管",          "chain_pos": "核心"},
    "FUTU":  {"name": "富途控股",     "sector": "跨境券商",      "chain_pos": "中概"},
    "TIGR":  {"name": "老虎证券",     "sector": "跨境券商",      "chain_pos": "中概"},
}

# ════════════════════════════════════════════
# 二、美股 ETF — 关键跟踪
# ════════════════════════════════════════════
US_ETFS = {
    "SPY":   {"name": "标普500",       "category": "宽基",       "market": "US"},
    "QQQ":   {"name": "纳指100",       "category": "宽基成长",   "market": "US"},
    "IWM":   {"name": "罗素2000小盘",   "category": "小盘",      "market": "US"},
    "DIA":   {"name": "道指",          "category": "宽基价值",   "market": "US"},
    "SMH":   {"name": "半导体",         "category": "科技",      "market": "US"},
    "SOXX":  {"name": "费城半导体",     "category": "科技",      "market": "US"},
    "IGV":   {"name": "软件/SaaS",      "category": "科技",      "market": "US"},
    "XLU":   {"name": "公用事业",       "category": "防御",      "market": "US"},
    "XLE":   {"name": "能源",           "category": "周期",      "market": "US"},
    "XLF":   {"name": "金融",           "category": "周期",      "market": "US"},
    "XLV":   {"name": "医疗健康",       "category": "防御",      "market": "US"},
    "XLI":   {"name": "工业",           "category": "周期",      "market": "US"},
    "TLT":   {"name": "20年+美债",      "category": "债券",      "market": "US"},
    "IEF":   {"name": "7-10年美债",     "category": "债券",      "market": "US"},
    "SHY":   {"name": "1-3年美债",      "category": "债券",      "market": "US"},
    "GLD":   {"name": "黄金",           "category": "商品",      "market": "US"},
    "USO":   {"name": "原油",           "category": "商品",      "market": "US"},
    "UUP":   {"name": "美元指数",       "category": "汇率",      "market": "US"},
    "FXI":   {"name": "中国大盘股",     "category": "新兴市场",  "market": "CN"},
    "KWEB":  {"name": "中概互联网",     "category": "新兴市场",  "market": "CN"},
    "EEM":   {"name": "新兴市场",       "category": "新兴市场",  "market": "EM"},
    "VWO":   {"name": "富时新兴市场",   "category": "新兴市场",  "market": "EM"},
}

# ════════════════════════════════════════════
# 三、港股关键标的
# ════════════════════════════════════════════
HK_WATCHLIST_V2 = {
    # 互联网/AI平台
    "0700.HK": {"name": "腾讯控股",     "sector": "互联网/AI",   "chain": "AI应用"},
    "9988.HK": {"name": "阿里巴巴",     "sector": "电商/云",     "chain": "AI应用"},
    "3690.HK": {"name": "美团",         "sector": "本地生活",    "chain": "消费科技"},
    "9999.HK": {"name": "网易",         "sector": "游戏",        "chain": "消费科技"},
    "9888.HK": {"name": "百度",         "sector": "AI/搜索",     "chain": "AI应用"},
    # 硬件/半导体
    "1810.HK": {"name": "小米集团",     "sector": "消费电子/AI",  "chain": "消费电子"},
    "0981.HK": {"name": "中芯国际",     "sector": "晶圆代工",    "chain": "半导体"},
    "1347.HK": {"name": "华虹半导体",   "sector": "晶圆代工",    "chain": "半导体"},
    # 新能源车
    "1211.HK": {"name": "比亚迪",       "sector": "电动车",      "chain": "新能源车"},
    "9868.HK": {"name": "小鹏汽车",     "sector": "电动车",      "chain": "新能源车"},
    "2015.HK": {"name": "理想汽车",     "sector": "电动车",      "chain": "新能源车"},
    "9866.HK": {"name": "蔚来",         "sector": "电动车",      "chain": "新能源车"},
    # 金融
    "0388.HK": {"name": "港交所",       "sector": "交易所",      "chain": "金融"},
    "1299.HK": {"name": "友邦保险",     "sector": "保险",        "chain": "金融"},
    "0005.HK": {"name": "汇丰控股",     "sector": "银行",        "chain": "金融"},
    "2318.HK": {"name": "中国平安",     "sector": "保险",        "chain": "金融"},
    # 消费/品牌
    "9992.HK": {"name": "泡泡玛特",     "sector": "IP/潮玩",     "chain": "品牌消费"},
    "6181.HK": {"name": "老铺黄金",     "sector": "黄金珠宝",    "chain": "品牌消费"},
    "2020.HK": {"name": "安踏体育",     "sector": "运动品牌",    "chain": "品牌消费"},
    "1876.HK": {"name": "百威亚太",     "sector": "啤酒",        "chain": "消费"},
    # 能源/资源
    "0883.HK": {"name": "中国海油",     "sector": "能源",        "chain": "能源"},
    "2899.HK": {"name": "紫金矿业",     "sector": "黄金/铜",     "chain": "大宗商品"},
}

# ════════════════════════════════════════════
# 四、大宗商品 + 汇率 + 债券
# ════════════════════════════════════════════
COMMODITIES_V2 = {
    "GC=F":  {"name": "黄金",     "unit": "美元/盎司",  "category": "贵金属"},
    "SI=F":  {"name": "白银",     "unit": "美元/盎司",  "category": "贵金属"},
    "CL=F":  {"name": "WTI原油",  "unit": "美元/桶",    "category": "能源"},
    "NG=F":  {"name": "天然气",   "unit": "美元/MMBTU", "category": "能源"},
    "HG=F":  {"name": "铜",       "unit": "美元/磅",    "category": "工业金属"},
    "ZC=F":  {"name": "玉米",     "unit": "美元/蒲式耳","category": "农产品"},
    "ZW=F":  {"name": "小麦",     "unit": "美元/蒲式耳","category": "农产品"},
    "ZS=F":  {"name": "大豆",     "unit": "美元/蒲式耳","category": "农产品"},
}

FX_V2 = {
    "CNY=X": {"name": "USD/CNY",  "direction": "↑利空A股"},
    "JPY=X": {"name": "USD/JPY",  "direction": "↑日元强=套息平仓风险"},
    "EUR=X": {"name": "EUR/USD",  "direction": "↑欧元强=美元弱"},
    "DXY":   {"name": "美元指数", "direction": "↑美元强=新兴承压"},
}

BONDS_V2 = {
    "^TNX": {"name": "美国10Y收益率",  "type": "基准"},
    "^TYX": {"name": "美国30Y收益率",  "type": "长端"},
    "ZB=F": {"name": "30年美债期货",   "type": "价格"},
}

SENTIMENT_V2 = {
    "^VIX": {"name": "VIX恐慌指数",    "type": "情绪"},
}

# ════════════════════════════════════════════
# 五、聚合导出
# ════════════════════════════════════════════

# 所有美股（用于多因子扫描）
ALL_US_STOCKS = {}
for chain_dict in [NVDA_CHAIN_US, SEMI_CHAIN_US, AI_SAAS_US, AI_POWER_US,
                    DATA_CENTER_REIT_US, CONSUMER_US, CYBERSEC_US, AI_NETWORK_US,
                    FINANCIAL_US]:
    ALL_US_STOCKS.update(chain_dict)

# 美股按链分组
US_CHAINS = {
    "英伟达算力链(美股)": NVDA_CHAIN_US,
    "半导体设备链(美股)": SEMI_CHAIN_US,
    "AI应用/SaaS链(美股)": AI_SAAS_US,
    "AI电力链(美股)": AI_POWER_US,
    "数据中心REITs(美股)": DATA_CENTER_REIT_US,
    "品牌消费(美股)": CONSUMER_US,
    "网络安全(美股)": CYBERSEC_US,
    "AI网络设备(美股)": AI_NETWORK_US,
    "金融(美股)": FINANCIAL_US,
}

def get_full_hk_list() -> Dict:
    return HK_WATCHLIST_V2

def get_full_us_list() -> Dict:
    return ALL_US_STOCKS

def get_us_by_chain(chain_name: str) -> Dict:
    return US_CHAINS.get(chain_name, {})

if __name__ == "__main__":
    print(f"美股选票池: {len(ALL_US_STOCKS)}只 (7条链)")
    print(f"港股选票池: {len(HK_WATCHLIST_V2)}只")
    print(f"美股ETF: {len(US_ETFS)}只")
    print(f"大宗商品: {len(COMMODITIES_V2)}种")
    print(f"汇率: {len(FX_V2)}组")
    print(f"债券: {len(BONDS_V2)}组")
    print(f"\n各链分布:")
    for name, chain in US_CHAINS.items():
        print(f"  {name}: {len(chain)}只")
