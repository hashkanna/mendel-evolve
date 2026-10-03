#!/usr/bin/env python3
"""Check the evaluator against the published point sets in published/ and against a few hand cases.

    python selftest.py            exit 0 if every fixture reproduces its published exact value

Each fixture is a leaderboard entry (github.com/tejstead/heilbronn-site, data/canonical) stored as a
certificate. evaluate.py must return exactly the published value_fraction and 30-digit decimal, and
verify.py (independent code) must agree. The malformed inputs must be rejected without an exception.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"heilbronn_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ev, vf = _load("evaluate"), _load("verify")
    failures = 0
    fixtures = sorted((HERE / "published").glob("*.json"))
    for path in fixtures:
        cert = json.loads(path.read_text())
        out = ev.evaluate(cert["instance"], cert["solution"])
        published = Fraction(cert["value_fraction"])
        ok = (out["valid"] and Fraction(out["detail"]["value_fraction"]) == published
              and out["detail"]["value_decimal"] == cert["value_decimal"] and out["score"] == cert["score"]
              and out["detail"]["ties_within_1e-9"] == cert["ties"])
        reason, value = vf.check(cert)
        ok = ok and reason is None and value == published
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {path.name:22s} {ev.instance_key(cert['instance']):11s} {cert['value_decimal']}")

    sq = {"shape": "square", "n": 3}
    tr = {"shape": "triangle", "n": 3}
    cv = {"shape": "convex", "n": 4}
    cases = [
        ("unit right triangle in the square is 1/2", sq, [["0", "0"], ["1", "0"], ["0", "1"]], True, 0.5),
        ("the same three points in the triangle are 1", tr, [["0", "0"], ["1", "0"], ["0", "1"]], True, 1.0),
        ("a square as a convex region is 1/2", cv, [["0", "0"], ["7", "0"], ["7", "7"], ["0", "7"]], True, 0.5),
        ("a negative coordinate is fine for convex", cv, [["-1", "0"], ["1", "0"], ["1", "2"], ["-1", "2"]], True, 0.5),
        ("outside the square by 1e-30", sq, [["0", "0"], ["1." + "0" * 29 + "1", "0"], ["0", "1"]], False, None),
        ("outside the triangle by 1e-30", tr, [["0", "0"], ["0.5", "0.5" + "0" * 28 + "1"], ["0", "1"]], False, None),
        ("duplicate point", sq, [["0", "0"], ["0.0", "0"], ["0", "1"]], False, None),
        ("float instead of string", sq, [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]], False, None),
        ("exponent notation", sq, [["0", "0"], ["1e0", "0"], ["0", "1"]], False, None),
        ("wrong count", sq, [["0", "0"], ["1", "0"]], False, None),
        ("not a list", sq, "points", False, None),
        ("collinear points score 0", sq, [["0", "0"], ["0.5", "0.5"], ["1", "1"]], True, 0.0),
    ]
    for name, inst, sol, valid, score in cases:
        out = ev.evaluate(inst, sol)
        ok = out["valid"] == valid and (score is None or out["score"] == score)
        failures += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name}")
    print(f"{len(fixtures)} fixtures, {len(cases)} hand cases, {failures} failures")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
