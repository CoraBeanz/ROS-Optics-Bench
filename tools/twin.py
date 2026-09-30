#!/usr/bin/env python3
"""Bench twin: what the simulator says about the bench.

    py -3 tools/twin.py                      key numbers for the single-mode fiber
    py -3 tools/twin.py --fiber mm50         ... for the multimode first-light fiber
    py -3 tools/twin.py ceiling              best coupling vs aperture size and lens
    py -3 tools/twin.py trials -n 100        knock a mirror and recover, 100 times
    py -3 tools/twin.py trials --naive       ... one motor at a time, for comparison
    py -3 tools/twin.py landscape            picture of the peak over M1X and M2X (needs matplotlib)

Fibers: sm630 (single-mode, the goal), mm50 (50 um multimode, first light),
smf28 (the SMF-28 practice cable, which carries a few modes at 635 nm).
"""

import argparse
import math
import os
import sys
import time

import numpy as np

from bench_twin import FIBERS, Aligner, Bench, Optics, Settings, make_plan
from bench_twin.trials import run_trials


def summary(fiber):
    b = Bench(Optics(fiber=fiber))
    o, m = b.optics, b.mech
    plan = make_plan(b)
    tilt = m.pitch_mm / m.usteps_per_rev / m.lever_mm[0] * 1e6
    b.jump_to_peak()
    ref, out = b.volts()
    print(f"Bench twin, {FIBERS[fiber].label}")
    print(f"  1 microstep tilts a mirror {tilt:.2f} urad and moves the beam {2 * tilt:.2f} urad (X) "
          f"or {math.sqrt(2) * tilt:.2f} urad (Y)")
    ap = "no aperture" if o.aperture_radius is None else f"the {o.p.aperture_mm:g} mm aperture"
    print(f"  {o.throughput:.0%} of the laser power gets through {ap}")
    print(f"  Best coupling {o.peak:.0%}, out/ref ratio at the peak {b.peak_ratio():.3f} "
          f"(ref {ref:.2f} V, out {out:.2f} V)")
    print(f"  Peak half-width (to 1/e): M2X {plan.narrow[0]:.0f}, M2Y {plan.narrow[1]:.0f} microsteps "
          f"({plan.narrow[0] / 16:.1f} and {plan.narrow[1] / 16:.1f} full steps)")
    print(f"  Along the walk (M1 with M2 turned the opposite way): {plan.walk[0]:.0f} (x), "
          f"{plan.walk[1]:.0f} (y) microsteps of M1: a valley {plan.walk[0] / plan.narrow[0]:.0f} times "
          f"longer than it is wide")
    print(f"  Light drops to 2% of the peak {plan.capture[0]:.0f} (M2X) and {plan.capture[1]:.0f} (M2Y) "
          f"microsteps off")
    if o.fiber.kind == "sm":
        print(f"  Fiber mode seen at the lens: {2 * o.mode_radius_lens:.2f} mm across; "
              f"beam after the aperture about {2 * o.beam_radius_eq[0]:.2f} x {2 * o.beam_radius_eq[1]:.2f} mm")


def ceiling():
    print("Best single-mode (sm630) coupling, and how much of the laser gets through the aperture")
    fs = (8.0, 9.0, 10.0, 11.0)
    print("  aperture  " + "".join(f"{f'f={f:g} mm':>10s}" for f in fs) + "   through")
    for ap in (None, 1.5, 1.8, 2.0, 2.5, 3.0):
        row = [Bench(Optics(fiber="sm630", aperture_mm=ap, lens_f_mm=f)).optics for f in fs]
        name = "none" if ap is None else f"{ap:g} mm"
        print(f"  {name:8s}" + "".join(f"{r.peak:10.0%}" for r in row) + f"{row[0].throughput:10.0%}")
    for fiber in ("mm50", "smf28"):
        o = Bench(Optics(fiber=fiber)).optics
        print(f"  {fiber}: {o.peak:.0%} with the 2 mm aperture and f = 8 mm")


def trials(args):
    s = Settings()
    methods = [("walk", False), ("one motor", True)] if args.compare else \
              [("one motor" if args.naive else "walk", args.naive)]
    print(f"{args.n} knocks of {args.knock[0]:g}-{args.knock[1]:g} mrad on a random mirror, "
          f"{args.fiber}, seed {args.seed}")
    print("  method      recovered   time median / worst   coupling median / worst   moves   reads")
    for name, naive in methods:
        t0 = time.time()
        rs = run_trials(args.n, args.fiber, naive, args.seed, tuple(args.knock), s)
        ok = sum(r.ok for r in rs)
        t = np.array([r.seconds for r in rs])
        c = np.array([r.coupling for r in rs])
        print(f"  {name:10s} {ok:4d}/{len(rs):<4d}   {np.median(t):6.1f} s / {t.max():5.1f} s"
              f"        {np.median(c):6.1%} / {c.min():6.1%}      {np.median([r.moves for r in rs]):5.0f}"
              f"   {np.median([r.reads for r in rs]):5.0f}   ({time.time() - t0:.1f} s to run)")


def landscape(args):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        sys.exit("landscape needs matplotlib: py -3 -m pip install matplotlib")
    knock = 1.2e-3             # rad of M1 tilt about the vertical: the X plane only

    def knocked():
        b = Bench(Optics(fiber=args.fiber), seed=args.seed)
        b.jump_to_peak()
        b.offset[0] += knock
        return b

    bench = knocked()
    plan = make_plan(bench)
    a0 = bench.peak_adjuster()

    def grid(x0, x1, y0, y1, n=301):
        g1, g2 = np.meshgrid(np.linspace(x0, x1, n), np.linspace(y0, y1, n))
        adj = np.zeros(g1.shape + (4,)) + a0
        adj[..., 0] += g1
        adj[..., 2] += g2
        return g1, g2, bench.coupling(adj) / bench.best_coupling()

    # Recover from the knock both ways; paths relative to the new peak
    paths = {}
    for name, naive in (("steer + walk", False), ("one motor at a time", True)):
        b = knocked()
        al = Aligner(b, plan, Settings(naive=naive))
        res = al.recover()
        pts = np.array([p for _, p, _ in al.trace])
        ref = b.peak_motor()
        paths[name] = (pts[:, 0] - ref[0], pts[:, 2] - ref[2], res, b.coupling() / b.best_coupling())

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), dpi=110)
    colors = {"one motor at a time": "#4a9eff", "steer + walk": "#2ecc40"}
    s1 = 2.2 * plan.walk[0]
    s2 = s1 * abs(plan.slope[0]) + 3 * plan.capture[0]
    xs = np.concatenate([p[0] for p in paths.values()])
    ys = np.concatenate([p[1] for p in paths.values()])
    mx, my = 0.15 * np.ptp(xs) + 30, 0.15 * np.ptp(ys) + 30
    boxes = [(-s1, s1, -s2, s2), (xs.min() - mx, xs.max() + mx, ys.min() - my, ys.max() + my)]
    for ax, box, zoom in zip(axes, boxes, (False, True)):
        g1, g2, eta = grid(*box)
        im = ax.pcolormesh(g1, g2, eta, shading="auto", cmap="magma", vmin=0, vmax=1)
        cs = ax.contour(g1, g2, eta, levels=[0.02, 0.25, 0.5, 0.9], colors="white", linewidths=0.6, alpha=0.6)
        ax.clabel(cs, fmt=lambda v: f"{v:.0%}", fontsize=7)
        if zoom:
            for name, (x, y, res, final) in paths.items():
                ax.plot(x, y, "-", color=colors[name], lw=1.0, alpha=0.9,
                        label=f"{name}: {final:.0%} of best after {res.seconds:.0f} s")
                ax.plot(x, y, ".", color=colors[name], ms=2.5)
                ax.plot(x[-1], y[-1], "o", color=colors[name], ms=6, mec="white")
            ax.plot(xs[0], ys[0], "x", color="white", ms=8)
            ax.annotate("start (knocked)", (xs[0], ys[0]), textcoords="offset points", xytext=(6, 6),
                        color="white", fontsize=8)
            ax.legend(loc="lower right", fontsize=8)
            ax.set_title("Zoom: the paths after a 1.2 mrad knock of M1", fontsize=9)
        else:
            ax.add_patch(plt.Rectangle((boxes[1][0], boxes[1][2]), boxes[1][1] - boxes[1][0],
                                       boxes[1][3] - boxes[1][2], fill=False, ec="#4a9eff", lw=1))
            ax.set_title(f"Coupling over M1X and M2X, {FIBERS[args.fiber].label}", fontsize=9)
        ax.set_xlabel("M1X from the peak (microsteps)")
        ax.set_ylabel("M2X from the peak (microsteps)")
    fig.colorbar(im, ax=axes, label="coupling / best", shrink=0.9)
    fig.savefig(args.out, bbox_inches="tight")
    print(f"saved {args.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", nargs="?", default="summary", choices=["summary", "ceiling", "trials", "landscape"])
    ap.add_argument("--fiber", default="sm630", choices=sorted(FIBERS))
    ap.add_argument("-n", type=int, default=50, help="trials: number of knocks")
    ap.add_argument("--knock", type=float, nargs=2, default=[0.3, 3.0], metavar=("MIN", "MAX"),
                    help="trials: knock size range, mrad of mirror tilt")
    ap.add_argument("--naive", action="store_true", help="trials: one motor at a time")
    ap.add_argument("--compare", action="store_true", help="trials: run both methods")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir, "docs",
                                                  "images", "twin_landscape.png"),
                    help="landscape: output file (default: the README's picture)")
    args = ap.parse_args()
    if args.what == "summary":
        summary(args.fiber)
    elif args.what == "ceiling":
        ceiling()
    elif args.what == "trials":
        trials(args)
    else:
        landscape(args)


if __name__ == "__main__":
    main()
