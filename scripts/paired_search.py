"""Several solver arms on the same instances and seeds, with every arm of a seed in the same container.

A record search (`mendel.campaign`) runs one configuration; comparing two such searches compares runs
made in different containers, and container hardware alone can move the mean score by several hundredths
of a point. Here all arms go to the executor in one call, which keeps the arms of each (instance, seed)
together in one batch, so differences between arms are not differences between machines.

    uv run python scripts/paired_search.py --arms configs/paired/arms.json --problem problems/no5sphere \
        --instances n23 n26 n28 n31 --seeds 150 --seed-offset 40000 --time 240 --out runs/paired-1

arms.json is a list of {"name", "solver", "config"}; a config is completed with the solver's defaults.
Writes raw.jsonl (one line per run) while batches return, and at the end a verified certificate for the
best valid result of each arm and instance.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--arms", required=True)
    p.add_argument("--problem", required=True)
    p.add_argument("--instances", nargs="+", required=True)
    p.add_argument("--seeds", type=int, required=True)
    p.add_argument("--seed-offset", type=int, required=True)
    p.add_argument("--time", type=float, required=True)
    p.add_argument("--max-cpu-hours", type=float, default=800.0)
    p.add_argument("--out", required=True)
    args = p.parse_args()

    from mendel.backends.modal_backend import ModalExecutor

    problem = Path(args.problem).resolve()
    spec = importlib.util.spec_from_file_location("problem_evaluate", problem / "evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    arms = json.loads(Path(args.arms).read_text())
    for arm in arms:
        solver = (ROOT / arm["solver"]).resolve()
        config = {g["name"]: g["default"] for g in json.loads((solver / "genes.json").read_text())["genes"]}
        unknown = set(arm.get("config", {})) - set(config)
        if unknown:
            raise SystemExit(f"arm {arm['name']}: genes not in {solver}: {sorted(unknown)}")
        config.update(arm.get("config", {}))
        arm["solver_dir"], arm["full_config"] = str(solver), config
    instances = [{i[0]: int(i[1:])} for i in args.instances]
    seeds = list(range(args.seed_offset, args.seed_offset + args.seeds))
    jobs, tags = [], []
    for inst in instances:
        for seed in seeds:
            for arm in arms:
                jobs.append({"solver_dir": arm["solver_dir"], "problem_dir": str(problem), "config": arm["full_config"],
                             "instance": inst, "seed": seed, "budget": {"kind": "time", "value": args.time}})
                tags.append(arm["name"])
    (out / "plan.json").write_text(json.dumps({"arms": arms, "instances": args.instances, "seeds": args.seeds,
                                               "seed_offset": args.seed_offset, "time": args.time}, indent=1))
    executor = ModalExecutor(max_cpu_hours=args.max_cpu_hours, deploy=False,
                             function=os.environ.get("MENDEL_MODAL_BG_FUNCTION", "run_batch_bg_x64"))
    index = {id(j): n for n, j in enumerate(jobs)}
    done = [0]
    raw = (out / "raw.jsonl").open("a")

    def on_batch(batch_jobs: list[dict], batch_results: list[dict]) -> None:
        batch_id = f"{time.time():.3f}"
        for job, res in zip(batch_jobs, batch_results):
            done[0] += 1
            raw.write(json.dumps({"arm": tags[index[id(job)]], "instance": job["instance"], "seed": job["seed"],
                                  "ok": res.get("ok"), "valid": res.get("valid"), "score": res.get("score"),
                                  "batch": batch_id, "error": res.get("error"),
                                  "stats": {k: v for k, v in (res.get("stats") or {}).items() if k != "trace"}}) + "\n")
        raw.flush()
        (out / "progress.json").write_text(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "jobs_done": done[0],
                                                       "jobs_total": len(jobs)}))

    results = executor.run(jobs, journal=out / "modal_calls.json", on_batch=on_batch)
    raw.close()

    # the best valid result of each arm and instance, re-checked here before it is written down
    certs = out / "certificates"
    certs.mkdir(exist_ok=True)
    best: dict = {}
    for job, tag, res in zip(jobs, tags, results):
        if res.get("ok") and res.get("valid") and res.get("score") is not None:
            key = (tag, ev.instance_key(job["instance"]))
            if key not in best or res["score"] > best[key][1]["score"]:
                best[key] = (job, res)
    summary = []
    for (tag, key), (job, res) in sorted(best.items()):
        check = ev.evaluate(job["instance"], res["solution"])
        ok = bool(check.get("valid")) and check.get("score") == res["score"]
        path = certs / f"{tag}_{key}_{res['score']:g}.json"
        path.write_text(json.dumps({"problem": problem.name, "instance": job["instance"], "score": check.get("score"),
                                    "solution": res["solution"], "seed": job["seed"], "budget_cpu_seconds": args.time,
                                    "config": job["config"], "arm": tag, "solver": os.path.relpath(job["solver_dir"], ROOT),
                                    "found": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1) + "\n")
        verifier = problem / "verify.py"
        if ok and verifier.exists():
            ok = subprocess.run([sys.executable, str(verifier), str(path)], capture_output=True, text=True).returncode == 0
        summary.append({"arm": tag, "instance": key, "best": res["score"], "verified": ok, "certificate": str(path)})
    (out / "summary.json").write_text(json.dumps({"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": summary}, indent=1))
    print(f"finished: {len(results)} runs, {len(summary)} certificates")
    return 0


if __name__ == "__main__":
    sys.exit(main())
