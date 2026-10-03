#!/usr/bin/env python3
"""Re-score an OpenEvolve run with Mendel's strict evaluator.

    uv run python baselines/openevolve/rescore.py baselines/openevolve/runs/iter100_seed1

For the initial program (iteration 0), for the best program at every checkpoint and for the final
best program, this runs the program (in OpenEvolve's own virtual environment), takes the packing
that `run_packing()` returns and scores it with problems/circle_packing/evaluate.py: exact rational
arithmetic, no tolerance, radii strictly positive. OpenEvolve's own evaluator accepts overlaps of
up to 1e-6 and radii of zero, so its `sum_radii` can be higher than anything that is really feasible.

Output: <run>/strict_scores.csv, one row per checkpoint, with the columns

    iteration, requests, tokens, dollars, strict_score          the comparison: cost so far, strict score
    prompt_tokens, completion_tokens                            the split behind `tokens` and `dollars`
    strict_valid, strict_reason                                 why a packing was rejected
    openevolve_sum_radii                                        what OpenEvolve's tolerant evaluator reported
    repaired_score                                              strict score after Mendel's `finalise` (see below)
    program_sha256, program_wall_s, program_cpu_s               which program, and what running it cost

`strict_score` is 0 for a packing that fails the exact test. `repaired_score` answers "what is this
packing worth once it is made feasible": the same centres are passed through the Mendel solver's
`finalise` (coincident centres separated, radii shrunk until the exact test passes), so every row
gets a number that is comparable with a Mendel score. No API calls are made.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from common import EXAMPLE, ROOT, VENV_PYTHON, parse_usage

N = 26
DRIVER = r'''
import importlib.util, json, sys
import numpy as np
spec = importlib.util.spec_from_file_location("program", sys.argv[1])
program = importlib.util.module_from_spec(spec)
spec.loader.exec_module(program)
centers, radii, _ = program.run_packing()
centers = np.asarray(centers, dtype=float).reshape(-1, 2)
radii = np.asarray(radii, dtype=float).reshape(-1)
with open(sys.argv[2], "w") as f:
    json.dump([[float(c[0]), float(c[1]), float(r)] for c, r in zip(centers, radii)], f)
'''


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_program(program: Path, timeout: float) -> tuple[list | None, str, float, float]:
    """Run `run_packing()` of a program in a subprocess. Returns (packing, error, wall seconds, CPU seconds)."""
    env = dict(os.environ, MPLBACKEND="Agg")
    env.pop("VIRTUAL_ENV", None)
    with tempfile.TemporaryDirectory() as tmp:
        driver, result = Path(tmp) / "driver.py", Path(tmp) / "packing.json"
        driver.write_text(DRIVER)
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        started = time.time()
        try:
            done = subprocess.run([str(VENV_PYTHON), str(driver), str(program), str(result)], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=timeout)
            error = "" if done.returncode == 0 else f"exit {done.returncode}: {done.stderr.strip()[-300:]}"
        except subprocess.TimeoutExpired:
            error = f"timed out after {timeout:g}s"
        wall = time.time() - started
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu = (after.ru_utime + after.ru_stime) - (before.ru_utime + before.ru_stime)
        packing = None
        if not error:
            try:
                packing = json.loads(result.read_text())
            except (OSError, ValueError) as exc:
                error = f"no packing written: {exc}"
    return packing, error, wall, cpu


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-score an OpenEvolve run with the strict evaluator (no API calls).")
    parser.add_argument("run", help="run directory written by run_openevolve.py")
    parser.add_argument("--timeout", type=float, default=600.0,
                        help="seconds allowed per program (OpenEvolve's evaluator allows 600 inside a 60 s evaluation)")
    parser.add_argument("--out", help="CSV path (default: <run>/strict_scores.csv)")
    args = parser.parse_args(argv)

    run = Path(args.run).resolve()
    output_dir = run / "openevolve_output"
    if not output_dir.exists():
        raise SystemExit(f"{output_dir} not found")
    evaluator = load_module(ROOT / "problems" / "circle_packing" / "evaluate.py", "strict_evaluate")
    solver = load_module(ROOT / "solvers" / "circle_packing" / "solver.py", "mendel_circle_solver")
    import numpy as np

    usage = parse_usage(output_dir)
    zero = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0, "tokens": 0, "usd": 0.0}

    # (label, program path, usage so far, OpenEvolve's metrics)
    stages: list[tuple[str, Path, dict, dict]] = [("0", EXAMPLE / "initial_program.py", zero, {})]
    checkpoints = sorted((output_dir / "checkpoints").glob("checkpoint_*"), key=lambda p: int(p.name.split("_")[-1]))
    for checkpoint in checkpoints:
        program = checkpoint / "best_program.py"
        if not program.exists():
            continue
        iteration = int(checkpoint.name.split("_")[-1])
        info = json.loads((checkpoint / "best_program_info.json").read_text()) if (checkpoint / "best_program_info.json").exists() else {}
        spent = usage["at_checkpoint"].get(str(iteration))
        if spent is None:  # checkpoint written without a log line (should not happen): count iterations up to it
            rows = [r for r in usage["by_iteration"] if r["iteration"] <= iteration]
            p, c = sum(r["prompt_tokens"] for r in rows), sum(r["completion_tokens"] for r in rows)
            spent = {"requests": len(rows), "prompt_tokens": p, "completion_tokens": c, "tokens": p + c,
                     "usd": round((p * usage["usd_per_mtok"]["input"] + c * usage["usd_per_mtok"]["output"]) / 1e6, 6)}
        stages.append((str(iteration), program, spent, info.get("metrics", {})))
    # Iterations finish out of order (4 run in parallel), so order the rows by what had been spent.
    stages[1:] = sorted(stages[1:], key=lambda stage: (stage[2]["requests"], int(stage[0])))
    final = output_dir / "best" / "best_program.py"
    if final.exists():
        info = json.loads((output_dir / "best" / "best_program_info.json").read_text()) if (output_dir / "best" / "best_program_info.json").exists() else {}
        stages.append(("final", final, usage["total"], info.get("metrics", {})))

    cache: dict[str, dict] = {}
    rows = []
    for label, program, spent, metrics in stages:
        digest = hashlib.sha256(program.read_bytes()).hexdigest()
        if digest not in cache:
            packing, error, wall, cpu = run_program(program, args.timeout)
            if packing is None:
                result = {"strict_score": 0.0, "strict_valid": False, "strict_reason": f"program failed: {error}",
                          "repaired_score": ""}
            else:
                verdict = evaluator.evaluate({"n": N}, packing)
                result = {"strict_score": verdict["score"], "strict_valid": verdict["valid"],
                          "strict_reason": "" if verdict["valid"] else verdict["detail"].get("reason", "")}
                try:
                    array = np.array(packing, dtype=float).reshape(-1, 3)
                    if len(array) != N:
                        raise ValueError(f"{len(array)} circles")
                    centers, radii = solver.finalise(array[:, :2], {}, radii=array[:, 2])
                    repaired = evaluator.evaluate({"n": N}, [[float(x), float(y), float(r)] for (x, y), r in zip(centers, radii)])
                    result["repaired_score"] = repaired["score"] if repaired["valid"] else ""
                except Exception as exc:  # noqa: BLE001 - a packing that cannot be repaired simply has no repaired score
                    result["repaired_score"] = ""
                    result["strict_reason"] = (result["strict_reason"] + f" | not repairable: {exc}").strip(" |")
            result.update({"program_wall_s": round(wall, 2), "program_cpu_s": round(cpu, 2)})
            cache[digest] = result
        result = cache[digest]
        rows.append({
            "iteration": label, "requests": spent["requests"], "tokens": spent["tokens"], "dollars": f"{spent['usd']:.6f}",
            "strict_score": repr(result["strict_score"]),
            "prompt_tokens": spent["prompt_tokens"], "completion_tokens": spent["completion_tokens"],
            "strict_valid": result["strict_valid"], "strict_reason": result["strict_reason"],
            "openevolve_sum_radii": metrics.get("sum_radii", ""),
            "repaired_score": repr(result["repaired_score"]) if result["repaired_score"] != "" else "",
            "program_sha256": digest[:16], "program_wall_s": result["program_wall_s"], "program_cpu_s": result["program_cpu_s"],
        })

    target = Path(args.out) if args.out else run / "strict_scores.csv"
    with target.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"{'iter':>5s} {'requests':>8s} {'tokens':>9s} {'dollars':>9s} {'strict':>12s} {'valid':>5s} {'openevolve':>12s} {'repaired':>12s}")
    last = None
    for row in rows:
        key = (row["program_sha256"], row["iteration"] == "final")
        if key == last and row is not rows[-1]:
            continue  # the table only shows rows where the best program changed; the CSV has every checkpoint
        last = key
        shown = lambda v: f"{float(v):.9f}" if v not in ("", None) else "-"  # noqa: E731
        print(f"{row['iteration']:>5s} {row['requests']:>8d} {row['tokens']:>9d} {float(row['dollars']):>9.4f} "
              f"{shown(row['strict_score']):>12s} {str(row['strict_valid']):>5s} {shown(row['openevolve_sum_radii']):>12s} "
              f"{shown(row['repaired_score']):>12s}")
    print(f"{len(rows)} rows, {len(cache)} distinct programs run -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
