"""Make a packing exactly feasible by shrinking radii only, so that the strict evaluator can score it.

OpenEvolve's evaluator accepts overlaps of up to 1e-6 and radii of zero; Mendel's evaluator
(problems/circle_packing/evaluate.py) accepts neither. Almost every program OpenEvolve produces
therefore fails the strict test as it stands, often only by rounding error. `repair` answers
"what is this packing worth once it is feasible", without giving the program credit for anything
it did not do:

  * centres are kept. The only exceptions are centres on or outside the boundary (clamped 1e-6
    inside) and centres that coincide with an earlier one (moved 1e-6 along x): no positive radius
    is possible there otherwise;
  * a radius is never enlarged. The only exception is a radius that is zero or negative, which
    becomes 5e-7, because the strict evaluator requires radii to be positive;
  * radii are then reduced until the exact test passes, two ways, and the better result is kept:
      (a) all radii together, by the smallest factor 1 - 2^(k-53) that works (up to 0.1%);
      (b) only where needed: each radius capped at the distance to the nearest side, then each
          overlapping pair scaled down in proportion, in index order (the rule of OpenEvolve's own
          initial program), followed by (a) for the last few units of rounding.

The procedure is frozen here on purpose: it is a copy of the feasibility code of the Mendel seed
solver, kept apart so that the baseline's scores do not move when the solver evolves.
"""

from __future__ import annotations

import math

import numpy as np

MIN_GAP = 1e-6


def exactly_feasible(centers: np.ndarray, radii: np.ndarray) -> bool:
    """The strict evaluator's test in integer arithmetic (a double is an integer over a power of two)."""
    n = len(radii)
    values = [float(v) for v in centers[:, 0]] + [float(v) for v in centers[:, 1]] + [float(v) for v in radii]
    if not all(math.isfinite(v) for v in values):
        return False
    ratios = [v.as_integer_ratio() for v in values]
    unit = max(den for _, den in ratios)
    scaled = [num * (unit // den) for num, den in ratios]
    xs, ys, rs = scaled[:n], scaled[n:2 * n], scaled[2 * n:]
    for i in range(n):
        if rs[i] <= 0 or xs[i] < rs[i] or ys[i] < rs[i] or xs[i] + rs[i] > unit or ys[i] + rs[i] > unit:
            return False
    for i in range(n):
        xi, yi, ri = xs[i], ys[i], rs[i]
        for j in range(i + 1, n):
            dx, dy, reach = xi - xs[j], yi - ys[j], ri + rs[j]
            if dx * dx + dy * dy < reach * reach:
                return False
    return True


def separate(centers: np.ndarray) -> np.ndarray:
    """Distinct, interior centres; centres that already are come back unchanged."""
    c = np.array(centers, dtype=float).reshape(-1, 2)
    c[~np.isfinite(c)] = 0.5
    c = np.clip(c, MIN_GAP, 1.0 - MIN_GAP)
    for i in range(1, len(c)):
        x0 = float(c[i, 0])
        step = MIN_GAP if x0 < 0.5 else -MIN_GAP
        k = 0
        while any(abs(c[i, 0] - c[j, 0]) < 0.5 * MIN_GAP and abs(c[i, 1] - c[j, 1]) < 0.5 * MIN_GAP
                  for j in range(i)):
            k += 1
            c[i, 0] = x0 + k * step
    return c


def fit_pairwise(centers: np.ndarray, start: np.ndarray) -> np.ndarray:
    """Cap each radius at the distance to the nearest side, then scale overlapping pairs down in proportion."""
    n = centers.shape[0]
    radii = np.array(start, dtype=float)
    for i in range(n):
        x, y = centers[i]
        radii[i] = min(radii[i], x, y, 1 - x, 1 - y)
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.sqrt(np.sum((centers[i] - centers[j]) ** 2))
            if radii[i] + radii[j] > dist:
                scale = dist / (radii[i] + radii[j])
                radii[i] *= scale
                radii[j] *= scale
    return radii


def shrink_to_exact(centers: np.ndarray, radii: np.ndarray) -> np.ndarray | None:
    """The smallest uniform shrink 1 - 2^(k-53), k = 0..43, that passes the exact test; None if 0.1% is not enough."""
    if not np.all(np.isfinite(radii)) or not np.all(radii > 0):
        return None
    for k in range(44):
        candidate = radii if k == 0 else radii * (1.0 - 2.0 ** (k - 53))
        if exactly_feasible(centers, candidate):
            return candidate
    return None


def repair(packing) -> list[list[float]] | None:
    """A strictly feasible packing made from `packing` ([[x, y, r], ...]) by shrinking only, or None."""
    try:
        array = np.array(packing, dtype=float).reshape(-1, 3)
    except (TypeError, ValueError):
        return None
    if len(array) == 0 or not np.all(np.isfinite(array[:, 2])):
        return None
    centers = separate(array[:, :2])
    start = np.where(array[:, 2] > 0, array[:, 2], 0.5 * MIN_GAP)
    candidates = [shrink_to_exact(centers, start), shrink_to_exact(centers, fit_pairwise(centers, start))]
    candidates = [c for c in candidates if c is not None]
    if not candidates:
        return None
    radii = max(candidates, key=lambda r: math.fsum(r))
    return [[float(x), float(y), float(r)] for (x, y), r in zip(centers, radii)]
