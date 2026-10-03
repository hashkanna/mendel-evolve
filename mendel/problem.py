"""Problem packs: problem.toml plus the trusted evaluate.py, imported by path."""
from __future__ import annotations

import hashlib
import importlib.util
import math
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Problem:
    dir: Path
    name: str
    title: str
    direction: str                      # "max" or "min"
    statement: str
    instances: dict[str, list[dict]]    # split ("train", "heldout") -> instance tables
    best_known: dict[str, float]        # instance key -> best published value
    evaluator_hash: str
    module: object = field(repr=False, default=None)

    @property
    def sign(self) -> float:
        """+1 for max, -1 for min. sign * score is always 'bigger is better'."""
        return 1.0 if self.direction == "max" else -1.0

    def key(self, instance: dict) -> str:
        return str(self.module.instance_key(instance))

    def keys(self, split: str) -> list[str]:
        return [self.key(i) for i in self.instances.get(split, [])]

    def evaluate(self, instance: dict, solution) -> dict:
        """{"valid": bool, "score": float | None, "detail": ...}. Never raises."""
        try:
            out = self.module.evaluate(instance, solution)
            valid = bool(out.get("valid"))
            score = out.get("score")
            score = float(score) if score is not None else None
            if valid and (score is None or not math.isfinite(score)):
                return {"valid": False, "score": None,
                        "detail": {"reason": f"evaluator returned a non-finite score: {score!r}"}}
            return {"valid": valid, "score": score, "detail": out.get("detail")}
        except Exception as e:  # the evaluator is supposed to never raise; do not trust that
            return {"valid": False, "score": None,
                    "detail": {"reason": f"evaluator raised {type(e).__name__}: {e}"}}

    def normalised(self, key: str, score: float | None) -> float:
        """Score relative to the best known value; 1.0 means 'matches best known'.

        max: score / best known.  min: best known / score.
        A missing score (failed or invalid run) is 0.0. If the instance has no best-known value the
        reference is 1.0, so the result is still monotone in the score."""
        if score is None:
            return 0.0
        ref = float(self.best_known.get(key, 1.0))
        if self.direction == "max":
            return score / ref if ref != 0 else score
        if score > 0:
            return ref / score
        return 1.0 if score == ref else 0.0

    def better(self, a: float, b: float) -> bool:
        """True when score a is strictly better than score b."""
        return self.sign * a > self.sign * b


_CACHE: dict[str, Problem] = {}


def load_problem(problem_dir) -> Problem:
    """Load a problem pack. Cached per process by resolved path."""
    root = Path(problem_dir).resolve()
    cached = _CACHE.get(str(root))
    if cached is not None:
        return cached
    with open(root / "problem.toml", "rb") as f:
        meta = tomllib.load(f)
    direction = meta.get("direction", "max")
    if direction not in ("max", "min"):
        raise ValueError(f"{root / 'problem.toml'}: direction must be 'max' or 'min', got {direction!r}")
    source = (root / "evaluate.py").read_bytes()
    digest = hashlib.sha256(source).hexdigest()[:16]
    module_name = f"mendel_evaluate_{digest}"
    spec = importlib.util.spec_from_file_location(module_name, root / "evaluate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    sys.path.insert(0, str(root))       # lets evaluate.py import helpers that sit beside it
    write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True      # the pack is read-only to us: no __pycache__ in it
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = write_bytecode
        try:
            sys.path.remove(str(root))
        except ValueError:
            pass
    for needed in ("instance_key", "evaluate"):
        if not callable(getattr(module, needed, None)):
            raise ValueError(f"{root / 'evaluate.py'} must define {needed}()")
    instances = {split: [dict(i) for i in items] for split, items in (meta.get("instances") or {}).items()}
    problem = Problem(
        dir=root,
        name=meta.get("name", root.name),
        title=meta.get("title", meta.get("name", root.name)),
        direction=direction,
        statement=meta.get("statement", ""),
        instances=instances,
        best_known={str(k): float(v) for k, v in (meta.get("best_known") or {}).items()},
        evaluator_hash=digest,
        module=module,
    )
    _CACHE[str(root)] = problem
    return problem


def find_problem_dir(solver_dir, explicit=None) -> Path:
    """Resolve a solver's problem pack: an explicit path wins; otherwise the `problem` name in
    mendel.toml is looked up under ./problems/ and under <solver_dir>/../../problems/."""
    if explicit:
        path = Path(explicit)
        if not (path / "problem.toml").exists():
            raise FileNotFoundError(f"no problem.toml in {path}")
        return path.resolve()
    from mendel.solver import load_manifest

    name = load_manifest(solver_dir).get("problem")
    if not name:
        raise ValueError(f"{solver_dir}/mendel.toml has no 'problem'; pass --problem")
    candidates = [Path.cwd() / "problems" / name, Path(solver_dir).resolve().parent.parent / "problems" / name]
    for path in candidates:
        if (path / "problem.toml").exists():
            return path.resolve()
    raise FileNotFoundError(f"problem pack {name!r} not found; looked in: " + ", ".join(map(str, candidates)))
