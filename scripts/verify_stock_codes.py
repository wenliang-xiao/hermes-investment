#!/usr/bin/env python3
"""
股票代码数据完整性验证脚本
在 ECS 上运行：python scripts/verify_stock_codes.py
需要 baostock 可用
"""
import sys
sys.path.insert(0, '/home/admin/.hermes')

import baostock as bs
from investment_system.config import WATCHLIST, INDUSTRY_CHAINS

def query_name(code_str):
    try:
        rs = bs.query_stock_basic(code=code_str)
        if rs.error_code == "0":
            while rs.next():
                r = rs.get_row_data()
                return r[1] if len(r) > 1 else "?"
    except Exception:
        pass
    return "查询失败"

def to_bs_code(code):
    if code.startswith(("5", "6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"

bs.login()

print("=" * 80)
print("股票代码数据完整性验证报告")
print("=" * 80)

errors = []
warnings = []

print("\n【1】WATCHLIST A股代码验证")
print("-" * 60)
for code, info in WATCHLIST.items():
    if not str(code).isdigit():
        continue
    config_name = info.get("name", "")
    real_name = query_name(to_bs_code(str(code)))
    match = config_name in real_name or real_name in config_name
    status = "✅" if match else "❌"
    if not match:
        errors.append({
            "code": code,
            "config_name": config_name,
            "real_name": real_name,
            "location": "WATCHLIST"
        })
    print(f"  {status} {code}: config='{config_name}' | baostock='{real_name}'")

print("\n【2】INDUSTRY_CHAINS symbols验证（重点链）")
print("-" * 60)
key_chains = ["英伟达算力链", "台积电先进制程链", "存储/HBM链",
              "机器人/自动化链", "新能源链", "新能源汽车链",
              "医药创新链", "军工链", "半导体链"]

seen_codes = {}
for chain_name, chain_data in INDUSTRY_CHAINS.items():
    if chain_name not in key_chains:
        continue
    symbols = chain_data.get("symbols", [])
    a_symbols = [str(s) for s in symbols if str(s).isdigit()]
    print(f"\n  {chain_name} ({len(a_symbols)}只A股):")
    for code in a_symbols:
        real_name = query_name(to_bs_code(code))
        if code in seen_codes and seen_codes[code] != chain_name:
            warnings.append(f"  {code} 在多条链中: {seen_codes[code]} + {chain_name}")
        seen_codes[code] = chain_name
        status = "✅" if real_name not in ("查询失败", "?") else "⚠️"
        print(f"    {status} {code}: '{real_name}'")
        if real_name == "查询失败":
            errors.append({"code": code, "config_name": "unknown",
                           "real_name": "查询失败", "location": chain_name})

print("\n【3】重点可疑代码专项核查")
print("-" * 60)
suspicious = [
    ("601012", "config标注为阳光电源"),
    ("300308", "旧版曾被误标为中际旭创"),
    ("002371", "在先进制程链symbols里"),
    ("688120", "在先进制程链symbols里"),
    ("601319", "国家队主题里，疑似中国人保非中国银行"),
    ("601988", "中国银行正确代码应是这个?"),
    ("688029", "在医药链里"),
    ("300832", "在医药链里"),
    ("002850", "在新能源链里"),
    ("600438", "在新能源汽车链里"),
    ("300182", "在新能源汽车链里"),
    ("002460", "在新能源汽车链里"),
    ("002812", "在新能源汽车链里"),
    ("601633", "在新能源汽车链里"),
    ("600399", "在军工链里"),
    ("600391", "在军工链里"),
    ("600845", "数据链+机器人链都有"),
]
for code, note in suspicious:
    real_name = query_name(to_bs_code(code))
    print(f"  {code}: '{real_name}' | {note}")

bs.logout()

print("\n" + "=" * 80)
print(f"验证完成 | 发现错误: {len(errors)} | 警告: {len(warnings)}")
print("=" * 80)
if errors:
    print("\n❌ 需要修复的错误:")
    for e in errors:
        print(f"  {e['code']} [{e['location']}]: config='{e['config_name']}' 实际='{e['real_name']}'")
if warnings:
    print("\n⚠️ 警告:")
    for w in warnings:
        print(f"  {w}")
