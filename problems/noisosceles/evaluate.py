"""Trusted exact evaluator for "subsets of the grid with no isosceles triangles"
(Tao et al., AlphaEvolve repository of problems, problem 59; arXiv:2511.02864, section 6.39).

A solution for instance {"n": n} is a list of [x, y] integer pairs with 0 <= x, y < n.
It is valid when the points are distinct and no three of them form an isosceles triangle, flat ones
included: for all distinct a, b, c in the set, |a - b| != |b - c|. Equivalently, for every point b of
the set, the squared distances from b to the other points are pairwise different.
The score of a valid solution is its number of points.

Arithmetic is exact: squared distances are integers, at most 2 (n - 1)^2. For every apex b the m - 1
squared distances are sorted and neighbours compared, so all m (m - 1) (m - 2) / 2 (apex, pair)
combinations are covered in O(m^2 log m). int64 holds 2 (n - 1)^2 for n <= 2^31; beyond that the same
check runs on Python integers.

This module imports nothing from any solver.
"""

from __future__ import annotations

try:  # numpy only makes the check faster; the pure-Python path is the same test
    import numpy as np
except Exception:  # pragma: no cover
    np = None

_NUMPY_MAX_N = 2**31


def instance_key(instance: dict) -> str:
    return f"n{int(instance['n'])}"


def _is_int(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, int):
        return True
    return np is not None and isinstance(v, np.integer)


def _fail(reason: str, **extra) -> dict:
    detail = {"reason": reason}
    detail.update(extra)
    return {"valid": False, "score": 0.0, "detail": detail}


def _first_isosceles_numpy(points: list):
    """Returns (apex index, other index, other index) of a forbidden triple, or None."""
    pts = np.array(points, dtype=np.int64).reshape(-1, 2)
    m = len(pts)
    idx = np.arange(m)
    for b in range(m):
        diff = pts - pts[b]
        d = diff[:, 0] * diff[:, 0] + diff[:, 1] * diff[:, 1]
        keep = idx != b
        dd, who = d[keep], idx[keep]
        order = np.argsort(dd, kind="stable")
        ds = dd[order]
        same = np.flatnonzero(ds[1:] == ds[:-1])
        if same.size:
            t = int(same[0])
            return b, int(who[order[t]]), int(who[order[t + 1]])
    return None


def _first_isosceles_python(points: list):
    for b, (bx, by) in enumerate(points):
        seen = {}
        for a, (ax, ay) in enumerate(points):
            if a == b:
                continue
            d = (ax - bx) * (ax - bx) + (ay - by) * (ay - by)
            if d in seen:
                return b, seen[d], a
            seen[d] = a
    return None


def _evaluate(instance, solution) -> dict:
    if not isinstance(instance, dict) or "n" not in instance:
        return _fail("instance must be a table with an integer n")
    n = instance["n"]
    if not _is_int(n) or n < 1:
        return _fail("instance n must be a positive integer")
    n = int(n)
    if not isinstance(solution, (list, tuple)):
        return _fail("solution must be a list of [x, y] pairs")
    points = []
    for idx, p in enumerate(solution):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return _fail(f"point {idx} is not a pair")
        if not all(_is_int(v) for v in p):
            return _fail(f"point {idx} has a non-integer coordinate")
        x, y = int(p[0]), int(p[1])
        if not (0 <= x < n and 0 <= y < n):
            return _fail(f"point {idx} = {[x, y]} is outside the grid 0..{n - 1}")
        points.append((x, y))
    m = len(points)
    if len(set(points)) != m:
        seen = set()
        dup = next(p for p in points if p in seen or seen.add(p))
        return _fail("duplicate point", witness=[list(dup)])
    detail = {"n": n, "points": m, "apex_pair_checks": m * (m - 1) * (m - 2) // 2}
    if m >= 3:
        use_numpy = np is not None and n <= _NUMPY_MAX_N
        detail["arithmetic"] = "int64" if use_numpy else "python-int"
        hit = _first_isosceles_numpy(points) if use_numpy else _first_isosceles_python(points)
        if hit is not None:
            b, a, c = hit
            (bx, by), (ax, ay) = points[b], points[a]
            return _fail(
                "isosceles triangle: the first witness point is equidistant from the other two",
                n=n,
                points=m,
                witness=[list(points[b]), list(points[a]), list(points[c])],
                squared_distance=(ax - bx) ** 2 + (ay - by) ** 2,
            )
    return {"valid": True, "score": float(m), "detail": detail}


def evaluate(instance: dict, solution) -> dict:
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # the contract: never raise on malformed input
        return _fail(f"evaluator error: {type(exc).__name__}: {exc}")
