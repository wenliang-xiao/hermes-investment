#!/usr/bin/env python3
"""
产业链分布统计：
1. 读取 domain/__init__.py 的 WATCHLIST，统计每个 chain 的股票数量和 tier 分布
2. 用 baostock 获取 A 股持仓的最新 PE_TTM 和 PB
3. 输出 JSON
"""

import sys
import os
import json
import re
import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── 1. 解析 WATCHLIST ──
filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'domain', '__init__.py')

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

watchlist_match = re.search(r'^WATCHLIST\s*=\s*\{', content, re.MULTILINE)
if not watchlist_match:
    print("ERROR: Cannot find WATCHLIST in domain/__init__.py")
    sys.exit(1)

start = watchlist_match.start()
depth = 0
in_string = False
string_char = None
escape = False
in_comment = False
watchlist_text = ""
brace_started = False

for i in range(start, len(content)):
    c = content[i]
    
    if in_comment and c != '\n':
        watchlist_text += c
        continue
    if in_comment and c == '\n':
        in_comment = False
        watchlist_text += c
        continue
    
    if escape:
        watchlist_text += c
        escape = False
        continue
    
    if in_string:
        watchlist_text += c
        if c == '\\':
            escape = True
        elif c == string_char:
            in_string = False
        continue
    
    if c == '#':
        watchlist_text += c
        in_comment = True
        continue
    
    if c in '"\'':
        watchlist_text += c
        in_string = True
        string_char = c
        continue
    
    if c == '{':
        depth += 1
        brace_started = True
        watchlist_text += c
        continue
    
    if c == '}':
        depth -= 1
        watchlist_text += c
        if depth == 0 and brace_started:
            break
        continue
    
    watchlist_text += c

# Parse entries
entries = {}
pattern = r'\s*["\']([^"\']+)["\']\s*:\s*\{([^}]+)\}'
for m in re.finditer(pattern, watchlist_text):
    code = m.group(1)
    inner = m.group(2)
    
    name_m = re.search(r'["\']name["\']\s*:\s*["\']([^"\']*)["\']', inner)
    chain_m = re.search(r'["\']chain["\']\s*:\s*["\']([^"\']*)["\']', inner)
    tier_m = re.search(r'["\']tier["\']\s*:\s*["\']([^"\']*)["\']', inner)
    
    if name_m and chain_m and tier_m:
        entries[code] = {
            'name': name_m.group(1),
            'chain': chain_m.group(1),
            'tier': tier_m.group(1),
        }

print(f"Parsed {len(entries)} entries from WATCHLIST", file=sys.stderr)

# ── 2. 按 chain 统计 ──
chain_stats = {}
for code, info in entries.items():
    chain = info['chain']
    tier = info['tier']
    
    if chain not in chain_stats:
        chain_stats[chain] = {'count': 0, 'by_tier': {}}
    
    chain_stats[chain]['count'] += 1
    chain_stats[chain]['by_tier'][tier] = chain_stats[chain]['by_tier'].get(tier, 0) + 1

print("\n=== 产业链分布统计 ===", file=sys.stderr)
for chain, stats in sorted(chain_stats.items(), key=lambda x: x[1]['count'], reverse=True):
    tiers_str = ', '.join(f"{t}:{c}" for t, c in sorted(stats['by_tier'].items()))
    print(f"  {chain:20s} | 共 {stats['count']:2d} 只 | {tiers_str}", file=sys.stderr)

# ── 3. 获取 A 股 PE_TTM / PB（baostock）──
a_share_codes = []
for code in entries:
    if re.match(r'^\d{6}$', code):
        a_share_codes.append(code)

print(f"\nA股持仓数量: {len(a_share_codes)}", file=sys.stderr)

def get_stock_market(code):
    """Determine if a stock code belongs to Shanghai or Shenzhen"""
    if code.startswith('6'):
        return 'sh'
    return 'sz'

def query_stock_pe_pb(code, query_date):
    """Query PE and PB for a single stock on a given date"""
    market = get_stock_market(code)
    bs_code = f"{market}.{code}"
    
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,code,peTTM,pbMRQ",
        start_date=query_date,
        end_date=query_date,
        frequency="d",
        adjustflag="3"
    )
    
    if rs.error_code != '0':
        return None
    
    df = rs.to_df()
    if df.empty:
        return None
    
    row = df.iloc[0]
    if row['peTTM'] == '' or row['pbMRQ'] == '':
        return None
    
    return {
        'pe': float(row['peTTM']),
        'pb': float(row['pbMRQ'])
    }

# Login to baostock
print("正在连接 baostock...", file=sys.stderr)
lg = bs.login()
if lg.error_code != '0':
    print(f"baostock登录失败: {lg.error_msg}", file=sys.stderr)
    sys.exit(1)
print(f"登录成功", file=sys.stderr)

pe_pb_data = {}

# Try multiple recent dates
today = datetime.now()
found_any = False

for days_ago in range(0, 10):
    query_date = (today - timedelta(days=days_ago)).strftime('%Y-%m-%d')
    success_count = 0
    
    for code in a_share_codes:
        if code in pe_pb_data:
            continue  # already have data
        try:
            result = query_stock_pe_pb(code, query_date)
            if result:
                pe_pb_data[code] = result
                success_count += 1
        except Exception as e:
            pass
    
    if success_count > 0:
        print(f"  日期 {query_date}: 获取到 {success_count} 只", file=sys.stderr)
        found_any = True
    
    if len(pe_pb_data) >= len(a_share_codes) * 0.8:
        print(f"  已获取 {len(pe_pb_data)}/{len(a_share_codes)} 只, 停止搜索", file=sys.stderr)
        break

if not found_any:
    print("  WARNING: 未找到任何 PE/PB 数据", file=sys.stderr)

bs.logout()

# Print per-stock PE/PB
print("\n=== 各股 PE/PB ===", file=sys.stderr)
for code in a_share_codes:
    info = entries[code]
    if code in pe_pb_data:
        d = pe_pb_data[code]
        pe_str = f"{d['pe']:.2f}" if d['pe'] is not None else "N/A"
        pb_str = f"{d['pb']:.2f}" if d['pb'] is not None else "N/A"
        print(f"  {code} {info['name']:8s} | {info['chain']:12s} | PE={pe_str:>7s} PB={pb_str:>6s}", file=sys.stderr)
    else:
        print(f"  {code} {info['name']:8s} | {info['chain']:12s} | PE=N/A PB=N/A", file=sys.stderr)

# ── 4. 计算每个 chain 的 avg_pe / avg_pb ──
chain_pe_pb = {}
for code, info in entries.items():
    chain = info['chain']
    if code in pe_pb_data and pe_pb_data[code]['pe'] is not None and pe_pb_data[code]['pb'] is not None:
        if chain not in chain_pe_pb:
            chain_pe_pb[chain] = {'pe_sum': 0.0, 'pb_sum': 0.0, 'pe_count': 0, 'pb_count': 0}
        chain_pe_pb[chain]['pe_sum'] += pe_pb_data[code]['pe']
        chain_pe_pb[chain]['pb_sum'] += pe_pb_data[code]['pb']
        chain_pe_pb[chain]['pe_count'] += 1
        chain_pe_pb[chain]['pb_count'] += 1

# ── 5. 构建输出 JSON ──
output = {}
for chain in sorted(chain_stats.keys()):
    stats = chain_stats[chain]
    entry = {
        'count': stats['count'],
        'by_tier': {}
    }
    tier_order = ['核心', '底仓', '关注', '追踪']
    for t in tier_order:
        if t in stats['by_tier']:
            entry['by_tier'][t] = stats['by_tier'][t]
    
    if chain in chain_pe_pb:
        cp = chain_pe_pb[chain]
        entry['avg_pe'] = round(cp['pe_sum'] / cp['pe_count'], 2) if cp['pe_count'] > 0 else None
        entry['avg_pb'] = round(cp['pb_sum'] / cp['pb_count'], 2) if cp['pb_count'] > 0 else None
    else:
        entry['avg_pe'] = None
        entry['avg_pb'] = None
    
    output[chain] = entry

# Output JSON
print("\n=== FINAL JSON OUTPUT ===")
print(json.dumps(output, ensure_ascii=False, indent=2))

# Also compute overall stats
total = sum(s['count'] for s in chain_stats.values())
print(f"\n总计: {total} 只持仓, {len(chain_stats)} 个产业链", file=sys.stderr)
tier_totals = {}
for s in chain_stats.values():
    for t, c in s['by_tier'].items():
        tier_totals[t] = tier_totals.get(t, 0) + c
print("各 tier 合计:", ', '.join(f"{t}:{c}" for t, c in sorted(tier_totals.items())), file=sys.stderr)
