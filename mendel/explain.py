"""mendel explain: a causal breakdown of a program that another system evolved.

Given a problem pack, an initial program and an evolved program (for example OpenEvolve's
`initial_program.py` and the `best_program.py` of one of its runs), answer the question "what did the
evolution actually add: new structure, or re-tuned constants?" by intervention rather than by reading.

  1. Decompose (one LLM step). A headless Claude session, restricted like the idea inventor (it can edit
     only its sandbox and run two harness tools), writes a Mendel solver in which every difference between
     the two programs is a named switch with a one-line hypothesis, and changed constants are alleles.
     The harness checks the result itself, the *bookend check*, and feeds failures back to the session:
       all switches off, alleles at their initial values  -> the initial program's output
       all switches on, alleles at their evolved values   -> the evolved program's output
     "Output" means the repaired solution on a fixed seed; see `bookend_check` for exactly what is compared.
  2. Measure (no LLM). Knock out each switch from the all-on configuration, switch each one on alone from
     the all-off configuration, knock out the top few in pairs, tune the constants with every switch off,
     and reset the constants with every switch on. Paired seeds and bootstrap intervals, as elsewhere.
  3. Report. runs/<id>/state.json in the PROTOCOL.md format (so the dashboard shows it) and report.md.

The problem-specific parts (how to call the original programs, the wrapper that ends every run with the
repair step) live in ADAPTERS; only circle packing has one so far.

Module commands, used by the sandbox tools:
    python -m mendel.explain bookend --solver DIR --problem DIR --reference FILE [--quick]
    python -m mendel.explain try --solver DIR --problem DIR [--all-on] [--set gene=value ...]
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mendel.genes import GeneError, defaults, is_idea, load_genes
from mendel.types import make_job, usable

ROOT = Path(__file__).resolve().parent.parent
TOLERANCE = 1e-9          # bookend check: largest allowed difference in any coordinate, radius or score
NEGLIGIBLE = 1e-9         # an effect this small is reported as "no effect"
BUDGET = {"kind": "iters", "value": 1}   # the programs are constructors: the budget is accepted and ignored
JOB_TIMEOUT = 600.0
_THREADS = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
            "NUMEXPR_NUM_THREADS")


# --------------------------------------------------------------------------------------------
# Adapters: what is specific to a problem
# --------------------------------------------------------------------------------------------

CIRCLE_DRIVER = r'''
import importlib.util, json, random, sys
import numpy as np
seed = int(sys.argv[3])
random.seed(seed); np.random.seed(seed % 2**32)
spec = importlib.util.spec_from_file_location("program", sys.argv[1])
program = importlib.util.module_from_spec(spec)
spec.loader.exec_module(program)
random.seed(seed); np.random.seed(seed % 2**32)
centers, radii = program.run_packing()[:2]
centers = np.asarray(centers, dtype=float).reshape(-1, 2)
radii = np.asarray(radii, dtype=float).reshape(-1)
with open(sys.argv[2], "w") as f:
    json.dump([[float(c[0]), float(c[1]), float(r)] for c, r in zip(centers, radii)], f)
'''

CIRCLE_WRAPPER = r'''#!/usr/bin/env python3
"""Fixed wrapper written by `mendel explain`. Do not edit it: the harness checks its hash and restores it.

Solver contract (PROTOCOL.md):
    python solver.py --config CFG.json --instance INSTANCE.json --seed N (--time S | --iters N) --out OUT.json

It seeds the global random generators (`random`, `numpy.random`) with the run seed, calls
program.construct(cfg, n, seed) and finishes, in every configuration, with repair.repair(): the radii-only
repair of the Mendel seed solver and of baselines/openevolve/repair.py, so the output is strictly feasible
under the exact evaluator. Both programs are constructors that run to completion, so the budget is accepted
and ignored; the output is deterministic under --iters as long as program.py does not read the clock.
If program.construct raises, or its output cannot be repaired, the run fails (exit 1) instead of inventing
a packing: a made-up fallback would be measured as if it were the configuration's result.
`stats.raw` is the packing before the repair.
"""
from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
              "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_name, "1")
os.environ.setdefault("MPLBACKEND", "Agg")

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--instance", required=True)
    parser.add_argument("--seed", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--time", type=float)
    group.add_argument("--iters", type=int)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    cfg = {g["name"]: g["default"] for g in json.loads((HERE / "genes.json").read_text())["genes"]}
    cfg.update(json.loads(Path(args.config).read_text()))
    n = int(json.loads(Path(args.instance).read_text())["n"])

    from repair import repair

    random.seed(args.seed)
    np.random.seed(args.seed % 2**32)
    import program

    random.seed(args.seed)
    np.random.seed(args.seed % 2**32)
    centers, radii = program.construct(cfg, n, args.seed)[:2]
    centers = np.asarray(centers, dtype=float).reshape(-1, 2)
    radii = np.asarray(radii, dtype=float).reshape(-1)
    raw = [[float(c[0]), float(c[1]), float(r)] for c, r in zip(centers, radii)]
    if len(raw) != n:
        print(f"program.construct returned {len(raw)} circles, expected {n}", file=sys.stderr)
        return 1
    solution = repair(raw)
    if solution is None:
        print("the packing could not be repaired (non-finite values, or radii wrong by more than rounding)",
              file=sys.stderr)
        return 1
    out = {"solution": solution, "stats": {"iters": 0, "trace": [], "raw": raw}}
    tmp = Path(args.out + ".tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

CIRCLE_STUB = '''"""The decomposed program. Write it here (helper modules next to it are fine).

    construct(cfg, n, seed) -> (centers, radii)

cfg     dict, gene name -> value; every gene of genes.json is present
n       number of circles, from the instance
seed    the run seed; solver.py has already seeded `random` and `numpy.random` with it
return  centres, shape (n, 2), and radii, shape (n,), exactly as run_packing() of the original program
        would return them. solver.py repairs them afterwards; do not repair or "fix" anything here that
        the original programs do not.
"""


def construct(cfg, n, seed):
    raise NotImplementedError
'''

CIRCLE_INTERFACE = """\
solver/program.py must define `construct(cfg, n, seed) -> (centers, radii)`: `cfg` maps every gene name in
genes.json to its value, `n` is the number of circles from the instance (26 in both programs; keep layouts
that are written for 26 as they are), `seed` is the run seed. solver/solver.py (fixed, do not edit) seeds
`random` and `numpy.random` with the seed, calls construct, and ends every run with solver/repair.py
(fixed, do not edit): radii are shrunk until the packing passes the exact evaluator. The original programs
return (centers, radii, sum) from run_packing(); return the same centres and radii, before any repair."""

ADAPTERS = {
    "circle_packing": {
        "driver": CIRCLE_DRIVER,
        "wrapper": CIRCLE_WRAPPER,
        "stub": CIRCLE_STUB,
        "interface": CIRCLE_INTERFACE,
        "repair_source": ROOT / "baselines" / "openevolve" / "repair.py",
        "run": "python solver.py",
    },
}
FIXED_FILES = ("solver.py", "repair.py", "mendel.toml")


def adapter_for(problem) -> dict:
    if problem.name not in ADAPTERS:
        raise SystemExit(f"mendel explain has no adapter for problem {problem.name!r} yet "
                         f"(known: {', '.join(ADAPTERS)}); add one to mendel.explain.ADAPTERS")
    return ADAPTERS[problem.name]


def _load_repair(path: Path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(f"mendel_explain_repair_{abs(hash(str(path)))}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.repair


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _now() -> str:
    from mendel.ledger import now

    return now()


# --------------------------------------------------------------------------------------------
# Reference outputs of the two original programs
# --------------------------------------------------------------------------------------------

def run_original(adapter: dict, program: Path, seed: int, timeout: float = JOB_TIMEOUT) -> tuple[list | None, str, float]:
    """Run an original program with the harness's interpreter and seeded global generators.
    Returns (raw solution, error, wall seconds)."""
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    env.update({name: "1" for name in _THREADS})
    env["MPLBACKEND"] = "Agg"
    with tempfile.TemporaryDirectory(prefix="mendel-explain-") as tmp:
        driver, result = Path(tmp) / "driver.py", Path(tmp) / "out.json"
        driver.write_text(adapter["driver"])
        started = time.time()
        try:
            done = subprocess.run([sys.executable, str(driver), str(Path(program).resolve()), str(result), str(seed)],
                                  cwd=tmp, env=env, capture_output=True, text=True, timeout=timeout)
            error = "" if done.returncode == 0 else f"exit {done.returncode}: {done.stderr.strip()[-400:]}"
        except subprocess.TimeoutExpired:
            error = f"timed out after {timeout:g}s"
        wall = time.time() - started
        raw = None
        if not error:
            try:
                raw = json.loads(result.read_text())
            except (OSError, ValueError) as exc:
                error = f"no output written: {exc}"
    return raw, error, wall


def make_reference(problem, initial: Path, evolved: Path, seeds=(0, 1), log=print) -> dict:
    """Run both original programs on each seed, repair their outputs and score them with the trusted evaluator.

    {"seeds", "instance", "tolerance", "initial"/"evolved": {"sha256", "deterministic", "reproducible",
     "runs": {seed: {"raw", "solution", "score", "raw_valid", "raw_score", "wall"}}}}"""
    adapter = adapter_for(problem)
    repair = _load_repair(adapter["repair_source"])
    out: dict = {"seeds": list(seeds), "tolerance": TOLERANCE, "repair_sha256": _sha(adapter["repair_source"]),
                 "interpreter": sys.version.split()[0]}
    instance = None
    for role, program in (("initial", Path(initial)), ("evolved", Path(evolved))):
        runs: dict = {}
        jobs = [(s, k) for s in seeds for k in ((0, 1) if s == seeds[0] else (0,))]   # first seed twice
        with ThreadPoolExecutor(3) as pool:
            results = list(pool.map(lambda job: run_original(adapter, program, job[0]), jobs))
        repeat = None
        for (seed, k), (raw, error, wall) in zip(jobs, results):
            if raw is None:
                raise SystemExit(f"the {role} program failed to run (seed {seed}): {error}")
            if k == 1:
                repeat = raw
                continue
            fixed = repair(raw)
            if fixed is None:
                raise SystemExit(f"the {role} program's output could not be repaired (seed {seed})")
            if instance is None or role == "evolved":
                instance = next((i for i in problem.instances.get("train", []) if i.get("n") == len(raw)), None) \
                    or {"n": len(raw)}
            strict, scored = problem.evaluate(instance, raw), problem.evaluate(instance, fixed)
            if not scored["valid"]:
                raise SystemExit(f"the {role} program's repaired output is invalid: {scored['detail']}")
            runs[str(seed)] = {"raw": raw, "solution": fixed, "score": scored["score"], "raw_valid": strict["valid"],
                               "raw_score": strict["score"] if strict["valid"] else None,
                               "raw_sum": float(sum(c[2] for c in raw)), "wall": round(wall, 2)}
            log(f"  reference {role} seed {seed}: repaired score {scored['score']!r} "
                f"(as returned: {'valid' if strict['valid'] else 'invalid under the exact evaluator'}), {wall:.1f}s")
        first = runs[str(seeds[0])]["raw"]
        out[role] = {"path": str(program), "sha256": _sha(program), "runs": runs,
                     "reproducible": repeat == first,                                   # same seed, same output
                     "deterministic": all(r["raw"] == first for r in runs.values())}    # the seed does not matter
        if not out[role]["reproducible"]:
            log(f"  warning: the {role} program gave two different outputs for the same seed; the bookend check "
                "cannot hold exactly for it")
    out["instance"] = instance
    return out


# --------------------------------------------------------------------------------------------
# The bookend check
# --------------------------------------------------------------------------------------------

def bookend_configs(genes: list[dict]) -> tuple[dict, dict, dict]:
    """(all off, all on, all on with the alleles reset): every switch off and every allele at its `default`
    (the initial program); every switch on and every allele at its `evolved` value (the evolved program);
    every switch on and every allele back at `default`."""
    all_off = defaults(genes)
    all_on = {g["name"]: True if is_idea(g) else g.get("evolved", g["default"]) for g in genes}
    reset = {g["name"]: True if is_idea(g) else g["default"] for g in genes}
    return all_off, all_on, reset


def registry_problems(genes: list[dict]) -> list[str]:
    """What `mendel explain` needs from genes.json beyond PROTOCOL.md."""
    reasons = []
    if not any(g["kind"] == "switch" for g in genes):
        reasons.append("genes.json has no switch: every difference between the two programs must be a switch")
    for g in genes:
        name, kind = g["name"], g["kind"]
        if kind == "choice":
            reasons.append(f"gene {name!r}: use a switch (off = the initial program's behaviour), not a choice")
        elif kind == "switch":
            if not str(g.get("hypothesis") or "").strip():
                reasons.append(f"switch {name!r} needs a one-line 'hypothesis' saying what the change does")
            if g.get("evolved", True) is not True:
                reasons.append(f"switch {name!r}: 'evolved' must be true (on is the evolved program's behaviour)")
        else:
            value = g.get("evolved")
            ok = isinstance(value, int) and not isinstance(value, bool) if kind == "int" else \
                isinstance(value, (int, float)) and not isinstance(value, bool)
            if "evolved" not in g:
                reasons.append(f"allele {name!r} needs an 'evolved' value (its value in the evolved program; "
                               "'default' is its value in the initial program)")
            elif not ok or not g["low"] <= value <= g["high"]:
                reasons.append(f"allele {name!r}: 'evolved' must be a {kind} within low..high "
                               f"({g['low']!r}..{g['high']!r}), got {value!r}")
    return reasons


def solution_diff(a, b) -> tuple[float, str]:
    """(largest absolute difference between two solutions, where it is). Infinite when the shapes differ."""
    try:
        if len(a) != len(b):
            return float("inf"), f"{len(a)} circles versus {len(b)}"
        worst, where = 0.0, "identical"
        for i, (p, q) in enumerate(zip(a, b)):
            for name, u, v in zip("xyr", p, q):
                if not abs(float(u) - float(v)) <= worst:
                    worst, where = abs(float(u) - float(v)), f"circle {i}, {name}: {float(u)!r} versus {float(v)!r}"
        return worst, where
    except (TypeError, ValueError) as exc:
        return float("inf"), f"not comparable: {exc}"


def bookend_check(solver_dir, problem, reference: dict, *, tol: float | None = None, smoke: bool = True,
                  workers: int = 3, fixed_hashes: dict | None = None, run=None) -> dict:
    """The harness's own check of a decomposed solver. Nothing the session says is believed.

    What is compared, for every seed in the reference (default 0 and 1), on the reference instance:
      * the solver with every switch off and every allele at `default`, against the initial program;
      * the solver with every switch on and every allele at `evolved`, against the evolved program.
    Both sides are *repaired solutions*: the original program is run by the same interpreter with `random`
    and `numpy.random` seeded with the seed, and its returned packing goes through the same repair.py that
    ends every solver run. The check passes when every centre coordinate and every radius agrees within
    `tol` (1e-9) and the exact evaluator's scores agree within `tol`.
    With smoke=True every single-switch configuration (each switch alone off from all-on, alone on from
    all-off) and the all-on configuration with alleles reset must also run and give a valid solution, since
    those are the configurations the measurement needs.

    Returns {"ok", "reasons", "warnings", "checks", "max_diff": {"initial", "evolved"}, "runs"}."""
    from mendel.worker import run_job

    run = run or run_job
    tol = float(reference.get("tolerance", TOLERANCE) if tol is None else tol)
    solver_dir = Path(solver_dir)
    verdict: dict = {"ok": False, "reasons": [], "warnings": [], "checks": [], "max_diff": {}, "runs": 0,
                     "tolerance": tol}

    def record(name: str, ok: bool, detail: str) -> None:
        verdict["checks"].append({"name": name, "ok": ok, "detail": detail})

    # 1. the registry and the fixed files
    try:
        genes = load_genes(solver_dir)
        reasons = registry_problems(genes)
    except GeneError as exc:
        genes, reasons = [], [str(exc)]
    for name, digest in (fixed_hashes or {}).items():
        if not (solver_dir / name).exists() or _sha(solver_dir / name) != digest:
            reasons.append(f"solver/{name} was changed or removed; it is fixed (the harness restores it)")
    if reasons:
        verdict["reasons"] += reasons
        record("registry", False, "; ".join(reasons))
        return verdict
    switches = [g["name"] for g in genes if is_idea(g)]
    record("registry", True, f"{len(switches)} switches, {len(genes) - len(switches)} alleles")

    all_off, all_on, reset = bookend_configs(genes)
    instance = reference["instance"]
    seeds = [int(s) for s in reference["seeds"]]
    arms: dict[str, tuple[dict, int]] = {}
    for seed in seeds:
        arms[f"all off, seed {seed}"] = (all_off, seed)
        arms[f"all on, seed {seed}"] = (all_on, seed)
    if smoke:
        for name in switches:
            arms[f"only {name} off"] = ({**all_on, name: False}, seeds[0])
            arms[f"only {name} on"] = ({**all_off, name: True}, seeds[0])
        if reset != all_on:
            arms["all on, alleles at default"] = (reset, seeds[0])
    jobs = [make_job(solver_dir, problem.dir, config, instance, seed, BUDGET, JOB_TIMEOUT)
            for config, seed in arms.values()]
    with ThreadPoolExecutor(max(1, workers)) as pool:
        results = dict(zip(arms, pool.map(run, jobs)))
    verdict["runs"] = len(jobs)

    # 2. the two bookends
    for role, label in (("initial", "all off"), ("evolved", "all on")):
        worst = 0.0
        for seed in seeds:
            got, want = results[f"{label}, seed {seed}"], reference[role]["runs"][str(seed)]
            what = (f"bookend '{label}' (every switch {'off' if role == 'initial' else 'on'}, alleles at "
                    f"{'default' if role == 'initial' else 'evolved'}), seed {seed}")
            if not got["ok"]:
                verdict["reasons"].append(f"{what}: the solver failed to run: {got['error']}")
                worst = float("inf")
                continue
            if not got["valid"]:
                verdict["reasons"].append(f"{what}: the solver's output is invalid: {got['error']}")
                worst = float("inf")
                continue
            diff, where = solution_diff(got["solution"], want["solution"])
            gap = abs(got["score"] - want["score"])
            worst = max(worst, diff, gap)
            if not (diff <= tol and gap <= tol):
                raw = (got.get("stats") or {}).get("raw")
                raw_note = ""
                if raw is not None:
                    raw_diff, raw_where = solution_diff(raw, want["raw"])
                    raw_note = f" Before the repair the largest difference is {raw_diff:.3e} ({raw_where})."
                hint = (" The scores agree closely, so the structure is right and something small differs: a "
                        "constant, the order of floating-point operations, or an optimiser amplifying one of those."
                        if gap < 1e-4 else "")
                verdict["reasons"].append(
                    f"{what}: does not reproduce the {role} program. Score {got['score']!r}, the {role} program "
                    f"scores {want['score']!r} (difference {gap:.3e}); largest difference in the repaired "
                    f"solution {diff:.3e} ({where}); allowed {tol:g}.{raw_note}{hint}")
        verdict["max_diff"][role] = worst
        record(f"bookend: {label}", worst <= tol,
               f"largest difference from the {role} program over seeds {seeds}: {worst:.3e} (allowed {tol:g})")

    # 3. every configuration the measurement needs
    if smoke:
        bad, noop = [], []
        for arm, res in results.items():
            if arm.startswith("all o") and "alleles" not in arm:
                continue
            if not usable(res):
                bad.append(f"configuration '{arm}' {'failed' if not res['ok'] else 'gave an invalid solution'}: "
                           f"{str(res['error'])[-500:]}")
            elif arm.startswith("only "):
                base = results[f"all on, seed {seeds[0]}" if arm.endswith(" off") else f"all off, seed {seeds[0]}"]
                if base["ok"] and res["solution"] == base["solution"]:
                    noop.append(arm)
        verdict["reasons"] += bad[:6]
        for arm in noop:
            verdict["warnings"].append(f"'{arm}' gives exactly the same solution as its bookend; from that side "
                                       "the switch does nothing (fine if that is what the code really does)")
        record("single-switch configurations", not bad,
               bad[0] if bad else f"{len(arms) - 2 * len(seeds)} configurations ran and gave valid solutions")

    verdict["ok"] = not verdict["reasons"]
    return verdict


def format_verdict(verdict: dict) -> str:
    lines = ["PASS" if verdict["ok"] else "FAIL"]
    lines += [f"  [{'ok' if c['ok'] else 'FAILED'}] {c['name']}: {c['detail']}" for c in verdict["checks"]]
    lines += [f"  reason: {r}" for r in verdict["reasons"]]
    lines += [f"  warning: {w}" for w in verdict["warnings"]]
    return "\n".join(lines)


# --------------------------------------------------------------------------------------------
# Decompose: the one LLM step
# --------------------------------------------------------------------------------------------

TASK_TEMPLATE = """\
You are the decomposer of `mendel explain`. Mendel measures what an idea is worth by switching it off
(a knockout). Another system, an evolutionary coding agent, started from ./initial_program.py and
produced ./evolved_program.py. Nobody knows which of its changes matter, or whether the gain is new
structure or re-tuned constants. Your job is to make that measurable: rewrite the pair as ONE
parameterised program in ./solver in which every way the evolved program differs from the initial
program is a named switch, and changed numeric constants are named values ("alleles"). A harness then
measures every switch with no further help from you, so the decomposition has to be faithful.

Read first: PROBLEM.md, initial_program.py, evolved_program.py, solver/solver.py, solver/program.py.

{interface}

What to write
1. solver/program.py. With a switch off the code does, at that point, what the initial program does;
   with it on, what the evolved program does. Read switches and constants from `cfg` only.
2. solver/genes.json, {{"genes": [...]}}, with for every gene "name" (snake_case), "kind", "default",
   "evolved", "hypothesis", "author": "{author}", "added_gen": 1:
   - a switch per difference: "kind": "switch", "default": false, "evolved": true, and a one-line
     "hypothesis" saying what the change does and why it might help (plain words, no praise);
   - a numeric constant of the INITIAL program (changed by the evolution or not): "kind": "int" or
     "float", "of": null, "default": its initial value, "evolved": its value in the evolved program
     (equal to "default" if it is unchanged or no longer used), "low"/"high" a sensible range holding
     both, "log": true only for a range over orders of magnitude. Expose these even when unchanged: a
     tuner will vary them with every switch off, to see what tuning constants alone could have bought;
   - a numeric constant that exists only in new code of the evolved program: the same, with
     "of": "<the switch it belongs to>" and "default" equal to "evolved". Expose the ones that carry
     meaning (margins, safety factors, iteration counts, tolerances); at most about 12 alleles in all.
3. DECOMPOSITION.json in the current directory (see Finish).

The bookend check (run by the harness, and again after you finish; you cannot argue with it)
  - every switch off and every allele at "default" must reproduce the initial program's output;
  - every switch on and every allele at "evolved" must reproduce the evolved program's output;
  - "reproduce": on seeds {seeds}, after the same repair step, every centre coordinate, every radius and
    the score agree within {tol:g};
  - every single-switch configuration (one switch off from all-on, one switch on from all-off) must run
    and return a packing the wrapper can repair.

Rules
1. Granularity. A switch is one idea a person would name: a layout, an optimiser, a refinement pass,
   a radius rule. Not one switch for "the evolved program", and not one per line. Usually 4 to 10.
2. Independence. Make the switches as independent as the code allows: each must mean something when
   switched off alone and when switched on alone. If a stage has nothing to act on while another switch
   is off, let it act on what the previous stage produced when that is meaningful. If two changes cannot
   be separated at all, give them one switch, or keep two and state the dependence; either way record
   the pair under "inseparable" in DECOMPOSITION.json with the reason.
3. Fidelity. Move code rather than rewrite it. An optimiser amplifies a difference of one unit in the
   last place, so keep the arithmetic of both programs exactly as written: the same operations in the
   same order, the same library calls with the same arguments.
4. No clock. The solver must be deterministic, so wall-clock logic (time-outs, time-based iteration
   counts) must not influence the output: replace it by what it evaluates to in a normal run of the
   original and list it under "not_genes".
5. Random numbers. If a program draws random numbers, draw them with the same calls in the same order;
   the wrapper has seeded `random` and `numpy.random`. Code behind a switch that is off must not draw.
6. Differences that cannot change the output (names, comments, logging, plotting, dead code) are not
   genes; list them under "not_genes".
7. Edit only files under ./solver (not solver.py, repair.py or mendel.toml) and DECOMPOSITION.json.

Tools (the only shell commands you can run)
  ../tools/bookend.sh            the full check: both bookends and every single-switch configuration
  ../tools/bookend.sh --quick    the two bookends only (faster)
  ../tools/try.sh --set a=true b=0.3      one configuration, starting from all off; prints its score
  ../tools/try.sh --all-on --set a=false  the same, starting from all on

Finish
When ../tools/bookend.sh prints PASS, write DECOMPOSITION.json:
  {{"summary": "<two sentences: what the evolved program does differently>",
    "inseparable": [{{"switches": ["a", "b"], "why": "<why these could not be separated cleanly>"}}],
    "not_genes": ["<difference with no effect on the output, or replaced clock logic>"],
    "caveats": ["<anything a reader of the measurements must know>"]}}
Use empty lists where there is nothing to say. You have about {minutes} minutes; a faithful
decomposition that passes the check beats a finer one that does not.
"""

RETRY_TEMPLATE = """\

The harness re-ran the bookend check after your previous session and it did not pass. Your files are
still in ./solver. Fix them; do not start again unless you must. The harness's verdict:

{verdict}
"""


def render_problem(problem) -> str:
    return (f"# {problem.title}\n\n{problem.statement.strip()}\n\nObjective: "
            f"{'maximise' if problem.direction == 'max' else 'minimise'} the score.\n\n"
            "The evaluator is exact and trusted; a copy is in reference/evaluate.py. You cannot change it.\n")


def prepare_sandbox(problem, initial: Path, evolved: Path, workdir: Path, reference_path: Path) -> tuple[Path, dict]:
    """workdir/sandbox (what the session may edit) and workdir/tools (what it may run). Returns the sandbox
    and the hashes of the fixed solver files."""
    adapter = adapter_for(problem)
    sandbox, tools = workdir / "sandbox", workdir / "tools"
    solver = sandbox / "solver"
    solver.mkdir(parents=True, exist_ok=True)
    tools.mkdir(parents=True, exist_ok=True)
    shutil.copy(initial, sandbox / "initial_program.py")
    shutil.copy(evolved, sandbox / "evolved_program.py")
    (sandbox / "PROBLEM.md").write_text(render_problem(problem))
    (sandbox / "reference").mkdir(exist_ok=True)
    shutil.copy(problem.dir / "evaluate.py", sandbox / "reference" / "evaluate.py")
    hashes = write_fixed_files(problem, solver)
    if not (solver / "program.py").exists():
        (solver / "program.py").write_text(adapter["stub"])
    if not (solver / "genes.json").exists():
        (solver / "genes.json").write_text('{\n  "genes": []\n}\n')
    py = sys.executable
    base = f'--solver "{solver}" --problem "{problem.dir}"'
    scripts = {"bookend.sh": f'exec "{py}" -m mendel.explain bookend {base} --reference "{reference_path}" "$@"',
               "try.sh": f'exec "{py}" -m mendel.explain try {base} --reference "{reference_path}" "$@"'}
    for name, body in scripts.items():
        path = tools / name
        path.write_text(f'#!/bin/sh\ncd "{ROOT}" || exit 1\n{body}\n')
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return sandbox, hashes


def write_fixed_files(problem, solver: Path) -> dict:
    """(Re)write the files of a decomposed solver that the session must not change; returns their hashes."""
    adapter = adapter_for(problem)
    solver.mkdir(parents=True, exist_ok=True)
    (solver / "solver.py").write_text(adapter["wrapper"])
    shutil.copy(adapter["repair_source"], solver / "repair.py")
    (solver / "mendel.toml").write_text(f'problem = "{problem.name}"\nrun = "{adapter["run"]}"\n')
    return {name: _sha(solver / name) for name in FIXED_FILES}


def decompose(problem, initial: Path, evolved: Path, workdir: Path, reference: dict, *, model: str = "fable",
              effort: str = "high", attempts: int = 3, minutes: int = 20, timeout_s: int = 2400,
              max_budget_usd: float | None = None, workers: int = 3, log=print) -> dict:
    """Run the decomposition session(s) until the harness's own bookend check passes or attempts run out.

    Returns {"ok", "solver_dir", "verdict", "sessions": [{"cost_usd", "model", "seconds", "verdict"}],
             "cost_usd", "author", "notes"}."""
    workdir = Path(workdir).resolve()
    reference_path = workdir / "reference.json"
    workdir.mkdir(parents=True, exist_ok=True)
    reference_path.write_text(json.dumps(reference))
    sandbox, hashes = prepare_sandbox(problem, Path(initial), Path(evolved), workdir, reference_path)
    adapter = adapter_for(problem)
    author = f"llm:{model}"
    base_prompt = TASK_TEMPLATE.format(interface=adapter["interface"], author=author, minutes=minutes,
                                       seeds=" and ".join(str(s) for s in reference["seeds"]),
                                       tol=reference.get("tolerance", TOLERANCE))
    allowed = ",".join(["Read", "Edit", "Write", "Glob", "Grep"]
                       + [f"Bash(../tools/{t}.sh{suffix})" for t in ("bookend", "try") for suffix in ("", " *")])
    cmd = ["claude", "-p", "--model", model, "--effort", effort, "--safe-mode", "--no-chrome",
           "--permission-mode", "acceptEdits", "--permission-prompts", "none",
           "--allowedTools", allowed, "--output-format", "json", "--no-session-persistence"]
    if max_budget_usd:
        cmd += ["--max-budget-usd", str(max_budget_usd)]
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}   # the user's Claude login, never a key

    out: dict = {"ok": False, "solver_dir": str(sandbox / "solver"), "sessions": [], "cost_usd": 0.0,
                 "author": author, "verdict": None, "notes": {}}
    prompt = base_prompt
    for attempt in range(1, max(1, attempts) + 1):
        (sandbox / "TASK.md").write_text(prompt)
        log(f"  decomposition session {attempt}/{attempts} ({model}) ...")
        session: dict = {"attempt": attempt, "cost_usd": 0.0, "model": None, "seconds": 0.0}
        started = time.time()
        try:
            done = subprocess.run(cmd, cwd=sandbox, input=prompt, capture_output=True, text=True,
                                  timeout=timeout_s, env=env)
            (workdir / f"session{attempt}.json").write_text(done.stdout or done.stderr or "")
            try:
                result = json.loads(done.stdout)
                session["cost_usd"] = float(result.get("total_cost_usd") or 0.0)
                session["model"] = next(iter(result.get("modelUsage") or {}), None)
                session["turns"] = result.get("num_turns")
            except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
                session["error"] = "the session's output was not JSON"
        except subprocess.TimeoutExpired:
            session["error"] = f"the session timed out after {timeout_s}s"
        except FileNotFoundError:
            raise SystemExit("the `claude` CLI is not installed; pass --solver DIR to use an existing decomposition")
        session["seconds"] = round(time.time() - started, 1)
        out["cost_usd"] = round(out["cost_usd"] + session["cost_usd"], 6)
        if session["model"]:
            out["author"] = author = f"llm:{session['model']}"

        restored = [n for n in FIXED_FILES if not (sandbox / "solver" / n).exists()
                    or _sha(sandbox / "solver" / n) != hashes[n]]
        if restored:   # never trust the session with the wrapper or the repair step
            write_fixed_files(problem, sandbox / "solver")
            session["restored"] = restored
        verdict = bookend_check(sandbox / "solver", problem, reference, workers=workers, fixed_hashes=hashes)
        session["verdict"] = verdict
        out["sessions"].append(session)
        out["verdict"] = verdict
        log(f"  session {attempt}: {session['seconds']:.0f}s, ${session['cost_usd']:.2f}; bookend check: "
            + format_verdict(verdict).replace("\n", "\n    "))
        if verdict["ok"]:
            out["ok"] = True
            break
        prompt = base_prompt + RETRY_TEMPLATE.format(verdict=format_verdict(verdict))

    try:
        notes = json.loads((sandbox / "DECOMPOSITION.json").read_text())
        out["notes"] = notes if isinstance(notes, dict) else {}
    except (OSError, ValueError):
        out["notes"] = {}
    if out["ok"]:   # normalise the bookkeeping fields ourselves, as the inventor does
        path = sandbox / "solver" / "genes.json"
        registry = json.loads(path.read_text())
        for g in registry["genes"]:
            g["author"], g["added_gen"] = author, 1
            g.setdefault("of", None)
        path.write_text(json.dumps(registry, indent=2) + "\n")
    return out


# --------------------------------------------------------------------------------------------
# Measure (no LLM)
# --------------------------------------------------------------------------------------------

def _slim(result: dict) -> dict:
    """An experiment result without its per-pair rows."""
    return {k: v for k, v in result.items() if k not in ("pairs", "per_instance")}


def _spread(runs: dict) -> float | None:
    """Largest difference between two seeds' scores within one arm (0 for a deterministic solver)."""
    by_key: dict = {}
    for (key, _seed), res in runs.items():
        if usable(res):
            by_key.setdefault(key, []).append(res["score"])
    spreads = [max(v) - min(v) for v in by_key.values() if len(v) > 1]
    return max(spreads) if spreads else None


def measure(executor, problem, solver_dir, *, seeds, tune_seeds, confirm_seeds, tune_trials: int = 40,
            pairwise_top: int = 3, instances: list[dict] | None = None, log=print) -> dict:
    """Every intervention on a decomposed solver. Effects are in score units, positive means better.

    knockouts   all on, minus all on with that switch off   (what the evolved program loses without it)
    alone       all off with that switch on, minus all off  (what it adds on its own)
    pairs       synergy between the top `pairwise_top` switches by knockout size, from the all-on side
    tuning      all off with the alleles tuned, minus all off      (what constants alone can buy)
    constants   all on, minus all on with alleles at `default`     (what the evolved constants are worth)
    """
    from mendel import experiments
    from mendel.tune import tune

    seeds, tune_seeds, confirm_seeds = list(seeds), list(tune_seeds), list(confirm_seeds)
    genes = load_genes(solver_dir)
    all_off, all_on, reset = bookend_configs(genes)
    instances = instances or problem.instances.get("train", [])
    keys = [problem.key(i) for i in instances]
    switches = [g["name"] for g in genes if is_idea(g)]

    log(f"  bookend arms on {len(seeds)} seeds ...")
    arms = {"all_off": (solver_dir, all_off), "all_on": (solver_dir, all_on), "reset": (solver_dir, reset)}
    runs = experiments.run_arms(executor, problem, arms, instances, seeds, BUDGET)
    total = experiments.contrast(problem, runs, {"all_on": 1.0, "all_off": -1.0}, keys, seeds)
    constants = experiments.contrast(problem, runs, {"all_on": 1.0, "reset": -1.0}, keys, seeds)
    scores = {arm: experiments._mean_score(problem, runs[arm], keys, seeds) for arm in arms}
    if scores["all_on"] is None or scores["all_off"] is None:
        raise RuntimeError("a bookend configuration has no usable runs; the decomposition is broken")
    spreads = {arm: _spread(runs[arm]) for arm in arms}

    log(f"  knockouts of {len(switches)} switches from the all-on configuration ...")
    knockouts = experiments.knockouts(executor, problem, solver_dir, all_on, instances, seeds, BUDGET)
    log("  each switch alone from the all-off configuration ...")
    alone = experiments.knockins(executor, problem, solver_dir, all_off, instances, seeds, BUDGET)

    top = sorted((n for n in switches if knockouts[n]["runs"]), key=lambda n: -abs(knockouts[n]["effect"]))
    pairs = list(itertools.combinations(top[:max(0, pairwise_top)], 2))
    log(f"  pairwise knockouts: {', '.join(f'{a} x {b}' for a, b in pairs) or 'none'} ...")
    interactions = experiments.pairwise(executor, problem, solver_dir, all_on, pairs, instances, seeds,
                                        BUDGET) if pairs else []

    tunable = [g["name"] for g in genes if not is_idea(g) and g.get("of") is None and g["low"] < g["high"]]
    log(f"  tuning only: {len(tunable)} alleles of the initial program, {tune_trials} trials, switches off ...")
    tuned = tune(executor, problem, solver_dir, instances=instances, seeds=tune_seeds, budget=BUDGET,
                 base_config=all_off, n_trials=tune_trials if tunable else 0, alleles_only=True,
                 confirm_seeds=confirm_seeds)
    tuning = experiments.compare(executor, problem, solver_dir, tuned["config"], all_off, instances, seeds, BUDGET)
    decomposition = experiments.decomposition(executor, problem, solver_dir, solver_dir, all_on, instances, seeds,
                                              BUDGET, tuned_seed_config=tuned["config"])
    decomposition = {"seed": decomposition["seed"], "tuning": decomposition["tuning"],
                     "ideas": decomposition["ideas"], "compute": 0.0, "unit": decomposition["unit"]}

    best = {}
    for key in keys:
        good = [r for (k, _s), r in runs["all_on"].items() if k == key and usable(r)]
        if good:
            best[key] = max(good, key=lambda r: problem.sign * r["score"])
    return {
        "configs": {"all_off": all_off, "all_on": all_on, "reset": reset, "tuned_off": tuned["config"]},
        "instances": keys, "seeds": seeds, "tune_seeds": tune_seeds, "confirm_seeds": confirm_seeds,
        "scores": scores, "spreads": spreads, "total": _slim(total), "constants": _slim(constants),
        "reset_differs": reset != all_on,
        "knockouts": {n: _slim(r) for n, r in knockouts.items()},
        "alone": {n: _slim(r) for n, r in alone.items()},
        "interactions": interactions,
        "tuning": {**_slim(tuning), "tunable": tunable, "trials": len(tuned["trials"]),
                   "changed": {n: [all_off[n], tuned["config"][n]] for n in tunable
                               if tuned["config"][n] != all_off[n]}},
        "decomposition": decomposition,
        "champion_scores": {key: {"mean": scores["all_on"], "best": r["score"], "runs": len(seeds),
                                  "budget": "one run to completion"} for key, r in best.items()},
        "champion_solutions": {key: r["solution"] for key, r in best.items()},
    }


# --------------------------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------------------------

def _fmt(result: dict | None, digits: int = 4) -> str:
    if not result or not result.get("runs"):
        return "not measurable (the configuration failed)"
    lo, hi = result["ci"]
    return f"{result['effect']:+.{digits}f} [{lo:+.{digits}f}, {hi:+.{digits}f}]"


def classify(result: dict | None, gain: float) -> str:
    """A switch's knockout in words. `gain` is the evolved program's score minus the initial program's."""
    if not result or not result.get("runs"):
        return "not measurable"
    effect, (lo, hi) = result["effect"], result["ci"]
    if abs(effect) <= NEGLIGIBLE and -NEGLIGIBLE <= lo and hi <= NEGLIGIBLE:
        return "no effect"
    if gain > 0 and lo > gain + NEGLIGIBLE:
        # Without it the program scores below the initial program: the other switches fail without this
        # one. That is a dependence between switches, not the size of this switch's own contribution.
        return "breaks the rest"
    if lo > 0:
        return "carries gain" if gain > 0 and effect >= 0.01 * gain else "small gain"
    if hi < 0:
        return "hurts"
    return "inconclusive"


def _pct(value: float, gain: float) -> str:
    return f"{100.0 * value / gain:.0f}%" if abs(gain) > NEGLIGIBLE else "n/a"


def _rel(path) -> str:
    """A path relative to the project root when it is inside it (reports are meant to be published)."""
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return Path(path).name


def build_state(run_id: str, problem, info: dict) -> dict:
    """state.json in the PROTOCOL.md format, plus an "explain" section with everything else."""
    m, genes = info.get("measure"), info.get("genes") or []
    state = {
        "run": {"id": run_id, "problem": problem.name, "title": f"Explain: {problem.title}",
                "direction": problem.direction, "started": info["started"], "updated": _now(),
                "status": info.get("status", "running"), "generation": 1 if m else 0,
                "spend": info["spend"], "problem_dir": str(problem.dir), "kind": "explain"},
        "instances": {split: problem.keys(split) for split in problem.instances},
        "best_known": dict(problem.best_known),
        "champion": {"config": {}, "solver_version": "", "scores": {}, "solutions": {}},
        "genes": [], "interactions": [], "decomposition": None, "records": [],
        "history": info.get("history", []), "timeline": [],
        "explain": {k: info.get(k) for k in ("initial", "evolved", "bookend", "sessions", "notes", "settings")},
    }
    if not m:
        return state
    gain = m["total"]["effect"]
    state["champion"] = {"config": m["configs"]["all_on"], "solver_version": info.get("solver_version", ""),
                         "solver_dir": info.get("solver_dir"), "scores": m["champion_scores"],
                         "solutions": m["champion_solutions"]}
    for g in genes:
        entry = {k: g[k] for k in ("name", "kind", "author", "added_gen", "hypothesis", "of", "default", "evolved",
                                   "low", "high", "log") if k in g}
        entry.update(status="active", value=m["configs"]["all_on"][g["name"]])
        if is_idea(g):
            ko, on = m["knockouts"].get(g["name"]), m["alone"].get(g["name"])
            if ko and ko["runs"]:
                entry["knockout"] = {"effect": ko["effect"], "ci": ko["ci"], "runs": ko["runs"], "generation": 1}
            if on and on["runs"]:   # "screen": on versus off in the context of the initial program
                entry["screen"] = {"effect": on["effect"], "ci": on["ci"], "runs": on["runs"], "generation": 1,
                                   "context": "all switches off"}
            entry["verdict"] = classify(ko, gain)
        state["genes"].append(entry)
    state["interactions"] = [{**i, "generation": 1} for i in m["interactions"]]
    state["decomposition"] = m["decomposition"]
    key = m["instances"][0]
    state["timeline"] = [{"t": 0.0, "generation": 0, "score": problem.normalised(key, m["scores"]["all_off"])},
                         {"t": round(info.get("elapsed", 1.0), 1), "generation": 1,
                          "score": problem.normalised(key, m["scores"]["all_on"])}]
    state["engine"] = {"config": {"budget": dict(BUDGET), "seeds": len(m["seeds"])}}   # for `mendel knockout`
    state["explain"]["measure"] = {k: v for k, v in m.items() if k != "champion_solutions"}
    return state


def build_report(run_id: str, problem, info: dict) -> str:
    m, genes, ref, bookend = info["measure"], info["genes"], info["reference"], info["bookend"]
    notes = info.get("notes") or {}
    switches = [g for g in genes if is_idea(g)]
    alleles = [g for g in genes if not is_idea(g)]
    gain = m["total"]["effect"]
    off, on = m["scores"]["all_off"], m["scores"]["all_on"]
    key = m["instances"][0]
    deterministic = all(v is not None and v == 0 for v in m["spreads"].values()) if len(m["seeds"]) > 1 else None
    order = sorted(switches, key=lambda g: -(m["knockouts"].get(g["name"]) or {}).get("effect", 0.0))
    L: list[str] = []
    L += [f"# What did the evolution add? `{run_id}`", "",
          f"Problem: {problem.title}. Instance {key}; best known {problem.best_known.get(key, 'n/a')}.", "",
          f"- initial program: `{_rel(ref['initial']['path'])}` (sha256 {ref['initial']['sha256'][:12]})",
          f"- evolved program: `{_rel(ref['evolved']['path'])}` (sha256 {ref['evolved']['sha256'][:12]})",
          f"- decomposed by: {info.get('author', 'n/a')}, {len(info.get('sessions') or [])} session(s), "
          f"${info['spend']['llm_usd']:.2f}; everything below the bookend check is measured without an LLM "
          f"({info['spend']['evaluations']} solver runs).", ""]

    L += ["## In short", ""]
    L.append(f"The initial program scores {off:.6f} and the evolved program {on:.6f} after the same repair step "
             f"(strictly feasible, exact evaluator): a gain of {gain:+.6f}.")
    for g in order:
        ko, verdict = m["knockouts"].get(g["name"]), classify(m["knockouts"].get(g["name"]), gain)
        if verdict == "carries gain":
            L.append(f"- Without `{g['name']}` the evolved program loses {ko['effect']:.4f} "
                     f"({_pct(ko['effect'], gain)} of the gain) and scores {on - ko['effect']:.4f}.")
        elif verdict == "breaks the rest":
            others = []
            for i in m["interactions"]:
                if g["name"] in (i["a"], i["b"]):
                    other, worth = (i["b"], i["effect_a"]) if i["a"] == g["name"] else (i["a"], i["effect_b"])
                    others.append(f"with `{other}` off as well, `{g['name']}` is worth {worth:+.4f}")
            L.append(f"- Without `{g['name']}` the evolved program scores {on - ko['effect']:.4f}, below the initial "
                     f"program: the other switches fail without it. That is a dependence between switches, not "
                     f"the size of its own contribution" + (" (" + "; ".join(others) + ")" if others else "") + ".")
    for label, text in (("no effect", "No effect when switched off from the evolved program (the score does not move)"),
                        ("small gain", "Worth less than 1% of the gain each"),
                        ("hurts", "Hurts: the evolved program scores higher without it"),
                        ("inconclusive", "Interval spans zero"),
                        ("not measurable", "Could not be measured (the configuration failed)")):
        names = [f"`{g['name']}`" + (f" ({m['knockouts'][g['name']]['effect']:+.4f})" if label == "hurts" else "")
                 for g in order if classify(m["knockouts"].get(g["name"]), gain) == label]
        if names:
            L.append(f"- {text}: {', '.join(names)}.")
    solo = sorted(((m["alone"][g["name"]]["effect"], g["name"]) for g in switches
                   if (m["alone"].get(g["name"]) or {}).get("runs")), reverse=True)
    if solo:
        L.append("- Added alone to the initial program: "
                 + ", ".join(f"`{name}` {effect:+.4f} ({_pct(effect, gain)})" for effect, name in solo) + ".")
    t = m["tuning"]
    if t["tunable"]:
        L.append(f"- Constants alone (a counterfactual, not what the evolution did): tuning the {len(t['tunable'])} "
                 f"constant(s) of the initial program with every switch off ({t['trials']} trials) reaches "
                 f"{off + t['effect']:.4f}, that is {_fmt(t)}, {_pct(t['effect'], gain)} of the gain.")
    else:
        L.append("- Constants alone: the decomposition exposes no constant of the initial program, so there was "
                 "nothing to tune.")
    if m["reset_differs"]:
        L.append(f"- The evolved constants: with every switch on, putting the alleles back at their initial values "
                 f"changes the score by {_fmt({**m['constants'], 'effect': -m['constants']['effect'], 'ci': [-m['constants']['ci'][1], -m['constants']['ci'][0]]})}.")
    else:
        L.append("- No constant of the initial program has a different value in the evolved program: every changed "
                 "number belongs to new code behind a switch, so the gain is structure, not re-tuning of what was there.")
    L.append("")

    L += ["## The bookend check", "",
          "The decomposition is trusted only as far as this check, which the harness runs itself: "
          f"on seeds {ref['seeds']} and instance {key}, the decomposed solver with every switch off and every "
          "allele at its initial value is compared with the initial program, and with every switch on and every "
          "allele at its evolved value with the evolved program. Both sides are repaired solutions (the original "
          "program run by the same interpreter with `random` and `numpy.random` seeded, its packing passed "
          f"through the same `repair.py`). It passes when every centre coordinate, every radius and the exact score "
          f"agree within {bookend['tolerance']:g}.", "",
          f"- result: **{'passed' if bookend['ok'] else 'FAILED'}** "
          + (f"after {len(info['sessions'])} decomposition session(s)" if info.get("sessions")
             else "for a decomposed solver that was given (no LLM session in this run)")
          + f"; {bookend.get('runs', 0)} solver runs, including every single-switch configuration",
          f"- largest difference, all off versus the initial program: {bookend['max_diff'].get('initial', float('nan')):.3e}",
          f"- largest difference, all on versus the evolved program: {bookend['max_diff'].get('evolved', float('nan')):.3e}"]
    for role in ("initial", "evolved"):
        r = ref[role]["runs"][str(ref["seeds"][0])]
        L.append(f"- the {role} program as returned is {'valid' if r['raw_valid'] else 'invalid'} under the exact "
                 f"evaluator (sum of radii {r['raw_sum']:.9f}); repaired it scores {r['score']:.9f}")
    if not bookend["ok"]:
        L += ["", "**The check failed, so the numbers below describe the decomposed solver, not the evolved program:**"]
        L += [f"- {r}" for r in bookend["reasons"]]
    L += [f"- warning: {w}" for w in bookend.get("warnings", [])]
    L.append("")

    L += ["## Switches", "",
          "Knockout: all on minus all on with this switch off (what the evolved program loses without it). "
          "Alone: all off with this switch on minus all off (what it adds to the initial program by itself). "
          "Score units; brackets are 95% paired-bootstrap intervals over seeds.", "",
          "| switch | what the change does (the decomposer's words) | knockout | share of gain | alone | verdict |",
          "|---|---|---|---|---|---|"]
    for g in order:
        ko, al = m["knockouts"].get(g["name"]), m["alone"].get(g["name"])
        share = _pct(ko["effect"], gain) if ko and ko["runs"] else "n/a"
        L.append(f"| `{g['name']}` | {str(g.get('hypothesis', '')).replace('|', '/')} | {_fmt(ko)} | {share} | "
                 f"{_fmt(al)} | {classify(ko, gain)} |")
    L += ["", "Shares need not add up to 100%: switches overlap and depend on each other (next section)."]
    if deterministic:
        L += ["", f"Every arm gave the same score on all {len(m['seeds'])} seeds: neither program draws random "
              "numbers, so each effect is an exact difference and its interval has zero width. The intervals say "
              "nothing about other instances or other runs of the evolution."]
    L.append("")

    if m["interactions"]:
        L += ["## Pairs", "",
              "Synergy = (both on) - (only a on) - (only b on) + (both off), other switches on. Positive: the two "
              "only pay off together. Negative: they overlap (each can stand in for the other). The last three "
              "columns are relative to the evolved program with both switched off.", "",
              "| a | b | synergy | a and b together | a without b | b without a |", "|---|---|---|---|---|---|"]
        for i in m["interactions"]:
            L.append(f"| `{i['a']}` | `{i['b']}` | {_fmt({'effect': i['synergy'], 'ci': i['ci'], 'runs': i['runs']})} | "
                     f"{i['pair_effect']:+.4f} | {i['effect_a']:+.4f} | {i['effect_b']:+.4f} |")
        L.append("")

    L += ["## Constants", ""]
    if alleles:
        L += ["| allele | belongs to | initial | evolved | tuned with switches off |", "|---|---|---|---|---|"]
        for g in alleles:
            tuned = m["configs"]["tuned_off"][g["name"]] if g["name"] in t["tunable"] else "not tuned"
            L.append(f"| `{g['name']}` | {g.get('of') or 'the initial program'} | {g['default']} | "
                     f"{g.get('evolved', g['default'])} | {tuned if isinstance(tuned, str) else f'{tuned:.6g}'} |")
        L.append("")
    L.append(f"- Tuning only (every switch off, the initial program's constants tuned by Optuna on seeds "
             f"{m['tune_seeds']}, confirmed on {m['confirm_seeds']}, measured on {m['seeds']}): {_fmt(t)}, "
             f"that is {off + t['effect']:.4f} against {on:.4f} for the evolved program.")
    L.append(f"- The evolved score split the way Mendel splits a champion: initial program "
             f"{m['decomposition']['seed']:.4f}, plus {m['decomposition']['tuning']:+.4f} that tuning the initial "
             f"program's own constants could have bought, plus {m['decomposition']['ideas']:+.4f} that needs the "
             "new structure. The middle term is a counterfactual: it says how much of the gain was within reach "
             "of a tuner, not that the evolved program got it that way.")
    L.append("")

    L += ["## What could not be separated", ""]
    insep = [i for i in notes.get("inseparable") or [] if isinstance(i, dict)]
    L += [f"- {' + '.join(f'`{s}`' for s in i.get('switches', []))}: {i.get('why', '')}" for i in insep] or \
        ["- The decomposer reported no inseparable pairs."]
    if notes.get("not_genes"):
        L += ["", "Differences that are not switches (no effect on the output, or clock logic that was fixed):"]
        L += [f"- {x}" for x in notes["not_genes"]]
    if notes.get("caveats"):
        L += ["", "The decomposer's caveats:"] + [f"- {x}" for x in notes["caveats"]]
    L += ["", "This section is the decomposer's own account and is not measured."]
    L.append("")

    L += ["## Limits", "",
          "- This is one decomposition of several possible ones. Another split into switches would give different "
          "rows, and the sizes of effects depend on where the lines are drawn.",
          "- It is only as faithful as the bookend check: the two end points are verified, the configurations "
          "in between are the decomposer's reading of the code.",
          "- A knockout is measured with everything else on, `alone` with everything else off; an effect in "
          "another context can differ. Pairs are measured only for the top few.",
          f"- One instance ({key}) and the output of one evolution run. Nothing here says the same switches would "
          "matter at another size or in another run.",
          "- Scores are after the repair step, so a switch that only changes how much the repair has to shrink "
          "is measured through that.", ""]
    return "\n".join(L)


# --------------------------------------------------------------------------------------------
# The command
# --------------------------------------------------------------------------------------------

def run_explain(*, problem_dir, initial, evolved, run_id: str, runs_dir="runs", model: str = "fable",
                effort: str = "high", executor: str = "local", workers: int = 3, seeds: int = 4,
                seed_base: int = 1000, tune_trials: int = 40, pairwise_top: int = 3, attempts: int = 3,
                minutes: int = 20, timeout_s: int = 2400, max_budget_usd: float | None = None, solver=None,
                stage: str = "all", overwrite: bool = False, log=print) -> Path:
    """Decompose, measure and report. Returns the run directory.

    solver: an existing decomposed solver directory; the LLM step is skipped and it is checked and measured.
    stage:  "decompose" stops after the bookend check; "measure" needs a decomposition from an earlier call."""
    from mendel.executor import CachedExecutor, MeteredExecutor, make_executor
    from mendel.ledger import write_json_atomic
    from mendel.problem import load_problem
    from mendel.solver import copy_sources, solver_version

    problem = load_problem(problem_dir)
    adapter_for(problem)
    initial, evolved = Path(initial).resolve(), Path(evolved).resolve()
    run_dir = Path(runs_dir) / run_id
    progress = run_dir / "explain.json"
    if run_dir.exists() and overwrite:
        shutil.rmtree(run_dir)
    info = json.loads(progress.read_text()) if progress.exists() else None
    if info is None:
        if run_dir.exists() and any(run_dir.iterdir()):
            raise SystemExit(f"{run_dir} exists and is not an explain run; choose another --run-id")
        run_dir.mkdir(parents=True, exist_ok=True)
        info = {"started": _now(), "history": [], "sessions": [], "status": "running",
                "spend": {"llm_calls": 0, "llm_usd": 0.0, "cpu_seconds": 0.0, "evaluations": 0}}
    info.update(initial=str(initial), evolved=str(evolved),
                settings={"model": model, "effort": effort, "seeds": seeds, "seed_base": seed_base,
                          "tune_trials": tune_trials, "pairwise_top": pairwise_top, "attempts": attempts})
    t0 = time.time()

    def save(event: str | None = None, detail: str = "", gene: str | None = None) -> None:
        if event:
            entry = {"t": _now(), "generation": 1 if info.get("measure") else 0, "event": event, "detail": detail}
            if gene:
                entry["gene"] = gene
            info["history"].append(entry)
        info["elapsed"] = info.get("elapsed_before", 0.0) + time.time() - t0
        write_json_atomic(progress, info)
        write_json_atomic(run_dir / "state.json", build_state(run_id, problem, info))

    # 0. the two programs' own outputs
    if "reference" not in info or info["reference"]["initial"]["sha256"] != _sha(initial) \
            or info["reference"]["evolved"]["sha256"] != _sha(evolved):
        log("reference runs of the two programs ...")
        info["reference"] = make_reference(problem, initial, evolved, log=log)
        for name in ("solver_dir", "bookend", "measure"):
            info.pop(name, None)
        (run_dir / "inputs").mkdir(exist_ok=True)
        shutil.copy(initial, run_dir / "inputs" / "initial_program.py")
        shutil.copy(evolved, run_dir / "inputs" / "evolved_program.py")
        r = info["reference"]
        save("explain_started", f"initial {r['initial']['runs']['0']['score']:.6f}, evolved "
             f"{r['evolved']['runs']['0']['score']:.6f} (repaired, exact evaluator)")
    reference = info["reference"]

    # 1. decompose
    final = run_dir / "solver"
    if solver is not None:
        log(f"using the decomposed solver in {solver}")
        if final.exists():
            shutil.rmtree(final)
        copy_sources(solver, final)
        hashes = write_fixed_files(problem, final)
        info["bookend"] = bookend_check(final, problem, reference, workers=workers, fixed_hashes=hashes)
        info["author"] = info.get("author") or "given"
        log(format_verdict(info["bookend"]))
        save("bookend_check", ("passed" if info["bookend"]["ok"] else "FAILED") + f" for the solver given ({solver})")
    elif not (info.get("bookend") or {}).get("ok") and stage in ("all", "decompose"):
        log("decomposing (LLM step) ...")
        result = decompose(problem, initial, evolved, run_dir / "decompose", reference, model=model, effort=effort,
                           attempts=attempts, minutes=minutes, timeout_s=timeout_s, max_budget_usd=max_budget_usd,
                           workers=workers, log=log)
        for s in result["sessions"]:
            info["sessions"].append({k: v for k, v in s.items() if k != "verdict"})
            info["spend"]["llm_calls"] += 1
            info["spend"]["llm_usd"] = round(info["spend"]["llm_usd"] + s["cost_usd"], 6)
            v = s["verdict"]
            info["history"].append({"t": _now(), "generation": 0, "event": "decompose_session",
                                    "detail": f"session {s['attempt']}: {s['seconds']:.0f}s, ${s['cost_usd']:.2f}; "
                                              f"bookend check {'passed' if v['ok'] else 'failed: ' + ' | '.join(v['reasons'])[:600]}"})
        info["bookend"], info["notes"], info["author"] = result["verdict"], result["notes"], result["author"]
        if final.exists():
            shutil.rmtree(final)
        copy_sources(result["solver_dir"], final)
        if (Path(result["solver_dir"]).parent / "DECOMPOSITION.json").exists():
            shutil.copy(Path(result["solver_dir"]).parent / "DECOMPOSITION.json", run_dir / "DECOMPOSITION.json")
        save("bookend_check", "passed" if result["ok"] else "FAILED after every attempt")
    if not info.get("bookend"):
        raise SystemExit("there is no decomposition yet; run the decompose stage or pass --solver DIR")
    if not info["bookend"]["ok"]:
        info["status"] = "failed: bookend check"
        save()
        log(f"the bookend check did not pass; not measuring. See {progress}")
        return run_dir
    info["solver_dir"] = str(final.resolve())
    info["solver_version"] = solver_version(final)
    info["genes"] = load_genes(final)
    if stage == "decompose":
        save()
        return run_dir

    # 2. measure
    def metered(n: int, cpu: float) -> None:
        info["spend"]["evaluations"] += n
        info["spend"]["cpu_seconds"] = round(info["spend"]["cpu_seconds"] + cpu, 3)

    inner = make_executor(executor, workers)
    ex = CachedExecutor(MeteredExecutor(inner, metered), run_dir / "cache.sqlite")
    try:
        log("measuring (no LLM) ...")
        info["history"] = [h for h in info["history"] if h["event"] not in ("knockout", "explain_finished")]
        info["measure"] = measure(ex, problem, final, seeds=range(seed_base, seed_base + seeds),
                                  tune_seeds=range(seeds), confirm_seeds=range(100, 100 + seeds),
                                  tune_trials=tune_trials, pairwise_top=pairwise_top,
                                  instances=[reference["instance"]], log=log)
    finally:
        ex.close()
    m = info["measure"]
    for name, ko in m["knockouts"].items():
        info["history"].append({"t": _now(), "generation": 1, "event": "knockout", "gene": name,
                                "detail": f"knockout {_fmt(ko)}; alone {_fmt(m['alone'].get(name))}"})

    # 3. report
    info["status"] = "finished"
    save("explain_finished", f"gain {m['total']['effect']:+.6f}: tuning alone {m['tuning']['effect']:+.6f}, "
         f"{len(m['knockouts'])} switches measured")
    (run_dir / "report.md").write_text(build_report(run_id, problem, info))
    log(f"wrote {run_dir / 'state.json'} and {run_dir / 'report.md'}")
    return run_dir


# --------------------------------------------------------------------------------------------
# Sandbox tools
# --------------------------------------------------------------------------------------------

def _tool_bookend(args) -> int:
    from mendel.problem import load_problem

    problem = load_problem(args.problem)
    reference = json.loads(Path(args.reference).read_text())
    solver = Path(args.solver)
    hashes = None
    with tempfile.TemporaryDirectory() as tmp:   # what the fixed files must hash to
        hashes = write_fixed_files(problem, Path(tmp))
    verdict = bookend_check(solver, problem, reference, smoke=not args.quick, fixed_hashes=hashes)
    print(format_verdict(verdict))
    return 0 if verdict["ok"] else 1


def _tool_try(args) -> int:
    from mendel.problem import load_problem
    from mendel.worker import run_job

    problem = load_problem(args.problem)
    reference = json.loads(Path(args.reference).read_text())
    genes = load_genes(args.solver)
    all_off, all_on, _ = bookend_configs(genes)
    config = dict(all_on if args.all_on else all_off)
    for item in args.set or []:
        name, _, value = item.partition("=")
        if name not in config:
            raise SystemExit(f"unknown gene {name!r}; genes: {', '.join(config)}")
        try:
            config[name] = json.loads(value)
        except json.JSONDecodeError:
            config[name] = value
    res = run_job(make_job(args.solver, problem.dir, config, reference["instance"], args.seed, BUDGET, JOB_TIMEOUT))
    if not usable(res):
        print(f"FAILED: {res['error']}")
        return 1
    raw = (res.get("stats") or {}).get("raw") or []
    print(f"score {res['score']!r} (valid; sum of radii before the repair {sum(c[2] for c in raw)!r}), "
          f"{res['wall']:.1f}s")
    for role in ("initial", "evolved"):
        print(f"  the {role} program scores {reference[role]['runs'][str(reference['seeds'][0])]['score']!r}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mendel.explain")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, func in (("bookend", _tool_bookend), ("try", _tool_try)):
        p = sub.add_parser(name)
        p.add_argument("--solver", required=True)
        p.add_argument("--problem", required=True)
        p.add_argument("--reference", required=True)
        p.set_defaults(func=func)
        if name == "bookend":
            p.add_argument("--quick", action="store_true", help="the two bookends only")
        else:
            p.add_argument("--all-on", action="store_true", help="start from the all-on configuration")
            p.add_argument("--set", nargs="*", metavar="GENE=VALUE")
            p.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
