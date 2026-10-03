"""Record campaign: run one solver configuration at scale and keep verified certificates.

    python -m mendel.campaign --solver solvers/no5sphere --problem problems/no5sphere \
        --instances n17 n18 n19 n20 --seeds 32 --time 600 --executor modal --out runs/campaign-1

Every result that the remote worker reports as valid is re-checked here with the problem's
evaluator, and again with the pack's independent `verify.py` when it has one, before it is
written down as a certificate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import time
import tomllib
from pathlib import Path


def _load_evaluator(problem_dir: Path):
    spec = importlib.util.spec_from_file_location("mendel_problem_evaluate", problem_dir / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_instance(text: str) -> dict:
    if text.startswith("{"):
        return json.loads(text)
    return {text[0]: int(text[1:])}  # "n17" -> {"n": 17}


def run_campaign(*, solver_dir: Path, problem_dir: Path, config: dict, instances: list[dict], seeds: list[int],
                 time_s: float, executor, out_dir: Path) -> list[dict]:
    meta = tomllib.loads((problem_dir / "problem.toml").read_text())
    direction = meta.get("direction", "max")
    best_known = meta.get("best_known", {})
    ev = _load_evaluator(problem_dir)
    better = (lambda a, b: a > b) if direction == "max" else (lambda a, b: a < b)

    def beats_published(value: float, known: float) -> bool:
        # Published values are rounded decimals, so a tie must not be announced as a record.
        if float(value).is_integer() and float(known).is_integer():
            return better(value, known)
        margin = 1e-9 * max(1.0, abs(known))
        return value > known + margin if direction == "max" else value < known - margin

    jobs = [{"solver_dir": str(solver_dir), "problem_dir": str(problem_dir), "config": config,
             "instance": inst, "seed": seed, "budget": {"kind": "time", "value": time_s}}
            for inst in instances for seed in seeds]
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    progress: dict[str, dict] = {}
    done_jobs = [0]

    def on_batch(batch_jobs: list[dict], batch_results: list[dict]) -> None:
        # Best-so-far per instance, as reported by the workers (not yet re-verified here).
        for job, res in zip(batch_jobs, batch_results):
            done_jobs[0] += 1
            key = ev.instance_key(job["instance"])
            row = progress.setdefault(key, {"runs": 0, "best": None, "best_known": best_known.get(key)})
            row["runs"] += 1
            if res.get("ok") and res.get("valid") and res.get("score") is not None:
                if row["best"] is None or better(res["score"], row["best"]):
                    row["best"] = res["score"]
        (out_dir / "campaign_progress.json").write_text(json.dumps(
            {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "jobs_done": done_jobs[0], "jobs_total": len(jobs),
             "unverified_best": progress}, indent=1) + "\n")
        if done_jobs[0] % 25 < len(batch_jobs):
            print(f"[{time.strftime('%H:%M:%S')}] {done_jobs[0]}/{len(jobs)} runs back", flush=True)

    try:  # a journal lets a crashed campaign collect its results again instead of recomputing them
        results = executor.run(jobs, journal=out_dir / "modal_calls.json", on_batch=on_batch)
    except TypeError:
        results = executor.run(jobs)

    out_dir.mkdir(parents=True, exist_ok=True)
    certs = out_dir / "certificates"
    certs.mkdir(exist_ok=True)
    (out_dir / "campaign_raw.jsonl").open("a").writelines(
        json.dumps({"instance": j["instance"], "seed": j["seed"], "time": time_s, "ok": r.get("ok"),
                    "valid": r.get("valid"), "score": r.get("score"), "error": r.get("error"),
                    "stats": {k: v for k, v in (r.get("stats") or {}).items() if k != "trace"}}) + "\n"
        for j, r in zip(jobs, results))

    summary = []
    for inst in instances:
        key = ev.instance_key(inst)
        runs = [(j, r) for j, r in zip(jobs, results) if j["instance"] == inst]
        scores = [r["score"] for _, r in runs if r.get("ok") and r.get("valid") and r.get("score") is not None]
        row = {"instance": key, "runs": len(runs), "valid_runs": len(scores), "best_known": best_known.get(key),
               "value": None, "mean": (sum(scores) / len(scores)) if scores else None, "verified": False,
               "certificate": None, "errors": sorted({str(r.get("error"))[:200] for _, r in runs if not r.get("ok")})[:3]}
        best = None
        for job, res in runs:
            if res.get("ok") and res.get("valid") and res.get("score") is not None:
                if best is None or better(res["score"], best[1]["score"]):
                    best = (job, res)
        if best:
            job, res = best
            check = ev.evaluate(inst, res["solution"])  # never trust the remote verdict alone
            row["value"] = check.get("score") if check.get("valid") else None
            row["verified"] = bool(check.get("valid")) and check.get("score") == res["score"]
            if row["verified"]:
                score_text = repr(res["score"]).replace(".", "p")  # full precision, so names never collide
                path = certs / f"{key}_{score_text}.json"
                path.write_text(json.dumps({
                    "problem": meta.get("name"), "instance": inst, "score": res["score"],
                    "solution": res["solution"], "seed": job["seed"], "budget_cpu_seconds": time_s,
                    "config": config, "found": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }, indent=1) + "\n")
                row["certificate"] = str(path)
                verifier = problem_dir / "verify.py"
                if verifier.exists():
                    done = subprocess.run([sys.executable, str(verifier), str(path)], capture_output=True, text=True)
                    row["independent_check"] = "pass" if done.returncode == 0 else f"FAIL: {(done.stdout + done.stderr)[-300:]}"
                    row["verified"] = row["verified"] and done.returncode == 0
        known = row["best_known"]
        row["record"] = bool(row["verified"] and row["value"] is not None
                             and (known is None or beats_published(row["value"], known)))
        summary.append(row)

    (out_dir / "campaign_summary.json").write_text(json.dumps(
        {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "wall_seconds": round(time.time() - started, 1),
         "time_per_run": time_s, "seeds": len(seeds), "config": config, "rows": summary}, indent=1) + "\n")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="mendel.campaign")
    p.add_argument("--solver", required=True)
    p.add_argument("--problem", required=True)
    p.add_argument("--instances", nargs="+", required=True, help='keys like n17, or JSON like {"n": 17}')
    p.add_argument("--seeds", type=int, default=16)
    p.add_argument("--seed-offset", type=int, default=1000)
    p.add_argument("--time", type=float, default=300.0, help="CPU seconds per run")
    p.add_argument("--config", help="JSON file with gene values; defaults are used for anything missing")
    p.add_argument("--executor", choices=["local", "modal"], default="local")
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--max-cpu-hours", type=float, default=100.0)
    p.add_argument("--no-deploy", action="store_true", help="use the Modal app as already deployed")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    solver, problem = Path(args.solver).resolve(), Path(args.problem).resolve()
    config = {g["name"]: g["default"] for g in json.loads((solver / "genes.json").read_text())["genes"]}
    if args.config:
        config.update(json.loads(Path(args.config).read_text()))
    if args.executor == "modal":
        from .backends.modal_backend import ModalExecutor
        executor = ModalExecutor(max_cpu_hours=args.max_cpu_hours, function="run_batch_bg",
                                 deploy=not args.no_deploy)
    else:
        from .executor import LocalExecutor
        executor = LocalExecutor(workers=args.workers)

    rows = run_campaign(solver_dir=solver, problem_dir=problem, config=config,
                        instances=[_parse_instance(i) for i in args.instances],
                        seeds=list(range(args.seed_offset, args.seed_offset + args.seeds)),
                        time_s=args.time, executor=executor, out_dir=Path(args.out))
    print(f"{'instance':9s} {'ours':>5s} {'mean':>7s} {'known':>6s}  verified  record")
    for r in rows:
        mean = f"{r['mean']:.6g}" if r["mean"] is not None else "-"
        print(f"{r['instance']:9s} {str(r['value']):>5s} {mean:>7s} {str(r['best_known']):>6s}  "
              f"{'yes' if r['verified'] else 'NO':8s}  {'NEW RECORD' if r['record'] else ''}")
        for e in r["errors"]:
            print(f"    error: {e}")
    if args.executor == "modal":
        print(f"estimated Modal spend for this call: ${executor.estimated_usd:.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
