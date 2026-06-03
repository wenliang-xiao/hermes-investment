#!/bin/bash
# Wrapper to run daily.py with long timeout in background
cd /home/admin/.hermes/investment_system
> /tmp/report_daily_log.txt
nohup timeout 600 python3 scripts/run_daily.py > /tmp/report_daily_stdout.txt 2>&1 &
PID=$!
echo "Started PID: $PID"
# Wait up to 540 seconds
for i in $(seq 1 540); do
    if ! kill -0 $PID 2>/dev/null; then
        break
    fi
    sleep 1
done
echo "Done waiting. Exit or timeout."