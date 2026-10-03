#!/usr/bin/env python3
"""Soundness check of ALL rows used in an upper-bound proof, by a method independent of the enumeration
code: exact Gram determinants in Python integers (Bareiss).
  M = matrix with rows [x, y, z, x^2+y^2+z^2, 1] over the points of a row.
  hyperplane row valid  <=> points lie in a common hyperplane of the lift <=> rank M <= 4 <=> det(M^T M) = 0  (5x5)
  circle row valid      <=> points lie in a common 2-flat of the lift     <=> rank M <= 3
                        <=> det(M_J M_J^T) = 0 for every 4-subset J of the row                      (4x4)
A mutation test (swap one point of a row for a point outside it) shows the check is not vacuous.
Usage: verify_rows_all.py n min_hyper_size"""
import itertools, json, os, random, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))


def det_bareiss(A):
    n = len(A)
    A = [list(r) for r in A]
    sign, prev = 1, 1
    for k in range(n - 1):
        if A[k][k] == 0:
            sw = next((i for i in range(k + 1, n) if A[i][k] != 0), None)
            if sw is None:
                return 0
            A[k], A[sw] = A[sw], A[k]
            sign = -sign
        for i in range(k + 1, n):
            for j in range(k + 1, n):
                A[i][j] = (A[i][j] * A[k][k] - A[i][k] * A[k][j]) // prev
        prev = A[k][k]
    return sign * A[n - 1][n - 1]


def hyper_ok(M):  # rank <= 4
    G = [[sum(r[a] * r[b] for r in M) for b in range(5)] for a in range(5)]
    return det_bareiss(G) == 0


def circle_ok(M):  # rank <= 3
    for J in itertools.combinations(M, 4):
        G = [[sum(u[k] * v[k] for k in range(5)) for v in J] for u in J]
        if det_bareiss(G) != 0:
            return False
    return True


def main():
    n = int(sys.argv[1]); minsize = int(sys.argv[2])
    d = json.load(open(os.path.join(HERE, f"rows_n{n}.json")))
    L = [(x, y, z, x * x + y * y + z * z, 1) for x in range(n) for y in range(n) for z in range(n)]
    N = len(L)
    t = time.time()
    circles = d["circles"]; hypers = [h for h in d["hypers"] if len(h) >= minsize]
    assert det_bareiss([[2, 0, 1], [1, 3, 2], [1, 1, 1]]) == 2 * (3 - 2) - 0 + 1 * (1 - 3)
    for K in circles:
        assert len(K) >= 4 and len(set(K)) == len(K) and all(0 <= i < N for i in K) and circle_ok([L[i] for i in K]), ("bad circle row", K)
    for H in hypers:
        assert len(H) >= 5 and len(set(H)) == len(H) and all(0 <= i < N for i in H) and hyper_ok([L[i] for i in H]), ("bad hyperplane row", H)
    # mutation test: the check must reject most corrupted rows
    rng = random.Random(1)
    rej = tot = 0
    for rows, ok in ((circles, circle_ok), (hypers, hyper_ok)):
        for row in rng.sample(rows, min(2000, len(rows))):
            q = rng.choice([i for i in range(N) if i not in row])
            mut = list(row); mut[rng.randrange(len(mut))] = q
            tot += 1; rej += not ok([L[i] for i in mut])
    out = {"n": n, "min_hyper_size": minsize, "circle_rows_verified": len(circles), "hyperplane_rows_verified": len(hypers), "all_valid": True,
           "mutants_rejected": rej, "mutants_tested": tot, "seconds": round(time.time() - t, 1)}
    json.dump(out, open(os.path.join(HERE, f"rows_n{n}_min{minsize}_verified.json"), "w"))
    print(out)


if __name__ == "__main__":
    main()
