#!/usr/bin/env python3
"""Fixed wrapper written by `mendel explain`. Do not edit it: the harness checks its hash and restores it.

Solver contract (PROTOCOL.md):
    python solver.py --config CFG.json --instance INSTANCE.json --seed N (--time S | --iters N) --out OUT.json

It seeds the global random generators (`random`, `numpy.random`) with the run seed, calls
program.construct(cfg, n, seed) and finishes, in every configuration, with repair.repair(): the radii-only
repair of the Mendel seed solver and of baselines/openevolve/repair.py, so the output is strictly feasible
under the exact evaluator. Both programs are constructors that run to completion, so the budget is accepted
and ignored; the output is deterministic under --iters as long as program.py does not read the clock.
If program.construct raises, or its output cannot be repaired, the run fails (exit 1) instead of inventing
a packing: a made-up fallback would be measured as if it were the configuration's result.
`stats.raw` is the packing before the repair.
"""
from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
              "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--seed", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--time", type=float)
    group.add_argument("--iters", type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    cfg = {g["name"]: g["default"] for g in json.loads((HERE / "genes.json").read_text())["genes"]}
    cfg.update(json.loads(Path(args.config).read_text()))
    n = int(json.loads(Path(args.instance).read_text())["n"])

    from repair import repair

    random.seed(args.seed)
    np.random.seed(args.seed % 2**32)
    import program

    random.seed(args.seed)
    np.random.seed(args.seed % 2**32)
    centers, radii = program.construct(cfg, n, args.seed)[:2]
    centers = np.asarray(centers, dtype=float).reshape(-1, 2)
    radii = np.asarray(radii, dtype=float).reshape(-1)
    raw = [[float(c[0]), float(c[1]), float(r)] for c, r in zip(centers, radii)]
    if len(raw) != n:
        print(f"program.construct returned {len(raw)} circles, expected {n}", file=sys.stderr)
        return 1
    solution = repair(raw)
    if solution is None:
        print("the packing could not be repaired (non-finite values, or radii wrong by more than rounding)",
              file=sys.stderr)
        return 1
    out = {"solution": solution, "stats": {"iters": 0, "trace": [], "raw": raw}}
    tmp = Path(args.out + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
