#!/usr/bin/env python3
"""Validate evaluate.py against the published certificates in published/ and against broken sets.

    uv run python problems/no5sphere/selftest.py            # evaluator only (seconds)
    uv run python problems/no5sphere/selftest.py --verify   # also the slow independent checker, n <= 16

Exit status 0 when every check passes.
"""

from __future__ import annotations

import glob
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import evaluate as ev  # noqa: E402
import verify as vf  # noqa: E402


def mutants(n, pts):
    """Deliberately broken variants of a valid set; each must be rejected."""
    out = []
    out.append(("duplicate point", pts + [pts[0]]))
    out.append(("out of range", pts[:-1] + [[n, 0, 0]]))
    out.append(("negative coordinate", pts[:-1] + [[-1, 0, 0]]))
    out.append(("float coordinate", pts[:-1] + [[0.0, 1, 2]]))
    out.append(("bool coordinate", pts[:-1] + [[True, 1, 2]]))
    out.append(("not a triple", pts[:-1] + [[1, 2]]))
    # five coplanar points: put five points into the plane z = pts[0][2]
    z0 = pts[0][2]
    plane = [p for p in pts if p[2] == z0]
    extra = [[x, y, z0] for x in range(n) for y in range(n) if [x, y, z0] not in pts]
    out.append(("five in a plane", pts + extra[: 5 - len(plane)]))
    # five cospherical points: add a grid point on the sphere through the first four points, if one exists
    (x1, y1, z1), b, c, d = pts[0], pts[1], pts[2], pts[3]
    quad = [pts[0], b, c, d]
    for x in range(n):
        for y in range(n):
            for z in range(n):
                q = [x, y, z]
                if q in pts:
                    continue
                rows = [(p[0], p[1], p[2], p[0] ** 2 + p[1] ** 2 + p[2] ** 2, 1) for p in quad + [q]]
                if vf.bareiss_det(rows) == 0:
                    out.append(("fifth point on the sphere of the first four", pts + [q]))
                    return out
    return out


def main():
    slow = "--verify" in sys.argv
    ok = True
    files = sorted(glob.glob(os.path.join(HERE, "published", "*.json")), key=lambda f: (json.load(open(f))["instance"]["n"], f))
    for path in files:
        doc = json.load(open(path))
        inst, pts, value = doc["instance"], doc["solution"], doc["value"]
        t0 = time.perf_counter()
        res = ev.evaluate(inst, pts)
        dt = time.perf_counter() - t0
        good = res["valid"] and res["score"] == value
        bad = 0
        muts = mutants(inst["n"], [list(p) for p in pts])
        for name, mset in muts:
            r = ev.evaluate(inst, mset)
            if r["valid"]:
                bad += 1
                print("   MUTANT ACCEPTED:", name)
        line = (
            f"{'PASS' if good and not bad else 'FAIL'} {os.path.basename(path):34s} {ev.instance_key(inst):>4s} "
            f"size={int(res['score']):3d} min|det|={res['detail'].get('min_abs_det')} "
            f"subsets={res['detail'].get('five_subsets')} eval={dt:.3f}s mutants_rejected={len(muts) - bad}/{len(muts)}"
        )
        if slow and inst["n"] <= 16:
            t0 = time.perf_counter()
            vok, msg, info = vf.verify(inst["n"], pts)
            line += f" verify.py={'VALID' if vok else 'INVALID'} ({time.perf_counter() - t0:.1f}s)"
            good = good and vok and info["min_abs_det"] == res["detail"]["min_abs_det"]
        print(line)
        ok = ok and good and not bad
    # malformed inputs must not raise
    for inst, sol in [({}, []), ({"n": "x"}, []), ({"n": 5}, None), ({"n": 5}, "abc"), ({"n": 5}, [[1, 2, 3], "p"]), (None, [[0, 0, 0]]), ({"n": 5}, {"a": 1})]:
        r = ev.evaluate(inst, sol)
        if r["valid"]:
            ok = False
            print("FAIL malformed input accepted:", inst, sol)
    r = ev.evaluate({"n": 5}, [])
    ok = ok and r["valid"] and r["score"] == 0.0
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
