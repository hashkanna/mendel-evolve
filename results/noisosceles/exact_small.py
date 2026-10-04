"""Exact values of f(n) for small n: the largest subset of the n x n grid with no isosceles triangle.

Definition, as in PatternBoost (arXiv:2411.00566, section 4.1) and Problem 6.59 of arXiv:2511.02864:
a, b, c distinct implies d(a, b) != d(b, c), which also forbids a midpoint of two chosen points.

A complete branch-and-bound search in pure Python. It reproduces the published values
f(4..10) = 6, 7, 9, 10, 13, 16, 18 (n = 10 takes about two minutes), which shows that the definition used
by the checkers in this repository is the published one.

    python results/noisosceles/exact_small.py          # n = 4 to 9
    python results/noisosceles/exact_small.py 10       # one size
"""

import sys
import time

PUBLISHED = {4: 6, 5: 7, 6: 9, 7: 10, 8: 13, 9: 16, 10: 18}


def exact(n: int) -> int:
    points = [(x, y) for x in range(n) for y in range(n)]
    count = len(points)

    def d(p, q):
        return (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2

    # forbidden[i][j]: bitmask of the points that form an isosceles triple with points i and j
    forbidden = [[0] * count for _ in range(count)]
    for i in range(count):
        for j in range(i + 1, count):
            mask, dij = 0, d(points[i], points[j])
            for k in range(count):
                if k in (i, j):
                    continue
                a, b = d(points[i], points[k]), d(points[j], points[k])
                if a == b or a == dij or b == dij:
                    mask |= 1 << k
            forbidden[i][j] = forbidden[j][i] = mask
    best = [0]

    def search(chosen: list, candidates: int, size: int) -> None:
        if size > best[0]:
            best[0] = size
        while candidates:
            if size + bin(candidates).count("1") <= best[0]:
                return
            k = candidates.bit_length() - 1
            candidates &= ~(1 << k)
            rest = candidates
            for c in chosen:
                rest &= ~forbidden[c][k]
            search(chosen + [k], rest, size + 1)

    search([], (1 << count) - 1, 0)
    return best[0]


if __name__ == "__main__":
    sizes = [int(a) for a in sys.argv[1:]] or [4, 5, 6, 7, 8, 9]
    for n in sizes:
        start = time.time()
        value = exact(n)
        print(f"f({n}) = {value}  (published {PUBLISHED.get(n, '?')})  {time.time() - start:.1f} s")
