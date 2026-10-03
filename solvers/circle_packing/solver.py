#!/usr/bin/env python3
"""Mendel seed solver for circle packing in the unit square (maximise the sum of radii).

The seed is a port of OpenEvolve's starting point for the same benchmark,

    https://github.com/algorithmicsuperintelligence/openevolve
    examples/circle_packing/initial_program.py            (Apache-2.0)

generalised from n = 26 to any n and wrapped in the Mendel solver contract (PROTOCOL.md).
It is weak on purpose: a fixed ring pattern and a greedy radius rule, nothing else. Every later
improvement is meant to arrive as a named gene, so that its worth can be measured by a knockout.

Pipeline
    construct   where the circles go                      (the OpenEvolve constructor)
    improve     search over the centres                   (no ideas in the seed: returns at once)
    finalise    radii for the centres, made exactly feasible

Rules for adding an idea
    * Register it in genes.json and read it from `cfg` (the one config dict, read once in main).
    * Guard every new line with the gene. With the gene at its default the solver must produce
      the same output as before, so an idea that is off must not draw from `rng` or reorder floats.
    * Randomness comes from `rng` (numpy.random.default_rng(seed)) or from `idea_rng(seed, name)`,
      a private stream for one idea that leaves every other idea's random numbers untouched.
    * Every packing goes through `finalise`, which is what guarantees a valid output.
    * Import scipy inside the function that needs it; the seed does not pay for that import.

Feasibility guarantee
    The evaluator checks the packing in exact rational arithmetic with no tolerance. `finalise`
    runs the same test itself, in integer arithmetic (`exactly_feasible`), and shrinks all radii
    by 1 - 2^(k-53), k = 1, 2, ... (one unit in the last place, then two, four, ...) until the
    test passes. Only packings that passed are ever recorded or written. See `finalise`.
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
              "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")  # one core: --time is CPU seconds, and the machine is shared

import argparse
import json
import math
import sys
import time
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
MIN_GAP = 1e-6  # centres closer than this to each other or to a side are moved apart in `separate`
MAX_TRACE = 2000  # improvements kept in stats.trace; beyond this, every other one is dropped


# --------------------------------------------------------------------------------------------
# Config, budget, random numbers
# --------------------------------------------------------------------------------------------

def load_config(path: str | None) -> dict:
    """The one config dict: defaults from genes.json, overridden by the harness's CFG.json."""
    cfg: dict = {}
    try:
        cfg.update({g["name"]: g["default"] for g in json.loads((HERE / "genes.json").read_text())["genes"]})
    except (OSError, ValueError, KeyError):
        pass  # CFG.json lists every gene anyway
    if path:
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


class Budget:
    """`--time` is CPU seconds of this process (time.process_time, so start-up and imports count);
    `--iters` is a number of improve-loop iterations and never looks at the clock."""

    def __init__(self, time_s: float | None, iters: int | None):
        self.time_s, self.iters, self.done = time_s, iters, 0

    def tick(self) -> bool:
        """True if one more iteration may run. Call it exactly once per iteration."""
        if self.iters is not None:
            if self.done >= self.iters:
                return False
        elif time.process_time() >= self.time_s:
            return False
        self.done += 1
        return True


def idea_rng(seed: int, name: str) -> np.random.Generator:
    """A private, reproducible random stream for one idea, derived from the run seed and the gene name."""
    return np.random.default_rng([int(seed), zlib.crc32(name.encode())])


class Best:
    """The best exactly-feasible packing seen so far, and the trace of its improvements."""

    def __init__(self) -> None:
        self.score = -math.inf
        self.centers: np.ndarray | None = None
        self.radii: np.ndarray | None = None
        self.trace: list[list[float]] = []

    def offer(self, centers: np.ndarray, radii: np.ndarray) -> bool:
        """Record a packing returned by `finalise` if it beats the best so far."""
        score = math.fsum(float(r) for r in radii)
        if score <= self.score:
            return False
        self.score, self.centers, self.radii = score, np.array(centers), np.array(radii)
        self.trace.append([round(time.process_time(), 4), score])
        if len(self.trace) > MAX_TRACE:  # keep the first and the latest point, thin the ones between
            self.trace = self.trace[:1] + self.trace[1:-1][1::2] + self.trace[-1:]
        return True


# --------------------------------------------------------------------------------------------
# Stage 1: construct (OpenEvolve's initial program, with its constants as alleles)
# --------------------------------------------------------------------------------------------

def construct(n: int, cfg: dict, rng: np.random.Generator) -> np.ndarray:
    """One circle in the middle, a ring of `inner_count` around it, a ring of `outer_count` outside.

    With the default alleles and n = 26 this is OpenEvolve's `construct_packing` to the last bit:
    1 + 8 + 16 = 25 circles are placed and the 26th is left at the origin, as it is there. For other
    n the same slots are filled in the same order; circles beyond the last slot stay at the origin.
    Everything is then clipped into [clip_margin, 1 - clip_margin]. The outer ring (radius 0.7) pokes
    out of the square, so the clip flattens it onto the sides.
    """
    inner_count, outer_count = int(cfg["inner_count"]), int(cfg["outer_count"])
    inner_radius, outer_radius = float(cfg["inner_radius"]), float(cfg["outer_radius"])
    margin = float(cfg["clip_margin"])

    centers = np.zeros((n, 2))
    centers[0] = [0.5, 0.5]
    k = 1
    for count, ring_radius in ((inner_count, inner_radius), (outer_count, outer_radius)):
        for i in range(count):
            if k >= n:
                break
            angle = 2 * np.pi * i / count
            centers[k] = [0.5 + ring_radius * np.cos(angle), 0.5 + ring_radius * np.sin(angle)]
            k += 1
    return np.clip(centers, margin, 1 - margin)


def compute_max_radii(centers: np.ndarray, start: np.ndarray | None = None) -> np.ndarray:
    """OpenEvolve's radius rule: start from the distance to the nearest side, then walk over the
    pairs in index order and scale both radii of an overlapping pair down in proportion.

    `start` (not used by the seed) caps the starting radii, so that radii proposed by an idea can
    be fitted with the same rule.
    """
    n = centers.shape[0]
    radii = np.ones(n)
    for i in range(n):
        x, y = centers[i]
        radii[i] = min(x, y, 1 - x, 1 - y)
    if start is not None:
        radii = np.minimum(radii, start)
    for i in range(n):
        for j in range(i + 1, n):
            dist = np.sqrt(np.sum((centers[i] - centers[j]) ** 2))
            if radii[i] + radii[j] > dist:
                scale = dist / (radii[i] + radii[j])
                radii[i] *= scale
                radii[j] *= scale
    return radii


# --------------------------------------------------------------------------------------------
# Stage 2: improve (the seed has no improvement ideas)
# --------------------------------------------------------------------------------------------

def improve(cfg: dict, rng: np.random.Generator, budget: Budget, best: Best, seed: int) -> None:
    """Search over the centres within the budget: steps propose, the best packing is kept.

    An idea adds a step here: a function `step(centers, cfg, rng) -> new centres` (it must not
    modify its argument), appended to `steps` only when its gene is on. Each iteration every step
    proposes from the centres of the best packing so far; a proposal that scores strictly higher
    after `finalise` becomes the new best. An idea that needs something else (its own acceptance
    rule, a population, an inner optimiser) keeps that state inside its step.

    With no steps the stage returns at once and uses no iterations, so the seed is a pure
    constructor, exactly like the program it was ported from. `seed` is here for `idea_rng`.
    """
    steps: list = []
    if not steps:
        return
    while budget.tick():
        for step in steps:
            best.offer(*finalise(step(best.centers, cfg, rng), cfg))


# --------------------------------------------------------------------------------------------
# Stage 3: finalise (radii, and the exact-feasibility guarantee)
# --------------------------------------------------------------------------------------------

def exactly_feasible(centers: np.ndarray, radii: np.ndarray) -> bool:
    """The evaluator's test, re-implemented in integer arithmetic.

    A double is an integer divided by a power of two, so after multiplying everything by the
    largest denominator the constraints are comparisons between Python integers: no rounding.
    """
    n = len(radii)
    values = [float(v) for v in centers[:, 0]] + [float(v) for v in centers[:, 1]] + [float(v) for v in radii]
    if not all(math.isfinite(v) for v in values):
        return False
    ratios = [v.as_integer_ratio() for v in values]
    unit = max(den for _, den in ratios)  # all denominators are powers of two
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
    """Make the centres distinct and interior; centres that already are come back unchanged.

    Two circles with the same centre can only have radius zero, which the evaluator rejects
    (radii must be positive). The ported constructor does produce such circles: for n = 26 the
    unplaced 26th circle and one circle of the outer ring are both clipped into the same corner.
    A centre within MIN_GAP / 2 of an earlier one (in both coordinates) is walked along x, towards
    the middle of the square, in steps of MIN_GAP until it is clear.
    """
    c = np.array(centers, dtype=float).reshape(-1, 2)
    c[~np.isfinite(c)] = 0.5
    c = np.clip(c, MIN_GAP, 1.0 - MIN_GAP)
    for i in range(1, len(c)):
        x0 = float(c[i, 0])
        step = MIN_GAP if x0 < 0.5 else -MIN_GAP
        k = 0
        while any(abs(c[i, 0] - c[j, 0]) < 0.5 * MIN_GAP and abs(c[i, 1] - c[j, 1]) < 0.5 * MIN_GAP
                  for j in range(i)):
            k += 1  # each earlier centre can block at most one position, so k never exceeds i
            c[i, 0] = x0 + k * step
    return c


def shrink_to_exact(centers: np.ndarray, radii: np.ndarray) -> np.ndarray | None:
    """The smallest uniform shrink 1 - 2^(k-53) that makes the packing exactly feasible, or None
    if a shrink of 0.1% is not enough (the radii were wrong, not merely rounded)."""
    radii = np.asarray(radii, dtype=float)
    if radii.shape != (len(centers),) or not np.all(np.isfinite(radii)) or not np.all(radii > 0):
        return None
    for k in range(44):
        candidate = radii if k == 0 else radii * (1.0 - 2.0 ** (k - 53))
        if exactly_feasible(centers, candidate):
            return candidate
    return None


def safe_radii(centers: np.ndarray) -> np.ndarray:
    """Radii that cannot fail: 0.49 of the distance to the nearest side or nearest other centre."""
    n = len(centers)
    radii = np.empty(n)
    for i in range(n):
        x, y = centers[i]
        reach = min(x, y, 1 - x, 1 - y)
        for j in range(n):
            if j != i:
                reach = min(reach, math.hypot(x - centers[j, 0], y - centers[j, 1]))
        radii[i] = 0.49 * reach
    return radii


def finalise(centers: np.ndarray, cfg: dict, radii: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Turn centres (and, optionally, radii proposed by an idea) into an exactly feasible packing.

    Radii are tried in this order, each followed by the exact test and the minimal shrink:
      1. proposed radii, repaired two ways with the better result kept: as they are (all shrunk
         together), and fitted with the seed's pairwise rule (only overlapping pairs shrunk);
      2. the seed's rule from scratch (`compute_max_radii`, the OpenEvolve port);
      3. `safe_radii`, which has a 2% margin and therefore always passes once `separate` has made
         the centres distinct and interior.
    The seed takes route 2. Floating-point rounding leaves touching pairs overlapping by about
    1e-16, so the shrink is normally a few units in the last place (a loss of about 1e-15 in score).
    A proposal is never enlarged, and one that is already exactly feasible comes back unchanged.
    """
    centers = separate(centers)

    def attempt(route) -> np.ndarray | None:
        try:
            return shrink_to_exact(centers, route())
        except (ArithmeticError, ValueError):  # a route that breaks is skipped, like one that does not fit
            return None

    if radii is not None:
        proposed = np.array(radii, dtype=float).reshape(-1)
        if proposed.shape == (len(centers),) and np.all(np.isfinite(proposed)):  # otherwise ignore the proposal
            repaired = [r for r in (attempt(lambda: proposed),
                                    attempt(lambda: compute_max_radii(centers, start=np.clip(proposed, 0.0, 1.0))))
                        if r is not None]
            if repaired:
                return centers, max(repaired, key=lambda r: math.fsum(r))  # a tie keeps the proposal as it is
    for route in (lambda: compute_max_radii(centers), lambda: safe_radii(centers)):
        exact = attempt(route)
        if exact is not None:
            return centers, exact
    raise RuntimeError("no exactly feasible radii found")  # not reachable: route 3 cannot fail


def grid_packing(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Last resort if anything above raises: n equal circles on a square grid, with a wide margin."""
    m = max(1, math.ceil(math.sqrt(n)))
    centers = np.array([[(2 * (i % m) + 1) / (2 * m), (2 * (i // m) + 1) / (2 * m)] for i in range(n)])
    return centers, np.full(n, 0.49 / m)


# --------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------

def solve(n: int, cfg: dict, rng: np.random.Generator, budget: Budget, seed: int) -> Best:
    best = Best()
    centers = construct(n, cfg, rng)
    best.offer(*finalise(centers, cfg))
    improve(cfg, rng, budget, best, seed)
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--seed", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--time", type=float, help="budget in CPU seconds")
    group.add_argument("--iters", type=int, help="budget in improve-loop iterations (deterministic)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    n = int(json.loads(Path(args.instance).read_text())["n"])
    rng = np.random.default_rng(args.seed)
    budget = Budget(args.time, args.iters)

    try:
        best = solve(n, cfg, rng, budget, args.seed)
    except Exception as exc:  # noqa: BLE001 - a broken idea must still leave a valid packing behind
        print(f"solver error, falling back to a grid packing: {exc!r}", file=sys.stderr)
        best = Best()
    if best.centers is None:
        best.offer(*grid_packing(n))
    if not exactly_feasible(best.centers, best.radii):  # every recorded packing has passed already
        print("refusing to write a packing that fails the exact test", file=sys.stderr)
        return 1

    out = {
        "solution": [[float(x), float(y), float(r)] for (x, y), r in zip(best.centers, best.radii)],
        "stats": {"iters": budget.done, "trace": best.trace},
    }
    tmp = Path(args.out + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
