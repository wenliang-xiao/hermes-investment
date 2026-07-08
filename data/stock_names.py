"""面基·名称映射表 — A股 + 港股 + 美股 + ETF 中文名"""
import sys

STOCK_NAMES = {
    # A股核心
    "300502": "新易盛", "688041": "海光信息", "688008": "澜起科技",
    "002371": "北方华创", "603259": "药明康德", "688256": "寒武纪",
    "600519": "贵州茅台", "000858": "五粮液", "300750": "宁德时代",
    "002594": "比亚迪", "000333": "美的集团", "002415": "海康威视",
    "000651": "格力电器", "002304": "洋河股份", "600585": "海螺水泥",
    "601318": "中国平安", "601398": "工商银行", "600036": "招商银行",
    "600030": "中信证券", "002475": "立讯精密", "300124": "汇川技术",
    "688012": "中微公司", "300274": "阳光电源", "601012": "隆基绿能",
    "300014": "亿纬锂能", "002460": "赣锋锂业", "300059": "东方财富",
    "002230": "科大讯飞", "002129": "中环股份",     "300136": "信维通信", "300308": "中际旭创", "002747": "埃斯顿",
    "600760": "中航沈飞", "002179": "中航光电", "600900": "长江电力",
    "688525": "佰维存储", "688599": "天合光能", "688981": "中芯国际A",
    "600893": "航发动力", "601138": "工业富联", "601985": "中国核电",
    "601877": "正泰电器",
    # 美股
    "NVDA": "英伟达", "AMD": "AMD", "MU": "美光", "TSM": "台积电",
    "VST": "Vistra", "CEG": "Constellation",
    "AMZN": "亚马逊", "AAPL": "苹果", "AVGO": "博通", "LLY": "礼来",
    "JPM": "摩根大通", "XOM": "埃克森美孚", "COST": "好市多",
    "MSFT": "微软", "META": "Meta", "GOOGL": "谷歌", "BABA": "阿里巴巴",
    "ANET": "Arista网络", "COHR": "Coherent",
    # 港股
    "0700.HK": "腾讯控股", "9988.HK": "阿里巴巴",     "9618.HK": "京东", "9868.HK": "小鹏汽车",
    # ETF
    "GDX": "黄金矿场ETF", "GLD": "黄金ETF", "SLV": "白银ETF",
    "IEF": "7-10年国债ETF", "TLT": "20+年国债ETF", "TIP": "抗通胀国债ETF",
    "XLP": "必需消费ETF", "XLU": "公用事业ETF",
}

ETF_NAMES = {
    "510300": "沪深300ETF", "511010": "国债ETF", "512480": "半导体ETF",
    "518880": "黄金ETF", "513100": "纳指ETF", "159985": "豆粕ETF",
}


def _load_config_fallback():
    """延迟加载 config.WATCHLIST 作为名称回退数据源"""
    try:
        from investment_system import config
    except ImportError:
        try:
            import config as _cfg
            config = _cfg
        except ImportError:
            return {}
    wl = getattr(config, "WATCHLIST", {})
    result = {}
    for k, v in wl.items():
        if isinstance(v, dict) and "name" in v:
            result[k] = v["name"]
    return result


_config_fallback: dict = {}


def get_name(code: str) -> str:
    code_str = str(code)
    # 1) 直接硬编码映射
    name = STOCK_NAMES.get(code_str)
    if name:
        return name
    # 2) ETF 专用映射
    name = ETF_NAMES.get(code_str)
    if name:
        return name
    # 3) A股 ETF 模式匹配 (51/15/16/588/159 开头)
    if code_str.isdigit() and len(code_str) == 6:
        if code_str.startswith(("51", "15", "16", "588", "159")):
            name = ETF_NAMES.get(code_str)
            if name:
                return name
    # 4) config.WATCHLIST 回退 (HK/US/ETF 等)
    global _config_fallback
    if not _config_fallback:
        _config_fallback = _load_config_fallback()
    name = _config_fallback.get(code_str)
    if name:
        return name
    # 5) 兜底: 打印警告, 返回代码本身
    print(f"  ⚠️ stock_names: 未找到 {code_str} 的名称映射", file=sys.stderr)
    return code_str
