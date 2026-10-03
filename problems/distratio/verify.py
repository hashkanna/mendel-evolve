#!/usr/bin/env python3
"""Independent check of a distratio certificate. Shares no code with evaluate.py.

    python verify.py certificate.json       exit 0 if the solution is valid and the score is right

A certificate is {"instance": {"n": N, "d": D}, "score": S, "solution": [[x, y, ...], ...], ...}
(D defaults to 2).

evaluate.py is the arena's float64 verifier (numpy broadcasting, sqrt, then the ratio squared). This
file computes the same quantity two other ways and compares:

  1. EXACT. Every double is m * 2^e, so after multiplying every coordinate by 2^E (E large enough)
     all coordinates are Python integers. Squared distances are then exact integers, and
     R = max d^2 / min d^2 is an exact fraction; nothing is rounded until the final comparison.
  2. FLOAT, by scipy.spatial.distance.pdist, an implementation unrelated to evaluate.py's.

The certificate passes when the points are N distinct points in D dimensions with finite coordinates,
the arena's distinctness condition min distance >= 1e-12 holds exactly, the exact value agrees with
the certificate's score to 1e-12 relative (the float verifier rounds; observed differences are a few
units in the last place), and the pdist value agrees with the exact one to 1e-10.
"""

from __future__ import annotations

import json
import math
import sys
from fractions import Fraction

EXACT_TOL = 1e-12
PDIST_TOL = 1e-10


def exact_ratio(points: list[list[float]]) -> tuple[Fraction, int, int, tuple, tuple, int]:
    """(R, min d^2, max d^2 as scaled integers, argmin pair, argmax pair, scale exponent)."""
    ratios = [float(c).as_integer_ratio() for p in points for c in p]
    unit = max(den for _, den in ratios)  # powers of two: the largest is a common denominator
    it = iter(num * (unit // den) for num, den in ratios)
    ints = [[next(it) for _ in p] for p in points]
    lo = hi = None
    lo_pair = hi_pair = (-1, -1)
    for i in range(len(ints)):
        for j in range(i + 1, len(ints)):
            s = sum((a - b) ** 2 for a, b in zip(ints[i], ints[j]))
            if lo is None or s < lo:
                lo, lo_pair = s, (i, j)
            if hi is None or s > hi:
                hi, hi_pair = s, (i, j)
    if not lo:
        raise ZeroDivisionError("two points coincide")
    return Fraction(hi, lo), lo, hi, lo_pair, hi_pair, unit


def pdist_ratio(points: list[list[float]]) -> float:
    import numpy as np
    from scipy.spatial.distance import pdist

    dist = pdist(np.asarray(points, dtype=np.float64))
    return float((dist.max() / dist.min()) ** 2)


def check(certificate: dict) -> tuple[str | None, dict]:
    """(None, numbers) if the certificate holds, otherwise (reason, numbers)."""
    info: dict = {}
    inst = certificate.get("instance") or {}
    n, d = inst.get("n"), inst.get("d", 2)
    solution, claimed = certificate.get("solution"), certificate.get("score")
    if isinstance(solution, dict):
        solution = solution.get("vectors")
    if type(n) is not int or n < 2 or type(d) is not int or d < 1:
        return "instance must have integer n >= 2 and d >= 1", info
    if not isinstance(solution, list) or len(solution) != n:
        return f"expected a list of {n} points", info
    for i, p in enumerate(solution):
        if not isinstance(p, list) or len(p) != d:
            return f"point {i} does not have {d} coordinates", info
        if any(type(c) not in (int, float) or not math.isfinite(c) for c in p):
            return f"point {i} has a coordinate that is not a finite number", info
    if type(claimed) is not float or not math.isfinite(claimed):
        return "score must be a finite float", info
    try:
        exact, lo, hi, lo_pair, hi_pair, unit = exact_ratio(solution)
    except ZeroDivisionError as exc:
        return str(exc), info
    info.update(exact=float(exact), min_pair=lo_pair, max_pair=hi_pair,
                exact_minus_claimed=float(exact - Fraction(claimed)))
    if Fraction(lo, unit * unit) < Fraction(1e-12) ** 2:
        return "two points are closer than the arena's threshold of 1e-12", info
    if abs(exact - Fraction(claimed)) > EXACT_TOL * exact:
        return f"score in the certificate is {claimed!r}, the exact value is {float(exact)!r}", info
    by_pdist = pdist_ratio(solution)
    info["pdist"] = by_pdist
    if abs(by_pdist - float(exact)) > PDIST_TOL * float(exact):
        return f"pdist cross-check gives {by_pdist!r}, the exact value is {float(exact)!r}", info
    return None, info


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    info: dict = {}
    try:
        with open(argv[1]) as f:
            certificate = json.load(f)
        if isinstance(certificate, dict):
            reason, info = check(certificate)
        else:
            reason = "certificate is not a JSON object"
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a failed check
        reason = f"could not check the certificate: {type(exc).__name__}: {exc}"
    if reason:
        print(f"FAIL: {reason}")
        return 1
    inst = certificate["instance"]
    print(f"OK: {inst['n']} points in {inst.get('d', 2)}D, score {certificate['score']!r}; exact rational value "
          f"{info['exact']!r} (exact - claimed = {info['exact_minus_claimed']:.2e}), pdist value {info['pdist']!r}, "
          f"closest pair {list(info['min_pair'])}, farthest pair {list(info['max_pair'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
