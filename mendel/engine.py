"""The generation loop.

Run directory layout, under runs/<id>/:
  state.json              the run state (PROTOCOL.md section 3), rewritten after every sub-step
  events.jsonl            append-only log, one JSON object per event
  trunk/genNNN/           solver snapshots; gen000 is the seed, a new one appears whenever a gene is merged
  proposals/genNNN/<k>/   inventor sandboxes
  ideas.jsonl             queue of human ideas: {"text": ..., "author": ...} per line
  results.sqlite          the evaluation cache
  live.json               written by `mendel knockout` for the live demo
  certificates/           solutions that beat the best known value
"""
from __future__ import annotations

import copy
import itertools
import json
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from mendel import experiments, gate
from mendel.executor import CachedExecutor, MeteredExecutor, make_executor
from mendel.genes import by_name, complete_config, defaults, is_idea, is_on, load_genes
from mendel.ledger import Ledger, write_json_atomic
from mendel.problem import load_problem
from mendel.solver import copy_sources, solver_version
from mendel.tune import tune
from mendel.types import Proposal


def _default_budget() -> dict:
    return {"kind": "time", "value": 2.0}


@dataclass
class EngineConfig:
    problem_dir: str
    solver_dir: str                     # the seed solver
    runs_dir: str = "runs"
    run_id: str | None = None           # default: <date>-<time>-<problem>
    generations: int = 3
    proposals: int = 4                  # K: proposals per generation
    inventor: str = "claude-cli"        # kind passed to mendel.inventor.make_inventor
    inventor_opts: dict = field(default_factory=dict)
    executor: str = "local"             # "local" or "modal"
    workers: int | None = None
    executor_opts: dict = field(default_factory=dict)
    cache: bool = True                  # keep results in runs/<id>/results.sqlite
    budget: dict = field(default_factory=_default_budget)   # per run: screening, knockouts, scoring
    seeds: int = 8                      # paired seeds for screening, knockouts and scoring
    heldout_seeds: int = 4              # seeds on held-out instances (scores and the generality test)
    score_heldout: bool = True          # also score the champion on held-out instances
    require_significant: bool = False   # merge only when the screening interval is entirely above zero
    tune_every: int = 2                 # tune + knockouts every this many generations (0: never tune)
    tune_trials: int = 32
    tune_batch: int = 8
    tune_seeds: int = 2
    tune_top: int = 3                   # configs re-evaluated on all `seeds` after tuning
    tune_budget: dict | None = None     # default: `budget`
    pairwise_top: int = 3               # pairwise interactions among the top ideas (0 or 1: off)
    generality: bool = True
    decomposition: bool = True          # at the end of the run
    neutral_tol: float | None = None    # score units; default 0.5% of the champion's mean score
    gate_iters: int = 2000              # long enough to reach restarts/kicks; the invariance check is only as good as this
    gate_seeds: int = 2
    gate_instances: int = 2
    gate_timeout: float = 120.0


class Engine:
    def __init__(self, cfg: EngineConfig, inventor=None, executor=None):
        """inventor and executor may be injected (tests, custom backends); otherwise they are built
        from cfg. An injected executor is still wrapped with spend metering and the cache."""
        self.cfg = cfg
        self.problem = load_problem(cfg.problem_dir)
        self.inventor = inventor
        self._raw_executor = executor
        self.train = self.problem.instances.get("train", [])
        self.heldout = self.problem.instances.get("heldout", [])
        self.port_queue: list[dict] = []
        self.ideas_taken = 0
        self.provenance: dict[str, dict] = {}   # merged gene -> {"author", "added_gen"} as the engine saw it
        self._scored_gen = -1
        self._analysed_gen = -1
        self._seed_mean: float | None = None

    # ---------------------------------------------------------------- run

    def run(self) -> Path:
        self._start()
        try:
            for g in range(1, self.cfg.generations + 1):
                self._generation(g)
            self._finish()
        except BaseException as e:
            self.ledger.state["run"]["status"] = "stopped" if isinstance(e, KeyboardInterrupt) else "failed"
            self.ledger.event("run_failed", detail=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())
            raise
        finally:
            if self._raw_executor is None:
                self.executor.close()
        return self.run_dir

    def _start(self) -> None:
        cfg = self.cfg
        run_id = cfg.run_id or f"{datetime.now():%Y%m%d-%H%M}-{self.problem.name}"
        self.run_dir = Path(cfg.runs_dir).resolve() / run_id
        (self.run_dir / "trunk").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "proposals").mkdir(exist_ok=True)
        (self.run_dir / "ideas.jsonl").touch()
        self.trunk = self.run_dir / "trunk" / "gen000"
        if self.trunk.exists():
            shutil.rmtree(self.trunk)
        copy_sources(cfg.solver_dir, self.trunk)
        self.seed_trunk = self.trunk
        self.ledger = Ledger.create(self.run_dir, run_id, self.problem)
        inner = self._raw_executor or make_executor(cfg.executor, cfg.workers, **cfg.executor_opts)
        metered = MeteredExecutor(inner, lambda n, cpu: self.ledger.spend(evaluations=n, cpu_seconds=cpu))
        self.executor = CachedExecutor(metered, self.run_dir / "results.sqlite") if cfg.cache else metered
        self.genes = load_genes(self.trunk)
        self.champion = defaults(self.genes)
        self.ledger.state["engine"] = {"config": asdict(cfg), "trunk": str(self.trunk), "port_queue": [],
                                       "ideas_taken": 0}
        self._sync_genes()
        self.ledger.event("run_started", detail=f"seed solver {cfg.solver_dir}, {len(self.genes)} genes, "
                                                f"budget {cfg.budget['kind']}={cfg.budget['value']}")
        self._rescore()

    def _finish(self) -> None:
        cfg = self.cfg
        last = self.ledger.state["run"]["generation"]
        if self._analysed_gen != last:
            self._analyse_safely(last, do_tune=False)
        if cfg.decomposition:
            try:
                d = experiments.decomposition(
                    self.executor, self.problem, self.seed_trunk, self.trunk, self.champion, self.train,
                    range(cfg.seeds), cfg.budget,
                    tune_opts={"n_trials": cfg.tune_trials, "batch": cfg.tune_batch, "seeds": range(cfg.tune_seeds),
                               "budget": cfg.tune_budget or cfg.budget, "confirm_seeds": range(cfg.seeds),
                               "top_k": cfg.tune_top})
                # `compute` is filled in separately; 0.0 keeps the field numeric for the dashboard
                self.ledger.state["decomposition"] = {"seed": d["seed"], "tuning": d["tuning"], "ideas": d["ideas"],
                                                      "compute": 0.0, "unit": d["unit"]}
                self.ledger.event("decomposition", detail=f"seed {d['seed']:.4g}, tuning {d['tuning']:+.4g}, "
                                                          f"ideas {d['ideas']:+.4g}")
            except Exception as e:
                self.ledger.event("decomposition_failed", detail=f"{type(e).__name__}: {e}")
        self.ledger.state["run"]["status"] = "finished"
        self.ledger.event("run_finished", detail=f"{last} generations")

    # ---------------------------------------------------------------- bookkeeping

    def _status(self, gene: dict) -> str:
        """active: on in the champion (an allele follows its `of` idea). inactive: in the solver, off."""
        if is_idea(gene):
            return "active" if is_on(gene, self.champion[gene["name"]]) else "inactive"
        parent = by_name(self.genes).get(gene.get("of"))
        if parent is not None and not is_on(parent, self.champion[parent["name"]]):
            return "inactive"
        return "active"

    def _sync_genes(self) -> None:
        """Mirror the trunk's registry and the champion's values into state.genes."""
        for g in self.genes:
            fields = {k: g[k] for k in ("kind", "author", "added_gen", "hypothesis", "predicted", "of", "default",
                                        "choices", "low", "high", "log") if k in g}
            fields.setdefault("author", "seed")
            fields.setdefault("added_gen", 0)
            fields.setdefault("hypothesis", "")
            # the proposal's author and the generation it was merged in win over what the inventor
            # wrote into genes.json (the trunk's genes.json itself is left exactly as it was gated)
            fields.update(self.provenance.get(g["name"], {}))
            entry = self.ledger.upsert_gene(g["name"], **fields)
            entry["status"] = self._status(g)
            entry["value"] = self.champion[g["name"]]
            entry.pop("gate", None)
        self.ledger.state["engine"]["trunk"] = str(self.trunk)
        self.ledger.save()

    def _rescore(self) -> None:
        """Score the champion, refresh state.champion, add a timeline point, check for records."""
        cfg = self.cfg
        res = experiments.score_config(self.executor, self.problem, self.trunk, self.champion, self.train,
                                       range(cfg.seeds), cfg.budget)
        scores, solutions = dict(res["scores"]), dict(res["solutions"])
        if cfg.score_heldout and self.heldout:
            held = experiments.score_config(self.executor, self.problem, self.trunk, self.champion, self.heldout,
                                            range(cfg.heldout_seeds), cfg.budget)
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
            # provisional until the end-of-run decomposition separates tuning from ideas
            state["decomposition"] = {"seed": self._seed_mean, "tuning": 0.0,
                                      "ideas": self.problem.sign * (mean - self._seed_mean), "compute": 0.0,
                                      "unit": "points, mean over train instances", "provisional": True}
        self._check_records(scores, solutions)
        self.ledger.save()

    def _check_records(self, scores: dict, solutions: dict) -> None:
        """A best score strictly better than the best known value is re-verified and certified."""
        instances = {self.problem.key(i): i for i in self.train + self.heldout}
        records = self.ledger.state["records"]
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
        """A ledger name for a proposal that is not merged; never clobbers an existing entry."""
        return name if self.ledger.gene(name) is None else f"{name}@g{g}.{k}"

    def _record_unmerged(self, g: int, k: int, proposal: Proposal, status: str, **fields) -> str:
        name = self._record_name(proposal.genes[0] if proposal.genes else f"proposal_g{g}_{k}", g, k)
        kind = "switch"
        try:
            kind = by_name(load_genes(proposal.solver_dir))[proposal.genes[0]]["kind"]
        except Exception:
            pass
        self.ledger.upsert_gene(name, kind=kind, author=proposal.author, added_gen=g,
                                hypothesis=proposal.hypothesis, predicted=proposal.predicted, status=status,
                                sandbox=str(proposal.solver_dir), **fields)
        return name

    # ---------------------------------------------------------------- one generation

    def _generation(self, g: int) -> None:
        # The inventor gets the state as it stood at the end of the previous generation, so
        # state["run"]["generation"] + 1 is the generation it is inventing for.
        snapshot = self.ledger.snapshot()
        self.ledger.state["run"]["generation"] = g
        self.ledger.event("generation_started", detail=f"trunk {self.trunk.name}")
        proposals = self._propose(g, snapshot)
        survivors = self._gate(g, proposals)
        screened = self._screen(g, survivors)
        self._select(g, screened)
        if self.cfg.tune_every > 0 and g % self.cfg.tune_every == 0:
            self._analyse_safely(g, do_tune=True)
        if self._scored_gen != g:   # nothing changed: carry the score forward so the timeline moves
            timeline = self.ledger.state["timeline"]
            timeline.append({"t": round(self.ledger.elapsed(), 1), "generation": g,
                             "score": timeline[-1]["score"] if timeline else 0.0})
            self._scored_gen = g
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
        for port in self.port_queue[:k - len(slots)]:
            directive = (
                "Port an idea that already screened positive onto the current trunk.\n"
                f"Idea gene: {port['name']}\n"
                f"Hypothesis: {port['hypothesis']}\n"
                f"Predicted: {port['predicted']}\n"
                f"Measured effect on the previous trunk: {port['effect']:+.4g} "
                f"(95% interval {port['ci'][0]:+.4g} to {port['ci'][1]:+.4g}).\n"
                f"Its implementation against the previous trunk is in: {port['sandbox']}\n"
                "Re-implement the same idea on top of the current trunk, keeping the gene name unless the "
                "trunk already has a gene with that name.")
            author = port["author"] if str(port.get("author", "")).startswith("human:") else None
            slots.append({"source": "port", "directive": directive, "author": author})
        self.port_queue = []
        while len(slots) < k:
            slots.append({"source": "inventor", "directive": None, "author": None})
        self.ledger.state["engine"]["ideas_taken"] = self.ideas_taken
        self.ledger.state["engine"]["port_queue"] = []
        return slots

    def _propose(self, g: int, snapshot: dict) -> list[Proposal]:
        k = self.cfg.proposals
        if k <= 0:
            return []
        if self.inventor is None:
            from mendel.inventor import make_inventor  # lazy: so everything else imports without it

            self.inventor = make_inventor(self.cfg.inventor, **self.cfg.inventor_opts)
        slots = self._slots(k)
        gen_dir = self.run_dir / "proposals" / f"gen{g:03d}"

        def one(i: int) -> Proposal:
            workdir = gen_dir / str(i)
            if workdir.exists():
                shutil.rmtree(workdir)
            workdir.mkdir(parents=True)
            try:
                return self.inventor.propose(trunk=self.trunk, problem_dir=self.problem.dir,
                                             state=copy.deepcopy(snapshot), workdir=workdir,
                                             directive=slots[i]["directive"], author=slots[i]["author"])
            except Exception as e:
                return Proposal(ok=False, solver_dir=None, genes=[], hypothesis="", predicted="",
                                author=slots[i]["author"] or "llm:unknown", error=f"{type(e).__name__}: {e}")

        self.ledger.event("inventing", detail=f"{k} proposals: " + ", ".join(s["source"] for s in slots))
        with ThreadPoolExecutor(max_workers=k) as pool:
            proposals = list(pool.map(one, range(k)))
        for i, p in enumerate(proposals):
            self.ledger.spend(llm_calls=1, llm_usd=p.cost_usd or 0.0)
            if p.ok and p.solver_dir and p.genes:
                self.ledger.event("gene_proposed", gene=p.genes[0], detail=p.hypothesis, author=p.author,
                                  predicted=p.predicted, source=slots[i]["source"], slot=i, genes=p.genes,
                                  cost_usd=p.cost_usd, log=str(p.log_path) if p.log_path else None)
            else:
                p.ok = False
                self.ledger.event("inventor_failed", detail=p.error or "the inventor returned no solver", slot=i,
                                  author=p.author, source=slots[i]["source"])
        return proposals

    def _gate(self, g: int, proposals: list[Proposal]) -> list[dict]:
        cfg = self.cfg
        contexts = [defaults(self.genes)]
        if self.champion != contexts[0]:
            contexts.append(self.champion)   # last: also the context for the smoke test
        survivors = []
        for k, p in enumerate(proposals):
            if not p.ok:
                continue
            try:
                verdict = gate.check(self.trunk, p.solver_dir, p.genes, executor=self.executor,
                                     problem=self.problem, configs=contexts,
                                     instances=self.train[:cfg.gate_instances], seeds=range(cfg.gate_seeds),
                                     iters=cfg.gate_iters, timeout=cfg.gate_timeout)
            except Exception as e:
                verdict = gate.GateVerdict(ok=False, reasons=[f"the gate crashed: {type(e).__name__}: {e}"])
            if verdict.ok:
                survivors.append({"k": k, "proposal": p, "gate": verdict})
                self.ledger.event("gate_passed", gene=p.genes[0], detail=verdict.summary(),
                                  warnings=verdict.warnings)
            else:
                name = self._record_unmerged(g, k, p, "failed-gate",
                                             gate={"ok": False, "reasons": verdict.reasons})
                self.ledger.event("gate_failed", gene=name, detail=" | ".join(verdict.reasons),
                                  checks=verdict.checks)
        return survivors

    def _screen(self, g: int, survivors: list[dict]) -> list[dict]:
        cfg = self.cfg
        screened = []
        for s in survivors:
            p = s["proposal"]
            try:
                res = experiments.screen_gene(self.executor, self.problem, p.solver_dir, self.champion,
                                              p.genes[0], self.train, range(cfg.seeds), cfg.budget,
                                              off_solver_dir=self.trunk)
            except Exception as e:
                name = self._record_unmerged(g, s["k"], p, "rejected")
                self.ledger.event("gene_rejected", gene=name, detail=f"screening crashed: {type(e).__name__}: {e}")
                continue
            s["screen"] = res
            s["summary"] = {"effect": res["effect"], "ci": res["ci"], "runs": res["runs"], "generation": g}
            screened.append(s)
            self.ledger.event("gene_screened", gene=p.genes[0],
                              detail=f"effect {res['effect']:+.4g}, 95% interval [{res['ci'][0]:+.4g}, "
                                     f"{res['ci'][1]:+.4g}], {res['runs']} runs",
                              effect=res["effect"], ci=res["ci"], runs=res["runs"], failed_on=res["failed_a"])
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
                port = {"name": p.genes[0], "hypothesis": p.hypothesis, "predicted": p.predicted,
                        "author": p.author, "sandbox": str(p.solver_dir), "effect": r["effect"], "ci": r["ci"],
                        "from_generation": g}
                self.port_queue.append(port)
                self.ledger.state["engine"]["port_queue"] = list(self.port_queue)
                self.ledger.event("gene_queued", gene=p.genes[0],
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
                                predicted=p.predicted, screen=s["summary"])
        self.ledger.event("gene_merged", gene=p.genes[0],
                          detail=f"effect {res['effect']:+.4g}; new trunk {dst.name}")
        self._rescore()

    # ---------------------------------------------------------------- tuning and analysis

    def _neutral_tol(self) -> float:
        if self.cfg.neutral_tol is not None:
            return self.cfg.neutral_tol
        scores = self.ledger.state["champion"]["scores"]
        means = [abs(scores[k]["mean"]) for k in self.problem.keys("train")
                 if scores.get(k, {}).get("mean") is not None]
        return 0.005 * sum(means) / len(means) if means else 0.0

    def _analyse_safely(self, g: int, do_tune: bool) -> None:
        """A failed analysis step is logged, not fatal: the run carries on with the next generation."""
        try:
            self._analyse(g, do_tune)
        except Exception as e:
            self.ledger.event("analysis_failed", detail=f"{type(e).__name__}: {e}", traceback=traceback.format_exc())

    def _analyse(self, g: int, do_tune: bool) -> None:
        """Tune, then knock out every active idea; optionally pairwise interactions and generality."""
        cfg = self.cfg
        ledger = self.ledger
        if do_tune and cfg.tune_trials > 0:
            ledger.event("tuning_started", detail=f"{cfg.tune_trials} trials in batches of {cfg.tune_batch}")
            result = tune(self.executor, self.problem, self.trunk, base_config=self.champion,
                          instances=self.train, seeds=range(cfg.tune_seeds), budget=cfg.tune_budget or cfg.budget,
                          n_trials=cfg.tune_trials, batch=cfg.tune_batch, top_k=cfg.tune_top,
                          confirm_seeds=range(cfg.seeds), sampler_seed=g)
            if result["improved"] and result["config"] != self.champion:
                changes = ", ".join(f"{k}: {self.champion[k]!r} -> {v!r}" for k, v in result["config"].items()
                                    if self.champion[k] != v)
                self.champion = result["config"]
                self._sync_genes()
                ledger.event("tuned", detail=f"normalised score {result['base_score']:.4f} -> "
                                             f"{result['score']:.4f}; {changes}")
                self._rescore()
            else:
                ledger.event("tuned", detail="no better config found")

        kos = experiments.knockouts(self.executor, self.problem, self.trunk, self.champion, self.train,
                                    range(cfg.seeds), cfg.budget)
        for name, ko in kos.items():
            ledger.upsert_gene(name, knockout={"effect": ko["effect"], "ci": ko["ci"], "runs": ko["runs"],
                                               "generation": g})
        ledger.event("knockouts", detail="; ".join(f"{n} {ko['effect']:+.4g}" for n, ko in kos.items()) or
                                         "no active ideas")
        self._analysed_gen = g

        if cfg.pairwise_top >= 2 and len(kos) >= 2:
            top = sorted(kos, key=lambda n: kos[n]["effect"], reverse=True)[:cfg.pairwise_top]
            pairs = list(itertools.combinations(top, 2))
            found = experiments.pairwise(self.executor, self.problem, self.trunk, self.champion, pairs,
                                         self.train, range(cfg.seeds), cfg.budget)
            keep = [i for i in ledger.state["interactions"]
                    if not any({i["a"], i["b"]} == {f["a"], f["b"]} for f in found)]
            ledger.state["interactions"] = keep + [
                {"a": f["a"], "b": f["b"], "synergy": f["synergy"], "ci": f["ci"], "runs": f["runs"],
                 "generation": g} for f in found]
            ledger.event("pairwise", detail="; ".join(f"{f['a']} x {f['b']} {f['synergy']:+.4g}" for f in found))

        if cfg.generality and self.heldout and kos:
            found = experiments.generality(self.executor, self.problem, self.trunk, self.champion, self.heldout,
                                           range(cfg.heldout_seeds), cfg.budget, kos, tol=self._neutral_tol())
            for name, r in found.items():
                ledger.upsert_gene(name, generality=r["generality"], label=r["label"])
            ledger.event("generality", detail="; ".join(f"{n}: {r['label']}" for n, r in found.items()))


def run_engine(cfg: EngineConfig, inventor=None, executor=None) -> Path:
    """Run the generation loop and return the run directory."""
    return Engine(cfg, inventor=inventor, executor=executor).run()
