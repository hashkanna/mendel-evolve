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
| 15 | **41** | 40 | [n15_41.json](results/no5sphere/certificates/n15_41.json) |
| 16 | **43** | 42 | [n16_43.json](results/no5sphere/certificates/n16_43.json) |
| 21 | **56** | 55 | [n21_56.json](results/no5sphere/certificates/n21_56.json) |
| 23 | **60** | 59 | [n23_60.json](results/no5sphere/certificates/n23_60.json) |
| 26 | **68** | 67 | [n26_68.json](results/no5sphere/certificates/n26_68.json) |

Each set was checked over every 5-subset by three independent exact integer methods:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants;
- `problems/no5sphere/verify.py`: Bareiss elimination on each 5x5 matrix in Python integers;
- `results/no5sphere/third_check.py`: sphere coefficients from 4x4 cofactors, then one dot product per point.

Reproduce: `python results/no5sphere/third_check.py results/no5sphere/certificates/*.json`

### How they were found, stated plainly

All five came from the **seed solver** (a from-scratch C ruin-and-recreate search written at the start of
the hackathon) before any idea had been evolved. n = 21, 23 and 26: 24 seeds per size at 120 CPU-seconds
each, with the `centrosymmetric` seed switch off (n = 23) or on (n = 21, 23, 26); the two searches cost
about $0.90 of Modal compute. n = 15 and 16: 100 seeds per size at 90 CPU-seconds with the switch on. Larger
searches at every size from 13 to 40 are reported below as they finish.

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

## Problem 59: a 58-point set at n = 32, where 56 is reported as the best

f(n) is the size of the largest subset of an n x n grid with no isosceles triangle, flat ones included
(Tao et al., [problem 59](https://google-deepmind.github.io/alphaevolve_repository_of_problems/problems/59.html)).
The PatternBoost paper ([arXiv:2411.00566](https://arxiv.org/abs/2411.00566), section 4.1, figure 12) reports
f(32) = 56 and says that "for n up to ≈ 32, SAT solvers can find the best constructions and prove their
optimality"; the AlphaEvolve paper quotes C(32) = 56.

Our from-scratch solver found two different **58-point** sets at n = 32:
[n32_58.json](results/noisosceles/certificates/n32_58.json) and
[n32_58_seed13_iters600000.json](results/noisosceles/certificates/n32_58_seed13_iters600000.json).

Both pass four independent checks:

- `problems/noisosceles/evaluate.py` (sorted squared distances per apex);
- `problems/noisosceles/verify.py` (perpendicular-bisector test, no distances);
- a third check written separately (every apex has distinct squared distances to all other points, and a
  brute-force pass over every ordered triple);
- **DeepMind's own `verify_construction`** from the problem's notebook in their repository, run unchanged. It
  returns True for both sets, True for their published 112-point set at n = 64, and False for a set that
  contains three equally spaced collinear points.

The same checkers reproduce the published values at smaller sizes: exhaustive search gives 6, 7, 9 at
n = 4, 5, 6, and the solver's best equals the published 10, 13, 16, 18, 28 and 48 at n = 7, 8, 9, 10, 16
and 27 without exceeding them.

What we claim: f(32) >= 58, so 56 is not optimal at n = 32. What we do not know: where the published
optimality proofs actually stop. The solver found 58 in 2 of 20 short runs and 56 in the rest. At n = 64
and n = 100 it has not yet matched AlphaEvolve's 112 and 164 (best so far 104 and 162).

On this problem the seed solver's own switches matter a great deal, and more together than apart
(n = 64 / n = 100, mean of 3 seeds at a short budget): base 92.3 / 141.0; `greedy_victim` alone 95.7 / 145.0;
`symmetric` alone 96.0 / 141.7; both 101.3 / 151.0.

## Explaining another system's result: what did OpenEvolve evolve?

`mendel explain` takes a program evolved by another system, has an LLM split every difference from the
initial program into a named switch, checks that all-off reproduces the initial program and all-on
reproduces the evolved one (here: bit for bit), and then runs knockouts.

Applied to the best program of one OpenEvolve run on circle packing (its two-phase recipe on
`claude-haiku-4-5`, seed 3, stopped at 61 of 100 phase 2 iterations; strict score 2.624480 from an initial
0.959765):

| switch | knocked out of the evolved program | switched on alone in the initial program |
|---|---|---|
| `slsqp_optimizer` | -0.3490 | **+1.6415 (99% of the whole gain)** |
| `row_layout` | breaks the rest (the optimiser collapses without it) | +0.6758 |
| `neighbor_radii` | -0.0066 | +0.0193 |
| `refine_expand` | 0 exactly | +0.2776 |
| `refine_shrink` | 0 exactly | -0.0001 |

- Switching on the SLSQP optimiser alone reaches 2.6013. Everything else adds 0.0232 in total, about 1.4%
  of the gain, and the two refinement passes do nothing in the evolved program.
- OpenEvolve's shipped phase 2 prompt recommends this optimiser by name.
- No constant of the initial program was changed by the evolution. Tuning those constants alone, with every
  switch off, reaches 1.9338.
- Limits: one run, one instance, deterministic programs (so the differences are exact, not statistical), and
  one decomposition out of several possible. Details in
  [results/explain/oe-two-phase-seed3/report.md](results/explain/oe-two-phase-seed3/report.md); snapshot at
  [docs/explain-oe-two-phase-seed3.html](docs/explain-oe-two-phase-seed3.html).

## Third autocorrelation inequality: honest status

From scratch our solver reaches 1.45414 (the best of 43 runs of 600 CPU-seconds), short of the public
leaderboard's 1.45081. We do not compare it with AlphaEvolve's published 1.4557, because the two may be
stated for different variants of the inequality. Starting from the leaderboard's top solution and re-optimising it gives 1.4507562130316245, which is
below the leaderboard value by 5.0e-5 (its minimum improvement is 1e-5) and passes the leaderboard's own
verifier code. That is an improvement of someone else's construction, not a discovery from scratch, and we
report it as such. Nothing has been submitted.

## Circle packing (n = 26): Mendel and OpenEvolve from the same seed program, same model

In progress: five MendelEvolve runs with `claude-haiku-4-5` inventors and no hints, one run that receives
OpenEvolve's phase 2 hint as a typed-in idea, one run with Fable inventors, and five OpenEvolve runs of its
shipped two-phase recipe on `claude-haiku-4-5`, all scored by the same strict evaluator.

OpenEvolve so far (three seeds, phase 2 stopped early by a spending cap that has since been lifted): after
phase 1, 2.17 to 2.29; after phase 2, 2.607 to 2.624. Its phase 2 prompt names the technique that produces
the jump.

## Exact small cases of problem 60

An independent confirmation, not a new result: C(2) = 4, C(3) = 8 and C(4) = 11 proven with CP-SAT on a row
model whose rows were re-verified by a separate method, and C(5) <= 19. The exact values, including
C(5) = 14, had already been claimed in the record-holder's repository by a different method. See
[exact/RESULTS.md](exact/RESULTS.md).
