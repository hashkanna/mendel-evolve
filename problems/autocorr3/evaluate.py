"""Evaluator for the third autocorrelation inequality: the EinsteinArena verifier, to the letter.

A solution is a list of n real numbers, the heights of a step function on [-1/4, 1/4].
`verify_and_compute_c3` below is the arena's verifier, copied verbatim from

    GET https://einsteinarena.com/api/problems/third-autocorrelation-inequality   (field "verifier")

as read on 2026-10-03T19:14:06Z. The score is its return value. Note what it computes:
abs(np.max(conv)), the absolute value OUTSIDE the maximum. conv[0] = f[0]^2 >= 0, so the maximum
is never negative and the abs() does nothing: negative values of the autoconvolution are not
penalised. This is the "|max f*f|" variant, not the "max |f*f|" one (see problem.toml).

Arithmetic. The arena's number is a float64 computation and this evaluator reproduces that
computation, so it is not exact rational arithmetic: numpy.convolve sums in an order that depends on
the platform's BLAS, and the last one or two units in the last place (about 4e-16 relative) differ
between machines. `verify.py` computes the exact rational value independently.

On top of the arena's own check, a solution must be a list of exactly instance["n"] finite numbers.
`evaluate` never raises.
"""

from __future__ import annotations

import math

import numpy as np

MAX_N = 1_000_000  # nothing the arena has published is longer than 25600


# ---- verbatim from the arena -----------------------------------------------------------------
def verify_and_compute_c3(values: list[float]) -> float:
    f = np.array(values, dtype=np.float64)
    n_points = len(values)
    dx = 0.5 / n_points
    integral_f_sq = (np.sum(f) * dx) ** 2
    if integral_f_sq < 1e-9:
        raise ValueError("Function integral is close to zero, ratio is unstable.")
    conv = np.convolve(f, f, mode="full")
    scaled_conv = conv * dx
    max_conv = abs(np.max(scaled_conv))
    return float(max_conv / integral_f_sq)
# ---- end of verbatim code --------------------------------------------------------------------


def instance_key(instance: dict) -> str:
    """{"n": 4096} -> "n4096"."""
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
        score = verify_and_compute_c3(values)
    except ValueError as exc:
        return _invalid(str(exc))
    if not math.isfinite(score):
        return _invalid(f"score is not finite: {score!r}")
    f = np.array(values, dtype=np.float64)
    conv = np.convolve(f, f, mode="full")
    return {
        "valid": True,
        "score": score,
        "detail": {
            "n": n,
            "argmax_shift": int(np.argmax(conv)),
            "min_over_max_conv": float(np.min(conv) / np.max(conv)),
            "sum": float(np.sum(f)),
            "variant": "|max f*f| (abs outside the max, a no-op); negative f*f not penalised",
            "arithmetic": "float64 numpy.convolve, the arena verifier verbatim",
        },
    }
