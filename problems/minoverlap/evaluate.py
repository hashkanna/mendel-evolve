"""Evaluator for the Erdos minimum overlap problem: the EinsteinArena verifier, to the letter.

A solution is a list of n numbers in [0, 1], the heights of a step function on [0, 2].
`_normalize_sum_constraint` and `compute_upper_bound` below are the arena's verifier, copied verbatim from

    GET https://einsteinarena.com/api/problems/erdos-min-overlap   (field "verifier")

as read on 2026-10-03T21:40:07Z (a copy of the record is in published/arena_problem_1.json). The score
is the return value of compute_upper_bound.

Arithmetic. The arena's number is a float64 computation and this evaluator reproduces that computation,
so it is not exact rational arithmetic: numpy.correlate sums in an order that may depend on the platform,
and the last unit in the last place can differ between machines (on the three published top solutions
this file is within 3e-16 relative of the arena's numbers). `verify.py` computes the exact rational
value independently. Exactness would be possible here (every double is a dyadic rational), but the
leaderboard ranks the float64 number, so that is the score.

On top of the arena's own checks, a solution must be a list (or {"values": [...]}) of exactly
instance["n"] finite numbers. `evaluate` never raises.
"""

from __future__ import annotations

import math

import numpy as np

MAX_N = 1_000_000  # nothing the arena has published is longer than 3584


# ---- verbatim from the arena -----------------------------------------------------------------
def _normalize_sum_constraint(sequence_array: np.ndarray) -> np.ndarray:
    target_sum = len(sequence_array) / 2.0
    current_sum = float(np.sum(sequence_array))
    if current_sum != target_sum:
        if current_sum == 0.0:
            raise AssertionError("Cannot normalize sequence with zero total sum.")
        sequence_array = sequence_array * (target_sum / current_sum)
    return sequence_array

def compute_upper_bound(sequence: list[float]) -> float:
    sequence_array = np.array(sequence, dtype=np.float64)
    if np.isnan(sequence_array).any():
        raise AssertionError("The sequence contains NaN values.")
    if np.any(sequence_array < 0) or np.any(sequence_array > 1):
        raise AssertionError("All values in the sequence must be between 0 and 1.")
    sequence_array = _normalize_sum_constraint(sequence_array)
    if np.any(sequence_array < 0) or np.any(sequence_array > 1):
        raise AssertionError("After normalization, all values in the sequence must be between 0 and 1.")
    convolution_values = np.correlate(sequence_array, 1 - sequence_array, mode="full")
    return np.max(convolution_values) / len(sequence) * 2
# ---- end of verbatim code --------------------------------------------------------------------


def instance_key(instance: dict) -> str:
    """{"n": 512} -> "n512"."""
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
    if isinstance(solution, dict) and "values" in solution:  # the arena's own submission format
        solution = solution["values"]
    if not isinstance(solution, (list, tuple)):
        return _invalid("solution must be a list of step heights")
    if len(solution) != n:
        return _invalid(f"solution has {len(solution)} steps, expected {n}", steps=len(solution))
    values: list[float] = []
    for i, v in enumerate(solution):
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return _invalid(f"step {i} is not a finite number")
        values.append(float(v))
    try:
        score = float(compute_upper_bound(values))
    except AssertionError as exc:
        return _invalid(str(exc))
    if not math.isfinite(score):
        return _invalid(f"score is not finite: {score!r}")
    h = np.array(values, dtype=np.float64)
    h = h * ((n / 2.0) / float(h.sum()))
    corr = np.correlate(h, 1 - h, mode="full")
    return {
        "valid": True,
        "score": score,
        "detail": {
            "n": n,
            "argmax_shift": int(np.argmax(corr)) - (n - 1),
            "sum_before_scaling": float(sum(values)),
            "arithmetic": "float64 numpy.correlate, the arena verifier verbatim",
        },
    }
