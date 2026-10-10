"""Optical path of the bench, seen from above (docs/images/beam_path.svg).

Run: py -3 docs/images/src/beam_path.py   (python3 on Linux; plain Python, no extra packages)

Laser, aperture, polarizers and beamsplitter along the bottom row; M1 and M2 fold the
beam in a Z; irises, the f = 8 mm asphere and the fiber along the top row. A schematic,
not to scale. The strip at the bottom gives the design distances along the beam, from
tools/bench_twin/optics.py and the bench layout.
"""
import math

from common import *

W, H = 1280, 800

# ── layout ───────────────────────────────────────────────────────────────────
Y_TOP, Y_LOW = 300, 530                 # fiber row, laser row
X_M = 700                               # M1 and M2
X_LASER0, X_LASER1 = 64, 180
X_AP = 220
X_POL = (350, 368)
X_BS = 560
Y_REF = Y_LOW - 84                      # reference photodiode, on the beamsplitter's reflected port
X_IRIS = (775, 975)
X_LENS, X_FIBER = 1040, 1080
OUT_PD = (1214, 468)
Y_ROW = 186                             # baseline of the label row above the fiber row
EDGE = "#3b4a7a"                        # leader ticks


def rot(c, deg, x, y):
    """Local (x, y) in a frame at c turned by deg (SVG sense) to page coordinates."""
    a = math.radians(deg)
    return c[0] + x * math.cos(a) - y * math.sin(a), c[1] + x * math.sin(a) + y * math.cos(a)


# ── parts ────────────────────────────────────────────────────────────────────
def mount(cx, cy, deg):
    """A kinematic mirror mount from above, with its two NEMA 8 motors behind it.
    Local frame: the mirror lies along x, +y points behind it (adjusters, rods, motors)."""
    motors = "".join(f'''
      <g transform="translate({mx} 0)">
        <rect x="-3.5" y="19" width="7" height="9" rx="1" fill="#94a3b8"/>
        <line x1="0" y1="28" x2="0" y2="41" stroke="#cbd5e1" stroke-width="2.6"/>
        <rect x="-6" y="40" width="12" height="13" rx="2" fill="{BRASS}"/>
        <line x1="-6" y1="46.5" x2="6" y2="46.5" stroke="#8a6a24" stroke-width="1"/>
        <rect x="-16" y="53" width="32" height="40" rx="4" fill="url(#metal)" stroke="{METAL_EDGE}" stroke-width="1.2"/>
        <rect x="-16" y="85" width="32" height="8" rx="2.5" fill="#11182f" stroke="{METAL_EDGE}"/>
        <line x1="-9" y1="62" x2="9" y2="62" stroke="#4b5f95" stroke-width="1.4"/>
        <line x1="-9" y1="67" x2="9" y2="67" stroke="#4b5f95" stroke-width="1.4"/>
      </g>''' for mx in (-21, 21))
    return f'''
  <g transform="translate({cx} {cy}) rotate({deg})">
    <rect x="-36" y="34" width="72" height="9" rx="2" fill="{CHIP}" stroke="{CHIP_EDGE}"/>{motors}
    <rect x="-35" y="12" width="70" height="7" rx="2" fill="#151d38" stroke="{METAL_EDGE}"/>
    <rect x="-35" y="3" width="70" height="7" rx="2" fill="url(#metal)" stroke="{METAL_EDGE}"/>
    <rect x="-32" y="-3" width="64" height="6" rx="1.5" fill="{MIRROR}" filter="url(#softglow)"/>
    <rect x="-32" y="0.5" width="64" height="2.5" fill="#94a3b8" opacity="0.6"/>
  </g>'''


def laser():
    y = Y_LOW
    return f'''
  <rect x="{X_LASER0}" y="{y - 20}" width="{X_LASER1 - X_LASER0}" height="40" rx="9" fill="url(#metal)" stroke="{METAL_EDGE}" stroke-width="1.2"/>
  <rect x="{X_LASER0 + 12}" y="{y - 10}" width="60" height="20" rx="4" fill="#0a0f22" stroke="#2c3966"/>
  <circle cx="{X_LASER0 + 23}" cy="{y}" r="3.2" fill="{OK}" filter="url(#softglow)"/>
  <line x1="{X_LASER0 + 36}" y1="{y}" x2="{X_LASER0 + 63}" y2="{y}" stroke="#2c3966" stroke-width="2"/>
  <rect x="{X_LASER1 - 3}" y="{y - 9}" width="9" height="18" rx="2" fill="#94a3b8"/>'''


def plate_pair(x, y, gap, h=24, color="#5b6b9c"):
    """Aperture or iris from above: two plates with a hole between them."""
    return (f'<rect x="{x - 2.5}" y="{y - gap - h}" width="5" height="{h}" rx="1.5" fill="{color}"/>'
            f'<rect x="{x - 2.5}" y="{y + gap}" width="5" height="{h}" rx="1.5" fill="{color}"/>')


def polarizers():
    y = Y_LOW
    plates = "".join(f'<rect x="{x - 3}" y="{y - 25}" width="6" height="50" rx="2" fill="{POLARIZER}" fill-opacity="0.8"/>'
                     for x in X_POL)
    x = X_POL[0]                                  # turning arrow on the first one
    return plates + (f'<path d="M{x - 16} {y - 34} A 18 11 0 0 1 {x + 16} {y - 34}" fill="none" stroke="{POLARIZER}" '
                     f'stroke-width="1.5" marker-start="url(#ahp)" marker-end="url(#ahp)"/>')


def beamsplitter():
    x, y = X_BS, Y_LOW
    return f'''
  <rect x="{x - 14}" y="{y - 14}" width="28" height="28" rx="2.5" fill="{LENS}" fill-opacity="0.16" stroke="{LENS}" stroke-opacity="0.85" stroke-width="1.4"/>
  <line x1="{x - 14}" y1="{y + 14}" x2="{x + 14}" y2="{y - 14}" stroke="{LENS}" stroke-opacity="0.95" stroke-width="1.4"/>'''


def photodiode(x, y, facing):
    """A small amp board with the BPW34 window toward the light (facing = +1 down, -1 up)."""
    win_y = y + (9 if facing > 0 else -13)
    return f'''
  <rect x="{x - 17}" y="{y - 13}" width="34" height="26" rx="3.5" fill="#1b2442" stroke="{METAL_EDGE}"/>
  <rect x="{x - 7}" y="{win_y}" width="14" height="4" fill="#94a3b8"/>
  <circle cx="{x}" cy="{win_y + 2}" r="9" fill="{LASER}" opacity="0.55" filter="url(#haze)"/>'''


def lens_and_stage():
    x, y = X_LENS, Y_TOP
    return f'''
  <rect x="{x - 30}" y="{y - 30}" width="60" height="60" rx="6" fill="#121a35" stroke="{METAL_EDGE}"/>
  <line x1="{x - 20}" y1="{y + 21}" x2="{x + 20}" y2="{y + 21}" stroke="{MUTED}" stroke-width="1.2" marker-start="url(#ahm)" marker-end="url(#ahm)"/>
  <path d="M{x} {y - 25} Q{x + 11} {y} {x} {y + 25} Q{x - 11} {y} {x} {y - 25}Z" fill="{LENS}" fill-opacity="0.22" stroke="{LENS}" stroke-width="1.6"/>'''


def fiber_end():
    x, y = X_FIBER, Y_TOP
    return f'''
  <rect x="{x + 7}" y="{y - 25}" width="8" height="50" rx="2" fill="#3c4c7c"/>
  <rect x="{x}" y="{y - 9}" width="32" height="18" rx="3" fill="url(#metal)" stroke="{METAL_EDGE}"/>
  <rect x="{x}" y="{y - 2.5}" width="10" height="5" rx="1" fill="#e2e8f0" fill-opacity="0.85"/>'''


FIBER_PATH = (f"M{X_FIBER + 32} {Y_TOP} C{X_FIBER + 90} {Y_TOP} {OUT_PD[0]} {Y_TOP + 20} {OUT_PD[0]} {Y_TOP + 70} "
              f"L{OUT_PD[0]} {OUT_PD[1] - 34}")


def fiber_and_out_pd():
    x, y = OUT_PD
    return f'''
  <path d="{FIBER_PATH}" fill="none" stroke="{FIBER}" stroke-width="5" stroke-linecap="round" opacity="0.9"/>
  <path d="{FIBER_PATH}" fill="none" stroke="{LASER}" stroke-width="2" stroke-linecap="round" opacity="0.55" filter="url(#glow)"/>
  <rect x="{x - 8}" y="{y - 36}" width="16" height="24" rx="3" fill="url(#metal)" stroke="{METAL_EDGE}"/>
  <rect x="{x - 22}" y="{y - 13}" width="44" height="6" rx="2" fill="#3c4c7c"/>
  {photodiode(x, y + 6, -1)}'''


# ── the beam ─────────────────────────────────────────────────────────────────
def beam():
    main = [(X_AP, Y_LOW), (X_M, Y_LOW), (X_M, Y_TOP), (X_LENS, Y_TOP)]
    pts = " ".join(f"{x},{y}" for x, y in main)
    ref = f"{X_BS},{Y_LOW} {X_BS},{Y_REF + 13}"
    cone = f"{X_LENS},{Y_TOP - 3.2} {X_LENS},{Y_TOP + 3.2} {X_FIBER},{Y_TOP}"
    return f'''
  <rect x="{X_LASER1 + 6}" y="{Y_LOW - 7}" width="{X_AP - X_LASER1 - 8}" height="14" fill="{LASER}" opacity="0.35" filter="url(#haze)"/>
  <rect x="{X_LASER1 + 6}" y="{Y_LOW - 5}" width="{X_AP - X_LASER1 - 8}" height="10" fill="{LASER}" opacity="0.5"/>
  <line x1="{X_LASER1 + 6}" y1="{Y_LOW}" x2="{X_AP}" y2="{Y_LOW}" stroke="{LASER_HOT}" stroke-width="1" opacity="0.8"/>
  <g filter="url(#haze)" opacity="0.55">
    <polyline points="{pts}" fill="none" stroke="{LASER}" stroke-width="9" stroke-linejoin="round"/>
    <polyline points="{ref}" fill="none" stroke="{LASER}" stroke-width="6"/>
  </g>
  <polyline points="{ref}" fill="none" stroke="{LASER}" stroke-width="1.8" opacity="0.85" filter="url(#glow)"/>
  <polyline points="{pts}" fill="none" stroke="{LASER}" stroke-width="2.8" stroke-linejoin="round" filter="url(#glow)"/>
  <polyline points="{pts}" fill="none" stroke="{LASER_HOT}" stroke-width="1" stroke-linejoin="round"/>
  <polygon points="{cone}" fill="{LASER}" fill-opacity="0.8" filter="url(#glow)"/>
  <circle cx="{X_FIBER + 2}" cy="{Y_TOP}" r="6" fill="{LASER}" opacity="0.8" filter="url(#haze)"/>'''


# ── labels ───────────────────────────────────────────────────────────────────
def lab(x, y, title, lines, anchor="middle"):
    out = [f'<text x="{f(x)}" y="{f(y)}" text-anchor="{anchor}" class="lt">{title}</text>']
    for k, (cls, txt) in enumerate(lines):
        out.append(f'<text x="{f(x)}" y="{f(y + 22 + 19 * k)}" text-anchor="{anchor}" class="{cls}">{txt}</text>')
    return "".join(out)


def tick(x0, y0, x1=None, y1=None):
    x1 = x0 if x1 is None else x1
    return f'<line x1="{f(x0)}" y1="{f(y0)}" x2="{f(x1)}" y2="{f(y1)}" stroke="{EDGE}" stroke-width="1.2"/>'


def callouts():
    """Name the drive train of one M1 adjuster, from points on the outer side of its motor stack."""
    out, x_text = [], 812
    parts = (((24.5, 23), "100 TPI adjuster"), ((22.3, 34), "2 mm hex rod"), ((27, 44), "brass coupler"), ((37, 70), "NEMA 8 motor"))
    for k, ((lx, ly), name) in enumerate(parts):
        px, py = rot((X_M, Y_LOW), -45, lx, ly)
        ty = 496 + 22 * k
        out.append(f'<line x1="{f(px)}" y1="{f(py)}" x2="{x_text - 6}" y2="{ty - 5}" stroke="{EDGE}" stroke-width="1.1"/>'
                   f'<circle cx="{f(px)}" cy="{f(py)}" r="2" fill="{FG}"/>'
                   f'<text x="{x_text}" y="{ty}" class="small">{name}</text>')
    return "".join(out)


LABELS = "".join([
    lab(X_LASER0, 584, "635 nm laser", [("spec", "Quarton VLM-635-32 LPT"), ("ls", "Under 1 mW,"), ("ls", "beam about 7 × 3 mm.")], "start"),
    lab(sum(X_POL) / 2, 584, "Crossed polarizers", [("spec", "linear polarizer sheet"), ("ls", "The brightness knob:"), ("ls", "rotate the first one.")]),
    lab(X_BS, 584, "Beamsplitter", [("spec", "plate or cube"), ("ls", "Sends a slice to the"), ("ls", "reference photodiode.")]),
    tick(sum(X_POL) / 2, Y_LOW + 30, None, 564), tick(X_BS, Y_LOW + 20, None, 564), tick(122, Y_LOW + 24, None, 564),
    lab(64, 392, "2 mm aperture", [("spec", "printed, 10-20 mm after the laser"), ("ls", "Trims the beam to the fiber mode. In the"),
                                  ("ls", "twin 83% of what passes it couples, against"),
                                  ("ls", "25% of the whole beam without it.")], "start"),
    tick(X_AP, 484, None, Y_LOW - 30),
    lab(X_BS, 356, "Reference photodiode", [("spec", "BPW34, MCP6002 amp, 47 kΩ"), ("ls", "Read on ADS1115 A0.")]),
    tick(X_BS, 408, None, Y_REF - 15),
    lab(590, Y_ROW, "M1 and M2", [("spec", "1 in mirrors, Thorlabs KMS-style mounts"), ("ls", "Each 100 TPI adjuster is turned"),
                               ("ls", "by its own NEMA 8: four axes.")], "end"),
    f'<text x="{X_M + 22}" y="{Y_TOP + 36}" class="mname">M2</text>',
    f'<text x="{X_M - 22}" y="{Y_LOW - 18}" text-anchor="end" class="mname">M1</text>',
    callouts(),
    lab(sum(X_IRIS) / 2, Y_ROW, "Iris 1 and iris 2", [("spec", "printed"), ("ls", "Mark the beam axis in phase 1. For the fiber,"),
                                                     ("ls", "iris 1 comes out and iris 2 is a 3 mm baffle.")]),
    tick(X_IRIS[0], Y_ROW + 65, None, Y_TOP - 32), tick(X_IRIS[1], Y_ROW + 65, None, Y_TOP - 32),
    lab(X_LENS, 368, "f = 8 mm asphere", [("spec", "on a micrometer stage"), ("ls", "The stage moves it to focus."),
                                         ("ls", "In phase 1 the OV9281 takes its place.")]),
    tick(X_LENS, Y_TOP + 33, None, 348),
    lab(X_FIBER + 11, Y_ROW, "FC bulkhead", [("spec", "fixed"), ("ls", "The lens moves,"), ("ls", "the fiber does not.")], "start"),
    tick(X_FIBER + 11, Y_ROW + 65, None, Y_TOP - 29),
    lab(1232, 536, "Output photodiode", [("spec", "a second BPW34 board, ADS1115 A1"), ("ls", "Score = output / reference:"),
                                        ("ls", "the ratio cancels laser flicker.")], "end"),
])


# ── distance strip ───────────────────────────────────────────────────────────
STOPS = ["laser", "aperture", "M1", "M2", "iris 1", "iris 2", "lens", "fiber"]
GAPS = ["15", "115", "150", "70", "190", "50", "8"]       # mm; optics.py and the bench layout


def strip():
    y, x0, x1 = 742, 64, 1010
    step = (x1 - x0) / (len(STOPS) - 1)
    out = [f'<text x="{x0 - 16}" y="{y - 38}" class="spec">Light path, design distances in mm</text>',
           f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="url(#pathGrad)" stroke-width="3" stroke-linecap="round"/>']
    for k, name in enumerate(STOPS):
        x = x0 + k * step
        out.append(f'<circle cx="{f(x)}" cy="{y}" r="5.5" fill="#0b1020" stroke="{FG}" stroke-width="1.8"/>'
                   f'<text x="{f(x)}" y="{y + 26}" text-anchor="middle" class="ls">{name}</text>')
        if k < len(GAPS):
            out.append(f'<text x="{f(x + step / 2)}" y="{y - 10}" text-anchor="middle" class="mono">{GAPS[k]}</text>')
    out.append(f'<text x="{x1 + 36}" y="{y - 6}" class="spec">≈ 600 mm</text>'
               f'<text x="{x1 + 36}" y="{y + 13}" class="ls">laser to fiber</text>')
    return "".join(out)


BG_DEFS, BG_BODY = background(W, H, fade_cx=0.55, fade_cy=0.5)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
  <title id="t">Optical path of the bench, seen from above</title>
  <desc id="d">Schematic top view, not to scale. A 635 nm laser fires right through a 2 mm printed aperture, two crossed polarizers and a beamsplitter whose reflected slice goes to the reference photodiode. Motorized mirror M1 turns the beam up to motorized mirror M2, 150 mm away, which turns it right through iris 1 and iris 2 to an f = 8 mm asphere on a micrometer stage. The asphere focuses the beam into a fixed FC bulkhead, and the fiber loops to the output photodiode; the score is the output reading divided by the reference, and the ratio cancels laser flicker. In phase 1 the OV9281 camera takes the lens's place, and the irises mark the beam axis. Each mirror sits in a kinematic mount whose two 100 TPI adjusters are turned by NEMA 8 motors through brass couplers and 2 mm hex rods. A strip along the bottom gives the design distances along the beam: 15 mm to the aperture, 115 to M1, 150 to M2, 70 to iris 1, 190 to iris 2, 50 to the lens and 8 to the fiber, about 600 mm in all.</desc>
  <style>
    text {{ font-family: {FONT}; }}
    .h1 {{ font-size: 32px; font-weight: 800; fill: #f1f5ff; }}
    .sub {{ font-size: 17px; fill: #a3acc9; }}
    .lt {{ font-size: 18px; font-weight: 700; fill: {FG}; }}
    .spec {{ font-size: 15px; font-weight: 600; fill: {LENS}; }}
    .ls {{ font-size: 15px; fill: {MUTED}; }}
    .small {{ font-size: 14px; fill: {MUTED}; font-style: italic; }}
    .mname {{ font-size: 20px; font-weight: 800; fill: {FG}; }}
    .mono {{ font-size: 14.5px; fill: {FG}; font-family: {MONO}; }}
  </style>
  <defs>{BG_DEFS}{GLOW}
    <filter id="softglow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="1.4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="metal" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{METAL0}"/><stop offset="1" stop-color="{METAL1}"/>
    </linearGradient>
    <linearGradient id="pathGrad" gradientUnits="userSpaceOnUse" x1="64" y1="0" x2="1010" y2="0">
      <stop offset="0" stop-color="{FG}" stop-opacity="0.7"/><stop offset="1" stop-color="{LASER}"/>
    </linearGradient>
    <marker id="ahm" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="{MUTED}"/></marker>
    <marker id="ahp" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="{POLARIZER}"/></marker>
  </defs>

  {BG_BODY}

  <text x="48" y="68" class="h1">Optical path</text>
  <text x="48" y="102" class="sub">One 635 nm beam, two motorized mirrors and one fiber, seen from above. Schematic, not to scale.</text>
  <text x="48" y="127" class="sub">The Z-fold lets M1 and M2 set both the angle and the position of the beam at the lens.</text>

  <!-- the bench -->
  {laser()}
  {plate_pair(X_AP, Y_LOW, 2.5)}
  {polarizers()}
  {beamsplitter()}
  {photodiode(X_BS, Y_REF, 1)}
  {lens_and_stage()}
  {plate_pair(X_IRIS[0], Y_TOP, 3)}{plate_pair(X_IRIS[1], Y_TOP, 3)}
  {fiber_end()}
  {fiber_and_out_pd()}
  {beam()}
  {mount(X_M, Y_LOW, -45)}
  {mount(X_M, Y_TOP, 135)}

  <!-- M1 to M2 -->
  <g stroke="{MUTED}" stroke-opacity="0.5" stroke-width="1" fill="none">
    <path d="M{X_M + 34} {Y_TOP + 52} H{X_M + 42} M{X_M + 38} {Y_TOP + 52} V{Y_LOW - 52} M{X_M + 34} {Y_LOW - 52} H{X_M + 42}"/>
  </g>
  <text transform="translate({X_M + 54} {(Y_TOP + Y_LOW) / 2}) rotate(-90)" text-anchor="middle" class="mono">150 mm</text>

  {LABELS}
  {strip()}
</svg>
'''

write("beam_path.svg", svg)
