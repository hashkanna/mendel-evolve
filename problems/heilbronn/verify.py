#!/usr/bin/env python3
"""Independent check of a Heilbronn certificate. Shares no code with evaluate.py.

    python verify.py certificate.json                 exit 0 if the point set is valid and the score is right
    python verify.py certificate.json --against V     also require value > V exactly (V: "p/q" or a decimal)

A certificate is {"instance": {"shape": S, "n": N}, "score": float, "solution": [["x", "y"], ...], ...}.

evaluate.py scales every coordinate to an integer and works on a grid. This file works differently on
purpose: each coordinate becomes a fractions.Fraction, each triangle area is the shoelace expression
|x1(y2 - y3) + x2(y3 - y1) + x3(y1 - y2)| / 2 over itertools.combinations, and the convex hull is found by
gift wrapping (Jarvis march) instead of a monotone chain. Two implementations that agree are harder to
fool than one.

Rules checked (those of github.com/tejstead/heilbronn-site): plain decimal literals, N distinct points,
square 0 <= x, y <= 1, triangle x, y >= 0 and x + y <= 1, convex unrestricted; value = smallest area
(square), twice the smallest area (triangle), smallest area over hull area (convex).

Exit status: 0 valid, 1 invalid, 2 usage.
"""

from __future__ import annotations

import itertools
import json
import string
import sys
from fractions import Fraction

DIGITS = set(string.digits)


def parse_number(text) -> Fraction:
    """A plain decimal literal as an exact rational; raises ValueError for anything else."""
    if not isinstance(text, str):
        raise ValueError(f"coordinate {text!r} is not a decimal string")
    body = text[1:] if text[:1] == "-" else text
    whole, dot, frac = body.partition(".")
    if not 1 <= len(whole) <= 6 or not set(whole) <= DIGITS:
        raise ValueError(f"{text[:40]!r}: need 1 to 6 digits before the decimal point")
    if dot and (not 1 <= len(frac) <= 200 or not set(frac) <= DIGITS):
        raise ValueError(f"{text[:40]!r}: need 1 to 200 digits after the decimal point")
    value = Fraction(int(whole + frac), 10 ** len(frac))
    return -value if text[:1] == "-" else value


def area(p, q, r) -> Fraction:
    return abs(p[0] * (q[1] - r[1]) + q[0] * (r[1] - p[1]) + r[0] * (p[1] - q[1])) / 2


def turn(o, a, b) -> Fraction:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def hull_area(points) -> Fraction:
    """Area of the convex hull by gift wrapping: from the lowest-leftmost point, always take the point
    that leaves every other point on the left (the farthest one among collinear candidates)."""
    start = min(points, key=lambda p: (p[1], p[0]))
    hull = [start]
    while True:
        here = hull[-1]
        pick = None
        for p in points:
            if p == here:
                continue
            if pick is None:
                pick = p
                continue
            t = turn(here, pick, p)
            if t < 0:
                pick = p
            elif t == 0:
                dp = (p[0] - here[0]) ** 2 + (p[1] - here[1]) ** 2
                dq = (pick[0] - here[0]) ** 2 + (pick[1] - here[1]) ** 2
                if dp > dq:
                    pick = p
        if pick is None or pick == start or len(hull) > len(points):
            break
        hull.append(pick)
    total = Fraction(0)
    for a in range(len(hull)):
        (x1, y1), (x2, y2) = hull[a], hull[(a + 1) % len(hull)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2


def exact_value(shape: str, n, solution) -> Fraction:
    """The exact leaderboard value of a point set; raises ValueError when it is not a valid set."""
    if shape not in ("square", "triangle", "convex"):
        raise ValueError(f"unknown shape {shape!r}")
    if type(n) is not int or not 3 <= n <= 100:
        raise ValueError("n must be an integer from 3 to 100")
    if not isinstance(solution, list) or len(solution) != n:
        raise ValueError(f"expected a list of {n} points")
    points = []
    for i, point in enumerate(solution):
        if not isinstance(point, list) or len(point) != 2:
            raise ValueError(f"point {i} is not [x, y]")
        points.append((parse_number(point[0]), parse_number(point[1])))
    if len(set(points)) != n:
        raise ValueError("duplicate points")
    for i, (x, y) in enumerate(points):
        if shape == "square" and not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(f"point {i} is outside the unit square")
        if shape == "triangle" and (x < 0 or y < 0 or x + y > 1):
            raise ValueError(f"point {i} is outside the triangle")
    smallest = min(area(p, q, r) for p, q, r in itertools.combinations(points, 3))
    if shape == "square":
        return smallest
    if shape == "triangle":
        return 2 * smallest
    region = hull_area(points)
    return smallest / region if region else Fraction(0)


def check(certificate: dict, against: Fraction | None = None) -> tuple[str | None, Fraction | None]:
    """(None, value) if the certificate holds, otherwise (reason, value or None)."""
    instance = certificate.get("instance")
    if not isinstance(instance, dict):
        return "certificate has no instance table", None
    try:
        value = exact_value(instance.get("shape"), instance.get("n"), certificate.get("solution"))
    except ValueError as exc:
        return str(exc), None
    score = value.numerator / value.denominator  # integer / integer: correctly rounded
    if certificate.get("score") != score:
        return f"score in the certificate is {certificate.get('score')!r}, the point set's is {score!r}", value
    if against is not None and not value > against:
        return f"value {float(value)!r} does not exceed {float(against)!r}", value
    return None, value


def main(argv: list[str]) -> int:
    args = argv[1:]
    against = None
    if "--against" in args:
        at = args.index("--against")
        try:
            against = Fraction(args[at + 1])
        except (IndexError, ValueError, ZeroDivisionError):
            print(__doc__)
            return 2
        del args[at:at + 2]
    if len(args) != 1:
        print(__doc__)
        return 2
    try:
        with open(args[0]) as f:
            certificate = json.load(f)
        if isinstance(certificate, dict):
            reason, value = check(certificate, against)
        else:
            reason, value = "certificate is not a JSON object", None
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a failed check
        reason, value = f"could not read the certificate: {type(exc).__name__}: {exc}", None
    if reason:
        print(f"FAIL: {reason}")
        return 1
    inst = certificate["instance"]
    extra = f", exceeds {against}" if against is not None else ""
    print(f"OK: {inst['shape']} n={inst['n']}, value {value.numerator}/{value.denominator} "
          f"= {certificate['score']!r}, exact rational check{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
