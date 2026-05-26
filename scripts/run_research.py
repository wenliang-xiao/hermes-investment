#!/usr/bin/env python3
"""
个股深度研报
Entry point: python scripts/run_research.py --symbol 603986
Wraps: deep_research.py
Hermes trigger: on-demand
"""
import sys, os
sys.path.insert(0, '/home/admin/.hermes')

import runpy
runpy.run_path(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'deep_research.py'),
    run_name='__main__'
)
