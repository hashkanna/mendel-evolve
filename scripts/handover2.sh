#!/bin/sh
# Move a running engine onto the code and Modal lane currently on disk, at its next generation boundary.
# Usage: scripts/handover2.sh RUN_ID [extra `mendel run` flags, e.g. --seeds 24]
# Waits for the run's next "generation_finished", interrupts the engine and its inventor sessions (the run
# checkpoints after every generation), waits for it to exit, and resumes it on the eight-core lane.
cd "$(dirname "$0")/.." || exit 1
RUN="$1"; shift
EVENTS="runs/$RUN/events.jsonl"
count() { grep -c '"event": "generation_finished"' "$EVENTS" 2>/dev/null || echo 0; }
START=$(count)
until [ "$(count)" -gt "$START" ]; do sleep 10; done
PIDS=$(pgrep -f "bin/mendel run .*--run-id $RUN( |\$)")
for pid in $PIDS; do kill -INT "$pid" 2>/dev/null; sleep 2; pkill -TERM -P "$pid" 2>/dev/null; done
for i in $(seq 1 200); do
  alive=""; for pid in $PIDS; do kill -0 "$pid" 2>/dev/null && alive=1; done
  [ -z "$alive" ] && break
  [ "$i" = 60 ] && for pid in $PIDS; do kill -INT "$pid" 2>/dev/null; pkill -TERM -P "$pid" 2>/dev/null; done
  sleep 3
done
echo "$(date '+%H:%M:%S') resuming $RUN on the eight-core lane $*"
MENDEL_MODAL_FUNCTION=run_batch_x8 MENDEL_SANDBOX_EXECUTOR=modal MENDEL_WALL_FACTOR=10 \
  exec caffeinate -i uv run mendel run --resume --run-id "$RUN" "$@"
