"""Write <board>/<board>.kicad_sch plus the project and library tables.

Every pin gets a net label, a power symbol or a no-connect flag at its end, so the
schematic reads as a labelled netlist. Positions come from design.py.

Usage: py -3 electronics/pcb/gen/make_sch.py [board ...]
"""
import copy
import json
import os
import sys
import uuid

import design
from sexp import Sym, dump, find, find_all, parse

S = Sym
HERE = os.path.dirname(os.path.abspath(__file__))
PCB_DIR = os.path.normpath(os.path.join(HERE, ".."))
KICAD = os.environ.get("KICAD_DIR", r"C:\Users\Vince\AppData\Local\Programs\KiCad\10.0")
SYMDIR = os.path.join(KICAD, "share", "kicad", "symbols")
_lib_cache = {}


def uid(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "optics-bench/" + "/".join(map(str, parts))))


def load_lib(name):
    if name not in _lib_cache:
        path = (os.path.join(PCB_DIR, "lib", "optics_bench.kicad_sym") if name == "optics_bench"
                else os.path.join(SYMDIR, name + ".kicad_sym"))
        with open(path, encoding="utf8") as f:
            tree = parse(f.read())
        _lib_cache[name] = {s[1]: s for s in find_all(tree, "symbol")}
    return _lib_cache[name]


def lib_symbol(lib_id):
    """Return a flattened copy of the library symbol, renamed to lib_id."""
    lib, name = lib_id.split(":")
    syms = load_lib(lib)
    sym = copy.deepcopy(syms[name])
    ext = find(sym, "extends")
    if ext:
        parent = copy.deepcopy(syms[ext[1]])
        own_props = {p[1]: p for p in find_all(sym, "property")}
        out = []
        for x in parent:
            if isinstance(x, list) and x and x[0] == "property" and x[1] in own_props:
                out.append(own_props.pop(x[1]))
            elif isinstance(x, list) and x and x[0] == "symbol":
                x[1] = x[1].replace(ext[1], name, 1)
                out.append(x)
            else:
                out.append(x)
        # properties only on the child go after the parent's
        idx = max(i for i, x in enumerate(out) if isinstance(x, list) and x and x[0] == "property")
        out[idx + 1:idx + 1] = list(own_props.values())
        sym = out
    sym[1] = lib_id
    return sym


def unit_pins(sym, unit):
    """Pins of one unit (plus the shared unit 0): {number: (x, y, rot, type)} in library coords."""
    base = sym[1].split(":")[1]
    pins = {}
    for sub in find_all(sym, "symbol"):
        u = int(sub[1][len(base) + 1:].split("_")[0])
        if u not in (0, unit):
            continue
        for p in find_all(sub, "pin"):
            at = find(p, "at")
            pins[find(p, "number")[1]] = (float(at[1]), float(at[2]), int(float(at[3])), str(p[1]))
    return pins


def num_units(sym):
    base = sym[1].split(":")[1]
    return max(int(s[1][len(base) + 1:].split("_")[0]) for s in find_all(sym, "symbol")) or 1


def effects(size=1.27, justify=None, hide=False):
    e = [S("effects"), [S("font"), [S("size"), size, size]]]
    if justify:
        e.append([S("justify"), *[S(j) for j in justify.split()]])
    out = [e]
    if hide:
        out.insert(0, [S("hide"), S("yes")])
    return out


class Sheet:
    def __init__(self, board):
        self.b = board
        self.name = board["name"]
        self.root = uid(self.name, "root")
        self.items, self.libsyms = [], {}
        self.pwr_n = 0

    def libsym(self, lib_id):
        if lib_id not in self.libsyms:
            self.libsyms[lib_id] = lib_symbol(lib_id)
        return self.libsyms[lib_id]

    def place(self, ref, lib_id, x, y, unit=1, value=None, footprint=None, key=None, hidden_ref=False):
        sym = self.libsym(lib_id)
        u = uid(self.name, key or ref, unit)
        flag = {k: (find(sym, k) or [k, S("yes")])[1] for k in ("in_bom", "on_board")}
        node = [S("symbol"), [S("lib_id"), lib_id], [S("at"), x, y, 0], [S("unit"), unit],
                [S("exclude_from_sim"), S("no")], [S("in_bom"), flag["in_bom"]],
                [S("on_board"), flag["on_board"]], [S("dnp"), S("no")],
                [S("uuid"), u]]
        for p in find_all(sym, "property"):
            pname, pval = p[1], p[2]
            if pname.startswith("ki_"):          # library-only keys, as eeschema does
                continue
            if pname == "Reference":
                pval = ref
            elif pname == "Value" and value is not None:
                pval = value
            elif pname == "Footprint" and footprint:
                pval = footprint
            at = find(p, "at")
            hide = find(p, "hide") is not None or (pname == "Reference" and hidden_ref)
            just = None
            eff = find(p, "effects")
            if eff and find(eff, "justify"):
                just = " ".join(str(j) for j in find(eff, "justify")[1:])
            node.append([S("property"), pname, pval, [S("at"), x + float(at[1]), y - float(at[2]), float(at[3]) if len(at) > 3 else 0],
                         *effects(justify=just, hide=hide)])
        for num in unit_pins(sym, unit):
            node.append([S("pin"), num, [S("uuid"), uid(self.name, key or ref, unit, "pin", num)]])
        node.append([S("instances"), [S("project"), self.name,
                                      [S("path"), "/" + self.root, [S("reference"), ref], [S("unit"), unit]]]])
        self.items.append(node)
        return sym

    def power(self, net, x, y, rot=0, out=(0, 0)):
        self.pwr_n += 1
        ref = f"#PWR{self.pwr_n:03d}"
        self.place(ref, design.POWER_NETS[net], x, y, key=f"pwr{self.pwr_n}", hidden_ref=True)
        if not rot:
            return
        node = self.items[-1]
        node[2] = [S("at"), x, y, rot]
        for p in find_all(node, "property"):
            at = find(p, "at")
            if out[0]:
                # sideways symbol: horizontal net name just past its tip, clear of the next pin row
                at[1], at[2], at[3] = round(x + out[0] * 3.3, 3), y, rot
                eff = find(p, "effects")
                eff[:] = [e for e in eff if not (isinstance(e, list) and e[0] == "justify")]
                # KiCad applies the symbol rotation to the justification, so this reads reversed
                eff.append([S("justify"), S("left" if out[0] < 0 else "right")])
            else:                                     # upside down: mirror the field positions
                at[1], at[2] = round(2 * x - float(at[1]), 3), round(2 * y - float(at[2]), 3)

    def wire(self, x1, y1, x2, y2):
        self.items.append([S("wire"), [S("pts"), [S("xy"), x1, y1], [S("xy"), x2, y2]],
                           [S("stroke"), [S("width"), 0], [S("type"), S("default")]],
                           [S("uuid"), uid(self.name, "wire", x1, y1, x2, y2)]])

    def label(self, net, x, y, angle):
        just = {0: "left bottom", 90: "left bottom", 180: "right bottom", 270: "right bottom"}[angle]
        self.items.append([S("label"), net, [S("at"), x, y, angle], *effects(justify=just),
                           [S("uuid"), uid(self.name, "label", net, x, y)]])

    def no_connect(self, x, y):
        self.items.append([S("no_connect"), [S("at"), x, y], [S("uuid"), uid(self.name, "nc", x, y)]])

    def note(self, text, x, y, size=1.27):
        self.items.append([S("text"), text, [S("exclude_from_sim"), S("no")], [S("at"), x, y, 0],
                           *effects(size, "left top"), [S("uuid"), uid(self.name, "text", x, y)]])

    def connect_pins(self, ref, part, sym, unit, sx, sy):
        for num, (px, py, rot, _t) in unit_pins(sym, unit).items():
            if num not in part["pins"]:
                raise KeyError(f"{ref} pin {num} has no entry in design.py")
            net = part["pins"][num]
            x, y = round(sx + px, 3), round(sy - py, 3)
            out = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}[rot]
            if net is None:
                self.no_connect(x, y)
                continue
            ex, ey = round(x + out[0] * 2.54, 3), round(y + out[1] * 2.54, 3)
            self.wire(x, y, ex, ey)
            if net in design.POWER_NETS:
                # point the symbol away from the part: GND bars and supply arrows face outward
                gnd_rot = {(-1, 0): 270, (1, 0): 90, (0, 1): 0, (0, -1): 180}[out]
                sup_rot = {(-1, 0): 90, (1, 0): 270, (0, 1): 180, (0, -1): 0}[out]
                self.power(net, ex, ey, gnd_rot if net == design.GND else sup_rot, out)
            else:
                ang = {(-1, 0): 180, (1, 0): 0, (0, 1): 270, (0, -1): 90}[out]
                self.label(net, ex, ey, ang)

    def build(self):
        for ref, part in sorted(self.b["parts"].items(), key=lambda kv: natural(kv[0])):
            sym = self.libsym(part["lib"])
            placements = part["sch"] if isinstance(part["sch"], dict) else {1: part["sch"]}
            if isinstance(part["sch"], dict) and len(placements) != num_units(sym):
                raise ValueError(f"{ref}: place all {num_units(sym)} units")
            for unit, (sx, sy) in placements.items():
                self.place(ref, part["lib"], sx, sy, unit, part["value"], part.get("fp"))
                self.connect_pins(ref, part, sym, unit, sx, sy)
        n = 0
        for net, (x, y) in self.b["flags"].items():
            n += 1
            self.place(f"#FLG{n:02d}", "power:PWR_FLAG", x, y, key=f"flag{n}", hidden_ref=True)
            self.wire(x, y, x, y + 5.08)
            self.power(net, x, y + 5.08)
        for (x, y), text in self.b["notes"]:
            self.note(text, x, y)

    def write(self, path):
        paper = self.b.get("paper", "A3")
        doc = [S("kicad_sch"), [S("version"), 20250610], [S("generator"), "eeschema"],
               [S("generator_version"), "10.0"], [S("uuid"), self.root], [S("paper"), paper],
               [S("title_block"), [S("title"), self.b["title"]], [S("date"), "2026-09-29"],
                [S("rev"), self.b["rev"]], [S("company"), "ROS-Optics-Bench"],
                [S("comment"), 1, "Generated by electronics/pcb/gen/make_sch.py from design.py"]],
               [S("lib_symbols"), *self.libsyms.values()]]
        doc += self.items
        doc += [[S("sheet_instances"), [S("path"), "/", [S("page"), "1"]]], [S("embedded_fonts"), S("no")]]
        with open(path, "w", encoding="utf8", newline="\n") as f:
            f.write(dump(doc) + "\n")


def natural(ref):
    i = len(ref.rstrip("0123456789"))
    return ref[:i], int(ref[i:] or 0)


NETCLASSES = {
    "control_board": [
        dict(name="Power", track_width=1.0, clearance=0.3, patterns=["+12V", "/VIN", "/VIN_F"]),
        dict(name="Motor", track_width=0.6, clearance=0.25, patterns=["/M*_1A", "/M*_1B", "/M*_2A", "/M*_2B"]),
        dict(name="Supply3V3", track_width=0.5, clearance=0.2, patterns=["+3V3"]),
    ],
    "pd_amp": [dict(name="Supply3V3", track_width=0.5, clearance=0.2, patterns=["+3V3"])],
}


def netclass(name, track_width, clearance):
    return {"bus_width": 12, "clearance": clearance, "diff_pair_gap": 0.25, "diff_pair_via_gap": 0.25,
            "diff_pair_width": 0.2, "line_style": 0, "microvia_diameter": 0.3, "microvia_drill": 0.1,
            "name": name, "pcb_color": "rgba(0, 0, 0, 0.000)", "priority": 2147483647 if name == "Default" else 0,
            "schematic_color": "rgba(0, 0, 0, 0.000)", "track_width": track_width, "via_diameter": 0.8,
            "via_drill": 0.4, "wire_width": 6}


def write_project(board, bdir):
    name = board["name"]
    classes = [netclass("Default", 0.3, 0.2)]
    patterns = []
    for i, c in enumerate(NETCLASSES.get(name, [])):
        nc = netclass(c["name"], c["track_width"], c["clearance"])
        nc["priority"] = i
        classes.append(nc)
        patterns += [{"netclass": c["name"], "pattern": p} for p in c["patterns"]]
    pro = {
        "board": {"design_settings": {
            "defaults": {"board_outline_line_width": 0.1, "copper_line_width": 0.2, "silk_line_width": 0.12,
                         "silk_text_size_h": 1.0, "silk_text_size_v": 1.0, "silk_text_thickness": 0.15},
            "rules": {"min_clearance": 0.2, "min_copper_edge_clearance": 0.5, "min_hole_clearance": 0.25,
                      "min_hole_to_hole": 0.25, "min_through_hole_diameter": 0.3, "min_track_width": 0.2,
                      "min_via_annular_width": 0.15, "min_via_diameter": 0.6, "min_text_height": 0.6,
                      "min_text_thickness": 0.08, "min_silk_clearance": 0.0, "max_error": 0.005},
            "track_widths": [0.0, 0.3, 0.5, 0.6, 1.0, 1.5],
            "via_dimensions": [{"diameter": 0.0, "drill": 0.0}, {"diameter": 0.8, "drill": 0.4}],
            "rule_severities": {"silk_overlap": "ignore", "silk_over_copper": "warning",
                                "silk_edge_clearance": "warning", "lib_footprint_issues": "ignore",
                                "lib_footprint_mismatch": "ignore", "text_height": "warning",
                                "text_thickness": "warning"},
        }},
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "net_settings": {"classes": classes, "meta": {"version": 5}, "netclass_patterns": patterns},
        "erc": {"rule_severities": {"lib_symbol_issues": "ignore", "lib_symbol_mismatch": "ignore",
                                    "footprint_link_issues": "ignore"}},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[uid(name, "root"), "Root"]],
    }
    with open(os.path.join(bdir, f"{name}.kicad_pro"), "w", encoding="utf8", newline="\n") as f:
        json.dump(pro, f, indent=2)
        f.write("\n")
    with open(os.path.join(bdir, "sym-lib-table"), "w", encoding="utf8", newline="\n") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "optics_bench") (type "KiCad") '
                '(uri "${KIPRJMOD}/../lib/optics_bench.kicad_sym") (options "") (descr "Optics bench parts"))\n)\n')
    with open(os.path.join(bdir, "fp-lib-table"), "w", encoding="utf8", newline="\n") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "optics_bench") (type "KiCad") '
                '(uri "${KIPRJMOD}/../lib/optics_bench.pretty") (options "") (descr "Optics bench sockets"))\n)\n')


def main(names):
    for name in names or design.BOARDS:
        board = design.BOARDS[name]()
        bdir = os.path.join(PCB_DIR, name)
        os.makedirs(bdir, exist_ok=True)
        sh = Sheet(board)
        sh.build()
        sh.write(os.path.join(bdir, f"{name}.kicad_sch"))
        pro = os.path.join(bdir, f"{name}.kicad_pro")
        if not os.path.exists(pro) or "--project" in sys.argv:
            write_project(board, bdir)
        print("wrote", os.path.join(bdir, f"{name}.kicad_sch"))


if __name__ == "__main__":
    main([a for a in sys.argv[1:] if not a.startswith("--")])
