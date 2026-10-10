"""Knock-and-recover trials on a simulated bench."""

from __future__ import annotations

from dataclasses import replace
from typing import NamedTuple

import numpy as np

from .align import Aligner, Settings, make_plan
from .bench import Bench, Mechanics, randomized
from .optics import Optics


class Trial(NamedTuple):
    mirror: int
    knock_mrad: float
    ok: bool             # back to 90% of the best coupling this bench can reach
    coupling: float      # final coupling as a share of the best
    seconds: float
    moves: int
    reads: int


def make_bench(fiber="sm630", seed=0, spread=1.0, optics=None, mechanics=None):
    """A 'real' bench: design values nudged at random (see bench.randomized),
    with the peak somewhere within 0.1 turn of zero on every axis."""
    rng = np.random.default_rng(seed)
    opt = optics or Optics(fiber=fiber)
    mech = mechanics or Mechanics()
    m, o = randomized(mech, opt, rng, spread)
    peak = rng.uniform(-0.1, 0.1, 4) * mech.usteps_per_rev
    return Bench(o, m, peak_usteps=peak, seed=seed)


def run_trials(n=50, fiber="sm630", naive=False, seed=0, knock_mrad=(0.3, 3.0), settings=None,
               spread=1.0):
    """Calibrate once on the peak, then n times: back to the peak, knock a
    random mirror, recover. The aligner only knows the design values."""
    settings = replace(settings or Settings(), naive=naive)
    plan = make_plan(Bench(Optics(fiber=fiber)), settings.detect_frac)
    bench = make_bench(fiber, seed, spread)
    rng = np.random.default_rng(seed + 1)
    aligner = Aligner(bench, plan, settings)
    bench.jump_to_peak()
    aligner.calibrate()
    out = []
    for _ in range(n):
        bench.clear_knocks()
        bench.jump_to_peak()
        aligner.forget_direction()
        # The knock comes from this loop's own generator, not the bench's (which
        # also draws photodiode noise), so two methods compared on the same
        # seed meet the same knocks.
        mirror, dx, dy = bench.knock(int(rng.integers(1, 3)), rng.uniform(*knock_mrad), rng.uniform(0, 2 * np.pi))
        res = aligner.recover()
        c = float(bench.coupling() / bench.best_coupling())
        out.append(Trial(mirror, float(np.hypot(dx, dy)), c >= 0.9, c, res.seconds, res.moves, res.reads))
    return out
