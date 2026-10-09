"""Automatic alignment: find light after a knock, then walk the beam back to the peak.

This is the controller side, kept apart from the model so the same code can
drive the real bench. It needs a bench object with:

    position               -> the four motor positions, microsteps (M1X, M1Y, M2X, M2Y)
    move_to(target, speed_rpm=None, accel_rpm_s=None)   blocking move
    read(seconds)          -> a reading with .ratio (out/ref, or None with no light)
    clock, n_moves, n_reads   for the statistics

bench_twin.Bench has all of these.

How it works. With a single-mode fiber the coupling depends on two things
per axis: where the spot lands on the fiber (set by the beam's angle at the
lens) and the angle it comes in at (set by the beam's offset at the lens).
The first is ~25 times more sensitive than the second, and both mirrors change
both, so in motor coordinates the peak is a long, thin valley running
diagonally across M1/M2. Stepping one motor at a time crawls along it. The
aligner instead uses the two directions people use by hand:

    steer: M2 alone. Moves the spot across the fiber (the narrow direction).
    walk:  M1 plus a matched opposite M2 move that keeps the spot where it is
           and only changes the angle (the wide direction).

`calibrate` measures the walk ratio on the bench (it depends on the motor
directions and lever arms). Every line search approaches each of its points
with every axis moving +, whichever way the search runs, so the play in the
hex couplings always sits on the same side.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import NamedTuple

import numpy as np

E = np.eye(4)        # unit moves of M1X, M1Y, M2X, M2Y


@dataclass(frozen=True)
class Plan:
    """What the aligner knows about the bench, from the design values (make_plan)
    and refined on the bench by Aligner.calibrate."""
    narrow: tuple        # 1/e half-width of the peak along M2X, M2Y alone, microsteps
    walk: tuple          # 1/e half-width along the walk, in M1 microsteps (x, y)
    slope: tuple         # M2 microsteps per M1 microstep along the walk (x, y)
    capture: tuple       # distance along M2X, M2Y where the signal falls to the detect level
    peak_ratio: float    # out/ref expected at the peak


@dataclass(frozen=True)
class Settings:
    read_s: float = 0.02         # photodiode averaging per point
    detect_frac: float = 0.02    # "light found" above this share of the aligned ratio
    success_frac: float = 0.90   # a recovery counts once back to this share
    step_frac: float = 0.6       # line-search step, as a share of the 1/e half-width
    overshoot: float = 40        # microsteps past a point before approaching it; more than the play
    flat_tol: float = 0.01       # samples this close to the best count as one plateau (multimode)
    tol: float = 0.003           # stop sweeping when a sweep gains less than this share
    max_sweeps: int = 8
    search_turns: float = 0.4    # how far the spiral goes on M2, adjuster turns
    max_travel: float = 1600     # a line search goes no further than this from its start, microsteps
    spiral_pitch: float = 1.2    # spiral spacing as a multiple of the capture distance
    speed_rpm: float = 60.0      # motion used while aligning (try on the bench)
    accel_rpm_s: float = 600.0
    naive: bool = False          # climb one motor at a time instead of steer + walk


class Result(NamedTuple):
    ok: bool
    found: bool          # light was found (straight away or by the spiral)
    ratio: float
    seconds: float
    moves: int
    reads: int
    note: str = ""       # why a run that found light is not ok


class NoReference(RuntimeError):
    """The reading has no out/ref ratio: the laser is off or the reference
    photodiode sees under 10 mV, so the output can't be judged."""


def make_plan(bench, detect_frac=Settings.detect_frac):
    """Work out step sizes and walk directions from a model bench with design values."""
    a0 = bench.peak_adjuster()
    e0 = float(bench.coupling(a0))

    def width(v, level):
        lo, hi = 0.0, 1.0
        while float(bench.coupling(a0 + hi * v)) > level * e0 and hi < 1e6:
            hi *= 2
        for _ in range(40):
            mid = (lo + hi) / 2
            if float(bench.coupling(a0 + mid * v)) > level * e0:
                lo = mid
            else:
                hi = mid
        return lo

    beam0 = bench.beam_at_lens(a0)
    d_theta = np.array([bench.beam_at_lens(a0 + E[i])[1 + 2 * (i % 2)] - beam0[1 + 2 * (i % 2)]
                        for i in range(4)])
    slope = (-d_theta[0] / d_theta[2], -d_theta[1] / d_theta[3])
    inv_e = math.exp(-1)
    return Plan(narrow=(width(E[2], inv_e), width(E[3], inv_e)),
                walk=(width(E[0] + slope[0] * E[2], inv_e), width(E[1] + slope[1] * E[3], inv_e)),
                slope=slope,
                capture=(width(E[2], detect_frac), width(E[3], detect_frac)),
                peak_ratio=float(bench.peak_ratio()))


def square_spiral(rings):
    """(i, j) grid points ring by ring outward from (0, 0), each next to the last."""
    yield 0, 0
    for k in range(1, rings + 1):
        for j in range(-k + 1, k + 1):
            yield k, j
        for i in range(k - 1, -k - 1, -1):
            yield i, k
        for j in range(k - 1, -k - 1, -1):
            yield -k, j
        for i in range(-k + 1, k + 1):
            yield i, -k


def spiral_points(plan, search_turns, usteps_per_rev=3200, spiral_pitch=Settings.spiral_pitch):
    """How many positions the M2 search visits out to search_turns either way."""
    reach = search_turns * usteps_per_rev
    n = [2 * int(reach // (spiral_pitch * c)) + 1 for c in plan.capture]
    return n[0] * n[1]


class Aligner:
    def __init__(self, bench, plan: Plan, settings: Settings = None, say=None):
        self.bench = bench
        self.plan = plan
        self.s = settings or Settings()
        self.say = say or (lambda text: None)    # progress messages
        self.good = plan.peak_ratio          # the aligned ratio; measured by calibrate()
        self._last_dir = np.zeros(4)         # last move direction per axis, 0 = unknown
        self.trace = []                      # (clock, position, ratio) for every reading

    # ── moving and reading ───────────────────────────────────────────────────
    def forget_direction(self):
        """Call after anything else moved the motors: the play state is unknown."""
        self._last_dir[:] = 0

    def _read(self):
        r = self.bench.read(self.s.read_s).ratio
        if r is None:                    # searching on zeros would only report "no light"
            raise NoReference("no reference light: the laser is off, blocked, or the reference "
                              "photodiode reads under 10 mV")
        r = float(r)
        self.trace.append((self.bench.clock, self.bench.position, r))
        return r

    def _move(self, target):
        d = target - self.bench.position
        if np.any(d != 0):
            self.bench.move_to(target, self.s.speed_rpm, self.s.accel_rpm_s)
            moved = d != 0
            self._last_dir[moved] = np.sign(d[moved])

    def _go(self, target, rising=None):
        """Move to target. With `rising` (a direction), every axis that direction
        moves arrives travelling the same way it points, so the play sits on the
        same side every time; axes that would arrive the other way first go
        `overshoot` past."""
        target = np.round(np.asarray(target, float))
        if rising is not None:
            v = np.sign(np.asarray(rising, float))
            d = target - self.bench.position
            ok = (v == 0) | ((self._last_dir == v) & (d * v >= 0))
            if not np.all(ok):
                self._move(np.where(ok, target, target - v * self.s.overshoot))
        self._move(target)

    # ── building blocks ──────────────────────────────────────────────────────
    def line_peak(self, v, h, max_ext=12):
        """Peak the ratio along direction v (microsteps per unit) with steps of h
        units, finishing at the peak. Returns the ratio there."""
        v = np.asarray(v, float)
        base = self.bench.position.astype(float)
        pts = {}

        def at(c):
            return base + v * (c * h)

        # Every axis arrives moving +, whichever way v points: a walk line moves
        # M2 against M1 when the slope is negative, and arriving the other way
        # there would put the play on the other side from the steer searches.
        up = np.abs(v)

        def sample(c):
            self._go(at(c), rising=up)
            pts[c] = self._read()

        for c in (-1, 0, 1):
            sample(c)
        reach = self.s.max_travel / (h * max(np.abs(v).max(), 1e-9))
        for _ in range(max_ext):          # bracket: keep going while the best is at an end
            best = max(pts, key=pts.get)
            if best == max(pts) and best + 1 <= reach:
                sample(best + 1)
            elif best == min(pts) and best - 1 >= -reach:
                sample(best - 1)
            else:
                break
        best = max(pts, key=pts.get)
        if pts[best] <= 0:                # nothing seen at all: go back
            self._go(base, rising=up)
            return self._read()

        # A flat top (multimode core): aim for the middle of it. A peak: fit a
        # parabola to log(ratio), which is exact for a Gaussian peak.
        flat = [c for c in pts if pts[c] >= pts[best] * (1 - self.s.flat_tol)]
        c_star = float(best)
        if len(flat) > 1 and max(flat) - min(flat) == len(flat) - 1:
            c_star = (min(flat) + max(flat)) / 2
        elif best - 1 in pts and best + 1 in pts and min(pts[best - 1], pts[best + 1]) > 0:
            lm, l0, lp = (math.log(pts[c]) for c in (best - 1, best, best + 1))
            den = lm - 2 * l0 + lp
            if den < 0:
                c_star = best + max(-0.5, min(0.5, 0.5 * (lm - lp) / den))
        self._go(at(c_star), rising=up)
        r = self._read()
        if r < pts[best] * (1 - self.s.flat_tol):   # play or noise put it off: take the best sample
            self._go(at(best), rising=up)
            r = self._read()
        return r

    def steer(self):
        p, f = self.plan, self.s.step_frac
        return [(E[2 + k], f * p.narrow[k]) for k in (0, 1)]

    def sweep(self):
        """(direction, step) for each line search of a sweep. A sweep ends with
        the steer searches: a walk can shift the spot by the play in M1's
        coupling, and steering puts it back."""
        p, f = self.plan, self.s.step_frac
        if self.s.naive:
            return [(E[i], f * p.narrow[i % 2]) for i in (0, 1, 2, 3)]
        return [(E[k] + p.slope[k] * E[2 + k], f * p.walk[k]) for k in (0, 1)] + self.steer()

    def peak(self):
        """Steer onto the ridge, then sweep until a sweep no longer changes the ratio."""
        self.say("peaking")
        r = self._read()
        if not self.s.naive:
            for v, h in self.steer():
                r = self.line_peak(v, h)
        for _ in range(self.s.max_sweeps):
            before = r
            for v, h in self.sweep():
                r = self.line_peak(v, h)
            if abs(r - before) < self.s.tol * before:
                break
        return r

    def spiral(self):
        """Search M2 outward on a grid until the ratio clears the detect level."""
        u = getattr(getattr(self.bench, "mech", None), "usteps_per_rev", 3200)
        thr = self.s.detect_frac * self.good
        start = self.bench.position.astype(float)
        pitch = self.s.spiral_pitch * np.asarray(self.plan.capture, float)
        reach = self.s.search_turns * u
        self.say(f"no light: searching M2 up to {self.s.search_turns:g} turn either way "
                 f"({spiral_points(self.plan, self.s.search_turns, u, self.s.spiral_pitch)} points)")
        for i, j in square_spiral(int(math.ceil(reach / pitch.min()))):
            dx, dy = i * pitch[0], j * pitch[1]
            if abs(dx) > reach or abs(dy) > reach:
                continue
            self._go(start + np.array([0.0, 0.0, dx, dy]))
            if self._read() > thr:
                return True
        self._go(start)
        return False

    # ── entry points ─────────────────────────────────────────────────────────
    def calibrate(self, span=10.0):
        """Measure the walk directions on this bench. Start on or near the peak.
        Push M1 off by `span` steer steps, find where M2 re-peaks, and take
        the ratio of the two moves. Ends on the peak and records its ratio."""
        slopes = list(self.plan.slope)
        self.problems = []
        self.say("calibrating the walk directions")
        for k in (0, 1):
            m1, m2 = k, 2 + k
            h = self.s.step_frac * self.plan.narrow[k]
            self.line_peak(E[m2], h)
            c0 = self.bench.position[m2]
            d = round(span * h)
            self._go(self.bench.position + d * E[m1], rising=E[m1])
            # Scan M2 across where the peak could have gone, either way
            n = int(math.ceil(1.5 * d * abs(self.plan.slope[k]) / h)) + 1
            base = self.bench.position.astype(float)
            best_c, best_r = 0, -1.0
            for c in range(-n, n + 1):
                self._go(base + c * h * E[m2], rising=E[m2])
                r = self._read()
                if r > best_r:
                    best_c, best_r = c, r
            self._go(base + best_c * h * E[m2], rising=E[m2])
            self.line_peak(E[m2], h)
            slopes[k] = (self.bench.position[m2] - c0) / d
            axis = "XY"[k]
            design = abs(self.plan.slope[k])
            if design > 0 and not 0.5 <= abs(slopes[k]) / design <= 2.0:
                self.problems.append(f"walk direction {axis} measured {slopes[k]:+.2f}, expected about "
                                     f"{design:.2f} either sign")
            back = self.bench.position.astype(float)
            back[m1] -= d
            back[m2] = c0
            self._go(back)
        self.plan = replace(self.plan, slope=tuple(float(s) for s in slopes))
        self.good = self.peak()
        self._check_contrast()
        return self.plan

    def _check_contrast(self, reach=3.0):
        """Real coupling is a peak: `reach` capture distances to either side of
        it along M2X and M2Y the ratio is far below the top. An offset, room
        light or scatter reads about the same everywhere. Ends back on the peak."""
        home = self.bench.position.astype(float)
        side = 0.0
        for k in (0, 1):
            for sign in (-1, 1):
                self._go(home + sign * reach * self.plan.capture[k] * E[2 + k])
                side = max(side, self._read())
        self._go(home, rising=np.ones(4))     # every line search ends arriving moving +
        if self.good <= 0 or side > 0.5 * self.good:
            self.problems.append(f"no peak: {side:.4g} off to the side against {self.good:.4g} on the peak, "
                                 "so this looks like an offset, room light or scatter rather than light in "
                                 "the fiber (check Measure dark)")

    def first_align(self):
        """On a bench seen for the first time (or a new fiber): find light,
        measure the walk directions and peak. Returns a Result whose ok means
        light was found, the calibration looks like real coupling, and the
        peak it ended on is the new reference; otherwise note says why."""
        b = self.bench
        t0, m0, r0 = b.clock, b.n_moves, b.n_reads
        r = self._read()
        found = r > self.s.detect_frac * self.good or self.spiral()
        note = ""
        if found:
            self.calibrate()
            r = self.good
            note = "; ".join(self.problems)
        return Result(found and not note, found, r, b.clock - t0, b.n_moves - m0, b.n_reads - r0, note)

    def recover(self):
        """Get back to the peak from wherever the beam is now."""
        b = self.bench
        t0, m0, r0 = b.clock, b.n_moves, b.n_reads
        r = self._read()
        found = r > self.s.detect_frac * self.good or self.spiral()
        if found:
            r = self.peak()
        return Result(found and r >= self.s.success_frac * self.good, found, r,
                      b.clock - t0, b.n_moves - m0, b.n_reads - r0)
