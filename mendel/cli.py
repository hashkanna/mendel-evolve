"""Command line: mendel score | gate | tune | knockout | run | idea | serve."""
from __future__ import annotations

import argparse
import getpass
import json
import random
import sys
from pathlib import Path


def _budget(args, default: dict | None = None) -> dict:
    if getattr(args, "iters", None) is not None:
        return {"kind": "iters", "value": args.iters}
    if getattr(args, "time", None) is not None:
        return {"kind": "time", "value": args.time}
    return dict(default or {"kind": "time", "value": 1.0})


def _config(text: str | None) -> dict | None:
    """A config given as JSON text or as @path/to/file.json."""
    if not text:
        return None
    if text.startswith("@"):
        return json.loads(Path(text[1:]).read_text())
    return json.loads(text)


def _instances(problem, split: str) -> list[dict]:
    if split == "all":
        return [i for items in problem.instances.values() for i in items]
    return problem.instances.get(split, [])


def _problem(solver_dir, explicit):
    from mendel.problem import find_problem_dir, load_problem

    return load_problem(find_problem_dir(solver_dir, explicit))


def _add_eval_options(p: argparse.ArgumentParser, seeds: int = 4) -> None:
    p.add_argument("--problem", help="problem pack directory (default: found from the solver's mendel.toml)")
    p.add_argument("--seeds", type=int, default=seeds, help=f"number of seeds (default {seeds})")
    p.add_argument("--time", type=float, help="budget per run in CPU seconds")
    p.add_argument("--iters", type=int, help="budget per run in solver iterations (deterministic)")
    p.add_argument("--workers", type=int, default=None, help="worker processes (0: run inline)")


def cmd_score(args) -> int:
    from mendel import experiments
    from mendel.executor import LocalExecutor

    problem = _problem(args.solver, args.problem)
    budget = _budget(args)
    with LocalExecutor(args.workers) as ex:
        res = experiments.score_config(ex, problem, args.solver, _config(args.config) or {},
                                       _instances(problem, args.split), range(args.seeds), budget)
    for key, s in res["scores"].items():
        known = problem.best_known.get(key)
        print(f"{key:>12}  mean {s['mean']}  best {s['best']}  runs {s['runs']}  best known {known}  ({s['budget']})")
    print(f"mean normalised score: {res['normalised_mean']:.4f}   failed runs: {res['failed']}")
    if args.json:
        print(json.dumps({"scores": res["scores"], "normalised_mean": res["normalised_mean"]}, indent=1))
    return 0


def cmd_gate(args) -> int:
    from mendel import gate
    from mendel.executor import LocalExecutor
    from mendel.genes import GeneError, by_name, is_idea, load_genes

    problem = _problem(args.old, args.problem)
    if args.genes:
        names = [n.strip() for n in args.genes.split(",") if n.strip()]
    else:  # the genes the new solver adds, idea first
        try:
            old = by_name(load_genes(args.old))
            added = [g for g in load_genes(args.new) if g["name"] not in old]
            names = [g["name"] for g in added if is_idea(g)] + [g["name"] for g in added if not is_idea(g)]
        except GeneError:
            names = []
    context = _config(args.config)
    with LocalExecutor(args.workers) as ex:
        verdict = gate.check(args.old, args.new, names, executor=ex, problem=problem,
                             configs=[{}, context] if context else None,   # {} completes to the defaults
                             iters=args.iters or 2000, seeds=range(args.seeds))
    print("PASS" if verdict.ok else "FAIL", "- new genes:", ", ".join(names) or "(none)")
    for c in verdict.checks:
        print(f"  [{'ok' if c['ok'] else 'FAILED'}] {c['name']}: {c['detail']}")
    for w in verdict.warnings:
        print(f"  warning: {w}")
    if args.json:
        print(json.dumps(verdict.to_dict(), indent=1))
    return 0 if verdict.ok else 1


def cmd_tune(args) -> int:
    from mendel.executor import LocalExecutor
    from mendel.tune import tune

    problem = _problem(args.solver, args.problem)

    def progress(done, total, best):
        print(f"  {done}/{total} trials, best mean normalised score {best:.4f}", file=sys.stderr)

    with LocalExecutor(args.workers) as ex:
        res = tune(ex, problem, args.solver, base_config=_config(args.config),
                   instances=problem.instances.get("train", []), seeds=range(args.seeds), budget=_budget(args),
                   n_trials=args.trials, batch=args.batch, alleles_only=args.alleles_only, on_batch=progress)
    print(f"mean normalised score {res['base_score']:.4f} -> {res['score']:.4f}", file=sys.stderr)
    print(json.dumps(res["config"], indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(res["config"], indent=1) + "\n")
    return 0


def cmd_knockout(args) -> int:
    """A live knockout of one gene in the champion; writes runs/<id>/live.json after every seed."""
    from mendel import experiments
    from mendel.executor import LocalExecutor
    from mendel.genes import by_name, complete_config, is_idea, is_on, knockout, load_genes, on_values
    from mendel.ledger import now, write_json_atomic
    from mendel.problem import load_problem
    from mendel.types import budget_label

    run_dir = Path(args.runs) / args.run
    state = json.loads((run_dir / "state.json").read_text())
    solver_dir = state["champion"].get("solver_dir") or state.get("engine", {}).get("trunk")
    problem = load_problem(args.problem or state["run"]["problem_dir"])
    genes = load_genes(solver_dir)
    known = by_name(genes)
    if args.gene not in known or not is_idea(known[args.gene]):
        names = ", ".join(g["name"] for g in genes if is_idea(g))
        print(f"{args.gene!r} is not an idea gene of the champion's solver. Ideas: {names}", file=sys.stderr)
        return 2
    gene = known[args.gene]
    champion = complete_config(genes, state["champion"]["config"])
    was_on = is_on(gene, champion[args.gene])
    if was_on:      # knockout: champion versus champion without the gene
        on, off = champion, knockout(champion, gene)
    else:           # the gene is off in the champion: measure switching it on instead
        off, on = champion, {**champion, args.gene: on_values(gene)[0]}

    settings = state.get("engine", {}).get("config", {})
    budget = _budget(args, settings.get("budget"))
    if args.quick and args.time is None and args.iters is None and budget["kind"] == "time":
        budget["value"] = min(float(budget["value"]), 1.0)
    n_seeds = args.seeds or (4 if args.quick else int(settings.get("seeds", 8)))
    base = args.seed_base if args.seed_base is not None else random.randrange(1000, 1_000_000)
    seeds = [base + i for i in range(n_seeds)]
    instances = problem.instances.get("train", [])
    keys = [problem.key(i) for i in instances]
    live = {"run": args.run, "gene": args.gene, "status": "running", "was_on": was_on, "effect": 0.0,
            "ci": [0.0, 0.0], "runs": 0, "total_runs": 2 * len(instances) * len(seeds), "pairs": [],
            "budget": budget_label(budget), "direction": problem.direction, "started": now(), "t": now()}
    write_json_atomic(run_dir / "live.json", live)
    runs: dict = {"on": {}, "off": {}}
    with LocalExecutor(args.workers) as ex:
        for i, seed in enumerate(seeds):
            got = experiments.run_arms(ex, problem, {"on": (solver_dir, on), "off": (solver_dir, off)}, instances,
                                       [seed], budget)
            runs["on"].update(got["on"])
            runs["off"].update(got["off"])
            res = experiments.contrast(problem, runs, {"on": 1.0, "off": -1.0}, keys, seeds[:i + 1])
            live.update(effect=res["effect"], ci=res["ci"], runs=res["runs"], pairs=res["pairs"],
                        dropped=res["dropped"], t=now(), status="running" if i + 1 < len(seeds) else "done")
            write_json_atomic(run_dir / "live.json", live)
            print(f"  seed {i + 1}/{len(seeds)}: effect {res['effect']:+.4g}  "
                  f"95% interval [{res['ci'][0]:+.4g}, {res['ci'][1]:+.4g}]  runs {res['runs']}", file=sys.stderr)
    print(json.dumps({k: live[k] for k in ("gene", "effect", "ci", "runs", "budget", "was_on")}))
    return 0


def _options(items: list[str] | None) -> dict:
    """KEY=VALUE pairs; values are parsed as JSON when possible, else kept as strings."""
    out = {}
    for item in items or []:
        key, _, value = item.partition("=")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out


def cmd_run(args) -> int:
    from mendel.engine import EngineConfig, run_engine
    from mendel.problem import find_problem_dir

    given = {
        "runs_dir": args.runs, "run_id": args.run_id, "generations": args.generations, "proposals": args.k,
        "inventor": args.inventor, "executor": args.executor, "workers": args.workers, "seeds": args.seeds,
        "heldout_seeds": args.heldout_seeds, "tune_every": args.tune_every, "tune_trials": args.tune_trials,
        "pairwise_top": args.pairwise_top, "gate_iters": args.gate_iters,
    }
    settings = {k: v for k, v in given.items() if v is not None}
    if args.time is not None or args.iters is not None:
        settings["budget"] = _budget(args)
    if args.inventor_opt:
        settings["inventor_opts"] = _options(args.inventor_opt)
    if args.executor_opt:
        settings["executor_opts"] = _options(args.executor_opt)
    if args.no_generality:
        settings["generality"] = False
    if args.no_decomposition:
        settings["decomposition"] = False
    if args.significant:
        settings["require_significant"] = True
    cfg = EngineConfig(problem_dir=str(find_problem_dir(args.solver, args.problem)), solver_dir=args.solver,
                       **settings)
    run_dir = run_engine(cfg)
    print(run_dir)
    return 0


def cmd_idea(args) -> int:
    from mendel.ledger import now

    run_dir = Path(args.runs) / args.run
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / "ideas.jsonl", "a") as f:
        f.write(json.dumps({"text": args.text, "author": args.author or getpass.getuser(), "t": now()}) + "\n")
    print(f"queued for the next generation of {args.run}")
    return 0


def cmd_serve(args) -> int:
    from mendel.dashboard.server import serve  # provided by the dashboard package

    serve(args.runs, args.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mendel", description="Genetics for algorithm discovery.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("score", help="score a config on a problem's instances")
    p.add_argument("--solver", required=True)
    p.add_argument("--config", help="JSON text or @file; missing genes take their defaults")
    p.add_argument("--split", default="train", choices=["train", "heldout", "all"])
    p.add_argument("--json", action="store_true")
    _add_eval_options(p)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("gate", help="check the invariance rule: OLD solver versus NEW solver")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--genes", help="comma-separated new gene names, idea first (default: inferred)")
    p.add_argument("--config", help="also check invariance in this context (e.g. the champion config)")
    p.add_argument("--json", action="store_true")
    _add_eval_options(p, seeds=2)
    p.set_defaults(func=cmd_gate)

    p = sub.add_parser("tune", help="tune a solver's genes with Optuna TPE (no LLM)")
    p.add_argument("--solver", required=True)
    p.add_argument("--config", help="starting config: JSON text or @file")
    p.add_argument("--trials", type=int, default=40)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--alleles-only", action="store_true", help="hold ideas fixed; tune numeric constants only")
    p.add_argument("--out", help="write the best config to this file")
    _add_eval_options(p, seeds=2)
    p.set_defaults(func=cmd_tune)

    p = sub.add_parser("knockout", help="live knockout of one gene in a run's champion; writes live.json")
    p.add_argument("--run", required=True, help="run id")
    p.add_argument("--gene", required=True)
    p.add_argument("--quick", action="store_true", help="4 seeds and at most 1 second per run")
    p.add_argument("--runs", default="runs", help="runs directory (default: runs)")
    p.add_argument("--seed-base", type=int, help="first seed (default: random, so every demo is a fresh experiment)")
    _add_eval_options(p, seeds=0)
    p.set_defaults(func=cmd_knockout)

    p = sub.add_parser("run", help="run the generation loop")
    p.add_argument("--solver", required=True, help="the seed solver directory")
    p.add_argument("--problem")
    p.add_argument("--runs", help="runs directory (default: runs)")
    p.add_argument("--run-id")
    p.add_argument("--generations", type=int)
    p.add_argument("--k", type=int, help="proposals per generation")
    p.add_argument("--inventor", help="inventor kind for mendel.inventor.make_inventor")
    p.add_argument("--inventor-opt", action="append", metavar="KEY=VALUE")
    p.add_argument("--executor", choices=["local", "modal"])
    p.add_argument("--executor-opt", action="append", metavar="KEY=VALUE")
    p.add_argument("--workers", type=int)
    p.add_argument("--seeds", type=int)
    p.add_argument("--heldout-seeds", type=int)
    p.add_argument("--time", type=float, help="budget per run in CPU seconds")
    p.add_argument("--iters", type=int, help="budget per run in solver iterations")
    p.add_argument("--tune-every", type=int)
    p.add_argument("--tune-trials", type=int)
    p.add_argument("--pairwise-top", type=int)
    p.add_argument("--gate-iters", type=int)
    p.add_argument("--no-generality", action="store_true")
    p.add_argument("--no-decomposition", action="store_true")
    p.add_argument("--significant", action="store_true",
                   help="merge a gene only when its screening interval is entirely above zero")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("idea", help="queue a human idea for a run's next generation")
    p.add_argument("--run", required=True)
    p.add_argument("text")
    p.add_argument("--author")
    p.add_argument("--runs", default="runs")
    p.set_defaults(func=cmd_idea)

    p = sub.add_parser("serve", help="serve the dashboard")
    p.add_argument("--runs", default="runs")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
