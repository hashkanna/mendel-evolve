# Usability report: adding `flatpoly` to MendelEvolve

Tester: Devin (an AI agent), working from a fresh clone, on a shared macOS arm64 laptop (10 cores, load
average around 100 during the test). Session started 22:40 BST on 2026-10-03.

The question was whether someone new can add a benchmark from README.md and PROTOCOL.md. Short answer:
**yes, but only by copying an existing pack and reading framework source.** The two documents describe
the minimum contract correctly. The deliverables that matter in practice (`verify.py`, `records.json`,
`min_improvement`, `gate` instances, what a `--generations 1` run actually does) are documented only
in code, or not at all.

## Timeline (wall clock)

| Step | Time | Notes |
|---|---|---|
| Read README, PROTOCOL, `autocorr3` pack, arena API | 22:40 to 22:42 | quick; `autocorr3` was the right template (float leaderboard, `min`) |
| Read `problem.py`, `campaign.py`, `cli.py`, `gate.py` | 22:42 to 22:44 | needed to find out what `verify.py` must do (see below) |
| `evaluate.py`, `verify.py`, `records.json`, `problem.toml` | 22:43 to 22:46 | reproduced the top arena score bit for bit at the first attempt |
| C solver, first version | 22:45 to 22:47 | |
| Found and fixed a solver bug (internal score below the arena's) | 22:47 to 22:48 | my bug, caught by comparing with the evaluator |
| `uv run pytest -q` | 22:47 to 22:49 | 46 passed in 95 s |
| `mendel score`, `mendel gate` | 22:49 to 22:51 | the gate command as specified cannot pass (see 3) |
| Attribution run (`mendel run ... --tune-trials 16`) | 22:51 to 22:58 | 7 minutes; the in-loop tuning did not run (see 4) |
| Second run with `--tune-every 1` (local) and two Modal campaigns, in parallel | 22:58 to 23:09 | |
| This report, commit, pull request | 23:00 to 23:15 | |

Total: about 35 minutes. Most of the time went into waiting for runs, not into being stuck.

## What was easy

- **The solver contract.** The command line, `--iters` determinism, `genes.json` and the three-line
  `mendel.toml` are specified precisely and briefly enough to implement from PROTOCOL.md alone. A C
  solver built and ran through the harness first time. The build cache (`~/.cache/mendel/builds/<hash>`)
  and the `solvers/*/solver` entry in `.gitignore` meant I never had to think about binaries.
- **The existing packs are good templates.** `problems/autocorr3` already solves this problem's main
  difficulty (the leaderboard defines its score by a float64 computation): copy the verifier verbatim,
  say so, and put exact arithmetic into `verify.py` instead. Its `records.json` showed me what "source and
  time you read them" should look like. `solvers/noisosceles/solver.c` had a flat JSON reader and a
  seeded xoshiro I could reuse.
- **The gate is genuinely useful.** Its warning "switching kick_restart on did not change any solution in
  the smoke test; the gene may be a no-op" found a real mistake: my default `stall_limit` (2000) equalled
  `--gate-iters` (2000), so the restart branch, where two of my ideas live, was never reached. PROTOCOL.md
  warns about exactly this ("The check must run long enough to reach every branch"). I lowered the
  default to 500.
- `mendel score` worked first time and its output is clear.

## What was unclear, wrong or missing

1. **The README says a problem pack is "two files", but the work required (and every real pack) has more.**
   `verify.py` and `records.json` are not mentioned in README.md or PROTOCOL.md at all. I found the
   `verify.py` contract only by reading `mendel/campaign.py`:
   - it is run as `python verify.py CERTIFICATE.json` with the harness's interpreter, and exit code 0 means pass;
   - the certificate is `{"problem", "instance", "score", "solution", "seed", "budget_cpu_seconds", "config", "found"}`;
   - a failure turns `verified` off for that row; the stdout tail goes into `independent_check`.
   None of this is written down. Nothing says that `verify.py` must not import `evaluate.py`; the
   existing packs say it in their own docstrings.
2. **`records.json` in a pack is not read by anything.** It is a convention, and the name collides with
   `runs/<id>/records.json`, a different file that the engine and ledger *do* read (ledger.py line 5).
   When I grepped for `records.json` to learn the format, I found the wrong one first.
3. **`mendel gate solvers/flatpoly solvers/flatpoly` cannot pass.** With the same directory as OLD and
   NEW there are no new genes, and `check_registry` fails with "the proposal names no new genes". Naming
   a gene with `--genes` fails too ("already exists in the trunk"). There is no documented way to gate
   the *seed* solver's own switches. I made one OLD directory per idea (same `solver.c`, `genes.json`
   without that idea and its alleles) and gated each against the real solver. That is a real test of the
   invariance rule, and all three passed. **Suggestion:** `mendel gate --self solvers/x`, which does exactly
   this for every idea gene.
4. **The README's "tune and attribute" recipe does not tune in the loop.** With `--generations 1` and the
   default `tune_every = 2`, the generation never reaches `_analyse(g, do_tune=True)` (engine.py line 489).
   `--tune-trials 16` is used only by the decomposition's alleles-only tuning arm, in `_finish`. The event
   log shows `generation_started` and `generation_finished` in the same second, then knockouts on the
   untuned seed. README example 1 has the same flags, so it presumably has the same behaviour. I reran
   with `--tune-every 1` to compare (results below). **Suggestion:** default `tune_every` to 1 when
   `generations == 1`, or warn when `--tune-trials` will not be used.
5. **A seed whose ideas are all off gets no generality labels.** PROTOCOL.md requires switches to default
   to off. With `--k 0`, and no in-loop tuning to switch anything on, every seed idea is measured as a
   *knock-in* (the event log says `(off)`), and `_generality` runs only for knockouts of active genes
   (engine.py lines 789 and 863). So the held-out instances and `--heldout-seeds 2` are spent on scoring
   only, and `label` stays `null` for every gene. PROTOCOL.md describes labels as if every gene gets one.
6. **The decomposition can say something misleading.** It reported `tuning +0.006416, ideas -0.006416`.
   No idea was on, so the ideas contributed nothing. The champion was simply the untuned seed (because of
   4), and "ideas" is defined as champion minus tuned seed, so it absorbs the tuning gain with a minus
   sign. A reader would conclude that the ideas hurt. The unit is also hard-coded as
   `"points, mean over train instances"` (experiments.py line 279), which is wrong for a continuous
   objective like this one.
7. **`min_improvement` is undocumented.** `campaign.py` reads a top-level `min_improvement` from
   `problem.toml`, so that a tie with a published value is not announced as a record. Without it the
   margin is 1e-9 relative. For a leaderboard that requires an improvement of 1e-6 that is the
   difference between "NEW RECORD" and the truth. Only `autocorr3` mentions it, and only in a comment. It
   belongs in the PROTOCOL.md `problem.toml` example.
8. **The `gate` instances apply only to the CLI.** PROTOCOL.md says `gate` gives "small instances for the
   invariance gate (default: first two of train)". `mendel gate` uses them, but the engine's own gate
   uses `self.train[:cfg.gate_instances]` (engine.py line 607) and ignores the pack's list. My
   `gate = [{n=30},{n=70}]` therefore never affects `mendel run`.
9. **Normalisation without a best-known value is silent.** Only n = 70 has a published value. For the
   other instances `Problem.normalised` falls back to a reference of 1.0, so for `min` the normalised
   score is `1 / score`. The "mean normalised score" printed by `mendel score` (0.84) averages
   `1.2807/1.36` with `1/1.35`, two numbers that measure different things. That is harmless for ranking
   configurations, but it is not documented in PROTOCOL.md, and it makes the printed number look like a
   gap to the record when it is not.
10. **"Exact where the problem allows" needs a sentence about float leaderboards.** PROTOCOL.md says
    `evaluate` "must be exact". Here the authority is a float64 *sampled* maximum: 10^6 points of
    `linspace(0, 2 pi)`, which are the 999999-th roots of unity, divided by `sqrt(n+1)`, not `sqrt(n)`.
    An "exact" evaluator (the true supremum) would differ from the leaderboard by up to 1.2e-8 relative.
    Copying the verifier and putting the exact or rigorous work into `verify.py` is the right pattern, as
    in `autocorr3`, but it should be written down as the rule.
11. **The README is out of date.** The benchmark table lists `no5sphere`, `circle_packing` and `toy`;
    the repository also has `autocorr3`, `heilbronn` and `noisosceles`, the best templates for a new pack.
    "32+ tests" is now 46, and they take about 95 s. That is worth saying, because it is not a quick check.
12. **CPU-time budgets on a loaded machine.** PROTOCOL.md says the harness kills a run at `3 x time + 10`
    wall seconds, while `--time` is CPU seconds. At a load average of 100 on 10 cores, a 5 CPU-second run
    can approach 25 wall seconds. Nothing failed here (I used `--workers 4`), but on a shared machine the
    default of `cpu_count - 2` workers seems risky. A sentence in the README about `--workers` would help.

## Where I had to read source code to get unstuck

- `mendel/campaign.py`: what `verify.py` is called with and how its exit code is used; the certificate
  format; `min_improvement`; how `n70` on the command line becomes `{"n": 70}` (only single-letter
  integer keys work, `_parse_instance`).
- `mendel/gate.py` and `mendel/cli.py`: why `gate X X` fails, and how the gate picks instances.
- `mendel/engine.py`: why tuning did not run, why there are no generality labels, which gate instances
  the engine uses.
- `mendel/experiments.py`: what the decomposition's "ideas" term means.
- `mendel/problem.py`: the normalisation fallback.
- `mendel/solver.py`: where builds go, and whether the compiled binary lands in the solver directory (it does not).

## Problem-specific notes (for whoever extends this pack)

- The arena divides by `sqrt(len(coefficients) + 1)` = sqrt(71), not sqrt(70) as the task brief said.
  The pack generalises this literally to `sqrt(n + 1)` for the held-out sizes.
- `linspace(0, 2 pi, 10^6)` includes both endpoints, so the sample points are the 999999-th roots of
  unity. `verify.py` uses this for an FFT cross-check. Bernstein's inequality bounds the true supremum
  to within 1.2e-8 of the sampled value at n = 70, below the arena's `minImprovement` of 1e-6.
- `GET /api/solutions/best` returns `data` as a JSON object with `coefficients`; the verifier source is
  in the `verifier` field of the problem record. Both are saved under `published/`.
- 71 is prime, which is why the Fekete (Legendre-symbol) idea is in the seed.

## Results

**Evaluator agreement.** `evaluate.py` returns 1.2807274949642549 for the top arena solution (id 2475),
bit for bit the published score. For ids 599 and 891 it is 1.4e-15 relative away (float summation order).
`verify.py` (exact integer autocorrelations with a cosine sum, plus an FFT) agrees with all three to 2e-15.
Over 96 solver outputs (n = 30, 50, 70, 90; grid_mult 3 and 8) the solver's internal supremum was never
below the arena's sampled score, and at most 5e-11 relative above it.

**Attribution run, as specified** (`--generations 1 --k 0 --seeds 4 --heldout-seeds 2 --time 5
--tune-trials 16`; 7 minutes, 1643 CPU-s, 124 evaluations, no LLM). No tuning took place (see 4), so the
champion is the seed at its defaults and each switch was *knocked in*. Effects are "on minus off", with
the sign flipped so that positive means a lower score, over n = 70 and 60, from 16 runs each:

| switch | effect | 95% interval | reading |
|---|---|---|---|
| `fekete_start` | +0.0052 | [-0.0033, +0.0136] | inconclusive |
| `kick_restart` | -0.0033 | [-0.0087, +0.0013] | inconclusive |
| `lp_surrogate` | +0.0079 | [-0.0024, +0.0184] | inconclusive |

No generality labels (see 5). Decomposition: seed 1.354; "tuning +0.0064, ideas -0.0064", an artifact (see 6).

**Same run with `--tune-every 1`** (11 minutes, 2526 CPU-s). The tuner switched `lp_surrogate` on with
`lp_q = 2`, which makes the surrogate the L4 norm, i.e. the merit-factor objective. It also set
`grid_mult` 22, `tenure` 3, `tenure_rand` 18 and `stall_limit` 2542, and reported normalised
0.8399 -> 0.8477 on its confirmation seeds. Attribution on fresh seeds:

| switch | status | effect | 95% interval | label |
|---|---|---|---|---|
| `lp_surrogate` | active (knockout) | +0.0043 | [-0.0015, +0.0092] | inconclusive: harmful at n = 50 (-0.016 [-0.024, -0.008]), helpful at n = 90 (+0.034 [+0.032, +0.036]) |
| `kick_restart` | off (knock-in) | +0.0100 | [+0.0009, +0.0216] | interval above zero in this context (it was below zero, though not significantly, in the untuned one) |
| `fekete_start` | off (knock-in) | -0.0002 | [-0.0038, +0.0031] | nothing measurable |

Decomposition: tuning +0.0064, ideas -0.0096. The tuned champion did *not* beat the alleles-only tuned
seed on fresh seeds: 2 tuning seeds and 5 s runs are too few for this objective, and the champion's
n = 70 mean (1.3639) is no better than the untuned seed's (1.3636). My reading of the switches:
`fekete_start` does nothing at a 5 s budget. The best Fekete shift scores about 1.50 and the walk leaves
it at once. `kick_restart` helps only once restarts are rare enough (large `stall_limit`) for the best
sequence to be worth returning to. `lp_surrogate` depends on n.

**Modal record search** (`python -m mendel.campaign ... --instances n70 --seeds 16 --time 120
--executor modal --no-deploy --max-cpu-hours 20`). Two campaigns, about 0.53 CPU-hours and $0.03 each,
about 11 minutes of wall time each:

| config | best | mean of 16 | verified (evaluate + verify.py) | record |
|---|---|---|---|---|
| seed defaults | 1.3262193205837083 | 1.3440 | yes | no |
| `fekete_start` + `lp_surrogate` | 1.326536159970722 | 1.3333 | yes | no |

The published best, 1.2807274949642549 (read 2026-10-03T21:40:22Z), is 3.4% lower. **No record is
claimed.** The seed is a plain single-flip tabu search, and the gap is what the inventor loop is for.

Campaign usability: nothing is printed until 25 runs are back, so a 16-run campaign is silent until it
ends. The summary table's `ours` column is 5 characters wide and holds a 17-digit float. Both are minor.

## What I would change (in order of value)

1. Document `verify.py` (CLI, certificate format, independence) and `records.json` in PROTOCOL.md, and
   say "a pack is two required files plus these optional ones".
2. Add `mendel gate --self` (gate each seed idea against the solver without it), or document how to gate
   a seed solver's own switches.
3. Make a one-generation `mendel run` tune when `--tune-trials` is given, or warn that it will not.
   Run generality on knock-ins as well, or say in PROTOCOL.md that it covers only active ideas.
4. Make the decomposition say "ideas: none active" instead of the negative of the tuning gain, and take
   the unit from the problem.
5. Put `min_improvement` into the PROTOCOL.md `problem.toml` example, and say how float leaderboards
   should be handled.
6. Bring the README's benchmark table and test count up to date, and add a word on `--workers` on shared
   machines.
