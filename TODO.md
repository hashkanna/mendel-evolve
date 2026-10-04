# After the hackathon: ideas and open work

Written on 4 October 2026, during the hackathon. Nothing here is needed for the submission.

## A paper, later

Two candidates. Decide between them about a week after the event, once the two threads on DeepMind's
repository have had time to get replies
([problem 60](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/6#issuecomment-5974924530),
[problem 59](https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/10)).

1. **A methods paper on attribution at record scale.** The finding: the same evolved solver looks neutral in
   48 short paired runs and clearly better in 1,600 long ones, and a switch worth a fifth of a point on the mean
   doubles the rate of record-beating runs. It extends
   [Evolution or Illusion?](https://arxiv.org/abs/2609.19799) and
   [What Do Evolutionary Coding Agents Evolve?](https://arxiv.org/abs/2605.20086) with interventions built into
   the search.
2. **A short mathematics note.** C(32) >= 58 for the no-isosceles problem, where two papers state 56, if the
   thread confirms it is not already known; the problem 60 lower bounds could go in the same note.

What either needs before it is worth writing:

- Evidence on more than one problem. The record-scale result rests on problem 60 alone; run the same protocol
  (frozen champion, seeds and sizes the engine never used, a control arm) on problem 59 and circle packing.
- A proper test of the ledger feedback: many more than four runs per arm, more than one problem and model.
- The fix as well as the diagnosis: an engine that selects on the record rate, and a demonstration that this
  changes what it keeps.
- Complete baselines: OpenEvolve has three seeds, five were planned; `mendel explain` has one program.
- Replies on both threads, so that what is new is known before it is claimed.
- A reader from the field: a combinatorialist for the note, someone working on LLM-driven search for the
  methods paper.

What to avoid: rushing it out on the weekend's evidence; describing the records as discoveries made by
evolution (most of the record sets came from the hand-written seed solver); claiming the efficiency idea as new (X-evolve
has it, see the README). Nearly all code and analysis here was written by an AI agent under direction; say so
plainly in anything submitted.

## Framework work the weekend showed is needed

- **Select on the tail.** An objective for screening and tuning based on the rate of runs above a target, or
  best-of-k, next to the mean. `results/no5sphere/tail_effect.py` computes the statistic after the fact.
- **Power where it matters.** Sequential screening: start small, add seed pairs for ideas whose interval still
  spans zero, and state the smallest effect a screen could have detected. Budgets nearer convergence at the
  larger sizes.
- **An untouched final test, built in.** Freeze the champion and evaluate it on reserved seeds and instance
  sizes whose results never reached the inventors. Today the attribution seeds are reused every generation.
- **Activation counters.** The engine now reports how many seed pairs differed; solvers could also report
  how often each gene's branch ran.
- **Record checks in the engine.** It ignores `min_improvement` and does not run `verify.py`; the record search
  does both.
- **From the five usability reports** (see `RESULTS.md`): `mendel check SOLVER` for a seed solver's own
  switches, progress output from `mendel run`, generality labels for switches that are off in the champion,
  CPU-time accounting that is not wall-clock time.

## Experiments left open

- OpenEvolve seeds 4 and 5.
- `mendel explain` on more evolved programs, and a second decomposition of the same program.
- Longer searches at n = 64 and n = 100 on problem 59, where we only equal the published values.
- Whatever the deep screen and the component knockouts of 4 October leave unresolved (see `RESULTS.md`).
