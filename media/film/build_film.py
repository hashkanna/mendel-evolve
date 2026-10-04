"""Build the MendelEvolve film: every frame drawn in code from the real data, voice from Gemini TTS, score
synthesised. Run from the repo root:

    python3 media/film/build_film.py voice      # one Gemini clip per beat (cached in media/work/film/tts)
    uv run --with numpy --with scipy python media/film/build_film.py data   # media/film/data/film_data.json
    python3 media/film/build_film.py timeline   # beat and scene times from the clip lengths
    uv run --with playwright python media/film/build_film.py render [WORKERS]  # frames from film.html
    uv run --with numpy python media/film/build_film.py audio   # voice + score + effects, mixed
    python3 media/film/build_film.py mux        # media/mendelevolve_film.mp4
    uv run --with playwright python media/film/build_film.py still T [T ...]   # single frames, for checking
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
import script  # noqa: E402

CUT = os.environ.get("FILM_CUT", "")                 # "" is the full film, "short" the two-minute cut
SCENES = script.SCENES_SHORT if CUT == "short" else script.SCENES
MAX_TOTAL = 118.5 if CUT == "short" else None        # Iterate allows two minutes at most
SUFFIX = f"_{CUT}" if CUT else ""

FFMPEG, FFPROBE = "/opt/homebrew/bin/ffmpeg", "/opt/homebrew/bin/ffprobe"
WORK = ROOT / "media" / "work" / "film"
TTS = WORK / "tts"
TAG = os.environ.get("FILM_TAG", "")
FRAMES = WORK / (f"frames_{TAG}" if TAG else "frames")
FPS = 30
SR = 48000
W, H = 1920, 1080
# The narrator. SOURCE "tts" uses media/tts_gemini.py, "live" uses media/film/live_tts.py (a Live native-audio model,
# which takes a TONE). ACCENT "none" leaves the accent to the voice. Each can be overridden from the environment:
# FILM_VOICE, FILM_SOURCE, FILM_MODEL, FILM_ACCENT, FILM_TONE. Samples are in media/work/film/voices.
VOICE = os.environ.get("FILM_VOICE", "Algieba")
SOURCE = os.environ.get("FILM_SOURCE", "live")     # chosen on 4 October: Algieba on Gemini 3.8 Live
TTS_MODEL = os.environ.get("FILM_MODEL", "gemini-3.8-live" if SOURCE == "live" else "gemini-3.8-flash-tts")
ACCENT = os.environ.get("FILM_ACCENT", "en-GB" if SOURCE == "tts" else "none")
TONE = os.environ.get("FILM_TONE", "")
SEC_PER_WORD = 0.43
LOUDNESS = -17.0
XFADE = 0.8          # scenes overlap by this much; the voice never does
OUT = ROOT / "media" / (f"mendelevolve_film_{TAG}.mp4" if TAG else "mendelevolve_film.mp4")
SCORE = HERE / f"score_lyria{SUFFIX}.mp3"      # made by lyria.py; delete it to use the synthesised score
LYRIA_GAIN = 1.6
MUSIC_GAIN, FX_GAIN = 0.34, 0.4   # under a voice at about -20 dB RMS


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit("FAILED: " + " ".join(str(c) for c in cmd)[:300] + "\n" + (r.stdout + r.stderr)[-2000:])
    return r


def wav_seconds(path):
    with wave.open(str(path)) as w:
        return w.getnframes() / w.getframerate()


def beats():
    for scene, lead, items, tail in SCENES:
        for i, (bid, text, pause) in enumerate(items):
            yield scene, bid, text, pause


def key(text):
    tag = VOICE if (SOURCE, TTS_MODEL, ACCENT) == ("tts", "gemini-3.8-flash-tts", "en-GB") else f"{VOICE}|{SOURCE}|{TTS_MODEL}|{ACCENT}|{TONE}"
    return hashlib.sha1(f"{tag}|{text}".encode()).hexdigest()[:12]


# ------------------------------------------------------------------------------------------------ voice
def synth(bid, text):
    raw = TTS / f"{key(text)}.raw.wav"
    if raw.exists():
        return raw
    words = len(text.split())
    for attempt in range(3):
        tmp = TTS / f"{key(text)}.try{attempt}.wav"
        if SOURCE == "live":
            run(["uv", "run", "-q", "--with", "websockets", "python", HERE / "live_tts.py", tmp, text, "--voice", VOICE,
                 "--model", TTS_MODEL] + (["--tone", TONE] if TONE else []))
        else:
            run(["python3", ROOT / "media" / "tts_gemini.py", tmp, text, "--voice", VOICE, "--model", TTS_MODEL, "--language", ACCENT])
        dur = wav_seconds(tmp)
        if dur <= words * (0.6 if SOURCE == "live" else SEC_PER_WORD) * 1.35 + (2.5 if SOURCE == "live" else 1.5):  # Whisper checks the words
            tmp.rename(raw)
            return raw
        print(f"  {bid}: {dur:.1f} s for {words} words looks too long, regenerating")
    raise SystemExit(f"{bid}: over-long audio three times")


def prepare(text, raw):
    """Trim silence at both ends, common loudness, 48 kHz mono."""
    out = TTS / f"{key(text)}.wav"
    if out.exists() and out.stat().st_mtime >= raw.stat().st_mtime:
        return out
    log = subprocess.run([FFMPEG, "-hide_banner", "-i", str(raw), "-af", "silencedetect=noise=-38dB:d=0.1", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: (-?[\d.]+)", log)]
    dur = wav_seconds(raw)
    sil = [(max(0.0, s), ends[i] if i < len(ends) else dur) for i, s in enumerate(starts)]
    a = sil[0][1] if sil and sil[0][0] <= 0.01 else 0.0
    b = sil[-1][0] if sil and sil[-1][1] >= dur - 0.01 else dur
    a, b = max(0.0, a - 0.03), min(dur, b + 0.12)
    log = subprocess.run([FFMPEG, "-hide_banner", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", str(raw), "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    loud = float(re.findall(r"I:\s+(-?[\d.]+) LUFS", log)[-1])
    peak = float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", log)[-1])
    gain = min(LOUDNESS - loud, -1.0 - peak)
    run([FFMPEG, "-y", "-ss", f"{a:.3f}", "-to", f"{b:.3f}", "-i", raw, "-af", f"volume={gain:.2f}dB", "-ar", SR, "-ac", 1,
         "-c:a", "pcm_s16le", out])
    return out


def voice():
    TTS.mkdir(parents=True, exist_ok=True)
    todo = list(beats())

    def one(item):
        scene, bid, text, pause = item
        wav = prepare(text, synth(bid, text))
        return bid, wav_seconds(wav)

    for round_ in range(3):
        with ThreadPoolExecutor(4) as pool:
            for bid, dur in pool.map(one, todo):
                print(f"{bid}: {dur:.2f} s")
        bad = check_takes(todo)
        if not bad:
            return
        for scene, bid, text, pause in bad:          # the model strayed from the script: take it again
            for f in TTS.glob(f"{key(text)}*.wav"):
                f.unlink()
    raise SystemExit("some lines still differ from the script after three takes; listen to them")


NUMBER_WORDS = set("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                   "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred thousand "
                   "and point percent".split())


def check_takes(todo):
    """Whisper every take not checked yet; return the lines whose words differ from the script."""
    import difflib
    checked_path = TTS / "checked.json"
    checked = json.loads(checked_path.read_text()) if checked_path.exists() else {}
    new = [(item, TTS / f"{key(item[2])}.wav") for item in todo if key(item[2]) not in checked]
    if new:
        asr = WORK / "asr_takes"; asr.mkdir(exist_ok=True)
        run(["/opt/homebrew/bin/whisper", *[w for _, w in new], "--model", "base.en", "--language", "en",
             "--output_format", "txt", "--output_dir", asr, "--fp16", "False"])
        norm = lambda t: [w for w in re.sub(r"[^a-z0-9 ]", " ", t.lower().replace("mendelevolve", "mendel evolve")
                                               .replace("alphaevolve", "alpha evolve").replace("openevolve", "open evolve")
                                               .replace("-", " ")).split() if w not in NUMBER_WORDS and not w[0].isdigit()]
        for (scene, bid, text, pause), w in new:
            heard = (asr / (w.stem + ".txt")).read_text()
            ratio = difflib.SequenceMatcher(a=norm(text), b=norm(heard), autojunk=False).ratio()
            checked[key(text)] = round(ratio, 3)
            print(f"  {bid}: {ratio:.2f} {'' if ratio >= 0.85 else 'DIFFERS: ' + heard.strip()[:120]}")
        checked_path.write_text(json.dumps(checked, indent=1))
    return [item for item in todo if checked.get(key(item[2]), 0) < 0.85]


# ------------------------------------------------------------------------------------------------ timeline
def timeline(squeeze=1.0):
    t = 0.0
    scenes, beat_times = [], {}
    for i, (scene, lead, items, tail) in enumerate(SCENES):
        start = t
        t += lead * squeeze
        for bid, text, pause in items:
            dur = wav_seconds(TTS / f"{key(text)}.wav")
            beat_times[bid] = {"t": round(t, 3), "dur": round(dur, 3), "text": text,
                               "wav": str((TTS / f"{key(text)}.wav").relative_to(ROOT))}
            t += dur + pause * squeeze
        t += tail * squeeze
        scenes.append({"id": scene, "start": round(start, 3), "end": round(t, 3)})
        if i < len(SCENES) - 1:
            t -= XFADE   # the next scene begins under this one's last frames
    total = round(scenes[-1]["end"], 3)
    tl = {"fps": FPS, "total": total, "xfade": XFADE, "scenes": scenes, "beats": beat_times}
    (HERE / "data" / f"timeline{SUFFIX}.json").write_text(json.dumps(tl, indent=1))
    (HERE / "data" / f"timeline{SUFFIX}.js").write_text("window.TL = " + json.dumps(tl) + ";\n")
    if MAX_TOTAL and total > MAX_TOTAL and squeeze > 0.35:   # tighten the gaps until the cut fits
        return timeline(squeeze - 0.05)
    if MAX_TOTAL and total > MAX_TOTAL:
        raise SystemExit(f"{total:.1f} s even with tight gaps: shorten the script")
    print(f"total {total:.1f} s, {int(total * FPS)} frames" + (f", gaps at {squeeze:.0%}" if squeeze < 1 else ""))
    for s in scenes:
        print(f"  {s['id']:8s} {s['start']:6.1f} to {s['end']:6.1f}")


# ------------------------------------------------------------------------------------------------ data
def data():
    import numpy as np
    from scipy.optimize import linear_sum_assignment

    out = {}
    state = json.loads((ROOT / "runs/cp-fable-1/state.json").read_text())
    best = state["champion"]["solutions"]["n26"]
    scratch = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    off = json.loads((scratch / "cp_off.json").read_text()) if scratch else None
    on = json.loads((scratch / "cp_on.json").read_text()) if scratch else None
    if off is None:
        raise SystemExit("pass the folder holding cp_off.json and cp_on.json (solver runs with and without slsqp_polish)")
    a = np.array([[x, y] for x, y, r in off["solution"]])
    b = np.array([[x, y] for x, y, r in best])
    rows, cols = linear_sum_assignment(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    out["cp"] = {
        "off": off["solution"], "best": [best[j] for j in cols[np.argsort(rows)]],
        "off_score": round(sum(r for *_, r in off["solution"]), 6), "best_score": 2.635983,
        "trace": on["stats"]["trace"], "effect": 1.67,
        "genes": [{"name": g["name"], "status": g["status"], "author": g.get("author")} for g in state["genes"]],
    }

    cert = json.loads((ROOT / "results/no5sphere/certificates/n32_85.json").read_text())
    pts = np.array(cert["solution"], dtype=float)
    out["p60"] = {"n": 32, "points": cert["solution"]}
    # spheres through four of the points, centre inside the cube and a radius that reads well on screen
    rng = np.random.default_rng(7)
    spheres = []
    while len(spheres) < 6:
        idx = rng.choice(len(pts), 4, replace=False)
        P = pts[idx]
        A = 2 * (P[1:] - P[0])
        rhs = (P[1:] ** 2).sum(1) - (P[0] ** 2).sum()
        if abs(np.linalg.det(A)) < 1e-6:
            continue
        c = np.linalg.solve(A, rhs)
        r = np.linalg.norm(P[0] - c)
        if np.all(c > 6) and np.all(c < 25) and 7 < r < 12:
            d = np.abs(np.linalg.norm(pts - c, axis=1) - r)
            assert (d < 1e-9).sum() == 4
            spheres.append({"idx": idx.tolist(), "c": c.round(4).tolist(), "r": round(float(r), 4)})
    out["p60"]["spheres"] = spheres
    published = {int(k[1:]): r["value"] for k, r in json.loads((ROOT / "problems/no5sphere/records.json").read_text())["records"].items()}
    ours = {}
    for path in (ROOT / "results/no5sphere/certificates").glob("n*_*.json"):
        m = re.fullmatch(r"n(\d+)_(\d+)\.json", path.name)
        if m:
            n, s = int(m.group(1)), int(m.group(2))
            ours[n] = max(ours.get(n, 0), s)
    out["p60"]["records"] = [{"n": n, "old": published[n], "new": ours[n]} for n in sorted(ours)
                             if n <= 32 and ours[n] > published[n]]
    assert len(out["p60"]["records"]) == 17, out["p60"]["records"]

    iso = json.loads((ROOT / "results/noisosceles/certificates/n32_58.json").read_text())
    out["p59"] = {"n": 32, "points": iso["solution"]}
    assert len(iso["solution"]) == 58

    # quick screen and record scale, from the table in docs/record-scale.html
    out["forest"] = [
        {"name": "two identical controls", "quick": None, "rec": [0.00, -0.00, 0.01], "kind": "control"},
        {"name": "centrosymmetric", "quick": [0.00, -0.19, 0.17], "rec": [0.13, 0.06, 0.20], "kind": "seed"},
        {"name": "evolved champion", "quick": [0.10, 0.10, 0.10], "rec": [0.24, 0.18, 0.29], "kind": "champion"},
        {"name": "multi_recreate", "quick": [-0.04, -0.23, 0.12], "rec": [0.19, 0.11, 0.28], "rec2": [0.31, 0.22, 0.39], "kind": "star"},
        {"name": "layer_balance", "quick": [-0.15, -0.33, 0.04], "rec": [0.08, -0.01, 0.17]},
        {"name": "incidence_index", "quick": [0.00, -0.06, 0.06], "rec": [0.03, 0.02, 0.05]},
        {"name": "best_restart", "quick": [-0.06, -0.23, 0.08], "rec": [0.03, -0.04, 0.10]},
        {"name": "load_ruin", "quick": [-0.21, -0.38, -0.04], "rec": [0.03, -0.05, 0.11]},
        {"name": "dead_memo", "quick": [-0.27, -0.44, -0.10], "rec": [0.03, -0.06, 0.11]},
        {"name": "tent_cache", "quick": [-0.04, -0.10, 0.00], "rec": [0.02, -0.06, 0.10]},
        {"name": "far_pick", "quick": [-0.02, -0.25, 0.19], "rec": [0.00, -0.08, 0.09]},
        {"name": "kick_escalate", "quick": [0.02, -0.08, 0.12], "rec": [-0.02, -0.07, 0.04]},
        {"name": "sym_insert", "quick": [-0.02, -0.23, 0.19], "rec": [-0.06, -0.14, 0.02]},
    ]
    seed = (ROOT / "solvers/circle_packing/solver.py")
    code = seed.read_text().splitlines() if seed.exists() else []
    out["code"] = [l.rstrip() for l in code if l.strip() and len(l) < 90][:220]
    (HERE / "data" / "film_data.json").write_text(json.dumps(out))
    (HERE / "data" / "film_data.js").write_text("window.FILM = " + json.dumps(out) + ";\n")
    print("film_data.json:", {k: (len(v) if isinstance(v, list) else list(v)) for k, v in out.items()})


# ------------------------------------------------------------------------------------------------ frames
def open_page(p):
    browser = p.chromium.launch(channel="chrome", headless=True, args=["--disable-gpu-vsync", "--force-device-scale-factor=1"])
    page = browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
    page.on("pageerror", lambda e: print("PAGE ERROR:", e))
    page.goto((HERE / "film.html").as_uri() + (f"?cut={CUT}" if CUT else ""))
    page.wait_for_function("window.READY === true", timeout=60000)
    return browser, page


def grab(page, t, path):
    page.evaluate(f"renderFrame({t})")
    page.screenshot(path=str(path), type="jpeg", quality=93, clip={"x": 0, "y": 0, "width": W, "height": H})


def render_range(args):
    lo, hi = args
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, page = open_page(p)
        for f in range(lo, hi):
            path = FRAMES / f"f{f:05d}.jpg"
            if not path.exists():
                grab(page, f / FPS, path)
        browser.close()
    return hi - lo


def render():
    import time
    from concurrent.futures import ProcessPoolExecutor
    FRAMES.mkdir(parents=True, exist_ok=True)
    tl = json.loads((HERE / "data" / f"timeline{SUFFIX}.json").read_text())
    total = int(round(tl["total"] * FPS))
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    step = (total + workers - 1) // workers
    t0 = time.time()
    with ProcessPoolExecutor(workers) as pool:
        done = sum(pool.map(render_range, [(i, min(total, i + step)) for i in range(0, total, step)]))
    print(f"{done} frames in {time.time() - t0:.0f} s")


def still():
    from playwright.sync_api import sync_playwright
    (WORK / "stills").mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser, page = open_page(p)
        for t in sys.argv[2:]:
            grab(page, float(t), WORK / "stills" / f"t{float(t):07.2f}.jpg")
            print(WORK / "stills" / f"t{float(t):07.2f}.jpg")
        browser.close()


# ------------------------------------------------------------------------------------------------ sound
def audio():
    """Voice, a synthesised score and effects cued to the same moments film.html animates."""
    import numpy as np
    from scipy.signal import butter, fftconvolve, sosfilt

    tl = json.loads((HERE / "data" / f"timeline{SUFFIX}.json").read_text())
    total = tl["total"]
    N = int((total + 0.5) * SR)
    rng = np.random.default_rng(3)
    sc = {s["id"]: s for s in tl["scenes"]}
    bt = {k: v["t"] for k, v in tl["beats"].items()}
    bd = {k: v["dur"] for k, v in tl["beats"].items()}
    bw = lambda b, f: bt[b] + bd[b] * f

    def T(sec):
        return np.arange(int(sec * SR)) / SR

    def place(bus, x, t, gain=1.0, pan=0.0):
        i = int(t * SR)
        if i >= N or i + len(x) <= 0:
            return
        if i < 0:
            x, i = x[-i:], 0
        x = x[:N - i]
        if x.ndim == 1:
            l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
            bus[i:i + len(x), 0] += x * gain * l * 1.414
            bus[i:i + len(x), 1] += x * gain * r * 1.414
        else:
            bus[i:i + len(x)] += x * gain

    def lp(x, f, order=2):
        return sosfilt(butter(order, f, "low", fs=SR, output="sos"), x, axis=0)

    def hp(x, f, order=2):
        return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x, axis=0)

    def bp(x, lo, hi):
        return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x, axis=0)

    def env(n, a, r):           # attack then exponential release
        t = np.arange(n) / SR
        return np.minimum(1, t / max(a, 1e-4)) * np.exp(-t / r)

    hz = lambda m: 440 * 2 ** ((m - 69) / 12)

    # ---- effects
    def click():
        n = int(0.05 * SR); t = T(0.05)
        return (hp(rng.standard_normal(n), 3000) * env(n, 0.0005, 0.006) * 0.5 + np.sin(2 * np.pi * 1800 * t) * env(n, 0.001, 0.012) * 0.6)

    def tick(f=3200):
        t = T(0.06)
        return np.sin(2 * np.pi * f * t) * env(len(t), 0.0005, 0.012)

    def pluck(m, d=0.6):
        t = T(d); f = hz(m)
        return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t) + 0.12 * np.sin(6 * np.pi * f * t)) * env(len(t), 0.003, d / 4)

    def bell(m, d=2.5):
        t = T(d); f = hz(m)
        x = sum(a * np.sin(2 * np.pi * f * k * t) * np.exp(-t / (d / (1 + 1.5 * k)))
                for k, a in ((1, 1), (2.76, 0.4), (5.40, 0.2), (8.93, 0.08)))
        return x * np.minimum(1, t / 0.002)

    def boom(d=2.2, f0=110, f1=38):
        t = T(d)
        f = f1 + (f0 - f1) * np.exp(-t / 0.08)
        x = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.7)
        noise = lp(rng.standard_normal(len(t)), 900) * np.exp(-t / 0.05) * 0.5
        return x + noise

    BANDS = 200 * 2 ** (np.arange(18) / 3)             # 200 Hz to 10 kHz, a third of an octave apart

    def swept_noise(centre):
        """Noise whose pitch follows centre (Hz per sample): fixed bands crossfaded, so it never crackles."""
        x = rng.standard_normal(len(centre)); out = np.zeros(len(centre))
        lc = np.log2(centre)
        for f in BANDS:
            g = np.exp(-((lc - np.log2(f)) / 0.45) ** 2)
            if g.max() > 1e-3:
                out += bp(x, f / 1.12, min(f * 1.12, SR / 2 - 100)) * g
        return out / 2.5

    def whoosh(d=1.2, peak=0.5):
        n = int(d * SR); p = np.arange(n) / n
        return swept_noise(300 + 2400 * np.sin(np.pi * p) ** 1.5) * np.sin(np.pi * p) ** 2 * peak

    def riser(d=2.0):
        n = int(d * SR); t = np.arange(n) / SR
        f = 180 * (4 ** (t / d))                      # a tonal sweep only: no noise, so nothing swishes
        tone = sum(np.sin(2 * np.pi * np.cumsum(f * k) / SR) / k for k in (1, 2, 3)) * 0.3
        return tone * (t / d) ** 2

    def glitch(d=0.45):
        n = int(d * SR); t = np.arange(n) / SR
        x = rng.standard_normal(n)
        x = np.round(x * 3) / 3                                   # crushed
        gate = (np.floor(t * 34) % 2 == 0).astype(float)
        f = 900 * np.exp(-t / 0.12) + 60
        sq = np.sign(np.sin(2 * np.pi * np.cumsum(f) / SR))
        return (hp(x, 800) * 0.5 * gate + sq * 0.35) * np.exp(-t / 0.25)

    def shimmer(root=86):
        return sum(bell(root + k, 3.0) * 0.25 for k in (0, 7, 12, 16))

    fx = np.zeros((N, 2))
    xf = tl["xfade"]

    # open and problem
    place(fx, boom(2.6, 90, 36), bt["b1"] - 0.05, 0.5)
    for i in range(4):
        place(fx, glitch(0.12), bt["b4"] + 0.2 + i * 0.15, 0.25, -0.3 + i * 0.2)
        place(fx, pluck(76 + [0, 3, 7, 10][i], 0.5), bt["b4"] + 1.6 + i * 0.25, 0.35, 0.3 - i * 0.2)
    place(fx, boom(2.8, 80, 34), bt["b5"] + 0.1, 0.7)
    # genes
    g0 = sc["genes"]["start"]
    place(fx, shimmer(81), g0 + 0.5, 0.5)
    place(fx, boom(2.4, 70, 33), g0 + 0.25, 0.45)
    for i in range(9):
        place(fx, click(), bt["b6"] + 0.8 + i * 0.32, 0.6, -0.8 + i * 0.2)
        place(fx, pluck(69 + [0, 2, 4, 7, 9, 12, 14, 16, 19][i], 0.5), bt["b6"] + 0.8 + i * 0.32, 0.18, -0.8 + i * 0.2)
    for i in range(3):
        a = bt["b7"] + 0.6 + i * 0.45
        place(fx, riser(0.55) * 0.5, a - 0.55, 0.35)
        place(fx, bell(88 + i * 3, 1.5), a, 0.22, -0.3 + i * 0.3)
    t = bw("b7", 0.47)
    while t < bw("b7", 0.95):
        place(fx, click(), t, 0.25, rng.uniform(-0.7, 0.7)); t += 1 / 6
    ko = bw("b8", 0.62)
    place(fx, click(), ko - 0.35, 0.9)
    place(fx, boom(2.0, 140, 40), ko - 0.05, 0.6)
    place(fx, glitch(0.25), ko - 0.05, 0.25)
    # packing
    p0 = sc["packing"]["start"]
    for i in range(26):
        place(fx, pluck(64 + [0, 3, 5, 7, 10, 12, 15][i % 7] + 12 * (i // 14), 0.35), p0 + 0.5 + i * 0.04, 0.12, -0.6 + i * 0.05)
    evoA, evoB = bt["b9"] + 2.4, bt["b10"] + 0.05
    place(fx, click(), evoA - 0.5, 0.8)
    place(fx, riser(evoB - evoA), evoA, 0.45)
    place(fx, boom(3.0, 100, 35), evoB - 0.05, 0.8)
    place(fx, shimmer(86), evoB - 0.05, 0.6)
    knock = bw("b11", 0.56)
    place(fx, click(), knock - 0.05, 0.9)
    place(fx, glitch(0.5), knock, 0.7)
    place(fx, boom(2.5, 60, 28), knock + 0.05, 0.6)
    place(fx, boom(3.0, 120, 32), bt["b12"] + 0.2, 0.9)
    # sphere
    s0 = sc["sphere"]["start"]
    for i in range(0, 85, 3):
        place(fx, tick(2400 + 40 * (i % 12)), s0 + 0.4 + i * 0.022, 0.08, rng.uniform(-0.8, 0.8))
    ts = bw("b13", 0.48)
    k = 0
    while ts + k * 1.9 < bt["b14"] - 0.2 and k < 6:
        place(fx, bell([74, 77, 81, 79, 76, 72][k], 2.2), ts + k * 1.9, 0.3, [-0.4, 0.3, -0.2, 0.4, 0, -0.3][k]); k += 1
    place(fx, boom(2.6, 90, 34), bt["b14"] + 0.05, 0.7)
    for i in range(17):
        place(fx, pluck(67 + [0, 2, 4, 7, 9][i % 5] + 12 * (i // 5), 0.4), bt["b14"] + 0.5 + i * 0.13, 0.22, -0.8 + i * 0.1)
    for i in range(3):
        place(fx, bell(84 + [0, 4, 7][i], 2.0), bt["b15"] + 0.6 + i * 0.45, 0.3, -0.4 + i * 0.4)
    # iso
    for i in range(58):
        place(fx, pluck(60 + [0, 2, 4, 7, 9][i % 5] + 12 * ((i // 5) % 4), 0.3), bt["b16"] + 0.4 + i * 0.045, 0.13, -0.7 + (i % 15) * 0.1)
    place(fx, boom(1.0, 200, 70), bw("b17", 0.9) + 0.25, 0.35)
    ca, cb = bw("b18", 0.0) + 0.1, bw("b18", 0.62)
    t = ca
    while t < cb:
        place(fx, tick(2600 + rng.integers(0, 900)), t, 0.06, rng.uniform(-0.6, 0.6)); t += 1 / 24
    place(fx, shimmer(84), bw("b18", 0.74), 0.5)
    # twice
    for i in range(13):
        place(fx, tick(2000 + 90 * i), bt["b20"] + 0.2 + i * 0.09, 0.15)
    place(fx, riser(1.7), bw("b21", 0.25) - 0.1, 0.4)
    place(fx, bell(83, 2.5), bt["b22"], 0.35)
    place(fx, boom(0.9, 260, 80), bt["b23"] + 1.4, 0.55)
    place(fx, glitch(0.15), bt["b23"] + 1.4, 0.2)
    place(fx, riser(1.0), bw("b23", 0.62) - 0.05, 0.4)
    place(fx, boom(3.2, 110, 33), bw("b23", 0.66), 0.85)
    place(fx, shimmer(88), bw("b23", 0.66), 0.5)
    # close
    c0 = sc["close"]["start"]
    place(fx, riser(2.4), c0 + 0.1, 0.5)
    place(fx, boom(4.0, 90, 30), c0 + 2.45, 0.8)
    place(fx, shimmer(81), c0 + 2.45, 0.7)

    # ---- score: slow chords, a sub pulse and an arpeggio where the film moves fastest
    music = np.zeros((N, 2))
    D, F, G, A, Bb, C = 50, 53, 55, 57, 46, 48
    chords = {"Dm": [D, D + 12, F + 12, A + 12], "Bb": [Bb, Bb + 12, D + 12, F + 12], "F": [F, F + 12, A + 12, C + 24],
              "C": [C, C + 12, G + 12, C + 24 + 4], "Gm": [G - 12, G, Bb + 12, D + 12], "Am": [A - 12, A, C + 12, 64],
              "Fadd9": [F, F + 12, A + 12, C + 24, G + 24]}
    plan = {"open": ["Dm", "Dm"], "problem": ["Bb", "Gm", "Dm"], "genes": ["F", "C", "Dm", "Bb"],
            "packing": ["Dm", "Bb", "F", "C"], "sphere": ["Gm", "Bb", "F", "C"], "iso": ["Dm", "Am", "Bb", "C"],
            "twice": ["Dm", "Bb", "Gm", "C", "F"], "close": ["Fadd9"]}
    events = []
    for s in tl["scenes"]:
        names = plan[s["id"]]
        seg = (s["end"] - s["start"]) / len(names)
        for i, nm in enumerate(names):
            events.append((s["start"] + i * seg, seg + 1.5, nm))
    for t0, d, nm in events:
        n = int(d * SR); t = np.arange(n) / SR
        a = np.minimum(1, t / 1.2) * np.minimum(1, (d - t) / 1.5).clip(0)
        for m in chords[nm]:
            f = hz(m)
            for det, pan in ((-0.07, -0.6), (0.0, 0.0), (0.06, 0.6)):
                ff = f * 2 ** (det / 12)
                x = sum(np.sin(2 * np.pi * ff * k * t + rng.uniform(0, 6)) / k ** 1.4 for k in range(1, 6))
                place(music, x * a * 0.035, t0, 1.0, pan)
    music = lp(music, 2200)
    # sub pulse
    def kick():
        t = T(0.5); f = 40 + 70 * np.exp(-t / 0.04)
        return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t / 0.18)
    for sid, every in (("packing", 1.0), ("sphere", 1.0), ("iso", 1.0), ("twice", 0.75)):
        s = sc[sid]; t = s["start"] + 1.0
        while t < s["end"] - 1.0:
            place(music, kick(), t, 0.22); t += every
    # arpeggio
    for sid in ("genes", "sphere", "twice"):
        s = sc[sid]; names = plan[sid]; seg = (s["end"] - s["start"]) / len(names)
        t = s["start"] + 1.5; k = 0
        while t < s["end"] - 1.0:
            nm = names[min(len(names) - 1, int((t - s["start"]) / seg))]
            notes = [m + 24 for m in chords[nm][1:]]
            place(music, pluck(notes[k % len(notes)], 0.5), t, 0.06, -0.5 if k % 2 else 0.5)
            t += 0.25; k += 1

    # ---- the score itself comes from Lyria when its file is there; the synthesised pad then only carries the end card
    if SCORE.exists():
        raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(SCORE), "-f", "f32le", "-ac", "2", "-ar", str(SR), "-"],
                             capture_output=True, check=True).stdout
        ly = np.frombuffer(raw, dtype=np.float32).reshape(-1, 2).astype(float)
        ly *= 10 ** (-20 / 20) / np.sqrt(np.mean(ly ** 2))
        lyria = np.zeros((N, 2)); lyria[:min(N, len(ly))] = ly[:N]
        tail_from = min(sc["close"]["start"] + 3.0, len(ly) / SR - 9.0)   # Lyria fades over its last ~9 s
        keep = np.clip((np.arange(N) / SR - tail_from) / 4.0, 0, 1)
        music = lyria * LYRIA_GAIN + music * keep[:, None]
        print(f"score: Lyria, {len(ly) / SR:.1f} s")

    # ---- reverb on effects and score
    ir_n = int(2.4 * SR); ir_t = np.arange(ir_n) / SR
    ir = np.stack([rng.standard_normal(ir_n), rng.standard_normal(ir_n)], 1) * np.exp(-ir_t / 0.55)[:, None]
    ir = lp(ir, 5000); ir /= np.abs(ir).sum(0) ** 0.5 * 4
    wet = np.stack([fftconvolve(fx[:, c] + (0.0 if SCORE.exists() else 0.6) * music[:, c], ir[:, c])[:N] for c in range(2)], 1)
    fxmix = fx + 0.35 * wet

    # ---- voice
    voice = np.zeros(N)
    for b in tl["beats"].values():
        with wave.open(str(ROOT / b["wav"])) as w:
            x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float) / 32768
        i = int(b["t"] * SR); voice[i:i + len(x)] += x[:N - i]
    # ducking from the voice envelope
    envv = np.abs(voice)
    k = int(0.02 * SR); envv = np.convolve(envv, np.ones(k) / k, mode="same")
    att, rel = np.exp(-1 / (0.03 * SR)), np.exp(-1 / (0.5 * SR))
    from scipy.signal import lfilter
    smooth = lfilter([1 - rel], [1, -rel], (envv > 0.01).astype(float))
    duck = 1 - 0.72 * np.clip(smooth * 1.4, 0, 1)
    duck_fx = 1 - 0.4 * np.clip(smooth * 1.4, 0, 1)

    bedmix = music * duck[:, None] * MUSIC_GAIN + fxmix * duck_fx[:, None] * FX_GAIN
    mix = voice[:, None] * 1.0 + bedmix
    speech = np.zeros(N, bool)
    for b in tl["beats"].values():
        speech[int(b["t"] * SR):int((b["t"] + b["dur"]) * SR)] = True
    db = lambda x: 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
    print(f"voice {db(voice[speech]):.1f} dB, bed under speech {db(bedmix[speech].mean(1)):.1f} dB, "
          f"bed between lines {db(bedmix[~speech].mean(1)):.1f} dB")
    # fade out at the end
    fo = int(2.0 * SR); mix[-fo:] *= np.linspace(1, 0, fo)[:, None]
    mix /= max(1.0, np.abs(mix).max() / 0.95)
    out = WORK / (f"film_mix_{TAG}.wav" if TAG else "film_mix.wav")
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((mix * 32767).astype(np.int16).tobytes())
    # music and effects alone, for a version without the voice
    bed = music * MUSIC_GAIN + fxmix * FX_GAIN
    bed /= max(1.0, np.abs(bed).max() / 0.95)
    with wave.open(str(WORK / "film_bed.wav"), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((bed * 32767).astype(np.int16).tobytes())
    print(out, f"{N / SR:.1f} s")


def mux():
    if sys.argv[2:] == ["sound"]:                    # frames unchanged: keep the encoded picture, replace the sound
        tmp = OUT.with_suffix(".tmp.mp4")
        run([FFMPEG, "-y", "-i", OUT, "-i", WORK / (f"film_mix_{TAG}.wav" if TAG else "film_mix.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
             "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", SR, "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart",
             "-shortest", tmp])
        tmp.replace(OUT)
        print(OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")
        return
    tl = json.loads((HERE / "data" / f"timeline{SUFFIX}.json").read_text())
    frames = int(round(tl["total"] * FPS))
    missing = [f for f in range(frames) if not (FRAMES / f"f{f:05d}.jpg").exists()]
    if missing:
        raise SystemExit(f"{len(missing)} frames missing, first {missing[:5]}")
    run([FFMPEG, "-y", "-framerate", FPS, "-i", FRAMES / "f%05d.jpg", "-i", WORK / (f"film_mix_{TAG}.wav" if TAG else "film_mix.wav"),
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", SR,
         "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-tune", "film",
         "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-shortest", OUT])
    print(OUT, f"{OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    {"voice": voice, "timeline": timeline, "data": data, "render": render, "still": still,
     "audio": audio, "mux": mux}[sys.argv[1]]()
