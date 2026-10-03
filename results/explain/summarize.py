"""Build results/explain/SUMMARY.md from the finished `mendel explain` runs.

    uv run python results/explain/summarize.py

One row per explained program. "Top switch alone" is the switch whose effect, when it alone is switched on
from the all-off configuration (the initial program), is the largest; its share is that effect over the gain.
"Everything else" is the gain minus that effect: what the remaining switches add on top of the top one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
RUNS = ROOT / "runs"

# run id -> (label, OpenEvolve program provenance, note)
PROGRAMS = [
    ("explain-oe-seed1", "1", "final best (phase 2 iteration 64 of 100)", ""),
    ("explain-oe-seed2", "2", "final best (phase 2 iteration 62 of 100)",
     "draws np.random.uniform jitter in one candidate layout; the harness seeds numpy, so each seed is reproducible"),
    ("explain-oe-seed3", "3", "best at the $15 cap (phase 2 iteration 17; the program explained first)", "decomposition A (effort medium)"),
    ("explain-oe-seed3-redo", "3", "the same program as the row above", "decomposition B (fresh session, effort high)"),
    ("explain-oe-seed3-it98", "3", "final best (phase 2 iteration 98 of 100)", ""),
    ("explain-oe-seed4", "4", "best at phase 2 checkpoint 100 (run still live when copied)", ""),
    ("explain-oe-seed5", "5", "best at phase 2 checkpoint 55 (run still live when copied)", ""),
]


def load(run_id: str) -> dict | None:
    path = RUNS / run_id / "explain.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def row(run_id: str, seed: str, provenance: str, note: str) -> dict:
    info = load(run_id)
    out = {"run": run_id, "seed": seed, "provenance": provenance, "note": note, "status": "not run"}
    if info is None:
        return out
    out["status"] = info.get("status", "running")
    ref = info.get("reference") or {}
    if ref:
        out["sha"] = ref["evolved"]["sha256"][:12]
        out["evolved_ref"] = ref["evolved"]["runs"]["0"]["score"]
        out["initial_ref"] = ref["initial"]["runs"]["0"]["score"]
        out["raw_valid"] = ref["evolved"]["runs"]["0"]["raw_valid"]
    bookend = info.get("bookend") or {}
    out["bookend"] = "passed" if bookend.get("ok") else ("FAILED" if bookend else "not run")
    out["sessions"] = len(info.get("sessions") or [])
    out["llm_usd"] = info["spend"]["llm_usd"]
    out["evaluations"] = info["spend"]["evaluations"]
    m = info.get("measure")
    if not m:
        return out
    gain = m["total"]["effect"]
    out.update(evolved=m["scores"]["all_on"], initial=m["scores"]["all_off"], gain=gain, gain_ci=m["total"]["ci"],
               seeds=len(m["seeds"]), spreads=m["spreads"])
    alone = {n: r for n, r in m["alone"].items() if r.get("runs")}
    if alone:
        top = max(alone, key=lambda n: alone[n]["effect"])
        out.update(top=top, top_alone=alone[top]["effect"], top_alone_ci=alone[top]["ci"],
                   top_share=alone[top]["effect"] / gain if abs(gain) > 1e-12 else float("nan"),
                   rest=gain - alone[top]["effect"])
        ko = m["knockouts"].get(top) or {}
        out["top_knockout"] = ko.get("effect")
    out["switches"] = list(m["knockouts"])
    out["knockouts"] = {n: r.get("effect") for n, r in m["knockouts"].items()}
    out["alone"] = {n: r.get("effect") for n, r in alone.items()}
    genes = info.get("genes") or []
    initial_alleles = [g for g in genes if g["kind"] != "switch" and g.get("of") is None]
    changed = [g["name"] for g in initial_alleles if g.get("evolved", g["default"]) != g["default"]]
    out.update(constants_changed=changed, n_initial_alleles=len(initial_alleles),
               reset_differs=m.get("reset_differs"), constants_effect=m["constants"]["effect"],
               tuning_effect=m["tuning"]["effect"], tuning_trials=m["tuning"]["trials"])
    return out


def fmt(x, digits=4):
    return "n/a" if x is None or isinstance(x, str) else f"{x:+.{digits}f}"


def main() -> int:
    rows = [row(*p) for p in PROGRAMS]
    done = [r for r in rows if r.get("gain") is not None]
    L = ["# `mendel explain` across OpenEvolve runs (circle packing, n = 26)", "",
         "Every row is one OpenEvolve program (claude-haiku-4-5, the two-phase recipe) decomposed into named "
         "switches by one LLM session and then measured by knockouts with no LLM. Scores are repaired, strictly "
         "feasible sums of radii under the exact evaluator (best known 2.635983). The initial program scores "
         "0.959765 in every row. \"Top switch alone\" is the single switch that adds the most when switched on "
         "alone from the initial program; its share is that effect over the gain; \"everything else\" is the "
         "gain minus it, that is what all the other switches add on top of the top one (shares overlap, so the "
         "two columns do not describe disjoint parts). \"Constants changed\" asks whether any numeric constant "
         "of the initial program has a different value in the evolved program.", "",
         "| seed | program | evolved score | gain | top switch alone | share | everything else | constants changed | bookend | decomposition cost |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        if r["status"] == "not run":
            continue
        if r.get("gain") is None:
            L.append(f"| {r['seed']} | {r['provenance']} (sha {r.get('sha', '?')}) | {r.get('evolved_ref', float('nan')):.6f} | "
                     f"n/a | n/a | n/a | n/a | n/a | {r['bookend']} ({r['status']}) | ${r['llm_usd']:.2f}, {r['sessions']} session(s) |")
            continue
        const = (", ".join(f"`{c}`" for c in r["constants_changed"])) if r["constants_changed"] else \
            f"no ({r['n_initial_alleles']} exposed)"
        sp = r["spreads"]
        stochastic = any(v for v in sp.values() if v)
        L.append(f"| {r['seed']} | {r['provenance']}{'; ' + r['note'] if r['note'] else ''} (sha {r['sha']}) | "
                 f"{r['evolved']:.6f} | {r['gain']:+.4f} | `{r['top']}` {fmt(r['top_alone'])} | "
                 f"{100 * r['top_share']:.0f}% | {fmt(r['rest'])} | {const} | {r['bookend']} | "
                 f"${r['llm_usd']:.2f}, {r['sessions']} session(s) |")
    L.append("")
    L += ["Per-switch detail (knockout = all on minus all on with the switch off; alone = all off with the switch "
          "on minus all off; score units):", ""]
    for r in done:
        L.append(f"- **seed {r['seed']}, `{r['run']}`** ({r['seeds']} seeds; "
                 + ("every arm identical across seeds, so intervals have zero width"
                    if not any(v for v in r['spreads'].values() if v) else
                    f"largest within-arm spread across seeds {max(v for v in r['spreads'].values() if v):.4f}, so intervals are real")
                 + f"): " + "; ".join(f"`{n}` knockout {fmt(r['knockouts'][n])}, alone {fmt(r['alone'].get(n))}"
                                      for n in r["switches"])
                 + f". Tuning the initial program's constants alone: {fmt(r['tuning_effect'])} ({r['tuning_trials']} trials)"
                 + (f"; resetting the evolved constants with every switch on changes the score by {fmt(-r['constants_effect'])}"
                    if r["reset_differs"] else "") + ".")
    L.append("")
    out = ROOT / "results" / "explain" / "SUMMARY_table.md"
    out.write_text("\n".join(L))
    print("\n".join(L))
    print(f"\nwrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
