# Circle packing champions

The final solvers of two circle-packing runs, copied from `runs/` (which is not in the repository) so the code
behind each idea can be read. Every idea is a switch read from the config; search for its name.

| Run | Solver | The idea that carries the result | Where in `solver.py` |
|---|---|---|---|
| `cp-fable-1` (best known value, 2.635983) | [cp-fable-1-champion/solver.py](cp-fable-1-champion/solver.py) | `slsqp_polish`: knockout effect +1.67 | search `slsqp_polish` |
| `cp-haiku-4` (the live demo) | [cp-haiku-4-champion/solver.py](cp-haiku-4-champion/solver.py) | `local_perturbation`: knockout effect +1.78 | `if cfg.get("local_perturbation", False):` |

In `cp-haiku-4`, `efficient_pair_distances` is a small, real effect (a faster distance loop: about +0.01 at
the run's 10-second budget, +0.05 at the dashboard's 1-second live budget).

One flaw we found while preparing the demo: `cp-haiku-4`'s `vectorized_separation` is listed as a switch, but
the inventor wrote its faster loop into the code unconditionally, so the solver never reads the switch and its
knockout is 0.00 by construction rather than by measurement. The invariance gate cannot catch this (the solver
does behave the same with the switch off); a check that every gene's name is read by the solver would.
