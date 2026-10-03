#!/usr/bin/env python3
"""Turn campaign certificates into record claims, checked against the leaderboard as it is NOW.

    python results/heilbronn/claim_records.py --leaderboard /path/to/heilbronn-site [campaign dirs ...]

`--leaderboard` is a clone of https://github.com/tejstead/heilbronn-site that you have just pulled; the
published value of each instance is read from data/canonical/<shape>/nNN.json (verify.value_fraction),
never from this repository's problem.toml, because records there move daily. Campaign directories default
to runs/heilbronn-campaign-*.

For every certificate (<campaign>/certificates/*.json) this script
  1. re-evaluates the point set with problems/heilbronn/evaluate.py (exact integers),
  2. checks it again with problems/heilbronn/verify.py (independent, exact rationals),
  3. compares the exact value with the published exact fraction. A claim needs value - published > 1e-9,
     the campaign runner's margin, so a tie or a re-polish of the same configuration is never a claim.
For each claim it copies the certificate to results/heilbronn/certificates/, writes the leaderboard's
submission files (coordinates.txt and meta.json) under results/heilbronn/leaderboard/<shape>-nNN/, and
records the comparison value, the leaderboard commit and the time of reading in claims.json.

Nothing is submitted or posted anywhere. Exit status 0 always; read the table it prints.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "problems" / "heilbronn"
MARGIN = Fraction(1, 10 ** 9)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"heilbronn_{name}", PACK / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaigns", nargs="*")
    ap.add_argument("--leaderboard", required=True, help="an up-to-date clone of tejstead/heilbronn-site")
    ap.add_argument("--results", default=str(ROOT / "results" / "heilbronn"))
    ap.add_argument("--credit", help='meta.json credit, "Human Name, Month YYYY"')
    args = ap.parse_args(argv)

    sys.dont_write_bytecode = True
    ev, vf, lb = _load("evaluate"), _load("verify"), _load("to_leaderboard")
    board = Path(args.leaderboard)
    commit = subprocess.run(["git", "log", "-1", "--format=%H %cI"], cwd=board, capture_output=True, text=True).stdout.strip()
    read_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    campaigns = [Path(c) for c in args.campaigns] or sorted((ROOT / "runs").glob("heilbronn-campaign-*"))
    results = Path(args.results)

    best: dict[str, tuple[Fraction, Path, dict]] = {}
    for campaign in campaigns:
        for path in sorted((campaign / "certificates").glob("*.json")):
            cert = json.loads(path.read_text())
            out = ev.evaluate(cert.get("instance"), cert.get("solution"))
            reason, value = vf.check(cert)
            if not out["valid"] or reason is not None or Fraction(out["detail"]["value_fraction"]) != value:
                print(f"REJECTED {path}: evaluate valid={out['valid']}, verify: {reason}")
                continue
            key = ev.instance_key(cert["instance"])
            if key not in best or value > best[key][0]:
                best[key] = (value, path, cert)

    claims = []
    print(f"leaderboard commit {commit or 'UNKNOWN'}, read {read_at}")
    print(f"{'instance':12s} {'ours':>22s} {'published':>22s} {'ours/published':>14s}  verdict")
    for key, (value, path, cert) in sorted(best.items()):
        shape, n = cert["instance"]["shape"], cert["instance"]["n"]
        canonical = board / "data" / "canonical" / shape / f"n{n:02d}.json"
        if not canonical.exists():
            print(f"{key:12s} {float(value):22.18f} {'no entry':>22s} {'':14s}  the leaderboard has no entry: not a record claim")
            continue
        published = Fraction(json.loads(canonical.read_text())["verify"]["value_fraction"])
        ratio = float(value / published)
        if value - published > MARGIN:
            verdict = "BEATS the published value"
            (results / "certificates").mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, results / "certificates" / path.name)
            note = (f"Found by the mendel seed solver (multi-start with LP active-set polish, config {json.dumps(cert.get('config'))}, "
                    f"seed {cert.get('seed')}, {cert.get('budget_cpu_seconds')} CPU-seconds).")
            extra = ["--note", note] + (["--credit", args.credit] if args.credit else [])
            lb.main([str(path), str(results / "leaderboard"), *extra])
            claims.append({"instance": key, "value": ev.decimal30(value), "value_fraction": f"{value.numerator}/{value.denominator}",
                           "published": ev.decimal30(published), "published_fraction": f"{published.numerator}/{published.denominator}",
                           "relative_gain": ratio - 1.0, "certificate": f"results/heilbronn/certificates/{path.name}",
                           "leaderboard_files": f"results/heilbronn/leaderboard/{shape}-n{n:02d}/",
                           "leaderboard_commit": commit, "leaderboard_read": read_at, "found_in": str(path)})
        elif value >= published:
            verdict = "tie within the 1e-9 margin: not a record"
        else:
            verdict = "below the published value"
        print(f"{key:12s} {float(value):22.18f} {float(published):22.18f} {ratio:14.6f}  {verdict}")
    if claims:
        (results / "claims.json").write_text(json.dumps({"claims": claims}, indent=1) + "\n")
        print(f"{len(claims)} claim(s) written to {results / 'claims.json'}; both checkers passed for each.")
    else:
        print("no certificate beats the current leaderboard value")
    return 0


if __name__ == "__main__":
    sys.exit(main())
