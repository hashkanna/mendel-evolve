"""Shared by run_openevolve.py and rescore.py: paths, the price of the model, and log parsing. Standard library only."""

from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
VENDOR = HERE / "vendor"
OPENEVOLVE = VENDOR / "openevolve"
VENV_PYTHON = VENDOR / "venv" / "bin" / "python"
EXAMPLE = OPENEVOLVE / "examples" / "circle_packing"

MODEL = "claude-haiku-4-5"
# Anthropic list price for claude-haiku-4-5, USD per million tokens (checked 2026-10-03).
USD_PER_MTOK_INPUT = 1.00
USD_PER_MTOK_OUTPUT = 5.00

# OpenEvolve's main process logs one of these per iteration whose LLM call returned a response:
#   Iteration 7: Program <id> (parent: <id>) completed in 12.34s | tokens: 5123 (prompt: 3000, completion: 2123)
#   Iteration 7 error: <message> | tokens: 5123 (prompt: 3000, completion: 2123)
TOKENS = re.compile(r"Iteration (\d+)(?::| error:).*\| tokens: (\d+) \(prompt: (\d+), completion: (\d+)\)")
ITERATION = re.compile(r" - Iteration (\d+)(?::| error:)")
CHECKPOINT = re.compile(r"Saved checkpoint at iteration (\d+) to ")
NEW_BEST = re.compile(r"New best solution found at iteration (\d+)")


def dollars(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens * USD_PER_MTOK_INPUT + completion_tokens * USD_PER_MTOK_OUTPUT) / 1_000_000


def parse_usage(output_dir: Path) -> dict:
    """Read OpenEvolve's log files and return what the run was billed for.

    A request is counted when OpenEvolve logged token usage for an iteration, which it does for
    every iteration whose LLM call returned a response (also when the answer then failed to parse
    or to evaluate). Requests that failed without a response (rate limit, overload, time-out) carry
    no usage and are not counted; the API does not bill the first two. With `use_llm_feedback: false`
    there is one request per iteration.

    `at_checkpoint[i]` is the running total at the moment checkpoint i was written, so it includes
    iterations that finished out of order before it and excludes requests still in flight.
    """
    totals = {"requests": 0, "prompt_tokens": 0, "completion_tokens": 0}
    by_iteration: list[dict] = []
    at_checkpoint: dict[int, dict] = {}
    new_best: list[int] = []
    iterations_seen = 0
    logs = sorted((output_dir / "logs").glob("openevolve_*.log"))
    for log in logs:
        for line in log.read_text(errors="replace").splitlines():
            if ITERATION.search(line):
                iterations_seen += 1
            found = TOKENS.search(line)
            if found:
                iteration, _, prompt, completion = (int(g) for g in found.groups())
                totals["requests"] += 1
                totals["prompt_tokens"] += prompt
                totals["completion_tokens"] += completion
                by_iteration.append({"iteration": iteration, "prompt_tokens": prompt, "completion_tokens": completion,
                                     "error": " error:" in line.split("| tokens:")[0]})
            found = CHECKPOINT.search(line)
            if found:
                at_checkpoint[int(found.group(1))] = _with_cost(totals)
            found = NEW_BEST.search(line)
            if found:
                new_best.append(int(found.group(1)))
    return {
        "model": MODEL,
        "usd_per_mtok": {"input": USD_PER_MTOK_INPUT, "output": USD_PER_MTOK_OUTPUT},
        "total": _with_cost(totals),
        "iterations_logged": iterations_seen,
        "iterations_without_usage": iterations_seen - totals["requests"],
        "new_best_at_iterations": new_best,
        "at_checkpoint": {str(k): v for k, v in sorted(at_checkpoint.items())},
        "by_iteration": by_iteration,
        "logs": [str(p) for p in logs],
    }


def _with_cost(totals: dict) -> dict:
    out = dict(totals)
    out["tokens"] = totals["prompt_tokens"] + totals["completion_tokens"]
    out["usd"] = round(dollars(totals["prompt_tokens"], totals["completion_tokens"]), 6)
    return out
