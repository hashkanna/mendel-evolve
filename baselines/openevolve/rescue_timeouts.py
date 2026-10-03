#!/usr/bin/env python3
"""Re-run, offline, the programs that OpenEvolve discarded because their evaluation timed out.

    uv run python baselines/openevolve/rescue_timeouts.py            # then: two_phase_results.py

Why. OpenEvolve's evaluation limit is wall time (90 seconds in phase 2). The runs of 2026-10-03
shared a 10-core laptop with other jobs (load average 30 to 150), so a program that needs, say,
50 seconds of CPU could take more than 90 seconds of wall time and be thrown away with a score of
zero. That is a handicap of the machine, not of OpenEvolve. This script finds every program whose
metrics say `timeout: true` and gives it a second chance under a limit that does not depend on the
load: CPU seconds, enforced by the kernel (RLIMIT_CPU).

What it does. For every seed and phase under the group directory it reads the programs stored in
the checkpoints (each program once, from the first checkpoint that has it), keeps those that timed
out, writes their code to <group>/rescue/, runs each one with `--cpu-limit` CPU seconds (default
180: twice OpenEvolve's 90 wall seconds, to allow for CPU seconds being worth less on a contended
machine) and stores the packing, the CPU seconds it used and the wall time in
<group>/rescue_cache.json. No API calls. `two_phase_results.py` then scores the packings with the
strict evaluator after repair and reports which of them would have been a new best.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import HERE
from rescore import run_program


def timed_out_programs(group: Path) -> list[dict]:
    """Every program under the group whose stored metrics say it timed out."""
    found = []
    for run in sorted(p for p in group.iterdir() if p.is_dir() and p.name.startswith("seed")):
        for phase in ("phase1", "phase2"):
            directory = run / phase / "openevolve_output" / "checkpoints"
            if not directory.exists():
                continue
            seen: set[str] = set()
            for checkpoint in sorted(directory.glob("checkpoint_*"), key=lambda p: int(p.name.split("_")[-1])):
                for path in (checkpoint / "programs").glob("*.json"):
                    if path.stem in seen:
                        continue
                    seen.add(path.stem)
                    try:
                        program = json.loads(path.read_text())
                    except (OSError, ValueError):
                        continue
                    if program.get("metrics", {}).get("timeout") is True:
                        found.append({"seed": int(run.name.removeprefix("seed")), "phase": phase, "id": program["id"],
                                      "iteration": program.get("iteration_found"), "timestamp": program.get("timestamp"),
                                      "code": program["code"]})
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-run timed-out OpenEvolve programs under a CPU-time limit (no API calls).")
    parser.add_argument("--group", default=str(HERE / "runs" / "two_phase_haiku"))
    parser.add_argument("--cpu-limit", type=int, default=180, help="CPU seconds allowed per program")
    parser.add_argument("--wall-limit", type=float, default=3600.0, help="backstop in wall seconds")
    parser.add_argument("--workers", type=int, default=3, help="programs run at the same time")
    args = parser.parse_args(argv)

    group = Path(args.group).resolve()
    programs = timed_out_programs(group)
    cache_path = group / "rescue_cache.json"
    cache: dict[str, dict] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    code_dir = group / "rescue"
    code_dir.mkdir(exist_ok=True)

    todo = []
    for program in programs:
        key = f"seed{program['seed']}/{program['phase']}/{program['id']}"
        name = f"seed{program['seed']}_{program['phase']}_it{int(program['iteration'] or 0):03d}_{program['id'][:8]}.py"
        path = code_dir / name
        if not path.exists():
            path.write_text(program["code"])
        entry = cache.get(key)
        if entry is None or entry.get("cpu_limit") != args.cpu_limit:
            todo.append((key, program, path))
    by_seed = {}
    for program in programs:
        by_seed[(program["seed"], program["phase"])] = by_seed.get((program["seed"], program["phase"]), 0) + 1
    print(f"{len(programs)} timed-out programs {dict(sorted(by_seed.items()))}; {len(todo)} to run "
          f"with {args.cpu_limit}s of CPU each, {args.workers} at a time", flush=True)

    def work(item):
        key, program, path = item
        packing, error, wall, cpu = run_program(path, args.wall_limit, cpu_limit=args.cpu_limit)
        return key, {"seed": program["seed"], "phase": program["phase"], "id": program["id"],
                     "iteration": program["iteration"], "timestamp": program["timestamp"],
                     "sha": hashlib.sha256(program["code"].encode()).hexdigest(), "code_file": f"rescue/{path.name}",
                     "cpu_limit": args.cpu_limit, "packing": packing, "cpu_s": round(cpu, 2), "wall_s": round(wall, 1),
                     "error": error, "run_at": time.strftime("%Y-%m-%dT%H:%M:%S")}

    started = time.time()
    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        for done, (key, entry) in enumerate(pool.map(work, todo), 1):
            cache[key] = entry
            cache_path.write_text(json.dumps(cache) + "\n")
            state = "finished" if entry["packing"] is not None else entry["error"][:60]
            print(f"  {done}/{len(todo)} seed{entry['seed']} {entry['phase']} iteration {entry['iteration']}: {state}; "
                  f"{entry['cpu_s']:.0f}s CPU, {entry['wall_s']:.0f}s wall ({time.time() - started:.0f}s elapsed)", flush=True)
    finished = sum(1 for e in cache.values() if e["packing"] is not None)
    print(f"{len(cache)} programs in {cache_path}: {finished} finished, {len(cache) - finished} did not")
    return 0


if __name__ == "__main__":
    sys.exit(main())
