**Update: certificate-backed lower bounds at 13 sizes from n = 15 to 32, and first point sets for n = 33 to 40**

This extends my comment above: C(21) >= 56 and C(26) >= 68 stand, C(23) goes from 60 to 61, and ten more sizes are added. Same convention as before: lower bounds only, no optimality claim. "Apparently new" means new relative to the public sources I could find on 2026-10-03 (this issue, #4 and #7; the milesandmistakes v1.1.1 release; the Demonstrandum Zenodo bundle; the algal-lab claims file `no-five-on-sphere-frontier.json`; a GitHub and web search), with this repository's issues and the algal-lab claims file re-checked on 2026-10-04. It is not guaranteed priority.

| n | best public value I found | source | new certificate |
|---:|---:|---|---:|
| 15 | 40 | Demonstrandum `cert_n15_m40`, matched by milesandmistakes in this thread | **41** |
| 16 | 42 | Demonstrandum `cert_n16_m42` | **43** |
| 17 | 45 | 0thernet's comment above (2026-09-25) | **46** |
| 21 | 55 | same | **56** (posted above) |
| 23 | 59 | same | **61** (60 above) |
| 24 | 62 | same | **64** |
| 25 | 65 | same | **66** |
| 26 | 67 | same | **68** (posted above) |
| 28 | 71 | algal-lab claims file, round 27 (2026-09-25) | **74** |
| 29 | 75 | same | **76** |
| 30 | 76 | same | **79** |
| 31 | 79 | same | **80** |
| 32 | 82 | same | **84** |

At n = 13, 14, 18, 19, 20, 22 and 27 the same search equals the public values (36, 38, 48, 50, 53, 58, 70) and does not exceed them.

For n = 33 to 40 I found no published point sets, so the only public baseline is the monotone closure of the n = 32 value. First sets from the same search: 86, 90, 91, 94, 96, 98, 100 and 103 points. Only 40 runs were made per size there, so I would read these as under-searched rather than hard.

Certificates, with 0-based coordinates in `{0,...,n-1}^3` and the seed, CPU budget and solver configuration of the run that found each one: https://github.com/hashkanna/mendel-evolve/tree/535aaac2dacdfd7b52285b77fd00945858c86871/results/no5sphere/certificates

**Verification.** Every set passes three independent exact-integer checks over every 5-subset, with zero degenerate 5-subsets and minimum |det| = 2 in each:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants of the 5x5 matrix with rows `[x, y, z, x^2+y^2+z^2, 1]`
- `problems/no5sphere/verify.py`: Bareiss elimination in Python integers
- `results/no5sphere/third_check.py`: for every 4-subset, the integer coefficients of its sphere or plane from 4x4 cofactors, then one dot product per remaining point

Output of the third checker, re-run today (`python results/no5sphere/third_check.py results/no5sphere/certificates/*.json`, pure Python, no dependencies):

```
n15_41.json: n=15 points=41 five_subsets=749398 degenerate=0 min_abs_det=2 -> VALID
n16_43.json: n=16 points=43 five_subsets=962598 degenerate=0 min_abs_det=2 -> VALID
n17_46.json: n=17 points=46 five_subsets=1370754 degenerate=0 min_abs_det=2 -> VALID
n21_56.json: n=21 points=56 five_subsets=3819816 degenerate=0 min_abs_det=2 -> VALID
n23_61.json: n=23 points=61 five_subsets=5949147 degenerate=0 min_abs_det=2 -> VALID
n24_64.json: n=24 points=64 five_subsets=7624512 degenerate=0 min_abs_det=2 -> VALID
n25_66.json: n=25 points=66 five_subsets=8936928 degenerate=0 min_abs_det=2 -> VALID
n26_68.json: n=26 points=68 five_subsets=10424128 degenerate=0 min_abs_det=2 -> VALID
n28_74.json: n=28 points=74 five_subsets=16108764 degenerate=0 min_abs_det=2 -> VALID
n29_76.json: n=29 points=76 five_subsets=18474840 degenerate=0 min_abs_det=2 -> VALID
n30_79.json: n=30 points=79 five_subsets=22537515 degenerate=0 min_abs_det=2 -> VALID
n31_80.json: n=31 points=80 five_subsets=24040016 degenerate=0 min_abs_det=2 -> VALID
n32_84.json: n=32 points=84 five_subsets=30872016 degenerate=0 min_abs_det=2 -> VALID
n33_86.json: n=33 points=86 five_subsets=34826302 degenerate=0 min_abs_det=2 -> VALID
n34_90.json: n=34 points=90 five_subsets=43949268 degenerate=0 min_abs_det=2 -> VALID
n35_91.json: n=35 points=91 five_subsets=46504458 degenerate=0 min_abs_det=2 -> VALID
n36_94.json: n=36 points=94 five_subsets=54891018 degenerate=0 min_abs_det=2 -> VALID
n37_96.json: n=37 points=96 five_subsets=61124064 degenerate=0 min_abs_det=2 -> VALID
n38_98.json: n=38 points=98 five_subsets=67910864 degenerate=0 min_abs_det=2 -> VALID
n39_100.json: n=39 points=100 five_subsets=75287520 degenerate=0 min_abs_det=2 -> VALID
n40_103.json: n=40 points=103 five_subsets=87541245 degenerate=0 min_abs_det=2 -> VALID
```

**How they were found.** The same exact ruin-and-recreate local search in C as before, started from scratch at every size: 100 to 150 seeded runs per size at 90 to 480 CPU-seconds each for n <= 32, and 40 runs at 720 CPU-seconds for n = 33 to 40, about 520 core-hours in total. Every set in the table, and those for n = 33 to 39, came from the variant that builds the set from antipodal pairs about the cube centre (p together with (n-1, n-1, n-1) - p); the sets at n = 15, 16, 23, 30 and 35 carry one extra unpaired point. The n = 40 set is from the unconstrained search.

One observation that may be useful to others. The antipodal constraint moves the average run by only about 0.2 points (+0.22, 95% interval 0.19 to 0.26, averaged over the 13 sizes in the table), but it roughly doubles the fraction of runs that beat the previous public value: 262 of 1,600 runs with it against 136 of 1,600 without, on the same seeds and budgets. Without it the same search reaches 60, 63, 68, 72, 76, 78, 80 and 83 at n = 23, 24, 26, 28, 29, 30, 31 and 32: above the previous values at all eight sizes, equal to the table at n = 26, 29 and 31 and below it at the other five. Per-run scores for both variants are in `results/no5sphere/search_scores.json`, and `results/no5sphere/tail_effect.py` reproduces these counts.

As 0thernet reported for their pipeline, the evolutionary layer of ours contributed nothing measurable here. 39 screenings of LLM-proposed modifications of the search were run with paired seeds and none showed a positive effect whose 95% interval excludes zero (those screens resolve effects down to about 0.2 points, so smaller gains would have been missed). The gain is the fixed local search, the symmetry constraint and compute.

**Disclosure.** These came out of a hackathon project, MendelEvolve (London AI x Science Hackathon, 3 to 4 October 2026). The search code, the checkers and this post were produced with an AI coding agent (Claude) under my direction. No search code from other contributors was read or used; the prose descriptions in this thread were read, and published certificates were used only to validate the checkers. I take responsibility for the claim; it rests on the published coordinates and the exact checkers, not on trust in model output.

Deeper searches (more seeds, longer budgets) are running. If they improve an entry I will edit this comment and say so. Corrections welcome: if anyone knows of an earlier public certificate at or above any of these values, I will amend the table.
