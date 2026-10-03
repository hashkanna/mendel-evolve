# `mendel explain` across OpenEvolve runs (circle packing, n = 26)

Every row is one OpenEvolve program (claude-haiku-4-5, the two-phase recipe) decomposed into named switches by one LLM session and then measured by knockouts with no LLM. Scores are repaired, strictly feasible sums of radii under the exact evaluator (best known 2.635983). The initial program scores 0.959765 in every row. "Top switch alone" is the single switch that adds the most when switched on alone from the initial program; its share is that effect over the gain; "everything else" is the gain minus it, that is what all the other switches add on top of the top one (shares overlap, so the two columns do not describe disjoint parts). "Constants changed" asks whether any numeric constant of the initial program has a different value in the evolved program.

| seed | program | evolved score | gain | top switch alone | share | everything else | constants changed | bookend | decomposition cost |
|---|---|---|---|---|---|---|---|---|---|
| 2 | final best (phase 2 iteration 62 of 100) (sha 7f0fb6c422a4) | 2.613274 | n/a | n/a | n/a | n/a | n/a | not run (running) | $0.00, 0 session(s) |
| 3 | best at the $15 cap (phase 2 iteration 17; the program explained first); decomposition A (effort medium) (sha a229b24f335a) | 2.624480 | +1.6647 | `slsqp_optimizer` +1.6415 | 99% | +0.0232 | no (3 exposed) | passed | $1.23, 1 session(s) |
| 3 | the same program as the row above (sha a229b24f335a) | 2.624480 | n/a | n/a | n/a | n/a | n/a | not run (running) | $0.00, 0 session(s) |

Per-switch detail (knockout = all on minus all on with the switch off; alone = all off with the switch on minus all off; score units):

- **seed 3, `explain-oe-seed3`** (3 seeds; every arm identical across seeds, so intervals have zero width): `row_layout` knockout +2.6242, alone +0.6758; `neighbor_radii` knockout +0.0066, alone +0.0193; `slsqp_optimizer` knockout +0.3490, alone +1.6415; `refine_shrink` knockout +0.0000, alone -0.0001; `refine_expand` knockout +0.0000, alone +0.2776. Tuning the initial program's constants alone: +0.9740 (40 trials).
