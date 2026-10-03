"""Shared by the baseline scripts: paths, the price of the model, .env loading and log parsing. Standard library only."""

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
# and this when the call failed after all its retries (nothing billed, the iteration is lost):
#   Iteration 7 error: LLM generation failed: <exception>
TOKENS = re.compile(r"Iteration (\d+)(?::| error:).*\| tokens: (\d+) \(prompt: (\d+), completion: (\d+)\)")
ITERATION = re.compile(r" - Iteration (\d+)(?::| error:)")
CHECKPOINT = re.compile(r"Saved checkpoint at iteration (\d+) to ")
NEW_BEST = re.compile(r"New best solution found at iteration (\d+)")
LLM_FAILED = re.compile(r"Iteration (\d+) error: LLM generation failed: (.*)")
TIMED_OUT = re.compile(r"Iteration \d+ timed out|Evaluation timed out")


def load_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines from a .env file. Callers must never print or store the values."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def dollars(prompt_tokens: int, completion_tokens: int) -> float:
    return (prompt_tokens * USD_PER_MTOK_INPUT + completion_tokens * USD_PER_MTOK_OUTPUT) / 1_000_000


def with_cost(totals: dict) -> dict:
    out = {k: totals[k] for k in ("requests", "prompt_tokens", "completion_tokens")}
    out["tokens"] = out["prompt_tokens"] + out["completion_tokens"]
    out["usd"] = round(dollars(out["prompt_tokens"], out["completion_tokens"]), 6)
    return out


def add_usage(a: dict, b: dict) -> dict:
    return with_cost({k: a[k] + b[k] for k in ("requests", "prompt_tokens", "completion_tokens")})


ZERO = with_cost({"requests": 0, "prompt_tokens": 0, "completion_tokens": 0})


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
    llm_failures: list[dict] = []
    iterations_seen = 0
    timeouts = 0
    logs = sorted((output_dir / "logs").glob("openevolve_*.log")) if (output_dir / "logs").exists() else []
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
                at_checkpoint[int(found.group(1))] = with_cost(totals)
            found = NEW_BEST.search(line)
            if found:
                new_best.append(int(found.group(1)))
            found = LLM_FAILED.search(line)
            if found:
                llm_failures.append({"iteration": int(found.group(1)), "message": found.group(2)[:240]})
            if TIMED_OUT.search(line):
                timeouts += 1
    return {
        "model": MODEL,
        "usd_per_mtok": {"input": USD_PER_MTOK_INPUT, "output": USD_PER_MTOK_OUTPUT},
        "total": with_cost(totals),
        "iterations_logged": iterations_seen,
        "iterations_without_usage": iterations_seen - totals["requests"],
        "llm_failures": llm_failures,
        "timeout_lines": timeouts,
        "new_best_at_iterations": new_best,
        "at_checkpoint": {str(k): v for k, v in sorted(at_checkpoint.items())},
        "by_iteration": by_iteration,
        "logs": [str(p) for p in logs],
    }


def output_dirs(run_dir: Path) -> list[Path]:
    """The OpenEvolve output directories of a run: one for a one-phase run, phase1 and phase2 for the recipe."""
    found = [run_dir / "openevolve_output"] if (run_dir / "openevolve_output").exists() else []
    return found + sorted(p for p in run_dir.glob("phase*/openevolve_output") if p.is_dir())


def run_spend(run_dir: Path) -> tuple[dict, list[dict]]:
    """(usage summed over the phases of a run, LLM failures)."""
    total, failures = ZERO, []
    for output_dir in output_dirs(run_dir):
        usage = parse_usage(output_dir)
        total = add_usage(total, usage["total"])
        failures += usage["llm_failures"]
    return total, failures


def group_spend(group_dir: Path) -> float:
    """Dollars logged so far by every run directory directly under `group_dir`."""
    return sum(run_spend(run)[0]["usd"] for run in sorted(group_dir.iterdir()) if run.is_dir())
