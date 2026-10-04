#!/usr/bin/env python3
"""Independent check of a flatpoly certificate. Shares no code with evaluate.py.

    python verify.py certificate.json      exit 0 if the solution is valid and the score is right
    python verify.py published.json        the same for every entry of a saved arena response
                                           (GET /api/solutions/best?problem_id=12), against its "score"

A certificate is {"instance": {"n": N}, "score": S, "solution": [c_0, ..., c_(N-1)], ...}, with every
c_i the integer +1 or -1, highest power first.

evaluate.py is the arena's verifier: Horner's rule (np.poly1d) at the 10^6 points
exp(i t), t = linspace(0, 2 pi, 10^6), maximum of the modulus, divided by sqrt(N + 1). This file computes
the same quantity in two other ways and adds a rigorous statement about the true supremum:

  1. COSINE SUM. The aperiodic autocorrelations a_k = sum_j c_j c_(j+k) are exact integers, and
         |g(e^{it})|^2 = N + 2 sum_{k=1}^{N-1} a_k cos(k t)
     exactly. That trigonometric polynomial is evaluated at the arena's own sample points.
  2. FFT. The arena's points are the 999999-th roots of unity (linspace includes 2 pi, which repeats
     t = 0), so a length-999999 FFT of the coefficients gives g at all of them.
  3. TRUE SUPREMUM. T(t) = |g(e^{it})|^2 is a real trigonometric polynomial of degree d = N - 1, so
     |T''| <= d^2 max T (Bernstein). At the maximiser T' = 0, and some sample lies within h / 2 of it
     (h = 2 pi / 999999), so  max T <= (sampled max T) / (1 - d^2 h^2 / 8).  This brackets the true
     sup |g| / sqrt(N + 1) between the sampled score and an upper bound (about 1.2e-8 higher at N = 70).

The certificate passes when both recomputations agree with its score to 1e-9 relative (observed
differences are about 1e-15) and the coefficients are exactly +1 or -1.
"""

from __future__ import annotations

import ast
import json
import math
import sys

import numpy as np

TOL = 1e-9
POINTS = 1_000_000


def autocorrelations(c: list[int]) -> list[int]:
    n = len(c)
    return [sum(c[j] * c[j + k] for j in range(n - k)) for k in range(n)]


def cosine_sum_max(c: list[int]) -> float:
    """max over the arena's sample points of |g|, from the exact autocorrelations."""
    a = autocorrelations(c)
    t = np.linspace(0.0, 2.0 * math.pi, POINTS)
    T = np.full(POINTS, float(a[0]))
    for k in range(1, len(c)):
        if a[k]:
            T += 2.0 * a[k] * np.cos(k * t)
    return math.sqrt(max(0.0, float(T.max())))


def fft_max(c: list[int]) -> float:
    """max |g| over the 999999-th roots of unity, by one FFT (g(w^m) for w = exp(-2 pi i / M) up to
    conjugation, which does not change the modulus for real coefficients)."""
    m = POINTS - 1
    x = np.zeros(m)
    x[:len(c)] = c[::-1]           # x[k] = coefficient of z^k
    return float(np.abs(np.fft.fft(x)).max())


def check(certificate: dict) -> tuple[str | None, dict]:
    info: dict = {}
    n = (certificate.get("instance") or {}).get("n")
    c = certificate.get("solution")
    if isinstance(c, dict):
        c = c.get("coefficients")
    claimed = certificate.get("score")
    if type(n) is not int or n < 2:
        return "instance.n must be an integer >= 2", info
    if not isinstance(c, list) or len(c) != n:
        return f"expected a list of {n} coefficients", info
    if any(type(v) is not int or v not in (1, -1) for v in c):
        return "every coefficient must be the integer +1 or -1", info
    if type(claimed) is not float or not math.isfinite(claimed):
        return "score must be a finite float", info
    norm = math.sqrt(n + 1)
    by_cos = cosine_sum_max(c) / norm
    by_fft = fft_max(c) / norm
    d, h = n - 1, 2.0 * math.pi / (POINTS - 1)
    shrink = 1.0 - d * d * h * h / 8.0
    info.update(cosine_sum=by_cos, fft=by_fft, sup_upper_bound=by_cos / math.sqrt(shrink) * (1 + 1e-12),
                merit_factor=n * n / (2.0 * sum(a * a for a in autocorrelations(c)[1:]) or float("inf")))
    if abs(by_cos - claimed) > TOL * claimed:
        return f"score in the certificate is {claimed!r}, the cosine sum gives {by_cos!r}", info
    if abs(by_fft - claimed) > TOL * claimed:
        return f"score in the certificate is {claimed!r}, the FFT gives {by_fft!r}", info
    return None, info


def _arena_entries(data: list) -> list[dict]:
    out = []
    for e in data:
        raw = e["data"]
        sol = ast.literal_eval(raw) if isinstance(raw, str) else raw   # an object; tolerate a repr string
        coeffs = [int(v) for v in sol["coefficients"]]
        out.append({"instance": {"n": len(coeffs)}, "score": float(e["score"]), "solution": coeffs,
                    "label": f"arena id {e.get('id')} ({e.get('agentName')})"})
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    try:
        with open(argv[1]) as f:
            data = json.load(f)
        certs = _arena_entries(data) if isinstance(data, list) else [data]
    except Exception as exc:  # noqa: BLE001 - anything unreadable is a failed check
        print(f"FAIL: could not read {argv[1]}: {type(exc).__name__}: {exc}")
        return 1
    failed = 0
    for cert in certs:
        label = cert.get("label", argv[1])
        try:
            reason, info = check(cert) if isinstance(cert, dict) else ("certificate is not a JSON object", {})
        except Exception as exc:  # noqa: BLE001
            reason, info = f"could not check: {type(exc).__name__}: {exc}", {}
        if reason:
            failed += 1
            print(f"FAIL {label}: {reason}")
        else:
            print(f"OK {label}: n = {cert['instance']['n']}, score {cert['score']!r}; cosine sum {info['cosine_sum']!r}, "
                  f"FFT {info['fft']!r}; true sup / sqrt(n+1) <= {info['sup_upper_bound']!r}; "
                  f"merit factor {info['merit_factor']:.4f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
