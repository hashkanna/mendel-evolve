#!/usr/bin/env python3
"""Relaxation rows for n=7 (all rich circles + all spheres/planes with >= MIN points).
First self-tests enumerate_big against the complete n=5 enumeration."""
import sys, json, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from no5sphere_exact import enumerate_big, verify_rows, HERE
n = int(sys.argv[1]); MIN = int(sys.argv[2])
d5 = json.load(open(os.path.join(HERE, "rows_n5.json")))
c5, h5 = enumerate_big(5, 8, log=lambda *a: None)
full_big = set(tuple(h) for h in d5["hypers"] if len(h) >= 8)
assert set(c5) == set(tuple(k) for k in d5["circles"]), "circle mismatch"
assert full_big <= set(h5), "big hyperplanes missing"
assert all(len(h) >= 8 for h in h5)
verify_rows(5, c5, h5)
print("self-test on n=5 passed:", len(c5), "circles;", len(h5), "big hyperplanes (incl. circle+1 type);", len(full_big), "in complete list", flush=True)
t = time.time()
c, h = enumerate_big(n, MIN, log=lambda *a: print(*a, flush=True))
verify_rows(n, c, h, sample=20000)
json.dump({"n": n, "min_size": MIN, "circles": c, "hypers": h}, open(os.path.join(HERE, f"rows_n{n}_big{MIN}.json"), "w"))
print("done", len(c), len(h), round(time.time() - t, 1), flush=True)
