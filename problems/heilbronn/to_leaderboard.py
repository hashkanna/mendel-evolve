#!/usr/bin/env python3
"""Write a certificate's points in the submission format of github.com/tejstead/heilbronn-site.

    python to_leaderboard.py certificate.json OUT_DIR [--credit "Name, Month YYYY"] [--ref TEXT] [--note TEXT]

Creates OUT_DIR/<variant>-nNN/coordinates.txt (one point per line, two plain decimals separated by a
tab, '#' comments) and meta.json ({"ref": ..., "credit": ..., "note": ...}), which is what that
repository's CONTRIBUTING.md asks for under data/sources/external/. The decimal strings are copied
verbatim from the certificate, so the value its checker computes is the one evaluate.py computed.
Nothing is submitted anywhere: this only writes files.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("certificate")
    ap.add_argument("out_dir")
    ap.add_argument("--credit")
    ap.add_argument("--ref", default="mendel (autoresearch-for-discovery) seed solver solvers/heilbronn, "
                                     "London AI x Science Hackathon, October 2026")
    ap.add_argument("--note")
    args = ap.parse_args(argv)
    cert = json.loads(Path(args.certificate).read_text())
    spec = importlib.util.spec_from_file_location("heilbronn_evaluate", HERE / "evaluate.py")
    ev = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ev)
    out = ev.evaluate(cert["instance"], cert["solution"])
    if not out["valid"]:
        print(f"refusing to write an invalid point set: {out['detail'].get('reason')}")
        return 1
    shape, n = cert["instance"]["shape"], cert["instance"]["n"]
    target = Path(args.out_dir) / f"{shape}-n{n:02d}"
    target.mkdir(parents=True, exist_ok=True)
    lines = [f"# Heilbronn {shape} n={n}, value {out['detail']['value_decimal']} (exact {out['detail']['value_fraction']})"]
    lines += [f"{x}\t{y}" for x, y in cert["solution"]]
    (target / "coordinates.txt").write_text("\n".join(lines) + "\n")
    meta = {"ref": args.ref[:300]}
    if args.credit:
        meta["credit"] = args.credit[:300]
    if args.note:
        meta["note"] = args.note[:2000]
    (target / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    print(f"wrote {target}/coordinates.txt and meta.json: value {out['detail']['value_decimal']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
