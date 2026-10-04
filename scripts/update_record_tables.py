"""Rewrite the problem 60 record tables from the certificates in results/no5sphere/certificates.

    python scripts/update_record_tables.py

Updates the table between the `records` markers in RESULTS.md and docs/index.html, and the records strip
of the p60 run (runs/p60/records.json and, because that run is finished, its state.json). Prints the
number of record sizes so that the prose elsewhere can be kept in step.
"""

import glob
import json
import os
import re
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "results/no5sphere/certificates")


def provenance(cert: dict) -> str:
    text = cert.get("solver")
    if text:
        text = re.sub(r"^results/no5sphere/evolved_solver \(.*?\), with centrosymmetric on$",
                      "evolved champion of run p60 with centrosymmetric", text)
        return text
    return "seed solver" + (" with centrosymmetric" if (cert.get("config") or {}).get("centrosymmetric") else "")


def main() -> None:
    published = {int(k[1:]): r["value"] for k, r in
                 json.load(open(os.path.join(ROOT, "problems/no5sphere/records.json")))["records"].items()}
    best: dict = {}
    for path in glob.glob(os.path.join(CERTS, "n*_*.json")):
        m = re.fullmatch(r"n(\d+)_(\d+)\.json", os.path.basename(path))
        if not m:
            continue
        n, score = int(m.group(1)), int(m.group(2))
        if n not in best or score > best[n][0]:
            best[n] = (score, os.path.basename(path), json.load(open(path)))
    records = [(n, *best[n]) for n in sorted(best) if n <= 32 and best[n][0] > published[n]]

    rows = ["| n | ours | published | certificate | found by |", "|---|---|---|---|---|"]
    for n, score, name, cert in records:
        rows.append(f"| {n} | **{score}** | {published[n]} | [{name}](results/no5sphere/certificates/{name}) | {provenance(cert)} |")
    replace_block(os.path.join(ROOT, "RESULTS.md"), "\n".join(rows))
    html = ["    <tr><th>n</th><th>ours</th><th>best published</th></tr>"]
    html += [f"    <tr><td>{n}</td><td><b>{score}</b></td><td>{published[n]}</td></tr>" for n, score, _, _ in records]
    replace_block(os.path.join(ROOT, "docs/index.html"), "\n".join(html))

    strip = []
    for n, score, name, cert in records:
        strip.append({"instance": f"n{n}", "value": score, "best_known": published[n], "verified": True,
                      "checks": ["evaluate.py", "verify.py", "third_check.py"],
                      "certificate": f"results/no5sphere/certificates/{name}",
                      "source": f"separate record search: {provenance(cert)}, seed {cert.get('seed')}, "
                                f"{cert.get('budget_cpu_seconds'):g} CPU-seconds; not the engine's champion run"})
    run = os.path.join(ROOT, "runs/p60")
    if os.path.isdir(run):
        write_atomic(os.path.join(run, "records.json"), json.dumps(strip, indent=1))
        state = json.load(open(os.path.join(run, "state.json")))
        if state["run"]["status"] != "running":
            own = [r for r in state.get("records", []) if str(r.get("certificate", "")).startswith("certificates/")
                   and (r["instance"], r["value"]) not in {(s["instance"], s["value"]) for s in strip}]
            state["records"] = strip + own
            write_atomic(os.path.join(run, "state.json"), json.dumps(state))
    print(f"{len(records)} record sizes:", ", ".join(f"n{n}={score}" for n, score, _, _ in records))
    print("first sets for n = 33 to 40:", ", ".join(str(best[n][0]) for n in sorted(best) if n > 32))


def replace_block(path: str, body: str) -> None:
    text = open(path).read()
    start, end = "<!-- records:start -->", "<!-- records:end -->"
    if start not in text or end not in text:
        raise SystemExit(f"{path}: add the markers {start} and {end} around the table first")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    open(path, "w").write(head + start + "\n" + body + "\n" + end + tail)


def write_atomic(path: str, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path))
    os.write(fd, text.encode())
    os.close(fd)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
