"""
analysis/knowledge_ref.py — 面基播客知识库主动引用模块

面基154期内容已被整理为12主题13篇飞书文档（QhIOfB63Sl6Kqmd81fycjR6jnDd）。
本模块提供结构化知识查找，供策略/研报/日报引用。

用法:
    from analysis.knowledge_ref import KnowledgeBase, get_relevant_knowledge

    # 获取某产业链相关知识
    kb = KnowledgeBase()
    refs = kb.query_chain("光模块")
    print(refs[0]["title"], refs[0]["episodes"])

    # 获取某维度的方法论引用
    methods = kb.get_methodology("dcf")
    # => [{"title": "DCF估值", "episodes": ["E124"], "concepts": [...]}, ...]
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class KnowledgeRef:
    """一条面基知识引用"""
    topic: str              # 主题名
    title: str              # 飞书文档名
    doc_token: str          # 飞书文档 token
    episodes: list[str]     # 相关期数
    concepts: list[str]     # 核心概念
    relevance: list[str]    # 适用场景标签


@dataclass
class MethodologyRef:
    """方法论级引用"""
    method: str             # 方法名
    topic: str              # 主题
    episodes: list[str]     # 期数
    key_points: list[str]   # 关键点
    chain_tags: list[str]   # 适用的产业链


# ─── 12主题知识库定义 ───
# 源: 面基播客154期, 整理为13篇飞书文档

KNOWLEDGE_BASE: list[KnowledgeRef] = [
    # 1. 产业链分析
    KnowledgeRef("中观产业链", "产业链分析框架", "OVRjdru7xodDFxdcHmHc8QcWnWb",
                 ["E7", "E84", "E94"], ["中观四层次", "Perez阶段", "利润池", "瓶颈度"],
                 ["chain_analysis", "position", "moat"]),
    # 2. DCF/估值
    KnowledgeRef("估值方法", "DCF估值与自由现金流", "UL2Sdi0RyoSJ7EcNYxHcJIGGnWg",
                 ["E68", "E124"], ["DCF三情景", "FCF两朵花", "永续增长率", "WACC"],
                 ["dcf", "valuation", "fcf"]),
    # 3. 凯利/仓位管理
    KnowledgeRef("仓位管理", "凯利公式与复利", "Mj5PdfcTsoeG47cW6jdcY9tGnVg",
                 ["E153"], ["凯利公式", "半凯利", "复利效应", "仓位纪律"],
                 ["kelly", "position_sizing", "risk"]),
    # 4. Nick四问
    KnowledgeRef("决策框架", "Nick四问决策框架", "HkZXdsYItogyDoxbBUtcMKBjn4f",
                 ["E81"], ["紧急性", "趋势", "共识", "拥挤度"],
                 ["decision", "timing", "consensus"]),
    # 5. 贝叶斯
    KnowledgeRef("贝叶斯更新", "贝叶斯思维与投资更新", "SjjHdTRMioiIbwxO5khc5otCn0e",
                 ["E30", "E77"], ["先验概率", "贝叶斯更新", "后验条件"],
                 ["bayesian", "probability_update"]),
    # 6. 宏观+中观
    KnowledgeRef("宏观中观", "宏观中观分析体系", "Irsads5j1ogY0Yxi5jbc4ozEnFe",
                 ["E33", "E46", "E85"], ["宏观四象限", "美林时钟", "信用周期"],
                 ["macro", "cycle", "regime"]),
    # 7. 风险/塔勒布
    KnowledgeRef("风险管理", "风险管理与塔勒布", "SFk5dIZmzoQHy6x8NucchU4gn1b",
                 ["E111"], ["尾部风险", "反脆弱", "杠铃策略"],
                 ["risk", "tail_risk", "antifragile"]),
    # 8. 情绪/择时
    KnowledgeRef("择时框架", "情绪周期与择时", "J52odsN5aoOOiUxM4Pbc3MF6nUf",
                 ["E128"], ["情绪钟摆", "拥挤度", "逆向指标"],
                 ["timing", "sentiment", "contrarian"]),
    # 9. 新坐标/五层蛋糕
    KnowledgeRef("新坐标体系", "新坐标与五层蛋糕", "XtC7dPTYloa4VOxfMHQcoDRVnBc",
                 ["E131", "E155"], ["新坐标", "五层蛋糕", "产业链升级"],
                 ["value_chain", "upgrade", "positioning"]),
    # 10. 不为清单/段永平
    KnowledgeRef("不为清单", "段永平投资体系", "JRmAdoHfUo2OIpxYE2GcV2LinKh",
                 ["fastisslow"], ["不为清单", "Stop Doing List", "护城河", "能力圈"],
                 ["stop_list", "moat", "circle_of_competence"]),
    # 11. 中观四层次详解
    KnowledgeRef("中观四层次", "中观四层次分析详解", "Qx2GdTq5IoqgAYxh1kCcEIEJnZh",
                 ["E7", "E84"], ["要素驱动→效率驱动→创新驱动→资本驱动",
                                "利润池迁移", "产业升级路径"],
                 ["chain_analysis", "upgrade", "positioning"]),
    # 12. 新易盛/光模块
    KnowledgeRef("光模块产业链", "光模块深度分析", "YosrdscCroax09xHX5LcPOK6nHf",
                 ["E90", "E105", "E140"], ["光模块", "数通市场", "CPO/LPO", "硅光"],
                 ["chain_specific", "optical"]),
    # 13. 新能源/锂电
    KnowledgeRef("新能源产业链", "新能源与锂电分析", "LZG3dsqQsoqGVOxtPGZcbcm6nXe",
                 ["E50", "E78", "E115"], ["锂电", "光伏", "储能", "逆变器"],
                 ["chain_specific", "new_energy", "ev"]),
]

# 方法论引用
METHODOLOGY_REFS: list[MethodologyRef] = [
    MethodologyRef("dcf", "估值方法", ["E68", "E124"],
                   ["FCF两朵花: 经营FCF+投资FCF",
                    "DCF三情景: 基准/乐观/悲观",
                    "永续增长率敏感性分析"],
                   ["all"]),
    MethodologyRef("kelly", "仓位管理", ["E153"],
                   ["f* = (bp - q)/b",
                    "半凯利 = f* × 0.5",
                    "凯利只适用于独立重复博弈"],
                   ["all"]),
    MethodologyRef("nick", "决策框架", ["E81"],
                   ["紧急: 现在不做会错过吗",
                    "趋势: 方向向上还是向下",
                    "共识: 市场主流观点是什么",
                    "拥挤: 这笔交易拥挤吗"],
                   ["all"]),
    MethodologyRef("bayers", "贝叶斯更新", ["E30", "E77"],
                   ["先验概率: 基于历史的基准概率",
                    "似然比: 新证据的权重",
                    "后验概率: 更新后的判断"],
                   ["all"]),
    MethodologyRef("chain", "产业链分析", ["E7", "E84", "E94", "E131"],
                   ["四层次: 要素→效率→创新→资本",
                    "Perez新坐标: 爆发→狂热→协同→成熟",
                    "利润池: 追踪利润在整个链的分布"],
                   ["all"]),
    MethodologyRef("risk", "风险管理", ["E111"],
                   ["杠铃策略: 90%安全+10%高风险",
                    "尾部风险对冲: 小仓位高赔率",
                    "止损纪律: -8%硬止损, -12%回落止盈"],
                   ["all"]),
]


class KnowledgeBase:
    """面基知识库查询引擎"""

    def __init__(self):
        self._knowledge = {k.title.lower(): k for k in KNOWLEDGE_BASE}
        self._methods = {m.method.lower(): m for m in METHODOLOGY_REFS}

    def get_doc_tokens(self) -> list[str]:
        """返回所有飞书文档 token"""
        return [k.doc_token for k in KNOWLEDGE_BASE]

    def query_chain(self, keyword: str) -> list[KnowledgeRef]:
        """按关键词查询产业链相关知识"""
        keyword = keyword.lower()
        results = []
        for k in KNOWLEDGE_BASE:
            if any(keyword in c.lower() for c in k.concepts):
                results.append(k)
            elif any(keyword in t.lower() for t in k.relevance):
                results.append(k)
            elif keyword in k.topic.lower() or keyword in k.title.lower():
                results.append(k)
        return results

    def get_methodology(self, method: str) -> Optional[MethodologyRef]:
        """获取某个方法论引用"""
        return self._methods.get(method.lower())

    def get_chain_section(self, section_title: str) -> list[KnowledgeRef]:
        """为日报/研报中某节生成引用"""
        refs = self.query_chain(section_title)
        if refs:
            return refs
        # fallback: 按relevance标签
        for k in KNOWLEDGE_BASE:
            if section_title in k.relevance:
                refs.append(k)
        return refs

    def format_refs_for_report(self, refs: list[KnowledgeRef]) -> str:
        """格式化为报告可插入的引用文字"""
        if not refs:
            return ""
        lines = ["📚 面基知识引用:"]
        seen = set()
        for r in refs:
            if r.title not in seen:
                seen.add(r.title)
                episodes = ", ".join(r.episodes)
                concepts = "、".join(r.concepts[:4])
                lines.append(f"  • {r.title} (第{episodes}期) — {concepts}")
        return "\n".join(lines)

    def enrich_analysis(self, analysis_text: str, tags: list[str]) -> str:
        """给分析文本追加知识引用"""
        all_refs = []
        for tag in tags:
            refs = self.query_chain(tag)
            all_refs.extend(refs)
        # 去重
        seen = set()
        unique_refs = []
        for r in all_refs:
            if r.title not in seen:
                seen.add(r.title)
                unique_refs.append(r)
        if unique_refs:
            ref_text = self.format_refs_for_report(unique_refs)
            return f"{analysis_text}\n\n{ref_text}"
        return analysis_text


# 全局单例
_KB: Optional[KnowledgeBase] = None


def get_kb() -> KnowledgeBase:
    global _KB
    if _KB is None:
        _KB = KnowledgeBase()
    return _KB


def get_relevant_knowledge(tags: list[str]) -> list[KnowledgeRef]:
    """快速查询知识引用"""
    return get_kb().query_chain(" ".join(tags)) if tags else []


if __name__ == "__main__":
    import json
    kb = KnowledgeBase()

    # 测试查询
    for keyword in ["光模块", "DCF", "仓位", "贝叶斯", "产业链"]:
        refs = kb.query_chain(keyword)
        print(f"\n[{keyword}] {len(refs)}条引用:")
        for r in refs:
            print(f"  {r.title} (第{', '.join(r.episodes)}期): {'/'.join(r.concepts[:3])}")

    # 测试方法论
    for method in ["dcf", "kelly", "nick", "bayers", "chain", "risk"]:
        m = kb.get_methodology(method)
        if m:
            print(f"\n[{method}] {m.topic}: {m.key_points[0]}")
