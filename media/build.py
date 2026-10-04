"""Build the MendelEvolve demo videos. Run from the repo root:

    uv run --with playwright python media/build.py audio      # voice (one clip per scene) and the timeline
    uv run --with playwright python media/build.py stills     # slides and site pages as PNG
    uv run --with playwright python media/build.py knockout 4min   # one real take of the dashboard (presses Knock out once)
    uv run --with playwright python media/build.py knockout 2min
    uv run --with playwright python media/build.py captions   # caption bars as PNG
    uv run --with playwright python media/build.py assemble   # the four mp4 files
    uv run --with playwright python media/build.py frames     # one frame per shot into media/frames/

Everything intermediate goes to media/work/.
"""
import difflib
import hashlib
import json
import re
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scenes import (FPS, GEMINI_VOICE, LEAD, LIMITS, MEDIA, PLAN, SAY_RATE, SAY_VOICE, SCENE_AIR, TAIL, TEMPO,
                    VOICE_SOURCE, WORK, XFADE, read_narration, sentences)

FFMPEG, FFPROBE = "/opt/homebrew/bin/ffmpeg", "/opt/homebrew/bin/ffprobe"
WHISPER = "/opt/homebrew/bin/whisper"
SR = 48000
TTS = WORK / "tts"
SEC_PER_WORD = 0.43   # what the Gemini voice needs; a clip far longer than this probably holds extra speech
LOUDNESS = -17.0      # LUFS, every scene is brought to this


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit("FAILED: " + " ".join(str(c) for c in cmd)[:400] + "\n" + (r.stdout + r.stderr)[-2500:])
    return r


def fr(t):
    """Round a time to a whole frame."""
    return round(t * FPS) / FPS


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def silences(path, noise="-38dB", d=0.1):
    log = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path), "-af", f"silencedetect=noise={noise}:d={d}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    dur = wav_seconds(path)
    return [(max(0.0, s), ends[i] if i < len(ends) else dur) for i, s in enumerate(starts)], dur


# ---------------------------------------------------------------------------------------------- voice
def synth(key, text):
    """One scene's narration as raw audio (cached), from the source named in scenes.VOICE_SOURCE."""
    raw = TTS / f"{key}.raw.wav"
    if raw.exists():
        return raw
    words = len(text.split())
    if VOICE_SOURCE == "say":
        aiff = TTS / f"{key}.aiff"
        run(["say", "-v", SAY_VOICE, "-r", SAY_RATE, "-o", aiff, text])
        run([FFMPEG, "-y", "-i", aiff, "-ar", SR, "-ac", 1, raw])
        aiff.unlink()
        return raw
    for attempt in range(3):
        tmp = TTS / f"{key}.try{attempt}.wav"
        run(["python3", MEDIA / "tts_gemini.py", tmp, text, "--voice", GEMINI_VOICE])
        dur = wav_seconds(tmp)
        if dur <= words * SEC_PER_WORD * 1.35 + 1.5:
            tmp.rename(raw)
            return raw
        print(f"  {key}: {dur:.1f} s for {words} words looks too long, regenerating")
    raise SystemExit(f"{key}: Gemini kept returning over-long audio")


def prepare(key, raw):
    """Trim the silence at both ends, bring to a common loudness, 48 kHz mono. Returns the wav path."""
    out = TTS / f"{key}.wav"
    if out.exists() and out.stat().st_mtime >= raw.stat().st_mtime:
        return out
    sil, dur = silences(raw)
    a = sil[0][1] if sil and sil[0][0] <= 0.01 else 0.0
    b = sil[-1][0] if sil and sil[-1][1] >= dur - 0.01 else dur
    a, b = max(0.0, a - 0.03), min(dur, b + 0.10)
    log = subprocess.run([FFMPEG, "-hide_banner", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(raw), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    loud = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)[-1])
    gain = min(LOUDNESS - loud, -1.0 - peak)
    af = f"volume={gain:.2f}dB" + (f",atempo={TEMPO}" if TEMPO != 1.0 else "")
    run([FFMPEG, "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", raw, "-af", af, "-ar", SR, "-ac", 1, "-c:a", "pcm_s16le", out])
    return out


def norm(word):
    return re.sub(r"[^a-z0-9]", "", word.lower())


def transcribe(wavs):
    """Whisper word timings for every wav that has none yet (local model, nothing is sent anywhere)."""
    todo = [w for w in wavs if not w.with_suffix(".json").exists() or w.with_suffix(".json").stat().st_mtime < w.stat().st_mtime]
    if todo:
        run([WHISPER, *todo, "--model", "small.en", "--language", "en", "--word_timestamps", "True", "--fp16", "False",
             "--output_format", "json", "--output_dir", TTS, "--verbose", "False"])
    out = {}
    for w in wavs:
        j = json.loads(w.with_suffix(".json").read_text())
        out[w] = (j["text"].strip(), [(x["word"], x["start"], x["end"]) for seg in j["segments"] for x in seg.get("words", [])])
    return out


def align(text, heard, sil, dur):
    """Start time of every word of the script inside the scene's audio, from the transcript's word timings."""
    script = [(m.group(0), m.start()) for m in re.finditer(r"\S+", text)]
    a, b = [norm(w) for w, _ in script], [norm(w) for w, _, _ in heard]
    times = [None] * len(script)
    matched = 0
    for blk in difflib.SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(blk.size):
            times[blk.a + k] = heard[blk.b + k][1]
            matched += 1
    anchors = [(-1, 0.0)] + [(i, t) for i, t in enumerate(times) if t is not None] + [(len(script), dur)]
    for (i1, t1), (i2, t2) in zip(anchors, anchors[1:]):     # words written differently (numbers): spread evenly
        for i in range(i1 + 1, i2):
            times[i] = t1 + (t2 - t1) * (i - i1) / (i2 - i1)
    times[0] = 0.0
    return script, times, matched / len(script)


def word_time(script, times, char):
    """Time of the first word starting at or after character `char` of the scene text."""
    for (w, pos), t in zip(script, times):
        if pos >= char:
            return t
    return times[-1]


def chunk_sentence(s, limit):
    """Split a sentence into caption chunks of at most `limit` characters, at clause marks where possible."""
    if len(s) <= limit:
        return [s]
    cuts = [m.end() for m in re.finditer(r"[,:;] ", s)]
    best = None
    for c in cuts:                                   # one cut that balances the halves
        x, y = s[:c].strip(), s[c:].strip()
        if len(x) <= limit and len(y) <= limit:
            score = abs(len(x) - len(y))
            if best is None or score < best[0]:
                best = (score, [x, y])
    if best:
        return best[1]
    if cuts:                                         # cut at the clause mark nearest the middle, then recurse
        c = min(cuts, key=lambda c: abs(c - len(s) / 2))
    else:
        sp = [m.end() for m in re.finditer(r" ", s)]
        c = min(sp, key=lambda c: abs(c - len(s) / 2))
    return chunk_sentence(s[:c].strip(), limit) + chunk_sentence(s[c:].strip(), limit)


def build_audio():
    TTS.mkdir(parents=True, exist_ok=True)
    narr = read_narration()
    jobs = []
    for video, plan in PLAN.items():
        assert len(narr[video]) == len(plan), (video, len(narr[video]), len(plan))
        for si, (label, text) in enumerate(narr[video]):
            src = f"say|{SAY_VOICE}|{SAY_RATE}" if VOICE_SOURCE == "say" else f"gemini|{GEMINI_VOICE}"
            jobs.append((f"{video}_s{si + 1:02d}_" + hashlib.sha1(f"{src}|{text}".encode()).hexdigest()[:8], text))
    with ThreadPoolExecutor(3) as ex:
        raws = list(ex.map(lambda j: synth(*j), jobs))
    wavs = [prepare(key, raw) for (key, _), raw in zip(jobs, raws)]
    heard = transcribe(wavs)
    it = iter(zip(jobs, wavs))
    report = []
    for video, plan in PLAN.items():
        scenes_txt = narr[video]
        n = len(plan)
        voice_total = sum(wav_seconds(w) for (k, _), w in zip(jobs, wavs) if k.startswith(video))
        holds = sum(c.get("hold", 0.0) for c in plan)
        # air between scenes: as planned, or less if the limit needs it
        air = min(SCENE_AIR, (LIMITS[video] - 0.6 - LEAD - TAIL - voice_total - holds) / (n - 1))
        assert air >= 0.4, f"{video}: {voice_total:.1f} s of voice does not fit under {LIMITS[video]} s; raise TEMPO in scenes.py"
        t, scenes, shots, caps, placed = LEAD, [], [], [], []
        for si, ((label, text), cfg) in enumerate(zip(scenes_txt, plan)):
            (key, _), wav = next(it)
            dur = wav_seconds(wav)
            said, words = heard[wav]
            sil, _ = silences(wav)
            script, times, frac = align(text, words, sil, dur)
            report.append((video, si + 1, len(text.split()), dur, frac, said))
            # sentences: start at the script word's time, moved to the end of the pause just before it
            rows, pos = [], 0
            for s in sentences(text):
                c = text.index(s, pos)
                pos = c + len(s)
                u = word_time(script, times, c) if rows else 0.0
                if rows:
                    near = [(e - s0, s0, e) for s0, e in sil if u - 0.5 <= e <= u + 0.3]
                    if near:
                        _, s0, e = max(near)
                        rows[-1]["voice_end"], u = t + s0, e - 0.03
                    else:
                        rows[-1]["voice_end"], u = t + u - 0.08, u - 0.04
                rows.append(dict(text=s, char=c, start=t + u, voice_end=t + dur))
            rows[-1]["voice_end"] = t + dur - 0.08
            placed.append((wav, t))
            hold = cfg.get("hold", 0.0)
            voice_end = rows[-1]["voice_end"]
            scene = dict(index=si + 1, label=label, text=text, start=t, voice_end=voice_end, hold=hold, audio=wav.name,
                         heard=said, matched=round(frac, 3), sentences=rows)
            for k, (visual, at) in enumerate(cfg["shots"]):
                if k == 0:
                    b = None                          # the scene boundary, set below
                elif isinstance(at, int):
                    b = rows[at]["start"] - 0.2
                else:                                 # right after these words: the pause that follows them
                    u = word_time(script, times, text.index(at) + len(at))
                    near = [(abs((s0 + e) / 2 - u), (s0 + e) / 2) for s0, e in sil if u - 0.6 <= e <= u + 0.3]
                    b = t + (min(near)[1] if near else u - 0.1)
                shots.append(dict(scene=si + 1, visual=visual, t0=b, cfg={k2: v for k2, v in cfg.items() if k2 != "shots"}))
            if "click_at" in cfg:
                j = next(j for j, r in enumerate(rows) if r["text"] == cfg["click_at"])
                scene["click"] = rows[j]["start"] + 0.3
                scene["zoom"] = rows[cfg["zoom_at"]]["start"] + cfg.get("zoom_shift", 0.0)
            if "scroll_at" in cfg:
                scene["scroll"] = rows[cfg["scroll_at"]]["start"] - 0.6
            limit = 62 if cfg.get("one_line") else 112
            chunks = []
            for r in rows:
                off = r["char"]
                for i, p in enumerate(chunk_sentence(r["text"], limit)):
                    c = text.index(p, off)
                    off = c + len(p)
                    u = r["start"] if i == 0 else t + word_time(script, times, c) - 0.06
                    chunks.append(dict(text=p, start=u, end=None, lines=1 if cfg.get("one_line") else 2, scene=si + 1))
            for x, y in zip(chunks, chunks[1:]):
                x["end"] = y["start"]                 # contiguous inside a scene
            chunks[-1]["end"] = voice_end + 0.3
            caps += chunks
            scenes.append(scene)
            t = t + dur + hold + air
        total = fr(scenes[-1]["voice_end"] + scenes[-1]["hold"] + TAIL)
        first = {}
        for i, sh in enumerate(shots):
            first.setdefault(sh["scene"], i)
        for sc in scenes:                             # the crossfade sits in the air between two scenes
            prev_end = scenes[sc["index"] - 2]["voice_end"] + scenes[sc["index"] - 2]["hold"] if sc["index"] > 1 else 0.0
            shots[first[sc["index"]]]["t0"] = 0.0 if sc["index"] == 1 else (prev_end + sc["start"]) / 2
        for i, sh in enumerate(shots):
            sh["t0"], sh["index"] = fr(sh["t0"]), i + 1
        for i, sh in enumerate(shots):
            sh["t1"] = shots[i + 1]["t0"] if i + 1 < len(shots) else total
            sh["clip_start"] = 0.0 if i == 0 else fr(sh["t0"] - XFADE / 2)      # half a crossfade past each boundary
            sh["clip_end"] = total if i + 1 == len(shots) else fr(sh["t1"] + XFADE / 2)
        for c in caps:
            c["start"], c["end"] = fr(c["start"]), fr(c["end"])
        pcm = bytearray(int(total * SR) * 2)          # the narration track
        for wav, at in placed:
            with wave.open(str(wav)) as w:
                data = w.readframes(w.getnframes())
            o = int(at * SR) * 2
            assert o + len(data) <= len(pcm), "narration runs past the end of the video"
            pcm[o:o + len(data)] = data
        with wave.open(str(WORK / f"narration_{video}.wav"), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(bytes(pcm))
        (WORK / f"timeline_{video}.json").write_text(json.dumps(dict(video=video, total=total, air=air, scenes=scenes, shots=shots, captions=caps), indent=1))
        print(f"\n{video}: {total:.2f} s (limit {LIMITS[video]:.0f}), voice {voice_total:.1f} s, air between scenes {air:.2f} s, "
              f"{len(scenes)} scenes, {len(shots)} shots, {len(caps)} captions")
        assert total <= LIMITS[video], "too long"
        for sc in scenes:
            ev = "".join(f"  {k} {sc[k]:.2f}" for k in ("zoom", "click", "scroll") if k in sc)
            print(f"  scene {sc['index']:2d}  voice {sc['start']:7.2f} to {sc['voice_end']:7.2f}  ({sc['voice_end'] - sc['start']:5.2f} s){ev}  {sc['label'][:44]}")
        for sh in shots:
            print(f"  shot {sh['index']:2d}  {sh['t0']:7.2f} to {sh['t1']:7.2f}  {sh['visual']}")
    print("\nWhat the transcriber heard (check against the script):")
    for video, si, words, dur, frac, said in report:
        flag = "" if frac > 0.8 and dur <= words * SEC_PER_WORD * 1.35 + 1.5 else "   <-- CHECK"
        print(f" {video} scene {si}: {words} words, {dur:.1f} s ({dur / words:.2f} s/word), {frac:.0%} of words matched{flag}\n    {said}")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "audio":
        build_audio()
    else:
        import steps
        steps.main(step, sys.argv[2:])
