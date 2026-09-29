"""Build docs/bom/README.md from docs/bom/bom.csv.

bom.csv is the source of truth. Edit it, then run:
    py -3 tools/make_bom_md.py
"""
import csv
from pathlib import Path

BOM_DIR = Path(__file__).resolve().parent.parent / "docs" / "bom"
SECTIONS = ["Electronics", "Motion", "Optics", "Fiber", "Base", "Host"]

HEADER = """# Bill of materials

Generated from [`bom.csv`](bom.csv) by `tools/make_bom_md.py`. Edit the CSV, not this file.

This is the NEMA 8 build (the current Motor-Mirror Assembly). Prices are Sept 2026 estimates
in USD, not quotes; blank means already owned or not priced.

Status: **Have** = on the bench, **Print** = 3D printed, **To buy**, **Check** = confirm
whether it is already on hand, **TBD** = part not chosen yet.
"""

ALTERNATE = """## Alternate: NEMA 11 build

Fall back to this if the knob torque test shows the adjusters need more than about 4 mN-m.
It swaps these lines; everything else stays the same.

| Replaces | With | Qty | Est. unit ($) |
| --- | --- | --- | --- |
| M1 NEMA 8 motor | NEMA 11, 28 mm frame, 45-51 mm body, 5 mm shaft, 10+ N-cm (StepperOnline 11HS20-0674S class) | 4 | 16 |
| M2 3-to-4 mm adapter | 5 mm to 5 mm shaft coupler | 4 | 3 |
| M3 3 mm drive rod | 5 mm steel rod, 100-200 mm, with bonded hex tip | 2 | 4 |
| M7 M2 motor screws | M3 screws (NEMA 11 flange) | 8 | |
| E6 12 V 2 A supply | 12 V 3 A supply | 1 | 10 |

The Motor Mount must be redrawn for the larger frame.
"""


def money(x):
    return f"{x:g}" if x else ""


def main():
    rows = list(csv.DictReader(open(BOM_DIR / "bom.csv", newline="", encoding="utf-8")))
    out = [HEADER]
    to_buy = 0.0
    for section in SECTIONS:
        part = [r for r in rows if r["section"] == section]
        if not part:
            continue
        out.append(f"## {section}\n")
        out.append("| ID | Item | Spec | Qty | Est. unit ($) | Source | Status | Phase | Notes |")
        out.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in part:
            unit = float(r["unit_usd"]) if r["unit_usd"] else 0.0
            if r["status"] == "To buy":
                to_buy += unit * int(r["qty"])
            cells = [r["id"], r["item"], r["spec"], r["qty"], money(unit), r["source"],
                     r["status"], r["phase"], r["notes"]]
            out.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
        out.append("")
    out.append(f"**Estimated spend on To buy lines: ${to_buy:g}** (excludes Check and TBD lines).\n")
    out.append(ALTERNATE)
    (BOM_DIR / "README.md").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    main()
