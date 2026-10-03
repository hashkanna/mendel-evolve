# OpenEvolve baseline: circle packing, n = 26

The head-to-head for Mendel's circle-packing run. OpenEvolve evolves whole programs with an LLM;
Mendel adds named ideas to one solver and measures each. Both start from the same program
(OpenEvolve's `initial_program.py`; Mendel's seed solver is a port of it) and both are scored by
the same strict evaluator, `problems/circle_packing/evaluate.py`.

The baseline is OpenEvolve's **own two-phase recipe** for this example, with every prompt hint it
ships, on `claude-haiku-4-5`.

## Commands

All from the project root. Steps 2 and 3 are the ones behind `results/two_phase_haiku.csv`.

```bash
# 1. Set up (once): clone OpenEvolve at the pinned commit into baselines/openevolve/vendor/
#    (git-ignored) and install it into its own virtual environment. No API calls.
bash baselines/openevolve/setup.sh

# 2. Run the two-phase recipe, one command per seed. PAID: one claude-haiku-4-5 request per
#    iteration, 100 + 100 iterations. Reads ANTHROPIC_API_KEY from .env. The three seeds can run
#    at the same time; they share the cap because they share the group directory.
for seed in 1 2 3; do
  uv run python baselines/openevolve/run_openevolve.py --recipe two-phase --seed $seed \
      --parallel-evaluations 2 --cap-usd 15 &
done; wait
#    -> baselines/openevolve/runs/two_phase_haiku/seed<S>/
#         phase1/, phase2/    config.yaml, console.log and openevolve_output/ of each phase;
#                             openevolve_output/checkpoints/checkpoint_<i>/best_program.py is the
#                             best program after iteration i
#         usage.json          billed requests, tokens and dollars per phase and cumulative
#         manifest.json       OpenEvolve commit, seed, every config change, wall-clock per phase
#         watch.log           spend, lost iterations and machine load, every 10 seconds
#       baselines/openevolve/runs/two_phase_haiku/STOP   only if the runs were stopped (with the reason)

# 3. Re-score every best-so-far program with the strict evaluator and summarise. No API calls.
uv run python baselines/openevolve/two_phase_results.py
#    -> baselines/openevolve/results/two_phase_haiku.csv            one row per seed, phase, checkpoint
#       baselines/openevolve/results/two_phase_haiku_summary.json   per seed and over seeds
```

Other entry points:

```bash
# One phase only, with config.yaml of this directory (phase 1 prompt, 100 iterations), and its re-score.
uv run python baselines/openevolve/run_openevolve.py --iterations 100 --seed 1
uv run python baselines/openevolve/rescore.py baselines/openevolve/runs/iter100_seed1

# The account's rate limits, from one 5-token request (about $0.00004).
baselines/openevolve/vendor/venv/bin/python baselines/openevolve/probe_limits.py

# The plumbing without spending anything: a local stub in place of the model. (Not on port 8765,
# which is the Mendel dashboard's; stop the stub by its process id, never by port.)
baselines/openevolve/vendor/venv/bin/python baselines/openevolve/fake_llm_server.py --port 8791 & STUB=$!
uv run python baselines/openevolve/run_openevolve.py --recipe two-phase --seed 1 --iterations 4 \
    --api-base http://127.0.0.1:8791/v1 --group /tmp/oe-stub
uv run python baselines/openevolve/two_phase_results.py --group /tmp/oe-stub --out /tmp/oe-stub/results.csv
kill $STUB

# Continue runs that the cap stopped, with a new cap (remove the STOP file first). The cap counts
# everything the group has logged, before and after; the configs of the first leg are kept.
rm baselines/openevolve/runs/two_phase_haiku/STOP
for seed in 1 2 3; do
  uv run python baselines/openevolve/run_openevolve.py --recipe two-phase --seed $seed --resume --cap-usd 22 &
done; wait
uv run python baselines/openevolve/two_phase_results.py
```

Options of `run_openevolve.py`: `--iterations N` (per phase), `--group DIR` or `--out DIR` (a run
directory is never overwritten), `--checkpoint-interval K`, `--parallel-evaluations W`,
`--cap-usd X --cap-margin M`, `--max-llm-failures K`, `--resume` (each unfinished phase continues
from its last saved checkpoint, with OpenEvolve's `--checkpoint`, for the iterations it still
lacks; `--cap-usd` then counts everything the group has spent, before and after), `--dry-run`
(write the configs, print the commands, call nothing). With `--api-base` set to anything but the Anthropic endpoint, `.env` is
not loaded and a dummy key is used, so the real key is never sent anywhere else.

## The run of 2026-10-03 (`results/two_phase_haiku.csv`)

Seeds 1, 2 and 3 ran at the same time under a shared cap of $15. Phase 1 finished on every seed
(100 iterations each). **The cap stopped all three during phase 2**, after 37, 59 and 61 of its
100 iterations, at $14.43 of logged spend. `--resume` continues them (see Commands).

| seed | best repaired score after phase 1 | after phase 2 (as far as it got) | requests | dollars | wall-clock |
|---|---|---|---|---|---|
| 1 | 2.171793 | 2.606686 | 100 + 37 | 4.05 | 47.7 min |
| 2 | 2.270560 | 2.619368 | 100 + 59 | 5.26 | 47.7 min |
| 3 | 2.290542 | 2.624480 | 100 + 61 | 5.12 | 47.7 min |
| mean (sd) | 2.244299 (0.063581) | 2.616845 (0.009162) | 152 | 4.81 | |

Best known: 2.635983. Cumulative dollars at which each seed's best repaired score first passed a
level: 2.0 at $0.15 / $1.05 / $0.21; 2.5 at $2.88 / $2.91 / $2.97; 2.6 at $2.94 / $2.91 / $2.97;
2.63 was not reached. Every seed passed 2.5 within its first four phase 2 requests, that is, as
soon as the phase 2 prompt had told the model to use SLSQP.

Conditions that the comparison should state:

- **The machine was heavily loaded by other jobs during phase 2** (one-minute load average: median
  33, maximum 153, on 10 cores; median 6 during phase 1). OpenEvolve's evaluation limit is wall
  time, and 35 of the 157 phase 2 programs hit it (18 of 37 on seed 1, 6 of 59 on seed 2, 11 of 61
  on seed 3); none did in phase 1. Some of those programs would have finished on a quiet machine.
- From 20:25, `reap_orphans.py` ended evaluation subprocesses that OpenEvolve had already timed
  out (19 of them); before that they ran on for up to ten minutes each. See that file.
- Two of the 38 distinct best programs (both seed 2, phase 2) draw unseeded random numbers, so a
  re-run does not reproduce what OpenEvolve evaluated. For seed 2's final program OpenEvolve
  recorded 2.625856; the re-run in the CSV gave 2.619368, and five more re-runs gave 2.6159 to
  2.6231 (`results/two_phase_haiku_stochastic_reruns.json`).
- No iteration was lost to an API error. Requests in flight when the cap fired (at most two per
  seed) were billed but are not in the logs, so the true spend is a little above $14.43.

## What is being run

- **OpenEvolve** `4f4b0c4f40906f434d64fe5089aff24e927f7e24` (main, 2026-09-29, version 0.4.0),
  with its own `examples/circle_packing/initial_program.py` and `evaluator.py`, unmodified.
- **The recipe** is the pair of commands in the example's README ("Running the Example"):
  1. phase 1: `initial_program.py`, phase 1 config, `--iterations 100`;
  2. phase 2: a *fresh* OpenEvolve run (not a resume: the population starts again) whose initial
     program is phase 1's `openevolve_output/checkpoints/checkpoint_100/best_program.py`, with the
     phase 2 config, `--iterations 100`.
- **Configs**: the shipped `config_phase_1_anthropic.yaml` and `config_phase_2_anthropic.yaml`.
  `run_openevolve.py` edits them as text and lists every change in `manifest.json`:
  - `primary_model: claude-haiku-4-5` with weight 1.0, in place of Sonnet 4.5 (0.8) and Opus 4.5 (0.2);
  - `checkpoint_interval: 1` instead of 10, so that every best-so-far program is on disk;
  - `random_seed: <seed>`, the same in both phases (the shipped files leave it at the default, 42);
  - `parallel_evaluations: 2` instead of 4, because three seeds ran at once on a shared 10-core
    machine. This is the number of OpenEvolve worker processes, so it also means that 2 rather
    than 4 iterations are in flight at a time.

  Everything else is as shipped: the system messages, population 60 then 70, 4 then 5 islands,
  evaluation time-out 60 s then 90 s, full rewrites, `temperature: 0.7`, `max_tokens: 8192`.
- **Endpoint** `https://api.anthropic.com/v1` (Anthropic's OpenAI-compatible endpoint), key from
  `ANTHROPIC_API_KEY`. `top_p` is not sent. OpenEvolve also sends a `seed` field, which the
  endpoint accepts and ignores, so a run is not reproducible from its seed: the seed fixes
  OpenEvolve's own sampling of parents and prompts, not the model's answers.
- **Environment of the evolved programs**: OpenEvolve's virtual environment (numpy, scipy,
  matplotlib), with BLAS limited to one thread per process.
- **Cost**: claude-haiku-4-5 at $1.00 per million input tokens and $5.00 per million output tokens
  (`common.py`). One request per iteration; no prompt caching.

## Hints in OpenEvolve's shipped prompts

The comparison has to state these, because the inventor on the Mendel side should be told no more.

**Phase 1 system message** (verbatim from `config_phase_1_anthropic.yaml`) tells the model:

1. the target: "The AlphaEvolve paper achieved a sum of 2.635 for n=26";
2. six "key geometric insights": hexagonal patterns in the densest regions; the density bound
   pi/(2*sqrt(3)) of the infinite packing; edge effects in a square; placement in layers or shells;
   equal radii form regular patterns while varied radii use space better; perfect symmetry may not
   be optimal;
3. a direction: "Focus on designing an explicit constructor that places each circle in a specific
   position, rather than an iterative search algorithm."

**Phase 2 system message** (verbatim from `config_phase_2_anthropic.yaml`) tells the model:

1. the target again, and the plateau its authors saw: "The current implementation has plateaued at
   2.377" (said whatever phase 1 actually reached);
2. seven "key insights to explore": variable-sized circles; a pure hexagonal arrangement may not be
   optimal; a hybrid approach; circles at the corners and edges; larger circles in the centre and
   smaller at the edges; special arrangements for specific n; and, as item 4, **the method**:
   "STRONGLY RECOMMENDED: Formulate this as a constrained optimization problem. Use
   `scipy.optimize.minimize` with the 'SLSQP' method. Define the objective function as minimizing
   the negative sum of radii. Define constraints to ensure no circle overlaps and all circles stay
   within bounds. This approach is mathematically superior to custom physics simulations for this
   specific problem.";
3. a direction: "Focus on breaking through the plateau by using numerical optimization libraries
   like scipy rather than writing custom solvers."

The Anthropic variant of the phase 2 config is more explicit than the OpenRouter one
(`config_phase_2.yaml`), which only says that "the optimization routine is critically important -
simple physics-based models with carefully tuned parameters". SLSQP on (x, y, r) is the method of
OpenEvolve's own published 2.634 program, so the phase 2 prompt names the winning technique.

Outside the system messages: the initial program repeats the target in a comment ("AlphaEvolve
improved this to 2.635"), and the evaluator scores `sum_radii / 2.635`, so the target is also in
the metrics shown to the model, together with the evaluator's printed output (artifacts are on by
default).

## How the two evaluators differ

OpenEvolve's `validate_packing` works in floating point and accepts a circle that crosses a side
by up to 1e-6, a pair that overlaps by up to 1e-6, and radii of zero. Mendel's evaluator works in
exact rational arithmetic, accepts no overlap at all and requires positive radii.

Consequences that the comparison should state:

- OpenEvolve's **initial program is invalid under the strict evaluator**: its 26th circle is never
  placed, lands in the same corner as a circle of the outer ring, and both get radius 0.
  OpenEvolve scores it 0.9597642; strictly it scores 0. Mendel's seed is the same construction with
  that pair moved 1e-6 apart, and scores 0.9597652.
- **A program's packing can fail the strict test as returned** and still be worth nearly its full
  score. Circles made to touch in floating point overlap by rounding error (around 1e-17 with the
  initial program's own radius rule), and an optimiser run against OpenEvolve's tolerance can leave
  overlaps of up to 1e-6; both pass OpenEvolve's test and fail the exact one, and the raw strict
  score is then 0. The number to quote is therefore the **repaired** score: the same centres, with
  radii shrunk by `repair.py` until the exact test passes (never enlarged; `repair.py` is a frozen
  copy of the Mendel seed solver's feasibility code, so these scores do not move when the solver
  evolves). In the runs of 2026-10-03, 28 of the 38 distinct best programs were strictly valid as
  returned (Haiku's programs tend to leave a safety margin), and the repair never cost more than
  2e-13; the only visible changes are zero radii becoming 5e-7.
- "Best so far" in the results ranges over the programs that were OpenEvolve's best at some
  checkpoint, by OpenEvolve's own metric. A program that OpenEvolve ranked lower is not re-scored.
- Checkpoint `i` is the state when iteration `i` finished. Iterations run in parallel and finish
  out of order, so the CSVs are ordered by requests spent, not by iteration number. An iteration
  whose answer failed to parse or evaluate is billed but leaves no checkpoint; its cost shows up in
  the next row.
- OpenEvolve gives each evaluation 60 seconds of wall time in phase 1 and 90 in phase 2
  (`evaluator.timeout`), and the cascade runs each program twice. `program_wall_s` in the CSV
  records what one run of each best program took when re-scored, to set against the `--time`
  budget of the Mendel solver.
- An evolved program that draws random numbers without a seed can return a different packing each
  time it is run; the repaired score is of the run made when re-scoring (`rerun_sum_radii` next to
  `openevolve_score` shows whether that happened).

## How requests, tokens and dollars are counted

OpenEvolve logs the token usage returned by the API for every iteration whose request got a
response (`... | tokens: T (prompt: P, completion: C)`), including iterations whose answer then
failed to parse or evaluate. `usage.json` sums those lines; `at_checkpoint[i]` is the running total
when checkpoint `i` was written, and phase 2 continues from the phase 1 total. Requests that ended
without a response (rate limit, overload, time-out) carry no usage and are not counted; OpenEvolve
retries them, and an iteration that still fails is listed under `llm_failures`.

## The spend cap

Every runner polls the logs of all runs in its group every 10 seconds. When the logged spend of
the group reaches `--cap-usd` minus `--cap-margin` (default $0.60, for requests in flight and for
what is spent between two polls), it writes the reason to `<group>/STOP` and sends OpenEvolve the
signal for a graceful shutdown; the other runners see the file and do the same. The same happens
when `--max-llm-failures` iterations (default 3) were lost to API errors. `oe_launch.py` adds one
more guard: if a runner dies, its OpenEvolve process shuts itself down.
