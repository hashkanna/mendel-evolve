"""Generate the film's score with Google's Lyria music model. The key is read as in media/tts_gemini.py and never printed.

    python3 media/film/lyria.py OUT_BASENAME [MODEL]

Writes OUT_BASENAME.<ext> for whatever audio the model returns, and OUT_BASENAME.txt with any text it returns.
"""
import base64
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tts_gemini import api_key  # noqa: E402

PROMPT = """Instrumental film score, no vocals, exactly 3 minutes long, for a short science documentary about an
AI system that discovers algorithms. Modern cinematic electronic: warm analogue synth pads, a soft pulsing
arpeggio, felt piano, low strings, subtle sub bass, gentle percussion. Key of D minor moving to F major. About
100 BPM. Calm and confident, never busy, so a narrator can speak over all of it. No whooshes, no risers made of
noise, no vinyl crackle.

Structure:
0:00 to 0:12 - sparse and mysterious: a low pad and a quiet ticking pulse.
0:12 to 0:31 - slight tension: low strings enter, still restrained.
0:31 to 0:56 - a brighter lift: felt piano and a soft arpeggio, a sense of something new.
0:56 to 1:21 - driving but understated: the pulse and sub bass come in; a gentle swell peaks at 1:04.
1:21 to 1:46 - wide and spacious, a little awe: shimmering pads over the pulse.
1:46 to 2:07 - curious and precise: plucked arpeggio, light percussion.
2:07 to 2:45 - building patiently towards a resolution, the fullest section, peaking at 2:40.
2:45 to 3:00 - resolve to F major and fade out gently to silence by 3:00."""


def main() -> None:
    out = Path(sys.argv[1])
    model = sys.argv[2] if len(sys.argv) > 2 else "lyria-3.5"
    body = {"contents": [{"parts": [{"text": PROMPT}]}]}
    req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                 data=json.dumps(body).encode(),
                                 headers={"x-goog-api-key": api_key(), "Content-Type": "application/json"})
    try:
        reply = json.load(urllib.request.urlopen(req, timeout=600))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code}: {e.read()[:600]!r}")
    parts = reply["candidates"][0]["content"]["parts"]
    texts = []
    for i, p in enumerate(parts):
        if "inlineData" in p:
            mime = p["inlineData"].get("mimeType", "audio/unknown")
            ext = {"audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3",
                   "audio/ogg": "ogg", "audio/flac": "flac", "audio/aac": "aac"}.get(mime.split(";")[0], "bin")
            path = out.with_name(out.name + (f"_{i}" if i else "") + "." + ext)
            path.write_bytes(base64.b64decode(p["inlineData"]["data"]))
            print("audio", mime, path, path.stat().st_size)
        elif "text" in p:
            texts.append(p["text"])
    if texts:
        out.with_suffix(".txt").write_text("\n".join(texts))
        print("text:", " ".join(texts)[:400])
    print("usage:", reply.get("usageMetadata"))


if __name__ == "__main__":
    main()
