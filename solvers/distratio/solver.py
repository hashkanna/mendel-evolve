"""Seed solver for the max/min distance ratio problem (problems/distratio), written for MendelEvolve.

    python solver.py --config CFG.json --instance INST.json --seed N (--time S | --iters K) --out OUT.json

Method. R is scale invariant, so fix the smallest squared distance at 1 and minimise the largest one:

    minimise t   subject to   |p_i - p_j|^2 >= 1   and   |p_i - p_j|^2 <= t   for all i < j,

a smooth nonlinear program in n * d + 1 variables, solved by SLSQP with analytic Jacobians. One
"iteration" is one local solve from one starting configuration; the best configuration over all
iterations is returned. Starting points are uniform in the unit ball unless an idea says otherwise.

Ideas (genes; all off by default):
  lattice_init     start from a jittered patch of the hexagonal (2D) / fcc (3D) lattice
  smooth_presolve  L-BFGS on a log-sum-exp surrogate of log(max d^2) - log(min d^2) before SLSQP
  basin_hop        perturb the current local optimum instead of always starting afresh

Contract (PROTOCOL.md): --time is a CPU-second budget measured here with time.process_time();
--iters K runs exactly K local solves and is deterministic (same config, instance, seed, K -> same
solution and same stats.iters). The output is always a valid solution: a start is written before any
optimisation, and every candidate is renormalised (centroid at 0, smallest distance 1).
"""
from __future__ import annotations

import os

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")  # one core: CPU time stays meaningful and runs stay deterministic

import argparse
import json
import math
import time

import numpy as np
from scipy.optimize import minimize

DEFAULTS = {
    "lattice_init": False, "smooth_presolve": False, "basin_hop": False,
    "slsqp_maxiter": 150, "lattice_jitter": 0.15, "smooth_beta": 20.0, "hop_sigma": 0.15, "hop_patience": 8,
}


class Pairs:
    def __init__(self, n: int, d: int):
        self.n, self.d = n, d
        self.i, self.j = np.triu_indices(n, 1)
        self.m = len(self.i)

    def d2(self, p: np.ndarray) -> np.ndarray:
        diff = p[self.i] - p[self.j]
        return np.einsum("kd,kd->k", diff, diff)

    def ratio(self, p: np.ndarray) -> float:
        d2 = self.d2(p)
        lo = d2.min()
        return float(d2.max() / lo) if lo > 0 else math.inf

    def normalise(self, p: np.ndarray) -> np.ndarray:
        p = p - p.mean(axis=0)
        lo = self.d2(p).min()
        return p / math.sqrt(lo) if lo > 0 else p

    def grad_d2(self, p: np.ndarray, w: np.ndarray) -> np.ndarray:
        """Gradient of sum_k w_k d2_k with respect to p."""
        g = 2.0 * (p[self.i] - p[self.j]) * w[:, None]
        out = np.zeros_like(p)
        np.add.at(out, self.i, g)
        np.add.at(out, self.j, -g)
        return out


def uniform_ball(rng, n: int, d: int) -> np.ndarray:
    v = rng.normal(size=(n, d))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v * rng.random(n)[:, None] ** (1.0 / d)


def lattice_patch(rng, n: int, d: int, jitter: float) -> np.ndarray:
    """n points of the hexagonal (d = 2) or fcc (d >= 3) lattice with unit spacing, the ones nearest to a
    random centre, each moved by jitter * N(0, 1)."""
    k = int(math.ceil(n ** (1.0 / d))) + 2
    grid = np.array(np.meshgrid(*[np.arange(-k, k + 1)] * d, indexing="ij")).reshape(d, -1).T.astype(float)
    if d == 2:
        pts = np.column_stack([grid[:, 0] + 0.5 * grid[:, 1], grid[:, 1] * math.sqrt(3) / 2])
    else:
        pts = grid[grid.sum(axis=1) % 2 == 0] / math.sqrt(2)   # fcc: integer points with even sum
    centre = rng.random(d) - 0.5
    order = np.argsort(np.linalg.norm(pts - centre, axis=1), kind="stable")
    return pts[order[:n]] + jitter * rng.normal(size=(n, d))


def smooth_descent(pairs: Pairs, p: np.ndarray, beta: float) -> np.ndarray:
    """L-BFGS on softmax(log d2) + softmax(-log d2), a smooth stand-in for log(max d2 / min d2)."""
    shape = p.shape

    def f(x):
        q = x.reshape(shape)
        d2 = np.maximum(pairs.d2(q), 1e-300)
        L = np.log(d2)
        a, b = beta * (L - L.max()), -beta * (L - L.min())
        ea, eb = np.exp(a), np.exp(b)
        sa, sb = ea.sum(), eb.sum()
        val = L.max() + math.log(sa) / beta - L.min() + math.log(sb) / beta
        w = (ea / sa - eb / sb) / d2
        return val, pairs.grad_d2(q, w).ravel()

    res = minimize(f, p.ravel(), jac=True, method="L-BFGS-B", options={"maxiter": 200})
    q = res.x.reshape(shape)
    return q if np.all(np.isfinite(q)) and pairs.d2(q).min() > 0 else p


def slsqp(pairs: Pairs, p: np.ndarray, maxiter: int) -> np.ndarray:
    """The epigraph NLP above, from p (already normalised so that min d2 = 1)."""
    n, d, m = pairs.n, pairs.d, pairs.m
    nv = n * d
    rows = np.arange(m)

    def cons(x):
        d2 = pairs.d2(x[:nv].reshape(n, d))
        return np.concatenate([d2 - 1.0, x[nv] - d2])

    def cons_jac(x):
        p_ = x[:nv].reshape(n, d)
        diff = 2.0 * (p_[pairs.i] - p_[pairs.j])
        J = np.zeros((m, nv + 1))
        for c in range(d):
            J[rows, pairs.i * d + c] = diff[:, c]
            J[rows, pairs.j * d + c] = -diff[:, c]
        return np.vstack([J, np.column_stack([-J[:, :nv], np.ones(m)])])

    obj_grad = np.zeros(nv + 1)
    obj_grad[nv] = 1.0
    x0 = np.concatenate([p.ravel(), [pairs.d2(p).max()]])
    res = minimize(lambda x: x[nv], x0, jac=lambda x: obj_grad, method="SLSQP",
                   constraints=[{"type": "ineq", "fun": cons, "jac": cons_jac}],
                   options={"maxiter": int(maxiter), "ftol": 1e-15})
    q = res.x[:nv].reshape(n, d)
    return q if np.all(np.isfinite(q)) else p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--time", type=float)
    ap.add_argument("--iters", type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.config) as f:
        cfg = {**DEFAULTS, **json.load(f)}
    with open(args.instance) as f:
        inst = json.load(f)
    n, d = int(inst["n"]), int(inst.get("d", 2))
    start = time.process_time()

    rng = np.random.default_rng([args.seed, n, d])
    pairs = Pairs(n, d)

    def fresh() -> np.ndarray:
        if cfg["lattice_init"]:
            return lattice_patch(rng, n, d, cfg["lattice_jitter"])
        return uniform_ball(rng, n, d)

    def write(p: np.ndarray, iters: int, trace: list) -> None:
        with open(args.out, "w") as f:
            json.dump({"solution": p.tolist(),
                       "stats": {"iters": iters, "trace": trace, "cpu": round(time.process_time() - start, 3)}}, f)

    best = pairs.normalise(fresh())
    best_r = pairs.ratio(best)
    trace = [[round(time.process_time() - start, 4), best_r]]
    write(best, 0, trace)              # a valid answer exists before any optimisation

    current, current_r, fails = best, best_r, 0
    iters = 0
    while True:
        if args.iters is not None:
            if iters >= args.iters:
                break
        elif time.process_time() - start >= args.time:
            break
        if cfg["basin_hop"] and iters > 0 and fails < cfg["hop_patience"]:
            p = current + cfg["hop_sigma"] * rng.normal(size=(n, d))
        else:
            p = fresh() if iters > 0 else best
            current_r, fails = math.inf, 0
        p = pairs.normalise(p)
        if cfg["smooth_presolve"]:
            p = pairs.normalise(smooth_descent(pairs, p, cfg["smooth_beta"]))
        try:
            q = pairs.normalise(slsqp(pairs, p, cfg["slsqp_maxiter"]))
        except (ValueError, ArithmeticError, np.linalg.LinAlgError):
            q = p
        r = pairs.ratio(q)
        iters += 1
        if r < current_r - 1e-12:
            current, current_r, fails = q, r, 0
        else:
            fails += 1
        if r < best_r:
            best, best_r = q, r
            trace.append([round(time.process_time() - start, 4), best_r])
    write(best, iters, trace)


if __name__ == "__main__":
    main()
