"""
中观产业链分析引擎
基于面基播客知识体系（12条产业链），扫描利润池分布 + 瓶颈度评分

每条链定义：
  - profit_pool: 利润池最厚的环节及其利润率估算
  - bottleneck: 技术/产能瓶颈环节
  - mapped_stocks: 该链映射到WATCHLIST的标的
"""
import sys, os
from datetime import date

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
sys.path.insert(0, _PROJECT_DIR)

from domain import WATCHLIST

# ═══════════════════════════════════════════
# 12条产业链定义
# ═══════════════════════════════════════════
CHAINS = {
    "nvidia": {
        "name": "英伟达算力链",
        "desc": "英伟达GPU→光模块→HBM→服务器→数据中心互联",
        "profit_pool": {
            "main": "光模块(30-55%)、HBM(50%+)",
            "upstream": "HBM(50%+)",
            "midstream": "光模块(30-55%)、PCB(25-35%)",
            "downstream": "AI服务器(15-20%)、数据中心",
        },
        "bottleneck": "HBM产能、800G光模块产能",
        "directional_bias": "利润向上游HBM集中(有限产能),中游光模块爆发(800G放量)",
        "stocks": [
            {"symbol": "300502", "role": "800G光模块龙头", "position": "中游", "profit_share": 55},
            {"symbol": "300308", "role": "光模块(800G/1.6T)", "position": "中游", "profit_share": 50},
        ]
    },
    "tsmc": {
        "name": "台积电先进制程链",
        "desc": "台积电→半导体设备→材料→CoWoS封测→EDA/IP",
        "profit_pool": {
            "main": "半导体设备(40-55%)、CoWoS(45%+)",
            "upstream": "设备(40-55%)、材料(25-35%)",
            "midstream": "晶圆制造(台积电独家)",
            "downstream": "封测(15-20%)",
        },
        "bottleneck": "CoWoS产能、先进光刻机、EUV光刻胶",
        "directional_bias": "受益于台积电资本开支扩张,设备增量明确",
        "stocks": [
            {"symbol": "002371", "role": "刻蚀/薄膜沉积设备", "position": "上游", "profit_share": 45},
            {"symbol": "688012", "role": "刻蚀设备龙头", "position": "上游", "profit_share": 45},
            {"symbol": "688120", "role": "CMP/减薄设备", "position": "上游", "profit_share": 40},
            {"symbol": "688041", "role": "CPU/DCU替代", "position": "下游", "profit_share": 30},
        ]
    },
    "robot": {
        "name": "机器人核心零部件",
        "desc": "谐波减速器→RV减速器→伺服电机→控制器→整机集成",
        "profit_pool": {
            "main": "减速器(40%)、伺服电机(30%)",
            "upstream": "减速器(40%)、传感器(35%)",
            "midstream": "伺服系统(25-30%)、控制器(20-25%)",
            "downstream": "整机集成(10-15%)",
        },
        "bottleneck": "谐波减速器精密加工、空心杯电机",
        "directional_bias": "人形机器人量产前夜,减速器最先受益(验证→放量→定价权)",
        "stocks": [
            {"symbol": "688017", "role": "谐波减速器龙头", "position": "上游", "profit_share": 40},
            {"symbol": "300124", "role": "伺服系统/PLC", "position": "中游", "profit_share": 30},
            {"symbol": "002747", "role": "减速器/RV减速器", "position": "上游", "profit_share": 38},
            {"symbol": "002472", "role": "齿轮/减速器部件", "position": "上游", "profit_share": 35},
        ]
    },
    "semiconductor": {
        "name": "半导体链",
        "desc": "设计IP→EDA→制造→封测→芯片设计→分销",
        "profit_pool": {
            "main": "设计IP(80%+)、设备(40-55%)",
            "upstream": "IP授权(80%+)、EDA(70%+)",
            "midstream": "晶圆代工(25-35%)、封测(15-20%)",
            "downstream": "芯片设计(20-40%)、分销(8-12%)",
        },
        "bottleneck": "先进制程产能、HBM、Chiplet互联",
        "directional_bias": "自主可控主线,设备/材料长期受益,设计环节景气度跟随下游需求",
        "stocks": [
            {"symbol": "688041", "role": "DCU/CPU国产替代", "position": "下游", "profit_share": 35},
            {"symbol": "688008", "role": "内存接口芯片/DDR5", "position": "下游", "profit_share": 30},
            {"symbol": "603501", "role": "CIS图像传感器", "position": "下游", "profit_share": 25},
            {"symbol": "002371", "role": "半导体设备", "position": "上游", "profit_share": 45},
            {"symbol": "688012", "role": "刻蚀设备", "position": "上游", "profit_share": 45},
            {"symbol": "688120", "role": "CMP设备", "position": "上游", "profit_share": 40},
        ]
    },
    "ai_power": {
        "name": "AI电力",
        "desc": "核电→燃气轮机→变压器→电力IT→数据中心配电",
        "profit_pool": {
            "main": "核电PPA(稳定)、燃气轮机(寡头定价)、变压器(国内寡头)",
            "upstream": "核电燃料(稀缺)、燃气轮机叶片(壁垒高)",
            "midstream": "变压器(30-35%)、高压开关(25-30%)",
            "downstream": "电力运营(15-20%)、数据中心配电(20-25%)",
        },
        "bottleneck": "核电审批、特高压变压器、燃气轮机热端部件",
        "directional_bias": "AI算力扩建→电力需求爆发,变压器缺货周期最长(18-24月)",
        "stocks": [
            {"symbol": "600900", "role": "水电基荷电源", "position": "下游", "profit_share": 20},
            {"symbol": "601985", "role": "核电运营商", "position": "下游", "profit_share": 25},
            {"symbol": "601877", "role": "低压电器/配电", "position": "中游", "profit_share": 28},
        ]
    },
    "new_energy": {
        "name": "新能源链",
        "desc": "锂矿→电池材料→电芯→储能逆变器→光伏组件→电站运营",
        "profit_pool": {
            "main": "储能逆变器、锂矿(周期底部反弹)",
            "upstream": "锂矿(波动大)、正极材料(15-20%)",
            "midstream": "电芯(10-15%)、逆变器(25-35%)",
            "downstream": "电站运营(8-12%)、EPC(5-8%)",
        },
        "bottleneck": "储能电芯产能过剩,逆变器IGBT国产替代",
        "directional_bias": "产能过剩出清中→利润向逆变器/新技术集中,组件/电池片最惨烈",
        "stocks": [
            {"symbol": "300750", "role": "动力电池/储能", "position": "中游", "profit_share": 15},
            {"symbol": "601012", "role": "光伏硅片/组件", "position": "中游", "profit_share": 10},
            {"symbol": "688390", "role": "光伏逆变器/储能", "position": "中游", "profit_share": 30},
        ]
    },
    "defense": {
        "name": "军工链",
        "desc": "主机厂→航发→电子系统→连接器→材料→锻件",
        "profit_pool": {
            "main": "连接器(35-40%)、高温合金/材料(30-35%)",
            "upstream": "高温合金(30-35%)、钛合金(25-30%)",
            "midstream": "连接器(35-40%)、航电系统(25-30%)",
            "downstream": "主机厂(5-10%)、总装(8-12%)",
        },
        "bottleneck": "航发叶片、高端连接器",
        "directional_bias": "连接器是军工链中ROE最高+现金流最好的环节,主机厂最苦",
        "stocks": [
            {"symbol": "600760", "role": "军机主机厂", "position": "下游", "profit_share": 8},
            {"symbol": "002179", "role": "军用连接器", "position": "中游", "profit_share": 35},
        ]
    },
    "pharma": {
        "name": "医药创新链",
        "desc": "CXO→创新药→原料药→医疗器械→医疗服务",
        "profit_pool": {
            "main": "CXO(25-35%)、创新药(20-40%+)、高端器械(30-40%)",
            "upstream": "原料药(15-20%)、生命科学试剂(40-50%)",
            "midstream": "CXO(25-35%)、医疗器械(30-40%)",
            "downstream": "创新药(20-40%)、医疗服务(15-20%)",
        },
        "bottleneck": "CXO产能（生物安全法案扰动）、高端影像设备",
        "directional_bias": "CXO受地缘政治压制,国内创新药企受益于海外授权(BD出海)",
        "stocks": [
            {"symbol": "603259", "role": "CXO一体化龙头", "position": "中游", "profit_share": 28},
            {"symbol": "300760", "role": "医疗器械龙头", "position": "中游", "profit_share": 35},
        ]
    },
    "consumer_defense": {
        "name": "消费防守链",
        "desc": "白酒→乳制品→调味品→家电→品牌服饰",
        "profit_pool": {
            "main": "高端白酒(70-80%毛利率)",
            "upstream": "农产品(波动大)、包材(10-15%)",
            "midstream": "白酒酿造(70-80%)、乳制品加工(25-35%)",
            "downstream": "品牌运营(15-25%)、渠道分销(8-12%)",
        },
        "bottleneck": "高端白酒产能（时间窖藏）、奶源",
        "directional_bias": "高端白酒是消费链最厚的利润环节,但当前处于去库存周期底部",
        "stocks": [
            {"symbol": "600519", "role": "高端白酒", "position": "中游", "profit_share": 75},
            {"symbol": "000858", "role": "高端白酒", "position": "中游", "profit_share": 72},
            {"symbol": "600887", "role": "乳制品龙头", "position": "中游", "profit_share": 28},
        ]
    },
    "finance": {
        "name": "金融链",
        "desc": "银行→保险→券商→资管→金融科技",
        "profit_pool": {
            "main": "零售银行(净息差)、券商(行情驱动)",
            "upstream": "资金端(央行/同业)",
            "midstream": "零售银行(净息差1.5-2.5%)、对公银行(0.8-1.5%)",
            "downstream": "财富管理(手续费0.5-1%)、保险(死差+费差)",
        },
        "bottleneck": "优质信贷资产荒、保险代理人转型",
        "directional_bias": "零售银行ROE最高且稳定(招行),券商具有高β属性→成交量放大时弹性最大",
        "stocks": [
            {"symbol": "600036", "role": "零售银行龙头", "position": "中游", "profit_share": 18},
            {"symbol": "601318", "role": "综合金融/保险", "position": "下游", "profit_share": 12},
            {"symbol": "600030", "role": "头部券商", "position": "下游", "profit_share": 10},
        ]
    },
    "grid": {
        "name": "电网设备链",
        "desc": "特高压→变压器→开关→线缆→智能电表→电力IT",
        "profit_pool": {
            "main": "超高压变压器(30-35%)、特高压换流阀(40-45%)",
            "upstream": "硅钢/铜(原材料)、绝缘材料(15-20%)",
            "midstream": "变压器(30-35%)、高压开关(25-30%)、换流阀(40-45%)",
            "downstream": "输变电EPC(8-12%)、运维服务(15-20%)",
        },
        "bottleneck": "特高压变压器产能(国产仅3家)、IGBT功率模块",
        "directional_bias": "特高压是十四五/十五五确定性最高的基建方向,换流阀/变压器环节壁垒最高",
        "stocks": [
            {"symbol": "601877", "role": "低压电器", "position": "中游", "profit_share": 28},
            {"symbol": "688390", "role": "储能变流器/PCS", "position": "中游", "profit_share": 32},
        ]
    },
    "commodity": {
        "name": "大宗商品链",
        "desc": "铜→黄金→原油→工业金属→煤炭→化工",
        "profit_pool": {
            "main": "铜(矿端)、黄金(避险)、原油(上游)",
            "upstream": "采矿(铜/金/原油)",
            "midstream": "冶炼(3-5%利润率)、化工(10-15%)",
            "downstream": "加工(5-8%)、贸易(1-2%)",
        },
        "bottleneck": "铜矿资本开支不足(新矿10年+),黄金矿产量见顶",
        "directional_bias": "利润集中在上游采矿环节,冶炼/加工无定价权→只买矿股不买冶",
        "stocks": [
            {"symbol": "601899", "role": "铜/金矿开采", "position": "上游", "profit_share": 40},
            {"symbol": "600028", "role": "石化一体化", "position": "中游", "profit_share": 12},
        ]
    },
}


def get_stock_chain_mapping():
    """返回 {symbol -> [(chain_key, chain_info, role, position, profit_share)]}"""
    mapping = {}
    for key, chain in CHAINS.items():
        for s in chain["stocks"]:
            sym = s["symbol"]
            if sym not in mapping:
                mapping[sym] = []
            mapping[sym].append({
                "chain_key": key,
                "chain_name": chain["name"],
                "role": s["role"],
                "position": s["position"],
                "profit_share": s["profit_share"],
                "bottleneck": chain["bottleneck"],
                "directional_bias": chain["directional_bias"],
            })
    return mapping


def get_chain_for_symbol(symbol):
    """获取单个标的的链信息"""
    mapping = get_stock_chain_mapping()
    return mapping.get(symbol, [])


def score_chain_position(chain_info_list):
    """
    根据链定位评分（0-10）
    - 利润池厚度：profit_share越高越好（0-5分）
    - 位置权重：上游(瓶颈) > 中游 > 下游（0-3分）
    - 瓶颈度：标的是否是chain.bottleneck中的环节（0-2分）
    """
    total = 0
    for ci in chain_info_list:
        ps = ci.get("profit_share", 20)
        pos = ci.get("position", "中游")
        bt = ci.get("bottleneck", "")

        # 利润池厚度分 (0-5)
        pool_score = min(ps / 10, 5)
        # 位置分 (0-3)
        pos_score = {"上游": 3, "中游": 2, "下游": 1}.get(pos, 2)
        # 瓶颈度 (0-2)
        role = ci.get("role", "")
        bottleneck_score = 2 if any(kw in role for kw in ["龙头", "稀缺", "寡头", "独家"]) else \
                           (1 if any(kw in bt for kw in role[:4]) else 0)
        total += pool_score + pos_score + bottleneck_score

    return min(total, 10)


def scan_chains():
    """主扫描：遍历所有WATCHLIST标的，输出链标注结果"""
    mapping = get_stock_chain_mapping()
    results = []

    for sym, info in WATCHLIST.items():
        sym_str = str(sym)
        chain_info = mapping.get(sym_str, [])
        name = info.get("name", sym_str) if isinstance(info, dict) else str(info)
        if not chain_info:
            results.append({
                "symbol": sym_str,
                "name": name,
                "chains": [],
                "chain_scores": {"total": 0, "pool": 0, "position": 0, "bottleneck": 0},
                "best_chain": "未映射",
            })
            continue

        cs = score_chain_position(chain_info)
        chain_names = [c["chain_name"] for c in chain_info]
        roles = [c["role"] for c in chain_info]
        positions = [c["position"] for c in chain_info]
        pool_scores = [min(c["profit_share"]/10, 5) for c in chain_info]
        pos_scores = [{"上游": 3, "中游": 2, "下游": 1}.get(c["position"], 2) for c in chain_info]

        best = max(chain_info, key=lambda c: c.get("profit_share", 0))

        results.append({
            "symbol": sym_str,
            "name": name,
            "chains": chain_names,
            "roles": roles,
            "positions": positions,
            "chain_scores": {
                "total": round(cs, 1),
                "pool": round(max(pool_scores), 1),
                "position": max(pos_scores),
                "bottleneck": best.get("profit_share", 20) / 10,
            },
            "best_chain": best["chain_name"],
            "best_role": best["role"],
            "best_position": best["position"],
            "direction": best.get("directional_bias", ""),
        })

    return results


def format_chain_report(scan_results):
    """生成为日报可用的文本报告"""
    chains_covered = set()
    for r in scan_results:
        for c in r.get("chains", []):
            if c:
                chains_covered.add(c)

    lines = []
    lines.append(f"📊 产业链覆盖: {len(chains_covered)}/12条链")
    lines.append(f"   已覆盖: {' | '.join(sorted(chains_covered))}")
    lines.append("")

    # 按链分组
    by_chain = {}
    for r in scan_results:
        for i, c_name in enumerate(r.get("chains", [])):
            if c_name:
                by_chain.setdefault(c_name, []).append(r)

    for chain_name, chain_stocks in sorted(by_chain.items()):
        chain_key = None
        for k, c in CHAINS.items():
            if c["name"] == chain_name:
                chain_key = k
                break
        if chain_key:
            chain_def = CHAINS[chain_key]
        else:
            chain_def = {}
        lines.append(f"  {chain_name}")
        lines.append(f"    利润池: {chain_def.get('profit_pool', {}).get('main', 'N/A')}")
        lines.append(f"    瓶颈: {chain_def.get('bottleneck', 'N/A')}")
        lines.append(f"    方向: {chain_def.get('directional_bias', 'N/A')}")
        for st in sorted(chain_stocks, key=lambda x: x.get("chain_scores", {}).get("total", 0), reverse=True):
            pos = st.get("best_position", "?")
            role = st.get("best_role", "?")
            cs = st.get("chain_scores", {})
            lines.append(f"      {st['symbol']}({st['name']}) [{pos}] {role} — 链分{cs.get('total',0):.1f}")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    results = scan_chains()
    report = format_chain_report(results)
    print(report)
    print(f"\n✅ {len(results)}个标的完成链标注")
