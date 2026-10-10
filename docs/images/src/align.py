"""How Auto-align gets the light back (docs/images/align.svg).

Run: py -3 docs/images/src/align.py   (needs numpy; it runs the bench twin, a few seconds)

The main panel is the bench twin's single-mode (sm630) coupling over M1X and M2X
around the peak, the landscape `tools/twin.py landscape` plots, drawn as filled
contour bands (marching squares on a grid sheared along the ridge, so the thin
ridge gets enough samples). Over it are the two recoveries that command plots for
the same 1.2 mrad knock of M1: steer + walk, and one motor at a time. Beside it are
the three steps of Auto-align; below, the results of 100 simulated knocks.
"""
import math
import sys

import numpy as np

from common import *

sys.path.insert(0, str(REPO / "tools"))
from bench_twin import Aligner, Bench, Optics, Settings, make_plan  # noqa: E402

# ── the twin: the scenario of tools/twin.py landscape ───────────────────────
FIBER, SEED = "sm630", 0
KNOCK = 1.2e-3           # rad of M1 tilt about the vertical: the X plane only


def knocked():
    b = Bench(Optics(fiber=FIBER), seed=SEED)
    b.jump_to_peak()
    b.offset[0] += KNOCK
    return b


BENCH = knocked()
PLAN = make_plan(BENCH)
A0 = BENCH.peak_adjuster()
SLOPE = PLAN.slope[0]                    # M2X microsteps per M1X microstep along the walk
NARROW, WALK = PLAN.narrow[0], PLAN.walk[0]
S = Settings()


def coupling(m1, m2):
    """Coupling / best with M1X and M2X moved from the peak (microsteps), as twin.py's grid."""
    m1, m2 = np.broadcast_arrays(np.asarray(m1, float), np.asarray(m2, float))
    adj = np.zeros(m1.shape + (4,)) + A0
    adj[..., 0] += m1
    adj[..., 2] += m2
    flat = adj.reshape(-1, 4)
    eta = np.concatenate([BENCH.coupling(flat[i:i + 2000]) for i in range(0, len(flat), 2000)])
    return (eta / BENCH.best_coupling()).reshape(m1.shape)


def recover(naive):
    """Recover from the knock; positions relative to the new peak, as twin.py plots them."""
    b = knocked()
    said = []
    al = Aligner(b, PLAN, Settings(naive=naive), say=lambda text: said.append((b.clock, text)))
    settled, line_peak = [], al.line_peak

    def settle(*args, **kw):                                 # note where each line search ends
        r = line_peak(*args, **kw)
        settled.append(b.position)
        return r
    al.line_peak = settle
    res = al.recover()
    pos = np.array([p for _, p, _ in al.trace]) - b.peak_motor()
    t = np.array([c for c, _, _ in al.trace])
    t_found = next(c for c, text in said if text == "peaking")
    i_found = int(np.nonzero(t <= t_found + 1e-9)[0][-1])     # the reading that saw light again
    steps = np.vstack([pos[i_found], np.array(settled) - b.peak_motor()])
    return dict(pos=pos, i_found=i_found, t_found=t_found, steps=steps, seconds=res.seconds,
                final=float(b.coupling() / b.best_coupling()))


SW, NV = recover(False), recover(True)

# Contours: sample on (u, v) with M1X = u, M2X = v + SLOPE * u, so v runs across the ridge
U = np.arange(-800, 801, 16.0)
V = np.arange(-96, 97, 1.2)
UU, VV = np.meshgrid(U, V)
ETA = coupling(UU, VV + SLOPE * UU)
LEVELS = [0.02, 0.10, 0.25, 0.50, 0.75, 0.90]
FILLS = ["#4c1224", "#7f1d2a", "#c42a2c", LASER, "#ff8566", LASER_HOT]

# 1-D cuts through the peak for the step cards: M2X alone, and along the walk
CUT = np.linspace(-700, 700, 561)
CUT_STEER = coupling(0 * CUT, CUT)
CUT_WALK = coupling(CUT, SLOPE * CUT)

# The 100-knock trials, from: py -3 tools/twin.py trials -n 100 --compare (seed 0)
#   walk        100/100   time median 19.1 s / worst 65.8 s   coupling median 100.0% / worst 99.9%
#   one motor    68/100                                        coupling worst 35.4%
TRIALS = dict(n=100, sw_ok=100, sw_median_s=19, sw_worst_s=66, nv_ok=68, nv_worst=35)

W, H = 1280, 800
SEARCH_C, SW_C, NV_C = WARN, LENS, POLARIZER
HALO = "#060a18"


# ── marching squares ─────────────────────────────────────────────────────────
# corners: a (i, j), b (i, j+1), c (i+1, j+1), d (i+1, j); edges: 0 a-b, 1 b-c, 2 d-c, 3 a-d
SEGS = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)],
        9: [(0, 2)], 11: [(1, 2)], 12: [(1, 3)], 13: [(0, 1)], 14: [(3, 0)]}


def contours(z, xs, ys, level):
    """Closed loops around z >= level (z[i, j] sampled at xs[j], ys[i]). The grid is
    padded with a low border so every loop closes; returns a list of (n, 2) arrays."""
    zp = np.full((z.shape[0] + 2, z.shape[1] + 2), -1.0)
    zp[1:-1, 1:-1] = z
    xp = np.concatenate([[2 * xs[0] - xs[1]], xs, [2 * xs[-1] - xs[-2]]])
    yp = np.concatenate([[2 * ys[0] - ys[1]], ys, [2 * ys[-1] - ys[-2]]])
    inside = zp >= level
    case = inside[:-1, :-1] * 1 + inside[:-1, 1:] * 2 + inside[1:, 1:] * 4 + inside[1:, :-1] * 8

    def edge(i, j, e):
        """(key, point) for edge e of cell (i, j); the key is shared with the neighbouring cell."""
        if e in (0, 2):                           # horizontal edge on row i or i + 1
            r = i + (e == 2)
            t = (level - zp[r, j]) / (zp[r, j + 1] - zp[r, j])
            return ("h", r, j), (xp[j] + t * (xp[j + 1] - xp[j]), yp[r])
        c = j + (e == 1)                          # vertical edge on column j or j + 1
        t = (level - zp[i, c]) / (zp[i + 1, c] - zp[i, c])
        return ("v", i, c), (xp[c], yp[i] + t * (yp[i + 1] - yp[i]))

    links, where = {}, {}
    for i, j in zip(*np.nonzero((case > 0) & (case < 15))):
        k = int(case[i, j])
        if k in (5, 10):                          # saddle: the cell centre decides
            centre = zp[i:i + 2, j:j + 2].mean() >= level
            segs = [(3, 2), (0, 1)] if (k == 5) == centre else [(3, 0), (1, 2)]
        else:
            segs = SEGS[k]
        for e0, e1 in segs:
            (k0, p0), (k1, p1) = edge(i, j, e0), edge(i, j, e1)
            where[k0], where[k1] = p0, p1
            links.setdefault(k0, []).append(k1)
            links.setdefault(k1, []).append(k0)
    loops, seen = [], set()
    for start in links:
        if start in seen:
            continue
        loop, cur = [], start
        while cur is not None:
            seen.add(cur)
            loop.append(where[cur])
            cur = next((n for n in links[cur] if n not in seen), None)
        loops.append(np.array(loop))
    return loops


def rdp(pts, eps):
    """Ramer-Douglas-Peucker: drop points closer than eps (px) to the simplified line."""
    keep = np.zeros(len(pts), bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, d = pts[i], pts[j] - pts[i]
        rel = pts[i + 1:j] - a
        n = math.hypot(*d)
        dist = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0]) / n if n else np.hypot(rel[:, 0], rel[:, 1])
        k = int(np.argmax(dist))
        if dist[k] > eps:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


def clip_rect(pts, x0, y0, x1, y1):
    """Sutherland-Hodgman: a polygon cut to a rectangle (the SVG clip makes the exact edge)."""
    for axis, lim, below in ((0, x0, False), (0, x1, True), (1, y0, False), (1, y1, True)):
        out = []
        for p, q in zip(pts, np.roll(pts, -1, axis=0)):
            p_in, q_in = (p[axis] <= lim, q[axis] <= lim) if below else (p[axis] >= lim, q[axis] >= lim)
            if p_in:
                out.append(p)
            if p_in != q_in:
                out.append(p + (lim - p[axis]) / (q[axis] - p[axis]) * (q - p))
        pts = np.array(out)
        if len(pts) < 3:
            return pts
    return pts


LOOPS = {lv: contours(ETA, U, V, lv) for lv in LEVELS}


def g(x):
    """One decimal, for long path data."""
    s = f"{x:.1f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def poly(xs, ys):
    return " ".join(f"{f(x)},{f(y)}" for x, y in zip(xs, ys))


class Frame:
    """Screen mapping for a plot box (x0, y0, x1, y1) showing M1X and M2X ranges."""

    def __init__(self, box, m1_range, m2_range):
        self.box = box
        self.m1, self.m2 = m1_range, m2_range
        self.kx = (box[2] - box[0]) / (m1_range[1] - m1_range[0])
        self.ky = (box[3] - box[1]) / (m2_range[1] - m2_range[0])

    def x(self, m1):
        return self.box[0] + (np.asarray(m1, float) - self.m1[0]) * self.kx

    def y(self, m2):
        return self.box[3] - (np.asarray(m2, float) - self.m2[0]) * self.ky

    def bands(self, clip_id, glow=True):
        """The coupling as filled contour bands, lowest level first, clipped to the box."""
        x0, y0, x1, y1 = self.box
        out = [f'<clipPath id="{clip_id}"><rect x="{f(x0)}" y="{f(y0)}" width="{f(x1 - x0)}" height="{f(y1 - y0)}"/></clipPath>',
               f'<g clip-path="url(#{clip_id})">']
        for lv, fill in zip(LEVELS, FILLS):
            d = []
            for loop in LOOPS[lv]:
                pts = np.stack([self.x(loop[:, 0]), self.y(loop[:, 1] + SLOPE * loop[:, 0])], -1)
                pts = clip_rect(rdp(np.vstack([pts, pts[:1]]), 0.25)[:-1], x0 - 4, y0 - 4, x1 + 4, y1 + 4)
                if len(pts) >= 3:
                    d.append("M" + " ".join(f"{g(a)} {g(b)}" for a, b in pts) + "Z")
            d = "".join(d)
            if glow and lv == 0.25:
                out.insert(2, f'<path d="{d}" fill="{LASER}" opacity="0.6" filter="url(#haze)"/>')
            out.append(f'<path d="{d}" fill="{fill}" fill-opacity="{0.9 if lv < 0.25 else 1}" fill-rule="evenodd"/>')
        out.append("</g>")
        return "\n  ".join(out)

    def dots(self, pos, color, r):
        """One dot per reading (pos: motor positions from the peak)."""
        return "".join(f'<circle cx="{f(a)}" cy="{f(b)}" r="{r}" fill="{color}" stroke="{HALO}" stroke-width="1"/>'
                       for a, b in zip(self.x(pos[:, 0]), self.y(pos[:, 2])))


def ring(x, y, color, r=7):
    return (f'<circle cx="{f(x)}" cy="{f(y)}" r="{r}" fill="none" stroke="{HALO}" stroke-width="4.5" stroke-opacity="0.75"/>'
            f'<circle cx="{f(x)}" cy="{f(y)}" r="{r}" fill="none" stroke="{color}" stroke-width="2.2"/>')


def arrow_head(x, y, ang, size, color):
    """A filled arrowhead with its tip at (x, y), pointing along ang (radians, screen)."""
    c, s = math.cos(ang), math.sin(ang)
    return (f'<path d="M{f(x)} {f(y)} L{f(x - size * c + 0.5 * size * s)} {f(y - size * s - 0.5 * size * c)} '
            f'L{f(x - size * c - 0.5 * size * s)} {f(y - size * s + 0.5 * size * c)}Z" fill="{color}"/>')


def double_arrow(x0, y0, x1, y1, color, width=2, head=8):
    ang = math.atan2(y1 - y0, x1 - x0)
    c, s = math.cos(ang), math.sin(ang)
    return (f'<line x1="{f(x0 + c * head * 0.8)}" y1="{f(y0 + s * head * 0.8)}" x2="{f(x1 - c * head * 0.8)}" '
            f'y2="{f(y1 - s * head * 0.8)}" stroke="{color}" stroke-width="{width}"/>'
            + arrow_head(x1, y1, ang, head, color) + arrow_head(x0, y0, ang + math.pi, head, color))


# ── main panel ───────────────────────────────────────────────────────────────
CARD_M = (48, 146, 708, 518)                 # x, y, w, h
MAIN = Frame((CARD_M[0] + 86, CARD_M[1] + 80, CARD_M[0] + CARD_M[2] - 36, CARD_M[1] + CARD_M[3] - 60),
             (-640, 800), (-700, 520))
RIDGE_ANG = math.atan2(MAIN.ky, MAIN.kx)    # the ridge on screen, pointing down and right

# The zoom: one motor at a time, where the light came back, with the main plot's aspect
ZOOM_X = 4
ZS, ZH, ZCAP = 188, 146, 46                    # inset width, picture height, caption height
ZX0, ZY0 = MAIN.box[2] - ZS - 12, MAIN.box[1] + 12
_nv = NV["pos"][NV["i_found"]:, [0, 2]]
ZC = (_nv.min(axis=0) + _nv.max(axis=0)) / 2
_hx, _hy = ZS / 2 / (ZOOM_X * MAIN.kx), ZH / 2 / (ZOOM_X * MAIN.ky)
ZOOM = Frame((ZX0, ZY0, ZX0 + ZS, ZY0 + ZH), (ZC[0] - _hx, ZC[0] + _hx), (ZC[1] - _hy, ZC[1] + _hy))


def axes():
    x0, y0, x1, y1 = MAIN.box
    out = []
    for v in range(-600, 801, 200):
        x = f(MAIN.x(v))
        out.append(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y1}" stroke="#ffffff" stroke-opacity="{0.08 if v == 0 else 0.035}"/>'
                   f'<text x="{x}" y="{y1 + 19}" text-anchor="middle" class="tick">{v:+d}</text>')
    for v in range(-600, 401, 200):
        y = f(MAIN.y(v))
        out.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="#ffffff" stroke-opacity="{0.08 if v == 0 else 0.035}"/>'
                   f'<text x="{x0 - 9}" y="{f(MAIN.y(v) + 4)}" text-anchor="end" class="tick">{v:+d}</text>')
    out.append(f'<text x="{f((x0 + x1) / 2)}" y="{y1 + 42}" text-anchor="middle" class="axis">M1X from the peak, microsteps</text>'
               f'<text transform="translate({CARD_M[0] + 34} {f((y0 + y1) / 2)}) rotate(-90)" text-anchor="middle" class="axis">M2X from the peak, microsteps</text>')
    return "".join(out).replace(">+0<", ">0<")


def legend(right, y):
    """The colour key of the bands: swatches with their levels, right-aligned at `right`."""
    sw = 33
    x = right - len(LEVELS) * sw + 1
    out = [f'<text x="{x - 10}" y="{y + 12.5}" text-anchor="end" class="ls">coupling / best</text>']
    for k, (lv, fill) in enumerate(zip(LEVELS, FILLS)):
        ink = "#ffe4dc" if k < 4 else "#4a1016"
        out.append(f'<rect x="{x + k * sw}" y="{y}" width="{sw - 1}" height="17" rx="3" fill="{fill}"/>'
                   f'<text x="{f(x + k * sw + (sw - 1) / 2)}" y="{y + 12.5}" text-anchor="middle" class="swatch" fill="{ink}">{lv * 100:.0f}%</text>')
    return "".join(out)


def pill(right, y, text, color, text_w):
    """A status pill ending at `right`; text_w is the text's width, fixed with textLength."""
    x = right - text_w - 31
    return (f'<rect x="{f(x)}" y="{f(y)}" width="{f(text_w + 31)}" height="22" rx="11" fill="{color}" fill-opacity="0.12" '
            f'stroke="{color}" stroke-opacity="0.5"/>'
            f'<circle cx="{f(x + 12)}" cy="{f(y + 11)}" r="3.5" fill="{color}"/>'
            f'<text x="{f(x + 21)}" y="{f(y + 15.5)}" class="pilltext" fill="{color}" textLength="{text_w}" '
            f'lengthAdjust="spacingAndGlyphs">{text}</text>')


def key(x, y):
    """Steer and walk, drawn on a short piece of the ridge."""
    cx, cy, half = x + 56, y + 50, 52
    c, s = math.cos(RIDGE_ANG), math.sin(RIDGE_ANG)
    return f'''
  <rect x="{x}" y="{y}" width="300" height="104" rx="12" fill="{CARD}" fill-opacity="0.94" stroke="{CARD_EDGE}"/>
  <g transform="translate({cx} {cy}) rotate({f(math.degrees(RIDGE_ANG))})">
    <rect x="{-half}" y="-11" width="{2 * half}" height="22" rx="11" fill="url(#stripe)"/>
  </g>
  {double_arrow(cx - c * (half - 2), cy - s * (half - 2), cx + c * (half - 2), cy + s * (half - 2), SW_C)}
  {double_arrow(cx, cy - 33, cx, cy + 33, SW_C, width=2)}
  <text x="{x + 124}" y="{y + 28}" class="klabel">walk<tspan class="kdesc" dx="8">M1 + opposite M2,</tspan></text>
  <text x="{x + 124}" y="{y + 46}" class="kdesc">along the ridge</text>
  <text x="{x + 124}" y="{y + 68}" class="klabel">steer<tspan class="kdesc" dx="8">M2 alone, across it</tspan></text>
  <circle cx="{x + 128}" cy="{y + 85}" r="2.6" fill="{SW_C}" stroke="{HALO}"/>
  <text x="{x + 139}" y="{y + 89.5}" class="kdesc">one out/ref reading</text>'''


def main_panel():
    x, y, w, h = CARD_M
    x0, y0, x1, y1 = MAIN.box
    sp = SW["pos"][:SW["i_found"] + 1]                   # the search: M2 only, seen edge-on here
    col_x = MAIN.x(sp[0, 0])
    m2s = np.unique(np.round(sp[:, 2], 1))
    search = (f'<line x1="{f(col_x)}" y1="{f(MAIN.y(m2s.max()))}" x2="{f(col_x)}" y2="{f(MAIN.y(m2s.min()))}" '
              f'stroke="{SEARCH_C}" stroke-opacity="0.55" stroke-width="1.4" stroke-dasharray="2 3"/>'
              + "".join(f'<circle cx="{f(col_x)}" cy="{f(MAIN.y(m))}" r="2.3" fill="{SEARCH_C}"/>' for m in m2s))
    st, fd, end = SW["pos"][0], SW["pos"][SW["i_found"]], SW["pos"][-1]
    stx, sty = MAIN.x(st[0]), MAIN.y(st[2])
    fx, fy = MAIN.x(fd[0]), MAIN.y(fd[2])
    ex, ey = MAIN.x(end[0]), MAIN.y(end[2])
    c, s = math.cos(RIDGE_ANG), math.sin(RIDGE_ANG)
    # steer + walk: every reading as a dot, and where each line search settled as a line
    route = SW["steps"]
    rx, ry = MAIN.x(route[:, 0]), MAIN.y(route[:, 2])
    long = int(np.argmax(np.hypot(np.diff(rx), np.diff(ry))))           # the long walk
    hx, hy = (rx[long] + rx[long + 1]) / 2, (ry[long] + ry[long + 1]) / 2
    sw = (MAIN.dots(SW["pos"][SW["i_found"]:], SW_C, 2.3)
          + f'<polyline points="{poly(rx, ry)}" fill="none" stroke="{HALO}" stroke-width="6" stroke-opacity="0.8" stroke-linejoin="round"/>'
            f'<polyline points="{poly(rx, ry)}" fill="none" stroke="{SW_C}" stroke-width="2.4" stroke-linejoin="round" filter="url(#softglow)"/>'
          + arrow_head(hx - c * 7, hy - s * 7, RIDGE_ANG + math.pi, 11, SW_C)
          + ring(ex, ey, SW_C))
    lx, ly = (fx + ex) / 2 - s * 20 - c * 8, (fy + ey) / 2 + c * 20 - s * 8
    cross = f"M{f(stx - 6)} {f(sty - 6)} L{f(stx + 6)} {f(sty + 6)} M{f(stx + 6)} {f(sty - 6)} L{f(stx - 6)} {f(sty + 6)}"
    zb = ZOOM.m1[0], ZOOM.m2[1], ZOOM.m1[1], ZOOM.m2[0]
    zx0, zy0, zx1, zy1 = MAIN.x(zb[0]), MAIN.y(zb[1]), MAIN.x(zb[2]), MAIN.y(zb[3])
    return f'''
  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{CARD}" fill-opacity="0.96" stroke="{CARD_EDGE}"/>
  <text x="{x + 24}" y="{y + 36}" class="lt">Coupling over M1X and M2X</text>
  <text x="{x + 24}" y="{y + 58}" class="ls">Single-mode fiber, M1 knocked {KNOCK * 1e3:g} mrad</text>
  {pill(x + w - 24, y + 19, "BENCH TWIN, NOT MEASURED", WARN, 181)}
  {legend(x + w - 24, y + 45)}
  <rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="#070c1f" stroke="{CARD_EDGE}" stroke-opacity="0.7"/>
  {axes()}
  {MAIN.bands("plotClip")}
  {search}
  {sw}
  <path d="{cross}" stroke="{HALO}" stroke-width="5.5" stroke-linecap="round"/>
  <path d="{cross}" stroke="#ffffff" stroke-width="2.2" stroke-linecap="round"/>
  <circle cx="{f(fx)}" cy="{f(fy)}" r="4.5" fill="{SEARCH_C}" filter="url(#glow)"/>
  {ring(MAIN.x(NV["pos"][-1, 0]), MAIN.y(NV["pos"][-1, 2]), NV_C, r=5)}
  <rect x="{f(zx0)}" y="{f(zy0)}" width="{f(zx1 - zx0)}" height="{f(zy1 - zy0)}" rx="2" fill="none" stroke="#e6e9f2" stroke-opacity="0.8" stroke-width="1.2"/>
  <path d="M{f(zx1)} {f(zy0)} L{ZX0} {ZY0 + ZH + ZCAP} M{f(zx1)} {f(zy1)} L{ZX0 + ZS} {ZY0 + ZH + ZCAP}" stroke="#e6e9f2" stroke-opacity="0.3" stroke-dasharray="3 3"/>
  <text x="{f(stx - 13)}" y="{f(sty + 4.5)}" text-anchor="end" class="plabel" fill="{FG}">knocked</text>
  <text x="{f(col_x - 12)}" y="{f(MAIN.y(m2s.max()) + 4.5)}" text-anchor="end" class="plabel" fill="{SEARCH_C}">square spiral on M2</text>
  <text transform="translate({f(lx)} {f(ly)}) rotate({f(math.degrees(RIDGE_ANG))})" text-anchor="middle" class="plabel" fill="{SW_C}">steer + walk</text>
  <text x="{f(ex - 16)}" y="{f(ey + 3)}" text-anchor="end" class="plabel" fill="{FG}">{SW["final"]:.0%} of the best</text>
  <text x="{f(ex - 16)}" y="{f(ey + 20)}" text-anchor="end" class="psmall">after {SW["seconds"]:.0f} s</text>
  {zoom_panel()}
  {key(x0 + 12, y1 - 116)}'''


def zoom_panel():
    nv = NV["pos"][NV["i_found"]:]
    route = NV["steps"]
    fd, end = NV["pos"][NV["i_found"]], NV["pos"][-1]
    rx, ry = ZOOM.x(route[:, 0]), ZOOM.y(route[:, 2])
    cy = ZY0 + ZH
    return f'''
  <rect x="{ZX0 - 1}" y="{ZY0 - 1}" width="{ZS + 2}" height="{ZH + ZCAP + 2}" rx="8" fill="#0b1229" stroke="#e6e9f2" stroke-opacity="0.55"/>
  <rect x="{ZX0}" y="{ZY0}" width="{ZS}" height="{ZH}" fill="#070c1f"/>
  {ZOOM.bands("zoomClip", glow=False)}
  <g clip-path="url(#zoomClip)">
    {ZOOM.dots(nv, NV_C, 2.4)}
    <polyline points="{poly(rx, ry)}" fill="none" stroke="{HALO}" stroke-width="6" stroke-opacity="0.8" stroke-linejoin="round"/>
    <polyline points="{poly(rx, ry)}" fill="none" stroke="{NV_C}" stroke-width="2.4" stroke-linejoin="round"/>
    <circle cx="{f(ZOOM.x(fd[0]))}" cy="{f(ZOOM.y(fd[2]))}" r="5" fill="{SEARCH_C}" filter="url(#glow)"/>
    {ring(ZOOM.x(end[0]), ZOOM.y(end[2]), NV_C, r=8)}
  </g>
  <line x1="{ZX0}" y1="{cy}" x2="{ZX0 + ZS}" y2="{cy}" stroke="#e6e9f2" stroke-opacity="0.25"/>
  <text x="{ZX0 + 12}" y="{cy + 19}" class="plabel" fill="{NV_C}">one motor at a time</text>
  <text x="{ZX0 + ZS - 10}" y="{cy + 19}" text-anchor="end" class="zlabel">{ZOOM_X}×</text>
  <text x="{ZX0 + 12}" y="{cy + 36}" class="psmall">stalls at {NV["final"]:.0%} after {NV["seconds"]:.0f} s</text>'''


# ── step cards ───────────────────────────────────────────────────────────────
CX, CW = 776, 456
STEP_H, STEP_GAP = 140, 12
GX = CX + CW - 152                            # left edge of each card's picture


def step_card(y, n, title, spec, rows, picture):
    x = CX
    return f'''
  <rect x="{x}" y="{y}" width="{CW}" height="{STEP_H}" rx="16" fill="{CARD}" fill-opacity="0.96" stroke="{CARD_EDGE}"/>
  <circle cx="{x + 36}" cy="{y + 29}" r="14" fill="{LENS}" fill-opacity="0.12" stroke="{LENS}" stroke-width="1.5"/>
  <text x="{x + 36}" y="{y + 34.5}" text-anchor="middle" class="num">{n}</text>
  <text x="{x + 60}" y="{y + 36}" class="lt">{title}</text>
  <text x="{x + 24}" y="{y + 60}" class="spec">{spec}</text>
  {"".join(f'<text x="{x + 24}" y="{y + 84 + 18 * i}" class="desc">{t}</text>' for i, t in enumerate(rows))}
  {picture}'''


def spiral_picture(cx, cy, size):
    """The square spiral of this run, on M2X and M2Y, out to where it saw light."""
    sp = SW["pos"][1:SW["i_found"] + 1][:, 2:4]
    k = size / 2 / np.abs(sp).max()
    xs, ys = cx + sp[:, 0] * k, cy - sp[:, 1] * k
    n = len(sp)
    return (f'<polyline points="{poly(xs, ys)}" fill="none" stroke="{SEARCH_C}" stroke-width="1.2" stroke-opacity="0.75" stroke-linejoin="round"/>'
            + "".join(f'<circle cx="{f(a)}" cy="{f(b)}" r="1.5" fill="{SEARCH_C}"/>' for a, b in zip(xs[:-1], ys[:-1]))
            + f'<circle cx="{f(xs[-1])}" cy="{f(ys[-1])}" r="5" fill="{LASER}" filter="url(#glow)"/>'
            f'<circle cx="{f(xs[-1])}" cy="{f(ys[-1])}" r="2" fill="{LASER_HOT}"/>'
            f'<text x="{f(cx)}" y="{f(cy + size / 2 + 22)}" text-anchor="middle" class="tick">{n} points, {SW["t_found"]:.0f} s</text>')


def cut_picture(x0, y0, w, h, eta, label):
    xs = x0 + (CUT - CUT[0]) / (CUT[-1] - CUT[0]) * w
    ys = y0 + h - eta * h
    area = f"M{f(xs[0])} {f(y0 + h)} L" + " L".join(f"{f(a)} {f(b)}" for a, b in zip(xs, ys)) + f" L{f(xs[-1])} {f(y0 + h)}Z"
    return (f'<line x1="{f(x0)}" y1="{f(y0 + h)}" x2="{f(x0 + w)}" y2="{f(y0 + h)}" stroke="{MUTED}" stroke-opacity="0.5"/>'
            f'<path d="{area}" fill="url(#cutFill)"/>'
            f'<polyline points="{poly(xs, ys)}" fill="none" stroke="{LASER}" stroke-width="1.6" stroke-linejoin="round" filter="url(#softglow)"/>'
            f'<text x="{f(x0)}" y="{f(y0 + h + 16)}" class="tick">-700</text>'
            f'<text x="{f(x0 + w / 2)}" y="{f(y0 + h + 16)}" text-anchor="middle" class="tick">0</text>'
            f'<text x="{f(x0 + w)}" y="{f(y0 + h + 16)}" text-anchor="end" class="tick">+700</text>'
            f'<text x="{f(x0 + w / 2)}" y="{f(y0 - 8)}" text-anchor="middle" class="tick">{label}</text>')


def steps():
    y1 = CARD_M[1]
    y2, y3 = y1 + STEP_H + STEP_GAP, y1 + 2 * (STEP_H + STEP_GAP)
    return (step_card(y1, 1, "Find the light", f"square spiral on M2, up to ±{S.search_turns:g} turn",
                      ["No light at the output: M2 steps", "the spot outward until out/ref",
                       f"clears {S.detect_frac:.0%} of its aligned value."],
                      spiral_picture(GX + 76, y1 + 60, 76))
            + step_card(y2, 2, "Steer", f"M2 alone, 1/e at {NARROW:.0f} microsteps on M2X",
                        ["Moves the spot across the", "fiber core: the narrow direction."],
                        cut_picture(GX + 6, y2 + 42, 128, 58, CUT_STEER, "M2X, microsteps"))
            + step_card(y3, 3, "Walk", f"M1 + opposite M2, 1/e at {WALK:.0f} on M1X",
                        ["Keeps the spot still and turns only", "the angle: the wide direction.",
                         f"Repeat until a sweep gains &lt; {S.tol:.1%}."],
                        cut_picture(GX + 6, y3 + 42, 128, 58, CUT_WALK, "M1X along the walk")))


def play_note():
    y = CARD_M[1] + 3 * (STEP_H + STEP_GAP)
    h = CARD_M[1] + CARD_M[3] - y
    return f'''
  <rect x="{CX}" y="{y}" width="{CW}" height="{h}" rx="14" fill="{CARD}" fill-opacity="0.55" stroke="{CARD_EDGE}" stroke-dasharray="5 5"/>
  <text x="{CX + 24}" y="{y + 25}" class="desc">Each line search approaches its points from one side,</text>
  <text x="{CX + 24}" y="{y + 44}" class="desc">so the play in the hex couplings always sits the same way.</text>'''


# ── results strip ────────────────────────────────────────────────────────────
RY, RH = CARD_M[1] + CARD_M[3] + 16, 96


def waffle(x, y, n_on, color, step=7):
    return "".join(f'<circle cx="{x + (k % 10) * step}" cy="{y + (k // 10) * step}" r="2.6" '
                   f'fill="{color if k < n_on else FAINT}"/>' for k in range(100))


def results():
    t = TRIALS
    x, y = 48, RY
    wy = y + (RH - 63) / 2
    return f'''
  <rect x="{x}" y="{y}" width="1184" height="{RH}" rx="16" fill="{CARD}" fill-opacity="0.96" stroke="{CARD_EDGE}"/>
  <text x="{x + 24}" y="{y + 33}" class="lt">{t["n"]} simulated knocks</text>
  <text x="{x + 24}" y="{y + 56}" class="ls">0.3–3 mrad on a random mirror,</text>
  <text x="{x + 24}" y="{y + 75}" class="ls">at 60 RPM and 600 RPM/s</text>
  {waffle(x + 308, wy, t["sw_ok"], SW_C)}
  <text x="{x + 396}" y="{y + 35}" class="big" fill="{SW_C}">{t["sw_ok"]} / {t["n"]}</text>
  <text x="{x + 396}" y="{y + 57}" class="desc"><tspan font-weight="700">steer + walk</tspan>, back above 99.9% of the best</text>
  <text x="{x + 396}" y="{y + 76}" class="ls">median {t["sw_median_s"]} s, worst {t["sw_worst_s"]} s</text>
  {waffle(x + 778, wy, t["nv_ok"], NV_C)}
  <text x="{x + 866}" y="{y + 35}" class="big" fill="{NV_C}">{t["nv_ok"]} / {t["n"]}</text>
  <text x="{x + 866}" y="{y + 57}" class="desc"><tspan font-weight="700">one motor at a time</tspan>, back to 90%</text>
  <text x="{x + 866}" y="{y + 76}" class="ls">the worst ended at {t["nv_worst"]}%</text>'''


BG_DEFS, BG_BODY = background(W, H)
DESC = (f"Filled contour plot of the single-mode fiber coupling, as a share of the best, over M1X and M2X in "
        f"microsteps from the peak, computed by the bench twin simulator, not measured. The high coupling is a long, "
        f"thin ridge running diagonally across the plot. After M1 is knocked {KNOCK * 1e3:g} mrad there is no light; "
        f"a square spiral on M2 finds it on the ridge after {SW['i_found']} points and {SW['t_found']:.0f} s. "
        f"Steer and walk then follows the ridge to the peak and ends at {SW['final']:.0%} of the best after "
        f"{SW['seconds']:.0f} s. A {ZOOM_X} times zoom shows one motor at a time stalling partway along the ridge, "
        f"at {NV['final']:.0%} after {NV['seconds']:.0f} s. A key shows walk, M1 plus an opposite M2 move, along the "
        f"ridge, and steer, M2 alone, across it. Three steps: 1, find the light with a square spiral on M2, up to "
        f"{S.search_turns:g} turn either way by default, until out/ref clears {S.detect_frac:.0%} of its aligned value; "
        f"2, steer with M2 alone, the narrow direction, 1/e at {NARROW:.0f} microsteps of M2X; 3, walk with M1 and an "
        f"opposite M2 move, the wide direction, 1/e at {WALK:.0f} microsteps of M1X, repeated until a sweep gains less "
        f"than {S.tol:.1%}. Each line search approaches its points from one side, so the play in the hex couplings "
        f"always sits the same way. In {TRIALS['n']} simulated knocks of 0.3 to 3 mrad on a random mirror, at 60 RPM "
        f"and 600 RPM/s, steer and walk brought {TRIALS['sw_ok']} back above 99.9% of the best coupling, median "
        f"{TRIALS['sw_median_s']} s, worst {TRIALS['sw_worst_s']} s; one motor at a time brought {TRIALS['nv_ok']} "
        f"back to 90%, and the worst ended at {TRIALS['nv_worst']}%.")

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
  <title id="t">How Auto-align gets the light back</title>
  <desc id="d">{DESC}</desc>
  <style>
    text {{ font-family: {FONT}; }}
    .h1 {{ font-size: 30px; font-weight: 800; fill: #f1f5ff; }}
    .sub {{ font-size: 17px; fill: #a3acc9; }}
    .lt {{ font-size: 19px; font-weight: 700; fill: {FG}; }}
    .ls {{ font-size: 14px; fill: {MUTED}; }}
    .desc {{ font-size: 14.5px; fill: #c9d3f5; }}
    .spec {{ font-size: 14px; font-weight: 600; fill: {LENS}; }}
    .num {{ font-size: 15px; font-weight: 800; fill: {LENS}; }}
    .tick {{ font-size: 11.5px; fill: {MUTED}; font-family: {MONO}; }}
    .axis {{ font-size: 13px; fill: {MUTED}; }}
    .plabel {{ font-size: 13px; font-weight: 700; paint-order: stroke; stroke: {HALO}; stroke-width: 3.5px; stroke-opacity: 0.85; stroke-linejoin: round; }}
    .psmall {{ font-size: 12.5px; fill: #c9d3f5; }}
    .zlabel {{ font-size: 12px; font-weight: 700; fill: {MUTED}; }}
    .swatch {{ font-size: 11px; font-weight: 700; font-family: {MONO}; }}
    .klabel {{ font-size: 13.5px; font-weight: 700; fill: {LENS}; }}
    .pilltext {{ font-size: 11px; font-weight: 800; letter-spacing: 0.6px; }}
    .kdesc {{ font-size: 13px; font-weight: 400; fill: {MUTED}; }}
    .big {{ font-size: 26px; font-weight: 800; }}
  </style>
  <defs>{BG_DEFS}{GLOW}
    <filter id="softglow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="1.4" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <linearGradient id="cutFill" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{LASER}" stop-opacity="0.45"/><stop offset="1" stop-color="{LASER}" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="stripe" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{FILLS[0]}"/><stop offset="0.3" stop-color="{FILLS[2]}"/><stop offset="0.5" stop-color="{LASER_HOT}"/>
      <stop offset="0.7" stop-color="{FILLS[2]}"/><stop offset="1" stop-color="{FILLS[0]}"/>
    </linearGradient>
  </defs>

  {BG_BODY}

  <text x="48" y="66" class="h1">How Auto-align gets the light back</text>
  <text x="48" y="98" class="sub">For a single-mode fiber the peak is a ridge {WALK / NARROW:.0f} times longer than it is wide, running diagonally across M1 and M2.</text>
  <text x="48" y="122" class="sub">One motor at a time often stalls partway along it; steering and walking follow it, the way people align by hand.</text>
  {main_panel()}
  {steps()}
  {play_note()}
  {results()}
</svg>
'''

write("align.svg", svg)
print(f"steer + walk: {SW['final']:.2%} of best after {SW['seconds']:.1f} s (light found at {SW['t_found']:.1f} s); "
      f"one motor at a time: {NV['final']:.2%} after {NV['seconds']:.1f} s (found at {NV['t_found']:.1f} s)")
print(f"ridge: 1/e {NARROW:.1f} (M2X) by {WALK:.1f} (M1 along the walk) microsteps, x{WALK / NARROW:.1f}; "
      f"coupling at the grid's v edges {max(ETA[0].max(), ETA[-1].max()):.4f}")
