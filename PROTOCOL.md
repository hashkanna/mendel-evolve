# MendelEvolve protocol

MendelEvolve (Mendel for short) evolves **ideas**, not programs. Every idea is a *gene*: a named switch in a solver, with a
stated hypothesis. The framework measures what each gene is worth by switching it off (a *knockout*).

This file is the contract between the three parts of the system: a **problem pack**, a **solver**,
and the **run state** that the dashboard reads. Anything that follows this contract works with Mendel,
in any language.

## 1. Problem pack: `problems/<name>/`

```
problem.toml     metadata, instances, best-known values
evaluate.py      the trusted, exact evaluator
```

`problem.toml`:

```toml
name = "no5sphere"
title = "No 5 on a sphere (Tao et al., problem 60)"
direction = "max"            # or "min"
statement = """plain-text statement shown to the idea inventor"""

[instances]                  # each instance is a table of parameters
train   = [{ n = 10 }, { n = 12 }, { n = 14 }]
heldout = [{ n = 16 }, { n = 18 }, { n = 20 }]
gate    = [{ n = 8 }]        # optional: small instances for the invariance gate (default: first two of train)

[best_known]                 # instance key -> best published value
n10 = 28
```

`evaluate.py` exposes two functions and must import nothing from the solver:

```python
def instance_key(instance: dict) -> str: ...          # {"n": 17} -> "n17"
def evaluate(instance: dict, solution) -> dict: ...   # {"valid": bool, "score": float, "detail": {...}}
```

`evaluate` must be exact (integer or rational arithmetic where the problem allows), must never raise on
malformed input (return `valid: False` with a reason in `detail`), and is never editable by the inventor.

## 2. Solver: `solvers/<name>/`

```
mendel.toml      how to build and run
genes.json       the gene registry
<sources>        any language
```

`mendel.toml`:

```toml
problem = "no5sphere"
build = "cc -O3 -o solver solver.c -lm"   # optional; run once per solver version
run = "./solver"                          # required
```

The harness runs:

```
<run> --config CFG.json --instance INSTANCE.json --seed N (--time SECONDS | --iters N) --out OUT.json
```

- `CFG.json` is a flat object `gene name -> value`. Every gene in `genes.json` is present.
- `INSTANCE.json` is one instance table from `problem.toml`.
- `--time` is a budget in **CPU seconds measured by the solver itself**. `--iters` is a budget in solver
  iterations and must be **deterministic**: the same config, instance, seed and iteration count give the
  same `solution` and the same `stats.iters`. Timing fields under `stats` may differ.
- `OUT.json` is `{"solution": <problem-specific>, "stats": {"iters": int, "trace": [[cpu_seconds, score], ...]}}`.
  `stats` is optional. `trace` records each improvement of the best score.
- Exit code 0 on success. The harness kills the process at three times the time budget plus ten seconds.
- A `run` command that starts with `python` or `python3` is run with the harness's own interpreter, so a
  Python solver sees the same packages locally and in containers.

`genes.json`:

```json
{
  "genes": [
    {
      "name": "centrosymmetric",
      "kind": "switch",
      "default": false,
      "hypothesis": "Building the set from antipodal pairs halves the search space.",
      "predicted": "+1 to +2 points for n >= 16",
      "author": "seed",
      "added_gen": 0
    },
    {
      "name": "ruin_fraction",
      "kind": "float", "default": 0.2, "low": 0.02, "high": 0.6, "log": false,
      "of": null,
      "hypothesis": "Fraction of the set removed in each ruin step.",
      "author": "seed",
      "added_gen": 0
    }
  ]
}
```

Gene kinds:

| kind | values | role |
|---|---|---|
| `switch` | `true` / `false`; default is always `false` (off) | an idea |
| `choice` | one of `choices`; `default` is the baseline choice | an idea with variants |
| `int`, `float` | within `low`..`high` (`log: true` for log scale) | a tunable constant ("allele") |

An allele may carry `"of": "<idea gene>"`; it only matters when that idea is on.

`author` is `"seed"`, `"llm:<model>"` or `"human:<name>"`.

### The invariance rule

Adding a gene must not change behaviour while the gene is at its default. Mendel checks this with
`--iters` runs: the solver before the change and the solver after it, with the new gene at its default,
must produce identical solutions for the same seeds, both at the default configuration and at the
current champion's. A gene that fails this check is rejected, because its knockout would not be a clean
intervention. The check must run long enough to reach every branch of the search (restarts included),
which is what `--gate-iters` controls.

## 3. Run state: `runs/<run>/state.json`

The engine rewrites this file atomically after every step. The dashboard only reads it.

```json
{
  "run": {
    "id": "20261003-2100-no5sphere",
    "problem": "no5sphere", "title": "...", "direction": "max",
    "started": "2026-10-03T21:00:00", "updated": "...",
    "status": "running",
    "generation": 3,
    "spend": { "llm_calls": 12, "llm_usd": 3.1, "cpu_seconds": 81234, "evaluations": 5120 }
  },
  "instances": { "train": ["n10", "n12", "n14"], "heldout": ["n16", "n18", "n20"] },
  "best_known": { "n10": 28 },
  "champion": {
    "config": { "centrosymmetric": true, "ruin_fraction": 0.31 },
    "solver_version": "a1b2c3d4",
    "scores": { "n10": { "mean": 27.6, "best": 28, "runs": 32, "budget": "time=10" } },
    "solutions": { "n10": [[0, 1, 2], [3, 0, 7]] }
  },
  "genes": [
    {
      "name": "centrosymmetric", "kind": "switch", "author": "seed", "added_gen": 0,
      "hypothesis": "...", "predicted": "...",
      "status": "active",
      "screen":   { "effect": 0.8, "ci": [0.3, 1.3], "runs": 48, "generation": 1 },
      "knockout": { "effect": 1.1, "ci": [0.6, 1.6], "runs": 96, "generation": 3 },
      "generality": { "n16": { "effect": 1.4, "ci": [0.7, 2.1] }, "n18": { "effect": -0.2, "ci": [-0.9, 0.5] } },
      "label": "general"
    }
  ],
  "interactions": [ { "a": "centrosymmetric", "b": "tabu", "synergy": 0.6, "ci": [0.1, 1.1], "runs": 96 } ],
  "decomposition": { "seed": 24.1, "tuning": 1.2, "ideas": 2.3, "compute": 0.9, "unit": "points, mean over train instances" },
  "records": [ { "instance": "n20", "value": 54, "best_known": 53, "verified": true, "certificate": "certificates/n20_54.json" } ],
  "history": [ { "t": "2026-10-03T21:04:10", "generation": 1, "event": "gene_screened", "gene": "tabu", "detail": "..." } ],
  "timeline": [ { "t": 0.0, "generation": 0, "score": 0.91 }, { "t": 610.0, "generation": 1, "score": 0.94 } ]
}
```

Field notes:

- `effect` is always "gene on minus gene off", in score units, averaged over paired seeds and the listed
  instances, so a positive effect means the idea helps (for `direction = "min"` the sign is flipped so
  positive still means better). `ci` is a 95% paired-bootstrap interval.
- Gene `status`: `active` (on in the champion), `inactive` (in the solver, off in the champion),
  `queued` (screened positive, waiting to be ported onto the new trunk), `rejected` (failed screening,
  not merged), `failed-gate` (broke the invariance rule or crashed), `pruned` (null knockouts in three
  consecutive rounds).
- Gene `label` compares the knockout interval on training instances with the one pooled over held-out
  instances: `general` (both above zero), `specific` (training above zero, held-out not), `harmful`
  (either below zero without the other helping), `neutral` (both within a small tolerance of zero),
  `inconclusive` (anything else).
- `runs` counts solver runs behind an estimate: two per paired comparison, four per pair for a synergy.
- The engine may add keys beyond these (for example `engine`, `run.problem_dir`, `genes[].value`). Readers
  must ignore keys they do not know.
- `synergy` is the effect of the pair minus the sum of the two single effects; positive means the ideas
  only pay off together.
- `champion.solutions` holds the best solution found per instance, in the problem's own format, for the
  dashboard's viewer. It is optional.
- `timeline.score` is the champion's mean normalised score (score divided by best known) on training
  instances.
