"""Render the two YouTube thumbnails (1280x720 PNG) with the installed Chrome.

    uv run --with playwright python media/thumbnails.py
"""

import os

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
HEAD = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=JetBrains+Mono:wght@500;600&display=swap">
<style>
  * { box-sizing: border-box; margin: 0; }
  body { width: 1280px; height: 720px; overflow: hidden; background: #0B0F17; color: #F2F5FB;
         font-family: 'IBM Plex Sans', Arial, sans-serif; position: relative; }
  .glow { position: absolute; inset: 0; background: radial-gradient(900px 520px at 78% 42%, #16376F 0%, #0B0F17 70%); }
  .label { position: absolute; left: 64px; top: 52px; font: 600 26px 'JetBrains Mono', monospace; letter-spacing: 3px; color: #6EA8FE; }
  .tag { position: absolute; left: 64px; bottom: 54px; font: 600 30px 'IBM Plex Sans', sans-serif; color: #C9D3E6; }
  .tag b { color: #F2F5FB; }
  h1 { position: absolute; left: 64px; top: 130px; font-weight: 700; letter-spacing: -2px; line-height: 1.02; }
  .mono { font-family: 'JetBrains Mono', monospace; }
</style></head><body><div class="glow"></div>"""

FOUR = HEAD + """
<div class="label">MENDELEVOLVE</div>
<h1 style="font-size:104px; width:700px">The best idea was the one it <span style="color:#F0A35E">threw away</span></h1>
<div class="tag"><b>17</b> new bounds · <b>58</b> beats 56 · every idea measured</div>
<svg style="position:absolute; left:770px; top:150px" width="460" height="420" viewBox="0 0 460 420">
  <line x1="150" y1="20" x2="150" y2="400" stroke="#55607A" stroke-width="3"/>
  <text x="150" y="16" text-anchor="middle" fill="#A9B4C8" font-size="24" font-family="IBM Plex Sans">0</text>
  <text x="20" y="92" fill="#F0A35E" font-size="30" font-weight="600" font-family="IBM Plex Sans">quick screen</text>
  <line x1="40" y1="140" x2="220" y2="140" stroke="#F0A35E" stroke-width="8" stroke-linecap="round"/>
  <circle cx="132" cy="140" r="20" fill="#F0A35E" stroke="#0B0F17" stroke-width="6"/>
  <text x="240" y="152" fill="#F2F5FB" font-size="40" font-weight="700" font-family="IBM Plex Sans">−0.04</text>
  <text x="20" y="262" fill="#6EA8FE" font-size="30" font-weight="600" font-family="IBM Plex Sans">measured properly</text>
  <line x1="262" y1="312" x2="344" y2="312" stroke="#6EA8FE" stroke-width="8" stroke-linecap="round"/>
  <circle cx="302" cy="312" r="20" fill="#6EA8FE" stroke="#0B0F17" stroke-width="6"/>
  <text x="240" y="384" fill="#F2F5FB" font-size="64" font-weight="700" font-family="IBM Plex Sans">+0.31</text>
</svg>
</body></html>"""

TWO = HEAD + """
<div class="label">MENDELEVOLVE · 2 MIN</div>
<h1 style="font-size:118px; width:720px">Which idea deserves the <span style="color:#6EA8FE">credit?</span></h1>
<div class="tag">Switch it off. Measure what is lost.</div>
<div style="position:absolute; left:800px; top:176px; width:416px; padding:36px 40px; background:#0B0F17; border:2px solid #2A344A; border-radius:28px">
  <div class="mono" style="font-size:30px; font-weight:600; color:#6EA8FE">slsqp_polish</div>
  <div style="display:flex; align-items:center; gap:22px; margin-top:26px">
    <div style="width:132px; height:68px; border-radius:34px; background:#2A344A; position:relative">
      <div style="position:absolute; left:8px; top:8px; width:52px; height:52px; border-radius:50%; background:#8793A8"></div>
    </div>
    <div style="font-size:36px; font-weight:600; color:#C9D3E6">off</div>
  </div>
  <div style="font-size:124px; font-weight:700; letter-spacing:-3px; line-height:1.05; margin-top:18px">−1.67</div>
</div>
</body></html>"""


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 720})
        for name, html in (("thumbnail_4min.png", FOUR), ("thumbnail_2min.png", TWO)):
            page.set_content(html, wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=os.path.join(HERE, name))
            print("wrote", name)
        browser.close()


if __name__ == "__main__":
    main()
