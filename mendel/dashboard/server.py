"""Mendel dashboard server.

Standard library only. Serves the single-page dashboard and a small JSON API over
the run-state files the engine writes (PROTOCOL.md, section 3).

    uv run python -m mendel.dashboard.server             # real runs in ./runs
    uv run python -m mendel.dashboard.server --mock      # demo data, no engine needed

Endpoints
    GET  /                    index.html
    GET  /api/runs            run ids, newest first
    GET  /api/state?run=ID    that run's state.json
    GET  /api/live?run=ID     result of the most recent live knockout, or {}
    GET  /api/ideas?run=ID    ideas queued through the idea box
    POST /api/idea            {"run", "text", "author"} -> appended to ideas.jsonl
    POST /api/knockout        {"run", "gene"} -> starts `mendel knockout ... --quick`

Run ids and gene names are only ever looked up in what exists on disk (a directory
listing, the genes in state.json). No file path is built from request input.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

HERE = Path(__file__).resolve().parent
INDEX_HTML = HERE / "index.html"
MOCK_STATE = HERE / "mock_state.json"
MOCK_RUN = "demo"

SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,127}$")
MAX_BODY = 64 * 1024
MAX_IDEA_CHARS = 2000
MAX_AUTHOR_CHARS = 80
MAX_IDEAS_RETURNED = 500


class ApiError(Exception):
    """An error that maps to an HTTP status and a JSON {"error": ...} body."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_text(value, limit: int) -> str:
    """Printable, single-spaced text, cut to `limit` characters."""
    if not isinstance(value, str):
        return ""
    value = "".join(ch if ch.isprintable() else " " for ch in value)
    return " ".join(value.split())[:limit]


def _bootstrap_ci(diffs: list[float], rng: random.Random, resamples: int = 400) -> list[float]:
    """95% bootstrap interval for the mean of paired differences."""
    n = len(diffs)
    if n == 0:
        return [0.0, 0.0]
    means = sorted(sum(rng.choice(diffs) for _ in range(n)) / n for _ in range(resamples))
    return [round(means[int(0.025 * resamples)], 3), round(means[int(0.975 * resamples) - 1], 3)]


class Dashboard:
    """Everything the HTTP handler needs: run lookup, state, live knockouts, ideas."""

    def __init__(self, runs_dir: str = "runs", mock: bool = False):
        self.runs_dir = Path(runs_dir)
        self.mock = bool(mock)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}      # run id -> the knockout process we started
        self._mock_live: dict = {}            # mock mode: the faked live.json
        self._mock_busy = False
        self._mock_ideas: list[dict] = []

    # ------------------------------------------------------------------ runs

    def _scan(self) -> dict[str, Path]:
        """Run id -> directory, for every subdirectory of runs_dir that holds a state.json.

        Ordered newest first (by when state.json was last written). The paths come
        from the directory listing, never from request input.
        """
        found: list[tuple[float, str, Path]] = []
        try:
            with os.scandir(self.runs_dir) as entries:
                for entry in entries:
                    if not SAFE_NAME.match(entry.name):
                        continue
                    try:
                        if not entry.is_dir():
                            continue
                        mtime = os.stat(os.path.join(entry.path, "state.json")).st_mtime
                    except OSError:
                        continue
                    found.append((mtime, entry.name, Path(entry.path)))
        except OSError:
            pass
        found.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return {name: path for _, name, path in found}

    def run_ids(self) -> list[str]:
        ids = list(self._scan())
        if self.mock:
            ids = [MOCK_RUN] + [run_id for run_id in ids if run_id != MOCK_RUN]
        return ids

    def _run_dir(self, run_id) -> Path | None:
        """The directory of an existing run; None for the mock run. Raises ApiError otherwise."""
        if not isinstance(run_id, str) or not SAFE_NAME.match(run_id):
            raise ApiError(400, "missing or malformed run id")
        if self.mock and run_id == MOCK_RUN:
            return None
        path = self._scan().get(run_id)
        if path is None:
            raise ApiError(404, f"unknown run: {run_id}")
        return path

    # ----------------------------------------------------------------- state

    def state_bytes(self, run_id) -> bytes:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            return json.dumps(self._mock_state()).encode("utf-8")
        try:
            return (run_dir / "state.json").read_bytes()
        except OSError:
            raise ApiError(404, "state.json is not readable") from None

    def _mock_state(self) -> dict:
        try:
            state = json.loads(MOCK_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ApiError(500, "mock_state.json is missing or invalid") from None
        run = state.get("run") if isinstance(state, dict) else None
        if isinstance(run, dict):
            run["id"] = MOCK_RUN
            run["updated"] = _now_iso()   # the demo run looks alive
        return state

    def _genes(self, run_dir: Path | None) -> dict[str, dict]:
        """Gene name -> gene record, read from the run's state."""
        try:
            state = self._mock_state() if run_dir is None else json.loads(
                (run_dir / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ApiError(503, "state.json is not readable yet") from None
        genes = state.get("genes") if isinstance(state, dict) else None
        out: dict[str, dict] = {}
        for gene in genes if isinstance(genes, list) else []:
            if isinstance(gene, dict) and isinstance(gene.get("name"), str):
                out[gene["name"]] = gene
        return out

    # ------------------------------------------------------------------ live

    def live(self, run_id) -> dict:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            with self._lock:
                return json.loads(json.dumps(self._mock_live))

        data: dict = {}
        mtime = None
        try:
            path = run_dir / "live.json"
            mtime = path.stat().st_mtime
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            pass

        with self._lock:
            job = self._jobs.get(run_id)
        if job is None:
            return data

        # We started a knockout for this run: report on it even before (or without)
        # the engine writing live.json, so the page never waits on a dead process.
        code = job["proc"].poll()
        fresh = (mtime is not None and mtime >= job["started"] - 1.0
                 and data.get("gene") == job["gene"])
        if code is None:
            return data if fresh else {
                "gene": job["gene"], "status": "running", "pairs": [], "t": job["t"]}
        if fresh and data.get("status") in ("done", "error"):
            return data
        return {
            "gene": job["gene"], "status": "error", "t": job["t"],
            "error": f"the knockout command exited with code {code} without a result",
            "detail": self._log_tail(job.get("log")),
        }

    @staticmethod
    def _log_tail(path: Path | None, limit: int = 600) -> str:
        if path is None:
            return ""
        try:
            with open(path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - limit))
                return fh.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""

    # -------------------------------------------------------------- knockout

    def start_knockout(self, run_id, gene) -> dict:
        run_dir = self._run_dir(run_id)
        if not isinstance(gene, str) or not SAFE_NAME.match(gene):
            raise ApiError(400, "missing or malformed gene name")
        genes = self._genes(run_dir)
        if gene not in genes:
            raise ApiError(404, f"unknown gene: {gene}")

        if run_dir is None:
            return self._start_mock_knockout(gene, genes[gene])

        with self._lock:
            job = self._jobs.get(run_id)
            if job is not None and job["proc"].poll() is None:
                raise ApiError(409, f"a knockout of {job['gene']} is still running")
            # Both values were checked against what exists; passed as a list, no shell.
            cmd = [sys.executable, "-m", "mendel.cli", "knockout",
                   "--run", run_id, "--gene", gene, "--quick"]
            if self.runs_dir != Path("runs"):
                # Not the CLI's default: tell it where this server's runs live (set at start-up).
                cmd += ["--runs", str(self.runs_dir)]
            log_path = run_dir / "knockout.log"
            try:
                log = open(log_path, "ab")
            except OSError:
                log, log_path = None, None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=log if log is not None else subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as exc:
                raise ApiError(500, f"could not start the knockout: {exc}") from None
            finally:
                if log is not None:
                    log.close()
            self._jobs[run_id] = {"gene": gene, "proc": proc, "started": time.time(),
                                  "t": _now_iso(), "log": log_path}
        return {"ok": True, "run": run_id, "gene": gene, "status": "running"}

    def _start_mock_knockout(self, gene: str, record: dict) -> dict:
        with self._lock:
            if self._mock_busy:
                raise ApiError(409, f"a knockout of {self._mock_live.get('gene')} is still running")
            self._mock_busy = True
            self._mock_live = {"run": MOCK_RUN, "gene": gene, "status": "running", "was_on": True,
                               "effect": 0.0, "ci": [0.0, 0.0], "runs": 0, "pairs": [],
                               "started": _now_iso(), "t": _now_iso()}
        threading.Thread(target=self._mock_knockout, args=(gene, record), daemon=True).start()
        return {"ok": True, "run": MOCK_RUN, "gene": gene, "status": "running"}

    def _mock_knockout(self, gene: str, record: dict) -> None:
        """Fake a quick knockout in the shape `mendel knockout` writes to live.json.

        One seed at a time, every training instance, scattered around the gene's known effect.
        """
        try:
            state = self._mock_state()
            train = (state.get("instances") or {}).get("train") or []
            keys = [k for k in train if isinstance(k, str)] or ["train"]
            scores = (state.get("champion") or {}).get("scores") or {}
            direction = (state.get("run") or {}).get("direction") or "max"
            sign = -1.0 if direction == "min" else 1.0
            measured = record.get("knockout") or record.get("screen") or {}
            target = measured.get("effect") if isinstance(measured, dict) else None
            target = float(target) if isinstance(target, (int, float)) else 0.5
            rng = random.Random(f"{gene}-{time.time()}")
            n_seeds = 6
            base = rng.randrange(1000, 1_000_000)
            cells: dict[tuple[str, int], tuple[float, float]] = {}
            started = self._mock_live.get("started", _now_iso())
            for i in range(n_seeds):
                time.sleep(0.45)
                for key in keys:
                    mean = (scores.get(key) or {}).get("mean")
                    mean = float(mean) if isinstance(mean, (int, float)) else 30.0
                    on = float(round(mean + rng.choice([-1, 0, 0, 0, 1])))
                    diff = float(round(rng.gauss(target, 0.85)))      # positive: the idea helped
                    cells[(key, base + i)] = (on, on - sign * diff)
                pairs = [{"instance": key, "seed": base + j, "on": cells[(key, base + j)][0],
                          "off": cells[(key, base + j)][1],
                          "diff": sign * (cells[(key, base + j)][0] - cells[(key, base + j)][1])}
                         for key in keys for j in range(i + 1)]
                diffs = [p["diff"] for p in pairs]
                with self._lock:
                    self._mock_live = {
                        "run": MOCK_RUN, "gene": gene,
                        "status": "running" if i + 1 < n_seeds else "done", "was_on": True,
                        "effect": round(sum(diffs) / len(diffs), 4),
                        "ci": _bootstrap_ci(diffs, rng),
                        "runs": 2 * len(pairs), "total_runs": 2 * len(keys) * n_seeds,
                        "pairs": pairs, "budget": "time=1", "direction": direction,
                        "started": started, "t": _now_iso(), "dropped": 0,
                    }
        except Exception as exc:  # never leave the page waiting on a dead thread
            with self._lock:
                self._mock_live = {"gene": gene, "status": "error", "t": _now_iso(),
                                   "error": f"mock knockout failed: {exc}"}
        finally:
            with self._lock:
                self._mock_busy = False

    # ----------------------------------------------------------------- ideas

    def add_idea(self, run_id, text, author) -> dict:
        run_dir = self._run_dir(run_id)
        text = _clean_text(text, MAX_IDEA_CHARS)
        if not text:
            raise ApiError(400, "the idea text is empty")
        record = {"text": text,
                  "author": _clean_text(author, MAX_AUTHOR_CHARS) or "anonymous",
                  "t": _now_iso()}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            if run_dir is None:
                # Mock run: keep it in memory, and on disk too so demo ideas are not lost.
                self._mock_ideas.append(record)
                try:
                    target = self.runs_dir / MOCK_RUN
                    target.mkdir(parents=True, exist_ok=True)
                    with open(target / "ideas.jsonl", "a", encoding="utf-8") as fh:
                        fh.write(line)
                except OSError:
                    pass
            else:
                try:
                    with open(run_dir / "ideas.jsonl", "a", encoding="utf-8") as fh:
                        fh.write(line)
                except OSError as exc:
                    raise ApiError(500, f"could not save the idea: {exc}") from None
        return {"ok": True, "queued": record}

    def ideas(self, run_id) -> list[dict]:
        run_dir = self._run_dir(run_id)
        if run_dir is None:
            with self._lock:
                return list(self._mock_ideas[-MAX_IDEAS_RETURNED:])
        # Same reading rules as the engine, so that position N here is the engine's idea N
        # (it reports how many it has taken): a line that is not JSON counts as plain text.
        out: list[dict] = []
        try:
            with open(run_dir / "ideas.jsonl", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        record = json.loads(raw)
                    except ValueError:
                        record = {"text": raw}
                    if isinstance(record, dict) and str(record.get("text") or "").strip():
                        out.append({"text": str(record["text"]),
                                    "author": str(record.get("author") or ""),
                                    "t": record.get("t")})
        except OSError:
            pass
        return out[:MAX_IDEAS_RETURNED]


def _make_handler(app: Dashboard, quiet: bool):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MendelDashboard/0.1"

        def log_message(self, format, *args):  # noqa: A002 - signature of the base class
            if not quiet:
                super().log_message(format, *args)

        # -- responses

        def _send(self, status: int, body: bytes, ctype: str = "application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload):
            self._send(status, json.dumps(payload).encode("utf-8"))

        def _guarded(self, work):
            try:
                work()
            except ApiError as exc:
                self._json(exc.status, {"error": exc.message})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                try:
                    self._json(500, {"error": f"internal error: {type(exc).__name__}"})
                except OSError:
                    pass

        # -- routes

        def do_GET(self):
            url = urlsplit(self.path)
            run = (parse_qs(url.query).get("run") or [None])[0]

            def work():
                if url.path in ("/", "/index.html"):
                    try:
                        page = INDEX_HTML.read_bytes()
                    except OSError:
                        raise ApiError(500, "index.html is missing") from None
                    self._send(200, page, "text/html; charset=utf-8")
                elif url.path == "/api/runs":
                    self._json(200, app.run_ids())
                elif url.path == "/api/state":
                    self._send(200, app.state_bytes(run))
                elif url.path == "/api/live":
                    self._json(200, app.live(run))
                elif url.path == "/api/ideas":
                    self._json(200, app.ideas(run))
                else:
                    raise ApiError(404, "not found")

            self._guarded(work)

        do_HEAD = do_GET

        def _body(self) -> dict:
            # Requiring JSON keeps other web pages from posting here with a plain form.
            if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                raise ApiError(415, "send application/json")
            try:
                length = int(self.headers.get("Content-Length") or "")
            except ValueError:
                raise ApiError(411, "Content-Length is required") from None
            if length < 0 or length > MAX_BODY:
                raise ApiError(413, "request body is too large")
            try:
                body = json.loads(self.rfile.read(length).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                raise ApiError(400, "the request body is not valid JSON") from None
            if not isinstance(body, dict):
                raise ApiError(400, "the request body must be a JSON object")
            return body

        def do_POST(self):
            url = urlsplit(self.path)

            def work():
                if url.path == "/api/idea":
                    body = self._body()
                    self._json(200, app.add_idea(body.get("run"), body.get("text"), body.get("author")))
                elif url.path == "/api/knockout":
                    body = self._body()
                    self._json(200, app.start_knockout(body.get("run"), body.get("gene")))
                else:
                    raise ApiError(404, "not found")

            self._guarded(work)

    return Handler


def serve(runs_dir: str = "runs", port: int = 8765, mock: bool = False,
          host: str = "127.0.0.1", quiet: bool = True) -> None:
    """Serve the dashboard until interrupted.

    runs_dir: directory whose subdirectories hold a state.json each.
    mock:     also serve mock_state.json as a run called "demo", with faked knockouts.
    """
    app = Dashboard(runs_dir, mock=mock)
    httpd = ThreadingHTTPServer((host, port), _make_handler(app, quiet))
    httpd.daemon_threads = True
    source = "demo data (mock)" if mock else f"runs in {Path(runs_dir).resolve()}"
    print(f"Mendel dashboard: http://{host}:{port}/   [{source}]", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="python -m mendel.dashboard.server",
        description="Serve the Mendel dashboard.")
    parser.add_argument("--runs", "--runs-dir", dest="runs_dir", default="runs",
                        help="directory that holds the runs (default: runs)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to bind (default: 127.0.0.1, this machine only)")
    parser.add_argument("--mock", action="store_true",
                        help="serve mock_state.json as a run called 'demo' and fake knockouts")
    parser.add_argument("--verbose", action="store_true", help="log every request")
    args = parser.parse_args(argv)
    serve(args.runs_dir, args.port, mock=args.mock, host=args.host, quiet=not args.verbose)


if __name__ == "__main__":
    main()
