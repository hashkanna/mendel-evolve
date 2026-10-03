#!/usr/bin/env python3
"""Run the OpenEvolve circle-packing baseline, and record what it found and what it cost.

OpenEvolve's own two-phase recipe (the commands in its example README, its shipped Anthropic configs):

    uv run python baselines/openevolve/run_openevolve.py --recipe two-phase --seed 1 \
        --parallel-evaluations 2 --cap-usd 15

One phase with the config in this directory:

    uv run python baselines/openevolve/run_openevolve.py --iterations 100 --seed 1

THESE CALL THE ANTHROPIC API AND COST MONEY (one claude-haiku-4-5 request per iteration), unless
--dry-run is given or --api-base points at a local stub (see fake_llm_server.py).

What a run does
  1. loads ANTHROPIC_API_KEY from .env in the project root into the child's environment, unprinted;
  2. writes each phase's config: the source config with the model, seed, iteration count,
     checkpoint interval and (if asked) evaluation parallelism set; every change is listed in manifest.json;
  3. runs OpenEvolve from vendor/ (see setup.sh) with its own initial_program.py and evaluator.py.
     In the two-phase recipe, phase 2 is a fresh OpenEvolve run whose initial program is phase 1's
     checkpoints/checkpoint_<N>/best_program.py, exactly as in OpenEvolve's README;
  4. leaves every best-so-far program on disk (checkpoint interval 1):
     <phase>/openevolve_output/checkpoints/checkpoint_<i>/best_program.py;
  5. writes usage.json: billed requests, tokens and dollars per phase and cumulative across phases,
     from the token usage OpenEvolve logs for every API response;
  6. watches the spend while it runs. With --cap-usd, all runs that share a group directory (the
     parent of the run directory) stop together, gracefully, once their logged spend reaches the cap
     minus --cap-margin (requests in flight are not logged yet). They also stop if the API starts
     refusing requests (--max-llm-failures lost iterations). The reason is written to <group>/STOP.

Standard library only, so any Python 3.11+ runs it; OpenEvolve itself runs in vendor/venv.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from common import (EXAMPLE, HERE, MODEL, OPENEVOLVE, ROOT, VENV_PYTHON, ZERO, add_usage, group_spend, load_dotenv,
                    parse_usage, run_spend)
from reap_orphans import reap

ANTHROPIC_BASE = "https://api.anthropic.com/v1"
SHOW = re.compile(r"New best solution|Evolution completed|Total LLM Token Usage| - ERROR - |LLM generation failed|"
                  r"Iteration \d+ (?:error|timed out)|graceful shutdown")
POLL_SECONDS = 10.0
GRACE_SECONDS = 90.0


# --------------------------------------------------------------------------------------------
# Config derivation (YAML edited as text, so the result is the source file plus the listed changes)
# --------------------------------------------------------------------------------------------

def derive_config(source: Path, target: Path, *, iterations: int, seed: int, checkpoint_interval: int,
                  parallel_evaluations: int | None, api_base: str | None) -> list[str]:
    """Write `target` = `source` with this run's settings. Returns the changes, for the manifest."""
    lines = source.read_text().splitlines()
    changes: list[str] = []

    def find(key: str) -> int | None:
        for i, line in enumerate(lines):
            if re.match(rf"^\s*{re.escape(key)}:", line):
                return i
        return None

    def current(i: int) -> str:
        return lines[i].split(":", 1)[1].split(" #")[0].strip().strip('"')

    def set_value(key: str, value: str, after: str | None = None) -> None:
        i = find(key)
        shown = value.strip('"')
        if i is not None:
            if current(i) != shown:
                changes.append(f"{key}: {current(i)} -> {shown}")
            indent = re.match(r"^\s*", lines[i]).group(0)
            lines[i] = f"{indent}{key}: {value}"
        else:
            j = find(after) if after else None
            if j is None:
                raise SystemExit(f"{source} has neither '{key}:' nor '{after}:'")
            indent = re.match(r"^\s*", lines[j]).group(0)
            lines.insert(j + 1, f"{indent}{key}: {value}")
            changes.append(f"{key}: (not set) -> {shown}")

    def delete(key: str) -> None:
        i = find(key)
        if i is not None:
            changes.append(f"{key}: {current(i)} -> (removed)")
            del lines[i]

    set_value("max_iterations", str(iterations))
    set_value("checkpoint_interval", str(checkpoint_interval))
    set_value("random_seed", str(seed), after="checkpoint_interval")
    set_value("primary_model", f'"{MODEL}"')
    set_value("primary_model_weight", "1.0")
    delete("secondary_model")
    delete("secondary_model_weight")
    if parallel_evaluations is not None:
        set_value("parallel_evaluations", str(parallel_evaluations))
    if api_base:
        set_value("api_base", json.dumps(api_base))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n")
    return changes


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


def redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if len(secret) >= 12:
            text = text.replace(secret, "[REDACTED]")
    return text


# --------------------------------------------------------------------------------------------
# The watchdog: spend cap and API refusals
# --------------------------------------------------------------------------------------------

class Watchdog(threading.Thread):
    """Polls the logs while OpenEvolve runs and stops it, gracefully, when a stop condition holds."""

    def __init__(self, run_dir: Path, group_dir: Path | None, cap_usd: float | None, cap_margin: float,
                 max_llm_failures: int, secrets: list[str]):
        super().__init__(daemon=True)
        self.run_dir, self.group_dir = run_dir, group_dir
        self.cap_usd, self.cap_margin, self.max_llm_failures = cap_usd, cap_margin, max_llm_failures
        self.secrets = secrets
        self.process: subprocess.Popen | None = None
        self.phase = ""
        self.eval_timeout = 300.0  # set per phase from its config
        self.reason: str | None = None
        self.finished = threading.Event()
        self.lock = threading.Lock()

    @property
    def stop_file(self) -> Path:
        return (self.group_dir or self.run_dir) / "STOP"

    def run(self) -> None:
        while not self.finished.wait(POLL_SECONDS):
            try:
                self.check()
            except Exception as exc:  # noqa: BLE001 - a failed poll must not kill the watchdog
                self.note(f"watchdog error: {exc!r}")

    def note(self, text: str) -> None:
        with (self.run_dir / "watch.log").open("a") as f:
            f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {redact(text, self.secrets)}\n")

    def check(self) -> None:
        own, failures = run_spend(self.run_dir)
        total = group_spend(self.group_dir) if self.group_dir else own["usd"]
        load = os.getloadavg()
        self.note(f"{self.phase} requests={own['requests']} usd={own['usd']:.4f} group_usd={total:.4f} "
                  f"llm_failures={len(failures)} load={load[0]:.1f}/{load[1]:.1f}")
        process = self.process
        if process is not None and process.poll() is None:
            # Evaluations OpenEvolve has already timed out keep running for up to ten minutes (the example
            # evaluator's own limit) with a result nobody reads; end them so they do not hold cores.
            _, killed = reap(self.eval_timeout + 10.0, groups={process.pid})
            if killed:
                self.note(f"reaped {len(killed)} evaluation(s) past the {self.eval_timeout:.0f}s time-out: "
                          + ", ".join(f"pid {pid} ({age}s)" for pid, _, age in killed))
        if self.reason:
            return
        reason = None
        if self.stop_file.exists():
            reason = "stop requested: " + self.stop_file.read_text().strip()[:300]
        elif self.cap_usd is not None and total >= self.cap_usd - self.cap_margin:
            reason = (f"spend cap: ${total:.2f} logged, limit ${self.cap_usd:.2f} minus ${self.cap_margin:.2f} "
                      f"for requests in flight")
        elif len(failures) >= self.max_llm_failures:
            reason = (f"the API is refusing requests: {len(failures)} iterations lost in {self.run_dir.name}, "
                      f"last: {failures[-1]['message']}")
        if reason:
            if not self.stop_file.exists():
                self.stop_file.write_text(redact(reason, self.secrets) + "\n")
            self.stop(reason)

    def stop(self, reason: str) -> None:
        with self.lock:
            if self.reason:
                return
            self.reason = reason
        self.note(f"STOPPING: {reason}")
        print(f"[{self.run_dir.name}] stopping: {redact(reason, self.secrets)}", flush=True)
        process = self.process
        if process is None or process.poll() is not None:
            return
        process.send_signal(signal.SIGTERM)  # OpenEvolve shuts down gracefully: no new iterations, results saved
        deadline = time.time() + GRACE_SECONDS
        while time.time() < deadline and process.poll() is None:
            time.sleep(1.0)
        if process.poll() is None:
            self.note("still running after the grace period: killing the process group")
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                process.kill()


# --------------------------------------------------------------------------------------------
# Running OpenEvolve
# --------------------------------------------------------------------------------------------

def evaluator_timeout(config: Path) -> float:
    """`timeout` in the `evaluator:` block of an OpenEvolve config, in seconds (OpenEvolve's default is 300)."""
    inside = False
    for line in config.read_text().splitlines():
        if re.match(r"^evaluator:\s*(#.*)?$", line):
            inside = True
        elif inside and line[:1] not in ("", " ", "\t", "#"):
            break
        elif inside:
            found = re.match(r"^\s+timeout:\s*([\d.]+)", line)
            if found:
                return float(found.group(1))
    return 300.0


def set_evaluator_timeout(config: Path, seconds: float) -> tuple[float, float] | None:
    """Set `timeout` in the `evaluator:` block of a config. Returns (old, new), or None if unchanged."""
    lines = config.read_text().splitlines()
    inside = False
    for i, line in enumerate(lines):
        if re.match(r"^evaluator:\s*(#.*)?$", line):
            inside = True
        elif inside and line[:1] not in ("", " ", "\t", "#"):
            break
        elif inside:
            found = re.match(r"^(\s+)timeout:\s*([\d.]+)", line)
            if found:
                before = float(found.group(2))
                if before == seconds:
                    return None
                lines[i] = f"{found.group(1)}timeout: {seconds:g}"
                config.write_text("\n".join(lines) + "\n")
                return before, float(seconds)
    raise SystemExit(f"{config} has no evaluator timeout to set")


def phase_progress(phase_dir: Path) -> tuple[int, Path | None]:
    """(iterations already logged, the most recently saved checkpoint) of a phase."""
    output_dir = phase_dir / "openevolve_output"
    done = parse_usage(output_dir)["iterations_logged"]
    latest, latest_time = None, -1.0
    directory = output_dir / "checkpoints"
    for checkpoint in (directory.glob("checkpoint_*") if directory.exists() else []):
        try:
            saved = float(json.loads((checkpoint / "best_program_info.json").read_text())["saved_at"])
        except (OSError, ValueError, KeyError):
            saved = checkpoint.stat().st_mtime
        if saved > latest_time:
            latest, latest_time = checkpoint, saved
    return done, latest


def run_phase(*, label: str, phase_dir: Path, initial_program: Path, config: Path, iterations: int, env: dict,
              secrets: list[str], watchdog: Watchdog, dry_run: bool, checkpoint: Path | None = None) -> dict:
    output_dir = phase_dir / "openevolve_output"
    # oe_launch.py is openevolve-run.py plus a guard that shuts OpenEvolve down if this runner dies
    command = [str(VENV_PYTHON), str(HERE / "oe_launch.py"), str(initial_program), str(EXAMPLE / "evaluator.py"),
               "--config", str(config), "--iterations", str(iterations), "--output", str(output_dir)]
    if checkpoint is not None:  # a resume: OpenEvolve reloads its population and runs `iterations` more
        command += ["--checkpoint", str(checkpoint)]
    record = {"command": command, "initial_program": str(initial_program), "initial_program_sha256": sha256(initial_program),
              "config_sha256": sha256(config), "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    print(f"[{label}] command: {' '.join(command)}", flush=True)
    if dry_run:
        return record
    started = time.time()
    watchdog.phase = label
    watchdog.eval_timeout = evaluator_timeout(config)
    with (phase_dir / "console.log").open("a" if checkpoint is not None else "w") as console:
        process = subprocess.Popen(command, cwd=phase_dir, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace", start_new_session=True)
        watchdog.process = process
        if watchdog.reason:  # a stop that arrived between the phases
            process.send_signal(signal.SIGTERM)
        for line in process.stdout:
            line = redact(line, secrets)
            console.write(line)
            if SHOW.search(line):
                print(f"[{label}] {line.rstrip()[:220]}", flush=True)
        code = process.wait()
    watchdog.process = None
    try:  # anything OpenEvolve left behind (evaluation subprocesses) goes with it
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        pass
    usage = parse_usage(output_dir)
    record.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"), "wall_seconds": round(time.time() - started, 1),
                   "exit_code": code, "checkpoints": len(list((output_dir / "checkpoints").glob("checkpoint_*")))
                   if (output_dir / "checkpoints").exists() else 0, "requests": usage["total"]["requests"],
                   "usd": usage["total"]["usd"]})
    print(f"[{label}] exit code {code}; {record['checkpoints']} checkpoints; {usage['total']['requests']} billed requests; "
          f"${usage['total']['usd']:.4f}; {record['wall_seconds']:.0f}s", flush=True)
    return record


def write_usage(run_dir: Path, phases: list[tuple[str, Path]], stopped: str | None) -> dict:
    cumulative, out = ZERO, {"model": MODEL, "phases": {}, "stopped": stopped}
    for name, phase_dir in phases:
        usage = parse_usage(phase_dir / "openevolve_output")
        usage["cumulative_before"] = cumulative
        cumulative = add_usage(cumulative, usage["total"])
        usage["cumulative_after"] = cumulative
        out["phases"][name] = usage
    out["total"] = cumulative
    (run_dir / "usage.json").write_text(json.dumps(out, indent=1) + "\n")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the OpenEvolve circle-packing baseline (paid API calls).")
    parser.add_argument("--recipe", choices=["one-phase", "two-phase"], default="one-phase",
                        help="two-phase: OpenEvolve's README recipe with its shipped Anthropic configs")
    parser.add_argument("--iterations", type=int, help="iterations = LLM requests, per phase (two-phase default: 100)")
    parser.add_argument("--seed", type=int, required=True, help="OpenEvolve random_seed (same for both phases)")
    parser.add_argument("--out", help="run directory (default: runs/iter<N>_seed<S>, or <group>/seed<S> for two-phase)")
    parser.add_argument("--group", help="two-phase: directory shared by the runs of one experiment "
                                        "(default: baselines/openevolve/runs/two_phase_haiku)")
    parser.add_argument("--config", default=str(HERE / "config.yaml"), help="one-phase: config template")
    parser.add_argument("--checkpoint-interval", type=int, default=1,
                        help="iterations between checkpoints; 1 keeps every best-so-far program")
    parser.add_argument("--parallel-evaluations", type=int,
                        help="OpenEvolve worker processes per run (shipped configs: 4)")
    parser.add_argument("--cap-usd", type=float, help="stop when the logged spend of the run (two-phase: of the "
                                                      "whole group) reaches this minus --cap-margin")
    parser.add_argument("--cap-margin", type=float, default=0.60,
                        help="allowance for requests in flight and for the time between two polls (USD)")
    parser.add_argument("--max-llm-failures", type=int, default=3,
                        help="stop when this many iterations were lost to API errors")
    parser.add_argument("--api-base", help="override the endpoint (for the local stub; .env is then NOT loaded)")
    parser.add_argument("--resume", action="store_true",
                        help="continue a run that was stopped: each unfinished phase goes on from its last saved "
                             "checkpoint for the iterations it still lacks (remove <group>/STOP first)")
    parser.add_argument("--eval-timeout", type=float,
                        help="set OpenEvolve's evaluator.timeout (wall seconds per evaluation stage) for every phase "
                             "that still has iterations to run; the change and the iteration it starts at are "
                             "recorded in manifest.json, and the config it replaces is kept next to it")
    parser.add_argument("--eval-timeout-factor", type=float,
                        help="like --eval-timeout, but as a multiple of each phase's shipped evaluator.timeout "
                             "(4 gives 240 s in phase 1 and 360 s in phase 2); for a machine shared with other jobs")
    parser.add_argument("--dry-run", action="store_true", help="prepare the run and print the commands; call nothing")
    args = parser.parse_args(argv)

    if not VENV_PYTHON.exists() or not (EXAMPLE / "initial_program.py").exists():
        raise SystemExit("OpenEvolve is not set up: run  bash baselines/openevolve/setup.sh  first")
    two_phase = args.recipe == "two-phase"
    iterations = args.iterations or (100 if two_phase else None)
    if iterations is None:
        raise SystemExit("--iterations is required for the one-phase recipe")

    if two_phase:
        group = Path(args.group).resolve() if args.group else HERE / "runs" / "two_phase_haiku"
        run = Path(args.out).resolve() if args.out else group / f"seed{args.seed}"
        group = run.parent
        phases = [("phase1", run / "phase1"), ("phase2", run / "phase2")]
        sources = [EXAMPLE / "config_phase_1_anthropic.yaml", EXAMPLE / "config_phase_2_anthropic.yaml"]
    else:
        group = None
        run = Path(args.out).resolve() if args.out else HERE / "runs" / f"iter{iterations}_seed{args.seed}"
        phases = [("phase1", run)]
        sources = [Path(args.config)]
    for _, phase_dir in phases:
        output_dir = phase_dir / "openevolve_output"
        if not args.resume and output_dir.exists() and any(output_dir.iterdir()):
            raise SystemExit(f"{output_dir} already has results; choose another --out, or --resume to continue it")
    if args.resume and not (run / "manifest.json").exists():
        raise SystemExit(f"nothing to resume in {run}")
    if group is not None and (group / "STOP").exists():
        raise SystemExit(f"{group / 'STOP'} exists ({(group / 'STOP').read_text().strip()[:200]}); remove it to run again")
    run.mkdir(parents=True, exist_ok=True)

    config_changes = {}
    for (name, phase_dir), source in zip(phases, sources):
        phase_dir.mkdir(parents=True, exist_ok=True)
        if args.resume and (phase_dir / "config.yaml").exists():
            continue  # a resumed run keeps the configs it started with
        config_changes[name] = {"source": str(source), "changes": derive_config(
            source, phase_dir / "config.yaml", iterations=iterations, seed=args.seed,
            checkpoint_interval=args.checkpoint_interval, parallel_evaluations=args.parallel_evaluations,
            api_base=args.api_base)}

    env = dict(os.environ)
    env.pop("VIRTUAL_ENV", None)
    env["MPLBACKEND"] = "Agg"  # evolved programs may import matplotlib; never open a window
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        env.setdefault(name, "1")  # one core per evaluation: the machine is shared
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

    commit = subprocess.run(["git", "-C", str(OPENEVOLVE), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    manifest = {
        "recipe": args.recipe, "openevolve_commit": commit, "model": MODEL, "iterations_per_phase": iterations,
        "seed": args.seed, "checkpoint_interval": args.checkpoint_interval, "endpoint": args.api_base or ANTHROPIC_BASE,
        "paid": paid, "cap_usd": args.cap_usd, "cap_margin": args.cap_margin, "configs": config_changes,
        "evaluator_sha256": sha256(EXAMPLE / "evaluator.py"), "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "phases": {},
    }
    previous_wall = 0.0
    if args.resume:
        earlier = json.loads((run / "manifest.json").read_text())
        previous_wall = float(earlier.get("wall_seconds") or 0.0)
        earlier.setdefault("resumes", []).append({"started": manifest["started"], "cap_usd": args.cap_usd,
                                                  "stopped_before": earlier.get("stopped")})
        earlier["configs"].update(config_changes)
        earlier.update({"cap_usd": args.cap_usd, "cap_margin": args.cap_margin})
        manifest = earlier
    (run / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print("run directory:", run)

    watchdog = Watchdog(run, group, args.cap_usd, args.cap_margin, args.max_llm_failures, secrets)

    def on_signal(signum, _frame) -> None:  # a kill of the runner stops OpenEvolve gracefully too
        threading.Thread(target=watchdog.stop, args=(f"runner received signal {signum}",), daemon=True).start()

    if not args.dry_run:
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
        watchdog.start()

    started = time.time()
    code = 0
    initial_program = EXAMPLE / "initial_program.py"
    for index, (name, phase_dir) in enumerate(phases):
        if watchdog.reason:
            break
        label = f"seed{args.seed} {name}"
        if index == 1:
            # OpenEvolve's README: phase 2 starts from openevolve_output/checkpoints/checkpoint_100/best_program.py
            previous = phases[0][1] / "openevolve_output"
            initial_program = previous / "checkpoints" / f"checkpoint_{iterations}" / "best_program.py"
            if not initial_program.exists() and not args.dry_run:
                initial_program = previous / "best" / "best_program.py"
            if args.dry_run and not initial_program.exists():
                print(f"[{label}] would start from {initial_program}")
                break
            if not initial_program.exists():
                print(f"[{label}] phase 1 left no best program; phase 2 not run", flush=True)
                code = code or 1
                break
        todo, checkpoint = iterations, None
        if args.resume:
            done, checkpoint = phase_progress(phase_dir)
            todo = iterations - done
            if todo <= 0:
                print(f"[{label}] already complete ({done} iterations logged)", flush=True)
                continue
            print(f"[{label}] resuming: {done} iterations logged, {todo} to go, from "
                  f"{checkpoint.name if checkpoint else 'the start'}", flush=True)
        wanted = args.eval_timeout
        if wanted is None and args.eval_timeout_factor is not None:
            wanted = evaluator_timeout(sources[index]) * args.eval_timeout_factor  # a multiple of the shipped limit
        if wanted is not None:
            config_path = phase_dir / "config.yaml"
            before = evaluator_timeout(config_path)
            if before != wanted:
                # OpenEvolve numbers the first iteration after a checkpoint as that checkpoint's iteration + 1
                first = int(checkpoint.name.split("_")[-1]) + 1 if checkpoint is not None else 1
                print(f"[{label}] evaluator.timeout {before:g}s -> {wanted:g}s from iteration {first}", flush=True)
                if not args.dry_run:
                    kept = phase_dir / f"config.timeout{before:g}.yaml"
                    kept.write_text(config_path.read_text())
                    set_evaluator_timeout(config_path, wanted)
                    manifest.setdefault("changes_during_run", []).append({
                        "phase": name, "setting": "evaluator.timeout", "before": before, "after": wanted,
                        "from_iteration": first, "iterations_logged_before": iterations - todo,
                        "applied": time.strftime("%Y-%m-%dT%H:%M:%S"), "previous_config": kept.name,
                        "reason": "machine load: the limit is wall time"})
                    (run / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        record = run_phase(label=label, phase_dir=phase_dir, initial_program=initial_program,
                           config=phase_dir / "config.yaml", iterations=todo, env=env, secrets=secrets,
                           watchdog=watchdog, dry_run=args.dry_run, checkpoint=checkpoint)
        if args.dry_run:
            continue
        before = manifest["phases"].get(name)
        if args.resume and before:  # keep the first record, add this leg to it
            before.setdefault("resumed", []).append(record)
            before["wall_seconds"] = round(float(before.get("wall_seconds") or 0.0) + record["wall_seconds"], 1)
            before.update({k: record[k] for k in ("finished", "exit_code", "checkpoints", "requests", "usd")})
        else:
            manifest["phases"][name] = record
        (run / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        code = code or record["exit_code"]
        if watchdog.reason or code != 0:
            break
    if args.dry_run:
        print("dry run: nothing was called")
        return 0

    watchdog.finished.set()
    scrubbed = scrub(run, secrets)
    usage = write_usage(run, phases, watchdog.reason)
    manifest.update({"finished": time.strftime("%Y-%m-%dT%H:%M:%S"),
                     "wall_seconds": round(previous_wall + time.time() - started, 1),
                     "exit_code": code, "stopped": watchdog.reason, "files_scrubbed": scrubbed})
    (run / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    total = usage["total"]
    print(f"[seed{args.seed}] done: exit code {code}; {total['requests']} billed requests, {total['prompt_tokens']} prompt + "
          f"{total['completion_tokens']} completion tokens, ${total['usd']:.4f}; {manifest['wall_seconds']:.0f}s"
          + (f"; STOPPED: {watchdog.reason}" if watchdog.reason else ""), flush=True)
    return code


if __name__ == "__main__":
    sys.exit(main())
