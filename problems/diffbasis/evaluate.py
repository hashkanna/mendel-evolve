"""Evaluator for difference bases (Tao et al. problem 6.7; EinsteinArena problem 19, `difference-bases`).

A solution is a list of non-negative integers B. Its score is the one the public EinsteinArena verifier
computes,

    GET https://einsteinarena.com/api/problems/difference-bases          (field "verifier")

read on 2026-10-03T21:40:04Z and copied verbatim below as `arena_evaluate` (a copy of the whole problem
record is in published/problem_19.json):

    B     = sorted(set(int(x) for x in B)), with 0 added if it is missing
    v     = the largest integer >= 1 such that every one of 1, ..., v is a difference b - b' of B
    score = |B|^2 / v                                                    (lower is better)

and the score is infinite (here: invalid) when |B| > 2000 or 1 is not a difference.

Arithmetic. |B| and v are integers, and Python's int / int is correctly rounded, so the arena's float is
the exact rational |B|^2 / v rounded once. `evaluate` computes v with integers only and returns
float(Fraction(|B|^2, v)), which is the same double; detail carries the exact numerator and denominator.

Instances. The leaderboard is one number for every |B| <= 2000. An instance {n = N} here means "a set of
exactly N elements, counted the way the arena counts them" (after removing duplicates and adding 0), so
that N is the size the solver works at.

On top of the arena's own checks, this evaluator is stricter in three places, each a case the arena's
schema ("list of non-negative integers") excludes but its code would silently accept: every entry must
be a Python int (not bool, not a float such as 3.7, which int() would truncate, not a string), every entry
must be >= 0, and the arena-counted size must equal instance["n"]. `evaluate` never raises.
"""

from __future__ import annotations

from fractions import Fraction

MAX_SIZE = 2000          # the arena's limit on |B|
MAX_VALUE = 10**9        # far above anything useful (v <= |B|(|B|-1)/2 <= 1999000); keeps memory bounded


# ---- verbatim from the arena -----------------------------------------------------------------
def arena_evaluate(data):
    B_list = data["set"]
    B = sorted(set(int(x) for x in B_list))
    if 0 not in B:
        B = sorted([0] + B)
    if len(B) > 2000:
        return float("inf")
    diffs = set()
    for i in range(len(B)):
        for j in range(i+1, len(B)):
            diffs.add(B[j] - B[i])
    if not diffs:
        return float("inf")
    max_d = max(diffs)
    for v in range(1, max_d + 2):
        if v not in diffs:
            if v == 1:
                return float("inf")
            return float(len(B) ** 2 / (v - 1))
    return float("inf")
# ---- end of verbatim code --------------------------------------------------------------------


def instance_key(instance: dict) -> str:
    """{"n": 360} -> "n360"."""
    try:
        return f"n{int(instance['n'])}"
    except Exception:  # noqa: BLE001 - a key for a malformed instance, rather than an exception
        return "n?"


def _invalid(reason: str, **detail) -> dict:
    return {"valid": False, "score": 0.0, "detail": {"reason": reason, **detail}}


def covered_prefix(marks: list[int]) -> int:
    """Largest v >= 0 with every 1..v a positive difference of the sorted, distinct `marks`."""
    if len(marks) < 2:
        return 0
    seen = bytearray(marks[-1] - marks[0] + 2)
    for i, a in enumerate(marks):
        for b in marks[i + 1:]:
            seen[b - a] = 1
    v = 0
    while seen[v + 1]:
        v += 1
    return v


def evaluate(instance: dict, solution) -> dict:
    """{"valid": bool, "score": float, "detail": {...}}; never raises."""
    try:
        return _evaluate(instance, solution)
    except Exception as exc:  # noqa: BLE001 - the contract is "never raise on malformed input"
        return _invalid(f"evaluator could not read the solution: {type(exc).__name__}: {exc}")


def _evaluate(instance, solution) -> dict:
    n = instance.get("n") if isinstance(instance, dict) else None
    if isinstance(n, bool) or not isinstance(n, int) or not 2 <= n <= MAX_SIZE:
        return _invalid(f"instance must be a table with an integer n between 2 and {MAX_SIZE}")
    if isinstance(solution, dict) and "set" in solution:  # the arena's own submission format
        solution = solution["set"]
    if not isinstance(solution, (list, tuple)):
        return _invalid("solution must be a list of non-negative integers")
    if len(solution) > 4 * MAX_SIZE:
        return _invalid(f"solution has {len(solution)} entries; the arena accepts at most {MAX_SIZE} distinct ones")
    for i, x in enumerate(solution):
        if type(x) is not int:
            return _invalid(f"entry {i} is {x!r}, not an integer")
        if not 0 <= x <= MAX_VALUE:
            return _invalid(f"entry {i} is {x}, outside 0..{MAX_VALUE}")
    marks = sorted(set(solution) | {0})
    size = len(marks)
    if size != n:
        return _invalid(f"the set has {size} distinct elements (0 included), expected {n}", size=size)
    v = covered_prefix(marks)
    if v < 1:
        return _invalid("1 is not a difference of the set (the arena scores this as infinity)", size=size)
    score = Fraction(size * size, v)
    return {
        "valid": True,
        "score": float(score),
        "detail": {"size": size, "v": v, "max_element": marks[-1], "numerator": size * size, "denominator": v,
                   "zero_added": 0 not in solution},
    }
