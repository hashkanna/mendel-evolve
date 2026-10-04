"""Narration audio from Gemini text-to-speech.

    python3 media/tts_gemini.py OUT.wav "Text to speak." [--voice Charon] [--style "..."]

Reads GEMINI_API_KEY from the environment, or from a .env file: the one named in media/.key_file (a local,
untracked one-line file holding a path) or the repo's own .env. The key is never printed. Writes 24 kHz mono 16-bit WAV. Retries on rate limits.
The model speaks any instruction it is given, so pass only the words to be spoken. Expect about 0.43 seconds
per word; a clip much longer than that probably contains extra speech.
"""

import argparse
import array
import base64
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
import wave

MODEL = "gemini-3.8-flash-tts"
HERE = os.path.dirname(os.path.abspath(__file__))
STYLE = ""    # this model speaks any instruction aloud, so the text goes in alone; the accent comes from LANGUAGE
LANGUAGE = "en-GB"


def api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    pointer = os.path.join(HERE, ".key_file")
    candidates = [open(pointer).read().strip()] if os.path.exists(pointer) else []
    candidates.append(os.path.join(os.path.dirname(HERE), ".env"))
    for path in candidates:
        if not os.path.exists(path):
            continue
        for line in open(path):
            m = re.match(r"""\s*GEMINI_API_KEY\s*=\s*["']?([^"'\s]+)""", line)
            if m:
                return m.group(1)
    raise SystemExit("no GEMINI_API_KEY found: set it in the environment or name a .env file in media/.key_file")


def synthesise(text: str, voice: str, style: str) -> bytes:
    body = {"contents": [{"parts": [{"text": f"{style}\n\n{text}" if style else text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    if LANGUAGE not in ("", "none"):          # "none" leaves the accent to the voice
        body["generationConfig"]["speechConfig"]["languageCode"] = LANGUAGE
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent",
        data=json.dumps(body).encode(), headers={"x-goog-api-key": api_key(), "Content-Type": "application/json"})
    for attempt in range(6):
        try:
            reply = json.load(urllib.request.urlopen(request, timeout=180))
            parts = reply["candidates"][0]["content"]["parts"]
            return b"".join(base64.b64decode(p["inlineData"]["data"]) for p in parts if "inlineData" in p)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 503) and attempt < 5:
                time.sleep(8 * (attempt + 1))
                continue
            raise SystemExit(f"Gemini TTS failed: HTTP {error.code} {error.read()[:300]!r}")
        except (KeyError, IndexError):
            if attempt < 5:
                time.sleep(4)
                continue
            raise SystemExit(f"Gemini TTS returned no audio: {json.dumps(reply)[:300]}")
    raise SystemExit("Gemini TTS failed after retries")


def trim_tail_burst(pcm: bytes, rate: int = 24000) -> bytes:
    """Gemini 3.8 Flash TTS ends clips with ~0.13 s of near-full-scale noise after the speech has stopped (heard as a
    scratch between scenes on 4 October). Drop it: walk back from the end through anything loud to the silence."""
    a = array.array("h"); a.frombytes(pcm[: len(pcm) // 2 * 2])
    hop = rate // 100

    def level(i: int) -> float:
        seg = a[i:i + hop]
        return 10 * math.log10(sum(v * v for v in seg) / max(1, len(seg)) / 32768 ** 2 + 1e-12)

    n = len(a)
    if n < 3 * hop or level(n - 3 * hop) < -30:
        return pcm
    i, lo = n - hop, max(0, n - int(0.4 * rate))
    while i > lo and level(i) > -50:
        i -= hop
    return a[:i].tobytes() if i > lo else pcm


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("text")
    parser.add_argument("--voice", default="Algieba")   # British with LANGUAGE = en-GB; Sadaltager is a slower alternative
    parser.add_argument("--style", default=STYLE)
    parser.add_argument("--model", default=None)
    parser.add_argument("--language", default=None)
    args = parser.parse_args()
    global MODEL, LANGUAGE
    MODEL = args.model or MODEL
    LANGUAGE = args.language or LANGUAGE
    # the model blends "MendelEvolve" into "Mendeleev"; two words are read correctly
    pcm = trim_tail_burst(synthesise(args.text.replace("MendelEvolve", "Mendel Evolve"), args.voice, args.style))
    with wave.open(args.out, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        out.writeframes(pcm)
    print(f"{args.out}: {len(pcm) / 48000:.1f} s, voice {args.voice}")


if __name__ == "__main__":
    main()
