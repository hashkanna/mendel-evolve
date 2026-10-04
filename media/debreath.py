"""Turn down breath noise in the pauses of a narration track, using Whisper word timings.

    whisper NARRATION.wav --model base.en --language en --word_timestamps True --output_format json --output_dir DIR
    uv run --with numpy python media/debreath.py NARRATION.wav DIR/NARRATION.json CLEAN.wav

Used on 4 October for media/mendelevolve_4min.mp4: 41 breaths turned down by 30 dB, and Whisper hears the same
531 words before and after.

A pause is only touched after the previous word has died away (60 ms below -42 dB), so word endings stay whole.
"""
import json, sys, wave
import numpy as np

src, words_json, out = sys.argv[1:4]
w = wave.open(src); sr = w.getframerate(); ch = w.getnchannels()
x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(float).reshape(-1, ch).mean(1) / 32768
words = [x_ for s in json.load(open(words_json))['segments'] for x_ in s.get('words', [])]
hop = int(0.01 * sr); n = len(x) // hop
lev = np.empty(n); hf = np.empty(n); fq = np.fft.rfftfreq(hop * 2, 1 / sr)
for i in range(n):
    seg = x[i*hop:i*hop + hop*2]
    seg = np.pad(seg, (0, hop*2 - len(seg)))
    lev[i] = 20*np.log10(np.sqrt(np.mean(seg**2)) + 1e-9)
    S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))); hf[i] = S[fq > 2500].sum() / (S.sum() + 1e-9)
cut = np.zeros(n, bool)
for a, b in zip(words, words[1:]):
    i = int((a['end'] + 0.03) * 100); stop = int((b['start'] - 0.03) * 100)
    while i < stop and not np.all(lev[i:i + 6] < -42): i += 1   # wait for 60 ms of real quiet after the word
    for k in range(i, min(n, stop)):
        if -60 < lev[k] < -26 and (lev[k] < -36 or hf[k] > 0.35):
            cut[k] = True
g = np.where(cut, 0.03, 1.0)
k = 3; g = np.convolve(np.pad(g, k, mode='edge'), np.ones(2*k+1)/(2*k+1), mode='same')[k:-k]
gain = np.pad(np.repeat(g, hop), (0, len(x)), constant_values=1.0)[:len(x)]
y = x * gain
with wave.open(out, 'wb') as o:
    o.setnchannels(1); o.setsampwidth(2); o.setframerate(sr); o.writeframes((np.clip(y, -1, 1) * 32767).astype(np.int16).tobytes())
runs = np.diff(np.concatenate([[0], cut.astype(int), [0]])); starts = np.where(runs == 1)[0]; ends = np.where(runs == -1)[0]
print(f"{sum((e - s) >= 6 for s, e in zip(starts, ends))} stretches of 60 ms or more turned down; "
      f"energy removed {10*np.log10(np.sum((x - y)**2) / np.sum(x**2) + 1e-12):.1f} dB below the narration")
