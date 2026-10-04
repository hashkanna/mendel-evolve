#!/usr/bin/env python3
"""Independent check of a minoverlap certificate. Shares no code with evaluate.py.

    python verify.py certificate.json       exit 0 if the solution is valid and the score is right

A certificate is {"instance": {"n": N}, "score": S, "solution": [h_0, ..., h_(N-1)], ...}
(the format mendel.campaign writes). The arena's {"values": [...]} is accepted as the solution too.

evaluate.py is the arena's float64 verifier (numpy.correlate). This file computes the same quantity
two other ways and compares:

  1. EXACT. Every double is an integer divided by a power of two, so after scaling by the largest
     denominator the heights are integers a_i with sum T. The arena rescales h to sum n/2, i.e.
     h_i = lam a_i with lam = n / (2 T). Its correlation with 1 - h at shift s is

         c_s = lam P_s - lam^2 R_s,   P_s = sum over the overlap of a_(m+s),  R_s = sum a_(m+s) a_m,

     where P_s is a difference of prefix sums and R_s (the autocorrelation of the integers a_i) is one
     big-integer product (Kronecker substitution). The score max_s c_s * 2 / n is an exact rational;
     the validity conditions are checked exactly too: 0 <= h_i <= 1 before the rescaling, and after
     it h_i <= 1 + 1e-12 (see RESCALE_SLACK: the arena's own check is in float64).
  2. FLOAT, by FFT (numpy.fft), an algorithm unrelated to numpy.correlate's direct sums.

The certificate passes when the exact value agrees with the certificate's score to 1e-12 relative (the
float verifier rounds, observed differences are below 1e-15; the arena's minImprovement is 1e-7) and
with the FFT value to 1e-9.
"""

from __future__ import annotations

import json
import math
import sys
from fractions import Fraction

EXACT_TOL = 1e-12
FFT_TOL = 1e-9
# The arena rescales in float64 and skips the rescaling when the float sum is exactly n / 2. Published
# solution 2407 has float sum 256.0 but exact sum 256 - 6.4e-16, so exact rescaling lifts its height 1.0
# to 1 + 2.5e-18; the arena accepts it. Exact rescaling may therefore exceed 1 by this much.
RESCALE_SLACK = Fraction(1, 10**12)


def _autocorrelation(a: list[int]) -> list[int]:
    """R_s = sum_m a_(m+s) a_m for s = 0 .. n-1, for non-negative integers, by one big product."""
    n = len(a)
    width = max(1, max(v.bit_length() for v in a))
    slot = (2 * width + n.bit_length() + 1 + 7) // 8  # bytes per digit; a digit is at most n * max(a)^2
    forward = int.from_bytes(b"".join(v.to_bytes(slot, "little") for v in a), "little")
    backward = int.from_bytes(b"".join(v.to_bytes(slot, "little") for v in reversed(a)), "little")
    raw = (forward * backward).to_bytes(slot * (2 * n - 1) + 1, "little")
    if raw[slot * (2 * n - 1):] != b"\0":
        raise ArithmeticError("Kronecker digits overflowed")
    digits = [int.from_bytes(raw[k * slot:(k + 1) * slot], "little") for k in range(2 * n - 1)]
    # digit k of a(x) * reversed-a(x) is sum_i a_i a_(n-1-k+i) = R_(n-1-k)
    return [digits[n - 1 - s] for s in range(n)]


def exact_score(values: list[float]) -> tuple[Fraction | None, str | None, int]:
    """(exact score, reason it is invalid or None, a maximising shift)."""
    n = len(values)
    ratios = [float(v).as_integer_ratio() for v in values]
    if any(num < 0 for num, _ in ratios):
        return None, "a height is negative", 0
    if any(num > den for num, den in ratios):
        return None, "a height is above 1", 0
    unit = max(den for _, den in ratios)  # powers of two: the largest is a common denominator
    a = [num * (unit // den) for num, den in ratios]
    total = sum(a)
    if total == 0:
        return None, "the heights sum to zero", 0
    lam = Fraction(n, 2 * total)
    if max(a) * lam > 1 + RESCALE_SLACK:
        return None, "after rescaling to sum n/2 a height is above 1", 0
    prefix = [0]
    for v in a:
        prefix.append(prefix[-1] + v)
    autocorr = _autocorrelation(a)
    best, best_s = None, 0
    for s in range(-(n - 1), n):
        # overlap: m and m + s both in [0, n); P_s sums a_(m+s), R_|s| is symmetric in the sign of s
        p = prefix[n] - prefix[s] if s >= 0 else prefix[n + s]
        c = lam * p - lam * lam * autocorr[abs(s)]
        if best is None or c > best:
            best, best_s = c, s
    return best * Fraction(2, n), None, best_s


def fft_score(values: list[float]) -> float:
    import numpy as np

    h = np.asarray(values, dtype=np.float64)
    n = len(h)
    h = h * (n / 2.0 / h.sum())
    size = 1 << (2 * n - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(h, size) * np.conj(np.fft.rfft(1.0 - h, size)), size)
    # circular index s (mod size) holds sum_m h_(m+s) (1 - h)_m
    full = np.concatenate([corr[size - (n - 1):], corr[:n]])
    return float(full.max() * 2.0 / n)


def check(certificate: dict) -> tuple[str | None, dict]:
    """(None, numbers) if the certificate holds, otherwise (reason, numbers)."""
    info: dict = {}
    n = (certificate.get("instance") or {}).get("n")
    solution = certificate.get("solution")
    if isinstance(solution, dict):
        solution = solution.get("values")
    claimed = certificate.get("score")
    if type(n) is not int or n < 1:
        return "instance.n must be a positive integer", info
    if not isinstance(solution, list) or len(solution) != n:
        return f"expected a list of {n} heights", info
    for i, v in enumerate(solution):
        if type(v) not in (int, float) or not math.isfinite(v):
            return f"height {i} is not a finite number", info
    if type(claimed) not in (int, float) or not math.isfinite(claimed):
        return "score must be a finite number", info
    exact, reason, shift = exact_score(solution)
    if reason:
        return reason, info
    info["exact"] = float(exact)
    info["argmax_shift"] = shift
    info["exact_minus_claimed"] = float(exact - Fraction(claimed))
    if abs(exact - Fraction(claimed)) > EXACT_TOL * exact:
        return f"score in the certificate is {claimed!r}, the exact value is {float(exact)!r}", info
    by_fft = fft_score(solution)
    info["fft"] = by_fft
    if abs(by_fft - float(exact)) > FFT_TOL * float(exact):
        return f"FFT cross-check gives {by_fft!r}, the exact value is {float(exact)!r}", info
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
    print(f"OK: {certificate['instance']['n']} steps, score {certificate['score']!r}; exact rational value "
          f"{info['exact']!r} (exact - claimed = {info['exact_minus_claimed']:.2e}), FFT value {info['fft']!r}, "
          f"maximum at shift {info['argmax_shift']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
