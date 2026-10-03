"""Helpers for the toy fixture: paths, the ground-truth champion, a way to add a gene to a copy of the
solver, a scripted inventor and an executor wrapper for fault injection."""
import json
import shutil
import threading
from pathlib import Path

from mendel.types import Proposal

FIXTURES = Path(__file__).parent / "fixtures"
TOY_PROBLEM = FIXTURES / "problems" / "toy"
TOY_SOLVER = FIXTURES / "solvers" / "toy"
HOOK = "    # HOOK"
BUDGET = {"kind": "iters", "value": 200}
ALL_ON = {"boost": True, "noop": True, "left": True, "right": True, "small_trick": True, "step": 0.7}

GOOD = '    if cfg["{name}"]:\n        cap += {gain}'
SNEAKY = "    cap += 1.0  # changes behaviour even while the new gene is off"

SPECS = {
    "extra1": GOOD.format(name="extra1", gain=5.0),         # truth: +5
    "doubling": GOOD.format(name="doubling", gain=3.0),     # truth: +3; what the human idea turns into
    "worse": GOOD.format(name="worse", gain=-4.0),          # truth: -4
    "sneaky": SNEAKY,                                       # breaks the invariance rule ...
    "sneaky:fixed": GOOD.format(name="sneaky", gain=2.0),   # ... until the inventor is told why (truth: +2)
    "stubborn": SNEAKY,                                     # breaks it again on the retry
}


def add_gene(src, dst, name: str, code: str, hypothesis: str = "a test gene") -> Path:
    """Copy solver `src` to `dst`, register switch `name` and insert `code` into ceiling()."""
    src, dst = Path(src), Path(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", ".*"))
    registry = json.loads((dst / "genes.json").read_text())
    registry["genes"].append({"name": name, "kind": "switch", "default": False, "hypothesis": hypothesis,
                              "predicted": "unknown", "author": "llm:test", "added_gen": 1})
    (dst / "genes.json").write_text(json.dumps(registry, indent=2))
    text = (dst / "solver.py").read_text()
    assert HOOK in text
    (dst / "solver.py").write_text(text.replace(HOOK, code + "\n" + HOOK))
    return dst


class ScriptedInventor:
    """Stands in for the LLM.

    script: generation -> gene names to propose, in call order. None: the inventor reports failure;
    "explode": it raises. A human idea becomes `human`; a port or a gate retry re-implements the gene
    named in the directive (a retry uses SPECS["<name>:fixed"] when there is one)."""

    def __init__(self, script: dict, specs: dict = SPECS, human: str = "doubling"):
        self.lock = threading.Lock()
        self.script = {g: list(names) for g, names in script.items()}
        self.specs = specs
        self.human = human
        self.calls: list[dict] = []

    def propose(self, *, trunk, problem_dir, state, workdir, directive=None, author=None):
        generation = state["run"]["generation"] + 1   # the state is from the end of the previous generation
        retry = bool(directive) and directive.startswith("Your previous attempt")
        with self.lock:
            self.calls.append({"generation": generation, "directive": directive, "author": author,
                               "workdir": str(workdir)})
            if retry or (directive and directive.startswith("Port an idea")):
                name = directive.split("Idea gene: ")[1].split("\n")[0]
            elif author and author.startswith("human:"):
                name = self.human
            else:
                name = self.script[generation].pop(0)
        if name is None:
            return Proposal(ok=False, solver_dir=None, genes=[], hypothesis="", predicted="",
                            author="llm:scripted", error="scripted failure")
        if name == "explode":
            raise RuntimeError("the inventor exploded")
        code = self.specs.get(name + ":fixed", self.specs[name]) if retry else self.specs[name]
        solver = add_gene(trunk, Path(workdir) / "solver", name, code, hypothesis=f"{name} helps")
        return Proposal(ok=True, solver_dir=solver, genes=[name], hypothesis=f"{name} helps", predicted="+?",
                        author=author or "llm:scripted", cost_usd=0.01)


class Hooked:
    """An executor wrapper: hook(step, generation, jobs) runs before every batch and may raise.
    `step` is the engine's current sub-step. Set .engine after creating the Engine."""

    def __init__(self, inner, hook):
        self.inner = inner
        self.hook = hook
        self.engine = None

    def run(self, jobs):
        engine = self.engine
        self.hook(engine.step, engine.ledger.state["run"]["generation"], jobs)
        return self.inner.run(jobs)
