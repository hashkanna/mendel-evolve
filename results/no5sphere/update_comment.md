**Certificate-backed lower bounds at 17 sizes from n = 15 to 32, and point sets for n = 33 to 40**

*Edited on 2026-10-04 with the results of deeper searches: the entries for n = 15, 16, 19, 20, 22, 23, 26, 27, 30, 31, 32, 38, 39, 40 are new or improved since this comment was first posted. Everything below is the current state.*

This extends my comment above. Same convention as before: lower bounds only, no optimality claim. "Apparently new" means new relative to the public sources I could find on 2026-10-03 (this issue, #4 and #7; the milesandmistakes v1.1.1 release; the Demonstrandum Zenodo bundle; the algal-lab claims file `no-five-on-sphere-frontier.json`; a GitHub and web search), with this repository's issues and the algal-lab claims file re-checked on 2026-10-04. It is not guaranteed priority.

| n | best public value I found | source | new certificate | found by |
|---:|---:|---|---:|---|
| 15 | 40 | Demonstrandum `cert_n15_m40`, matched by milesandmistakes in this thread | **42** (was 41 when first posted) | variant A |
| 16 | 42 | Demonstrandum `cert_n16_m42` | **44** (was 43 when first posted) | variant A |
| 17 | 45 | 0thernet's comment above (2026-09-25) | **46** | base search |
| 19 | 50 | 0thernet's comment above (2026-09-25) | **51** (new size) | variant A |
| 20 | 53 | 0thernet's comment above (2026-09-25) | **54** (new size) | base search |
| 21 | 55 | 0thernet's comment above (2026-09-25) | **56** | base search |
| 22 | 58 | 0thernet's comment above (2026-09-25) | **59** (new size) | variant A |
| 23 | 59 | 0thernet's comment above (2026-09-25) | **62** (was 61 when first posted) | variant C (layer_ruin) |
| 24 | 62 | 0thernet's comment above (2026-09-25) | **64** | base search |
| 25 | 65 | 0thernet's comment above (2026-09-25) | **66** | base search |
| 26 | 67 | 0thernet's comment above (2026-09-25) | **70** (was 68 when first posted) | variant B |
| 27 | 70 | algal-lab claims file, round 27 (2026-09-25) | **72** (new size) | base search |
| 28 | 71 | algal-lab claims file, round 27 (2026-09-25) | **74** | base search |
| 29 | 75 | algal-lab claims file, round 27 (2026-09-25) | **76** | base search |
| 30 | 76 | algal-lab claims file, round 27 (2026-09-25) | **80** (was 79 when first posted) | variant B |
| 31 | 79 | algal-lab claims file, round 27 (2026-09-25) | **82** (was 80 when first posted) | variant C (region_kick) |
| 32 | 82 | algal-lab claims file, round 27 (2026-09-25) | **85** (was 84 when first posted) | variant B |

At n = 13, 14, 18 the searches equal the public values (36, 38, 48) and do not exceed them.

For n = 33 to 40 I found no published point sets, so the only public baseline is the monotone closure of the n = 32 value. Sets from the same searches: 86, 90, 91, 94, 96, 99, 102, 104 points. Far fewer runs were made at these sizes, so I would read them as under-searched rather than hard.

Certificates, with 0-based coordinates in `{0,...,n-1}^3` and the seed, CPU budget and solver configuration of the run that found each one: https://github.com/hashkanna/mendel-evolve/tree/b8d6f668243bcde36188f31e933f9a7268cbe1d7/results/no5sphere/certificates

**Verification.** Every set passes three independent exact-integer checks over every 5-subset, with zero degenerate 5-subsets and minimum |det| = 2 in each:

- `problems/no5sphere/evaluate.py`: vectorised int64 determinants of the 5x5 matrix with rows `[x, y, z, x^2+y^2+z^2, 1]`
- `problems/no5sphere/verify.py`: Bareiss elimination in Python integers
- `results/no5sphere/third_check.py`: for every 4-subset, the integer coefficients of its sphere or plane from 4x4 cofactors, then one dot product per remaining point

Output of the third checker on the files in the table (pure Python, no dependencies):

```
n15_42.json: n=15 points=42 five_subsets=850668 degenerate=0 min_abs_det=2 -> VALID
n16_44.json: n=16 points=44 five_subsets=1086008 degenerate=0 min_abs_det=2 -> VALID
n17_46.json: n=17 points=46 five_subsets=1370754 degenerate=0 min_abs_det=2 -> VALID
n19_51.json: n=19 points=51 five_subsets=2349060 degenerate=0 min_abs_det=2 -> VALID
n20_54.json: n=20 points=54 five_subsets=3162510 degenerate=0 min_abs_det=2 -> VALID
n21_56.json: n=21 points=56 five_subsets=3819816 degenerate=0 min_abs_det=2 -> VALID
n22_59.json: n=22 points=59 five_subsets=5006386 degenerate=0 min_abs_det=2 -> VALID
n23_62.json: n=23 points=62 five_subsets=6471002 degenerate=0 min_abs_det=2 -> VALID
n24_64.json: n=24 points=64 five_subsets=7624512 degenerate=0 min_abs_det=2 -> VALID
n25_66.json: n=25 points=66 five_subsets=8936928 degenerate=0 min_abs_det=2 -> VALID
n26_70.json: n=26 points=70 five_subsets=12103014 degenerate=0 min_abs_det=2 -> VALID
n27_72.json: n=27 points=72 five_subsets=13991544 degenerate=0 min_abs_det=2 -> VALID
n28_74.json: n=28 points=74 five_subsets=16108764 degenerate=0 min_abs_det=2 -> VALID
n29_76.json: n=29 points=76 five_subsets=18474840 degenerate=0 min_abs_det=2 -> VALID
n30_80.json: n=30 points=80 five_subsets=24040016 degenerate=0 min_abs_det=2 -> VALID
n31_82.json: n=31 points=82 five_subsets=27285336 degenerate=0 min_abs_det=2 -> VALID
n32_85.json: n=32 points=85 five_subsets=32801517 degenerate=0 min_abs_det=2 -> VALID
n33_86.json: n=33 points=86 five_subsets=34826302 degenerate=0 min_abs_det=2 -> VALID
n34_90.json: n=34 points=90 five_subsets=43949268 degenerate=0 min_abs_det=2 -> VALID
n35_91.json: n=35 points=91 five_subsets=46504458 degenerate=0 min_abs_det=2 -> VALID
n36_94.json: n=36 points=94 five_subsets=54891018 degenerate=0 min_abs_det=2 -> VALID
n37_96.json: n=37 points=96 five_subsets=61124064 degenerate=0 min_abs_det=2 -> VALID
n38_99.json: n=38 points=99 five_subsets=71523144 degenerate=0 min_abs_det=2 -> VALID
n39_102.json: n=39 points=102 five_subsets=83291670 degenerate=0 min_abs_det=2 -> VALID
n40_104.json: n=40 points=104 five_subsets=91962520 degenerate=0 min_abs_det=2 -> VALID
```

**How they were found.** One exact ruin-and-recreate local search in C, started from scratch at every size, in three variants. Every set is built from antipodal pairs about the cube centre (p together with (n-1, n-1, n-1) - p), some with one extra unpaired point.

- *Base search:* 100 to 500 seeded runs per size at 90 to 720 CPU-seconds.
- *Variant A:* the same code with constants tuned by an automatic tuner (far fewer restarts: a kick only after about 30,000 steps without improvement, instead of 3,000), plus two small modifications that did not measurably matter.
- *Variant B:* after each ruin, the hole is refilled several times and the best refill kept, instead of once. The ruin is the expensive step, so the extra refills are nearly free.
- *Variant C:* a search arm with one other proposed modification switched on. These arms were part of a screen of 30 modifications; the one named found the set, which is not evidence that it helped.

What we measured about why, for anyone searching these sizes. All comparisons use the same seeds, with both arms in the same container, 600 paired runs at n = 23, 26, 28 and 31 and 240 CPU-seconds:

- The antipodal constraint is worth +0.13 points on the mean (95% interval 0.06 to 0.20) and takes the share of runs that beat the previous public value from 10% to 34%.
- Variant B is worth +0.19 (0.11 to 0.28) in one experiment and +0.31 (0.22 to 0.39) in a second.
- Variant A is worth +0.24 (0.18 to 0.29) over the base search without the antipodal constraint, and +0.12 with it.
- Ten other modifications tested the same way gave nothing resolved above +0.03 points.
- A caution we learned the hard way: comparing two searches that ran on different machines can show differences of 0.1 points that are not real. Identical runs on different containers differed by 0.06 on the mean.

Variant B was proposed by an LLM inside an evolutionary pipeline and rejected by that pipeline's own quick screening (48 paired runs of 45 CPU-seconds), which could not resolve effects of this size. As 0thernet reported for their pipeline, the evolutionary layer is not what found these: the sets come from a fixed local search, a symmetry constraint, one refill trick and compute. Per-run scores and the scripts behind these numbers: https://github.com/hashkanna/mendel-evolve/tree/b8d6f668243bcde36188f31e933f9a7268cbe1d7/results/no5sphere/paired_scores.json and https://github.com/hashkanna/mendel-evolve/tree/b8d6f668243bcde36188f31e933f9a7268cbe1d7/results/no5sphere/paired_effects.py.

**Disclosure.** These came out of a hackathon project, MendelEvolve (London AI x Science Hackathon, 3 to 4 October 2026). The search code, the checkers and this post were produced with an AI coding agent (Claude) under my direction. No search code from other contributors was read or used; the prose descriptions in this thread were read, and published certificates were used only to validate the checkers. I take responsibility for the claim; it rests on the published coordinates and the exact checkers, not on trust in model output.

Corrections welcome: if anyone knows of an earlier public certificate at or above any of these values, I will amend the table.
