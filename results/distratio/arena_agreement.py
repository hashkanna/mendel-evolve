import json, math, subprocess, sys, tempfile
sys.path.insert(0, "problems/distratio")
import evaluate as ev
print("n8 closed form", repr(1/(2-2*math.cos(math.pi/7))), "d3n8", repr(1+math.sqrt(2)))
arena = json.load(open("results/distratio/arena/best_problem5_top3.json"))
ae = json.load(open("results/distratio/alphaevolve_constructions.json"))
cases = [(f"arena id {s['id']} ({s['agentName']})", {"n": 16, "d": 2}, s["data"]["vectors"], s["score"]) for s in arena]
cases += [("AlphaEvolve 2D", {"n": 16, "d": 2}, ae["construction_1"], 12.889266112),
          ("AlphaEvolve 3D", {"n": 14, "d": 3}, ae["construction_2"], 4.165849767)]
for name, inst, sol, published in cases:
    r = ev.evaluate(inst, sol)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"instance": inst, "score": r["score"], "solution": sol}, f)
    v = subprocess.run([sys.executable, "problems/distratio/verify.py", f.name], capture_output=True, text=True)
    print(f"{name}: valid={r['valid']} score={r['score']!r} published={published!r} "
          f"bit-equal={r['score'] == published} exact={r['detail'].get('exact')!r}\n   verify.py: {v.stdout.strip()[:160]}")
good = arena[0]["data"]["vectors"]
bad = {
  "not a list": 5, "wrong count": good[:15], "3 coords": [p + [0] for p in good], "nan": [[float("nan"), 0]] + good[1:],
  "inf": [[float("inf"), 0]] + good[1:], "string": [["1", "2"]] + good[1:], "bool": [[True, 0]] + good[1:],
  "duplicate": [good[0]] + good[:15], "near dup": [[good[1][0] + 1e-13, good[1][1]]] + good[1:], "huge": [[1e200, 0]] + good[1:],
  "None": None, "dict wrong": {"x": 1},
}
for k, sol in bad.items():
    r = ev.evaluate({"n": 16, "d": 2}, sol); print(f"  {k:10s} valid={r['valid']} {r['detail'].get('reason')}")
for inst in ({}, {"n": "16"}, {"n": 16, "d": True}, None, {"n": 10**9}):
    r = ev.evaluate(inst, good); print(f"  inst {inst!r}: valid={r['valid']} {r['detail'].get('reason')}")
print("arena dict format:", ev.evaluate({"n": 16}, arena[0]["data"])["score"], ev.instance_key({"n": 16}), ev.instance_key({"n": 14, "d": 3}))
