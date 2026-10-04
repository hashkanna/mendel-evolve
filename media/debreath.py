"""Turn down breath noise in a narration track, using Whisper word timings.

    whisper NARRATION.wav --model base.en --language en --word_timestamps True --output_format json --output_dir DIR
    uv run --with numpy python media/debreath.py NARRATION.wav DIR/NARRATION.json CLEAN.wav [TIMELINE.json CLIPS_DIR]

Pauses inside a line: cut only after 40 ms below -45 dB, so word endings stay whole. With a timeline (one voice
clip per scene, as media/build.py writes), also: the breathy exhale after a scene's last word, any inhale before
its first word, and a short fade at both clip edges so nothing stops abruptly. Cut means -30 dB with 15 ms ramps.
It also removes the ~0.13 s burst of near-full-scale noise that Gemini 3.8 Flash TTS left at the end of every clip
(the "scratch" between slides). Used on 4 October for the 4- and 2-minute videos; Whisper hears the same words.
"""
import json
import sys
import wave

import numpy as np

src, words_json, out = sys.argv[1:4]
timeline = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else None
clips = sys.argv[5] if len(sys.argv) > 5 else None
w = wave.open(src); sr = w.getframerate(); ch = w.getnchannels()
x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float).reshape(-1, ch).mean(1) / 32768
words = [x_ for s in json.load(open(words_json))['segments'] for x_ in s.get('words', [])]
hop = int(0.01 * sr); n = len(x) // hop
lev = np.empty(n); hf = np.empty(n); fq = np.fft.rfftfreq(hop * 2, 1 / sr)
for i in range(n):
    seg = np.pad(x[i*hop:i*hop + hop*2], (0, max(0, hop*2 - len(x[i*hop:i*hop + hop*2]))))
    lev[i] = 20*np.log10(np.sqrt(np.mean(seg**2)) + 1e-9)
    S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))); hf[i] = S[fq > 2500].sum() / (S.sum() + 1e-9)
cut = np.zeros(n, bool)
fr = lambda t: max(0, min(n, int(round(t * 100))))
for a, b in zip(words, words[1:]):                      # pauses between words
    i, stop = fr(a['end'] + 0.03), fr(b['start'] - 0.03)
    while i < stop and not np.all(lev[i:i + 4] < -45): i += 1
    for k in range(i, stop):
        if -60 < lev[k] < -26 and (lev[k] < -36 or hf[k] > 0.35):
            cut[k] = True
fades = []
if timeline:
    sc = timeline['scenes']
    for j, s in enumerate(sc):
        nxt = sc[j + 1]['start'] if j + 1 < len(sc) else len(x) / sr
        inside = [wd for wd in words if s['start'] - 0.3 <= wd['start'] < nxt - 0.1]
        if not inside: continue
        first, last = inside[0], inside[-1]
        for k in range(fr(last['end'] + 0.04), fr(min(nxt, last['end'] + 0.6))):     # exhale after the last word
            if hf[k] > 0.55 and lev[k] < -20: cut[k] = True
        for k in range(fr(s['start']), fr(first['start'] - 0.03)):                 # inhale before the first word
            if hf[k] > 0.55 and lev[k] < -30: cut[k] = True
        if clips:
            cw = wave.open(f"{clips}/{s['audio']}"); end = s['start'] + cw.getnframes() / cw.getframerate()
            fades.append((s['start'], end))
bursts = []
if timeline and clips:                                   # Gemini TTS ends every clip with ~0.13 s of loud noise
    for s in timeline['scenes']:
        cw = wave.open(f"{clips}/{s['audio']}"); end = s['start'] + cw.getnframes() / cw.getframerate()
        i = fr(end) - 1; lo = fr(end - 0.4)
        while i > lo and lev[i] > -50: i -= 1           # walk back through the burst to the silence before it
        if i > lo and lev[fr(end) - 3:fr(end)].max() > -30:
            bursts.append((i / 100, end))
g = np.where(cut, 0.03, 1.0)
k = 3; g = np.convolve(np.pad(g, k, mode='edge'), np.ones(2*k+1)/(2*k+1), mode='same')[k:-k]
gain = np.pad(np.repeat(g, hop), (0, len(x)), constant_values=1.0)[:len(x)]
for a, b in fades:                                       # 10 ms in, 40 ms out at every clip edge
    ia, ib = int(a * sr), int(b * sr)
    m = int(0.01 * sr); gain[ia:ia + m] *= np.linspace(0, 1, len(gain[ia:ia + m]))
    m = int(0.04 * sr); seg = gain[max(0, ib - m):ib]; gain[max(0, ib - m):ib] = seg * np.cos(np.linspace(0, np.pi / 2, len(seg)))
for a, b in bursts:                                      # silence the burst outright (it follows near-silence)
    gain[int(a * sr):int(b * sr) + int(0.01 * sr)] = 0.0
y = x * gain
with wave.open(out, 'wb') as o:
    o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr); o.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
runs = np.diff(np.concatenate([[0], cut.astype(int), [0]])); st = np.where(runs == 1)[0]; en = np.where(runs == -1)[0]
print(f"{len(bursts)} end-of-clip noise bursts removed, {sum((e - s) >= 4 for s, e in zip(st, en))} breath stretches turned down, {len(fades)} clip edges faded; "
      f"energy removed {10*np.log10(np.sum((x - y)**2) / np.sum(x**2) + 1e-12):.1f} dB below the narration")
