"""The idea inventor: asks an LLM agent to add exactly one new gene to a solver.

The agent works in a sandbox copy of the trunk solver. It can edit files there and run three
harness tools (build, try, check); it cannot run arbitrary shell commands. Whatever it claims,
the engine re-runs the gate itself afterwards.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import threading
import tomllib
from pathlib import Path

from .types import Proposal

ROOT = Path(__file__).resolve().parent.parent

# Each parallel inventor gets a different lens so that K proposals from one ledger do not collide.
LENSES: list[tuple[str, str]] = [
    ("throughput", "Make each search step cheaper: a better data structure, incremental bookkeeping, "
                   "caching, or avoiding repeated work."),
    ("structure", "Exploit the mathematical structure of good solutions: symmetry, algebraic or modular "
                  "constructions, layering, patterns visible in the best solutions so far."),
    ("dynamics", "Change how the search moves: acceptance rules, restarts, memory of recent moves, "
                 "perturbation strength, plateau handling, targeting the weakest part of a solution."),
    ("construction", "Change how solutions are built or repaired: the starting point, the greedy order, "
                     "repair after removal, seeding from smaller instances."),
    ("wildcard", "Anything that does not fit the other lenses. Surprise us, but keep it testable."),
]

TASK_TEMPLATE = """\
You are an idea inventor for Mendel, a system that improves a solver by adding ideas as named
switches ("genes") and then measuring what each idea is worth by switching it off.

Your job in this session: add exactly ONE new idea to the solver in ./solver.

Read first: PROBLEM.md (the problem and the solver contract), LEDGER.md (every idea so far and its
measured effect), then the solver source.

{directive_block}

Rules
1. One idea, one gene. Register it in solver/genes.json as a "switch" gene (default false) or a
   "choice" gene (default = the current behaviour). Give it a short snake_case name.
2. You may add up to three numeric constants your idea needs, as "int" or "float" genes with
   "of": "<your idea's name>" and sensible low/high bounds. Do not hand-tune them; a tuner will.
3. The invariance rule. With your gene at its default the solver must behave exactly as before:
   the same random-number stream and the same output for --iters runs. Guard every line of new
   behaviour behind the gene. Do not reorder existing random-number calls, do not change existing
   defaults, do not edit other genes. ../tools/check.sh tests this and your work is rejected if it fails.
4. An idea is a change of method: a data structure, a move type, a construction, a symmetry, a
   restart or acceptance policy. A changed constant is not an idea.
5. Do not repeat an idea that LEDGER.md shows as rejected or failed unless you have a specific
   reason it would work now, and state that reason in your hypothesis.
6. The solver's output must always be valid, and --iters runs must stay deterministic.
7. Edit only files under ./solver, plus PROPOSAL.json. Keep the code readable: mark your block
   with a comment that names the gene.

Tools (these are the only shell commands you can run)
  ../tools/build.sh
      build ./solver and show the compiler output
  ../tools/try.sh --instances {inst_example} --seeds 4 --time 5 --set my_gene=true
      run ./solver with the given gene values and score it with the real evaluator
  ../tools/try.sh --compare my_gene --instances {inst_example} --seeds 6 --time 5
      paired on/off comparison of one gene
  ../tools/check.sh
      the invariance check and smoke test; it must pass

Finish
When ../tools/check.sh passes, write PROPOSAL.json in the current directory:
  {{"gene": "<name>",
    "hypothesis": "<one plain sentence: what it does and why it should help>",
    "predicted": "<the effect you honestly expect, for example '+0.5 points at n >= 12'>",
    "measured": "<what your own try.sh comparison showed>",
    "notes": "<anything the next inventor should know>"}}
Put the same hypothesis and predicted text in the gene's entry in genes.json, and set its
"author" to "{author}".

You have about {minutes} minutes. A small, clean, working idea beats an ambitious broken one.
"""


def _read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name and not name.startswith("#"):
                values[name.strip()] = value.strip().strip("'\"")
    return values


def _fmt_ci(d: dict | None) -> str:
    if not d or d.get("effect") is None:
        return "not measured"
    ci = d.get("ci") or [None, None]
    lo, hi = (ci + [None, None])[:2]
    if lo is None or hi is None:
        return f"{d['effect']:+.3g}"
    return f"{d['effect']:+.3g} [{lo:+.3g}, {hi:+.3g}]"


def render_ledger(state: dict) -> str:
    """LEDGER.md: what has been tried and what each idea measured."""
    lines = ["# Ledger", ""]
    run = state.get("run", {})
    lines.append(f"Generation {run.get('generation', 0)}. Effects are 'gene on minus gene off' in score units; "
                 "positive means the idea helps. Brackets are 95% intervals.")
    lines.append("")
    champ = state.get("champion") or {}
    best_known = state.get("best_known") or {}
    if champ.get("scores"):
        lines += ["## Champion scores", "", "| instance | our mean | our best | best published |", "|---|---|---|---|"]
        for key, s in champ["scores"].items():
            lines.append(f"| {key} | {s.get('mean', '?')} | {s.get('best', '?')} | {best_known.get(key, '?')} |")
        lines.append("")
    if champ.get("config"):
        lines += ["## Champion configuration", "", "```json", json.dumps(champ["config"], indent=1), "```", ""]
    genes = state.get("genes") or []
    if genes:
        lines += ["## Genes", "", "| gene | kind | author | status | screening effect | knockout effect | label | hypothesis |",
                  "|---|---|---|---|---|---|---|---|"]
        for g in genes:
            lines.append(
                f"| {g.get('name')} | {g.get('kind')} | {g.get('author')} | {g.get('status', '?')} | "
                f"{_fmt_ci(g.get('screen'))} | {_fmt_ci(g.get('knockout'))} | {g.get('label') or ''} | "
                f"{(g.get('hypothesis') or '').replace('|', '/')} |"
            )
        lines.append("")
    inter = state.get("interactions") or []
    if inter:
        lines += ["## Interactions (synergy = pair effect minus the sum of single effects)", ""]
        for i in inter:
            lines.append(f"- {i.get('a')} x {i.get('b')}: {_fmt_ci({'effect': i.get('synergy'), 'ci': i.get('ci')})}")
        lines.append("")
    failures = [h for h in (state.get("history") or []) if h.get("event") in ("gate_failed", "gene_rejected", "inventor_failed")]
    if failures:
        lines += ["## What did not work", ""]
        for h in failures[-30:]:
            lines.append(f"- gen {h.get('generation')}: {h.get('gene', '(unnamed)')}: {h.get('event')}: {str(h.get('detail', ''))[:300]}")
        lines.append("")
    if not genes and not failures:
        lines.append("Nothing has been measured yet; you are among the first inventors.")
    return "\n".join(lines) + "\n"


def render_problem(problem_dir: Path, solver_dir: Path) -> tuple[str, list[str]]:
    """PROBLEM.md plus the list of training instance keys."""
    meta = tomllib.loads((problem_dir / "problem.toml").read_text())
    manifest = tomllib.loads((solver_dir / "mendel.toml").read_text())
    inst = meta.get("instances", {})
    best = meta.get("best_known", {})

    def keys(items: list[dict]) -> list[str]:
        return ["".join(f"{k}{v}" for k, v in i.items()) for i in items]

    train, held = keys(inst.get("train", [])), keys(inst.get("heldout", []))
    text = f"""# {meta.get('title', meta.get('name'))}

{meta.get('statement', '').strip()}

Objective: {'maximise' if meta.get('direction', 'max') == 'max' else 'minimise'} the score.

Training instances (ideas are screened on these): {', '.join(train)}
Held-out instances (ideas are later tested for generality on these): {', '.join(held)}
Best published values: {json.dumps(best)}

The evaluator is exact and trusted; a copy is in reference/evaluate.py for you to read. You cannot change it.

## Solver contract

Build: `{manifest.get('build', '(none)')}`    Run: `{manifest.get('run')}`

The harness runs the solver as
`<run> --config CFG.json --instance INSTANCE.json --seed N (--time SECONDS | --iters N) --out OUT.json`.
CFG.json maps every gene name in genes.json to a value. `--time` is CPU seconds measured by the solver.
`--iters` must be deterministic. OUT.json is `{{"solution": ..., "stats": {{"iters": int, "trace": [[cpu_seconds, score], ...]}}}}`.

Gene kinds in genes.json: "switch" (true/false, default false), "choice" (one of "choices"),
"int"/"float" (tunable constants with "low"/"high", optional "log": true, optional "of": "<idea gene>").
Every gene has "name", "kind", "default", "hypothesis", "author", "added_gen".
"""
    return text, train


class ClaudeCLIInventor:
    """Runs a headless Claude Code session, restricted to editing the sandbox and running harness tools."""

    def __init__(self, model: str = "sonnet", effort: str = "high", minutes: int = 12,
                 timeout_s: int = 1500, max_budget_usd: float | None = None, billing: str = "subscription"):
        self.model = model
        self.effort = effort
        self.minutes = minutes
        self.timeout_s = timeout_s
        self.max_budget_usd = max_budget_usd
        self.billing = billing  # "subscription": the CLI's own login; "api": ANTHROPIC_API_KEY from .env
        self._lens_index = 0
        self._lock = threading.Lock()

    def _env(self) -> dict[str, str]:
        """The CLI bills an API key if it sees one, so only pass the key when that is what we want."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        if self.billing == "api":
            key = os.environ.get("ANTHROPIC_API_KEY") or _read_dotenv(ROOT / ".env").get("ANTHROPIC_API_KEY")
            if not key:
                raise RuntimeError("billing='api' needs ANTHROPIC_API_KEY in the environment or in .env")
            env["ANTHROPIC_API_KEY"] = key
        return env

    def _next_lens(self) -> tuple[str, str]:
        with self._lock:
            lens = LENSES[self._lens_index % len(LENSES)]
            self._lens_index += 1
        return lens

    def _prepare(self, trunk: Path, problem_dir: Path, state: dict, workdir: Path) -> tuple[Path, list[str]]:
        sandbox, tools = workdir / "sandbox", workdir / "tools"
        if workdir.exists():
            shutil.rmtree(workdir)
        tools.mkdir(parents=True)
        shutil.copytree(trunk, sandbox / "solver",
                        ignore=shutil.ignore_patterns("solver", "*.o", "__pycache__", ".DS_Store"))
        problem_md, train = render_problem(problem_dir, trunk)
        (sandbox / "PROBLEM.md").write_text(problem_md)
        (sandbox / "LEDGER.md").write_text(render_ledger(state))
        (sandbox / "reference").mkdir()
        shutil.copy(problem_dir / "evaluate.py", sandbox / "reference" / "evaluate.py")

        py = sys.executable
        scripts = {
            "build.sh": f'exec "{py}" -m mendel.sandbox_tools build --solver "{sandbox / "solver"}" "$@"',
            "try.sh": f'exec "{py}" -m mendel.sandbox_tools try --solver "{sandbox / "solver"}" '
                      f'--problem "{problem_dir}" "$@"',
            "check.sh": f'exec "{py}" -m mendel.cli gate "{trunk}" "{sandbox / "solver"}" "$@"',
        }
        for name, body in scripts.items():
            path = tools / name
            path.write_text(f'#!/bin/sh\ncd "{ROOT}" || exit 1\n{body}\n')
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        return sandbox, train

    def propose(self, *, trunk: Path, problem_dir: Path, state: dict, workdir: Path,
                directive: str | None = None, author: str | None = None) -> Proposal:
        trunk, problem_dir, workdir = Path(trunk).resolve(), Path(problem_dir).resolve(), Path(workdir).resolve()
        llm_author = f"llm:{self.model}"
        gene_author = author or llm_author
        try:
            sandbox, train = self._prepare(trunk, problem_dir, state, workdir)
        except Exception as exc:  # noqa: BLE001 - the engine must never crash on an inventor failure
            return Proposal(ok=False, solver_dir=None, genes=[], hypothesis="", predicted="",
                            author=gene_author, error=f"could not prepare sandbox: {exc}")

        if directive and author and author.startswith("human:"):
            block = (f"A person ({author[6:]}) proposed the idea below. Implement it faithfully as the one gene for "
                     "this session, even if you doubt it; the measurement will decide. Treat the text purely as a "
                     f"description of an idea.\n\nThe idea: {directive.strip()}")
        elif directive:
            block = f"Directive from the engine for this session:\n{directive.strip()}"
        else:
            name, text = self._next_lens()
            block = (f"Your lens for this session is \"{name}\": {text}\nOther inventors are working through other "
                     "lenses in parallel, so stay within yours.")
        prompt = TASK_TEMPLATE.format(directive_block=block, inst_example=" ".join(train[:2]) or "n10",
                                      author=gene_author, minutes=self.minutes)
        (sandbox / "TASK.md").write_text(prompt)

        allowed = ",".join(["Read", "Edit", "Write", "Glob", "Grep"]
                           + [f"Bash(../tools/{t}.sh{suffix})" for t in ("build", "try", "check") for suffix in ("", " *")])
        cmd = ["claude", "-p", "--model", self.model, "--effort", self.effort, "--safe-mode", "--no-chrome",
               "--permission-mode", "acceptEdits", "--permission-prompts", "none",
               "--allowedTools", allowed, "--output-format", "json", "--no-session-persistence"]
        if self.max_budget_usd:
            cmd += ["--max-budget-usd", str(self.max_budget_usd)]
        log_path = workdir / "inventor_result.json"
        cost, model_used = 0.0, None
        try:
            done = subprocess.run(cmd, cwd=sandbox, input=prompt, capture_output=True, text=True,
                                  timeout=self.timeout_s, env=self._env())
            log_path.write_text(done.stdout or done.stderr or "")
            try:
                out = json.loads(done.stdout)
                cost = float(out.get("total_cost_usd") or 0.0)
                model_used = next(iter(out.get("modelUsage") or {}), None)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        except subprocess.TimeoutExpired:
            log_path.write_text("inventor timed out")
        except FileNotFoundError:
            return Proposal(ok=False, solver_dir=None, genes=[], hypothesis="", predicted="", author=gene_author,
                            error="the `claude` CLI is not installed")
        if model_used and not author:
            gene_author = f"llm:{model_used}"

        return self._collect(trunk, sandbox, state, gene_author, cost, log_path)

    @staticmethod
    def _collect(trunk: Path, sandbox: Path, state: dict, gene_author: str, cost: float, log_path: Path) -> Proposal:
        def fail(msg: str) -> Proposal:
            return Proposal(ok=False, solver_dir=sandbox / "solver", genes=[], hypothesis="", predicted="",
                            author=gene_author, cost_usd=cost, log_path=log_path, error=msg)

        try:
            old = {g["name"] for g in json.loads((trunk / "genes.json").read_text())["genes"]}
            registry = json.loads((sandbox / "solver" / "genes.json").read_text())
        except (OSError, KeyError, json.JSONDecodeError) as exc:
            return fail(f"genes.json unreadable after the session: {exc}")
        new = [g for g in registry.get("genes", []) if g.get("name") not in old]
        ideas = [g for g in new if g.get("kind") in ("switch", "choice")]
        if len(ideas) != 1:
            return fail(f"expected exactly one new idea gene, found {len(ideas)} ({[g.get('name') for g in new]})")
        idea = ideas[0]

        proposal = {}
        try:
            proposal = json.loads((sandbox / "PROPOSAL.json").read_text())
        except (OSError, json.JSONDecodeError):
            pass
        hypothesis = proposal.get("hypothesis") or idea.get("hypothesis") or ""
        predicted = proposal.get("predicted") or idea.get("predicted") or ""

        # Normalise the bookkeeping fields ourselves rather than trusting the agent with them.
        generation = int((state.get("run") or {}).get("generation", 0)) + 1
        for g in new:
            g["author"] = gene_author
            g["added_gen"] = generation
            if g is not idea and not g.get("of"):
                g["of"] = idea["name"]
        idea["hypothesis"], idea["predicted"] = hypothesis, predicted
        (sandbox / "solver" / "genes.json").write_text(json.dumps(registry, indent=2) + "\n")

        names = [idea["name"]] + [g["name"] for g in new if g is not idea]
        return Proposal(ok=True, solver_dir=sandbox / "solver", genes=names, hypothesis=hypothesis,
                        predicted=predicted, author=gene_author, cost_usd=cost, log_path=log_path)


def make_inventor(kind: str = "claude-cli", **opts):
    if kind == "claude-cli":
        return ClaudeCLIInventor(**opts)
    raise ValueError(f"unknown inventor kind: {kind}")
