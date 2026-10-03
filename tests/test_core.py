"""Genes, problem packs, solver versions, the worker, executors and statistics."""
import json
import shutil

import pytest

from mendel import genes as G
from mendel.executor import CachedExecutor, LocalExecutor
from mendel.solver import solver_version, source_files
from mendel.stats import label_gene, paired_bootstrap, summarise
from mendel.types import make_job
from mendel.worker import hard_timeout, run_job
from toyhelpers import BUDGET, TOY_PROBLEM, TOY_SOLVER


# ---------------------------------------------------------------- genes

def test_registry_defaults_and_kinds():
    genes = G.load_genes(TOY_SOLVER)
    assert [g["name"] for g in G.ideas(genes)] == ["boost", "noop", "left", "right", "small_trick"]
    assert [g["name"] for g in G.alleles(genes)] == ["step"]
    config = G.defaults(genes)
    assert config["boost"] is False and config["step"] == 0.2
    assert G.validate_config(genes, config) == []
    assert G.complete_config(genes, {"boost": True, "unknown": 1}) == {**config, "boost": True}


def test_validation_reports_every_problem():
    bad = [
        {"name": "a", "kind": "switch", "default": True},
        {"name": "b", "kind": "choice", "default": "x", "choices": ["y", "z"]},
        {"name": "c", "kind": "float", "default": 5.0, "low": 0.0, "high": 1.0},
        {"name": "d", "kind": "int", "default": 1, "low": 0, "high": 3, "of": "c"},
        {"name": "a", "kind": "switch", "default": False},
        {"name": "not valid", "kind": "switch", "default": False},
    ]
    errors = G.validate_genes(bad)
    assert len(errors) == 6
    with pytest.raises(G.GeneError):
        G.parse_genes(json.dumps({"genes": bad}))
    genes = G.load_genes(TOY_SOLVER)
    errors = G.validate_config(genes, {**G.defaults(genes), "step": 3.0, "boost": "yes"})
    assert len(errors) == 2


def test_knockout_and_search_space():
    genes = [
        {"name": "idea", "kind": "switch", "default": False},
        {"name": "mode", "kind": "choice", "default": "a", "choices": ["a", "b"]},
        {"name": "strength", "kind": "float", "default": 0.5, "low": 0.0, "high": 1.0, "of": "idea"},
        {"name": "free", "kind": "int", "default": 2, "low": 1, "high": 9, "of": None},
    ]
    assert G.validate_genes(genes) == []
    on = {"idea": True, "mode": "b", "strength": 0.9, "free": 4}
    assert G.active_ideas(genes, on) == ["idea", "mode"]
    assert G.knockout(on, genes[0]) == {"idea": False, "mode": "b", "strength": 0.9, "free": 4}
    assert G.knockout(on, genes[1])["mode"] == "a"
    names = lambda space: [g["name"] for g in space]
    assert names(G.search_space(genes)) == ["idea", "mode", "strength", "free"]
    assert names(G.search_space(genes, on, alleles_only=True)) == ["strength", "free"]
    # an allele whose idea is off is irrelevant
    assert names(G.search_space(genes, {**on, "idea": False}, alleles_only=True)) == ["free"]


# ---------------------------------------------------------------- problem pack

def test_problem_pack(problem):
    assert problem.direction == "max" and problem.sign == 1.0
    assert problem.keys("train") == ["n4", "n6"] and problem.keys("heldout") == ["n8", "n10"]
    assert problem.evaluate({"n": 2}, [10, 30]) == {"valid": True, "score": 20.0, "detail": {"sum": 40}}
    assert problem.evaluate({"n": 2}, "junk")["valid"] is False
    assert problem.normalised("n4", 50.0) == 0.5
    assert problem.normalised("n4", None) == 0.0


# ---------------------------------------------------------------- solver versions and the worker

def test_version_ignores_build_outputs(tmp_path):
    copy = tmp_path / "solver"
    shutil.copytree(TOY_SOLVER, copy)
    version = solver_version(copy)
    assert version == solver_version(TOY_SOLVER)
    (copy / "__pycache__").mkdir(exist_ok=True)
    (copy / "__pycache__" / "solver.cpython-313.pyc").write_bytes(b"junk")
    (copy / "solver.o").write_bytes(b"junk")
    (copy / "solver").write_bytes(b"\x7fELF" + b"\0" * 32)       # a Linux binary
    (copy / "solver_mac").write_bytes(b"\xcf\xfa\xed\xfe" + b"\0" * 32)
    (copy / ".DS_Store").write_bytes(b"junk")
    assert solver_version(copy) == version
    assert [p.as_posix() for p in source_files(copy)] == ["genes.json", "mendel.toml", "solver.py"]
    (copy / "solver.py").write_text((copy / "solver.py").read_text() + "\n# changed\n")
    assert solver_version(copy) != version


def test_run_job_is_deterministic_and_evaluated(problem):
    job = make_job(TOY_SOLVER, TOY_PROBLEM, {}, {"n": 4}, 3, BUDGET)
    a, b = run_job(job), run_job(job)
    assert a["ok"] and a["valid"] and a["error"] is None
    assert a["solution"] == b["solution"] and a["score"] == b["score"]
    assert a["score"] == sum(a["solution"]) / 4
    assert a["stats"]["iters"] == 200
    assert set(a) == {"ok", "valid", "score", "stats", "wall", "error", "solution"}
    timed = run_job(make_job(TOY_SOLVER, TOY_PROBLEM, {}, {"n": 4}, 3, {"kind": "time", "value": 0.05}))
    assert timed["ok"] and timed["valid"] and timed["stats"]["iters"] > 0
    assert hard_timeout({"kind": "time", "value": 5}) == 25.0


def test_run_job_never_raises(tmp_path):
    missing = run_job(make_job(tmp_path / "nowhere", TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET))
    assert missing["ok"] is False and missing["error"]
    assert run_job({"budget": {"kind": "iters", "value": 1}})["ok"] is False
    assert run_job({})["ok"] is False

    def variant(name, body, build=None):
        d = tmp_path / name
        shutil.copytree(TOY_SOLVER, d)
        (d / "solver.py").write_text(body)
        if build:
            (d / "mendel.toml").write_text(f'problem = "toy"\nbuild = "{build}"\nrun = "python3 solver.py"\n')
        return d

    crash = run_job(make_job(variant("crash", "raise SystemExit('kaboom')"), TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET))
    assert crash["ok"] is False and "kaboom" in crash["error"]
    silent = run_job(make_job(variant("silent", "pass"), TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET))
    assert silent["ok"] is False and "no --out" in silent["error"]
    slow = make_job(variant("slow", "import time; time.sleep(30)"), TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET, timeout=1)
    slow = run_job(slow)
    assert slow["ok"] is False and "timeout" in slow["error"] and slow["wall"] < 10
    writes_junk = ("import json, sys\n"
                   "json.dump({'solution': [999, -1, 0, 0]}, open(sys.argv[sys.argv.index('--out') + 1], 'w'))\n")
    invalid = run_job(make_job(variant("invalid", writes_junk), TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET))
    assert invalid["ok"] is True and invalid["valid"] is False and invalid["score"] is None
    assert "invalid solution" in invalid["error"]
    broken = run_job(make_job(variant("nobuild", "pass", build="echo cannot compile >&2; exit 3"), TOY_PROBLEM, {},
                              {"n": 4}, 0, BUDGET))
    assert broken["ok"] is False and "build failed" in broken["error"] and "cannot compile" in broken["error"]
    bad_config = run_job(make_job(TOY_SOLVER, TOY_PROBLEM, {"step": 7.0}, {"n": 4}, 0, BUDGET))
    assert bad_config["ok"] is False and "bad config" in bad_config["error"]


def test_concurrent_builds_are_safe(tmp_path, pool, build_cache):
    """Three workers ask for the same unbuilt version at once; it is built exactly once."""
    d = tmp_path / "built"
    shutil.copytree(TOY_SOLVER, d)
    (d / "mendel.toml").write_text(
        'problem = "toy"\nbuild = "sleep 0.3 && echo x >> build.log && cp solver.py built.py"\n'
        'run = "python3 built.py"\n')
    results = pool.run([make_job(d, TOY_PROBLEM, {}, {"n": 4}, seed, BUDGET) for seed in range(3)])
    assert [r["ok"] for r in results] == [True, True, True], [r["error"] for r in results]
    build_dir = build_cache / solver_version(d)
    assert (build_dir / "build.log").read_text() == "x\n"
    assert not list(build_cache.glob("*.tmp.*"))


# ---------------------------------------------------------------- executors

def test_local_executor_preserves_order(pool):
    jobs = [make_job(TOY_SOLVER, TOY_PROBLEM, {}, {"n": n}, seed, BUDGET) for n in (4, 6) for seed in range(3)]
    parallel = pool.run(jobs)
    inline = LocalExecutor(workers=0).run(jobs)
    assert [r["solution"] for r in parallel] == [r["solution"] for r in inline]
    assert [len(r["solution"]) for r in parallel] == [4, 4, 4, 6, 6, 6]


class Counting:
    def __init__(self, inner):
        self.inner, self.seen = inner, 0

    def run(self, jobs):
        self.seen += len(jobs)
        return self.inner.run(jobs)


def test_cached_executor(tmp_path):
    counting = Counting(LocalExecutor(workers=0))
    cached = CachedExecutor(counting, tmp_path / "results.sqlite")
    job = make_job(TOY_SOLVER, TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET)
    other = make_job(TOY_SOLVER, TOY_PROBLEM, {"boost": True}, {"n": 4}, 0, BUDGET)
    first = cached.run([job, other, job])            # the duplicate runs once
    assert counting.seen == 2 and first[0] == first[2] and first[0] != first[1]
    again = CachedExecutor(counting, tmp_path / "results.sqlite").run([other, job])
    assert counting.seen == 2 and again == [first[1], first[0]]
    # every part of the key matters
    for change in ({"seed": 1}, {"instance": {"n": 6}}, {"budget": {"kind": "iters", "value": 201}}):
        cached.run([{**job, **change}])
    assert counting.seen == 5
    failing = make_job(tmp_path / "nowhere", TOY_PROBLEM, {}, {"n": 4}, 0, BUDGET)
    assert cached.run([failing])[0]["ok"] is False and cached.run([failing])[0]["ok"] is False
    assert counting.seen == 7                        # failures are not cached


# ---------------------------------------------------------------- statistics

def test_paired_bootstrap():
    mean, lo, hi = paired_bootstrap([1.0, 1.2, 0.8, 1.1, 0.9, 1.0])
    assert mean == pytest.approx(1.0) and 0.8 < lo < mean < hi < 1.2
    assert paired_bootstrap([0.5] * 5) == (0.5, 0.5, 0.5)
    assert paired_bootstrap([]) == (0.0, 0.0, 0.0)
    assert paired_bootstrap([1.0, 2.0, 3.0]) == paired_bootstrap([1.0, 2.0, 3.0])   # seeded
    # strata: the mean of per-instance means, not the pooled mean
    mean, lo, hi = paired_bootstrap([0.0, 0.0, 4.0, 4.0, 4.0, 4.0], strata=["a", "a", "b", "b", "b", "b"])
    assert mean == pytest.approx(2.0) and lo == hi == pytest.approx(2.0)
    # one seed per instance: nothing to resample within an instance, so the pairs are pooled
    mean, lo, hi = paired_bootstrap([1.0, 3.0, 2.0], strata=["a", "b", "c"])
    assert mean == pytest.approx(2.0) and lo < mean < hi


def test_summarise_and_labels():
    assert summarise([1, 2, 3], "max") == {"mean": 2.0, "best": 3.0, "runs": 3}
    assert summarise([1, 2, 3], "min")["best"] == 1.0
    assert summarise([])["runs"] == 0
    helps = {"effect": 1.0, "ci": [0.5, 1.5], "runs": 16}
    hurts = {"effect": -1.0, "ci": [-1.5, -0.5], "runs": 16}
    wide = {"effect": 0.1, "ci": [-0.9, 1.1], "runs": 16}
    zero = {"effect": 0.0, "ci": [0.0, 0.0], "runs": 16}
    assert label_gene(helps, helps) == "general"
    assert label_gene(helps, wide) == "specific"
    assert label_gene(helps, hurts) == "specific"
    assert label_gene(hurts, helps) == "harmful"
    assert label_gene(wide, hurts) == "harmful"
    assert label_gene(zero, zero) == "neutral"
    assert label_gene(wide, zero) == "inconclusive"
    assert label_gene(wide, wide, tol=2.0) == "neutral"
    assert label_gene(wide, helps) == "inconclusive"
    assert label_gene({"effect": 0.0, "ci": [0.0, 0.0], "runs": 0}, zero) == "inconclusive"
