"""Writes docs/record-scale.html: each idea measured twice, by the engine's quick screen and at record scale."""

import html

SCREEN, RECORD = "#d95926", "#3987e5"     # categorical slots 2 and 1, validated on the page's dark surface
LO, HI = -0.5, 0.5                         # plotted range, in points


def write(rows: list, path: str) -> None:
    plot = [r for r in rows if r["kind"] in ("reference", "idea") and "noise floor" not in r["label"]]
    floor = next((r for r in rows if "noise floor" in r["label"]), None)
    label_w, plot_w, row_h, top = 300, 520, 36, 34
    width, height = label_w + plot_w + 24, top + row_h * len(plot) + 34

    def x(v: float) -> float:
        return label_w + (max(LO, min(HI, v)) - LO) / (HI - LO) * plot_w

    parts = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Effect of each idea: quick screen and record scale">']
    for tick in (-0.4, -0.2, 0.0, 0.2, 0.4):
        cls = "zero" if tick == 0 else "grid"
        parts.append(f'<line x1="{x(tick):.1f}" y1="{top - 8}" x2="{x(tick):.1f}" y2="{height - 26}" class="{cls}"/>')
        parts.append(f'<text x="{x(tick):.1f}" y="{height - 8}" text-anchor="middle" class="tick">{tick:+.1f}</text>'
                     if tick else f'<text x="{x(tick):.1f}" y="{height - 8}" text-anchor="middle" class="tick">0</text>')
    parts.append(f'<text x="{label_w + plot_w}" y="{top - 16}" text-anchor="end" class="tick">points, idea on minus idea off</text>')
    for i, r in enumerate(plot):
        y = top + row_h * i + row_h / 2
        name = html.escape(r["label"].replace("`", ""))
        cls = "name ref" if r["kind"] == "reference" else "name"
        parts.append(f'<text x="{label_w - 14}" y="{y + 4:.1f}" text-anchor="end" class="{cls}">{name}</text>')
        if i:
            parts.append(f'<line x1="0" y1="{y - row_h / 2:.1f}" x2="{width}" y2="{y - row_h / 2:.1f}" class="sep"/>')
        s = r.get("screen")
        if s and s.get("effect") is not None:
            ys = y - 7
            tip = f"{name}: quick screen {s['effect']:+.2f}" + (f", 95% interval {s['ci'][0]:+.2f} to {s['ci'][1]:+.2f}" if s.get("ci") else ", no interval")
            if s.get("ci"):
                parts.append(f'<line x1="{x(s["ci"][0]):.1f}" y1="{ys:.1f}" x2="{x(s["ci"][1]):.1f}" y2="{ys:.1f}" stroke="{SCREEN}" class="iv"/>')
            parts.append(f'<circle cx="{x(s["effect"]):.1f}" cy="{ys:.1f}" r="5" fill="{SCREEN}" class="dot"/>')
            parts.append(f'<rect x="{label_w}" y="{ys - 7:.1f}" width="{plot_w}" height="14" class="hit"><title>{tip}</title></rect>')
        yr = y + 7
        tip = (f"{name}: record scale {r['effect']:+.2f}, 95% interval {r['lo']:+.2f} to {r['hi']:+.2f}; "
               f"{100 * r['above_a']:.0f}% of runs above the published value against {100 * r['above_b']:.0f}%; {r['pairs']} pairs")
        parts.append(f'<line x1="{x(r["lo"]):.1f}" y1="{yr:.1f}" x2="{x(r["hi"]):.1f}" y2="{yr:.1f}" stroke="{RECORD}" class="iv"/>')
        parts.append(f'<circle cx="{x(r["effect"]):.1f}" cy="{yr:.1f}" r="5" fill="{RECORD}" class="dot"/>')
        if r["lo"] > 0 or r["hi"] < 0:     # label only the effects that are resolved
            parts.append(f'<text x="{x(r["hi"]) + 8:.1f}" y="{yr + 4:.1f}" class="val">{r["effect"]:+.2f}</text>')
        parts.append(f'<rect x="{label_w}" y="{yr - 7:.1f}" width="{plot_w}" height="14" class="hit"><title>{tip}</title></rect>')
    parts.append("</svg>")

    def cell(r: dict) -> str:
        s = r.get("screen")
        screen = "" if not s or s.get("effect") is None else (
            f"{s['effect']:+.2f}" + (f" [{s['ci'][0]:+.2f}, {s['ci'][1]:+.2f}]" if s.get("ci") else ""))
        return (f"<tr><td>{html.escape(r['label'].replace('`', ''))}</td><td>{screen}</td>"
                f"<td>{r['effect']:+.2f} [{r['lo']:+.2f}, {r['hi']:+.2f}]</td>"
                f"<td>{100 * r['above_a']:.0f}% against {100 * r['above_b']:.0f}%</td><td>{r['pairs']}</td></tr>")

    best = next((r for r in rows if r["label"] == "`multi_recreate`"), None)
    again = next((r for r in rows if r["label"].startswith("`multi_recreate`, second")), None)
    champ = next((r for r in rows if r["label"].startswith("evolved champion, whole")), None)
    headline = ""
    if best and champ:
        second = f" ({again['effect']:+.2f} in a second experiment on other seeds)" if again else ""
        headline = (f"One idea the engine rejected, <code>multi_recreate</code>, is worth {best['effect']:+.2f} points at record "
                    f"scale{second} and takes the share of record-beating runs from {100 * best['above_b']:.0f}% to "
                    f"{100 * best['above_a']:.0f}%. The evolved champion as a whole is worth {champ['effect']:+.2f} against the "
                    f"seed solver. None of the other ten ideas tested is worth more than a few hundredths of a point.")
    noise = (f"Two identical arms differ by {floor['effect']:+.2f} [{floor['lo']:+.2f}, {floor['hi']:+.2f}] "
             f"({100 * floor['differ']:.0f}% of pairs differ at all)." if floor else "")
    page = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The same ideas, measured twice · MendelEvolve</title>
<style>
  :root {{ color-scheme: dark; --bg: #0b0f17; --panel: #121826; --line: #232c3f; --text: #e6eaf2; --dim: #8e9ab0; --accent: #6ea8fe; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font: 16px/1.55 -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif; }}
  main {{ max-width: 940px; margin: 0 auto; padding: 48px 16px 72px; }}
  h1 {{ font-size: 30px; margin: 0 0 6px; letter-spacing: -0.02em; }}
  .tag {{ color: var(--dim); font-size: 17px; margin: 0 0 20px; }}
  a {{ color: var(--accent); text-decoration: none; }} a:hover {{ text-decoration: underline; }}
  figure {{ margin: 18px 0; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px 14px 8px; overflow-x: auto; }}
  svg {{ min-width: 720px; width: 100%; height: auto; display: block; }}
  .legend {{ display: flex; gap: 22px; font-size: 14px; color: var(--text); margin: 0 0 6px 4px; flex-wrap: wrap; }}
  .legend i {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 7px; }}
  .grid {{ stroke: #1f283a; stroke-width: 1; }} .zero {{ stroke: #55607a; stroke-width: 1; }} .sep {{ stroke: #182033; stroke-width: 1; }}
  .tick {{ fill: var(--dim); font-size: 12px; }} .name {{ fill: var(--text); font-size: 13.5px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  .name.ref {{ font-family: inherit; fill: #c3cbe0; }} .val {{ fill: var(--text); font-size: 12.5px; font-weight: 650; }}
  .iv {{ stroke-width: 2; stroke-linecap: round; }} .dot {{ stroke: var(--panel); stroke-width: 2; }} .hit {{ fill: transparent; }}
  table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; font-size: 14.5px; }}
  th, td {{ text-align: left; padding: 6px 14px 6px 0; border-bottom: 1px solid var(--line); }} th {{ color: var(--dim); font-weight: 500; }}
  details {{ margin: 12px 0; }} summary {{ cursor: pointer; color: var(--dim); }}
  .note {{ color: var(--dim); font-size: 14px; }} code {{ font-size: 0.92em; }}
</style>
</head>
<body>
<main>
  <p class="note"><a href="index.html">MendelEvolve</a></p>
  <h1>The same ideas, measured twice</h1>
  <p class="tag">Problem 60. What the engine's quick screen said about each idea, and what a knockout at record-search scale says.</p>

  <p>{headline}</p>

  <figure>
    <div class="legend"><span><i style="background:{SCREEN}"></i>engine's quick screen: 48 seed pairs, 45 CPU-seconds</span>
      <span><i style="background:{RECORD}"></i>record scale: {plot[0]['pairs'] if plot else 600} seed pairs, 240 CPU-seconds, both arms in one container</span></div>
    {''.join(parts)}
  </figure>

  <p class="note">Each dot is "idea on minus idea off" in points, with its 95% interval. An interval that crosses zero means the
  measurement could not tell the idea from nothing. The quick screen's intervals are all wide enough to hide an effect of a fifth
  of a point, which is the size that matters here. {noise}</p>

  <details open><summary>The numbers</summary>
  <table>
    <tr><th></th><th>quick screen</th><th>record scale</th><th>runs above the published value</th><th>pairs</th></tr>
    {''.join(cell(r) for r in rows)}
  </table></details>

  <p>How it was measured, and what it does not show, is in
  <a href="https://github.com/hashkanna/mendel-evolve/blob/main/RESULTS.md">RESULTS.md</a>. The table can be rebuilt with
  <code>python results/no5sphere/paired_effects.py</code>.</p>
</main>
</body>
</html>
'''
    open(path, "w").write(page)
