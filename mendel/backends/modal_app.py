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


@app.function(image=image, cpu=1.0, memory=1024, timeout=3600, max_containers=100)
def run_batch(payload: dict) -> list[dict]:
    """payload = {"dirs": {ref: {relative path: bytes}}, "jobs": [job with solver_ref / problem_ref]}"""
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

    results = []
    for job in payload["jobs"]:
        job = dict(job)
        job["solver_dir"] = str(root / job.pop("solver_ref"))
        job["problem_dir"] = str(root / job.pop("problem_ref"))
        try:
            results.append(run_job(job))
        except Exception as exc:  # noqa: BLE001 - one bad job must not lose the batch
            results.append({"ok": False, "valid": False, "score": None, "stats": {}, "wall": 0.0,
                            "error": f"worker raised: {exc!r}", "solution": None})
    return results
