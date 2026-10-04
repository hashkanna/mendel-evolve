"""Write results/no5sphere/update_comment.md: the text of our comment on DeepMind's problem 60 record thread.

    python scripts/make_thread_update.py COMMIT

COMMIT is the commit that holds the certificates (the links in the comment point at it). The table comes
from the best certificate per grid size in results/no5sphere/certificates, and the checker output quoted
in the comment is produced here by running third_check.py on exactly those files.
"""

import glob
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CERTS = os.path.join(ROOT, "results/no5sphere/certificates")
PUBLIC_SOURCE = {15: "Demonstrandum `cert_n15_m40`, matched by milesandmistakes in this thread", 16: "Demonstrandum `cert_n16_m42`"}
POSTED_FIRST = {15: 41, 16: 43, 17: 46, 21: 56, 23: 61, 24: 64, 25: 66, 26: 68, 28: 74, 29: 76, 30: 79, 31: 80, 32: 84,
                33: 86, 34: 90, 35: 91, 36: 94, 37: 96, 38: 98, 39: 100, 40: 103}


def variant(cert: dict) -> str:
    solver = cert.get("solver") or ""
    if "champion" in solver:           # the evolved champion of run p60, or a variant of it
        return "variant A"
    if "multi_recreate" in solver:
        return "variant B"
    if "LLM idea" in solver:
        return "variant C (" + re.search(r"LLM idea (\w+)", solver).group(1) + ")"
    return "base search"


def main() -> None:
    commit = sys.argv[1]
    published = {int(k[1:]): r["value"] for k, r in
                 json.load(open(os.path.join(ROOT, "problems/no5sphere/records.json")))["records"].items()}
    best: dict = {}
    for path in glob.glob(os.path.join(CERTS, "n*_*.json")):
        m = re.fullmatch(r"n(\d+)_(\d+)\.json", os.path.basename(path))
        if m and (int(m.group(1)) not in best or int(m.group(2)) > best[int(m.group(1))][0]):
            best[int(m.group(1))] = (int(m.group(2)), os.path.basename(path), json.load(open(path)))
    records = [n for n in sorted(best) if n <= 32 and best[n][0] > published[n]]
    large = [n for n in sorted(best) if n > 32]

    cache_path = os.environ.get("THIRD_CHECK_CACHE")
    cache = json.load(open(cache_path)) if cache_path and os.path.exists(cache_path) else {}

    def check(n: int) -> str:
        if best[n][1] in cache:
            return cache[best[n][1]]
        done = subprocess.run([sys.executable, os.path.join(ROOT, "results/no5sphere/third_check.py"),
                               os.path.join(CERTS, best[n][1])], capture_output=True, text=True)
        line = done.stdout.strip().splitlines()[-1]
        if done.returncode != 0 or "-> VALID" not in line:
            raise SystemExit(f"third_check failed for {best[n][1]}: {done.stdout} {done.stderr}")
        return os.path.basename(line.split(":")[0]) + ":" + line.split(":", 1)[1]

    with ThreadPoolExecutor(8) as pool:
        lines = list(pool.map(check, records + large))
    if cache_path:
        json.dump({best[n][1]: line for n, line in zip(records + large, lines)}, open(cache_path, "w"))

    def source(n: int) -> str:
        if n in PUBLIC_SOURCE:
            return PUBLIC_SOURCE[n]
        if n <= 26:
            return "0thernet's comment above (2026-09-25)"
        return "algal-lab claims file, round 27 (2026-09-25)"

    rows = []
    for n in records:
        score, name, cert = best[n]
        note = "" if POSTED_FIRST.get(n) == score else (f" (was {POSTED_FIRST[n]} when first posted)" if n in POSTED_FIRST else " (new size)")
        rows.append(f"| {n} | {published[n]} | {source(n)} | **{score}**{note} | {variant(cert)} |")
    changed = [n for n in records + large if POSTED_FIRST.get(n) != best[n][0]]

    def antipodal(n: int) -> bool:
        pts = {tuple(p) for p in best[n][2]["solution"]}
        return sum(1 for p in pts if tuple(n - 1 - v for v in p) in pts) >= len(pts) - 1
    paired_sets = sum(antipodal(n) for n in records + large)
    ties = [n for n in range(13, 33) if n not in records]
    base = f"https://github.com/hashkanna/mendel-evolve/tree/{commit}/results/no5sphere"
    text = f"""**Certificate-backed lower bounds at {len(records)} sizes from n = {records[0]} to {records[-1]}, and point sets for n = 33 to 40**

*Edited on 2026-10-04 with the results of deeper searches: the entries for n = {", ".join(str(n) for n in changed)} are new or improved since this comment was first posted. Everything below is the current state.*

This extends my comment above. Same convention as before: lower bounds only, no optimality claim. "Apparently new" means new relative to the public sources I could find on 2026-10-03 (this issue, #4 and #7; the milesandmistakes v1.1.1 release; the Demonstrandum Zenodo bundle; the algal-lab claims file `no-five-on-sphere-frontier.json`; a GitHub and web search), with this repository's issues and the algal-lab claims file re-checked on 2026-10-04. It is not guaranteed priority.

| n | best public value I found | source | new certificate | found by |
|---:|---:|---|---:|---|
{chr(10).join(rows)}

At n = {", ".join(str(n) for n in ties)} the searches equal the public values ({", ".join(str(published[n]) for n in ties)}) and do not exceed them.

For n = 33 to 40 I found no published point sets, so the only public baseline is the monotone closure of the n = 32 value. Sets from the same searches: {", ".join(str(best[n][0]) for n in large)} points. Far fewer runs were made at these sizes, so I would read them as under-searched rather than hard.

Certificates, with 0-based coordinates in `{{0,...,n-1}}^3` and the seed, CPU budget and solver configuration of the run that found each one: {base}/certificates

**Verification.** Every set passes three independent exact-integer checks over every 5-subset, with zero degenerate 5-subsets and minimum |det| = 2 in each:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants of the 5x5 matrix with rows `[x, y, z, x^2+y^2+z^2, 1]`
- `problems/no5sphere/verify.py`: Bareiss elimination in Python integers
- `results/no5sphere/third_check.py`: for every 4-subset, the integer coefficients of its sphere or plane from 4x4 cofactors, then one dot product per remaining point

Output of the third checker on the files in the table (pure Python, no dependencies):

```
{chr(10).join(lines)}
```

**How they were found.** One exact ruin-and-recreate local search in C, started from scratch at every size, in three variants. {"Every set is" if paired_sets == len(records) + len(large) else f"{paired_sets} of the {len(records) + len(large)} sets are"} built from antipodal pairs about the cube centre (p together with (n-1, n-1, n-1) - p), some with one extra unpaired point.

- *Base search:* 100 to 500 seeded runs per size at 90 to 720 CPU-seconds.
- *Variant A:* the same code with constants tuned by an automatic tuner (far fewer restarts: a kick only after about 30,000 steps without improvement, instead of 3,000), plus two small modifications that did not measurably matter.
- *Variant B:* after each ruin, the hole is refilled several times and the best refill kept, instead of once. The ruin is the expensive step, so the extra refills are nearly free.
- *Variant C:* a search arm with one other proposed modification switched on. These arms were part of a screen of 30 modifications; the one named found the set, which is not evidence that it helped.

What we measured about why, for anyone searching these sizes. All comparisons use the same seeds, with both arms in the same container, 600 paired runs at n = 23, 26, 28 and 31 and 240 CPU-seconds:

- The antipodal constraint is worth +0.13 points on the mean (95% interval 0.06 to 0.20) and takes the share of runs that beat the previous public value from 10% to 34%.
- Variant B is worth +0.19 (0.11 to 0.28) in one experiment and +0.31 (0.22 to 0.39) in a second.
- Variant A is worth +0.24 (0.18 to 0.29) over the base search without the antipodal constraint, and +0.12 with it.
- Ten other modifications tested the same way gave nothing resolved above +0.03 points.
- A caution we learned the hard way: comparing two searches that ran on different machines can show differences of 0.1 points that are not real. Identical runs on different containers differed by 0.06 on the mean.

Variant B was proposed by an LLM inside an evolutionary pipeline and rejected by that pipeline's own quick screening (48 paired runs of 45 CPU-seconds), which could not resolve effects of this size. As 0thernet reported for their pipeline, the evolutionary layer is not what found these: the sets come from a fixed local search, a symmetry constraint, one refill trick and compute. Per-run scores and the scripts behind these numbers: {base}/paired_scores.json and {base}/paired_effects.py.

**Disclosure.** These came out of a hackathon project, MendelEvolve (London AI x Science Hackathon, 3 to 4 October 2026). The search code, the checkers and this post were produced with an AI coding agent (Claude) under my direction. No search code from other contributors was read or used; the prose descriptions in this thread were read, and published certificates were used only to validate the checkers. I take responsibility for the claim; it rests on the published coordinates and the exact checkers, not on trust in model output.

Corrections welcome: if anyone knows of an earlier public certificate at or above any of these values, I will amend the table.
"""
    open(os.path.join(ROOT, "results/no5sphere/update_comment.md"), "w").write(text)
    print(f"wrote update_comment.md: {len(records)} record sizes, changed since first posted: {changed}")


if __name__ == "__main__":
    main()
