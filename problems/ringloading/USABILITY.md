# Usability report: adding `ringloading` to MendelEvolve

Tester: Devin (AI agent), working from a fresh clone, with README.md and PROTOCOL.md as the starting point.
Date: 2026-10-03. Wall clock: about 22:40 to 23:25 BST (about 45 minutes, of which about 25 were spent
waiting for runs). The laptop was shared and heavily
loaded (load average around 32 on 10 cores), so every local command ran with `--workers 2`.

## Summary

Adding a problem works, and the contract in PROTOCOL.md is mostly accurate. The parts it covers
(problem.toml, evaluate.py, the solver command line, genes.json, the invariance rule) were enough to write a pack
and a C solver that the framework accepted on the first try: `score`, the gate, `run` and the Modal campaign
all worked without changes. The problems are in what the documents leave out. Three things the brief asks
for (`verify.py`, `records.json`, a record campaign) are not in PROTOCOL.md at all. Two of the commands
in the brief do not do what they appear to do: `mendel gate S S` always fails, and `mendel run --generations 1
--tune-trials 16` never tunes. In each case I only found out by reading the source.

## Timeline (approximate)

| step | time | notes |
|---|---|---|
| Read README, PROTOCOL, arena verifier and top solutions | 22:40-22:41 | quick; both docs are short and clear |
| Look at existing packs and campaign.py to see what a "complete" pack is | 22:41-22:42 | needed because PROTOCOL.md describes only 2 of the 4 files the brief asks for |
| evaluate.py, verify.py; reproduce the arena scores | 22:42-22:44 | all three top solutions bit for bit on the first run |
| problem.toml, records.json | 22:44-22:45 | hit the `min_improvement` TOML placement trap (below) |
| C solver: first version, determinism and validity checks | 22:45-22:46 | the protocol is easy to implement in C |
| Solver experiments (score stuck at exactly 1.0), add the ascent move | 22:46-22:55 | problem difficulty, not framework; interleaved with the next two rows |
| `uv sync`, `pytest` | 22:48-22:50 | 46 passed in 85 s |
| `mendel score`, `mendel gate` (both forms) | 22:50-22:55 | self-gate fails by design; built a trunk copy to get a meaningful gate |
| `mendel run` (the command in the brief) | 22:55-23:08 | 12 min wall, 1450 CPU-s, 8.5 min of it in the decomposition's own tuner |
| Reading engine.py to understand why no tuning happened | 23:00-23:05 | |
| Modal campaign | 23:08-23:11 | 32 x 60 s, 2 min wall, about $0.03 |
| Extra run with `--tune-every 1` | 23:08-23:19 | to get the tuning and knockouts the brief's command never runs |
| This report, commit, PR | 23:11-23:25 | |

## What was easy

- **The solver contract.** The command line, `--time` as self-measured CPU seconds, `--iters`
  determinism, the `OUT.json` shape and `mendel.toml` with a `build` line are clear, and they are enough. A C solver
  with its own JSON scanning worked with the harness first time, both locally and on Modal (the container
  compiled it without any configuration).
- **Gene semantics.** The kinds, `of`, "switch default is always false" and the invariance rule are clearly
  stated. The gate's failure messages say exactly what was compared.
- **The evaluator contract.** The two functions and "never raise" were enough. `mendel/problem.py` also
  guards against an evaluator that raises, which is a good second line.
- **Existing packs as templates.** `problems/autocorr3` was the most useful single reference, more than the
  toy fixture the README points to. It has the same shape of task (one arena leaderboard, the arena verifier
  verbatim, an exact second checker, records.json with read times), and its comments explain why it is
  built the way it is.
- **Modal campaign.** `python -m mendel.campaign ... --executor modal --no-deploy --max-cpu-hours 20` worked as
  is. It re-checked the result with evaluate.py and with my verify.py and wrote a certificate. It correctly
  did not call 1.0911 a record against 1.125.

## What was unclear, wrong or missing

Ordered by how much time it cost or how likely it is to mislead the next person.

1. **`mendel gate solvers/X solvers/X` always fails.** The brief (and the obvious reading of "gate") suggests
   gating a seed solver against itself as a smoke test. The gate's first check is "the proposal adds exactly one
   idea gene", so with OLD == NEW it prints `FAIL - [FAILED] registry: the proposal names no new genes` and
   exits 1. `--genes NAME` does not help either: the name is then "already in the trunk". Neither README nor
   PROTOCOL says what the gate expects as OLD and NEW for a brand-new solver. The meaningful check needed a
   hand-made trunk copy without one gene (here: without `refine_grid` and `refine_max`), and that passed.
   *Suggested change:* a `mendel check SOLVER` command (or `gate` with one argument) that runs the
   seed-solver checks: build, `--iters` determinism (same solution twice), valid output on the gate and train
   instances, every gene in genes.json present in CFG.json, smoke runs with each idea on. That is what I
   wrote by hand in a throwaway script.

2. **`mendel run --generations 1 --tune-trials 16` never runs the tuner.** `EngineConfig.tune_every`
   defaults to 2 (engine.py, line 85). Generation 1 is therefore not a tuning generation, and `_finish()`
   calls `_analyse(last, do_tune=False)`. So `--tune-trials 16` is silently ignored, apart from the
   decomposition, which runs its own alleles-only tuner. README's run example 1 says "tune and attribute
   the seed solver" with exactly these flags. On my run the events show no `tuned` event, and the champion
   stays at the defaults. *Suggested change:* tune at the final analysis when no generation has tuned yet, or
   default `tune_every` to 1. At the least, warn when `--tune-trials` is given but no generation will tune.
   I had to add `--tune-every 1` to get a tuned champion (second run below).

3. **The decomposition's output is misleading when the champion is untuned.** The brief's run reports
   `seed 1, tuning +0.04647, ideas -0.04647`. No idea is on in the champion, so "ideas -0.046" is not a
   measured harm of any idea. It is the difference between the untuned champion and the separately tuned seed.
   A reader of the dashboard would conclude that the ideas hurt. The decomposition also took about 8.5 of the
   12 minutes. *Suggested change:* when the champion equals the seed configuration, report "ideas: none
   active" and do not attribute the residual to ideas.

4. **No generality labels, no pairwise interactions for ideas that are off.** Knockouts of ideas that are off
   are run as knock-ins (that is documented in a docstring, not in PROTOCOL.md). But `_generality` and
   `_pairwise` only consider the champion's active ideas, so in a run where nothing is merged the brief's
   `--heldout-seeds 2` has no effect on any gene: `label` stays null. PROTOCOL.md's field notes describe
   `label` as if every gene gets one. *Suggested change:* say in PROTOCOL.md section 3 which steps apply to
   active ideas only, or run generality on knock-ins as well.

5. **PROTOCOL.md says a pack is two files. In practice it is four.** `verify.py` is read by `mendel.campaign`,
   which runs `python verify.py CERT.json` and treats exit code 0 as a pass. Its command line, the
   certificate format (`{"problem", "instance", "score", "solution", "seed", "budget_cpu_seconds",
   "config", "found"}`) and the exit-code convention are documented only in campaign.py's source and
   docstring. `records.json` in a pack is read by no code at all. (`mendel/ledger.py` reads
   `runs/<id>/records.json`, an unrelated file with the same name, which confused me briefly.) Its schema
   exists only by example (autocorr3, heilbronn and noisosceles do not even agree on the layout). *Suggested change:* a
   section "1b. Optional files" in PROTOCOL.md covering `verify.py` (CLI, certificate schema, exit code),
   `records.json` (suggested schema: source URL, read time, top values, evaluator agreement) and
   `published/`.

6. **`min_improvement` is undocumented, and TOML makes it easy to misplace.** `mendel.campaign` reads a
   top-level `min_improvement` from problem.toml. If it is absent, the margin is 1e-9 times the known value.
   PROTOCOL.md does not mention the key. My first draft put it at the end of the file, after `[best_known]`.
   TOML then makes it `best_known.min_improvement`, which `load_problem` would have accepted as the best-known
   value of an instance called `min_improvement`. The campaign would also have silently used the default
   margin. Nothing warns about either. *Suggested change:* document the key in PROTOCOL.md's problem.toml
   example, *above* `[instances]`, and have `load_problem` reject `best_known` keys that are not instance
   keys of any split.

7. **Instance keys must have a single-letter prefix for the campaign.** `mendel.campaign._parse_instance`
   turns `"m15"` into `{"m": 15}` by taking the first character as the parameter name. That works for this
   pack by luck. A pack with `instance_key` returning `"size15"` or `"n15k3"` would need the JSON form on
   the command line, and nothing says so. *Suggested change:* parse keys by matching them against
   `instance_key` of the pack's listed instances, or document the convention.

8. **Problems with a single official instance.** The arena problem is m = 15 only, but the engine needs
   training *and* held-out instances. PROTOCOL.md does not say what to do when the benchmark has a single
   size. I chose train m = 15, 14 and held-out m = 13, 16, 17, and left `best_known` empty for the sizes
   without a published value. `Problem.normalised` then uses 1.0 as the reference, which is documented only in
   a docstring. The "mean normalised score" printed by `mendel score` mixes 1.0/1.125 with 1.0/1.0, which is
   hard to read. A sentence in PROTOCOL.md on single-instance benchmarks, and on what normalisation does
   without `best_known`, would help.

9. **Default parallelism is not mentioned.** `LocalExecutor` uses `cpu_count - 2` workers by default (8 here).
   README does not say that `score`, `gate` and `run` accept `--workers`. On a shared machine this matters.

10. **Smaller points.**
    - README says "32+ tests". There are 46, all of which passed.
    - PROTOCOL.md does not say whether extra keys under `stats` are allowed. I added `score`, `exact`, `grid`
      and `cpu_seconds`. Nothing complained, and the gate compares only `solution`, but it would be good to
      state this.
    - The gate warning "switching refine_grid on did not change any solution in the smoke test; the gene may
      be a no-op" appears for any idea that only acts after the gate's default 2000 iterations (refine_grid
      first acts at the end of a 5000-iteration cycle). PROTOCOL.md does mention `--gate-iters` for this, which
      is good. The warning could say "or the gate run is too short for it to act".
    - The campaign's summary table pads `ours` to 5 characters, so a float value misaligns the columns.
    - `mendel score` prints `best known None` for instances without a value. A dash would read better.

## Where I had to read source code

- `mendel/gate.py` (`check_registry`): to understand why the self-gate fails and how to get a meaningful one.
- `mendel/engine.py` (`_generation`, `_analyse`, `_finish`, `_decomposition`): to understand why no tuning
  happened, why the decomposition blamed ideas, and why no gene got a generality label.
- `mendel/campaign.py`: for the `verify.py` contract, the certificate format, `min_improvement`, the instance
  key parsing, and the Modal function used (`run_batch_bg_x16`).
- `mendel/problem.py`: what happens to instances without `best_known`.
- `mendel/executor.py`: the default number of workers.
- `mendel/backends/modal_app.py`: to confirm that the container has a C compiler (`apt_install("gcc")`), since
  the README does not say so for non-Python solvers on Modal.

## What I would change, in priority order

1. Add `mendel check SOLVER`: a seed-solver self-test, so that `gate` is not misused for this.
2. Make `--generations 1 --tune-trials N` tune, or warn loudly that it will not.
3. Do not attribute the decomposition residual to ideas when none is active.
4. Document `verify.py`, the certificate schema, `records.json` and `min_improvement` in PROTOCOL.md; validate
   `best_known` keys against the instance keys.
5. Say in PROTOCOL.md which attribution steps apply to active ideas only.
6. Mention `--workers` in the README.

## Results, for reference

- Evaluator: reproduces the three top arena scores bit for bit (1.125 = 9/8, 1.1249999999999991,
  1.1249999999999858). It agrees with the arena's brute force (verify.py) on 300 random instances with m = 1..9.
- Seed solver at defaults, 5 CPU-s: exactly 1.0 on m = 15 in every run. The plateau at A = 1 is a strong
  attractor.
- Knock-ins in the brief's run (4 seeds, train m = 15 and m = 14, 5 CPU-s each, ideas off in the champion):
  `tiebreak_critical` +0.0313 [+0.0208, +0.0417] (clearly positive); `ascent_moves` +0.0104 [0, +0.0208];
  `refine_grid` +0.0130 [0, +0.0286] (both lower bounds exactly 0: suggestive, not significant).
- Tuned run (`--tune-every 1`, otherwise the same flags; 11 min wall, 1306 CPU-s). The tuner switched
  `ascent_moves` on and moved to `grid_den` 104, `step_max` 1, `t0` 0.0073, `cycle` 106345, `kick` 4 and
  `ascent_prob` 0.019. On its two selection seeds this raised the normalised score from 0.9549 to 0.9907, and
  the m = 15 mean went from 1.0 to 1.034 (best 1.0865). On fresh attribution seeds:
  - `ascent_moves` (now on), knockout: -0.0144 [-0.0313, +0.0024]. Inconclusive and leaning negative on the
    training sizes, even though the tuner had chosen it: the selection bias that the README warns about,
    measured. On held-out sizes it was +0.005 (m13), +0.019 (m16) and +0.029 (m17), labelled `inconclusive`.
  - `tiebreak_critical` (off), knock-in: -0.0108 [-0.0300, +0.0060]. It was clearly positive at the default
    constants and is not in the tuned context, so the effect depends on context.
  - `refine_grid` (off), knock-in: -0.0291 [-0.0496, -0.0084]. Harmful in the tuned context, which is plausible:
    with `grid_den` 104 already fine, doubling it only dilutes the search.
  - Decomposition: seed 1.0, tuning +0.0475, ideas -0.0127. The tuning gain is real. The idea number is
    the same mixture of selection noise and context described in point 3.
- Modal campaign, all three ideas on, m = 15, 32 x 60 CPU-s: best 419/384 = 1.0911458, mean 1.018, passed
  evaluate.py and verify.py. That is below the published 9/8 = 1.125, so it is not a record and not claimed as one.
