"""The gene registry (genes.json): loading, validation, configs, knockouts and the tunable search space.

Ideas are genes of kind switch or choice. Alleles are genes of kind int or float (tunable constants).
A config is a flat dict gene name -> value with every gene present.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

IDEA_KINDS = ("switch", "choice")
ALLELE_KINDS = ("int", "float")
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GeneError(ValueError):
    """genes.json is missing or invalid."""


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def validate_genes(genes) -> list[str]:
    """Return a list of human-readable problems; empty means the registry is valid."""
    if not isinstance(genes, list):
        return ["'genes' must be a list of gene objects"]
    errors: list[str] = []
    seen: dict[str, dict] = {}
    for i, g in enumerate(genes):
        if not isinstance(g, dict):
            errors.append(f"gene #{i} is not an object")
            continue
        name = g.get("name")
        if not isinstance(name, str) or not _NAME.match(name):
            errors.append(f"gene #{i}: 'name' must be an identifier (letters, digits, underscore), got {name!r}")
            continue
        if name in seen:
            errors.append(f"gene {name!r} is defined twice")
            continue
        seen[name] = g
        kind = g.get("kind")
        if kind not in IDEA_KINDS + ALLELE_KINDS:
            errors.append(f"gene {name!r}: 'kind' must be one of switch, choice, int, float, got {kind!r}")
            continue
        if "default" not in g:
            errors.append(f"gene {name!r}: 'default' is required")
            continue
        default = g["default"]
        if kind == "switch":
            if default is not False:
                errors.append(f"gene {name!r}: a switch's default must be false (off), got {default!r}")
        elif kind == "choice":
            choices = g.get("choices")
            if not isinstance(choices, list) or len(choices) < 2:
                errors.append(f"gene {name!r}: a choice needs a 'choices' list with at least two entries")
            elif default not in choices:
                errors.append(f"gene {name!r}: default {default!r} is not one of its choices {choices!r}")
        else:
            low, high = g.get("low"), g.get("high")
            check = _is_int if kind == "int" else _is_number
            if not (check(low) and check(high) and check(default)):
                errors.append(f"gene {name!r}: 'low', 'high' and 'default' must all be {kind} numbers")
            elif not low <= default <= high:
                errors.append(f"gene {name!r}: default {default!r} is outside low..high ({low!r}..{high!r})")
            elif g.get("log") and low <= 0:
                errors.append(f"gene {name!r}: log scale needs low > 0, got {low!r}")
    for name, g in seen.items():
        of = g.get("of")
        if of is None:
            continue
        if of == name or of not in seen or seen[of].get("kind") not in IDEA_KINDS:
            errors.append(f"gene {name!r}: 'of' must name an idea gene (switch or choice) in this registry, got {of!r}")
    return errors


def parse_genes(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise GeneError(f"genes.json is not valid JSON: {e}") from e
    if not isinstance(data, dict) or "genes" not in data:
        raise GeneError('genes.json must be an object with a "genes" list')
    errors = validate_genes(data["genes"])
    if errors:
        raise GeneError("genes.json is invalid: " + "; ".join(errors))
    return data["genes"]


def load_genes(solver_dir) -> list[dict]:
    """Load and validate <solver_dir>/genes.json. Raises GeneError with every problem listed."""
    path = Path(solver_dir) / "genes.json"
    try:
        text = path.read_text()
    except OSError as e:
        raise GeneError(f"cannot read {path}: {e}") from e
    return parse_genes(text)


def by_name(genes: list[dict]) -> dict[str, dict]:
    return {g["name"]: g for g in genes}


def is_idea(gene: dict) -> bool:
    return gene["kind"] in IDEA_KINDS


def is_allele(gene: dict) -> bool:
    return gene["kind"] in ALLELE_KINDS


def ideas(genes: list[dict]) -> list[dict]:
    return [g for g in genes if is_idea(g)]


def alleles(genes: list[dict]) -> list[dict]:
    return [g for g in genes if is_allele(g)]


def defaults(genes: list[dict]) -> dict:
    return {g["name"]: g["default"] for g in genes}


def complete_config(genes: list[dict], config: dict | None = None) -> dict:
    """Defaults overlaid with the known keys of `config`. Unknown keys are dropped, so a champion
    config can be replayed on an older solver that lacks some genes."""
    out = defaults(genes)
    for name, value in (config or {}).items():
        if name in out:
            out[name] = value
    return out


def validate_config(genes: list[dict], config: dict) -> list[str]:
    errors: list[str] = []
    known = by_name(genes)
    for name in config:
        if name not in known:
            errors.append(f"unknown gene {name!r} in config")
    for name, g in known.items():
        if name not in config:
            errors.append(f"gene {name!r} is missing from the config")
            continue
        value = config[name]
        kind = g["kind"]
        if kind == "switch":
            if not isinstance(value, bool):
                errors.append(f"{name}: a switch must be true or false, got {value!r}")
        elif kind == "choice":
            if value not in g["choices"]:
                errors.append(f"{name}: {value!r} is not one of {g['choices']!r}")
        elif kind == "int":
            if not _is_int(value) or not g["low"] <= value <= g["high"]:
                errors.append(f"{name}: must be an int in {g['low']}..{g['high']}, got {value!r}")
        else:
            if not _is_number(value) or not g["low"] <= value <= g["high"]:
                errors.append(f"{name}: must be a number in {g['low']}..{g['high']}, got {value!r}")
    return errors


def is_on(gene: dict, value) -> bool:
    """An idea is on when it is away from its default (switch true, or a non-baseline choice)."""
    return value != gene["default"]


def on_values(gene: dict) -> list:
    """The values an idea can take when it is on."""
    if gene["kind"] == "switch":
        return [True]
    return [c for c in gene["choices"] if c != gene["default"]]


def active_ideas(genes: list[dict], config: dict) -> list[str]:
    return [g["name"] for g in genes if is_idea(g) and is_on(g, config[g["name"]])]


def knockout(config: dict, gene: dict) -> dict:
    """The config with this idea at its default (off). Its alleles are left alone: they are
    irrelevant while the idea is off."""
    out = dict(config)
    out[gene["name"]] = gene["default"]
    return out


def is_relevant(genes: list[dict], config: dict, gene: dict) -> bool:
    """False for a gene whose `of` idea is off in `config`."""
    of = gene.get("of")
    if of is None:
        return True
    parent = by_name(genes).get(of)
    return parent is None or is_on(parent, config[of])


def search_space(genes: list[dict], config: dict | None = None, alleles_only: bool = False) -> list[dict]:
    """The genes a tuner may vary.

    alleles_only=False: every idea, plus every allele (the tuner samples an allele only when its `of`
    idea is on in the sampled config).
    alleles_only=True: ideas stay as they are in `config`; only the alleles relevant to it are tuned.
    """
    config = complete_config(genes, config)
    space = []
    for g in genes:
        if is_idea(g):
            if not alleles_only:
                space.append(g)
        elif g["low"] < g["high"]:
            if not alleles_only or is_relevant(genes, config, g):
                space.append(g)
    return space
