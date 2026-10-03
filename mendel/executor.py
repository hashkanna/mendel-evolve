"""Executors: run(jobs) -> results, order-preserving.

LocalExecutor    a process pool on this machine
CachedExecutor   sqlite cache in front of any executor
MeteredExecutor  reports fresh evaluations and CPU seconds to a callback (spend tracking)
"""
from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import sqlite3
import threading
import time
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing

from mendel.problem import load_problem
from mendel.solver import solver_version
from mendel.types import fail_result
from mendel.worker import run_job


class LocalExecutor:
    """Runs jobs in a process pool. workers=0 runs them inline in this process (handy for debugging)."""

    def __init__(self, workers: int | None = None):
        if workers is None:
            workers = max(1, (os.cpu_count() or 2) - 2)
        self.workers = workers
        self._pool: ProcessPoolExecutor | None = None
        self._lock = threading.Lock()

    def _get_pool(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._pool is None:
                # spawn, not fork: the engine has threads, and fork with threads is unsafe
                self._pool = ProcessPoolExecutor(max_workers=self.workers,
                                                 mp_context=multiprocessing.get_context("spawn"))
            return self._pool

    def run(self, jobs: list[dict]) -> list[dict]:
        if not jobs:
            return []
        if self.workers <= 0:
            return [run_job(job) for job in jobs]
        try:
            return list(self._get_pool().map(run_job, jobs))
        except Exception as e:  # a worker process died; start a fresh pool next time
            self.close()
            return [fail_result(f"executor failure: {type(e).__name__}: {e}") for _ in jobs]

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.shutdown(wait=False, cancel_futures=True)
                self._pool = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class MeteredExecutor:
    """Calls on_batch(evaluations, cpu_seconds) after every batch that was actually executed."""

    def __init__(self, inner, on_batch):
        self.inner = inner
        self.on_batch = on_batch

    def run(self, jobs: list[dict]) -> list[dict]:
        results = self.inner.run(jobs)
        if results:
            self.on_batch(len(results), sum(float(r.get("wall") or 0.0) for r in results))
        return results

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close:
            close()


class CachedExecutor:
    """sqlite-backed cache keyed by solver version, problem evaluator hash, config, instance, seed
    and budget. Only successful runs (ok=True) are stored. Identical jobs in one batch run once."""

    def __init__(self, inner, path):
        self.inner = inner
        self.path = str(path)
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        with closing(self._connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS results "
                       "(key TEXT PRIMARY KEY, result TEXT NOT NULL, created REAL NOT NULL)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=60)

    @staticmethod
    def job_key(job: dict, versions: dict | None = None) -> str | None:
        """None when the key cannot be computed (missing solver or problem); such jobs are never cached."""
        versions = versions if versions is not None else {}
        try:
            solver_dir = job["solver_dir"]
            if solver_dir not in versions:
                versions[solver_dir] = solver_version(solver_dir)
            budget = job["budget"]
            value = float(budget["value"]) if budget["kind"] == "time" else int(budget["value"])
            payload = {
                "solver": versions[solver_dir],
                "evaluator": load_problem(job["problem_dir"]).evaluator_hash,
                "config": job["config"],
                "instance": job["instance"],
                "seed": int(job["seed"]),
                "budget": [budget["kind"], value],
            }
            return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        except Exception:
            return None

    def _lookup(self, keys: list[str]) -> dict[str, dict]:
        found: dict[str, dict] = {}
        with closing(self._connect()) as db:
            for i in range(0, len(keys), 500):
                chunk = keys[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for key, text in db.execute(f"SELECT key, result FROM results WHERE key IN ({marks})", chunk):
                    found[key] = json.loads(text)
        return found

    def _store(self, rows: list[tuple[str, dict]]) -> None:
        if not rows:
            return
        now = time.time()
        with closing(self._connect()) as db, db:
            db.executemany("INSERT OR REPLACE INTO results (key, result, created) VALUES (?, ?, ?)",
                           [(key, json.dumps(result), now) for key, result in rows])

    def run(self, jobs: list[dict]) -> list[dict]:
        if not jobs:
            return []
        versions: dict = {}
        keys = [self.job_key(job, versions) for job in jobs]
        with self._lock:
            cached = self._lookup(sorted({k for k in keys if k is not None}))
        todo_jobs: list[dict] = []
        slot_of_key: dict[str, int] = {}
        slots: list[int | None] = []  # per job: index into todo_jobs, or None when served from cache
        for job, key in zip(jobs, keys):
            if key is not None and key in cached:
                slots.append(None)
            elif key is not None and key in slot_of_key:
                slots.append(slot_of_key[key])
            else:
                if key is not None:
                    slot_of_key[key] = len(todo_jobs)
                slots.append(len(todo_jobs))
                todo_jobs.append(job)
        fresh = self.inner.run(todo_jobs) if todo_jobs else []
        with self._lock:
            self.hits += sum(1 for s in slots if s is None)
            self.misses += len(todo_jobs)
            self._store([(key, fresh[slot]) for key, slot in slot_of_key.items() if fresh[slot].get("ok")])
        return [cached[key] if slot is None else fresh[slot] for key, slot in zip(keys, slots)]

    def close(self) -> None:
        close = getattr(self.inner, "close", None)
        if close:
            close()


def make_executor(kind: str = "local", workers: int | None = None, **opts):
    """'local' -> LocalExecutor. 'modal' -> mendel.backends.modal_backend (imported lazily)."""
    if kind == "local":
        return LocalExecutor(workers)
    if kind == "modal":
        from mendel.backends import modal_backend  # provided separately

        for name in ("ModalExecutor", "make_executor"):
            factory = getattr(modal_backend, name, None)
            if factory is not None:
                return factory(**opts)
        raise ImportError("mendel.backends.modal_backend defines neither ModalExecutor nor make_executor")
    raise ValueError(f"unknown executor kind {kind!r} (expected 'local' or 'modal')")
