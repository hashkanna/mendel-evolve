#!/usr/bin/env python3
"""Kill evaluation subprocesses that OpenEvolve has already given up on.

    python baselines/openevolve/reap_orphans.py [--max-age 100] [--log FILE]

Why this exists. OpenEvolve gives an evaluation `evaluator.timeout` seconds (60 in phase 1, 90 in
phase 2) and then records a time-out and moves on. The circle-packing evaluator, however, runs the
program in a subprocess with its own limit of 600 seconds, and nothing stops that subprocess when
OpenEvolve times out. Every timed-out program therefore keeps a core busy for up to ten minutes
with a result nobody will read. In phase 2, where a quarter of the programs time out, three runs
of two workers each had six such processes at once, on a machine shared with other jobs.

What it kills, and nothing else: a process
  * whose process group is led by an `oe_launch.py` process (run_openevolve.py starts OpenEvolve in
    its own session, so the group contains exactly that run's workers and evaluations), and
  * whose command line is an evaluator temp script (`python .../T/tmpXXXXXXXX.py`), and
  * that is older than --max-age seconds, i.e. past the evaluation time-out, so OpenEvolve has
    already recorded its result as a time-out.
It changes nothing about OpenEvolve's search; it only frees the cores. It exits when no OpenEvolve
run started by run_openevolve.py has been alive for a minute. run_openevolve.py does the same from
its watchdog, so this script is only needed for runs started before that was added.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import time

# a Python interpreter whose script is oe_launch.py (not any command line that merely mentions it)
LAUNCHER = re.compile(r"^\S*[Pp]ython[\d.]*\s+\S*baselines/openevolve/oe_launch\.py\s")
TEMP_SCRIPT = re.compile(r"/var/folders/\S+/tmp[^/\s]+\.py$")


def processes() -> list[tuple[int, int, int, str]]:
    """(pid, process group, age in seconds, command line) of every process."""
    out = subprocess.run(["ps", "-Ao", "pid=,pgid=,etime=,command="], capture_output=True, text=True).stdout
    rows = []
    for line in out.splitlines():
        parts = line.split(None, 3)
        if len(parts) != 4:
            continue
        days, _, rest = parts[2].rpartition("-")
        fields = [int(x) for x in rest.split(":")]
        while len(fields) < 3:
            fields.insert(0, 0)
        age = (int(days) if days else 0) * 86400 + fields[0] * 3600 + fields[1] * 60 + fields[2]
        rows.append((int(parts[0]), int(parts[1]), age, parts[3]))
    return rows


def reap(max_age: float, groups: set[int] | None = None) -> tuple[int, list[tuple[int, int, int]]]:
    """Kill orphaned evaluations. Returns (OpenEvolve runs alive, [(pid, group, age)] killed)."""
    rows = processes()
    leaders = {pid for pid, pgid, _, command in rows if pid == pgid and LAUNCHER.search(command)}
    if groups is not None:
        leaders &= groups
    killed = []
    for pid, pgid, age, command in rows:
        if pgid in leaders and pid not in leaders and age > max_age and TEMP_SCRIPT.search(command):
            try:
                os.kill(pid, signal.SIGKILL)
                killed.append((pid, pgid, age))
            except OSError:
                pass
    return len(leaders), killed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-age", type=float, default=100.0, help="seconds; above the evaluation time-out")
    parser.add_argument("--log", help="append a line per kill to this file")
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    args = parser.parse_args()
    idle_since = None
    while True:
        alive, killed = reap(args.max_age)
        for pid, group, age in killed:
            line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} killed evaluation {pid} of OpenEvolve run {group}, {age}s old"
            print(line, flush=True)
            if args.log:
                with open(args.log, "a") as f:
                    f.write(line + "\n")
        if args.once:
            return 0
        if alive:
            idle_since = None
        else:
            idle_since = idle_since or time.time()
            if time.time() - idle_since > 60:
                return 0
        time.sleep(10.0)


if __name__ == "__main__":
    sys.exit(main())
