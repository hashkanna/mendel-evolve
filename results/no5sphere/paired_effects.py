"""Effects at record scale, measured with every arm of a seed in the same container.

    python results/no5sphere/paired_effects.py              # tables from paired_scores.json
    python results/no5sphere/paired_effects.py --collect    # rebuild paired_scores.json from runs/ (local only)
    python results/no5sphere/paired_effects.py --page       # also write docs/record-scale.html

Two experiments (scripts/paired_search.py), each 150 seeds at n = 23, 26, 28, 31 for 240 CPU-seconds:
`paired-1` has the seed solver, two identical controls (seed solver with `centrosymmetric`), the evolved
champion with and without `centrosymmetric`, and eleven LLM ideas each switched on in the control
configuration; `paired-2` combines the idea `multi_recreate` with the champion's settings. Intervals are
95% bootstrap intervals that resample seeds within each grid size.
"""

import collections
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
DATA = os.path.join(HERE, "paired_scores.json")
PUBLISHED = {"n23": 59, "n26": 67, "n28": 71, "n31": 79}


def collect() -> None:
    out = {}
    for run in ("paired-1", "paired-2"):
        path = os.path.join(ROOT, "runs", run, "raw.jsonl")
        if not os.path.exists(path):
            continue
        arms: dict = collections.defaultdict(dict)
        for line in open(path):
            r = json.loads(line)
            if r.get("ok") and r.get("valid"):
                arms[r["arm"]][f"n{r['instance']['n']}:{r['seed']}"] = int(r["score"])
        out[run] = arms
    engine = {}
    manifest = os.path.join(ROOT, "configs/deep_screen/manifest.json")
    if os.path.exists(manifest):
        for m in json.load(open(manifest))["arms"]:
            if m.get("screen_effect") is not None:
                engine[m["idea"]] = {"effect": m["screen_effect"], "ci": m["screen_ci"], "author": m["author"],
                                     "generation": m["generation"], "status": m["status"], "hypothesis": m["hypothesis"]}
    json.dump({"note": "Scores by experiment, arm and 'size:seed'. Every arm of a seed ran in the same container.",
               "published": PUBLISHED, "experiments": out, "engine_screen": engine}, open(DATA, "w"), separators=(",", ":"))
    print("wrote", DATA, {k: {a: len(v) for a, v in arms.items()} for k, arms in out.items()})


def effect(a: dict, b: dict, level: float = 0.95, n_boot: int = 10000) -> dict:
    keys = sorted(set(a) & set(b))
    by: dict = collections.defaultdict(list)
    for k in keys:
        by[k.split(":")[0]].append((a[k], b[k]))

    def stat(sample: dict) -> float:
        return sum(sum(x - y for x, y in v) / len(v) for v in sample.values()) / len(sample)

    rng = random.Random(0)
    boots = sorted(stat({k: [v[rng.randrange(len(v))] for _ in v] for k, v in by.items()}) for _ in range(n_boot))
    tail = (1 - level) / 2
    above = lambda arm: sum(arm[k] > PUBLISHED[k.split(":")[0]] for k in keys) / len(keys)
    return {"effect": stat(by), "lo": boots[int(tail * n_boot)], "hi": boots[min(n_boot - 1, int((1 - tail) * n_boot))],
            "pairs": len(keys), "above_a": above(a), "above_b": above(b),
            "differ": sum(a[k] != b[k] for k in keys) / len(keys)}


def rows(data: dict) -> list:
    p1, p2, eng = data["experiments"].get("paired-1", {}), data["experiments"].get("paired-2", {}), data["engine_screen"]
    out = []
    if p1:
        ref = [("two identical controls (noise floor)", "control2", "control", None),
               ("`centrosymmetric` (seed switch)", "control", "seed", {"effect": 0.0, "ci": [-0.19, 0.17]}),
               ("evolved champion, whole", "evolved", "seed", {"effect": 0.10, "ci": None}),
               ("evolved champion, with `centrosymmetric`", "evolved+centro", "control", None)]
        for label, a, b, screen in ref:
            if a in p1 and b in p1:
                out.append({"label": label, "kind": "reference", "screen": screen, **effect(p1[a], p1[b])})
        for idea in p1:
            if idea in ("seed", "control", "control2", "evolved", "evolved+centro"):
                continue
            s = eng.get(idea, {})
            out.append({"label": f"`{idea}`", "kind": "idea", "author": s.get("author", ""), "status": s.get("status", ""),
                        "screen": {"effect": s.get("effect"), "ci": s.get("ci")} if s else None,
                        **effect(p1[idea], p1["control"])})
    if p2:
        for label, a in (("`multi_recreate`, second experiment", "mr"), ("`multi_recreate`, six refills", "mr_m6"),
                         ("`multi_recreate` + `guided_ruin`", "mr+guided"), ("`multi_recreate` + tuned constants", "mr+tuned"),
                         ("`multi_recreate` + tuned constants + `guided_ruin`", "mr+tuned+guided")):
            if a in p2:
                out.append({"label": label, "kind": "combination", "screen": None, **effect(p2[a], p2["control"])})
    return out


def table(rs: list) -> str:
    lines = ["| | engine's quick screen (48 pairs, 45 s) | record scale: mean difference, 95% interval | runs above published | pairs that differ |",
             "|---|---|---|---|---|"]
    for r in rs:
        s = r.get("screen")
        screen = "" if not s or s.get("effect") is None else (
            f"{s['effect']:+.2f}" + (f" [{s['ci'][0]:+.2f}, {s['ci'][1]:+.2f}]" if s.get("ci") else ""))
        lines.append(f"| {r['label']} | {screen} | {r['effect']:+.2f} [{r['lo']:+.2f}, {r['hi']:+.2f}] | "
                     f"{100 * r['above_a']:.0f}% against {100 * r['above_b']:.0f}% | {100 * r['differ']:.0f}% of {r['pairs']} |")
    return "\n".join(lines)


def main() -> None:
    if "--collect" in sys.argv:
        collect()
    data = json.load(open(DATA))
    rs = rows(data)
    order = {"reference": 0, "idea": 1, "combination": 2}
    rs.sort(key=lambda r: (order[r["kind"]], -r["effect"] if r["kind"] == "idea" else 0))
    print(table(rs))
    if "--page" in sys.argv:
        sys.path.insert(0, HERE)
        import paired_page
        paired_page.write(rs, os.path.join(ROOT, "docs/record-scale.html"))
        print("wrote docs/record-scale.html")


if __name__ == "__main__":
    main()
