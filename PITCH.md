# MendelEvolve: pitch, demo flow, video scripts, submission email

Updated Sunday 04:00. Every number is from `RESULTS.md`. The record count (17 sizes) can still rise while the
last searches finish; check the table at the top of `RESULTS.md` before recording.

## One line

MendelEvolve searches for better algorithms, and measures which ideas deserve the credit.

The hook, if there is room for a second sentence: evolutionary coding agents are Darwin without Mendel, selection
but no genes. MendelEvolve evolves ideas instead of programs, and measures what each idea is worth.

## The 90-second pitch

1. **The problem.** AlphaEvolve, OpenEvolve and CodeEvolve have an LLM mutate whole programs and keep the high
   scorers. They find good algorithms, but afterwards nobody can say which idea produced the result. A study of their
   search traces this year (EvoTrace, arXiv:2605.20086) found that about 30% of the lines they add are lines they
   had previously deleted, and that a high score can come from re-tuned constants or evaluator overfitting
   rather than new structure. A second (arXiv:2609.19799) asks in its title: "evolution or illusion?"
2. **The idea.** In MendelEvolve every idea an LLM proposes becomes a *gene*: a named switch in the solver with a
   stated hypothesis. The LLM only invents genes. Classical search recombines and tunes them, with no LLM calls.
   Then we do what geneticists do: knock each gene out, singly and in pairs, on seeds the tuner never saw, and
   measure what the solver loses. That gives a causal effect per idea, an interaction map, and a test of whether
   each idea generalises to instance sizes it was never selected on. The ledger of measured effects is what the
   next inventors read, and it is the explanation of the result.
3. **What it did in a weekend.** Apparently new lower bounds at 17 sizes of Tao et al.'s problem 60, and first
   point sets for eight more sizes, each verified by three independent exact checkers. On problem 59, two 58-point
   sets in the 32 x 32 grid where the literature states that the optimum is 56. On circle packing, Fable inventors took
   OpenEvolve's own starting program to the best known value with no hints, and the ledger names the one idea
   that did it: knock it out and the score falls by 1.67.
4. **The honest part, which is the point.** We turned the knockouts on our own records. The engine's quick
   screens said evolution had added nothing. That measurement was too weak to see a fifth of a point, so we
   repeated the knockouts at record scale: 600 paired runs per arm, every pair in one container, seeds the
   engine never saw. Three things showed up that the quick screens had missed. One switch of the hand-written
   seed solver takes the share of record-beating runs from 10% to 34%. The solver the engine evolved is worth a
   quarter of a point over the seed solver, nearly all of it from tuning. And one idea from an LLM inventor,
   `multi_recreate`, which the engine had rejected in its first generation, is worth more than anything it kept:
   +0.19 to +0.31 points. On a program that OpenEvolve itself evolved, one switch, the optimiser its prompt
   recommends by name, carries 99% of the gain. A framework that tells you where a result came from, and
   catches itself when its own measurement was too weak, is what this field is missing.

## The 90-second live demo

Open http://127.0.0.1:8765 (or the public snapshots at https://hashkanna.github.io/mendel-evolve/).

The core is two things: one knockout and one verified construction. If time is short, do steps 2, 3 and 6 and
drop the rest.

1. **Circle packing run with Fable inventors** (`cp-fable-1`), 15 s. Header: best known reached, 8 LLM calls,
   dollars. Timeline: the step where each idea joined.
2. **Gene ledger**, 25 s. Read the top row aloud: `slsqp_polish`, its hypothesis in plain words, knockout effect
   +1.67 with its interval, `general` label. Point at "Not kept", collapsed at the bottom: every rejected idea
   with its measured effect, split into measured harmful and unresolved. Say: every row is an experiment, not an
   opinion, and an idea that was not shown to hurt is not called a failure.
3. **Knock out live**, 20 s. Press "Knock out" on `slsqp_polish`. Dots appear per paired seed; the effect and
   interval settle in about five seconds (+1.65 when tested at 01:00). Say: "The AI proposed several ideas.
   Which one mattered? We switch this one off and measure the loss, on fresh seeds, right now. This idea carries
   the result." On the public snapshot the button is not live; show the recorded +1.67 there.
4. **Typed-in idea**, 15 s. Switch to `cp-haiku-hint`: OpenEvolve's phase 2 hint, typed into the idea box by a
   person, became a gene credited to its source and measured +1.44, labelled general. Judges can type one too.
5. **Explain another system's result**, 15 s. Open `explain-oe-two-phase-seed3`: OpenEvolve's evolved program cut
   into five switches, bookend check passed bit for bit, SLSQP alone 99% of the gain, two components do nothing.

   Optional seventh, 15 s, if there is time: https://hashkanna.github.io/mendel-evolve/record-scale.html, every
   tested idea measured twice. Point at `multi_recreate`: orange (quick screen) sits on zero, blue (record
   scale) is clear of it. Say: "The engine threw this idea away. A proper knockout says it is the best one."
6. **One verified construction**, 15 s. Open https://hashkanna.github.io/mendel-evolve/problem59-n32.html: 58
   points in the 32 x 32 grid with no isosceles triangle, where the literature states 56. The page checks every
   triple in the browser as it loads: 58 points, 30,856 triples, 0 violations. Say: "These coordinates are the
   result. Every triple is checked in exact integers, here, now. DeepMind's own verifier accepts them too, and
   the question is on their repository as issue 10." Keep the two examples apart: the knockout shows
   attribution, the construction shows validity, and this set came from the seed solver, not from the
   circle-packing gene.

Backup if the live server misbehaves: the same pages are static HTML in `docs/`.

## Research efficiency (the fourth judging area)

- LLM calls scale with ideas, not evaluations: 399 calls (about $164) for 22,802 evaluations across the nine
  engine runs. The record searches and the deep screen used no LLM calls.
- Circle packing: Fable inventors reached the best known value after $10.95 and 8 calls ($26.07 for the whole
  run). Five Haiku runs with no hints: 2.314 to 2.440 for $6.55 to $8.40 each. OpenEvolve (its own two-phase
  recipe, same model, same strict evaluator): phase 1 plateau 2.17 to 2.29 for about $2.90 per seed; phase 2,
  whose prompt names the SLSQP technique, 2.612 to 2.626, for $7.01 to $7.60 per seed in all. That baseline is
  three seeds; with the hint it costs about the same as our Haiku run with the same hint ($7.60 for 2.620) and
  passes 2.6 early (seed 1 after $2.94). Say so if asked.
- Does showing inventors the measured ledger help? We tested it: same model (Haiku), seed program and budgets,
  four runs with the ledger and four without. No benefit shows (mean final score 0.872 with, 0.903 without,
  not resolved at four runs each), and the ledger costs about a quarter more per run. Its value so far is as
  the explanation, not as a search heuristic. Say this plainly if asked.
- Every evaluation is cached by solver version, config, instance, seed and budget; paired arms run in the same
  container; 100 Modal containers running 8 to 64 jobs each.

## Q&A preparation

- **Is the efficiency trick new?** No, and we say so: X-evolve and LLaMEA-HPO have an LLM write parameterised
  programs that non-LLM search explores. What we have not found elsewhere: interventional attribution inside the
  loop (knockouts of every idea in every champion, singly and in pairs), the forced named-switch representation
  that makes it possible, and per-idea generalisation tests. Component-Aware Feedback and DeltaEvolve keep
  memories of effects, but from parent-child differences, not interventions.
- **What about ideas that need a whole-program rewrite?** They do not fit behind a switch; they would start a
  separate lineage. The invariance gate rejects anything that changes behaviour while off.
- **What did your method itself discover?** On circle packing, the idea that carries the result: Fable
  inventors proposed an SLSQP polish with no hint, and its knockout costs 1.67 on training sizes and 1.5 to 1.9 on held-out
  sizes. On problem 59, a map of which of the seed solver's switches matter and that two of them are worth more
  together (+2.81). On problem 60, two things, both visible only at record scale: a tuned solver that beats the
  seed solver by +0.24 [0.18, 0.29], and an LLM idea, `multi_recreate`, worth +0.19 to +0.31 that the engine
  itself had rejected. Of ten other ideas tested the same way, none is resolved above +0.03.
- **Is "no idea helped" just an underpowered test?** It was, and we measured by how much. The engine's screen
  (48 seed pairs, 45 seconds) resolves about 0.2 points, and everything that matters here is that size or
  smaller. At 600 paired runs in shared containers the noise floor is 0.01, and one of the eleven ideas we
  re-tested is clearly positive. The engine now also reports, for each knockout, how many seed pairs differed at
  all: one kept idea (`kick_escalate`) turned out almost never to have executed in its own knockout.
- **Did you get anything wrong along the way?** Yes, and it is in `RESULTS.md`. Our first deep screen ran each
  idea in its own containers and made eight more ideas look helpful by 0.11 to 0.16. A same-program control
  showed that container hardware alone moves the mean by 0.06, and in the shared-container test none of the
  eight is above +0.08. Pairing has to include the machine.
- **So is the mean the wrong objective?** For record hunting, yes. A record is the best of hundreds of long runs;
  the engine selects on the mean of a few short ones. Selecting on the rate of runs above a target is the first
  thing we would change, and the record-rate analysis in `RESULTS.md` is that statistic computed after the fact.
- **Why should we believe the records?** Three independent exact checkers over every 5-subset (int64 determinants,
  Bareiss elimination, cofactor-plus-dot-product), every set checked all three ways, certificates public.
  All 17 sizes are on DeepMind's record thread with provenance and the checker output
  (https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/6#issuecomment-5974924530). For problem 59, DeepMind's own notebook verifier accepts the sets, the same
  definition reproduces every published value from n = 4 to 10 by exhaustive search, and the result is raised on
  their repository as issue 10 (https://github.com/google-deepmind/alphaevolve_repository_of_problems/issues/10).
- **Reusable?** Ten problem packs in the repo (C and Python solvers) and a protocol document. Five of the ten
  were added by Devin sessions given only the README and the protocol: each wrote a solver and ran the gate, an
  attribution run and a verified record search in about 20 to 45 minutes, and all five are merged. Their reports
  named three gaps in the docs, all fixed.
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
2:15 Screen: records strip on problem 60, then the DeepMind thread. "Apparently new lower bounds at 17 sizes, three
     independent exact checkers each, posted with provenance. And the knockouts say where they came from: one
     switch of the seed solver takes the record rate from 10% to 34%, the engine's tuning adds a quarter of a point, and one
     LLM idea the engine had thrown away turns out to be the best single change." Show record-scale.html.
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
Video (max 4 min): https://youtu.be/zJbiS09MMh8 (YouTube, unlisted; 3:42). The brief asks for a Google Drive link: if the organisers
want that instead, upload `media/mendelevolve_4min.mp4` to Drive and swap the link.
Two-minute video (for the Iterate platform): https://youtu.be/BWDx5ijEeTc
Live demo pages: https://hashkanna.github.io/mendel-evolve/

Short description: MendelEvolve is an autoresearch framework that evolves ideas instead of programs. Every
LLM-proposed idea becomes a named, switchable gene with a stated hypothesis; the LLM only invents, classical
search recombines and tunes, and knockouts (singly, in pairs, on fresh seeds and held-out instance sizes) give a
causal effect per idea. The ledger of measured effects is what the next inventors read, and it explains the result. During
the hackathon it produced apparently new lower bounds at 17 sizes of Tao et al.'s problem 60 (verified by three
independent exact checkers), 58-point isosceles-free sets in the 32 x 32 grid where 56 was reported, and the
best known circle packing value from OpenEvolve's initial program with no hints. Its knockouts also say where
results come from: on problem 60, one switch of the seed solver takes the share of record-beating runs from
10% to 34%, the solver the engine evolved doubles the seed solver's rate (21% against 10%), and one LLM idea
that the engine's quick screen had rejected is worth more than anything it kept; a program OpenEvolve itself
evolved owes 99% of its gain to one switch. Ten problem packs (five added by outside agents from the docs alone), a protocol for adding more, and a
dashboard with live knockouts are in the repo.
