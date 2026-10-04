#!/usr/bin/env python3
"""Independent check of a diffbasis certificate. Shares no code with evaluate.py.

    python verify.py certificate.json       exit 0 if the solution is valid and the score is right

A certificate is {"instance": {"n": N}, "score": S, "solution": [b_0, b_1, ...], ...} (the format
mendel.campaign writes). The arena's own submission format {"set": [...]} is accepted as the solution.

evaluate.py finds the covered differences with a double loop over pairs. This file counts them another
way: with M the largest element, the polynomial P(x) = sum over b of x^b times P(1/x) x^M has, at the
power M + d, the number of pairs (b, b') with b - b' = d. Both polynomials are packed into one big
integer each (Kronecker substitution, base 2^w with w wide enough that no coefficient can carry), and
one big-integer product gives every count at once. v is the first d >= 1 whose count is zero; the
score |B|^2 / v is compared as an exact rational with the certificate's double.
"""

from __future__ import annotations

import json
import sys
from fractions import Fraction


def representation_counts(marks: list[int]) -> list[int]:
    """counts[d] = number of ordered pairs with difference d, for d = 0..max(marks)."""
    top = max(marks)
    slot = (len(marks).bit_length() + 8) // 8     # bytes per coefficient; every coefficient is <= |B|
    p = bytearray(slot * (top + 1))
    q = bytearray(slot * (top + 1))
    for b in marks:
        p[b * slot] = 1
        q[(top - b) * slot] = 1
    product = (int.from_bytes(p, "little") * int.from_bytes(q, "little")).to_bytes(slot * (2 * top + 2), "little")
    return [int.from_bytes(product[(top + d) * slot:(top + d + 1) * slot], "little") for d in range(top + 1)]


def check(certificate: dict) -> tuple[str | None, dict]:
    """(None, numbers) if the certificate holds, otherwise (reason, numbers)."""
    info: dict = {}
    instance = certificate.get("instance")
    n = instance.get("n") if isinstance(instance, dict) else None
    solution = certificate.get("solution")
    if isinstance(solution, dict):
        solution = solution.get("set")
    claimed = certificate.get("score")
    if type(n) is not int or not 2 <= n <= 2000:
        return "instance.n must be an integer between 2 and 2000", info
    if not isinstance(solution, list) or not all(type(x) is int and x >= 0 for x in solution):
        return "solution must be a list of non-negative integers", info
    if not isinstance(claimed, (int, float)) or isinstance(claimed, bool):
        return "score must be a number", info
    marks = sorted(set(solution + [0]))
    info["size"] = len(marks)
    if len(marks) != n:
        return f"{len(marks)} distinct elements with 0 included, the instance asks for {n}", info
    counts = representation_counts(marks)
    if counts[0] != len(marks):
        return "internal error: the zero difference must be counted once per element", info
    v = 0
    while v + 1 < len(counts) and counts[v + 1] > 0:
        v += 1
    info["v"] = v
    if v < 1:
        return "1 is not a difference of the set", info
    exact = Fraction(len(marks) ** 2, v)
    info["exact"] = f"{exact.numerator}/{exact.denominator}"
    info["float"] = float(exact)
    if float(exact) != float(claimed):
        return f"score in the certificate is {claimed!r}, the exact value rounds to {float(exact)!r}", info
    return None, info


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    info: dict = {}
    try:
        with open(argv[1]) as f:
            certificate = json.load(f)
        reason, info = check(certificate) if isinstance(certificate, dict) else ("not a JSON object", {})
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a failed check
        reason = f"could not check the certificate: {type(exc).__name__}: {exc}"
    if reason:
        print(f"FAIL: {reason}")
        return 1
    print(f"OK: |B| = {info['size']}, every difference 1..{info['v']} present, "
          f"score {info['exact']} = {info['float']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
