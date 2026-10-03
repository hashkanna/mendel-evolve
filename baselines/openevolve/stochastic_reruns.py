#!/usr/bin/env python3
"""Re-run the best programs that are not deterministic several times, to show the spread of their scores.

    uv run python baselines/openevolve/stochastic_reruns.py        # after two_phase_results.py

Some programs OpenEvolve evolves draw random numbers without a seed, so every run returns a
different packing. OpenEvolve scored such a program once; the combined CSV scores one re-run of it.
Neither number is "the" score. This script finds, in the combined CSV, every best program whose
re-run did not reproduce the sum of radii OpenEvolve recorded, runs each of them `--repeats` times
and scores every run with the strict evaluator after repair. It writes
<csv stem>_stochastic_reruns.json: per program, what OpenEvolve recorded, the score in the CSV, and
the minimum, median and maximum over the repeats. No API calls.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import HERE, ROOT
from repair import repair
from rescore import load_module, run_program

N = 26


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score spread of non-deterministic best programs (no API calls).")
    parser.add_argument("--group", default=str(HERE / "runs" / "two_phase_haiku"))
    parser.add_argument("--csv", default=str(HERE / "results" / "two_phase_haiku.csv"))
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=900.0, help="wall seconds allowed per run")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)

    group = Path(args.group).resolve()
    evaluator = load_module(ROOT / "problems" / "circle_packing" / "evaluate.py", "strict_evaluate")
    rows = list(csv.DictReader(open(args.csv)))
    targets: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not row["openevolve_score"] or not row["rerun_sum_radii"] or row["iteration"] == "0":
            continue
        if abs(float(row["openevolve_score"]) - float(row["rerun_sum_radii"])) > 1e-9:
            targets.setdefault((row["seed"], row["program_sha256"]), row)
    print(f"{len(targets)} best programs did not reproduce OpenEvolve's recorded score when re-run", flush=True)

    def program_path(row: dict) -> Path:
        return (group / f"seed{row['seed']}" / f"phase{row['phase']}" / "openevolve_output" / "checkpoints"
                / f"checkpoint_{row['iteration']}" / "best_program.py")

    def one(job):
        key, row, _ = job
        packing, error, wall, cpu = run_program(program_path(row), args.timeout)
        if packing is None:
            return key, {"repaired_strict_score": None, "raw_sum_radii": None, "wall_s": round(wall, 1), "error": error}
        fixed = repair(packing) if len(packing) == N else None
        verdict = evaluator.evaluate({"n": N}, fixed) if fixed else {"valid": False}
        return key, {"repaired_strict_score": verdict["score"] if verdict["valid"] else None,
                     "raw_sum_radii": float(sum(c[2] for c in packing)), "wall_s": round(wall, 1), "cpu_s": round(cpu, 1),
                     "error": ""}

    jobs = [(key, row, k) for key, row in targets.items() for k in range(args.repeats)]
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        for key, result in pool.map(one, jobs):
            row = targets[key]
            name = f"seed{row['seed']}/phase{row['phase']}/checkpoint_{row['iteration']}"
            out.setdefault(name, {"seed": int(row["seed"]), "phase": int(row["phase"]), "iteration": int(row["iteration"]),
                                  "program_sha256": row["program_sha256"],
                                  "openevolve_recorded_sum_radii": float(row["openevolve_score"]),
                                  "repaired_score_in_csv": float(row["repaired_strict_score"]) if row["repaired_strict_score"] else None,
                                  "runs": []})["runs"].append(result)
    for name, entry in out.items():
        values = sorted(r["repaired_strict_score"] for r in entry["runs"] if r["repaired_strict_score"] is not None)
        entry["repaired_min"], entry["repaired_median"], entry["repaired_max"] = (
            (values[0], values[len(values) // 2], values[-1]) if values else (None, None, None))
        print(f"  {name}: OpenEvolve recorded {entry['openevolve_recorded_sum_radii']:.6f}, CSV {entry['repaired_score_in_csv']}, "
              f"{len(values)} re-runs: min {entry['repaired_min']}, median {entry['repaired_median']}, max {entry['repaired_max']}")
    target = Path(args.csv).with_name(Path(args.csv).stem + "_stochastic_reruns.json")
    target.write_text(json.dumps({"note": "Best programs that draw unseeded random numbers, each re-run "
                                          f"{args.repeats} times; every run repaired (repair.py) and scored by the strict evaluator.",
                                  "programs": out}, indent=1) + "\n")
    print(f"-> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
