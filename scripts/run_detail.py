#!/usr/bin/env python3
"""
全资产深度日报
Entry point: python scripts/run_detail.py
Replaces: scripts/run_report_v7.py
Hermes cron: 09:30 daily
"""
import sys, os
sys.path.insert(0, '/home/admin/.hermes')

import runpy
runpy.run_path(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'run_report_v7.py'),
    run_name='__main__'
)
