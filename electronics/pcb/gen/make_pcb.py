"""Build <board>/<board>.kicad_pcb from the schematic netlist and design.py placement, route it
and pour the ground planes.

Run with KiCad's Python (it has pcbnew and numpy), after make_sch.py and a netlist export:
  kicad-cli sch export netlist --format kicadsexpr -o <board>/<board>.net <board>/<board>.kicad_sch
  "<KiCad>/bin/python.exe" electronics/pcb/gen/make_pcb.py [board ...]
build.py runs the whole chain.
"""
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pcbnew  # noqa: E402

import design  # noqa: E402
from make_sch import write_project, KICAD  # noqa: E402
from route import Router, Shape  # noqa: E402
from sexp import find, find_all, parse  # noqa: E402

PCB_DIR = os.path.normpath(os.path.join(HERE, ".."))
FP_DIR = os.path.join(KICAD, "share", "kicad", "footprints")
MM = pcbnew.FromMM

# Routing widths and clearances by net (mm). GND is not routed: both layers are ground pours.
POWER = {"+12V", "/VIN", "/VIN_F"}


def net_rule(net):
    if net == "GND":
        return 0.4, 0.2
    if net in POWER:
        return 1.0, 0.3
    if net.startswith("/M") and net[-3:] in ("_1A", "_1B", "_2A", "_2B"):
        return 0.6, 0.25
    if net == "+3V3":
        return 0.5, 0.2
    return 0.3, 0.2


def load_netlist(path):
    with open(path, encoding="utf8") as f:
        t = parse(f.read())
    comps = {}
    for c in find_all(find(t, "components"), "comp"):
        ref = find(c, "ref")[1]
        fields = {}
        for fl in find_all(find(c, "fields") or [], "field"):
            key = find(fl, "name")[1]
            if key != "Footprint" and not key.startswith("ki_"):
                fields[key] = fl[2] if len(fl) > 2 else ""
        comps[ref] = dict(value=find(c, "value")[1], footprint=find(c, "footprint")[1],
                          tstamp=find(c, "tstamps")[1], fields=fields)
    pinnet = {}
    for n in find_all(find(t, "nets"), "net"):
        name = find(n, "name")[1]
        for nd in find_all(n, "node"):
            pinnet[(find(nd, "ref")[1], find(nd, "pin")[1])] = name
    return comps, pinnet


def load_fp(fpid):
    lib, name = fpid.split(":")
    path = (os.path.join(PCB_DIR, "lib", "optics_bench.pretty") if lib == "optics_bench"
            else os.path.join(FP_DIR, lib + ".pretty"))
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise FileNotFoundError(fpid)
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def pt(x, y):
    return pcbnew.VECTOR2I(MM(float(x)), MM(float(y)))


def pad_shape(pad, net):
    pos = pad.GetPosition()
    cx, cy = pos.x / 1e6, pos.y / 1e6
    size = pad.GetSize(pcbnew.F_Cu) if hasattr(pad, "GetSize") else pad.GetSize()
    sx, sy = size.x / 1e6, size.y / 1e6
    shape = pad.GetShape(pcbnew.F_Cu)
    ang = pad.GetOrientation().AsRadians()
    tht = pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
    layers = (0, 1) if tht else ((0,) if pad.IsOnLayer(pcbnew.F_Cu) else (1,))
    _, clr = net_rule(net) if net else (0, 0.2)
    if shape == pcbnew.PAD_SHAPE_CIRCLE or (shape == pcbnew.PAD_SHAPE_OVAL and abs(sx - sy) < 1e-3):
        return Shape("circle", net, layers, clr, cx=cx, cy=cy, r=max(sx, sy) / 2, drill=tht)
    # KiCad angles are clockwise-positive on screen (y down) -> use -ang in the rect's frame
    return Shape("rect", net, layers, clr, cx=cx, cy=cy, hx=sx / 2, hy=sy / 2, angle=-ang, drill=tht)


def edge_rect(board, w, h, r=1.5):
    """Board outline with rounded corners."""
    def seg(a, b):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pt(*a))
        s.SetEnd(pt(*b))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)

    def arc(c, start, end):
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_ARC)
        s.SetCenter(pt(*c))
        s.SetStart(pt(*start))
        s.SetEnd(pt(*end))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)

    seg((r, 0), (w - r, 0))
    seg((w, r), (w, h - r))
    seg((w - r, h), (r, h))
    seg((0, h - r), (0, r))
    arc((w - r, r), (w - r, 0), (w, r))
    arc((w - r, h - r), (w, h - r), (w - r, h))
    arc((r, h - r), (r, h), (0, h - r))
    arc((r, r), (0, r), (r, 0))


def silk_text(board, text, x, y, size=1.0, rot=0, layer=None, bold=False):
    layer = pcbnew.F_SilkS if layer is None else layer
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(pt(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(size * (0.2 if bold else 0.15)))
    t.SetTextAngleDegrees(rot)
    if layer == pcbnew.B_SilkS:
        t.SetMirrored(True)
    board.Add(t)


def gnd_zone(board, net, layer, w, h, inset=0.3):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    o = z.Outline()
    o.NewOutline()
    for x, y in ((inset, inset), (w - inset, inset), (w - inset, h - inset), (inset, h - inset)):
        o.Append(MM(x), MM(y))
    z.SetLocalClearance(MM(0.3))
    z.SetMinThickness(MM(0.25))
    z.SetThermalReliefGap(MM(0.4))
    z.SetThermalReliefSpokeWidth(MM(0.5))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    z.SetZoneName(f"GND_{'F' if layer == pcbnew.F_Cu else 'B'}")
    board.Add(z)
    return z


def route_board(b, board, nets, pad_shapes, w, h, pad_by_key):
    r = Router(w, h, **b.get("router", {}))
    for s in pad_shapes:
        r.add(s)
    for (x, y) in b.get("keepouts", []):          # screw heads around mounting holes
        r.keepouts.append((Shape("circle", None, (0, 1), 0, cx=x, cy=y, r=3.0), False))
    for s in pad_shapes:                           # standoffs on the smaller unplated holes
        if s.net is None and s.kind == "circle" and s.g["r"] < 1.5:
            r.keepouts.append((Shape("circle", None, (0, 1), 0, cx=s.g["cx"], cy=s.g["cy"],
                                     r=s.g["r"] + 1.0), False))
    by_net = {}
    for s in pad_shapes:
        if s.net and s.net != "GND" and not s.net.startswith("unconnected"):
            by_net.setdefault(s.net, []).append(s)

    def span(n):
        xs = [s.g["cx"] for s in by_net[n]]
        ys = [s.g["cy"] for s in by_net[n]]
        return (max(xs) - min(xs)) + (max(ys) - min(ys))

    order = b.get("route_first", [])
    rest = [n for n in by_net if n not in order and len(by_net[n]) > 1]
    rank = {"power": 0, "motor": 1, "3v3": 2, "sig": 3}

    def kind(n):
        wdt, _ = net_rule(n)
        return "power" if wdt >= 1 else "motor" if wdt >= 0.6 else "3v3" if n == "+3V3" else "sig"

    rest.sort(key=lambda n: (rank[kind(n)], -span(n)))
    failed = []
    # short ground ties first (strap pins boxed in by signals would otherwise be cut off the pour)
    for a_key, b_key in b.get("gnd_links", []):
        sa, sb = pad_by_key[a_key], pad_by_key[b_key]
        width, clr = 0.5, 0.2
        blk, vblk = r.blocked("GND", width / 2, clr)
        tree = r.cells_in(sa, sa.layers)
        targets = [c for c in r.cells_in(sb, sb.layers) if not blk[c[0], 2 * c[1], 2 * c[2]]]
        path = r.astar(tree, targets, blk, vblk) if targets else None
        if path is None:
            failed.append(("GND", "tie", a_key, b_key))
        else:
            r.commit(path, "GND", width / 2, clr)
    nets_to_route = [n for n in order if n in by_net] + rest
    if b.get("route_gnd"):
        # a thin ground tree under the pours, so no pour piece boxed in by other nets is left floating
        by_net["GND"] = [s for s in pad_shapes if s.net == "GND"]
        nets_to_route.append("GND")
    for net in nets_to_route:
        width, clr = net_rule(net)
        hw = width / 2
        pads = list(by_net[net])
        root = pads.pop(0)
        tree = r.cells_in(root, root.layers)
        blk, vblk = r.blocked(net, hw, clr)
        while pads:
            tx = [c[2] for c in tree]
            ty = [c[1] for c in tree]

            def near(s):
                i, j = s.g["cx"] / r.pitch, s.g["cy"] / r.pitch
                return min((a - i) ** 2 + (bb - j) ** 2 for a, bb in zip(tx, ty))

            pads.sort(key=near)
            tgt = pads.pop(0)
            targets = [c for c in r.cells_in(tgt, tgt.layers) if not blk[c[0], 2 * c[1], 2 * c[2]]]
            path = r.astar(tree, targets, blk, vblk) if targets else None
            if path is None:
                if net != "GND":                   # the pours usually reach a pad the tree could not
                    failed.append((net, "no path", tgt.g["cx"], tgt.g["cy"]))
                continue
            r.commit(path, net, hw, clr)
            tree |= set(path) | r.cells_in(tgt, tgt.layers)
    return r, failed


def stitch(r, gnd_name, w, h, step=5.08, avoid=()):
    """GND vias on a regular grid wherever they fit, to tie the two pours together."""
    blk, vblk = r.blocked(gnd_name, 0.4, 0.3)
    out = []
    y = step / 2
    while y < h:
        x = step / 2
        while x < w:
            i, j = int(round(x / r.pitch)), int(round(y / r.pitch))
            if 0 < i < r.nx - 1 and 0 < j < r.ny - 1 and not vblk[2 * j, 2 * i]:
                px, py = i * r.pitch, j * r.pitch
                if all(math.hypot(px - ax, py - ay) > 4.5 for ax, ay in avoid):
                    out.append((px, py))
            x += step
        y += step
    return out


def build(name):
    t0 = time.time()
    b = design.BOARDS[name]()
    w, h = b["size"]
    bdir = os.path.join(PCB_DIR, name)
    comps, pinnet = load_netlist(os.path.join(bdir, f"{name}.net"))
    pcb_path = os.path.join(bdir, f"{name}.kicad_pcb")
    write_project(b, bdir)                         # rules and net classes, read by NewBoard
    board = pcbnew.NewBoard(pcb_path)
    tb = board.GetTitleBlock()
    tb.SetTitle(b["title"])
    tb.SetRevision(b["rev"])
    tb.SetDate("2026-09-29")
    tb.SetCompany("ROS-Optics-Bench")
    tb.SetComment(0, "Generated by electronics/pcb/gen/make_pcb.py from design.py")
    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)

    netinfo = {}

    def net(nm):
        if nm not in netinfo:
            ni = pcbnew.NETINFO_ITEM(board, nm)
            board.Add(ni)
            netinfo[nm] = ni
        return netinfo[nm]

    pad_shapes, pad_by_key = [], {}
    for ref, part in b["parts"].items():
        c = comps[ref]
        fp = load_fp(c["footprint"])
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH("/" + c["tstamp"]))
        for key, val in c["fields"].items():
            fp.SetField(key, val)
        x, y, rot = part["pcb"]
        fp.SetPosition(pt(x, y))
        fp.SetOrientationDegrees(rot)
        if "ref_at" in part:
            if part["ref_at"] is None:
                fp.Reference().SetVisible(False)
            else:
                fp.Reference().SetPosition(pt(*part["ref_at"]))
                fp.Reference().SetTextAngleDegrees(0)
        board.Add(fp)
        for pad in fp.Pads():
            nm = pinnet.get((ref, pad.GetNumber()))
            if nm:
                pad.SetNet(net(nm))
            if nm == "GND" and (c["footprint"].startswith("optics_bench:") or ref in b.get("solid_gnd", ())):
                # header pins between routed signals get too few thermal spokes; tie them solid
                pad.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_FULL)
            if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH or (not nm and not pad.GetNumber()):
                pad_shapes.append(pad_shape(pad, None))
            else:
                pad_shapes.append(pad_shape(pad, nm or f"nc-{ref}-{pad.GetNumber()}"))
                pad_by_key[f"{ref}.{pad.GetNumber()}"] = pad_shapes[-1]

    edge_rect(board, w, h)
    r, failed = route_board(b, board, netinfo, pad_shapes, w, h, pad_by_key)
    lay = {0: pcbnew.F_Cu, 1: pcbnew.B_Cu}
    for nm, l, width, (a, bpt) in r.tracks:
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(pt(*a))
        t.SetEnd(pt(*bpt))
        t.SetWidth(MM(width))
        t.SetLayer(lay[l])
        t.SetNet(net(nm))
        board.Add(t)
    vias = [(nm, x, y) for nm, x, y in r.vias]
    gnd = net("GND")
    hole_xy = b.get("keepouts", [])
    for x, y in stitch(r, "GND", w, h, b.get("stitch_step", 5.08), hole_xy):
        vias.append(("GND", x, y))
    for nm, x, y in vias:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(pt(x, y))
        v.SetWidth(MM(0.8))
        v.SetDrill(MM(0.4))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetNet(net(nm))
        board.Add(v)
    for layer in (pcbnew.F_Cu, pcbnew.B_Cu):
        gnd_zone(board, gnd, layer, w, h)
    for txt in b.get("silk", []):
        silk_text(board, *txt)
    pcbnew.SaveBoard(pcb_path, board)
    write_project(b, bdir)
    # reload so the design rules come from the project file, then pour the ground planes
    board = pcbnew.LoadBoard(pcb_path)
    board.BuildConnectivity()
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    # drop stitching vias that landed where a pour didn't reach on both layers
    zones = {z.GetLayer(): z for z in board.Zones()}
    stitched = {(round(x, 3), round(y, 3)) for nm, x, y in vias[len(r.vias):]}
    dropped = 0
    for v in list(board.GetTracks()):
        if v.Type() != pcbnew.PCB_VIA_T or v.GetNetname() != "GND":
            continue
        p = v.GetPosition()
        if (round(p.x / 1e6, 3), round(p.y / 1e6, 3)) not in stitched:
            continue
        if not all(zones[l].GetFilledPolysList(l).Contains(p) for l in (pcbnew.F_Cu, pcbnew.B_Cu)):
            board.Remove(v)
            dropped += 1
    if dropped:
        pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(pcb_path, board)
    print(f"{name}: {len(r.tracks)} segments, {len(vias)} vias, {len(failed)} failed "
          f"({time.time() - t0:.0f} s)")
    for f in failed:
        print("  FAILED", *f)
    return failed


if __name__ == "__main__":
    bad = []
    for nm in sys.argv[1:] or list(design.BOARDS):
        bad += build(nm)
    sys.exit(1 if bad else 0)
