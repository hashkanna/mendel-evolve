#!/usr/bin/env python3
"""Orbit case 0 (S contains the representative r_0 of the largest point orbit O_0) split by t = |S ∩ O_0|.
Exhaustive: r_0 in S gives t >= 1, and if all of O_0 lies on one sphere (asserted: O_0 is a hyperplane row)
a valid set has t <= 4.  Case 0 is refuted iff every sub-case t = 1..4 is INFEASIBLE.
Usage: refute_case0_split.py n K time_per_subcase [t ...]"""
import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refute import load_rows, point_orbits, run, HERE
n = int(sys.argv[1]); K = int(sys.argv[2]); tl = float(sys.argv[3])
ts = [int(v) for v in sys.argv[4:]] or [1, 2, 3, 4]
minsize = 9 if n >= 6 else 5
circles, hypers, pool = load_rows(n, None, minsize)
orbits = point_orbits(n)
O0 = tuple(orbits[0][1])
assert O0 in set(hypers), "O_0 must be the point set of a sphere row (then t <= 4)"
tag = "".join(str(t) for t in ts)
out = os.path.join(HERE, f"refute_n{n}_K{K}_case0_split_t{tag}.json")
subs = []
for t in ts:
    r = run(n, K, circles, hypers, "orbit", tl, 1, {}, case=0, orbits=orbits, pool=pool, implied_layers=True, count_eq=(O0, t))
    r["t"] = t
    subs.append(r)
    print(f"[n={n} K={K} case 0, |S ∩ O_0| = {t}] {r['status']} {r['wall_seconds']}s conflicts={r['conflicts']}", flush=True)
    json.dump({"n": n, "K": K, "case": 0, "subcases": subs, "rows": {"circles": len(circles), "hyperplanes": len(hypers), "min_hyper_size": minsize}}, open(out, "w"), indent=1)
