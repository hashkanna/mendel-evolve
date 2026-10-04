# MendelEvolve demo videos

Four files, all 1920x1080, 30 fps, H.264 video and AAC audio:

| File | Length | Size | What |
|---|---|---|---|
| `mendelevolve_4min.mp4` | 3:41.93 | 51.6 MB | narrated, captions burned in |
| `mendelevolve_4min_no_voice.mp4` | 3:41.93 | 47.3 MB | same pictures and captions, silent audio track, for recording your own voice |
| `mendelevolve_2min.mp4` | 1:32.57 | 24.6 MB | narrated, captions burned in |
| `mendelevolve_2min_no_voice.mp4` | 1:32.57 | 22.9 MB | same pictures and captions, silent audio track, for recording your own voice |

The script is `narration.md`; the voice and the captions use its text unchanged. The videos, `work/` and `frames/` are not tracked by git.

## How they were built

Everything is driven by `build.py` (the audio and timeline), `steps.py` (pictures and assembly) and `scenes.py` (which picture goes with which sentence, and the timing constants). Run from the repository root, in this order:

```
python3 media/build.py audio                                   # voice, one clip per scene, and the timeline of both videos
uv run --with playwright python media/build.py stills          # slides and site pages as PNG (serves docs/ on 127.0.0.1:8931 while it runs)
uv run --with playwright python media/build.py knockout 4min   # one real take of the live dashboard; presses Knock out once
uv run --with playwright python media/build.py knockout 2min   # the same, timed to the two-minute narration; presses it once
uv run --with playwright python media/build.py captions        # caption bars as transparent PNG
uv run --with playwright python media/build.py assemble        # the four mp4 files (add 4min or 2min to build one)
uv run --with playwright python media/build.py frames          # check frames into media/frames/
uv run --with playwright python media/build.py readme          # this file
```

Needs: ffmpeg and ffprobe in `/opt/homebrew/bin`, Google Chrome (Playwright drives the installed browser, `channel="chrome"`, nothing is downloaded), macOS `say`, the `whisper` command with its `small.en` model already cached (it runs locally and is only used to find when each sentence starts), and the dashboard running at `http://127.0.0.1:8765/?run=cp-fable-1`.

What each step does:

- **audio.** One clip per scene with `say -v Daniel -r 172`, trimmed of silence at both ends and brought to a common loudness. Whisper transcribes each clip with word timings; the script's words are matched to them, and each sentence start is moved to the end of the pause just before it. From this come the caption times, the moment of the button press, the page scrolls and the cuts inside a scene. Scenes are 0.8 s apart (last word to first word); the picture changes in the middle of that gap.
- **stills.** Each slide in `media/slides/` (a copy of the deck's fragments) is wrapped in a minimal page with the two Google Fonts and screenshotted at 3840x2160. The two site pages are screenshotted full length at 3840 px wide: `problem59-n32.html` laid out 1200 px wide, `record-scale.html` 1500 px wide.
- **knockout.** A real screen recording (Playwright video, 1920x1080). The dashboard is laid out at 1536x864 and shown 1.25x larger so that it fills the frame; at the sentence about the ledger the view pushes in on the ledger; an arrow is drawn for the pointer because recorded video has none; the pointer glides to the button and presses it once, 0.3 s into "We press knock out." The step then finds the press inside the recording (the first frame in which the result strip is open) so the clip can be cut to the narration. If the audio is rebuilt and the press moves by more than 0.12 s relative to the start of the scene, `assemble` stops and asks for a new take.
- **captions.** The narration split at sentence ends, and at a comma or colon when a sentence is longer than 112 characters (62 on the title and closing slides, which keep captions to one line because they have text low in the frame). 40 px IBM Plex Sans on a dark band across the bottom 158 px (100 px on the title and closing slides).
- **assemble.** Slides get a slow push-in (0.16% per second, from an 8K upscale so the motion is smooth). Site pages are a moving crop of the tall screenshot. Shots are joined with 0.3 s crossfades, the captions are overlaid, and the video fades from and to black over 0.5 s. The no-voice files copy the video stream and replace the audio with silence.

## Voice

These files use Gemini text-to-speech (`media/tts_gemini.py`, voice Algieba), one call per scene.

## Four-minute video: `mendelevolve_4min.mp4`, 3:41.93 (limit 3:55.00)

The live take shows `+1.66` (1.66 to 1.67), "Switching it off costs 1.66 points", from 4 paired runs; it settled 5.1 s after the press.

| Scene | On screen | Picture | Voice | Voice length |
|---|---|---|---|---|
| 1 | Title slide | slide:cover 0:00.00 to 0:07.67 | 0:00.50 to 0:07.24 | 6.74 s |
| 2 | Problem slide | slide:problem 0:07.67 to 0:33.90 | 0:08.12 to 0:33.45 | 25.33 s |
| 3 | Idea slide | slide:idea 0:33.90 to 0:57.63 | 0:34.33 to 0:57.20 | 22.87 s |
| 4 | Live dashboard, circle packing run; the Knock out button is pressed and the result appears | dash 0:57.63 to 1:23.10; zoom at 1:06.53; press at 1:13.41 | 0:58.07 to 1:22.66 | 24.59 s |
| 5 | Results slide | slide:results 1:23.10 to 1:37.27 | 1:23.54 to 1:36.83 | 13.29 s |
| 6 | The 58-point page, scrolling to the check table | p59:plots-then-table 1:37.27 to 1:59.07; scroll at 1:48.23 | 1:37.71 to 1:58.63 | 20.92 s |
| 7 | "Measured twice" slide, then the record-scale chart page | slide:twice 1:59.07 to 2:12.30; record:chart-then-table 2:12.30 to 2:35.67; scroll at 2:21.23 | 1:59.51 to 2:35.23 | 35.73 s |
| 8 | Statement slide | slide:statement 2:35.67 to 2:57.53 | 2:36.12 to 2:57.09 | 20.98 s |
| 9 | Limits slide | slide:limits 2:57.53 to 3:19.93 | 2:57.97 to 3:19.49 | 21.51 s |
| 10 | Ease-of-use slide | slide:use 3:19.93 to 3:29.53 | 3:20.37 to 3:29.08 | 8.72 s |
| 11 | Closing slide | slide:close 3:29.53 to 3:41.93 | 3:29.96 to 3:40.92 | 10.96 s |

Captions:

| From | To | Text |
|---|---|---|
| 0:00.50 | 0:02.17 | MendelEvolve. |
| 0:02.17 | 0:03.93 | It searches for better algorithms, |
| 0:03.93 | 0:07.53 | and measures which ideas deserve the credit. |
| 0:08.13 | 0:16.23 | Evolutionary coding agents such as AlphaEvolve and OpenEvolve mutate whole programs and keep the high scorers. |
| 0:16.23 | 0:21.93 | They find good algorithms, but afterwards nobody can say which idea produced the result. |
| 0:21.93 | 0:25.17 | A study of their search traces found that about thirty percent |
| 0:25.17 | 0:28.90 | of the lines they add are lines they had deleted earlier. |
| 0:28.90 | 0:33.73 | They are Darwin without Mendel: selection, but no genes. |
| 0:34.33 | 0:39.53 | In MendelEvolve, every idea a language model proposes becomes a gene: |
| 0:39.53 | 0:43.57 | a named switch in the solver, with a stated hypothesis. |
| 0:43.57 | 0:45.70 | The language model only invents. |
| 0:45.70 | 0:50.13 | Classical search tunes and recombines, with no model calls. |
| 0:50.13 | 0:51.80 | Then we do what geneticists do. |
| 0:51.80 | 0:57.50 | We knock each gene out, on fresh seeds, and measure what the solver loses. |
| 0:58.07 | 1:04.63 | This is a real run on circle packing, starting from OpenEvolve's own initial program, with no hints. |
| 1:04.63 | 1:06.53 | It reached the best known value. |
| 1:06.53 | 1:11.17 | The ledger lists every idea with its hypothesis and its measured effect. |
| 1:11.17 | 1:13.10 | Which idea did it? |
| 1:13.10 | 1:14.90 | We press knock out. |
| 1:14.90 | 1:20.63 | The solver runs again on fresh seeds with that one idea switched off, and loses about one point six seven. |
| 1:20.63 | 1:22.97 | One idea carries the result. |
| 1:23.53 | 1:30.67 | In one weekend it produced new lower bounds at seventeen sizes of problem sixty from Tao and co-authors, |
| 1:30.67 | 1:37.13 | no five points on a sphere, each verified by three independent exact checkers. |
| 1:37.70 | 1:44.87 | And on problem fifty-nine: fifty-eight points in the thirty-two by thirty-two grid with no isosceles triangle, |
| 1:44.87 | 1:48.83 | where two papers state that fifty-six is optimal. |
| 1:48.83 | 1:53.73 | This page checks all thirty thousand eight hundred and fifty-six triples in the browser. |
| 1:53.73 | 1:58.93 | DeepMind's own verifier accepts both sets, and the question is now on their repository. |
| 1:59.50 | 2:02.50 | Now the honest part, which is the point. |
| 2:02.50 | 2:05.53 | We turned the knockouts on our own records. |
| 2:05.53 | 2:09.10 | The engine's quick screens said evolution had added nothing. |
| 2:09.10 | 2:12.50 | That measurement was too weak to see a fifth of a point. |
| 2:12.50 | 2:19.97 | So we repeated it at record scale: six hundred paired runs per arm, both arms in the same container. |
| 2:19.97 | 2:21.83 | Three things appeared. |
| 2:21.83 | 2:25.57 | One switch of the hand-written seed solver takes the share |
| 2:25.57 | 2:29.27 | of record-beating runs from ten percent to thirty-four. |
| 2:29.27 | 2:35.53 | The solver the engine evolved is a quarter of a point better, almost all of it from tuning. |
| 2:36.10 | 2:40.73 | And the best single idea we found was one the engine had thrown away. |
| 2:40.73 | 2:44.23 | A language model proposed it in the first generation. |
| 2:44.23 | 2:46.37 | The quick screen rejected it. |
| 2:46.37 | 2:52.70 | Measured properly, it is worth between zero point one nine and zero point three one points, |
| 2:52.70 | 2:57.40 | and three of our seventeen records came from searches with it switched on. |
| 2:57.97 | 3:00.20 | What it cannot do yet. |
| 3:00.20 | 3:02.73 | Its quick screens are too weak. |
| 3:02.73 | 3:07.60 | It selects on the mean, and records live in the tail. |
| 3:07.60 | 3:12.20 | Showing inventors the ledger did not improve their search in our test. |
| 3:12.20 | 3:16.73 | And our own first large screen had false positives from hardware differences, |
| 3:16.73 | 3:19.80 | which we found, corrected and wrote up. |
| 3:20.37 | 3:21.53 | It is easy to pick up. |
| 3:21.53 | 3:26.53 | Five outside coding agents each added a new benchmark from the documentation alone, |
| 3:26.53 | 3:29.40 | in twenty to forty-five minutes. |
| 3:29.97 | 3:31.93 | MendelEvolve. |
| 3:31.93 | 3:34.30 | Evolve ideas, not programs, |
| 3:34.30 | 3:36.87 | then measure them at the scale that matters. |
| 3:36.87 | 3:41.23 | The code, the results and every certificate are public. |

## Two-minute video: `mendelevolve_2min.mp4`, 1:32.57 (limit 1:58.00)

The live take shows `+1.67` (1.67 to 1.67), "Switching it off costs 1.67 points", from 4 paired runs; it settled 4.7 s after the press.

| Scene | On screen | Picture | Voice | Voice length |
|---|---|---|---|---|
| 1 | Title slide | slide:cover 0:00.00 to 0:06.67 | 0:00.50 to 0:06.22 | 5.72 s |
| 2 | Problem slide | slide:problem 0:06.67 to 0:17.07 | 0:07.10 to 0:16.63 | 9.54 s |
| 3 | Idea slide | slide:idea 0:17.07 to 0:32.83 | 0:17.51 to 0:32.39 | 14.88 s |
| 4 | Live dashboard; Knock out is pressed | dash 0:32.83 to 0:49.67; zoom at 0:36.96; press at 0:40.59 | 0:33.27 to 0:48.21 | 14.94 s |
| 5 | Results slide, then the 58-point page with its check table | slide:results 0:49.67 to 0:55.53; p59:plots-then-table 0:55.53 to 1:04.50; scroll at 1:00.54 | 0:50.09 to 1:04.06 | 13.97 s |
| 6 | "Measured twice" slide, then the statement slide | slide:twice 1:04.50 to 1:18.87; slide:statement 1:18.87 to 1:22.97 | 1:04.94 to 1:22.52 | 17.57 s |
| 7 | Closing slide | slide:close 1:22.97 to 1:32.57 | 1:23.40 to 1:31.56 | 8.16 s |

Captions:

| From | To | Text |
|---|---|---|
| 0:00.50 | 0:03.03 | MendelEvolve searches for better algorithms, |
| 0:03.03 | 0:06.50 | and measures which ideas deserve the credit. |
| 0:07.10 | 0:12.57 | Evolutionary coding agents mutate whole programs and keep the high scorers. |
| 0:12.57 | 0:16.93 | Afterwards nobody can say which idea produced the result. |
| 0:17.50 | 0:24.27 | Here, every idea a language model proposes becomes a gene: a named switch in the solver. |
| 0:24.27 | 0:25.77 | The model only invents. |
| 0:25.77 | 0:28.40 | Classical search tunes. |
| 0:28.40 | 0:32.70 | Then we knock each gene out and measure what the solver loses. |
| 0:33.27 | 0:38.57 | This is a real run on circle packing that reached the best known value. |
| 0:38.57 | 0:40.30 | Which idea did it? |
| 0:40.30 | 0:42.30 | We press knock out. |
| 0:42.30 | 0:48.50 | On fresh seeds, without this one idea, the solver loses about one point six seven. |
| 0:50.10 | 0:55.57 | In one weekend: new lower bounds at seventeen sizes of Tao's problem sixty, |
| 0:55.57 | 1:01.13 | and fifty-eight points with no isosceles triangle where two papers state fifty-six. |
| 1:01.13 | 1:04.37 | Every triple is checked right here in the browser. |
| 1:04.93 | 1:08.33 | And the knockouts tell us where results came from. |
| 1:08.33 | 1:12.13 | The engine's quick screens said evolution had added nothing. |
| 1:12.13 | 1:18.87 | At record scale, six hundred paired runs, they were wrong: the evolved solver is a quarter of a point better, |
| 1:18.87 | 1:22.83 | and the best single idea was one the engine had thrown away. |
| 1:23.40 | 1:26.27 | A framework that tells you where a result came from, |
| 1:26.27 | 1:30.10 | and catches itself when its measurement was too weak. |
| 1:30.10 | 1:31.87 | MendelEvolve. |

## Checks made

- `ffprobe` on each file: 1920x1080, 30 fps, H.264 and AAC, lengths as in the table above.
- One frame per shot (three for the dashboard, two for each scrolling page) is in `media/frames/`; each was looked at for borders, cut-off text and captions covering content.
- Every scene's picture starts before its voice and ends after it (asserted when this file is written).
- The slide footnotes sit under the caption band while a caption is showing; they are visible only in the gaps between scenes.

## The film (`media/film/`)

A three-minute motion-graphics version, every frame drawn in code from the real data: the circle packing
climbing from 0.959 to 2.635983 and falling back when `slsqp_polish` is knocked out (the solver's own runs), the
85-point set for problem 60 with spheres through four of its points, the 58-point set for problem 59 and the
record-scale effect table. The narration is in `media/film/script.py`, one Gemini clip per sentence, and the
visuals are cued to those sentences. The score and the effects are synthesised in `build_film.py`.

    python3 media/film/build_film.py voice
    uv run --with numpy --with scipy python media/film/build_film.py data FOLDER   # FOLDER holds cp_on.json, cp_off.json
    python3 media/film/build_film.py timeline
    uv run --with playwright python media/film/build_film.py render 6
    uv run --with numpy --with scipy python media/film/build_film.py audio
    python3 media/film/build_film.py mux          # media/mendelevolve_film.mp4

`cp_on.json` and `cp_off.json` come from running the circle-packing champion
(`runs/cp-fable-1/trunk/gen002/solver.py`, seed 1000, 10 seconds) with `slsqp_polish` on and off.
