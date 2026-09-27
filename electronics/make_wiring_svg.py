"""Generate electronics/wiring.svg. Keep in step with firmware/optics_bench/config.h.

Usage: python electronics/make_wiring_svg.py electronics/wiring.svg
"""
import sys
from xml.sax.saxutils import escape

W, H = 1420, 1310
C = dict(pwr="#c62828", gnd="#212121", uart="#6a1b9a", step="#1565c0", dir="#00838f", en="#2e7d32",
         laser="#e65100", strap="#6d4c41", motor="#455a64", box="#fafafa", edge="#424242", mute="#757575",
         vm="#ad1457")
out = []


def a(s):
    out.append(s)


def text(x, y, s, size=13, color="#212121", anchor="start", weight="normal", family="Helvetica, Arial, sans-serif"):
    a(f'<text xml:space="preserve" x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{color}" '
      f'text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')


def line(x1, y1, x2, y2, color, w=2, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    a(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{w}" stroke-linecap="round"{d}/>')


def poly(pts, color, w=2):
    p = " ".join(f"{x},{y}" for x, y in pts)
    a(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round"/>')


def rect(x, y, w, h, fill=C["box"], stroke=C["edge"], rx=6, sw=1.5):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def dot(x, y, color):
    a(f'<circle cx="{x}" cy="{y}" r="4" fill="{color}"/>')


def resistor(x1, x2, y, color, label):
    # zig-zag between x1 and x2
    n, pts = 6, [(x1, y)]
    step = (x2 - x1) / (n + 1)
    for i in range(1, n + 1):
        pts.append((x1 + i * step, y + (-7 if i % 2 else 7)))
    pts.append((x2, y))
    poly(pts, color)
    text((x1 + x2) / 2, y - 12, label, 12, color, "middle", "bold")


a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
a(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(40, 42, "Optics bench wiring: Feather ESP32 V2, 4x Adafruit TMC2209, Quarton laser", 22, weight="bold")
text(40, 66, "Matches firmware/optics_bench/config.h. Same-named labels are connected. "
     "All grounds (12 V supply, Feather, every breakout) are tied together.", 13, C["mute"])

# ── Feather ──────────────────────────────────────────────────────────────────
FX, FY, FW = 40, 100, 240
feather_pins = [  # pad, gpio, net text, colour key
    ("3V3", None, "3V3 rail (drivers VDD, MS straps, laser)", "pwr"),
    ("GND", None, "GND (common)", "gnd"),
    ("RX", 7, None, "uart"),
    ("TX", 8, None, "uart"),
    ("A5", 4, "M1X STEP", "step"),
    ("13", 13, "M1X DIR", "dir"),
    ("12", 12, "M1X EN", "en"),
    ("27", 27, "M1Y STEP", "step"),
    ("33", 33, "M1Y DIR", "dir"),
    ("15", 15, "M1Y EN", "en"),
    ("32", 32, "M2X STEP", "step"),
    ("14", 14, "M2X DIR", "dir"),
    ("A1", 25, "M2X EN", "en"),
    ("A0", 26, "M2Y STEP", "step"),
    ("SCK", 5, "M2Y DIR", "dir"),
    ("MO", 19, "M2Y EN", "en"),
    ("MI", 21, "LASER TTL", "laser"),
]
ROW = 34
fh = 60 + ROW * len(feather_pins) + 40
rect(FX, FY, FW, fh, fill="#e8eaf6")
text(FX + FW / 2, FY + 26, "Adafruit ESP32 Feather V2", 15, anchor="middle", weight="bold")
text(FX + FW / 2, FY + 44, "(product 5400)  USB-C to PC", 12, C["mute"], "middle")
pin_y = {}
for k, (pad, gpio, net, col) in enumerate(feather_pins):
    y = FY + 72 + k * ROW
    pin_y[pad] = y
    label = pad if gpio is None or str(gpio) == pad else f"{pad}  (GPIO {gpio})"
    if pad in ("RX", "TX"):
        label = f"{pad}  (GPIO {gpio})"
    text(FX + FW - 12, y + 4, label, 13, anchor="end", weight="bold", family="Menlo, Consolas, monospace")
    if net:
        line(FX + FW, y, FX + FW + 40, y, C[col])
        text(FX + FW + 46, y + 4, net, 13, C[col], weight="bold")
text(FX + FW / 2, FY + fh - 14, "SDA 22 / SCL 20 kept free for the ADS1115", 11, C["mute"], "middle")

# ── Drivers ──────────────────────────────────────────────────────────────────
DX, DW, DH, DGAP, DY0 = 660, 470, 256, 22, 100
drivers = [
    ("M1X", 0, "GND", "GND", "A5 (GPIO 4)", "13 (GPIO 13)", "12 (GPIO 12)", "Mirror M1, X adjuster"),
    ("M1Y", 1, "3V3", "GND", "27 (GPIO 27)", "33 (GPIO 33)", "15 (GPIO 15)", "Mirror M1, Y adjuster"),
    ("M2X", 2, "GND", "3V3", "32 (GPIO 32)", "14 (GPIO 14)", "A1 (GPIO 25)", "Mirror M2, X adjuster"),
    ("M2Y", 3, "3V3", "3V3", "A0 (GPIO 26)", "SCK (GPIO 5)", "MO (GPIO 19)", "Mirror M2, Y adjuster"),
]
BUS_X = 590
VM_X, GND_X = 1370, 1395
uart_rows = []
for d, (name, addr, ms1, ms2, step, dirp, en, role) in enumerate(drivers):
    y0 = DY0 + d * (DH + DGAP)
    rect(DX, y0, DW, DH, fill="#f1f8e9")
    text(DX + 14, y0 + 24, f"Driver {name}   UART address {addr}", 15, weight="bold")
    text(DX + 14, y0 + 42, f"Adafruit TMC2209 breakout (6121). {role}", 12, C["mute"])
    rows = [
        ("VDD", "Feather 3V3", "pwr"), ("GND", "Feather GND", "gnd"), ("DIR", f"Feather {dirp}", "dir"),
        ("STEP", f"Feather {step}", "step"), ("MS1", f"tie to {ms1}", "strap"), ("MS2", f"tie to {ms2}", "strap"),
        ("DIAG", "not connected", "mute"), ("INDEX", "not connected", "mute"), ("UART", "UART bus", "uart"),
        ("EN", f"Feather {en}", "en"),
    ]
    for r, (pin, dest, col) in enumerate(rows):
        y = y0 + 64 + r * 19
        text(DX + 14, y + 4, f"{r + 1:>2} {pin}", 12, weight="bold", family="Menlo, Consolas, monospace")
        text(DX + 92, y + 4, dest, 12, C[col], weight="bold" if col not in ("mute",) else "normal")
        if pin == "UART":
            uart_rows.append(y)
            line(BUS_X, y, DX, y, C["uart"])
            dot(BUS_X, y, C["uart"])
    # terminal block
    tx = DX + 300
    rect(tx, y0 + 56, 150, 176, fill="#ffffff", rx=4)
    text(tx + 75, y0 + 74, "screw terminals", 11, C["mute"], "middle")
    terms = [("+ VMotor", "vm"), ("- GND", "gnd"), ("1A", "motor"), ("1B", "motor"), ("2A", "motor"), ("2B", "motor")]
    for t, (lab, col) in enumerate(terms):
        y = y0 + 96 + t * 23
        a(f'<circle cx="{tx + 136}" cy="{y}" r="5" fill="#ffffff" stroke="{C["edge"]}" stroke-width="1.5"/>')
        text(tx + 124, y + 4, lab, 12, C[col], "end", "bold")
        if col == "vm":
            line(tx + 141, y, VM_X, y, C["vm"])
            dot(VM_X, y, C["vm"])
        elif col == "gnd":
            line(tx + 141, y, GND_X, y, C["gnd"])
            dot(GND_X, y, C["gnd"])
    # motor
    mx, my = tx + 225, y0 + 176
    for t, y in enumerate([y0 + 142, y0 + 165, y0 + 188, y0 + 211]):
        poly([(tx + 141, y), (mx - 38, y), (mx - 24, my - 12 + t * 8)], C["motor"], 1.6)
    a(f'<circle cx="{mx}" cy="{my}" r="24" fill="#eceff1" stroke="{C["motor"]}" stroke-width="2"/>')
    text(mx, my + 4, "NEMA 8", 11, C["motor"], "middle", "bold")
    text(mx, my + 40, "coil A: 1A/1B", 10, C["motor"], "middle")
    text(mx, my + 52, "coil B: 2A/2B", 10, C["motor"], "middle")

# ── UART bus with 1k on TX ───────────────────────────────────────────────────
y_rx, y_tx = pin_y["RX"], pin_y["TX"]
line(FX + FW, y_rx, BUS_X, y_rx, C["uart"])
dot(BUS_X, y_rx, C["uart"])
line(FX + FW, y_tx, 430, y_tx, C["uart"])
resistor(430, 500, y_tx, C["uart"], "1 kOhm")
line(500, y_tx, BUS_X, y_tx, C["uart"])
dot(BUS_X, y_tx, C["uart"])
line(BUS_X, y_rx, BUS_X, max(uart_rows), C["uart"], 3)
text(FX + FW + 46, y_rx - 8, "RX direct to bus", 12, C["uart"], weight="bold")
text(FX + FW + 10, y_tx + 22, "TX through 1 kOhm", 12, C["uart"], weight="bold")
text(BUS_X + 8, max(uart_rows) + 22, "UART bus", 12, C["uart"], weight="bold")

# ── 12 V supply ──────────────────────────────────────────────────────────────
last = DY0 + 4 * (DH + DGAP) - DGAP
py = last + 40
line(VM_X, DY0 + 96, VM_X, py, C["vm"], 3)
line(GND_X, DY0 + 96 + 23, GND_X, py, C["gnd"], 3)
rect(1150, py, 250, 74, fill="#fce4ec")
text(1282, py + 26, "12 V 2 A motor supply", 14, anchor="middle", weight="bold")
text(1282, py + 46, "+ to every VMotor, - to every GND", 12, C["mute"], "middle")
text(1282, py + 62, "and to Feather GND", 12, C["mute"], "middle")
dot(VM_X, py, C["vm"])
dot(GND_X, py, C["gnd"])

# ── Laser ────────────────────────────────────────────────────────────────────
LY = FY + fh + 36
rect(FX, LY, 520, 150, fill="#fff3e0")
text(FX + 14, LY + 26, "Quarton VLM-635-32 LPT laser (635 nm, < 1 mW)", 15, weight="bold")
text(FX + 14, LY + 44, "3-6 V, < 40 mA; TTL high = on (1-20 mA input), up to 10 kHz", 12, C["mute"])
laser_rows = [("+V", "Feather 3V3", "pwr"), ("GND", "Feather GND", "gnd"), ("TTL", "Feather MI (GPIO 21)", "laser")]
for r, (pin, dest, col) in enumerate(laser_rows):
    y = LY + 72 + r * 22
    text(FX + 24, y, pin, 13, weight="bold", family="Menlo, Consolas, monospace")
    text(FX + 80, y, dest, 13, C[col], weight="bold")
text(FX + 24, LY + 138, "Check the wire colours against the module's label (usually red +V, black GND).",
     11, C["mute"])
a(f'<rect x="{FX + 380}" y="{LY + 70}" width="90" height="26" rx="4" fill="#bdbdbd" stroke="{C["edge"]}"/>')
line(FX + 470, LY + 83, FX + 510, LY + 83, "#e53935", 3)

# ── Notes ────────────────────────────────────────────────────────────────────
NY = LY + 170
notes = [
    "Notes",
    "- MS1/MS2 have no pull resistors on the breakout: tie each one",
    "  to 3V3 or GND to set that driver's UART address.",
    "- Leave the SPREAD solder jumper open (StealthChop).",
    "- The current pot does nothing: the firmware sets current over UART.",
    "- EN is pulled low on the breakout, so each driver is enabled until",
    "  the firmware boots and drives EN high.",
    "- The drivers only answer on UART once 12 V is on.",
    "- Never connect or disconnect a motor while 12 V is on.",
    "- Coil pairs: find the two wires with a few ohms between them",
    "  (one coil) and put them on 1A/1B, the other pair on 2A/2B.",
]
for k, n in enumerate(notes):
    text(FX, NY + k * 18, n, 13 if k == 0 else 12, "#212121" if k == 0 else C["mute"], weight="bold" if k == 0 else "normal")

a("</svg>")
open(sys.argv[1], "w").write("\n".join(out) + "\n")
print("height used:", NY + len(notes) * 18, "of", H)
