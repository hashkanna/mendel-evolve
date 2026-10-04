"""Gather the best verified problem 60 set per grid size from every search under runs/.

    uv run python scripts/collect_records.py            # report only
    uv run python scripts/collect_records.py --apply    # also copy improvements into results/no5sphere/certificates

A candidate is a certificate that a search wrote after re-evaluating the set locally. Before one is
copied it is checked again here with evaluate.py, verify.py and third_check.py. The table says which
solver and configuration found each set, so that a record is never credited to the wrong arm.
"""

import glob
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "results/no5sphere/certificates")
PROBLEM = os.path.join(ROOT, "problems/no5sphere")


def source_of(run: str, cert: dict) -> str:
    """Which solver produced a set, from the run it came from."""
    cfg = cert.get("config") or {}
    centro = " with centrosymmetric" if cfg.get("centrosymmetric") else ""
    if run.startswith("paired-"):
        return f"arm {cert.get('arm')} of {run}"
    if run.startswith(("w-", "w2-")):
        return "seed solver" + centro
    if run.startswith(("w3-", "w5-")):
        return "evolved champion of run p60" + centro
    if run.startswith("w4-"):
        parts = [k for k in ("guided_ruin", "kick_escalate") if cfg.get(k)]
        return "champion variant (" + (", ".join(parts) or "tuned constants only") + ")" + centro
    if run.startswith("w6-"):
        return "seed solver with the LLM idea multi_recreate" + centro
    if run.startswith("ds-"):
        return f"seed solver with the LLM idea {run[3:]}" + centro
    return run


def main() -> None:
    apply = "--apply" in sys.argv
    spec = importlib.util.spec_from_file_location("ev", os.path.join(PROBLEM, "evaluate.py"))
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    published = {k: r["value"] for k, r in json.load(open(os.path.join(PROBLEM, "records.json")))["records"].items()}
    current: dict = {}
    for path in glob.glob(os.path.join(CERTS, "n*_*.json")):
        m = re.match(r"n(\d+)_(\d+)", os.path.basename(path))
        if m:
            current[int(m.group(1))] = max(current.get(int(m.group(1)), 0), int(m.group(2)))
    best: dict = {}
    for path in glob.glob(os.path.join(ROOT, "runs/*/certificates/*.json")):
        run = path.split(os.sep)[-3]
        if run.startswith(("p60", "p59", "cp-", "abl-", "w59", "explain")):
            continue
        try:
            cert = json.load(open(path))
        except (OSError, json.JSONDecodeError):
            continue
        if cert.get("problem") not in ("no5sphere", None) or "n" not in (cert.get("instance") or {}):
            continue
        n, score = cert["instance"]["n"], int(cert["score"])
        if n not in best or score > best[n][0]:
            best[n] = (score, path, run, cert)
    print("| n | published | in the repo | best in runs/ | found by |")
    print("|---|---|---|---|---|")
    for n in sorted(best):
        score, path, run, cert = best[n]
        have = current.get(n, 0)
        flag = " **new**" if score > have and score > published.get(f"n{n}", 0) else ""
        print(f"| {n} | {published.get(f'n{n}', '')} | {have or ''} | {score}{flag} | {source_of(run, cert)} ({run}) |")
        if not (apply and flag):
            continue
        verdict = ev.evaluate(cert["instance"], cert["solution"])
        ok = bool(verdict.get("valid")) and int(verdict.get("score")) == score
        target = os.path.join(CERTS, f"n{n}_{score}.json")
        cert["solver"] = source_of(run, cert)
        json.dump(cert, open(target, "w"), indent=1)
        for checker in (os.path.join(PROBLEM, "verify.py"), os.path.join(ROOT, "results/no5sphere/third_check.py")):
            done = subprocess.run([sys.executable, checker, target], capture_output=True, text=True)
            ok = ok and done.returncode == 0 and "INVALID" not in done.stdout
        if ok:
            print(f"    copied to {os.path.relpath(target, ROOT)} after three checks")
        else:
            os.remove(target)
            print(f"    NOT copied: a check failed for {path}")


if __name__ == "__main__":
    main()
