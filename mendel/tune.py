"""Tuning: Optuna TPE with ask-and-tell in parallel batches, then a greedy single-flip pass. No LLM calls.

Objective: mean normalised score over the training instances and a few seeds (failed or invalid runs
count as 0). The best few configs are then re-evaluated with more seeds (the confirmation seeds),
together with the starting config, and the best of those is kept, so tuning never returns something
worse than it was given on the confirmation seeds.

TPE is noisy about ideas: with few trials it can land on a config that has a helpful idea switched
off. The flip pass repairs that: each idea is flipped relative to the tuned config, and the flip is
kept only when its paired 95% interval on the confirmation seeds is entirely above zero.
"""
from __future__ import annotations

import json

from mendel.genes import by_name, complete_config, is_idea, is_on, load_genes, search_space
from mendel.types import usable


def objective(executor, problem, solver_dir, configs: list[dict], instances: list[dict], seeds,
              budget: dict) -> list[float]:
    """Mean normalised score of each config: mean over instances of the mean over seeds."""
    from mendel.experiments import run_arms

    seeds = list(seeds)
    arms = {str(i): (solver_dir, config) for i, config in enumerate(configs)}
    runs = run_arms(executor, problem, arms, instances, seeds, budget)
    keys = [problem.key(i) for i in instances]
    values = []
    for i in range(len(configs)):
        cell = runs[str(i)]
        per_instance = []
        for key in keys:
            scores = [problem.normalised(key, cell[(key, s)]["score"]) if usable(cell[(key, s)]) else 0.0
                      for s in seeds]
            per_instance.append(sum(scores) / len(scores))
        values.append(sum(per_instance) / len(per_instance))
    return values


def _suggest(trial, genes: list[dict], base: dict, space_names: set[str]) -> dict:
    """Sample one config. Ideas first, then alleles; an allele whose `of` idea is off keeps its base value."""
    known = by_name(genes)
    config = dict(base)
    for g in genes:
        name = g["name"]
        if name not in space_names or not is_idea(g):
            continue
        choices = [False, True] if g["kind"] == "switch" else list(g["choices"])
        config[name] = trial.suggest_categorical(name, choices)
    for g in genes:
        name = g["name"]
        if name not in space_names or is_idea(g):
            continue
        of = g.get("of")
        if of is not None and of in known and not is_on(known[of], config[of]):
            continue
        if g["kind"] == "int":
            config[name] = trial.suggest_int(name, g["low"], g["high"], log=bool(g.get("log")))
        else:
            config[name] = trial.suggest_float(name, g["low"], g["high"], log=bool(g.get("log")))
    return config


def _alternatives(gene: dict, value) -> list:
    """The other values an idea can take."""
    if gene["kind"] == "switch":
        return [not value]
    return [c for c in gene["choices"] if c != value]


def _arm(gene: dict, value) -> str:
    return f"{gene['name']}={json.dumps(value)}"


def flip_pass(executor, problem, solver_dir, config: dict, instances: list[dict], seeds,
              budget: dict) -> tuple[dict, list[dict]]:
    """One greedy pass over the idea genes, in registry order.

    Each idea is flipped relative to the current config (for a choice gene, every other choice is
    tried). A flip is kept only when every run with it succeeded and its paired 95% interval over
    `seeds` is entirely above zero; later ideas are then measured against the config with that flip
    in it. All flips against one config run as a single batch, so the pass costs one batch plus one
    more for every flip that is kept.

    Returns (config, flips kept as [{"gene", "from", "to", "effect", "ci"}]); effects are in score
    units with positive meaning better."""
    from mendel.experiments import contrast, run_arms

    seeds = list(seeds)
    genes = load_genes(solver_dir)
    keys = [problem.key(i) for i in instances]
    current = complete_config(genes, config)
    pending = [g for g in genes if is_idea(g)]
    kept: list[dict] = []
    while pending:
        arms = {"current": (solver_dir, current)}
        for g in pending:
            for value in _alternatives(g, current[g["name"]]):
                arms[_arm(g, value)] = (solver_dir, {**current, g["name"]: value})
        runs = run_arms(executor, problem, arms, instances, seeds, budget)
        remaining: list[dict] = []
        for i, g in enumerate(pending):
            best = None
            for value in _alternatives(g, current[g["name"]]):
                flipped = runs[_arm(g, value)]
                if not all(usable(r) for r in flipped.values()):
                    continue
                res = contrast(problem, {"a": flipped, "b": runs["current"]}, {"a": 1.0, "b": -1.0}, keys, seeds)
                if res["runs"] > 0 and res["ci"][0] > 0 and (best is None or res["effect"] > best["effect"]):
                    best = {"gene": g["name"], "from": current[g["name"]], "to": value,
                            "effect": res["effect"], "ci": res["ci"]}
            if best is not None:
                current = {**current, g["name"]: best["to"]}
                kept.append(best)
                remaining = pending[i + 1:]   # their flips must be measured again, in the new context
                break
        pending = remaining
    return current, kept


def tune(executor, problem, solver_dir, *, instances: list[dict], seeds, budget: dict,
         base_config: dict | None = None, n_trials: int = 40, batch: int = 8, alleles_only: bool = False,
         top_k: int = 3, confirm_seeds=None, sampler_seed: int = 0, flip: bool = True, on_batch=None) -> dict:
    """Search the gene space for a better config.

    alleles_only: hold every idea as it is in base_config and tune only the alleles relevant to it.
    confirm_seeds: seeds for re-evaluating the top_k configs (default: twice as many as `seeds`).
    flip: after the search, run flip_pass() on the confirmation seeds (never when alleles_only).
    on_batch(done, n_trials, best_value): progress callback after each batch.

    Returns {"config", "score", "base_score", "improved", "trials": [{"config", "value"}],
             "confirmed": [{"config", "value"}], "flips": [...]}; scores are mean normalised scores
    on confirm_seeds."""
    import optuna

    optuna.logging.set_verbosity(optuna.logging.WARNING)
    seeds = list(seeds)
    confirm = list(confirm_seeds) if confirm_seeds is not None else list(range(2 * len(seeds)))
    genes = load_genes(solver_dir)
    base = complete_config(genes, base_config)
    space = search_space(genes, base, alleles_only)
    space_names = {g["name"] for g in space}
    history: list[dict] = []

    if space and n_trials > 0:
        sampler = optuna.samplers.TPESampler(seed=sampler_seed, constant_liar=True,
                                             n_startup_trials=max(4, min(10, n_trials // 3)))
        study = optuna.create_study(direction="maximize", sampler=sampler)
        study.enqueue_trial({name: base[name] for name in space_names})  # start from the incumbent
        done = 0
        while done < n_trials:
            trials = [study.ask() for _ in range(min(batch, n_trials - done))]
            configs = [_suggest(t, genes, base, space_names) for t in trials]
            values = objective(executor, problem, solver_dir, configs, instances, seeds, budget)
            for trial, config, value in zip(trials, configs, values):
                study.tell(trial, value)
                history.append({"config": config, "value": value})
            done += len(trials)
            if on_batch is not None:
                on_batch(done, n_trials, max(h["value"] for h in history))

    # confirm: the best few distinct configs plus the starting point, on more seeds
    candidates = [base]
    seen = {json.dumps(base, sort_keys=True)}
    for h in sorted(history, key=lambda h: h["value"], reverse=True):
        ident = json.dumps(h["config"], sort_keys=True)
        if ident not in seen:
            seen.add(ident)
            candidates.append(h["config"])
        if len(candidates) > top_k:
            break
    values = objective(executor, problem, solver_dir, candidates, instances, confirm, budget)
    confirmed = [{"config": c, "value": v} for c, v in zip(candidates, values)]
    best = max(range(len(candidates)), key=lambda i: (values[i], -i))  # ties go to the starting config
    config, score = candidates[best], values[best]

    flips: list[dict] = []
    if flip and not alleles_only:
        config, flips = flip_pass(executor, problem, solver_dir, config, instances, confirm, budget)
        if flips:
            score = objective(executor, problem, solver_dir, [config], instances, confirm, budget)[0]
    return {"config": config, "score": score, "base_score": values[0], "improved": config != base,
            "trials": history, "confirmed": confirmed, "flips": flips}
