"""A third, deliberately different check of a no-5-on-a-sphere certificate.

evaluate.py computes vectorised int64 determinants; verify.py runs Bareiss elimination on each 5x5
matrix. This one, for every 4-subset, derives the integer coefficients of the sphere or plane through
those four points from 4x4 cofactors and then tests each later point with one dot product, all in
Python integers.

    python results/no5sphere/third_check.py results/no5sphere/certificates/n23_60.json
"""

import itertools
import json
import sys
from math import comb


def det3(a):
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))


def det4(m):
    return sum(((-1) ** j) * m[0][j] * det3([[m[i][k] for k in range(4) if k != j] for i in range(1, 4)])
               for j in range(4))


def check(path):
    cert = json.load(open(path))
    n = cert["instance"]["n"]
    pts = [tuple(p) for p in cert["solution"]]
    assert len(set(pts)) == len(pts), "duplicate points"
    assert all(isinstance(v, int) and 0 <= v < n for p in pts for v in p), "point out of range"
    rows = [(x, y, z, x * x + y * y + z * z, 1) for x, y, z in pts]
    k, checked, degenerate, min_abs = len(rows), 0, 0, None
    for a, b, c, d in itertools.combinations(range(k), 4):
        four = [rows[a], rows[b], rows[c], rows[d]]
        cof = [((-1) ** j) * det4([[r[t] for t in range(5) if t != j] for r in four]) for j in range(5)]
        for e in range(d + 1, k):
            value = sum(cof[j] * rows[e][j] for j in range(5))
            checked += 1
            degenerate += value == 0
            if min_abs is None or abs(value) < min_abs:
                min_abs = abs(value)
    assert checked == comb(k, 5)
    print(f"{path}: n={n} points={k} five_subsets={checked} degenerate={degenerate} min_abs_det={min_abs} "
          f"-> {'VALID' if degenerate == 0 else 'INVALID'}")
    return degenerate == 0


if __name__ == "__main__":
    sys.exit(0 if all([check(p) for p in sys.argv[1:]]) else 1)
