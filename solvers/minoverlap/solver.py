#!/usr/bin/env python3
"""Mendel seed solver for the Erdos minimum overlap problem (minimise max_s correlate(h, 1 - h)_s * 2 / n).

A solution is a list of n heights h in [0, 1] with sum n / 2 (the arena rescales to that sum; we keep it
exactly, so the rescaling is a no-op up to rounding). The score is

    C(h) = (2 / n) max_s c_s,   c_s = sum_m h_(m+s) (1 - h_m)        (s = -(n-1) .. n-1, zero padding)

Pipeline
    start      h = 1/2 + noise, projected onto the feasible set F = {0 <= h <= 1, sum h = n / 2}   (seeded)
               (idea `coarse_to_fine`: the first part of the budget runs on n / coarse_factor steps,
               then every height is repeated, which leaves the score unchanged)
    descend    projected gradient on the log-sum-exp surrogate of the max, gradients by FFT, with an
               adaptive step; the sharpness beta grows every `stage_iters` evaluations
               (idea `symmetric`: h is kept symmetric, h_i = h_(n-1-i), which makes c symmetric too)
    polish     (idea `lp_polish`) sequential linear programming on the near-maximal shifts in a trust box

Budget
    One iteration is one evaluation of the surrogate and its gradient; one linear program of the polish
    counts as LP_ITERS of them. --iters N stops after N iterations and never reads the clock, so it is
    deterministic. --time T is CPU seconds of this process (time.process_time, imports included).

Rules for adding an idea
    * Register it in genes.json and read it from `cfg`. With the gene at its default the solver must do
      exactly what it did before: no extra draws from `rng`, no change in the order of floating-point work.
    * Randomness comes from `rng` or from `idea_rng(seed, name)`, a private stream for one idea.
    * Every candidate goes through `Best.offer`; `valid_output` makes the written solution valid.
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
              "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")  # one core: --time is CPU seconds, and machines are shared

import argparse
import json
import math
import sys
import time
import zlib
from pathlib import Path

import numpy as np
from scipy import fft as sfft

HERE = Path(__file__).resolve().parent
BETA_MAX = 1.0e7        # beyond this the surrogate is the max itself to float64 precision
LP_ITERS = 200          # one linear program of the polish counts as this many iterations
TRACE_STEP = 1e-5       # an improvement enters stats.trace when it is at least this large (relative)


class Stop(Exception):
    """The budget is spent."""


def load_config(path: str | None) -> dict:
    cfg: dict = {}
    try:
        cfg.update({g["name"]: g["default"] for g in json.loads((HERE / "genes.json").read_text())["genes"]})
    except (OSError, ValueError, KeyError):
        pass
    if path:
        cfg.update(json.loads(Path(path).read_text()))
    return cfg


class Budget:
    def __init__(self, time_s: float | None, iters: int | None):
        self.time_s, self.iters, self.done = time_s, iters, 0
        self.limit = max(0.0, time_s - min(1.0, 0.05 * time_s)) if time_s is not None else None

    def tick(self, cost: int = 1) -> None:
        if self.iters is not None:
            if self.done >= self.iters:
                raise Stop
        elif time.process_time() >= self.limit:
            raise Stop
        self.done += cost

    def fraction(self) -> float:
        if self.iters is not None:
            return self.done / max(1, self.iters)
        return time.process_time() / max(1e-9, self.limit)

    def seconds_left(self) -> float | None:
        return None if self.iters is not None else max(0.05, self.limit - time.process_time())


def idea_rng(seed: int, name: str) -> np.random.Generator:
    return np.random.default_rng([int(seed), zlib.crc32(name.encode())])


def arena_score(h: np.ndarray) -> float:
    """The arena's rule, reimplemented: rescale to sum n/2, check [0, 1], max correlation * 2 / n."""
    n = len(h)
    if not np.all(np.isfinite(h)) or h.min() < 0 or h.max() > 1:
        return math.inf
    s = float(np.sum(h))
    if s == 0.0:
        return math.inf
    if s != n / 2.0:
        h = h * ((n / 2.0) / s)
        if h.min() < 0 or h.max() > 1:
            return math.inf
    return float(np.max(np.correlate(h, 1 - h, mode="full"))) * 2.0 / n


def valid_output(h: np.ndarray) -> np.ndarray:
    """h itself if the arena accepts it; otherwise the nearest thing it accepts (flat 1/2 at worst)."""
    x = np.clip(np.nan_to_num(np.asarray(h, dtype=float), nan=0.5), 0.0, 1.0)
    for _ in range(4):
        if math.isfinite(arena_score(x)):
            return x
        s = float(x.sum())
        x = np.clip(x * ((len(x) / 2.0) / s), 0.0, 1.0) if s > 0 else x
        x = np.minimum(x, np.nextafter(1.0, 0.0))
    return np.full(len(h), 0.5)


class Best:
    def __init__(self) -> None:
        self.score = math.inf
        self.x: np.ndarray | None = None
        self.trace: list[list[float]] = []
        self._traced = math.inf

    def offer(self, x: np.ndarray, score: float) -> bool:
        if not (score < self.score) or not math.isfinite(score):
            return False
        self.score, self.x = float(score), np.array(x, dtype=float)
        if score < self._traced * (1.0 - TRACE_STEP):
            self._traced = float(score)
            self.trace.append([round(time.process_time(), 3), float(score)])
        return True


# --------------------------------------------------------------------------------------------
# Geometry: the feasible set and resampling
# --------------------------------------------------------------------------------------------

def project(y: np.ndarray) -> np.ndarray:
    """Euclidean projection onto {0 <= h <= 1, sum h = n/2}: h = clip(y - tau, 0, 1) for the right tau."""
    target = len(y) / 2.0
    lo, hi = float(y.min()) - 1.0, float(y.max())
    for _ in range(64):
        mid = 0.5 * (lo + hi)
        if np.clip(y - mid, 0.0, 1.0).sum() > target:
            lo = mid
        else:
            hi = mid
    return np.clip(y - 0.5 * (lo + hi), 0.0, 1.0)


def resample(x: np.ndarray, n: int) -> np.ndarray:
    """The same step function on n steps: exact repetition when n is a multiple of len(x), otherwise the
    averages of the old function over the new steps (then projected, to restore the sum exactly)."""
    old = len(x)
    if n == old:
        return x.copy()
    if n % old == 0:
        return np.repeat(x, n // old)
    cum = np.concatenate([[0.0], np.cumsum(x)]) / old
    knots = np.interp(np.linspace(0.0, 1.0, n + 1), np.linspace(0.0, 1.0, old + 1), cum)
    return project(np.diff(knots) * n)


# --------------------------------------------------------------------------------------------
# The objective on one grid
# --------------------------------------------------------------------------------------------

class Grid:
    def __init__(self, n: int):
        self.n = n
        self.m = 2 * n - 1
        self.L = sfft.next_fast_len(3 * n - 2, real=True)

    def corr(self, h: np.ndarray) -> np.ndarray:
        """c_s for s = -(n-1) .. n-1, i.e. numpy.correlate(h, 1 - h, 'full'), by FFT."""
        return sfft.irfft(sfft.rfft(h, self.L) * sfft.rfft((1.0 - h)[::-1], self.L), self.L)[:self.m]

    def score(self, h: np.ndarray) -> float:
        return float(self.corr(h).max()) * 2.0 / self.n

    def surrogate(self, h: np.ndarray, beta: float) -> tuple[float, float, np.ndarray]:
        """(true score, log-sum-exp_beta of the scores of all shifts, its gradient in h)."""
        n, L, m = self.n, self.L, self.m
        g = 1.0 - h
        Hf = sfft.rfft(h, L)
        c = sfft.irfft(Hf * sfft.rfft(g[::-1], L), L)[:m] * (2.0 / n)
        top = float(c.max())
        e = np.exp(beta * (c - top))
        z = float(e.sum())
        w = e / z
        # d c_s / d h_j = g_(j-s) - h_(j+s); summed with weights w over s, both terms are convolutions
        a = sfft.irfft(sfft.rfft(w, L) * sfft.rfft(g, L), L)[n - 1:2 * n - 1]
        b = sfft.irfft(sfft.rfft(w[::-1], L) * Hf, L)[n - 1:2 * n - 1]
        return top, top + math.log(z) / beta, (2.0 / n) * (a - b)


# --------------------------------------------------------------------------------------------
# Start and descent
# --------------------------------------------------------------------------------------------

def start(n: int, cfg: dict, rng: np.random.Generator) -> np.ndarray:
    return project(0.5 + float(cfg["init_noise"]) * rng.standard_normal(n))


def symmetrise(v: np.ndarray) -> np.ndarray:
    return 0.5 * (v + v[::-1])


def descend(h: np.ndarray, grid: Grid, beta: float, until: float, cfg: dict, budget: Budget,
            best: Best) -> tuple[np.ndarray, float]:
    """Projected gradient on the surrogate with an adaptive step, until `until` of the budget is used.
    The step is in units of h (the gradient is scaled to max-norm 1); it grows by 1.2 after an accepted
    move and halves after a rejected one. Beta grows every `stage_iters` evaluations, and the descent
    then restarts from the best point of this grid. `best` holds solutions with grid.n steps."""
    sym = bool(cfg.get("symmetric"))
    stage = int(cfg["stage_iters"])
    growth = float(cfg["beta_growth"])
    step = float(cfg["step0"])
    if sym:
        h = project(symmetrise(h))
    budget.tick()
    top, val, grad = grid.surrogate(h, beta)
    best.offer(h, top)
    count = 0
    while budget.fraction() < until:
        if sym:
            grad = symmetrise(grad)
        norm = float(np.abs(grad).max())
        if not math.isfinite(norm) or norm == 0.0:
            break
        trial = project(h - (step / norm) * grad)
        budget.tick()
        t_top, t_val, t_grad = grid.surrogate(trial, beta)
        count += 1
        best.offer(trial, t_top)
        if t_val < val:
            h, top, val, grad = trial, t_top, t_val, t_grad
            step = min(step * 1.2, 0.5)
        else:
            step = max(step * 0.5, 1e-12)
        if count % stage == 0:
            beta = min(beta * growth, BETA_MAX)
            # re-centre on the best point of this grid, re-evaluated at the new sharpness
            h = best.x.copy()
            budget.tick()
            top, val, grad = grid.surrogate(h, beta)
            step = max(step, 1e-4)
    return h, beta


# --------------------------------------------------------------------------------------------
# Idea: sequential linear programming on the near-maximal shifts
# --------------------------------------------------------------------------------------------

def polish(h: np.ndarray, grid: Grid, cfg: dict, budget: Budget, best: Best) -> np.ndarray:
    """Minimise the linearised maximum over the shifts within `polish_window` of the top, in a box of
    half-width `radius`, keeping sum h fixed and 0 <= h <= 1. The radius doubles after a step that
    delivers at least half of its predicted gain and shrinks after a step that does not help.

        c_s(h + d) = c_s(h) + sum_j (g_(j-s) - h_(j+s)) d_j - sum_m d_(m+s) d_m
    """
    from scipy.optimize import linprog

    n = grid.n
    sym = bool(cfg.get("symmetric"))
    radius = float(cfg["polish_radius"])
    window = float(cfg["polish_window"])
    j = np.arange(n)[None, :]
    c = grid.corr(h)
    top = float(c.max())
    while radius > 1e-9:
        budget.tick(LP_ITERS)
        idx = np.flatnonzero(c >= top - window * abs(top))
        s = (idx - (n - 1))[:, None]
        g = 1.0 - h
        jm, jp = j - s, j + s
        jac = (np.where((jm >= 0) & (jm < n), g[np.clip(jm, 0, n - 1)], 0.0)
               - np.where((jp >= 0) & (jp < n), h[np.clip(jp, 0, n - 1)], 0.0))
        lower, upper = np.maximum(-h, -radius), np.minimum(1.0 - h, radius)
        a_eq = [np.append(np.ones(n), 0.0)]
        b_eq = [0.0]
        if sym:  # d_i = d_(n-1-i): keeps the polished function symmetric
            half = n // 2
            rows = np.zeros((half, n + 1))
            rows[np.arange(half), np.arange(half)] = 1.0
            rows[np.arange(half), n - 1 - np.arange(half)] = -1.0
            a_eq = np.vstack([a_eq, rows])
            b_eq = b_eq + [0.0] * half
        options = {"presolve": True}
        left = budget.seconds_left()
        if left is not None:
            options["time_limit"] = left
        res = linprog(np.append(np.zeros(n), 1.0), A_ub=np.hstack([jac, -np.ones((len(idx), 1))]),
                      b_ub=top - c[idx], A_eq=np.asarray(a_eq), b_eq=b_eq,
                      bounds=list(zip(lower, upper)) + [(None, None)], method="highs", options=options)
        if res.status != 0 or res.x is None:
            radius *= 0.5
            continue
        trial = project(np.clip(h + res.x[:n], 0.0, 1.0))
        t_c = grid.corr(trial)
        t_top = float(t_c.max())
        if t_top < top:
            predicted = -float(res.x[-1])
            gain = top - t_top
            h, c, top = trial, t_c, t_top
            best.offer(h, top * 2.0 / n)
            if gain > 0.5 * predicted:
                radius = min(2.0 * radius, 0.5)
        else:
            radius *= 0.3
    return h


# --------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------

def solve(n: int, cfg: dict, rng: np.random.Generator, budget: Budget, best: Best) -> None:
    beta = float(cfg["beta0"])
    polish_on = bool(cfg.get("lp_polish"))
    descend_end = 1.0 - float(cfg["polish_fraction"]) if polish_on else 1.0
    if cfg.get("coarse_to_fine"):
        m = max(8, n // int(cfg["coarse_factor"]))
        coarse = Grid(m)
        local = Best()
        try:
            descend(start(m, cfg, rng), coarse, beta, float(cfg["coarse_fraction"]) * descend_end,
                    cfg, budget, local)
        finally:  # even if the budget ran out on the coarse grid, its best point is the answer
            if local.x is not None:
                h = resample(local.x, n)
                best.offer(h, Grid(n).score(h))
        beta = float(cfg["beta0"])
    else:
        h = start(n, cfg, rng)
    grid = Grid(n)
    best.offer(h, grid.score(h))
    h, beta = descend(h, grid, beta, descend_end, cfg, budget, best)
    if polish_on:
        polish(best.x.copy(), grid, cfg, budget, best)
    while True:  # budget left over (the polish converged): keep descending from the best point
        h, beta = descend(best.x.copy(), grid, beta, 2.0, cfg, budget, best)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--seed", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--time", type=float, help="budget in CPU seconds")
    group.add_argument("--iters", type=int, help="budget in surrogate evaluations (deterministic)")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    n = int(json.loads(Path(args.instance).read_text())["n"])
    rng = np.random.default_rng(args.seed)
    budget = Budget(args.time, args.iters)
    best = Best()
    best.offer(np.full(n, 0.5), 0.5)  # flat 1/2: always valid, score exactly 1/2

    try:
        solve(n, cfg, rng, budget, best)
    except Stop:
        pass
    except Exception as exc:  # noqa: BLE001 - a broken idea must still leave a valid solution behind
        print(f"solver error, keeping the best solution so far: {exc!r}", file=sys.stderr)

    x = valid_output(best.x)
    score = arena_score(x)
    if not (score <= 0.5):
        x, score = np.full(n, 0.5), 0.5
    if not best.trace or best.trace[-1][1] != score:
        best.trace.append([round(time.process_time(), 3), score])
    out = {"solution": [float(v) for v in x], "stats": {"iters": budget.done, "trace": best.trace, "score": score}}
    tmp = Path(args.out + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
