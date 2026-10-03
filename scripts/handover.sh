#!/bin/sh
# Restart an engine run onto the code currently on disk, at a generation boundary.
# Usage: scripts/handover.sh RUN_ID GENERATION
# Waits until GENERATION has finished, interrupts the engine (it checkpoints after every generation) and
# its inventor sessions, waits for it to exit, then resumes it. The run keeps its saved configuration.
cd "$(dirname "$0")/.." || exit 1
RUN="$1"; GEN="$2"
until grep -q "\"generation\": $GEN, \"event\": \"generation_finished\"" "runs/$RUN/events.jsonl" 2>/dev/null; do sleep 10; done
PIDS=$(pgrep -f "bin/mendel run .*--run-id $RUN " ; pgrep -f "mendel.cli run .*--run-id $RUN ")
for pid in $PIDS; do
  kill -INT "$pid" 2>/dev/null
  sleep 2
  pkill -TERM -P "$pid" 2>/dev/null   # the inventor sessions it is waiting on; their generation will be redone
done
for i in $(seq 1 200); do
  alive=""; for pid in $PIDS; do kill -0 "$pid" 2>/dev/null && alive=1; done
  [ -z "$alive" ] && break
  [ "$i" = 60 ] && for pid in $PIDS; do kill -INT "$pid" 2>/dev/null; pkill -TERM -P "$pid" 2>/dev/null; done
  sleep 3
done
rm -f "runs/$RUN/engine.lock.stale" 2>/dev/null
echo "$(date '+%H:%M:%S') resuming $RUN after generation $GEN"
MENDEL_SANDBOX_EXECUTOR=modal exec caffeinate -i uv run mendel run --resume --run-id "$RUN"
