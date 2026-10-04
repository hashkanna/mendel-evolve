"""Scene plan for the two MendelEvolve videos.

The narration text is read from narration.md and never retyped here, so the voice and the captions are the
script verbatim. This file only says which picture is on screen for which part of each scene.
"""
import re
from pathlib import Path

MEDIA = Path(__file__).resolve().parent
WORK = MEDIA / "work"

W, H, FPS = 1920, 1080, 30
XFADE = 0.3          # crossfade between shots, seconds
LEAD = 0.5           # black-to-picture time before the first word
SCENE_AIR = 0.8      # from the last word of a scene to the first word of the next (less if the limit needs it)
TAIL = 1.0           # picture after the last word, the last 0.5 s fades to black
TEMPO = 1.0          # speed-up of the voice; 1.0 unless a video cannot fit its limit otherwise

# Where the voice comes from, one clip per scene:
#   "say"    : macOS `say -v Daniel -r 172` (what the delivered videos use)
#   "gemini" : media/tts_gemini.py, voice Algieba. Needs the user's API key and a network call, which the
#              permission system did not allow from the build agent. To switch: set "gemini", run the audio step
#              yourself, then captions and assemble; all timings are re-derived from the new audio.
VOICE_SOURCE = "gemini"
SAY_VOICE, SAY_RATE = "Daniel", 172
GEMINI_VOICE = "Algieba"

# shots: (visual, where it starts). The first shot of a scene starts with the scene. A later shot starts at
# the sentence with that index (int) or right after the given words inside a sentence (str).
# one_line: captions limited to one line because the slide has text low in the frame.
PLAN = {
    "4min": [
        dict(shots=[("slide:cover", 0)], one_line=True),
        dict(shots=[("slide:problem", 0)]),
        dict(shots=[("slide:idea", 0)]),
        dict(shots=[("dash", 0)], click_at="We press knock out.", zoom_at=2),
        dict(shots=[("slide:results", 0)]),
        dict(shots=[("p59:plots-then-table", 0)], scroll_at=1),
        dict(shots=[("slide:twice", 0), ("record:chart-then-table", 4)], scroll_at=6),
        dict(shots=[("slide:statement", 0)]),
        dict(shots=[("slide:limits", 0)]),
        dict(shots=[("slide:use", 0)]),
        dict(shots=[("slide:close", 0)], one_line=True),
    ],
    "2min": [
        dict(shots=[("slide:cover", 0)], one_line=True),
        dict(shots=[("slide:problem", 0)]),
        dict(shots=[("slide:idea", 0)]),
        dict(shots=[("dash", 0)], click_at="We press knock out.", zoom_at=1, zoom_shift=-1.6, hold=1.0),
        dict(shots=[("slide:results", 0), ("p59:plots-then-table", "problem sixty,")], scroll_at=1),
        dict(shots=[("slide:twice", 0), ("slide:statement", "a quarter of a point better,")]),
        dict(shots=[("slide:close", 0)], one_line=True),
    ],
}

LIMITS = {"4min": 235.0, "2min": 118.0}


def read_narration():
    """Return {"4min": [(label, text), ...], "2min": [...]} from narration.md."""
    out, cur = {}, None
    for block in re.split(r"\n(?=## |\d+\. )", (MEDIA / "narration.md").read_text()):
        block = block.strip()
        if block.startswith("## "):
            cur = "4min" if "Four" in block else "2min"
            out[cur] = []
            continue
        m = re.match(r"\d+\.\s+\*\*(.+?)\*\*\s+(.*)", block, re.S)
        if m and cur:
            out[cur].append((m.group(1), " ".join(m.group(2).split())))
    return out


def sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


if __name__ == "__main__":
    for name, scenes in read_narration().items():
        words = sum(len(t.split()) for _, t in scenes)
        print(name, len(scenes), "scenes", words, "words")
        for i, (label, text) in enumerate(scenes, 1):
            print(f"  {i}. [{label}]")
            for s in sentences(text):
                print("      ", s)
