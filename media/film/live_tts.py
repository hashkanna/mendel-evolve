"""Narration from a Gemini Live (native audio) model, which sounds more natural than the TTS models.

    uv run --with websockets python media/film/live_tts.py OUT.wav "Text to speak." [--voice Charon] [--model gemini-3.8-live]

The key is read as in media/tts_gemini.py and never printed. Live models converse, so the script is framed as a
read-aloud job; check the take (for example with Whisper) before using it. Writes 24 kHz mono 16-bit WAV.
"""
import argparse
import asyncio
import base64
import json
import sys
import wave
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tts_gemini import api_key  # noqa: E402

URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
TONE = "a warm, clear, confident documentary voice at a calm pace"
SYSTEM = ("You are the narrator of a short science documentary. You will be given one line of the script. Read it "
          "aloud exactly as written, word for word, in {tone}. "
          "Do not add, drop or change any words, and say nothing before or after it.")


async def speak(text: str, voice: str, model: str, tone: str = TONE) -> bytes:
    async with websockets.connect(URL, additional_headers={"x-goog-api-key": api_key()}, max_size=None) as ws:
        await ws.send(json.dumps({"setup": {
            "model": f"models/{model}",
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}},
            "systemInstruction": {"parts": [{"text": SYSTEM.format(tone=tone)}]}}}))
        json.loads(await ws.recv())                       # setupComplete
        await ws.send(json.dumps({"clientContent": {"turns": [{"role": "user", "parts": [{"text": text}]}],
                                                    "turnComplete": True}}))
        pcm = bytearray()
        async for msg in ws:
            m = json.loads(msg)
            sc = m.get("serverContent", {})
            for p in sc.get("modelTurn", {}).get("parts", []):
                if "inlineData" in p:
                    pcm += base64.b64decode(p["inlineData"]["data"])
            if sc.get("turnComplete"):
                break
        return bytes(pcm)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out"); ap.add_argument("text")
    ap.add_argument("--voice", default="Charon"); ap.add_argument("--model", default="gemini-3.8-live")
    ap.add_argument("--tone", default=TONE)
    a = ap.parse_args()
    pcm = asyncio.run(speak(a.text.replace("MendelEvolve", "Mendel Evolve"), a.voice, a.model, a.tone))
    if not pcm:
        raise SystemExit("no audio came back")
    with wave.open(a.out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
    print(f"{a.out}: {len(pcm) / 48000:.1f} s, voice {a.voice}, {a.model}")


if __name__ == "__main__":
    main()
