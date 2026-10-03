"""mendel explain without the LLM step: a hand-written decomposition of a toy pair of programs.

The pair is a small circle packing "initial" program and an "evolved" one that differs in three known
ways (a changed constant, a staggered layout, a radius-growing pass), so the bookend check and the
measurements have a ground truth.
"""
import json
from pathlib import Path

import pytest

from mendel import explain
from mendel.problem import load_problem

ROOT = Path(__file__).resolve().parent.parent
PACK = ROOT / "problems" / "circle_packing"

INITIAL = '''
import numpy as np


def run_packing():
    n = 26
    centers = np.zeros((n, 2))
    for i in range(n):
        centers[i] = [0.1 + 0.16 * (i % 6), 0.1 + 0.19 * (i // 6)]
    radii = np.full(n, 0.05)
    return centers, radii, float(radii.sum())
'''

EVOLVED = '''
import numpy as np


def run_packing():
    n = 26
    centers = np.zeros((n, 2))
    for i in range(n):
        row = i // 6
        centers[i] = [0.1 + 0.16 * (i % 6) + (0.02 if row % 2 else 0.0), 0.1 + 0.19 * row]
    radii = np.full(n, 0.07)
    for i in range(n):
        x, y = centers[i]
        room = min(x, y, 1 - x, 1 - y)
        for j in range(n):
            if j != i:
                room = min(room, float(np.hypot(*(centers[i] - centers[j]))) - radii[j])
        radii[i] = max(radii[i], 0.999 * room)
    return centers, radii, float(radii.sum())
'''

PROGRAM = '''
import numpy as np


def construct(cfg, n, seed):
    centers = np.zeros((n, 2))
    for i in range(n):
        row = i // 6
        if cfg["stagger"]:
            centers[i] = [0.1 + 0.16 * (i % 6) + (0.02 if row % 2 else 0.0), 0.1 + 0.19 * row]
        else:
            centers[i] = [0.1 + 0.16 * (i % 6), 0.1 + 0.19 * (i // 6)]
    radii = np.full(n, cfg["radius"])
    if cfg["grow_pass"]:
        for i in range(n):
            x, y = centers[i]
            room = min(x, y, 1 - x, 1 - y)
            for j in range(n):
                if j != i:
                    room = min(room, float(np.hypot(*(centers[i] - centers[j]))) - radii[j])
            radii[i] = max(radii[i], cfg["grow_factor"] * room)
    return centers, radii
'''

GENES = {"genes": [
    {"name": "stagger", "kind": "switch", "default": False, "evolved": True, "of": None,
     "hypothesis": "Odd rows are shifted along x.", "author": "test", "added_gen": 1},
    {"name": "grow_pass", "kind": "switch", "default": False, "evolved": True, "of": None,
     "hypothesis": "Each radius grows into the room its neighbours leave.", "author": "test", "added_gen": 1},
    {"name": "radius", "kind": "float", "default": 0.05, "evolved": 0.07, "low": 0.02, "high": 0.075, "log": False,
     "of": None, "hypothesis": "The common starting radius.", "author": "test", "added_gen": 1},
    {"name": "grow_factor", "kind": "float", "default": 0.999, "evolved": 0.999, "low": 0.9, "high": 1.0,
     "log": False, "of": "grow_pass", "hypothesis": "Safety factor of the growing pass.", "author": "test",
     "added_gen": 1},
]}


@pytest.fixture(scope="module")
def pack():
    return load_problem(PACK)


@pytest.fixture(scope="module")
def pair(tmp_path_factory, pack, build_cache):
    """The two programs, their reference outputs, and a faithful hand-written decomposition."""
    root = tmp_path_factory.mktemp("explain")
    initial, evolved = root / "initial.py", root / "evolved.py"
    initial.write_text(INITIAL)
    evolved.write_text(EVOLVED)
    reference = explain.make_reference(pack, initial, evolved, log=lambda *_: None)
    solver = root / "solver"
    hashes = explain.write_fixed_files(pack, solver)
    (solver / "program.py").write_text(PROGRAM)
    (solver / "genes.json").write_text(json.dumps(GENES, indent=1))
    return {"root": root, "initial": initial, "evolved": evolved, "reference": reference, "solver": solver,
            "hashes": hashes}


def test_reference_is_repaired_and_deterministic(pair):
    ref = pair["reference"]
    assert ref["instance"] == {"n": 26}
    assert ref["initial"]["deterministic"] and ref["initial"]["reproducible"]
    assert ref["initial"]["runs"]["0"]["score"] == pytest.approx(1.3, abs=1e-9)
    assert ref["evolved"]["runs"]["0"]["score"] > ref["initial"]["runs"]["0"]["score"]


def test_bookend_configs_use_default_and_evolved():
    all_off, all_on, reset = explain.bookend_configs(GENES["genes"])
    assert all_off == {"stagger": False, "grow_pass": False, "radius": 0.05, "grow_factor": 0.999}
    assert all_on == {"stagger": True, "grow_pass": True, "radius": 0.07, "grow_factor": 0.999}
    assert reset == {"stagger": True, "grow_pass": True, "radius": 0.05, "grow_factor": 0.999}


def test_bookend_check_passes_for_a_faithful_decomposition(pair, pack):
    verdict = explain.bookend_check(pair["solver"], pack, pair["reference"], fixed_hashes=pair["hashes"])
    assert verdict["ok"], explain.format_verdict(verdict)
    assert verdict["max_diff"] == {"initial": 0.0, "evolved": 0.0}
    assert [c["name"] for c in verdict["checks"]] == ["registry", "bookend: all off", "bookend: all on",
                                                      "single-switch configurations"]


def test_bookend_check_names_what_differs(pair, pack, tmp_path):
    import shutil

    wrong = tmp_path / "solver"
    shutil.copytree(pair["solver"], wrong)
    genes = json.loads(json.dumps(GENES))
    genes["genes"][2]["evolved"] = 0.06                      # the evolved constant is mis-stated
    (wrong / "genes.json").write_text(json.dumps(genes))
    verdict = explain.bookend_check(wrong, pack, pair["reference"], smoke=False, fixed_hashes=pair["hashes"])
    assert not verdict["ok"]
    assert verdict["max_diff"]["initial"] == 0.0             # the initial bookend still holds
    assert any("does not reproduce the evolved program" in r for r in verdict["reasons"])

    del genes["genes"][2]["evolved"]                         # an allele without its evolved value
    (wrong / "genes.json").write_text(json.dumps(genes))
    verdict = explain.bookend_check(wrong, pack, pair["reference"], smoke=False, fixed_hashes=pair["hashes"])
    assert not verdict["ok"] and "needs an 'evolved' value" in verdict["reasons"][0]

    (wrong / "genes.json").write_text(json.dumps(GENES))
    (wrong / "solver.py").write_text((wrong / "solver.py").read_text() + "\n# edited\n")   # the wrapper is fixed
    verdict = explain.bookend_check(wrong, pack, pair["reference"], smoke=False, fixed_hashes=pair["hashes"])
    assert not verdict["ok"] and "solver/solver.py was changed" in verdict["reasons"][0]


def test_explain_measures_and_reports_a_given_decomposition(pair, tmp_path):
    run_dir = explain.run_explain(problem_dir=PACK, initial=pair["initial"], evolved=pair["evolved"], run_id="toy",
                                  runs_dir=tmp_path, solver=pair["solver"], seeds=2, tune_trials=6, pairwise_top=2,
                                  workers=2, log=lambda *_: None)
    state = json.loads((run_dir / "state.json").read_text())
    assert state["run"]["status"] == "finished" and state["run"]["spend"]["llm_calls"] == 0
    assert state["explain"]["bookend"]["ok"]
    genes = {g["name"]: g for g in state["genes"]}
    assert set(genes) == {"stagger", "grow_pass", "radius", "grow_factor"}
    m = state["explain"]["measure"]
    gain = m["total"]["effect"]
    assert gain == pytest.approx(m["scores"]["all_on"] - m["scores"]["all_off"]) and gain > 0.3

    # the growing pass is what the evolved program cannot do without; it also helps on its own
    assert genes["grow_pass"]["knockout"]["effect"] > 0.1
    assert genes["grow_pass"]["screen"]["effect"] > 0.1
    assert genes["grow_pass"]["verdict"] == "carries gain"
    # the programs draw no random numbers: every interval has zero width
    assert genes["grow_pass"]["knockout"]["ci"][0] == genes["grow_pass"]["knockout"]["ci"][1]
    assert all(v == 0 for v in m["spreads"].values())

    # tuning the one constant of the initial program buys part of the gain, not all of it
    assert m["tuning"]["tunable"] == ["radius"]
    assert 0 < m["tuning"]["effect"] < gain
    d = state["decomposition"]
    assert d["seed"] + d["tuning"] + d["ideas"] == pytest.approx(m["scores"]["all_on"])
    # resetting the evolved constant with both switches on
    assert m["reset_differs"] and m["constants"]["runs"] == 4

    assert len(state["interactions"]) == 1 and {state["interactions"][0]["a"], state["interactions"][0]["b"]} == {
        "stagger", "grow_pass"}
    assert state["champion"]["config"] == m["configs"]["all_on"]
    assert len(state["champion"]["solutions"]["n26"]) == 26

    report = (run_dir / "report.md").read_text()
    for text in ("## The bookend check", "**passed**", "`grow_pass`", "## Limits", "one decomposition of several"):
        assert text in report

    from mendel.dashboard.snapshot import render

    assert "grow_pass" in render(state)
