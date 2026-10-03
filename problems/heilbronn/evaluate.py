"""Exact evaluator for the Heilbronn triangle problems (Tao et al., problems 48 and 49).

An instance is {"shape": "square" | "triangle" | "convex", "n": N}. A solution is a list of N points,
each a pair [x, y] of **decimal strings** such as ["0.25", "0.9034"].

The rules are those of the public leaderboard (github.com/tejstead/heilbronn-site,
build/vendor/verify_exact.py and scripts/check_submission.py), so that a set this file accepts with
value v is accepted there with exactly the same value:

    number    plain decimal literal: optional "-", 1 to 6 digits, optionally "." and 1 to 200 digits;
              no exponent, no fraction. It is read as the exact rational it denotes.
    points    exactly N of them, all distinct.
    square    0 <= x <= 1 and 0 <= y <= 1.                     value = smallest triangle area
    triangle  x >= 0, y >= 0, x + y <= 1 (area 1/2).            value = 2 * smallest triangle area
    convex    any coordinates.                                 value = smallest area / area of the convex hull

The smallest triangle is taken over all C(N, 3) triples. Boundary points are allowed, containment is
tested exactly, and there is no tolerance anywhere.

Arithmetic: every coordinate is multiplied by 10^D (D = the largest number of decimals used), which makes
it a Python integer. Cross products, the hull and all comparisons are then exact integer operations. The
only rounding is the final conversion of the exact value to a double for `score`; the exact value is in
`detail["value_fraction"]`. `evaluate` never raises.
"""

from __future__ import annotations

import re
from decimal import ROUND_HALF_EVEN, Context, Decimal
from fractions import Fraction

SHAPES = ("square", "triangle", "convex")
MIN_POINTS = 3
MAX_POINTS = 100                                              # the leaderboard's own cap
NUMBER = re.compile(r"-?[0-9]{1,6}(?:\.[0-9]{1,200})?")       # ASCII digits only, matched with fullmatch
TIE_NUM, TIE_DEN = 10 ** 9 + 1, 10 ** 9                       # ties: area <= min * (1 + 1e-9), tested exactly


def instance_key(instance: dict) -> str:
    """{"shape": "square", "n": 30} -> "square30"."""
    try:
        shape = instance["shape"]
        n = instance["n"]
        if shape in SHAPES and isinstance(n, int) and not isinstance(n, bool):
            return f"{shape}{n}"
    except Exception:  # noqa: BLE001 - a key for a malformed instance, rather than an exception
        pass
    return "heilbronn?"


def evaluate(instance: dict, solution) -> dict:
    """{"valid": bool, "score": float, "detail": {...}}; exact, and never raises."""
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise on malformed input"
        return _invalid(f"evaluator could not read the solution: {type(exc).__name__}: {exc}")


def _invalid(reason: str, **detail) -> dict:
    return {"valid": False, "score": 0.0, "detail": {"reason": reason, **detail}}


def _scaled(text: str, digits: int) -> int:
    """The integer text * 10**digits, for a literal already matched by NUMBER."""
    negative = text.startswith("-")
    body = text[1:] if negative else text
    whole, _, frac = body.partition(".")
    value = int(whole) * 10 ** digits + (int(frac) * 10 ** (digits - len(frac)) if frac else 0)
    return -value if negative else value


def _cross(o, a, b) -> int:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _hull(points: list) -> list:
    """Convex hull (Andrew's monotone chain, exact integers), counter-clockwise, collinear points dropped."""
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts
    lower: list = []
    for p in pts:
        while len(lower) >= 2 and _cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list = []
    for p in reversed(pts):
        while len(upper) >= 2 and _cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def decimal30(value: Fraction) -> str:
    """30 significant digits, round-half-even: the leaderboard's display format for a value."""
    if value == 0:
        return "0"
    return str(Context(prec=30, rounding=ROUND_HALF_EVEN).divide(Decimal(value.numerator), Decimal(value.denominator)))


def _evaluate(instance, solution) -> dict:
    if not isinstance(instance, dict):
        return _invalid("instance must be a table with shape and n")
    shape, n = instance.get("shape"), instance.get("n")
    if shape not in SHAPES:
        return _invalid(f"instance.shape must be one of {', '.join(SHAPES)}")
    if isinstance(n, bool) or not isinstance(n, int) or not MIN_POINTS <= n <= MAX_POINTS:
        return _invalid(f"instance.n must be an integer from {MIN_POINTS} to {MAX_POINTS}")
    if not isinstance(solution, (list, tuple)):
        return _invalid("solution must be a list of [x, y] pairs of decimal strings")
    if len(solution) != n:
        return _invalid(f"solution has {len(solution)} points, expected {n}", points=len(solution))

    texts = []
    for i, point in enumerate(solution):
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return _invalid(f"point {i} is not an [x, y] pair")
        for c in point:
            if not isinstance(c, str):
                return _invalid(f"point {i}: coordinates must be decimal strings, got {type(c).__name__}")
            if not NUMBER.fullmatch(c):
                return _invalid(f"point {i}: {c[:40]!r} is not a plain decimal literal "
                                "(at most 6 digits before the point and 200 after, no exponent)")
        texts.append((point[0], point[1]))

    digits = max((len(c.partition(".")[2]) for p in texts for c in p), default=0)
    unit = 10 ** digits
    pts = [(_scaled(x, digits), _scaled(y, digits)) for x, y in texts]

    if len(set(pts)) != n:
        return _invalid("duplicate points")

    violations = []
    if shape == "square":
        for i, (x, y) in enumerate(pts):
            if not (0 <= x <= unit and 0 <= y <= unit):
                violations.append(f"point {i} is outside the unit square")
    elif shape == "triangle":
        for i, (x, y) in enumerate(pts):
            if x < 0 or y < 0 or x + y > unit:
                violations.append(f"point {i} is outside the triangle x >= 0, y >= 0, x + y <= 1")
    if violations:
        return _invalid(violations[0], violations=len(violations), examples=violations[:5])

    # Smallest |cross product| over all triples: twice the smallest area, in units of 1 / unit^2.
    best = None
    best_triple = None
    crosses = []
    for i in range(n - 2):
        xi, yi = pts[i]
        for j in range(i + 1, n - 1):
            dxj, dyj = pts[j][0] - xi, pts[j][1] - yi
            for k in range(j + 1, n):
                c = dxj * (pts[k][1] - yi) - dyj * (pts[k][0] - xi)
                if c < 0:
                    c = -c
                crosses.append(c)
                if best is None or c < best:
                    best, best_triple = c, (i, j, k)
    ties = sum(1 for c in crosses if c * TIE_DEN <= best * TIE_NUM)

    hull_vertices = None
    if shape == "square":
        value = Fraction(best, 2 * unit * unit)
    elif shape == "triangle":
        value = Fraction(best, unit * unit)
    else:
        hull = _hull(pts)
        hull_vertices = len(hull)
        twice_area = 0
        if len(hull) >= 3:
            for a in range(len(hull)):
                x1, y1 = hull[a]
                x2, y2 = hull[(a + 1) % len(hull)]
                twice_area += x1 * y2 - x2 * y1
            twice_area = abs(twice_area)
        value = Fraction(best, twice_area) if twice_area else Fraction(0)

    return {
        "valid": True,
        "score": float(value),          # the exact value, rounded once to the nearest double
        "detail": {
            "shape": shape,
            "n": n,
            "value_fraction": f"{value.numerator}/{value.denominator}",
            "value_decimal": decimal30(value),
            "min_triple": list(best_triple),
            "ties_within_1e-9": ties,
            "triples_checked": len(crosses),
            "hull_vertices": hull_vertices,
            "decimals": digits,
            "arithmetic": "exact integers on a 10^-D grid, no tolerance",
        },
    }
