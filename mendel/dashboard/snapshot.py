"""Save a MendelEvolve run as one self-contained, read-only HTML file.

    uv run python -m mendel.dashboard.snapshot --run ID --out FILE.html
    uv run python -m mendel.dashboard.snapshot --mock --out demo.html
    uv run python -m mendel.dashboard.snapshot --mock --run viewer-shapes --out shapes.html

The file is the live dashboard page (index.html) with the run's state embedded, so it opens
straight from disk or from any static host: no server, no network. The knock-out buttons and
the idea box are switched off in it. `live.json` and the idea queue are included when present.

The state is cleaned before it is embedded, because the file is meant to be published:
engine-internal sections and local directory paths are left out.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from .server import INDEX_HTML, MOCK_RUN, MOCK_RUNS, read_ideas

MARKER = "<!--MENDEL_SNAPSHOT-->"

# What the page reads, by section. Everything else the engine adds stays out of the file.
_STATE_KEYS = ("run", "instances", "best_known", "champion", "genes", "interactions",
               "decomposition", "records", "history", "timeline")
_DROP = {"run": ("problem_dir",), "champion": ("solver_dir",), "genes": ("sandbox",)}


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scrub(value, home: str):
    """Replace this machine's home directory in any string, at any depth; NaN and infinity become null."""
    if isinstance(value, str):
        return value.replace(home, "~") if home and home in value else value
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, list):
        return [_scrub(item, home) for item in value]
    if isinstance(value, dict):
        return {key: _scrub(item, home) for key, item in value.items()}
    return value


def public_state(state: dict) -> dict:
    """The part of a run's state that the page shows, without machine-specific paths."""
    out: dict = {key: state[key] for key in _STATE_KEYS if key in state}
    for section, names in _DROP.items():
        part = out.get(section)
        rows = part if isinstance(part, list) else [part]
        cleaned = [{k: v for k, v in row.items() if k not in names and not k.endswith("_dir")}
                   if isinstance(row, dict) else row for row in rows]
        out[section] = cleaned if isinstance(part, list) else cleaned[0]
    engine = state.get("engine")
    if isinstance(engine, dict) and isinstance(engine.get("ideas_taken"), int):
        out["engine"] = {"ideas_taken": engine["ideas_taken"]}     # tells queued ideas from picked-up ones
    return _scrub(out, str(Path.home()))


def _embed(payload: dict) -> str:
    """A <script> element that sets window.MENDEL_SNAPSHOT; the JSON cannot close it early."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for char, escape in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                         (" ", "\\u2028"), (" ", "\\u2029")):
        text = text.replace(char, escape)
    return "<script>window.MENDEL_SNAPSHOT = " + text + ";</script>"


def render(state: dict, live: dict | None = None, ideas: list | None = None,
           run_id: str | None = None) -> str:
    """The snapshot page as a string, generated from index.html."""
    if not isinstance(state, dict):
        raise ValueError("the run state must be a JSON object")
    run = state.get("run") if isinstance(state.get("run"), dict) else {}
    payload = {
        "run": run_id or run.get("id") or "snapshot",
        "taken": datetime.now().isoformat(timespec="seconds"),
        "state": public_state(state),
        "live": _scrub(live, str(Path.home())) if isinstance(live, dict) else {},
        "ideas": _scrub([i for i in (ideas or []) if isinstance(i, dict)], str(Path.home())),
    }
    page = INDEX_HTML.read_text(encoding="utf-8")
    script = _embed(payload)
    if MARKER in page:
        return page.replace(MARKER, script, 1)
    at = page.find("<script>")                       # fall back to: just before the page's own script
    if at < 0:
        raise ValueError("index.html has no script to attach the snapshot to")
    return page[:at] + script + "\n" + page[at:]


def snapshot(run_dir, out_path) -> Path:
    """Write the run in `run_dir` (the folder that holds state.json) to `out_path` as one HTML file."""
    run_dir = Path(run_dir)
    state = _read_json(run_dir / "state.json")
    if not isinstance(state, dict):
        raise FileNotFoundError(f"no readable state.json in {run_dir}")
    live = _read_json(run_dir / "live.json")
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(state, live, read_ideas(run_dir / "ideas.jsonl"), run_dir.name),
                        encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mendel.dashboard.snapshot",
        description="Save a run as one self-contained, read-only HTML file.")
    parser.add_argument("--run", help="run id (a folder under --runs that holds state.json)")
    parser.add_argument("--runs", default="runs", help="runs directory (default: runs)")
    parser.add_argument("--mock", action="store_true", help="snapshot the demo data instead of a run")
    parser.add_argument("--out", required=True, help="the HTML file to write")
    args = parser.parse_args(argv)

    try:
        if args.mock:
            run_id = args.run or MOCK_RUN                 # --mock alone is the demo; --run picks another mock run
            if run_id not in MOCK_RUNS:
                raise ValueError(f"no mock run called {run_id}; there are: {', '.join(MOCK_RUNS)}")
            state = _read_json(MOCK_RUNS[run_id])
            if not isinstance(state, dict):
                raise FileNotFoundError(f"{MOCK_RUNS[run_id].name} is missing or invalid")
            out = Path(args.out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(render(state, run_id=run_id), encoding="utf-8")
        elif args.run:
            out = snapshot(Path(args.runs) / args.run, args.out)
        else:
            parser.error("give --run ID or --mock")
    except (OSError, ValueError) as exc:
        print(f"snapshot failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out} ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
