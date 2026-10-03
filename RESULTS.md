# Results

Everything here comes from runs made during the hackathon (3-4 October 2026). Numbers are filled in as runs
finish; a section that says "pending" has no result yet.

## Problem 60: new lower bounds at 13 grid sizes

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
| 17 | **46** | 45 | [n17_46.json](results/no5sphere/certificates/n17_46.json) |
| 21 | **56** | 55 | [n21_56.json](results/no5sphere/certificates/n21_56.json) |
| 23 | **61** | 59 | [n23_61.json](results/no5sphere/certificates/n23_61.json) |
| 24 | **64** | 62 | [n24_64.json](results/no5sphere/certificates/n24_64.json) |
| 25 | **66** | 65 | [n25_66.json](results/no5sphere/certificates/n25_66.json) |
| 26 | **68** | 67 | [n26_68.json](results/no5sphere/certificates/n26_68.json) |
| 28 | **74** | 71 | [n28_74.json](results/no5sphere/certificates/n28_74.json) |
| 29 | **76** | 75 | [n29_76.json](results/no5sphere/certificates/n29_76.json) |
| 30 | **79** | 76 | [n30_79.json](results/no5sphere/certificates/n30_79.json) |
| 31 | **80** | 79 | [n31_80.json](results/no5sphere/certificates/n31_80.json) |
| 32 | **84** | 82 | [n32_84.json](results/no5sphere/certificates/n32_84.json) |

We equal the published value at n = 13, 14, 18, 19, 20, 22 and 27. For n = 33 to 40, where no sets are
published (the n = 32 set implies 82 because C is non-decreasing), the search gives 86, 90, 91, 94, 96, 98, 100, 103.

Each of the 13 sets was checked over every 5-subset by three independent exact integer methods:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants;
- `problems/no5sphere/verify.py`: Bareiss elimination on each 5x5 matrix in Python integers;
- `results/no5sphere/third_check.py`: sphere coefficients from 4x4 cofactors, then one dot product per point.

The n = 33 to 40 sets passed the first two. Reproduce:
`python results/no5sphere/third_check.py results/no5sphere/certificates/n23_61.json`

### How they were found, stated plainly

All of them came from the **seed solver**, a from-scratch C ruin-and-recreate search written at the start of
the hackathon, before any idea had been evolved, and all 13 records were found with its `centrosymmetric`
switch on. The first search (24 seeds per size, 120 CPU-seconds, about $0.90 of Modal compute) gave n = 21, 23
and 26. The full search ran 100 to 150 seeds per size at 90 to 480 CPU-seconds, with and without the switch,
for every size from 13 to 32, and 40 seeds at 720 CPU-seconds for 33 to 40: about 520 core-hours.

This is the phenomenon that "Evolution or Illusion?" and "What Do Evolutionary Coding Agents Evolve?"
describe: a strong model's first program plus compute already reaches the frontier.

## Problem 60: what the evolved ideas are worth

The engine ran 8 generations on this problem (run `p60`): 37 ideas, 10 from Fable 5.1 inventors and 27 from
Sonnet 5.5, each gated for invariance and screened with paired seeds on n = 17, 20, 23 and 26 at 45 CPU-seconds.

- No idea has a positive effect whose 95% interval excludes zero. Two were merged on their point estimates
  (`fresh_first`, `kick_escalate`) and measure as no effect on seeds the selection never saw.
- Several are clearly harmful at screening, for example `axis_symmetry` -0.67, `old_first` -0.67 and
  `revisit_tabu` -0.46 points.
- Where the gain came from (mean over training sizes): seed solver 54.90, tuning 0.0, ideas +0.10, which is
  inside the noise.

So on this problem evolution added nothing we can measure, and the ledger says so. One limitation showed up
clearly: the seed's own `centrosymmetric` switch measures -0.01 [-0.19, +0.17] on the mean at this budget, yet
every one of the 13 records was found with it on. The engine optimises the mean over seeds at a short budget;
a record is the best of hundreds of longer runs. Selecting on a best-of-k statistic is the first thing we would
change.

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
optimality proofs actually stop. The solver found 58 in 2 of 20 short runs and 56 in the rest, and a later
200-seed search produced a third, different 58-point set. At n = 64 and n = 100 longer searches equal the
published 112 and 164 ([n64_112.json](results/noisosceles/certificates/n64_112.json)) without exceeding them.

On this problem the seed solver's own switches matter a great deal, and more together than apart
(n = 64 / n = 100, mean of 3 seeds at a short budget): base 92.3 / 141.0; `greedy_victim` alone 95.7 / 145.0;
`symmetric` alone 96.0 / 141.7; both 101.3 / 151.0.

The engine run on this problem (`p59`, 9 generations so far) measures the same thing with intervals, on
seeds the tuner never saw: `symmetric` +9.25 [8.5, 10.0], `greedy_victim` +4.56 [3.25, 5.88], `hollow` +1.81
[0.94, 2.62], all labelled general on held-out sizes, with a pair synergy of +3.69 between the first two.
27 LLM ideas were screened on top of that; none is conclusively positive.

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

## Circle packing (n = 26): MendelEvolve and OpenEvolve from the same seed program

Every system starts from OpenEvolve's own initial program (strict score 0.96) and is scored by the same exact
evaluator with no overlap tolerance. Best known: 2.635983.

| System | Best packing | LLM spend | LLM calls |
|---|---|---|---|
| MendelEvolve, Fable 5.1 inventors, no hints | **2.635983** (the best known value, to 11 decimals) | $26.07 over 8 generations; reached after $10.95 | 50; reached after 8 |
| MendelEvolve, Haiku 4.5 inventors, plus OpenEvolve's hint typed in as an idea | 2.6199 | $7.60 | 45 |
| MendelEvolve, Haiku 4.5 inventors, no hints (five runs) | 2.314 to 2.440 | $6.55 to $8.40 each | 40 to 42 each |
| OpenEvolve, Haiku 4.5, phase 1, no technique hint (three seeds) | 2.17 to 2.29 | about $2.90 each | 100 each |
| OpenEvolve, Haiku 4.5, phase 2, whose prompt names the SLSQP technique (three seeds, incomplete) | 2.607 to 2.624 when first stopped | $21.99 for all three seeds so far | 137 to 161 each when first stopped |

- What the ledger says did it. In the Fable run one kept gene, `slsqp_polish`, has a knockout effect of +1.67
  [1.67, 1.68] and is labelled general. In the hint run, the typed-in idea (credited to "OpenEvolve phase-2
  prompt") has a knockout effect of +1.44 and is labelled general. In the five Haiku runs the main gene is a
  local-search idea worth +0.2 to +1.8, with several small genes correctly labelled inconclusive or harmful.
- The comparison in plain terms: without the technique hint, MendelEvolve's Haiku runs end at or above
  OpenEvolve's phase 1 plateau, for about twice the money per run, because an inventor session costs more than a
  single completion. With the hint, both systems land near 2.62. With a stronger inventor and no hint,
  MendelEvolve reaches the best known value.
- Limits of the comparison: the OpenEvolve baseline has three seeds, its phase 2 was stopped part-way twice (a
  spending cap, then to save credits), and its evaluations ran on a heavily loaded laptop with a wall-clock limit
  while ours ran on Modal. Per-seed data: `baselines/openevolve/results/`.

## Research efficiency

| Run | Generations | LLM calls | LLM spend | Evaluations | CPU-hours |
|---|---|---|---|---|---|
| Problem 60 (`p60`) | 8 | 41 | $30.63 | 5,886 | 72.4 |
| Problem 59 (`p59`, still running) | 9 | 36 | $18.23 | 3,720 | 29.0 |
| Circle packing, Fable | 8 | 50 | $26.07 | 919 | 1.3 |
| Circle packing, Haiku, five runs | 10 each | 40 to 42 each | $6.55 to $8.40 each | 1,518 to 2,103 each | 3.3 to 4.2 each |

LLM calls are spent only on inventing genes; every other evaluation is plain compute. The record searches used
no LLM calls at all: about 520 core-hours on Modal.

## Ease of use: five outside agents added a benchmark each

Five Devin sessions, each in a fresh clone and given only `README.md` and `PROTOCOL.md`, were asked to add a new
benchmark from Tao et al.'s repository and to write down what was unclear. All five opened pull requests:
[#1](https://github.com/hashkanna/mendel-evolve/pull/1) distance ratio,
[#2](https://github.com/hashkanna/mendel-evolve/pull/2) flat polynomials,
[#3](https://github.com/hashkanna/mendel-evolve/pull/3) difference bases,
[#4](https://github.com/hashkanna/mendel-evolve/pull/4) Erdos minimum overlap,
[#5](https://github.com/hashkanna/mendel-evolve/pull/5) ring loading. Each contains a `USABILITY.md` with its
findings. We have not yet reviewed them.

## Exact small cases of problem 60

An independent confirmation, not a new result: C(2) = 4, C(3) = 8 and C(4) = 11 proven with CP-SAT on a row
model whose rows were re-verified by a separate method, and C(5) <= 19. The exact values, including
C(5) = 14, had already been claimed in the record-holder's repository by a different method. See
[exact/RESULTS.md](exact/RESULTS.md).
