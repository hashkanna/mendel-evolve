#!/usr/bin/env python3
"""Third-level split of orbit case 0, sub-case (t, u) = (|S ∩ O_0|, |S ∩ O_1|) fixed, by v = |S ∩ O_2| in {0..4}.
Exhaustive because O_2 is the point set of a sphere row (asserted), so a valid set has v <= 4.
If all five v are INFEASIBLE, writes a split2-format file recording (t, u) as INFEASIBLE.
Usage: refute_case0_split3.py n K time t u [v ...]"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from refute import load_rows, point_orbits, run, HERE
n = int(sys.argv[1]); K = int(sys.argv[2]); tl = float(sys.argv[3]); t = int(sys.argv[4]); u = int(sys.argv[5])
vs = [int(v) for v in sys.argv[6:]] or [0, 1, 2, 3, 4]
minsize = 9 if n >= 6 else 5
circles, hypers, pool = load_rows(n, None, minsize)
orbits = point_orbits(n)
O0, O1, O2 = (tuple(orbits[j][1]) for j in range(3))
hs = set(hypers)
assert O0 in hs and O1 in hs and O2 in hs, "O_0, O_1, O_2 must each be the point set of a sphere row"
tag = "".join(map(str, vs))
log = os.path.join(HERE, f"refute_n{n}_K{K}_case0_level3_t{t}_u{u}_v{tag}.json")
subs = []
for v in vs:
    r = run(n, K, circles, hypers, "orbit", tl, 1, {}, case=0, orbits=orbits, pool=pool, implied_layers=True, count_eq=[(O0, t), (O1, u), (O2, v)])
    r["t"] = t; r["u"] = u; r["v"] = v
    subs.append(r)
    print(f"[n={n} K={K} case 0, counts in O_0,O_1,O_2 = {t},{u},{v}] {r['status']} {r['wall_seconds']}s conflicts={r['conflicts']}", flush=True)
    json.dump({"n": n, "K": K, "case": 0, "t": t, "u": u, "level3_subcases": subs}, open(log, "w"), indent=1)
if sorted(vs) == [0, 1, 2, 3, 4] and all(s["status"] == "INFEASIBLE" for s in subs):
    agg = {"status": "INFEASIBLE", "t": t, "u": u, "wall_seconds": round(sum(s["wall_seconds"] for s in subs), 2), "conflicts": sum(s["conflicts"] for s in subs),
           "derived_from_level3_split_over_v": [{k: s[k] for k in ("v", "status", "wall_seconds", "conflicts")} for s in subs]}
    json.dump({"n": n, "K": K, "case": 0, "t": t, "subcases": [agg], "rows": {"circles": len(circles), "hyperplanes": len(hypers), "min_hyper_size": minsize}},
              open(os.path.join(HERE, f"refute_n{n}_K{K}_case0_split2_t{t}_u{u}_via_level3.json"), "w"), indent=1)
    print(f"== (t,u)=({t},{u}) refuted via all five v", flush=True)
