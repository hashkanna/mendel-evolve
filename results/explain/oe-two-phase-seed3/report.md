# What did the evolution add? `explain-oe-seed3`

Problem: Circles in the unit square, maximum sum of radii (AlphaEvolve B.12). Instance n26; best known 2.635983084919.

- initial program: `baselines/openevolve/vendor/openevolve/examples/circle_packing/initial_program.py` (sha256 9d87e817e403)
- evolved program: `baselines/openevolve/runs/two_phase_haiku/seed3/phase2/openevolve_output/best/best_program.py` (sha256 a229b24f335a)
- decomposed by: llm:claude-fable-5-1, 1 session(s), $1.23; everything below the bookend check is measured without an LLM (180 solver runs).

## In short

The initial program scores 0.959765 and the evolved program 2.624480 after the same repair step (strictly feasible, exact evaluator): a gain of +1.664715.
- Without `row_layout` the evolved program scores 0.0003, below the initial program: the other switches fail without it. That is a dependence between switches, not the size of its own contribution (with `slsqp_optimizer` off as well, `row_layout` is worth +1.0855; with `neighbor_radii` off as well, `row_layout` is worth +0.0166).
- Without `slsqp_optimizer` the evolved program loses 0.3490 (21% of the gain) and scores 2.2755.
- No effect when switched off from the evolved program (the score does not move): `refine_shrink`, `refine_expand`.
- Worth less than 1% of the gain each: `neighbor_radii`.
- Added alone to the initial program: `slsqp_optimizer` +1.6415 (99%), `row_layout` +0.6758 (41%), `refine_expand` +0.2776 (17%), `neighbor_radii` +0.0193 (1%), `refine_shrink` -0.0001 (-0%).
- Constants alone (a counterfactual, not what the evolution did): tuning the 3 constant(s) of the initial program with every switch off (40 trials) reaches 1.9338, that is +0.9740 [+0.9740, +0.9740], 59% of the gain.
- No constant of the initial program has a different value in the evolved program: every changed number belongs to new code behind a switch, so the gain is structure, not re-tuning of what was there.

## The bookend check

The decomposition is trusted only as far as this check, which the harness runs itself: on seeds [0, 1] and instance n26, the decomposed solver with every switch off and every allele at its initial value is compared with the initial program, and with every switch on and every allele at its evolved value with the evolved program. Both sides are repaired solutions (the original program run by the same interpreter with `random` and `numpy.random` seeded, its packing passed through the same `repair.py`). It passes when every centre coordinate, every radius and the exact score agree within 1e-09.

- result: **passed** after 1 decomposition session(s); 14 solver runs, including every single-switch configuration
- largest difference, all off versus the initial program: 0.000e+00
- largest difference, all on versus the evolved program: 0.000e+00
- the initial program as returned is invalid under the exact evaluator (sum of radii 0.959764217); repaired it scores 0.959765217
- the evolved program as returned is valid under the exact evaluator (sum of radii 2.624480158); repaired it scores 2.624480158
- warning: 'only refine_shrink off' gives exactly the same solution as its bookend; from that side the switch does nothing (fine if that is what the code really does)
- warning: 'only refine_expand off' gives exactly the same solution as its bookend; from that side the switch does nothing (fine if that is what the code really does)

## Switches

Knockout: all on minus all on with this switch off (what the evolved program loses without it). Alone: all off with this switch on minus all off (what it adds to the initial program by itself). Score units; brackets are 95% paired-bootstrap intervals over seeds.

| switch | what the change does (the decomposer's words) | knockout | share of gain | alone | verdict |
|---|---|---|---|---|---|
| `row_layout` | Start from five horizontal rows (5,5,5,5,6 circles) instead of a centre circle plus two rings; the rows spread the centres evenly, whereas the outer ring is clipped onto the walls. | +2.6242 [+2.6242, +2.6242] | 158% | +0.6758 [+0.6758, +0.6758] | breaks the rest |
| `slsqp_optimizer` | Optimise all centres and radii jointly with SLSQP under no-overlap and in-square constraints; moves the centres, which the initial program never does. | +0.3490 [+0.3490, +0.3490] | 21% | +1.6415 [+1.6415, +1.6415] | carries gain |
| `neighbor_radii` | Set each starting radius to a fixed fraction of the distance to the nearest wall and nearest neighbour instead of scaling pairs down in turn; gives a uniform, strictly feasible start. | +0.0066 [+0.0066, +0.0066] | 0% | +0.0193 [+0.0193, +0.0193] | small gain |
| `refine_shrink` | Post-pass that shrinks overlapping pairs proportionally and caps radii at the wall distance (centres clipped to [0.001, 0.999]); removes the small violations a solver leaves. | +0.0000 [+0.0000, +0.0000] | 0% | -0.0001 [-0.0001, -0.0001] | no effect |
| `refine_expand` | Post-pass that grows each radius to nearly the largest value its neighbours and the walls allow; recovers slack left by margins and by the starting radii. | +0.0000 [+0.0000, +0.0000] | 0% | +0.2776 [+0.2776, +0.2776] | no effect |

Shares need not add up to 100%: switches overlap and depend on each other (next section).

Every arm gave the same score on all 3 seeds: neither program draws random numbers, so each effect is an exact difference and its interval has zero width. The intervals say nothing about other instances or other runs of the evolution.

## Pairs

Synergy = (both on) - (only a on) - (only b on) + (both off), other switches on. Positive: the two only pay off together. Negative: they overlap (each can stand in for the other). The last three columns are relative to the evolved program with both switched off.

| a | b | synergy | a and b together | a without b | b without a |
|---|---|---|---|---|---|
| `row_layout` | `slsqp_optimizer` | +1.5386 [+1.5386, +1.5386] | +1.4345 | +1.0855 | -1.1896 |
| `row_layout` | `neighbor_radii` | +2.6076 [+2.6076, +2.6076] | +0.0232 | +0.0166 | -2.6010 |
| `slsqp_optimizer` | `neighbor_radii` | -0.0005 [-0.0005, -0.0005] | +0.3561 | +0.3495 | +0.0071 |

## Constants

| allele | belongs to | initial | evolved | tuned with switches off |
|---|---|---|---|---|
| `ring_inner_radius` | the initial program | 0.3 | 0.3 | 0.292684 |
| `ring_outer_radius` | the initial program | 0.7 | 0.7 | 0.549293 |
| `clip_margin` | the initial program | 0.01 | 0.01 | 0.0669334 |
| `init_radius_fraction` | neighbor_radii | 0.46 | 0.46 | not tuned |
| `slsqp_maxiter` | slsqp_optimizer | 300 | 300 | not tuned |
| `slsqp_ftol` | slsqp_optimizer | 1e-09 | 1e-09 | not tuned |
| `slsqp_overlap_margin` | slsqp_optimizer | 1e-06 | 1e-06 | not tuned |
| `slsqp_wall_margin` | slsqp_optimizer | 0.001 | 0.001 | not tuned |
| `refine_pair_shrink` | refine_shrink | 0.9994 | 0.9994 | not tuned |
| `refine_wall_shrink` | refine_shrink | 0.9995 | 0.9995 | not tuned |
| `refine_iterations` | refine_expand | 6 | 6 | not tuned |
| `refine_expand_factor` | refine_expand | 0.999 | 0.999 | not tuned |

- Tuning only (every switch off, the initial program's constants tuned by Optuna on seeds [0, 1, 2], confirmed on [100, 101, 102], measured on [1000, 1001, 1002]): +0.9740 [+0.9740, +0.9740], that is 1.9338 against 2.6245 for the evolved program.
- The evolved score split the way Mendel splits a champion: initial program 0.9598, plus +0.9740 that tuning the initial program's own constants could have bought, plus +0.6907 that needs the new structure. The middle term is a counterfactual: it says how much of the gain was within reach of a tuner, not that the evolved program got it that way.

## What could not be separated

- `refine_shrink` + `refine_expand`: Both are phases of the same refinement loop and share its frame: the clip of the centres to [0.001, 0.999], the sweep count (refine_iterations, registered under refine_expand) and the final radius floor of 1e-5 run when either switch is on. The phases themselves are separate, but they interleave inside each sweep, so shrink+expand together is not the same as one after the other.

Differences that are not switches (no effect on the output, or clock logic that was fixed):
- Clock logic replaced by its value in a normal run: the 85 s timeout check after SLSQP (never fires; it would return the starting packing), the time-based sweep count min(6, max(1, int(remaining/5))) = 6 (now the allele refine_iterations), and the per-sweep timeout break in the refinement (never fires).
- phi = (1 + sqrt(5)) / 2 is computed in the evolved layout but never used (the 'golden ratio' layout is a plain row layout); the `count` field of the row configs is also unused.
- The initial program's layout hard-codes n = 26; the decomposed ring layout takes n from the instance and guards the indices, which is identical for n = 26.
- Docstrings, comments, function names, the visualize() function and the __main__ block.
- sum_radii is no longer returned; the wrapper computes the score from the repaired packing.

The decomposer's caveats:
- From the all-on side, switching off refine_shrink alone or refine_expand alone gives exactly the evolved output: after SLSQP has converged with its margins there are no overlaps to shrink, and the expansion's safety factors (about 0.9986 of the free space) never exceed the radii SLSQP already found. The refinement only matters when the packing entering it has slack or violations (e.g. with slsqp_optimizer off).
- refine_iterations is registered under refine_expand but also sets the number of sweeps of refine_shrink.
- Constants of the evolved code left fixed (not alleles): the row layout coordinates, SLSQP variable bounds (centres in [0.005, 0.995], radii in [1e-4, 0.5]), the refinement centre clip 0.001, the overlap threshold 1e-8, the expansion gap 1e-9, the safety factors 0.9996/0.9997, and the radius floors 1e-4 (neighbor_radii) and 1e-5 (refinement).
- ring_inner_radius and ring_outer_radius have no effect when row_layout is on; clip_margin applies to whichever starting layout is active (it does not bind for the row layout at its default).
- Both layouts are written for 26 circles. For n > 26 the extra centres all sit at the clipped origin and coincide (zero radii with the initial radius rule, which the exact evaluator rejects); for n < 26 the layouts are truncated. Measurements on held-out n are therefore not meaningful for the layouts alone.
- Neither program draws random numbers, so the output does not depend on the seed.
- slsqp_optimizer on alone (ring start, no refinement) passed the repair check at default alleles, but with non-default alleles (few iterations, tiny margins) SLSQP may stop at an infeasible point that only the refinement would clean up.

This section is the decomposer's own account and is not measured.

## Limits

- This is one decomposition of several possible ones. Another split into switches would give different rows, and the sizes of effects depend on where the lines are drawn.
- It is only as faithful as the bookend check: the two end points are verified, the configurations in between are the decomposer's reading of the code.
- A knockout is measured with everything else on, `alone` with everything else off; an effect in another context can differ. Pairs are measured only for the top few.
- One instance (n26) and the output of one evolution run. Nothing here says the same switches would matter at another size or in another run.
- Scores are after the repair step, so a switch that only changes how much the repair has to shrink is measured through that.
