#!/usr/bin/env python3
"""创建段永平投资体系学习笔记飞书文档"""
import sys, time, json, os
sys.path.insert(0, '/home/admin/.hermes')
from dotenv import load_dotenv
load_dotenv('/home/admin/.hermes/.env')

import investment_system.output.report_v6 as rpt
w = rpt.FeishuWriter()

title = "段永平投资体系学习笔记 — fastisslow 仓库深度分析"
doc_id = w.create_doc(title)
log = lambda m: print(f"[{time.strftime('%H:%M:%S')}] {m}")
log(f"Doc: {doc_id}")

# ── 0. 引子 ──
w.write(doc_id, [('h2', '0. 📖 关于本文档')])
w.write(doc_id, [('text', '本文档基于 github.com/iqiancheng/fastisslow 仓库（段永平投资理念资料合集）的系统性整理，')])
w.write(doc_id, [('text', '结合段永平公开访谈、斯坦福对话、投资问答录（商业逻辑篇/投资逻辑篇）等核心材料，')])
w.write(doc_id, [('text', '提炼出一套可用于改进面基·LDS·Vibe-Trading 三源融合选股系统的价值投资框架。')])
w.write(doc_id, [('divider', '')])

# ── 1. 仓库概览 ──
w.write(doc_id, [('h2', '1. 📂 fastisslow 仓库概览')])
w.write(doc_id, [('text', '仓库名称 fastisslow 取自段永平的核心理念 "fast is slow"（欲速不达），')])
w.write(doc_id, [('text', '收录段永平投资问答录（商业逻辑篇 + 投资逻辑篇）、斯坦福对话 Stop Doing List 全文、')])
w.write(doc_id, [('text', '雪球系列分析、不为清单原始 PDF 等 16 份核心材料。')])
w.write(doc_id, [('divider', '')])
w.write(doc_id, [('bold', '关键文件清单：')])
w.write(doc_id, [('bullet', '段永平投资问答录(商业逻辑篇).pdf — 核心，17MB，商业分析框架')])
w.write(doc_id, [('bullet', '段永平投资问答录(投资逻辑篇).pdf — 核心，4MB，选股买入框架')])
w.write(doc_id, [('bullet', '段永平的投资逻辑(雪球).pdf — 雪球社区精华整理')])
w.write(doc_id, [('bullet', '在斯坦福对话段永平：Stop Doing List（附学习笔记）.html — 2018年斯坦福演讲全文')])
w.write(doc_id, [('bullet', '段永平：不为清单（Stop Doing List）.pdf — 不为清单原始档')])
w.write(doc_id, [('bullet', '段永平连答49问：成功秘诀在"Stop Doing List".pdf — 49问全文')])
w.write(doc_id, [('bullet', '张昕帆/早期报纸上的段永平/段永平投资逻辑等 — 补充材料')])
w.write(doc_id, [('divider', '')])

# ── 2. 核心哲学 ──
w.write(doc_id, [('h2', '2. 🧠 核心哲学：Stop Doing List')])
w.write(doc_id, [('quote', '"不做的事情更重要。聚焦，才能做长期正确的事情。" — 段永平，2018年斯坦福对话')])
w.write(doc_id, [('text', '段永平的整个投资体系可以归结为三层结构：')])
w.write(doc_id, [('bullet', '第一层：什么是对的事（Do right thing）— 长期看有复利的事')])
w.write(doc_id, [('bullet', '第二层：怎么把事做对（Do things right）— 执行层面的方法论')])
w.write(doc_id, [('bullet', '第三层：不做错的事（Stop Doing List）— 这是最关键的一层')])

w.write(doc_id, [('bold', '理论基础（来自仓库原文学习笔记）：')])
w.write(doc_id, [('bullet', '德鲁克："效率是以正确的方式做事，效能源是做正确的事。"先效能、再效率。')])
w.write(doc_id, [('bullet', '波普尔证伪主义：知识是递减的——是我们减掉的内容（什么行不通），不是我们增加的内容。')])
w.write(doc_id, [('bullet', '塔勒布："某人告诉你该做什么（咨询师/股票经纪人），而不是不该做什么——你需要警惕。"')])
w.write(doc_id, [('divider', '')])

w.write(doc_id, [('h3', '2.1 长期思维是核心引擎')])
w.write(doc_id, [('text', '段永平强调用 10 年以上的视角看问题。2018 年中美贸易战时他说：')])
w.write(doc_id, [('quote', '"其实我们一直都是在动荡中……贸易战是好公司的机会、坏公司的借口。"')])
w.write(doc_id, [('text', '用长期思维看问题，才能承受波动不动摇，让时间产生复利。')])
w.write(doc_id, [('divider', '')])

# ── 3. 不为清单十条 ──
w.write(doc_id, [('h2', '3. ⛔ 不为清单 — 选股前置过滤器')])
w.write(doc_id, [('text', '以下十条适用于面基系统扫描结果的快速过滤，有任一条不满足则不应进入建仓池：')])
w.write(doc_id, [('divider', '')])

rules = [
    ('不懂的不做', '无法用三句话说清商业模式的股票不投。如果说不清它在赚什么钱、为什么别人抢不走，pass。'),
    ('不借钱投资', '杠杆会扭曲判断。段永平在网易上赚 100 倍时也没加杠杆。体系内对应：模拟盘始终全现金，不 margin。'),
    ('不做空', '时间不在你这边。做空最多赚 100%，但亏损无上限。'),
    ('不投短期利益驱动', '赚快钱、频繁资本运作、不断转型的公司——"管理层心不定"是最大风险。'),
    ('不信管理层不投', '诚信是底线。段永平买入 PDD 是因为信任黄峥的人品。有财务造假记录或大股东频繁减持者 pass。'),
    ('不追热点概念', '"风口上的猪"段永平从来不信。AI 概念、元宇宙、区块链等热度与公司质量无关。'),
    ('不预测宏观', '宏观是用来应对的，不是用来交易的。段永平说"我从来不靠宏观预测赚钱"。'),
    ('不因为便宜而买', '便宜一定有便宜的理由。低 PE 不等于低估值——可能是价值陷阱。'),
    ('不到合理估值不买', '"等"是价投最重要的技能。预留现金、等待好价格是超额收益来源。'),
    ('不投不易理解的高频变化行业', '比如难以预测的产品驱动型消费电子。段永平自己做消费电子出身，反而最不投——他知道不确定性。'),
]

for i, (name, desc) in enumerate(rules, 1):
    w.write(doc_id, [('h3', f'3.{i} {name}')])
    w.write(doc_id, [('text', desc)])

w.write(doc_id, [('divider', '')])

# ── 4. 选股四步框架 ──
w.write(doc_id, [('h2', '4. 🎯 选股四步框架')])
w.write(doc_id, [('text', '根据段永平实践提炼的选股流程，与面基 8 维深研互补：')])

w.write(doc_id, [('h3', 'Step 1: 商业逻辑穿透')])
w.write(doc_id, [('quote', '"买股票就是买公司，买公司就是买生意。"')])
w.write(doc_id, [('text', '三句话问清楚：')])
w.write(doc_id, [('bullet', '卖什么？— 产品/服务有多难复制（技术壁垒 vs 品牌壁垒 vs 规模壁垒）')])
w.write(doc_id, [('bullet', '卖给谁？— 客户有多强的黏性（转换成本/网络效应/习惯依赖）')])
w.write(doc_id, [('bullet', '为什么是你？— 护城河深度（品牌溢价/成本优势/监管准入）')])

w.write(doc_id, [('h3', 'Step 2: 护城河类型识别')])
w.write(doc_id, [('text', '段永平认为真正的护城河只有这几类：')])
w.write(doc_id, [('bullet', '🔵 品牌溢价 — 你敢卖便宜你同行先死（苹果/茅台）')])
w.write(doc_id, [('bullet', '🟢 转换成本 — 客户换不掉你（Adobe/SAP/恒生电子）')])
w.write(doc_id, [('bullet', '🟡 网络效应 — 用户越多越好用（腾讯/PDD/美团）')])
w.write(doc_id, [('bullet', '🔴 规模成本 — 拼命砸钱就是壁垒（台积电/中芯国际）')])
w.write(doc_id, [('bullet', '⚪ 监管准入 — 没有牌照你进不来（中移动/茅台）')])

w.write(doc_id, [('h3', 'Step 3: "等" — 关注 vs 买入的区分')])
w.write(doc_id, [('text', '段永平 90% 的时间在等待。好公司 + 好价格才是买点：')])
w.write(doc_id, [('bullet', '看不懂 → 永久 pass，不进入扫描')])
w.write(doc_id, [('bullet', '看懂了但贵 → 纳入"观察"，等待估值回调')])
w.write(doc_id, [('bullet', '看懂了，贵也不卖 → 如苹果，持有几十年的核心仓位')])
w.write(doc_id, [('bullet', '看懂了 + 好价格 → 大仓位买入（可达 40%+ 单票）')])

w.write(doc_id, [('h3', 'Step 4: 买入后 — 不看盘')])
w.write(doc_id, [('quote', '"如果买入某公司，你应该觉得即使明天关掉股市 5 年也无所谓。"')])
w.write(doc_id, [('text', '段永平买入苹果后，基本不看日线。他的卖出只有两个条件：①公司基本面永久性恶化 ②估值极度泡沫。')])
w.write(doc_id, [('divider', '')])

# ── 5. 与面基系统对比诊断 ──
w.write(doc_id, [('h2', '5. 🔍 当前面基选股系统的差距诊断')])
w.write(doc_id, [('bold', '五大核心差距：')])
w.write(doc_id, [('divider', '')])

w.write(doc_id, [('h3', '5.1 不够动态发现')])
w.write(doc_id, [('text', '问题：WATCHLIST 138 只固定池，新增票全靠扫描偶然发现。138 只 A 股打散扫描，')])
w.write(doc_id, [('text', '缺乏产业链视角的主动发现机制。')])
w.write(doc_id, [('bold', '段永平解法：')])
w.write(doc_id, [('bullet', '"先看懂一条链，才投一个链"。不是 138 只打散评分，而是从链的中游利润率提升 → 发现上游机会。')])

w.write(doc_id, [('h3', '5.2 不够深度理解')])
w.write(doc_id, [('text', '问题：6 因子综合评分（质量/价值/成长/低波/红利/动量）打高分 ≠ 好公司。')])
w.write(doc_id, [('text', '一个 ROE 高 + 动量好 + PE 低的票，可能商业模式已经崩塌。')])
w.write(doc_id, [('bold', '段永平解法：')])
w.write(doc_id, [('bullet', '商业逻辑穿透优先于财务指标。ROE 高是果，护城河深是因。')])
w.write(doc_id, [('bullet', '不做"打分建仓"——分数只用来排序注意力，真正的买卖决策靠深度研究。')])

w.write(doc_id, [('h3', '5.3 轮动频率太高')])
w.write(doc_id, [('text', '问题：模拟盘日频检查 → 评分变化触发换仓。段永平说这是"炒股"，不是投资。')])
w.write(doc_id, [('bold', '段永平解法：')])
w.write(doc_id, [('bullet', '好公司不需要每天评分。建仓前想清楚——五年后这家公司还在不在？')])

w.write(doc_id, [('h3', '5.4 仓位过于分散')])
w.write(doc_id, [('text', '问题：最多 8 只，单票上限 ~2%，凯利公式限制在 f* ≤ 25%。')])
w.write(doc_id, [('bold', '段永平解法：')])
w.write(doc_id, [('bullet', '"不是一般的集中，而是绝对的集中。"苹果占他个人仓位的 80%+。')])
w.write(doc_id, [('bullet', '确定性与集中度正相关——看懂 100% 才可以押 40%+。')])

w.write(doc_id, [('h3', '5.5 买入前过滤不够')])
w.write(doc_id, [('text', '问题：当前扫描→评分→前 5 名建仓，无"不为清单"过滤。')])
w.write(doc_id, [('bold', '段永平解法：')])
w.write(doc_id, [('bullet', '买入前必须有 Stop Doing List 检查：管理层可信吗？商业模式理解吗？有短期诱惑吗？')])
w.write(doc_id, [('divider', '')])

# ── 6. 三段式改造方案 ──
w.write(doc_id, [('h2', '6. 🔧 三段式选股改造方案')])
w.write(doc_id, [('text', '将段永平框架融入现有面基系统的具体实施方案：')])
w.write(doc_id, [('divider', '')])

w.write(doc_id, [('h3', 'Phase 1: 因子扫描（现有，保留）')])
w.write(doc_id, [('text', '138 只 LDS 标的，6 因子排序分位法评分，输出 TOP15。作为粗筛工具。')])

w.write(doc_id, [('h3', 'Phase 2: 不为清单过滤（新增）')])
w.write(doc_id, [('text', '在 score_stock 返回结果中加 pass_stop_doing_list 字段。')])
w.write(doc_id, [('bullet', 'LLM 驱动或规则引擎判断：商业模式可理解？管理层可信？不在热点概念里？')])
w.write(doc_id, [('bullet', '不通过者→即使分数高也不建仓')])

w.write(doc_id, [('h3', 'Phase 3: 深度研报（现有 deep_research.py）')])
w.write(doc_id, [('text', '对不为清单 PASS 的票执行 8 维深研，输出买入建议 + 仓位建议 + 等待条件。')])

w.write(doc_id, [('bold', '关键改动点：')])
w.write(doc_id, [('bullet', '① WATCHLIST 按"理解深度"分层 L0-L3，L0（不理解）不建仓')])
w.write(doc_id, [('bullet', '② 扫描+链追踪双轨 — 新增链健康度监测（毛利率趋势/竞争格局）')])
w.write(doc_id, [('bullet', '③ 不为清单→代码化前置过滤器')])
w.write(doc_id, [('bullet', '④ 模拟盘从日频改为周频评估')])
w.write(doc_id, [('divider', '')])

# ── 7. 与面基8维深研映射 ──
w.write(doc_id, [('h2', '7. 🔗 与面基 8 维深研框架的融合')])
w.write(doc_id, [('text', '段永平框架与现有 8 维深研天然互补，不是替代关系：')])
w.write(doc_id, [('divider', '')])

pairs = [
    ('产业链定位', '商业逻辑 + 利润池', '已有但可增加段永平式"三句话说清"检验'),
    ('翻倍逻辑', '好公司 + 好价格', '段永平不追求翻倍，而是"合理价格买好公司"，可改为双轨'),
    ('DCF 估值', '"你愿意买下整家公司吗"测试', '保留 DCF，加一段"买下公司 test"作为 sanity check'),
    ('凯利仓位', '确定性决定集中度', '段永平的凯利是"确定性越高仓位越集中"，对应理解深度分层'),
    ('Nick 四问', '不为清单前置过滤', '不为清单 pass 后才问 Nick，减少无效分析'),
    ('贝叶斯更新', '跟踪事实变化', '段永平买入后跟踪的核心是"事实变了没有"，而非价格波动'),
    ('风险清单', 'Stop Doing List', '不为清单是最佳风险过滤器，覆盖 8% 硬止损之外的大部分风险'),
    ('面基引用', '段永平引用索引', '新增段永平材料引用'),
]

for dim, dyp_match, suggestion in pairs:
    w.write(doc_id, [('bold', f'{dim}')])
    w.write(doc_id, [('bullet', f'段永平对应: {dyp_match}')])
    w.write(doc_id, [('bullet', f'融合建议: {suggestion}')])
    w.write(doc_id, [('text', '')])

w.write(doc_id, [('divider', '')])

# ── 8. 段永平实际持仓分析 ──
w.write(doc_id, [('h2', '8. 💼 段永平实际持仓案例')])
w.write(doc_id, [('text', '观察段永平的公开持仓，可以验证他的框架如何落地：')])
w.write(doc_id, [('divider', '')])

cases = [
    ('苹果 (AAPL)', '段永平最大持仓（估计占 ~80%）', 
     '品牌溢价护城河：iOS 生态转换成本极高\n'
     '管理层：库克是运营天才，乔布斯订的方向被执行到极致\n'
     '不为清单通过：没有借债、不追热点（汽车项目取消）、不盲目并购\n'
     '买入时点：2011 年乔布斯去世后市场恐慌，PE~12x\n'
     '持有方式：从未卖出，至今 14 年'),
    ('拼多多 (PDD)', '段永平是早期投资者兼 mentor',
     '信任管理层：黄峥是段永平的浙大师弟 + 谷歌同事\n'
     '网络效应护城河：社交裂变成本极低，下沉市场先发优势\n'
     '不为清单通过：无借债、不烧钱买流量、不碰金融\n'
     '买入时点：2015 年创立时即投资'),
    ('网易 (NTES)', '段永平最著名的投资（~100 倍回报）',
     '困境反转机会：2002 年互联网泡沫破灭后，网易因游戏复苏\n'
     '管理层：丁磊对游戏的专注被低估\n'
     '不为清单通过：不做门户烧钱，专注游戏现金牛\n'
     '买入时点：2002 年，跌到 $0.8 时买入\n'
     '退出时机：2006 年逐步退出，涨幅已超百倍'),
]

for name, role, detail in cases:
    w.write(doc_id, [('h3', name)])
    w.write(doc_id, [('text', f'角色: {role}')])
    for line in detail.split('\n'):
        w.write(doc_id, [('bullet', line)])
    w.write(doc_id, [('text', '')])

w.write(doc_id, [('divider', '')])

# ── 9. 学习笔记总结 ──
w.write(doc_id, [('h2', '9. 📝 学习总结与下一步行动')])
w.write(doc_id, [('divider', '')])

w.write(doc_id, [('bold', '核心认知转变：')])
w.write(doc_id, [('bullet', '多因子评分是高效粗筛工具，不是买卖决策引擎。')])
w.write(doc_id, [('bullet', '"不为清单"前置过滤比任何止损都重要——买入前想清楚不卖的条件。')])
w.write(doc_id, [('bullet', '好公司 + 好价格 = 超额收益。不同时满足这两条，不建仓。')])
w.write(doc_id, [('bullet', '集中度 = 确定性。L2 以下理解程度的票，上限 2%；L3 可达 30%。')])
w.write(doc_id, [('bullet', '时间是最好的朋友——看 10 年的视角比任何技术指标都准。')])
w.write(doc_id, [('bold', '即刻可落地的高优先级事项：')])
w.write(doc_id, [('bullet', '#1: 在 factor_scanner.py score_stock 返回中增加 pass_stop_doing_list 字段')])
w.write(doc_id, [('bullet', '#2: WATCHLIST 分层（L0-L3 理解深度）')])
w.write(doc_id, [('bullet', '#3: 链健康度监测替代纯分数扫描作为发现机制')])
w.write(doc_id, [('bullet', '#4: 模拟盘从日频改为周频')])
w.write(doc_id, [('bold', '段永平个人传记/扩展阅读：')])
w.write(doc_id, [('bullet', '《段永平投资问答录(商业逻辑篇)》 — 仓库内，核心必读')])
w.write(doc_id, [('bullet', '《段永平投资问答录(投资逻辑篇)》 — 仓库内，核心必读')])
w.write(doc_id, [('bullet', '《段永平：不为清单 Stop Doing List》 — 仓库内，一页极简')])
w.write(doc_id, [('bullet', '斯坦福对话全文 — 仓库内，约 2 万字对话实录')])
w.write(doc_id, [('bullet', '段永平雪球账号 @大道无形我有型 持续更新')])
w.write(doc_id, [('divider', '')])

# ── 10. 仓库信息 ──
w.write(doc_id, [('h2', '10. 🔗 仓库引用')])
w.write(doc_id, [('bullet', '仓库: github.com/iqiancheng/fastisslow')])
w.write(doc_id, [('bullet', '精选语录: "fast is slow." (欲速不达)')])
w.write(doc_id, [('bullet', '核心材料: 段永平投资问答录(商业逻辑篇) + (投资逻辑篇) + Stop Doing List + 斯坦福对话')])
w.write(doc_id, [('bullet', '本文档创建于: 2026-06-05 收盘后')])

log(f"✅ 文档已创建: https://bytedance.feishu.cn/docx/{doc_id}")
print(f"📄 https://bytedance.feishu.cn/docx/{doc_id}")