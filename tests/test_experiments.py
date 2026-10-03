"""Experiments, the gate and the tuner, against the toy solver's known ground truth."""
import json

import pytest

from mendel import experiments, gate
from mendel.genes import defaults, load_genes
from mendel.tune import tune
from toyhelpers import ALL_ON, BUDGET, GOOD, SNEAKY, TOY_SOLVER, add_gene

SEEDS = range(4)


@pytest.fixture(scope="module")
def train(problem):
    return problem.instances["train"]


@pytest.fixture(scope="module")
def train_knockouts(pool, problem, train):
    return experiments.knockouts(pool, problem, TOY_SOLVER, ALL_ON, train, SEEDS, BUDGET)


def test_score_config(pool, problem, train):
    res = experiments.score_config(pool, problem, TOY_SOLVER, {}, train, SEEDS, BUDGET)
    assert set(res["scores"]) == {"n4", "n6"}
    n4 = res["scores"]["n4"]
    assert n4["runs"] == 4 and n4["budget"] == "iters=200" and 25 < n4["mean"] <= n4["best"] < 30
    assert sum(res["solutions"]["n4"]) / 4 == n4["best"]
    assert res["normalised_mean"] == pytest.approx((n4["mean"] + res["scores"]["n6"]["mean"]) / 200)
    assert res["failed"] == 0


def test_compare_sign_follows_direction(pool, problem, train):
    better = experiments.compare(pool, problem, TOY_SOLVER, {"boost": True}, {}, train, SEEDS, BUDGET)
    assert 8.5 < better["effect"] < 10.5 and better["ci"][0] > 0 and better["runs"] == 16
    assert better["failed_a"] == better["failed_b"] == 0
    pair = better["pairs"][0]
    assert pair["diff"] == pair["a"] - pair["b"] and {"instance", "seed"} <= set(pair)
    worse = experiments.compare(pool, problem, TOY_SOLVER, {}, {"boost": True}, train, SEEDS, BUDGET)
    assert worse["effect"] == pytest.approx(-better["effect"])

    class Minimise:   # the same problem read as a minimisation: a higher score is now worse
        sign, direction, dir = -1.0, "min", problem.dir
        key = staticmethod(problem.key)

    flipped = experiments.compare(pool, Minimise, TOY_SOLVER, {"boost": True}, {}, train, SEEDS, BUDGET)
    assert flipped["effect"] == pytest.approx(-better["effect"])


def test_knockouts_recover_known_effects(train_knockouts):
    ko = train_knockouts
    assert set(ko) == {"boost", "noop", "left", "right", "small_trick"}     # every idea that is on
    assert 8.5 < ko["boost"]["effect"] < 10.5 and ko["boost"]["ci"][0] > 8      # truth: +10
    assert ko["noop"]["effect"] == 0.0 and ko["noop"]["ci"] == [0.0, 0.0]        # truth: 0
    for half in ("left", "right"):                                              # truth: +8 in the pair
        assert 6.5 < ko[half]["effect"] < 8.5 and ko[half]["ci"][0] > 6
    assert 4.5 < ko["small_trick"]["effect"] < 6.5                              # truth: +6 on training sizes
    assert ko["boost"]["runs"] == 16 and len(ko["boost"]["pairs"]) == 8
    assert set(ko["boost"]["per_instance"]) == {"n4", "n6"}


def test_knockouts_skip_ideas_that_are_off(pool, problem, train):
    ko = experiments.knockouts(pool, problem, TOY_SOLVER, {"boost": True}, train, range(2), BUDGET)
    assert set(ko) == {"boost"}


def test_screen_gene(pool, problem, train):
    res = experiments.screen_gene(pool, problem, TOY_SOLVER, {"left": True}, "right", train, SEEDS, BUDGET)
    assert 6.5 < res["effect"] < 8.5 and res["value"] is True      # right pays off because left is on
    assert res["config"]["right"] is True and res["config"]["left"] is True
    alone = experiments.screen_gene(pool, problem, TOY_SOLVER, {}, "right", train, SEEDS, BUDGET)
    assert alone["effect"] == 0.0


def test_pairwise_finds_the_synergy(pool, problem, train):
    found = experiments.pairwise(pool, problem, TOY_SOLVER, ALL_ON, [("left", "right"), ("boost", "left")],
                                 train, SEEDS, BUDGET)
    pair, independent = found
    assert (pair["a"], pair["b"]) == ("left", "right")
    assert 6.5 < pair["synergy"] < 8.5 and pair["ci"][0] > 6       # only pays off together
    assert pair["effect_a"] == 0.0 and pair["effect_b"] == 0.0 and pair["pair_effect"] == pair["synergy"]
    assert pair["runs"] == 32
    assert abs(independent["synergy"]) < 0.5                       # boost and left simply add up
    assert independent["effect_a"] > 8 and independent["effect_b"] > 6


def test_generality_labels(pool, problem, train_knockouts):
    found = experiments.generality(pool, problem, TOY_SOLVER, ALL_ON, problem.instances["heldout"], SEEDS,
                                   BUDGET, train_knockouts, tol=0.1)
    labels = {name: r["label"] for name, r in found.items()}
    assert labels == {"boost": "general", "noop": "neutral", "left": "general", "right": "general",
                      "small_trick": "specific"}                   # small_trick only helps when n <= 6
    assert set(found["boost"]["generality"]) == {"n8", "n10"}
    assert found["boost"]["generality"]["n8"]["effect"] > 8
    assert found["small_trick"]["heldout"]["effect"] == 0.0


def test_tuner_finds_the_allele_optimum(pool, problem, train):
    res = tune(pool, problem, TOY_SOLVER, instances=train, seeds=range(2), budget=BUDGET, n_trials=24, batch=8,
               alleles_only=True)
    assert abs(res["config"]["step"] - 0.7) < 0.1                  # truth: optimum at 0.7, default 0.2
    assert res["improved"] and res["score"] > res["base_score"] + 0.05
    ideas_untouched = {k: v for k, v in res["config"].items() if k != "step"}
    assert ideas_untouched == {k: v for k, v in defaults(load_genes(TOY_SOLVER)).items() if k != "step"}
    assert len(res["trials"]) == 24


def test_tuner_recombines_ideas(pool, problem, train):
    res = tune(pool, problem, TOY_SOLVER, instances=train, seeds=range(2), budget=BUDGET, n_trials=32, batch=8)
    assert res["config"]["boost"] is True                          # the one idea that always helps
    assert res["score"] > res["base_score"] + 0.1


def test_decomposition(pool, problem, train):
    d = experiments.decomposition(pool, problem, TOY_SOLVER, TOY_SOLVER, ALL_ON, train, SEEDS, BUDGET,
                                  tuned_seed_config={"step": 0.7})
    assert 27 < d["seed"] < 30                                     # ceiling 40 - 10, minus the search gap
    assert 8.5 < d["tuning"] < 10.5                                # step 0.2 -> 0.7 is worth +10
    assert 22 < d["ideas"] < 25                                    # boost 10 + pair 8 + small_trick 6
    assert d["seed"] + d["tuning"] + d["ideas"] == pytest.approx(d["champion"])


# ---------------------------------------------------------------- the gate

def test_gate_passes_a_well_behaved_gene(pool, problem, tmp_path):
    new = add_gene(TOY_SOLVER, tmp_path / "good", "extra", GOOD.format(name="extra", gain=5.0))
    verdict = gate.check(TOY_SOLVER, new, ["extra"], executor=pool, problem=problem, iters=100)
    assert verdict.ok and verdict.reasons == [] and verdict.warnings == []
    assert [c["name"] for c in verdict.checks] == ["registry", "invariance", "smoke"]
    assert all(c["ok"] for c in verdict.checks)
    json.dumps(verdict.to_dict())


def test_gate_rejects_a_gene_that_changes_behaviour_while_off(pool, problem, tmp_path):
    new = add_gene(TOY_SOLVER, tmp_path / "sneaky", "sneaky", SNEAKY)
    verdict = gate.check(TOY_SOLVER, new, ["sneaky"], executor=pool, problem=problem, iters=100)
    assert not verdict.ok
    assert "invariance broken" in verdict.reasons[0] and "at its default" in verdict.reasons[0]
    assert "instance n4, seed 0" in verdict.reasons[0]            # the reason says what was run


def test_gate_checks_invariance_in_the_champion_context(pool, problem, tmp_path):
    # behaves at the defaults, but changes the solver whenever boost is on
    code = '    if cfg["boost"]:\n        cap += 2.0'
    new = add_gene(TOY_SOLVER, tmp_path / "contextual", "contextual", code)
    assert not gate.check(TOY_SOLVER, new, ["contextual"], executor=pool, problem=problem, iters=100,
                          configs=[{}, {"boost": True}]).ok


def test_gate_rejects_registry_tampering_and_crashes(pool, problem, tmp_path):
    tampered = add_gene(TOY_SOLVER, tmp_path / "tampered", "extra", GOOD.format(name="extra", gain=5.0))
    registry = json.loads((tampered / "genes.json").read_text())
    registry["genes"][0]["hypothesis"] = "rewritten"
    (tampered / "genes.json").write_text(json.dumps(registry))
    verdict = gate.check(TOY_SOLVER, tampered, ["extra"], executor=pool, problem=problem)
    assert not verdict.ok and "'boost' was modified" in verdict.reasons[0]

    verdict = gate.check(TOY_SOLVER, TOY_SOLVER, ["boost"], executor=pool, problem=problem)
    assert not verdict.ok and "already exists" in verdict.reasons[0]

    crash = add_gene(TOY_SOLVER, tmp_path / "crash", "boom", '    if cfg["boom"]:\n        raise RuntimeError("bang")')
    verdict = gate.check(TOY_SOLVER, crash, ["boom"], executor=pool, problem=problem, iters=100)
    assert not verdict.ok and "boom=true" in verdict.reasons[0] and "bang" in verdict.reasons[0]
    assert [c["ok"] for c in verdict.checks] == [True, True, False]

    noop = add_gene(TOY_SOLVER, tmp_path / "noop2", "noop2", "    pass")
    verdict = gate.check(TOY_SOLVER, noop, ["noop2"], executor=pool, problem=problem, iters=100)
    assert verdict.ok and "no-op" in verdict.warnings[0]
