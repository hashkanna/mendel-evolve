#!/usr/bin/env python3
"""Run the OpenEvolve circle-packing baseline once, and record what it found and what it cost.

    uv run python baselines/openevolve/run_openevolve.py --iterations 100 --seed 1

THIS CALLS THE ANTHROPIC API AND COSTS MONEY (one claude-haiku-4-5 request per iteration), unless
--dry-run is given or --api-base points at a local stub (see fake_llm_server.py).

What it does
  1. loads .env from the project root into the child process's environment, without printing it;
  2. writes the run's config (config.yaml with the iteration count, seed and checkpoint interval);
  3. runs OpenEvolve from vendor/ (see setup.sh) on its own initial_program.py and evaluator.py;
  4. leaves every best-so-far program on disk: openevolve_output/checkpoints/checkpoint_<i>/best_program.py
     is the best program after iteration i (checkpoint interval 1 by default);
  5. writes usage.json: billed requests, prompt and completion tokens, and dollars, in total and
     at each checkpoint, taken from the token usage OpenEvolve logs for every API response.

Standard library only, so any Python 3.11+ runs it; OpenEvolve itself runs in vendor/venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from common import EXAMPLE, HERE, MODEL, OPENEVOLVE, ROOT, VENV_PYTHON, parse_usage

ANTHROPIC_BASE = "https://api.anthropic.com/v1"
SHOW = re.compile(r"Iteration \d+|New best|Saved checkpoint|Evolution completed|Total LLM Token Usage| - ERROR - ")


def load_dotenv(path: Path) -> dict[str, str]:
    """KEY=VALUE lines from .env. The values are never printed or written anywhere by this script."""
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


def write_config(template: Path, target: Path, *, iterations: int, seed: int, checkpoint_interval: int,
                 api_base: str | None) -> None:
    text = template.read_text()

    def set_line(key: str, value: str, body: str) -> str:
        new, count = re.subn(rf"(?m)^(\s*){re.escape(key)}:.*$", lambda m: f"{m.group(1)}{key}: {value}", body, count=1)
        if count != 1:
            raise SystemExit(f"{template} has no '{key}:' line to set")
        return new

    text = set_line("max_iterations", str(iterations), text)
    text = set_line("checkpoint_interval", str(checkpoint_interval), text)
    text = set_line("random_seed", str(seed), text)
    if api_base:
        text = set_line("api_base", json.dumps(api_base), text)
    target.write_text(text)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def scrub(directory: Path, secrets: list[str]) -> int:
    """Belt and braces: if a secret ever reached a file of the run, replace it. Returns files changed."""
    changed = 0
    secrets = [s for s in secrets if len(s) >= 12]
    if not secrets:
        return 0
    for path in directory.rglob("*"):
        if not path.is_file() or path.stat().st_size > 50_000_000:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        clean = data
        for secret in secrets:
            clean = clean.replace(secret.encode(), b"[REDACTED]")
        if clean != data:
            path.write_bytes(clean)
            changed += 1
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OpenEvolve circle-packing baseline (paid API calls).")
    parser.add_argument("--iterations", type=int, required=True, help="OpenEvolve iterations = LLM requests")
    parser.add_argument("--seed", type=int, required=True, help="OpenEvolve random_seed")
    parser.add_argument("--out", help="run directory (default: baselines/openevolve/runs/iter<N>_seed<S>)")
    parser.add_argument("--config", default=str(HERE / "config.yaml"), help="config template")
    parser.add_argument("--checkpoint-interval", type=int, default=1,
                        help="iterations between checkpoints; 1 keeps every best-so-far program")
    parser.add_argument("--api-base", help="override the endpoint (for the local stub; .env is then NOT loaded)")
    parser.add_argument("--dry-run", action="store_true", help="prepare the run and print the command; call nothing")
    args = parser.parse_args(argv)

    if not VENV_PYTHON.exists() or not (EXAMPLE / "initial_program.py").exists():
        raise SystemExit("OpenEvolve is not set up: run  bash baselines/openevolve/setup.sh  first")

    out = Path(args.out).resolve() if args.out else HERE / "runs" / f"iter{args.iterations}_seed{args.seed}"
    output_dir = out / "openevolve_output"
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"{output_dir} already has results; choose another --out (runs are never overwritten)")
    out.mkdir(parents=True, exist_ok=True)

    run_config = out / "config.yaml"
    write_config(Path(args.config), run_config, iterations=args.iterations, seed=args.seed,
                 checkpoint_interval=args.checkpoint_interval, api_base=args.api_base)

    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env["MPLBACKEND"] = "Agg"  # evolved programs may import matplotlib; never open a window
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env.setdefault(name, "1")  # evaluations run 4 at a time on a shared machine
    paid = not args.api_base or args.api_base.rstrip("/") == ANTHROPIC_BASE
    secrets: list[str] = []
    if paid:
        dotenv = load_dotenv(ROOT / ".env")
        if dotenv.get("ANTHROPIC_API_KEY"):  # the only value OpenEvolve needs; nothing else in .env is passed on
            env.setdefault("ANTHROPIC_API_KEY", dotenv["ANTHROPIC_API_KEY"])
        secrets = [v for v in dotenv.values() if v]
        if env.get("ANTHROPIC_API_KEY"):
            secrets.append(env["ANTHROPIC_API_KEY"])
        elif not args.dry_run:
            raise SystemExit("ANTHROPIC_API_KEY is not set (looked in the environment and in .env)")
        print(f"ANTHROPIC_API_KEY: {'found' if env.get('ANTHROPIC_API_KEY') else 'NOT FOUND'}")
    else:
        env["ANTHROPIC_API_KEY"] = "stub-key-for-local-testing"  # never send the real key to another endpoint
        print(f"endpoint overridden ({args.api_base}): .env not loaded, no paid calls")

    command = [str(VENV_PYTHON), str(OPENEVOLVE / "openevolve-run.py"),
               str(EXAMPLE / "initial_program.py"), str(EXAMPLE / "evaluator.py"),
               "--config", str(run_config), "--iterations", str(args.iterations), "--output", str(output_dir)]
    commit = subprocess.run(["git", "-C", str(OPENEVOLVE), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {
        "openevolve_commit": commit, "model": MODEL, "iterations": args.iterations, "seed": args.seed,
        "checkpoint_interval": args.checkpoint_interval, "endpoint": args.api_base or ANTHROPIC_BASE, "paid": paid,
        "config_sha256": sha256(run_config), "initial_program_sha256": sha256(EXAMPLE / "initial_program.py"),
        "evaluator_sha256": sha256(EXAMPLE / "evaluator.py"), "command": command,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print("run directory:", out)
    print("command:", " ".join(command))
    if args.dry_run:
        print("dry run: nothing was called")
        return 0

    started = time.time()
    with (out / "console.log").open("w") as console:
        process = subprocess.Popen(command, cwd=out, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                   errors="replace")
        try:
            for line in process.stdout:
                for secret in secrets:
                    if len(secret) >= 12:
                        line = line.replace(secret, "[REDACTED]")
                console.write(line)
                if SHOW.search(line):
                    print(line.rstrip()[:240], flush=True)
        except KeyboardInterrupt:
            process.terminate()
        code = process.wait()

    scrubbed = scrub(out, secrets)
    usage = parse_usage(output_dir)
    (out / "usage.json").write_text(json.dumps(usage, indent=1) + "\n")
    manifest.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "wall_seconds": round(time.time() - started, 1),
                     "exit_code": code, "files_scrubbed": scrubbed})
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")

    total = usage["total"]
    checkpoints = sorted((output_dir / "checkpoints").glob("checkpoint_*")) if (output_dir / "checkpoints").exists() else []
    print(f"exit code {code}; {len(checkpoints)} checkpoints; {total['requests']} billed requests, "
          f"{total['prompt_tokens']} prompt + {total['completion_tokens']} completion tokens, ${total['usd']:.4f}")
    print(f"next:  uv run python baselines/openevolve/rescore.py {out}")
    return code


if __name__ == "__main__":
    sys.exit(main())
