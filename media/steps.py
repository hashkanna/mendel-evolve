"""The picture steps of build.py: stills, the knockout take, captions, assembly, check frames."""
import html
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from scenes import FPS, H, LIMITS, MEDIA, PLAN, SCENE_AIR, W, WORK, XFADE

SCENE_AIR_TXT = f"{SCENE_AIR:.1f}"

FFMPEG, FFPROBE = "/opt/homebrew/bin/ffmpeg", "/opt/homebrew/bin/ffprobe"
SLIDES = MEDIA / "slides"                 # a copy of the deck's ten slide fragments (one <section> each, 1920x1080)
DASH = "http://127.0.0.1:8765/?run=cp-fable-1"
SITE_PORT = 8931
FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&'
         'family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">')
STILLS, CAPS, CLIPS, TAKES = WORK / "stills", WORK / "captions", WORK / "clips", WORK / "takes"

# Site pages: CSS viewport width, and the scroll positions (CSS px) used by the page shots.
PAGES = {
    "p59": dict(file="problem59-n32.html", css_w=1200, y=[60, 270, 800], scroll_s=1.3),
    "record": dict(file="record-scale.html", css_w=1500, y=[40, 285, 1062], scroll_s=1.5),
}


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        raise SystemExit("FAILED: " + " ".join(str(c) for c in cmd)[:600] + "\n" + r.stderr[-3000:])
    return r


def load(video):
    return json.loads((WORK / f"timeline_{video}.json").read_text())


def browser(p):
    return p.chromium.launch(channel="chrome", headless=True)


# --------------------------------------------------------------------------------------------- stills
SLIDE_CSS = """
html,body{margin:0;background:#0B0F17}
section{width:1920px;height:1080px;position:relative;box-sizing:border-box;overflow:hidden}
aside{display:none}
h1,h2,h3,p,table{margin:0}
table{border-collapse:collapse;width:100%}
td,th{padding:10px 17px;border-bottom:1px solid #2A344A;vertical-align:top}
"""


def stills():
    from playwright.sync_api import sync_playwright
    STILLS.mkdir(parents=True, exist_ok=True)
    srv = subprocess.Popen(["python3", "-m", "http.server", str(SITE_PORT), "--bind", "127.0.0.1",
                            "--directory", str(MEDIA.parent / "docs")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.8)
        with sync_playwright() as p:
            b = browser(p)
            ctx = b.new_context(viewport={"width": W, "height": H}, device_scale_factor=2)
            pg = ctx.new_page()
            for f in sorted(SLIDES.glob("*.html")):
                page = f"<!doctype html><html><head><meta charset='utf-8'>{FONTS}<style>{SLIDE_CSS}</style></head><body style='margin:0'>{f.read_text()}</body></html>"
                pg.set_content(page, wait_until="networkidle")
                pg.evaluate("document.fonts.ready")
                pg.wait_for_timeout(300)
                fonts = pg.evaluate("[...document.fonts].filter(f=>f.status==='loaded').map(f=>f.family+' '+f.weight)")
                assert any("IBM Plex Sans" in x for x in fonts), ("fonts did not load", fonts)
                pg.screenshot(path=str(STILLS / f"slide_{f.stem}.png"))
                print("slide", f.stem, len(fonts), "font faces")
            ctx.close()
            for name, cfg in PAGES.items():
                dsf = 2 * W / cfg["css_w"]
                ctx = b.new_context(viewport={"width": cfg["css_w"], "height": round(H * cfg["css_w"] / W)}, device_scale_factor=dsf)
                pg = ctx.new_page()
                pg.goto(f"http://127.0.0.1:{SITE_PORT}/{cfg['file']}", wait_until="networkidle")
                pg.wait_for_timeout(1500)
                # room below the last scroll position, so the crop never runs off the page
                pg.add_style_tag(content="body{min-height:%dpx}" % (cfg["y"][-1] + round(H * cfg["css_w"] / W) + 40))
                pg.wait_for_timeout(200)
                pg.screenshot(path=str(STILLS / f"page_{name}.png"), full_page=True)
                print("page", name, pg.evaluate("document.documentElement.scrollHeight"), "css px tall")
                ctx.close()
            b.close()
    finally:
        srv.terminate()
        srv.wait()


# ------------------------------------------------------------------------------------- knockout take
DASH_VIEW = dict(w=1536, h=864)          # the dashboard is laid out at this size and shown 1.25x larger, filling 1920x1080
DASH_K = W / DASH_VIEW["w"]
CURSOR_JS = ("""
(() => {
  const st = document.createElement('style');
  st.textContent = `
    html, body { overflow: hidden !important; }
    #tip { display: none !important; }
    #app { width: %dpx !important; height: %dpx !important; min-width: 0 !important; min-height: 0 !important;
      transform-origin: 0 0; transform: scale(%s); }
    #mv-cursor { position: fixed; left: 0; top: 0; width: 33px; height: 40px; z-index: 2147483647; pointer-events: none;
      filter: drop-shadow(0 2px 4px rgba(0,0,0,.6)); }
    #mv-cursor svg { display: block; transform-origin: 3px 2px; transition: transform .08s; }
    #mv-cursor.down svg { transform: scale(.86); }
    #mv-ring { position: fixed; left: 0; top: 0; width: 26px; height: 26px; margin: -13px 0 0 -13px; border-radius: 50%;
      border: 3px solid rgba(110,168,254,.95); z-index: 2147483646; pointer-events: none; opacity: 0; }
    #mv-ring.go { animation: mvring .7s ease-out; }
    @keyframes mvring { from { opacity: .95; transform: var(--at) scale(1); } to { opacity: 0; transform: var(--at) scale(3.4); } }
  `;
  document.documentElement.appendChild(st);
  const c = document.createElement('div'); c.id = 'mv-cursor';
  c.innerHTML = '<svg width="33" height="40" viewBox="0 0 20 24"><path d="M2 1.2 L2 19 L6.6 14.9 L9.8 22 L12.7 20.7 L9.6 13.8 L15.7 13.6 Z" fill="#fff" stroke="#0b0f17" stroke-width="1.5" stroke-linejoin="round"/></svg>';
  const r = document.createElement('div'); r.id = 'mv-ring';
  document.documentElement.append(r, c);
  const at = (x, y) => `translate(${x}px, ${y}px)`;
  const tip = (x, y) => at(x - 3.3, y - 2);       // the arrow's point is the pointer position
  document.addEventListener('mousemove', (e) => { c.style.transform = tip(e.clientX, e.clientY); }, true);
  document.addEventListener('mousedown', (e) => {
    c.classList.add('down'); r.style.setProperty('--at', at(e.clientX, e.clientY)); r.classList.remove('go'); void r.offsetWidth; r.classList.add('go');
  }, true);
  document.addEventListener('mouseup', () => setTimeout(() => c.classList.remove('down'), 180), true);
  window.dispatchEvent(new Event('resize'));      // the dashboard redraws its charts for the new width
})();
""").replace("%d", "{0}", 1).replace("%d", "{1}", 1).replace("%s", "{2}", 1)
ZOOM_JS = """
() => {
  const k = %s, app = document.getElementById('app');
  const led = document.getElementById('p-ledger').getBoundingClientRect();
  const top = document.querySelector('.row-top').getBoundingClientRect();
  const s = innerWidth / (led.width / k + 16);
  app.style.transition = 'transform 1.5s cubic-bezier(.45,.05,.25,1)';
  app.style.transform = `translate(${-(led.left / k - 8) * s}px, ${-(top.top / k - 8) * s}px) scale(${s})`;
  return s;
}
""" % DASH_K
BUTTON_JS = """
() => {
  const row = [...document.querySelectorAll('.lrow')].find((r) => r.textContent.includes('slsqp_polish') && r.querySelector('button.btn'));
  if (!row) return null;
  const b = row.querySelector('button.btn'), r = b.getBoundingClientRect();
  // aim below the label so the arrow does not hide it
  return { x: r.left + r.width * 0.62, y: r.top + r.height * 0.74, disabled: b.disabled, text: b.textContent };
}
"""
STRIP_JS = """
() => {
  const st = document.querySelector('.strip');
  if (!st) return null;
  const cap = st.querySelector('.st-cap'), big = st.querySelector('.st-big'), sub = st.querySelector('.st-sub');
  const r = st.getBoundingClientRect();
  return { cls: st.className, cap: cap && cap.textContent, big: big && big.textContent, sub: sub && sub.textContent,
           dots: st.querySelectorAll('circle').length, rect: [r.left, r.top, r.width, r.height] };
}
"""


def knockout(video, dry=""):
    """Record one real take of the dashboard, timed to the narration of `video`. Presses Knock out once."""
    from playwright.sync_api import sync_playwright
    tl = load(video)
    sc = next(s for s in tl["scenes"] if "click" in s)
    sh = next(s for s in tl["shots"] if s["visual"] == "dash")
    t_zoom, t_click, t_end = sc["zoom"] - sh["clip_start"], sc["click"] - sh["clip_start"], sh["clip_end"] - sh["clip_start"]
    out = TAKES / video
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    pre, post = 1.2, 1.5
    ease = lambda u: u * u * (3 - 2 * u)
    with sync_playwright() as p:
        b = browser(p)
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(out), record_video_size={"width": W, "height": H})
        pg = ctx.new_page()
        pg.goto(DASH, wait_until="networkidle")
        pg.wait_for_selector(".lrow button.btn")
        pg.evaluate(CURSOR_JS.replace("{0}", str(DASH_VIEW["w"])).replace("{1}", str(DASH_VIEW["h"])).replace("{2}", str(DASH_K)))
        park = (1160.0, 800.0)
        pg.mouse.move(*park)
        pg.wait_for_timeout(2500)
        btn = pg.evaluate(BUTTON_JS)
        assert btn and not btn["disabled"] and btn["text"] == "Knock out", btn
        t0 = time.monotonic() + pre                   # the clip starts here

        def until(t):
            d = t0 + t - time.monotonic()
            if d > 0:
                time.sleep(d)

        def glide(a, z, seconds):
            n = max(2, int(seconds / 0.016))
            start = time.monotonic()
            for i in range(1, n + 1):
                u = ease(i / n)
                pg.mouse.move(a[0] + (z[0] - a[0]) * u, a[1] + (z[1] - a[1]) * u)
                d = start + seconds * i / n - time.monotonic()
                if d > 0:
                    time.sleep(d)

        until(t_zoom)
        scale = pg.evaluate(ZOOM_JS)
        until(t_click - 1.45)
        btn = pg.evaluate(BUTTON_JS)                  # where the button is after the zoom
        target = (btn["x"], btn["y"])
        glide(park, target, 1.05)
        until(t_click)
        events = []
        if dry:
            print("dry run: not pressing")
        else:
            pg.mouse.down()
            events.append(("down", time.monotonic() - t0))
            time.sleep(0.09)
            pg.mouse.up()
        clicked = time.monotonic()
        time.sleep(0.7)
        away = (target[0] - 90, min(860.0, target[1] + 400))
        glide(target, away, 0.8)
        last, settled = None, None
        while time.monotonic() - t0 < t_end + post:
            st = pg.evaluate(STRIP_JS)
            if st and (st["cap"], st["big"], st["dots"]) != last:
                last = (st["cap"], st["big"], st["dots"])
                events.append((time.monotonic() - clicked, st))
                if settled is None and st["cap"] and st["cap"].startswith("Live knockout"):
                    settled = time.monotonic() - clicked
            time.sleep(0.1)
        final = pg.evaluate(STRIP_JS)
        pg.screenshot(path=str(out / "end.png"))
        ctx.close()
        video_path = pg.video.path()
        b.close()
    take = out / "take.webm"
    Path(video_path).rename(take)
    meta = dict(video=video, t_zoom=t_zoom, t_click=t_click, t_end=t_end, pre=pre, scale=scale, button=btn, settled_after=settled,
                final=final, events=[e for e in events if isinstance(e[1], dict)][-6:], dry=bool(dry))
    meta["click_in_take"] = find_click(take, meta)
    (out / "take.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("t_zoom", "t_click", "t_end", "scale", "settled_after", "click_in_take")}, indent=1))
    print("final strip:", final)


def find_click(take, meta):
    """Time of the button press inside the take: the first frame in which the result strip has opened.

    The strip pushes the "Not kept" line down into a place that was empty, and the cursor never goes there
    before the press, so that patch of the picture changes exactly once."""
    final = meta.get("final")
    if not final:
        return None
    x, y, w, h = [round(v) for v in final["rect"]]
    cx, cy, cw, ch = 60, y + h + 10, 640, 40
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(take), "-vf", f"crop={cw}:{ch}:{cx}:{cy},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True).stdout
    size = cw * ch
    n = len(raw) // size
    num, den = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v", "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0", str(take)],
                              capture_output=True, text=True).stdout.strip().split("/")
    fps = int(num) / int(den)
    ref_i = min(n - 1, int((meta["pre"] + meta["t_click"] - 1.0) * fps))    # after the zoom, before the press
    ref = raw[ref_i * size:(ref_i + 1) * size]
    for i in range(ref_i, n):
        cur = raw[i * size:(i + 1) * size]
        if sum(abs(a - b) for a, b in zip(cur[::5], ref[::5])) / (size / 5) > 1.5:
            return i / fps
    return None


def findclick(video):
    out = TAKES / video
    meta = json.loads((out / "take.json").read_text())
    meta["click_in_take"] = find_click(out / "take.webm", meta)
    (out / "take.json").write_text(json.dumps(meta, indent=1))
    print(video, "click at", meta["click_in_take"], "s in the take; the clip starts at", meta["click_in_take"] - meta["t_click"])


# -------------------------------------------------------------------------------------------- captions
CAP_CSS = """
html,body{margin:0;background:transparent}
#bar{position:fixed;left:0;right:0;bottom:0;height:158px;box-sizing:border-box;display:flex;align-items:center;justify-content:center;
  padding:0 110px 4px;background:rgba(6,9,15,.96);border-top:1px solid rgba(255,255,255,.10)}
#bar.one{height:100px}
#txt{font:500 40px/52px 'IBM Plex Sans',Arial,sans-serif;color:#F4F6FB;text-align:center;text-wrap:balance;letter-spacing:.1px}
"""


def captions():
    from playwright.sync_api import sync_playwright
    CAPS.mkdir(parents=True, exist_ok=True)
    for f in CAPS.glob("*"):
        f.unlink()
    with sync_playwright() as p:
        b = browser(p)
        pg = b.new_context(viewport={"width": W, "height": H}).new_page()
        pg.set_content(f"<!doctype html><html><head><meta charset='utf-8'>{FONTS}<style>{CAP_CSS}</style></head><body><div id='bar'><div id='txt'>x</div></div></body></html>",
                       wait_until="networkidle")
        pg.evaluate("document.fonts.load(\"500 40px 'IBM Plex Sans'\")")
        pg.wait_for_timeout(400)
        assert pg.evaluate("document.fonts.check(\"500 40px 'IBM Plex Sans'\")"), "caption font did not load"
        pg.evaluate("document.getElementById('bar').style.display='none'")
        pg.screenshot(path=str(CAPS / "blank.png"), omit_background=True)
        pg.evaluate("document.getElementById('bar').style.display=''")
        for video in PLAN:
            tl = load(video)
            lines = [f"file '{CAPS / 'blank.png'}'", f"duration {tl['captions'][0]['start']:.4f}"]
            for i, c in enumerate(tl["captions"]):
                png = CAPS / f"{video}_{i + 1:03d}.png"
                top = pg.evaluate("""([t, one]) => { const b = document.getElementById('bar'), x = document.getElementById('txt');
                    b.className = one ? 'one' : ''; x.textContent = t;
                    return [Math.round(x.getBoundingClientRect().height / 52), b.getBoundingClientRect().top]; }""", [c["text"], c["lines"] == 1])
                assert top[0] <= c["lines"], (video, c["text"], top)
                pg.screenshot(path=str(png), omit_background=True)
                c["png"], c["bar_top"] = png.name, top[1]
                lines += [f"file '{png}'", f"duration {c['end'] - c['start']:.4f}"]
                nxt = tl["captions"][i + 1]["start"] if i + 1 < len(tl["captions"]) else tl["total"] + 1.0
                if nxt - c["end"] > 0.001:
                    lines += [f"file '{CAPS / 'blank.png'}'", f"duration {nxt - c['end']:.4f}"]
            lines.append(f"file '{CAPS / 'blank.png'}'")
            (CAPS / f"{video}.txt").write_text("\n".join(lines) + "\n")
            (WORK / f"timeline_{video}.json").write_text(json.dumps(tl, indent=1))
            print(video, len(tl["captions"]), "captions; highest bar top at y =", min(c["bar_top"] for c in tl["captions"]))
        b.close()


# -------------------------------------------------------------------------------------------- assembly
X264 = ["-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p", "-r", str(FPS)]
PUSH = 0.0016            # push-in on a still slide: zoom per second
PUSH_MAX = 1.045


def smooth_terms(keys):
    """ffmpeg expression for a value that eases between keyframes [(t_from, t_to, delta), ...]."""
    out = []
    for i, (a, b, d) in enumerate(keys):
        out.append(f"{d:.2f}*(st({i},clip((t-{a:.3f})/{max(b - a, 0.01):.3f},0,1))*ld({i})*ld({i})*(3-2*ld({i})))")
    return "+".join(out)


def clip_for(video, tl, sh):
    """Render one shot as a silent clip of exactly its length."""
    CLIPS.mkdir(parents=True, exist_ok=True)
    out = CLIPS / f"{video}_{sh['index']:02d}.mp4"
    length = sh["clip_end"] - sh["clip_start"]
    frames = round(length * FPS)
    kind, _, name = sh["visual"].partition(":")
    sc = tl["scenes"][sh["scene"] - 1]
    if kind == "slide":
        zmax = min(PUSH_MAX, 1 + PUSH * length)
        vf = (f"scale=7680:4320:flags=lanczos,zoompan=z='min({zmax:.5f},1+{PUSH / FPS:.8f}*on)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d=1:s={W}x{H}:fps={FPS},format=yuv420p")
        cmd = [FFMPEG, "-y", "-v", "error", "-loop", "1", "-framerate", FPS, "-i", STILLS / f"slide_{name}.png", "-vf", vf,
               "-frames:v", frames, *X264, "-crf", "14", out]
    elif kind in PAGES:
        cfg = PAGES[kind]
        k = 2 * W / cfg["css_w"]
        y0, y1, y2 = [v * k for v in cfg["y"]]
        scroll = sc["scroll"] - sh["clip_start"]
        drift_end = max(1.6, min(scroll - 0.8, 0.5 + 4.5))
        keys = [(0.5, drift_end, y1 - y0), (scroll, scroll + cfg["scroll_s"], y2 - y1)]
        vf = f"crop={2 * W}:{2 * H}:0:'{y0:.1f}+{smooth_terms(keys)}',scale={W}:{H}:flags=lanczos,format=yuv420p"
        cmd = [FFMPEG, "-y", "-v", "error", "-loop", "1", "-framerate", FPS, "-i", STILLS / f"page_{kind}.png", "-vf", vf,
               "-frames:v", frames, *X264, "-crf", "14", out]
    elif kind == "dash":
        meta = json.loads((TAKES / video / "take.json").read_text())
        want = sc["click"] - sh["clip_start"]
        assert abs(want - meta["t_click"]) < 0.12, f"the {video} take was timed for a click at {meta['t_click']:.2f} s, the timeline now wants {want:.2f} s: record it again"
        start = meta["click_in_take"] - 0.1 - want       # the press is about 0.1 s before the strip shows
        assert start >= 0
        cmd = [FFMPEG, "-y", "-v", "error", "-ss", f"{start:.3f}", "-i", TAKES / video / "take.webm", "-vf", f"fps={FPS},scale={W}:{H},format=yuv420p",
               "-frames:v", frames, *X264, "-crf", "14", out]
    else:
        raise SystemExit("unknown visual " + sh["visual"])
    run(cmd)
    got = float(run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out]).stdout)
    assert abs(got - length) < 0.05, (out, got, length)
    return out


def assemble(only=""):
    for video in PLAN:
        if only and only != video:
            continue
        tl = load(video)
        clips = [clip_for(video, tl, sh) for sh in tl["shots"]]
        total = tl["total"]
        cmd = [FFMPEG, "-y", "-v", "error"]
        for c in clips:
            cmd += ["-i", c]
        cmd += ["-f", "concat", "-safe", "0", "-i", CAPS / f"{video}.txt", "-i", WORK / f"narration_{video}.wav"]
        n = len(clips)
        fc = [f"[{i}:v]settb=AVTB,fps={FPS},setpts=PTS-STARTPTS[c{i}]" for i in range(n)]
        prev = "c0"
        for i in range(1, n):
            fc.append(f"[{prev}][c{i}]xfade=transition=fade:duration={XFADE}:offset={tl['shots'][i]['clip_start']:.4f}[x{i}]")
            prev = f"x{i}"
        fc.append(f"[{n}:v]fps={FPS},format=rgba[cap]")
        fc.append(f"[{prev}][cap]overlay=0:0:format=auto:eof_action=pass,fade=t=in:st=0:d=0.5,fade=t=out:st={total - 0.5:.3f}:d=0.5,format=yuv420p[v]")
        fc.append(f"[{n + 1}:a]aresample=48000,apad,atrim=0:{total:.3f},aformat=channel_layouts=stereo[a]")
        out = MEDIA / f"mendelevolve_{video}.mp4"
        cmd += ["-filter_complex", ";".join(fc), "-map", "[v]", "-map", "[a]", *X264, "-crf", "18", "-c:a", "aac", "-b:a", "160k",
                "-t", f"{total:.3f}", "-movflags", "+faststart", out]
        run(cmd)
        silent = MEDIA / f"mendelevolve_{video}_no_voice.mp4"
        run([FFMPEG, "-y", "-v", "error", "-i", out, "-f", "lavfi", "-t", f"{total:.3f}", "-i", "anullsrc=r=48000:cl=stereo", "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-shortest", "-movflags", "+faststart", silent])
        for f in (out, silent):
            print(f.name, probe(f))


def probe(f):
    j = json.loads(run([FFPROBE, "-v", "error", "-show_entries", "stream=codec_name,width,height,r_frame_rate,duration,channels:format=duration,size",
                        "-of", "json", f]).stdout)
    v = next(s for s in j["streams"] if s["codec_name"] == "h264")
    a = next(s for s in j["streams"] if s["codec_name"] == "aac")
    d = float(j["format"]["duration"])
    return (f"{v['width']}x{v['height']} {v['r_frame_rate']} fps h264, aac {a['channels']} ch, video {float(v['duration']):.2f} s, audio {float(a['duration']):.2f} s, "
            f"{int(d // 60)}:{d % 60:05.2f}, {int(j['format']['size']) / 1e6:.1f} MB")


# ---------------------------------------------------------------------------------------- check frames
def frames():
    out = MEDIA / "frames"
    out.mkdir(exist_ok=True)
    for f in out.glob("*.png"):
        f.unlink()
    for video in PLAN:
        tl = load(video)
        src = MEDIA / f"mendelevolve_{video}.mp4"
        for sh in tl["shots"]:
            sc = tl["scenes"][sh["scene"] - 1]
            kind = sh["visual"].replace(":", "-")
            times = {"mid": (sh["t0"] + sh["t1"]) / 2}
            if "scroll" in sc and sh["visual"].split(":")[0] in PAGES:
                times = {"before-scroll": sc["scroll"] - 0.4, "after-scroll": min(sh["t1"] - 0.4, sc["scroll"] + 3.0)}
            if kind == "dash":
                times = {"wide": sc["zoom"] - 0.5, "press": sc["click"] + 0.25, "result": sc["voice_end"] - 0.3}
            for label, t in times.items():
                png = out / f"{video}_scene{sh['scene']:02d}_shot{sh['index']:02d}_{kind}_{label}.png"
                run([FFMPEG, "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", png])
                print(png.name, f"at {t:.2f} s")


# ---------------------------------------------------------------------------------------------- readme
def clock(t):
    return f"{int(t // 60)}:{t % 60:05.2f}"


def readme():
    import scenes as S
    L = []
    w = L.append
    w("# MendelEvolve demo videos\n")
    w("Four files, all 1920x1080, 30 fps, H.264 video and AAC audio:\n")
    w("| File | Length | Size | What |\n|---|---|---|---|")
    for video in PLAN:
        for suffix, what in (("", "narrated, captions burned in"), ("_no_voice", "same pictures and captions, silent audio track, for recording your own voice")):
            f = MEDIA / f"mendelevolve_{video}{suffix}.mp4"
            if f.exists():
                j = json.loads(run([FFPROBE, "-v", "error", "-show_entries", "format=duration,size", "-of", "json", f]).stdout)["format"]
                w(f"| `{f.name}` | {clock(float(j['duration']))} | {int(j['size']) / 1e6:.1f} MB | {what} |")
    w("\nThe script is `narration.md`; the voice and the captions use its text unchanged. The videos, `work/` and `frames/` are not tracked by git.\n")
    w("## How they were built\n")
    w("Everything is driven by `build.py` (the audio and timeline), `steps.py` (pictures and assembly) and `scenes.py` (which picture goes with which "
      "sentence, and the timing constants). Run from the repository root, in this order:\n")
    w("```\n"
      "python3 media/build.py audio                                   # voice, one clip per scene, and the timeline of both videos\n"
      "uv run --with playwright python media/build.py stills          # slides and site pages as PNG (serves docs/ on 127.0.0.1:8931 while it runs)\n"
      "uv run --with playwright python media/build.py knockout 4min   # one real take of the live dashboard; presses Knock out once\n"
      "uv run --with playwright python media/build.py knockout 2min   # the same, timed to the two-minute narration; presses it once\n"
      "uv run --with playwright python media/build.py captions        # caption bars as transparent PNG\n"
      "uv run --with playwright python media/build.py assemble        # the four mp4 files (add 4min or 2min to build one)\n"
      "uv run --with playwright python media/build.py frames          # check frames into media/frames/\n"
      "uv run --with playwright python media/build.py readme          # this file\n"
      "```\n")
    w("Needs: ffmpeg and ffprobe in `/opt/homebrew/bin`, Google Chrome (Playwright drives the installed browser, `channel=\"chrome\"`, nothing is "
      "downloaded), macOS `say`, the `whisper` command with its `small.en` model already cached (it runs locally and is only used to find when "
      "each sentence starts), and the dashboard running at `http://127.0.0.1:8765/?run=cp-fable-1`.\n")
    w("What each step does:\n")
    w(f"- **audio.** One clip per scene with `say -v {S.SAY_VOICE} -r {S.SAY_RATE}`, trimmed of silence at both ends and brought to a common loudness. "
      "Whisper transcribes each clip with word timings; the script's words are matched to them, and each sentence start is moved to the end of the "
      "pause just before it. From this come the caption times, the moment of the button press, the page scrolls and the cuts inside a scene. "
      f"Scenes are {SCENE_AIR_TXT} s apart (last word to first word); the picture changes in the middle of that gap.")
    w("- **stills.** Each slide in `media/slides/` (a copy of the deck's fragments) is wrapped in a minimal page with the two Google Fonts and "
      "screenshotted at 3840x2160. The two site pages are screenshotted full length at 3840 px wide: `problem59-n32.html` laid out 1200 px wide, "
      "`record-scale.html` 1500 px wide.")
    w("- **knockout.** A real screen recording (Playwright video, 1920x1080). The dashboard is laid out at 1536x864 and shown 1.25x larger so that it "
      "fills the frame; at the sentence about the ledger the view pushes in on the ledger; an arrow is drawn for the pointer because recorded video "
      "has none; the pointer glides to the button and presses it once, 0.3 s into \"We press knock out.\" The step then finds the press inside the "
      "recording (the first frame in which the result strip is open) so the clip can be cut to the narration. If the audio is rebuilt and the "
      "press moves by more than 0.12 s relative to the start of the scene, `assemble` stops and asks for a new take.")
    w("- **captions.** The narration split at sentence ends, and at a comma or colon when a sentence is longer than 112 characters "
      "(62 on the title and closing slides, which keep captions to one line because they have text low in the frame). 40 px IBM Plex Sans on a dark "
      "band across the bottom 158 px (100 px on the title and closing slides).")
    w(f"- **assemble.** Slides get a slow push-in ({PUSH * 100:.2f}% per second, from an 8K upscale so the motion is smooth). Site pages are a moving crop "
      f"of the tall screenshot. Shots are joined with {XFADE} s crossfades, the captions are overlaid, and the video fades from and to black over 0.5 s. "
      "The no-voice files copy the video stream and replace the audio with silence.\n")
    w("## Voice\n")
    if S.VOICE_SOURCE == "say":
        w(f"These files use macOS `say -v {S.SAY_VOICE} -r {S.SAY_RATE}`. Nothing in the script was respelled: `say` reads every number as written "
          "(the script already spells them out) and reads MendelEvolve, AlphaEvolve and OpenEvolve as two words.\n")
        w("A Gemini voice was asked for part-way through (`media/tts_gemini.py`, voice Algieba). The build agent's permission system refused that "
          "network call, so it was not used. To switch: set `VOICE_SOURCE = \"gemini\"` in `scenes.py`, run `audio`, then `knockout 4min`, "
          "`knockout 2min` (the press moves with the new timing), `captions`, `assemble`, `frames`, `readme`. `audio` prints what the transcriber "
          "heard for every scene and flags a clip that is too long for its word count. The Gemini voice is slower (about 0.43 s per word against "
          "0.36 here): `audio` shortens the gap between scenes down to 0.4 s to stay under the limits and stops if that is not enough "
          "(then raise `TEMPO` in `scenes.py`).\n")
    else:
        w(f"These files use Gemini text-to-speech (`media/tts_gemini.py`, voice {S.GEMINI_VOICE}), one call per scene.\n")
    for video in PLAN:
        tl = load(video)
        title = "Four-minute video" if video == "4min" else "Two-minute video"
        w(f"## {title}: `mendelevolve_{video}.mp4`, {clock(tl['total'])} (limit {clock(LIMITS[video])})\n")
        take = TAKES / video / "take.json"
        if take.exists():
            m = json.loads(take.read_text())
            f = m["final"]
            big = re.match(r"([+\-−]?[\d.]{4})(.*)", f["big"])
            w(f"The live take shows `{big.group(1)}` ({big.group(2)}), \"{f['sub']}\", from {f['cap'].split(' · ')[1]}; it settled {m['settled_after']:.1f} s after the press.\n")
        w("| Scene | On screen | Picture | Voice | Voice length |\n|---|---|---|---|---|")
        for sc in tl["scenes"]:
            shots = [sh for sh in tl["shots"] if sh["scene"] == sc["index"]]
            pics = "; ".join(f"{sh['visual']} {clock(sh['t0'])} to {clock(sh['t1'])}" for sh in shots)
            assert shots[0]["t0"] <= sc["start"] and shots[-1]["t1"] >= sc["voice_end"], "a scene's audio runs past its picture"
            extra = "".join(f"; {k} at {clock(sc[k])}" for k in ("zoom", "click", "scroll") if k in sc).replace("click", "press")
            w(f"| {sc['index']} | {sc['label'].rstrip('.')} | {pics}{extra} | {clock(sc['start'])} to {clock(sc['voice_end'])} | {sc['voice_end'] - sc['start']:.2f} s |")
        w("\nCaptions:\n")
        w("| From | To | Text |\n|---|---|---|")
        for c in tl["captions"]:
            w(f"| {clock(c['start'])} | {clock(c['end'])} | {c['text']} |")
        w("")
    w("## Checks made\n")
    w("- `ffprobe` on each file: 1920x1080, 30 fps, H.264 and AAC, lengths as in the table above.")
    w("- One frame per shot (three for the dashboard, two for each scrolling page) is in `media/frames/`; each was looked at for borders, cut-off "
      "text and captions covering content.")
    w("- Every scene's picture starts before its voice and ends after it (asserted when this file is written).")
    w("- The slide footnotes sit under the caption band while a caption is showing; they are visible only in the gaps between scenes.")
    (MEDIA / "README.md").write_text("\n".join(L) + "\n")
    print("wrote", MEDIA / "README.md", len(L), "lines")


def main(step, args):
    fn = {"stills": stills, "knockout": knockout, "findclick": findclick, "captions": captions, "assemble": assemble, "frames": frames, "readme": readme}.get(step)
    if not fn:
        raise SystemExit(__doc__)
    fn(*args)
