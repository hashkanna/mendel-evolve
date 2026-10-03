"""Experiments. Every comparison is paired by (instance, seed): all arms see the same seeds.

Sign convention (PROTOCOL.md): an effect is 'on minus off' in score units, flipped for
direction = "min", so positive always means better. `runs` counts solver runs behind an estimate.
Pairs in which any arm failed or gave an invalid solution are dropped and counted in `dropped`.
"""
from __future__ import annotations

import json

from mendel.genes import (active_ideas, by_name, complete_config, defaults, is_idea, is_on, knockout, load_genes,
                          on_values)
from mendel.stats import label_gene, paired_bootstrap, summarise
from mendel.types import budget_label, make_job, usable


def run_arms(executor, problem, arms: dict, instances: list[dict], seeds, budget: dict,
             timeout: float | None = None) -> dict:
    """Run every arm on every (instance, seed) in one batch.

    arms: name -> (solver_dir, config). Returns name -> {(instance key, seed): result}.
    Configs are completed against their solver's registry; identical jobs run once."""
    seeds = list(seeds)
    jobs: list[dict] = []
    slot_of: dict[str, int] = {}
    index: list[tuple] = []
    for name, (solver_dir, config) in arms.items():
        config = complete_config(load_genes(solver_dir), config)
        for inst in instances:
            key = problem.key(inst)
            for seed in seeds:
                ident = json.dumps([str(solver_dir), config, key, seed], sort_keys=True)
                if ident not in slot_of:
                    slot_of[ident] = len(jobs)
                    jobs.append(make_job(solver_dir, problem.dir, config, inst, seed, budget, timeout))
                index.append((name, key, seed, slot_of[ident]))
    results = executor.run(jobs)
    out: dict = {name: {} for name in arms}
    for name, key, seed, slot in index:
        out[name][(key, seed)] = results[slot]
    return out


def contrast(problem, runs: dict, weights: dict, keys: list[str], seeds) -> dict:
    """A paired linear contrast between arms, e.g. {"on": 1, "off": -1}.

    Returns {"effect", "ci", "runs", "pairs", "dropped", "per_instance"}; each pair lists the arms'
    scores and the signed difference."""
    diffs: list[float] = []
    strata: list[str] = []
    pairs: list[dict] = []
    dropped = 0
    for key in keys:
        for seed in seeds:
            cell = {arm: runs[arm].get((key, seed)) for arm in weights}
            if not all(usable(r) for r in cell.values()):
                dropped += 1
                continue
            diff = problem.sign * sum(w * cell[arm]["score"] for arm, w in weights.items())
            diffs.append(diff)
            strata.append(key)
            pairs.append({"instance": key, "seed": seed, **{arm: cell[arm]["score"] for arm in weights}, "diff": diff})
    effect, lo, hi = paired_bootstrap(diffs, strata)
    per_instance = {}
    for key in keys:
        own = [d for d, s in zip(diffs, strata) if s == key]
        if own:
            e, l, h = paired_bootstrap(own)
            per_instance[key] = {"effect": e, "ci": [l, h], "runs": len(own) * len(weights)}
    return {"effect": effect, "ci": [lo, hi], "runs": len(diffs) * len(weights), "pairs": pairs,
            "dropped": dropped, "per_instance": per_instance}


def _failed(runs: dict) -> int:
    return sum(1 for r in runs.values() if not usable(r))


def score_config(executor, problem, solver_dir, config: dict, instances: list[dict], seeds, budget: dict) -> dict:
    """Per-instance mean, best and run count, plus the best solution per instance.

    Returns {"scores": {key: {"mean", "best", "runs", "budget"}}, "solutions": {key: solution},
             "normalised": {key: mean normalised score, failures counted as 0}, "normalised_mean", "failed",
             "errors": up to three distinct error strings from failed runs}."""
    seeds = list(seeds)
    runs = run_arms(executor, problem, {"c": (solver_dir, config)}, instances, seeds, budget)["c"]
    scores, solutions, normalised = {}, {}, {}
    failed = 0
    for inst in instances:
        key = problem.key(inst)
        cell = [runs[(key, s)] for s in seeds]
        good = [r for r in cell if usable(r)]
        failed += len(cell) - len(good)
        scores[key] = {**summarise([r["score"] for r in good], problem.direction), "budget": budget_label(budget)}
        normalised[key] = sum(problem.normalised(key, r["score"]) for r in good) / len(cell) if cell else 0.0
        if good:
            solutions[key] = max(good, key=lambda r: problem.sign * r["score"])["solution"]
    mean = sum(normalised.values()) / len(normalised) if normalised else 0.0
    errors = sorted({str(r.get("error")) for r in runs.values() if not usable(r)})[:3]
    return {"scores": scores, "solutions": solutions, "normalised": normalised, "normalised_mean": mean,
            "failed": failed, "errors": errors}


def compare(executor, problem, solver_dir, config_a: dict, config_b: dict, instances: list[dict], seeds,
            budget: dict, *, solver_dir_b=None, timeout: float | None = None) -> dict:
    """Effect of A relative to B (positive means A is better) with its 95% paired-bootstrap interval."""
    seeds = list(seeds)
    arms = {"a": (solver_dir, config_a), "b": (solver_dir_b or solver_dir, config_b)}
    runs = run_arms(executor, problem, arms, instances, seeds, budget, timeout)
    keys = [problem.key(i) for i in instances]
    out = contrast(problem, runs, {"a": 1.0, "b": -1.0}, keys, seeds)
    out["failed_a"] = _failed(runs["a"])
    out["failed_b"] = _failed(runs["b"])
    return out


def screen_gene(executor, problem, solver_dir, champion_config: dict, gene_name: str, instances: list[dict],
                seeds, budget: dict, *, off_solver_dir=None) -> dict:
    """A new idea on versus off, everything else as in the champion.

    off_solver_dir: run the 'off' arm on this solver instead (the trunk, which the gate has shown to
    behave identically; its runs are shared between proposals and already cached).
    For a choice gene every non-baseline variant is tried and the best is returned.
    Adds "value" (the on-value), "config" (champion + gene on), "failed_a" (failures with the gene on)."""
    genes = load_genes(solver_dir)
    gene = by_name(genes)[gene_name]
    off = knockout(complete_config(genes, champion_config), gene)
    best = None
    for value in on_values(gene):
        on = dict(off)
        on[gene_name] = value
        result = compare(executor, problem, solver_dir, on, off, instances, seeds, budget,
                         solver_dir_b=off_solver_dir)
        result["value"] = value
        result["config"] = on
        if best is None or result["effect"] > best["effect"]:
            best = result
    return best


def knockouts(executor, problem, solver_dir, champion_config: dict, instances: list[dict], seeds, budget: dict,
              *, only: list[str] | None = None) -> dict:
    """One-at-a-time knockouts for every idea that is on in the champion (or just those in `only`).

    Returns gene name -> {"effect", "ci", "runs", "pairs", "per_instance", "dropped"}, where effect is
    champion minus knockout, i.e. what the gene is worth in the champion's context."""
    seeds = list(seeds)
    genes = load_genes(solver_dir)
    known = by_name(genes)
    champion = complete_config(genes, champion_config)
    names = [n for n in active_ideas(genes, champion) if only is None or n in only]
    arms = {"champion": (solver_dir, champion)}
    for name in names:
        arms[f"ko:{name}"] = (solver_dir, knockout(champion, known[name]))
    runs = run_arms(executor, problem, arms, instances, seeds, budget)
    keys = [problem.key(i) for i in instances]
    out = {}
    for name in names:
        pair = {"on": runs["champion"], "off": runs[f"ko:{name}"]}
        out[name] = contrast(problem, pair, {"on": 1.0, "off": -1.0}, keys, seeds)
    return out


def knockins(executor, problem, solver_dir, champion_config: dict, instances: list[dict], seeds, budget: dict,
             *, skip=()) -> dict:
    """The mirror image of knockouts(), for every idea that is off in the champion (except `skip`):
    the champion with that idea switched on, minus the champion. So the effect is still 'gene on
    minus gene off' in the champion's context. Same shape as knockouts(), plus "value" (the on-value
    measured; for a choice gene, the variant with the largest effect)."""
    seeds = list(seeds)
    genes = load_genes(solver_dir)
    champion = complete_config(genes, champion_config)
    off = [g for g in genes if is_idea(g) and not is_on(g, champion[g["name"]]) and g["name"] not in skip]
    arms = {"champion": (solver_dir, champion)}
    for g in off:
        for value in on_values(g):
            arms[f"in:{g['name']}:{json.dumps(value)}"] = (solver_dir, {**champion, g["name"]: value})
    runs = run_arms(executor, problem, arms, instances, seeds, budget)
    keys = [problem.key(i) for i in instances]
    out = {}
    for g in off:
        best = None
        for value in on_values(g):
            pair = {"on": runs[f"in:{g['name']}:{json.dumps(value)}"], "off": runs["champion"]}
            res = contrast(problem, pair, {"on": 1.0, "off": -1.0}, keys, seeds)
            res["value"] = value
            if best is None or res["effect"] > best["effect"]:
                best = res
        out[g["name"]] = best
    return out


def pairwise(executor, problem, solver_dir, champion_config: dict, pairs: list[tuple[str, str]],
             instances: list[dict], seeds, budget: dict) -> list[dict]:
    """For each pair of ideas: both on (champion), each one off, both off.

    synergy = (both on - both off) - (a alone - both off) - (b alone - both off)
            = S11 - S10 - S01 + S00,
    so it is positive when the ideas only pay off together. Returns a list of
    {"a", "b", "synergy", "ci", "runs", "pair_effect", "effect_a", "effect_b"}."""
    seeds = list(seeds)
    genes = load_genes(solver_dir)
    known = by_name(genes)
    champion = complete_config(genes, champion_config)
    arms = {"11": (solver_dir, champion)}
    for a, b in pairs:
        a_off = knockout(champion, known[a])
        b_off = knockout(champion, known[b])
        arms[f"{a}|{b}|01"] = (solver_dir, a_off)                     # a off, b on
        arms[f"{a}|{b}|10"] = (solver_dir, b_off)                     # a on, b off
        arms[f"{a}|{b}|00"] = (solver_dir, knockout(a_off, known[b]))  # both off
    runs = run_arms(executor, problem, arms, instances, seeds, budget)
    keys = [problem.key(i) for i in instances]
    out = []
    for a, b in pairs:
        cell = {"11": runs["11"], "10": runs[f"{a}|{b}|10"], "01": runs[f"{a}|{b}|01"], "00": runs[f"{a}|{b}|00"]}
        synergy = contrast(problem, cell, {"11": 1.0, "10": -1.0, "01": -1.0, "00": 1.0}, keys, seeds)
        both = contrast(problem, cell, {"11": 1.0, "00": -1.0}, keys, seeds)
        only_a = contrast(problem, cell, {"10": 1.0, "00": -1.0}, keys, seeds)
        only_b = contrast(problem, cell, {"01": 1.0, "00": -1.0}, keys, seeds)
        out.append({"a": a, "b": b, "synergy": synergy["effect"], "ci": synergy["ci"], "runs": synergy["runs"],
                    "pair_effect": both["effect"], "effect_a": only_a["effect"], "effect_b": only_b["effect"]})
    return out


def generality(executor, problem, solver_dir, champion_config: dict, heldout_instances: list[dict], seeds,
               budget: dict, train_knockouts: dict, *, tol: float = 0.0) -> dict:
    """Knockouts per held-out instance, and each gene's label.

    train_knockouts is the output of knockouts() on the training instances. Returns gene name ->
    {"generality": {key: {"effect", "ci"}}, "heldout": {"effect", "ci", "runs"}, "label": str}."""
    held = knockouts(executor, problem, solver_dir, champion_config, heldout_instances, seeds, budget,
                     only=list(train_knockouts))
    out = {}
    for name, ko in held.items():
        per = {key: {"effect": v["effect"], "ci": v["ci"]} for key, v in ko["per_instance"].items()}
        pooled = {"effect": ko["effect"], "ci": ko["ci"], "runs": ko["runs"]}
        out[name] = {"generality": per, "heldout": pooled, "label": label_gene(train_knockouts[name], pooled, tol)}
    return out


def _mean_score(problem, runs: dict, keys: list[str], seeds) -> float | None:
    """Mean over instances of the mean score over seeds (usable runs only)."""
    means = []
    for key in keys:
        good = [runs[(key, s)]["score"] for s in seeds if usable(runs.get((key, s)))]
        if good:
            means.append(sum(good) / len(good))
    return sum(means) / len(means) if means else None


def decomposition(executor, problem, seed_solver_dir, champion_solver_dir, champion_config: dict,
                  instances: list[dict], seeds, budget: dict, *, tuned_seed_config: dict | None = None,
                  tune_opts: dict | None = None) -> dict:
    """Where the champion's score comes from, in points (mean over the given instances):

      seed    the seed solver at its defaults
      tuning  gain from tuning only the seed solver's alleles (ideas stay at their defaults)
      ideas   the champion minus that tuned seed solver
    Gains are signed so that positive means better (flipped for direction = "min").
    `compute` is not filled in here. Pass tuned_seed_config to skip the alleles-only tuning run."""
    seeds = list(seeds)
    seed_config = defaults(load_genes(seed_solver_dir))
    if tuned_seed_config is None:
        from mendel.tune import tune

        opts = {"instances": instances, "seeds": seeds, "budget": budget, **(tune_opts or {})}
        tuned_seed_config = tune(executor, problem, seed_solver_dir, base_config=seed_config,
                                 alleles_only=True, **opts)["config"]
    arms = {"seed": (seed_solver_dir, seed_config), "tuned": (seed_solver_dir, tuned_seed_config),
            "champion": (champion_solver_dir, champion_config)}
    runs = run_arms(executor, problem, arms, instances, seeds, budget)
    keys = [problem.key(i) for i in instances]
    seed = _mean_score(problem, runs["seed"], keys, seeds)
    tuned = _mean_score(problem, runs["tuned"], keys, seeds)
    champion = _mean_score(problem, runs["champion"], keys, seeds)
    if seed is None or tuned is None or champion is None:
        raise RuntimeError("decomposition: an arm has no usable runs")
    return {"seed": seed, "tuning": problem.sign * (tuned - seed), "ideas": problem.sign * (champion - tuned),
            "unit": "points, mean over train instances", "champion": champion,
            "tuned_seed_config": tuned_seed_config}
