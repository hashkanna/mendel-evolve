# Results

Everything here comes from runs made during the hackathon (3-4 October 2026). Numbers are filled in as runs
finish; a section that says "pending" has no result yet.

## Problem 60: new lower bounds at 14 grid sizes

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
| 16 | **44** | 42 | [n16_44.json](results/no5sphere/certificates/n16_44.json) (evolved solver; 43 from the seed solver) |
| 17 | **46** | 45 | [n17_46.json](results/no5sphere/certificates/n17_46.json) |
| 21 | **56** | 55 | [n21_56.json](results/no5sphere/certificates/n21_56.json) |
| 23 | **61** | 59 | [n23_61.json](results/no5sphere/certificates/n23_61.json) |
| 24 | **64** | 62 | [n24_64.json](results/no5sphere/certificates/n24_64.json) |
| 25 | **66** | 65 | [n25_66.json](results/no5sphere/certificates/n25_66.json) |
| 26 | **68** | 67 | [n26_68.json](results/no5sphere/certificates/n26_68.json) |
| 27 | **71** | 70 | [n27_71.json](results/no5sphere/certificates/n27_71.json) (evolved solver) |
| 28 | **74** | 71 | [n28_74.json](results/no5sphere/certificates/n28_74.json) |
| 29 | **76** | 75 | [n29_76.json](results/no5sphere/certificates/n29_76.json) |
| 30 | **79** | 76 | [n30_79.json](results/no5sphere/certificates/n30_79.json) |
| 31 | **81** | 79 | [n31_81.json](results/no5sphere/certificates/n31_81.json) (evolved solver; 80 from the seed solver) |
| 32 | **84** | 82 | [n32_84.json](results/no5sphere/certificates/n32_84.json) |

The first 13 (with 43 at n = 16 and 80 at n = 31), and the sets for n = 33 to 40, were posted on the record thread on 4 October 2026
([comment](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/6#issuecomment-5974924530)); the first three had been posted there the day before.

We equal the published value at n = 13, 14, 18, 19, 20 and 22. For n = 33 to 40, where no sets are
published (the n = 32 set implies 82 because C is non-decreasing), the search gives 86, 90, 91, 94, 96, 98, 100, 103.

Each of the 24 certificates (the 14 above, the two earlier sets at n = 16 and 31, and those for n = 33 to 40)
was checked over every 5-subset by three independent exact integer methods:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants;
- `problems/no5sphere/verify.py`: Bareiss elimination on each 5x5 matrix in Python integers;
- `results/no5sphere/third_check.py`: sphere coefficients from 4x4 cofactors, then one dot product per point.

Reproduce: `python results/no5sphere/third_check.py results/no5sphere/certificates/n23_61.json`

### How they were found, stated plainly

Eleven of the 14 came from the **seed solver**, a from-scratch C ruin-and-recreate search written at the start
of the hackathon, before any idea had been evolved, with its `centrosymmetric` switch on. The other three
(n = 16, 27 and 31) came from the engine's evolved champion, run with the same switch on; see the next section. The first search (24 seeds per size, 120 CPU-seconds, about $0.90 of Modal compute) gave n = 21, 23
and 26. The full search ran 100 to 150 seeds per size at 90 to 480 CPU-seconds, with and without the switch,
for every size from 13 to 32, and 40 seeds at 720 CPU-seconds for 33 to 40: about 520 core-hours.

This is the phenomenon that "Evolution or Illusion?" and "What Do Evolutionary Coding Agents Evolve?"
describe: a strong model's first program plus compute already reaches the frontier.

### What the `centrosymmetric` switch is worth, on the statistic that finds records

Both variants of the seed solver ran on the same seeds and budgets (2,550 runs each over n = 13 to 32), so the
switch can be knocked out at record-search scale:

| over the 13 record sizes, 1,600 paired runs | switch off | switch on | difference, 95% interval |
|---|---|---|---|
| runs that beat the published value | 136 (8.5%) | 262 (16.4%) | +7.9 points [+6.1, +9.6] |
| mean score, averaged over sizes | | | +0.22 points [+0.19, +0.26] |

- The switch moves the average run by a fifth of a point and doubles the rate of record-beating runs. It gives
  the top value at 10 of the 13 sizes and equals the plain solver at the other three (n = 26, 29, 31).
- Without the switch the seed solver still beats the published value at 8 of the 13 sizes (60, 63, 68, 72, 76,
  78, 80 and 83 points at n = 23, 24, 26, 28, 29, 30, 31 and 32).
- Per-run scores are in [search_scores.json](results/no5sphere/search_scores.json); reproduce the table with
  `python results/no5sphere/tail_effect.py`.

## Problem 60: what evolution was worth, and why the engine could not see it

### What the engine measured

The engine ran seven full generations on this problem (run `p60`) and was stopped during the eighth. Its final
ledger holds 30 ideas, 8 from Fable 5.1 inventors and 22 from Sonnet 5.5. Counting generations that were
interrupted and run again, 39 screenings were made. Each idea passed the invariance gate and was screened on
48 seed pairs (n = 17, 20, 23 and 26, 12 seeds each, 45 CPU-seconds per run).

- No idea has a positive effect whose 95% interval excludes zero.
- Of the 30 ideas in the final ledger, five are measured as harmful (interval below zero): `axis_symmetry`
  -0.67, `revisit_tabu` -0.46, `dead_memo` -0.27, `load_ruin` -0.21 and `sphere_bounds` -0.10 points. 23 are
  unresolved: their intervals span zero, so they were shown neither to help nor to hurt. The four ideas of the
  interrupted eighth generation all screened negative (-0.10 to -0.67).
- Two were merged on their point estimates. On seeds the selection never saw, `fresh_first` measures -0.10
  [-0.29, +0.08] and the tuner switched it off again; `kick_escalate` measures +0.04 [-0.04, +0.13].
- The end-of-run decomposition, mean over the training sizes: seed solver 54.90, tuning +0.06, ideas +0.04,
  champion 55.00. Every step is inside the noise of that measurement.

On these numbers alone the conclusion would be that evolution added nothing. It is not the right conclusion.

### A final test at record scale: the evolved solver is better

The champion (the seed solver's constants as tuned by the engine, its switch `guided_ruin` turned on, and the
LLM idea `kick_escalate`) was frozen and run on the same seeds and budgets as the seed solver's record
searches: 2,550 runs per arm over n = 13 to 32. The engine never used these seeds, and 12 of the 20 sizes were
never used by it at all, so this is a test on data that could not have steered the search.

| 13 record sizes, 1,600 paired runs per arm | runs above the published value | difference, 95% interval | mean score, 95% interval |
|---|---|---|---|
| evolved against seed | 218 (13.6%) against 136 (8.5%) | +5.1 points [+3.5, +6.8] | +0.20 [+0.17, +0.24] |
| evolved against seed, both with `centrosymmetric` on | 318 (19.9%) against 262 (16.4%) | +3.5 points [+1.5, +5.4] | +0.08 [+0.04, +0.12] |

- Over all 20 sizes the picture is the same: 8.6% against 5.3% (+3.3 points [+2.3, +4.2]) without the switch,
  12.5% against 10.3% (+2.2 points [+1.0, +3.5]) with it.
- The evolved solver produced the best sets we have at n = 16 (44), n = 27 (71, a size where the seed solver
  only equalled the published 70) and n = 31 (81).
- The engine's own measurement of the same champion against the same seed solver was +0.10, inside its noise.
  At 1,600 pairs and record budgets it is +0.20 with an interval that excludes zero, and the rate of
  record-beating runs is up by 60%.
- Which part of the champion carries this (the tuned constants, `guided_ruin`, or the LLM idea
  `kick_escalate`) is being measured by knocking each one out at the same scale. Results: pending.
- Source of the evolved solver: [results/no5sphere/evolved_solver](results/no5sphere/evolved_solver). Per-run
  scores of all four arms: [search_scores.json](results/no5sphere/search_scores.json), table from
  `python results/no5sphere/tail_effect.py`.

### Why the engine could not see it

Each of these is a limit of the framework as it stands.

1. **Power.** 48 pairs at 45 seconds resolve about +-0.2 points. The effects that matter here are that size:
   `centrosymmetric` is worth +0.22 at record scale and measured -0.01 [-0.19, +0.17] in the engine; the whole
   evolved champion is worth +0.20 and measured +0.10. The default tolerance for the `neutral` label (0.5% of
   the champion's mean, 0.27 points here) is wider than both.
2. **Activation.** `kick_escalate` changes only the second and later kicks in a row that fail to improve the
   best set. At the champion's tuned patience (30,531 iterations) that needs about 61,000 iterations after the
   last improvement. Of the 5,763 stored 45-second runs, 319 were long enough, nearly all at n = 17, and 1 of
   2,941 at n >= 21. In most pairs both arms of its knockout ran the same code, and its knockout on the
   held-out sizes is exactly zero in all 32 pairs. The engine now records, for every screening and knockout,
   how many pairs differed at all, and the dashboard says when none did.
3. **Budget.** At n = 26 half of the 45-second runs were still improving after 20 seconds. A screen at that
   budget measures how fast an idea climbs, not where a long search ends, and records come from long searches.
4. **Statistic.** The engine selects on the mean. Records are in the tail: a change worth a fifth of a point
   on the mean moves the rate of record-beating runs by a half or more.

One more experiment is running: every idea in the ledger, including the 28 that were not kept, screened again
at record-search scale (600 runs per idea, with a control arm). Results: pending.

## Problem 59: a 58-point set at n = 32, where 56 is reported as the best

f(n) is the size of the largest subset of an n x n grid with no isosceles triangle, flat ones included
(Tao et al., [problem 59](https://google-deepmind.github.io/alphaevolve_repository_of_problems/problems/59.html)).
The PatternBoost paper ([arXiv:2411.00566](https://arxiv.org/abs/2411.00566), section 4.1, figure 12) reports
f(32) = 56 and says that "for n up to ≈ 32, SAT solvers can find the best constructions and prove their
optimality"; the AlphaEvolve paper quotes C(32) = 56.

Our from-scratch solver found two different **58-point** sets at n = 32:
[n32_58.json](results/noisosceles/certificates/n32_58.json) and
[n32_58_seed13_iters600000.json](results/noisosceles/certificates/n32_58_seed13_iters600000.json). They share no
point and neither is an image of the other under the symmetries of the square. (A third certificate,
`n32_58_campaign.json`, turned out to be the second set again.)

Both pass four independent checks, re-run on 4 October:

- **DeepMind's own `verify_construction`** from the problem's notebook in their repository, run unchanged. It
  returns True for both sets, True for their published 112-point set at n = 64, and False for one of our sets
  with the midpoint of two of its points added.
- a brute-force pass over every unordered triple (the three squared distances pairwise different);
- `problems/noisosceles/evaluate.py` (sorted squared distances per apex);
- `problems/noisosceles/verify.py` (perpendicular-bisector test, no distances).

The same definition reproduces every published small value: a complete exhaustive search gives 6, 7, 9, 10,
13, 16 and 18 at n = 4 to 10 ([exact_small.py](results/noisosceles/exact_small.py)), and the solver's best
equals the published 28 and 48 at n = 16 and 27 in 200 of 200 runs each, without exceeding them.

What we claim: f(32) >= 58, so 56 is not optimal at n = 32. What we do not know: where the published
optimality proofs actually stop. At n = 32 the solver ends at 58 in 15 of 200 runs and at 56 in the other 185,
so 56 is a very common endpoint, which may be why it looked like the optimum. At n = 64 and n = 100 longer
searches equal the published 112 and 164 ([n64_112.json](results/noisosceles/certificates/n64_112.json))
without exceeding them. We raised it on DeepMind's repository on 4 October 2026 as a discrepancy to be
explained ([issue 10](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/10)); the text is in
[results/noisosceles/announcement.md](results/noisosceles/announcement.md).

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
`claude-haiku-4-5`, seed 3, taken at iteration 61 of 100 in phase 2; strict score 2.624480 from an initial
0.959765; the run later finished at 2.625659):

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
| OpenEvolve, Haiku 4.5, after phase 2, whose prompt names the SLSQP technique (three seeds) | 2.612 to 2.626 | $7.01 to $7.60 per seed for both phases | 200 each |

- What the ledger says did it. In the Fable run one kept gene, `slsqp_polish`, has a knockout effect of +1.67
  [1.67, 1.68] and is labelled general. In the hint run, the typed-in idea (credited to "OpenEvolve phase-2
  prompt") has a knockout effect of +1.44 and is labelled general. In the five Haiku runs the main gene is a
  local-search idea worth +0.2 to +1.8, with several small genes correctly labelled inconclusive or harmful.
- The comparison in plain terms: without the technique hint, MendelEvolve's Haiku runs end at or above
  OpenEvolve's phase 1 plateau, for about twice the money per run, because an inventor session costs more than a
  single completion. With the hint, both systems land near 2.62. With a stronger inventor and no hint,
  MendelEvolve reaches the best known value.
- Limits of the comparison: the OpenEvolve baseline has three seeds (five were planned). All three completed
  both phases, 100 iterations each. Its evaluations ran on a heavily loaded laptop under a wall-clock limit,
  which was raised from 90 to 360 seconds during phase 2, while ours ran on Modal. With the hint the two systems
  cost about the same per run ($7 to $8), and OpenEvolve gets there quickly: its first seed passed 2.6 after
  $2.94. Per-seed data: `baselines/openevolve/results/`.

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
[#5](https://github.com/hashkanna/mendel-evolve/pull/5) ring loading. Each contains a `USABILITY.md`. All five
are merged: each adds only its own `problems/`, `solvers/` and `results/` folders, the test suite passes, and
each solver runs through `mendel score` on the main branch.

- **What worked.** All five wrote a problem pack and a solver (C or Python) that `mendel score` accepted,
  checked the solver's switches with the invariance gate, ran the attribution engine, and ran a record search
  on Modal (about $0.02 to $0.15 each) whose certificates passed an independent checker. The sessions took
  between about 20 and 45 minutes each, much of it waiting for runs. None found a record.
- **What was hard, in all five reports.** `verify.py`, `records.json` and `min_improvement` were not
  documented, so every session read `mendel/campaign.py` to find the contract. `mendel gate SOLVER SOLVER`
  always fails, and nothing said how to check a seed solver's own switches. The README's one-generation
  example never ran the tuner. All three are now fixed in `README.md` and `PROTOCOL.md`.
- **What they found that is still open.** The engine's own record check ignores `min_improvement`, so for
  decimal scores it can log a polished tie as a record (one session saw this; the record searches do apply
  the margin). Seed switches that are off in the champion are measured as knock-ins and get no generality
  label. `mendel run` prints no progress.

## Exact small cases of problem 60

An independent confirmation, not a new result: C(2) = 4, C(3) = 8 and C(4) = 11 proven with CP-SAT on a row
model whose rows were re-verified by a separate method, and C(5) <= 19. The exact values, including
C(5) = 14, had already been claimed in the record-holder's repository by a different method. See
[exact/RESULTS.md](exact/RESULTS.md).
