"""
analysis/stop_list.py — 段永平不为清单过滤框架

三段式选股的第二步：因子扫描 → [不为清单过滤] → 深度研报

段永平核心原则（从 stop doing list 提取）:
1. 不做空
2. 不借钱（不加杠杆）
3. 不做不懂的事
4. 不投没有护城河的企业
5. 不投商业模式差的企业（苦生意）
6. 不投高杠杆（高负债率）
7. 不投管理层不诚信的
8. 不投ROE长期低于15%的
9. 不投机（不用短期资金投长期资产）
10. 不投重资产低回报（资本密集型但ROIC<WACC）

用法:
    from engine.stop_list import StopListFilter, DEFAULT_RULES

    filter = StopListFilter()
    passed, reasons = filter.apply(symbol="300502", name="新易盛",
                                    roe=20.5, debt_ratio=25.0, gross_margin=45.0,
                                    asset_heavy=False)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class StopListRule:
    """一条不为清单规则"""
    name: str          # 规则名，如 "高负债"
    description: str   # 段永平原话或解释
    check: Callable[[dict], tuple[bool, str]]  # (pass_or_fail, reason)
    severity: str = "medium"  # high = 一票否决, medium = 警告, low = 提示


# ─── 内置规则 ───

def _check_no_short(data: dict) -> tuple[bool, str]:
    """规则1: 不做空（代码层面保持）"""
    direction = data.get("direction", "long")
    if direction == "short":
        return False, "❌ 不做空: 段永平原则禁止做空"
    return True, "✅ 做多方向"


def _check_no_leverage(data: dict) -> tuple[bool, str]:
    """规则2: 不借钱（不加杠杆）"""
    strategy = data.get("strategy", "")
    if "margin" in strategy.lower() or "lever" in strategy.lower():
        return False, "❌ 不借钱: 段永平'不借钱买股票'"
    return True, "✅ 无杠杆"


def _check_roe(data: dict) -> tuple[bool, str]:
    """规则3: ROE长期不低于15%"""
    roe = data.get("roe")
    if roe is None:
        return True, "⚠️ ROE未知, 需确认"
    if roe < 10:
        return False, f"❌ ROE={roe:.1f}% < 10%, 段永平原则不投低ROE企业"
    elif roe < 15:
        return False, f"⚠️ ROE={roe:.1f}% < 15%, 段永平建议'长期ROE低于15%不投'"
    return True, f"✅ ROE={roe:.1f}% ≥ 15%"


def _check_debt_ratio(data: dict) -> tuple[bool, str]:
    """规则4: 不投高杠杆（高负债率）"""
    debt = data.get("debt_ratio")
    if debt is None:
        return True, "⚠️ 负债率未知, 需确认"
    if debt > 70:
        return False, f"❌ 负债率{debt:.0f}% > 70%, 段永平原则'不投高杠杆企业'"
    elif debt > 50:
        return False, f"⚠️ 负债率{debt:.0f}% > 50%, 偏高需谨慎"
    return True, f"✅ 负债率{debt:.0f}% ≤ 50%"


def _check_gross_margin(data: dict) -> tuple[bool, str]:
    """规则5: 不投商业模式差（低毛利=苦生意）"""
    gm = data.get("gross_margin")
    if gm is None:
        return True, "⚠️ 毛利率未知, 需确认"
    if gm < 20:
        return False, f"❌ 毛利率{gm:.1f}% < 20%, 段永平'没有护城河的苦生意'"
    elif gm < 30:
        return False, f"⚠️ 毛利率{gm:.1f}% < 30%, 商业模式偏弱"
    return True, f"✅ 毛利率{gm:.1f}% ≥ 30%"


def _check_moat(data: dict) -> tuple[bool, str]:
    """规则6: 护城河检查"""
    moat = data.get("moat_score")  # 0-10, 用户/系统自评
    if moat is None:
        return True, "⚠️ 护城河评分未知"
    if moat < 3:
        return False, f"❌ 护城河评分{moat}/10, 段永平'没有护城河的企业不值得投资'"
    elif moat < 6:
        return False, f"⚠️ 护城河评分{moat}/10, 偏弱"
    return True, f"✅ 护城河评分{moat}/10"


def _check_asset_heavy(data: dict) -> tuple[bool, str]:
    """规则7: 不投重资产低回报"""
    heavy = data.get("asset_heavy")
    if heavy is None:
        return True, "⚠️ 资产轻重未知"
    roic = data.get("roic", 0)
    if heavy and roic and roic < 10:
        return False, f"❌ 重资产+ROIC{roic:.1f}% < 10%, 段永平'资本回报率低的生意不做'"
    elif heavy:
        return False, f"⚠️ 重资产企业, ROIC={roic:.1f}%, 需确认资本效率"
    return True, "✅ 轻资产模式"


def _check_management(data: dict) -> tuple[bool, str]:
    """规则8: 管理层诚信"""
    mgmt = data.get("management_score")  # 0-10
    if mgmt is None:
        return True, "⚠️ 管理层评分未知"
    if mgmt < 4:
        return False, f"❌ 管理层评分{mgmt}/10, 段永平'不投不诚信的管理层'"
    return True, f"✅ 管理层评分{mgmt}/10"


def _check_cash_flow(data: dict) -> tuple[bool, str]:
    """规则9: 自由现金流是否持续为正"""
    fcf = data.get("fcf_positive")
    if fcf is None:
        return True, "⚠️ 自由现金流未知"
    if not fcf:
        return False, "❌ 自由现金流持续为负, 段永平'没有自由现金流的生意不投'"
    return True, "✅ 自由现金流正数"


def _check_understandable(data: dict) -> tuple[bool, str]:
    """规则10: 是否在自己能力圈内"""
    understand = data.get("understand_score")  # 0-10
    if understand is None:
        return True, "⚠️ 能力圈评分未知（建议深入理解业务后再投）"
    if understand < 5:
        return False, f"❌ 能力圈评分{understand}/10, 段永平'不投自己不懂的东西'"
    return True, f"✅ 能力圈评分{understand}/10"


# ─── 默认规则集 ───

DEFAULT_RULES: list[StopListRule] = [
    StopListRule("不做空", "不投做空策略", _check_no_short, "high"),
    StopListRule("不加杠杆", "不借钱买股票", _check_no_leverage, "high"),
    StopListRule("ROE标准", "长期ROE不低于15%", _check_roe, "high"),
    StopListRule("负债率", "不投高杠杆企业", _check_debt_ratio, "high"),
    StopListRule("毛利率", "不投苦生意(低毛利)", _check_gross_margin, "high"),
    StopListRule("护城河", "不投没有护城河的企业", _check_moat, "high"),
    StopListRule("资产轻重", "不投重资产低回报", _check_asset_heavy, "medium"),
    StopListRule("管理层", "管理层诚信", _check_management, "high"),
    StopListRule("自由现金流", "自由现金流为正", _check_cash_flow, "medium"),
    StopListRule("能力圈", "不做不懂的事", _check_understandable, "high"),
]


class StopListFilter:
    """不为清单过滤器

    对传入标的运行所有规则，输出:
    - passed: bool (所有 high 规则通过)
    - rejected_by: 被拒绝的规则
    - warnings: 警告性规则
    - detail: 逐条详细结果
    """

    def __init__(self, rules: list[StopListRule] | None = None):
        self.rules = rules or DEFAULT_RULES

    def apply(self, data: dict) -> dict:
        """运行不为清单过滤

        Args:
            data: 标的字典, 支持字段见各规则

        Returns:
            {
                "symbol": str,
                "name": str,
                "passed": bool,
                "rejected_by": [规则名],
                "warnings": [规则名],
                "high_passed": bool,  # 一票否决全通过
                "details": [{"rule", "result", "detail"}, ...],
                "score_adjustment": float,  # 分数调整(-2.0 ~ +0.0)
            }
        """
        symbol = data.get("symbol", "?")
        name = data.get("name", symbol)

        details = []
        rejected_by = []
        warnings_list = []
        high_passed = True

        for rule in self.rules:
            try:
                passed, detail = rule.check(data)
            except Exception as e:
                passed, detail = False, f"检查异常: {e}"

            details.append({
                "rule": rule.name,
                "description": rule.description,
                "severity": rule.severity,
                "result": "✅" if passed else ("⚠️" if rule.severity != "high" else "❌"),
                "detail": detail,
            })

            if not passed:
                if rule.severity == "high":
                    rejected_by.append(rule.name)
                    high_passed = False
                else:
                    warnings_list.append(rule.name)

        # 分数调整: 每项high失败 -0.5, medium -0.2
        adjustment = -len(rejected_by) * 0.5 - len(warnings_list) * 0.2
        adjustment = max(-2.0, adjustment)  # 最多扣2分

        return {
            "symbol": symbol,
            "name": name,
            "passed": high_passed and len(rejected_by) == 0,
            "rejected_by": rejected_by,
            "warnings": warnings_list,
            "high_passed": high_passed,
            "score_adjustment": round(adjustment, 2),
            "n_rules_passed": sum(1 for d in details if d["result"] == "✅"),
            "n_rules_total": len(self.rules),
            "details": details,
            "verdict": self._verdict(high_passed, len(rejected_by), len(warnings_list)),
        }

    def _verdict(self, high_passed: bool, n_reject: int, n_warn: int) -> str:
        if not high_passed:
            return f"🔴 不为清单拦截 — {n_reject}项一票否决, 不予关注"
        elif n_warn > 0:
            return f"🟡 通过一票否决但有{n_warn}项警告, 谨慎评估"
        return "🟢 通过不为清单, 进入深度研报阶段"

    def filter_candidates(self, candidates: list[dict]) -> list[dict]:
        """批量过滤候选池

        Args:
            candidates: [{"symbol", "name", "score", ...}, ...]

        Returns:
            通过不为清单的候选（按调整后分数排序）
        """
        results = []
        for cand in candidates:
            result = self.apply(cand)
            if result["passed"]:
                adjusted_score = cand.get("score", 5.0) + result["score_adjustment"]
                cand["stop_list_passed"] = True
                cand["stop_list_adjustment"] = result["score_adjustment"]
                cand["adjusted_score"] = max(0, round(adjusted_score, 2))
                cand["stop_list_detail"] = result
                results.append(cand)

        results.sort(key=lambda x: x.get("adjusted_score", 0), reverse=True)
        return results


# ─── Quick test ───
if __name__ == "__main__":
    import json
    f = StopListFilter()

    # 测试通过标的
    test_pass = {
        "symbol": "300502", "name": "新易盛",
        "roe": 22.5, "debt_ratio": 25.0, "gross_margin": 45.0,
        "moat_score": 8, "asset_heavy": False, "roic": 18.0,
        "management_score": 7, "fcf_positive": True,
        "understand_score": 8, "score": 5.5,
    }
    r = f.apply(test_pass)
    print(f"[通过测试] {test_pass['symbol']}({test_pass['name']}): {r['verdict']}")
    print(f"  分数调整: {r['score_adjustment']}, 规则通过: {r['n_rules_passed']}/{r['n_rules_total']}")

    # 测试拒绝标的
    test_fail = {
        "symbol": "600123", "name": "高杠杆煤企",
        "roe": 8.0, "debt_ratio": 75.0, "gross_margin": 15.0,
        "moat_score": 2, "asset_heavy": True, "roic": 5.0,
        "management_score": 3, "fcf_positive": False,
        "understand_score": 4, "score": 4.8,
    }
    r2 = f.apply(test_fail)
    print(f"\n[拒绝测试] {test_fail['symbol']}({test_fail['name']}): {r2['verdict']}")
    print(f"  拦截规则: {r2['rejected_by']}")
    print(f"  分数调整: {r2['score_adjustment']}")
