#!/usr/bin/env python3
"""Independent certificate checker for "no isosceles triangles in the grid" (standard library only).

    python verify.py <certificate.json> [--n N]

Deliberately written differently from evaluate.py. evaluate.py compares squared distances from each
apex. This checker never computes a distance: for every unordered pair {a, c} of the set and every
third point b it tests whether b lies on the perpendicular bisector of a and c,

    2 * (b . (c - a)) == c . c - a . a,

which is the same condition |b - a| = |b - c| written as a linear equation in b. Python integers are
unbounded, so overflow is impossible. It is cubic in the number of points (about a second for 164
points) and that is fine.

Accepted certificate layouts:
    {"instance": {"n": 100}, "solution": [[x, y], ...]}      (what published/*.json and campaigns use)
    {"n": 100, "points": [[x, y], ...]}
    {"solution": [[x, y], ...]}  or a bare list              (n must then be given with --n)
Coordinates are 0-based: 0 <= x, y < n.

Exit status: 0 valid, 1 invalid, 2 unreadable certificate.
"""

from __future__ import annotations

import argparse
import json
import sys


def load_certificate(path, n_override=None):
    with open(path) as f:
        doc = json.load(f)
    n = n_override
    points = doc
    if isinstance(doc, dict):
        points = doc.get("solution", doc.get("points"))
        if n is None:
            inst = doc.get("instance")
            n = inst.get("n") if isinstance(inst, dict) else doc.get("n")
    if n is None:
        raise ValueError("grid size n is not in the certificate; pass --n")
    if not isinstance(points, list):
        raise ValueError("no point list found (expected 'solution' or 'points')")
    return int(n), points


def verify(n, points):
    """Returns (ok, message, info)."""
    pts = []
    for idx, p in enumerate(points):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return False, f"point {idx} is not a pair", {}
        for c in p:
            if type(c) is not int:
                return False, f"point {idx} has a non-integer coordinate {c!r}", {}
            if not 0 <= c < n:
                return False, f"point {idx} = {list(p)} is outside 0..{n - 1}", {}
        pts.append((p[0], p[1]))
    if len(set(pts)) != len(pts):
        return False, "duplicate points", {}
    m = len(pts)
    norms = [x * x + y * y for x, y in pts]
    tests = 0
    for i in range(m):
        ax, ay = pts[i]
        na = norms[i]
        for j in range(i + 1, m):
            cx, cy = pts[j]
            vx, vy = 2 * (cx - ax), 2 * (cy - ay)
            rhs = norms[j] - na
            for t in range(m):
                if t == i or t == j:
                    continue
                bx, by = pts[t]
                if bx * vx + by * vy == rhs:
                    return False, (f"isosceles triangle: {list(pts[t])} is equidistant from "
                                   f"{list(pts[i])} and {list(pts[j])}"), {}
            tests += m - 2
    return True, "ok", {"points": m, "bisector_tests": tests}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("certificate")
    ap.add_argument("--n", type=int, default=None, help="grid size, if the certificate does not carry it")
    args = ap.parse_args(argv)
    try:
        n, points = load_certificate(args.certificate, args.n)
    except Exception as exc:
        print(f"UNREADABLE {args.certificate}: {exc}")
        return 2
    ok, message, info = verify(n, points)
    if ok:
        print(f"VALID n={n} points={info['points']} bisector_tests={info['bisector_tests']} isosceles=0")
        return 0
    print(f"INVALID n={n}: {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
