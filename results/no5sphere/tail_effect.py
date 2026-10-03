"""What finds records on problem 60: the mean of a run, or its tail?

The engine's knockouts compare mean scores at a short budget. A record is the best of hundreds of longer
runs. This script compares search arms on the statistic that matters for records: the fraction of runs
that beat the best published value, on the same seeds and CPU budgets.

    python results/no5sphere/tail_effect.py              # tables from search_scores.json
    python results/no5sphere/tail_effect.py --collect    # rebuild search_scores.json from runs/ (local only)

Arms (every run is one seeded search from scratch):
    seed                    the seed solver at its defaults
    seed+centro             the seed solver with its `centrosymmetric` switch on
    evolved                 the engine's champion (run p60, generation 7: tuned constants, `guided_ruin`,
                            and the LLM idea `kick_escalate`)
    evolved+centro          the same champion with `centrosymmetric` on
"""

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "search_scores.json")
ARMS = {
    "seed": ["w-default-tiny", "w-default-small", "w-default-mid", "w-default-large"],
    "seed+centro": ["w-centro-tiny", "w-centro-small", "w-centro-mid", "w-centro-large"],
    "evolved": ["w3-evo-tiny", "w3-evo-small", "w3-evo-mid", "w3-evo-large"],
    "evolved+centro": ["w3-evoc-tiny", "w3-evoc-small", "w3-evoc-mid", "w3-evoc-large"],
}
RECORD_SIZES = ["n15", "n16", "n17", "n21", "n23", "n24", "n25", "n26", "n28", "n29", "n30", "n31", "n32"]


def collect() -> None:
    published = {k: r["value"] for k, r in
                 json.load(open(os.path.join(ROOT, "problems/no5sphere/records.json")))["records"].items()}
    arms: dict = {}
    for arm, runs in ARMS.items():
        cells: dict = {}
        for run in runs:
            path = os.path.join(ROOT, "runs", run, "campaign_raw.jsonl")
            if not os.path.exists(path):
                continue
            for line in open(path):
                r = json.loads(line)
                if not (r.get("ok") and r.get("valid")):
                    continue
                key = f"n{r['instance']['n']}"
                cell = cells.setdefault(key, {"cpu_seconds": r["time"], "scores": {}})
                cell["scores"][str(r["seed"])] = int(r["score"])
        if cells:
            arms[arm] = cells
    json.dump({"note": "Scores of every run in the problem 60 record searches, by arm, grid size and seed. "
                       "Built by tail_effect.py --collect from the raw search logs.",
               "published": {k: published[k] for k in sorted(published, key=lambda s: int(s[1:])) if 13 <= int(k[1:]) <= 32},
               "arms": arms}, open(DATA, "w"), indent=0, separators=(",", ":"))
    print("wrote", DATA, {a: sum(len(c["scores"]) for c in cells.values()) for a, cells in arms.items()})


def boot_ci(per_size: list, stat, n_boot: int = 4000, rng_seed: int = 0) -> tuple:
    """95% interval of stat(a, b) under a bootstrap that resamples seeds within each grid size.
    per_size: [(scores_a, scores_b, published)] with scores paired by seed."""
    rng = random.Random(rng_seed)
    values = []
    for _ in range(n_boot):
        sample = []
        for a, b, p in per_size:
            idx = [rng.randrange(len(a)) for _ in a]
            sample.append(([a[i] for i in idx], [b[i] for i in idx], p))
        values.append(stat(sample))
    values.sort()
    return values[int(0.025 * n_boot)], values[int(0.975 * n_boot) - 1]


def beat_rate_diff(sample: list) -> float:
    runs = sum(len(a) for a, _, _ in sample)
    return (sum(sum(x > p for x in a) for a, _, p in sample) - sum(sum(x > p for x in b) for _, b, p in sample)) / runs


def mean_diff(sample: list) -> float:
    return sum(sum(a) / len(a) - sum(b) / len(b) for a, b, _ in sample) / len(sample)


def compare(data: dict, arm_a: str, arm_b: str, sizes: list) -> None:
    arms, pub = data["arms"], data["published"]
    if arm_a not in arms or arm_b not in arms:
        return
    per_size = []
    for key in sizes:
        ca, cb = arms[arm_a].get(key), arms[arm_b].get(key)
        if not ca or not cb:
            continue
        seeds = sorted(set(ca["scores"]) & set(cb["scores"]), key=int)
        per_size.append(([ca["scores"][s] for s in seeds], [cb["scores"][s] for s in seeds], pub[key]))
    if not per_size:
        return
    runs = sum(len(a) for a, _, _ in per_size)
    beat_a = sum(sum(x > p for x in a) for a, _, p in per_size)
    beat_b = sum(sum(x > p for x in b) for _, b, p in per_size)
    lo, hi = boot_ci(per_size, beat_rate_diff)
    mlo, mhi = boot_ci(per_size, mean_diff)
    print(f"{arm_a} against {arm_b}, {len(per_size)} sizes, {runs} paired runs per arm:")
    print(f"  runs above the published value: {beat_a} ({100 * beat_a / runs:.1f}%) against {beat_b} "
          f"({100 * beat_b / runs:.1f}%); difference {100 * (beat_a - beat_b) / runs:+.1f} points "
          f"[{100 * lo:+.1f}, {100 * hi:+.1f}]")
    print(f"  mean score, averaged over sizes: {mean_diff(per_size):+.3f} points [{mlo:+.3f}, {mhi:+.3f}]")


def main() -> None:
    if "--collect" in sys.argv:
        collect()
    data = json.load(open(DATA))
    arms, pub = data["arms"], data["published"]
    names = [a for a in ARMS if a in arms]
    print("| n | published | " + " | ".join(f"{a}: best, mean, runs above published" for a in names) + " |")
    print("|---|---|" + "---|" * len(names))
    for key in sorted(pub, key=lambda s: int(s[1:])):
        cells = []
        for a in names:
            c = arms[a].get(key)
            if not c:
                cells.append("")
                continue
            s = list(c["scores"].values())
            cells.append(f"{max(s)}, {sum(s) / len(s):.2f}, {sum(x > pub[key] for x in s)} of {len(s)}")
        print(f"| {key[1:]} | {pub[key]} | " + " | ".join(cells) + " |")
    print()
    all_sizes = sorted(pub, key=lambda s: int(s[1:]))
    for a, b in [("seed+centro", "seed"), ("evolved", "seed"), ("evolved+centro", "seed+centro")]:
        compare(data, a, b, RECORD_SIZES)
        compare(data, a, b, all_sizes)


if __name__ == "__main__":
    main()
