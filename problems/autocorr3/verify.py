#!/usr/bin/env python3
"""Independent check of an autocorr3 certificate. Shares no code with evaluate.py.

    python verify.py certificate.json       exit 0 if the solution is valid and the score is right

A certificate is {"instance": {"n": N}, "score": S, "solution": [h_0, ..., h_(N-1)], ...}.

evaluate.py is the arena's float64 verifier (numpy.convolve). This file computes the same quantity
two other ways and compares:

  1. EXACT. Every double is an integer divided by a power of two, so after scaling by the largest
     denominator the heights are integers a_i. The whole autoconvolution is then one big-integer
     product (Kronecker substitution: pack the a_i into the digits of one integer in base 2^b, with b
     wide enough that the digits of the square cannot overlap). Its maximum, the sum of the a_i and
     the ratio 2 N max / sum^2 are exact rationals; nothing is rounded until the final conversion
     to a double. This works at full size (N = 16384 takes a second or two).
  2. FLOAT, by FFT (numpy.fft), an algorithm unrelated to numpy.convolve's direct sums.

The certificate passes when the exact value agrees with the certificate's score to 1e-10 relative
(the float verifier rounds; the observed differences are about 1e-15) and with the FFT value to 1e-8,
and the arena's validity condition (sum * 0.5 / N)^2 >= 1e-9 holds in exact arithmetic.
"""

from __future__ import annotations

import json
import math
import sys
from fractions import Fraction

EXACT_TOL = 1e-10
FFT_TOL = 1e-8


def exact_score(values: list[float]) -> tuple[Fraction, int, Fraction]:
    """(exact score, a shift where the maximum is attained, exact sum of the heights)."""
    n = len(values)
    ratios = [float(v).as_integer_ratio() for v in values]
    unit = max(den for _, den in ratios)  # denominators are powers of two: the largest is common to all
    a = [num * (unit // den) for num, den in ratios]
    total = sum(a)
    width = max(abs(v).bit_length() for v in a)
    # |digit of the square| <= n * 2^(2 width); one more bit for the sign offset, one to spare
    slot_bytes = (2 * width + n.bit_length() + 2 + 7) // 8
    pos = int.from_bytes(b"".join((v if v > 0 else 0).to_bytes(slot_bytes, "little") for v in a), "little")
    neg = int.from_bytes(b"".join((-v if v < 0 else 0).to_bytes(slot_bytes, "little") for v in a), "little")
    square = (pos - neg) ** 2
    # add 2^(8 slot_bytes - 1) to every digit so that all digits are non-negative, then read them off
    half = 1 << (8 * slot_bytes - 1)
    m = 2 * n - 1
    offset = int.from_bytes(half.to_bytes(slot_bytes, "little") * m, "little")
    raw = (square + offset).to_bytes(slot_bytes * m + 1, "little")
    if raw[slot_bytes * m:] != b"\0":
        raise ArithmeticError("Kronecker digits overflowed")
    best, best_k = None, -1
    for k in range(m):
        c = int.from_bytes(raw[k * slot_bytes:(k + 1) * slot_bytes], "little") - half
        if best is None or c > best:
            best, best_k = c, k
    if total == 0:
        raise ZeroDivisionError("the heights sum to zero")
    return Fraction(2 * n * abs(best), total * total), best_k, Fraction(total, unit)


def fft_score(values: list[float]) -> float:
    import numpy as np

    f = np.asarray(values, dtype=np.float64)
    n = len(f)
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(f, size)
    conv = np.fft.irfft(spectrum * spectrum, size)[:2 * n - 1]
    return float(2 * n * abs(conv.max()) / f.sum() ** 2)


def check(certificate: dict) -> tuple[str | None, dict]:
    """(None, numbers) if the certificate holds, otherwise (reason, numbers)."""
    info: dict = {}
    n = certificate.get("instance", {}).get("n")
    solution = certificate.get("solution")
    claimed = certificate.get("score")
    if type(n) is not int or n < 1:
        return "instance.n must be a positive integer", info
    if not isinstance(solution, list) or len(solution) != n:
        return f"expected a list of {n} heights", info
    for i, v in enumerate(solution):
        if type(v) not in (int, float) or not math.isfinite(v):
            return f"height {i} is not a finite number", info
    if type(claimed) is not float or not math.isfinite(claimed):
        return "score must be a finite float", info
    exact, shift, total = exact_score(solution)
    info["exact"] = float(exact)
    info["argmax_shift"] = shift
    info["exact_minus_claimed"] = float(exact - Fraction(claimed))
    if (total * Fraction(1, 2 * n)) ** 2 < Fraction(1e-9):
        return "(integral of f)^2 is below the arena's threshold of 1e-9", info
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
