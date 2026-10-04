"""Narration audio from Gemini text-to-speech.

    python3 media/tts_gemini.py OUT.wav "Text to speak." [--voice Charon] [--style "..."]

Reads GEMINI_API_KEY from the environment, or from a .env file: the one named in media/.key_file (a local,
untracked one-line file holding a path) or the repo's own .env. The key is never printed. Writes 24 kHz mono 16-bit WAV. Retries on rate limits.
The model speaks any instruction it is given, so pass only the words to be spoken. Expect about 0.43 seconds
per word; a clip much longer than that probably contains extra speech.
"""

import argparse
import base64
import json
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
                                 "speechConfig": {"languageCode": LANGUAGE,
                                                  "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("text")
    parser.add_argument("--voice", default="Algieba")   # British with LANGUAGE = en-GB; Sadaltager is a slower alternative
    parser.add_argument("--style", default=STYLE)
    args = parser.parse_args()
    # the model blends "MendelEvolve" into "Mendeleev"; two words are read correctly
    pcm = synthesise(args.text.replace("MendelEvolve", "Mendel Evolve"), args.voice, args.style)
    with wave.open(args.out, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(24000)
        out.writeframes(pcm)
    print(f"{args.out}: {len(pcm) / 48000:.1f} s, voice {args.voice}")


if __name__ == "__main__":
    main()
