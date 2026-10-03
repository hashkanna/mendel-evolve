#!/bin/sh
# Restart an engine run onto the code currently on disk, at a generation boundary, without losing work.
# Usage: scripts/handover.sh RUN_ID GENERATION
# Waits until GENERATION has finished, interrupts the engine (it checkpoints after every generation),
# then resumes it. The run keeps its saved configuration.
cd "$(dirname "$0")/.." || exit 1
RUN="$1"; GEN="$2"
until grep -q "\"generation\": $GEN, \"event\": \"generation_finished\"" "runs/$RUN/events.jsonl" 2>/dev/null; do sleep 15; done
PIDS=$(pgrep -f "bin/mendel run .*--run-id $RUN " ; pgrep -f "mendel.cli run .*--run-id $RUN ")
[ -n "$PIDS" ] && kill -INT $PIDS 2>/dev/null
for i in $(seq 1 40); do [ -f "runs/$RUN/engine.lock" ] || break; sleep 3; done
echo "$(date '+%H:%M:%S') resuming $RUN after generation $GEN"
MENDEL_SANDBOX_EXECUTOR=modal exec caffeinate -i uv run mendel run --resume --run-id "$RUN"
