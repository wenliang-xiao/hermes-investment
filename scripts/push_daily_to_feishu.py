#!/usr/bin/env python3
"""Push daily report to Feishu group"""
import sys
sys.path.insert(0, '/home/admin/.hermes')
from investment_system.output.report_v6 import push_to_group

url = "https://bytedance.feishu.cn/docx/AxKSd71tho0KlcxJbA6cnZqonSb"
summary = "🌅 6月2日(二)开盘前决策简报已生成\n\n✅ 盘前简报已完成\n📦 ETF组合推荐（复苏期配置）\n🔗 链路摘要 & 今日情报\n\n点击链接查看完整日报 👇"

push_to_group(url, summary)
print("✅ 日报推送完成")
