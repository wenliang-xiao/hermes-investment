#!/usr/bin/env python3
"""
中美脱钩·挖掘通道 v2.0
================================
四路扫描：
  1. 🇭🇰 港股地缘折价 — 中概回归/港股科技，PE打3-5折
  2. 🇺🇸 美股脱钩受益 — CHIPS Act/近岸制造/供应链安全 $1-50B 中小票
  3. 🇨🇳 A股国产替代 — 自主可控/内循环/进口替代（半导体/信创/军工/稀土）
  4. 🌉 夹缝红利 — 两边都有业务的桥梁型公司

面基引用: E116(逆风试金石) E131(新宏观坐标) E94(Perez五阶段)
"""
import sys, os, time
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from investment_system.yf_data_layer import get_factor_data, get_current_price, score_stock

# ═══════════════════════════════════
# ① 港股地缘折价
# ═══════════════════════════════════
HK_DECOUPLING_DISCOUNT = {
    "9988.HK":  {"name":"阿里巴巴","us_peer":"AMZN","us_peer_pe":35,"reason":"监管+地缘双杀，PE不足美同行1/3"},
    "0700.HK":  {"name":"腾讯控股","us_peer":"META","us_peer_pe":24,"reason":"游戏+社交垄断，大股东减持压制"},
    "9888.HK":  {"name":"百度集团","us_peer":"GOOGL","us_peer_pe":22,"reason":"AI未定价，PE~12→安全边际极高"},
    "9618.HK":  {"name":"京东集团","us_peer":"AMZN","us_peer_pe":35,"reason":"自营物流壁垒+回购，PB接近1"},
    "9999.HK":  {"name":"网易","us_peer":"EA","us_peer_pe":20,"reason":"游戏出海+暴雪回归，现金流极好"},
    "1024.HK":  {"name":"快手","us_peer":"META","us_peer_pe":24,"reason":"短视频+电商加速，盈利拐点已至"},
    "9626.HK":  {"name":"哔哩哔哩","us_peer":"YOUTUBE","us_peer_pe":30,"reason":"Z世代平台，游戏+广告三引擎"},
    "2015.HK":  {"name":"理想汽车","us_peer":"TSLA","us_peer_pe":80,"reason":"增程+纯电，盈利能力强于蔚来小鹏"},
    "9868.HK":  {"name":"小鹏汽车","us_peer":"TSLA","us_peer_pe":80,"reason":"智驾XNGP领先+MONA下沉，VW背书"},
    "0020.HK":  {"name":"商汤科技","us_peer":"NVDA","us_peer_pe":33,"reason":"AI infra+大模型，算力被低估"},
}

# ═══════════════════════════════════
# ② 美股脱钩受益
# ═══════════════════════════════════
US_DECOUPLING_BENEFIT = {
    "ONTO": {"name":"Onto Innovation","chain":"半导体设备","mkt_range":"$10-20B","thesis":"先进封装检测，CHIPS Act受益"},
    "ACLS": {"name":"Axcelis Technologies","chain":"半导体设备","mkt_range":"$5-10B","thesis":"离子注入设备，SiC+功率半导体"},
    "ICHR": {"name":"Ichor Holdings","chain":"半导体设备","mkt_range":"$1-3B","thesis":"气体/流体子系统，设备关键供应商"},
    "UCTT": {"name":"Ultra Clean Holdings","chain":"半导体设备","mkt_range":"$2-5B","thesis":"AMAT/LRCX一级子系统供应商"},
    "FORM": {"name":"FormFactor","chain":"半导体测试","mkt_range":"$3-6B","thesis":"探针卡龙头，HBM测试需求爆发"},
    "MTSI": {"name":"MACOM Technology","chain":"射频/光通信","mkt_range":"$8-12B","thesis":"数据中心光模块+国防射频"},
    "CRUS": {"name":"Cirrus Logic","chain":"消费电子芯片","mkt_range":"$5-8B","thesis":"音频芯片，苹果供应链+新品类"},
    "POWI": {"name":"Power Integrations","chain":"功率半导体","mkt_range":"$3-5B","thesis":"高效电源IC，AI数据中心电力"},
    "AMSC": {"name":"AMSC美超导","chain":"电力/电网","mkt_range":"$1-3B","thesis":"电网弹性+风电，美国本土制造"},
    "RUN":  {"name":"Sunrun","chain":"新能源","mkt_range":"$3-5B","thesis":"户用光伏+储能，利率下行受益"},
}

# ═══════════════════════════════════
# ③ A股国产替代
# ═══════════════════════════════════
A_SHARE_SELF_RELIANCE = {
    "002371.SZ": {"name":"北方华创","chain":"半导体设备","thesis":"刻蚀/薄膜/清洗/炉管四大平台，国内半导体设备绝对龙头"},
    "688012.SS": {"name":"中微公司","chain":"半导体设备","thesis":"等离子体刻蚀+MOCVD，5nm已验证，技术最接近国际水平"},
    "688126.SS": {"name":"沪硅产业","chain":"半导体材料","thesis":"300mm大硅片国产化唯一标的，全球硅片紧缺"},
    "688981.SS": {"name":"中芯国际","chain":"晶圆代工","thesis":"大陆最先进代工厂，14nm量产+7nm研发"},
    "301269.SZ": {"name":"华大九天","chain":"EDA软件","thesis":"国内EDA龙头，模拟全流程，Synopsys断供唯一选择"},
    "688256.SS": {"name":"寒武纪","chain":"AI芯片","thesis":"云端+边缘AI芯片，NVDA禁售→国产推理芯片刚需"},
    "688041.SS": {"name":"海光信息","chain":"AI芯片/CPU","thesis":"x86兼容CPU+DCU(GPGPU)，深算系列对标A100"},
    "688111.SS": {"name":"金山办公","chain":"信创/软件","thesis":"WPS国产Office替代唯一商用化，政府信创采购刚性"},
    "600893.SS": {"name":"航发动力","chain":"军工/航发","thesis":"国产航空发动机唯一主机厂，不受经济周期影响"},
    "600760.SS": {"name":"中航沈飞","chain":"军工/战机","thesis":"歼-15/16/35主机厂，装备列装加速"},
    "600111.SS": {"name":"北方稀土","chain":"稀土/战略资源","thesis":"全球最大稀土供应商，中国掌握70%+加工产能"},
    "300760.SZ": {"name":"迈瑞医疗","chain":"医疗器械","thesis":"监护/超声/体外诊断龙头，高端出海+进口替代"},
}

# ═══════════════════════════════════
# ④ 夹缝红利
# ═══════════════════════════════════
BRIDGE_COMPANIES = {
    "TSM":  {"name":"台积电","reason":"全球代工，亚利桑那+南京两边工厂，技术垄断"},
    "BABA": {"name":"阿里巴巴","reason":"云+国际电商(AliExpress)，全球布局"},
}

# ═══════════════════════════════════
# 评分引擎
# ═══════════════════════════════════

def _score_hk(name, info, us_peer_pe, reason):
    """港股折价评分"""
    pe = info.get("pe") or 20; roe = info.get("roe") or 0; earn_g = info.get("earnings_growth") or 0
    if pe > 0 and us_peer_pe > 0:
        discount = 1 - pe / us_peer_pe
        d_score = min(10, max(1, discount * 10))
    else:
        d_score = 5
    q_score = min(10, max(1, (roe or 0) * 25)) if roe else 5
    g_score = min(10, max(1, (earn_g or 0) * 50)) if earn_g else 5
    return {"name":name,"score":round(d_score*0.4+q_score*0.3+g_score*0.3,1),"pe":pe,"roe":roe,"earn_g":earn_g,"discount":f"{discount*100:.0f}%折价" if d_score>3 else "","reason":reason}

def _score_a_share(name, info, chain, thesis):
    """A股国产替代评分"""
    pe = info.get("pe") or 30; roe = info.get("roe") or 0; earn_g = info.get("earnings_growth") or 0
    q_score = min(10, max(1, (roe or 0) * 25)) if roe else 5
    g_score = min(10, max(1, (earn_g or 0) * 40)) if earn_g else 5
    p_score = 10 - min(8, max(0, (pe - 20) / 10)) if pe and pe > 0 else 5
    return {"name":name,"chain":chain,"score":round(q_score*0.30+g_score*0.35+p_score*0.15+2.0,1),"pe":pe,"roe":roe,"earn_g":earn_g,"thesis":thesis}

def scan_hk_discount():
    picks = []
    for sym, m in HK_DECOUPLING_DISCOUNT.items():
        try:
            info = get_factor_data(sym)
            if "error" in info: picks.append({"symbol":sym,"name":m["name"],"score":0,"error":info["error"]}); continue
            p = _score_hk(m["name"], info, m["us_peer_pe"], m["reason"])
            p["symbol"] = sym; p["price"] = get_current_price(sym); picks.append(p); time.sleep(0.6)
        except Exception as e: picks.append({"symbol":sym,"name":m["name"],"score":0,"error":str(e)[:80]})
    picks.sort(key=lambda x: x["score"], reverse=True); return picks

def scan_us_benefit():
    picks = []
    for sym, m in US_DECOUPLING_BENEFIT.items():
        try:
            r = score_stock(sym, m["name"]); info = get_factor_data(sym)
            if r and r.get("score",0) > 0:
                picks.append({"symbol":sym,"name":m["name"],"chain":m["chain"],"mkt_range":m["mkt_range"],
                    "score":round(r["score"],1),"pe":info.get("pe"),"roe":info.get("roe"),"thesis":m["thesis"]})
            time.sleep(0.6)
        except Exception as e: picks.append({"symbol":sym,"name":m["name"],"score":0,"error":str(e)[:80]})
    picks.sort(key=lambda x: x["score"], reverse=True); return picks

def scan_a_share_self_reliance():
    picks = []
    for sym, m in A_SHARE_SELF_RELIANCE.items():
        try:
            info = get_factor_data(sym)
            if "error" in info: picks.append({"symbol":sym,"name":m["name"],"score":0,"error":info["error"]}); continue
            p = _score_a_share(m["name"], info, m["chain"], m["thesis"])
            p["symbol"] = sym; p["price"] = get_current_price(sym); picks.append(p); time.sleep(0.6)
        except Exception as e: picks.append({"symbol":sym,"name":m["name"],"score":0,"error":str(e)[:80]})
    picks.sort(key=lambda x: x["score"], reverse=True); return picks

def scan_bridge():
    picks = []
    for sym, m in BRIDGE_COMPANIES.items():
        try:
            r = score_stock(sym, m["name"]); info = get_factor_data(sym)
            if r and r.get("score",0) > 0:
                picks.append({"symbol":sym,"name":m["name"],"reason":m["reason"],"score":round(r["score"],1),
                    "pe":info.get("pe"),"roe":info.get("roe"),"mkt_cap":info.get("market_cap")})
            time.sleep(0.6)
        except Exception as e: picks.append({"symbol":sym,"name":m["name"],"score":0,"error":str(e)[:80]})
    picks.sort(key=lambda x: x["score"], reverse=True); return picks

def scan_decoupling_universe():
    print("🔄 中美脱钩·挖掘通道 v2.0\n" + "="*50)
    print("  🇭🇰 港股地缘折价..."); hk = scan_hk_discount()
    print("  🇺🇸 美股脱钩受益..."); us = scan_us_benefit()
    print("  🇨🇳 A股国产替代..."); cn = scan_a_share_self_reliance()
    print("  🌉 夹缝红利..."); bridge = scan_bridge()
    return {"hk":hk,"us":us,"cn":cn,"bridge":bridge}

if __name__ == "__main__":
    results = scan_decoupling_universe()
    for ch, label in [("hk","港股折价"),("us","美股受益"),("cn","A股替代"),("bridge","夹缝红利")]:
        print(f"\n📊 {label} Top 5:")
        for p in results[ch][:5]:
            if p["score"] > 0:
                print(f"  {p['name']}({p['symbol']}): {p['score']} | PE={p.get('pe','?')} | {p.get('discount','') or p.get('thesis','')[:50]}")
