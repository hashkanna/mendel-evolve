#!/usr/bin/env python3
"""Evaluator agreement with the arena: run from the project root.

    uv run python results/autocorr3/arena_agreement.py

For each of the top solutions downloaded from the arena (results/autocorr3/arena/), prints the score
the arena reports, the score problems/autocorr3/evaluate.py gives on this machine, and the exact
rational value from problems/autocorr3/verify.py.
"""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ev = load("ac3_evaluate", ROOT / "problems/autocorr3/evaluate.py")
vf = load("ac3_verify", ROOT / "problems/autocorr3/verify.py")
top = json.loads((ROOT / "results/autocorr3/arena/best_problem4_top5.json").read_text())
print(f"{'id':>5s} {'agent':12s} {'n':>6s}  {'arena score':<19s} {'evaluate.py':<19s} {'exact rational':<19s} {'FFT':<19s} ulps  verify.py")
worst = 0.0
for item in top:
    values = item["data"]["values"]
    n = len(values)
    res = ev.evaluate({"n": n}, values)
    t = time.time()
    reason, info = vf.check({"instance": {"n": n}, "score": res["score"], "solution": values})
    took = time.time() - t
    import math
    ulps = round((res["score"] - item["score"]) / math.ulp(item["score"]))
    worst = max(worst, abs(res["score"] - item["score"]) / item["score"])
    print(f"{item['id']:>5d} {item['agentName']:12s} {n:>6d}  {item['score']!r:<19s} {res['score']!r:<19s} "
          f"{info.get('exact')!r:<19s} {info.get('fft')!r:<19s} {ulps:+d}    {'pass' if reason is None else 'FAIL: ' + reason} ({took:.1f}s)")
print(f"largest relative difference between evaluate.py and the arena's reported score: {worst:.2e}")
