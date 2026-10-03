#!/usr/bin/env python3
"""Second-level split of orbit case 0, sub-case t = |S ∩ O_0| (fixed), by u = |S ∩ O_1| in {0..4}.
Exhaustive because O_1 is the point set of a sphere row (asserted), so a valid set has u <= 4.
Usage: refute_case0_split2.py n K time t u [u ...]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refute import load_rows, point_orbits, run, HERE
n = int(sys.argv[1]); K = int(sys.argv[2]); tl = float(sys.argv[3]); t = int(sys.argv[4]); us = [int(v) for v in sys.argv[5:]]
minsize = 9 if n >= 6 else 5
circles, hypers, pool = load_rows(n, None, minsize)
orbits = point_orbits(n)
O0 = tuple(orbits[0][1]); O1 = tuple(orbits[1][1])
hs = set(hypers)
assert O0 in hs and O1 in hs, "O_0 and O_1 must each be the point set of a sphere row"
out = os.path.join(HERE, f"refute_n{n}_K{K}_case0_split2_t{t}_u{''.join(map(str, us))}.json")
subs = []
for u in us:
    r = run(n, K, circles, hypers, "orbit", tl, 1, {}, case=0, orbits=orbits, pool=pool, implied_layers=True, count_eq=[(O0, t), (O1, u)])
    r["t"] = t; r["u"] = u
    subs.append(r)
    print(f"[n={n} K={K} case 0, |S ∩ O_0| = {t}, |S ∩ O_1| = {u}] {r['status']} {r['wall_seconds']}s conflicts={r['conflicts']}", flush=True)
    json.dump({"n": n, "K": K, "case": 0, "t": t, "subcases": subs, "rows": {"circles": len(circles), "hyperplanes": len(hypers), "min_hyper_size": minsize}}, open(out, "w"), indent=1)
