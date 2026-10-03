"""The gate: the invariance rule of PROTOCOL.md.

Adding a gene must not change behaviour while the gene is at its default. check() compares the old
solver with the new one (new genes at default) on --iters runs and requires identical solutions,
then smoke-tests the new idea switched on. The verdict's reasons are written for the LLM that made
the proposal: they say what was run, what differed and what the rule is.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mendel.genes import GeneError, by_name, complete_config, defaults, is_idea, load_genes, on_values
from mendel.solver import load_manifest
from mendel.types import make_job

RULE = ("Adding a gene must not change behaviour while the gene is at its default: with the new gene off, "
        "the solver must make exactly the same random draws in the same order and return the same solution.")


@dataclass
class GateVerdict:
    ok: bool
    reasons: list[str] = field(default_factory=list)    # why it failed; fed back to the inventor
    warnings: list[str] = field(default_factory=list)   # suspicious but not disqualifying
    checks: list[dict] = field(default_factory=list)    # [{"name", "ok", "detail"}] in the order they ran
    infra: bool = False   # True when the trunk itself failed to run: says nothing about the proposal

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        if self.ok:
            return "gate passed" + (f" ({len(self.warnings)} warning(s))" if self.warnings else "")
        return "gate failed: " + " | ".join(self.reasons)


def _short(value, limit: int = 160) -> str:
    text = json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + "..."


def check_registry(old_dir, new_dir, new_genes: list[str]) -> tuple[list[str], list[str]]:
    """Static checks. Returns (reasons, warnings); no reasons means the registry is acceptable."""
    reasons: list[str] = []
    warnings: list[str] = []
    old = load_genes(old_dir)  # the trunk is trusted; let it raise if it is broken
    try:
        new = load_genes(new_dir)
    except GeneError as e:
        return [str(e)], warnings
    try:
        manifest = load_manifest(new_dir)
        if manifest["problem"] != load_manifest(old_dir)["problem"]:
            reasons.append("mendel.toml: 'problem' must not change")
    except Exception as e:
        reasons.append(f"mendel.toml is missing or invalid: {e}")
    old_by, new_by = by_name(old), by_name(new)
    for name, gene in old_by.items():
        if name not in new_by:
            reasons.append(f"existing gene {name!r} was removed from genes.json; existing genes must stay unchanged")
        elif new_by[name] != gene:
            changed = sorted(k for k in set(gene) | set(new_by[name]) if gene.get(k) != new_by[name].get(k))
            reasons.append(f"existing gene {name!r} was modified (fields: {', '.join(changed)}); "
                           "existing genes must stay unchanged")
    if not new_genes:
        reasons.append("the proposal names no new genes")
    for name in new_genes:
        if name in old_by:
            reasons.append(f"gene name {name!r} already exists in the trunk; choose a new name")
        elif name not in new_by:
            reasons.append(f"new gene {name!r} is not in the candidate's genes.json")
    extra = [n for n in new_by if n not in old_by and n not in new_genes]
    if extra:
        reasons.append(f"genes.json adds genes the proposal does not name: {', '.join(extra)}")
    added = [new_by[n] for n in new_genes if n in new_by and n not in old_by]
    added_ideas = [g["name"] for g in added if is_idea(g)]
    if added and len(added_ideas) != 1:
        reasons.append("a proposal must add exactly one idea gene (kind switch or choice) plus optional alleles; "
                       f"this one adds {len(added_ideas)} idea genes: {', '.join(added_ideas) or 'none'}")
    elif added and added[0]["name"] != added_ideas[0]:
        reasons.append(f"the first new gene must be the idea gene ({added_ideas[0]!r}), not an allele")
    for g in added:
        if is_idea(g) and not str(g.get("hypothesis") or "").strip():
            reasons.append(f"new idea gene {g['name']!r} needs a non-empty 'hypothesis'")
        if not is_idea(g) and added_ideas and g.get("of") != added_ideas[0]:
            warnings.append(f"new allele {g['name']!r} does not declare \"of\": \"{added_ideas[0]}\"; "
                            "it will be tuned even while the idea is off")
    return reasons, warnings


def check(old_dir, new_dir, new_genes: list[str], *, executor, problem, configs: list[dict] | None = None,
          instances: list[dict] | None = None, seeds=(0, 1), iters: int = 2000,
          timeout: float | None = 120.0) -> GateVerdict:
    """Gate a candidate solver against the trunk.

    configs: contexts in which invariance is checked (old-solver configs; default: the old defaults).
             The last one is the context for the smoke test (pass the champion config last).
    instances: default: the first two training instances."""
    old_dir, new_dir = Path(old_dir), Path(new_dir)
    verdict = GateVerdict(ok=False)

    def record(name: str, ok: bool, detail: str) -> None:
        verdict.checks.append({"name": name, "ok": ok, "detail": detail})

    # 1. the registry
    if not new_dir.is_dir():
        verdict.reasons.append(f"candidate solver directory does not exist: {new_dir}")
        record("registry", False, verdict.reasons[-1])
        return verdict
    reasons, warnings = check_registry(old_dir, new_dir, list(new_genes))
    verdict.warnings += warnings
    if reasons:
        verdict.reasons += reasons
        record("registry", False, "; ".join(reasons))
        return verdict
    record("registry", True, "genes.json is valid and existing genes are unchanged")

    old_genes, new_registry = load_genes(old_dir), load_genes(new_dir)
    idea = by_name(new_registry)[new_genes[0]]
    seeds = list(seeds)
    if instances is None:
        instances = problem.instances.get("train", [])[:2]
    contexts = [complete_config(old_genes, c) for c in (configs or [defaults(old_genes)])]
    budget = {"kind": "iters", "value": int(iters)}

    # 2 + 3 in one batch: invariance pairs, then smoke runs with the idea on
    jobs: list[dict] = []
    pairs: list[tuple] = []   # (instance key, seed, context number, old slot, new slot)
    for c, context in enumerate(contexts):
        for inst in instances:
            for seed in seeds:
                pairs.append((problem.key(inst), seed, c, len(jobs), len(jobs) + 1))
                jobs.append(make_job(old_dir, problem.dir, context, inst, seed, budget, timeout))
                jobs.append(make_job(new_dir, problem.dir, complete_config(new_registry, context), inst, seed,
                                     budget, timeout))
    smoke: list[tuple] = []   # (on value, instance key, slot, slot of the matching 'off' run)
    for value in on_values(idea):
        on = complete_config(new_registry, contexts[-1])
        on[idea["name"]] = value
        for inst in instances:
            off_slot = next(p[4] for p in pairs if p[0] == problem.key(inst) and p[1] == seeds[0]
                            and p[2] == len(contexts) - 1)
            smoke.append((value, problem.key(inst), len(jobs), off_slot))
            jobs.append(make_job(new_dir, problem.dir, on, inst, seeds[0], budget, timeout))
    results = executor.run(jobs)

    # 2. invariance
    broken: list[str] = []
    trunk_errors = [results[p[3]]["error"] for p in pairs if not results[p[3]]["ok"]]
    new_errors = [results[p[4]]["error"] for p in pairs if not results[p[4]]["ok"]]
    if trunk_errors:
        verdict.infra = True
        broken.append(f"the trunk solver itself failed to run (not caused by the proposal): {trunk_errors[0]}")
    elif new_errors:
        broken.append(f"the candidate solver failed to run with the new gene at its default: {new_errors[0]}")
    else:
        differ = [p for p in pairs if results[p[3]]["solution"] != results[p[4]]["solution"]]
        if differ:
            examples = "; ".join(
                f"instance {key}, seed {seed}, --iters {iters}: score {results[o]['score']} before, "
                f"{results[n]['score']} after (solution before {_short(results[o]['solution'], 80)}, "
                f"after {_short(results[n]['solution'], 80)})"
                for key, seed, _, o, n in differ[:3])
            broken.append(f"invariance broken in {len(differ)} of {len(pairs)} paired runs: with the new gene at "
                          f"its default the solver no longer reproduces the trunk. {examples}. {RULE}")
    if broken:
        verdict.reasons += broken
        record("invariance", False, broken[0])
    else:
        record("invariance", True, f"{len(pairs)} paired --iters {iters} runs gave identical solutions")

    # 3. smoke test with the idea on
    smoke_reasons: list[str] = []
    changed = False
    for value, key, slot, off_slot in smoke:
        r = results[slot]
        setting = f"{idea['name']}={json.dumps(value)}"
        if not r["ok"]:
            smoke_reasons.append(f"with {setting} the solver failed on instance {key}: {r['error']}")
        elif not r["valid"]:
            smoke_reasons.append(f"with {setting} the solver returned an invalid solution on instance {key}: {r['error']}")
        elif results[off_slot]["ok"] and r["solution"] != results[off_slot]["solution"]:
            changed = True
    if smoke_reasons:
        verdict.reasons += smoke_reasons[:3]
        record("smoke", False, smoke_reasons[0])
    else:
        record("smoke", True, f"{len(smoke)} runs with {idea['name']} on finished with valid solutions")
        if not changed and not broken:
            verdict.warnings.append(f"switching {idea['name']} on did not change any solution in the smoke test; "
                                    "the gene may be a no-op")

    verdict.ok = not verdict.reasons
    return verdict
