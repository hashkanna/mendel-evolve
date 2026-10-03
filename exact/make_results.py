#!/usr/bin/env python3
"""Collect run outputs into results.json and RESULTS.md.  Re-checks every reported set with the
exact 5-subset determinant checker.  A value is 'exact' only if proven UB == verified LB."""
import glob, itertools, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from no5sphere_exact import exact_check, det5, HERE

PUBLIC_LB = {3: 8, 4: 11, 5: 14, 6: 18, 7: 21, 8: 23, 9: 26, 10: 28, 11: 31, 12: 33, 13: 36}


def project_evaluate(n, sol):
    """Second, independent check with the project's trusted evaluator (imported read-only), if present."""
    path = os.path.join(os.path.dirname(HERE), "problems", "no5sphere", "evaluate.py")
    if not os.path.exists(path):
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("no5sphere_evaluate", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.evaluate({"n": n}, sol)
    return {"valid": bool(r["valid"]), "score": r["score"]}


def load(name):
    p = os.path.join(HERE, name)
    return json.load(open(p)) if os.path.exists(p) else None


def main():
    res = {}
    # ---- n = 2 by hand: all 8 cube vertices are cospherical
    cube = list(itertools.product((0, 1), repeat=3))
    assert all(det5(*f) == 0 for f in itertools.combinations(cube, 5))
    s2 = [[0, 0, 0], [0, 1, 1], [1, 0, 1], [1, 1, 0]]
    res[2] = {"n": 2, "proven_upper_bound": 4, "verified_lower_bound": 4, "exact": 4, "set": s2,
              "upper_bound_proof": "all 56 five-subsets of {0,1}^3 have zero determinant (the 8 points lie on one sphere); checked exhaustively",
              "status": "exhaustive determinant check (no solver needed)", "seconds": 0.0}
    # ---- refutations: collect, per (n, K), the set of orbit cases proven INFEASIBLE
    refs = {}
    split_files = sorted(glob.glob(os.path.join(HERE, "refute_n*_case0_split_t*.json")))
    split2_files = sorted(glob.glob(os.path.join(HERE, "refute_n*_case0_split2_t*.json")))
    for f in sorted(glob.glob(os.path.join(HERE, "refute_*.json"))):
        if f in split_files or f in split2_files:
            continue
        data = json.load(open(f))
        if not isinstance(data, list):  # sub-case logs (level-3 split) are handled via their aggregate files
            continue
        for e in data:
            key = (e["n"], e["K"])
            d = refs.setdefault(key, {"cases": {}, "files": [], "num_orbit_cases": e.get("num_orbit_cases"), "plain": None})
            d["files"].append(os.path.basename(f))
            if e["mode"] == "orbit":
                if d["num_orbit_cases"] is None:
                    d["num_orbit_cases"] = len(e["cases"]) if e["verdict"] == "INFEASIBLE" else None
                for c in e["cases"]:
                    if c["status"] == "INFEASIBLE":
                        prev = d["cases"].get(c["case"])
                        if prev is None or c["wall_seconds"] < prev["wall_seconds"]:
                            d["cases"][c["case"]] = {"wall_seconds": c["wall_seconds"], "conflicts": c["conflicts"], "file": os.path.basename(f),
                                                     "lazy_rows_added": c.get("lazy_rows_added", 0), "rows": e.get("rows")}
            elif e["verdict"] == "INFEASIBLE":
                d["plain"] = e
    # orbit case 0 split by t = |S ∩ O_0| in {1,2,3,4} (exhaustive, see refute_case0_split.py):
    # case 0 counts as refuted only if all four sub-cases are INFEASIBLE.
    split = {}
    for f in split_files:
        d = json.load(open(f))
        for sc in d["subcases"]:
            if sc["status"] == "INFEASIBLE":
                cur = split.setdefault((d["n"], d["K"]), {})
                if sc["t"] not in cur or sc["wall_seconds"] < cur[sc["t"]]["wall_seconds"]:
                    cur[sc["t"]] = {"wall_seconds": sc["wall_seconds"], "conflicts": sc["conflicts"], "file": os.path.basename(f), "rows": d.get("rows")}
    # second-level split of a sub-case t by u = |S ∩ O_1| in {0..4}: t is refuted if all five are INFEASIBLE
    split2 = {}
    for f in split2_files:
        d = json.load(open(f))
        for sc in d["subcases"]:
            if sc["status"] == "INFEASIBLE":
                cur = split2.setdefault((d["n"], d["K"], d["t"]), {})
                if sc["u"] not in cur or sc["wall_seconds"] < cur[sc["u"]]["wall_seconds"]:
                    cur[sc["u"]] = {"wall_seconds": sc["wall_seconds"], "conflicts": sc["conflicts"], "file": os.path.basename(f)}
    for (n_, K_, t_), cur in split2.items():
        if all(u in cur for u in range(5)) and t_ not in split.get((n_, K_), {}):
            split.setdefault((n_, K_), {})[t_] = {"wall_seconds": round(sum(c["wall_seconds"] for c in cur.values()), 2), "conflicts": sum(c["conflicts"] for c in cur.values()),
                                                 "file": ", ".join(sorted(set(c["file"] for c in cur.values()))), "split_by_second_orbit_count": {str(u): cur[u] for u in sorted(cur)}}
    for key, cur in split.items():
        if all(t in cur for t in (1, 2, 3, 4)) and key in refs and 0 not in refs[key]["cases"]:
            refs[key]["cases"][0] = {"wall_seconds": round(sum(c["wall_seconds"] for c in cur.values()), 2), "conflicts": sum(c["conflicts"] for c in cur.values()),
                                     "file": ", ".join(sorted(set(c["file"] for c in cur.values()))), "split_by_generic_orbit_count": {str(t): cur[t] for t in sorted(cur)}}
            refs[key]["files"] += sorted(set(c["file"] for c in cur.values()))
    proven_ub = {}
    ub_detail = {}
    partial = {}
    for (n, K), d in sorted(refs.items()):
        k = d["num_orbit_cases"]
        complete = (k is not None and all(j in d["cases"] for j in range(k))) or d["plain"] is not None
        if not complete and d["cases"]:
            partial.setdefault(n, {})[str(K)] = {"orbit_cases_refuted": sorted(d["cases"]), "orbit_cases_total": k,
                                                 "note": "NOT a proof: the remaining orbit cases did not finish", "files": sorted(set(d["files"]))}
        if complete and K >= 5:
            if n not in proven_ub or K - 1 < proven_ub[n]:
                proven_ub[n] = K - 1
                ub_detail[n] = {"refuted_K": K, "orbit_cases": k, "total_solver_seconds": round(sum(c["wall_seconds"] for c in d["cases"].values()), 2),
                                "total_conflicts": sum(c["conflicts"] for c in d["cases"].values()), "files": sorted(set(d["files"])),
                                "cases": {str(j): d["cases"][j] for j in sorted(d["cases"])}}
    # ---- optimisation runs (plain CP-SAT maximisation on the complete model)
    best_set = {}
    opt = {}
    for f in sorted(glob.glob(os.path.join(HERE, "run_n*.json"))) + sorted(glob.glob(os.path.join(HERE, "lb_n*.json"))):
        r = json.load(open(f))
        n = r["n"]
        sol = r.get("solution")
        if sol:
            ok, det = exact_check(sol, n)
            if ok and (n not in best_set or len(sol) > len(best_set[n][0])):
                best_set[n] = (sol, os.path.basename(f), det)
        if r.get("status") == "OPTIMAL" and r.get("solution_exact_check") and r.get("lower_cut") is None:
            opt[n] = {"value": r["objective"], "seconds": r["wall_seconds"], "workers": r["workers"], "file": os.path.basename(f),
                      "rows": [r["num_circle_rows"], r["num_hyperplane_rows"]], "bruteforce_crosscheck_equal": r.get("bruteforce_crosscheck_equal")}
    for n in sorted(set(list(best_set) + list(proven_ub) + list(opt) + list(partial))):
        e = {"n": n, "trivial_upper_bound_4n": 4 * n, "public_lower_bound": PUBLIC_LB.get(n)}
        if n in partial:
            e["unfinished_refutations"] = partial[n]
        vf = sorted(glob.glob(os.path.join(HERE, f"rows_n{n}_min*_verified.json")))
        if vf:
            e["rows_verified"] = [json.load(open(f)) for f in vf]
        ubs = []
        if n in proven_ub:
            ubs.append(proven_ub[n])
            e["refutation"] = ub_detail[n]
        if n in opt:
            ubs.append(opt[n]["value"])
            e["optimisation_run"] = opt[n]
        e["proven_upper_bound"] = min(ubs) if ubs else 4 * n
        if n in best_set:
            sol, f, det = best_set[n]
            e["verified_lower_bound"] = len(sol)
            e["set"] = sol
            e["set_source"] = f
            e["set_exact_check"] = det
            pe = project_evaluate(n, sol)
            e["set_project_evaluate"] = pe
            assert pe is None or (pe["valid"] and int(pe["score"]) == len(sol)), ("project evaluator disagrees", n, pe)
        e["exact"] = e["proven_upper_bound"] if e.get("verified_lower_bound") == e["proven_upper_bound"] else None
        res[n] = e
    json.dump({"problem": "C(n): largest subset of {0..n-1}^3 with no 5 points on a common sphere or plane",
               "results": [res[n] for n in sorted(res)]}, open(os.path.join(HERE, "results.json"), "w"), indent=1)
    lines = ["# Results", "",
             "| n | proven upper bound | verified lower bound (this work) | exact C(n) | trivial 4n | public lower bound | how the upper bound was proven |",
             "|---:|---:|---:|---:|---:|---:|---|"]
    for n in sorted(res):
        e = res[n]
        how = e.get("upper_bound_proof", "")
        if "optimisation_run" in e and e["optimisation_run"]["value"] == e["proven_upper_bound"]:
            o = e["optimisation_run"]
            how = f"CP-SAT OPTIMAL on the complete model ({o['rows'][0]} circle + {o['rows'][1]} hyperplane rows), {o['seconds']} s, {o['workers']} workers"
            if "refutation" in e and e["refutation"]["refuted_K"] - 1 == e["proven_upper_bound"]:
                r = e["refutation"]
                how += f"; independently: `sum >= {r['refuted_K']}` INFEASIBLE in all {r['orbit_cases']} orbit cases ({r['total_solver_seconds']} s, 1 worker)"
        elif "refutation" in e:
            r = e["refutation"]
            how = f"`sum >= {r['refuted_K']}` INFEASIBLE in all {r['orbit_cases']} orbit cases ({r['total_solver_seconds']} s solver time, {r['total_conflicts']} conflicts)"
        elif not how:
            how = "none below 4n proven here"
            for K, pr in e.get("unfinished_refutations", {}).items():
                how += f" (`sum >= {K}`: {len(pr['orbit_cases_refuted'])} of {pr['orbit_cases_total']} orbit cases refuted, the rest unfinished - not a proof)"
        lines.append(f"| {n} | {e['proven_upper_bound']} | {e.get('verified_lower_bound', '-')} | {e['exact'] if e.get('exact') else 'open'} | {4*n} | {e.get('public_lower_bound') or '-'} | {how} |")
    lines += ["", "Sets (all re-verified by the exact 5-subset determinant checker):", ""]
    for n in sorted(res):
        if "set" in res[n]:
            lines.append(f"- n = {n}, {len(res[n]['set'])} points: `{json.dumps(res[n]['set'])}`")
    open(os.path.join(HERE, "RESULTS.md"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
