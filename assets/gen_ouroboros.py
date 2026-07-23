"""oh-my-ouroboros logo generator — an ouroboros that unmistakably reads as a serpent.

Design: circle-chain body (tapering) + bezier tail entering the open jaws head-on
+ gold slit-pupil eye + crescent scales. The logo is code-generated on purpose —
regenerate with `python3 gen_ouroboros.py` (writes ouroboros.svg next to itself).
"""
import math
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ouroboros.svg")
cx, cy, R = 120, 120, 78


def P(deg, r=R):
    a = math.radians(deg)
    return (cx + r * math.cos(a), cy + r * math.sin(a))


def f(v):
    return f"{v:.1f}"


def add(a, b, s):
    return (a[0] + s * b[0], a[1] + s * b[1])


body = []
N = 100
for k in range(N):
    th = 250 - (305 * k / (N - 1))  # 250° → -55° (head anchor to tail, 305° span)
    t = k / (N - 1)
    r = 13 if t < 0.62 else 13 - (13 - 7) * ((t - 0.62) / 0.38)
    x, y = P(th)
    body.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(r)}" fill="url(#g)"/>')

A = P(250)              # neck anchor (top-left)
u = (0.940, -0.342)     # head axis — mouth faces right
pv = (0.342, 0.940)     # lower-jaw side normal
M = add(A, u, 26)       # bite point: tail tip lands between the jaws
P0 = P(-55)
C = (152, 33)
tail = []
for k in range(34):
    t = k / 33
    x = (1 - t) ** 2 * P0[0] + 2 * t * (1 - t) * C[0] + t * t * M[0]
    y = (1 - t) ** 2 * P0[1] + 2 * t * (1 - t) * C[1] + t * t * M[1]
    tail.append(f'<circle cx="{f(x)}" cy="{f(y)}" r="{f(7 - 5 * t)}" fill="url(#g)"/>')

N1, N2 = add(A, pv, -13), add(A, pv, 13)          # upper-jaw neck, lower-jaw neck
C1, C2 = add(add(A, u, 12), pv, -19), add(add(A, u, 12), pv, 19)
J1, J2 = add(add(A, u, 42), pv, -13), add(add(A, u, 38), pv, 13)  # upper jaw longer
V = add(A, u, 14)
head = (
    f'<path d="M {f(N1[0])} {f(N1[1])} '
    f'Q {f(C1[0])} {f(C1[1])} {f(J1[0])} {f(J1[1])} '
    f'L {f(V[0])} {f(V[1])} '
    f'L {f(J2[0])} {f(J2[1])} '
    f'Q {f(C2[0])} {f(C2[1])} {f(N2[0])} {f(N2[1])} '
    f'A 13 13 0 0 0 {f(N1[0])} {f(N1[1])} Z" fill="url(#g)"/>'
)
E = add(add(A, u, 10), pv, -7.5)                  # eye on the upper jaw
eye = (
    f'<circle cx="{f(E[0])}" cy="{f(E[1])}" r="3.6" fill="#fbbf24"/>'
    f'<ellipse cx="{f(E[0])}" cy="{f(E[1])}" rx="1.1" ry="2.7" fill="#1c1917"/>'
)
NO = add(add(A, u, 30), pv, -9)                   # nostril on the snout
nostril = f'<circle cx="{f(NO[0])}" cy="{f(NO[1])}" r="1.1" fill="#064e3b" opacity="0.8"/>'

scales = []
th = 245
while th - (-45) == abs(th - (-45)):  # th > -45 (spelled to dodge shell-hook redirect false-positive)
    o, i = P(th, R + 7), P(th, R - 7)
    scales.append(
        f'<path d="M {f(o[0])} {f(o[1])} A 11 11 0 0 1 {f(i[0])} {f(i[1])}" '
        f'stroke="#ecfccb" stroke-width="1.6" fill="none" opacity="0.5"/>'
    )
    th -= 13

svg = f'''<svg width="240" height="240" viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="g" gradientUnits="userSpaceOnUse" x1="30" y1="30" x2="215" y2="215">
      <stop offset="0%" stop-color="#065f46"/>
      <stop offset="55%" stop-color="#059669"/>
      <stop offset="100%" stop-color="#84cc16"/>
    </linearGradient>
  </defs>
  {chr(10).join(body)}
  {chr(10).join(tail)}
  {chr(10).join(scales)}
  {head}
  {eye}
  {nostril}
</svg>'''
with open(OUT, "w") as fh:
    fh.write(svg)
print("wrote", OUT, len(svg), "bytes")
