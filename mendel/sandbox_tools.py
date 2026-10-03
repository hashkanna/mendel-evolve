"""The three commands an inventor agent may run inside its sandbox: build, try, and (via the CLI) check.

Kept deliberately small and capped, because several inventors run at once on one machine.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

MAX_SEEDS, MAX_TIME, MAX_INSTANCES, MAX_PARALLEL = 8, 20.0, 4, 4


def _load_evaluator(problem_dir: Path):
    spec = importlib.util.spec_from_file_location("mendel_problem_evaluate", problem_dir / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _instances(problem_dir: Path, keys: list[str]) -> list[tuple[str, dict]]:
    meta = tomllib.loads((problem_dir / "problem.toml").read_text())
    ev = _load_evaluator(problem_dir)
    known = {ev.instance_key(i): i for group in meta.get("instances", {}).values() for i in group}
    out = []
    for key in keys:
        if key in known:
            out.append((key, known[key]))
        elif key.startswith("{"):
            inst = json.loads(key)
            out.append((ev.instance_key(inst), inst))
        elif key[:1].isalpha() and key[1:].isdigit():  # e.g. n17 for an instance not listed in problem.toml
            inst = {key[0]: int(key[1:])}
            out.append((ev.instance_key(inst), inst))
        else:
            raise SystemExit(f"unknown instance {key!r}; known: {', '.join(known)}")
    return out


def _parse_value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _config(solver_dir: Path, overrides: list[str]) -> dict:
    genes = json.loads((solver_dir / "genes.json").read_text())["genes"]
    config = {g["name"]: g["default"] for g in genes}
    for item in overrides:
        name, _, value = item.partition("=")
        if name not in config:
            raise SystemExit(f"unknown gene {name!r}; genes: {', '.join(config)}")
        config[name] = _parse_value(value)
    return config


def cmd_build(args) -> int:
    solver = Path(args.solver).resolve()
    manifest = tomllib.loads((solver / "mendel.toml").read_text())
    build = manifest.get("build")
    if not build:
        print("no build step")
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "solver"
        shutil.copytree(solver, work)
        done = subprocess.run(build, shell=True, cwd=work, capture_output=True, text=True, timeout=300)
    print((done.stdout + done.stderr).strip() or "(no compiler output)")
    print("BUILD OK" if done.returncode == 0 else f"BUILD FAILED (exit {done.returncode})")
    return done.returncode


def cmd_try(args) -> int:
    from .worker import run_job  # imported late so `build` works even if the harness is mid-change

    solver, problem = Path(args.solver).resolve(), Path(args.problem).resolve()
    instances = _instances(problem, args.instances[:MAX_INSTANCES])
    seeds = list(range(1, min(args.seeds, MAX_SEEDS) + 1))
    budget = ({"kind": "iters", "value": args.iters} if args.iters
              else {"kind": "time", "value": min(args.time, MAX_TIME)})
    base = _config(solver, args.set or [])

    arms = {"config": base}
    if args.compare:
        genes = {g["name"]: g for g in json.loads((solver / "genes.json").read_text())["genes"]}
        gene = genes.get(args.compare)
        if gene is None or gene["kind"] not in ("switch", "choice"):
            raise SystemExit(f"--compare needs a switch or choice gene; got {args.compare!r}")
        on_value = True if gene["kind"] == "switch" else next(c for c in gene["choices"] if c != gene["default"])
        if base[args.compare] != gene["default"]:
            on_value = base[args.compare]
        arms = {"on": {**base, args.compare: on_value}, "off": {**base, args.compare: gene["default"]}}

    jobs = [(arm, key, seed, {"solver_dir": str(solver), "problem_dir": str(problem), "config": cfg,
                              "instance": inst, "seed": seed, "budget": budget})
            for arm, cfg in arms.items() for key, inst in instances for seed in seeds]
    with ThreadPoolExecutor(MAX_PARALLEL) as pool:
        results = list(pool.map(lambda j: run_job(j[3]), jobs))

    table: dict[tuple[str, str], list[float]] = {}
    for (arm, key, seed, _), res in zip(jobs, results):
        if not res.get("ok") or not res.get("valid"):
            print(f"  {arm} {key} seed {seed}: FAILED: {str(res.get('error') or res.get('stats') or 'invalid solution')[:400]}")
            continue
        table.setdefault((arm, key), []).append(float(res["score"]))

    print(f"budget: {budget['kind']}={budget['value']}, seeds: {len(seeds)}")
    for (arm, key), scores in sorted(table.items()):
        print(f"  {arm:6s} {key:6s} mean {sum(scores) / len(scores):8.3f}  best {max(scores):g}  worst {min(scores):g}  runs {len(scores)}")
    if args.compare:
        for key, _ in instances:
            on, off = table.get(("on", key)), table.get(("off", key))
            if on and off and len(on) == len(off):
                diffs = [a - b for a, b in zip(on, off)]
                print(f"  effect of {args.compare} on {key}: {sum(diffs) / len(diffs):+.3f} (paired, on minus off)")
    return 0 if table else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mendel.sandbox_tools")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--solver", required=True)
    b.set_defaults(func=cmd_build)
    t = sub.add_parser("try")
    t.add_argument("--solver", required=True)
    t.add_argument("--problem", required=True)
    t.add_argument("--instances", nargs="+", required=True)
    t.add_argument("--seeds", type=int, default=4)
    t.add_argument("--time", type=float, default=5.0)
    t.add_argument("--iters", type=int)
    t.add_argument("--set", nargs="*", metavar="GENE=VALUE")
    t.add_argument("--compare", metavar="GENE")
    t.set_defaults(func=cmd_try)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
