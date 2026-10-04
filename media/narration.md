# Narration for the two videos

Every number here is from `RESULTS.md` as of Sunday 4 October, 06:00. Speak or synthesise the text exactly; do
not add numbers. Scene names say what is on screen.

## Four-minute video (track organisers)

1. **Title slide.** MendelEvolve. It searches for better algorithms, and measures which ideas deserve the credit.
2. **Problem slide.** Evolutionary coding agents such as AlphaEvolve and OpenEvolve mutate whole programs and keep
   the high scorers. They find good algorithms, but afterwards nobody can say which idea produced the result. A
   study of their search traces found that about thirty percent of the lines they add are lines they had deleted
   earlier. They are Darwin without Mendel: selection, but no genes.
3. **Idea slide.** In MendelEvolve, every idea a language model proposes becomes a gene: a named switch in the
   solver, with a stated hypothesis. The language model only invents. Classical search tunes and recombines, with
   no model calls. Then we do what geneticists do. We knock each gene out, on fresh seeds, and measure what the
   solver loses.
4. **Live dashboard, circle packing run; the Knock out button is pressed and the result appears.** This is a real
   run on circle packing, starting from OpenEvolve's own initial program, with no hints. It reached the best known
   value. The ledger lists every idea with its hypothesis and its measured effect. Which idea did it? We press
   knock out. The solver runs again on fresh seeds with that one idea switched off, and loses about one point six
   seven. One idea carries the result.
5. **Results slide.** In one weekend it produced new lower bounds at seventeen sizes of problem sixty from Tao and
   co-authors, no five points on a sphere, each verified by three independent exact checkers.
6. **The 58-point page, scrolling to the check table.** And on problem fifty-nine: fifty-eight points in the
   thirty-two by thirty-two grid with no isosceles triangle, where two papers state that fifty-six is optimal. This
   page checks all thirty thousand eight hundred and fifty-six triples in the browser. DeepMind's own verifier
   accepts both sets, and the question is now on their repository.
7. **"Measured twice" slide, then the record-scale chart page.** Now the honest part, which is the point. We turned
   the knockouts on our own records. The engine's quick screens said evolution had added nothing. That measurement
   was too weak to see a fifth of a point. So we repeated it at record scale: six hundred paired runs per arm, both
   arms in the same container. Three things appeared. One switch of the hand-written seed solver takes the share of
   record-beating runs from ten percent to thirty-four. The solver the engine evolved is a quarter of a point
   better, almost all of it from tuning.
8. **Statement slide.** And the best single idea we found was one the engine had thrown away. A language model
   proposed it in the first generation. The quick screen rejected it. Measured properly, it is worth between zero
   point one nine and zero point three one points, and three of our seventeen records came from searches with it
   switched on.
9. **Limits slide.** What it cannot do yet. Its quick screens are too weak. It selects on the mean, and records
   live in the tail. Showing inventors the ledger did not improve their search in our test. And our own first large
   screen had false positives from hardware differences, which we found, corrected and wrote up.
10. **Ease-of-use slide.** It is easy to pick up. Five outside coding agents each added a new benchmark from the
    documentation alone, in twenty to forty-five minutes.
11. **Closing slide.** MendelEvolve. Evolve ideas, not programs, then measure them at the scale that matters. The
    code, the results and every certificate are public.

## Two-minute video (Iterate platform)

1. **Title slide.** MendelEvolve searches for better algorithms, and measures which ideas deserve the credit.
2. **Problem slide.** Evolutionary coding agents mutate whole programs and keep the high scorers. Afterwards nobody
   can say which idea produced the result.
3. **Idea slide.** Here, every idea a language model proposes becomes a gene: a named switch in the solver. The
   model only invents. Classical search tunes. Then we knock each gene out and measure what the solver loses.
4. **Live dashboard; Knock out is pressed.** This is a real run on circle packing that reached the best known
   value. Which idea did it? We press knock out. On fresh seeds, without this one idea, the solver loses about one
   point six seven.
5. **Results slide, then the 58-point page with its check table.** In one weekend: new lower bounds at seventeen
   sizes of Tao's problem sixty, and fifty-eight points with no isosceles triangle where two papers state
   fifty-six. Every triple is checked right here in the browser.
6. **"Measured twice" slide, then the statement slide.** And the knockouts tell us where results came from. The
   engine's quick screens said evolution had added nothing. At record scale, six hundred paired runs, they were
   wrong: the evolved solver is a quarter of a point better, and the best single idea was one the engine had
   thrown away.
7. **Closing slide.** A framework that tells you where a result came from, and catches itself when its measurement
   was too weak. MendelEvolve.
