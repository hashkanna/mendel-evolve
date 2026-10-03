#!/usr/bin/env python3
"""Independent certificate checker for "no 5 on a sphere" (standard library only, no numpy).

    python verify.py <certificate.json> [--n N] [--jobs J]

Deliberately written differently from evaluate.py: it builds, for every 5-subset, the full 5x5 integer
matrix with rows [x, y, z, x^2+y^2+z^2, 1] and computes its determinant by fraction-free Bareiss
elimination on Python integers (unbounded, so overflow is impossible). No translation, no cofactors,
no vectorisation. It is slow (about a minute per three million 5-subsets per core) and that is fine.

Accepted certificate layouts:
    {"instance": {"n": 17}, "solution": [[x, y, z], ...]}      (what published/*.json use)
    {"n": 17, "points": [[x, y, z], ...]}
    {"solution": [[x, y, z], ...]}  or a bare list              (n must then be given with --n)
Coordinates are 0-based: 0 <= x, y, z < n.

Exit status: 0 valid, 1 invalid, 2 unreadable certificate.
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import combinations


def bareiss_det(rows):
    """Determinant of a square integer matrix by fraction-free elimination with row pivoting."""
    a = [list(r) for r in rows]
    size = len(a)
    sign = 1
    prev = 1
    for k in range(size - 1):
        if a[k][k] == 0:
            swap = next((r for r in range(k + 1, size) if a[r][k] != 0), None)
            if swap is None:
                return 0
            a[k], a[swap] = a[swap], a[k]
            sign = -sign
        akk = a[k][k]
        rowk = a[k]
        for i in range(k + 1, size):
            rowi = a[i]
            aik = rowi[k]
            for j in range(k + 1, size):
                rowi[j] = (rowi[j] * akk - aik * rowk[j]) // prev  # exact division (Bareiss)
        prev = akk
    return sign * a[size - 1][size - 1]


def _check_block(args):
    """All 5-subsets whose smallest index is `first`. Returns (count, min_abs, witness or None)."""
    rows, first = args
    head = rows[first]
    count = 0
    min_abs = None
    for rest in combinations(range(first + 1, len(rows)), 4):
        det = bareiss_det([head, rows[rest[0]], rows[rest[1]], rows[rest[2]], rows[rest[3]]])
        count += 1
        if det == 0:
            return count, 0, (first,) + rest
        if det < 0:
            det = -det
        if min_abs is None or det < min_abs:
            min_abs = det
    return count, min_abs, None


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


def verify(n, points, jobs=1):
    """Returns (ok, message, info)."""
    pts = []
    for idx, p in enumerate(points):
        if not isinstance(p, (list, tuple)) or len(p) != 3:
            return False, f"point {idx} is not a triple", {}
        for c in p:
            if type(c) is not int:
                return False, f"point {idx} has a non-integer coordinate {c!r}", {}
            if not 0 <= c < n:
                return False, f"point {idx} = {list(p)} is outside 0..{n - 1}", {}
        pts.append(tuple(p))
    if len(set(pts)) != len(pts):
        return False, "duplicate points", {}
    rows = [(x, y, z, x * x + y * y + z * z, 1) for (x, y, z) in pts]
    tasks = [(rows, first) for first in range(max(0, len(rows) - 4))]
    if jobs > 1 and tasks:
        import multiprocessing as mp

        with mp.Pool(jobs) as pool:
            results = pool.map(_check_block, tasks, chunksize=1)
    else:
        results = map(_check_block, tasks)
    total = 0
    min_abs = None
    for count, block_min, witness in results:
        total += count
        if witness is not None:
            return False, "five points on a common sphere or plane: " + str([list(pts[i]) for i in witness]), {}
        if block_min is not None and (min_abs is None or block_min < min_abs):
            min_abs = block_min
    return True, "ok", {"points": len(pts), "five_subsets": total, "min_abs_det": min_abs}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("certificate")
    ap.add_argument("--n", type=int, default=None, help="grid size, if the certificate does not carry it")
    ap.add_argument("--jobs", type=int, default=1, help="worker processes (default 1)")
    args = ap.parse_args(argv)
    try:
        n, points = load_certificate(args.certificate, args.n)
    except Exception as exc:
        print(f"UNREADABLE {args.certificate}: {exc}")
        return 2
    ok, message, info = verify(n, points, args.jobs)
    if ok:
        print(
            f"VALID n={n} points={info['points']} five_subsets={info['five_subsets']} "
            f"zero_dets=0 min_abs_det={info['min_abs_det']}"
        )
        return 0
    print(f"INVALID n={n}: {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
