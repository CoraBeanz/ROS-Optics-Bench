"""Generate electronics/system_wiring.svg: every cable on the bench, around the control board.

Connector numbers match electronics/pcb (control_board and pd_amp). Keep in step with
electronics/wiring.md.

Usage: py -3 electronics/make_system_svg.py electronics/system_wiring.svg
"""
import sys
from xml.sax.saxutils import escape

W, H = 1500, 1180
C = dict(pwr="#c62828", gnd="#212121", usb="#1565c0", motor="#455a64", laser="#e65100", pd="#00695c",
         i2c="#5e35b1", uart="#6a1b9a", vm="#ad1457", mute="#757575", edge="#424242", ad="#2e7d32")
out = []


def a(s):
    out.append(s)


def text(x, y, s, size=13, color="#212121", anchor="start", weight="normal", family="Helvetica, Arial, sans-serif"):
    a(f'<text xml:space="preserve" x="{x}" y="{y}" font-family="{family}" font-size="{size}" fill="{color}" '
      f'text-anchor="{anchor}" font-weight="{weight}">{escape(s)}</text>')


def mono(x, y, s, size=12, color="#212121", anchor="start", weight="normal"):
    text(x, y, s, size, color, anchor, weight, "Menlo, Consolas, monospace")


def rect(x, y, w, h, fill="#fafafa", stroke=C["edge"], rx=6, sw=1.5):
    a(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>')


def poly(pts, color, w=3, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    p = " ".join(f"{x},{y}" for x, y in pts)
    a(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{w}" stroke-linejoin="round" '
      f'stroke-linecap="round"{d}/>')


def plug(x, y, label, color, dx=0, dy=-10, anchor="middle"):
    """Connector on the board edge, with its label offset by (dx, dy)."""
    a(f'<rect x="{x - 9}" y="{y - 7}" width="18" height="14" rx="2" fill="#ffffff" stroke="{color}" stroke-width="2"/>')
    text(x + dx, y + dy, label, 12, color, anchor, "bold")


a(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">')
a(f'<rect width="{W}" height="{H}" fill="#ffffff"/>')
text(40, 42, "Optics bench system wiring: control board, host, motors, laser, photodiodes, test gear", 22,
     weight="bold")
text(40, 66, "Connector numbers are the control board's (electronics/pcb/control_board) and the photodiode "
     "board's (electronics/pcb/pd_amp). All grounds are common through the control board.", 13, C["mute"])

# ── Control board ────────────────────────────────────────────────────────────
BX, BY, BW, BH = 470, 330, 580, 420
rect(BX, BY, BW, BH, fill="#e8f5e9", rx=10, sw=2)
text(BX + BW / 2, BY + 30, "Control board (100 x 100 mm, 2 layers)", 17, anchor="middle", weight="bold")
text(BX + BW / 2, BY + 50, "electronics/pcb/control_board", 12, C["mute"], "middle")
inner = [
    ("A1  ESP32 Feather V2 (plug-in)", "USB-C at the board's top-left edge"),
    ("U1-U4  TMC2209 breakouts (plug-in, screw terminals kept)", "addresses 0-3 set by the board; terminals face the top/bottom edges"),
    ("A2  ADS1115 (plug-in), address 0x48", "A0 = PD reference, A1 = PD output"),
    ("12 V input: PTC fuse, Schottky, TVS, 470 uF", "use J5 or J6, not both; J1-J4 feed each driver's VM"),
]
for i, (t1, t2) in enumerate(inner):
    y = BY + 96 + i * 52
    text(BX + 110, y, t1, 14, weight="bold")
    text(BX + 110, y + 18, t2, 12, C["mute"])

# ── Motors (top) ─────────────────────────────────────────────────────────────
motors = [("U1", "M1X", "mirror M1, X adjuster"), ("U2", "M1Y", "mirror M1, Y adjuster"),
          ("U3", "M2X", "mirror M2, X adjuster"), ("U4", "M2Y", "mirror M2, Y adjuster")]
for i, (j, ax, role) in enumerate(motors):
    px = BX + 80 + i * 140
    mx, my = px, 150
    a(f'<circle cx="{mx}" cy="{my}" r="34" fill="#eceff1" stroke="{C["motor"]}" stroke-width="2"/>')
    text(mx, my - 2, "NEMA 8", 12, C["motor"], "middle", "bold")
    text(mx, my + 14, ax, 13, C["motor"], "middle", "bold")
    text(mx, my - 46, role, 11, C["mute"], "middle")
    for k in range(4):
        x = px - 9 + k * 6
        poly([(x, my + 34), (x, BY - 12)], C["motor"], 1.6)
    plug(px, BY, f"{j} terminals", C["motor"], dx=14, dy=-12, anchor="start")
text(BX + BW + 20, 130, "Motors wire into each breakout's screw terminals", 13, C["motor"], weight="bold")
for i, s in enumerate(["1A  } coil A", "1B  }", "2A  } coil B", "2B  }", "VM +, GND: 2-wire lead from J1-J4 (U1-U4)"]):
    mono(BX + BW + 20, 152 + i * 18, s, 12, C["motor"])
text(BX + BW + 20, 252, "Find a coil with an ohmmeter (a few ohms between its two wires).", 11, C["mute"])
text(BX + BW + 20, 268, "Wrong direction? Set invert in config.h instead of rewiring.", 11, C["mute"])
text(BX + BW + 20, 284, "Connect and disconnect motors only with 12 V off.", 11, C["mute"])

# ── Host (left) ──────────────────────────────────────────────────────────────
rect(40, 330, 300, 170, fill="#e3f2fd")
text(190, 360, "NVIDIA Jetson (ROS 2 host)", 15, anchor="middle", weight="bold")
text(190, 380, "optimizer, camera, experiment control", 12, C["mute"], "middle")
mono(60, 412, "USB-A  -> Feather USB-C", 12, C["usb"])
mono(60, 432, "        serial 115200 baud,", 12, C["mute"])
mono(60, 450, "        also powers the Feather", 12, C["mute"])
mono(60, 478, "USB-A  -> camera (USB 2.0)", 12, C["usb"])
poly([(340, 410), (BX - 12, 410)], C["usb"], 4)
plug(BX, 410, "USB-C (A1)", C["usb"], dx=16, dy=5, anchor="start")
text(345, 386, "USB-A to USB-C data cable", 12, C["usb"], weight="bold")

rect(40, 600, 300, 120, fill="#e3f2fd")
text(190, 630, "Arducam OV9281 (UVC)", 15, anchor="middle", weight="bold")
text(190, 650, "global-shutter beam profiler, phase 1", 12, C["mute"], "middle")
text(190, 668, "M12 lens removed; bare sensor in the beam", 12, C["mute"], "middle")
text(190, 700, "USB only, no control-board wiring", 12, C["usb"], "middle", "bold")
poly([(190, 500), (190, 600)], C["usb"], 4)
text(200, 556, "USB cable", 12, C["usb"], weight="bold")

# ── 12 V supply (right) ──────────────────────────────────────────────────────
rect(1190, 520, 270, 150, fill="#fce4ec")
text(1325, 550, "12 V 2 A DC supply", 15, anchor="middle", weight="bold")
text(1325, 570, "motor power; logic runs from USB", 12, C["mute"], "middle")
text(1325, 600, "barrel plug 5.5 x 2.1 mm, centre +", 12, C["vm"], "middle", "bold")
text(1325, 618, "or bare leads into the screw terminal", 12, C["vm"], "middle")
text(1325, 648, "Drivers answer on UART only with 12 V on", 11, C["mute"], "middle")
poly([(1190, 600), (BX + BW + 12, 600)], C["vm"], 4)
plug(BX + BW, 600, "J6", C["vm"], dx=-16, dy=5, anchor="end")
poly([(1190, 560), (1120, 560), (1120, 540), (BX + BW + 12, 540)], C["vm"], 3, "8 5")
plug(BX + BW, 540, "J5 (+ / -)", C["vm"], dx=-16, dy=5, anchor="end")
text(1075, 700, "J5 or J6 (reverse-polarity protected)", 12, C["vm"])

# ── Bottom row: laser, photodiode boards, Analog Discovery 3 ─────────────────
LY = 880
# laser
rect(40, LY, 330, 200, fill="#fff3e0")
text(205, LY + 28, "Quarton VLM-635-32 LPT laser", 15, anchor="middle", weight="bold")
text(205, LY + 48, "635 nm, < 1 mW, 3-6 V, < 40 mA", 12, C["mute"], "middle")
for i, (pin, wire, dest, col) in enumerate([("J7-1", "+V (red)", "3V3", "pwr"), ("J7-2", "TTL", "GPIO 21, high = on", "laser"),
                                            ("J7-3", "GND (black)", "GND", "gnd")]):
    mono(60, LY + 82 + i * 22, f"{pin}  {wire:<12} {dest}", 12, C[col], weight="bold")
text(60, LY + 160, "Check the module label for wire colours.", 11, C["mute"])
jx = BX + 60
poly([(205, LY), (205, 820), (jx, 820), (jx, BY + BH + 12)], C["laser"], 3)
plug(jx, BY + BH, "J7 laser", C["laser"], dx=0, dy=-14)

# photodiode boards
for i, (j, name, where, ch) in enumerate([("J8", "Reference", "behind the beamsplitter's reflected port", "A0"),
                                          ("J9", "Output", "behind the fiber output", "A1")]):
    x0 = 400 + i * 260
    rect(x0, LY, 240, 200, fill="#e0f2f1")
    text(x0 + 120, LY + 28, f"{name} photodiode board", 15, anchor="middle", weight="bold")
    text(x0 + 120, LY + 46, "electronics/pcb/pd_amp", 12, C["mute"], "middle")
    text(x0 + 120, LY + 64, where, 11, C["mute"], "middle")
    mono(x0 + 16, LY + 96, f"J1-1 3V3  -> {j}-1", 12, C["pwr"], weight="bold")
    mono(x0 + 16, LY + 116, f"J1-2 OUT  -> {j}-2 ({ch})", 12, C["pd"], weight="bold")
    mono(x0 + 16, LY + 136, f"J1-3 GND  -> {j}-3", 12, C["gnd"], weight="bold")
    text(x0 + 16, LY + 166, "3-wire JST-XH lead, 1:1, twisted", 11, C["mute"])
    text(x0 + 16, LY + 182, "BPW34 + MCP6002, 47k || 1 nF", 11, C["mute"])
    jx = BX + 190 + i * 130
    poly([(x0 + 120, LY), (x0 + 120, 840 + i * 20), (jx, 840 + i * 20), (jx, BY + BH + 12)], C["pd"], 3)
    plug(jx, BY + BH, f"{j} PD {name.lower()[:3]}", C["pd"], dx=0, dy=-14)

# Analog Discovery 3
AX = 940
rect(AX, LY, 520, 270, fill="#f1f8e9")
text(AX + 260, LY + 28, "Analog Discovery 3 (bench checks)", 15, anchor="middle", weight="bold")
text(AX + 260, LY + 46, "flywires onto the J10 test header; USB to a laptop", 12, C["mute"], "middle")
ad_rows = [
    ("GND (black)", "J10-1 GND", "gnd"),
    ("Scope 1+ / 1-", "J10-7 PD_REF / J10-1 GND", "pd"),
    ("Scope 2+ / 2-", "J10-8 PD_OUT / J10-1 GND", "pd"),
    ("DIO 0", "J10-5 driver UART bus (115200 8N1)", "uart"),
    ("DIO 1", "J10-6 laser TTL", "laser"),
    ("DIO 2 / DIO 3", "J10-3 SCL / J10-4 SDA (I2C decoder)", "i2c"),
    ("W1 (optional)", "J10-9 ADS1115 A2, spare input for ADC checks", "ad"),
    ("V+ / V-", "leave unconnected (board has its own supplies)", "mute"),
]
for i, (pin, dest, col) in enumerate(ad_rows):
    mono(AX + 20, LY + 80 + i * 22, f"{pin:<15} -> {dest}", 12, C[col], weight="bold" if col != "mute" else "normal")
text(AX + 20, LY + 262, "J10 pinout: 1 GND, 2 3V3, 3 SCL, 4 SDA, 5 UART, 6 LASER, 7 PD_REF, 8 PD_OUT, 9 A2, 10 A3",
     11, C["mute"])
jx = BX + 520
poly([(AX + 260, LY), (AX + 260, 800), (jx, 800), (jx, BY + BH + 12)], C["ad"], 3)
plug(jx, BY + BH, "J10 test", C["ad"], dx=0, dy=-14)

a("</svg>")
with open(sys.argv[1] if len(sys.argv) > 1 else "system_wiring.svg", "w", encoding="utf8") as f:
    f.write("\n".join(out) + "\n")
