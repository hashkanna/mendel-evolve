# MendelEvolve: pitch, demo flow, video scripts, submission email

Numbers in [brackets] are filled in from `RESULTS.md` once the overnight runs finish. Everything else is final.

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
3. **What it did in 20 hours.** [Five] apparently new lower bounds on Tao et al.'s problem 60, each verified by three
   independent exact checkers and posted on DeepMind's record thread. On problem 59, three 58-point sets in the
   32 x 32 grid where the literature reports 56 as optimal. On circle packing, Fable inventors took OpenEvolve's
   own weak starting program to the best known value with no hints, and the ledger says exactly which ideas did it.
4. **The honest part.** On problem 60 the records came from the from-scratch seed solver plus compute; ten evolved
   ideas added nothing measurable, and the ledger says so. We also pointed MendelEvolve at a program that
   OpenEvolve itself evolved: one switch, the SLSQP optimiser its prompt recommends by name, carries 99% of the
   gain. A framework that can tell you when evolution did nothing is the point.

## The 90-second live demo

Open http://127.0.0.1:8765 (or the public snapshots at https://hashkanna.github.io/mendel-evolve/).

1. **Circle packing run with Fable inventors** (`cp-fable-1`), 15 s. Header: best known reached, 8 LLM calls,
   dollars. Timeline: the step where each idea joined.
2. **Gene ledger**, 25 s. Read two rows aloud: name, hypothesis in plain words, knockout effect with its interval,
   `general` label. Point at "what did not work", collapsed at the bottom: rejected ideas with their measured
   effect. Say: every row is an experiment, not an opinion.
3. **Knock out live**, 20 s. Press "Knock out" on the top idea. Dots appear per paired seed; the effect and interval
   settle. Say: this is a fresh experiment on new seeds, not a replay.
4. **Typed-in idea**, 15 s. Switch to `cp-haiku-hint`: OpenEvolve's phase 2 hint, typed into the idea box by a
   person, became a gene and measured [+0.38, interval 0.36 to 0.41]. Judges can type one too.
5. **Explain another system's result**, 15 s. Open `explain-oe-two-phase-seed3`: OpenEvolve's evolved program cut
   into five switches, bookend check passed bit for bit, SLSQP alone 99% of the gain, two components do nothing.

Backup if the live server misbehaves: the same pages are static HTML in `docs/`.

## Research efficiency (the fourth judging area)

- LLM calls scale with ideas, not evaluations: [N] calls for [M] evaluations across the main runs.
- Circle packing: Fable inventors reached the best known value for [$10.95] and 8 calls. Five Haiku runs with no
  hints: [range] for [$ range]. OpenEvolve (its own two-phase recipe, same model, same strict evaluator): phase 1
  plateau 2.17 to 2.29 for about $2.90 per seed; phase 2, whose prompt names the SLSQP technique, [final numbers].
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
- **Problem 60 attribution is inconclusive; is that a failure?** It is the finding. Scores are small integers,
  the seed solver plateaus in seconds, and ten LLM ideas moved the mean by fractions of a point. The honest
  decomposition is: seed solver and compute set the records; evolution added nothing there. On problem 59 and
  circle packing the same machinery gives clean, large, interacting effects.
- **Why should we believe the records?** Three independent exact checkers over every 5-subset (int64 determinants,
  Bareiss elimination, cofactor-plus-dot-product), certificates public, posted on DeepMind's thread with
  provenance. For problem 59, DeepMind's own notebook verifier accepts the sets.
- **Reusable?** Five problem packs in the repo (C and Python solvers), a protocol document, and five Devin
  sessions given only the README each added a new benchmark [outcome].

## Video script, 4 minutes (track submission)

0:00 Title card: MendelEvolve. Genetics for algorithm discovery.
0:05 "Evolutionary coding agents mutate programs and keep the winners. Afterwards nobody can say which idea
     produced the result. They are Darwin without Mendel."
0:20 Diagram: invent, gate, screen, merge, tune, knock out, generalise. One sentence each.
0:55 Screen: the ledger on circle packing. Read one row. Press Knock out. Watch the dots land.
1:30 Screen: the idea box. "A person typed OpenEvolve's own hint in. It became a gene. It measured [+0.38]."
1:50 Screen: explain page. "We pointed it at a program OpenEvolve evolved. One switch is 99% of the gain."
2:15 Screen: records strip on problem 60, then the DeepMind thread. "[Five] apparently new lower bounds, three
     independent exact checkers each, posted with provenance."
2:40 Screen: problem 59 point set. "58 points where the literature says 56 is optimal. We raised it as a
     discrepancy to be understood, not a correction."
3:00 "What it cost": the efficiency tile. LLM calls, dollars, evaluations, cost per kept idea.
3:20 "What it cannot do yet": whole-program rewrites, noisy integer objectives, one decomposition among several.
3:40 "Next": transfer of proven genes across problems, best-of-k objectives for record hunting, more problems
     through the protocol. Repo and site URLs.

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
the hackathon it produced [five] apparently new lower bounds on Tao et al.'s problem 60 (verified by three
independent exact checkers, posted on DeepMind's record thread), 58-point isosceles-free sets in the 32 x 32 grid
where 56 was reported optimal, reached the best known circle packing value from OpenEvolve's initial program with
no hints, and, applied to a program OpenEvolve itself evolved, showed that one switch carries 99% of its gain.
Five problem packs, a protocol for adding more, and a dashboard with live knockouts are in the repo.
