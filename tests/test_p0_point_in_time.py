"""P0-1 时点评分 — 财务 point-in-time (2026-09-01)

financial_report_available_date: 报告期 → A股法定披露截止日映射。
这是消除"用未来财报回测过去"前视偏差的数据层基础。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_financial_report_available_date_mapping():
    from domain.financial_calendar import financial_report_available_date as f
    assert f("2024Q1") == "2024-04-30"  # 一季报 4/30
    assert f("2024Q2") == "2024-08-31"  # 半年报 8/31
    assert f("2024Q3") == "2024-10-31"  # 三季报 10/31
    assert f("2024Q4") == "2025-04-30"  # 年报次年 4/30


def test_financial_report_available_date_parse_failure():
    from domain.financial_calendar import financial_report_available_date as f
    assert f("bad") == "bad"  # 无法解析时原样返回, 不崩


def test_financial_history_asof_filter_logic():
    """as_of 过滤逻辑: 只保留「披露截止日 <= as_of」的财报。"""
    from domain.financial_calendar import financial_report_available_date as f
    periods = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    as_of = "2024-06-01"
    # 2024Q1(4/30) 已披露可见; 2024Q2(8/31)/Q3/Q4 尚未披露
    visible = [p for p in periods if f(p) <= as_of]
    assert visible == ["2024Q1"], f"as_of={as_of} 应只见 Q1, got {visible}"


def test_financial_history_asof_year_end():
    """年末视角: 年报(次年4/30)尚未披露, 只见当年 Q1/Q2/Q3。"""
    from domain.financial_calendar import financial_report_available_date as f
    periods = ["2024Q1", "2024Q2", "2024Q3", "2024Q4"]
    as_of = "2024-12-31"
    visible = [p for p in periods if f(p) <= as_of]
    assert visible == ["2024Q1", "2024Q2", "2024Q3"], f"got {visible}"


def test_ic_history_asof_filter(tmp_path):
    """IC 权重前视消除: as_of 时只读 date <= as_of 的 IC 记录。"""
    import json
    from engine.factor_engine import ICWeightSystem
    cache_dir = tmp_path / "ic_cache"
    cache_dir.mkdir()
    (cache_dir / "ic_history.json").write_text(json.dumps([
        {"date": "2024-01-01", "quality": 0.5},
        {"date": "2024-06-01", "quality": 0.6},
        {"date": "2025-01-01", "quality": 0.7},
    ]))
    icw = ICWeightSystem(cache_dir=str(cache_dir))
    icw.as_of = None
    assert len(icw.get_ic_history()) == 3, "无 as_of 应返回全部"
    icw.as_of = "2024-06-30"
    hist = icw.get_ic_history()
    assert [h["date"] for h in hist] == ["2024-01-01", "2024-06-01"], f"got {[h['date'] for h in hist]}"


def test_get_fin_asof_uses_financial_history(monkeypatch):
    """as_of 模式下 _get_fin 从财务历史映射字段(而非当前财报), 消除财务前视。"""
    import sys
    import types
    from engine.factor_engine import FactorEngine
    # mock data.data_layer 模块(避免触发其 investment_system import)
    fake_dl = types.ModuleType("data.data_layer")
    fake_dl.get_financial_history = lambda symbol, quarters=4, as_of_date=None: [{
        "period": "2024Q1", "roe": 17.9, "gross_margin": 89.5,
        "net_margin": 52.0, "debt_ratio": 15.0, "profit_growth": 8.0,
    }]
    monkeypatch.setitem(sys.modules, "data.data_layer", fake_dl)
    engine = FactorEngine()
    engine.as_of = "2024-06-30"
    fin = engine._get_fin("600519")
    assert fin.get("净资产收益率") == 17.9
    assert fin.get("毛利率") == 89.5
    assert fin.get("净利率") == 52.0
    assert fin.get("资产负债率") == 15.0
    assert fin.get("净利润同比增长率") == 8.0


def test_financial_report_bs_fallback_uses_field_names():
    """get_financial_report 的 baostock fallback 用字段名提取, 非索引硬编码(修复字段错位)。"""
    from pathlib import Path
    src_path = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))) / "data" / "data_layer.py"
    src = src_path.read_text(encoding="utf-8")
    # 旧的索引错位写法: (3, "净资产收益率"), (4, "营业收入同比增长率"), (4, "毛利率")
    assert 'for idx, key in [(3, "净资产收益率")' not in src, "仍有旧索引错位(growth_data)"
    assert 'for idx, key in [(4, "毛利率")' not in src, "仍有旧索引错位(dupont_data)"
    # 新的字段名提取
    assert 'roeAvg' in src, "应用字段名 roeAvg 提取 ROE"
    assert 'gpMargin' in src, "应用字段名 gpMargin 提取毛利率"
    assert 'YOYNI' in src, "应用字段名 YOYNI 提取净利增速"
