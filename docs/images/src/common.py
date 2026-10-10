"""Shared palette and helpers for the SVG diagram scripts in this folder.

Each script writes one SVG next to this folder, in docs/images:

    py -3 docs/images/src/hero.py         the README banner (needs numpy: it runs the bench twin)
    py -3 docs/images/src/beam_path.py    the optical path
    py -3 docs/images/src/system.py       how the code and hardware talk
    py -3 docs/images/src/align.py        how Auto-align gets the light back (needs numpy too)
"""
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent
REPO = OUT_DIR.parent.parent

FONT = "ui-sans-serif, -apple-system, 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"

# Page
BG0, BG1, BG2 = "#101a3a", "#0a1024", "#060914"     # background gradient, top left to bottom right
HOLE = "#1d2955"                                    # breadboard holes
FG, MUTED, FAINT, DIM = "#e6e9f2", "#8b93b0", "#2a3358", "#6b7394"
CARD, CARD_EDGE = "#0e1631", "#2c3b6e"
CHIP, CHIP_EDGE = "#0f1833", "#25325e"

# Bench parts
LASER = "#ff3b2f"          # the 635 nm beam
LASER_HOT = "#ffd2c2"      # its core
LENS = "#7dd3fc"
MIRROR = "#e2e8f0"
POLARIZER = "#c4b5fd"
BRASS = "#e0b354"
FIBER = "#facc15"          # OS2 single-mode jacket yellow
METAL0, METAL1, METAL_EDGE = "#2b3a63", "#18213f", "#3c4c7c"

# Status
OK, WARN, BAD, INFO = "#34d399", "#fbbf24", "#f87171", "#7dd3fc"


def f(x):
    """Short number for SVG attributes."""
    s = f"{x:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def background(w, h, fade_cx=0.72, fade_cy=0.55, rx=26):
    """The shared dark page: a gradient and a breadboard of 25 mm holes that fades out."""
    defs = f'''
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{BG0}"/><stop offset="0.55" stop-color="{BG1}"/><stop offset="1" stop-color="{BG2}"/>
    </linearGradient>
    <pattern id="holes" width="28" height="28" patternUnits="userSpaceOnUse">
      <circle cx="14" cy="14" r="1.7" fill="{HOLE}"/>
    </pattern>
    <radialGradient id="fade" cx="{fade_cx}" cy="{fade_cy}" r="0.7">
      <stop offset="0" stop-color="#fff" stop-opacity="1"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
    <mask id="holesMask"><rect width="{w}" height="{h}" fill="url(#fade)"/></mask>'''
    body = (f'<rect width="{w}" height="{h}" rx="{rx}" fill="url(#bg)"/>\n'
            f'  <rect width="{w}" height="{h}" rx="{rx}" fill="url(#holes)" mask="url(#holesMask)"/>')
    return defs, body


GLOW = '''
    <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur stdDeviation="3.2" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
    <filter id="haze" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="7"/></filter>'''


def write(name, svg):
    out = OUT_DIR / name
    out.write_text(svg, encoding="utf-8", newline="\n")
    print("wrote", out.relative_to(REPO), f"({len(svg.encode()) // 1024} KB)")
