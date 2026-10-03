#!/usr/bin/env python3
"""Read-only collector for an autocorr3 campaign whose driver process is gone or still waiting.

    uv run python results/autocorr3/collect_campaign.py runs/autocorr3-campaign-2 1024,4096 [--seeds 32] [--write]

It reads the Modal call ids from <run>/modal_calls.json (written by mendel.campaign), fetches the
calls that have finished (FunctionCall.get(timeout=0): it starts nothing and spends nothing), and
re-checks every result here with problems/autocorr3/evaluate.py. With --write it also writes
<run>/collected.json (all finished runs) and, per instance, a certificate for the best run under
<run>/certificates/, checked with problems/autocorr3/verify.py.

Why this exists: re-running `mendel.campaign` only re-attaches to the calls if the solver and
problem directories are byte-identical to what was submitted; otherwise it submits everything again.
The instances must be given in the order of the original command; calls are matched to
(instance, seed) the way ModalExecutor orders them (by instance JSON, then seed).
"""
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent.parent


def main() -> int:
    run = Path(sys.argv[1])
    sizes = [int(v) for v in sys.argv[2].split(",")]
    count = int(sys.argv[sys.argv.index("--seeds") + 1]) if "--seeds" in sys.argv else 32
    seeds = list(range(1000, 1000 + count))
    spec = importlib.util.spec_from_file_location("ac3_evaluate", ROOT / "problems/autocorr3/evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)

    ids = json.loads((run / "modal_calls.json").read_text())["call_ids"]
    jobs = [(n, s) for n in sorted(sizes, key=lambda n: json.dumps({"n": n}, sort_keys=True)) for s in seeds]
    if len(ids) != len(jobs):
        print(f"journal has {len(ids)} calls, expected {len(jobs)}: wrong instances or seeds?")
        return 2
    done, pending, failed = {}, 0, 0
    for call_id, (n, seed) in zip(ids, jobs):
        try:
            out = modal.FunctionCall.from_id(call_id).get(timeout=0)
        except TimeoutError:
            pending += 1
            continue
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"n{n} seed {seed}: call failed: {exc!r}"[:300])
            continue
        res = out[0] if isinstance(out, list) and out else {}
        if not (res.get("ok") and res.get("valid")):
            failed += 1
            print(f"n{n} seed {seed}: {str(res.get('error'))[:300]}")
            continue
        check = ev.evaluate({"n": n}, res["solution"])
        if not check["valid"]:
            failed += 1
            print(f"n{n} seed {seed}: local evaluator rejects the remote solution: {check['detail']}")
            continue
        done[(n, seed)] = {"instance": {"n": n}, "seed": seed, "score_remote": res["score"],
                           "score_local": check["score"], "solution": res["solution"],
                           "iters": (res.get("stats") or {}).get("iters")}
    print(f"{time.strftime('%H:%M:%S')} {run.name}: {len(done)} finished, {pending} pending, {failed} failed")
    for n in sizes:
        rows = sorted((v for (m, _), v in done.items() if m == n), key=lambda v: v["score_local"])
        if not rows:
            continue
        scores = [v["score_local"] for v in rows]
        same = sum(v["score_local"] == v["score_remote"] for v in rows)
        print(f"  n{n}: {len(rows)} runs, best {scores[0]!r} (seed {rows[0]['seed']}), median {scores[len(scores) // 2]:.6f}, "
              f"mean {sum(scores) / len(scores):.6f}, worst {scores[-1]:.6f}; "
              f"remote score == local score bit for bit in {same}/{len(rows)}, "
              f"largest difference {max(abs(v['score_local'] - v['score_remote']) for v in rows):.1e}")
        if "--write" in sys.argv:
            best = rows[0]
            certs = run / "certificates"
            certs.mkdir(parents=True, exist_ok=True)
            path = certs / f"n{n}_{repr(best['score_local']).replace('.', 'p')}.json"
            path.write_text(json.dumps({"problem": "autocorr3", "instance": {"n": n}, "score": best["score_local"],
                                        "solution": best["solution"], "seed": best["seed"],
                                        "provenance": "from scratch: solvers/autocorr3 via mendel.campaign on Modal; "
                                                      "collected by results/autocorr3/collect_campaign.py",
                                        "found": time.strftime("%Y-%m-%dT%H:%M:%S")}, indent=1) + "\n")
            verdict = subprocess.run([sys.executable, str(ROOT / "problems/autocorr3/verify.py"), str(path)],
                                     capture_output=True, text=True)
            print(f"    certificate {path}: verify.py says {verdict.stdout.strip() or verdict.stderr.strip()}")
    if "--write" in sys.argv and done:
        (run / "collected.json").write_text(json.dumps(
            [{k: v for k, v in row.items() if k != "solution"} for row in done.values()], indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
