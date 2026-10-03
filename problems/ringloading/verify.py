#!/usr/bin/env python3
"""Independent check of a ringloading certificate. Shares no code with evaluate.py.

    python verify.py certificate.json       exit 0 if the solution is valid and the score is right

A certificate is {"instance": {"m": M}, "score": S, "solution": {"pairs": [[u, v], ...]}, ...}
(the format mendel.campaign writes).

evaluate.py computes the score by an integer branch and bound. This file instead runs the
EinsteinArena verifier for problem 30 verbatim (GET https://einsteinarena.com/api/problems/ring-loading-15,
field "verifier", read 2026-10-03T21:40Z): exact Fractions, all 2^M sign choices, no pruning. The only
change is that PAIR_COUNT is set from the certificate's instance (the arena fixes it at 15). The
certificate passes when that brute force accepts the solution and its float equals the certificate's
score exactly (both are one rounding of the same rational).
"""

from __future__ import annotations

import json
import sys

# ---- verbatim from the arena (PAIR_COUNT is reassigned per certificate) ---------------------
import re
from fractions import Fraction

PAIR_COUNT = 15
MAX_RATIONAL_BITS = 64
RATIONAL_PATTERN = re.compile(r"^(?:0|[1-9]\d*)(?:(?:\.\d+)|(?:/[1-9]\d*))?$")


def parse_rational(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        raise ValueError("Values must be rational strings")
    if RATIONAL_PATTERN.fullmatch(value) is None:
        raise ValueError("Values must be nonnegative decimals or fractions")
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise ValueError("Values must be nonnegative decimals or fractions")
    if result < 0:
        raise ValueError("Values must be nonnegative")
    if result.numerator.bit_length() > MAX_RATIONAL_BITS or result.denominator.bit_length() > MAX_RATIONAL_BITS:
        raise ValueError("Reduced numerator and denominator must fit in 64 bits")
    return result


def evaluate(solution: dict) -> float:
    pairs = solution["pairs"]
    if not isinstance(pairs, list) or len(pairs) != PAIR_COUNT:
        raise ValueError("Expected exactly 15 pairs")

    checked = []
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2:
            raise ValueError("Each entry must be a pair [u, v]")
        u = parse_rational(pair[0])
        v = parse_rational(pair[1])
        if u + v > 1:
            raise ValueError("Every pair must satisfy u + v <= 1")
        checked.append((u, v))

    best = None
    for mask in range(1 << PAIR_COUNT):
        values = [
            -u if mask & (1 << i) else v
            for i, (u, v) in enumerate(checked)
        ]
        total = sum(values, Fraction(0))
        prefix = Fraction(0)
        worst = Fraction(0)
        for value in values:
            prefix += value
            worst = max(worst, abs(2 * prefix - total))
        if best is None or worst < best:
            best = worst

    return float(best)
# ---- end of verbatim code -------------------------------------------------------------------


def check(certificate: dict) -> tuple[str | None, float | None]:
    global PAIR_COUNT
    m = (certificate.get("instance") or {}).get("m")
    if type(m) is not int or not 1 <= m <= 20:
        return "instance.m must be an integer between 1 and 20", None
    claimed = certificate.get("score")
    if type(claimed) not in (int, float):
        return "score must be a number", None
    solution = certificate.get("solution")
    if isinstance(solution, list):
        solution = {"pairs": solution}
    if not isinstance(solution, dict):
        return "solution must be {\"pairs\": [...]}", None
    PAIR_COUNT = m
    try:
        value = evaluate(solution)
    except Exception as exc:  # noqa: BLE001 - the arena rejects the solution
        return f"the arena verifier rejects the solution: {type(exc).__name__}: {exc}", None
    if value != float(claimed):
        return f"score in the certificate is {claimed!r}, the arena verifier gives {value!r}", value
    return None, value


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        with open(argv[1]) as f:
            certificate = json.load(f)
        reason, value = check(certificate) if isinstance(certificate, dict) else ("not a JSON object", None)
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a failed check
        reason, value = f"could not check the certificate: {type(exc).__name__}: {exc}", None
    if reason:
        print(f"FAIL: {reason}")
        return 1
    print(f"OK: m = {certificate['instance']['m']}, score {value!r} (arena verifier, all {1 << PAIR_COUNT} sign choices)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
