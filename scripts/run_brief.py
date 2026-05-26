#!/usr/bin/env python3
"""
每日决策简报 (5分钟版)
Entry point: python scripts/run_brief.py
Replaces: scripts/run_report_v8.py
Hermes cron: 09:00 daily
"""
import sys, os
sys.path.insert(0, '/home/admin/.hermes')

import runpy
runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_report_v8.py'),
    run_name='__main__'
)
