#!/usr/bin/env python3
"""Exact values / proven upper bounds for C(n): the largest subset of {0..n-1}^3 with no
5 points on a common sphere or plane (Tao et al., AlphaEvolve repository, problem 60).

Model (see README.md for the soundness argument):
  lift p=(x,y,z) -> L(p)=(x,y,z,x^2+y^2+z^2) in R^4.  Five points are forbidden iff their
  lifts lie in a common affine hyperplane of R^4 (sphere if the last coefficient is nonzero,
  plane otherwise).
  * "rich circles": every affine 2-flat of R^4 containing >= 4 lifted grid points
    (= circle or line with >= 4 grid points)          ->  sum x <= 3
  * "rich hyperplanes": every affine hyperplane of R^4 containing >= 5 lifted grid points
    (= sphere or plane with >= 5 grid points), except those whose grid points are one rich
    circle plus a single extra point (implied by the circle row)  ->  sum x <= 4
  A set of >= 5 grid points is valid iff it satisfies all rows.

Usage:  uv run --with ortools python exact/no5sphere_exact.py --n 5 --time 600 --workers 3
"""
import argparse
import itertools
import json
import os
import sys
import time
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


# ----------------------------------------------------------------------------- geometry
def grid(n):
    return np.array([(x, y, z) for x in range(n) for y in range(n) for z in range(n)], dtype=np.int64)


def lift(pts):
    return np.concatenate([pts, (pts ** 2).sum(1, keepdims=True)], axis=1)


def symmetries(n):
    """The 48 isometries of the cube as permutations of point indices (idx = x*n*n+y*n+z)."""
    pts = grid(n)
    perms = []
    for perm in itertools.permutations(range(3)):
        for flips in itertools.product((0, 1), repeat=3):
            q = pts[:, perm].copy()
            for c in range(3):
                if flips[c]:
                    q[:, c] = n - 1 - q[:, c]
            perms.append((q[:, 0] * n * n + q[:, 1] * n + q[:, 2]).astype(np.int64))
    return perms


def det5(p, q, r, s, t):
    """Exact integer 5x5 determinant with rows [x,y,z,x^2+y^2+z^2,1] (Python ints)."""
    L = [(a[0], a[1], a[2], a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) for a in (p, q, r, s, t)]
    o = L[0]
    (a0, a1, a2, a3), (b0, b1, b2, b3), (c0, c1, c2, c3), (d0, d1, d2, d3) = [
        tuple(L[i][k] - o[k] for k in range(4)) for i in range(1, 5)
    ]
    return (
        (a0 * b1 - a1 * b0) * (c2 * d3 - c3 * d2)
        - (a0 * b2 - a2 * b0) * (c1 * d3 - c3 * d1)
        + (a0 * b3 - a3 * b0) * (c1 * d2 - c2 * d1)
        + (a1 * b2 - a2 * b1) * (c0 * d3 - c3 * d0)
        - (a1 * b3 - a3 * b1) * (c0 * d2 - c2 * d0)
        + (a2 * b3 - a3 * b2) * (c0 * d1 - c1 * d0)
    )


def exact_check(points, n):
    """Independent exact checker: every 5-subset must have nonzero determinant.
    Returns (ok, detail)."""
    pts = [tuple(int(c) for c in p) for p in points]
    if len(set(pts)) != len(pts):
        return False, "duplicate points"
    if any(len(p) != 3 or any(not 0 <= c < n for c in p) for p in pts):
        return False, "point out of range"
    mind = None
    cnt = 0
    for five in itertools.combinations(pts, 5):
        d = det5(*five)
        cnt += 1
        if d == 0:
            return False, {"degenerate_5_subset": [list(p) for p in five]}
        if mind is None or abs(d) < mind:
            mind = abs(d)
    return True, {"five_subsets_checked": cnt, "min_abs_det": mind}


def exact_rank(rows):
    """Rank of an integer matrix by exact Fraction elimination (independent code path)."""
    M = [[Fraction(v) for v in r] for r in rows]
    rank = 0
    ncol = len(M[0])
    for col in range(ncol):
        piv = None
        for i in range(rank, len(M)):
            if M[i][col] != 0:
                piv = i
                break
        if piv is None:
            continue
        M[rank], M[piv] = M[piv], M[rank]
        pr = M[rank]
        for i in range(rank + 1, len(M)):
            if M[i][col] != 0:
                f = M[i][col] / pr[col]
                M[i] = [a - f * b for a, b in zip(M[i], pr)]
        rank += 1
        if rank == len(M):
            break
    return rank


# ----------------------------------------------------------------------------- enumeration
def _normal_matrices(u, V):
    """For fixed u (4,) and all v=V[c] (N,4): A[c] (4x4) with  cross4(u,v,t) = A[c] @ t.
    cross4(u,v,t) is the normal of the hyperplane spanned by u,v,t (zero iff dependent)."""
    def P(i, j):
        return u[i] * V[:, j] - u[j] * V[:, i]
    P01, P02, P03, P12, P13, P23 = P(0, 1), P(0, 2), P(0, 3), P(1, 2), P(1, 3), P(2, 3)
    Z = np.zeros_like(P01)
    A = np.stack(
        [
            np.stack([Z, P23, -P13, P12], axis=1),
            np.stack([-P23, Z, P03, -P02], axis=1),
            np.stack([P13, -P03, Z, P01], axis=1),
            np.stack([-P12, P02, -P01, Z], axis=1),
        ],
        axis=1,
    )  # (N,4,4)
    return A


def _normalize(nrm):
    """Divide integer vectors (...,4) by gcd and make first nonzero entry positive."""
    g = np.gcd.reduce(nrm, axis=-1)
    g = np.where(g == 0, 1, g)
    nrm = nrm // g[..., None]
    sgn = np.zeros(nrm.shape[:-1], dtype=np.int64)
    for k in range(nrm.shape[-1]):
        sgn = np.where(sgn == 0, np.sign(nrm[..., k]), sgn)
    sgn = np.where(sgn == 0, 1, sgn)
    return nrm * sgn[..., None]


_HASH = np.array([0x9E3779B97F4A7C15, 0xC2B2AE3D27D4EB4F, 0x165667B19E3779F9, 0x27D4EB2F165667C5], dtype=np.uint64)


def enumerate_flats(n, log=print):
    """Return (circles, hypers): lists of sorted index tuples.
    circles: all 2-flats of the lift with >= 4 grid points.
    hypers : all hyperplanes of the lift with >= 5 grid points that are NOT (rich circle + 1 point).
    """
    t0 = time.time()
    pts = grid(n)
    L = lift(pts)
    N = len(pts)
    perms = symmetries(n)
    # orbit representatives of points under the 48 symmetries
    P = np.stack(perms, axis=0)  # (48,N)
    orbit_min = P.min(axis=0)
    reps = sorted(set(int(v) for v in orbit_min))
    log(f"[enum n={n}] N={N} point-orbit representatives={len(reps)}")

    weights = None  # bitmask helper
    circle_masks = set()
    hyper_rows = set()

    def mask_of_bool(row):
        return int.from_bytes(np.packbits(row, bitorder="little").tobytes(), "little")

    for a in reps:
        T = L - L[a]
        La = L[a]
        cand_chunks = []
        for b in range(N):
            if b == a:
                continue
            u = T[b]
            A = _normal_matrices(u, T)  # (N,4,4)
            nrm = np.einsum("clk,qk->cql", A, T)  # (N,N,4)
            zero = ~nrm.any(axis=2)  # q on the 2-flat through a,b,c (or c in {a,b})
            cmask = np.ones(N, dtype=bool)
            cmask[: b + 1] = False  # c > b
            cmask[a] = False
            # rich circles through a,b,c
            zc = zero.sum(axis=1)
            for c in np.nonzero(cmask & (zc >= 4))[0]:
                circle_masks.add(mask_of_bool(zero[c]))
            # hyperplanes through a,b,c with >= 2 further points off the 2-flat
            nn = _normalize(nrm)
            keys = (nn.astype(np.uint64) * _HASH).sum(axis=2, dtype=np.uint64)
            order = np.argsort(keys, axis=1, kind="stable")
            sk = np.take_along_axis(keys, order, axis=1)
            eq = sk[:, 1:] == sk[:, :-1]
            fs = np.zeros((N, N), dtype=bool)
            fs[:, 1:] |= eq
            fs[:, :-1] |= eq
            flagged = np.zeros((N, N), dtype=bool)
            np.put_along_axis(flagged, order, fs, axis=1)
            flagged &= ~zero
            flagged &= cmask[:, None]
            rows = nn[flagged]
            if len(rows):
                rows = np.unique(rows, axis=0)
                cand_chunks.append(rows)
        if cand_chunks:
            rows = np.unique(np.concatenate(cand_chunks, axis=0), axis=0)
            e = -(rows @ La)
            for r, ee in zip(rows.tolist(), e.tolist()):
                hyper_rows.add((r[0], r[1], r[2], r[3], ee))
        log(f"[enum n={n}] rep {a} done: circles so far={len(circle_masks)} hyperplane eqs so far={len(hyper_rows)} t={time.time()-t0:.1f}s")

    # point sets of candidate hyperplanes by exact incidence test
    hyper_masks = set()
    if hyper_rows:
        W = np.array(sorted(hyper_rows), dtype=np.int64)
        for s in range(0, len(W), 20000):
            Wc = W[s : s + 20000]
            inc = (Wc[:, :4] @ L.T + Wc[:, 4:5]) == 0  # (M,N)
            cnts = inc.sum(axis=1)
            for i in np.nonzero(cnts >= 5)[0]:
                hyper_masks.add(mask_of_bool(inc[i]))
    log(f"[enum n={n}] through-rep: circles={len(circle_masks)} hyperplanes={len(hyper_masks)} t={time.time()-t0:.1f}s")

    # close under the 48 symmetries
    def idx_of_mask(m):
        out = []
        i = 0
        while m:
            if m & 1:
                out.append(i)
            m >>= 1
            i += 1
        return out

    def close(masks):
        allm = set()
        for m in masks:
            idx = np.array(idx_of_mask(m), dtype=np.int64)
            for p in perms:
                im = 0
                for j in p[idx].tolist():
                    im |= 1 << j
                allm.add(im)
        return allm

    circles = close(circle_masks)
    hypers = close(hyper_masks)
    log(f"[enum n={n}] after symmetry closure: circles={len(circles)} hyperplanes={len(hypers)} t={time.time()-t0:.1f}s")

    # drop hyperplanes of the form (rich circle) + (one point): implied by the circle row
    kept = []
    dropped = 0
    for m in hypers:
        red = False
        mm = m
        while mm:
            low = mm & -mm
            if (m ^ low) in circles:
                red = True
                break
            mm ^= low
        if red:
            dropped += 1
        else:
            kept.append(m)
    log(f"[enum n={n}] hyperplanes kept={len(kept)} dropped(circle+1)={dropped} t={time.time()-t0:.1f}s")
    circles_l = sorted(tuple(idx_of_mask(m)) for m in circles)
    hypers_l = sorted(tuple(idx_of_mask(m)) for m in kept)
    return circles_l, hypers_l


def enumerate_big(n, min_size, log=print):
    """Relaxation rows for larger n: all rich circles, and all hyperplanes with >= min_size grid
    points (filtered per point-orbit representative before the symmetry closure, to save memory).
    Every row returned is a valid inequality; the list is NOT a complete description."""
    t0 = time.time()
    pts = grid(n)
    L = lift(pts)
    N = len(pts)
    perms = symmetries(n)
    P = np.stack(perms, axis=0)
    reps = sorted(set(int(v) for v in P.min(axis=0)))

    def mask_of_bool(row):
        return int.from_bytes(np.packbits(row, bitorder="little").tobytes(), "little")

    circle_masks, hyper_masks = set(), set()
    for a in reps:
        T = L - L[a]
        La = L[a]
        chunks = []
        for b in range(N):
            if b == a:
                continue
            A = _normal_matrices(T[b], T)
            nrm = np.einsum("clk,qk->cql", A, T)
            zero = ~nrm.any(axis=2)
            cmask = np.ones(N, dtype=bool)
            cmask[: b + 1] = False
            cmask[a] = False
            zc = zero.sum(axis=1)
            for c in np.nonzero(cmask & (zc >= 4))[0]:
                circle_masks.add(mask_of_bool(zero[c]))
            nn = _normalize(nrm)
            keys = (nn.astype(np.uint64) * _HASH).sum(axis=2, dtype=np.uint64)
            sk = np.sort(keys, axis=1)
            # keep only (c,q) whose key occurs >= min_size-3 times in row c (necessary for >= min_size points
            # when the 2-flat through a,b,c has exactly 3 points; rows with a rich 2-flat are kept if >= 2)
            need = max(2, min_size - 3)
            run = np.ones((N, N), dtype=np.int64)
            eq = sk[:, 1:] == sk[:, :-1]
            # count multiplicity of each key via searchsorted per row is slow; use run-length trick
            lo = np.zeros((N, N), dtype=np.int64)
            idxs = np.broadcast_to(np.arange(N), (N, N))
            start = np.where(np.concatenate([np.ones((N, 1), bool), ~eq], axis=1), idxs, 0)
            start = np.maximum.accumulate(start, axis=1)
            endm = np.where(np.concatenate([~eq, np.ones((N, 1), bool)], axis=1), idxs, N)
            endm = np.minimum.accumulate(endm[:, ::-1], axis=1)[:, ::-1]
            mult_sorted = endm - start + 1
            order = np.argsort(keys, axis=1, kind="stable")
            mult = np.zeros((N, N), dtype=np.int64)
            np.put_along_axis(mult, order, mult_sorted, axis=1)
            thr = np.where(zc > 3, 2, need)[:, None]
            flagged = (mult >= thr) & ~zero & cmask[:, None]
            rows = nn[flagged]
            if len(rows):
                chunks.append(np.unique(rows, axis=0))
        if chunks:
            rows = np.unique(np.concatenate(chunks, axis=0), axis=0)
            e = -(rows @ La)
            for s in range(0, len(rows), 20000):
                inc = (rows[s : s + 20000] @ L.T + e[s : s + 20000, None]) == 0
                cnts = inc.sum(axis=1)
                for i in np.nonzero(cnts >= max(5, min_size))[0]:
                    hyper_masks.add(mask_of_bool(inc[i]))
        log(f"[enum-big n={n}] rep {a} done: circles={len(circle_masks)} big hyperplanes={len(hyper_masks)} t={time.time()-t0:.1f}s")

    def idx_of_mask(m):
        out = []
        i = 0
        while m:
            if m & 1:
                out.append(i)
            m >>= 1
            i += 1
        return out

    def close(masks):
        allm = set()
        for m in masks:
            idx = np.array(idx_of_mask(m), dtype=np.int64)
            for p in perms:
                im = 0
                for j in p[idx].tolist():
                    im |= 1 << j
                allm.add(im)
        return allm

    circles = sorted(tuple(idx_of_mask(m)) for m in close(circle_masks))
    hypers = sorted(tuple(idx_of_mask(m)) for m in close(hyper_masks))
    log(f"[enum-big n={n}] closure: circles={len(circles)} hyperplanes(>= {min_size} pts)={len(hypers)} t={time.time()-t0:.1f}s")
    return circles, hypers


def verify_rows(n, circles, hypers, sample=None, seed=0):
    """Independent validity check of the rows (exact Fraction rank of [L(p),1])."""
    pts = grid(n)
    L = lift(pts)
    rng = np.random.default_rng(seed)

    def rk(idx):
        return exact_rank([[int(v) for v in L[i]] + [1] for i in idx])

    def pick(lst):
        if sample is None or len(lst) <= sample:
            return lst
        sel = rng.choice(len(lst), size=sample, replace=False)
        return [lst[i] for i in sel]

    for K in pick(circles):
        assert len(K) >= 4 and rk(K) == 3, ("bad circle row", K)
    for H in pick(hypers):
        assert len(H) >= 5 and rk(H) == 4, ("bad hyperplane row", H)
    return True


def brute_force_crosscheck(n, circles, hypers, log=print):
    """For small n: the set of 5-subsets forbidden by the rows must equal the set of 5-subsets
    with zero determinant (computed independently by brute force over all 5-subsets)."""
    pts = grid(n)
    N = len(pts)
    L = lift(pts)
    t0 = time.time()
    # brute force zero-determinant 5-subsets, vectorised over the last two indices
    bad = set()
    idx = np.arange(N)
    for i, j, k in itertools.combinations(range(N), 3):
        if k >= N - 2:
            continue
        a = L[j] - L[i]
        b = L[k] - L[i]
        rest = idx[k + 1 :]
        C = L[rest] - L[i]  # (m,4)
        A = _normal_matrices(a, b[None, :])[0]  # 4x4, cross4(a,b,t) = A @ t
        Wn = C @ A.T  # (m,4) normals of hyperplane through i,j,k,c
        D = Wn @ C.T  # (m,m): det[a;b;c;d] up to sign
        ii, jj = np.nonzero(np.triu(D == 0, k=1))
        for c, d in zip(rest[ii].tolist(), rest[jj].tolist()):
            bad.add((i, j, k, c, d))
    log(f"[xcheck n={n}] brute-force zero-det 5-subsets: {len(bad)} t={time.time()-t0:.1f}s")
    model = set()
    for H in hypers:
        for five in itertools.combinations(H, 5):
            model.add(five)
    for K in circles:
        Ks = set(K)
        others = [p for p in range(N) if p not in Ks]
        for four in itertools.combinations(K, 4):
            for five in itertools.combinations(K, 5):
                model.add(five)
            for p in others:
                model.add(tuple(sorted(four + (p,))))
    log(f"[xcheck n={n}] model-forbidden 5-subsets: {len(model)} t={time.time()-t0:.1f}s")
    ok = bad == model
    log(f"[xcheck n={n}] equal={ok} (only-brute={len(bad-model)} only-model={len(model-bad)})")
    return ok, len(bad)


# ----------------------------------------------------------------------------- solving
def solve(n, circles, hypers, time_limit, workers, symbreak, hint=None, lower_cut=None, log_search=False, log=print):
    from ortools.sat.python import cp_model

    pts = grid(n)
    N = len(pts)
    m = cp_model.CpModel()
    x = [m.NewBoolVar(f"x_{i}") for i in range(N)]
    for K in circles:
        m.Add(sum(x[i] for i in K) <= 3)
    for H in hypers:
        m.Add(sum(x[i] for i in H) <= 4)
    if symbreak:
        # Sound: reflections x->n-1-x (resp. y,z) swap the two opposite face counts of one axis
        # and leave the other axes' face counts unchanged; coordinate permutations permute the
        # (low,high) face-count pairs.  So every orbit contains a set with
        #   low_c >= high_c for each axis c   and   low_x >= low_y >= low_z.
        low = [sum(x[i] for i in range(N) if pts[i][c] == 0) for c in range(3)]
        high = [sum(x[i] for i in range(N) if pts[i][c] == n - 1) for c in range(3)]
        for c in range(3):
            m.Add(low[c] >= high[c])
        m.Add(low[0] >= low[1])
        m.Add(low[1] >= low[2])
    if lower_cut is not None:
        m.Add(sum(x) >= lower_cut)
    m.Maximize(sum(x))
    if hint is not None:
        hs = set(int(p[0]) * n * n + int(p[1]) * n + int(p[2]) for p in hint)
        for i in range(N):
            m.AddHint(x[i], 1 if i in hs else 0)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = workers
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.log_search_progress = bool(log_search)
    t0 = time.time()
    status = solver.Solve(m)
    wall = time.time() - t0
    name = solver.StatusName(status)
    out = {"status": name, "wall_seconds": round(wall, 2)}
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        sol = [pts[i].tolist() for i in range(N) if solver.Value(x[i])]
        out["objective"] = len(sol)
        out["best_bound"] = solver.BestObjectiveBound()
        out["solution"] = sol
    elif status == cp_model.INFEASIBLE:
        out["objective"] = None
    else:
        out["best_bound"] = solver.BestObjectiveBound()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--time", type=float, default=600)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--symbreak", action="store_true")
    ap.add_argument("--xcheck", action="store_true", help="brute-force cross-check of the rows (small n)")
    ap.add_argument("--hint", type=str, default=None, help="json file with a list of points")
    ap.add_argument("--lower-cut", type=int, default=None, help="add sum x >= K (feasibility/refutation mode)")
    ap.add_argument("--log-search", action="store_true")
    ap.add_argument("--out", type=str, default=None)
    args = ap.parse_args()
    n = args.n
    assert args.workers <= 3, "at most 3 solver threads on this machine"

    cache = os.path.join(HERE, f"rows_n{n}.json")
    t0 = time.time()
    if os.path.exists(cache):
        d = json.load(open(cache))
        circles = [tuple(k) for k in d["circles"]]
        hypers = [tuple(h) for h in d["hypers"]]
        print(f"[enum n={n}] loaded cache: circles={len(circles)} hyperplanes={len(hypers)}")
    else:
        circles, hypers = enumerate_flats(n)
        json.dump({"n": n, "circles": circles, "hypers": hypers}, open(cache, "w"))
    enum_t = time.time() - t0
    t1 = time.time()
    nrows = len(circles) + len(hypers)
    verify_rows(n, circles, hypers, sample=None if nrows <= 60000 else 20000)
    print(f"[rows n={n}] exact-rank validity check passed ({'all' if nrows <= 60000 else 'sample of 20000 per kind'}) t={time.time()-t1:.1f}s")
    res = {"n": n, "num_circle_rows": len(circles), "num_hyperplane_rows": len(hypers), "enum_seconds": round(enum_t, 2),
           "workers": args.workers, "symbreak": bool(args.symbreak), "time_limit": args.time, "lower_cut": args.lower_cut}
    if args.xcheck:
        ok, nbad = brute_force_crosscheck(n, circles, hypers)
        res["bruteforce_crosscheck_equal"] = ok
        res["zero_det_5_subsets"] = nbad
        assert ok
    hint = json.load(open(args.hint)) if args.hint else None
    out = solve(n, circles, hypers, args.time, args.workers, args.symbreak, hint=hint, lower_cut=args.lower_cut, log_search=args.log_search)
    res.update(out)
    if "solution" in out:
        ok, detail = exact_check(out["solution"], n)
        res["solution_exact_check"] = ok
        res["solution_exact_check_detail"] = detail
    print(json.dumps({k: v for k, v in res.items()}, indent=None))
    if args.out:
        json.dump(res, open(args.out, "w"), indent=1)


if __name__ == "__main__":
    main()
