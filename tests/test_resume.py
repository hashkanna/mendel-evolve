"""Overnight-run behaviour: resume, failing sub-steps, the budget stop, fresh seeds for attribution,
the flip pass, files from other processes, queued genes, the gate retry and pruning."""
import json

import pytest

from mendel import cli
from mendel.engine import Engine, EngineConfig, ResumeError, load_run_config, run_engine
from mendel.ledger import Ledger
from mendel.tune import flip_pass
from toyhelpers import BUDGET, TOY_PROBLEM, TOY_SOLVER, Hooked, ScriptedInventor


def make_cfg(runs, run_id, **over) -> EngineConfig:
    settings = dict(problem_dir=str(TOY_PROBLEM), solver_dir=str(TOY_SOLVER), runs_dir=str(runs), run_id=run_id,
                    generations=2, proposals=3, budget={"kind": "iters", "value": 120}, seeds=3, heldout_seeds=2,
                    tune_every=2, tune_trials=8, tune_batch=8, tune_seeds=1, pairwise_top=2, gate_iters=100,
                    gate_retries=0)
    settings.update(over)
    return EngineConfig(**settings)


def read(run_dir, name="state.json"):
    return json.loads((run_dir / name).read_text())


def events(run_dir, name=None):
    rows = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    return [e for e in rows if name is None or e["event"] == name]


def hooked_engine(cfg, inventor, pool, hook) -> Engine:
    executor = Hooked(pool, hook)
    engine = Engine(cfg, inventor=inventor, executor=executor)
    executor.engine = engine
    return engine


# ---------------------------------------------------------------- resume

def test_resume_after_a_crash_in_the_middle_of_a_generation(pool, tmp_path):
    runs = tmp_path / "runs"
    assert cli.main(["idea", "--run", "night", "--runs", str(runs), "--author", "alice", "double it"]) == 0
    script = {1: ["extra1", "sneaky"], 2: ["worse", None]}

    def crash(step, generation, jobs):          # Ctrl-C while screening in generation 2
        if step == "screen" and generation == 2:
            raise KeyboardInterrupt

    first = ScriptedInventor(script)
    with pytest.raises(KeyboardInterrupt):
        hooked_engine(make_cfg(runs, "night"), first, pool, crash).run()
    run_dir = runs / "night"
    crashed = read(run_dir)
    assert crashed["run"]["status"] == "stopped" and crashed["run"]["generation"] == 2
    assert crashed["run"]["spend"]["llm_calls"] == 6
    # generation 1 finished: extra1 merged, the human idea screened positive and is waiting for its port
    queued = {g["name"]: g for g in crashed["genes"]}["doubling"]
    assert queued["status"] == "queued" and 2 < queued["screen"]["effect"] < 4
    assert queued["author"] == "human:alice"
    checkpoint = read(run_dir, "checkpoint.json")
    assert checkpoint["generation"] == 1 and checkpoint["trunk"] == "gen001"
    assert [p["name"] for p in checkpoint["port_queue"]] == ["doubling"] and checkpoint["ideas_taken"] == 1
    assert checkpoint["champion"]["extra1"] is True

    # an existing run is never clobbered by accident, and never run by two engines at once
    with pytest.raises(ResumeError, match="already exists"):
        run_engine(make_cfg(runs, "night"), inventor=ScriptedInventor(script), executor=pool)
    import fcntl
    with open(run_dir / "engine.lock", "a") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ResumeError, match="already running"):
            run_engine(make_cfg(runs, "night"), inventor=ScriptedInventor(script), executor=pool, resume=True)
    assert read(run_dir) == crashed and read(run_dir, "checkpoint.json") == checkpoint   # both refusals left it alone
    assert load_run_config(run_dir).generations == 2

    second = ScriptedInventor(script)
    assert run_engine(make_cfg(runs, "night"), inventor=second, executor=pool, resume=True) == run_dir
    state = read(run_dir)
    assert state["run"]["status"] == "finished" and state["run"]["generation"] == 2
    assert state["run"]["started"] == crashed["run"]["started"]
    assert len(events(run_dir, "run_resumed")) == 1
    # generation 2 was redone from the end of generation 1: same trunk, port queue and idea counter
    assert [c["generation"] for c in second.calls] == [2, 2, 2]
    ports = [c for c in second.calls if c["directive"] and c["directive"].startswith("Port an idea")]
    assert len(ports) == 1 and "Idea gene: doubling" in ports[0]["directive"] and ports[0]["author"] == "human:alice"
    assert not [c for c in second.calls if c["directive"] == "double it"]      # the human idea is not taken twice
    assert [e["gene"] for e in events(run_dir, "gene_merged")] == ["extra1", "doubling"]
    assert (run_dir / "trunk" / "gen002" / "solver.py").exists()
    genes = {g["name"]: g for g in state["genes"]}
    assert len(genes) == len(state["genes"])                                   # nothing recorded twice
    assert genes["doubling"]["status"] == "active" and genes["doubling"]["added_gen"] == 2
    assert genes["extra1"]["status"] == "active" and genes["worse"]["status"] == "rejected"
    assert genes["sneaky"]["status"] == "failed-gate"
    # the ledger is the checkpoint plus the redone generation; the abandoned attempt is only in events.jsonl
    started = [h for h in state["history"] if h["event"] == "generation_started"]
    assert [h["generation"] for h in started] == [1, 2] and len(events(run_dir, "generation_started")) == 3
    # spend carries over, including what the abandoned attempt cost
    assert state["run"]["spend"]["llm_calls"] == 9
    assert state["run"]["spend"]["evaluations"] >= crashed["run"]["spend"]["evaluations"]
    times = [p["t"] for p in state["timeline"]]
    assert times == sorted(times) and state["timeline"][-1]["generation"] == 2

    # a finished run can be extended; --generations is the total
    assert cli.main(["run", "--resume", "--run-id", "night", "--runs", str(runs), "--generations", "3", "--k", "0",
                     "--workers", "2"]) == 0
    state = read(run_dir)
    assert state["run"]["status"] == "finished" and state["run"]["generation"] == 3
    assert len(events(run_dir, "run_resumed")) == 2 and state["run"]["spend"]["llm_calls"] == 9
    assert state["champion"]["config"]["doubling"] is True
    assert cli.main(["run", "--run-id", "night", "--runs", str(runs), "--solver", str(TOY_SOLVER),
                     "--problem", str(TOY_PROBLEM)]) == 2                      # needs --resume or --overwrite


# ---------------------------------------------------------------- robustness

def test_a_failing_sub_step_is_logged_and_the_run_carries_on(pool, tmp_path):
    failed_once = []

    def flaky(step, generation, jobs):          # e.g. one Modal batch dies during tuning
        if step == "tune" and not failed_once:
            failed_once.append(True)
            raise RuntimeError("modal batch failed")

    cfg = make_cfg(tmp_path, "flaky", generations=2, proposals=1, tune_every=1)
    engine = hooked_engine(cfg, ScriptedInventor({1: ["explode"], 2: ["extra1"]}), pool, flaky)
    run_dir = engine.run()
    state = read(run_dir)
    assert state["run"]["status"] == "finished" and state["run"]["generation"] == 2
    failures = events(run_dir, "step_failed")
    assert len(failures) == 1 and failures[0]["step"] == "tune" and "modal batch failed" in failures[0]["detail"]
    assert "RuntimeError" in failures[0]["traceback"]
    assert "the inventor exploded" in events(run_dir, "inventor_failed")[0]["detail"]
    # the steps after the failure still ran, and so did the next generation
    assert [e["generation"] for e in events(run_dir, "knockouts")] == [1, 2]
    assert [e["gene"] for e in events(run_dir, "gene_merged")] == ["extra1"]
    assert len(events(run_dir, "tuned")) == 1


def test_a_generation_that_fails_outside_a_step_is_rolled_back(pool, tmp_path):
    class BrokenSelect(Engine):
        def _select(self, g, screened):
            if g == 1:
                raise KeyError("a bug")
            return super()._select(g, screened)

    cfg = make_cfg(tmp_path, "rollback", proposals=1, tune_every=0, decomposition=False)
    run_dir = BrokenSelect(cfg, inventor=ScriptedInventor({1: ["extra1"], 2: ["extra1"]}), executor=pool).run()
    state = read(run_dir)
    assert state["run"]["status"] == "finished" and state["run"]["generation"] == 2
    assert len(events(run_dir, "generation_failed")) == 1
    assert [e["generation"] for e in events(run_dir, "gene_merged")] == [2]     # generation 2 started from gen 0
    assert state["run"]["spend"]["llm_calls"] == 2


def test_budget_exceeded_stops_cleanly_and_the_run_resumes(pool, tmp_path):
    class BudgetExceeded(RuntimeError):         # same name as the Modal executor's exception
        pass

    def capped(step, generation, jobs):
        if step == "knockouts":
            raise BudgetExceeded("this call needs 3.0 core-hours but only 1.0 remain under the cap")

    cfg = make_cfg(tmp_path, "capped", generations=1, proposals=0, tune_every=1)
    run_dir = hooked_engine(cfg, None, pool, capped).run()                      # returns; does not raise
    state = read(run_dir)
    assert state["run"]["status"] == "stopped: budget"
    assert "1.0 remain under the cap" in events(run_dir, "run_stopped")[0]["detail"]
    assert read(run_dir, "checkpoint.json")["generation"] == 0
    run_engine(make_cfg(tmp_path, "capped", generations=1, proposals=0, tune_every=1), executor=pool, resume=True)
    state = read(run_dir)
    assert state["run"]["status"] == "finished" and state["run"]["generation"] == 1
    assert events(run_dir, "knockouts")


# ---------------------------------------------------------------- fresh seeds for attribution

def test_attribution_uses_seeds_that_selection_never_saw(pool, tmp_path):
    seen = []

    def record(step, generation, jobs):
        seen.extend((step, job["seed"]) for job in jobs)

    cfg = make_cfg(tmp_path, "seeds", generations=1, proposals=1, tune_every=1, seeds=2, cache=False,
                   budget={"kind": "iters", "value": 80})
    run_dir = hooked_engine(cfg, ScriptedInventor({1: ["extra1"]}), pool, record).run()
    assert read(run_dir)["run"]["status"] == "finished"
    selection_steps = {"gate", "screen", "tune", "decomposition-tune"}
    attribution_steps = {"score", "knockouts", "pairwise", "generality", "decomposition"}
    steps = {step for step, _ in seen}
    assert steps <= selection_steps | attribution_steps
    assert {"gate", "screen", "tune", "decomposition-tune", "score", "knockouts", "generality",
            "decomposition"} <= steps
    selection = {seed for step, seed in seen if step in selection_steps}
    attribution = {seed for step, seed in seen if step in attribution_steps}
    assert selection == {0, 1} and attribution == {1000, 1001}                 # disjoint, and fixed for the run
    # the reported numbers say which seeds they came from
    assert events(run_dir, "knockouts")[0]["seeds"] == [1000, 1001]
    assert events(run_dir, "tuned")[0]["confirm_seeds"] == [0, 1]
    with pytest.raises(ValueError):
        Engine(make_cfg(tmp_path, "overlap", seeds=8, attribution_seed_base=4))


# ---------------------------------------------------------------- the flip pass

def test_flip_pass_keeps_only_flips_whose_interval_is_above_zero(pool, problem):
    start = {"boost": False, "noop": True, "left": True, "right": False, "small_trick": True, "step": 0.7}
    config, flips = flip_pass(pool, problem, TOY_SOLVER, start, problem.instances["train"], range(4), BUDGET)
    # boost on: +10. noop off: 0, not kept. left off: 0 while right is off, not kept.
    # right on: +8 because left is on. small_trick off: -6, not kept.
    assert config == {**start, "boost": True, "right": True}
    assert [(f["gene"], f["from"], f["to"]) for f in flips] == [("boost", False, True), ("right", False, True)]
    assert all(f["ci"][0] > 0 for f in flips) and 8.5 < flips[0]["effect"] < 10.5 and 6.5 < flips[1]["effect"] < 8.5
    assert flip_pass(pool, problem, TOY_SOLVER, config, problem.instances["train"], range(4), BUDGET) == (config, [])


# ---------------------------------------------------------------- records and compute from other processes

def test_ledger_folds_in_records_and_compute_from_other_processes(tmp_path, problem):
    ledger = Ledger.create(tmp_path, "r", problem)
    decomposition = {"seed": 1.0, "tuning": 0.0, "ideas": 0.0, "compute": 0.0, "unit": "points"}
    ledger.state["decomposition"] = dict(decomposition)
    own = {"instance": "n4", "value": 101, "best_known": 100, "verified": True, "certificate": "certificates/a.json"}
    theirs = {"instance": "n8", "value": 57, "best_known": 56, "verified": True, "certificate": "certificates/b.json"}
    ledger.own_records.append(own)
    ledger.save()
    assert read(tmp_path)["records"] == [own] and read(tmp_path)["decomposition"]["compute"] == 0.0

    (tmp_path / "records.json").write_text(json.dumps([theirs, own, "junk", {"value": 3}]))
    (tmp_path / "compute.json").write_text('{"compute": 1.5}')
    ledger.save()
    assert read(tmp_path)["records"] == [theirs, own] and read(tmp_path)["decomposition"]["compute"] == 1.5

    (tmp_path / "records.json").write_text('[{"instance": "n8", "val')         # caught half-written
    (tmp_path / "compute.json").write_text('{"compute": "a lot"}')
    ledger.save()
    assert read(tmp_path)["records"] == [theirs, own] and read(tmp_path)["decomposition"]["compute"] == 1.5

    ledger.state["decomposition"] = dict(decomposition)                         # the engine rewrites it ...
    (tmp_path / "compute.json").write_text('{"compute": 2}')
    ledger.event("decomposition", detail="rewritten")
    assert read(tmp_path)["decomposition"]["compute"] == 2                      # ... and the file still wins
    (tmp_path / "records.json").unlink()
    ledger.save()
    assert read(tmp_path)["records"] == [own]


# ---------------------------------------------------------------- the gate retry

def test_one_retry_after_a_gate_failure(pool, tmp_path):
    cfg = make_cfg(tmp_path, "retry", generations=1, proposals=2, tune_every=0, decomposition=False,
                   gate_retries=1)
    inventor = ScriptedInventor({1: ["sneaky", "stubborn"]})
    run_dir = run_engine(cfg, inventor=inventor, executor=pool)
    state = read(run_dir)
    assert sorted(e["gene"] for e in events(run_dir, "gate_retry")) == ["sneaky", "stubborn"]
    retries = [c for c in inventor.calls if c["directive"] and c["directive"].startswith("Your previous attempt")]
    assert len(retries) == 2
    retry = next(c for c in retries if "Idea gene: sneaky" in c["directive"])
    assert "invariance broken" in retry["directive"]                            # quotes the gate's reasons
    assert f"The failed implementation is in: {run_dir / 'proposals' / 'gen001'}" in retry["directive"]
    assert retry["workdir"].endswith("r") and (run_dir / "proposals" / "gen001" / "0").exists()
    # sneaky passes once fixed and is merged; stubborn fails again and is recorded once
    assert [e["gene"] for e in events(run_dir, "gene_merged")] == ["sneaky"]
    assert [e["gene"] for e in events(run_dir, "gate_failed")] == ["stubborn"]
    genes = {g["name"]: g for g in state["genes"]}
    assert genes["sneaky"]["status"] == "active" and 1 < genes["sneaky"]["screen"]["effect"] < 3
    assert genes["stubborn"]["status"] == "failed-gate" and "invariance broken" in genes["stubborn"]["gate"]["reasons"][0]
    assert state["run"]["spend"]["llm_calls"] == 4 and state["run"]["spend"]["llm_usd"] == pytest.approx(0.04)


# ---------------------------------------------------------------- pruning

def test_ideas_that_stay_neutral_while_off_are_pruned(pool, tmp_path):
    cfg = make_cfg(tmp_path, "prune", generations=3, proposals=0, tune_every=1, tune_trials=0, seeds=2,
                   decomposition=False, prune_after=3)
    run_dir = run_engine(cfg, executor=pool)
    state = read(run_dir)
    genes = {g["name"]: g for g in state["genes"]}
    # the champion is the seed's defaults (nothing is tuned): every idea is off and measured by switching it on
    assert genes["noop"]["status"] == "pruned" and genes["noop"]["knockout"]["effect"] == 0.0
    assert genes["boost"]["status"] == "inactive" and genes["boost"]["knockout"]["effect"] > 8
    assert genes["small_trick"]["status"] == "inactive" and genes["small_trick"]["knockout"]["effect"] > 4
    pruned = events(run_dir, "gene_pruned")
    assert {e["generation"] for e in pruned} == {3} and "noop" in {e["gene"] for e in pruned}
    assert genes["noop"]["neutral_rounds"] == 3 and genes["boost"]["neutral_rounds"] == 0
    assert (run_dir / "trunk" / "gen000" / "genes.json").read_text() == (TOY_SOLVER / "genes.json").read_text()
