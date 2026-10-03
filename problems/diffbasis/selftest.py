#!/usr/bin/env python3
"""Self-test of the diffbasis pack:  uv run python problems/diffbasis/selftest.py

1. On the published top solutions (published/best_3.json), evaluate.py, the arena's verbatim verifier
   and verify.py must all reproduce the score the leaderboard reports, bit for bit.
2. On random sets, evaluate.py, the arena verifier and verify.py must agree.
3. Malformed input must give valid: False, never an exception.
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import evaluate as ev  # noqa: E402
import verify as vf  # noqa: E402


def main() -> int:
    failures = 0

    def expect(ok: bool, what: str) -> None:
        nonlocal failures
        print(("ok    " if ok else "FAIL  ") + what)
        failures += not ok

    for entry in json.loads((HERE / "published" / "best_3.json").read_text()):
        data = entry["data"]
        n = len(set(data["set"]) | {0})
        ours = ev.evaluate({"n": n}, data["set"])
        arena = ev.arena_evaluate(data)
        cert = {"instance": {"n": n}, "score": entry["score"], "solution": data["set"]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(cert, f)
        done = subprocess.run([sys.executable, str(HERE / "verify.py"), f.name], capture_output=True, text=True)
        Path(f.name).unlink()
        expect(ours["valid"] and ours["score"] == entry["score"] == arena and done.returncode == 0,
               f"solution {entry['id']} ({entry['agentName']}): leaderboard {entry['score']!r}, arena verifier "
               f"{arena!r}, evaluate.py {ours['score']!r} (v = {ours['detail'].get('v')}, |B| = {n}); "
               f"verify.py: {done.stdout.strip()}")

    rng = random.Random(7)
    disagree = 0
    for trial in range(300):
        size = rng.randint(2, 40)
        top = rng.randint(size, 4 * size * size)
        marks = sorted({0, 1} | set(rng.sample(range(top + 1), size)))
        n = len(marks)
        ours = ev.evaluate({"n": n}, marks)
        arena = ev.arena_evaluate({"set": marks})
        reason, info = vf.check({"instance": {"n": n}, "score": arena, "solution": marks})
        if not (ours["valid"] and ours["score"] == arena and reason is None):
            disagree += 1
    expect(disagree == 0, f"300 random sets: evaluate.py, arena verifier and verify.py agree ({disagree} disagreements)")

    bad = [None, 3, "x", {}, {"set": None}, [], [0], [1.5, 2], [True, 0], [-1, 0, 1], ["1", "2"], [0, 2, 4],
           [0, 1, 1, 1], [10**12, 0, 1], list(range(3000))]
    for sol in bad:
        out = ev.evaluate({"n": 3}, sol)
        expect(out["valid"] is False and "reason" in out["detail"], f"invalid input {str(sol)[:30]!r} -> {out['detail']['reason']}")
    for inst in [None, {}, {"n": "3"}, {"n": True}, {"n": 1}, {"n": 2001}]:
        out = ev.evaluate(inst, [0, 1, 3])
        expect(out["valid"] is False, f"invalid instance {inst!r} -> {out['detail']['reason']}")
    good = ev.evaluate({"n": 3}, [1, 3])  # 0 is added, as the arena does
    expect(good["valid"] and good["score"] == 3.0 and good["detail"]["zero_added"], f"[1, 3] with 0 added -> {good}")
    print("PASS" if not failures else f"{failures} FAILURE(S)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
