# Text for the YouTube uploads

**Uploaded on 4 October 2026 to the Kannappan Sirchabesan channel, Unlisted:**
four minutes https://youtu.be/zJbiS09MMh8 · two minutes https://youtu.be/BWDx5ijEeTc.
The uploads are 10 MB copies (the browser tool that uploaded them caps files at 10 MB); the full-quality files
are `media/mendelevolve_4min.mp4` and `media/mendelevolve_2min.mp4`. Custom thumbnails were not applied: the
channel needs YouTube's one-off phone verification before it accepts them, and before links in descriptions
become clickable.

Upload as **Unlisted** (anyone with the link can watch; it does not appear on the channel) and answer
"No, it's not made for kids". Switch to Public afterwards if you want it on the channel.
Thumbnails: `media/thumbnail_4min.png` and `media/thumbnail_2min.png` (1280x720; rebuild with
`uv run --with playwright python media/thumbnails.py`).

## Four-minute video: `media/mendelevolve_4min.mp4`

**Title**

MendelEvolve: which idea deserves the credit? Evolving ideas, not programs (4 min)

**Description**

AI systems that evolve programs find good algorithms, but afterwards nobody can say which idea produced the result.
MendelEvolve makes every idea a named switch in the solver. A language model only invents ideas; classical search
tunes them; and knockouts, switching one idea off on fresh seeds, measure what each is worth.

In one weekend it produced new lower bounds at 17 sizes of an open problem from Tao and co-authors, a 58-point set
where two papers state that 56 is optimal, and the best known circle packing from another system's starting
program. Then we turned the knockouts on our own results, and found that the best single idea was one the engine
had thrown away.

Built at the London AI x Science Hackathon, 3 to 4 October 2026 (Track 1: AI Automated Discovery of Algorithms).

Chapters
0:00 What it is
0:08 The problem: selection, but no genes
0:34 Every idea is a gene
0:58 A live knockout on circle packing
1:23 17 new lower bounds on problem 60
1:37 58 points with no isosceles triangle, where 56 was stated
1:59 The same ideas, measured twice
2:36 The best idea was one the engine threw away
2:58 What it cannot do yet
3:20 Ease of use
3:30 Where to find it

Code, results and every certificate: https://github.com/hashkanna/mendel-evolve
Live pages: https://hashkanna.github.io/mendel-evolve/
Each idea measured twice: https://hashkanna.github.io/mendel-evolve/record-scale.html
The 58-point sets, checked in your browser: https://hashkanna.github.io/mendel-evolve/problem59-n32.html

The narration is synthetic speech. The screen recordings are real runs, and every number is from RESULTS.md in the
repository.

## Two-minute video: `media/mendelevolve_2min.mp4`

**Title**

MendelEvolve in two minutes: which idea deserves the credit?

**Description**

MendelEvolve searches for better algorithms, and measures which ideas deserve the credit. Every idea a language
model proposes becomes a named switch in the solver; switching it off on fresh seeds measures what it is worth.

In two minutes: a live knockout on circle packing, new lower bounds on two open problems, and what the knockouts
say about where those results came from.

Built at the London AI x Science Hackathon, 3 to 4 October 2026.

Chapters
0:00 What it is
0:07 The problem
0:17 Every idea is a gene
0:33 A live knockout
0:50 What it found in a weekend
1:05 Where the results came from

Code and results: https://github.com/hashkanna/mendel-evolve
Live pages: https://hashkanna.github.io/mendel-evolve/

The narration is synthetic speech. The screen recordings are real runs.
