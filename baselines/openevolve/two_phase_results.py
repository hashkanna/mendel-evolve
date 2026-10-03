#!/usr/bin/env python3
"""Re-score the two-phase OpenEvolve runs with Mendel's strict evaluator and summarise them.

    uv run python baselines/openevolve/two_phase_results.py
    uv run python baselines/openevolve/two_phase_results.py --group baselines/openevolve/runs/two_phase_haiku \
        --out baselines/openevolve/results/two_phase_haiku.csv

For every seed under the group directory, and for both phases, this takes OpenEvolve's best program
at each checkpoint (checkpoint interval 1, so after every iteration), runs it once in OpenEvolve's
own virtual environment and scores the packing it returns. No API calls are made.

One CSV row per (seed, phase, checkpoint), in the order the money was spent:

    seed, phase, iteration            which run and checkpoint (iteration 0 of phase 1 is the initial program)
    cumulative_requests               billed requests so far, phase 1 and phase 2 together
    cumulative_dollars                the same in USD (claude-haiku-4-5 list price)
    openevolve_score                  `sum_radii` as OpenEvolve's own evaluator recorded it (tolerance 1e-6)
    repaired_strict_score             the same program's packing, made exactly feasible by `repair.py`
                                      (radii shrunk, never enlarged) and scored by the strict
                                      evaluator; empty if the program failed when re-run
    best_so_far_repaired_score        running maximum of repaired_strict_score within the seed
    cumulative_tokens, raw_strict_score, raw_strict_valid, rerun_sum_radii, program_sha256, program_wall_s

`raw_strict_score` is the strict evaluator's verdict on the packing exactly as the program returned
it; it is 0 for nearly every program, because circles that touch in floating point overlap by
rounding error. `rerun_sum_radii` is the plain sum of the radii of the re-run, to compare with
`openevolve_score`: they differ when a program is not deterministic.

"Best so far" ranges over the programs that were OpenEvolve's best at some checkpoint, i.e. the
programs a user of OpenEvolve would have taken away. It also writes <out stem>_summary.json and
prints the summary table.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from common import EXAMPLE, HERE, ROOT, ZERO, add_usage, parse_usage
from repair import repair
from rescore import load_module, run_program

N = 26
THRESHOLDS = (2.0, 2.5, 2.6, 2.63)
BEST_KNOWN = 2.635983084919


def checkpoint_rows(seed: int, phase: str, output_dir: Path, before: dict) -> list[dict]:
    """One row per checkpoint of a phase, ordered by spend, with cumulative usage across phases."""
    usage = parse_usage(output_dir)
    rows = []
    directory = output_dir / "checkpoints"
    checkpoints = sorted(directory.glob("checkpoint_*"), key=lambda p: int(p.name.split("_")[-1])) if directory.exists() else []
    for checkpoint in checkpoints:
        program = checkpoint / "best_program.py"
        if not program.exists():
            continue
        iteration = int(checkpoint.name.split("_")[-1])
        info_path = checkpoint / "best_program_info.json"
        info = json.loads(info_path.read_text()) if info_path.exists() else {}
        spent = usage["at_checkpoint"].get(str(iteration))
        if spent is None:
            continue
        rows.append({"seed": seed, "phase": phase, "iteration": iteration, "usage": add_usage(before, spent),
                     "program": program, "openevolve_score": info.get("metrics", {}).get("sum_radii")})
    rows.sort(key=lambda r: (r["usage"]["requests"], r["iteration"]))
    return rows


def rerun(program: Path, timeout: float) -> dict:
    """Run a program once and keep the packing it returns (the expensive, possibly random, part)."""
    packing, error, wall, cpu = run_program(program, timeout)
    return {"packing": packing, "error": error, "wall": round(wall, 2), "cpu": round(cpu, 2)}


def score(entry: dict, evaluator) -> dict:
    """Strict verdict on a re-run's packing as returned, and on the same packing after `repair`."""
    import numpy as np

    packing = entry["packing"]
    result = {"raw_strict_score": 0.0, "raw_strict_valid": False, "repaired": None, "rerun_sum": None,
              "error": entry["error"], "wall": entry["wall"]}
    if packing is None:
        return result
    verdict = evaluator.evaluate({"n": N}, packing)
    result["raw_strict_score"], result["raw_strict_valid"] = verdict["score"], verdict["valid"]
    if not verdict["valid"]:
        result["error"] = verdict["detail"].get("reason", "")
    try:
        array = np.array(packing, dtype=float).reshape(-1, 3)
        result["rerun_sum"] = float(np.sum(array[:, 2]))
    except (TypeError, ValueError):
        return result
    if len(array) == N:
        repaired = repair(packing)
        if repaired is not None:
            check = evaluator.evaluate({"n": N}, repaired)
            if check["valid"]:
                result["repaired"] = check["score"]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Strict re-scoring and summary of the two-phase OpenEvolve runs.")
    parser.add_argument("--group", default=str(HERE / "runs" / "two_phase_haiku"))
    parser.add_argument("--out", default=str(HERE / "results" / "two_phase_haiku.csv"))
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds allowed per program when re-run")
    parser.add_argument("--workers", type=int, default=3, help="programs re-run at the same time")
    args = parser.parse_args(argv)

    group = Path(args.group).resolve()
    evaluator = load_module(ROOT / "problems" / "circle_packing" / "evaluate.py", "strict_evaluate")

    seeds: dict[int, dict] = {}
    rows: list[dict] = []
    for run in sorted(p for p in group.iterdir() if p.is_dir() and p.name.startswith("seed")):
        seed = int(run.name.removeprefix("seed"))
        manifest = json.loads((run / "manifest.json").read_text()) if (run / "manifest.json").exists() else {}
        seeds[seed] = {"manifest": manifest, "phase_usage": {}, "phase_iterations": {}}
        rows.append({"seed": seed, "phase": "phase1", "iteration": 0, "usage": ZERO,
                     "program": EXAMPLE / "initial_program.py", "openevolve_score": None})
        before = ZERO
        for phase in ("phase1", "phase2"):
            output_dir = run / phase / "openevolve_output"
            if not output_dir.exists():
                continue
            phase_rows = checkpoint_rows(seed, phase, output_dir, before)
            rows += phase_rows
            usage = parse_usage(output_dir)
            before = add_usage(before, usage["total"])
            seeds[seed]["phase_usage"][phase] = usage["total"]
            seeds[seed]["phase_iterations"][phase] = usage["iterations_logged"]
            seeds[seed].setdefault("lost", 0)
            seeds[seed]["lost"] += len(usage["llm_failures"])
        seeds[seed]["total"] = before
    if not rows:
        raise SystemExit(f"no runs found under {group}")

    # Re-run each distinct program once. The packings are cached next to the runs, keyed by the
    # program's hash, so scoring can be repeated without running (possibly random) programs again.
    cache_path = group / "rerun_cache.json"
    cache: dict[str, dict] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    for row in rows:
        row["sha"] = hashlib.sha256(row["program"].read_bytes()).hexdigest()
    todo = {}
    for row in rows:
        if row["sha"] not in cache:
            todo.setdefault(row["sha"], row["program"])
    print(f"{len(rows)} checkpoints, {len({r['sha'] for r in rows})} distinct programs, {len(todo)} to run", flush=True)
    started = time.time()

    def work(item):
        sha, program = item
        return sha, rerun(program, args.timeout)

    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        for done, (sha, entry) in enumerate(pool.map(work, todo.items()), 1):
            cache[sha] = entry
            if done % 10 == 0 or done == len(todo):
                cache_path.write_text(json.dumps(cache) + "\n")
                print(f"  re-ran {done}/{len(todo)} programs ({time.time() - started:.0f}s)", flush=True)
    scores = {sha: score(cache[sha], evaluator) for sha in {r["sha"] for r in rows}}

    # The combined CSV.
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    best: dict[int, float] = {}
    fields = ["seed", "phase", "iteration", "cumulative_requests", "cumulative_dollars", "openevolve_score",
              "repaired_strict_score", "best_so_far_repaired_score", "cumulative_tokens", "raw_strict_score",
              "raw_strict_valid", "rerun_sum_radii", "program_sha256", "program_wall_s"]
    table = []
    for row in rows:
        result = scores[row["sha"]]
        repaired = result["repaired"]
        if repaired is not None:
            best[row["seed"]] = max(best.get(row["seed"], -math.inf), repaired)
        openevolve_score = row["openevolve_score"] if row["openevolve_score"] is not None else result["rerun_sum"]
        table.append({
            "seed": row["seed"], "phase": row["phase"].removeprefix("phase"), "iteration": row["iteration"],
            "cumulative_requests": row["usage"]["requests"], "cumulative_dollars": f"{row['usage']['usd']:.6f}",
            "openevolve_score": "" if openevolve_score is None else repr(float(openevolve_score)),
            "repaired_strict_score": "" if repaired is None else repr(repaired),
            "best_so_far_repaired_score": "" if row["seed"] not in best else repr(best[row["seed"]]),
            "cumulative_tokens": row["usage"]["tokens"], "raw_strict_score": repr(result["raw_strict_score"]),
            "raw_strict_valid": result["raw_strict_valid"],
            "rerun_sum_radii": "" if result["rerun_sum"] is None else repr(result["rerun_sum"]),
            "program_sha256": row["sha"][:16], "program_wall_s": result["wall"],
        })
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(table)

    # The summary.
    summary = {"group": str(group), "csv": str(out), "best_known": BEST_KNOWN, "seeds": {}}
    for seed, info in sorted(seeds.items()):
        mine = [r for r in table if r["seed"] == seed]

        def best_after(phase: str):
            values = [float(r["best_so_far_repaired_score"]) for r in mine
                      if r["phase"] <= phase and r["best_so_far_repaired_score"] != ""]
            return values[-1] if values else None

        def openevolve_after(phase: str):
            values = [float(r["openevolve_score"]) for r in mine if r["phase"] == phase and r["openevolve_score"] != ""]
            return max(values) if values else None

        passed = {}
        for threshold in THRESHOLDS:
            hit = next((r for r in mine if r["best_so_far_repaired_score"] != ""
                        and float(r["best_so_far_repaired_score"]) >= threshold), None)
            passed[str(threshold)] = None if hit is None else {"dollars": float(hit["cumulative_dollars"]),
                                                               "requests": hit["cumulative_requests"],
                                                               "phase": hit["phase"], "iteration": hit["iteration"]}
        manifest = info["manifest"]
        phases = manifest.get("phases", {})
        summary["seeds"][str(seed)] = {
            "best_repaired_after_phase1": best_after("1"),
            "best_repaired_after_phase2": best_after("2") if "phase2" in info["phase_usage"] else None,
            "openevolve_best_phase1": openevolve_after("1"), "openevolve_best_phase2": openevolve_after("2"),
            "requests": info["total"]["requests"], "dollars": info["total"]["usd"], "tokens": info["total"]["tokens"],
            "requests_by_phase": {k: v["requests"] for k, v in info["phase_usage"].items()},
            "dollars_by_phase": {k: v["usd"] for k, v in info["phase_usage"].items()},
            "iterations_by_phase": info["phase_iterations"], "iterations_lost_to_api_errors": info.get("lost", 0),
            "wall_seconds": manifest.get("wall_seconds"),
            "wall_seconds_by_phase": {k: v.get("wall_seconds") for k, v in phases.items()},
            "stopped": manifest.get("stopped"), "first_passed": passed,
        }

    def spread(key: str):
        values = [s[key] for s in summary["seeds"].values() if s[key] is not None]
        if not values:
            return None
        return {"n": len(values), "mean": statistics.fmean(values), "min": min(values), "max": max(values),
                "sd": statistics.stdev(values) if len(values) > 1 else 0.0}

    summary["over_seeds"] = {key: spread(key) for key in ("best_repaired_after_phase1", "best_repaired_after_phase2",
                                                         "requests", "dollars", "wall_seconds")}
    summary["total_dollars"] = round(sum(s["dollars"] for s in summary["seeds"].values()), 6)
    summary_path = out.with_name(out.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=1) + "\n")

    def show(value, digits=6):
        return "-" if value is None else f"{value:.{digits}f}"

    print(f"\n{'seed':>4s} {'after phase 1':>14s} {'after phase 2':>14s} {'requests':>9s} {'dollars':>8s} {'wall min':>9s}  "
          + "  ".join(f"$ at {t}" for t in THRESHOLDS))
    for seed, s in summary["seeds"].items():
        marks = "  ".join(f"{('-' if s['first_passed'][str(t)] is None else format(s['first_passed'][str(t)]['dollars'], '.2f')):>{len(f'$ at {t}')}s}"
                          for t in THRESHOLDS)
        wall = "-" if s["wall_seconds"] is None else f"{s['wall_seconds'] / 60:.1f}"
        print(f"{seed:>4s} {show(s['best_repaired_after_phase1']):>14s} {show(s['best_repaired_after_phase2']):>14s} "
              f"{s['requests']:>9d} {s['dollars']:>8.2f} {wall:>9s}  {marks}" + (f"   STOPPED: {s['stopped'][:60]}" if s["stopped"] else ""))
    for key in ("best_repaired_after_phase1", "best_repaired_after_phase2"):
        sp = summary["over_seeds"][key]
        if sp:
            print(f"{key}: mean {sp['mean']:.6f}, sd {sp['sd']:.6f}, min {sp['min']:.6f}, max {sp['max']:.6f} (n={sp['n']})")
    print(f"total: ${summary['total_dollars']:.2f}   best known {BEST_KNOWN}")
    print(f"{len(table)} rows -> {out}\nsummary -> {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
