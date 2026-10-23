"""oh-my-ouroboros logo generator: a terminal-card ouroboros that reads as a serpent AND as dev tooling.

Design: a rounded terminal window (title-bar dots) holding a ring whose body is a git commit
graph (a rail with commit nodes that shrink toward the tail). The head is a "<" prompt chevron
whose two prongs are the open jaws; a gold eye sits on the upper prong; the tail's last node
is a blinking cursor block (SMIL opacity animation) sitting between the jaws, i.e. the snake
bites its own cursor. Centre carries a faint "{ }".
Why a fixed dark card: GitHub renders an <img> SVG with the OS colour scheme, not the site
theme, so a card that is dark in both themes is the only choice that never loses contrast;
@media (prefers-color-scheme) only nudges the card border/shadow per scheme.
The logo is code-generated on purpose: regenerate with `python3 gen_ouroboros.py`
(writes ouroboros.svg next to itself). Standard library only, no external fonts or images.
"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ouroboros.svg")
cx, cy, R = 120, 138, 68
BG = "#0d1117"


def P(deg, r=R):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def f(v):
    return f"{v:.1f}"


def add(a, b, s):
    return (a[0] + s * b[0], a[1] + s * b[1])


TH0, TH1 = 250, -55            # head anchor angle -> tail start angle (305 deg span)
A = P(TH0)                     # neck anchor (top-left of ring)
u = (0.940, -0.342)            # head axis: mouth faces right-up
pv = (0.342, 0.940)            # jaw-side normal
M = add(A, u, 24)              # bite point: cursor sits between the jaws
P0 = P(TH1)
tan = (-math.sin(math.radians(TH1)), math.cos(math.radians(TH1)))
C1 = add(P0, (-tan[0], -tan[1]), 26)   # leave the ring tangentially
C2 = add(M, u, 26)                     # enter the mouth head-on

# body rail: commit-graph line along the ring, then the tail curve
rail_arc = (
    f'<path d="M {f(A[0])} {f(A[1])} A {R} {R} 0 1 0 {f(P0[0])} {f(P0[1])}" '
    f'stroke="url(#g)" stroke-width="3.2" fill="none" stroke-linecap="round"/>'
)
rail_tail = (
    f'<path d="M {f(P0[0])} {f(P0[1])} C {f(C1[0])} {f(C1[1])} {f(C2[0])} {f(C2[1])} {f(M[0])} {f(M[1])}" '
    f'stroke="url(#g)" stroke-width="2.4" fill="none" stroke-linecap="round"/>'
)

# commit nodes: ring-shaped nodes every 18 deg, shrinking after 60% of the body
nodes = []
STEP = 18
n = int((TH0 - TH1) / STEP)
for k in range(1, n + 1):
    th = TH0 - STEP * k
    t = k / n
    r = 8.5 if t < 0.55 else 8.5 - (8.5 - 4.2) * ((t - 0.55) / 0.45)
    x, y = P(th)
    nodes.append(
        f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="{BG}" stroke="url(#g)" '
        f'stroke-width="{f(2.8 if t < 0.55 else 2.2)}"/>'
    )
    if k % 2 == 0 and t < 0.55:  # filled core on every other node = merge-commit look
        nodes.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r - 4.2)}" fill="url(#g)"/>')

# head: "<" prompt chevron, vertex on the neck, prongs are the jaws
V = add(A, u, -2)
up_tip = add(add(A, u, 34), pv, -19)
lo_tip = add(add(A, u, 30), pv, 19)
head = (
    f'<path d="M {f(up_tip[0])} {f(up_tip[1])} L {f(V[0])} {f(V[1])} L {f(lo_tip[0])} {f(lo_tip[1])}" '
    f'stroke="url(#h)" stroke-width="9" fill="none" stroke-linecap="round" stroke-linejoin="round"/>'
)
E = add(add(A, u, 15), pv, -11)  # eye on the upper jaw
eye = (
    f'<circle cx="{f(E[0])}" cy="{f(E[1])}" r="4" fill="#fbbf24"/>'
    f'<ellipse cx="{f(E[0])}" cy="{f(E[1])}" rx="1.2" ry="3" fill="{BG}"/>'
)

# blinking cursor block at the bite point
ang = math.degrees(math.atan2(u[1], u[0]))
cursor = (
    f'<rect x="-3" y="-7" width="6" height="14" rx="0.8" '
    f'fill="#a3e635" transform="translate({f(M[0])} {f(M[1])}) rotate({f(ang)})">'
    f'<animate attributeName="opacity" values="1;1;0;0" keyTimes="0;0.5;0.5;1" dur="1.1s" repeatCount="indefinite"/>'
    f'</rect>'
)

svg = f'''<svg width="240" height="240" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="oh-my-ouroboros: a snake of commit nodes biting a terminal cursor">
  <style>
    .card {{ fill: {BG}; stroke: #30363d; stroke-width: 2; }}
    @media (prefers-color-scheme: light) {{ .card {{ stroke: #57606a; }} }}
    @media (prefers-color-scheme: dark) {{ .card {{ stroke: #3d444d; }} }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
  </style>
  <defs>
    <linearGradient id="g" gradientUnits="userSpaceOnUse" x1="40" y1="80" x2="200" y2="210">
      <stop offset="0%" stop-color="#34d399"/>
      <stop offset="60%" stop-color="#10b981"/>
      <stop offset="100%" stop-color="#a3e635"/>
    </linearGradient>
    <linearGradient id="h" gradientUnits="userSpaceOnUse" x1="90" y1="40" x2="140" y2="80">
      <stop offset="0%" stop-color="#6ee7b7"/>
      <stop offset="100%" stop-color="#34d399"/>
    </linearGradient>
  </defs>
  <rect class="card" x="3" y="3" width="234" height="234" rx="22"/>
  <line x1="3" y1="32" x2="237" y2="32" stroke="#30363d" stroke-width="1.5"/>
  <circle cx="22" cy="18" r="5" fill="#ff5f56"/>
  <circle cx="38" cy="18" r="5" fill="#ffbd2e"/>
  <circle cx="54" cy="18" r="5" fill="#27c93f"/>
  <text class="mono" x="{cx}" y="{cy + 12}" font-size="34" text-anchor="middle" fill="#6ee7b7" opacity="0.4" font-weight="bold">{{ }}</text>
  {rail_arc}
  {rail_tail}
  {chr(10).join("  " + s for s in nodes).strip()}
  {head}
  {eye}
  {cursor}
</svg>'''
with open(OUT, "w") as fh:
    fh.write(svg)
print("wrote", OUT, len(svg.encode()), "bytes")
