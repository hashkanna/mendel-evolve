# Results

Everything here comes from runs made during the hackathon (3-4 October 2026). Numbers are filled in as runs
finish; a section that says "pending" has no result yet.

## Problem 60: new lower bounds

C(n) is the size of the largest subset of an n x n x n grid with no 5 points on a common sphere or plane.
"Published" is the best value we could find in public sources on 3 October 2026: the
[record thread](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/6) on the
AlphaEvolve problem repository and the record-holder's
[claims file](https://github.com/hraness/algal-lab/blob/main/research/extremal/claims/no-five-on-sphere-frontier.json),
both last changed on 25 September 2026. Following that thread's convention we call these "apparently new":
new relative to the public sources we found, with no claim of optimality or guaranteed priority.

| n | ours | published | certificate |
|---|---|---|---|
| 21 | **56** | 55 | [n21_56.json](results/no5sphere/certificates/n21_56.json) |
| 23 | **60** | 59 | [n23_60.json](results/no5sphere/certificates/n23_60.json) |
| 26 | **68** | 67 | [n26_68.json](results/no5sphere/certificates/n26_68.json) |

Each set was checked over every 5-subset by three independent exact integer methods:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants;
- `problems/no5sphere/verify.py`: Bareiss elimination on each 5x5 matrix in Python integers;
- `results/no5sphere/third_check.py`: sphere coefficients from 4x4 cofactors, then one dot product per point.

Reproduce: `python results/no5sphere/third_check.py results/no5sphere/certificates/*.json`

### How they were found, stated plainly

These three came from the **seed solver** (a from-scratch C ruin-and-recreate search written at the start of
the hackathon) before any idea had been evolved: 24 seeds per size at 120 CPU-seconds each, with the
`centrosymmetric` seed switch off (n = 23) or on (n = 21, 23, 26). The two searches cost about $0.90 of
Modal compute in total.

First record search, best of 24 seeds per size:

| n | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|
| published | 45 | 48 | 50 | 53 | 55 | 58 | 59 | 62 | 65 | 67 |
| seed solver, defaults | 45 | 47 | 50 | 52 | 55 | 57 | **60** | 62 | 65 | 67 |
| seed solver, centrosymmetric | 45 | 48 | 50 | 52 | **56** | 58 | **60** | 62 | 64 | **68** |

This is the phenomenon that "Evolution or Illusion?" and "What Do Evolutionary Coding Agents Evolve?"
describe: a strong model's first program plus compute already reaches the frontier. Mendel's job is to say
how much the evolved ideas add on top of that, which is the next section.

## Problem 60: what the evolved ideas are worth

Pending: the main run (`runs/p60`) is in progress.

## Circle packing (n = 26): Mendel and OpenEvolve from the same seed program, same model

Pending: three Mendel runs and three OpenEvolve runs (its shipped two-phase recipe), all on
`claude-haiku-4-5`, all scored by the same strict evaluator.

## Exact small cases of problem 60

An independent confirmation, not a new result: C(2) = 4, C(3) = 8 and C(4) = 11 proven with CP-SAT on a row
model whose rows were re-verified by a separate method, and C(5) <= 19. The exact values, including
C(5) = 14, had already been claimed in the record-holder's repository by a different method. See
[exact/RESULTS.md](exact/RESULTS.md).
