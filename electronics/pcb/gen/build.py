"""Regenerate both boards end to end and write the fab outputs.

  py -3 electronics/pcb/gen/build.py            # everything
  py -3 electronics/pcb/gen/build.py pd_amp     # one board

Steps per board: symbol/footprint library, schematic, netlist, PCB (placement, routing,
ground pours), ERC, DRC with schematic parity, then fab/<board>/:
  <board>_gerbers.zip   Gerbers + Excellon drill, upload as-is to JLCPCB / PCBWay / OSH Park
  <board>_bom.csv       Parts list with suggested part numbers
  <board>_schematic.pdf
  <board>_top.png       3D render
Stops with a non-zero exit if ERC or DRC finds an error or the router leaves a net open.
"""
import csv
import os
import re
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import design  # noqa: E402
from make_sch import KICAD  # noqa: E402

PCB_DIR = os.path.normpath(os.path.join(HERE, ".."))
CLI = os.path.join(KICAD, "bin", "kicad-cli.exe")
KPY = os.path.join(KICAD, "bin", "python.exe")


def run(*cmd, check=True):
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1")   # numpy in KiCad's Python can fail to allocate otherwise
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    out = "\n".join(l for l in (p.stdout + p.stderr).splitlines() if "image handler" not in l)
    if check and p.returncode:
        raise SystemExit(f"failed: {' '.join(cmd)}\n{out}")
    return out


def count(report, kind):
    m = re.search(rf"\*\* Found (\d+) {kind}", open(report, encoding="utf8").read())
    return int(m.group(1)) if m else 0


def bom(name, board, out):
    mpn = design.MPN[name]
    parts = board["parts"]
    rows = {}
    for ref in sorted(parts, key=lambda r: (r.rstrip("0123456789"), int(r[len(r.rstrip("0123456789")):]))):
        p = parts[ref]
        fp = p.get("fp", "")
        info = mpn.get(ref) or next((mpn[r] for r in mpn if r in parts and parts[r].get("fp", "") == fp
                                     and parts[r]["lib"] == p["lib"]), ("", p["value"]))
        if ref.startswith("H"):
            continue
        key = (info[1], info[0], fp)
        rows.setdefault(key, []).append(ref)
    with open(out, "w", newline="", encoding="utf8") as f:
        w = csv.writer(f)
        w.writerow(["refs", "qty", "description", "part number", "footprint"])
        for (desc, pn, fp), refs in rows.items():
            w.writerow([" ".join(refs), len(refs), desc, pn, fp])
        for refs, desc, pn, qty in design.EXTRA_BOM.get(name, []):
            w.writerow([refs, qty, desc, pn, ""])


def build(name):
    board = design.BOARDS[name]()
    bdir = os.path.join(PCB_DIR, name)
    sch, pcb, net = (os.path.join(bdir, f"{name}.{e}") for e in ("kicad_sch", "kicad_pcb", "net"))
    run(sys.executable, os.path.join(HERE, "make_sch.py"), name)
    run(CLI, "sch", "export", "netlist", "--format", "kicadsexpr", "-o", net, sch)
    print(run(KPY, os.path.join(HERE, "make_pcb.py"), name).strip())
    fab = os.path.join(PCB_DIR, "fab", name)
    shutil.rmtree(fab, ignore_errors=True)
    os.makedirs(fab)
    erc, drc = os.path.join(fab, "erc.rpt"), os.path.join(fab, "drc.rpt")
    run(CLI, "sch", "erc", "--severity-error", "-o", erc, sch, check=False)
    run(CLI, "pcb", "drc", "--schematic-parity", "--severity-error", "-o", drc, pcb, check=False)
    m = re.search(r"ERC messages: (\d+)", open(erc, encoding="utf8").read())
    errors = int(m.group(1)) if m else 0
    for kind in ("DRC violations", "unconnected pads", "Footprint errors"):
        errors += count(drc, kind)
    print(f"{name}: ERC/DRC errors: {errors}")
    gdir = os.path.join(fab, "gerbers")
    os.makedirs(gdir)
    run(CLI, "pcb", "export", "gerbers", "--layers",
        "F.Cu,B.Cu,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts",
        "--subtract-soldermask", "--check-zones", "-o", gdir + os.sep, pcb)
    run(CLI, "pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm",
        "--generate-map", "--map-format", "pdf", "-o", gdir + os.sep, pcb)
    with zipfile.ZipFile(os.path.join(fab, f"{name}_gerbers.zip"), "w", zipfile.ZIP_DEFLATED) as z:
        for fn in sorted(os.listdir(gdir)):
            if not fn.endswith(".pdf"):
                z.write(os.path.join(gdir, fn), fn)
    shutil.rmtree(gdir)
    run(CLI, "sch", "export", "pdf", "-o", os.path.join(fab, f"{name}_schematic.pdf"), sch)
    run(CLI, "pcb", "export", "pdf", "--layers", "F.Cu,F.SilkS,Edge.Cuts", "--mode-single",
        "-o", os.path.join(fab, f"{name}_layout_top.pdf"), pcb)
    run(CLI, "pcb", "render", "--side", "top", "--quality", "high", "--width", "1600", "--height", "1600",
        "--background", "opaque", "-o", os.path.join(fab, f"{name}_top.png"), pcb)
    bom(name, board, os.path.join(fab, f"{name}_bom.csv"))
    if not errors:                                   # keep the reports only when they have something to say
        os.remove(erc)
        os.remove(drc)
    return errors


if __name__ == "__main__":
    run(sys.executable, os.path.join(HERE, "make_lib.py"))
    bad = sum(build(n) for n in (sys.argv[1:] or list(design.BOARDS)))
    sys.exit(1 if bad else 0)
