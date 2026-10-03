# Usability report: adding `minoverlap` to MendelEvolve

Tester: Devin (an AI coding agent), working from a fresh clone, with README.md and PROTOCOL.md as the
starting point. Session 2026-10-03, 22:40 to about 23:35 local time. Times are wall clock as measured by
the shell, on a laptop with load average about 87 on 10 cores. An agent reads and types faster than a
person, so the time per step is less informative than where I got stuck and why.

## Summary

The core contract (solver command line, `genes.json`, `evaluate.py` with `instance_key` and `evaluate`,
the invariance rule) is clear and complete, and everything I wrote by following it worked the first
time through `mendel score`, `mendel gate` and `mendel run`. The trouble is everything around that core.
The task asked for `verify.py`, `records.json`, a CPU-time budget and a campaign, and none of these is
specified in README.md or PROTOCOL.md. I could only do them by copying `problems/autocorr3`, which the
README never mentions, and by reading `mendel/campaign.py`, `mendel/gate.py`, `mendel/engine.py` and
`mendel/cli.py`. Two of the four required commands do something other than what the task (and the
README) suggests:

* `mendel gate solvers/minoverlap solvers/minoverlap` can never pass: it fails at the registry check
  with "the proposal names no new genes", before running anything.
* `mendel run ... --generations 1` never tunes and never knocks out the seed's ideas, because
  `--tune-every` defaults to 2. With the seed's switches off, the "knockouts" are knock-ins, there is no
  generality label, and the decomposition reports a negative "ideas" share for ideas that are not in the
  champion.

## Timeline (approximate)

| step | time | notes |
|---|---|---|
| Read README.md, PROTOCOL.md, list the repo | 2 min | |
| Fetch the arena problem and top 3 solutions; run the verifier on them | 2 min | reproduced to 1 ulp straight away |
| Find a template: read `problems/autocorr3/*`, `solvers/autocorr3/*`, `mendel/problem.py`, `mendel/campaign.py`, `mendel/gate.py`, `mendel/cli.py` | 5 min | needed for verify.py, records.json and the campaign contract |
| Write problem.toml, evaluate.py, verify.py, selftest.py, records.json | 6 min | one fix: see "verify.py and the arena's float rescaling" below |
| Write the solver and genes.json; gradient check; determinism and 5 s runs by hand | 8 min | |
| `uv sync`, `uv run pytest -q` | 2 min | 46 passed in 84 s |
| `mendel score` | 15 s | worked first time |
| `mendel gate X X`: fails by design; read gate.py; build three one-idea-removed trunks and gate them | 3 min | |
| Required attribution run (`--generations 1`) | 4 min wall, 1821 CPU s | |
| Read engine.py to understand why nothing was tuned; second run with `--tune-every 1` | 9 min wall, 2835 CPU s | |
| Modal campaign (two configs, 64 runs of 300 s) | see below | |
| This report, branch, PR | 10 min | |

## What was easy

* **The solver contract (PROTOCOL.md section 2).** The command line, the meaning of `--iters`, the
  output format and the gene kinds are exact. The note that a `run` starting with `python` uses the
  harness's interpreter answered my question about numpy and scipy before I had to ask it.
* **The invariance rule** is well motivated and testable. My first gate runs on one-idea-removed trunks
  passed.
* **`mendel score`** worked first time, and its output (mean, best, runs, best known, normalised mean)
  is what you want to see.
* **`problems/autocorr3` is an excellent template**: also an EinsteinArena step-function problem, with
  the verifier copied verbatim, a written-down choice of variant, an exact rational `verify.py` and a
  `records.json` with sources and read times. Most of my pack follows its structure. It is a pity that
  only `ls problems/` leads you to it.
* **Pack loading** (`mendel/problem.py`) is forgiving and its error messages are clear.
* **Modal with `--no-deploy`**: the campaign found the deployed app, packed my new solver by content
  hash and needed no redeploy, as the README promises.

## What was unclear, wrong or missing

Ordered roughly by how much time they cost or how likely they are to mislead.

1. **`mendel gate OLD NEW` with OLD == NEW always fails.** `check_registry` requires at least one new
   gene, so gating a seed solver against itself prints
   `FAIL - new genes: (none) / [FAILED] registry: the proposal names no new genes` (exit code 1) and runs
   no solver at all. Nothing in the README or PROTOCOL.md says how to check a *seed* solver's
   invariance. I worked around it by building three trunks, each with one idea (and its alleles) removed
   from `genes.json`, and gating the real solver against each. All three passed (output in the PR).
   **Suggested change:** a `mendel check SOLVER` (or `mendel gate --seed SOLVER`) that does exactly
   this automatically. For every idea gene: remove it, gate, and also run the solver twice with the same
   seed under `--iters` to test determinism.

2. **`--generations 1` does not tune or knock out the seed's ideas.** `EngineConfig.tune_every`
   defaults to 2, and `_generation` tunes only when `g % tune_every == 0`. In a one-generation run the
   only analysis is the end-of-run `_analyse(do_tune=False)`. Since every seed switch is off by default
   (PROTOCOL.md: "default is always false"), there is nothing to knock out. The engine instead measures
   *knock-ins* (written into the `knockout` field of each gene), skips generality (it is computed only
   for active ideas) and skips the pairwise interactions. README example 1 says this configuration
   will "tune and attribute the seed solver", which it does not do. **Suggested change:** tune at the
   end of a run whose last generation was not tuned, or default `tune_every` to 1 when `k == 0`, or at
   least say in the README that `--tune-every 1` is needed.

3. **The decomposition is misleading when the champion was never tuned.** In the required run the
   champion stayed at the seed defaults, and the decomposition printed
   `seed 0.3817, tuning +0.0002869, ideas -0.0002869`: "ideas" is computed as champion minus tuned seed,
   so it is minus the tuning gain whenever the champion is untuned. A reader of the dashboard will
   conclude that the ideas hurt, but no idea was on. The decomposition should say "champion not tuned"
   or leave out the ideas share in that case.

4. **`verify.py` is a de facto part of the pack contract but is not in PROTOCOL.md.** README says a pack
   is "two files". `mendel/campaign.py` runs `python verify.py CERT.json` and treats exit code 0 as a
   pass. A certificate is `{"problem", "instance", "score", "solution", "seed", "budget_cpu_seconds",
   "config", "found"}`. I learned all of this from the source. The test brief asked for `verify.py`, as
   do the existing packs, so PROTOCOL.md should define its command line, input, exit codes and what
   "independent" means.

5. **`min_improvement` in problem.toml is undocumented.** `campaign.py` reads a top-level
   `min_improvement` to decide whether a value beats a published one. For leaderboards that require a
   margin (EinsteinArena: `minImprovement`) this matters. Without it the default margin is 1e-9
   relative, and a campaign could announce as a "NEW RECORD" a value the leaderboard would not accept. I
   found the key by reading `campaign.py` and set it to 1e-7.

6. **The engine's own record check is stricter about agreement but looser about margins than the
   campaign's.** `Engine._check_records` flags a record as soon as `problem.better(best, known)`, with
   no `min_improvement` margin and without running `verify.py`, and names certificates with
   `{best:g}` (6 significant digits, so two float records can collide). For a float objective like this
   one, a result one ulp better than the published value would show up in `state.json` as a verified
   record. I did not hit this, because the seed solver is far from the record.

7. **`records.json` means two different things.** In a problem pack (`problems/*/records.json`) it is a
   free-form record of published values with sources, a convention that no code reads. In a run
   (`runs/<id>/records.json`, see `mendel/ledger.py`) it is a list of
   `{"instance", "value", "best_known", "verified", "certificate"}` that the engine folds into
   `state.json`. The pack file has no schema anywhere; I copied the shape of autocorr3's.

8. **The README's benchmark table is out of date and does not point to the best template.** It lists
   `no5sphere`, `circle_packing` and `toy`, but the repo also has `autocorr3`, `heilbronn` and
   `noisosceles`. "Adding a problem" points to `tests/fixtures`, which has no `verify.py`,
   `records.json`, `selftest.py` or `published/` and does not show a CPU-time budget. Pointing new
   authors to `problems/autocorr3` + `solvers/autocorr3` (for continuous problems) and
   `problems/no5sphere` (for exact combinatorial ones) would have saved most of my source reading.

9. **Length-independent leaderboards have to be faked per instance.** `best_known` is keyed by
   instance, so for a problem where every n competes for the same number I repeated the same value for
   nine keys (as autocorr3 does). A `best_known_all = ...` default would be cleaner. Relatedly,
   `campaign._parse_instance("n512")` assumes a one-letter key followed by an integer. It works here, but
   it is undocumented, and a key like `n512_sym` would break it silently.

10. **The CPU-time budget is underspecified.** PROTOCOL.md says "CPU seconds measured by the solver
    itself" and "the harness kills the process at three times the time budget plus ten seconds". It does
    not say whether interpreter start-up and imports count (autocorr3 counts them; I followed), or that
    the kill is on *wall* time. On this laptop (load 87 on 10 cores) a CPU-budgeted solver can be
    killed on wall time before it uses its CPU budget. That did not happen to me, but on a shared
    machine it can.

11. **Local parallelism is not mentioned.** `LocalExecutor` defaults to `cpu_count - 2` workers (8 here).
    On a shared laptop the README should mention `--workers`. I used the defaults for the required
    commands and `--workers 6` for my extra run.

12. **Modal campaign details are only in the source.** `mendel.campaign` defaults to the 16-core lane
    `run_batch_bg_x16` (overridable through the `MENDEL_MODAL_BG_FUNCTION` environment variable).
    `--max-cpu-hours` counts the requested budget plus 2 s of overhead per job, and `--workers` is
    ignored on Modal. The campaign prints nothing until the first 16-job batch comes back (more than 5
    minutes for 300 s jobs), so the first minutes look like a hang. A "submitted N calls" line would help.

13. **The `--seeds` default differs between commands** (4 for `score`, 2 for `gate`, 8 in
    `EngineConfig`) and is not in the README. This is minor, but it means a bare `mendel gate` checks
    only 2 seeds × 2 gate instances = 4 pairs at `--iters 2000`.

## Things specific to this problem that a pack author must decide (documented in the pack)

* **The arena's float rules are the definition.** The verifier rescales to sum n/2 *in float64*, and
  only when the float sum differs from n/2. Published solution 2407 sums to exactly 256.0 in floats, but
  its exact rational sum is 256 - 6.4e-16, so exact rescaling would lift one height to 1 + 2.5e-18. My
  first exact `verify.py` therefore rejected a published, accepted solution. It now allows 1e-12 of
  slack on the post-rescaling bound and says why. Any "exact" checker for a float-defined leaderboard
  will meet this kind of thing; PROTOCOL.md's "must be exact where the problem allows" could say what to
  do when the problem itself is defined in float64. (Both autocorr3 and I kept `evaluate.py` as the
  verbatim float verifier and put the exact rational computation in `verify.py`.)
* **How to read the formula.** `1 - h(x + k)` in the statement is the complement *inside* [0, 2]
  (numpy.correlate pads with zeros), which matches Erdos's A and B = {1..2n} minus A. I wrote this into
  problem.toml so that the inventor does not optimise the wrong quantity.

## Results

### Evaluator

`evaluate.py` returns the arena's numbers for the three published top solutions to within one ulp
(largest relative difference 2.9e-16), and `verify.py` computes exact rationals that round to the same
doubles (`uv run python problems/minoverlap/selftest.py`, 0 failures).

### Attribution: the required run (`--generations 1`, default `--tune-every 2`)

No tuning took place, so these are knock-ins (idea switched on minus off, in the untuned default
context). They come from 2 training instances × 4 seeds, 5 CPU seconds per run; positive means better:

| idea | effect | 95% CI |
|---|---|---|
| symmetric | +1.30e-4 | [+6.9e-5, +1.9e-4] |
| coarse_to_fine | +1.02e-4 | [+7.4e-5, +1.27e-4] |
| lp_polish | +1.20e-4 | [+1.05e-4, +1.31e-4] |

All three help on their own at the default constants. There were no generality labels or interactions
(see item 2), and the decomposition's negative "ideas" share is the artifact in item 3.

### Attribution: the same run with `--tune-every 1` (my addition)

Optuna (16 trials) switched on `symmetric` and `coarse_to_fine` and retuned every constant (for example
`coarse_factor` 4 -> 30, `beta0` 50 -> 231, `init_noise` 0.3 -> 0.022). Knockouts in that champion, on
seeds the tuner never saw:

| idea | in champion | effect | 95% CI | label |
|---|---|---|---|---|
| symmetric | on | +1.65e-4 | [+5.4e-5, +2.5e-4] | general (held out: n384 +1.62e-4, n1024 +2.54e-4) |
| coarse_to_fine | on | +2.54e-4 | [+1.3e-4, +3.7e-4] | specific (held out: n384 -8.9e-5, n1024 +1.8e-4 with a CI that spans 0) |
| lp_polish | off | -1.47e-4 (knock-in) | [-2.1e-4, -7.6e-5] | - |

Synergy coarse_to_fine × symmetric: +1.4e-5, CI [-1.25e-4, +1.45e-4], inconclusive. Decomposition:
seed 0.38174, tuning +2.06e-4, ideas +8.6e-5. My predictions were partly wrong. `symmetric` helps at
5 s and generalises. `coarse_to_fine` helps on the training sizes but hurts at n = 384. I did not
find out why: the tuned `coarse_factor` = 30 gives coarse grids of 8, 17, 12 and 34 steps at n = 256,
512, 384 and 1024, and the 12-step grid at n = 384 is an exact repetition, so it is not a resampling
artifact. This is the kind of result the generality test exists for. `lp_polish` helps in the untuned
context but hurts once the descent is tuned. My guess is that each LP takes too much of a 5 s budget;
I did not measure that.

### Modal campaign

CAMPAIGN_RESULTS_PLACEHOLDER

## What I would change, in order

1. Add a seed-solver check command (determinism, plus invariance of each idea against a trunk without
   it), and make `mendel gate X X` say what to run instead.
2. Make a one-generation run tune and knock out (or document `--tune-every 1`), and fix the
   decomposition when the champion is untuned.
3. Promote `verify.py`, the certificate format, `min_improvement` and the pack's `records.json` /
   `published/` / `selftest.py` conventions into PROTOCOL.md section 1, with a short schema for each.
4. Update the README's benchmark table and point "Adding a problem" at `problems/autocorr3` as the
   template for float-scored leaderboard problems.
5. Give `Engine._check_records` the same margin and independent check as `mendel.campaign`.
6. Say in PROTOCOL.md that the harness kill is on wall time, and in the README how to limit local
   workers.
