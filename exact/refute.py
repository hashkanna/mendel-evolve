#!/usr/bin/env python3
"""Refutation runs: prove C(n) <= K-1 by showing that the model plus `sum x >= K` is INFEASIBLE.

Modes of (sound) symmetry handling, never combined with each other:
  --mode plain   : no explicit symmetry breaking (CP-SAT's internal symmetry detection only)
  --mode faces   : face-count ordering (see README)
  --mode orbit   : orbital case split.  Point orbits O_1..O_k of the 48 cube symmetries (largest first).
                   Case j: "S contains no point of O_1..O_{j-1} and contains a point of O_j"; by symmetry
                   WLOG that point is the representative r_j.  The k cases cover every nonempty S.
"""
import argparse, json, os, sys, time
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from no5sphere_exact import grid, symmetries, enumerate_flats, exact_check, HERE


def load_rows(n, rows_file=None, min_hyper_size=5):
    """Any subset of the rows is a valid relaxation: INFEASIBLE verdicts stay sound.
    Returns (circles, hypers, pool) where pool holds the rows left out (added lazily when violated)."""
    if rows_file or min_hyper_size > 5:
        d = json.load(open(rows_file or os.path.join(HERE, f"rows_n{n}.json")))
        pool = [(tuple(h), 4) for h in d["hypers"] if len(h) < min_hyper_size]
        return [tuple(k) for k in d["circles"]], [tuple(h) for h in d["hypers"] if len(h) >= min_hyper_size], pool
    cache = os.path.join(HERE, f"rows_n{n}.json")
    if os.path.exists(cache):
        d = json.load(open(cache))
        return [tuple(k) for k in d["circles"]], [tuple(h) for h in d["hypers"]], []
    circles, hypers = enumerate_flats(n)
    json.dump({"n": n, "circles": circles, "hypers": hypers}, open(cache, "w"))
    return circles, hypers, []


def point_orbits(n):
    P = np.stack(symmetries(n), axis=0)
    N = P.shape[1]
    orbs = {}
    for i in range(N):
        orbs.setdefault(int(P[:, i].min()), set()).update(int(v) for v in P[:, i])
    out = sorted(orbs.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    return [(rep, sorted(o)) for rep, o in out]


def run(n, K, circles, hypers, mode, time_limit, workers, params, case=None, orbits=None, objective=False, pool=None, implied_layers=False, count_eq=None):
    """Solve the model (base rows) + `sum x >= K`.  If `pool` (extra valid rows: list of (row, rhs)) is given,
    rows violated by a relaxation solution are added lazily and the model is re-solved.  All rows are valid
    inequalities, so an INFEASIBLE answer at any stage proves that no valid set of size >= K exists (in this case)."""
    from ortools.sat.python import cp_model
    pts = grid(n)
    N = len(pts)
    m = cp_model.CpModel()
    x = [m.NewBoolVar(f"x_{i}") for i in range(N)]
    for Kc in circles:
        m.Add(sum(x[i] for i in Kc) <= 3)
    for H in hypers:
        m.Add(sum(x[i] for i in H) <= 4)
    if K is not None:
        m.Add(sum(x) >= K)
    if implied_layers and K is not None:
        # Implied (hence sound): every axis-parallel layer is a plane, so it holds <= 4 points of a valid
        # set; with |S| >= K and n layers per axis, each layer holds >= K - 4(n-1) points.
        for c in range(3):
            for v in range(n):
                lay = [x[i] for i in range(N) if pts[i][c] == v]
                m.Add(sum(lay) <= 4)
                if K - 4 * (n - 1) > 0:
                    m.Add(sum(lay) >= K - 4 * (n - 1))
    if mode == "faces":
        low = [sum(x[i] for i in range(N) if pts[i][c] == 0) for c in range(3)]
        high = [sum(x[i] for i in range(N) if pts[i][c] == n - 1) for c in range(3)]
        for c in range(3):
            m.Add(low[c] >= high[c])
        m.Add(low[0] >= low[1])
        m.Add(low[1] >= low[2])
    elif mode == "orbit":
        rep, _ = orbits[case]
        m.Add(x[rep] == 1)
        for j in range(case):
            for p in orbits[j][1]:
                m.Add(x[p] == 0)
    if count_eq is not None:
        # sub-case split: exactly t chosen points inside a given point set (caller proves exhaustiveness)
        for idxs, t in (count_eq if isinstance(count_eq, list) else [count_eq]):
            m.Add(sum(x[i] for i in idxs) == t)
    if objective:
        m.Maximize(sum(x))
    t0 = time.time()
    rounds = 0
    added = 0
    conflicts = 0
    while True:
        rounds += 1
        solver = cp_model.CpSolver()
        solver.parameters.num_workers = workers
        solver.parameters.max_time_in_seconds = max(1.0, float(time_limit) - (time.time() - t0))
        for k, v in params.items():
            setattr(solver.parameters, k, v)
        st = solver.Solve(m)
        conflicts += solver.NumConflicts()
        res = {"status": solver.StatusName(st), "conflicts": conflicts, "lazy_rounds": rounds, "lazy_rows_added": added}
        if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            S = set(i for i in range(N) if solver.Value(x[i]))
            sol = [pts[i].tolist() for i in sorted(S)]
            ok, det = exact_check(sol, n)
            res.update({"solution": sol, "size": len(sol), "exact_check": ok})
            if not ok:
                viol = [(row, rhs) for row, rhs in (pool or []) if sum(1 for i in row if i in S) > rhs]
                if viol and time.time() - t0 < time_limit:
                    for row, rhs in viol:
                        m.Add(sum(x[i] for i in row) <= rhs)
                    added += len(viol)
                    continue
                res["status"] = "RELAXATION_FEASIBLE_ONLY"
        if objective:
            res["best_bound"] = solver.BestObjectiveBound()
        res["wall_seconds"] = round(time.time() - t0, 2)
        return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--K", type=int, nargs="+", required=True, help="thresholds to refute, tried in the given order")
    ap.add_argument("--mode", choices=["plain", "faces", "orbit"], default="orbit")
    ap.add_argument("--time", type=float, default=300, help="time limit per solve")
    ap.add_argument("--workers", type=int, default=1)
    ap.add_argument("--param", action="append", default=[], help="cp-sat parameter name=int")
    ap.add_argument("--out", type=str, default=None)
    ap.add_argument("--rows-file", type=str, default=None)
    ap.add_argument("--cases", type=int, nargs="*", default=None, help="orbit mode: only these case indices (results must be merged with the other cases)")
    ap.add_argument("--implied-layers", action="store_true", help="add implied per-layer bounds (sound, see code)")
    ap.add_argument("--min-hyper-size", type=int, default=5, help="relaxation: keep only hyperplane rows with >= this many points")
    args = ap.parse_args()
    assert args.workers <= 3
    params = {}
    for p in args.param:
        k, v = p.split("=")
        params[k] = int(v)
    n = args.n
    circles, hypers, pool = load_rows(n, args.rows_file, args.min_hyper_size)
    print(f"[n={n}] rows used: circles={len(circles)} hyperplanes={len(hypers)} (min hyperplane size {args.min_hyper_size}, rows_file={args.rows_file})", flush=True)
    orbits = point_orbits(n) if args.mode == "orbit" else None
    log = []
    for K in args.K:
        t0 = time.time()
        if args.mode == "orbit":
            cases = []
            verdict = "INFEASIBLE"
            for j in (args.cases if args.cases is not None else range(len(orbits))):
                r = run(n, K, circles, hypers, "orbit", args.time, args.workers, params, case=j, orbits=orbits, pool=pool, implied_layers=args.implied_layers)
                r["case"] = j; r["rep"] = orbits[j][0]; r["orbit_size"] = len(orbits[j][1])
                cases.append(r)
                print(f"[n={n} K={K} orbit-case {j} rep={orbits[j][0]} |O|={len(orbits[j][1])}] {r['status']} {r['wall_seconds']}s conflicts={r['conflicts']} lazy_rounds={r['lazy_rounds']} lazy_rows={r['lazy_rows_added']}", flush=True)
                if r["status"] != "INFEASIBLE":
                    verdict = r["status"]
                    break
            entry = {"n": n, "K": K, "mode": "orbit", "verdict": verdict, "cases": cases, "cases_run": (args.cases if args.cases is not None else list(range(len(orbits)))), "num_orbit_cases": len(orbits), "implied_layers": args.implied_layers}
            if args.cases is not None and sorted(args.cases) != list(range(len(orbits))):
                entry["partial"] = True
        else:
            r = run(n, K, circles, hypers, args.mode, args.time, args.workers, params, pool=pool, implied_layers=args.implied_layers)
            entry = {"n": n, "K": K, "mode": args.mode, "verdict": r["status"], "cases": [r]}
        entry["wall_seconds"] = round(time.time() - t0, 2)
        entry["workers"] = args.workers; entry["params"] = params; entry["time_limit_per_solve"] = args.time
        entry["rows"] = {"circles": len(circles), "hyperplanes": len(hypers), "min_hyper_size": args.min_hyper_size, "rows_file": args.rows_file}
        if entry["verdict"] == "INFEASIBLE" and not entry.get("partial"):
            entry["proves"] = f"C({n}) <= {K-1}"
        print(f"== n={n} K={K} mode={args.mode} verdict={entry['verdict']} wall={entry['wall_seconds']}s" + (f"  => PROVEN {entry['proves']}" if "proves" in entry else (" (PARTIAL: only cases %s)" % entry.get("cases_run") if entry.get("partial") else "")), flush=True)
        log.append(entry)
        if args.out:
            json.dump(log, open(args.out, "w"), indent=1)
        if entry["verdict"] != "INFEASIBLE":
            break


if __name__ == "__main__":
    main()
