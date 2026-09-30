"""Design data for the optics bench boards: parts, nets, schematic and PCB placement.

Everything the generators need lives here, so a pin change is one edit:
  make_lib.py  -> lib/optics_bench.kicad_sym and lib/optics_bench.pretty
  make_sch.py  -> <board>/<board>.kicad_sch (+ project files)
  make_pcb.py  -> <board>/<board>.kicad_pcb (run with KiCad's Python)

Pins must match firmware/optics_bench/config.h and electronics/wiring.md.
"""

GND, V33, V12 = "GND", "+3V3", "+12V"
POWER_NETS = {GND: "power:GND", V33: "power:+3V3", V12: "power:+12V"}
NC = None  # pin gets a no-connect flag

# ── Custom symbols (lib/optics_bench.kicad_sym) ─────────────────────────────
# Each pin: (number, name, electrical type). Left and right columns, top down.
# "" in a column leaves a gap.
SYMBOLS = {
    "Adafruit_Feather_ESP32_V2": dict(
        ref="A", descr="Adafruit ESP32 Feather V2 (product 5400), plugged into two female headers",
        footprint="optics_bench:Adafruit_Feather_ESP32_V2_Socket",
        left=[("2", "3V3", "passive"), ("4", "GND", "passive"), "", ("19", "VBUS", "passive"),
              ("17", "VBAT", "passive"), ("18", "EN", "passive"), ("1", "~{RST}", "passive"),
              ("3", "NC", "passive")],
        right=[("5", "A0/IO26", "passive"), ("6", "A1/IO25", "passive"), ("7", "A2/I34", "passive"),
               ("8", "A3/I39", "passive"), ("9", "A4/I36", "passive"), ("10", "A5/IO4", "passive"),
               ("11", "SCK/IO5", "passive"), ("12", "MO/IO19", "passive"), ("13", "MI/IO21", "passive"),
               ("14", "RX/IO7", "passive"), ("15", "TX/IO8", "passive"), ("16", "I37", "passive"),
               ("20", "IO13", "passive"), ("21", "IO12", "passive"), ("22", "IO27", "passive"),
               ("23", "IO33", "passive"), ("24", "IO15", "passive"), ("25", "IO32", "passive"),
               ("26", "IO14", "passive"), ("27", "SCL/IO20", "passive"), ("28", "SDA/IO22", "passive")],
        width=25.4),
    "Adafruit_TMC2209_Breakout": dict(
        ref="U", descr="Adafruit TMC2209 stepper driver breakout (product 6121), plugged in by its 10-pin "
                       "logic header. Motor and VM wires go to the breakout's own screw terminals",
        footprint="optics_bench:Adafruit_TMC2209_Socket",
        left=[("1", "VDD", "passive"), ("2", "GND", "passive"), "", ("9", "UART", "passive"),
              ("10", "~{EN}", "passive"), ("4", "STEP", "passive"), ("3", "DIR", "passive")],
        right=[("5", "MS1", "passive"), ("6", "MS2", "passive"), "", ("7", "DIAG", "passive"),
               ("8", "INDEX", "passive")],
        width=15.24),
    "Adafruit_ADS1115_Breakout": dict(
        ref="A", descr="Adafruit ADS1115 16-bit ADC breakout (product 1085), plugged into a female header",
        footprint="optics_bench:Adafruit_ADS1115_Socket",
        left=[("1", "VDD", "passive"), ("2", "GND", "passive"), ("3", "SCL", "passive"),
              ("4", "SDA", "passive"), ("5", "ADDR", "passive"), ("6", "ALRT", "passive")],
        right=[("7", "A0", "passive"), ("8", "A1", "passive"), ("9", "A2", "passive"), ("10", "A3", "passive")],
        width=12.7),
}

# ── Parts ───────────────────────────────────────────────────────────────────
# ref: dict(lib, value, fp, pins{num: net}, sch=(x, y) or {unit: (x, y)},
#           pcb=(x, y, rot) [, side "B"], fields{...})
# Schematic coordinates are in mm on an A3 sheet (snap to 2.54 on the 1.27 grid).

AXES = [  # name, STEP, DIR, EN, DIAG (Feather pad numbers), MS1, MS2 straps
    ("M1X", "10", "20", "21", "7", GND, GND),   # GPIO 4, 13, 12; DIAG to I34; addr 0
    ("M1Y", "22", "23", "24", "8", V33, GND),   # GPIO 27, 33, 15; DIAG to I39; addr 1
    ("M2X", "25", "26", "6", "9", GND, V33),    # GPIO 32, 14, 25; DIAG to I36; addr 2
    ("M2Y", "5", "11", "12", "16", V33, V33),   # GPIO 26, 5, 19; DIAG to I37; addr 3
]

# Control board layout (mm, y down): Feather upright on the left with USB at the top edge.
# The TMC2209 breakouts keep their screw terminals and plug in by the 10-pin logic header
# only. The top pair is turned so its terminals sit on the top edge and the bottom pair on
# the bottom edge, so motor and VM wires come in from outside the board. Power input,
# driver VM plugs and the test header sit in the middle; laser and photodiode plugs bottom left.
DRIVER_PCB = [(34.925, 22.225, 180), (64.135, 22.225, 180), (57.785, 77.775, 0), (86.995, 77.775, 0)]
# 2-pin VM plug for each driver (pin 1 = +12 V, 2 = GND) and its 100 uF capacitor
VM_JST_PCB = [(40.005, 28.575, 0), (69.215, 28.575, 0), (52.705, 70.485, 0), (81.915, 70.485, 0)]
DRIVER_CAP_PCB = [(47.625, 28.575), (77.47, 28.575), (45.085, 70.485), (73.66, 70.485)]
FEATHER_PCB = (8.89, 6.985, 270)                   # pad 1 (RST); USB end at the top edge
def control_board():
    parts = {}
    feather = {str(n): NC for n in range(1, 29)}
    feather.update({"2": V33, "4": GND, "13": "LASER_TTL", "14": "TMC_UART", "15": "TMC_TX",
                    "27": "I2C_SCL", "28": "I2C_SDA"})
    for i, (ax, st, di, en, dg, ms1, ms2) in enumerate(AXES):
        feather[st], feather[di], feather[en], feather[dg] = (f"{ax}_STEP", f"{ax}_DIR", f"{ax}_EN",
                                                              f"{ax}_DIAG")
    parts["A1"] = dict(lib="optics_bench:Adafruit_Feather_ESP32_V2", value="ESP32 Feather V2",
                       pins=feather, sch=(76.2, 101.6), pcb=FEATHER_PCB)

    for i, (ax, st, di, en, dg, ms1, ms2) in enumerate(AXES):
        parts[f"U{i + 1}"] = dict(
            lib="optics_bench:Adafruit_TMC2209_Breakout", value=f"TMC2209 {ax} (addr {i})",
            pins={"1": V33, "2": GND, "3": f"{ax}_DIR", "4": f"{ax}_STEP", "5": ms1, "6": ms2,
                  "7": f"{ax}_DIAG", "8": NC, "9": "TMC_UART", "10": f"{ax}_EN"},
            sch=(193.04 + (i % 2) * 91.44, 55.88 + (i // 2) * 71.12), pcb=DRIVER_PCB[i])
        parts[f"J{i + 1}"] = dict(
            lib="Connector_Generic:Conn_01x02", value=f"VM {ax}",
            fp="Connector_JST:JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical",
            pins={"1": V12, "2": GND},
            sch=(236.22 + (i % 2) * 91.44, 63.5 + (i // 2) * 71.12), pcb=VM_JST_PCB[i])
        parts[f"C{i + 1}"] = dict(
            lib="Device:C_Polarized", value="100uF 25V", fp="Capacitor_THT:CP_Radial_D6.3mm_P2.50mm",
            pins={"1": V12, "2": GND},
            sch=(223.52 + (i % 2) * 91.44, 30.48 + (i // 2) * 71.12), pcb=(*DRIVER_CAP_PCB[i], 0))

    parts["R1"] = dict(lib="Device:R", value="1k", fp="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
                       pins={"1": "TMC_TX", "2": "TMC_UART"}, sch=(119.38, 139.7), pcb=(8.89, 53.975, 0))

    # 12 V input: screw terminal or barrel jack, PTC fuse, series Schottky for reverse polarity,
    # TVS, bulk capacitor and a power LED.
    parts["J5"] = dict(lib="Connector:Screw_Terminal_01x02", value="12V IN",
                       fp="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal",
                       pins={"1": "VIN", "2": GND}, sch=(30.48, 195.58), pcb=(93.98, 50.8, 90))   # wire entry faces the right edge
    parts["J6"] = dict(lib="Connector:Barrel_Jack", value="12V IN 5.5x2.1",
                       fp="Connector_BarrelJack:BarrelJack_Horizontal",
                       pins={"1": "VIN", "2": GND}, sch=(30.48, 215.9), pcb=(85.725, 62.23, 180))
    parts["F1"] = dict(lib="Device:Polyfuse", value="MF-RHT200", fp="Fuse:Fuse_Bourns_MF-RHT200",
                       pins={"1": "VIN", "2": "VIN_F"}, sch=(50.8, 190.5), pcb=(79.375, 44.45, 0))
    parts["D1"] = dict(lib="Device:D_Schottky", value="1N5822", fp="Diode_THT:D_DO-201AD_P15.24mm_Horizontal",
                       pins={"1": V12, "2": "VIN_F"}, sch=(73.66, 185.42), pcb=(55.88, 53.34, 0))
    parts["D2"] = dict(lib="Device:D_TVS", value="P6KE18CA", fp="Diode_THT:D_DO-15_P10.16mm_Horizontal",
                       pins={"1": V12, "2": GND}, sch=(83.82, 198.12), pcb=(57.15, 62.23, 0))
    parts["C5"] = dict(lib="Device:C_Polarized", value="470uF 25V", fp="Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
                       pins={"1": V12, "2": GND}, sch=(109.22, 198.12), pcb=(45.72, 60.96, 0))
    parts["R2"] = dict(lib="Device:R", value="4.7k", fp="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
                       pins={"1": V12, "2": "LED_12V"}, sch=(127.0, 190.5), pcb=(55.88, 43.18, 0))
    parts["D3"] = dict(lib="Device:LED", value="12V ON (green)", fp="LED_THT:LED_D3.0mm",
                       pins={"1": GND, "2": "LED_12V"}, sch=(127.0, 213.36), pcb=(71.12, 43.18, 0))

    # Off-board connections
    parts["J7"] = dict(lib="Connector_Generic:Conn_01x03", value="Laser",
                       fp="Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical",
                       pins={"1": V33, "2": "LASER_TTL", "3": GND}, sch=(157.48, 190.5), pcb=(6.35, 81.28, 0))
    parts["J8"] = dict(lib="Connector_Generic:Conn_01x03", value="PD reference",
                       fp="Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical",
                       pins={"1": V33, "2": "PD_REF", "3": GND}, sch=(157.48, 205.74), pcb=(19.05, 81.28, 0))
    parts["J9"] = dict(lib="Connector_Generic:Conn_01x03", value="PD output",
                       fp="Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical",
                       pins={"1": V33, "2": "PD_OUT", "3": GND}, sch=(157.48, 220.98), pcb=(12.7, 92.71, 0))
    parts["J10"] = dict(lib="Connector_Generic:Conn_01x10", value="Test (Analog Discovery)",
                        fp="Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical",
                        pins={"1": GND, "2": V33, "3": "I2C_SCL", "4": "I2C_SDA", "5": "TMC_UART",
                              "6": "LASER_TTL", "7": "PD_REF", "8": "PD_OUT", "9": "AIN2", "10": "AIN3"},
                        sch=(203.2, 200.66), pcb=(35.56, 36.83, 90))
    parts["A2"] = dict(lib="optics_bench:Adafruit_ADS1115_Breakout", value="ADS1115 (0x48)",
                       pins={"1": V33, "2": GND, "3": "I2C_SCL", "4": "I2C_SDA", "5": GND, "6": NC,
                             "7": "PD_REF", "8": "PD_OUT", "9": "AIN2", "10": "AIN3"},
                       sch=(248.92, 200.66), pcb=(3.81, 71.755, 0))
    for n, (x, y) in enumerate([(3.5, 3.5), (96.5, 3.5), (3.5, 96.5), (96.5, 96.5)]):
        parts[f"H{n + 1}"] = dict(lib="Mechanical:MountingHole", value="M3",
                                  fp="MountingHole:MountingHole_3.2mm_M3", pins={},
                                  sch=(345.44 + n * 7.62, 256.54), pcb=(x, y, 0))
    holes = [p["pcb"][:2] for r, p in parts.items() if r.startswith("H")]
    # MS1/MS2 straps and ADS1115 ADDR tied to the part's own GND pin with a short track
    gnd_links = [(f"U{i + 1}.{pin}", f"U{i + 1}.2") for i, ax in enumerate(AXES)
                 for pin, strap in (("5", ax[5]), ("6", ax[6])) if strap == GND] + [("A2.5", "A2.2")]
    gnd_links += [(f"J{i + 1}.2", f"C{i + 1}.2") for i in range(4)]      # each VM plug's GND to its capacitor
    gnd_links += [("C1.2", "U1.2"), ("C2.2", "U2.2"), ("C5.2", "C3.2")]  # keep these pour pieces joined
    silk = [("OPTICS BENCH CONTROL  rev B", 78.0, 35.5, 1.0, 0, None, True),
            ("J5 12V IN", 93.98, 40.3, 1.0), ("+", 87.6, 50.8, 1.2), ("-", 87.6, 45.72, 1.2),
            ("J7 LASER", 8.85, 77.0, 0.8), ("J8 PD REF", 21.55, 77.0, 0.8), ("J9 PD OUT", 15.2, 88.4, 0.8),
            ("J10 TEST: GND 3V3 SCL SDA UART LSR REF OUT A2 A3", 47.0, 39.4, 0.6)]
    for i, (ax, *_rest) in enumerate(AXES):
        x, y, _r = VM_JST_PCB[i]
        if y < 50:
            silk.append((f"J{i + 1} VM {ax}  + -", x + 1.25, y + 4.6, 0.7))
        else:                                  # no room below: label to the right of the plug
            silk.append((f"J{i + 1} VM {ax}", x + 9.8, y - 0.6, 0.7))
            silk.append(("+  -", x + 9.8, y + 0.9, 0.7))
    # reference designators: None hides one that a silk label above already names
    for ref in ("J1", "J2", "J3", "J4", "J5", "J7", "J8", "J9", "J10", "H1", "H2", "H3", "H4"):
        parts[ref]["ref_at"] = None
    for i, (x, y, rot) in enumerate(DRIVER_PCB):
        cx = x + (11.43 if rot == 180 else -11.43)
        parts[f"U{i + 1}"]["ref_at"] = (cx, y + (-6.0 if rot == 180 else 6.0))
    for i, (x, y) in enumerate(DRIVER_CAP_PCB):
        parts[f"C{i + 1}"]["ref_at"] = (x + 1.25, y + 4.4) if y < 50 else (x - 3.3, y)
    parts["D3"]["ref_at"] = (72.39, 40.3)
    parts["J6"]["ref_at"] = (89.5, 54.4)
    return dict(name="control_board", title="Optics bench control board", rev="B",
                size=(100.0, 100.0), parts=parts, keepouts=holes, silk=silk,
                gnd_links=gnd_links, solid_gnd=["J1", "J2", "J3", "J4", "J10"], route_gnd=True,
                flags={V12: (60.96, 238.76), GND: (40.64, 238.76), V33: (50.8, 238.76)},
                notes=CONTROL_NOTES)


CONTROL_NOTES = [
    ((20.32, 20.32), "Carrier for the ESP32 Feather V2, four TMC2209 breakouts and the ADS1115.\n"
                     "Pins match firmware/optics_bench/config.h. Wiring: electronics/wiring.md."),
    ((20.32, 172.72), "12 V motor supply: PTC fuse, series Schottky (reverse polarity), TVS, bulk capacitor"),
    ((144.78, 172.72), "Off-board: laser, photodiode amp boards (1:1 JST-XH cables), test header"),
    ((175.26, 17.78), "Driver UART addresses from MS1/MS2: U1 0, U2 1, U3 2, U4 3.\n"
                      "The breakouts keep their screw terminals: motors wire straight into them, and\n"
                      "J1-J4 feed each breakout's VM +/- terminals over a short 2-wire lead."),
    ((50.8, 60.96), "TX reaches the shared single-wire UART bus through R1; RX joins it directly.\n"
                    "DIAG outputs go to input-only pins I34/I39/I36/I37 (firmware does not use them yet)."),
]


def pd_amp_board():
    parts = {
        "J1": dict(lib="Connector_Generic:Conn_01x03", value="To control board",
                   fp="Connector_JST:JST_XH_B3B-XH-A_1x03_P2.50mm_Vertical",
                   pins={"1": V33, "2": "VOUT", "3": GND}, sch=(40.64, 88.9), pcb=(26.035, 3.81, 0)),
        "D1": dict(lib="Sensor_Optical:BPW34", value="BPW34", fp="OptoDevice:Osram_DIL2_4.3x4.65mm_P5.08mm",
                   pins={"1": "TIA_IN", "2": GND}, sch=(101.6, 76.2), pcb=(14.605, 20.32, 0)),
        "U1": dict(lib="Amplifier_Operational:MCP6002-xP", value="MCP6002-I/P",
                   fp="Package_DIP:DIP-8_W7.62mm",
                   pins={"1": "TIA_OUT", "2": "TIA_IN", "3": GND, "5": GND, "6": "BUF_B", "7": "BUF_B",
                         "4": GND, "8": V33},
                   sch={1: (127.0, 71.12), 2: (127.0, 116.84), 3: (165.1, 116.84)}, pcb=(13.335, 12.7, 90)),
        "R1": dict(lib="Device:R", value="47k 1%",
                   fp="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
                   pins={"1": "TIA_IN", "2": "TIA_OUT"}, sch=(127.0, 50.8), pcb=(8.89, 15.24, 90)),
        "C1": dict(lib="Device:C", value="1nF C0G", fp="Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
                   pins={"1": "TIA_IN", "2": "TIA_OUT"}, sch=(139.7, 50.8), pcb=(4.445, 14.605, 90)),
        "C2": dict(lib="Device:C", value="100nF", fp="Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm",
                   pins={"1": V33, "2": GND}, sch=(180.34, 116.84), pcb=(5.715, 3.81, 0)),
        "R2": dict(lib="Device:R", value="100", fp="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P7.62mm_Horizontal",
                   pins={"1": "TIA_OUT", "2": "VOUT"}, sch=(157.48, 71.12), pcb=(24.13, 12.065, 0)),
        "H1": dict(lib="Mechanical:MountingHole", value="M3", fp="MountingHole:MountingHole_3.2mm_M3",
                   pins={}, sch=(200.66, 147.32), pcb=(4.645, 20.32, 0)),
        "H2": dict(lib="Mechanical:MountingHole", value="M3", fp="MountingHole:MountingHole_3.2mm_M3",
                   pins={}, sch=(208.28, 147.32), pcb=(29.645, 20.32, 0)),
    }
    silk = [("PD AMP rev A", 17.1, 1.6, 0.8), ("J1: 3V3 OUT GND", 28.5, 7.9, 0.6)]
    for ref in ("J1", "H1", "H2"):
        parts[ref]["ref_at"] = None
    parts["R1"]["ref_at"] = (8.89, 17.4)
    parts["C1"]["ref_at"] = (4.445, 7.4)
    return dict(name="pd_amp", title="Photodiode transimpedance amplifier", rev="A",
                size=(34.29, 25.4), parts=parts, keepouts=[(4.645, 20.32), (29.645, 20.32)], silk=silk,
                flags={GND: (50.8, 132.08), V33: (60.96, 132.08)},
                notes=PD_NOTES, paper="A4")


PD_NOTES = [
    ((20.32, 20.32), "BPW34 at zero bias into an MCP6002 transimpedance amp. Vout = I_photo x Rf.\n"
                     "47k || 1nF: full scale 70 uA (about 175 uW at 635 nm), 3.4 kHz bandwidth.\n"
                     "Build two: reference (control board J8 -> ADS1115 A0) and output (J9 -> A1).\n"
                     "If a channel saturates, fit a smaller Rf and change PD_*_TIA_OHMS in config.h."),
    ((20.32, 160.02), "Half B is unused: wired as a grounded follower. R2 isolates the cable capacitance."),
]

BOARDS = {"control_board": control_board, "pd_amp": pd_amp_board}


# ── Bill of materials ───────────────────────────────────────────────────────
# Manufacturer part numbers by reference (a suggestion; any equivalent fits the footprint).
MPN = {
    "control_board": {
        "A1": ("Adafruit 5400", "Adafruit ESP32 Feather V2 (on hand)"),
        "U1": ("Adafruit 6121", "Adafruit TMC2209 breakout (on hand)"),
        "A2": ("Adafruit 1085", "Adafruit ADS1115 breakout"),
        "J1": ("JST B2B-XH-A(LF)(SN)", "JST-XH 2-pin header, vertical (driver VM feed)"),
        "J5": ("Phoenix Contact 1729128", "Screw terminal 2-pin 5.08 mm (MKDS 1,5/2-5,08)"),
        "J6": ("CUI PJ-102AH", "DC barrel jack 5.5 x 2.1 mm"),
        "J7": ("JST B3B-XH-A(LF)(SN)", "JST-XH 3-pin header, vertical"),
        "J10": ("generic", "1x10 male pin header 2.54 mm"),
        "F1": ("Bourns MF-RHT200", "PTC resettable fuse, 2 A hold"),
        "D1": ("1N5822", "Schottky diode 3 A 40 V, DO-201AD"),
        "D2": ("Littelfuse P6KE18CA", "TVS 600 W, 15.3 V standoff, bidirectional, DO-15"),
        "D3": ("generic", "3 mm green LED"),
        "C1": ("Panasonic EEU-FR1E101", "100 uF 25 V electrolytic, 6.3 mm, 2.5 mm pitch"),
        "C5": ("Panasonic EEU-FR1E471", "470 uF 25 V electrolytic, 10 mm, 5 mm pitch"),
        "R1": ("generic", "1 kOhm 1/4 W axial"),
        "R2": ("generic", "4.7 kOhm 1/4 W axial"),
        "H1": ("", "M3 mounting hole"),
    },
    "pd_amp": {
        "J1": ("JST B3B-XH-A(LF)(SN)", "JST-XH 3-pin header, vertical"),
        "D1": ("Vishay BPW34", "Silicon PIN photodiode"),
        "U1": ("Microchip MCP6002-I/P", "Dual op-amp, DIP-8"),
        "R1": ("generic", "47 kOhm 1% 1/4 W axial (Rf)"),
        "R2": ("generic", "100 Ohm 1/4 W axial"),
        "C1": ("generic", "1 nF C0G/NP0 50 V, 5 mm pitch (Cf)"),
        "C2": ("generic", "100 nF X7R 50 V, 5 mm pitch"),
        "H1": ("", "M3 mounting hole"),
    },
}

# Parts that go with the board but have no symbol: sockets for the plug-in breakouts, cables.
EXTRA_BOM = {
    "control_board": [
        ("A1 socket", "Female header 1x16, 2.54 mm, 8.5 mm tall", "generic (e.g. Adafruit 2940 kit)", 1),
        ("A1 socket", "Female header 1x12, 2.54 mm, 8.5 mm tall", "generic (e.g. Adafruit 2940 kit)", 1),
        ("U1-U4 sockets", "Female header 1x10, 2.54 mm", "generic", 4),
        ("U1-U4 standoffs", "M2 x 11 mm standoff + 2 M2 screws, under each breakout's terminal-end holes",
         "generic", 8),
        ("J1-J4 VM leads", "JST-XH 2-pin lead, about 60 mm, bare ends into the breakout's VM + / - terminals",
         "JST", 4),
        ("A2 socket", "Female header 1x10, 2.54 mm", "generic", 1),
        ("J7-J9 cables", "JST-XH housings (XHP-3) and SXH-001T-P0.6 crimps, or pre-crimped leads",
         "JST", 1),
    ],
    "pd_amp": [
        ("U1", "DIP-8 socket (optional)", "generic", 1),
        ("J1 cable", "JST-XH 3-pin lead, wired 1:1 to control board J8 or J9", "JST", 1),
    ],
}

