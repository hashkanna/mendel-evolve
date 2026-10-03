**Certificate-backed lower bounds C(21) >= 56, C(23) >= 60, C(26) >= 68**

Following the convention of this thread: lower bounds only, no optimality claim. "Apparently new" means new relative to the public sources I could find on 2026-10-03 (this issue, #4 and #7; the milesandmistakes v1.1.1 release; the Demonstrandum Zenodo bundle; the algal-lab claims file `no-five-on-sphere-frontier.json` as of its 2026-09-25 revision; a GitHub and web search), not guaranteed priority.

| n | best public value I found | source | new certificate |
|---:|---:|---|---:|
| 21 | 55 | 0thernet's comment above (2026-09-25) | **56** |
| 23 | 59 | same | **60** |
| 26 | 67 | same | **68** |

Certificates, with 0-based coordinates in `{0,...,n-1}^3`, are in https://github.com/hashkanna/mendel-evolve/tree/main/results/no5sphere/certificates :

- `n21_56.json`: 56 points, centrosymmetric (28 antipodal pairs about the cube centre)
- `n23_60.json`: 60 points, no symmetry imposed
- `n23_60_centrosymmetric.json`: a second 60-point set, centrosymmetric
- `n26_68.json`: 68 points, centrosymmetric

**Verification.** Each set passes three independent exact-integer checks over every 5-subset (3,819,816, 5,461,512 and 10,424,128 subsets respectively), with zero forbidden determinants and minimum |det| = 2 in each:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants of the 5x5 matrix with rows `[x, y, z, x^2+y^2+z^2, 1]`
- `problems/no5sphere/verify.py`: Bareiss elimination in Python integers
- `results/no5sphere/third_check.py`: for every 4-subset, the integer coefficients of its sphere or plane from 4x4 cofactors, then one dot product per remaining point

To reproduce: `python results/no5sphere/third_check.py results/no5sphere/certificates/*.json` (pure Python, no dependencies, a few minutes).

As a cross-check of the checker itself, the same evaluator reproduces every published value I could download for n = 7 to 32 (the AlphaEvolve notebook, #4, milesandmistakes, Demonstrandum and algal-lab certificates).

**How they were found, and disclosure.** These came out of a hackathon project, MendelEvolve (London AI x Science Hackathon, 3 October 2026). The search is an exact ruin-and-recreate local search in C, written from scratch by an AI coding agent (Claude) inside that project. No search code from other contributors was read or used; the prose descriptions in this thread were read, and published certificates were used only to validate the checker. Each set is the best of 24 seeded runs of 120 CPU-seconds at that grid size, and each certificate records its seed and configuration. The checkers and this post were AI-assisted as well. I directed the work and take responsibility for the claim; it rests on the published coordinates and the exact checkers, not on trust in model output.

Larger searches across n = 13 to 40 are running. I will post any further certificates as an update here.
