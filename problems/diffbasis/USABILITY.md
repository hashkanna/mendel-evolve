# Usability report: adding `diffbasis` to MendelEvolve

Tester: Devin (an AI agent), working in a fresh clone with no prior knowledge of the project. I started
from README.md and PROTOCOL.md and read framework source only when they were not enough. Each place
where I had to read source is listed below with the file and line.

## Timeline (BST, 3 October 2026; times from `date` calls in the session)

| Step | From | To | Took |
|---|---|---|---|
| Read README.md and PROTOCOL.md; fetch the problem record and top-3 solutions | 22:40 | 22:41 | ~2 min |
| Read toy fixture, `problems/autocorr3`, `mendel/campaign.py`, `problem.py`, `cli.py`, `solver.py`, `gate.py`, `worker.py` | 22:41 | 22:43 | ~3 min |
| `evaluate.py`, `verify.py`, `selftest.py`; selftest reproduces the published score | 22:43 | 22:45 | ~3 min |
| `problem.toml`, `records.json`, `solver.c`, `genes.json`; standalone runs of the binary | 22:45 | 22:48 | ~4 min |
| `uv run pytest -q` (46 passed, 90 s) | 22:48 | 22:50 | 1.5 min |
| `mendel score` | 22:49:47 | 22:49:59 | 12 s |
| `mendel gate` (as briefed, then once per seed idea) | 22:50 | 22:50 | ~1 min |
| `mendel run` as briefed | 22:50:40 | 22:58:01 | 7.5 min |
| Second `mendel run` with `--tune-every 1` (see finding 7) | 22:58:31 | 23:10:06 | 11.5 min |
| Modal campaign, 32 runs of 120 s (in parallel with the above) | 22:58:42 | 23:10:06 | 11.5 min |
| This report, commit, PR | 23:10 | ~23:25 | ~15 min |

Writing code took about 15 minutes. Most of the wall-clock time went to waiting on runs. The machine is
shared, with a load average of about 100 on 10 cores during the session.

## What was easy

- **The solver contract in PROTOCOL.md section 2 was enough to write a C solver without reading framework
  code.** The command line, CPU-time versus `--iters` semantics, the OUT.json shape, the build/run lines
  and the gene kinds are all stated, and they were all correct. Everything worked the first time,
  including extra keys under `stats` (`v`, `window`), which are accepted silently.
- **`genes.json` is clear.** The examples cover switch, allele and `of`.
- **`problems/autocorr3` was the best template.** It is another EinsteinArena problem, with the arena
  verifier copied verbatim and a records.json that cites the API. I copied its conventions (one
  leaderboard number used as `best_known` for every instance size; `{n = N}` as the size the solver works
  at).
- **The gate's messages are good.** When something failed, it said exactly what had been run and why it
  failed.
- **The campaign runner just worked:** `--executor modal --no-deploy --max-cpu-hours 20` on the first
  try, $0.06 estimated, both best sets re-checked locally and by `verify.py`, and correctly not
  announced as records.
- **`uv sync` and `pytest` worked as documented.** README says "32+ tests"; 46 passed.

## What was unclear, wrong or missing (most important first)

1. **README contradicts itself: the problem pack is not "two files".** README "Adding a problem" and
   PROTOCOL section 1 list only `problem.toml` and `evaluate.py`. Every real pack also ships `verify.py`,
   `records.json`, `selftest.py` and `published/`, and the campaign runner depends on `verify.py`. Its
   contract appears nowhere in the docs. I learned it from `mendel/campaign.py:114-126`:
   - invocation is `python verify.py CERT.json`, with exit 0 meaning pass;
   - it runs under the harness interpreter;
   - the certificate keys are `problem`, `instance`, `score`, `solution`, `seed`,
     `budget_cpu_seconds`, `config`, `found`.

   `records.json` is never read by anything under `mendel/`. It is a convention only, and its schema
   differs between packs (autocorr3 uses `leaderboard.top[]`, noisosceles uses `records.<key>`). PROTOCOL
   should have a "1b. Optional pack files" section with the verify.py contract and a suggested
   records.json schema.

2. **`min_improvement` in problem.toml is undocumented, and the shipped packs are inconsistent about it.**
   `campaign.py:50` reads a top-level `min_improvement` from problem.toml to decide whether a verified
   value counts as a record. It must sit above the first `[table]`, or TOML puts it inside
   `[best_known]`. I found it only by reading the code.

   autocorr3 records the arena's `minImprovement = 1e-5` in records.json but not in problem.toml. Its
   campaign therefore uses the fallback margin of 1e-9 × |known|, and could announce a "record" that the
   arena would reject. I did not change autocorr3, because it is not my pack. I set
   `min_improvement = 1e-9` (the arena's value for problem 19) in `problems/diffbasis/problem.toml`.

3. **The brief's `mendel gate solvers/diffbasis solvers/diffbasis` cannot pass.** It prints
   `FAIL - new genes: (none) / [FAILED] registry: the proposal names no new genes` and exits 1
   (`gate.py:67-68`). The gate compares an old solver with a new one that adds one idea. Comparing a seed
   solver with itself is rejected before any run, so it does not even check determinism.

   There is no command that checks a seed solver on its own. Such a command would check:
   - `--iters` determinism;
   - always-valid output;
   - every switch's smoke test;
   - the invariance of each idea against a copy without it.

   My workaround was to build, for each seed idea, a copy of the solver whose genes.json lacks that idea
   and its alleles. The code is identical and only the registry differs. I then ran
   `mendel gate <copy> solvers/diffbasis --problem problems/diffbasis`, and all three passed (output in
   the PR). A `mendel check solvers/X` subcommand, or `gate --self`, would make this one line.

4. **A gate smoke test can call a working idea a no-op.** `restart_from_best` passed invariance but got
   "switching restart_from_best on did not change any solution in the smoke test; the gene may be a
   no-op", even at `--iters 400000`. The idea changes the trajectory, but the gate instances (n = 12, 20)
   are solved before any restart can matter, so the returned best set is unchanged. PROTOCOL should say
   that gate instances need to be hard enough for ideas to change the output, not only small.

5. **Briefed `mendel run` and README example 1: `--tune-trials 16` with `--generations 1` does not tune.**
   README example 1 promises to "tune and attribute the seed solver". Its flags match the brief's, and in
   neither case does the champion get tuned. The cause is that `tune_every` defaults to 2
   (`engine.py:85`), and tuning runs only when `g % tune_every == 0` (`engine.py:489`). With one
   generation, g = 1, so tuning never runs.

   What did run:
   - knock-ins of the three seed ideas;
   - the end-of-run decomposition, which tunes alleles only.

   The champion stayed at the seed defaults, although `wichmann_init` measured +0.589 with a 95%
   interval of [0.50, 0.70].

   The decomposition then reported `seed 3.532, tuning +0.078, ideas -0.078`. A reader takes "ideas
   -0.078" to mean the ideas hurt, but no idea was ever on. The number is just "untuned champion minus
   tuned seed". Adding `--tune-every 1` gave the intended behaviour (results below). Fix one of: make
   `tune_every` default to 1 when `generations` < `tune_every`; warn when `--tune-trials` will be
   unused; or put `--tune-every 1` in the README example.

6. **Generality labels are only computed for active ideas.** With every idea off in the champion
   (finding 5), the run measured knock-in effects and intervals but gave no `label` and no
   `generality`, because `_generality` is only fed knockouts (`engine.py:789`). PROTOCOL describes
   `label` without mentioning this.

7. **`spend.cpu_seconds` is summed wall time.** `MeteredExecutor` adds up `r["wall"]`
   (`executor.py:77`). On this loaded machine, 126 runs of 5 CPU-seconds reported 1729 "cpu_seconds",
   where about 630 is right. Either rename the field or measure CPU time (for example with
   `resource.getrusage(RUSAGE_CHILDREN)` in the worker).

8. **Running on a shared machine is not documented.** The kill is wall-clock, at 3 × budget + 10 s.
   With a load average of 100, a 5 CPU-second run can exceed 25 s of wall time.

   `MENDEL_WALL_FACTOR` exists but is documented only in a comment in `worker.py:30`. The default local
   worker count is `cpu_count - 2`, which was 8 here (`executor.py:30`). I set `MENDEL_WALL_FACTOR=10`
   and passed `--workers 4` on both runs. README should mention both in a "running on a busy machine"
   note.

9. **The campaign parses instances in an undocumented way.** `--instances n128` is parsed as
   `{text[0]: int(text[1:])}` (`campaign.py:31-34`). A pack's `instance_key` therefore has to be one
   letter followed by an integer, or the user must pass JSON. This is fine, but undocumented.

10. **`mendel run` is silent until the end.** It prints only the run directory. Progress is in
    `runs/<id>/state.json`, `events.jsonl` or `mendel serve`, so I had to poll state.json. One line per
    ledger event on stderr would help.

11. **PROTOCOL leaves out several small things:**
    - The solver's working directory is the build cache, `~/.cache/mendel/builds/<version>/`
      (`worker.py:99`, `solver.py:106`). This matters for solvers that read files by relative path.
    - It does not say what `score` to return when `valid` is false. The worker ignores it, and
      autocorr3 uses 0.0, which is a confusing value when `direction = "min"`.
    - `timeline.score` is described as "score divided by best known". For `direction = "min"` the code
      computes best known / score (`problem.py:51-64`).
    - For instances without `best_known`, the reference silently becomes 1.0.

12. **README's benchmarks table is out of date.** It lists no5sphere, circle_packing and toy. The repo
    also ships autocorr3, heilbronn and noisosceles, and autocorr3 is the best template for a leaderboard
    problem.

13. **Environment noise.** uv printed "`VIRTUAL_ENV=... does not match the project environment`" on every
    command. This is not the project's fault, but a README line ("unset VIRTUAL_ENV, or ignore this")
    would save a newcomer some worry.

## Decisions I had to make alone

- **Instance semantics.** The leaderboard accepts any |B| ≤ 2000 and ranks one number. Following
  autocorr3, an instance `{n = N}` means "exactly N elements, counted as the arena counts them" (after
  removing duplicates and adding 0). Every instance uses the leaderboard value as `best_known`, so small
  N normalise below 1 even at their own optimum. I chose train {40, 64}, heldout {32, 52, 80} and gate
  {12, 20}.
- **Strictness.** The evaluator returns the arena's score exactly. It is stricter than the arena's code
  in three cases that the arena's schema already excludes:
  - non-int entries (the arena's `int()` would truncate 3.7);
  - negative entries;
  - a size different from n.
- **Exactness.** The arena divides `int / int` in Python, which is correctly rounded, so
  `float(Fraction(|B|^2, v))` is bit-identical to it. verify.py counts differences by a big-integer
  polynomial product rather than the pair loop. On all three published solutions, all three checkers
  return 2.639027469506608 = 129600/49109; the published value is the same.

## Results (honest)

- **Seed solver.** C, simulated annealing at fixed temperature on "uncovered distances below the
  target", raising the target whenever 1..T is covered. It is deterministic under `--iters` (identical
  solutions; only trace timings differ) and always outputs a valid set. It is weak: from the plain start
  it reaches about 3.3 at n = 40 in 5 s.
- **Briefed run (`diffbasis-devin`, no tuning, see finding 5).** Knock-ins in the default context, 4
  attribution seeds × 2 training instances, effect = improvement in score, 95% interval:
  - `wichmann_init` +0.589 [+0.502, +0.696]: a large, clear gain.
  - `hole_directed` +0.166 [+0.028, +0.319]: a modest gain whose interval excludes zero.
  - `restart_from_best` +0.012 [−0.051, +0.115]: inconclusive.
- **Run with `--tune-every 1` (`diffbasis-devin-tune1`).** The tuner switched on `wichmann_init` and
  `hole_directed` and set temp to 0.118, width_factor to 1.52 and hole_prob to 0.41.
  - Knockout of `wichmann_init`: +0.591 [+0.526, +0.659], labelled **general** (held-out n32 +0.46,
    n52 +0.77, n80 +0.62).
  - `hole_directed`: exactly 0.000, labelled **neutral**.
  - `restart_from_best` (knock-in): 0.000.
  - Pair synergy: −0.049 [−0.16, +0.07].
  - Decomposition: seed 3.529, tuning +0.079, ideas +0.507.

  The champion's scores equal the Wichmann ruler's own value on every seed (1600/546 = 2.9304 at n = 40).
  **The annealer never improves on a Wichmann start.** Moving one mark of a near-optimal ruler destroys
  dozens of unique differences, so at the tuned temperature every move is rejected. This is why the
  other two ideas measure exactly zero in that context. Mendel showed this correctly. In effect, its
  attribution says the seed's search is useless once the construction is in place. A real next idea
  would need compound moves, or a secondary objective that rewards redundancy.
- **Modal campaign** (`--instances n128 n360 --seeds 16 --time 120`, config `wichmann_init` +
  `hole_directed`):
  - n128: 2.9778262450018174 (8192/2751).
  - n360: 2.991827877556674 (64800/21659), against the published 2.639027469506608.
  - All 16 seeds gave the same value. Both sets passed `evaluate.py` and `verify.py`, and neither is a
    record.
  - Estimated spend: $0.06. Wall time was 11.5 min, mostly queueing behind other tasks on the shared app.

## What I would change, in order

1. Fix the tuning trap: `--generations 1` combined with the default `tune_every = 2` (finding 5).
2. Add a `mendel check <solver>` for seed solvers (finding 3).
3. Document the optional pack files: the `verify.py` contract, `records.json` and `min_improvement`
   (findings 1 and 2). Fix autocorr3's `min_improvement`.
4. Report CPU time as CPU time, and document `MENDEL_WALL_FACTOR` and `--workers` for shared machines
   (findings 7 and 8).
5. Compute generality for knock-ins as well, or say in the docs that it is only for active ideas
   (finding 6).
6. Print progress from `mendel run` (finding 10).
