"""Trusted exact evaluator for "no 5 on a sphere" (Tao et al., AlphaEvolve repository, problem 60).

A solution for instance {"n": n} is a list of [x, y, z] integer triples with 0 <= x, y, z < n.
It is valid when the points are distinct and no five of them lie on a common sphere or plane,
i.e. when for every 5-subset the integer determinant with rows [x, y, z, x^2+y^2+z^2, 1] is nonzero.
The score of a valid solution is its number of points.

Arithmetic is exact. Subtracting one row from the other four turns the 5x5 determinant into the 4x4
determinant of rows (dx, dy, dz, dw), where |dx|, |dy|, |dz| <= s = n - 1 and |dw| <= 3 s^2. Expanding
along one row with 3x3 cofactors, every cofactor is at most 18 s^4 in absolute value, every partial sum
is at most 72 s^5, and so is the determinant. For n <= 40 that is 72 * 39^5 < 6.5e9, far below
2^63 ~ 9.2e18; int64 cannot overflow as long as 72 s^5 < 2^63, i.e. for n <= 2600. Beyond that the same
code runs on Python integers (numpy object arrays), which are unbounded.

This module imports nothing from any solver.
"""

from __future__ import annotations

from math import comb

import numpy as np

_INT64_LIMIT = 2**63 - 1


def instance_key(instance: dict) -> str:
    return f"n{int(instance['n'])}"


def _is_int(v) -> bool:
    return isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_))


def _fail(reason: str, **extra) -> dict:
    detail = {"reason": reason}
    detail.update(extra)
    return {"valid": False, "score": 0.0, "detail": detail}


def _triples_colex(m: int):
    """Index arrays (a, b, c) of all a < b < c < m, ordered by c, then b, then a.

    With this order the triples with c < j are exactly the first comb(j, 3) entries.
    """
    pa = np.concatenate([np.arange(b, dtype=np.int32) for b in range(m)]) if m > 1 else np.zeros(0, np.int32)
    pb = np.concatenate([np.full(b, b, dtype=np.int32) for b in range(m)]) if m > 1 else np.zeros(0, np.int32)
    ta = np.concatenate([pa[: comb(c, 2)] for c in range(m)])
    tb = np.concatenate([pb[: comb(c, 2)] for c in range(m)])
    tc = np.concatenate([np.full(comb(c, 2), c, dtype=np.int32) for c in range(m)])
    return ta, tb, tc


def _first_degenerate(points: list, n: int):
    """Check every 5-subset. Returns (witness_indices or None, min_abs_det, arithmetic)."""
    m = len(points)
    s = n - 1
    exact_int64 = 72 * s**5 < _INT64_LIMIT
    dtype = np.int64 if exact_int64 else object
    lifted = np.array([[x, y, z, x * x + y * y + z * z] for x, y, z in points], dtype=dtype)
    ta, tb, tc = _triples_colex(m)
    min_abs = None
    for i in range(4, m):  # i is the largest index of the 5-subset
        d = lifted[:i] - lifted[i]  # (i, 4) rows (dx, dy, dz, dw)
        nt = comb(i, 3)
        a, b, c = d[ta[:nt]], d[tb[:nt]], d[tc[:nt]]
        a0, a1, a2, a3 = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
        b0, b1, b2, b3 = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
        c0, c1, c2, c3 = c[:, 0], c[:, 1], c[:, 2], c[:, 3]
        m01 = a0 * b1 - a1 * b0
        m02 = a0 * b2 - a2 * b0
        m03 = a0 * b3 - a3 * b0
        m12 = a1 * b2 - a2 * b1
        m13 = a1 * b3 - a3 * b1
        m23 = a2 * b3 - a3 * b2
        # cofactor vector: det[v; a; b; c] = v . cof for any row v
        cof = np.empty((nt, 4), dtype=dtype)
        cof[:, 0] = m12 * c3 - m13 * c2 + m23 * c1
        cof[:, 1] = -(m02 * c3 - m03 * c2 + m23 * c0)
        cof[:, 2] = m01 * c3 - m03 * c1 + m13 * c0
        cof[:, 3] = -(m01 * c2 - m02 * c1 + m12 * c0)
        for j in range(3, i):  # j is the second largest index; triples a < b < c < j
            ntj = comb(j, 3)
            dets = np.abs(cof[:ntj] @ d[j])
            lo = dets.min()
            if lo == 0:
                t = int(np.flatnonzero(dets == 0)[0])
                return [int(ta[t]), int(tb[t]), int(tc[t]), j, i], 0, exact_int64
            if min_abs is None or lo < min_abs:
                min_abs = lo
    return None, (int(min_abs) if min_abs is not None else None), exact_int64


def _evaluate(instance, solution) -> dict:
    if not isinstance(instance, dict) or "n" not in instance:
        return _fail("instance must be a table with an integer n")
    n = instance["n"]
    if not _is_int(n) or n < 1:
        return _fail("instance n must be a positive integer")
    n = int(n)
    if not isinstance(solution, (list, tuple)):
        return _fail("solution must be a list of [x, y, z] triples")
    points = []
    for idx, p in enumerate(solution):
        if not isinstance(p, (list, tuple)) or len(p) != 3:
            return _fail(f"point {idx} is not a triple")
        if not all(_is_int(v) for v in p):
            return _fail(f"point {idx} has a non-integer coordinate")
        x, y, z = (int(v) for v in p)
        if not (0 <= x < n and 0 <= y < n and 0 <= z < n):
            return _fail(f"point {idx} = {[x, y, z]} is outside the grid 0..{n - 1}")
        points.append((x, y, z))
    m = len(points)
    if len(set(points)) != m:
        seen = set()
        dup = next(p for p in points if p in seen or seen.add(p))
        return _fail("duplicate point", witness=[list(dup)])
    if m > 4 * n:
        # each of the n planes z = const holds at most 4 points of a valid set
        return _fail(f"{m} points exceed the trivial upper bound 4n = {4 * n} (five points in a plane z = const)")
    detail = {"n": n, "points": m, "five_subsets": comb(m, 5)}
    if m >= 5:
        witness, min_abs, exact_int64 = _first_degenerate(points, n)
        detail["arithmetic"] = "int64" if exact_int64 else "python-int"
        if witness is not None:
            return _fail(
                "five points on a common sphere or plane",
                n=n,
                points=m,
                witness=[list(points[t]) for t in witness],
            )
        detail["min_abs_det"] = min_abs
    return {"valid": True, "score": float(m), "detail": detail}


def evaluate(instance: dict, solution) -> dict:
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # the contract: never raise on malformed input
        return _fail(f"evaluator error: {type(exc).__name__}: {exc}")
