"""Animated banner for the README (docs/images/hero.svg).

Run: py -3 docs/images/src/hero.py   (needs numpy; it runs the bench twin)

The banner replays one knock-and-recover run of the bench twin (tools/bench_twin):
the single-mode fiber is coupled, M1 gets knocked 1.5 mrad, and Auto-align searches
with M2, finds the light and peaks it again. The photodiode trace, the spot on the
fiber face and the mirror moves all come from that run, sped up; the mirror angles
in the drawing are exaggerated so they show. GitHub plays the SMIL animations in
README images.
"""
import math
import sys

import numpy as np

from common import *

sys.path.insert(0, str(REPO / "tools"))
from bench_twin import Aligner, Bench, Optics, Settings, make_plan  # noqa: E402
from bench_twin.trials import make_bench  # noqa: E402

W, H = 1280, 600

# ── the run ──────────────────────────────────────────────────────────────────
FIBER_KEY, SEED = "sm630", 0
KNOCK_MRAD, KNOCK_DIR_DEG = 1.5, 30      # M1 tilted 1.5 mrad, mostly in X (the drawing's plane)
PRE_S, POST_S, READ_EVERY = 2.5, 2.6, 0.1


def run_twin():
    """Calibrate on the peak, stream a little, knock M1, recover, stream a little.
    Returns the frames (one per photodiode reading) and the phase start times."""
    plan = make_plan(Bench(Optics(fiber=FIBER_KEY)))
    b = make_bench(FIBER_KEY, SEED)
    said = []
    al = Aligner(b, plan, Settings(), say=lambda text: said.append((b.clock, text)))
    b.jump_to_peak()
    al.calibrate()
    b.clear_knocks()
    b.jump_to_peak()
    al.forget_direction()
    frames = []

    def snap(t, ratio):
        beam = b.beam_at_lens()
        phi = b.mirror_tilts() * b._gain          # beam turn from each mirror axis, rad
        frames.append(dict(t=t, ratio=ratio, phi1=float(phi[0]), phi2=float(phi[2]),
                           spot=(8.0e3 * float(beam[1]), 8.0e3 * float(beam[3])),   # um on the fiber face (f = 8 mm)
                           c=float(b.coupling() / b.best_coupling()), pos=b.position.copy()))

    def stream(t0, seconds):
        n = int(round(seconds / READ_EVERY))
        for i in range(n):
            b.advance(READ_EVERY - Settings.read_s - b.sens.latency_s)
            r = b.read(Settings.read_s).ratio
            snap(t0 + (i + 1) * READ_EVERY, (r or 0.0) / al.good)

    stream(-PRE_S - READ_EVERY, PRE_S)
    a = math.radians(KNOCK_DIR_DEG)
    b.offset[0:2] += KNOCK_MRAD * 1e-3 * np.array([math.cos(a), math.sin(a)])
    snap(0.0, None)
    said.clear()
    t_knock = b.clock
    read = b.read

    def read_and_snap(seconds=0.02):
        r = read(seconds)
        snap(b.clock - t_knock, (r.ratio or 0.0) / al.good)
        return r
    b.read = read_and_snap
    res = al.recover()
    b.read = read
    t_done = b.clock - t_knock
    stream(t_done, POST_S)
    phases = {text.split(":")[0]: t - t_knock for t, text in said}
    return frames, phases, res, t_done, float(b.coupling() / b.best_coupling())


FRAMES, PHASES, RESULT, T_DONE, FINAL = run_twin()
T_SEARCH = PHASES.get("no light", 0.0)
T_PEAK = PHASES["peaking"]

# ── sim time to animation time ───────────────────────────────────────────────
A_KNOCK = 1.6        # the knock lands here
A_START = 2.2        # Align starts
SPEED = 3.0          # recovery replayed this much faster than the twin's clock
A_DONE = A_START + T_DONE / SPEED
A_END = A_DONE + POST_S
DUR = A_END + 1.4    # hold, then fade the trace and start again


def anim_time(t):
    if t < 0:
        return A_KNOCK + t / PRE_S * A_KNOCK * 0.98
    if t <= T_DONE:
        return A_START + t / SPEED
    return A_DONE + (t - T_DONE)


# ── drawing geometry ─────────────────────────────────────────────────────────
Y_LOW, Y_TOP = 438, 196          # laser row, fiber row
X_M = 806                        # mirror column
X_LASER0, X_LASER1 = 650, 712
X_AP, X_POL, X_BS = 724, (740, 751), 778
X_IRIS, X_LENS, X_FIBER = 1010, 1066, 1092
GAIN = 14.0                      # drawing exaggeration of the mirror angles
F_EFF = 230.0                    # px of focus offset per radian of beam angle at the lens (exaggerated)
BEAM_HALF = 3.2                  # px, half the beam's drawn width at the lens


def mirror_angles(fr):
    """Drawn rotation of M1 and M2 (radians, SVG sense) for a frame."""
    return -GAIN * fr["phi1"] / 2, GAIN * fr["phi2"] / 2


def reflect(p, d, c, ang):
    """Hit the mirror line through c at angle ang (radians, SVG coords) from p along d.
    Returns the hit point and the reflected direction."""
    m = np.array([math.cos(ang), math.sin(ang)])
    n = np.array([-m[1], m[0]])
    p, d, c = np.asarray(p, float), np.asarray(d, float), np.asarray(c, float)
    s = np.dot(c - p, n) / np.dot(d, n)
    hit = p + s * d
    return hit, d - 2 * np.dot(d, n) * n


BASE = -math.pi / 4              # "/" mirrors in SVG coordinates


def beam_points(d1, d2):
    p0 = np.array([X_LASER1, Y_LOW])
    h1, r1 = reflect(p0, (1, 0), (X_M, Y_LOW), BASE + d1)
    h2, r2 = reflect(h1, r1, (X_M, Y_TOP), BASE + d2)
    s = (X_LENS - h2[0]) / r2[0]
    hl = h2 + s * r2
    yf = Y_TOP + F_EFF * math.tan(math.atan2(r2[1], r2[0]))
    return h1, h2, hl, yf


def beam_attrs(fr):
    d1, d2 = mirror_angles(fr)
    h1, h2, hl, yf = beam_points(d1, d2)
    line = f"{X_LASER1},{Y_LOW} {f(h1[0])},{f(h1[1])} {f(h2[0])},{f(h2[1])} {f(hl[0])},{f(hl[1])}"
    cone = (f"{X_LENS},{f(hl[1] - BEAM_HALF)} {X_LENS},{f(hl[1] + BEAM_HALF)} {X_FIBER},{f(yf)}")
    return line, cone, math.degrees(d1), math.degrees(d2)


# ── keyframes ────────────────────────────────────────────────────────────────
KF = []          # (anim time, frame, extra mirror-1 shake in degrees)
for fr in FRAMES:
    if fr["ratio"] is None:          # the knock itself: a short ring of the mount
        k = fr
        for dt, shake in ((0.0, 0.0), (0.05, 3.2), (0.12, -1.8), (0.2, 0.9), (0.3, -0.35), (0.4, 0.0)):
            KF.append((A_KNOCK + dt, k, shake))
        KF.append((A_START, k, 0.0))
        continue
    KF.append((anim_time(fr["t"]), fr, 0.0))
KF.sort(key=lambda x: x[0])
# frame 0 at t = 0 and the loop back to it at the end
KF.insert(0, (0.0, FRAMES[0], 0.0))
KF.append((A_END + 0.8, KF[-1][1], 0.0))
KF.append((DUR, FRAMES[0], 0.0))
KT = ";".join(f"{a / DUR:.4f}" for a, _, _ in KF)


def anim(attr, values, **kw):
    extra = "".join(f' {k}="{v}"' for k, v in kw.items())
    return (f'<animate attributeName="{attr}" values="{";".join(values)}" keyTimes="{KT}" '
            f'dur="{f(DUR)}s" repeatCount="indefinite"{extra}/>')


def anim_rotate(values, cx, cy):
    vals = ";".join(f"{f(v)} {cx} {cy}" for v in values)
    return (f'<animateTransform attributeName="transform" type="rotate" values="{vals}" keyTimes="{KT}" '
            f'dur="{f(DUR)}s" repeatCount="indefinite"/>')


def timeline(points):
    """A discrete on/off timeline for opacity: points = [(anim start, anim end)]."""
    times, vals = [0.0], ["0"]
    for a0, a1 in points:
        times += [a0, a1]
        vals += ["1", "0"]
    times.append(DUR)
    vals.append("0")
    kt = ";".join(f"{t / DUR:.4f}" for t in times)
    return (f'<animate attributeName="opacity" values="{";".join(vals)}" keyTimes="{kt}" calcMode="discrete" '
            f'dur="{f(DUR)}s" repeatCount="indefinite"/>')


BEAMS = [beam_attrs(k[1]) for k in KF]
LINE_VALS = [b[0] for b in BEAMS]
CONE_VALS = [b[1] for b in BEAMS]
M1_DEG = [b[2] + k[2] for b, k in zip(BEAMS, KF)]
M2_DEG = [b[3] for b in BEAMS]
C_VALS = [k[1]["c"] for k in KF]

# ── left column ──────────────────────────────────────────────────────────────
CHIPS = [("4 axes", "motorized tilt"), ("79 nm", "per microstep†"),
         ("100 / 100*", "knocks recovered"), ("19 s*", "median recovery")]


def chips(x0=64, y0=356):
    out, w, gap = [], 131, 8
    for k, (big, small) in enumerate(CHIPS):
        x = x0 + k * (w + gap)
        out.append(f'''
  <g transform="translate({x} {y0})">
    <rect width="{w}" height="78" rx="14" fill="{CHIP}" stroke="{CHIP_EDGE}"/>
    <text x="13" y="35" class="chipbig">{big}</text>
    <text x="13" y="59" class="chipsmall">{small}</text>
  </g>''')
    return "".join(out)


METER_W = 548


def meter():
    """The out/ref meter under the chips: a live bar of coupling, share of the best."""
    widths = [f(max(0.0, min(1.0, c)) * METER_W) for c in C_VALS]
    return f'''
  <g transform="translate(64 468)">
    <rect width="{METER_W}" height="10" rx="5" fill="#16203f"/>
    <rect width="{METER_W}" height="10" rx="5" fill="url(#meterGrad)" clip-path="url(#meterClip)"/>
    <text x="0" y="33" class="tick">out / ref</text>
    <text x="{METER_W / 2}" y="33" class="tick" text-anchor="middle">coupling, share of the best</text>
    <text x="{METER_W}" y="33" class="tick" text-anchor="end">100%</text>
  </g>''', f'''
    <clipPath id="meterClip"><rect width="{METER_W}" height="10">{anim("width", widths)}</rect></clipPath>
    <linearGradient id="meterGrad" x1="0" x2="1">
      <stop offset="0" stop-color="#7f1d1d"/><stop offset="0.55" stop-color="{LASER}"/><stop offset="1" stop-color="#ffb4a2"/>
    </linearGradient>'''


# ── bench parts ──────────────────────────────────────────────────────────────
def mount(cx, cy, deg_values, name, motors_side):
    """A kinematic mirror mount seen from above, with its two NEMA 8 motors behind it.
    Local frame: the mirror lies along x; +y points behind the mirror (motor side)."""
    side = 1 if motors_side == "back" else -1
    m = f'''
  <g transform="translate({cx} {cy}) rotate({-45 if side > 0 else 135})">
    <!-- motors, couplers and hex rods, behind the mount -->
    {"".join(f"""
    <g transform="translate({mx} 0)">
      <line x1="0" y1="6" x2="0" y2="15" stroke="#cbd5e1" stroke-width="1.8"/>
      <rect x="-4.5" y="13" width="9" height="8" rx="1.8" fill="{BRASS}"/>
      <line x1="-4.5" y1="17" x2="4.5" y2="17" stroke="#8a6a24" stroke-width="0.8"/>
      <rect x="-12" y="21" width="24" height="25" rx="3.5" fill="url(#metal)" stroke="{METAL_EDGE}"/>
      <rect x="-12" y="40" width="24" height="6" rx="2" fill="#11182f" stroke="{METAL_EDGE}"/>
      <line x1="-7" y1="27" x2="7" y2="27" stroke="#4b5f95" stroke-width="1.2"/>
    </g>""" for mx in (-17, 17))}
    <rect x="-25" y="1" width="50" height="6" rx="2" fill="#151d38" stroke="{METAL_EDGE}"/>
  </g>
  <g>
    {anim_rotate(deg_values, cx, cy)}
    <g transform="translate({cx} {cy}) rotate(-45)">
      <rect x="-19" y="-2.2" width="38" height="4.4" rx="1.5" fill="{MIRROR}" filter="url(#softglow)"/>
      <rect x="-19" y="{-0.2 if side > 0 else -2.2}" width="38" height="2.4" fill="#94a3b8" opacity="0.55"/>
    </g>
  </g>'''
    return m


def motor_spin_marks():
    """Little turning arrows by each pair of motors, shown while those motors move."""
    out = []
    groups = {"m1": (0, 1), "m2": (2, 3)}
    for name, axes in groups.items():
        segs, on, start = [], False, 0.0
        for i in range(1, len(KF)):
            moving = bool(np.any(np.abs(KF[i][1]["pos"][list(axes)] - KF[i - 1][1]["pos"][list(axes)]) > 0.5))
            a_prev, a = KF[i - 1][0], KF[i][0]
            if moving and not on:
                on, start = True, a_prev
            elif not moving and on:
                on = False
                segs.append((start, a_prev))
        if on:
            segs.append((start, KF[-1][0]))
        merged = []
        for s in segs:                        # bridge gaps shorter than a blink
            if merged and s[0] - merged[-1][1] < 0.25:
                merged[-1] = (merged[-1][0], s[1])
            else:
                merged.append(s)
        out.append((name, timeline(merged)))
    return dict(out)


SPIN = motor_spin_marks()


def spin_icon(x, y, which):
    return f'''
  <g opacity="0">
    {SPIN[which]}
    <g transform="translate({x} {y})" filter="url(#softglow)">
      <path d="M-7 0 A7 7 0 1 1 0 7" fill="none" stroke="{INFO}" stroke-width="1.8" stroke-linecap="round">
        <animateTransform attributeName="transform" type="rotate" values="0;360" dur="0.9s" repeatCount="indefinite"/>
      </path>
    </g>
  </g>'''


# ── fiber-face inset ─────────────────────────────────────────────────────────
INSET = (1158, 96, 58)          # cx, cy, r (r = 62.5 um, the cladding)
UM = INSET[2] / 62.5            # px per um


def inset():
    cx, cy, r = INSET
    xs = [f(cx + k[1]["spot"][0] * UM) for k in KF]
    ys = [f(cy - k[1]["spot"][1] * UM) for k in KF]
    # the spot's path, drawn as it goes: dash offset follows the cumulative length
    pts, lens_, total = [], [], 0.0
    for i, k in enumerate(KF):
        p = (cx + k[1]["spot"][0] * UM, cy - k[1]["spot"][1] * UM)
        if pts:
            total += math.dist(p, pts[-1])
        pts.append(p)
        lens_.append(total)
    total = max(total, 1.0)
    trail = " ".join(f"{f(x)},{f(y)}" for x, y in pts)
    offs = [f(total - l) for l in lens_]
    offs[-1] = f(total)
    trail_op = ["0.55" if KF[i][0] < A_END + 0.8 else "0" for i in range(len(KF))]
    tip_x, tip_y = X_FIBER + 3, Y_TOP
    # tangent lines from the fiber tip to the circle
    dx, dy = cx - tip_x, cy - tip_y
    dist = math.hypot(dx, dy)
    a0 = math.atan2(dy, dx)
    da = math.asin(r / dist)
    t1 = (tip_x + math.cos(a0 - da) * math.sqrt(dist ** 2 - r ** 2), tip_y + math.sin(a0 - da) * math.sqrt(dist ** 2 - r ** 2))
    t2 = (tip_x + math.cos(a0 + da) * math.sqrt(dist ** 2 - r ** 2), tip_y + math.sin(a0 + da) * math.sqrt(dist ** 2 - r ** 2))
    return f'''
  <path d="M{tip_x} {tip_y} L{f(t1[0])} {f(t1[1])} M{tip_x} {tip_y} L{f(t2[0])} {f(t2[1])}" stroke="{LENS}" stroke-opacity="0.35" stroke-width="1" stroke-dasharray="3 4"/>
  <circle cx="{cx}" cy="{cy}" r="{r + 7}" fill="{CARD}" fill-opacity="0.92" stroke="{CARD_EDGE}"/>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="url(#cladding)"/>
  <clipPath id="faceClip"><circle cx="{cx}" cy="{cy}" r="{r}"/></clipPath>
  <g clip-path="url(#faceClip)">
    <line x1="{cx - r}" y1="{cy}" x2="{cx + r}" y2="{cy}" stroke="#ffffff" stroke-opacity="0.06"/>
    <line x1="{cx}" y1="{cy - r}" x2="{cx}" y2="{cy + r}" stroke="#ffffff" stroke-opacity="0.06"/>
    <polyline points="{trail}" fill="none" stroke="{LASER}" stroke-width="1.2" stroke-linejoin="round"
              stroke-dasharray="{f(total)} {f(total)}" stroke-dashoffset="{f(total)}" opacity="0.55">
      {anim("stroke-dashoffset", offs)}
      {anim("opacity", trail_op)}
    </polyline>
    <circle cx="{cx}" cy="{cy}" r="3.2" fill="none" stroke="{LENS}" stroke-width="1.6" filter="url(#softglow)"/>
    <circle cx="{xs[0]}" cy="{ys[0]}" r="4.2" fill="{LASER}" filter="url(#glow)">
      {anim("cx", xs)}
      {anim("cy", ys)}
    </circle>
    <circle cx="{xs[0]}" cy="{ys[0]}" r="1.6" fill="{LASER_HOT}">
      {anim("cx", xs)}
      {anim("cy", ys)}
    </circle>
  </g>
  <text x="{cx}" y="{cy - r - 16}" text-anchor="middle" class="label">fiber face</text>
  <text x="{cx + r + 14}" y="{cy - 4}" class="small">core</text>
  <text x="{cx + r + 14}" y="{cy + 10}" class="small">~4 µm</text>
  <line x1="{cx + 5}" y1="{cy - 2}" x2="{cx + r + 10}" y2="{cy - 8}" stroke="{MUTED}" stroke-opacity="0.6" stroke-width="0.8"/>
  <text x="{cx}" y="{cy + r + 22}" text-anchor="middle" class="small">125 µm cladding</text>'''


# ── coupling chart card ──────────────────────────────────────────────────────
CARDR = (884, 304, 366, 252)     # x, y, w, h
T0, T1 = -PRE_S, T_DONE + POST_S


def chart():
    x, y, w, h = CARDR
    px0, px1 = x + 46, x + w - 18
    py0, py1 = y + h - 36, y + 98           # 0 and 100%
    sx = lambda t: px0 + (t - T0) / (T1 - T0) * (px1 - px0)
    sy = lambda r: py0 - min(max(r, 0.0), 1.08) * (py0 - py1)
    pts = [(sx(fr["t"]), sy(fr["ratio"])) for fr in FRAMES if fr["ratio"] is not None]
    d = "M" + " L".join(f"{f(a)} {f(b)}" for a, b in pts)
    area = d + f" L{f(pts[-1][0])} {f(py0)} L{f(pts[0][0])} {f(py0)}Z"
    dots = "".join(f'<circle cx="{f(a)}" cy="{f(b)}" r="1.5"/>' for a, b in pts)
    # reveal: a clip rect whose right edge follows the playhead
    widths = [f(max(0.0, sx(min(max(k[1]["t"], T0), T1)) - px0 + 2)) for k in KF]
    for i, k in enumerate(KF):
        if k[0] >= DUR - 0.01:
            widths[i] = "0"
    head_x = [f(sx(k[1]["t"])) for k in KF]
    head_y = [f(sy(k[1]["ratio"] if k[1]["ratio"] is not None else 0.0)) for k in KF]
    trace_op = ["1" if k[0] <= A_END + 0.8 else "0" for k in KF]
    bands, band_labels = [], []
    for t_a, t_b, color, label in ((T_SEARCH, T_PEAK, WARN, "search M2"), (T_PEAK, T_DONE, INFO, "steer + walk")):
        bands.append(f'<rect x="{f(sx(t_a))}" y="{py1 - 14}" width="{f(sx(t_b) - sx(t_a))}" height="{f(py0 - py1 + 14)}" '
                     f'fill="{color}" fill-opacity="0.07"/>'
                     f'<rect x="{f(sx(t_a))}" y="{py1 - 14}" width="{f(sx(t_b) - sx(t_a))}" height="2" fill="{color}" fill-opacity="0.7"/>')
        band_labels.append(f'<g opacity="1">{timeline([(anim_time(t_a) + 0.15, A_END + 0.8)])}'
                           f'<text x="{f((sx(t_a) + sx(t_b)) / 2)}" y="{py1 - 20}" text-anchor="middle" class="band" fill="{color}">{label}</text></g>')
    ticks = "".join(f'<text x="{f(sx(t))}" y="{py0 + 17}" text-anchor="middle" class="tick">{lab}</text>'
                    for t, lab in ((0, "0 s"), (5, "5"), (10, "10"), (15, "15 s")))
    grid = "".join(f'<line x1="{px0}" y1="{f(sy(v))}" x2="{px1}" y2="{f(sy(v))}" stroke="#ffffff" stroke-opacity="{op}"/>'
                   f'<text x="{px0 - 8}" y="{f(sy(v) + 4)}" text-anchor="end" class="tick">{lab}</text>'
                   for v, op, lab in ((0, 0.12, "0"), (0.5, 0.05, "50%"), (1.0, 0.08, "100%")))
    return f'''
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="14" fill="{CARD}" fill-opacity="0.94" stroke="{CARD_EDGE}"/>
  <text x="{x + 16}" y="{y + 26}" class="cardtitle">out / ref, live</text>
  <text x="{x + 16}" y="{y + 46}" class="small">bench twin replay · M1 knocked {KNOCK_MRAD:g} mrad · single-mode fiber</text>
  {status_pills(x + w - 14, y + 11)}
  {grid}
  <line x1="{f(sx(0))}" y1="{py1 - 14}" x2="{f(sx(0))}" y2="{py0}" stroke="{BAD}" stroke-opacity="0.7" stroke-dasharray="3 3"/>
  <text x="{f(sx(0) - 5)}" y="{py1 - 20}" text-anchor="end" class="band" fill="{BAD}">knock</text>
  <clipPath id="reveal"><rect x="{px0}" y="{y}" width="{f(px1 - px0 + 2)}" height="{h}">{anim("width", widths)}</rect></clipPath>
  <g clip-path="url(#reveal)">
    {"".join(bands)}
    <g>
      {anim("opacity", trace_op)}
      <path d="{area}" fill="url(#chartFill)" opacity="0.28"/>
      <path d="{d}" fill="none" stroke="{LASER}" stroke-width="1.6" stroke-linejoin="round" filter="url(#softglow)"/>
      <g fill="#ffb4a2">{dots}</g>
    </g>
  </g>
  {"".join(band_labels)}
  <circle cx="{f(pts[-1][0])}" cy="{f(pts[-1][1])}" r="4" fill="#fff" filter="url(#glow)">
    {anim("cx", head_x)}
    {anim("cy", head_y)}
  </circle>
  {ticks}'''


def pill_text_width(text):
    """Width of 11 px heavy caps with 0.6 px tracking, close to what browsers draw."""
    w = {" ": 3.6, ".": 3.6, "·": 3.6, "%": 9.5}
    return sum(w.get(c, 7.0 if c.isdigit() else 8.3) for c in text)


def status_pills(right, top):
    """LOCKED / KNOCKED / SEARCHING / PEAKING / LOCKED again, top right of the card."""
    a_search = A_START + T_SEARCH / SPEED
    a_peak = A_START + T_PEAK / SPEED
    states = [
        ("LOCKED", OK, [(0.0, A_KNOCK)]),
        ("KNOCKED", BAD, [(A_KNOCK, a_search if a_search > A_KNOCK + 0.3 else A_START)]),
        ("SEARCHING", WARN, [(a_search if a_search > A_KNOCK + 0.3 else A_START, a_peak)]),
        ("PEAKING", INFO, [(a_peak, A_DONE)]),
        (f"BACK AT {FINAL * 100:.2f}% · {T_DONE:.0f} S", OK, [(A_DONE, DUR)]),
    ]
    out = []
    for k, (text, color, spans) in enumerate(states):
        tw = pill_text_width(text)
        wpx = tw + 32
        out.append(f'''
  <g opacity="{1 if k == len(states) - 1 else 0}">{timeline(spans)}
    <rect x="{f(right - wpx)}" y="{top}" width="{f(wpx)}" height="22" rx="11" fill="{color}" fill-opacity="0.13" stroke="{color}" stroke-opacity="0.55"/>
    <circle cx="{f(right - wpx + 12)}" cy="{top + 11}" r="3.6" fill="{color}"/>
    <text x="{f(right - wpx + 21)}" y="{top + 15.5}" class="pilltext" fill="{color}" textLength="{f(tw)}" lengthAdjust="spacingAndGlyphs">{text}</text>
  </g>''')
    return "".join(out)


# ── knock burst ──────────────────────────────────────────────────────────────
def knock_burst():
    cx, cy = X_M + 26, Y_LOW + 26
    t = [0, A_KNOCK, A_KNOCK + 0.05, A_KNOCK + 0.7, DUR]
    kt = ";".join(f"{v / DUR:.4f}" for v in t)
    def a(attr, vals):
        return f'<animate attributeName="{attr}" values="{vals}" keyTimes="{kt}" dur="{f(DUR)}s" repeatCount="indefinite"/>'
    rays = "".join(f'<line x1="{f(cx + 12 * math.cos(math.radians(g)))}" y1="{f(cy + 12 * math.sin(math.radians(g)))}" '
                   f'x2="{f(cx + 22 * math.cos(math.radians(g)))}" y2="{f(cy + 22 * math.sin(math.radians(g)))}"/>'
                   for g in (-10, 20, 50, 80, 110))
    return f'''
  <g opacity="0" stroke="{BAD}" stroke-width="2.2" stroke-linecap="round">
    {a("opacity", "0;0;1;0;0")}
    {rays}
  </g>
  <circle cx="{cx}" cy="{cy}" r="6" fill="none" stroke="{BAD}" stroke-width="2" opacity="0">
    {a("opacity", "0;0;0.9;0;0")}
    {a("r", "6;6;6;30;30")}
  </circle>
  <g opacity="0">
    {a("opacity", "0;0;1;0;0")}
    <text x="{cx - 8}" y="{cy + 50}" class="bump" fill="{BAD}">knock!</text>
  </g>'''


# ── fiber, photodiodes, glows ────────────────────────────────────────────────
FIBER_PATH = (f"M{X_FIBER + 20} {Y_TOP} C{X_FIBER + 64} {Y_TOP} {X_FIBER + 70} {Y_TOP + 44} {X_FIBER + 100} {Y_TOP + 52} "
              f"S{X_FIBER + 134} {Y_TOP + 56} {X_FIBER + 134} {Y_TOP + 74}")
OUT_PD = (X_FIBER + 134, Y_TOP + 86)


def glow_ops(scale=1.0, floor=0.0):
    return [f(floor + scale * max(0.0, min(1.0, c))) for c in C_VALS]


def bench():
    line0, cone0 = LINE_VALS[0], CONE_VALS[0]
    beam = f'''
  <g filter="url(#haze)" opacity="0.55">
    <polyline points="{line0}" fill="none" stroke="{LASER}" stroke-width="9" stroke-linejoin="round">{anim("points", LINE_VALS)}</polyline>
  </g>
  <polyline points="{line0}" fill="none" stroke="{LASER}" stroke-width="2.6" stroke-linejoin="round" filter="url(#glow)">{anim("points", LINE_VALS)}</polyline>
  <polyline points="{line0}" fill="none" stroke="{LASER_HOT}" stroke-width="0.9" stroke-linejoin="round">{anim("points", LINE_VALS)}</polyline>
  <polyline points="{line0}" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="1.5 22" opacity="0.85">
    {anim("points", LINE_VALS)}
    <animate attributeName="stroke-dashoffset" values="47;0" dur="0.45s" repeatCount="indefinite"/>
  </polyline>
  <polygon points="{cone0}" fill="{LASER}" fill-opacity="0.75" filter="url(#glow)">{anim("points", CONE_VALS)}</polygon>'''
    # reference arm: the beamsplitter's reflected share, straight down to the reference photodiode
    ref = f'''
  <line x1="{X_BS}" y1="{Y_LOW}" x2="{X_BS}" y2="{Y_LOW + 40}" stroke="{LASER}" stroke-width="1.8" opacity="0.8" filter="url(#glow)"/>
  <rect x="{X_BS - 9}" y="{Y_LOW + 40}" width="18" height="12" rx="2.5" fill="#1b2442" stroke="{METAL_EDGE}"/>
  <rect x="{X_BS - 4}" y="{Y_LOW + 40}" width="8" height="3" fill="#94a3b8"/>
  <circle cx="{X_BS}" cy="{Y_LOW + 42}" r="6" fill="{LASER}" opacity="0.6" filter="url(#haze)"/>'''
    laser = f'''
  <rect x="{X_LASER0}" y="{Y_LOW - 13}" width="{X_LASER1 - X_LASER0}" height="26" rx="6" fill="url(#metal)" stroke="{METAL_EDGE}"/>
  <rect x="{X_LASER0 + 8}" y="{Y_LOW - 7}" width="30" height="14" rx="3" fill="#0a0f22" stroke="#2c3966"/>
  <circle cx="{X_LASER0 + 14}" cy="{Y_LOW}" r="2.4" fill="{OK}"><animate attributeName="opacity" values="1;0.4;1" dur="1.6s" repeatCount="indefinite"/></circle>
  <rect x="{X_LASER1 - 2}" y="{Y_LOW - 5}" width="5" height="10" rx="1.5" fill="#94a3b8"/>
  <rect x="{X_AP - 2}" y="{Y_LOW - 13}" width="4" height="9" rx="1" fill="#3c4c7c"/><rect x="{X_AP - 2}" y="{Y_LOW + 4}" width="4" height="9" rx="1" fill="#3c4c7c"/>
  {"".join(f'<rect x="{x - 2}" y="{Y_LOW - 14}" width="4" height="28" rx="1.5" fill="{POLARIZER}" fill-opacity="0.85"/>' for x in X_POL)}
  <rect x="{X_BS - 9}" y="{Y_LOW - 9}" width="18" height="18" rx="2" fill="{LENS}" fill-opacity="0.18" stroke="{LENS}" stroke-opacity="0.8"/>
  <line x1="{X_BS - 9}" y1="{Y_LOW - 9}" x2="{X_BS + 9}" y2="{Y_LOW + 9}" stroke="{LENS}" stroke-opacity="0.9"/>'''
    top = f'''
  {"".join(f'<rect x="{X_IRIS - 2.5}" y="{y0}" width="5" height="22" rx="1.5" fill="#3c4c7c"/>' for y0 in (Y_TOP - 28, Y_TOP + 6))}
  <path d="M{X_LENS} {Y_TOP - 22} Q{X_LENS + 9} {Y_TOP} {X_LENS} {Y_TOP + 22} Q{X_LENS - 9} {Y_TOP} {X_LENS} {Y_TOP - 22}Z" fill="{LENS}" fill-opacity="0.22" stroke="{LENS}" stroke-width="1.4"/>
  <rect x="{X_LENS - 14}" y="{Y_TOP + 28}" width="28" height="7" rx="2" fill="#151d38" stroke="{METAL_EDGE}"/>
  <rect x="{X_FIBER - 1}" y="{Y_TOP - 14}" width="22" height="28" rx="3" fill="url(#metal)" stroke="{METAL_EDGE}"/>
  <rect x="{X_FIBER - 1}" y="{Y_TOP - 2.5}" width="12" height="5" rx="1" fill="#e2e8f0" fill-opacity="0.85"/>
  <path d="{FIBER_PATH}" fill="none" stroke="{FIBER}" stroke-width="5" stroke-linecap="round" opacity="0.9"/>
  <path d="{FIBER_PATH}" fill="none" stroke="{LASER}" stroke-width="2.4" stroke-linecap="round" filter="url(#glow)" opacity="{glow_ops()[0]}">{anim("opacity", glow_ops())}</path>
  <path d="{FIBER_PATH}" fill="none" stroke="#fff" stroke-width="1.4" stroke-linecap="round" stroke-dasharray="1.5 16" opacity="{glow_ops(0.8)[0]}">
    {anim("opacity", glow_ops(0.8))}
    <animate attributeName="stroke-dashoffset" values="35;0" dur="0.5s" repeatCount="indefinite"/>
  </path>
  <rect x="{OUT_PD[0] - 11}" y="{OUT_PD[1] - 12}" width="22" height="16" rx="3" fill="#1b2442" stroke="{METAL_EDGE}"/>
  <circle cx="{OUT_PD[0]}" cy="{OUT_PD[1] - 4}" r="11" fill="{LASER}" filter="url(#haze)" opacity="{glow_ops(0.9)[0]}">{anim("opacity", glow_ops(0.9))}</circle>
  <circle cx="{X_FIBER + 3}" cy="{Y_TOP}" r="5" fill="{LASER}" filter="url(#haze)" opacity="{glow_ops(0.9)[0]}">{anim("opacity", glow_ops(0.9))}</circle>'''
    m1 = mount(X_M, Y_LOW, M1_DEG, "M1", "back")
    m2 = mount(X_M, Y_TOP, M2_DEG, "M2", "front")
    labels = f'''
  <text x="{(X_LASER0 + X_LASER1) / 2}" y="{Y_LOW + 32}" text-anchor="middle" class="label">635 nm laser</text>
  <text x="{X_BS}" y="{Y_LOW + 68}" text-anchor="middle" class="small">ref PD</text>
  <text x="{X_M + 16}" y="{Y_LOW - 16}" class="mname">M1</text>
  <text x="{X_M + 16}" y="{Y_TOP + 30}" class="mname">M2</text>
  <text x="{X_M - 64}" y="{Y_TOP - 62}" text-anchor="middle" class="small">2× NEMA 8</text>
  <text x="{X_LENS}" y="{Y_TOP + 52}" text-anchor="middle" class="small">f 8 mm</text>
  <text x="{OUT_PD[0]}" y="{OUT_PD[1] + 20}" text-anchor="middle" class="small">out PD</text>'''
    spins = spin_icon(X_M + 46, Y_LOW + 8, "m1") + spin_icon(X_M - 46, Y_TOP - 8, "m2")
    # dimension lines: the two distances that set how M1 and M2 share the work
    xd, yd = X_M - 30, Y_TOP - 46
    dims = f'''
  <g stroke="{MUTED}" stroke-opacity="0.45" stroke-width="1" fill="none">
    <path d="M{xd - 4} {Y_TOP + 40} H{xd + 4} M{xd} {Y_TOP + 40} V{Y_LOW - 40} M{xd - 4} {Y_LOW - 40} H{xd + 4}" stroke-dasharray="0"/>
    <path d="M{X_M + 30} {yd - 4} V{yd + 4} M{X_M + 30} {yd} H{X_LENS} M{X_LENS} {yd - 4} V{yd + 4}"/>
  </g>
  <text transform="translate({xd - 8} {(Y_TOP + Y_LOW) / 2}) rotate(-90)" text-anchor="middle" class="tick">150 mm</text>
  <text x="{(X_M + 30 + X_LENS) / 2}" y="{yd - 8}" text-anchor="middle" class="tick">310 mm to the lens</text>
  <text x="{X_IRIS}" y="{Y_TOP + 44}" text-anchor="middle" class="small">iris</text>'''
    return ref + laser + top + beam + m1 + m2 + spins + labels + dims


METER_SVG, METER_DEFS = meter()
BG_DEFS, BG_BODY = background(W, H)

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
  <title id="t">ROS-Optics-Bench: a self-aligning laser-to-fiber bench</title>
  <desc id="d">A 635 nm laser beam runs through polarizers and a beamsplitter, folds off two motorized mirrors and is focused into a single-mode fiber. M1 gets knocked, the beam misses the fiber and the coupling drops to zero; the motors search with M2, find the light and walk both mirrors back until the coupling is back at its peak. A fiber-face inset shows the focused spot wandering around the core during the search, and a chart shows the output-to-reference photodiode ratio from the bench twin simulator.</desc>
  <style>
    text {{ font-family: {FONT}; }}
    .eyebrow {{ font-size: 13.5px; letter-spacing: 2.6px; font-weight: 700; fill: {LENS}; }}
    .title {{ font-size: 46px; font-weight: 800; letter-spacing: -0.6px; }}
    .tag {{ font-size: 19px; fill: #a3acc9; }}
    .chipbig {{ font-size: 19px; font-weight: 800; fill: #f1f5ff; }}
    .chipsmall {{ font-size: 13px; fill: {MUTED}; }}
    .foot {{ font-size: 12.5px; fill: {DIM}; }}
    .cardtitle {{ font-size: 15px; font-weight: 700; fill: {FG}; }}
    .label {{ font-size: 12.5px; font-weight: 600; fill: #c9cfe6; }}
    .small {{ font-size: 11.5px; fill: {MUTED}; }}
    .mname {{ font-size: 15px; font-weight: 800; fill: {FG}; }}
    .tick {{ font-size: 11.5px; fill: {MUTED}; font-family: {MONO}; }}
    .band {{ font-size: 11px; font-weight: 700; letter-spacing: 0.3px; }}
    .pill {{ font-size: 13px; font-weight: 700; fill: {WARN}; letter-spacing: 0.4px; }}
    .pilltext {{ font-size: 11px; font-weight: 800; letter-spacing: 0.6px; }}
    .bump {{ font-size: 15px; font-weight: 800; font-style: italic; }}
  </style>
  <defs>{BG_DEFS}{GLOW}
    <filter id="softglow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="1.4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="titleGrad" x1="0" x2="1">
      <stop offset="0" stop-color="#ff2a55"/><stop offset="0.35" stop-color="{LASER}"/>
      <stop offset="0.7" stop-color="#ff8a3d"/><stop offset="1" stop-color="#ffc861"/>
    </linearGradient>
    <linearGradient id="metal" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{METAL0}"/><stop offset="1" stop-color="{METAL1}"/>
    </linearGradient>
    <radialGradient id="cladding" cx="0.5" cy="0.5" r="0.5">
      <stop offset="0" stop-color="#1a2752"/><stop offset="0.8" stop-color="#121b3b"/><stop offset="1" stop-color="#2a3a70"/>
    </radialGradient>
    <linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{LASER}"/><stop offset="1" stop-color="{LASER}" stop-opacity="0"/>
    </linearGradient>{METER_DEFS}
  </defs>

  {BG_BODY}

  <!-- left column: the pitch -->
  <g transform="translate(64 0)">
    <rect x="0" y="62" width="168" height="30" rx="15" fill="{WARN}" fill-opacity="0.12" stroke="{WARN}" stroke-opacity="0.45"/>
    <circle cx="18" cy="77" r="4.5" fill="{WARN}">
      <animate attributeName="opacity" values="1;0.25;1" dur="2.4s" repeatCount="indefinite"/>
    </circle>
    <text x="31" y="82" class="pill">bench bring-up</text>
    <text x="0" y="132" class="eyebrow">PHOTONICS × ROBOTICS × ROS 2</text>
    <text x="0" y="190" class="title" fill="#f1f5ff">Self-Aligning</text>
    <text x="0" y="246" class="title" fill="url(#titleGrad)">Laser-to-Fiber Bench</text>
    <text x="0" y="292" class="tag">Knock a mirror out of line and four stepper-driven</text>
    <text x="0" y="320" class="tag">adjusters steer the beam back into the fiber.</text>
  </g>
  {chips()}
  {METER_SVG}
  <text x="64" y="540" class="foot">† adjuster screw travel: 100 TPI, 3200 microsteps per turn</text>
  <text x="64" y="558" class="foot">* bench twin simulator: 100 knocks of 0.3–3 mrad, each back above 99.9% of the best single-mode coupling</text>

  <!-- the bench, seen from above -->
  {bench()}
  {knock_burst()}
  {inset()}
  {chart()}
</svg>
'''

write("hero.svg", svg)
print(f"run: {len(FRAMES)} frames, search {T_SEARCH:.1f} s, peaking {T_PEAK:.1f} s, done {T_DONE:.1f} s "
      f"at {FINAL:.4f} of best ({RESULT.moves} moves, {RESULT.reads} readings); loop {DUR:.1f} s")
