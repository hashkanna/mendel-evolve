"""run_job: build if needed, run the solver as a subprocess, evaluate its solution.

This is the one function every backend calls (local process pool, Modal containers). It imports only
the standard library plus mendel.genes / mendel.problem / mendel.solver, works on Linux and macOS,
and never raises: every failure comes back as ok=False with an error string.
"""
from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mendel.genes import complete_config, load_genes, validate_config
from mendel.problem import load_problem
from mendel.solver import ensure_built, load_manifest
from mendel.types import fail_result

ITERS_TIMEOUT = float(os.environ.get("MENDEL_ITERS_TIMEOUT", "900"))  # hard cap for --iters runs, seconds


def hard_timeout(budget: dict) -> float:
    """Three times the time budget plus ten seconds; a generous fixed cap for iteration budgets."""
    if budget["kind"] == "time":
        return 3.0 * float(budget["value"]) + 10.0
    return ITERS_TIMEOUT


def run_job(job: dict) -> dict:
    started = time.time()
    try:
        return _run(job)
    except Exception as e:  # never raise: the caller may be a remote container
        return fail_result(f"{type(e).__name__}: {e}", wall=time.time() - started)


def _tail(path: Path, limit: int = 1500) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return data[-limit:].decode("utf-8", "replace").strip()


def _kill(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # the solver runs in its own session, so this gets children too
    except (OSError, AttributeError):
        proc.kill()
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def _run(job: dict) -> dict:
    budget = job["budget"]
    kind, value = budget["kind"], budget["value"]
    if kind == "time":
        budget_args = ["--time", repr(float(value))]
    elif kind == "iters":
        budget_args = ["--iters", str(int(value))]
    else:
        return fail_result(f"unknown budget kind {kind!r} (expected 'time' or 'iters')")
    timeout = float(job.get("timeout") or hard_timeout(budget))

    build_dir = ensure_built(job["solver_dir"])
    manifest = load_manifest(build_dir)
    genes = load_genes(build_dir)
    config = complete_config(genes, job.get("config"))
    problems = validate_config(genes, config)
    if problems:
        return fail_result("bad config: " + "; ".join(problems))

    with tempfile.TemporaryDirectory(prefix="mendel-job-") as tmp_name:
        tmp = Path(tmp_name)
        (tmp / "config.json").write_text(json.dumps(config))
        (tmp / "instance.json").write_text(json.dumps(job["instance"]))
        out_path = tmp / "out.json"
        argv = shlex.split(manifest["run"])
        if argv and argv[0] in ("python", "python3"):
            argv[0] = sys.executable  # the interpreter running the harness (it has numpy); same on macOS and Linux
        cmd = argv + [
            "--config", str(tmp / "config.json"),
            "--instance", str(tmp / "instance.json"),
            "--seed", str(int(job["seed"])),
            *budget_args,
            "--out", str(out_path),
        ]
        started = time.time()
        with open(tmp / "stdout.txt", "wb") as so, open(tmp / "stderr.txt", "wb") as se:
            proc = subprocess.Popen(cmd, cwd=build_dir, stdout=so, stderr=se, stdin=subprocess.DEVNULL,
                                    start_new_session=True)
            try:
                code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill(proc)
                return fail_result(f"solver killed after the hard timeout of {timeout:.0f}s",
                                   wall=time.time() - started)
            except BaseException:
                _kill(proc)
                raise
        wall = time.time() - started
        if code != 0:
            return fail_result(f"solver exited with code {code}: {_tail(tmp / 'stderr.txt') or _tail(tmp / 'stdout.txt')}",
                               wall=wall)
        try:
            out = json.loads(out_path.read_text())
            solution = out["solution"]
        except FileNotFoundError:
            return fail_result("solver exited 0 but wrote no --out file", wall=wall)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return fail_result(f"solver output is not {{\"solution\": ...}} JSON: {type(e).__name__}: {e}", wall=wall)
        stats = out.get("stats")
        if not isinstance(stats, dict):
            stats = {}

    problem = load_problem(job["problem_dir"])
    verdict = problem.evaluate(job["instance"], solution)
    valid = bool(verdict["valid"])
    error = None
    if not valid:
        error = "invalid solution: " + json.dumps(verdict.get("detail"), default=str)[:800]
    return {
        "ok": True,
        "valid": valid,
        "score": verdict["score"] if valid else None,
        "stats": stats,
        "wall": wall,
        "error": error,
        "solution": solution,
    }
