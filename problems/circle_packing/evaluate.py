"""Exact evaluator for circle packing in the unit square (maximise the sum of radii).

A solution is a list of n triples [x, y, r]. Every number is converted to an exact rational
(`fractions.Fraction(float)` is exact: a double is an integer divided by a power of two) and every
constraint is checked in rational arithmetic, with no tolerance of any kind:

    r > 0
    x - r >= 0,   x + r <= 1,   y - r >= 0,   y + r <= 1
    (xi - xj)^2 + (yi - yj)^2 >= (ri + rj)^2          for every pair i < j

Circles may touch each other and the sides of the square; they may not overlap by any amount.
Several published values for this benchmark were obtained with an overlap tolerance of 1e-6,
which inflates the sum of radii. Nothing of that kind is accepted here.

The score is the sum of the radii: the exact rational sum, rounded once to the nearest double.
An invalid solution scores 0.0. `evaluate` never raises.
"""

from __future__ import annotations

import math
from fractions import Fraction

MAX_REPORTED = 5  # violations listed in `detail`; all of them are counted


def instance_key(instance: dict) -> str:
    """{"n": 26} -> "n26"."""
    try:
        return f"n{int(instance['n'])}"
    except Exception:  # noqa: BLE001 - a key for a malformed instance, rather than an exception
        return "n?"


def evaluate(instance: dict, solution) -> dict:
    """{"valid": bool, "score": float, "detail": {...}}; exact, and never raises."""
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise on malformed input"
        return _invalid(f"evaluator could not read the solution: {type(exc).__name__}: {exc}")


def _invalid(reason: str, **detail) -> dict:
    return {"valid": False, "score": 0.0, "detail": {"reason": reason, **detail}}


def _exact(value) -> Fraction | None:
    """The exact rational value of a finite real number, or None for anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):  # includes numpy.float64, which subclasses float
        return Fraction(value) if math.isfinite(value) else None
    return None


def _evaluate(instance, solution) -> dict:
    n = instance.get("n") if isinstance(instance, dict) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        return _invalid("instance must be a table with a positive integer n")

    if hasattr(solution, "tolist"):  # a numpy array of shape (n, 3)
        solution = solution.tolist()
    if not isinstance(solution, (list, tuple)):
        return _invalid("solution must be a list of [x, y, r] triples")
    if len(solution) != n:
        return _invalid(f"solution has {len(solution)} circles, expected {n}", circles=len(solution))

    xs, ys, rs = [], [], []
    for i, circle in enumerate(solution):
        if hasattr(circle, "tolist"):
            circle = circle.tolist()
        if not isinstance(circle, (list, tuple)) or len(circle) != 3:
            return _invalid(f"circle {i} is not an [x, y, r] triple")
        x, y, r = (_exact(v) for v in circle)
        if x is None or y is None or r is None:
            return _invalid(f"circle {i} has a value that is not a finite number")
        xs.append(x)
        ys.append(y)
        rs.append(r)

    violations = 0
    reported: list[str] = []

    def violation(text: str) -> None:
        nonlocal violations
        violations += 1
        if len(reported) < MAX_REPORTED:
            reported.append(text)

    one = Fraction(1)
    wall_gap = None  # smallest distance from a circle to a side of the square (exact)
    for i in range(n):
        x, y, r = xs[i], ys[i], rs[i]
        if r <= 0:
            violation(f"circle {i} has radius {float(r)!r}; radii must be positive")
        gap = min(x - r, one - x - r, y - r, one - y - r)
        if gap < 0:
            violation(f"circle {i} crosses the square by {float(-gap):.3e}")
        if wall_gap is None or gap < wall_gap:
            wall_gap = gap

    pair_gap = None  # smallest (distance - sum of radii) over pairs, as a float, for information only
    worst_overlap = 0.0
    for i in range(n):
        xi, yi, ri = xs[i], ys[i], rs[i]
        for j in range(i + 1, n):
            dx, dy, reach = xi - xs[j], yi - ys[j], ri + rs[j]
            dist2 = dx * dx + dy * dy
            gap = math.sqrt(dist2) - float(reach)  # approximate, never used for the verdict
            if pair_gap is None or gap < pair_gap:
                pair_gap = gap
            if reach > 0 and dist2 < reach * reach:  # the exact test
                depth = float(reach) - math.sqrt(dist2)
                if depth < 1e-12:  # below what doubles resolve: first-order depth from the exact numbers
                    depth = float((reach * reach - dist2) / (2 * reach))
                worst_overlap = max(worst_overlap, depth)
                violation(f"circles {i} and {j} overlap by {depth:.3e}")

    if violations:
        return _invalid(reported[0], violations=violations, examples=reported, worst_overlap=worst_overlap)

    return {
        "valid": True,
        "score": float(sum(rs, Fraction(0))),
        "detail": {
            "n": n,
            "min_wall_gap": float(wall_gap),
            "min_pair_gap": pair_gap,  # None when n == 1
            "arithmetic": "exact rational, no tolerance",
        },
    }
