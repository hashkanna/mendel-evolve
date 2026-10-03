# Exact values and proven upper bounds for C(n) (no 5 points on a sphere or plane)

C(n) = size of the largest subset of the grid {0..n-1}^3 with no 5 points on a common sphere or
plane (Tao et al., AlphaEvolve repository, problem 60). Five points are forbidden exactly when the
5x5 integer determinant with rows `[x, y, z, x^2+y^2+z^2, 1]` is zero.

See `results.json` / `RESULTS.md` for the numbers. Everything here is exact integer arithmetic
plus OR-Tools CP-SAT; at most 3 solver threads were used.

## Files

| file | what |
|---|---|
| `no5sphere_exact.py` | row enumeration, exact checker, brute-force cross-check, CP-SAT optimisation |
| `refute.py` | refutation runs: "model + `sum x >= K`" is INFEASIBLE  =>  C(n) <= K-1 (orbit case split, lazy rows) |
| `refute_case0_split.py`, `refute_case0_split2.py`, `refute_case0_split3.py` | orbit case 0 split by the number of chosen points in the orbits O_0, O_1, O_2 |
| `verify_rows_all.py` | independent validity check of every row used in a proof (exact Gram determinants) |
| `lb_search.py` | lower-bound search by lazy row generation (found nothing for n = 6 in its 240 s budget) |
| `enum_big_n7.py` | relaxation rows for n = 7; its self-test against the complete n = 5 enumeration passed, the n = 7 run was stopped unfinished |
| `make_results.py` | collects the run outputs into `results.json` and `RESULTS.md` and re-checks every reported set |
| `rows_n{3,4,5,6}.json` | the complete row lists (point indices `x*n*n + y*n + z`); n = 6 is 56 MB |
| `rows_n*_verified.json` | output of `verify_rows_all.py` |
| `run_*.json`, `refute_*.json`, `*.log` | raw solver outputs (`t_n4_*.log` are the timing comparison of the symmetry modes on n = 4) |

Run: `uv run --with ortools python exact/no5sphere_exact.py --n 4 --xcheck --workers 3`
and `uv run --with ortools python exact/refute.py --n 5 --K 20 --mode orbit --workers 1`.

## The model

Lift p = (x,y,z) to L(p) = (x, y, z, x^2+y^2+z^2) in R^4. The determinant of five points vanishes
iff the five lifted points lie in a common affine hyperplane `a x + b y + c z + d (x^2+y^2+z^2) + e = 0`,
i.e. on a sphere (d != 0) or a plane (d = 0). Three distinct points always have affinely independent
lifts (a line meets the paraboloid in at most 2 points), so the only lower-dimensional degeneracy is
four lifted points in a common 2-flat = four points on a common circle or line.

One binary variable per grid point and two families of rows:

* **circle rows**: for every 2-flat of R^4 containing >= 4 lifted grid points (every circle or line
  with >= 4 grid points): `sum x <= 3`;
* **hyperplane rows**: for every hyperplane of R^4 containing >= 5 lifted grid points (every sphere
  or plane with >= 5 grid points), except those whose grid points are one rich circle plus a single
  extra point: `sum x <= 4`.

**Claim.** A set S of grid points with |S| >= 5 is valid iff it satisfies all rows.
*Valid => rows:* 4 points of S on a circle/line plus any 5th point of S have zero determinant, and so
do 5 points of S on a sphere/plane. *Rows => valid:* let T be 5 points of S with zero determinant and
F the affine span of L(T), dim F <= 3. If dim F = 2, T lies on a circle with >= 5 grid points and
violates its circle row. If dim F = 3, F is a hyperplane H with >= 5 grid points; either H has a
hyperplane row, violated by T, or H = (rich circle K) + (one point), then |T ∩ K| >= 4 violates the
circle row of K.

Circle rows are only valid for sets of size >= 5 (four concyclic points alone are a legal 4-set), so
the model computes C(n) whenever C(n) >= 5, which holds for n >= 3 by the verified sets found.
n = 2 is done by hand: all 8 cube vertices lie on one sphere and any 4 points are valid, so C(2) = 4
(`make_results.py` checks that all 56 five-subsets have zero determinant).

## Why the enumeration is complete

A hyperplane with a hyperplane row has grid points spanning a 3-flat, so it is spanned by four
affinely independent lifted grid points a, b, c, q. The enumerator fixes a, then b, then loops over
all c > b and groups every other grid point q by the hyperplane through a, b, c, q (the integer
normal `cross4(L(b)-L(a), L(c)-L(a), L(q)-L(a))`, divided by its gcd and sign-normalised; a zero
normal means q is on the circle through a, b, c). A group with >= 2 points off that circle is a
hyperplane with >= 5 grid points; a triple with a 4th point on its circle gives a rich circle.

* If H is a hyperplane with >= 5 grid points that is not "rich circle + one point", then for *any*
  b, c on H the circle through a, b, c leaves >= 2 points of H off it (otherwise H would be that
  circle plus one point), so H is found from every point a on it.
* a only runs over one representative of each orbit of grid points under the 48 symmetries of the
  cube, and the resulting point sets are then closed under the 48 symmetries. Any H contains some
  point p; a symmetry g moves p to its representative, gH is found, and g^-1 brings it back.
* Hash collisions in the grouping can only create extra candidates; every candidate's point set is
  recomputed by the exact incidence test `normal . L(p) + e == 0` over all grid points and kept only
  if it has >= 5 points.

Two independent checks:

* **Brute force, n = 3 and n = 4**: the set of 5-subsets forbidden by the rows was compared with
  the set of 5-subsets of the whole grid with zero determinant (computed over all C(27,5) = 80,730
  and C(64,5) = 7,624,512 subsets). They are identical (16,026 and 714,936 degenerate 5-subsets).
* **Row validity, every row used in any proof** (`verify_rows_all.py`): with M the matrix of rows
  `[x, y, z, x^2+y^2+z^2, 1]` over the points of a row, a hyperplane row needs `det(M^T M) = 0`
  and a circle row needs `det(M_J M_J^T) = 0` for each 4-subset J, in exact Python integers. Checked
  for all rows of n = 3, 4, 5 and for all rows loaded for n = 6 (102,488 circle + 61,901 hyperplane
  rows); a mutation test (one point of a row swapped for an outside point) rejected 4000 of 4000
  corrupted rows. `no5sphere_exact.py` additionally re-checks rows by exact Fraction rank.
* The n = 3 count of degenerate 5-subsets (16,026) was recomputed with the separate `det5` formula.

## What a claim rests on

Completeness is not needed for soundness, only for exactness of the model:

* **Upper bound**: every row is a valid inequality for every valid set of size >= 5. So any subset
  of rows is a relaxation, and if CP-SAT proves "rows + `sum x >= K`" INFEASIBLE (K >= 5), then
  C(n) <= K-1. For n = 6 only a subset of rows is loaded (all circle rows + the hyperplane rows with
  >= 9 points); the remaining rows would be added lazily if a relaxation solution violated them.
* **Lower bound**: every reported set is re-verified by the exact 5-subset determinant checker
  (`exact_check`, pure Python integers, written here; `problems/no5sphere/evaluate.py` did not exist
  when this was run).
* "Exact" is claimed only when both meet.

## Symmetry handling (sound)

`refute.py --mode orbit` splits on point orbits. Let O_1, ..., O_k be the orbits of grid points
under the 48 cube symmetries (largest first) with representatives r_1, ..., r_k. Case j: "S contains
no point of O_1, ..., O_{j-1} and contains r_j". Every non-empty valid set S falls, after applying a
symmetry, into exactly one case: let j be the first orbit that S meets and move a point of S ∩ O_j to
r_j; symmetries map valid sets to valid sets and orbits to themselves. So if all k cases are
INFEASIBLE with `sum x >= K`, no valid set of size >= K exists. Each case is a separate CP-SAT
solve; nothing else is added (CP-SAT's own internal symmetry detection stays on, default settings).

`--implied-layers` adds, for each axis-parallel layer, `sum <= 4` (it is a plane) and
`sum >= K - 4(n-1)` (the other n-1 layers of that axis hold <= 4 each). Both are implied by
"valid and |S| >= K".

`refute_case0_split*.py` split orbit case 0 further by counts: for n = 6 the orbits O_0, O_1, O_2 are
each the complete point set of a sphere around the cube centre (asserted against the row list), so a
valid set has between 0 and 4 points in each (at least 1 in O_0, which contains r_0). Fixing
`|S ∩ O_0| = t`, then `|S ∩ O_1| = u`, then `|S ∩ O_2| = v` and running over all values is an
exhaustive partition of case 0; no symmetry argument is involved.

The alternative `--mode faces` (face-count ordering) is implemented and sound but was slower and is
not used for any reported result. The two schemes are never combined.

## Status and limits

* n = 2, 3, 4 are exact. n = 5: only `sum >= 20` was refuted in the time box, so C(5) <= 19 here; the
  refutation of `sum >= 19` did not finish its first orbit case in 5 minutes on one thread.
* n = 6: nothing below 24 is proven. `sum >= 24` was refuted in 9 of the 10 orbit cases (77 s). The
  remaining case 0 (S contains the generic point (0,1,2); no symmetry left) did not finish as one
  solve (> 13 min). Splitting it by shell counts helps a lot: with t, u, v = the number of chosen
  points in the orbits O_0, O_1, O_2 (each orbit is a full sphere around the cube centre, so each
  count is <= 4; `refute_case0_split*.py`), t = 1, 2, 3 are refuted (about 12 s each), then
  (t, u) = (4, 0..3) (about 6 s each), then (t, u, v) = (4, 4, 0..2) (5-38 s). Only
  (4, 4, 3) and (4, 4, 4) were still running when the time box ended. `sum >= 23` was also refuted
  in orbit cases 1-9 (64 s); its case 0 was not started.
* n = 7 was not attempted beyond starting the row enumeration (`enum_big_n7.py`, stopped).
* The LP relaxation is weak at the root (uniform weights are nearly feasible), so the proofs are
  search-heavy; CP-SAT without its LP (`linearization_level=0`) was far slower on n = 4.
* CP-SAT's INFEASIBLE/OPTIMAL answers are trusted; no independent proof certificate was produced.
* Timings were taken on a machine under heavy load from other jobs (load average about 25 on 10
  cores), so they overstate the solver time needed.

## Prior exact results (checked 2026-10-03)

The DeepMind repository threads (issues #4, #6, #7) and the certificate repositories contain lower
bounds only and state that the only upper bound is 4n. The repository `hraness/algal-lab` (author
0thernet, pull requests #42, #43, #60, #67, merged 2026-09-25/26) claims C(3) = 8 and C(4) = 11
(CaDiCaL UNSAT proofs checked with lrat-check) and C(5) = 14 (exhaustive layer enumeration), with
C(6) >= 18 and a `k = 19` enumeration for n = 6 still pending. So the exact values for n = 3, 4 here
are independent confirmations by a different method, not new. That information comes from the pull
request pages as summarised by a web fetch; the memos themselves were not read.
