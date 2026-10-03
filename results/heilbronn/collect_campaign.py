#!/usr/bin/env python3
"""Collect a Heilbronn campaign whose driver process died, from the journal of Modal call ids.

    uv run python results/heilbronn/collect_campaign.py runs/heilbronn-campaign-2            # progress only
    uv run python results/heilbronn/collect_campaign.py runs/heilbronn-campaign-2 --wait     # block, then write
    uv run python results/heilbronn/collect_campaign.py runs/heilbronn-campaign-2 --partial  # use what is done

Why this exists: `python -m mendel.campaign` can pick its results up again from <out>/modal_calls.json, but
only if the solver and problem directories are byte-identical to what they were at launch (the journal's
fingerprint covers their content hashes), and the problem pack gained files after two of the campaigns
were submitted. This script reads the same journal and fetches the same calls by id, whatever the
directories look like now. It starts nothing on Modal. The results then go through
mendel.campaign.run_campaign itself, so the local re-evaluation, the independent verify.py check, the
certificates and campaign_summary.json are exactly the campaign runner's.

The launch parameters are read from <out>/launch.json (instances, config, seeds, seed_offset, time).
Each call holds exactly one job because every job is longer than the executor's 120-second batch size;
the job order is the executor's: sorted by (instance JSON, seed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def fetch(call_id: str, wait: bool):
    """The call's output (a list with one result), or None if it is still pending."""
    import modal

    try:
        return modal.FunctionCall.from_id(call_id).get(timeout=None if wait else 0)
    except TimeoutError:
        return None


class JournalCollector:
    estimated_usd = 0.0

    def __init__(self, wait: bool, partial: bool):
        self.wait, self.partial = wait, partial
        self.done = self.pending = 0

    def run(self, jobs: list[dict], journal: Path | None = None) -> list[dict]:
        call_ids = json.loads(Path(journal).read_text())["call_ids"]
        order = sorted(range(len(jobs)), key=lambda i: (json.dumps(jobs[i]["instance"], sort_keys=True), jobs[i]["seed"]))
        if len(call_ids) != len(jobs):
            raise SystemExit(f"journal has {len(call_ids)} calls but launch.json describes {len(jobs)} jobs")
        results: list[dict | None] = [None] * len(jobs)
        for i, call_id in zip(order, call_ids):
            failed = {"ok": False, "valid": False, "score": None, "stats": {}, "wall": 0.0, "solution": None}
            try:
                out = fetch(call_id, self.wait) if call_id else None
            except Exception as exc:  # noqa: BLE001 - a failed call is a failed result
                results[i] = {**failed, "error": f"modal call failed: {exc!r}"[:500]}
                self.done += 1
                continue
            if out is None:
                self.pending += 1
                results[i] = {**failed, "error": "pending: not finished when collected"}
                continue
            self.done += 1
            res = out[0] if isinstance(out, list) and len(out) == 1 else {**failed, "error": f"unexpected output {out!r}"[:300]}
            solution = res.get("solution")
            if solution is not None and len(solution) != jobs[i]["instance"]["n"]:
                res = {**failed, "error": "result does not belong to this job (point count differs)"}
            results[i] = res
        if self.pending and not self.partial:
            raise SystemExit(f"{self.done} of {len(jobs)} calls finished, {self.pending} pending; "
                             "nothing written (use --wait to block or --partial to use what is done)")
        return results  # type: ignore[return-value]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("campaign", help="campaign output directory with modal_calls.json and launch.json")
    ap.add_argument("--wait", action="store_true")
    ap.add_argument("--partial", action="store_true")
    args = ap.parse_args(argv)
    from mendel.campaign import run_campaign

    out_dir = Path(args.campaign)
    launch = json.loads((out_dir / "launch.json").read_text())
    solver, problem = (ROOT / launch["solver"]).resolve(), (ROOT / launch["problem"]).resolve()
    config = {g["name"]: g["default"] for g in json.loads((solver / "genes.json").read_text())["genes"]}
    config.update(launch["config"])
    collector = JournalCollector(args.wait, args.partial)
    rows = run_campaign(solver_dir=solver, problem_dir=problem, config=config, instances=launch["instances"],
                        seeds=list(range(launch["seed_offset"], launch["seed_offset"] + launch["seeds"])),
                        time_s=float(launch["time"]), executor=collector, out_dir=out_dir)
    print(f"{collector.done} calls collected, {collector.pending} pending")
    print(f"{'instance':12s} {'best':>21s} {'mean':>21s} {'published':>21s} {'best/pub':>8s} runs verified record")
    for r in rows:
        ratio = f"{r['value'] / r['best_known']:.4f}" if r["value"] and r["best_known"] else "-"
        print(f"{r['instance']:12s} {str(r['value']):>21s} {str(r['mean']):>21s} {str(r['best_known']):>21s} {ratio:>8s} "
              f"{r['valid_runs']:>2d}/{r['runs']:<2d} {'yes' if r['verified'] else 'NO':8s} {'beats problem.toml value' if r['record'] else ''}")
    print("A 'record' flag here is relative to problem.toml; confirm against the live leaderboard with claim_records.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
