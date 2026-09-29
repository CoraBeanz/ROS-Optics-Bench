"""Write lib/optics_bench.kicad_sym and lib/optics_bench.pretty (plug-in breakout sockets).

Usage: py -3 electronics/pcb/gen/make_lib.py
"""
import os

from design import SYMBOLS
from sexp import Sym, dump

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")
S = Sym


def font(size=1.27, hide=False, justify=None):
    e = [S("effects"), [S("font"), [S("size"), size, size]]]
    if justify:
        e.append([S("justify"), *[S(j) for j in justify.split()]])
    out = [e]
    if hide:
        out.insert(0, [S("hide"), S("yes")])
    return out


def prop(name, value, x, y, hide=False, justify=None):
    return [S("property"), name, value, [S("at"), x, y, 0], *font(hide=hide, justify=justify)]


def pin(num, name, etype, x, y, rot):
    return [S("pin"), S(etype), S("line"), [S("at"), x, y, rot], [S("length"), 2.54],
            [S("name"), name, *font()], [S("number"), num, *font()]]


def pin_rows(spec):
    rows = max(len(spec["left"]), len(spec["right"]))
    top = ((rows - 1) // 2 + 1) * 2.54
    return rows, top


def symbol(name, spec):
    rows, top = pin_rows(spec)
    hw = spec["width"] / 2
    bottom = top - (rows + 1) * 2.54
    pins = []
    for col, x, rot in ((spec["left"], -hw - 2.54, 0), (spec["right"], hw + 2.54, 180)):
        for i, p in enumerate(col):
            if p:
                pins.append(pin(p[0], p[1], p[2], x, round(top - (i + 1) * 2.54, 3), rot))
    body = [S("rectangle"), [S("start"), -hw, top], [S("end"), hw, bottom],
            [S("stroke"), [S("width"), 0.254], [S("type"), S("default")]], [S("fill"), [S("type"), S("background")]]]
    return [S("symbol"), name, [S("pin_names"), [S("offset"), 1.016]],
            [S("exclude_from_sim"), S("no")], [S("in_bom"), S("yes")], [S("on_board"), S("yes")],
            prop("Reference", spec["ref"], -hw, top + 1.27, justify="left bottom"),
            prop("Value", name.replace("_", " "), -hw, bottom - 1.27, justify="left top"),
            prop("Footprint", spec["footprint"], 0, bottom - 3.81, hide=True),
            prop("Datasheet", "", 0, 0, hide=True),
            prop("Description", spec["descr"], 0, 0, hide=True),
            [S("symbol"), f"{name}_0_1", body],
            [S("symbol"), f"{name}_1_1", *pins],
            [S("embedded_fonts"), S("no")]]


def write_symbols():
    lib = [S("kicad_symbol_lib"), [S("version"), 20251024], [S("generator"), "optics_bench_gen"],
           [S("generator_version"), "10.0"]]
    lib += [symbol(n, s) for n, s in SYMBOLS.items()]
    with open(os.path.join(LIB, "optics_bench.kicad_sym"), "w", encoding="utf8", newline="\n") as f:
        f.write(dump(lib) + "\n")


# ── Footprints ──────────────────────────────────────────────────────────────

def fp_text(kind, text, x, y, layer, size=1.0, hide=False):
    p = [S("property"), kind, text, [S("at"), x, y, 0], [S("layer"), layer]]
    if hide:
        p.append([S("hide"), S("yes")])
    p.append([S("effects"), [S("font"), [S("size"), size, size], [S("thickness"), round(size * 0.15, 3)]]])
    return p


def gr_text(text, x, y, layer, size=1.0, rot=0):
    return [S("fp_text"), S("user"), text, [S("at"), x, y, rot], [S("layer"), layer],
            [S("effects"), [S("font"), [S("size"), size, size], [S("thickness"), round(size * 0.15, 3)]]]]


def line(x1, y1, x2, y2, layer, w=0.12):
    return [S("fp_line"), [S("start"), x1, y1], [S("end"), x2, y2],
            [S("stroke"), [S("width"), w], [S("type"), S("solid")]], [S("layer"), layer]]


def rect(x1, y1, x2, y2, layer, w=0.12):
    return [S("fp_rect"), [S("start"), x1, y1], [S("end"), x2, y2],
            [S("stroke"), [S("width"), w], [S("type"), S("solid")]], [S("fill"), S("no")], [S("layer"), layer]]


def tht_pad(num, x, y, square=False):
    return [S("pad"), num, S("thru_hole"), S("rect") if square else S("circle"), [S("at"), x, y],
            [S("size"), 1.7, 1.7], [S("drill"), 1.0], [S("layers"), "*.Cu", "*.Mask"],
            [S("remove_unused_layers"), S("no")]]


def socket_strip(x0, y0, n, dx, layer="F.SilkS"):
    """Silk box around a straight row of n pins starting at (x0, y0) going dx per pin."""
    xs = [x0 + i * dx for i in range(n)]
    return rect(min(xs) - 1.33, y0 - 1.33, max(xs) + 1.33, y0 + 1.33, layer)


def footprint(name, descr, pads, body, labels, extra=()):
    x1, y1, x2, y2 = body
    fp = [S("footprint"), name, [S("version"), 20260206], [S("generator"), "optics_bench_gen"],
          [S("layer"), "F.Cu"], [S("descr"), descr], [S("tags"), "socket breakout adafruit"],
          fp_text("Reference", "REF**", x1 + 2.0, y1 + 1.5, "F.SilkS"),
          fp_text("Value", name, (x1 + x2) / 2, y2 - 1.2, "F.Fab"),
          [S("attr"), S("through_hole")],
          rect(x1, y1, x2, y2, "F.Fab", 0.1),
          rect(x1 - 0.25, y1 - 0.25, x2 + 0.25, y2 + 0.25, "F.CrtYd", 0.05),
          rect(x1 - 0.11, y1 - 0.11, x2 + 0.11, y2 + 0.11, "F.SilkS", 0.12)]
    fp += list(extra)
    for (txt, x, y, rot, size) in labels:
        fp.append(gr_text(txt, x, y, "F.SilkS", size, rot))
    fp += pads
    fp.append([S("embedded_fonts"), S("no")])
    return fp


def feather_socket():
    row16 = ["RST", "3V", "NC", "GND", "A0", "A1", "A2", "A3", "A4", "A5", "SCK", "MO", "MI", "RX", "TX", "37"]
    row12 = ["BAT", "EN", "USB", "13", "12", "27", "33", "15", "32", "14", "SCL", "SDA"]
    pads = [tht_pad(str(i + 1), i * 2.54, 0, i == 0) for i in range(16)]
    pads += [tht_pad(str(17 + i), 10.16 + i * 2.54, -20.32) for i in range(12)]
    labels = [(t, i * 2.54, -2.3, 90, 0.7) for i, t in enumerate(row16)]
    labels += [(t, 10.16 + i * 2.54, -18.0, 90, 0.7) for i, t in enumerate(row12)]
    labels += [("ESP32 FEATHER V2", 19.0, -10.2, 0, 1.2), ("USB", -3.6, -10.2, 90, 1.0)]
    extra = [socket_strip(0, 0, 16, 2.54), socket_strip(10.16, -20.32, 12, 2.54)]
    return footprint("Adafruit_Feather_ESP32_V2_Socket",
                     "Adafruit ESP32 Feather V2 (5400) on 16- and 12-pin female headers. Pad 1 = RST, "
                     "USB end at the left. Outline is the Feather board.",
                     pads, (-6.35, -21.59, 44.45, 1.27), labels, extra)


def tmc_socket():
    # Seen from the top with the logic header along the top edge (Adafruit 6121 rotated 180 deg).
    logic = ["VDD", "GND", "DIR", "STEP", "MS1", "MS2", "DIAG", "IDX", "UART", "EN"]
    term = ["1B", "1A", "2A", "2B", "GND", "VM"]
    pads = [tht_pad(str(i + 1), -i * 2.54, 0, i == 0) for i in range(10)]
    pads += [tht_pad(str(11 + i), -17.78 + i * 2.54, 17.78, i == 0) for i in range(6)]
    labels = [(t, -i * 2.54, 2.4, 90, 0.7) for i, t in enumerate(logic)]
    labels += [(t, -17.78 + i * 2.54, 15.4, 90, 0.7) for i, t in enumerate(term)]
    labels += [("TMC2209", -11.43, 8.0, 0, 1.2)]
    extra = [socket_strip(0, 0, 10, -2.54), socket_strip(-17.78, 17.78, 6, 2.54)]
    return footprint("Adafruit_TMC2209_Socket",
                     "Adafruit TMC2209 breakout (6121) on a 10-pin and a 6-pin female header. The 6-pin row "
                     "is the terminal-block holes (2.54 mm) fitted with a male header. Outline is the breakout.",
                     pads, (-24.765, -2.54, 1.905, 21.59), labels, extra)


def ads_socket():
    names = ["VDD", "GND", "SCL", "SDA", "ADDR", "ALRT", "A0", "A1", "A2", "A3"]
    pads = [tht_pad(str(i + 1), i * 2.54, 0, i == 0) for i in range(10)]
    labels = [(t, i * 2.54, -2.6, 90, 0.7) for i, t in enumerate(names)]
    labels += [("ADS1115", 11.43, -9.0, 0, 1.2)]
    extra = [socket_strip(0, 0, 10, 2.54)]
    return footprint("Adafruit_ADS1115_Socket",
                     "Adafruit ADS1115 breakout (1085) on a 10-pin female header, board above the header.",
                     pads, (-2.49, -15.24, 25.35, 2.54), labels, extra)


def write_footprints():
    d = os.path.join(LIB, "optics_bench.pretty")
    os.makedirs(d, exist_ok=True)
    for fp in (feather_socket(), tmc_socket(), ads_socket()):
        with open(os.path.join(d, fp[1] + ".kicad_mod"), "w", encoding="utf8", newline="\n") as f:
            f.write(dump(fp) + "\n")


if __name__ == "__main__":
    os.makedirs(LIB, exist_ok=True)
    write_symbols()
    write_footprints()
    print("wrote", os.path.normpath(LIB))
