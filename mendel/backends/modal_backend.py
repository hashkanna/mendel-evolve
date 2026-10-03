"""ModalExecutor: the same `run(jobs) -> results` interface as LocalExecutor, fanned out on Modal."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
from pathlib import Path

from .modal_app import APP_NAME

ROOT = Path(__file__).resolve().parent.parent.parent
SKIP_NAMES = {"solver", "__pycache__", ".DS_Store"}
SKIP_SUFFIXES = {".o", ".pyc", ".so", ".dylib"}
MAX_FILE_BYTES = 2_000_000
# Modal list prices (USD): about 0.0000131 per core-second and 0.00000222 per GiB-second.
USD_PER_CONTAINER_SECOND = 0.0000131 + 0.00000222


class BudgetExceeded(RuntimeError):
    pass


def pack_dir(path: Path) -> tuple[str, dict[str, bytes]]:
    """Read a solver or problem directory into memory and name it by a hash of its contents."""
    files: dict[str, bytes] = {}
    for item in sorted(path.rglob("*")):
        if not item.is_file() or item.name in SKIP_NAMES or item.suffix in SKIP_SUFFIXES:
            continue
        if any(part in SKIP_NAMES for part in item.relative_to(path).parts):
            continue
        if item.stat().st_size > MAX_FILE_BYTES:
            continue
        files[str(item.relative_to(path))] = item.read_bytes()
    digest = hashlib.sha256()
    for rel, content in files.items():
        digest.update(rel.encode() + b"\0" + content + b"\0")
    return digest.hexdigest()[:16], files


class ModalExecutor:
    """Runs jobs on Modal in batches of roughly `batch_cpu_seconds` each.

    `max_cpu_hours` is a hard cap on the total budget this executor will submit; it exists so that
    a bug in an overnight loop cannot spend the whole credit.
    """

    def __init__(self, batch_cpu_seconds: float = 120.0, max_cpu_hours: float = 200.0,
                 iters_job_seconds: float = 5.0, overhead_per_job: float = 2.0, deploy: bool = True):
        self.batch_cpu_seconds = batch_cpu_seconds
        self.max_cpu_seconds = max_cpu_hours * 3600.0
        self.iters_job_seconds = iters_job_seconds
        self.overhead_per_job = overhead_per_job
        self.submitted_cpu_seconds = 0.0
        self._lock = threading.Lock()
        self._function = None
        if deploy:
            self.deploy()

    @staticmethod
    def deploy() -> None:
        done = subprocess.run([sys.executable, "-m", "modal", "deploy", "-m", "mendel.backends.modal_app"],
                              cwd=ROOT, capture_output=True, text=True)
        if done.returncode != 0:
            raise RuntimeError(f"modal deploy failed:\n{done.stdout}\n{done.stderr}")

    @property
    def estimated_usd(self) -> float:
        return self.submitted_cpu_seconds * USD_PER_CONTAINER_SECOND

    def _job_seconds(self, job: dict) -> float:
        budget = job["budget"]
        base = float(budget["value"]) if budget["kind"] == "time" else self.iters_job_seconds
        return base + self.overhead_per_job

    def run(self, jobs: list[dict]) -> list[dict]:
        if not jobs:
            return []
        import modal

        if self._function is None:
            self._function = modal.Function.from_name(APP_NAME, "run_batch")

        total = sum(self._job_seconds(j) for j in jobs)
        with self._lock:
            if self.submitted_cpu_seconds + total > self.max_cpu_seconds:
                raise BudgetExceeded(
                    f"this call needs {total / 3600:.1f} core-hours but only "
                    f"{(self.max_cpu_seconds - self.submitted_cpu_seconds) / 3600:.1f} remain under the cap")
            self.submitted_cpu_seconds += total

        dirs: dict[str, dict[str, bytes]] = {}
        refs: dict[str, str] = {}

        def ref_for(path: str) -> str:
            if path not in refs:
                ref, files = pack_dir(Path(path))
                refs[path], dirs[ref] = ref, files
            return refs[path]

        # Keep every arm of the same (instance, seed) together so paired comparisons share hardware.
        order = sorted(range(len(jobs)),
                       key=lambda i: (json.dumps(jobs[i]["instance"], sort_keys=True), jobs[i]["seed"]))
        batches: list[list[int]] = []
        current: list[int] = []
        current_seconds = 0.0
        last_key = None
        for i in order:
            key = (json.dumps(jobs[i]["instance"], sort_keys=True), jobs[i]["seed"])
            if current and current_seconds >= self.batch_cpu_seconds and key != last_key:
                batches.append(current)
                current, current_seconds = [], 0.0
            current.append(i)
            current_seconds += self._job_seconds(jobs[i])
            last_key = key
        if current:
            batches.append(current)

        payloads = []
        for batch in batches:
            batch_jobs, batch_dirs = [], {}
            for i in batch:
                job = {k: v for k, v in jobs[i].items() if k not in ("solver_dir", "problem_dir")}
                job["solver_ref"] = ref_for(jobs[i]["solver_dir"])
                job["problem_ref"] = ref_for(jobs[i]["problem_dir"])
                batch_dirs[job["solver_ref"]] = dirs[job["solver_ref"]]
                batch_dirs[job["problem_ref"]] = dirs[job["problem_ref"]]
                batch_jobs.append(job)
            payloads.append({"dirs": batch_dirs, "jobs": batch_jobs})

        results: list[dict | None] = [None] * len(jobs)
        # Materialise the generator: leaving it half-consumed makes Modal's event loop complain at exit.
        outputs = list(self._function.map(payloads, order_outputs=True, return_exceptions=True))
        for batch, output in zip(batches, outputs):
            if isinstance(output, Exception):
                for i in batch:
                    results[i] = {"ok": False, "valid": False, "score": None, "stats": {}, "wall": 0.0,
                                  "error": f"modal batch failed: {output!r}", "solution": None}
            else:
                for i, res in zip(batch, output):
                    results[i] = res
        return results  # type: ignore[return-value]
