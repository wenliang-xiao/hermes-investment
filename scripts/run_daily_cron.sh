#!/bin/bash
cd /home/admin/.hermes/investment_system
python3 scripts/run_daily.py 2>&1
echo "EXIT_CODE=$?"