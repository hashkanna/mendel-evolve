#!/usr/bin/env python3
"""Lower-bound search: find a valid set of size exactly K by lazy row generation, then verify it with the
exact 5-subset determinant checker.  Only the final exact check matters for the lower-bound claim."""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from no5sphere_exact import grid, exact_check, HERE
from ortools.sat.python import cp_model

n = int(sys.argv[1]); K = int(sys.argv[2]); budget = float(sys.argv[3]); minsize = int(sys.argv[4]) if len(sys.argv) > 4 else 9
d = json.load(open(os.path.join(HERE, f"rows_n{n}.json")))
pts = grid(n); N = len(pts)
base = [(tuple(r), 3) for r in d["circles"]] + [(tuple(h), 4) for h in d["hypers"] if len(h) >= minsize]
pool = [tuple(h) for h in d["hypers"] if len(h) < minsize]
pool_masks = [sum(1 << i for i in h) for h in pool]
m = cp_model.CpModel()
x = [m.NewBoolVar(f"x_{i}") for i in range(N)]
for row, rhs in base:
    m.Add(sum(x[i] for i in row) <= rhs)
m.Add(sum(x) == K)
t0 = time.time(); rounds = 0; added = 0; seed = 0
while time.time() - t0 < budget:
    rounds += 1
    s = cp_model.CpSolver()
    s.parameters.num_workers = 1
    s.parameters.random_seed = rounds
    s.parameters.max_time_in_seconds = max(1.0, budget - (time.time() - t0))
    st = s.Solve(m)
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        print("solver status", s.StatusName(st), "after", rounds, "rounds", flush=True)
        break
    S = [i for i in range(N) if s.Value(x[i])]
    smask = sum(1 << i for i in S)
    viol = [pool[j] for j, pm in enumerate(pool_masks) if (pm & smask).bit_count() > 4]
    if not viol:
        sol = [pts[i].tolist() for i in S]
        ok, det = exact_check(sol, n)
        print("round", rounds, "candidate size", len(sol), "exact_check", ok, det, flush=True)
        if ok:
            json.dump({"n": n, "solution": sol, "method": "CP-SAT feasibility with lazy rows", "rounds": rounds, "lazy_rows_added": added,
                       "wall_seconds": round(time.time() - t0, 2), "exact_check": det}, open(os.path.join(HERE, f"lb_n{n}_{K}.json"), "w"))
            print("FOUND verified set of size", K, "for n =", n, sol, flush=True)
        break
    for row in viol:
        m.Add(sum(x[i] for i in row) <= 4)
    added += len(viol)
    print("round", rounds, "violated rows added", len(viol), "total", added, "t", round(time.time() - t0, 1), flush=True)
