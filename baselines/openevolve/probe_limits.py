#!/usr/bin/env python3
"""One tiny request to the endpoint the baseline uses, to read the account's rate limits.

    baselines/openevolve/vendor/venv/bin/python baselines/openevolve/probe_limits.py

PAID, but only just: one claude-haiku-4-5 request with a 5-token answer (about $0.00004). It goes
through the same OpenAI-compatible endpoint and client that OpenEvolve uses and prints the
`anthropic-ratelimit-*` response headers, which say how many requests and tokens per minute the
key may use. Nothing else is printed; the key is read from the environment or .env and never shown.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent


def api_key() -> str:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip().removeprefix("export ")
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.partition("=")[2].strip().strip("\"'")
    raise SystemExit("ANTHROPIC_API_KEY not found in the environment or .env")


def main() -> int:
    import openai

    client = openai.OpenAI(api_key=api_key(), base_url="https://api.anthropic.com/v1", timeout=60, max_retries=0)
    try:
        raw = client.chat.completions.with_raw_response.create(
            model="claude-haiku-4-5", max_tokens=5, temperature=0.7, seed=1,
            messages=[{"role": "system", "content": "Answer with one word."}, {"role": "user", "content": "Say ok."}])
    except openai.APIStatusError as exc:
        print(f"request refused: HTTP {exc.status_code}: {str(exc)[:300]}")
        return 1
    except openai.APIConnectionError as exc:
        print(f"could not connect: {exc}")
        return 1
    headers = {k.lower(): v for k, v in raw.headers.items()}
    for name in sorted(headers):
        if "ratelimit" in name or name in ("retry-after", "request-id"):
            print(f"{name}: {headers[name]}")
    completion = raw.parse()
    usage = completion.usage
    print(f"model: {completion.model} | prompt_tokens: {usage.prompt_tokens} | completion_tokens: {usage.completion_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
