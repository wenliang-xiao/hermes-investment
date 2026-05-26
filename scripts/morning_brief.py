"""
面基三源融合 v5.3 — 盘前简报
运行时间：每日 8:30 AM（开盘前）
聚焦：隔夜全球市场 + 政经新闻 + 今日预期 + 核心概念提醒
"""
import sys, os, json, time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from investment_system.data.global_data import (
    fetch_all_global_market, load_cached_global_data,
    fetch_global_indices, fetch_hk_stocks, fetch_us_stocks,
    fetch_commodities, fetch_fx_rates, fetch_bond_yields,
)
from investment_system.domain.news_fetcher import fetch_news
from investment_system.config import FEISHU_GROUP_CHAT

# ─── 常量 ────────────────────────────────────
TODAY = datetime.now()
TODAY_STR = TODAY.strftime("%Y-%m-%d")
WEEKDAY = ["一", "二", "三", "四", "五", "六", "日"][TODAY.weekday()]

# ─── 隔夜全球市场数据 ────────────────────────
OVERSEAS_WATCH = {
    "美股": [("^GSPC", "标普500"), ("^IXIC", "纳斯达克"), ("^DJI", "道琼斯")],
    "港股ADR": [("BABA", "阿里巴巴"), ("9988.HK", "阿里港股"), ("0700.HK", "腾讯港股")],
    "期货": [("GC=F", "黄金"), ("CL=F", "原油"), ("HG=F", "铜")],
    "外汇": [],  # 从 chinamoney 获取
    "债券": [("^TNX", "10Y美债收益率")],
}

# ─── 面基核心概念（每日重复） ────────────────
DAILY_MANTRA = """
> 📖 **面基今日概念 — 每日重温一条播客思想**

{concept}

> 💡 *结合今日市场：{insight}*
"""

# 30条轮换概念，每天一条
CONCEPTS = [
    ("E153 复利公式 G=Edge×Position×Frequency×Time",
     "任何交易的长期回报不取决于你对了多少次，而是你在正确方向上的暴露。今天思考：当前市场给你的「遍历性」够不够长到让Edge兑现？"),
    ("E153 凯利公式 f*=(bp-q)/b",
     "胜率p和赔率b共同决定仓位。半凯利是最优实践的保守版。今天如果买入，你算过你的b和p吗？"),
    ("E68 恽雷·两朵花",
     "FCF增长（成长）vs FCF释放（股息/回购）。哑铃两端，一手质量成长(外资定价)，一手高股息(南下偏好)。当前哪端更便宜？"),
    ("E31 丁昶·地效飞行器策略",
     "买最小市值的一批股票等量持有。底层逻辑：A股小票有壳价值+散户主导的波动红利。小市值因子长期有效。"),
    ("E111 塔勒布·杠铃策略",
     "90%极度安全 + 10%极度风险。不要在中间地带浪费仓位。反脆弱的凸性结构：损失有限但收益无限。"),
    ("E111 塔勒布·遍历性",
     "存在爆仓可能的策略，长期亏损概率=100%。不出局是复利的第一前提。2%风险管理常数比任何因子都重要。"),
    ("E81 Nick灵魂四问",
     "①紧急度 ②趋势真实性 ③身边人共识 ④持有者拥挤度。低共识+强趋势=最佳入场；高共识+高拥挤=危险信号。"),
    ("E32 南添·投资光谱右移",
     "增量时代看左侧(新技术/营收)，存量时代看右侧(现金流/股息)。你手里的标的处于光谱哪个位置？"),
    ("E75 丁昶·效率→公平周期",
     "一代人级别的范式转换。公平周期=自主可控优先级↑→国产替代估值中枢上移。效率周期=全球化/比较优势→成长股溢价。"),
    ("E7/E84 中观四层次",
     "产业生命周期→需求景气度→短期业绩兑现度→估值。二阶导>一阶导。问自己：现在买的是渗透率的哪个阶段？"),
    ("E94 康波衰退期·存量博弈",
     "康波衰退→繁荣的简单逻辑失效→存量博弈→寻找结构性机会。不再有β红利，α来自对细分链条的深度理解。"),
    ("E126 林晓明·技术是周期结果而非原因",
     "技术不是驱动周期的原因，而是周期的结果。当前的AI热，到底是新技术周期的启动，还是康波后半段的余波？"),
    ("E102 胡恒·投资第一性原理",
     "投资的第一性原理不是「买好公司」，而是「用合适的价格买入」。好公司买贵了也一样亏钱。"),
    ("E65 何潇·空仓哲学",
     "当市场没有能力圈内的机会时，空仓是最佳策略。最悲观时买(非最低)，最乐观时卖(非最高)。"),
    ("E114 复杂适应系统",
     "CAS世界观：市场是非线性/动态/不可预测的。均衡是幻觉，非均衡才是常态。在乱纪元里，防住风险本身就是一种收益。"),
    ("E147 控制论·正负反馈",
     "正反馈=成长投资(自我强化)，负反馈=价值投资(均值回归)。识别当前主导循环是繁荣(self-reinforcing)还是回归。"),
    ("E35 凌鹏·万物皆周期",
     "估值终有效，人性永不变。涨多了会跌，跌多了会涨——不是废话，是刻在基因里的规律。"),
    ("E85 田大伟·量化阿尔法=能力×宽度²",
     "因子多→IC提升→阿尔法空间大。A股动量与反转都很强但周期短。价值因子长期有效但时滞长。"),
    ("E128 董艺婷·择时胜率<50%",
     "择时的时间成本极高。更有效的策略是「动态再平衡」：纪律化低买高卖，不靠运气靠机制。"),
    ("E54 张翼轸·有纪律地追涨杀跌",
     "基于相对强度轮动。回看N月涨幅排名→持有到反转。不是主观判断，是规则执行。没感情地跟随大哥。"),
    ("E119 Dalio·债务周期",
     "短期6±3年(库存)，长期80±25年(结构性)。当前长期债务周期在什么位置？→决定了战略配置的大方向。"),
    ("E13 南添·实事求是三层",
     "事实层(what)→解释层(why)→决策层(how)。多数人跳过事实直奔决策。每次买入前：你看到的事实是什么？"),
    ("E30 贝叶斯哲学",
     "不当聪明投资者，只做合格持有人。用新信息不断更新先验概率。今天你有什么新证据修正了之前的判断？"),
    ("E109 Kevin·薄情逆向多元有限下注",
     "对未来没有观点→必须分散。四字诀背后的逻辑：承认自己是弱者才能活更久。"),
    ("E55 红利·保守时代公约数",
     "低利率+震荡市中，股息率+分红连续性是最可靠的超额收益来源。当前利率环境给红利策略多少空间？"),
    ("E72 南添·r>g>w",
     "利率>经济增长>工资增长=财富分配的底层逻辑。当r>g时，存量财富的增长快于增量→贫富分化加剧→政策纠偏。"),
    ("E99 丁昶·「退休传家组合」",
     "标普500+全球黄金ETF+全球REITs=穿越周期的三大支柱。不需要择时，需要的是耐心持有。"),
    ("E116 价值投资·逆风是试金石",
     "非对称风险承担：下行保护>上行收益。真正的好投资不是在顺风中跑得快，而是在逆风中不翻船。"),
    ("E144 Nick·交易艺术四原则",
     "不预测→统计优势→分散红利→随机波动。趋势跟踪的哲学：价格代表一切，我跟价格走就行。"),
    ("最新 有效前沿·协方差矩阵的魔力",
     "组合风险≠各资产风险相加。找更好的资产，或者找更不一样的资产。你的组合里有几对低相关性？"),
]

def _get_concept():
    """获取今日轮换概念"""
    idx = TODAY.timetuple().tm_yday % len(CONCEPTS)
    name, insight = CONCEPTS[idx]
    return DAILY_MANTRA.format(concept=name, insight=insight)

# ─── 隔夜数据获取 ───────────────────────────
def fetch_overnight():
    """获取隔夜全球市场数据"""
    lines = []
    try:
        idx_data = fetch_global_indices()
        for symbol, info in idx_data.items():
            name = info.get("name", symbol)
            price = info.get("price", "N/A")
            change = info.get("change_pct", 0)
            if change is None:
                change = 0
            dir_emoji = "🔴" if change < 0 else ("🟢" if change > 0 else "➡️")
            lines.append(f"  {dir_emoji} **{name}**：{price}（{change:+.2f}%）")
    except Exception as e:
        lines.append(f"  ⚠ 指数数据获取失败: {e}")

    try:
        comm_data = fetch_commodities()
        for symbol, info in comm_data.items():
            name = info.get("name", symbol)
            price = info.get("price", "N/A")
            change = info.get("change_pct", 0)
            if change is None:
                change = 0
            dir_emoji = "🔴" if change < 0 else ("🟢" if change > 0 else "➡️")
            lines.append(f"  {dir_emoji} **{name}**：{price}（{change:+.2f}%）")
    except Exception as e:
        lines.append(f"  ⚠ 商品数据获取失败: {e}")
    return lines


def fetch_fx():
    """获取人民币汇率"""
    try:
        fx = fetch_fx_rates()
        if fx:
            lines = []
            if fx.get("USD/CNY"):
                lines.append(f"  美元/人民币：{fx['USD/CNY']}")
            if fx.get("EUR/CNY"):
                lines.append(f"  欧元/人民币：{fx['EUR/CNY']}")
            return lines
    except Exception:
        pass
    return []

# ─── 新闻简报 ──────────────────────────────
def format_news_brief():
    """总分结构新闻：先总结再分类+链接"""
    try:
        data = fetch_news()
    except Exception:
        return "  ⚠ 新闻获取失败\n"

    cats = data.get("categories", {})
    total = data.get("total", 0)

    # 总述
    lines = [f"\n## 📰 隔夜政经新闻（共{total}条）\n"]

    # 分类详述
    priority = [("宏观政策", "🏛"), ("市场动态", "📈"), ("大宗商品", "🛢"),
                ("产业趋势", "🏭"), ("综合", "📋")]

    for cat, emoji in priority:
        items = cats.get(cat, [])
        if not items:
            continue
        lines.append(f"### {emoji} {cat}")
        for item in items[:5]:
            title = item.get("title", "")
            link = item.get("link", "")
            if link:
                lines.append(f"  • [{title}]({link})")
            else:
                lines.append(f"  • {title}")
        lines.append("")

    return "\n".join(lines)

# ─── 今日市场预期 ──────────────────────────
def format_today_outlook():
    """今日关注点和预期"""
    return f"""
## 🎯 今日关注

- 📅 周{WEEKDAY} · {TODAY_STR}
- 🕐 A股开盘 9:30 / 收盘 15:00
- 🔍 关注板块：结合当前宏观象限动态更新
- ⚡ 今日催化剂：政经新闻头条+大宗商品夜盘方向
"""

# ═══════════════════════════════════════════
# 主函数
# ═══════════════════════════════════════════
def build_morning_brief() -> str:
    """构建盘前简报全文"""
    print(f"[morning_brief] {TODAY_STR} 盘前简报生成中...")

    parts = []

    # 标题
    parts.append(f"# 🌅 面基三源融合 · 盘前简报")
    parts.append(f"📅 {TODAY_STR} 周{WEEKDAY} · v5.3")

    # ── Part 1: 隔夜全球市场 ──
    parts.append(f"\n## 🌍 隔夜全球市场\n")
    overseas = fetch_overnight()
    if overseas:
        parts.extend(overseas)
    else:
        parts.append("  ⚠ 隔夜数据获取失败")

    # 汇率
    fx = fetch_fx()
    if fx:
        parts.append(f"\n**💱 汇率**")
        parts.extend(fx)

    # ── Part 2: 新闻 ──
    parts.append(format_news_brief())

    # ── Part 3: 今日预期 ──
    parts.append(format_today_outlook())

    # ── Part 4: 核心概念提醒 ──
    parts.append(f"\n---\n")
    parts.append(_get_concept())

    # ── 脚注 ──
    parts.append(f"\n---\n")
    parts.append(f"> 🤖 面基三源融合系统 · 盘前简报 · 下次更新时间 {TODAY_STR} 15:30")
    parts.append(f"> 📊 完整日报将在收盘后推送，包含6层架构+产业链深度分析")

    body = "\n".join(parts)
    return body


# ═══════════════════════════════════════════
# 飞书推送
# ═══════════════════════════════════════════
def push_to_feishu(body: str):
    """推送盘前简报到飞书群"""
    import subprocess
    import json as _json

    FEISHU_TOOL = "/home/admin/.hermes/investment_system/node_modules/.bin/feishu-tool"

    payload = _json.dumps({
        "chatId": FEISHU_GROUP_CHAT,
        "content": body,
    }, ensure_ascii=False)

    try:
        r = subprocess.run(
            [FEISHU_TOOL, "send_feishu_message", payload],
            capture_output=True, text=True,
            env={**os.environ, "FEISHU_SCOPE_VALIDATION": "false"},
            timeout=30
        )
        if r.returncode == 0:
            print("  ✅ 盘前简报已推送")
        else:
            print(f"  ❌ 推送失败: {r.stderr[:200]}")
            # 备用：输出到文件
            out_path = f"/tmp/morning_brief_{TODAY_STR}.md"
            with open(out_path, "w") as f:
                f.write(body)
            print(f"  📄 已保存到 {out_path}")
    except Exception as e:
        print(f"  ❌ 推送异常: {e}")


if __name__ == "__main__":
    body = build_morning_brief()
    push_to_feishu(body)
    print("✅ 盘前简报完成")
