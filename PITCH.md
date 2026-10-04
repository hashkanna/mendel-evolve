# MendelEvolve: pitch, demo flow, video scripts, submission email

Updated Sunday 01:20. Three results are still running and marked [pending]: the deep screen of every idea, the
evolved solver at record budgets, and the ledger ablation. Every other number is from `RESULTS.md`.

## One line

Evolutionary coding agents are Darwin without Mendel: selection, but no genes. MendelEvolve evolves ideas instead
of programs, and measures what each idea is worth.

## The 90-second pitch

1. **The problem.** AlphaEvolve, OpenEvolve and CodeEvolve have an LLM mutate whole programs and keep the high
   scorers. They find good algorithms, but afterwards nobody can say which idea produced the result. A study of their
   search traces this year found that about 30% of the lines they add are lines they had previously deleted, and
   that a high score can come from re-tuned constants or evaluator overfitting rather than new structure. The
   question in the literature is now "evolution or illusion?"
2. **The idea.** In MendelEvolve every idea an LLM proposes becomes a *gene*: a named switch in the solver with a
   stated hypothesis. The LLM only invents genes. Classical search recombines and tunes them, with no LLM calls.
   Then we do what geneticists do: knock each gene out, singly and in pairs, on seeds the tuner never saw, and
   measure what the solver loses. That gives a causal effect per idea, an interaction map, and a test of whether
   each idea generalises to instance sizes it was never selected on. The ledger of measured effects is what the
   next inventors read, so the search stops repeating itself, and it is also the explanation of the result.
3. **What it did in a weekend.** Apparently new lower bounds at 13 sizes of Tao et al.'s problem 60, and first
   point sets for eight more sizes, each verified by three independent exact checkers. On problem 59, 58-point
   sets in the 32 x 32 grid where the literature reports 56. On circle packing, Fable inventors took
   OpenEvolve's own starting program to the best known value with no hints, and the ledger names the one idea
   that did it: knock it out and the score falls by 1.67.
4. **The honest part, which is the point.** We turned the knockouts on our own records. They did not come from
   evolved ideas. One switch in the hand-written seed solver doubles the share of runs that beat the published
   value (16.4% against 8.5% over 1,600 paired runs) while moving the average by a fifth of a point, too small
   for the engine's quick screens to see. So we screened all 30 evolved ideas again at that scale, 600 runs
   each: [pending]. And on a program that OpenEvolve itself evolved, one switch, the optimiser its prompt
   recommends by name, carries 99% of the gain. A framework that tells you when evolution did nothing, and when
   its own measurement was too weak to know, is what this field is missing.

## The 90-second live demo

Open http://127.0.0.1:8765 (or the public snapshots at https://hashkanna.github.io/mendel-evolve/).

1. **Circle packing run with Fable inventors** (`cp-fable-1`), 15 s. Header: best known reached, 8 LLM calls,
   dollars. Timeline: the step where each idea joined.
2. **Gene ledger**, 25 s. Read the top row aloud: `slsqp_polish`, its hypothesis in plain words, knockout effect
   +1.67 with its interval, `general` label. Point at "Not kept", collapsed at the bottom: every rejected idea
   with its measured effect, split into measured harmful and unresolved. Say: every row is an experiment, not an
   opinion, and an idea that was not shown to hurt is not called a failure.
3. **Knock out live**, 20 s. Press "Knock out" on `slsqp_polish`. Dots appear per paired seed; the effect and
   interval settle in about five seconds (+1.65 when tested at 01:00). Say: this is a fresh experiment on new
   seeds, not a replay.
4. **Typed-in idea**, 15 s. Switch to `cp-haiku-hint`: OpenEvolve's phase 2 hint, typed into the idea box by a
   person, became a gene credited to its source and measured +1.44, labelled general. Judges can type one too.
5. **Explain another system's result**, 15 s. Open `explain-oe-two-phase-seed3`: OpenEvolve's evolved program cut
   into five switches, bookend check passed bit for bit, SLSQP alone 99% of the gain, two components do nothing.

Backup if the live server misbehaves: the same pages are static HTML in `docs/`.

## Research efficiency (the fourth judging area)

- LLM calls scale with ideas, not evaluations: 383 calls ($128) for 21,206 evaluations across the nine engine
  runs (figures at 01:15; `p59` is still running). The record searches and the deep screen used no LLM calls.
- Circle packing: Fable inventors reached the best known value after $10.95 and 8 calls ($26.07 for the whole
  run). Five Haiku runs with no hints: 2.314 to 2.440 for $6.55 to $8.40 each. OpenEvolve (its own two-phase
  recipe, same model, same strict evaluator): phase 1 plateau 2.17 to 2.29 for about $2.90 per seed; phase 2,
  whose prompt names the SLSQP technique, 2.612 to 2.626, for $7.01 to $7.60 per seed in all. That baseline is
  three seeds; with the hint it costs about the same as our Haiku run with the same hint ($7.60 for 2.620) and
  passes 2.6 early (seed 1 after $2.94). Say so if asked.
- Does showing inventors the measured ledger help? Same model, seed program and budgets, with and without the
  ledger: [pending].
- Every evaluation is cached by solver version, config, instance, seed and budget; paired arms run in the same
  container; 100 Modal containers running 8 to 16 jobs each.

## Q&A preparation

- **Is the efficiency trick new?** No, and we say so: X-evolve and LLaMEA-HPO have an LLM write parameterised
  programs that non-LLM search explores. What we have not found elsewhere: interventional attribution inside the
  loop (knockouts of every idea in every champion, singly and in pairs), the forced named-switch representation
  that makes it possible, and per-idea generalisation tests. Component-Aware Feedback and DeltaEvolve keep
  memories of effects, but from parent-child differences, not interventions.
- **What about ideas that need a whole-program rewrite?** They do not fit behind a switch; they would start a
  separate lineage. The invariance gate rejects anything that changes behaviour while off.
- **What did your method itself discover?** On circle packing, the idea that carries the result: Fable
  inventors proposed an SLSQP polish with no hint, and its knockout costs 1.67 on training sizes and on held-out
  sizes. On problem 59, a map of which of the seed solver's switches matter and that two of them are worth more
  together (+3.69). On problem 60, nothing: the records are the seed solver, one of its own switches and compute.
- **Is "no idea helped" just an underpowered test?** It was, and we measured by how much. The engine's screen
  (48 seed pairs, 45 seconds) resolves about 0.2 points. The switch that finds our records is worth 0.22 on the
  mean, so that screen could not have seen it. We reran every idea at 600 paired runs with a control arm:
  [pending]. The engine now also reports, for each knockout, how many seed pairs differed at all: one kept idea
  (`kick_escalate`) turned out never to have executed in its own knockout.
- **So is the mean the wrong objective?** For record hunting, yes. A record is the best of hundreds of long runs;
  the engine selects on the mean of a few short ones. Selecting on the rate of runs above a target is the first
  thing we would change, and the record-rate analysis in `RESULTS.md` is that statistic computed after the fact.
- **Why should we believe the records?** Three independent exact checkers over every 5-subset (int64 determinants,
  Bareiss elimination, cofactor-plus-dot-product), all 21 sets re-checked on Sunday, certificates public. The
  first three are on DeepMind's record thread with provenance; the update with all 13 is written and is posted
  once [the user runs the command in HANDOFF.md]. For problem 59, DeepMind's own notebook verifier accepts the sets.
- **Reusable?** Five problem packs in the repo (C and Python solvers) and a protocol document. Five Devin
  sessions given only the README and the protocol each added a new benchmark, with solver, gate, attribution run
  and a verified record search, in about 20 to 45 minutes. Their reports named three gaps in the docs, all fixed.
- **What is weak?** The OpenEvolve baseline is three seeds. The explain result is one
  program and one decomposition. Attribution seeds are reused across generations, so the final numbers we quote
  for problem 60 come from separate searches on seeds the engine never used.

## Video script, 4 minutes (track submission)

0:00 Title card: MendelEvolve. Genetics for algorithm discovery.
0:05 "Evolutionary coding agents mutate programs and keep the winners. Afterwards nobody can say which idea
     produced the result. They are Darwin without Mendel."
0:20 Diagram: invent, gate, screen, merge, tune, knock out, generalise. One sentence each.
0:55 Screen: the ledger on circle packing. Read one row. Press Knock out. Watch the dots land.
1:30 Screen: the idea box. "A person typed OpenEvolve's own hint in. It became a gene. It measured +1.44."
1:50 Screen: explain page. "We pointed it at a program OpenEvolve evolved. One switch is 99% of the gain."
2:15 Screen: records strip on problem 60, then the DeepMind thread. "Apparently new lower bounds at 13 sizes, three
     independent exact checkers each, posted with provenance. And the knockout says where they came from: one
     switch of the seed solver doubles the record rate. The evolved ideas: [pending]."
2:40 Screen: problem 59 point set. "58 points where the literature says 56 is optimal. We raised it as a
     discrepancy to be understood, not a correction."
3:00 "What it cost": the efficiency tile. LLM calls, dollars, evaluations, cost per kept idea.
3:20 "What it cannot do yet": whole-program rewrites; quick screens miss effects under a fifth of a point; it
     selects on the mean, and records live in the tail.
3:40 "Next": select on the record rate, transfer of proven genes across problems, more problems through the
     protocol. Repo and site URLs.

## Video, 2 minutes (Iterate platform demo)

Cut the 4-minute script to: 0:00 title and one-line problem; 0:15 diagram; 0:40 ledger plus live knockout; 1:15
typed-in idea; 1:30 explain page; 1:45 records strip and URLs.

## Submission email (track organisers)

To: admin@algorithmdiscovery.org
Subject: Track 1 submission: MendelEvolve

Team name: MendelEvolve
Repo: https://github.com/hashkanna/mendel-evolve
Video (max 4 min): [Google Drive link]
Live demo pages: https://hashkanna.github.io/mendel-evolve/

Short description: MendelEvolve is an autoresearch framework that evolves ideas instead of programs. Every
LLM-proposed idea becomes a named, switchable gene with a stated hypothesis; the LLM only invents, classical
search recombines and tunes, and knockouts (singly, in pairs, on fresh seeds and held-out instance sizes) give a
causal effect per idea. The ledger of measured effects steers the next inventors and explains the result. During
the hackathon it produced apparently new lower bounds at 13 sizes of Tao et al.'s problem 60 (verified by three
independent exact checkers), 58-point isosceles-free sets in the 32 x 32 grid where 56 was reported, and the
best known circle packing value from OpenEvolve's initial program with no hints. Its knockouts also say where
results come from: our problem 60 records trace to one switch of the seed solver, which doubles the rate of
record-beating runs, and not to evolved ideas; a program OpenEvolve itself evolved owes 99% of its gain to one
switch. Five problem packs, a protocol for adding more (five outside agents each added a benchmark from the docs
alone), and a dashboard with live knockouts are in the repo.
