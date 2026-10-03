"""ModalExecutor: the same `run(jobs) -> results` interface as LocalExecutor, fanned out on Modal."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from .modal_app import APP_NAME, LANES

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
                 iters_job_seconds: float = 5.0, overhead_per_job: float = 2.0, deploy: bool = True,
                 function: str | None = None, network_retries: int = 6):
        # The lane: an engine lane by default, overridable per process with MENDEL_MODAL_FUNCTION.
        self.function_name = function or os.environ.get("MENDEL_MODAL_FUNCTION", "run_batch")
        self.parallel = LANES.get(self.function_name, 1)  # jobs a container of this lane runs side by side
        self.network_retries = network_retries
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

    def run(self, jobs: list[dict], journal: Path | None = None, on_batch=None) -> list[dict]:
        if not jobs:
            return []
        import modal

        if self._function is None:
            self._function = modal.Function.from_name(APP_NAME, self.function_name)

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
        # A batch should keep a container busy for about batch_cpu_seconds of wall time: on a lane that
        # runs `parallel` jobs side by side that is `parallel` times as much CPU, and never fewer jobs
        # than cores when the jobs are long.
        batches: list[list[int]] = []
        current: list[int] = []
        current_seconds = 0.0
        longest = 0.0
        last_key = None
        for i in order:
            key = (json.dumps(jobs[i]["instance"], sort_keys=True), jobs[i]["seed"])
            full = current_seconds >= max(self.batch_cpu_seconds, longest) * self.parallel
            if current and full and key != last_key:
                batches.append(current)
                current, current_seconds, longest = [], 0.0, 0.0
            current.append(i)
            seconds = self._job_seconds(jobs[i])
            current_seconds += seconds
            longest = max(longest, seconds)
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

        def landed(k: int, output) -> None:
            if on_batch is not None and isinstance(output, list) and len(output) == len(batches[k]):
                on_batch([jobs[i] for i in batches[k]], output)

        outputs = self._run_payloads(payloads, journal, landed)
        results: list[dict | None] = [None] * len(jobs)
        for batch, output in zip(batches, outputs):
            if isinstance(output, Exception) or not isinstance(output, list) or len(output) != len(batch):
                for i in batch:
                    results[i] = {"ok": False, "valid": False, "score": None, "stats": {}, "wall": 0.0,
                                  "error": f"modal batch failed: {output!r}"[:500], "solution": None}
            else:
                for i, res in zip(batch, output):
                    results[i] = res
        return results  # type: ignore[return-value]

    def _retry(self, what: str, fn):
        """Call fn, retrying on anything that looks like a dropped connection rather than a remote failure."""
        delay = 2.0
        for attempt in range(self.network_retries + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001 - the Modal client surfaces dropped connections in many shapes
                name = type(exc).__name__
                remote = name in ("RemoteError", "FunctionTimeoutError", "ExecutionError", "InputCancellation",
                                  "InvalidError", "NotFoundError", "ExternalFunctionError") or name.endswith("UserCodeException")
                if remote or attempt == self.network_retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 60.0)
        raise RuntimeError(f"unreachable: {what}")

    def _run_payloads(self, payloads: list[dict], journal: Path | None, landed=None) -> list:
        """Submit each batch as its own call and collect the results.

        One call per batch means a dropped connection costs a retry of one fetch, not the whole run, and
        with a journal of call ids a crashed driver process can pick its results up again later.
        """
        import modal

        digest = hashlib.sha256()
        for payload in payloads:
            digest.update(json.dumps(payload["jobs"], sort_keys=True, default=str).encode())
        fingerprint = digest.hexdigest()[:16]

        call_ids: list[str | None] = [None] * len(payloads)
        if journal is not None and journal.exists():
            try:
                saved = json.loads(journal.read_text())
                if saved.get("fingerprint") == fingerprint and len(saved.get("call_ids", [])) == len(payloads):
                    call_ids = saved["call_ids"]
            except (OSError, json.JSONDecodeError):
                pass

        def save() -> None:
            if journal is not None:
                journal.parent.mkdir(parents=True, exist_ok=True)
                tmp = journal.with_suffix(".tmp")
                tmp.write_text(json.dumps({"fingerprint": fingerprint, "function": self.function_name,
                                           "call_ids": call_ids}))
                tmp.replace(journal)

        def spawn(payload: dict):
            try:
                return self._function.spawn(payload)
            except Exception:
                # The handle can go stale (a redeploy, a dropped connection); look the function up again.
                self._function = modal.Function.from_name(APP_NAME, self.function_name)
                raise

        for k, payload in enumerate(payloads):
            if call_ids[k] is None:
                call = self._retry("spawn", lambda payload=payload: spawn(payload))
                call_ids[k] = call.object_id
                if journal is not None and (k % 25 == 0 or k == len(payloads) - 1):
                    save()
        save()

        outputs: list = []
        for k, call_id in enumerate(call_ids):
            try:
                outputs.append(self._retry("get", lambda call_id=call_id: modal.FunctionCall.from_id(call_id).get()))
            except Exception as exc:  # noqa: BLE001 - a failed batch becomes failed results, never a crash
                outputs.append(exc)
            if landed is not None:
                try:
                    landed(k, outputs[-1])
                except Exception:  # noqa: BLE001 - progress reporting must never cost results
                    pass
        return outputs
