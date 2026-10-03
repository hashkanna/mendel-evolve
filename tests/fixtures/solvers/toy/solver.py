"""Toy solver for Mendel's tests. Fast, deterministic under --iters, with known ground truth.

Each of the n entries ends up as the largest of its random draws from 0..ceiling, so the score climbs
towards the ceiling. Ground truth, in score units at a long budget:

  boost         +10   helpful everywhere
  noop            0   useless (never read)
  left + right   +8   only when both are on; nothing alone
  small_trick    +6   only when n <= 6 (the training instances)
  step          -40 * (step - 0.7)^2   optimum at 0.7; the default 0.2 costs 10
"""
import argparse
import json
import random
import time


def ceiling(cfg, n):
    cap = 40.0
    if cfg["boost"]:
        cap += 10.0
    if cfg["left"] and cfg["right"]:
        cap += 8.0
    if cfg["small_trick"] and n <= 6:
        cap += 6.0
    cap -= 40.0 * (cfg["step"] - 0.7) ** 2
    # HOOK
    return min(max(cap, 1.0), 100.0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--instance", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--time", type=float)
    ap.add_argument("--iters", type=int)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    with open(args.config) as f:
        cfg = json.load(f)
    with open(args.instance) as f:
        n = json.load(f)["n"]

    rng = random.Random(args.seed * 7919 + n)
    cap = ceiling(cfg, n)
    best = [0] * n
    total = 0
    trace = []
    start = time.process_time()
    iters = 0
    while True:
        if args.iters is not None:
            if iters >= args.iters:
                break
        elif time.process_time() - start >= args.time:
            break
        i = rng.randrange(n)
        v = int(cap * rng.random())
        if v > best[i]:
            total += v - best[i]
            best[i] = v
            trace.append([round(time.process_time() - start, 6), total / n])
        iters += 1

    with open(args.out, "w") as f:
        json.dump({"solution": best, "stats": {"iters": iters, "trace": trace}}, f)


if __name__ == "__main__":
    main()
