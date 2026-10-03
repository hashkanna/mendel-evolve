"""The engine: two generations on the toy fixture with a scripted inventor, then the CLI on that run."""
import json
import threading

import pytest

from mendel import cli
from mendel.engine import EngineConfig, run_engine
from mendel.types import Proposal
from toyhelpers import GOOD, SNEAKY, TOY_PROBLEM, TOY_SOLVER, add_gene

SPECS = {
    "extra1": GOOD.format(name="extra1", gain=5.0),      # truth: +5, the best of generation 1
    "doubling": GOOD.format(name="doubling", gain=3.0),  # truth: +3, the human idea; ported in generation 2
    "sneaky": SNEAKY,                                    # breaks the invariance rule
    "worse": GOOD.format(name="worse", gain=-4.0),       # truth: -4
}
SCRIPT = {1: ["extra1", "sneaky"], 2: ["worse", None]}   # None: the inventor fails


class ScriptedInventor:
    """Stands in for the LLM: human ideas become 'doubling', ports re-implement the named gene,
    everything else comes from SCRIPT."""

    def __init__(self):
        self.lock = threading.Lock()
        self.script = {g: list(names) for g, names in SCRIPT.items()}
        self.calls = []

    def propose(self, *, trunk, problem_dir, state, workdir, directive=None, author=None):
        generation = state["run"]["generation"] + 1   # the state is from the end of the previous generation
        with self.lock:
            self.calls.append({"generation": generation, "directive": directive, "author": author})
            if directive and directive.startswith("Port an idea"):
                name = directive.split("Idea gene: ")[1].split("\n")[0]
            elif author and author.startswith("human:"):
                name = "doubling"
            else:
                name = self.script[generation].pop(0)
        if name is None:
            return Proposal(ok=False, solver_dir=None, genes=[], hypothesis="", predicted="",
                            author="llm:scripted", error="scripted failure")
        solver = add_gene(trunk, workdir / "solver", name, SPECS[name], hypothesis=f"{name} helps")
        return Proposal(ok=True, solver_dir=solver, genes=[name], hypothesis=f"{name} helps", predicted="+?",
                        author=author or "llm:scripted", cost_usd=0.01)


@pytest.fixture(scope="module")
def run(pool, tmp_path_factory):
    runs = tmp_path_factory.mktemp("runs")
    assert cli.main(["idea", "--run", "toyrun", "--runs", str(runs), "--author", "alice", "double it"]) == 0
    inventor = ScriptedInventor()
    cfg = EngineConfig(problem_dir=str(TOY_PROBLEM), solver_dir=str(TOY_SOLVER), runs_dir=str(runs),
                       run_id="toyrun", generations=2, proposals=3, budget={"kind": "iters", "value": 150},
                       seeds=3, heldout_seeds=2, tune_every=2, tune_trials=16, tune_batch=8, tune_seeds=1,
                       pairwise_top=2, gate_iters=100, gate_retries=0)
    run_dir = run_engine(cfg, inventor=inventor, executor=pool)
    state = json.loads((run_dir / "state.json").read_text())
    events = [json.loads(line) for line in (run_dir / "events.jsonl").read_text().splitlines()]
    return {"dir": run_dir, "runs": runs, "state": state, "events": events, "inventor": inventor}


def _events(run, name):
    return [e for e in run["events"] if e["event"] == name]


def test_engine_completes_two_generations(run):
    state = run["state"]
    assert state["run"]["status"] == "finished" and state["run"]["generation"] == 2
    assert state["run"]["problem"] == "toy" and state["run"]["direction"] == "max"
    assert state["instances"] == {"train": ["n4", "n6"], "heldout": ["n8", "n10"]}
    for name in ("state.json", "events.jsonl", "ideas.jsonl", "results.sqlite", "trunk/gen000/solver.py",
                 "trunk/gen001/solver.py", "trunk/gen002/solver.py", "proposals/gen001/0", "proposals/gen002/2"):
        assert (run["dir"] / name).exists(), name
    spend = state["run"]["spend"]
    assert spend["llm_calls"] == 6 and spend["llm_usd"] == pytest.approx(0.05)
    assert spend["evaluations"] > 50 and spend["cpu_seconds"] > 0


def test_engine_follows_the_selection_rules(run):
    merged = [e["gene"] for e in _events(run, "gene_merged")]
    assert merged == ["extra1", "doubling"]              # best of generation 1, then the ported human idea
    assert [e["gene"] for e in _events(run, "gene_queued")] == ["doubling"]
    assert [e["gene"] for e in _events(run, "gate_failed")] == ["sneaky"]
    assert [e["gene"] for e in _events(run, "gene_rejected")] == ["worse"]
    assert len(_events(run, "inventor_failed")) == 1

    genes = {g["name"]: g for g in run["state"]["genes"]}
    assert genes["sneaky"]["status"] == "failed-gate"
    assert "invariance broken" in genes["sneaky"]["gate"]["reasons"][0]
    assert genes["worse"]["status"] == "rejected" and genes["worse"]["screen"]["effect"] < -3
    assert 4 < genes["extra1"]["screen"]["effect"] < 6 and genes["extra1"]["screen"]["ci"][0] > 0
    assert genes["extra1"]["added_gen"] == 1 and genes["extra1"]["author"] == "llm:scripted"
    assert genes["doubling"]["added_gen"] == 2 and genes["doubling"]["author"] == "human:alice"
    assert 2 < genes["doubling"]["screen"]["effect"] < 4
    assert genes["boost"]["author"] == "seed" and genes["step"]["kind"] == "float"
    assert all(g["status"] in ("active", "inactive", "rejected", "failed-gate") for g in genes.values())


def test_engine_feeds_human_ideas_and_ports_to_the_inventor(run):
    calls = run["inventor"].calls
    first = [c for c in calls if c["generation"] == 1]
    assert len(first) == 3 and sum(c["author"] == "human:alice" for c in first) == 1
    assert [c["directive"] for c in first if c["author"] == "human:alice"] == ["double it"]
    ports = [c for c in calls if c["generation"] == 2 and c["directive"]]
    assert len(ports) == 1 and ports[0]["author"] == "human:alice"
    assert "Idea gene: doubling" in ports[0]["directive"] and "doubling helps" in ports[0]["directive"]
    assert str(run["dir"] / "proposals" / "gen001") in ports[0]["directive"]   # the sandbox to port from


def test_engine_state_matches_the_protocol(run):
    state = run["state"]
    champion = state["champion"]
    assert set(champion["scores"]) == {"n4", "n6", "n8", "n10"}
    assert set(champion["scores"]["n4"]) == {"mean", "best", "runs", "budget"}
    assert champion["scores"]["n4"]["budget"] == "iters=150" and champion["solver_version"]
    assert len(champion["solutions"]["n4"]) == 4
    assert {"extra1", "doubling", "boost", "step"} <= set(champion["config"])
    # the flip pass after tuning keeps every idea that measurably helps switched on
    assert all(champion["config"][name] is True for name in ("extra1", "doubling", "boost", "small_trick"))

    timeline = state["timeline"]
    assert timeline[0]["generation"] == 0 and timeline[-1]["generation"] == 2
    assert timeline[-1]["score"] > timeline[0]["score"] + 0.05
    assert [p["score"] for p in timeline] == sorted(p["score"] for p in timeline)   # never gets worse

    genes = {g["name"]: g for g in state["genes"]}
    active = [n for n, g in genes.items() if g["status"] == "active" and g["kind"] == "switch"]
    assert active
    for name in active:                                   # every active idea was knocked out and labelled
        assert set(genes[name]["knockout"]) == {"effect", "ci", "runs", "generation"}
        assert genes[name]["label"] in ("general", "specific", "neutral", "harmful", "inconclusive")
        assert set(genes[name]["generality"]) == {"n8", "n10"}
    assert len(state["interactions"]) == 1
    assert set(state["interactions"][0]) >= {"a", "b", "synergy", "ci", "runs"}

    d = state["decomposition"]
    assert set(d) == {"seed", "tuning", "ideas", "compute", "unit"}
    assert 26 < d["seed"] < 30 and d["tuning"] > 5 and d["ideas"] > 0
    assert state["history"] and set(state["history"][0]) >= {"t", "generation", "event", "detail"}
    assert _events(run, "tuned") and _events(run, "knockouts") and _events(run, "generality")


def test_cli_knockout_writes_live_json(run, capsys):
    gene = next(g["name"] for g in run["state"]["genes"] if g["status"] == "active" and g["kind"] == "switch")
    code = cli.main(["knockout", "--run", "toyrun", "--runs", str(run["runs"]), "--gene", gene, "--quick",
                     "--seeds", "2", "--workers", "0", "--seed-base", "500"])
    assert code == 0
    live = json.loads((run["dir"] / "live.json").read_text())
    assert live["gene"] == gene and live["status"] == "done" and live["was_on"] is True
    assert live["runs"] == 8 and len(live["pairs"]) == 4 and live["budget"] == "iters=150"
    assert set(live["pairs"][0]) == {"instance", "seed", "on", "off", "diff"}
    assert len(live["ci"]) == 2 and live["ci"][0] <= live["effect"] <= live["ci"][1] and live["t"]
    assert cli.main(["knockout", "--run", "toyrun", "--runs", str(run["runs"]), "--gene", "step"]) == 2


def test_cli_idea_score_and_gate(run, tmp_path, capsys):
    ideas = (run["dir"] / "ideas.jsonl").read_text().splitlines()
    assert json.loads(ideas[0])["text"] == "double it" and json.loads(ideas[0])["author"] == "alice"
    args = ["--problem", str(TOY_PROBLEM), "--iters", "100", "--workers", "0"]
    assert cli.main(["score", "--solver", str(TOY_SOLVER), "--seeds", "2", "--config", '{"boost": true}', *args]) == 0
    assert "mean normalised score" in capsys.readouterr().out
    good = add_gene(TOY_SOLVER, tmp_path / "good", "extra", GOOD.format(name="extra", gain=5.0))
    assert cli.main(["gate", str(TOY_SOLVER), str(good), *args]) == 0
    assert "PASS" in capsys.readouterr().out
    bad = add_gene(TOY_SOLVER, tmp_path / "bad", "sneaky", SNEAKY)
    assert cli.main(["gate", str(TOY_SOLVER), str(bad), *args]) == 1
    assert "FAILED" in capsys.readouterr().out
