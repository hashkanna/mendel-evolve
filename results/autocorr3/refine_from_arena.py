#!/usr/bin/env python3
"""REFINEMENT of a downloaded arena solution (NOT a from-scratch result). Run from the project root:

    uv run python results/autocorr3/refine_from_arena.py --n 32768 --time 300 --out runs/autocorr3-refine/x.json

Loads solution number --rank (0 = the top one) from results/autocorr3/arena/best_problem4_top5.json,
resamples it to --n steps (exact repetition for multiples of its length, block averages otherwise),
and continues with the descent stage of solvers/autocorr3/solver.py from there. Anything this finds
is "an improvement of someone else's construction" and is labelled as such in the output file.
"""
import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "solvers/autocorr3"))
import solver as sv  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, required=True)
    p.add_argument("--time", type=float, required=True)
    p.add_argument("--rank", type=int, default=0)
    p.add_argument("--beta0", type=float, default=2e5)
    p.add_argument("--growth", type=float, default=2.0)
    p.add_argument("--stage-evals", type=int, default=400)
    p.add_argument("--polish", action="store_true")
    p.add_argument("--out", required=True)
    args = p.parse_args()

    spec = importlib.util.spec_from_file_location("ac3_evaluate", ROOT / "problems/autocorr3/evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)

    item = json.loads((ROOT / "results/autocorr3/arena/best_problem4_top5.json").read_text())[args.rank]
    source = np.array(item["data"]["values"], dtype=float)
    x = sv.resample(source, args.n)
    x = x * (args.n / x.sum())
    start = ev.evaluate({"n": args.n}, x.tolist())["score"]
    print(f"source: arena solution {item['id']} by {item['agentName']}, {len(source)} steps, arena score {item['score']!r}")
    print(f"resampled to {args.n} steps: {start!r}", flush=True)

    cfg = sv.load_config(None)
    cfg.update({"beta_growth": args.growth, "stage_evals": args.stage_evals})
    budget = sv.Budget(time.process_time() + args.time, None)
    best = sv.Best()
    grid = sv.Grid(args.n)
    best.offer(x, grid.score(x))
    beta = args.beta0
    try:
        if args.polish:
            sv.polish(x, grid, 2.0, cfg, budget, best)
        while True:
            x, beta = sv.descend(sv.resample(best.x, args.n), grid, beta, 2.0, cfg, budget, best)
    except sv.Stop:
        pass
    x = best.x * (args.n / best.x.sum())
    solution = [float(v) for v in x]
    result = ev.evaluate({"n": args.n}, solution)
    print(f"after {args.time:.0f} CPU s ({budget.done} evaluations): {result['score']!r}  (change {result['score'] - start:+.3e})")
    Path(args.out).write_text(json.dumps({
        "problem": "autocorr3", "instance": {"n": args.n}, "score": result["score"], "solution": solution,
        "provenance": f"REFINED from arena solution {item['id']} by {item['agentName']} (arena score {item['score']!r}); not found from scratch",
        "start_score_after_resampling": start, "budget_cpu_seconds": args.time,
        "found": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
