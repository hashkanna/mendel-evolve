"""Evaluator for the ring loading problem (Tao et al. problem 61; EinsteinArena problem 30).

A solution is {"pairs": [[u_1, v_1], ..., [u_m, v_m]]} (the arena's submission format; a bare list of
pairs is accepted too). Every value is a string that the arena's verifier accepts: a nonnegative
decimal or fraction such as "3/7", matching the arena's regular expression, with reduced numerator
and denominator of at most 64 bits. Every pair must satisfy u + v <= 1. The score is

    A(u, v) = min over z_i in {v_i, -u_i} of max over 1 <= k <= m of |sum_{i<=k} z_i - sum_{i>k} z_i|

which, with P_k = z_1 + ... + z_k and T = P_m, is min_z max_k |2 P_k - T|. This is what the arena's
verifier computes (GET https://einsteinarena.com/api/problems/ring-loading-15, field "verifier", read
2026-10-03T21:40Z; a copy is in published/arena_problem_30.json). The arena fixes m = 15; the
instance parameter m lets the framework also run the same objective at other sizes.

Arithmetic is exact. All values are put over one common denominator, so every prefix sum is an
integer, and the 2^m sign choices are enumerated depth first with a bound: for a partial choice the
spread (max prefix - min prefix) is a lower bound on the final value, because
max(2 maxP - T, T - 2 minP) >= maxP - minP whenever minP <= T <= maxP. A subtree whose spread already
reaches the best value found so far is cut. The result is the exact rational minimum; the float
score is that rational rounded once, as the arena does (float(best)). verify.py recomputes it with
the arena's own brute force, independently of this file.

`evaluate` never raises.
"""

from __future__ import annotations

import math
import re
from fractions import Fraction

MIN_M, MAX_M = 1, 24
MAX_RATIONAL_BITS = 64
RATIONAL_PATTERN = re.compile(r"^(?:0|[1-9]\d*)(?:(?:\.\d+)|(?:/[1-9]\d*))?$")  # the arena's


def instance_key(instance: dict) -> str:
    """{"m": 15} -> "m15"."""
    try:
        return f"m{int(instance['m'])}"
    except Exception:  # noqa: BLE001 - a key for a malformed instance, rather than an exception
        return "m?"


def _invalid(reason: str, **detail) -> dict:
    return {"valid": False, "score": 0.0, "detail": {"reason": reason, **detail}}


def _parse(value, where: str) -> Fraction | str:
    """A Fraction, or the reason the value is rejected (the arena's rules)."""
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        return f"{where}: values must be rational strings of 1 to 80 characters"
    if RATIONAL_PATTERN.fullmatch(value) is None:
        return f"{where}: {value!r} is not a nonnegative decimal or fraction"
    try:
        q = Fraction(value)
    except (ValueError, ZeroDivisionError):
        return f"{where}: {value!r} is not a nonnegative decimal or fraction"
    if q.numerator.bit_length() > MAX_RATIONAL_BITS or q.denominator.bit_length() > MAX_RATIONAL_BITS:
        return f"{where}: reduced numerator and denominator must fit in {MAX_RATIONAL_BITS} bits"
    return q


def ring_load(pairs: list[tuple[Fraction, Fraction]]) -> tuple[Fraction, list[int]]:
    """(exact A(u, v), one minimising sign choice: 1 means z_i = -u_i, 0 means z_i = v_i)."""
    m = len(pairs)
    den = 1
    for u, v in pairs:
        den = math.lcm(den, u.denominator, v.denominator)
    up = [int(u * den) for u, _ in pairs]
    vp = [int(v * den) for _, v in pairs]
    best = 2 * sum(max(a, b) for a, b in zip(up, vp)) + 1  # above any possible value
    best_choice: list[int] = []
    choice = [0] * m
    # iterative depth-first search; stack entries: (depth, prefix, max prefix, min prefix, option)
    stack = [(0, 0, None, None, 1), (0, 0, None, None, 0)]
    while stack:
        depth, prefix, hi, lo, option = stack.pop()
        p = prefix - up[depth] if option else prefix + vp[depth]
        hi = p if hi is None or p > hi else hi
        lo = p if lo is None or p < lo else lo
        if hi - lo >= best:
            continue
        choice[depth] = option
        if depth + 1 == m:
            value = max(2 * hi - p, p - 2 * lo)
            if value < best:
                best, best_choice = value, choice[:]
            continue
        stack.append((depth + 1, p, hi, lo, 1))
        stack.append((depth + 1, p, hi, lo, 0))
    return Fraction(best, den), best_choice


def evaluate(instance: dict, solution) -> dict:
    """{"valid": bool, "score": float, "detail": {...}}; never raises."""
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise on malformed input"
        return _invalid(f"evaluator could not read the solution: {type(exc).__name__}: {exc}")


def _evaluate(instance, solution) -> dict:
    m = instance.get("m") if isinstance(instance, dict) else None
    if isinstance(m, bool) or not isinstance(m, int) or not MIN_M <= m <= MAX_M:
        return _invalid(f"instance must be a table with an integer m between {MIN_M} and {MAX_M}")
    pairs = solution.get("pairs") if isinstance(solution, dict) else solution
    if not isinstance(pairs, list) or len(pairs) != m:
        return _invalid(f"expected exactly {m} pairs [u, v]")
    checked: list[tuple[Fraction, Fraction]] = []
    for i, pair in enumerate(pairs):
        if not isinstance(pair, list) or len(pair) != 2:
            return _invalid(f"entry {i} must be a pair [u, v]")
        u, v = _parse(pair[0], f"pair {i}, u"), _parse(pair[1], f"pair {i}, v")
        for q in (u, v):
            if isinstance(q, str):
                return _invalid(q)
        if u + v > 1:
            return _invalid(f"pair {i}: u + v = {u + v} exceeds 1")
        checked.append((u, v))
    exact, choice = ring_load(checked)
    return {
        "valid": True,
        "score": float(exact),
        "detail": {
            "m": m,
            "exact": f"{exact.numerator}/{exact.denominator}",
            "adversary": "".join("u" if c else "v" for c in choice),  # z_i = -u_i or z_i = v_i
            "arithmetic": "exact rationals (common denominator, integer branch and bound)",
        },
    }
