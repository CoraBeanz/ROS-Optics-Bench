"""The bench: four motors turning the mirror adjusters, the optics, and the
two photodiodes read by the ADS1115, with a clock so a routine can be timed.

Motor positions are in microsteps, like the firmware protocol. The model sits
between the motors and the light:

    motor microsteps -> adjuster (after the play in the hex bit coupling)
    adjuster turns -> mirror tilt (100 TPI screw on a lever arm, a little crosstalk)
    mirror tilts + knocks + drift -> beam offset and angle at the lens
    beam at the lens -> coupling (optics.py) -> photodiode volts -> out/ref ratio

The values marked "measure" are estimates to replace with bench numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import NamedTuple, Optional, Tuple

import numpy as np

from .optics import OpticalModel, Optics

AXES = ("M1X", "M1Y", "M2X", "M2Y")
SQRT2 = math.sqrt(2.0)
FSRS = (4.096, 2.048, 1.024, 0.512, 0.256)   # ADS1115 ranges the firmware uses


@dataclass(frozen=True)
class Mechanics:
    usteps_per_rev: int = 3200                # config.h: 200 full steps x 16
    pitch_mm: float = 0.254                   # 100 TPI adjuster
    # Adjuster to the tilt axis. Measure: taken from the 24.5 mm motor
    # spacing, assuming the pivot sits at the right-angle corner.
    lever_mm: Tuple[float, ...] = (17.3, 17.3, 17.3, 17.3)
    # Tilt about the other axis per unit of tilt, per mirror (measure)
    crosstalk: Tuple[float, float] = (0.0, 0.0)
    # Rotational play between the motor and the adjuster, mostly the hex bit
    # in its socket (measure with a hysteresis test)
    backlash_deg: Tuple[float, ...] = (1.0, 1.0, 1.0, 1.0)
    # Which way the beam moves for a positive step; depends on wiring and invert
    signs: Tuple[int, ...] = (1, 1, 1, 1)
    speed_rpm: float = 30.0                   # config.h defaults
    accel_rpm_s: float = 120.0
    settle_s: float = 0.02                    # mount ringing after a move
    drift_urad_rt_s: float = 0.0              # random walk of every mirror tilt


@dataclass(frozen=True)
class Sensors:
    laser_mw: float = 0.9                     # Quarton module, < 1 mW
    attenuator: float = 0.30                  # crossed polarizers, the brightness knob
    bs_reflect: float = 0.50                  # beamsplitter share to the reference photodiode
    bs_transmit: float = 0.50                 # share sent on to M1
    mirror_reflect: float = 0.95
    lens_transmit: float = 0.95
    fiber_face: float = 0.965                 # Fresnel loss at each fiber end
    responsivity_a_w: float = 0.40            # BPW34 at 635 nm (config.h)
    tia_ohms: Tuple[float, float] = (47000.0, 47000.0)
    rail_v: float = 3.25                      # MCP6002 output ceiling on 3.3 V
    dark_v: Tuple[float, float] = (0.004, 0.003)
    noise_v: float = 20e-6                    # per ADC sample, each channel
    laser_noise: float = 0.002                # fast relative noise, per sample
    samples_per_s: float = 430.0              # 860 SPS shared by two channels
    latency_s: float = 0.005                  # serial round trip per reading


class Reading(NamedTuple):
    ref_v: float
    out_v: float
    ratio: Optional[float]       # out/ref, None with the laser off or no reference light


def move_time(distance, speed_rpm, accel_rpm_s, usteps_per_rev):
    """Seconds for a trapezoidal move of `distance` microsteps (AccelStepper-like)."""
    v = speed_rpm / 60 * usteps_per_rev
    a = accel_rpm_s / 60 * usteps_per_rev
    d = np.abs(np.asarray(distance, float))
    return np.where(d <= v * v / a, 2 * np.sqrt(d / a), d / v + v / a)


class Bench:
    """A simulated bench. `peak_usteps` is where the motors put the beam on
    the lens axis with no knocks: the hidden best position."""

    def __init__(self, optics: Optional[Optics] = None, mechanics: Optional[Mechanics] = None,
                 sensors: Optional[Sensors] = None, peak_usteps=(0, 0, 0, 0), seed=None):
        self.rng = np.random.default_rng(seed)
        self.optics = OpticalModel(optics)
        self.mech = m = mechanics or Mechanics()
        self.sens = sensors or Sensors()
        self.peak_usteps = np.asarray(peak_usteps, float)
        u = m.usteps_per_rev
        self._tilt_per_ustep = m.pitch_mm / u / np.asarray(m.lever_mm, float)
        # Beam deviation per unit mirror tilt. X turns the mirror about the
        # vertical, in the plane of incidence: 2x. Y tilts it about an axis in
        # the plane of incidence of a 45 degree mirror: 2 cos 45 = sqrt(2).
        self._gain = np.asarray(m.signs, float) * np.array([2.0, SQRT2, 2.0, SQRT2])
        mix = np.eye(4)
        for mirror, ct in enumerate(m.crosstalk):
            i, j = 2 * mirror, 2 * mirror + 1
            mix[i, j] = mix[j, i] = ct
        self._mix = mix
        self._half_play = np.asarray(m.backlash_deg, float) / 360 * u / 2
        self.offset = np.zeros(4)                 # mirror tilts from knocks and drift, rad
        self.motor = np.zeros(4)
        self.adjuster = self.motor - self._half_play   # as if the last moves were positive
        self.laser = True
        self.clock = 0.0
        self.n_moves = 0
        self.n_reads = 0

    # ── state to light ───────────────────────────────────────────────────────
    @property
    def position(self):
        return self.motor.copy()

    def mirror_tilts(self, adjuster=None):
        a = self.adjuster if adjuster is None else np.asarray(adjuster, float)
        return ((a - self.peak_usteps) * self._tilt_per_ustep) @ self._mix.T + self.offset

    def beam_at_lens(self, adjuster=None):
        """(x, theta_x, y, theta_y) at the lens, relative to its axis."""
        phi = self.mirror_tilts(adjuster) * self._gain
        l1, l2 = self.optics.l1, self.optics.l2
        return np.stack([l1 * phi[..., 0] + l2 * phi[..., 2], phi[..., 0] + phi[..., 2],
                         l1 * phi[..., 1] + l2 * phi[..., 3], phi[..., 1] + phi[..., 3]], -1)

    def coupling(self, adjuster=None):
        return self.optics.coupling(self.beam_at_lens(adjuster))

    def best_coupling(self):
        return self.optics.peak

    def peak_adjuster(self):
        """Adjuster positions that put the beam back on the lens axis."""
        k = self._tilt_per_ustep
        return self.peak_usteps - np.linalg.solve(self._mix, self.offset) / k

    def peak_motor(self, approach=1):
        """Motor positions for the peak when every axis arrives moving in `approach`."""
        return self.peak_adjuster() + approach * self._half_play

    def path_ratio(self):
        """out/ref ratio per unit coupling: everything between the two photodiodes."""
        s = self.sens
        return (s.bs_transmit / s.bs_reflect * s.mirror_reflect ** 2 * s.lens_transmit * s.fiber_face ** 2
                * s.tia_ohms[1] / s.tia_ohms[0])

    def peak_ratio(self):
        return self.path_ratio() * self.best_coupling()

    # ── motion ───────────────────────────────────────────────────────────────
    def set_motor(self, pos):
        """Put the motors at `pos` right away (the GUI simulator calls this as
        its motors move). The adjusters follow through the play."""
        m = np.asarray(pos, float)
        self.adjuster = np.clip(self.adjuster, m - self._half_play, m + self._half_play)
        self.motor = m.copy()

    def move_to(self, target, speed_rpm=None, accel_rpm_s=None):
        """Move all axes together and wait; returns the seconds it took."""
        target = np.asarray(target, float)
        m = self.mech
        d = np.abs(target - self.motor)
        if not np.any(d > 0):
            return 0.0
        t = float(np.max(move_time(d, speed_rpm or m.speed_rpm, accel_rpm_s or m.accel_rpm_s,
                                   m.usteps_per_rev))) + m.settle_s
        self.set_motor(target)
        self.advance(t)
        self.n_moves += 1
        return t

    def jump_to_peak(self, approach=1):
        """Put the motors on the peak with no time cost (to set up a test)."""
        self.set_motor(self.peak_motor(approach) - approach * 2 * self._half_play)
        self.set_motor(self.peak_motor(approach))

    # ── disturbances ─────────────────────────────────────────────────────────
    def advance(self, dt):
        self.clock += dt
        if self.mech.drift_urad_rt_s and dt > 0:
            self.offset += self.rng.normal(0, self.mech.drift_urad_rt_s * 1e-6 * math.sqrt(dt), 4)

    def knock(self, mirror=None, mrad=None, angle=None):
        """Tilt a mirror mount by `mrad` in direction `angle` (radians; random
        if not given), as if bumped. Returns (mirror, x tilt, y tilt) in mrad."""
        mirror = int(self.rng.integers(1, 3)) if mirror is None else int(mirror)
        mrad = float(self.rng.uniform(0.3, 3.0)) if mrad is None else float(mrad)
        a = self.rng.uniform(0, 2 * math.pi) if angle is None else float(angle)
        dx, dy = mrad * math.cos(a), mrad * math.sin(a)
        self.offset[2 * (mirror - 1):2 * mirror] += np.array([dx, dy]) * 1e-3
        return mirror, dx, dy

    def clear_knocks(self):
        self.offset[:] = 0

    # ── photodiodes ──────────────────────────────────────────────────────────
    def volts(self):
        """Noise-free TIA outputs (ref, out) without dark offsets."""
        if not self.laser:
            return 0.0, 0.0
        s = self.sens
        p_ap = s.laser_mw * 1e-3 * self.optics.throughput * s.attenuator
        ref = p_ap * s.bs_reflect * s.responsivity_a_w * s.tia_ohms[0]
        out = ref * self.path_ratio() * float(self.coupling())
        return min(ref, s.rail_v), min(out, s.rail_v)

    def raw_volts(self, n=1):
        """What the ADC sees, averaged over n samples per channel: dark offsets
        and noise included (the GUI simulator reports these)."""
        s = self.sens
        out = []
        for v, dark in zip(self.volts(), s.dark_v):
            v_all = v + dark
            fsr = next((f for f in reversed(FSRS) if v_all < 0.9 * f), FSRS[0])
            lsb = fsr / 32768
            sigma = math.sqrt(s.noise_v ** 2 + lsb ** 2 / 12 + (s.laser_noise * v) ** 2) / math.sqrt(max(n, 1))
            out.append(min(max(v_all + self.rng.normal(0, sigma), 0.0), s.rail_v))
        return tuple(out)

    def read(self, seconds=0.02):
        """A photodiode reading averaged over `seconds`, dark offsets subtracted
        (as after PD DARK). Advances the clock."""
        s = self.sens
        n = max(1, int(round(seconds * s.samples_per_s)))
        self.advance(seconds + s.latency_s)
        self.n_reads += 1
        ref, out = (v - d for v, d in zip(self.raw_volts(n), s.dark_v))
        ratio = out / ref if self.laser and ref > 0.010 else None
        return Reading(ref, out, ratio)


def randomized(mech: Mechanics, optics: Optics, rng, spread=1.0):
    """A plausible 'real' bench around the design values: lever arms, distances,
    play, crosstalk and motor directions all a bit different, as the aligner
    will meet them."""
    s = spread
    m = replace(mech,
                lever_mm=tuple(float(v) for v in np.asarray(mech.lever_mm) * (1 + s * rng.uniform(-0.1, 0.1, 4))),
                crosstalk=tuple(float(v) for v in s * rng.uniform(-0.03, 0.03, 2)),
                backlash_deg=tuple(float(v) for v in rng.uniform(0.4, 1.6, 4)),
                signs=tuple(int(v) for v in rng.choice([-1, 1], 4)))
    o = replace(optics,
                aperture_to_m1_mm=optics.aperture_to_m1_mm + s * rng.uniform(-5, 5),
                m1_to_m2_mm=optics.m1_to_m2_mm + s * rng.uniform(-5, 5),
                m2_to_lens_mm=optics.m2_to_lens_mm + s * rng.uniform(-5, 5))
    return m, o
