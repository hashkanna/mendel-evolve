# Usability report: adding `distratio` to MendelEvolve

Tester: Devin (an AI coding agent) working from a fresh clone, with README.md and PROTOCOL.md as the
starting point. Machine: shared macOS arm64 laptop, load average 40-100 on 10 cores during the test.
Wall-clock times below are from the shell's `date`.

## Summary

Adding a benchmark is quick. The two-file problem pack and the solver command line are clearly
specified, and copying an existing pack gets you most of the way. The time went on things the docs
do not mention: `verify.py` and `records.json` (which the brief asked for, and which the campaign
runner uses) are not part of the documented contract; `min_improvement` in `problem.toml` is read
by the campaign but documented nowhere; and two of the commands in the brief do not do what their
flags suggest (`mendel gate X X` always fails, and `--tune-trials` with `--generations 1` never
tunes the ideas). I also found one framework issue that matters for honesty: the engine announces a
"record" that the leaderboard would not accept (details below).

## Timeline (approximate)

| step | start | took |
|---|---|---|
| Read README.md and PROTOCOL.md, list the packs | 22:40 | 3 min |
| Fetch the arena problem and top solutions; confirm the verifier reproduces the scores | 22:40 | 2 min (in parallel with reading) |
| Read the autocorr3 and heilbronn packs, `mendel/campaign.py`, `cli.py`, `gate.py`, `worker.py`, `problem.py`, `genes.py` | 22:41 | 5 min |
| Find the 3D value: the AlphaEvolve problem page is JavaScript-only, so it took the GitHub API, then the AlphaEvolve results notebook | 22:41 | 3 min |
| Write `evaluate.py`, `verify.py`, `problem.toml`; check them on 5 published configurations and 17 malformed inputs | 22:43 | 4 min |
| `uv sync` and `uv run pytest -q` (46 passed in 131 s on the loaded machine) | 22:41 | in the background |
| Write the solver and `genes.json`; smoke test determinism and every switch | 22:45 | 4 min |
| Re-choose the training instances after finding n = 16 saturates in about a second | 22:47 | 2 min |
| `mendel score`, `mendel gate` (fails by design), per-gene gates | 22:48 | 3 min |
| Attribution run (most of this went on reading `engine.py` to understand the output) | 22:49 | 8.5 min |
| Modal campaign (optional), launched while the run was going | 22:53 | see the end of this file |
| This report and the PR, written alongside the run | 22:52 | about 12 min |

From the first command to a complete pack, solver and evidence took about 20 minutes. The
documentation got me to a working pack and solver; reading source code took about a third of the
time, all of it on the points below.

## What was easy

- **The solver contract.** The command line in PROTOCOL.md section 2 is exact and complete: flags,
  `CFG.json` (all genes present), CPU-time budget, determinism under `--iters`, output shape, and the
  hard timeout. My solver worked the first time it ran under the harness.
- **`genes.json`.** The table of gene kinds and the example are enough. The `of` field (an allele that
  only matters when its idea is on) is well thought out, and `mendel.genes.validate_genes` gives
  clear errors.
- **Existing packs as templates.** `problems/autocorr3` is an almost perfect template for an
  EinsteinArena problem: a float verifier copied word for word, an exact rational re-check in
  `verify.py`, and a `records.json` with the read time, `min_improvement` and an
  `evaluator_agreement` section. I copied its structure.
- **`python` in `run` is replaced by the harness's interpreter**, so numpy and scipy are just there,
  locally and on Modal (the image installs both, `mendel/backends/modal_app.py`).
- **`mendel score`** worked first time and its output is easy to read.

## Unclear, wrong or missing in README.md / PROTOCOL.md

1. **`verify.py` and `records.json` are not in the contract.** PROTOCOL.md section 1 says a pack is
   `problem.toml` and `evaluate.py`; README says "A problem pack is two files". But all five shipped
   packs have a `verify.py`, four of them a `records.json`, and `mendel/campaign.py` runs
   `problems/<name>/verify.py <certificate>` and requires exit code 0 before it counts a result as
   verified. I had to read `campaign.py` to learn the interface: one argument (a certificate path),
   exit 0 for pass, and the certificate format (`{"problem", "instance", "score", "solution", "seed",
   "budget_cpu_seconds", "config", "found"}`). `records.json` has no schema at all and nothing in
   `mendel/` reads it (the `runs/<id>/records.json` in `ledger.py` is a different file with the same
   name, which confused me for a minute). Suggestion: a section 1b "Optional files" in PROTOCOL.md
   covering `verify.py` (interface, the certificate format, "must share no code with evaluate.py"),
   `records.json` (a suggested schema: source URL, read time, top entries, evaluator agreement) and
   `selftest.py` (heilbronn, no5sphere and noisosceles have one; it is unclear who runs it).
2. **`min_improvement` is undocumented.** `campaign.py` reads a top-level `min_improvement` from
   `problem.toml` to decide whether a result is a record. I found it only because autocorr3's
   `records.json` mentions it. It belongs in the `problem.toml` example in PROTOCOL.md. (It is also
   global, not per instance: a pack with several leaderboards cannot give each its own threshold.)
3. **The engine ignores `min_improvement` and `verify.py` when it announces records.**
   `Engine._check_records` (`mendel/engine.py`) counts any score strictly better than `best_known` as
   a record, checks it only with `evaluate.py`, and prints it with `:g`. In my run it logged
   `record: n16: 12.8892 beats the best known 12.8892`, and the dashboard will show it as a new record.
   The value, 12.889229907694, is 2.3e-11 below the arena's best, which is 4000 times smaller than
   the arena's minimum improvement of 1e-7: it is the same optimum, polished to more digits, not a
   record. The campaign runner does this correctly (`beats_published`, plus `verify.py`). Suggestion:
   share one record test between the two, and print values with `repr`, not `:g`. I did not change
   `mendel/`.
   **The two certificate formats also differ.** The campaign writes `{"instance", "score",
   "solution", ...}`; the engine writes `{"instance", "value", "best_known", "solution", ...}`. My
   first `verify.py`, written to match `campaign.py`, rejected the engine's certificate ("score must
   be a finite float"). It now accepts either key. With that change it passes the engine's n16
   certificate: exact value 12.889229907694023, so the solution is valid; it just is not a record.
4. **`mendel gate solvers/distratio solvers/distratio` always fails.** The gate compares an old solver
   with a new one and infers the new genes from the difference. With the same directory twice there
   are none, and `check_registry` rejects that with "the proposal names no new genes"; with `--genes`
   it says the gene "already exists in the trunk". So the brief's command fails for every solver
   (output in the PR). There is no documented way to check a *seed* solver's own switches. What I did
   instead: for each seed switch, a copy of the solver whose `genes.json` lacks that switch and its
   alleles, then `mendel gate <copy> solvers/distratio --genes <switch>,<alleles> --iters 60`. All
   three pass (invariance on 4 paired runs, smoke test valid). That only works because my solver
   falls back to its built-in defaults for missing config keys. Suggestion: a `mendel check
   <solver>` that validates `genes.json`, runs every switch on and off on the gate instances, checks
   determinism under `--iters` (two identical runs) and validity, and checks that the output is valid
   at `--iters 0`.
5. **`--tune-trials` with `--generations 1` does not tune the ideas.** `tune_every` defaults to 2, and
   tuning runs only in generations where `g % tune_every == 0`, so with `--generations 1` the
   Optuna search over switches never runs. `--tune-trials` is used only by the decomposition step,
   which tunes the seed solver's *alleles* with every idea off (here effectively only
   `slsqp_maxiter`, because the other alleles belong to ideas that are off). The champion stays at
   the defaults, so the "knockouts" are really knock-ins of ideas that are off. The README's first
   example ("tune and attribute the seed solver of the toy problem") has the same flags and the same
   behaviour. I only found this by reading `engine.py`. Suggestion: `--tune-every 1` in the README
   example, or tune in the last generation whatever `tune_every` says.
6. **The CPU-time budget versus the wall-clock kill.** PROTOCOL.md says the harness kills a solver at
   "three times the time budget plus ten seconds". On this shared laptop (load 100 on 10 cores) a
   5 CPU-second run can take more than 25 wall seconds. `MENDEL_WALL_FACTOR` exists for exactly this,
   but it is mentioned only in a comment in `mendel/worker.py`. It should be in PROTOCOL.md next to
   the timeout rule. I ran the attribution run with `MENDEL_WALL_FACTOR=6` to be safe.
7. **Instance keys and the campaign.** `mendel/campaign.py` turns `--instances n17` into `{"n": 17}`
   (the first letter becomes the parameter name). Any pack whose instances have more than one
   parameter must be given JSON on the command line (`'{"n": 14, "d": 3}'`). That is in the
   `--help` text but not in the README. I made `d` default to 2 in my evaluator so that `n16` works.
8. **Choosing instances.** Nothing says that training instances must be hard enough at the run's
   budget for knockouts to show anything. My first choice (n = 16 and the 3D n = 14, the two
   instances of the AlphaEvolve paper) saturates within about one CPU second, so every idea would
   have been "neutral" at `--time 5`. I moved the 3D instance to the held-out set and trained on n = 16
   and n = 30. A sentence in "Adding a problem" would save someone a wasted run.
9. **Small things.** README says "32+ tests"; there are 46. The `[best_known]` table is
   floats only (`problem.py` calls `float(v)`), so truncated published values like Friedman's
   "26.879+" can only be entered as 26.879; there is no way to mark a reference as a bound rather
   than a value, which matters for the engine's record check. PROTOCOL.md does not say how
   `instance_key` must relate to the `[best_known]` keys (it must produce exactly those strings).
   PROTOCOL.md says the time budget is "CPU seconds measured by the solver itself", but not that a
   numpy/scipy solver should pin BLAS to one thread: otherwise `process_time()` counts every BLAS
   thread, and results can depend on thread scheduling. My solver sets `OMP_NUM_THREADS` and similar
   to 1 before importing numpy.

## Where I had to read source code

- `mendel/campaign.py`: the `verify.py` interface, the certificate format, `min_improvement`, and
  the `"n17"` instance parsing.
- `mendel/gate.py`: why `gate X X` fails, and how to gate seed switches instead.
- `mendel/engine.py`: `tune_every`, what `--tune-trials` does with one generation, and
  `_check_records`.
- `mendel/worker.py`: `MENDEL_WALL_FACTOR`; whether `python` resolves to the venv.
- `mendel/problem.py`: that `best_known` values must be floats and that keys come from
  `instance_key`.
- `mendel/backends/modal_app.py`: whether numpy and scipy are available in containers.

## The problem itself

- The arena's verifier is a float64 computation (numpy, sqrt, then the ratio squared), so I made
  `evaluate.py` return exactly that number, as autocorr3 does, and added the exact rational value
  max d^2 / min d^2 as a cross-check (they must agree to 1e-12 relative). The exact value of the
  arena's top solution is 12.889229907717516; the arena shows 12.889229907717521 (5e-15 apart).
  `verify.py` recomputes the exact value on scaled integers and, separately, with `scipy`'s `pdist`.
- The arena hard-codes 16 points in 2D. I generalised the shape check to (n, d) and left the rest of
  the arena's code unchanged, so the same evaluator scores the 3D instance and the held-out sizes.
- The 3D n = 14 value was harder to source than it should have been: the AlphaEvolve problem page is
  JavaScript-only with no number, the paper is not on the arena, and the number (4.165849767) is in
  the AlphaEvolve results notebook. Friedman's page lists a newer "4.165+" (Sun and Samanta, June
  2026) with only three decimals, so I cannot tell whether our 4.16578347 beats it, and I do not
  claim it does.

## What I would change

1. Document `verify.py`, `records.json`, `selftest.py` and `min_improvement` in PROTOCOL.md.
2. One record rule shared by the engine and the campaign: `min_improvement`, `verify.py`, and
   printing with full precision.
3. A `mendel check <solver>` for seed solvers (see 4 above), and make `mendel gate X X` say what it
   is for instead of failing.
4. Make one-generation runs tune, or say clearly that they do not.
5. Put `MENDEL_WALL_FACTOR` in PROTOCOL.md.
6. In "Adding a problem", say that training instances should not be solved to the best known
   value within the run's budget.

## What the attribution run said

`uv run mendel run --solver solvers/distratio --problem problems/distratio --run-id distratio-devin
--generations 1 --k 0 --seeds 4 --heldout-seeds 2 --time 5 --tune-trials 16 --workers 4`, with
`MENDEL_WALL_FACTOR=6`. I added `--workers 4` and the environment variable to go easy on the shared
laptop. It took 8.5 min wall, 1981 CPU-seconds, 124 evaluations, no LLM calls.

All three seed switches are off at their defaults and nothing was tuned (point 5), so the champion
is the seed configuration and the run measured knock-ins (idea on minus idea off). Positive means
better (a lower ratio). The effect is pooled over n16 and n30 at 5 CPU s, 4 paired seeds:

| switch | effect (on - off) | 95% interval | reading |
|---|---|---|---|
| `lattice_init` | +0.091 | [-0.002, +0.244] | probably helps, inconclusive |
| `smooth_presolve` | +0.082 | [-0.008, +0.226] | probably helps, inconclusive |
| `basin_hop` | -0.216 | [-0.877, +0.232] | noisy; leans harmful at this budget |

All three intervals include zero. n16 contributes nothing to any effect (every arm reaches
12.88922990769 within the budget), so the effects come from n30 and are about twice as large there.
That matches what I saw by hand at n = 30, 5 CPU s, seed 1: baseline 27.74, `lattice_init` 26.89,
`smooth_presolve` 26.879, `basin_hop` 26.88.

What the run did **not** produce, and why (from `engine.py`):
- **No generality labels and no pairwise interactions.** `_pairwise` and `_generality` take only the
  knockouts of ideas that are *on* in the champion; knock-ins of ideas that are off are left out.
  With an all-off seed and no tuning, both steps are skipped without a word. The held-out instances
  were only scored (n28 mean 25.414, d3n14 mean 4.16793, best 4.16578347). The README's promise of a
  "per-idea test of whether it generalises" therefore does not apply to seed switches in this
  setting, and no message says so.
- **Decomposition: seed 19.99, tuning -0, ideas -0.** The alleles-only tuning found nothing better
  than `slsqp_maxiter = 150`, and the champion is the seed. ("-0" is a signed zero being printed.)
- **A false record.** `record: n16: 12.8892 beats the best known 12.8892`, with the certificate
  `certificates/n16_12.8892.json` and `"verified": true` in `state.json`. See point 3: this is not a
  record by the arena's own rule (minImprovement 1e-7), and `verify.py` was never run on it. The
  certificate file name uses `:g` as well, so two different values that both print as 12.8892 would
  overwrite each other.

To get real knockouts and generality labels for these seed switches, the next run should use
`--tune-every 1` (so the switches can be turned on in the champion) and more seeds; given the
interval widths, 12 or more seeds at 5-10 CPU s.
