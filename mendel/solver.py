"""Solver directories: the manifest, the version hash and the build cache.

A solver version is a hash of its source files (relative path + bytes), so it is identical on macOS
and Linux. Build outputs are ignored: dot-files, object files, compiled binaries (by magic number),
__pycache__ and the like. Each version is built once into <cache>/<version>/.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import tomllib
from contextlib import contextmanager
from pathlib import Path

try:
    import fcntl
except ImportError:  # not POSIX; builds are then only protected by the atomic rename
    fcntl = None

MARKER = ".mendel-built"
BUILD_TIMEOUT = 600.0
IGNORED_DIRS = {"__pycache__", "node_modules", "target", "build", "dist"}
IGNORED_SUFFIXES = {".o", ".a", ".so", ".dylib", ".pyc", ".pyo", ".obj", ".exe", ".class"}
IGNORED_NAMES = {"a.out"}
# ELF, Mach-O (64/32 bit, both byte orders), Mach-O fat, ar archive
BINARY_MAGIC = (b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe", b"!<ar")


class BuildError(RuntimeError):
    """The solver's build command failed."""


def _ignored_dir(name: str) -> bool:
    return name.startswith(".") or name in IGNORED_DIRS or name.endswith(".dSYM")


def _ignored_file(path: Path) -> bool:
    name = path.name
    if name.startswith(".") or name in IGNORED_NAMES or path.suffix in IGNORED_SUFFIXES:
        return True
    try:
        with open(path, "rb") as f:
            return f.read(4) in BINARY_MAGIC
    except OSError:
        return True


def source_files(solver_dir) -> list[Path]:
    """Relative paths of the files that define a solver version, in a stable order."""
    root = Path(solver_dir)
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _ignored_dir(d)]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_file() and not _ignored_file(path):
                found.append(path.relative_to(root))
    return sorted(found, key=lambda p: p.as_posix())


def solver_version(solver_dir) -> str:
    root = Path(solver_dir)
    files = source_files(root)
    if not files:
        raise FileNotFoundError(f"no solver sources found in {root}")
    h = hashlib.sha256()
    for rel in files:
        data = (root / rel).read_bytes()
        h.update(rel.as_posix().encode())
        h.update(b"\0")
        h.update(str(len(data)).encode())
        h.update(b"\0")
        h.update(data)
    return h.hexdigest()[:16]


def load_manifest(solver_dir) -> dict:
    """mendel.toml as {"problem": str | None, "build": str | None, "run": str}."""
    path = Path(solver_dir) / "mendel.toml"
    with open(path, "rb") as f:
        meta = tomllib.load(f)
    run = meta.get("run")
    if not isinstance(run, str) or not run.strip():
        raise ValueError(f"{path}: 'run' is required")
    build = meta.get("build")
    return {"problem": meta.get("problem"), "build": build if isinstance(build, str) and build.strip() else None,
            "run": run}


def copy_sources(src, dst) -> Path:
    """Copy a solver's source files (exactly the files that are hashed) into dst."""
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for rel in source_files(src):
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, target)
    return dst


def cache_root() -> Path:
    override = os.environ.get("MENDEL_BUILD_CACHE")
    return Path(override) if override else Path.home() / ".cache" / "mendel" / "builds"


@contextmanager
def _locked(path: Path):
    """Exclusive advisory lock, so only one process builds a given version at a time."""
    if fcntl is None:
        yield
        return
    with open(path, "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX)
        except OSError:
            pass  # e.g. a filesystem without flock; the atomic rename below still keeps builds safe
        try:
            yield
        finally:
            try:
                fcntl.flock(f, fcntl.LOCK_UN)
            except OSError:
                pass


_failed: dict[str, str] = {}  # version -> build error, per process, so a broken build is tried once


def ensure_built(solver_dir) -> Path:
    """Return the build directory for this solver version, building it if needed.

    Safe when several processes ask at once: one builds under a file lock into a temp directory and
    renames it into place; the others wait and then find the finished directory."""
    solver_dir = Path(solver_dir)
    version = solver_version(solver_dir)
    root = cache_root()
    final = root / version
    if (final / MARKER).exists():
        return final
    if version in _failed:
        raise BuildError(_failed[version])
    root.mkdir(parents=True, exist_ok=True)
    with _locked(root / f"{version}.lock"):
        if (final / MARKER).exists():
            return final
        tmp = Path(tempfile.mkdtemp(prefix=f"{version}.tmp.", dir=root))
        try:
            copy_sources(solver_dir, tmp)
            build = load_manifest(tmp)["build"]
            if build:
                try:
                    proc = subprocess.run(build, shell=True, cwd=tmp, capture_output=True, text=True,
                                          timeout=BUILD_TIMEOUT)
                except subprocess.TimeoutExpired:
                    raise BuildError(f"build timed out after {BUILD_TIMEOUT:.0f}s: {build}") from None
                if proc.returncode != 0:
                    output = (proc.stdout + "\n" + proc.stderr).strip()[-2000:]
                    raise BuildError(f"build failed (exit {proc.returncode}): {build}\n{output}")
            (tmp / MARKER).write_text(f"{version} {time.time()}\n")
            if final.exists():  # leftover without a marker: a build that died half way
                shutil.rmtree(final, ignore_errors=True)
            try:
                os.rename(tmp, final)
            except OSError:
                if not (final / MARKER).exists():  # otherwise another process won the race; use theirs
                    raise
        except BuildError as e:
            _failed[version] = str(e)
            raise
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
    return final
