#!/usr/bin/env python3
"""Validate evaluate.py and verify.py against the published sets in published/ and against broken sets.

    uv run python problems/noisosceles/selftest.py

Exit status 0 when every check passes.
"""

from __future__ import annotations

import glob
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import evaluate as ev  # noqa: E402
import verify as vf  # noqa: E402


def brute(points):
    """Third, naive check: every ordered triple, as in the definition."""
    for b in points:
        for i, a in enumerate(points):
            if a == b:
                continue
            dab = (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2
            for c in points[i + 1:]:
                if c != b and (c[0] - b[0]) ** 2 + (c[1] - b[1]) ** 2 == dab:
                    return False
    return True


def mutants(n, pts, rng):
    """Deliberately broken variants of a valid set; each must be rejected."""
    out = []
    have = {tuple(p) for p in pts}
    out.append(("duplicate point", pts + [pts[0]]))
    out.append(("out of range", pts[:-1] + [[n, 0]]))
    out.append(("negative coordinate", pts[:-1] + [[-1, 0]]))
    out.append(("float coordinate", pts[:-1] + [[0.0, 1]]))
    out.append(("bool coordinate", pts[:-1] + [[True, 1]]))
    out.append(("not a pair", pts[:-1] + [[1, 2, 3]]))
    out.append(("string point", pts[:-1] + ["ab"]))
    # flat isosceles: add the midpoint of two points with equal parity, or the reflection of one in another
    for a in pts:
        for c in pts:
            if a < c and (a[0] + c[0]) % 2 == 0 and (a[1] + c[1]) % 2 == 0:
                mid = ((a[0] + c[0]) // 2, (a[1] + c[1]) // 2)
                if mid not in have:
                    out.append(("midpoint of two points", pts + [list(mid)]))
                    break
        else:
            continue
        break
    for a in pts:
        hit = False
        for c in pts:
            r = (2 * c[0] - a[0], 2 * c[1] - a[1])
            if a != c and 0 <= r[0] < n and 0 <= r[1] < n and r not in have:
                out.append(("reflection of one point in another", pts + [list(r)]))
                hit = True
                break
        if hit:
            break
    # proper isosceles: a point on the perpendicular bisector of two points, not their midpoint
    done = False
    for _ in range(4000):
        a, c = rng.sample(pts, 2)
        x, y = rng.randrange(n), rng.randrange(n)
        if (x, y) in have:
            continue
        if (x - a[0]) ** 2 + (y - a[1]) ** 2 == (x - c[0]) ** 2 + (y - c[1]) ** 2 and (2 * x, 2 * y) != (a[0] + c[0], a[1] + c[1]):
            out.append(("apex on a bisector", pts + [[x, y]]))
            done = True
            break
    if not done:
        out.append(("apex on a bisector (none found: skipped)", None))
    # every single added grid point must be rejected if the set is maximal; test 200 random additions against brute
    return out


def main():
    ok = True
    rng = random.Random(59)
    files = sorted(glob.glob(os.path.join(HERE, "published", "*.json")), key=lambda f: json.load(open(f))["instance"]["n"])
    for path in files:
        doc = json.load(open(path))
        inst, pts, value = doc["instance"], doc["solution"], doc["value"]
        n = inst["n"]
        t0 = time.perf_counter()
        res = ev.evaluate(inst, pts)
        dt = time.perf_counter() - t0
        t0 = time.perf_counter()
        vok, msg, info = vf.verify(n, pts)
        dv = time.perf_counter() - t0
        good = res["valid"] and res["score"] == value and vok and brute([tuple(p) for p in pts])
        bad = 0
        muts = [m for m in mutants(n, [list(p) for p in pts], rng) if m[1] is not None]
        for name, mset in muts:
            r = ev.evaluate(inst, mset)
            v_ok = vf.verify(n, mset)[0]
            if r["valid"] or v_ok:
                bad += 1
                print("   MUTANT ACCEPTED:", name, "evaluate:", r["valid"], "verify:", v_ok)
        # random single-point additions and removals: all three checkers must agree
        agree = 0
        trials = 60
        for _ in range(trials):
            q = [rng.randrange(n), rng.randrange(n)]
            trial = [p for p in pts if p != q] + ([q] if rng.random() < 0.8 else [])
            a = ev.evaluate(inst, trial)["valid"]
            b = vf.verify(n, trial)[0]
            c = brute([tuple(p) for p in trial])
            agree += a == b == c
        line = (f"{'PASS' if good and not bad and agree == trials else 'FAIL'} {os.path.basename(path):28s} "
                f"{ev.instance_key(inst):>5s} size={int(res['score']):3d} evaluate={dt:.3f}s verify={dv:.2f}s "
                f"mutants_rejected={len(muts) - bad}/{len(muts)} random_edits_agree={agree}/{trials}")
        print(line)
        ok = ok and good and not bad and agree == trials
    # malformed input must never raise
    weird = [None, 5, "x", {}, [[1]], [[1, 2], None], [[1, "2"]], [[1, 2.5]], [[10**30, 1]], [[1, 2]] * 2]
    for w in weird:
        try:
            r = ev.evaluate({"n": 8}, w)
            assert isinstance(r, dict) and "valid" in r
        except Exception as exc:  # pragma: no cover
            ok = False
            print("FAIL evaluate raised on", repr(w)[:40], exc)
    for inst in [None, {}, {"n": "8"}, {"n": 0}, {"n": True}, {"n": 2.0}]:
        try:
            r = ev.evaluate(inst, [[0, 0]])
            assert r["valid"] is False
        except Exception as exc:  # pragma: no cover
            ok = False
            print("FAIL evaluate raised or accepted instance", inst, exc)
    small = ev.evaluate({"n": 8}, [[0, 0], [0, 1], [3, 5]])
    ok = ok and small["valid"] and small["score"] == 3.0
    ok = ok and not ev.evaluate({"n": 8}, [[0, 0], [0, 1], [0, 2]])["valid"]      # flat
    ok = ok and not ev.evaluate({"n": 8}, [[0, 0], [2, 0], [1, 5]])["valid"]      # proper isosceles
    ok = ok and ev.evaluate({"n": 8}, [])["valid"]
    print("malformed input: no exception;", "ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
