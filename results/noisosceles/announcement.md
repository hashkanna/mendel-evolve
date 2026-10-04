**Summary.** Below are two different 58-point subsets of the 32 x 32 grid that contain no isosceles triangle, flat ones included, so C(32) >= 58 for problem 59 (Problem 6.59 in the paper). The paper refers to "the fact that C(16) = 28 and C(32) = 56" (arXiv:2511.02864, section 6.39), following PatternBoost (arXiv:2411.00566, section 4.1), whose Figure 12(e) is captioned "f(32) = 56" and which says that "for n up to ≈ 32, SAT solvers can find the best constructions and prove their optimality".

Both sets satisfy the definition used in both papers (a, b, c distinct implies d(a, b) != d(b, c)), and `verify_construction` from this repository's notebook returns True for them, unchanged. So either 56 is not the optimum at n = 32, or I am misreading what was established there. I would be grateful for a pointer either way. This is a lower bound only: I make no claim that 58 is optimal, and no claim of priority beyond the sources I could find on 2026-10-04 (the two papers, this repository and its issues).

**The sets**, as 0-based (x, y) tuples in {0, ..., 31}^2, ready to paste into the notebook:

```python
set_a = [
    (0, 4), (0, 5), (0, 26), (0, 27), (1, 2), (1, 29), (3, 0), (3, 11), (3, 20), (3, 31), (6, 0), (6, 11),
    (6, 20), (6, 31), (7, 0), (7, 11), (7, 20), (7, 31), (8, 1), (8, 30), (9, 1), (9, 30), (11, 4), (11, 5),
    (11, 8), (11, 23), (11, 26), (11, 27), (12, 1), (12, 30), (19, 1), (19, 30), (20, 4), (20, 5), (20, 8),
    (20, 23), (20, 26), (20, 27), (22, 1), (22, 30), (23, 1), (23, 30), (24, 0), (24, 11), (24, 20), (24,
    31), (25, 0), (25, 11), (25, 20), (25, 31), (28, 0), (28, 11), (28, 20), (28, 31), (31, 4), (31, 5),
    (31, 26), (31, 27)
]

set_b = [
    (0, 3), (0, 6), (0, 7), (0, 24), (0, 25), (0, 28), (1, 8), (1, 9), (1, 12), (1, 19), (1, 22), (1, 23),
    (4, 0), (4, 11), (4, 20), (4, 31), (5, 0), (5, 11), (5, 20), (5, 31), (8, 11), (8, 20), (11, 3), (11,
    6), (11, 7), (11, 24), (11, 25), (11, 28), (20, 3), (20, 6), (20, 7), (20, 24), (20, 25), (20, 28), (23,
    11), (23, 20), (26, 0), (26, 11), (26, 20), (26, 31), (27, 0), (27, 11), (27, 20), (27, 31), (29, 1),
    (29, 30), (30, 8), (30, 9), (30, 12), (30, 19), (30, 22), (30, 23), (31, 3), (31, 6), (31, 7), (31, 24),
    (31, 25), (31, 28)
]
```

They share no point, and neither is an image of the other under the eight symmetries of the square. Each is symmetric under the reflection y -> 31 - y, and each is maximal: no further grid point can be added. As in the published constructions, most points lie near the border.

**Verification.** Each set was checked four ways, all exact integer arithmetic on squared distances:

- `verify_construction` from `experiments/subsets_of_the_grid_with_no_isosceles_triangles/subsets_of_the_grid_with_no_isosceles_triangles.ipynb`, run unchanged: True for both. As controls, it returns True for the notebook's own `sol_64` (112 points) and False for set_a with the midpoint of two of its points added.
- A brute-force pass over every unordered triple, requiring the three squared distances to be pairwise different.
- [`problems/noisosceles/evaluate.py`](https://github.com/hashkanna/mendel-evolve/blob/37001da0206230d2b039669c552bb675b1c9b0c6/problems/noisosceles/evaluate.py): for each apex, sorted squared distances to all other points with no repeat.
- [`problems/noisosceles/verify.py`](https://github.com/hashkanna/mendel-evolve/blob/37001da0206230d2b039669c552bb675b1c9b0c6/problems/noisosceles/verify.py): a perpendicular-bisector test that uses no distances.

Certificates with the seed and solver configuration of each run are in [`results/noisosceles/certificates/`](https://github.com/hashkanna/mendel-evolve/tree/37001da0206230d2b039669c552bb675b1c9b0c6/results/noisosceles/certificates) (`n32_58.json` and `n32_58_seed13_iters600000.json`; the second is from a deterministic run and can be regenerated).

**Agreement with the other published values.** The same solver and checkers agree with the published values everywhere else we looked, and do not exceed them:

| n | published | this search |
|---:|---:|---|
| 4 to 10 | 6, 7, 9, 10, 13, 16, 18 | the same seven values, by a complete exhaustive search (`results/noisosceles/exact_small.py`) |
| 16 | 28 | 28 in 200 of 200 runs |
| 27 | 48 | 48 in 200 of 200 runs |
| 32 | 56 | **58** in 15 of 200 runs, 56 in the other 185 |
| 64 | 112 (AlphaEvolve) | 112, not exceeded |
| 100 | 164 (AlphaEvolve) | 164, not exceeded |

The exhaustive search uses the same definition as the checkers, so the agreement at n = 4 to 10 is a check of the definition itself. The n = 16, 27 and 32 rows are 200 seeded runs of 60 CPU-seconds each. At n = 32 the value 56 is by far the most common endpoint, which may be why it looked like the optimum.

One remark, offered as a question and not as a claim. The paper recalls that 112 at n = 64 was guessed from C(2n) = 2 C(n) together with C(32) = 56. If C(32) is at least 58, the same heuristic would point at 116 for n = 64. Our searches at n = 64 have reached 112 and no more.

**How they were found, and disclosure.** These came out of a hackathon project, MendelEvolve (London AI x Science Hackathon, 3 to 4 October 2026). The search is a local search in C with a mirror-symmetry constraint, written from scratch by an AI coding agent (Claude) under my direction; the checkers and this post were AI-assisted as well. No search code from other contributors was used. I take responsibility for the claim; it rests on the coordinates above and the verifier in this repository, not on trust in model output.

Corrections welcome. If the optimality at n = 32 was established for a different definition, or a set of 58 or more points is already public, I will amend this.
