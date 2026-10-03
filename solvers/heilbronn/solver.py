#!/usr/bin/env python3
"""Seed solver for the Heilbronn triangle problems (square, triangle, convex region).

    python solver.py --config CFG.json --instance INSTANCE.json --seed N (--time S | --iters N) --out OUT.json

Method (written from scratch for this repository):

1. Start from random points in the region (seeded numpy Generator).
2. Active-set polish by sequential linear programming. A twice-area cross product is bilinear in the
   coordinates, so around the current points every constraint "this triangle keeps its orientation and has
   area >= t" is linear up to a quadratic term in the step. Each iteration takes the K smallest triangles,
   maximises t over a step inside a box trust region (HiGHS dual simplex), and accepts the step only if the
   true minimum over ALL triples went up. The radius grows after good steps and shrinks after bad ones.
   Region constraints are linear (bounds for the square, x + y <= 1 for the triangle, a linearised
   "hull area does not grow" row plus a gauge fix for the convex variant).
3. Multi-start: every start gets a coarse polish; only starts that come close to the incumbent get the
   full polish.

Idea genes (all off by default): energy_start (smooth soft-min descent before the LP polish),
basin_hopping (relocate a few points of the incumbent instead of restarting), symmetry (search inside a
symmetric subspace, then release it).

Exactness of the output. The search runs in doubles, but what is written is a list of decimal strings with
18 decimals, built from Python integers X, Y on the grid 10^-18: X = trunc(x * 10^18) computed with exact
rationals, then clamped in integers to 0 <= X <= 10^18 (square, convex) and to X + Y <= 10^18 (triangle).
So containment holds by construction in integer arithmetic, never by floating-point luck. The value of
every candidate is recomputed on the gridded integers (all triples, exact) before it can become the
incumbent, a candidate with a duplicate point or a zero triangle is discarded, and the run starts from a
trivially valid fallback (points on a parabola), so the output is always a valid point set.

Budgets. --time is CPU seconds (time.process_time, which includes interpreter start-up). --iters counts LP
solves, energy descents and restarts/hops; under --iters no clock is read, so runs are deterministic.
"""

import os

for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
           "NUMEXPR_NUM_THREADS"):
    os.environ[_v] = "1"  # one core: the budget is CPU time, and the machine is shared

import argparse  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from fractions import Fraction  # noqa: E402

import numpy as np  # noqa: E402
from scipy.optimize import linprog, minimize  # noqa: E402

DIGITS = 18
UNIT = 10 ** DIGITS
FINE_TOL = 1e-10        # relative predicted gain at which the full polish stops (the LP tolerance)
COARSE_STEPS = 80
FINE_STEPS = 400
ENERGY_GATE = 0.6       # with energy_start: a start whose relaxed value is below this fraction of the
                        # reference is dropped before any LP is solved
LP_OPTIONS = {"primal_feasibility_tolerance": 1e-10, "dual_feasibility_tolerance": 1e-10}


# ----------------------------------------------------------------------------------------------------
# exact output
# ----------------------------------------------------------------------------------------------------

def to_grid(P, shape):
    """Float points -> integer points on the 10^-18 grid, inside the region by construction."""
    P = np.asarray(P, dtype=float)
    if shape == "convex":  # the value is affine invariant: move the set into the unit square
        lo = P.min(axis=0)
        span = float((P.max(axis=0) - lo).max())
        P = (P - lo) / (span if span > 0 else 1.0)
    pts = []
    for x, y in P.tolist():
        if not (math.isfinite(x) and math.isfinite(y)):
            return None
        X = min(max(int(Fraction(x) * UNIT), 0), UNIT)
        Y = min(max(int(Fraction(y) * UNIT), 0), UNIT)
        if shape == "triangle" and X + Y > UNIT:
            Y = UNIT - X
        pts.append((X, Y))
    return pts


def exact_value(pts, shape):
    """Exact leaderboard value of gridded points as a Fraction, or None if a point repeats or a triangle is flat."""
    n = len(pts)
    if len(set(pts)) != n:
        return None
    best = None
    for i in range(n - 2):
        xi, yi = pts[i]
        for j in range(i + 1, n - 1):
            dxj, dyj = pts[j][0] - xi, pts[j][1] - yi
            for k in range(j + 1, n):
                c = dxj * (pts[k][1] - yi) - dyj * (pts[k][0] - xi)
                if c < 0:
                    c = -c
                if best is None or c < best:
                    best = c
    if not best:
        return None
    if shape == "square":
        return Fraction(best, 2 * UNIT * UNIT)
    if shape == "triangle":
        return Fraction(best, UNIT * UNIT)
    order = sorted(pts)

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in order:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(order):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    twice = abs(sum(hull[a][0] * hull[(a + 1) % len(hull)][1] - hull[(a + 1) % len(hull)][0] * hull[a][1]
                    for a in range(len(hull))))
    return Fraction(best, twice) if twice else None


def decimal_text(X):
    s = str(X).rjust(DIGITS + 1, "0")
    return s[:-DIGITS] + "." + s[-DIGITS:]


def fallback_points(n):
    """Points on a parabola: distinct, no three collinear, inside the square and inside the triangle."""
    return [(((i + 1) * UNIT) // (2 * (n + 1)), (((i + 1) * UNIT) // (n + 1)) ** 2 // (2 * UNIT)) for i in range(n)]


# ----------------------------------------------------------------------------------------------------
# geometry in doubles
# ----------------------------------------------------------------------------------------------------

def symmetry_maps(shape, symmetry):
    """The affine maps p -> M p + b of the chosen group that preserve the region (identity first)."""
    eye, zero = np.eye(2), np.zeros(2)
    if symmetry == "mirror":
        if shape == "triangle":
            return [(eye, zero), (np.array([[0.0, 1.0], [1.0, 0.0]]), zero)]                  # (x, y) -> (y, x)
        return [(eye, zero), (np.array([[-1.0, 0.0], [0.0, 1.0]]), np.array([1.0, 0.0]))]      # (x, y) -> (1 - x, y)
    order = {"rot2": 2, "rot3": 3, "rot4": 4, "rot5": 5}.get(symmetry, 1)
    if shape == "square":
        if order == 2:
            M, b = -eye, np.array([1.0, 1.0])
        elif order == 4:
            M, b = np.array([[0.0, -1.0], [1.0, 0.0]]), np.array([1.0, 0.0])                   # (x, y) -> (1 - y, x)
        else:
            return [(eye, zero)]
    elif shape == "triangle":
        if order != 3:
            return [(eye, zero)]
        M, b = np.array([[0.0, 1.0], [-1.0, -1.0]]), np.array([0.0, 1.0])                      # (x, y) -> (y, 1 - x - y)
    else:
        if order < 2:
            return [(eye, zero)]
        t = 2.0 * math.pi / order
        M = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
        c = np.array([0.5, 0.5])
        b = c - M @ c
    maps = [(eye, zero)]
    for _ in range(order - 1):
        Mp, bp = maps[-1]
        maps.append((M @ Mp, M @ bp + b))
    return maps


class Model:
    """A configuration space: n points, written as an affine function of parameter points z."""

    def __init__(self, shape, n, symmetry, active_per_point):
        self.shape, self.n = shape, n
        tri = np.array(list(itertools.combinations(range(n), 3)), dtype=np.intp)
        self.I, self.J, self.K = tri[:, 0].copy(), tri[:, 1].copy(), tri[:, 2].copy()
        self.m = len(tri)
        self.kact = min(self.m, max(4, int(active_per_point) * n))
        maps = symmetry_maps(shape, symmetry)
        k = len(maps)
        reps = n // k
        if k == 1 or reps == 0:
            maps, k, reps = maps[:1], 1, n
        free = n - reps * k
        self.order = k
        self.identity = k == 1
        self.npar = reps + free
        B = np.zeros((2 * n, 2 * self.npar))
        off = np.zeros(2 * n)
        for j, (M, b) in enumerate(maps):
            for q in range(reps):
                p = j * reps + q
                B[2 * p:2 * p + 2, 2 * q:2 * q + 2] = M
                off[2 * p:2 * p + 2] = b
        for f in range(free):
            p, q = k * reps + f, reps + f
            B[2 * p:2 * p + 2, 2 * q:2 * q + 2] = np.eye(2)
        self.B, self.off = B, off
        # Gauge of the convex variant: affine maps that commute with the symmetry leave the value unchanged.
        if shape == "convex":
            pins = {1: 5, 2: 3}.get(k, 1)
            if symmetry == "mirror" and k == 2:
                pins = 2
            self.pins = list(range(min(pins, 2 * self.npar - 1)))
        else:
            self.pins = []

    def expand(self, z):
        if self.identity:
            return z.reshape(self.n, 2)
        return (self.B @ z + self.off).reshape(self.n, 2)

    def crosses(self, P):
        x, y = P[:, 0], P[:, 1]
        xi, yi = x[self.I], y[self.I]
        return (x[self.J] - xi) * (y[self.K] - yi) - (y[self.J] - yi) * (x[self.K] - xi)

    def hull(self, P):
        """(area, gradient with respect to the flattened points) of the convex hull."""
        order = np.lexsort((P[:, 1], P[:, 0])).tolist()
        pts = P.tolist()

        def cr(o, a, b):
            return (pts[a][0] - pts[o][0]) * (pts[b][1] - pts[o][1]) - (pts[a][1] - pts[o][1]) * (pts[b][0] - pts[o][0])

        lower, upper = [], []
        for i in order:
            while len(lower) >= 2 and cr(lower[-2], lower[-1], i) <= 0:
                lower.pop()
            lower.append(i)
        for i in reversed(order):
            while len(upper) >= 2 and cr(upper[-2], upper[-1], i) <= 0:
                upper.pop()
            upper.append(i)
        h = np.array(lower[:-1] + upper[:-1], dtype=np.intp)
        x, y = P[h, 0], P[h, 1]
        xn, yn, xp, yp = np.roll(x, -1), np.roll(y, -1), np.roll(x, 1), np.roll(y, 1)
        area = 0.5 * float(np.sum(x * yn - xn * y))
        g = np.zeros(2 * self.n)
        g[2 * h] = 0.5 * (yn - yp)
        g[2 * h + 1] = 0.5 * (xp - xn)
        return area, g

    def scale(self, P):
        """value = scale * min |cross|."""
        if self.shape == "square":
            return 0.5
        if self.shape == "triangle":
            return 1.0
        area = self.hull(P)[0]
        return 0.5 / area if area > 0 else 0.0

    def value(self, z):
        P = self.expand(z)
        return self.scale(P) * float(np.abs(self.crosses(P)).min())

    def project(self, z):
        """Put the parameter points back into the region (their images follow, by symmetry)."""
        if self.shape == "convex":
            return z
        z = np.clip(z, 0.0, 1.0)
        if self.shape == "triangle":
            Z = z.reshape(-1, 2)
            over = Z.sum(axis=1) - 1.0
            bad = over > 0
            if bad.any():
                Z[bad] -= 0.5 * over[bad, None]
                np.clip(Z, 0.0, 1.0, out=Z)
                total = Z.sum(axis=1)
                still = total > 1.0
                Z[still] /= total[still, None]
            z = Z.reshape(-1)
        return z


# ----------------------------------------------------------------------------------------------------
# the search
# ----------------------------------------------------------------------------------------------------

class Search:
    def __init__(self, instance, config, seed, time_budget, iter_budget):
        self.shape, self.n = instance["shape"], int(instance["n"])
        self.cfg = config
        self.rng = np.random.default_rng(int(seed))
        self.time_budget, self.iter_budget = time_budget, iter_budget
        if time_budget is not None:
            self.deadline = time_budget - 0.35 if time_budget > 2.0 else 0.8 * time_budget
        self.iters = 0
        self.lp_solves = 0
        self.starts = 0
        self.trace = []
        self.radius = float(config["trust_radius"])
        self.model = Model(self.shape, self.n, config["symmetry"], config["active_per_point"])
        self.free = self.model if self.model.identity else Model(self.shape, self.n, "none", config["active_per_point"])
        pts = fallback_points(self.n)
        self.best_pts = pts
        self.best_exact = exact_value(pts, self.shape) or Fraction(0)
        self.best_float = float(self.best_exact)
        self.trace.append([round(time.process_time(), 3), self.best_float])

    def done(self):
        if self.iter_budget is not None:
            return self.iters >= self.iter_budget
        return time.process_time() >= self.deadline

    # -- starts ----------------------------------------------------------------------------------

    def random_points(self, count):
        u = self.rng.random((count, 2))
        if self.shape == "triangle":
            fold = u.sum(axis=1) > 1.0
            u[fold] = 1.0 - u[fold]
        return u

    def energy_descent(self, model, z, local=False):
        """L-BFGS-B on the soft-min energy (1/p) log sum a_t^-p with a_t = sqrt(c_t^2 + eps^2)
        (+ log hull area for the convex variant). eps > 0 removes the barrier at zero area, so points can
        cross lines and change the order type; it is lowered to 0 in stages (graduated smoothing). A hop
        of an already good configuration (local=True) only runs the last two stages."""
        p_final = float(self.cfg["energy_power"])
        eps0 = (2.0 if model.shape == "triangle" else 4.0) / (model.n * model.n)
        stages = [(eps0, min(2.0, p_final)), (eps0 / 5.0, min(4.0, p_final)), (eps0 / 25.0, p_final), (0.0, p_final)]
        if local:
            stages = stages[2:]
        for eps, p in stages:
            z = self._descend(model, z, p, eps)
        return z

    def _descend(self, model, z, p, eps):
        n, I, J, K = model.n, model.I, model.J, model.K
        penalty = 1e3
        # Convex variant: the smoothed stages (eps > 0) are not scale invariant, so they run inside the
        # unit box like the square; the last stage (eps = 0) is the free, scale-invariant ratio.
        free_hull = model.shape == "convex" and eps == 0.0

        def f(zv):
            P = model.expand(zv)
            c = model.crosses(P)
            a = np.sqrt(c * c + eps * eps)
            amin = float(a.min())
            if not amin > 0.0:
                return 1e30, np.zeros_like(zv)
            r = (amin / a) ** p
            total = float(r.sum())
            val = -math.log(amin) + math.log(total) / p
            d = -(r / total) * c / (a * a)
            x, y = P[:, 0], P[:, 1]
            g = np.empty(2 * n)
            g[0::2] = (np.bincount(I, d * (y[J] - y[K]), n) + np.bincount(J, d * (y[K] - y[I]), n)
                       + np.bincount(K, d * (y[I] - y[J]), n))
            g[1::2] = (np.bincount(I, d * (x[K] - x[J]), n) + np.bincount(J, d * (x[I] - x[K]), n)
                       + np.bincount(K, d * (x[J] - x[I]), n))
            if free_hull:
                area, gh = model.hull(P)
                if not area > 0.0:
                    return 1e30, np.zeros_like(zv)
                val += math.log(area)
                g += gh / area
            elif model.shape == "triangle":
                over = np.maximum(x + y - 1.0, 0.0)
                val += penalty * float(np.dot(over, over))
                g[0::2] += 2.0 * penalty * over
                g[1::2] += 2.0 * penalty * over
            return val, (g if model.identity else model.B.T @ g)

        bounds = None if free_hull else [(0.0, 1.0)] * len(z)
        self.iters += 1
        try:
            res = minimize(f, z, jac=True, method="L-BFGS-B", bounds=bounds, options={"maxiter": 150, "maxfun": 250})
            out = model.project(np.asarray(res.x, dtype=float))
        except Exception:  # noqa: BLE001 - a failed descent just leaves the start as it was
            return z
        return out if np.all(np.isfinite(out)) else z

    # -- active-set LP polish -------------------------------------------------------------------------

    def polish(self, model, z, tol, max_steps):
        n, nv, K = model.n, len(z), model.kact
        P = model.expand(z)
        c = model.crosses(P)
        a = np.abs(c)
        sc = model.scale(P)
        val = sc * float(a.min())
        if not val > 0.0:
            return z, val
        radius = self.radius
        rows = np.arange(K)
        extra = model.npar if model.shape == "triangle" else (1 if model.shape == "convex" else 0)
        cost = np.zeros(nv + 1)
        cost[nv] = -1.0
        for _ in range(max_steps):
            if self.done():
                break
            self.iters += 1
            self.lp_solves += 1
            tau = float(a.min())
            T = np.argpartition(a, K - 1)[:K] if K < model.m else np.arange(model.m)
            s = np.sign(c[T])
            i, j, k = model.I[T], model.J[T], model.K[T]
            x, y = P[:, 0], P[:, 1]
            G = np.zeros((K, 2 * n))
            G[rows, 2 * i] = s * (y[j] - y[k])
            G[rows, 2 * i + 1] = s * (x[k] - x[j])
            G[rows, 2 * j] = s * (y[k] - y[i])
            G[rows, 2 * j + 1] = s * (x[i] - x[k])
            G[rows, 2 * k] = s * (y[i] - y[j])
            G[rows, 2 * k + 1] = s * (x[j] - x[i])
            Gz = G if model.identity else G @ model.B
            # Variables: u = step / radius in [-1, 1], w = relative gain of the minimum.
            A = np.zeros((K + extra, nv + 1))
            b = np.zeros(K + extra)
            A[:K, :nv] = -(radius / tau) * Gz
            A[:K, nv] = 1.0
            b[:K] = (a[T] - tau) / tau
            lb = np.full(nv + 1, -1.0)
            ub = np.full(nv + 1, 1.0)
            lb[nv], ub[nv] = 0.0, np.inf
            if model.shape != "convex":
                lb[:nv] = np.maximum(-1.0, (0.0 - z) / radius)
                ub[:nv] = np.minimum(1.0, (1.0 - z) / radius)
                if model.shape == "triangle":
                    q = np.arange(model.npar)
                    A[K + q, 2 * q] = 1.0
                    A[K + q, 2 * q + 1] = 1.0
                    b[K:] = np.minimum((1.0 - z[0::2] - z[1::2]) / radius, 4.0)
            else:
                gh = model.hull(P)[1]
                gz = gh if model.identity else gh @ model.B
                norm = float(np.abs(gz).max())
                A[K, :nv] = gz / (norm if norm > 0 else 1.0)   # hull area must not grow (first order)
                lb[model.pins] = 0.0
                ub[model.pins] = 0.0
            lb[:nv] = np.minimum(lb[:nv], 0.0)
            ub[:nv] = np.maximum(ub[:nv], 0.0)
            try:
                res = linprog(cost, A_ub=A, b_ub=b, bounds=np.column_stack([lb, ub]), method="highs-ds",
                              options=LP_OPTIONS)
                ok = res.status == 0 and res.x is not None
            except Exception:  # noqa: BLE001 - treat a solver failure as a rejected step
                ok = False
            if not ok:
                radius *= 0.25
                if radius < 1e-13:
                    break
                continue
            predicted = float(res.x[nv])
            if predicted <= tol:
                break
            z_new = model.project(z + radius * res.x[:nv])
            P_new = model.expand(z_new)
            c_new = model.crosses(P_new)
            a_new = np.abs(c_new)
            sc_new = model.scale(P_new)
            val_new = sc_new * float(a_new.min())
            gain = val_new / val - 1.0
            if gain > 0.0:
                z, P, c, a, sc, val = z_new, P_new, c_new, a_new, sc_new, val_new
                if gain >= 0.7 * predicted:
                    radius = min(2.0 * radius, 0.2)
                elif gain < 0.25 * predicted:
                    radius *= 0.5
            else:
                radius *= 0.25
            if radius < 1e-13:
                break
        return z, val

    # -- bookkeeping -------------------------------------------------------------------------------------

    def consider(self, P, val):
        """Make P the incumbent if its exact gridded value is the best so far."""
        if not val > self.best_float * (1.0 - 1e-12):
            return
        pts = to_grid(P, self.shape)
        if pts is None:
            return
        exact = exact_value(pts, self.shape)
        if exact is not None and exact > self.best_exact:
            self.best_exact, self.best_pts, self.best_float = exact, pts, float(exact)
            self.trace.append([round(time.process_time(), 3), self.best_float])

    def hop(self, z):
        """Relocate a few parameter points, each to the best of some random spots."""
        model = self.model
        z = z.copy()
        count = min(int(self.cfg["hop_points"]), model.npar)
        tries = int(self.cfg["hop_candidates"])
        for q in self.rng.choice(model.npar, size=count, replace=False).tolist():
            best_v, best_c = -1.0, None
            for cand in self.random_points(tries):
                z[2 * q:2 * q + 2] = cand
                v = model.value(z)
                if v > best_v:
                    best_v, best_c = v, cand
            z[2 * q:2 * q + 2] = best_c
        return z

    def run(self):
        cfg, model = self.cfg, self.model
        hopping = bool(cfg["basin_hopping"])
        coarse = max(float(cfg["coarse_tol"]), FINE_TOL)
        gap = float(cfg["promise_gap"])
        patience = int(cfg["hop_patience"])
        cur_z, cur_val, fails = None, -1.0, 0
        while not self.done():
            self.iters += 1
            self.starts += 1
            if hopping and cur_z is not None and fails < patience:
                z = self.hop(cur_z)
            else:
                z = self.random_points(model.npar).reshape(-1)
                cur_z, cur_val, fails = None, -1.0, 0
            reference = cur_val if (hopping and cur_z is not None) else self.best_float
            if cfg["energy_start"]:
                z = self.energy_descent(model, z, local=hopping and cur_z is not None)
                if model.value(z) < ENERGY_GATE * reference:   # hopeless: not worth a single LP
                    if hopping:
                        fails += 1
                    continue
            z, val = self.polish(model, z, coarse, COARSE_STEPS)
            if val >= reference * (1.0 - gap):
                z, val = self.polish(model, z, FINE_TOL, FINE_STEPS)
                P = model.expand(z)
                self.consider(P, val)
                if not model.identity and val >= self.best_float * (1.0 - gap):
                    # Release the symmetry: a free polish can only keep or raise the value.
                    zf, vf = self.polish(self.free, P.reshape(-1).copy(), FINE_TOL, FINE_STEPS)
                    self.consider(self.free.expand(zf), vf)
            if hopping:
                if val > cur_val:
                    cur_z, cur_val, fails = z, val, 0
                else:
                    fails += 1
        return {
            "solution": [[decimal_text(X), decimal_text(Y)] for X, Y in self.best_pts],
            "stats": {"iters": self.iters, "trace": self.trace, "starts": self.starts, "lp_solves": self.lp_solves,
                      "cpu_seconds": round(time.process_time(), 3)},
        }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--time", type=float)
    ap.add_argument("--iters", type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if (args.time is None) == (args.iters is None):
        ap.error("give exactly one of --time and --iters")
    with open(args.config) as f:
        config = json.load(f)
    with open(args.instance) as f:
        instance = json.load(f)
    search = Search(instance, config, args.seed, args.time, args.iters)
    out = search.run()
    tmp = args.out + ".tmp"
    with open(tmp, "w") as f:
        json.dump(out, f)
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
