#!/usr/bin/env python3
"""Re-score the two-phase OpenEvolve runs with Mendel's strict evaluator and summarise them.

    uv run python baselines/openevolve/rescue_timeouts.py        # optional, see "Rescued" below
    uv run python baselines/openevolve/two_phase_results.py
    uv run python baselines/openevolve/two_phase_results.py --group baselines/openevolve/runs/two_phase_haiku \
        --out baselines/openevolve/results/two_phase_haiku.csv

For every seed under the group directory, and for both phases, this takes OpenEvolve's best program
at each checkpoint (checkpoint interval 1, so after every iteration), runs it once in OpenEvolve's
own virtual environment and scores the packing it returns. No API calls are made.

<out>.csv: one row per (seed, phase, checkpoint), in the order the money was spent:

    seed, phase, iteration            which run and checkpoint (iteration 0 of phase 1 is the initial program)
    cumulative_requests               billed requests so far, phase 1 and phase 2 together
    cumulative_dollars                the same in USD (claude-haiku-4-5 list price)
    openevolve_score                  `sum_radii` as OpenEvolve's own evaluator recorded it (tolerance 1e-6)
    repaired_strict_score             the same program's packing, made exactly feasible by `repair.py`
                                      (radii shrunk, never enlarged) and scored by the strict
                                      evaluator; empty if the program failed when re-run
    best_so_far_repaired_score        running maximum of repaired_strict_score within the seed
    cumulative_tokens, raw_strict_score, raw_strict_valid, rerun_sum_radii, program_sha256,
    program_wall_s, program_cpu_s, evaluator_timeout_s, openevolve_eval_time_s, within_shipped_time_limit

`raw_strict_score` is the strict evaluator's verdict on the packing exactly as the program returned
it. `rerun_sum_radii` is the plain sum of the radii of the re-run, to compare with
`openevolve_score`: they differ when a program is not deterministic. `evaluator_timeout_s` is
OpenEvolve's evaluation limit (wall seconds) in force when the checkpoint was written.

"Best so far" ranges over the programs that were OpenEvolve's best at some checkpoint, i.e. the
programs a user of OpenEvolve would have taken away.

Rescued. If rescue_timeouts.py has been run, <out stem>_rescued_timeouts.csv lists every program
OpenEvolve discarded because its evaluation timed out, with the strict score (after repair) of its
offline re-run under a CPU-time limit, the CPU seconds it needed, the best score OpenEvolve had at
that moment, and whether the program would have been a new best. The summary then gives each seed's
best score three ways:

    as run          whatever OpenEvolve's best programs were, under the limits actually in force
    with rescued    the same, plus every timed-out program that finished offline
    shipped limits  only programs that OpenEvolve's shipped limits (60 s, then 90 s) would have let
                    through on an idle machine: as-run best programs whose own evaluation took no
                    longer than that or which need no more CPU seconds than that, plus rescued
                    programs that need no more CPU seconds than that. This is the number that neither
                    penalises OpenEvolve for the machine load nor credits it for a raised limit.

<out stem>_summary.json has all of this per seed and over seeds; the table is also printed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
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


def epoch(stamp: str) -> float:
    return time.mktime(time.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))


def timeout_schedule(run: Path, manifest: dict, phase: str) -> list[tuple[float, float]]:
    """[(time from which it applies, OpenEvolve's evaluator.timeout in seconds)] for one phase, in order."""
    changes = [c for c in manifest.get("changes_during_run", [])
               if c.get("phase") == phase and c.get("setting") == "evaluator.timeout"]
    if changes:
        return [(0.0, float(changes[0]["before"]))] + [(epoch(c["applied"]), float(c["after"])) for c in changes]
    config = run / phase / "config.yaml"
    found = re.search(r"^evaluator:.*?^\s+timeout:\s*([\d.]+)", config.read_text(), re.S | re.M) if config.exists() else None
    return [(0.0, float(found.group(1)) if found else 300.0)]


def timeout_at(schedule: list[tuple[float, float]], when: float | None) -> float:
    value = schedule[0][1]
    for start, seconds in schedule:
        if when is not None and when >= start:
            value = seconds
    return value


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
                     "program": program, "openevolve_score": info.get("metrics", {}).get("sum_radii"),
                     "eval_time": info.get("metrics", {}).get("eval_time"), "saved_at": info.get("saved_at")})
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
              "error": entry["error"], "wall": entry.get("wall"), "cpu": entry.get("cpu")}
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


def first_passed(events: list[tuple[float, int, str, int, float]]) -> dict:
    """events: (dollars, requests, phase, iteration, best so far), in spend order -> where each level was first passed."""
    passed = {}
    for threshold in THRESHOLDS:
        hit = next((e for e in events if e[4] >= threshold), None)
        passed[str(threshold)] = None if hit is None else {"dollars": hit[0], "requests": hit[1], "phase": hit[2],
                                                           "iteration": hit[3]}
    return passed


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
        seeds[seed] = {"manifest": manifest, "phase_usage": {}, "phase_iterations": {}, "schedule": {}, "lost": 0}
        rows.append({"seed": seed, "phase": "phase1", "iteration": 0, "usage": ZERO,
                     "program": EXAMPLE / "initial_program.py", "openevolve_score": None, "eval_time": 0.0,
                     "saved_at": None})
        before = ZERO
        for phase in ("phase1", "phase2"):
            output_dir = run / phase / "openevolve_output"
            if not output_dir.exists():
                continue
            seeds[seed]["schedule"][phase] = timeout_schedule(run, manifest, phase)
            rows += checkpoint_rows(seed, phase, output_dir, before)
            usage = parse_usage(output_dir)
            before = add_usage(before, usage["total"])
            seeds[seed]["phase_usage"][phase] = usage["total"]
            seeds[seed]["phase_iterations"][phase] = usage["iterations_logged"]
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
            if done % 5 == 0 or done == len(todo):
                cache_path.write_text(json.dumps(cache) + "\n")
                print(f"  re-ran {done}/{len(todo)} programs ({time.time() - started:.0f}s)", flush=True)
    scores = {sha: score(cache[sha], evaluator) for sha in {r["sha"] for r in rows}}

    # The combined CSV.
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    best: dict[int, float] = {}
    fields = ["seed", "phase", "iteration", "cumulative_requests", "cumulative_dollars", "openevolve_score",
              "repaired_strict_score", "best_so_far_repaired_score", "cumulative_tokens", "raw_strict_score",
              "raw_strict_valid", "rerun_sum_radii", "program_sha256", "program_wall_s", "program_cpu_s",
              "evaluator_timeout_s", "openevolve_eval_time_s", "within_shipped_time_limit"]
    table = []
    for row in rows:
        result = scores[row["sha"]]
        repaired = result["repaired"]
        if repaired is not None:
            best[row["seed"]] = max(best.get(row["seed"], -math.inf), repaired)
        openevolve_score = row["openevolve_score"] if row["openevolve_score"] is not None else result["rerun_sum"]
        schedule = seeds[row["seed"]]["schedule"].get(row["phase"], [(0.0, 0.0)])
        shipped = schedule[0][1]
        # Would OpenEvolve's shipped limit have let this program through on an idle machine? Yes if its own
        # evaluation took no longer than that (wall time, under whatever load there was), or if a re-run
        # needs no more CPU seconds than that.
        fits = ((row["eval_time"] is not None and row["eval_time"] <= shipped)
                or (result["cpu"] is not None and repaired is not None and result["cpu"] <= shipped))
        table.append({
            "seed": row["seed"], "phase": row["phase"].removeprefix("phase"), "iteration": row["iteration"],
            "cumulative_requests": row["usage"]["requests"], "cumulative_dollars": f"{row['usage']['usd']:.6f}",
            "openevolve_score": "" if openevolve_score is None else repr(float(openevolve_score)),
            "repaired_strict_score": "" if repaired is None else repr(repaired),
            "best_so_far_repaired_score": "" if row["seed"] not in best else repr(best[row["seed"]]),
            "cumulative_tokens": row["usage"]["tokens"], "raw_strict_score": repr(result["raw_strict_score"]),
            "raw_strict_valid": result["raw_strict_valid"],
            "rerun_sum_radii": "" if result["rerun_sum"] is None else repr(result["rerun_sum"]),
            "program_sha256": row["sha"][:16], "program_wall_s": result["wall"], "program_cpu_s": result["cpu"],
            "evaluator_timeout_s": f"{timeout_at(schedule, row['saved_at']):g}",
            "openevolve_eval_time_s": "" if row["eval_time"] is None else f"{row['eval_time']:.1f}",
            "within_shipped_time_limit": fits,
            "_saved_at": row["saved_at"],
        })
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(table)

    # Programs that timed out, re-run offline by rescue_timeouts.py.
    rescue_path = group / "rescue_cache.json"
    rescue = json.loads(rescue_path.read_text()) if rescue_path.exists() else {}
    rescued = []
    for entry in sorted(rescue.values(), key=lambda e: (e["seed"], e["phase"], e["timestamp"] or 0)):
        seed, phase = entry["seed"], entry["phase"].removeprefix("phase")
        if seed not in seeds:
            continue
        mine = [r for r in table if r["seed"] == seed and r["best_so_far_repaired_score"] != ""]
        when = entry["timestamp"]
        earlier = [r for r in mine if r["_saved_at"] is None or (when is not None and r["_saved_at"] < when)]
        own = next((r for r in mine if r["phase"] == phase and r["_saved_at"] is not None and when is not None
                    and r["_saved_at"] >= when), earlier[-1] if earlier else mine[0])
        best_before = max((float(r["best_so_far_repaired_score"]) for r in earlier), default=-math.inf)
        result = score({"packing": entry["packing"], "error": entry["error"], "wall": entry["wall_s"],
                        "cpu": entry["cpu_s"]}, evaluator)
        schedule = seeds[seed]["schedule"][entry["phase"]]
        original_limit = schedule[0][1]
        value = result["repaired"]
        rescued.append({
            "seed": seed, "phase": phase, "iteration": entry["iteration"],
            "evaluator_timeout_s": f"{timeout_at(schedule, when):g}",
            "cumulative_requests": own["cumulative_requests"], "cumulative_dollars": own["cumulative_dollars"],
            "finished_offline": entry["packing"] is not None, "cpu_s": entry["cpu_s"], "wall_s": entry["wall_s"],
            "cpu_limit_s": entry["cpu_limit"],
            "within_original_limit_cpu": entry["packing"] is not None and entry["cpu_s"] <= original_limit,
            "rerun_sum_radii": "" if result["rerun_sum"] is None else repr(result["rerun_sum"]),
            "repaired_strict_score": "" if value is None else repr(value),
            "as_run_best_at_the_time": repr(best_before),
            "new_best_at_the_time": value is not None and value > best_before,
            "above_final_as_run_best": value is not None and value > best.get(seed, math.inf),
            "program_id": entry["id"], "code_file": entry["code_file"], "error": entry["error"],
        })
    rescued_path = out.with_name(out.stem + "_rescued_timeouts.csv")
    if rescued:
        with rescued_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rescued[0].keys()))
            writer.writeheader()
            writer.writerows(rescued)

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

        as_run_events = [(float(r["cumulative_dollars"]), r["cumulative_requests"], r["phase"], r["iteration"],
                          float(r["best_so_far_repaired_score"])) for r in mine if r["best_so_far_repaired_score"] != ""]
        manifest = info["manifest"]
        phases = manifest.get("phases", {})
        entry = {
            "best_repaired_after_phase1": best_after("1"),
            "best_repaired_after_phase2": best_after("2") if "phase2" in info["phase_usage"] else None,
            "openevolve_best_phase1": openevolve_after("1"), "openevolve_best_phase2": openevolve_after("2"),
            "requests": info["total"]["requests"], "dollars": info["total"]["usd"], "tokens": info["total"]["tokens"],
            "requests_by_phase": {k: v["requests"] for k, v in info["phase_usage"].items()},
            "dollars_by_phase": {k: v["usd"] for k, v in info["phase_usage"].items()},
            "iterations_by_phase": info["phase_iterations"], "iterations_lost_to_api_errors": info["lost"],
            "wall_seconds": manifest.get("wall_seconds"),
            "wall_seconds_by_phase": {k: v.get("wall_seconds") for k, v in phases.items()},
            "stopped": manifest.get("stopped"), "changes_during_run": manifest.get("changes_during_run", []),
            "first_passed": first_passed(as_run_events),
        }
        if rescue:
            timed = [r for r in rescued if r["seed"] == seed]
            done = [r for r in timed if r["repaired_strict_score"] != ""]
            fair = [r for r in done if r["within_original_limit_cpu"]]
            final = entry["best_repaired_after_phase2"] or entry["best_repaired_after_phase1"]
            limits = sorted({r["evaluator_timeout_s"] for r in timed}, key=float)
            entry["timed_out_programs"] = {
                "count": len(timed), "by_limit_in_force_s": {k: sum(1 for r in timed if r["evaluator_timeout_s"] == k) for k in limits},
                "finished_offline": len(done), "finished_within_original_limit_cpu": len(fair),
                "new_best_at_the_time": sum(1 for r in done if r["new_best_at_the_time"]),
                "new_best_at_the_time_within_original_limit_cpu": sum(1 for r in fair if r["new_best_at_the_time"]),
                "above_final_as_run_best": sum(1 for r in done if r["above_final_as_run_best"]),
                "best_rescued_score": max((float(r["repaired_strict_score"]) for r in done), default=None),
                "best_rescued_score_within_original_limit_cpu": max((float(r["repaired_strict_score"]) for r in fair), default=None),
            }
            # "with_rescued": everything as run, plus the timed-out programs that finished offline.
            # "shipped_limit": only programs that OpenEvolve's shipped time limits would have let through on
            # an idle machine: as-run best programs that fit them, plus rescued programs that fit them.
            own = [(float(r["cumulative_dollars"]), r["cumulative_requests"], r["phase"], r["iteration"],
                    float(r["repaired_strict_score"])) for r in mine if r["repaired_strict_score"] != ""]
            fitting = [(float(r["cumulative_dollars"]), r["cumulative_requests"], r["phase"], r["iteration"],
                        float(r["repaired_strict_score"])) for r in mine
                       if r["repaired_strict_score"] != "" and r["within_shipped_time_limit"]]
            for name, base, pool in (("with_rescued", own, done), ("shipped_limit", fitting, fair)):
                events = sorted(base + [(float(r["cumulative_dollars"]), r["cumulative_requests"], r["phase"],
                                         r["iteration"], float(r["repaired_strict_score"])) for r in pool])
                running, merged = -math.inf, []
                for e in events:
                    running = max(running, e[4])
                    merged.append((e[0], e[1], e[2], e[3], running))
                entry[f"best_repaired_after_phase2_{name}"] = running if merged else None
                entry[f"first_passed_{name}"] = first_passed(merged)
        summary["seeds"][str(seed)] = entry

    def spread(key: str):
        values = [s.get(key) for s in summary["seeds"].values() if s.get(key) is not None]
        if not values:
            return None
        return {"n": len(values), "mean": statistics.fmean(values), "min": min(values), "max": max(values),
                "sd": statistics.stdev(values) if len(values) > 1 else 0.0}

    keys = ["best_repaired_after_phase1", "best_repaired_after_phase2", "best_repaired_after_phase2_with_rescued",
            "best_repaired_after_phase2_shipped_limit", "requests", "dollars", "wall_seconds"]
    summary["over_seeds"] = {key: spread(key) for key in keys if spread(key) is not None}
    summary["total_dollars"] = round(sum(s["dollars"] for s in summary["seeds"].values()), 6)
    if rescued:
        summary["rescued_timeouts_csv"] = str(rescued_path)
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
        sp = summary["over_seeds"].get(key)
        if sp:
            print(f"{key}: mean {sp['mean']:.6f}, sd {sp['sd']:.6f}, min {sp['min']:.6f}, max {sp['max']:.6f} (n={sp['n']})")
    if rescue:
        print(f"\ntimed-out programs re-run offline ({rescued_path.name}):")
        print(f"{'seed':>4s} {'timed out':>9s} {'finished':>9s} {'<= limit CPU':>12s} {'new best then':>13s} {'> final best':>12s} "
              f"{'as run':>10s} {'with rescued':>13s} {'shipped limits only':>20s}")
        for seed, s in summary["seeds"].items():
            t = s["timed_out_programs"]
            print(f"{seed:>4s} {t['count']:>9d} {t['finished_offline']:>9d} {t['finished_within_original_limit_cpu']:>12d} "
                  f"{t['new_best_at_the_time']:>13d} {t['above_final_as_run_best']:>12d} "
                  f"{show(s['best_repaired_after_phase2']):>10s} {show(s['best_repaired_after_phase2_with_rescued']):>13s} "
                  f"{show(s['best_repaired_after_phase2_shipped_limit']):>20s}")
        for key in ("best_repaired_after_phase2_with_rescued", "best_repaired_after_phase2_shipped_limit"):
            sp = summary["over_seeds"].get(key)
            if sp:
                print(f"{key}: mean {sp['mean']:.6f}, sd {sp['sd']:.6f}, min {sp['min']:.6f}, max {sp['max']:.6f}")
    print(f"total: ${summary['total_dollars']:.2f}   best known {BEST_KNOWN}")
    print(f"{len(table)} rows -> {out}\nsummary -> {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
