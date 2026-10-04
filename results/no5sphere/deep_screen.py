"""Deep screen: every idea in the problem 60 ledger, measured again at record-search scale.

The engine screened each idea on 48 seed pairs at 45 CPU-seconds, which resolves about +-0.2 points.
Here each idea is switched on in the seed configuration (with `centrosymmetric` on, the configuration
that found the records) and run on 150 seeds at each of n = 23, 26, 28, 31 for 240 CPU-seconds: 600
runs per idea, paired by seed with a control arm that runs the seed solver itself.

    python results/no5sphere/deep_screen.py              # table from deep_screen_scores.json
    python results/no5sphere/deep_screen.py --collect    # rebuild that file from runs/ (local only)

Columns: mean difference in points (idea minus control) with a 95% bootstrap interval that resamples
seeds within each size; the same interval at the level that corrects for the number of ideas
(Bonferroni); the share of runs above the published value, idea against control; the share of seed
pairs whose scores differ at all. The A/A row compares the control with an earlier search of the same
solver, configuration, seeds and budget (n = 23 and 26 only): it is the noise floor of the method.
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "deep_screen_scores.json")
SIZES = ["n23", "n26", "n28", "n31"]


def _scores(run: str) -> dict:
    cells: dict = {}
    path = os.path.join(ROOT, "runs", run, "campaign_raw.jsonl")
    if not os.path.exists(path):
        return cells
    for line in open(path):
        r = json.loads(line)
        key = f"n{r['instance']['n']}"
        cells.setdefault(key, {})[str(r["seed"])] = int(r["score"]) if (r.get("ok") and r.get("valid")) else None
    return cells


def collect() -> None:
    manifest = json.load(open(os.path.join(ROOT, "configs/deep_screen/manifest.json")))
    published = {k: r["value"] for k, r in
                 json.load(open(os.path.join(ROOT, "problems/no5sphere/records.json")))["records"].items() if k in SIZES}
    arms = {}
    for m in manifest["arms"]:
        cells = _scores(m["run"])
        if cells:
            arms[m["idea"]] = {"author": m.get("author"), "generation": m.get("generation"),
                               "engine_screen": [m.get("screen_effect"), m.get("screen_ci")], "scores": cells}
    earlier = {k: v for k, v in _scores("w-centro-mid").items() if k in ("n23", "n26")}
    json.dump({"note": manifest["note"], "published": published, "cpu_seconds": manifest["time"], "arms": arms,
               "earlier_control": earlier}, open(DATA, "w"), separators=(",", ":"))
    print("wrote", DATA, "arms:", len(arms))


def paired(a: dict, b: dict, sizes: list) -> list:
    """[(scores_a, scores_b, size)] over the seeds both arms completed."""
    out = []
    for key in sizes:
        if key not in a or key not in b:
            continue
        seeds = [s for s in sorted(a[key], key=int) if a[key].get(s) is not None and b[key].get(s) is not None]
        if seeds:
            out.append(([a[key][s] for s in seeds], [b[key][s] for s in seeds], key))
    return out


def mean_diff(sample: list) -> float:
    return sum(sum(a) / len(a) - sum(b) / len(b) for a, b, _ in sample) / len(sample)


def interval(sample: list, stat, level: float, n_boot: int = 20000, seed: int = 0) -> tuple:
    rng = random.Random(seed)
    values = []
    for _ in range(n_boot):
        resampled = []
        for a, b, key in sample:
            idx = [rng.randrange(len(a)) for _ in a]
            resampled.append(([a[i] for i in idx], [b[i] for i in idx], key))
        values.append(stat(resampled))
    values.sort()
    tail = (1 - level) / 2
    return values[int(tail * n_boot)], values[min(n_boot - 1, int((1 - tail) * n_boot))]


def row(name: str, sample: list, published: dict, n_ideas: int, extra: str = "") -> tuple:
    runs = sum(len(a) for a, _, _ in sample)
    d = mean_diff(sample)
    lo, hi = interval(sample, mean_diff, 0.95)
    blo, bhi = interval(sample, mean_diff, 1 - 0.05 / max(1, n_ideas))
    beat_a = sum(sum(x > published[k] for x in a) for a, _, k in sample)
    beat_b = sum(sum(x > published[k] for x in b) for _, b, k in sample)
    differ = sum(sum(x != y for x, y in zip(a, b)) for a, b, _ in sample)
    verdict = "helps" if blo > 0 else "hurts" if bhi < 0 else "helps (95% only)" if lo > 0 else \
        "hurts (95% only)" if hi < 0 else "no effect resolved"
    text = (f"| `{name}` | {d:+.3f} | [{lo:+.3f}, {hi:+.3f}] | [{blo:+.3f}, {bhi:+.3f}] | "
            f"{100 * beat_a / runs:.1f}% vs {100 * beat_b / runs:.1f}% | {100 * differ / runs:.0f}% | {runs} | {verdict} | {extra} |")
    return d, text


def main() -> None:
    if "--collect" in sys.argv:
        collect()
    data = json.load(open(DATA))
    arms, published = data["arms"], data["published"]
    control = arms["_control"]["scores"]
    ideas = [k for k in arms if k != "_control"]
    print("| idea | mean difference | 95% interval | corrected for "
          f"{len(ideas)} ideas | runs above published: idea vs control | pairs that differ | pairs | reading | engine screen (48 pairs, 45 s) |")
    print("|---|---|---|---|---|---|---|---|---|")
    rows = []
    for name in ideas:
        sample = paired(arms[name]["scores"], control, SIZES)
        if not sample:
            continue
        e, ci = arms[name]["engine_screen"]
        extra = f"{e:+.2f} [{ci[0]:+.2f}, {ci[1]:+.2f}]" if e is not None and ci else ""
        rows.append(row(name, sample, published, len(ideas), extra))
    for _, text in sorted(rows, key=lambda r: -r[0]):
        print(text)
    aa = paired(control, data.get("earlier_control", {}), ["n23", "n26"])
    if aa:
        print(row("A/A: control vs an earlier identical search", aa, published, 1)[1])


if __name__ == "__main__":
    main()
