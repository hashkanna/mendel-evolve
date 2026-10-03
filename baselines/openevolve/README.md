# OpenEvolve baseline: circle packing, n = 26

The head-to-head for Mendel's circle-packing run. OpenEvolve evolves whole programs with an LLM;
Mendel adds named ideas to one solver and measures each. Both start from the same program
(OpenEvolve's `initial_program.py`; Mendel's seed solver is a port of it) and both are scored by
the same strict evaluator, `problems/circle_packing/evaluate.py`.

Nothing here calls the API until you run step 2.

## Commands

All from the project root.

```bash
# 1. Set up (once): clone OpenEvolve at the pinned commit into baselines/openevolve/vendor/
#    (git-ignored) and install it into its own virtual environment. No API calls.
bash baselines/openevolve/setup.sh

# 2. Run. PAID: one claude-haiku-4-5 request per iteration. Reads ANTHROPIC_API_KEY from .env.
uv run python baselines/openevolve/run_openevolve.py --iterations 100 --seed 1
#    -> baselines/openevolve/runs/iter100_seed1/
#         openevolve_output/checkpoints/checkpoint_<i>/best_program.py   best program after iteration i
#         openevolve_output/best/best_program.py                         final best program
#         openevolve_output/logs/openevolve_*.log                        OpenEvolve's log (token usage per iteration)
#         usage.json      billed requests, tokens and dollars: total, per iteration, at each checkpoint
#         manifest.json   OpenEvolve commit, seed, hashes of the config, initial program and evaluator
#         console.log     OpenEvolve's console output

# 3. Re-score every best-so-far program with the strict evaluator. No API calls.
uv run python baselines/openevolve/rescore.py baselines/openevolve/runs/iter100_seed1
#    -> baselines/openevolve/runs/iter100_seed1/strict_scores.csv
#       iteration, requests, tokens, dollars, strict_score, ... (one row per checkpoint)
```

Options: `run_openevolve.py --out DIR` (a run directory is never overwritten),
`--checkpoint-interval K`, `--config FILE`, `--dry-run` (prepare, print the command, call nothing);
`rescore.py --timeout SECONDS --out FILE`.

To test the plumbing without spending anything, run against the local stub:

```bash
baselines/openevolve/vendor/venv/bin/python baselines/openevolve/fake_llm_server.py --port 8765 &
uv run python baselines/openevolve/run_openevolve.py --iterations 4 --seed 1 \
    --api-base http://127.0.0.1:8765/v1 --out /tmp/oe-stub-run
uv run python baselines/openevolve/rescore.py /tmp/oe-stub-run
```

With `--api-base` set to anything but the Anthropic endpoint, `.env` is not loaded and a dummy key
is used, so the real key is never sent anywhere else.

## What is being run

- **OpenEvolve** `4f4b0c4f40906f434d64fe5089aff24e927f7e24` (main, 2026-09-29, version 0.4.0),
  with its own `examples/circle_packing/initial_program.py` and `evaluator.py`, unmodified.
- **Config** `config.yaml`: OpenEvolve's shipped `config_phase_1_anthropic.yaml` with two changes:
  the model is the single `claude-haiku-4-5` (instead of Sonnet 4.5 at 0.8 and Opus 4.5 at 0.2), and
  `checkpoint_interval` is 1 (instead of 10) so that every best-so-far program is on disk. Endpoint
  `https://api.anthropic.com/v1` (Anthropic's OpenAI-compatible endpoint), key from
  `ANTHROPIC_API_KEY`. Sampling: `temperature: 0.7`, `max_tokens: 8192`; `top_p` is not sent.
  OpenEvolve also sends a `seed` field derived from `random_seed`, which the endpoint ignores, so a
  run is not reproducible from its seed: the seed fixes OpenEvolve's own sampling of parents and
  prompts, not the model's answers.
- **One phase.** The example's README describes two phases: 100 iterations with the phase 1
  config, then a restart from the best program with `config_phase_2.yaml`, whose system message
  was written after seeing the phase 1 plateau. Only the phase 1 config is used here.
- **Cost**: claude-haiku-4-5 at $1.00 per million input tokens and $5.00 per million output tokens
  (`common.py`). One request per iteration; no prompt caching.

## Hints in OpenEvolve's shipped material

The comparison has to state these, because the inventor on the Mendel side should be told no more.

The phase 1 system message (used here, verbatim) tells the model:

1. the target: "The AlphaEvolve paper achieved a sum of 2.635 for n=26";
2. six "key geometric insights": hexagonal patterns in the densest regions; the density bound
   pi/(2*sqrt(3)) of the infinite packing; edge effects in a square; placement in layers or shells;
   equal radii form regular patterns while varied radii use space better; perfect symmetry may not
   be optimal;
3. a direction: "Focus on designing an explicit constructor that places each circle in a specific
   position, rather than an iterative search algorithm." Note that this steers the model *away*
   from numerical optimisation, which is what produced OpenEvolve's published 2.634 in phase 2.

The initial program repeats the target in a comment ("AlphaEvolve improved this to 2.635"), outside
the evolved block. The evaluator scores `sum_radii / 2.635`, so the target is also in the metrics
shown to the model, together with the evaluator's printed output (artifacts are on by default).

The phase 2 system message (NOT used here) adds: the current plateau (2.377), variable-sized
circles, a hybrid rather than purely hexagonal arrangement, "the optimization routine is
critically important - simple physics-based models with carefully tuned parameters", circles in
corners and along edges, larger circles in the centre, and special arrangements for specific n.

## How the two evaluators differ

OpenEvolve's `validate_packing` works in floating point and accepts a circle that crosses a side
by up to 1e-6, a pair that overlaps by up to 1e-6, and radii of zero. Mendel's evaluator works in
exact rational arithmetic, accepts no overlap at all and requires positive radii.

Consequences that the comparison should state:

- OpenEvolve's **initial program is invalid under the strict evaluator**: its 26th circle is never
  placed, lands in the same corner as a circle of the outer ring, and both get radius 0.
  OpenEvolve scores it 0.9597642; strictly it scores 0. Mendel's seed is the same construction with
  that pair moved 1e-6 apart, and scores 0.9597652.
- **Expect `strict_score` to be 0 on almost every row.** Any program that makes circles touch in
  floating point leaves about half of the contacts overlapping by rounding error (around 1e-17 with
  the initial program's own radius rule, as the stub test showed; up to 1e-6 with a numerical
  optimiser tuned against OpenEvolve's tolerance). That passes OpenEvolve's test and fails the exact
  one. `repaired_score` in the CSV is the fair number to quote: the same centres, with radii shrunk
  by Mendel's `finalise` until the exact test passes. For a packing that was only off by rounding
  the repair costs about 1e-15; for one that leans on the 1e-6 tolerance it costs what the
  tolerance was worth.
- Checkpoint `i` is the state when iteration `i` finished. Four iterations run in parallel and
  finish out of order, so the CSV is ordered by requests spent, not by iteration number.
- OpenEvolve gives each evaluation 60 seconds of wall time (`evaluator.timeout`), and the cascade
  runs each program twice. `program_wall_s` and `program_cpu_s` in the CSV record what one run of
  each best program cost, to set against the `--time` budget of the Mendel solver.
- An evolved program that draws random numbers without a seed can return a different packing each
  time it is run; the strict score is of the run made by `rescore.py`.

## How requests and tokens are counted

OpenEvolve logs the token usage returned by the API for every iteration whose request got a
response (`... | tokens: T (prompt: P, completion: C)`), including iterations whose answer then
failed to parse or evaluate. `usage.json` sums those lines; `at_checkpoint[i]` is the running total
when checkpoint `i` was written. Requests that ended without a response (rate limit, overload,
time-out) carry no usage and are not counted; OpenEvolve retries them up to three times.
`iterations_without_usage` in `usage.json` says how many iterations that was.
