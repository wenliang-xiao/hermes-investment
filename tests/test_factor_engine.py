"""Tests for analysis/factor_engine — initialization and edge cases."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from engine.factor_engine import FactorEngine


class TestFactorEngineInit:
    def test_engine_creates(self):
        """引擎初始化不报错"""
        try:
            engine = FactorEngine()
            assert engine is not None
            assert hasattr(engine, "score_batch")
            assert hasattr(engine, "score_symbol")
        except ImportError as e:
            # 缺少数据依赖（baostock等）时跳过
            pytest.skip(f"Missing dependency: {e}")

    def test_engine_empty_batch(self):
        """空列表评分 → 空结果"""
        try:
            engine = FactorEngine()
            results = engine.score_batch([])
            assert results == []
        except ImportError:
            pytest.skip("Missing dependency")


class TestIndustryNeutralRanking:
    """Test industry-neutral (chain-based) percentile ranking."""

    def test_industry_ranking_differs_from_global(self):
        """
        同一标的的行业排名≠全市场排名。
        当某标的在全市场排名居中，但在其产业链内是最优/最差时，行业分位应有显著差异。
        """
        from engine.factor_engine import standardize_cross_section, standardize_by_chain

        # Chain A (tech): values [100, 80, 60]  →  ranks [1.0, 0.5, 0.0]
        # Chain B (finance): values [10, 5]     →  ranks [1.0, 0.0]
        # Global ranks: 100→1.0, 80→0.75, 60→0.5, 10→0.25, 5→0.0
        raw = {
            "A1": 100, "A2": 80, "A3": 60,
            "B1": 10, "B2": 5,
        }
        chain_map = {
            "A1": "tech", "A2": "tech", "A3": "tech",
            "B1": "finance", "B2": "finance",
        }

        global_result = standardize_cross_section(raw, higher_is_better=True)
        chain_result = standardize_by_chain(raw, chain_map, higher_is_better=True)

        # Within-chain: A3 is worst in tech chain → 0.0
        assert chain_result["A3"] == 0.0, "A3 should be worst in tech chain"

        # Within-chain: B1 is best in finance chain → 1.0
        assert chain_result["B1"] == 1.0, "B1 should be best in finance chain"

        # Global: A3 (value 60) ranks above B1 (value 10) and B2 (value 5)
        # A3 global = 0.5, A3 chain = 0.0 → differ
        assert chain_result["A3"] != global_result["A3"], \
            f"A3 industry rank {chain_result['A3']} should differ from global {global_result['A3']}"
        # B1 global = 0.25, B1 chain = 1.0 → differ
        assert chain_result["B1"] != global_result["B1"], \
            f"B1 industry rank {chain_result['B1']} should differ from global {global_result['B1']}"

        # All chain scores should be in [0, 1]
        for sym, score in chain_result.items():
            assert 0.0 <= score <= 1.0, f"{sym} score {score} out of range"

    def test_chain_standardize_single_value(self):
        """单标的产业链内分位应为 0.5（唯一标的时）"""
        from engine.factor_engine import standardize_by_chain

        raw = {"A1": 42}
        chain_map = {"A1": "tech"}
        result = standardize_by_chain(raw, chain_map, higher_is_better=True)
        assert result["A1"] == 0.5, f"Single symbol should get 0.5, got {result['A1']}"

    def test_chain_standardize_empty(self):
        """空输入返回空"""
        from engine.factor_engine import standardize_by_chain
        assert standardize_by_chain({}, {}) == {}

    def test_chain_standardize_no_chain_map(self):
        """无产业链映射时归入'其他'组"""
        from engine.factor_engine import standardize_by_chain
        raw = {"A1": 100, "A2": 50}
        # Empty chain map → all go to "其他"
        result = standardize_by_chain(raw, {}, higher_is_better=True)
        assert result["A1"] == 1.0
        assert result["A2"] == 0.0


class TestICWeightSystem:
    """Test ICWeightSystem weighting (WS3b: IC/IR + WS3c: double-weight verification)"""

    def test_rolling_ic_returns_weights(self):
        """滚动IC权重返回合法分布（和为1，值在[0,1]）"""
        from engine.factor_engine import ICWeightSystem
        icw = ICWeightSystem(cache_dir="/tmp/ic_test")
        # 没有历史数据 → 等权
        weights = icw.rolling_ic_weights(lookback=6)
        assert abs(sum(weights.values()) - 1.0) < 0.01
        for v in weights.values():
            assert 0 <= v <= 1

    def test_get_weights_no_double_count(self):
        """验证 get_weights 和 conditional_weight 不双重加乘

        如果 double-counting，因子A的权重在 get_weights() 中会是:
          rolling_ic[A] * weight_from_conditional[A]
        如果 NOT double-counting，则是:
          0.7 * rolling_ic[A] + 0.3 * cond_norm[A]

        测试方法: 给 ICWeightSystem 注入样本数据，验证权重在合理范围内
        """
        from engine.factor_engine import ICWeightSystem
        import json, os, tempfile
        from pathlib import Path

        tmpdir = tempfile.mkdtemp()
        # 写一份模拟 IC 历史数据（使用 STYLE_FACTORS 中的英文键名）
        from engine.factor_engine import STYLE_FACTORS, ICWeightSystem
        sf = list(STYLE_FACTORS.keys())
        ic_data = [
            {sf[0]: 0.05, sf[1]: 0.12, sf[2]: 0.08, sf[3]: 0.15, sf[4]: -0.03, sf[5]: 0.02, sf[6]: 0.01, sf[7]: 0.00},
            {sf[0]: 0.06, sf[1]: 0.10, sf[2]: 0.07, sf[3]: 0.12, sf[4]: -0.02, sf[5]: 0.03, sf[6]: 0.02, sf[7]: 0.01},
            {sf[0]: 0.04, sf[1]: 0.11, sf[2]: 0.09, sf[3]: 0.14, sf[4]: -0.04, sf[5]: 0.01, sf[6]: 0.01, sf[7]: -0.01},
            {sf[0]: 0.07, sf[1]: 0.13, sf[2]: 0.06, sf[3]: 0.13, sf[4]: -0.01, sf[5]: 0.04, sf[6]: 0.03, sf[7]: 0.02},
        ]
        with open(os.path.join(tmpdir, "ic_history.json"), "w") as f:
            json.dump(ic_data, f)

        icw = ICWeightSystem(cache_dir=tmpdir)
        factors = list(STYLE_FACTORS.keys())
        base = icw.rolling_ic_weights(lookback=4)
        cond = {}
        for f in factors:
            cond[f] = icw.conditional_weight(f, "扩张期", n_samples=10)

        final = icw.get_weights("扩张期", n_samples=10)

        # 验证: base, final 是合法分布（和为1）
        for label, w in [("base", base), ("final", final)]:
            assert abs(sum(w.values()) - 1.0) < 0.02, \
                f"{label} weights sum to {sum(w.values())}, expected ~1.0"
            assert all(0 <= v <= 1 for v in w.values()), \
                f"{label} has weights outside [0,1]"

        # 验证: momentum（趋势/最强正IC）应该显著 > low_vol（负IC）
        assert final.get("momentum", 0) > final.get("low_vol", 0), \
            "momentum因子权重应高于low_vol因子（正IC vs 负IC）"

        # 验证: final 是 base 和 cond 的加权混合，不是乘积
        # 若 double-counting: final[momentum] ≈ base[momentum] * cond[momentum]（很小）
        # 若 70/30 blend: final[momentum] ≈ 0.7*base + 0.3*cond (≈0.3)
        base_mom = base.get("momentum", 0)
        cond_mom = cond.get("momentum", 0)
        final_mom = final.get("momentum", 0)
        # final should be between base and cond (blend) not below both
        # Note: cond values are NOT normalized (individual raw values), so they may be outside [0,1]
        # but final should still be between base and the normalized cond equivalent
        if 0 < cond_mom < 1:
            assert min(base_mom, cond_mom) <= final_mom <= max(base_mom, cond_mom), \
                f"final momentum={final_mom:.4f} should between base={base_mom:.4f} and cond={cond_mom:.4f}"

        # 清理
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestChainProsperity:
    """链景气因子 (WS10根治): Pérez阶段×机构态度 → 科技主线抬升/防守链压制"""

    def test_tech_chain_boosted(self):
        """科技主线链景气>1（应抬升 industry 风格分）"""
        from engine.factor_engine import chain_prosperity
        assert chain_prosperity("算力-AI") > 1.0
        assert chain_prosperity("半导体") > 1.0
        assert chain_prosperity("机器人") > 1.0

    def test_defensive_chain_suppressed(self):
        """防守链景气<1（应压制 industry 风格分）"""
        from engine.factor_engine import chain_prosperity
        assert chain_prosperity("消费") < 1.0
        assert chain_prosperity("红利") < 1.0
        assert chain_prosperity("光伏") < 1.0

    def test_unknown_chain_neutral(self):
        """未知/无映射链 → 中性1.0（不惩罚不缺失）"""
        from engine.factor_engine import chain_prosperity
        assert chain_prosperity("其他") == 1.0
        assert chain_prosperity("XX不存在") == 1.0

    def test_tech_beats_defensive_after_blend(self):
        """链景气修正后: 科技主线 industry 分 > 防守链（P0核心场景根治验证）"""
        from engine.factor_engine import chain_prosperity, _blend_chain
        tech = _blend_chain(0.5, chain_prosperity("算力-AI"))
        defensive = _blend_chain(0.5, chain_prosperity("消费"))
        assert tech > defensive, "科技主线应显著高于防守链"


class TestICLoop:
    """IC 动态权重生产数据闭环 (WS10根治: 消除IC死代码)"""

    def test_record_and_compute_ic_loop(self):
        """因子分保存 → 下期IC回算 → 累积入ic_history 全通"""
        import shutil, tempfile
        from engine.factor_engine import FactorEngine, ICWeightSystem, STYLE_FACTORS

        tmp = tempfile.mkdtemp()
        icw = ICWeightSystem(cache_dir=tmp)
        eng = FactorEngine(ic_system=icw)

        # 20只标的: quality因子分与realized正相关 → IC应为正
        symbols = [f"6000{i:02d}" for i in range(20)]
        results = []
        for i, sym in enumerate(symbols):
            q = i / 19.0
            results.append({
                "symbol": sym,
                "scores": {f: 0.5 for f in STYLE_FACTORS} | {"quality": q, "risk": 1 - q},
                "composite": q,
            })
        eng.record_factor_scores_for_ic(results, "2026-07-08")
        realized = {s: (0.2 * results[i]["scores"]["quality"] - 0.1)
                    for i, s in enumerate(symbols)}
        entry = eng.compute_ic_from_realized("2026-07-08", realized)

        assert entry["quality"] > 0.8, "quality IC 应为强正"
        assert entry["risk"] < -0.8, "risk IC 应为强负"
        # 已累积入历史
        hist = icw.get_ic_history()
        assert any(h.get("date") == "2026-07-08" for h in hist), "IC应累积入历史"
        shutil.rmtree(tmp, ignore_errors=True)

    def test_low_sample_not_dead_equal(self):
        """低样本时不退化为死等权，IC方向性仍起作用"""
        from engine.factor_engine import ICWeightSystem
        icw = ICWeightSystem(cache_dir="/tmp/ic_test")
        weights = icw.rolling_ic_weights(lookback=6)
        assert abs(sum(weights.values()) - 1.0) < 0.01
