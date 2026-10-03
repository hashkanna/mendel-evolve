"""The generation loop.

Run directory layout, under runs/<id>/:
  state.json              the run state (PROTOCOL.md section 3), rewritten after every sub-step
  checkpoint.json         everything needed to resume, written at the end of every completed generation
  events.jsonl            append-only log, one JSON object per event
  trunk/genNNN/           solver snapshots; gen000 is the seed, a new one appears whenever a gene is merged
  proposals/genNNN/<k>/   inventor sandboxes (<k>r is the retry after a gate failure)
  ideas.jsonl             queue of human ideas: {"text": ..., "author": ...} per line
  results.sqlite          the evaluation cache
  live.json               written by `mendel knockout` for the live demo
  certificates/           solutions that beat the best known value
  records.json, compute.json   optional, written by other processes; folded into state.json
  engine.lock             held while an engine is running this run (one engine per run directory)

Seeds. Selection (screening, tuning and its confirmation) uses seeds 0..seeds-1. Attribution
(knockouts, pairwise, generality, the champion's reported scores, the decomposition) uses a disjoint
block starting at attribution_seed_base, so a champion is never measured on the seeds it was
selected on. Both blocks are fixed for the whole run, so the cache keeps helping.

Robustness. Every sub-step runs under _guard(): a failure is logged as a step_failed event and the
run carries on. A generation that fails outside a guarded step is rolled back to the last checkpoint
and the run moves on to the next generation. Ctrl-C and the Modal executor's BudgetExceeded stop the
run; either way it can be resumed from the end of the last completed generation.
"""
from __future__ import annotations

import copy
import itertools
import json
import os
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path

from mendel import experiments, gate
from mendel.executor import CachedExecutor, MeteredExecutor, make_executor
from mendel.genes import by_name, complete_config, defaults, is_idea, is_on, load_genes
from mendel.ledger import Ledger, now, read_json, write_json_atomic
from mendel.problem import load_problem
from mendel.solver import copy_sources, solver_version
from mendel.tune import tune
from mendel.types import Proposal

MAX_FAILED_GENERATIONS = 3   # in a row; then the run stops instead of burning LLM calls


def _default_budget() -> dict:
    return {"kind": "time", "value": 2.0}


class ResumeError(RuntimeError):
    """The run directory cannot be started or resumed as asked (it exists, or it has no checkpoint)."""


def is_budget_stop(exc: BaseException) -> bool:
    """True for the Modal executor's BudgetExceeded. Matched by class name so that the backend (and
    modal itself) need not be importable here."""
    return any(c.__name__ == "BudgetExceeded" for c in type(exc).__mro__)


@dataclass
class EngineConfig:
    problem_dir: str
    solver_dir: str                     # the seed solver
    runs_dir: str = "runs"
    run_id: str | None = None           # default: <date>-<time>-<problem>
    generations: int = 3                # total; a resumed run continues up to this number
    proposals: int = 4                  # K: proposals per generation
    inventor: str = "claude-cli"        # kind passed to mendel.inventor.make_inventor
    inventor_opts: dict = field(default_factory=dict)
    executor: str = "local"             # "local" or "modal"
    workers: int | None = None
    executor_opts: dict = field(default_factory=dict)
    cache: bool = True                  # keep results in runs/<id>/results.sqlite
    budget: dict = field(default_factory=_default_budget)   # per run: screening, knockouts, scoring
    seeds: int = 8                      # paired seeds per instance: screening, knockouts, scoring
    heldout_seeds: int = 4              # seeds on held-out instances (scores and the generality test)
    attribution_seed_base: int = 1000   # first seed of the attribution block (see the module docstring)
    score_heldout: bool = True          # also score the champion on held-out instances
    require_significant: bool = False   # merge only when the screening interval is entirely above zero
    tune_every: int = 2                 # tune + knockouts every this many generations (0: never tune)
    tune_trials: int = 32
    tune_batch: int = 8
    tune_seeds: int = 2
    tune_top: int = 3                   # configs re-evaluated on all `seeds` after tuning
    tune_budget: dict | None = None     # default: `budget`
    flip_pass: bool = True              # after tuning, flip each idea and keep flips whose interval is above zero
    pairwise_top: int = 3               # pairwise interactions among the top ideas (0 or 1: off)
    generality: bool = True
    decomposition: bool = True          # at the end of the run
    neutral_tol: float | None = None    # score units; default 0.5% of the champion's mean score
    prune_after: int = 3                # mark an idea pruned after this many neutral rounds while off (0: never)
    gate_iters: int = 2000              # long enough to reach restarts/kicks; the invariance check is only as good as this
    gate_seeds: int = 2
    gate_instances: int = 2
    gate_timeout: float = 120.0
    gate_retries: int = 1               # inventor retries within a generation after a gate failure (0 or 1)


def config_from_dict(data: dict) -> EngineConfig:
    names = {f.name for f in fields(EngineConfig)}
    return EngineConfig(**{k: v for k, v in data.items() if k in names})


def load_run_config(run_dir) -> EngineConfig:
    """The EngineConfig a run was last started with (from its checkpoint, else its state.json)."""
    run_dir = Path(run_dir)
    for name in ("checkpoint.json", "state.json"):
        data = read_json(run_dir / name)
        if name == "checkpoint.json" and isinstance(data, dict):
            data = data.get("state")
        config = ((data.get("engine") or {}).get("config")) if isinstance(data, dict) else None
        if isinstance(config, dict) and "problem_dir" in config and "solver_dir" in config:
            return config_from_dict(config)
    raise FileNotFoundError(f"no run to resume in {run_dir} (no checkpoint.json or state.json with an engine config)")


class Engine:
    def __init__(self, cfg: EngineConfig, inventor=None, executor=None):
        """inventor and executor may be injected (tests, custom backends); otherwise they are built
        from cfg. An injected executor is still wrapped with spend metering and the cache."""
        if max(cfg.seeds, cfg.tune_seeds) > cfg.attribution_seed_base:
            raise ValueError("seeds and tune_seeds must not exceed attribution_seed_base: the selection and "
                             "attribution seed blocks have to stay disjoint")
        self.cfg = cfg
        self.problem = load_problem(cfg.problem_dir)
        self.inventor = inventor
        self._raw_executor = executor
        self.train = self.problem.instances.get("train", [])
        self.heldout = self.problem.instances.get("heldout", [])
        self.port_queue: list[dict] = []
        self.ideas_taken = 0
        self.provenance: dict[str, dict] = {}   # merged gene -> {"author", "added_gen"} as the engine saw it
        self.step = "idle"                      # the sub-step in progress
        self._scored_gen = -1
        self._analysed_gen = -1
        self._seed_mean: float | None = None
        self._lock_file = None

    # ---------------------------------------------------------------- seeds

    def _seeds(self, n: int | None = None) -> list[int]:
        """The selection block: screening, tuning and tuning's confirmation."""
        return list(range(self.cfg.seeds if n is None else n))

    def _fresh_seeds(self, n: int | None = None) -> list[int]:
        """The attribution block: seeds that screening and the tuner never see."""
        base = self.cfg.attribution_seed_base
        return list(range(base, base + (self.cfg.seeds if n is None else n)))

    # ---------------------------------------------------------------- run, resume, stop

    def run(self, resume: bool = False, overwrite: bool = False) -> Path:
        """Run (or resume) the generation loop. Returns the run directory; state.run.status says how
        it ended: "finished", "stopped: budget", "stopped" (Ctrl-C, re-raised) or "failed" (re-raised)."""
        try:
            fresh = self._open(resume, overwrite)
        except BaseException:
            self._unlock()
            raise
        try:
            if fresh:
                self._guard("score", self._rescore)
                self._checkpoint(0)
            failures = 0
            first = self.ledger.state["run"]["generation"] + 1
            for g in range(first, self.cfg.generations + 1):
                try:
                    self._generation(g)
                except Exception as e:
                    if is_budget_stop(e):
                        raise
                    failures += 1
                    self._rollback(g, e)
                    if failures >= MAX_FAILED_GENERATIONS:
                        raise RuntimeError(f"{failures} generations in a row failed; the last error was "
                                           f"{type(e).__name__}: {e}") from e
                    continue
                failures = 0
                self._checkpoint(g)
            self._finish()
            self._checkpoint(self.ledger.state["run"]["generation"])
        except KeyboardInterrupt:
            self._stop("stopped", "run_stopped", "interrupted; resume with --resume")
            raise
        except Exception as e:
            if is_budget_stop(e):
                self._stop("stopped: budget", "run_stopped", f"budget cap reached: {e}; resume with --resume")
            else:
                self._stop("failed", "run_failed", f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
                raise
        finally:
            if self._raw_executor is None:
                self.executor.close()
            self._unlock()
        return self.run_dir

    def _lock(self) -> None:
        """One engine per run directory: two would interleave their ledger and checkpoint writes."""
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
        except ImportError:   # not POSIX: no lock
            return
        self._lock_file = open(self.run_dir / "engine.lock", "a")
        try:
            fcntl.flock(self._lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._unlock()
            raise ResumeError(f"another engine is already running {self.cfg.run_id!r} "
                              f"({self.run_dir / 'engine.lock'} is held)") from None
        except OSError:       # a filesystem without flock: carry on unlocked
            return
        self._lock_file.truncate(0)
        self._lock_file.write(f"{os.getpid()}\n")
        self._lock_file.flush()

    def _unlock(self) -> None:
        if self._lock_file is not None:
            self._lock_file.close()   # closing releases the lock
            self._lock_file = None

    def _stop(self, status: str, event: str, detail: str, **extra) -> None:
        self.ledger.state["run"]["status"] = status
        self.ledger.event(event, detail=detail, **extra)

    def _open(self, resume: bool, overwrite: bool) -> bool:
        """Create the run directory and ledger, or restore them from the checkpoint. True when fresh."""
        cfg = self.cfg
        cfg.run_id = cfg.run_id or f"{datetime.now():%Y%m%d-%H%M}-{self.problem.name}"
        self.run_dir = Path(cfg.runs_dir).resolve() / cfg.run_id
        self.seed_trunk = self.run_dir / "trunk" / "gen000"
        self._lock()
        checkpoint = self._read_checkpoint()
        old_state = read_json(self.run_dir / "state.json")
        if overwrite:
            checkpoint = None
        elif not resume and (checkpoint is not None or isinstance(old_state, dict)):
            raise ResumeError(f"run {cfg.run_id!r} already exists in {self.run_dir.parent}: continue it with "
                              "--resume, start it over with --overwrite, or pick another run id")
        elif resume and checkpoint is None and isinstance(old_state, dict):
            reached = (old_state.get("run") or {}).get("generation") or 0
            if reached:   # do not silently restart a run that got somewhere but has nothing to resume from
                raise ResumeError(f"run {cfg.run_id!r} reached generation {reached} but has no checkpoint.json, so it "
                                  "cannot be resumed; start it over with --overwrite or pick another run id")
        (self.run_dir / "trunk").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "proposals").mkdir(exist_ok=True)
        (self.run_dir / "ideas.jsonl").touch()
        inner = self._raw_executor or make_executor(cfg.executor, cfg.workers, **cfg.executor_opts)
        metered = MeteredExecutor(inner, lambda n, cpu: self.ledger.spend(evaluations=n, cpu_seconds=cpu))
        self.executor = CachedExecutor(metered, self.run_dir / "results.sqlite") if cfg.cache else metered

        if checkpoint is not None and resume:
            self._restore(checkpoint)
            self.ledger.state["run"]["status"] = "running"
            self.ledger.state["engine"]["config"] = asdict(cfg)
            self.ledger.event("run_resumed", detail=f"from the end of generation {checkpoint['generation']}, "
                                                    f"trunk {self.trunk.name}")
            return False

        (self.run_dir / "checkpoint.json").unlink(missing_ok=True)
        if self.seed_trunk.exists():
            shutil.rmtree(self.seed_trunk)
        copy_sources(cfg.solver_dir, self.seed_trunk)
        self.trunk = self.seed_trunk
        self.ledger = Ledger.create(self.run_dir, cfg.run_id, self.problem)
        self.genes = load_genes(self.trunk)
        self.champion = defaults(self.genes)
        self.ledger.state["engine"] = {"config": asdict(cfg), "trunk": str(self.trunk), "port_queue": [],
                                       "ideas_taken": 0}
        self._sync_genes()
        detail = f"seed solver {cfg.solver_dir}, {len(self.genes)} genes, budget {cfg.budget['kind']}={cfg.budget['value']}"
        if resume:
            detail += "; nothing to resume, so this is a fresh start"
        self.ledger.event("run_started", detail=detail)
        return True

    def _read_checkpoint(self) -> dict | None:
        data = read_json(self.run_dir / "checkpoint.json")
        ok = isinstance(data, dict) and isinstance(data.get("state"), dict) and "trunk" in data
        return data if ok else None

    def _checkpoint(self, g: int) -> None:
        """Everything needed to continue after generation g, in one atomic write."""
        write_json_atomic(self.run_dir / "checkpoint.json", {
            "generation": g,
            "saved": now(),
            "trunk": self.trunk.name,
            "champion": self.champion,
            "port_queue": self.port_queue,
            "ideas_taken": self.ideas_taken,
            "provenance": self.provenance,
            "seed_mean": self._seed_mean,
            "analysed_gen": self._analysed_gen,
            "elapsed": self.ledger.elapsed(),
            "records": self.ledger.own_records,
            "state": self.ledger.state,
        })

    def _restore(self, checkpoint: dict, elapsed: float | None = None) -> None:
        """Put the engine and the ledger back to the end of the checkpointed generation."""
        state = checkpoint["state"]
        on_disk = read_json(self.run_dir / "state.json")
        spent = (on_disk.get("run") or {}).get("spend") if isinstance(on_disk, dict) else None
        if isinstance(spent, dict):   # whatever was spent after the checkpoint is still spent
            for key, value in state["run"]["spend"].items():
                if isinstance(spent.get(key), (int, float)) and not isinstance(spent.get(key), bool):
                    state["run"]["spend"][key] = max(value, spent[key])
        self.ledger = Ledger(self.run_dir, state)
        self.ledger.set_elapsed(checkpoint.get("elapsed", 0.0) if elapsed is None else elapsed)
        self.ledger.own_records = list(checkpoint.get("records") or [])
        self.trunk = self.run_dir / "trunk" / checkpoint["trunk"]
        self.genes = load_genes(self.trunk)
        self.champion = complete_config(self.genes, checkpoint["champion"])
        self.port_queue = list(checkpoint.get("port_queue") or [])
        self.ideas_taken = int(checkpoint.get("ideas_taken") or 0)
        self.provenance = dict(checkpoint.get("provenance") or {})
        self._seed_mean = checkpoint.get("seed_mean")
        self._analysed_gen = checkpoint.get("analysed_gen", -1)
        self._scored_gen = state["run"]["generation"]

    def _rollback(self, g: int, error: Exception) -> None:
        """Generation g failed outside a guarded step: go back to the last checkpoint and log it."""
        trace = traceback.format_exc()
        checkpoint = self._read_checkpoint()
        if checkpoint is not None:
            self._restore(checkpoint, elapsed=self.ledger.elapsed())
        self.ledger.state["run"]["status"] = "running"
        self.ledger.event("generation_failed", detail=f"generation {g} failed with {type(error).__name__}: {error}; "
                                                      "rolled back to the end of the last completed generation",
                          traceback=trace)

    def _guard(self, step: str, fn, *args, _gene: str | None = None, **kwargs):
        """Run one sub-step. If it fails, log a step_failed event and carry on (returns None).
        Ctrl-C and a budget stop are not swallowed."""
        self.step = step
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if is_budget_stop(e):
                raise
            self.ledger.event("step_failed", gene=_gene, detail=f"{step}: {type(e).__name__}: {e}", step=step,
                              traceback=traceback.format_exc())
            return None

    def _finish(self) -> None:
        last = self.ledger.state["run"]["generation"]
        if self._analysed_gen != last:
            self._analyse(last, do_tune=False)
        if self.cfg.decomposition:
            self._guard("decomposition", self._decomposition)
        self.ledger.state["run"]["status"] = "finished"
        self.ledger.event("run_finished", detail=f"{last} generations")

    # ---------------------------------------------------------------- bookkeeping

    def _status(self, gene: dict) -> str:
        """active: on in the champion (an allele follows its `of` idea). inactive: in the solver, off.
        pruned: stays pruned for as long as the idea is off."""
        if is_idea(gene):
            if is_on(gene, self.champion[gene["name"]]):
                return "active"
            entry = self.ledger.gene(gene["name"])
            return "pruned" if entry is not None and entry.get("status") == "pruned" else "inactive"
        parent = by_name(self.genes).get(gene.get("of"))
        if parent is not None and not is_on(parent, self.champion[parent["name"]]):
            return "inactive"
        return "active"

    def _sync_genes(self) -> None:
        """Mirror the trunk's registry and the champion's values into state.genes."""
        for g in self.genes:
            fields_ = {k: g[k] for k in ("kind", "author", "added_gen", "hypothesis", "predicted", "of", "default",
                                         "choices", "low", "high", "log") if k in g}
            fields_.setdefault("author", "seed")
            fields_.setdefault("added_gen", 0)
            fields_.setdefault("hypothesis", "")
            # the proposal's author and the generation it was merged in win over what the inventor
            # wrote into genes.json (the trunk's genes.json itself is left exactly as it was gated)
            fields_.update(self.provenance.get(g["name"], {}))
            status = self._status(g)
            entry = self.ledger.upsert_gene(g["name"], **fields_)
            entry["status"] = status
            entry["value"] = self.champion[g["name"]]
            entry.pop("gate", None)
            entry.pop("note", None)
        self.ledger.state["engine"]["trunk"] = str(self.trunk)
        self.ledger.save()

    def _rescore(self) -> None:
        """Score the champion on the attribution seeds, refresh state.champion, add a timeline point,
        check for records."""
        cfg = self.cfg
        res = experiments.score_config(self.executor, self.problem, self.trunk, self.champion, self.train,
                                       self._fresh_seeds(), cfg.budget)
        if res["scores"] and all(s["runs"] == 0 for s in res["scores"].values()):
            raise RuntimeError("no usable runs while scoring the champion: " + "; ".join(res["errors"]))
        scores, solutions = dict(res["scores"]), dict(res["solutions"])
        if cfg.score_heldout and self.heldout:
            held = experiments.score_config(self.executor, self.problem, self.trunk, self.champion, self.heldout,
                                            self._fresh_seeds(cfg.heldout_seeds), cfg.budget)
            scores.update(held["scores"])
            solutions.update(held["solutions"])
        state = self.ledger.state
        state["champion"] = {"config": dict(self.champion), "solver_version": solver_version(self.trunk),
                             "solver_dir": str(self.trunk), "scores": scores, "solutions": solutions}
        generation = state["run"]["generation"]
        state["timeline"].append({"t": round(self.ledger.elapsed(), 1), "generation": generation,
                                  "score": res["normalised_mean"]})
        self._scored_gen = generation
        means = [scores[k]["mean"] for k in self.problem.keys("train") if scores.get(k, {}).get("mean") is not None]
        if means:
            mean = sum(means) / len(means)
            if self._seed_mean is None:
                self._seed_mean = mean
            # provisional until the end-of-run decomposition separates tuning from ideas;
            # `compute` comes from compute.json when that exists (see ledger.py)
            state["decomposition"] = {"seed": self._seed_mean, "tuning": 0.0,
                                      "ideas": self.problem.sign * (mean - self._seed_mean), "compute": 0.0,
                                      "unit": "points, mean over train instances", "provisional": True}
        self._check_records(scores, solutions)
        self.ledger.save()

    def _check_records(self, scores: dict, solutions: dict) -> None:
        """A best score strictly better than the best known value is re-verified and certified."""
        instances = {self.problem.key(i): i for i in self.train + self.heldout}
        records = self.ledger.own_records
        for key, summary in scores.items():
            known = self.problem.best_known.get(key)
            best = summary.get("best")
            if known is None or best is None or key not in solutions or not self.problem.better(best, known):
                continue
            if any(r["instance"] == key and r["value"] == best for r in records):
                continue
            verdict = self.problem.evaluate(instances[key], solutions[key])
            verified = bool(verdict["valid"]) and verdict["score"] == best
            name = f"certificates/{key}_{best:g}.json"
            (self.run_dir / "certificates").mkdir(exist_ok=True)
            write_json_atomic(self.run_dir / name, {"instance": instances[key], "value": best, "best_known": known,
                                                    "solution": solutions[key], "config": self.champion,
                                                    "solver_version": solver_version(self.trunk)})
            records.append({"instance": key, "value": best, "best_known": known, "verified": verified,
                            "certificate": name})
            self.ledger.event("record", detail=f"{key}: {best:g} beats the best known {known:g}")

    def _record_name(self, name: str, g: int, k: int) -> str:
        """A ledger name for a proposal that is not merged. A queued entry of the same name is the
        same idea coming back from its port, so it is updated; anything else is never clobbered."""
        existing = self.ledger.gene(name)
        if existing is None or existing.get("status") == "queued":
            return name
        return f"{name}@g{g}.{k}"

    def _record_unmerged(self, g: int, k: int, proposal: Proposal, status: str, **fields_) -> str:
        name = self._record_name(proposal.genes[0] if proposal.genes else f"proposal_g{g}_{k}", g, k)
        kind = "switch"
        try:
            kind = by_name(load_genes(proposal.solver_dir))[proposal.genes[0]]["kind"]
        except Exception:
            pass
        entry = self.ledger.upsert_gene(name, kind=kind, author=proposal.author, added_gen=g,
                                        hypothesis=proposal.hypothesis, predicted=proposal.predicted, status=status,
                                        sandbox=str(proposal.solver_dir), **fields_)
        entry.pop("note", None)
        if status != "failed-gate":
            entry.pop("gate", None)
        return name

    # ---------------------------------------------------------------- one generation

    def _generation(self, g: int) -> None:
        # The inventor gets the state as it stood at the end of the previous generation, so
        # state["run"]["generation"] + 1 is the generation it is inventing for.
        # (After a rolled-back generation the counter in the ledger lags by more than one, so it is
        # set explicitly.)
        snapshot = self.ledger.snapshot()
        snapshot["run"]["generation"] = g - 1
        self.ledger.state["run"]["generation"] = g
        self.ledger.event("generation_started", detail=f"trunk {self.trunk.name}")
        entries = self._propose(g, snapshot)
        survivors = self._gate(g, entries, snapshot)
        screened = self._screen(g, survivors)
        self._select(g, screened)
        self._close_queue()
        if self.cfg.tune_every > 0 and g % self.cfg.tune_every == 0:
            self._analyse(g, do_tune=True)
        if self._scored_gen != g:   # nothing changed: carry the score forward so the timeline moves
            timeline = self.ledger.state["timeline"]
            timeline.append({"t": round(self.ledger.elapsed(), 1), "generation": g,
                             "score": timeline[-1]["score"] if timeline else 0.0})
            self._scored_gen = g
        self.step = "idle"
        self.ledger.event("generation_finished", detail=f"trunk {self.trunk.name}")

    def _pending_ideas(self) -> list[dict]:
        """Human ideas in ideas.jsonl that have not been handed to the inventor yet."""
        path = self.run_dir / "ideas.jsonl"
        ideas = []
        try:
            lines = path.read_text().splitlines()
        except OSError:
            return []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                item = {"text": line}
            if isinstance(item, dict) and str(item.get("text") or "").strip():
                ideas.append(item)
        return ideas[self.ideas_taken:]

    def _slots(self, k: int) -> list[dict]:
        """What each of the K proposals is asked for: human ideas first, then ports, then free invention."""
        slots: list[dict] = []
        for idea in self._pending_ideas()[:k]:
            slots.append({"source": "human", "directive": idea["text"],
                          "author": f"human:{idea.get('author') or 'anonymous'}"})
            self.ideas_taken += 1
        ports = self.port_queue[:k - len(slots)]
        for port in ports:
            directive = (
                "Port an idea that already screened positive onto the current trunk.\n"
                f"Idea gene: {port['name']}\n"
                f"Hypothesis: {port['hypothesis']}\n"
                f"Predicted: {port['predicted']}\n"
                f"Measured effect on an earlier trunk: {port['effect']:+.4g} "
                f"(95% interval {port['ci'][0]:+.4g} to {port['ci'][1]:+.4g}).\n"
                f"Its implementation against that earlier trunk is in: {port['sandbox']}\n"
                "Re-implement the same idea on top of the current trunk, keeping the gene name unless the "
                "trunk already has a gene with that name.")
            author = port["author"] if str(port.get("author", "")).startswith("human:") else None
            slots.append({"source": "port", "directive": directive, "author": author})
        self.port_queue = self.port_queue[len(ports):]   # ports that did not fit wait for the next generation
        while len(slots) < k:
            slots.append({"source": "inventor", "directive": None, "author": None})
        self.ledger.state["engine"]["ideas_taken"] = self.ideas_taken
        self.ledger.state["engine"]["port_queue"] = list(self.port_queue)
        return slots

    def _invent(self, workdir: Path, slot: dict, snapshot: dict, directive: str | None = None) -> Proposal:
        """One inventor call in a fresh sandbox. Never raises: a failure is a Proposal with ok=False."""
        if workdir.exists():
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        try:
            p = self.inventor.propose(trunk=self.trunk, problem_dir=self.problem.dir,
                                      state=copy.deepcopy(snapshot), workdir=workdir,
                                      directive=slot["directive"] if directive is None else directive,
                                      author=slot["author"])
        except Exception as e:
            return Proposal(ok=False, solver_dir=None, genes=[], hypothesis="", predicted="",
                            author=slot["author"] or "llm:unknown", error=f"{type(e).__name__}: {e}")
        if not (p.ok and p.solver_dir and p.genes):
            p.ok = False
        return p

    def _log_proposal(self, p: Proposal, slot: dict, k: int, retry: bool = False) -> None:
        self.ledger.spend(llm_calls=1, llm_usd=p.cost_usd or 0.0)
        if p.ok:
            self.ledger.event("gene_proposed", gene=p.genes[0], detail=p.hypothesis, author=p.author,
                              predicted=p.predicted, source=slot["source"], slot=k, genes=p.genes, retry=retry,
                              cost_usd=p.cost_usd, log=str(p.log_path) if p.log_path else None)
        else:
            self.ledger.event("inventor_failed", detail=p.error or "the inventor returned no solver", slot=k,
                              author=p.author, source=slot["source"], retry=retry)

    def _propose(self, g: int, snapshot: dict) -> list[dict]:
        """K inventor calls in parallel threads. Returns [{"k", "slot", "proposal"}]."""
        k = self.cfg.proposals
        if k <= 0:
            return []
        if self.inventor is None:
            try:
                from mendel.inventor import make_inventor  # lazy: so everything else imports without it

                self.inventor = make_inventor(self.cfg.inventor, **self.cfg.inventor_opts)
            except Exception as e:
                self.ledger.event("step_failed", detail=f"invent: cannot create the inventor: {type(e).__name__}: {e}",
                                  step="invent")
                return []
        slots = self._slots(k)
        gen_dir = self.run_dir / "proposals" / f"gen{g:03d}"
        self.step = "invent"
        self.ledger.event("inventing", detail=f"{k} proposals: " + ", ".join(s["source"] for s in slots))
        with ThreadPoolExecutor(max_workers=k) as pool:
            proposals = list(pool.map(lambda i: self._invent(gen_dir / str(i), slots[i], snapshot), range(k)))
        entries = []
        for i, p in enumerate(proposals):
            self._log_proposal(p, slots[i], i)
            entries.append({"k": i, "slot": slots[i], "proposal": p})
        return entries

    def _check_gate(self, p: Proposal):
        """The gate verdict, or None when the gate could not run (logged; not the proposal's fault)."""
        cfg = self.cfg
        contexts = [defaults(self.genes)]
        if self.champion != contexts[0]:
            contexts.append(self.champion)   # last: also the context for the smoke test
        verdict = self._guard("gate", gate.check, self.trunk, p.solver_dir, p.genes, executor=self.executor,
                              problem=self.problem, configs=contexts, instances=self.train[:cfg.gate_instances],
                              seeds=range(cfg.gate_seeds), iters=cfg.gate_iters, timeout=cfg.gate_timeout,
                              _gene=p.genes[0])
        if verdict is not None and verdict.infra:
            self.ledger.event("step_failed", gene=p.genes[0], detail="gate: " + " | ".join(verdict.reasons),
                              step="gate")
            return None
        return verdict

    def _retry_directive(self, entry: dict) -> str:
        p, verdict = entry["proposal"], entry["gate"]
        lines = [
            "Your previous attempt at this idea failed the gate, so it was never measured. Fix it.",
            f"Idea gene: {p.genes[0]}",
            f"Hypothesis: {p.hypothesis}",
            f"The failed implementation is in: {p.solver_dir}",
            "The gate's reasons:",
            *[f"- {reason}" for reason in verdict.reasons],
            "Re-implement the same idea on top of the current trunk, keeping the gene name, so that it passes "
            "the gate. " + gate.RULE,
        ]
        if entry["slot"]["directive"]:
            lines += ["", "The original request for this slot was:", entry["slot"]["directive"]]
        return "\n".join(lines)

    def _gate(self, g: int, entries: list[dict], snapshot: dict) -> list[dict]:
        """Gate every proposal. One that fails gets one retry from the inventor, with the gate's reasons."""
        survivors, failed = [], []
        for e in entries:
            p = e["proposal"]
            if not p.ok:
                continue
            verdict = self._check_gate(p)
            if verdict is None:
                continue
            if verdict.ok:
                survivors.append({**e, "gate": verdict})
                self.ledger.event("gate_passed", gene=p.genes[0], detail=verdict.summary(), warnings=verdict.warnings)
            else:
                failed.append({**e, "gate": verdict})

        retried: list[Proposal | None] = [None] * len(failed)
        if failed and self.cfg.gate_retries > 0:
            gen_dir = self.run_dir / "proposals" / f"gen{g:03d}"
            for e in failed:
                self.ledger.event("gate_retry", gene=e["proposal"].genes[0], detail=" | ".join(e["gate"].reasons),
                                  checks=e["gate"].checks)
            self.step = "invent"
            with ThreadPoolExecutor(max_workers=len(failed)) as pool:
                retried = list(pool.map(
                    lambda e: self._invent(gen_dir / f"{e['k']}r", e["slot"], snapshot, self._retry_directive(e)),
                    failed))
            for e, p2 in zip(failed, retried):
                self._log_proposal(p2, e["slot"], e["k"], retry=True)

        for e, p2 in zip(failed, retried):
            p, verdict = e["proposal"], e["gate"]
            if p2 is not None and p2.ok:
                second = self._check_gate(p2)
                if second is not None and second.ok:
                    survivors.append({**e, "proposal": p2, "gate": second, "retried": True})
                    self.ledger.event("gate_passed", gene=p2.genes[0], detail=second.summary() + " on the retry",
                                      warnings=second.warnings)
                    continue
                if second is not None:
                    p, verdict = p2, second
            name = self._record_unmerged(g, e["k"], p, "failed-gate", gate={"ok": False, "reasons": verdict.reasons})
            self.ledger.event("gate_failed", gene=name, detail=" | ".join(verdict.reasons), checks=verdict.checks)
        return survivors

    def _screen(self, g: int, survivors: list[dict]) -> list[dict]:
        cfg = self.cfg
        screened = []
        for s in survivors:
            p = s["proposal"]
            res = self._guard("screen", experiments.screen_gene, self.executor, self.problem, p.solver_dir,
                              self.champion, p.genes[0], self.train, self._seeds(), cfg.budget,
                              off_solver_dir=self.trunk, _gene=p.genes[0])
            if res is None:
                continue
            if res["failed_b"] > 0:   # the trunk's own runs failed: infrastructure, not the proposal
                self.ledger.event("step_failed", gene=p.genes[0], step="screen",
                                  detail=f"screen: {res['failed_b']} runs of the trunk itself failed; "
                                         "the proposal was not measured")
                continue
            s["screen"] = res
            s["summary"] = {"effect": res["effect"], "ci": res["ci"], "runs": res["runs"], "generation": g}
            screened.append(s)
            self.ledger.event("gene_screened", gene=p.genes[0],
                              detail=f"effect {res['effect']:+.4g}, 95% interval [{res['ci'][0]:+.4g}, "
                                     f"{res['ci'][1]:+.4g}], {res['runs']} runs",
                              effect=res["effect"], ci=res["ci"], runs=res["runs"], failed_on=res["failed_a"],
                              seeds=self._seeds())
        return screened

    def _select(self, g: int, screened: list[dict]) -> None:
        """The best positive proposal becomes the trunk; other positive ones are queued for porting."""
        cfg = self.cfg

        def viable(s: dict) -> bool:
            return s["screen"]["runs"] > 0 and s["screen"]["failed_a"] == 0

        def accepted(s: dict) -> bool:
            r = s["screen"]
            return viable(s) and r["effect"] > 0 and (not cfg.require_significant or r["ci"][0] > 0)

        winners = sorted((s for s in screened if accepted(s)), key=lambda s: s["screen"]["effect"], reverse=True)
        winner = winners[0] if winners else None
        for s in screened:
            if s is winner:
                continue
            p, r = s["proposal"], s["screen"]
            if winner is not None and viable(s) and r["effect"] > 0:
                name = self._record_unmerged(g, s["k"], p, "queued", screen=s["summary"])
                self.port_queue.append({"name": p.genes[0], "ledger_name": name, "hypothesis": p.hypothesis,
                                        "predicted": p.predicted, "author": p.author, "sandbox": str(p.solver_dir),
                                        "effect": r["effect"], "ci": r["ci"], "from_generation": g})
                self.ledger.state["engine"]["port_queue"] = list(self.port_queue)
                self.ledger.event("gene_queued", gene=name,
                                  detail=f"effect {r['effect']:+.4g}; will be ported onto the new trunk next generation")
                continue
            name = self._record_unmerged(g, s["k"], p, "rejected", screen=s["summary"])
            if not viable(s):
                why = f"{r['failed_a']} runs failed or were invalid with the gene on"
            elif r["effect"] > 0:
                why = f"effect {r['effect']:+.4g} is positive but its interval includes zero"
            else:
                why = f"effect {r['effect']:+.4g} is not positive"
            self.ledger.event("gene_rejected", gene=name, detail=why)
        if winner is not None:
            self._merge(g, winner)

    def _close_queue(self) -> None:
        """A queued gene whose port did not come back this generation stops being 'queued'."""
        waiting = {port.get("ledger_name", port["name"]) for port in self.port_queue}
        for entry in self.ledger.state["genes"]:
            if entry.get("status") == "queued" and entry["name"] not in waiting:
                entry["status"] = "rejected"
                entry["note"] = "screened positive, but its port onto the new trunk did not come back"
                self.ledger.event("gene_rejected", gene=entry["name"], detail=entry["note"])

    def _merge(self, g: int, s: dict) -> None:
        p, res = s["proposal"], s["screen"]
        dst = self.run_dir / "trunk" / f"gen{g:03d}"
        if dst.exists():
            shutil.rmtree(dst)
        copy_sources(p.solver_dir, dst)
        self.trunk = dst
        self.genes = load_genes(dst)
        self.champion = complete_config(self.genes, res["config"])
        for name in p.genes:
            self.provenance[name] = {"author": p.author, "added_gen": g}
        self._sync_genes()
        self.ledger.upsert_gene(p.genes[0], hypothesis=p.hypothesis or self.ledger.gene(p.genes[0])["hypothesis"],
                                predicted=p.predicted, screen=s["summary"], neutral_rounds=0)
        self.ledger.event("gene_merged", gene=p.genes[0],
                          detail=f"effect {res['effect']:+.4g}; new trunk {dst.name}")
        self._guard("score", self._rescore)

    # ---------------------------------------------------------------- tuning and attribution

    def _neutral_tol(self) -> float:
        if self.cfg.neutral_tol is not None:
            return self.cfg.neutral_tol
        scores = self.ledger.state["champion"]["scores"]
        means = [abs(scores[k]["mean"]) for k in self.problem.keys("train")
                 if scores.get(k, {}).get("mean") is not None]
        return 0.005 * sum(means) / len(means) if means else 0.0

    def _analyse(self, g: int, do_tune: bool) -> None:
        """Tune (selection seeds), then one attribution round on fresh seeds: knockouts for the ideas
        that are on, knock-ins for those that are off, pairwise interactions, generality.
        Each part is guarded on its own, so a tuner error does not cost the knockouts."""
        cfg = self.cfg
        if do_tune and cfg.tune_trials > 0:
            self._guard("tune", self._tune, g)
        kos = self._guard("knockouts", self._knockouts, g)
        if kos is None:
            return
        self._analysed_gen = g
        if cfg.pairwise_top >= 2 and len(kos) >= 2:
            self._guard("pairwise", self._pairwise, g, kos)
        if cfg.generality and self.heldout and kos:
            self._guard("generality", self._generality, kos)

    def _tune(self, g: int) -> None:
        cfg = self.cfg
        self.ledger.event("tuning_started", detail=f"{cfg.tune_trials} trials in batches of {cfg.tune_batch}")
        result = tune(self.executor, self.problem, self.trunk, base_config=self.champion, instances=self.train,
                      seeds=self._seeds(cfg.tune_seeds), budget=cfg.tune_budget or cfg.budget,
                      n_trials=cfg.tune_trials, batch=cfg.tune_batch, top_k=cfg.tune_top,
                      confirm_seeds=self._seeds(), sampler_seed=g, flip=cfg.flip_pass)
        seeds = {"seeds": self._seeds(cfg.tune_seeds), "confirm_seeds": self._seeds()}
        if not (result["improved"] and result["config"] != self.champion):
            self.ledger.event("tuned", detail="no better config found", **seeds)
            return
        changes = ", ".join(f"{k}: {self.champion[k]!r} -> {v!r}" for k, v in result["config"].items()
                            if self.champion[k] != v)
        flips = "; flip pass kept " + ", ".join(f"{f['gene']}={f['to']!r} ({f['effect']:+.4g})"
                                                for f in result["flips"]) if result["flips"] else ""
        self.champion = result["config"]
        self._sync_genes()
        self.ledger.event("tuned", detail=f"normalised score {result['base_score']:.4f} -> {result['score']:.4f} "
                                          f"on the confirmation seeds; {changes}{flips}",
                          flips=result["flips"], **seeds)
        self._guard("score", self._rescore)

    def _knockouts(self, g: int) -> dict:
        """One attribution round on the training instances. Returns the knockouts of the active ideas."""
        cfg = self.cfg
        ledger = self.ledger
        seeds = self._fresh_seeds()
        kos = experiments.knockouts(self.executor, self.problem, self.trunk, self.champion, self.train, seeds,
                                    cfg.budget)
        pruned = [g_["name"] for g_ in ledger.state["genes"] if g_.get("status") == "pruned"]
        ins = experiments.knockins(self.executor, self.problem, self.trunk, self.champion, self.train, seeds,
                                   cfg.budget, skip=pruned)
        for name, r in {**kos, **ins}.items():
            ledger.upsert_gene(name, knockout={"effect": r["effect"], "ci": r["ci"], "runs": r["runs"],
                                               "generation": g})
        # pruning: off in the champion and no measurable effect when switched on, round after round
        tol = self._neutral_tol()
        for name in kos:
            ledger.upsert_gene(name, neutral_rounds=0)
        for name, r in ins.items():
            entry = ledger.gene(name)
            neutral = r["runs"] > 0 and -tol <= r["ci"][0] and r["ci"][1] <= tol
            entry["neutral_rounds"] = entry.get("neutral_rounds", 0) + 1 if neutral else 0
            if cfg.prune_after > 0 and entry["neutral_rounds"] >= cfg.prune_after:
                entry["status"] = "pruned"
                ledger.event("gene_pruned", gene=name,
                             detail=f"off in the champion and within +-{tol:.3g} of zero when switched on, "
                                    f"{entry['neutral_rounds']} attribution rounds in a row")
        parts = [f"{n} {r['effect']:+.4g}" for n, r in kos.items()] + \
                [f"{n} (off) {r['effect']:+.4g}" for n, r in ins.items()]
        ledger.event("knockouts", detail="; ".join(parts) or "no ideas", seeds=seeds)
        return kos

    def _pairwise(self, g: int, kos: dict) -> None:
        cfg = self.cfg
        ledger = self.ledger
        top = sorted(kos, key=lambda n: kos[n]["effect"], reverse=True)[:cfg.pairwise_top]
        pairs = list(itertools.combinations(top, 2))
        found = experiments.pairwise(self.executor, self.problem, self.trunk, self.champion, pairs, self.train,
                                     self._fresh_seeds(), cfg.budget)
        keep = [i for i in ledger.state["interactions"]
                if not any({i["a"], i["b"]} == {f["a"], f["b"]} for f in found)]
        ledger.state["interactions"] = keep + [
            {"a": f["a"], "b": f["b"], "synergy": f["synergy"], "ci": f["ci"], "runs": f["runs"], "generation": g}
            for f in found]
        ledger.event("pairwise", detail="; ".join(f"{f['a']} x {f['b']} {f['synergy']:+.4g}" for f in found),
                     seeds=self._fresh_seeds())

    def _generality(self, kos: dict) -> None:
        cfg = self.cfg
        seeds = self._fresh_seeds(cfg.heldout_seeds)
        found = experiments.generality(self.executor, self.problem, self.trunk, self.champion, self.heldout, seeds,
                                       cfg.budget, kos, tol=self._neutral_tol())
        for name, r in found.items():
            self.ledger.upsert_gene(name, generality=r["generality"], label=r["label"])
        self.ledger.event("generality", detail="; ".join(f"{n}: {r['label']}" for n, r in found.items()), seeds=seeds)

    def _decomposition(self) -> None:
        """Seed solver at defaults, seed solver with only its alleles tuned, champion: all three
        measured on the attribution seeds. The alleles are tuned on the selection seeds."""
        cfg = self.cfg
        self.step = "decomposition-tune"
        tuned = tune(self.executor, self.problem, self.seed_trunk, base_config=defaults(load_genes(self.seed_trunk)),
                     instances=self.train, seeds=self._seeds(cfg.tune_seeds), budget=cfg.tune_budget or cfg.budget,
                     n_trials=cfg.tune_trials, batch=cfg.tune_batch, top_k=cfg.tune_top,
                     confirm_seeds=self._seeds(), alleles_only=True)["config"]
        self.step = "decomposition"
        d = experiments.decomposition(self.executor, self.problem, self.seed_trunk, self.trunk, self.champion,
                                      self.train, self._fresh_seeds(), cfg.budget, tuned_seed_config=tuned)
        # `compute` comes from compute.json when that exists (see ledger.py); 0.0 keeps the field numeric
        self.ledger.state["decomposition"] = {"seed": d["seed"], "tuning": d["tuning"], "ideas": d["ideas"],
                                              "compute": 0.0, "unit": d["unit"]}
        self.ledger.event("decomposition", detail=f"seed {d['seed']:.4g}, tuning {d['tuning']:+.4g}, "
                                                  f"ideas {d['ideas']:+.4g}", seeds=self._fresh_seeds())


def run_engine(cfg: EngineConfig, inventor=None, executor=None, resume: bool = False,
               overwrite: bool = False) -> Path:
    """Run (or resume) the generation loop and return the run directory."""
    return Engine(cfg, inventor=inventor, executor=executor).run(resume=resume, overwrite=overwrite)
