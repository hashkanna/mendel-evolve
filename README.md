# MendelEvolve

**Genetics for algorithm discovery.** MendelEvolve (Mendel for short; the command is `mendel`) is an
autoresearch framework that evolves *ideas* instead of whole programs, and measures what each idea is worth.

Evolutionary coding agents such as AlphaEvolve and OpenEvolve mutate programs and keep the high scorers.
They find good algorithms, but afterwards nobody can say which idea produced the result, and recent studies
of their search traces ask whether the gains are new structure, re-tuned constants or evaluator overfitting.
They are Darwin without Mendel: selection, but no genes.

In Mendel every idea is a **gene**: a named switch in the solver with a stated hypothesis.

- An LLM agent only **invents** genes. It never tunes constants and never re-tests old ideas.
- Classical search **recombines** genes and **tunes** their constants, with no LLM calls.
- **Knockouts** (switching one idea off, with paired seeds) give a measured effect for every idea, an
  interaction map, and a per-idea test of whether it generalises to instance sizes it was not selected on.
- The resulting **ledger** is what the next inventors read, so the search does not repeat itself, and it is
  also the explanation of the result.

Built at the London AI x Science Hackathon, 3-4 October 2026, for the track "AI Automated Discovery of
Algorithms". Everything here was written during the event.

## How it works

```
            +--------------------- ledger: every idea and its measured effect ---------------------+
            |                                                                                      |
            v                                                                                      |
   invent (LLM agent, K in parallel) --> gate --> screen --> merge --> tune --> knock out --> generalise
   one new gene each, in a sandbox      invariance  on vs off   best     constants   each idea    held-out
                                        rule        paired      idea     and         off, pairs   instance
                                                    seeds       joins    switches    off          sizes
                                                                trunk    (no LLM)
```

1. **Invent.** K headless agent sessions each get a copy of the current solver, the problem statement and the
   ledger, and add exactly one new gene. Each session looks through a different lens (throughput, structure,
   search dynamics, construction, wildcard) so that parallel proposals differ. Ideas typed in by a person go
   through the same path and are credited to that person.
2. **Gate.** The invariance rule: with the new gene at its default, the solver must behave exactly as before
   (same random stream, same output). This is what makes a later knockout a clean intervention. A gene that
   fails is rejected and the reason is recorded.
3. **Screen.** Gene on versus gene off, in the current champion's context, with paired seeds and a 95%
   bootstrap interval.
4. **Merge.** The best positive idea joins the trunk. Other positive ideas are queued to be ported.
5. **Tune.** Optuna searches over all switches and constants. No LLM calls.
6. **Knock out.** Every active idea is switched off in turn, and the top ideas in pairs, on seeds the tuner
   never saw. This gives each idea's causal effect and the synergy between ideas.
7. **Generalise.** The same knockouts on held-out instance sizes label each idea `general`, `specific`,
   `neutral`, `harmful` or `inconclusive`.
8. **Account.** The run reports where the gain came from: the seed solver, tuning alone, the ideas, and extra
   compute; and what it cost in LLM calls, dollars and CPU-hours.

The contract between a problem, a solver and the run state is in [PROTOCOL.md](PROTOCOL.md). Solvers can be
written in any language; the two shipped ones are C and Python.

## Install

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) and a C compiler.

```bash
uv sync --extra modal --extra dev
uv run pytest -q                      # 32+ tests on a toy problem with known ground truth
```

Optional: the [Claude Code CLI](https://claude.com/claude-code) for the idea inventor, and a
[Modal](https://modal.com) account for fan-out (`uv run modal setup`).

## Run

```bash
# 1. No LLM, no cloud: tune and attribute the seed solver of the toy problem (about 10 seconds).
uv run mendel run --solver tests/fixtures/solvers/toy --problem tests/fixtures/problems/toy \
    --run-id toy --generations 1 --k 0 --iters 150 --seeds 3 --heldout-seeds 2 --tune-trials 16

# 2. With the inventor: two new ideas per generation.
uv run mendel run --solver tests/fixtures/solvers/toy --problem tests/fixtures/problems/toy \
    --run-id toy-llm --generations 2 --k 2 --iters 150 --seeds 3 --heldout-seeds 2 --tune-trials 16

# 3. The real thing: Tao et al. problem 60, evaluations on Modal.
uv run mendel run --solver solvers/no5sphere --problem problems/no5sphere --run-id p60 \
    --generations 12 --k 4 --executor modal --time 10 --seeds 12 --heldout-seeds 8 --gate-iters 8000

# Watch it.
uv run mendel serve                   # http://127.0.0.1:8765

# Add your own idea; it becomes a gene and gets measured like any other.
uv run mendel idea --run p60 --author you "prefer points whose removal frees the most blocked cells"

# Knock out one idea live.
uv run mendel knockout --run p60 --gene centrosymmetric --quick

# Run the champion at scale and keep verified certificates.
uv run python -m mendel.campaign --solver runs/p60/trunk/gen012 --problem problems/no5sphere \
    --instances n17 n18 n19 n20 --seeds 32 --time 600 --executor modal --out runs/p60-campaign
```

## Benchmarks in this repository

| Problem | Solver | Evaluator | Why it is here |
|---|---|---|---|
| `no5sphere`: largest subset of an n x n x n grid with no 5 points on a sphere or plane (Tao et al., [problem 60](https://google-deepmind.github.io/alphaevolve_repository_of_problems/problems/60.html)) | C, ruin-and-recreate | exact integer determinants over every 5-subset, plus an independent Bareiss checker | open problem with many instance sizes and recent public records |
| `circle_packing`: n circles in the unit square, maximise the sum of radii | Python; the seed is a port of OpenEvolve's initial program | exact rational feasibility, no tolerance | the standard benchmark; head-to-head with OpenEvolve from the same starting point |
| `toy` (under `tests/fixtures`) | Python | exact | known ground truth for testing attribution |

### Adding a problem

A problem pack is two files, `problem.toml` and `evaluate.py`. A solver is a program that accepts
`--config --instance --seed (--time | --iters) --out`, plus a `genes.json` and a three-line `mendel.toml`.
See [PROTOCOL.md](PROTOCOL.md); `tests/fixtures` has the smallest complete example.

## Results

Results from the hackathon runs are in [RESULTS.md](RESULTS.md).

## Design notes

**Research efficiency.** LLM calls scale with the number of ideas, not the number of evaluations: tuning,
recombination and attribution are plain compute. Every evaluation is cached by solver version, configuration,
instance, seed and budget. On Modal, the two arms of a paired comparison run in the same container so that
hardware differences cancel. The run state records LLM calls, dollars, CPU-seconds and evaluations.

**Compute on Modal.** Every solver evaluation runs on [Modal](https://modal.com), one core per container.
- Solver sources and the trusted evaluator travel with each batch, named by a hash of their contents, so a
  new solver version needs no redeploy; containers compile it on first sight.
- Batches keep both arms of a paired comparison in the same container, so hardware differences cancel.
- There are two lanes over the same code: `run_batch` for the engine's short paired experiments and
  `run_batch_bg` for long record campaigns, so a campaign cannot starve the engine.
- The inventor agents' own trial runs go to Modal as well, which keeps a laptop usable while a dozen agents
  work and keeps their timings meaningful.
- Every executor has a hard cap on core-hours, so an overnight loop cannot spend the whole credit.

The first two record searches on problem 60 (480 runs of 120 CPU-seconds) cost about $0.90 in total.

**Trust.** Evaluators are exact and live outside the inventor's reach. The inventor agent can edit only its
sandbox copy and run three harness commands; it cannot run arbitrary shell commands. The engine re-runs the
gate itself rather than believing the agent. The campaign runner re-checks every remote result locally and
again with an independent checker before writing a certificate, and does not announce a tie with a published
value as a record.

**Honest attribution.** Knockouts use seeds the tuner never saw, because measuring a selected configuration
on the seeds that selected it biases every effect upward. Intervals are reported and an effect whose interval
spans zero is labelled inconclusive.

**Limits.**
- An idea that needs a whole-program rewrite does not fit behind a switch.
- Leave-one-out effects depend on context; pairwise knockouts only cover the top ideas.
- Integer-valued objectives make small effects hard to see without many seeds.
- Solvers are LLM-written code that runs on your machine in the sandbox tools; use the Modal executor, or a
  container, if that matters to you.

## Related work

Mendel combines ingredients that exist separately, and we want to be exact about which.

- The efficiency idea, an LLM writing a parameterised program that a non-LLM search explores, is from
  [X-evolve](https://arxiv.org/abs/2508.07932) and [LLaMEA-HPO](https://arxiv.org/abs/2410.16309).
- Keeping a memory of which changes moved the score is in
  [Component-Aware Feedback](https://arxiv.org/abs/2609.38639) and [DeltaEvolve](https://arxiv.org/abs/2602.02919),
  from differences between a program and its parent.
- The questions Mendel is built to answer come from
  [What Do Evolutionary Coding Agents Evolve?](https://arxiv.org/abs/2605.20086) and
  [Evolution or Illusion?](https://arxiv.org/abs/2609.19799).

What we have not found elsewhere, to our knowledge: interventional attribution inside the search loop
(knocking out every idea of every champion, singly and in pairs), a representation that forces each idea
into a named switch with a hypothesis so that such interventions are possible, and a per-idea test of
generalisation across instance sizes.

## Credits

[OpenEvolve](https://github.com/algorithmicsuperintelligence/openevolve) (Apache-2.0): the circle packing
seed solver is a port of its initial program, and it is our baseline.
[Optuna](https://optuna.org) for tuning, [Modal](https://modal.com) for compute,
[Claude Code](https://claude.com/claude-code) for the inventor agent.
Problem 60 and its published records: Georgiev, Gómez-Serrano, Tao and Wagner,
[Mathematical exploration and discovery at scale](https://arxiv.org/abs/2511.02864), and the contributors to
the [record threads](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/6); their
certificates are used only to validate our evaluator.
