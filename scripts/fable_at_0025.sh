#!/bin/sh
# Wait until 00:25 on 2026-10-04 (after the login's usage limit resets), then move the two long
# engine runs back to Fable inventors on the login at their next generation boundary.
cd "$(dirname "$0")/.." || exit 1
target=$(date -j -f "%Y-%m-%d %H:%M" "2026-10-04 00:25" +%s)
until [ "$(date +%s)" -ge "$target" ]; do sleep 60; done
for run in p60 p59; do
  pkill -f "scripts/handover3.sh $run( |\$)" 2>/dev/null
  sleep 1
  nohup scripts/handover3.sh "$run" --inventor-opt model=fable --inventor-opt billing=subscription --inventor-opt minutes=12 \
    > "runs/logs/handover-$run-fable-0025.log" 2>&1 &
done
echo "$(date '+%H:%M') scheduled Fable hand-overs for p60 and p59"
