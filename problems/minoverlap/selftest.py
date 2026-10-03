#!/usr/bin/env python3
"""Validate evaluate.py and verify.py against the published solutions in published/ and broken inputs.

    uv run python problems/minoverlap/selftest.py

Exit status 0 when every check passes.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import evaluate as ev  # noqa: E402
import verify as vf  # noqa: E402

failures: list[str] = []


def expect(ok: bool, what: str) -> None:
    print(("ok    " if ok else "FAIL  ") + what)
    if not ok:
        failures.append(what)


def verify_file(cert: dict) -> int:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cert, f)
    try:
        return vf.main(["verify.py", f.name])
    finally:
        os.unlink(f.name)


def main() -> int:
    published = json.load(open(os.path.join(HERE, "published", "arena_best_problem_1_top3.json")))
    for sol in published:
        values = sol["data"]["values"]
        n = len(values)
        res = ev.evaluate({"n": n}, values)
        rel = abs(res["score"] - sol["score"]) / sol["score"] if res["valid"] else None
        expect(res["valid"] and rel <= 1e-15,
               f"evaluate reproduces arena id {sol['id']} (n={n}): {res['score']!r} vs {sol['score']!r}, rel {rel}")
        expect(ev.evaluate({"n": n}, sol["data"])["score"] == res["score"], f"arena format {{'values': ...}} id {sol['id']}")
        exact, reason, _ = vf.exact_score(values)
        expect(reason is None and abs(float(exact) - sol["score"]) <= 1e-15 * sol["score"],
               f"exact rational value of id {sol['id']}: {float(exact)!r}")
        expect(verify_file({"instance": {"n": n}, "score": sol["score"], "solution": values}) == 0,
               f"verify.py accepts id {sol['id']}")
        expect(verify_file({"instance": {"n": n}, "score": sol["score"] - 1e-9, "solution": values}) == 1,
               f"verify.py rejects a wrong score for id {sol['id']}")
        rep = np.repeat(values, 2).tolist()
        r2 = ev.evaluate({"n": 2 * n}, rep)
        expect(abs(r2["score"] - res["score"]) <= 1e-14, f"repeating heights keeps the score (id {sol['id']})")

    flat = [0.5] * 8
    expect(abs(ev.evaluate({"n": 8}, flat)["score"] - float(vf.exact_score(flat)[0])) < 1e-15, "flat 1/2 agrees")
    rng = np.random.default_rng(0)
    for t in range(20):
        n = int(rng.integers(1, 60))
        x = rng.random(n) * 0.5 + (rng.random(n) < 0.3) * 0.5
        x = x.tolist()
        r = ev.evaluate({"n": n}, x)
        exact, reason, _ = vf.exact_score(x)
        agree = (r["valid"] == (reason is None)) and (not r["valid"] or abs(r["score"] - float(exact)) < 1e-13)
        if not agree:
            expect(False, f"random case {t}: evaluate {r} vs exact {exact} {reason}")
    expect(True, "20 random cases: evaluate and the exact value agree on validity and score")

    bad = [None, "x", {"values": "x"}, [0.5] * 7, [0.5] * 7 + [float("nan")], [0.5] * 7 + [1.5],
           [0.5] * 7 + [-0.1], [0.0] * 8, [1.0] + [0.01] * 7, [True] * 8, {"n": 8}]
    for b in bad:
        r = ev.evaluate({"n": 8}, b)
        expect(r["valid"] is False and "reason" in r["detail"], f"rejects {str(b)[:40]}: {r['detail'].get('reason')}")
    for inst in (None, {}, {"n": "8"}, {"n": 0}, {"n": True}):
        expect(ev.evaluate(inst, flat)["valid"] is False, f"rejects instance {inst!r}")
    expect(ev.instance_key({"n": 3584}) == "n3584" and ev.instance_key(None) == "n?", "instance_key")
    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
