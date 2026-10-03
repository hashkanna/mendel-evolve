"""The Modal app that runs batches of solver jobs in containers.

Deploy with `modal deploy -m mendel.backends.modal_app`; `ModalExecutor` does this for you.
Each container gets one core and runs its batch sequentially, so the two arms of a paired
comparison that land in the same batch run on the same hardware.
"""

from __future__ import annotations

import modal

APP_NAME = "mendel-workers"

app = modal.App(APP_NAME)

image = (
    modal.Image.debian_slim(python_version="3.13")
    .apt_install("gcc", "libc6-dev")
    .pip_install("numpy", "scipy")
    .add_local_python_source("mendel")
)


def _run_one(job: dict) -> dict:
    from mendel.worker import run_job

    try:
        return run_job(job)
    except Exception as exc:  # noqa: BLE001 - one bad job must not lose the batch
        return {"ok": False, "valid": False, "score": None, "stats": {}, "wall": 0.0,
                "error": f"worker raised: {exc!r}", "solution": None}


def _execute(payload: dict, parallel: int = 1) -> list[dict]:
    """payload = {"dirs": {ref: {relative path: bytes}}, "jobs": [job with solver_ref / problem_ref]}

    With parallel > 1 the jobs of a batch run side by side, one per reserved core. The plan limits the
    number of containers, not cores, so wide containers are how the same plan does ten times the work.
    """
    import pathlib

    from mendel.worker import run_job

    root = pathlib.Path("/tmp/mendel-dirs")
    for ref, files in payload["dirs"].items():
        target = root / ref
        if target.exists():
            continue
        for rel, content in files.items():
            path = target / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)

    jobs = []
    for job in payload["jobs"]:
        job = dict(job)
        job["solver_dir"] = str(root / job.pop("solver_ref"))
        job["problem_dir"] = str(root / job.pop("problem_ref"))
        jobs.append(job)
    if parallel <= 1 or len(jobs) <= 1:
        return [_run_one(job) for job in jobs]

    import concurrent.futures
    import multiprocessing

    # Build each distinct solver once before fanning out, so the workers do not race to compile it.
    seen = set()
    warm = []
    for job in jobs:
        if job["solver_dir"] not in seen:
            seen.add(job["solver_dir"])
            warm.append(dict(job, budget={"kind": "iters", "value": 1}, timeout=600))
    for job in warm:
        _run_one(job)
    with concurrent.futures.ProcessPoolExecutor(max_workers=parallel,
                                                mp_context=multiprocessing.get_context("fork")) as pool:
        return list(pool.map(_run_one, jobs))


# Lanes. LANES maps a function name to the number of jobs it runs side by side (its reserved cores).
# The one-core lanes are kept for driver processes that started before the wide lanes existed.
LANES = {"run_batch": 1, "run_batch_bg": 1, "run_batch_x8": 8, "run_batch_bg_x16": 16}


@app.function(image=image, cpu=1.0, memory=1024, timeout=3600, max_containers=20)
def run_batch(payload: dict) -> list[dict]:
    return _execute(payload)


@app.function(image=image, cpu=1.0, memory=1024, timeout=3 * 3600, max_containers=10)
def run_batch_bg(payload: dict) -> list[dict]:
    return _execute(payload)


@app.function(image=image, cpu=8.0, memory=8192, timeout=3600, max_containers=45)
def run_batch_x8(payload: dict) -> list[dict]:
    """The engine's lane: short paired experiments, eight at a time per container."""
    return _execute(payload, parallel=8)


@app.function(image=image, cpu=16.0, memory=16384, timeout=3 * 3600, max_containers=25)
def run_batch_bg_x16(payload: dict) -> list[dict]:
    """The campaign lane: long record searches, sixteen at a time per container."""
    return _execute(payload, parallel=16)
