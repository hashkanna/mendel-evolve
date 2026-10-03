"""Helpers for the toy fixture: paths, the ground-truth champion, and a way to add a gene to a copy."""
import json
import shutil
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TOY_PROBLEM = FIXTURES / "problems" / "toy"
TOY_SOLVER = FIXTURES / "solvers" / "toy"
HOOK = "    # HOOK"
BUDGET = {"kind": "iters", "value": 200}
ALL_ON = {"boost": True, "noop": True, "left": True, "right": True, "small_trick": True, "step": 0.7}

GOOD = '    if cfg["{name}"]:\n        cap += {gain}'
SNEAKY = "    cap += 1.0  # changes behaviour even while the new gene is off"


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
