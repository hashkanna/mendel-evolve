"""The run ledger: state.json (PROTOCOL.md section 3), written atomically after every step, plus an
append-only events.jsonl. Tracks spend: LLM calls, dollars, CPU seconds, evaluations.

Two files written by other processes are folded in on every state write, if they exist:
  runs/<id>/records.json   a list of {"instance", "value", "best_known", "verified", "certificate"}
  runs/<id>/compute.json   {"compute": number}, used for decomposition.compute
"""
from __future__ import annotations

import copy
import json
import math
import os
import threading
import time
from datetime import datetime
from pathlib import Path


def now() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def clean(obj):
    """Make obj strictly JSON-serialisable: NaN/inf -> null, Paths -> str, numpy scalars -> Python."""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [clean(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "tolist"):  # numpy scalars and arrays
        return clean(obj.tolist())
    return str(obj)


def write_json_atomic(path, obj) -> None:
    """Temp file plus rename, so a reader never sees a half-written file."""
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    with open(tmp, "w") as f:
        json.dump(clean(obj), f, indent=1, allow_nan=False)
    os.replace(tmp, path)


def read_json(path):
    """A JSON file that another process may be writing: None when it is missing or unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _record_key(record: dict) -> str:
    return json.dumps([record.get("instance"), record.get("value")], default=str)


class Ledger:
    def __init__(self, run_dir, state: dict):
        self.run_dir = Path(run_dir)
        self.state = state
        self.own_records: list[dict] = []   # records the engine found itself; merged with records.json
        self._lock = threading.RLock()
        self._t0 = time.time()

    @classmethod
    def create(cls, run_dir, run_id: str, problem) -> "Ledger":
        run_dir = Path(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        state = {
            "run": {
                "id": run_id,
                "problem": problem.name,
                "title": problem.title,
                "direction": problem.direction,
                "started": now(),
                "updated": now(),
                "status": "running",
                "generation": 0,
                "spend": {"llm_calls": 0, "llm_usd": 0.0, "cpu_seconds": 0.0, "evaluations": 0},
                "problem_dir": str(problem.dir),
            },
            "instances": {split: problem.keys(split) for split in problem.instances},
            "best_known": dict(problem.best_known),
            "champion": {"config": {}, "solver_version": "", "scores": {}, "solutions": {}},
            "genes": [],
            "interactions": [],
            "decomposition": None,
            "records": [],
            "history": [],
            "timeline": [],
        }
        ledger = cls(run_dir, state)
        ledger.save()
        return ledger

    @classmethod
    def load(cls, run_dir) -> "Ledger":
        with open(Path(run_dir) / "state.json") as f:
            return cls(run_dir, json.load(f))

    def elapsed(self) -> float:
        return time.time() - self._t0

    def set_elapsed(self, seconds: float) -> None:
        """Continue the run clock from `seconds` (used when a run is resumed)."""
        self._t0 = time.time() - float(seconds)

    def _merge_external(self) -> None:
        """Fold in records.json and compute.json. Anything missing, half-written or malformed is
        ignored and the previous values stay."""
        path = self.run_dir / "records.json"
        external: list | None = []
        if path.exists():
            data = read_json(path)
            external = None if not isinstance(data, list) else [
                r for r in data if isinstance(r, dict) and "instance" in r and "value" in r]
        if external is None:   # unreadable right now: keep what we had, but never lose our own records
            external = [r for r in self.state.get("records") or [] if isinstance(r, dict)]
        seen = {_record_key(r) for r in external}
        self.state["records"] = external + [r for r in self.own_records if _record_key(r) not in seen]

        compute = read_json(self.run_dir / "compute.json")
        value = compute.get("compute") if isinstance(compute, dict) else None
        if (isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                and isinstance(self.state.get("decomposition"), dict)):
            self.state["decomposition"]["compute"] = value

    def save(self) -> None:
        with self._lock:
            self.state["run"]["updated"] = now()
            self._merge_external()
            write_json_atomic(self.run_dir / "state.json", self.state)

    def snapshot(self) -> dict:
        with self._lock:
            return copy.deepcopy(clean(self.state))

    def event(self, event: str, gene: str | None = None, detail: str = "", **extra) -> None:
        """Append to state.history and events.jsonl (which also keeps the structured extras), then save."""
        with self._lock:
            entry = {"t": now(), "generation": self.state["run"]["generation"], "event": event}
            if gene is not None:
                entry["gene"] = gene
            entry["detail"] = detail
            self.state["history"].append(entry)
            with open(self.run_dir / "events.jsonl", "a") as f:
                f.write(json.dumps(clean({**entry, **extra}), allow_nan=False) + "\n")
            self.save()

    def spend(self, llm_calls: int = 0, llm_usd: float = 0.0, cpu_seconds: float = 0.0,
              evaluations: int = 0) -> None:
        with self._lock:
            s = self.state["run"]["spend"]
            s["llm_calls"] += int(llm_calls)
            s["llm_usd"] = round(s["llm_usd"] + float(llm_usd), 6)
            s["cpu_seconds"] = round(s["cpu_seconds"] + float(cpu_seconds), 3)
            s["evaluations"] += int(evaluations)
            self.save()

    def gene(self, name: str) -> dict | None:
        with self._lock:
            for g in self.state["genes"]:
                if g["name"] == name:
                    return g
        return None

    def upsert_gene(self, name: str, **fields) -> dict:
        """Create or update a gene entry. Does not save; call save() or event() afterwards."""
        with self._lock:
            g = self.gene(name)
            if g is None:
                g = {"name": name}
                self.state["genes"].append(g)
            g.update(fields)
            return g
