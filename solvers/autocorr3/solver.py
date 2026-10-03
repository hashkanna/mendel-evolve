#!/usr/bin/env python3
"""Mendel seed solver for the third autocorrelation inequality (minimise max f*f / (sum f)^2).

Written from scratch for this repository. A solution is a list of n step heights x; the score is

    C(x) = 2 n max_k (x*x)_k / (sum x)^2            (x*x: discrete autoconvolution, 2n - 1 shifts)

which is a maximum of 2n - 1 indefinite quadratic forms, invariant under scaling of x.

Pipeline
    start       heights 1 + noise on the coarsest grid                        (seeded)
                (idea `multistart_coarse`: many such starts, the best one continues)
    descend     L-BFGS on the log-sum-exp surrogate of the max, with the gradient from FFTs
                (three transforms per evaluation), the sharpness beta raised stage by stage
    refine      repeat every height twice (the score is unchanged, exactly) and descend again,
                until the grid has the n steps of the instance

The grids are n / 2^j for as long as that is an integer and not below `coarse_n`. The budget is
shared between the grids by fraction, so the same plan runs under --time and under --iters.

Budget
    One iteration is one evaluation of the surrogate; one linear program of the polish idea
    counts as 2000 of them.
    --iters N stops after exactly N iterations and never looks at the clock, so it is deterministic.
    --time T is CPU seconds of this process (time.process_time: imports count).

Rules for adding an idea
    * Register it in genes.json and read it from `cfg`. Guard every new line with the gene: with
      the gene at its default the solver must do exactly what it did before, so an idea that is
      off must not draw from `rng` or change the order of floating-point operations.
    * Randomness comes from `rng` or from `idea_rng(seed, name)`, a private stream for one idea.
    * Every candidate goes through `Best.offer`; the best one is what gets written.
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
from scipy import fft as sfft
from scipy.optimize import minimize

HERE = Path(__file__).resolve().parent
BETA_MAX = 3.0e6        # sharper than this and L-BFGS no longer moves in float64
POLISH_MAX_N = 2048     # the polish builds a dense (active shifts) x n matrix
LP_ITERS = 2000         # one linear program of the polish counts as this many iterations
TRACE_STEP = 1e-4       # an improvement enters stats.trace when it is at least this large (relative)


class Stop(Exception):
    """The budget is spent."""


# --------------------------------------------------------------------------------------------
# Config, budget, random numbers, the best solution so far
# --------------------------------------------------------------------------------------------

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
        if time_s is not None:  # keep a little back for writing the output
            self.limit = max(0.0, time_s - min(1.0, 0.03 * time_s))

    def tick(self, cost: int = 1) -> None:
        """Call once per iteration; raises Stop when the budget is spent. `cost` is the number of
        iterations the step is worth (a linear program is far dearer than a surrogate evaluation)."""
        if self.iters is not None:
            if self.done >= self.iters:
                raise Stop
        elif time.process_time() >= self.limit:
            raise Stop
        self.done += cost

    def fraction(self) -> float:
        """Share of the budget used so far, in [0, 1]."""
        if self.iters is not None:
            return self.done / max(1, self.iters)
        return time.process_time() / max(1e-9, self.limit)

    def seconds_left(self) -> float | None:
        return None if self.iters is not None else max(0.05, self.limit - time.process_time())


def idea_rng(seed: int, name: str) -> np.random.Generator:
    """A private, reproducible random stream for one idea."""
    return np.random.default_rng([int(seed), zlib.crc32(name.encode())])


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

    def close_trace(self) -> None:
        if self.x is not None and (not self.trace or self.trace[-1][1] != self.score):
            self.trace.append([round(time.process_time(), 3), self.score])


# --------------------------------------------------------------------------------------------
# The objective on one grid
# --------------------------------------------------------------------------------------------

class Grid:
    """Autoconvolution, score and surrogate gradient for step functions with n steps."""

    def __init__(self, n: int):
        self.n = n
        self.m = 2 * n - 1
        self.L = sfft.next_fast_len(self.m, real=True)

    def score(self, x: np.ndarray) -> float:
        s = float(x.sum())
        if s == 0.0 or not math.isfinite(s):
            return math.inf
        X = sfft.rfft(x, self.L)
        c = sfft.irfft(X * X, self.L)[:self.m]
        return 2.0 * self.n * float(c.max()) / (s * s)

    def surrogate(self, beta: float, budget: Budget, best: Best):
        """x -> (log-sum-exp_beta of the 2n-1 normalised convolution values, gradient)."""
        n, m, L = self.n, self.m, self.L

        def fun(x: np.ndarray):
            budget.tick()
            s = float(x.sum())
            if not math.isfinite(s) or s <= 1e-9 * n:
                return 1e30, np.zeros_like(x)
            X = sfft.rfft(x, L)
            scale = 2.0 * n / (s * s)
            g = scale * sfft.irfft(X * X, L)[:m]
            top = float(g.max())
            best.offer(x, top)
            e = np.exp(beta * (g - top))
            z = float(e.sum())
            w = e / z
            corr = sfft.irfft(sfft.rfft(w, L) * np.conj(X), L)[:n]  # corr_i = sum_k w_k x_(k-i)
            grad = (2.0 * scale) * corr - (2.0 * float(w @ g) / s)
            return top + math.log(z) / beta, grad

        return fun


def resample(x: np.ndarray, n: int) -> np.ndarray:
    """The same step function on n steps: exact repetition when n is a multiple of len(x),
    otherwise the averages of the old function over the new steps."""
    old = len(x)
    if n == old:
        return x.copy()
    if n % old == 0:
        return np.repeat(x, n // old)
    cum = np.concatenate([[0.0], np.cumsum(x)]) / old
    knots = np.interp(np.linspace(0.0, 1.0, n + 1), np.linspace(0.0, 1.0, old + 1), cum)
    return np.diff(knots) * n


def grid_sizes(n: int, coarse_n: int) -> list[int]:
    sizes = [n]
    while sizes[0] % 2 == 0 and sizes[0] // 2 >= max(2, coarse_n):
        sizes.insert(0, sizes[0] // 2)
    return sizes


# --------------------------------------------------------------------------------------------
# Stage 1: start
# --------------------------------------------------------------------------------------------

def start(n: int, cfg: dict, rng: np.random.Generator) -> np.ndarray:
    noise = float(cfg["init_noise"]) * rng.standard_normal(n)
    x = 1.0 + noise
    if cfg.get("edge_spike_init"):
        # idea: inverse-square-root singularities at both ends of the support
        u = (np.arange(n) + 0.5) / n
        x = (1.0 + noise) / np.sqrt(4.0 * u * (1.0 - u))
    if x.sum() <= 0.1 * n:  # the noise swamped the mean: fall back to its absolute value
        x = np.abs(x) + 0.1
    return x * (n / x.sum())


# --------------------------------------------------------------------------------------------
# Stage 2: descend on the smoothed maximum
# --------------------------------------------------------------------------------------------

def descend(x: np.ndarray, grid: Grid, beta: float, until: float, cfg: dict, budget: Budget,
            best: Best) -> tuple[np.ndarray, float]:
    """L-BFGS stages on the log-sum-exp surrogate, beta growing, until `until` of the budget is used."""
    growth = float(cfg["beta_growth"])
    evals = int(cfg["stage_evals"])
    first = True
    while first or budget.fraction() < until:
        first = False
        x = x * (grid.n / x.sum())
        res = minimize(grid.surrogate(beta, budget, best), x, jac=True, method="L-BFGS-B",
                       options={"maxfun": evals, "maxiter": evals, "maxcor": 16, "ftol": 1e-15, "gtol": 1e-11})
        x = np.asarray(res.x, dtype=float)
        if not np.all(np.isfinite(x)) or x.sum() <= 1e-9 * grid.n:
            x = resample(best.x, grid.n)
        beta = min(beta * growth, BETA_MAX)
    return x, beta


# --------------------------------------------------------------------------------------------
# Idea: many starts on the coarsest grid
# --------------------------------------------------------------------------------------------

def multistart(x0: np.ndarray, grid: Grid, until: float, cfg: dict, budget: Budget, best: Best,
               seed: int) -> tuple[np.ndarray, float]:
    """`multistart_count` descents from different noisy starts share the budget up to `until`
    equally; the one that ends lowest continues. The first start is the one the plain solver uses,
    the others come from a private random stream."""
    count = int(cfg["multistart_count"])
    private = idea_rng(seed, "multistart_coarse")
    begin = budget.fraction()
    winner: tuple[float, np.ndarray, float] | None = None
    for k in range(count):
        x = x0 if k == 0 else start(grid.n, cfg, private)
        local = Best()
        beta = float(cfg["beta0"])
        try:
            x, beta = descend(x, grid, beta, begin + (until - begin) * (k + 1) / count, cfg, budget, local)
        finally:
            if local.x is not None:
                best.offer(local.x, local.score)
        if winner is None or local.score < winner[0]:
            winner = (local.score, local.x, beta)
    return winner[1], winner[2]


# --------------------------------------------------------------------------------------------
# Idea: active-set polish (sequential linear programming on the near-maximal shifts)
# --------------------------------------------------------------------------------------------

def polish(x: np.ndarray, grid: Grid, until: float, cfg: dict, budget: Budget, best: Best) -> np.ndarray:
    """Minimise the linearised maximum over the shifts within `polish_window` of the top, inside a
    box of half-width `radius` that grows after a good step and shrinks after a bad one.

    With sum(d) = 0 the sum of x is unchanged, so the score moves with max(x*x) alone:
        (x + d)*(x + d)_k = (x*x)_k + 2 sum_i x_(k-i) d_i + (d*d)_k .
    """
    from scipy.optimize import linprog

    n = grid.n
    x = x * (n / x.sum())
    radius = float(cfg["polish_radius"])
    window = float(cfg["polish_window"])
    max_rows = max(8, min(2 * n - 1, 1536))
    cols = np.arange(n)[None, :]
    while budget.fraction() < until and radius > 1e-10:
        budget.tick(LP_ITERS)
        c = np.convolve(x, x)
        top = float(c.max())
        idx = np.flatnonzero(c >= top - window * abs(top))
        if len(idx) > max_rows:
            idx = np.sort(idx[np.argsort(c[idx], kind="stable")[-max_rows:]])
        k = idx[:, None] - cols
        jac = np.where((k >= 0) & (k < n), 2.0 * x[np.clip(k, 0, n - 1)], 0.0)
        a_ub = np.hstack([jac, -np.ones((len(idx), 1))])
        cost = np.zeros(n + 1)
        cost[-1] = 1.0
        options = {"presolve": True}
        left = budget.seconds_left()
        if left is not None:
            options["time_limit"] = left
        res = linprog(cost, A_ub=a_ub, b_ub=top - c[idx], A_eq=np.append(np.ones(n), 0.0)[None, :], b_eq=[0.0],
                      bounds=[(-radius, radius)] * n + [(None, None)], method="highs", options=options)
        if res.status != 0 or res.x is None:
            radius *= 0.5
            continue
        trial = x + res.x[:n]
        new_top = float(np.convolve(trial, trial).max())
        if new_top < top:
            predicted = -float(res.x[-1])
            x = trial
            best.offer(x, 2.0 * n * new_top / float(x.sum()) ** 2)
            if top - new_top > 0.5 * predicted:
                radius = min(2.0 * radius, 1.0)
        else:
            radius *= 0.4
    return x


# --------------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------------

def solve(n: int, cfg: dict, rng: np.random.Generator, budget: Budget, seed: int, best: Best) -> None:
    sizes = grid_sizes(n, int(cfg["coarse_n"]))
    # budget shares: the coarsest grid gets `coarse_fraction`, the finer ones share the rest
    # equally, except that the finest counts twice
    if len(sizes) == 1:
        ends = [1.0]
    else:
        coarse = float(cfg["coarse_fraction"])
        weights = [1.0] * (len(sizes) - 2) + [2.0]
        ends, used = [coarse], coarse
        for w in weights:
            used += (1.0 - coarse) * w / sum(weights)
            ends.append(used)
        ends[-1] = 1.0
    beta = float(cfg["beta0"])
    begin = 0.0
    x = start(sizes[0], cfg, rng)
    if cfg.get("multistart_coarse"):
        x, beta = multistart(x, Grid(sizes[0]), float(cfg["multistart_fraction"]) * ends[0], cfg, budget, best, seed)
    for level, size in enumerate(sizes):
        grid = Grid(size)
        if level > 0:
            x = resample(best.x, size)
        best.offer(x, grid.score(x))
        end = ends[level]
        polish_here = bool(cfg.get("active_set_polish")) and size <= POLISH_MAX_N
        descend_until = end - float(cfg["polish_fraction"]) * (end - begin) if polish_here else end
        x, beta = descend(x, grid, beta, descend_until, cfg, budget, best)
        if polish_here:
            polish(resample(best.x, size), grid, end, cfg, budget, best)
        beta = max(float(cfg["beta0"]), beta / float(cfg["beta_growth"]) ** 2)
        begin = end
    # budget left on the finest grid (the stages converged early): keep sharpening
    grid = Grid(n)
    while True:
        x, beta = descend(resample(best.x, n), grid, beta, 2.0, cfg, budget, best)


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
    best.offer(np.ones(n), 2.0 * n * n / float(n * n))  # the flat function, score 2: always valid

    try:
        solve(n, cfg, rng, budget, args.seed, best)
    except Stop:
        pass
    except Exception as exc:  # noqa: BLE001 - a broken idea must still leave a valid solution behind
        print(f"solver error, keeping the best solution so far: {exc!r}", file=sys.stderr)

    x = best.x if len(best.x) == n else resample(best.x, n)
    x = x * (n / x.sum())
    best.close_trace()
    out = {"solution": [float(v) for v in x], "stats": {"iters": budget.done, "trace": best.trace}}
    tmp = Path(args.out + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
