# Results

| n | proven upper bound | verified lower bound (this work) | exact C(n) | trivial 4n | public lower bound | how the upper bound was proven |
|---:|---:|---:|---:|---:|---:|---|
| 2 | 4 | 4 | 4 | 8 | - | all 56 five-subsets of {0,1}^3 have zero determinant (the 8 points lie on one sphere); checked exhaustively |
| 3 | 8 | 8 | 8 | 12 | 8 | CP-SAT OPTIMAL on the complete model (364 circle + 342 hyperplane rows), 0.04 s, 3 workers; independently: `sum >= 9` INFEASIBLE in all 4 orbit cases (0.05 s, 1 worker) |
| 4 | 11 | 11 | 11 | 16 | 11 | CP-SAT OPTIMAL on the complete model (3848 circle + 13674 hyperplane rows), 223.54 s, 3 workers |
| 5 | 19 | 14 | open | 20 | 14 | `sum >= 20` INFEASIBLE in all 10 orbit cases (60.15 s solver time, 2115 conflicts) |
| 6 | 24 | - | open | 24 | 18 | none below 4n proven here (`sum >= 23`: 9 of 10 orbit cases refuted, the rest unfinished - not a proof) (`sum >= 24`: 9 of 10 orbit cases refuted, the rest unfinished - not a proof) |

Sets (all re-verified by the exact 5-subset determinant checker):

- n = 2, 4 points: `[[0, 0, 0], [0, 1, 1], [1, 0, 1], [1, 1, 0]]`
- n = 3, 8 points: `[[0, 0, 0], [0, 1, 2], [0, 2, 0], [1, 1, 0], [1, 2, 1], [2, 0, 1], [2, 2, 0], [2, 2, 2]]`
- n = 4, 11 points: `[[0, 3, 0], [0, 3, 3], [1, 0, 0], [1, 0, 2], [1, 2, 3], [2, 0, 0], [2, 1, 2], [2, 2, 1], [3, 1, 1], [3, 1, 3], [3, 2, 3]]`
- n = 5, 14 points: `[[0, 0, 2], [0, 1, 0], [0, 2, 1], [0, 3, 4], [1, 3, 0], [1, 4, 4], [2, 1, 3], [2, 2, 1], [3, 2, 2], [3, 3, 0], [3, 4, 1], [4, 0, 0], [4, 0, 4], [4, 1, 3]]`
