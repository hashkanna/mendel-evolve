"""Shared types.

Jobs and results are plain JSON-serialisable dicts so they cross process and network boundaries
unchanged (local process pool, Modal containers, the sqlite cache):

    job    = {"solver_dir": str, "problem_dir": str, "config": dict, "instance": dict, "seed": int,
              "budget": {"kind": "time" | "iters", "value": number}}
             optional key "timeout": seconds, overrides the worker's hard timeout (the gate uses it)
    result = {"ok": bool, "valid": bool, "score": float | None, "stats": dict, "wall": float,
              "error": str | None, "solution": object | None}

`ok` means the run itself worked (built, exited 0, wrote parsable output, was evaluated).
`valid` is the evaluator's verdict. An invalid solution has ok=True, valid=False, score=None and the
evaluator's reason in `error`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


def make_job(solver_dir, problem_dir, config: dict, instance: dict, seed: int, budget: dict,
             timeout: float | None = None) -> dict:
    job = {
        "solver_dir": str(solver_dir),
        "problem_dir": str(problem_dir),
        "config": dict(config),
        "instance": dict(instance),
        "seed": int(seed),
        "budget": {"kind": budget["kind"], "value": budget["value"]},
    }
    if timeout is not None:
        job["timeout"] = float(timeout)
    return job


def fail_result(error: str, wall: float = 0.0) -> dict:
    return {"ok": False, "valid": False, "score": None, "stats": {}, "wall": float(wall),
            "error": str(error), "solution": None}


def usable(result: dict | None) -> bool:
    """True when a result carries a score that can be used in a comparison."""
    return bool(result) and bool(result.get("ok")) and bool(result.get("valid")) and result.get("score") is not None


def budget_label(budget: dict) -> str:
    """{"kind": "time", "value": 10} -> "time=10"."""
    value = budget["value"]
    if float(value) == int(value):
        value = int(value)
    return f"{budget['kind']}={value}"


class Executor(Protocol):
    def run(self, jobs: list[dict]) -> list[dict]:
        """Run every job and return the results in the same order."""
        ...


@dataclass
class Proposal:
    ok: bool
    solver_dir: Path | None   # complete candidate solver dir = trunk + exactly one new idea gene (+ its alleles)
    genes: list[str]          # new gene names; genes[0] is the idea gene
    hypothesis: str
    predicted: str
    author: str               # "llm:<model>" or "human:<name>"
    cost_usd: float = 0.0
    log_path: Path | None = None
    error: str | None = None


class Inventor(Protocol):
    def propose(self, *, trunk: Path, problem_dir: Path, state: dict, workdir: Path,
                directive: str | None = None, author: str | None = None) -> Proposal: ...
