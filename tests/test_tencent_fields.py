"""腾讯行情字段解析修复测试 (2026-09-02)

锁定: ① volume 单位转换(沪深"手"×100→"股", 科创板不转); ② pb 字段提取([46])。
依据: 知乎帖子实测腾讯 qt.gtimg 字段索引 39=PE/43=振幅/46=PB, 成交量单位是"手"。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _mock_tencent_text(sym):
    """构造腾讯 qt.gtimg 返回(GBK格式, 字段索引对齐真实响应)。"""
    # 真实字段: [3]=价 [6]=成交量(手) [32]=涨跌幅 [37]=成交额(万) [38]=换手率 [39]=PE [46]=PB
    fields = [""] * 60
    fields[1] = "贵州茅台"
    fields[3] = "1295.12"
    fields[6] = "11700"      # 成交量(手)
    fields[31] = "-4.44"
    fields[32] = "-0.34"
    fields[37] = "151686"    # 成交额(万)
    fields[38] = "0.09"
    fields[39] = "19.88"     # PE-TTM
    fields[46] = "6.44"      # PB
    return f'v_sh{sym}="' + "~".join(fields) + '~"'


def test_volume_unit_converts_hands_to_shares(monkeypatch):
    """沪深主板 volume 单位是"手", 应 ×100 转"股"。"""
    import data.sources.akshare_source as src

    class FakeResp:
        text = _mock_tencent_text("600519")
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp())
    monkeypatch.setattr(src.time, "time", lambda: 1000.0)  # 绕过缓存
    src._rt_cache.clear()
    rt = src.get_rt_em("600519")
    # 11700手 × 100 = 1,170,000 股
    assert rt["volume"] == 11700 * 100, f"沪深 volume 应×100转股, got {rt['volume']}"


def test_volume_unit_kcb_not_converted(monkeypatch):
    """科创板(688) volume 单位已是"股", 不应 ×100。"""
    import data.sources.akshare_source as src

    class FakeResp:
        text = _mock_tencent_text("688256")
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp())
    monkeypatch.setattr(src.time, "time", lambda: 2000.0)
    src._rt_cache.clear()
    rt = src.get_rt_em("688256")
    assert rt["volume"] == 11700, f"科创板 volume 不应×100, got {rt['volume']}"


def test_pb_field_extracted(monkeypatch):
    """腾讯 [46]=PB 应被提取(修复 PB 因子缺失)。"""
    import data.sources.akshare_source as src

    class FakeResp:
        text = _mock_tencent_text("600519")
    monkeypatch.setattr("requests.get", lambda url, timeout: FakeResp())
    monkeypatch.setattr(src.time, "time", lambda: 3000.0)
    src._rt_cache.clear()
    rt = src.get_rt_em("600519")
    assert rt["pb"] == 6.44, f"应提取 pb=[46]=6.44, got {rt.get('pb')}"
    assert rt["pe"] == 19.88, f"pe=[39]=19.88, got {rt.get('pe')}"
