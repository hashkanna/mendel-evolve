#!/usr/bin/env python3
"""Independent check of a circle-packing certificate. Shares no code with evaluate.py.

    python verify.py certificate.json       exit 0 if the packing is valid and the score is right

A certificate is {"instance": {"n": N}, "score": S, "solution": [[x, y, r], ...], ...}.

evaluate.py works with fractions.Fraction. This file works with plain integers instead: every
double is an integer divided by a power of two, so after multiplying all numbers by the largest
denominator the constraints are comparisons between integers. Two implementations that agree are
harder to fool than one.
"""

from __future__ import annotations

import json
import math
import sys


def check(certificate: dict) -> str | None:
    """None if the certificate holds, otherwise the reason it does not."""
    n = certificate.get("instance", {}).get("n")
    solution = certificate.get("solution")
    if type(n) is not int or n < 1:
        return "instance.n must be a positive integer"
    if not isinstance(solution, list) or len(solution) != n:
        return f"expected a list of {n} circles"
    values: list[float] = []
    for i, circle in enumerate(solution):
        if not isinstance(circle, list) or len(circle) != 3:
            return f"circle {i} is not [x, y, r]"
        for v in circle:
            if type(v) not in (int, float) or not math.isfinite(v):
                return f"circle {i} has a value that is not a finite number"
            values.append(float(v) if type(v) is float else v)
    ratios = [v.as_integer_ratio() for v in values]
    unit = max(den for _, den in ratios)  # denominators are powers of two: the largest is common to all
    scaled = [num * (unit // den) for num, den in ratios]
    xs, ys, rs = scaled[0::3], scaled[1::3], scaled[2::3]
    for i in range(n):
        if rs[i] <= 0:
            return f"circle {i} has a radius that is not positive"
        if xs[i] - rs[i] < 0 or ys[i] - rs[i] < 0 or xs[i] + rs[i] > unit or ys[i] + rs[i] > unit:
            return f"circle {i} is not inside the square"
    for i in range(n):
        for j in range(i + 1, n):
            if (xs[i] - xs[j]) ** 2 + (ys[i] - ys[j]) ** 2 < (rs[i] + rs[j]) ** 2:
                return f"circles {i} and {j} overlap"
    score = sum(rs) / unit  # integer / integer: the exact sum, rounded once
    if certificate.get("score") != score:
        return f"score in the certificate is {certificate.get('score')!r}, the packing's is {score!r}"
    return None


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        with open(argv[1]) as f:
            certificate = json.load(f)
        reason = check(certificate) if isinstance(certificate, dict) else "certificate is not a JSON object"
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a failed check
        reason = f"could not read the certificate: {type(exc).__name__}: {exc}"
    if reason:
        print(f"FAIL: {reason}")
        return 1
    print(f"OK: {certificate['instance']['n']} circles, sum of radii {certificate['score']!r}, exact integer check")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
