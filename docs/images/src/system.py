"""How the hardware and the code fit together (docs/images/system.svg): the bench, the ESP32
firmware, the serial link, the bench twin and the two front ends, what each runs on, what
passes between them and what has been tested; below them, the design files.

Run: py -3 docs/images/src/system.py   (python3 on Linux)
"""
from common import *

ARROW = "#6b7699"
FW_C, TWIN_C, GUI_C, ROS_C = WARN, POLARIZER, "#fb7185", LENS
MARKERS = {ARROW: "ah", FW_C: "ahFw", TWIN_C: "ahTwin"}
ARR = f'<tspan style="font-family:{FONT}">→</tspan>'   # a sans arrow inside mono text

# columns (x, width) and rows (y, height); the camera's line runs under the twin at CAM_DY
C1, C2, C3 = (48, 316), (500, 300), (880, 352)
R1, R2 = (154, 206), (400, 310)
CAM_DY, TWIN_H = 248, 202
BAND_Y = R2[0] + R2[1] + 18
W, H = 1280, BAND_Y + 72 + 20


def card(x, y, w, h, color, folder, where, title, accent=None):
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{CARD}" fill-opacity="0.96" stroke="{CARD_EDGE}"/>',
           f'<path d="M{x + 1.5} {y + 22} L{x + 1.5} {y + h - 22}" stroke="{accent or color}" stroke-width="3" stroke-linecap="round"/>',
           f'<text x="{x + 22}" y="{y + 32}" class="mono" style="fill:{color}">{folder}<tspan class="ls" dx="8">· {where}</tspan></text>',
           f'<text x="{x + 22}" y="{y + 62}" class="lt">{title}</text>']
    return "\n  ".join(out)


def lines(x, y, rows, cls="desc", dy=20.5):
    return "".join(f'<text x="{x}" y="{f(y + dy * i)}" class="{cls}">{t}</text>' for i, t in enumerate(rows))


def check(x, y, text):
    return (f'<circle cx="{x + 8}" cy="{y - 5}" r="8" fill="{OK}" fill-opacity="0.16" stroke="{OK}" stroke-width="1.4"/>'
            f'<path d="M{x + 4} {y - 5} L{x + 7} {y - 2} L{x + 12.5} {y - 8.5}" fill="none" stroke="{OK}" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'
            f'<text x="{x + 24}" y="{y}" class="test">{text}</text>')


def spec(x, y, rows, key_w=70, dy=19.5):
    """Key / value rows: a muted key and a mono value."""
    return "".join(f'<text x="{x}" y="{f(y + dy * i)}" class="key">{k}</text>'
                   f'<text x="{x + key_w}" y="{f(y + dy * i)}" class="val">{v}</text>' for i, (k, v) in enumerate(rows))


def rule(x0, x1, y):
    return f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{CARD_EDGE}" stroke-width="1"/>'


def badge(right, y, text, color):
    w = 31 + 6.2 * len(text)
    return (f'<rect x="{f(right - w)}" y="{y - 16}" width="{f(w)}" height="22" rx="11" fill="{color}" fill-opacity="0.12" stroke="{color}" stroke-opacity="0.5"/>'
            f'<circle cx="{f(right - w + 11)}" cy="{y - 5}" r="3.2" fill="{color}"/>'
            f'<text x="{f(right - w + 19)}" y="{y - 0.5}" class="badge" style="fill:{color}">{text}</text>')


def arrow(d, color=ARROW, both=False):
    start = f' marker-start="url(#{MARKERS[color]})"' if both else ''
    return f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{start} marker-end="url(#{MARKERS[color]})"/>'


# ── bench parts, drawn small ────────────────────────────────────────────────
def icon_motor(cx, cy):
    return (f'<rect x="{cx - 15}" y="{cy - 15}" width="30" height="30" rx="5" fill="url(#metal)" stroke="{METAL_EDGE}"/>'
            f'<circle cx="{cx}" cy="{cy}" r="7" fill="#11182f" stroke="#4b5f95"/>'
            f'<circle cx="{cx}" cy="{cy}" r="2.2" fill="{BRASS}"/>'
            + "".join(f'<circle cx="{cx + sx * 10}" cy="{cy + sy * 10}" r="1.4" fill="#4b5f95"/>' for sx in (-1, 1) for sy in (-1, 1)))


def icon_laser(cx, cy):
    return (f'<rect x="{cx + 15}" y="{cy - 1}" width="9" height="2" rx="1" fill="{LASER}" filter="url(#glow)"/>'
            f'<rect x="{cx - 20}" y="{cy - 8}" width="34" height="16" rx="4" fill="url(#metal)" stroke="{METAL_EDGE}"/>'
            f'<circle cx="{cx - 12}" cy="{cy}" r="2" fill="{OK}"/>'
            f'<rect x="{cx + 12}" y="{cy - 3.5}" width="4" height="7" rx="1" fill="#94a3b8"/>')


def icon_pd(cx, cy):
    return (f'<path d="M{cx - 5} {cy + 10} V{cy + 16} M{cx + 5} {cy + 10} V{cy + 16}" stroke="#94a3b8" stroke-width="1.6"/>'
            f'<rect x="{cx - 12}" y="{cy - 13}" width="24" height="23" rx="3" fill="#1b2442" stroke="{METAL_EDGE}"/>'
            f'<rect x="{cx - 7}" y="{cy - 8}" width="14" height="13" rx="1.5" fill="#0a0f22" stroke="{POLARIZER}" stroke-opacity="0.7"/>'
            f'<circle cx="{cx}" cy="{cy - 1.5}" r="5" fill="{LASER}" opacity="0.5" filter="url(#haze)"/>')


def icon_camera(cx, cy):
    pins = "".join(f'<rect x="{f(cx - 11.5 + 7 * i)}" y="{cy - 18}" width="3" height="4" fill="#4b5f95"/>'
                   f'<rect x="{f(cx - 11.5 + 7 * i)}" y="{cy + 14}" width="3" height="4" fill="#4b5f95"/>' for i in range(4))
    return (pins + f'<rect x="{cx - 16}" y="{cy - 14}" width="32" height="28" rx="4" fill="#151d38" stroke="#4b5f95" stroke-width="1.4"/>'
            f'<rect x="{cx - 8}" y="{cy - 7}" width="16" height="14" rx="1.5" fill="{OK}" fill-opacity="0.28" stroke="{OK}" stroke-width="1.1"/>')


def bench_panel(x, y, w, h, cam_y):
    """The parts the code talks to, in a dashed panel; the camera's row sits at cam_y."""
    rows = [(icon_motor, "4 mirror axes", ["NEMA 8 + TMC2209, one UART bus"]),
            (icon_laser, "635 nm laser", ["TTL on GPIO 21"]),
            (icon_pd, "2 photodiodes", ["BPW34 + MCP6002 into an ADS1115,", "16-bit ADC on I2C: A0 ref, A1 out"])]
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{CARD}" fill-opacity="0.6" stroke="{CARD_EDGE}" stroke-dasharray="5 5"/>',
           f'<text x="{x + 22}" y="{y + 36}" class="lt">Hardware</text>']
    ry = y + 64
    for icon, name, specs in rows:
        out += [icon(x + 38, ry + 5), f'<text x="{x + 66}" y="{ry}" class="part">{name}</text>', lines(x + 66, ry + 18, specs, "partspec", 16)]
        ry += 46 + 16 * (len(specs) - 1)
    out += [rule(x + 22, x + w - 22, cam_y - 34), icon_camera(x + 38, cam_y), f'<text x="{x + 66}" y="{cam_y - 3}" class="part">OV9281 camera</text>',
            lines(x + 66, cam_y + 15, ["global shutter, UVC", "beam profiler for phase 1"], "partspec", 16)]
    return "\n  ".join(out)


# ── the cards ───────────────────────────────────────────────────────────────
def firmware(x, y, w, h):
    return "\n  ".join([
        card(x, y, w, h, FW_C, "firmware/", "Arduino IDE sketch", "Adafruit ESP32 Feather V2"),
        lines(x + 22, y + 90, ["Moves the four axes inside soft limits,", "keeps positions in flash, releases the",
                               "coils between moves, auto-ranges both", "photodiodes and switches the laser."], dy=20),
        check(x + 22, y + h - 22, "runs on the bench"),
    ])


def bench_link(x, y, w, h):
    return "\n  ".join([
        card(x, y, w, h, FG, "tools/bench_link.py", "Python", "Bench link", accent="url(#linkGrad)"),
        f'<text x="{x + 22}" y="{y + 93}" class="val" style="fill:{FW_C}">SerialLink</text>'
        f'<text x="{x + 116}" y="{y + 93}" class="desc">the ESP32 over USB</text>',
        f'<text x="{x + 22}" y="{y + 116}" class="val" style="fill:{TWIN_C}">SimLink</text>'
        f'<text x="{x + 116}" y="{y + 116}" class="desc">the bench twin</text>',
        lines(x + 22, y + 150, ["Either way the front end gets one", "interface: send(line) and an rx queue."]),
    ])


def test_gui(x, y, w, h):
    return "\n  ".join([
        card(x, y, w, h, GUI_C, "tools/test_gui.py", "PySide6", "Bench test panel"),
        badge(x + w - 18, y + 62, "Aligner", TWIN_C),
        lines(x + 22, y + 90, ["Jog, nudge and go-to for each motor,", "live photodiode plots, Auto-align,",
                               "and Knock buttons on the simulator."], dy=20),
        check(x + 22, y + h - 44, "used on the bench"),
        check(x + 22, y + h - 22, "Auto-align on the simulator only"),
    ])


def ros(x, y, w, h, cam_y):
    return "\n  ".join([
        card(x, y, w, h, ROS_C, "host/ros2_ws/", "Humble, for the Jetson", "ROS 2 packages"),
        badge(x + w - 18, y + 62, "Aligner", TWIN_C),
        f'<text x="{x + 22}" y="{y + 92}" class="node">bench_driver<tspan class="key" dx="8">node in /bench</tspan></text>',
        spec(x + 22, y + 114, [("topics", "status, photodiodes, rx"), ("services", "command, laser, stop, pd_dark"),
                               ("actions", "move_to, align"), ("launch", "port:=sim or /dev/optics_bench")]),
        check(x + 22, y + 197, "run against the simulator only"),
        rule(x + 22, x + w - 22, cam_y - 34),
        f'<text x="{x + 22}" y="{cam_y - 6}" class="node">v4l2_camera {ARR} beam_spot<tspan class="key" dx="8">nodes in /camera</tspan></text>',
        spec(x + 22, cam_y + 15, [("topics", f'image_raw {ARR} beam_spot')]),
        check(x + 22, y + h - 22, "only run on synthetic frames"),
    ])


def twin(x, y, w, h):
    return "\n  ".join([
        card(x, y, w, h, TWIN_C, "tools/bench_twin/", "numpy", "Bench twin"),
        lines(x + 22, y + 91, ["Simulates the optics, motors,", "photodiodes and knocks."]),
        f'<text x="{x + 22}" y="{y + 136}" class="key" style="fill:{TWIN_C};font-weight:700">Aligner</text>'
        f'<text x="{x + 92}" y="{y + 136}" class="aval">spiral search → steer → walk</text>',
        spec(x + 22, y + 156, [("trials", "tools/twin.py")]),
        check(x + 22, y + h - 22, "14 unit tests"),
    ])


def design_band(x, y, w, h):
    def pill(px, pw, folder, name):
        return (f'<rect x="{px}" y="{y + 12}" width="{pw}" height="{h - 24}" rx="12" fill="#121a33" stroke="#3c4c7c"/>'
                f'<text x="{px + 16}" y="{y + 32}" class="mono" style="fill:#c9d3f5">{folder}</text>'
                f'<text x="{px + 16}" y="{y + 51}" class="ls">{name}</text>')
    return "\n  ".join([
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="16" fill="{CARD}" fill-opacity="0.5" stroke="{CARD_EDGE}" stroke-dasharray="5 5"/>',
        pill(x + 18, 234, "cad/", "Onshape STEP, whole bench"),
        pill(x + 264, 252, "electronics/pcb/", "KiCad 10 control board, PD amp"),
        pill(x + 528, 140, "docs/bom/", "bill of materials"),
        lines(x + 690, y + 32, ["Both boards have Gerbers in fab/, ready to order, and",
                                "every pin the firmware touches is set in config.h."], "band", 20),
    ])


# ── assembly ────────────────────────────────────────────────────────────────
x1r, x2l, x2r, x3l = C1[0] + C1[1], C2[0], C2[0] + C2[1], C3[0]
r1b, r2t = R1[0] + R1[1], R2[0]
gap1, gap2 = (x1r + x2l) / 2, (x2r + x3l) / 2
mid12 = (r1b + r2t) / 2
cam_y = R2[0] + CAM_DY
ser_y = R1[0] + 100
fork_y, ros_in = R1[0] + 104, R2[0] + 88

links = "\n  ".join([
    # firmware <-> bench link: commands one way, replies the other
    arrow(f"M{x2l - 4} {ser_y - 28} L{x1r + 4} {ser_y - 28}", FW_C),
    f'<text x="{f(gap1)}" y="{ser_y - 62}" text-anchor="middle" class="data">GOTO M2X 120</text>',
    f'<text x="{f(gap1)}" y="{ser_y - 42}" text-anchor="middle" class="data">PD STREAM 20</text>',
    f'<text x="{f(gap1)}" y="{ser_y - 4}" text-anchor="middle" class="small">USB serial,</text>',
    f'<text x="{f(gap1)}" y="{ser_y + 14}" text-anchor="middle" class="small">115200 baud</text>',
    arrow(f"M{x1r + 4} {ser_y + 28} L{x2l - 4} {ser_y + 28}", FW_C),
    f'<text x="{f(gap1)}" y="{ser_y + 52}" text-anchor="middle" class="data">OK · ERR</text>',
    f'<text x="{f(gap1)}" y="{ser_y + 72}" text-anchor="middle" class="data">EVT DONE</text>',
    # firmware <-> bench: motors and laser out, photodiodes in
    arrow(f"M{C1[0] + 50} {r1b + 4} L{C1[0] + 50} {r2t - 4}"),
    f'<text x="{C1[0] + 60}" y="{f(mid12 + 4.5)}" class="tick">STEP/DIR, UART</text>',
    arrow(f"M{C1[0] + 196} {r1b + 4} L{C1[0] + 196} {r2t - 4}"),
    f'<text x="{C1[0] + 206}" y="{f(mid12 + 4.5)}" class="tick">TTL</text>',
    arrow(f"M{C1[0] + 262} {r2t - 4} L{C1[0] + 262} {r1b + 4}"),
    f'<text x="{C1[0] + 272}" y="{f(mid12 + 4.5)}" class="tick">I2C</text>',
    # the twin behind SimLink
    arrow(f"M{x2l + 120} {r2t - 4} L{x2l + 120} {r1b + 4}", TWIN_C),
    f'<text x="{x2l + 134}" y="{f(mid12 + 5)}" class="small">SimLink runs the twin</text>',
    # bench link -> both front ends
    arrow(f"M{x2r + 4} {fork_y} L{x3l - 4} {fork_y}", both=True),
    arrow(f"M{f(gap2)} {fork_y} L{f(gap2)} {ros_in} L{x3l - 4} {ros_in}"),
    f'<circle cx="{f(gap2)}" cy="{fork_y}" r="3.5" fill="{ARROW}"/>',
    # camera -> ROS, under the twin
    arrow(f"M{x1r + 4} {cam_y} L{x3l - 4} {cam_y}"),
    f'<text x="{f(gap1)}" y="{cam_y - 10}" text-anchor="middle" class="small">USB video</text>',
])

BG_DEFS, BG_BODY = background(W, H, fade_cx=0.5, fade_cy=0.55)
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-labelledby="t d">
  <title id="t">How the bench's hardware and code fit together</title>
  <desc id="d">Block diagram. The hardware: four NEMA 8 steppers on TMC2209 drivers sharing one UART bus turn the mirror adjusters, a 635 nm laser is switched by a TTL line on GPIO 21, and two BPW34 photodiodes with MCP6002 amplifiers are read by an ADS1115 16-bit ADC on I2C, A0 the reference and A1 the output. An OV9281 global-shutter USB camera, not tried yet, is the beam profiler for phase 1. An Adafruit ESP32 Feather V2 runs the Arduino IDE sketch in firmware/: it moves the four axes inside soft limits, keeps their positions in flash, releases the coils between moves, auto-ranges both photodiodes and switches the laser. It talks to the host over USB serial at 115200 baud in a plain-text protocol, one command per line, such as GOTO M2X 120 or PD STREAM 20, with OK or ERR replies and EVT DONE when a move ends. tools/bench_link.py gives the host one interface, send(line) and an rx queue, to either the real ESP32 (SerialLink) or the bench twin (SimLink). Two front ends use it and run the same Aligner: the PySide6 bench test panel in tools/test_gui.py, and the ROS 2 Humble packages in host/ros2_ws, whose bench_driver node in /bench publishes the status, photodiodes and rx topics, offers the command, laser, stop and pd_dark services and the move_to and align actions. In /camera, the v4l2_camera node publishes the camera's images on /camera/image_raw, and the beam_spot node finds the spot in them and publishes /camera/beam_spot. The launch argument port:=sim runs the driver on the simulator, and port:=/dev/optics_bench on the ESP32. tools/bench_twin simulates the optics, motors, photodiodes and knocks and holds the Aligner, which searches in a spiral when there is no light, then steers and walks back to the peak; tools/twin.py runs it in trials. The firmware runs on the bench and the test panel is used there; the test panel's Auto-align and the bench_driver node have only been run against the simulator, the beam_spot node has only been run on synthetic frames, and the twin has 14 unit tests. A band at the bottom lists the design files: the Onshape STEP of the whole bench in cad/, the KiCad 10 control board and photodiode amplifier in electronics/pcb with Gerbers ready to order, and the bill of materials in docs/bom; every pin the firmware touches is set in config.h.</desc>
  <style>
    text {{ font-family: {FONT}; }}
    .h1 {{ font-size: 30px; font-weight: 800; fill: #f1f5ff; }}
    .sub {{ font-size: 17px; fill: #a3acc9; }}
    .lt {{ font-size: 19px; font-weight: 700; fill: {FG}; }}
    .ls {{ font-size: 14.5px; fill: {MUTED}; font-family: {FONT}; font-weight: 400; }}
    .desc {{ font-size: 14.5px; fill: #c9d3f5; }}
    .test {{ font-size: 14px; fill: #8fd9b6; }}
    .small {{ font-size: 13.5px; fill: {MUTED}; font-style: italic; }}
    .mono {{ font-size: 14px; font-weight: 700; fill: {FG}; font-family: {MONO}; }}
    .data {{ font-size: 13px; fill: {FG}; font-family: {MONO}; }}
    .tick {{ font-size: 12px; fill: {MUTED}; font-family: {MONO}; }}
    .key {{ font-size: 13px; fill: {MUTED}; font-family: {FONT}; font-weight: 400; }}
    .val {{ font-size: 13px; fill: {LENS}; font-family: {MONO}; }}
    .aval {{ font-size: 13.5px; fill: #c9d3f5; }}
    .node {{ font-size: 13.5px; font-weight: 700; fill: {FG}; font-family: {MONO}; }}
    .badge {{ font-size: 12px; font-weight: 700; }}
    .part {{ font-size: 14.5px; font-weight: 700; fill: {FG}; }}
    .partspec {{ font-size: 13px; fill: {MUTED}; }}
    .band {{ font-size: 14.5px; fill: #a3acc9; }}
  </style>
  <defs>{BG_DEFS}{GLOW}
    {"".join(f'<marker id="{m}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10z" fill="{c}"/></marker>' for c, m in MARKERS.items())}
    <linearGradient id="metal" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{METAL0}"/><stop offset="1" stop-color="{METAL1}"/></linearGradient>
    <linearGradient id="linkGrad" x1="0" y1="{R1[0] + 22}" x2="0" y2="{r1b - 22}" gradientUnits="userSpaceOnUse">
      <stop offset="0.2" stop-color="{FW_C}"/><stop offset="0.8" stop-color="{TWIN_C}"/>
    </linearGradient>
  </defs>

  {BG_BODY}

  <text x="48" y="66" class="h1">How it fits together</text>
  <text x="48" y="98" class="sub">The ESP32 does the real-time work. The test panel and ROS 2 both speak its plain-text serial protocol,</text>
  <text x="48" y="122" class="sub">and the simulator answers the same commands, so it can stand in for the bench.</text>

  {firmware(C1[0], R1[0], C1[1], R1[1])}
  {bench_panel(C1[0], R2[0], C1[1], R2[1], cam_y)}
  {bench_link(C2[0], R1[0], C2[1], R1[1])}
  {twin(C2[0], R2[0], C2[1], TWIN_H)}
  {test_gui(C3[0], R1[0], C3[1], R1[1])}
  {ros(C3[0], R2[0], C3[1], R2[1], cam_y)}

  {links}

  {design_band(48, BAND_Y, 1184, 72)}
</svg>
'''
write("system.svg", svg)
