"""Evaluator for flat polynomials: the EinsteinArena verifier (problem 12), to the letter.

A solution is a list of n coefficients, each +1 or -1, highest power first (the order np.poly1d uses):

    g(z) = c_0 z^(n-1) + c_1 z^(n-2) + ... + c_(n-1)

`arena_score` below is the arena's verifier, copied from

    GET https://einsteinarena.com/api/problems/flat-polynomials   (field "verifier")

as read on 2026-10-03T21:40:22Z (a copy is in published/problem_12.json). The only change is that the
hard-coded length 70 is replaced by the instance's n, so that other sizes can be used as held-out
instances; for n = 70 the code is the arena's, line for line. Note what it computes:

  * the maximum of |g| over 10^6 points z = exp(i t), t = numpy.linspace(0, 2 pi, 10^6). The first and
    last points coincide, so these are the 999999-th roots of unity: a SAMPLED maximum, not the true
    supremum (the true one is larger, by at most about 1.2e-8 relative for n = 70, see verify.py);
  * divided by sqrt(n + 1), i.e. sqrt(71) for the arena's n = 70, not by sqrt(n) = ||g||_2.

Arithmetic. The arena's number is a float64 computation and this evaluator reproduces it, so it is not
exact: it is the arena's score. The coefficients themselves are checked exactly (integers +1 or -1).
verify.py recomputes the same sampled maximum by an unrelated method (exact integer autocorrelations and
a cosine sum) and also bounds the true supremum rigorously.

`evaluate` never raises.
"""

from __future__ import annotations

import math

import numpy as np

NUM_POINTS = 1_000_000
MAX_N = 4096


# ---- the arena's verifier; only the fixed length 70 is replaced by n ----------------------------
def arena_score(coefficients_list: list[int], n: int) -> float:
    coefficients = np.array(coefficients_list, dtype=np.float64)
    assert len(coefficients) == n, f"Expected {n} coefficients, got {len(coefficients)}"
    assert all(c in (-1, 1) for c in coefficients), "All coefficients must be +1 or -1"
    poly_fn = np.poly1d(coefficients)
    num_points = NUM_POINTS
    zs = np.exp(1j * np.linspace(0, 2 * np.pi, num_points))
    vals = np.abs(poly_fn(zs))
    return float(np.max(vals) / np.sqrt(len(coefficients) + 1))
# ---- end of the arena's code --------------------------------------------------------------------


def instance_key(instance: dict) -> str:
    """{"n": 70} -> "n70"."""
    try:
        return f"n{int(instance['n'])}"
    except Exception:  # noqa: BLE001 - a key for a malformed instance, rather than an exception
        return "n?"


def _invalid(reason: str, **detail) -> dict:
    return {"valid": False, "score": 0.0, "detail": {"reason": reason, **detail}}


def evaluate(instance: dict, solution) -> dict:
    """{"valid": bool, "score": float, "detail": {...}}; never raises."""
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise on malformed input"
        return _invalid(f"evaluator could not read the solution: {type(exc).__name__}: {exc}")


def _evaluate(instance, solution) -> dict:
    n = instance.get("n") if isinstance(instance, dict) else None
    if isinstance(n, bool) or not isinstance(n, int) or n < 1 or n > MAX_N:
        return _invalid(f"instance must be a table with an integer n between 1 and {MAX_N}")
    if hasattr(solution, "tolist"):
        solution = solution.tolist()
    if isinstance(solution, dict) and "coefficients" in solution:  # the arena's own submission format
        solution = solution["coefficients"]
    if not isinstance(solution, (list, tuple)):
        return _invalid("solution must be a list of +1/-1 coefficients")
    if len(solution) != n:
        return _invalid(f"solution has {len(solution)} coefficients, expected {n}", length=len(solution))
    coeffs: list[int] = []
    for i, c in enumerate(solution):
        # exact check: the integers 1 and -1 (floats 1.0 / -1.0 are accepted, as the arena accepts them)
        if isinstance(c, bool) or not isinstance(c, (int, float)) or c not in (1, -1):
            return _invalid(f"coefficient {i} is {c!r}, not +1 or -1")
        coeffs.append(int(c))
    score = arena_score(coeffs, n)
    if not math.isfinite(score):
        return _invalid(f"score is not finite: {score!r}")
    return {
        "valid": True,
        "score": score,
        "detail": {
            "n": n,
            "max_modulus_sampled": score * math.sqrt(n + 1),
            "normalisation": f"sqrt(n + 1) = sqrt({n + 1})",
            "sum_of_coefficients": sum(coeffs),
            "arithmetic": "float64, np.poly1d at 10^6 linspace points: the arena verifier",
        },
    }
