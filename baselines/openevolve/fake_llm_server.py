#!/usr/bin/env python3
"""A local stand-in for the LLM endpoint, for testing the baseline scripts without spending anything.

    python baselines/openevolve/fake_llm_server.py --port 8791 & STUB=$!
    uv run python baselines/openevolve/run_openevolve.py --iterations 4 --seed 1 \
        --api-base http://127.0.0.1:8791/v1 --out /tmp/oe-stub-run
    kill $STUB

Port 8765 is the Mendel dashboard's: do not use it, and stop the stub by its process id, never by port.

It speaks just enough of the OpenAI chat-completions protocol for OpenEvolve: every request is
answered with OpenEvolve's own initial program, with the radius of the outer ring changed to the
next value in a fixed list, and with a made-up token count. It is not a model and proves nothing
about the baseline's performance; it only exercises the plumbing (run, checkpoints, usage, rescore).
"""

from __future__ import annotations

import argparse
import itertools
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from common import EXAMPLE

OUTER = itertools.cycle([0.45, 0.6, 0.40, 0.48, 0.42, 0.44])
LOCK = threading.Lock()
PROMPT_TOKENS, COMPLETION_TOKENS = 3000, 1500


FAIL_AFTER: int | None = None  # --fail-after N: answer N requests, then refuse the rest with HTTP 429
DELAY = 0.0  # --delay SECONDS: how long each answer takes
SERVED = 0


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - http.server's naming
        global SERVED
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        with LOCK:
            SERVED += 1
            refuse = FAIL_AFTER is not None and SERVED > FAIL_AFTER
            outer = next(OUTER)
        if DELAY:
            time.sleep(DELAY)
        if refuse:
            body = json.dumps({"type": "error", "error": {"type": "rate_limit_error", "message": "stub: refusing"}}).encode()
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        program = (EXAMPLE / "initial_program.py").read_text().replace("0.5 + 0.7 *", f"0.5 + {outer} *")
        body = json.dumps({
            "id": f"chatcmpl-stub-{time.time_ns()}", "object": "chat.completion", "created": int(time.time()),
            "model": request.get("model", "stub"),
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": f"Outer ring at {outer}.\n\n```python\n{program}\n```\n"}}],
            "usage": {"prompt_tokens": PROMPT_TOKENS, "completion_tokens": COMPLETION_TOKENS,
                      "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:  # keep the terminal quiet
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--fail-after", type=int, help="answer this many requests, then refuse with HTTP 429")
    parser.add_argument("--delay", type=float, default=0.0, help="seconds each answer takes")
    args = parser.parse_args()
    FAIL_AFTER, DELAY = args.fail_after, args.delay
    print(f"stub LLM on http://127.0.0.1:{args.port}/v1 (ctrl-c to stop)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
