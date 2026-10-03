"""Evaluator for the max/min distance ratio problem: the EinsteinArena verifier, to the letter.

An instance is {"n": N, "d": D} (D defaults to 2). A solution is a list of N points, each a list of D
finite numbers (the arena's own submission object {"vectors": [...]} is accepted too).

`evaluate_arena` below is the arena's verifier for problem 5, copied from

    GET https://einsteinarena.com/api/problems/min-distance-ratio-2d   (field "verifier")

as read on 2026-10-03T21:41:02Z, with ONE change: the arena hard-codes the shape (16, 2); here the
expected shape is (N, D) from the instance, so the same code scores the 3D instances of the
AlphaEvolve paper and the held-out sizes. For {"n": 16, "d": 2} it is the arena's code unchanged.
The score is its return value:

    R = (max_{i<j} |p_i - p_j| / min_{i<j} |p_i - p_j|)^2      (float64, numpy)

and the solution is invalid if the smallest distance is below 1e-12. Lower is better.

Arithmetic. The score is the arena's float64 number, so that a value here is the value the arena
would show (checked bit for bit on the three published top solutions, see records.json). The problem
allows an exact computation as well, and this file does it: every double is a dyadic rational, so
every squared distance is an exact rational and R = max d^2 / min d^2 is an exact fraction. That
exact value is in detail["exact"], and the evaluator rejects a solution whose float score disagrees
with it by more than 1e-12 relative (it never does for sane inputs; it guards against overflow and
cancellation in extreme coordinates). `verify.py` repeats the exact computation independently.

`evaluate` never raises.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

MAX_N = 200
MAX_D = 8
MAX_ABS_COORD = 1e100  # squares of larger doubles overflow numpy's float64
AGREE_REL = 1e-12


# ---- from the arena, shape generalised from (16, 2) to (n, d) --------------------------------
def evaluate_arena(data: dict, n: int = 16, d: int = 2) -> float:
    vectors = np.array(data["vectors"], dtype=np.float64)
    if vectors.ndim != 2 or vectors.shape[0] != n or vectors.shape[1] != d:
        raise ValueError(f"Expected exactly {n} points in {d} dimensions, shape ({n}, {d})")
    n = vectors.shape[0]
    diff = vectors[:, None, :] - vectors[None, :, :]
    dist_matrix = np.sqrt(np.sum(diff**2, axis=-1))
    mask = np.triu(np.ones((n, n), dtype=bool), k=1)
    pairwise = dist_matrix[mask]
    min_d = np.min(pairwise)
    if min_d < 1e-12:
        raise ValueError("Points must be distinct (min distance < 1e-12)")
    max_d = np.max(pairwise)
    return float((max_d / min_d) ** 2)
# ---- end of arena code -----------------------------------------------------------------------


def instance_key(instance: dict) -> str:
    """{"n": 16, "d": 2} -> "n16" (2D, the arena's problem); {"n": 14, "d": 3} -> "d3n14"."""
    try:
        n, d = int(instance["n"]), int(instance.get("d", 2))
        return f"n{n}" if d == 2 else f"d{d}n{n}"
    except Exception:  # noqa: BLE001 - a key for a malformed instance, rather than an exception
        return "distratio?"


def _invalid(reason: str, **detail) -> dict:
    return {"valid": False, "score": 0.0, "detail": {"reason": reason, **detail}}


def evaluate(instance: dict, solution) -> dict:
    """{"valid": bool, "score": float, "detail": {...}}; never raises."""
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise on malformed input"
        return _invalid(f"evaluator could not read the solution: {type(exc).__name__}: {exc}")


def _exact(points: list[list[float]]) -> tuple[Fraction, Fraction, Fraction, tuple, tuple]:
    """(R, min d^2, max d^2, argmin pair, argmax pair), all exact."""
    q = [[Fraction(c) for c in p] for p in points]
    lo = hi = None
    lo_pair = hi_pair = (-1, -1)
    for i in range(len(q)):
        for j in range(i + 1, len(q)):
            s = sum((a - b) * (a - b) for a, b in zip(q[i], q[j]))
            if lo is None or s < lo:
                lo, lo_pair = s, (i, j)
            if hi is None or s > hi:
                hi, hi_pair = s, (i, j)
    return hi / lo if lo else Fraction(0), lo, hi, lo_pair, hi_pair


def _evaluate(instance, solution) -> dict:
    if not isinstance(instance, dict):
        return _invalid("instance must be a table with n (and optionally d)")
    n, d = instance.get("n"), instance.get("d", 2)
    for name, v, top in (("n", n, MAX_N), ("d", d, MAX_D)):
        if isinstance(v, bool) or not isinstance(v, int) or not 2 <= v <= top:
            return _invalid(f"instance.{name} must be an integer from 2 to {top}")
    if hasattr(solution, "tolist"):
        solution = solution.tolist()
    if isinstance(solution, dict) and "vectors" in solution:  # the arena's own submission format
        solution = solution["vectors"]
    if not isinstance(solution, (list, tuple)):
        return _invalid("solution must be a list of points")
    if len(solution) != n:
        return _invalid(f"solution has {len(solution)} points, expected {n}", points=len(solution))
    points: list[list[float]] = []
    for i, p in enumerate(solution):
        if not isinstance(p, (list, tuple)) or len(p) != d:
            return _invalid(f"point {i} is not a list of {d} coordinates")
        for c in p:
            if isinstance(c, bool) or not isinstance(c, (int, float)) or not math.isfinite(c):
                return _invalid(f"point {i}: coordinate {c!r} is not a finite number")
            if abs(c) > MAX_ABS_COORD:
                return _invalid(f"point {i}: coordinate {c!r} exceeds {MAX_ABS_COORD:g} in absolute value")
        points.append([float(c) for c in p])

    exact, lo, hi, lo_pair, hi_pair = _exact(points)
    if lo < Fraction(1e-12) ** 2:
        return _invalid("points must be distinct (min distance < 1e-12)", min_pair=list(lo_pair))
    try:
        score = evaluate_arena({"vectors": points}, n, d)
    except ValueError as exc:
        return _invalid(str(exc))
    if not math.isfinite(score):
        return _invalid(f"score is not finite: {score!r}")
    if abs(Fraction(score) - exact) > AGREE_REL * exact:
        return _invalid(f"float score {score!r} disagrees with the exact value {float(exact)!r}",
                        exact=float(exact))
    return {
        "valid": True,
        "score": score,
        "detail": {
            "n": n,
            "d": d,
            "exact": float(exact),
            "exact_minus_score": float(exact - Fraction(score)),
            "min_pair": list(lo_pair),
            "max_pair": list(hi_pair),
            "arithmetic": "score: the arena's float64 verifier; exact: rational max d^2 / min d^2",
        },
    }
