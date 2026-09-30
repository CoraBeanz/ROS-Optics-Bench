"""Paraxial optics of the bench: laser, aperture, two steering mirrors, lens, fiber.

Lengths are in mm and angles in radians. The beam is described at the lens by
its offset from the lens axis and its angle to it, for each transverse axis:
x (horizontal, in the plane of the Z-fold) and y (vertical). A beam state is
the 4-vector (x, theta_x, y, theta_y); every function here also takes a stack
of them (shape (..., 4)) so many positions can be scored at once.

Single-mode coupling is the overlap integral of the laser field with the
fiber's mode. It is worked out in the aperture plane, where the laser field is
known exactly (an elliptical Gaussian cut off by the printed aperture): the
fiber mode is carried back there through the lens and free space as a Gaussian
beam, and the mirror misalignment shows up as a shift and a tilt of that mode.
That keeps the aperture's hard edge, the elliptical beam and the diffraction
between the aperture and the lens in the answer.

Multimode coupling is geometric: the share of the focused spot that lands in
the core at an angle the fiber accepts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

import numpy as np


@dataclass(frozen=True)
class Fiber:
    kind: str                 # "sm" Gaussian mode, "gi" graded-index multimode, "si" step-index
    label: str
    mfd_um: float = 0.0       # sm: mode field diameter at 635 nm
    core_um: float = 0.0      # gi / si
    na: float = 0.0           # gi / si
    clad_um: float = 125.0


FIBERS = {
    "sm630": Fiber("sm", "single-mode 630HP (Thorlabs P1-630A-FC)", mfd_um=4.2),
    "smf28": Fiber("si", "SMF-28 practice cable (several modes at 635 nm, rough)", core_um=8.2, na=0.14),
    "mm50": Fiber("gi", "50/125 graded-index multimode", core_um=50.0, na=0.20),
}


@dataclass(frozen=True)
class Optics:
    """Design values from the bench layout. Distances follow the beam."""
    wavelength_mm: float = 635e-6
    # Laser 1/e^2 radii. Ryan measured the beam at about 7 mm wide by 3 mm tall.
    beam_radius_mm: Tuple[float, float] = (3.5, 1.5)
    aperture_mm: Optional[float] = 2.0        # printed aperture after the laser; None = no aperture
    aperture_to_m1_mm: float = 115.0          # aperture 15 mm after the laser, M1 130 mm after it
    m1_to_m2_mm: float = 150.0
    m2_to_lens_mm: float = 310.0
    # Irises left in the beam: (distance after M2, diameter). Phase 2 removes
    # iris 1 and keeps iris 2 open to 3 mm as a baffle.
    irises: Tuple[Tuple[float, float], ...] = ((260.0, 3.0),)
    lens_f_mm: float = 8.0
    lens_ca_mm: float = 5.0                   # clear aperture of the asphere (check the part)
    focus_mm: float = 0.0                     # fiber face distance from the lens focus (stage error)
    fiber: str = "sm630"
    # Light that lands on the cladding and still reaches the output photodiode
    # through a short patch cable, as a fraction of what hits the fiber face.
    halo: float = 0.002


SQRT2 = math.sqrt(2.0)


def _erf(x):
    """Abramowitz & Stegun 7.1.26 (error < 1.5e-7), so numpy alone will do."""
    x = np.asarray(x, float)
    s = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    poly = ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t
    return s * (1.0 - poly * np.exp(-a * a))


def normal_cdf(z):
    return 0.5 * (1.0 + _erf(np.asarray(z, float) / SQRT2))


def _inside_ball(c, sig):
    """Share of an axis-aligned Gaussian (centre c, std sig, last axis = dims)
    inside the unit ball, using the local edge as a straight line. Good when
    the Gaussian is small next to the ball, which is the case here."""
    c = np.asarray(c, float)
    sig = np.asarray(sig, float)
    rho2 = np.sum(c * c, axis=-1)
    eps2 = 0.05 ** 2
    s_max2 = np.max(sig * sig, axis=-1)
    s_eff = np.sqrt((np.sum(c * c * sig * sig, axis=-1) + eps2 * s_max2) / (rho2 + eps2))
    return normal_cdf((1.0 - np.sqrt(rho2)) / s_eff)


def _abcd_mul(*ms):
    out = np.eye(2)
    for m in ms:
        out = out @ m
    return out


def _space(d):
    return np.array([[1.0, d], [0.0, 1.0]])


def _lens(f):
    return np.array([[1.0, 0.0], [-1.0 / f, 1.0]])


class OpticalModel:
    def __init__(self, p: Optional[Optics] = None):
        self.p = p = p or Optics()
        self.fiber = FIBERS[p.fiber] if isinstance(p.fiber, str) else p.fiber
        lam = p.wavelength_mm
        self.k = 2 * math.pi / lam
        wx, wy = p.beam_radius_mm
        self.l2 = p.m2_to_lens_mm                      # M2 to lens
        self.l1 = p.m1_to_m2_mm + self.l2              # M1 to lens
        self.d_ap = p.aperture_to_m1_mm + self.l1      # aperture to lens

        # Fiber mode (single-mode) carried back to the aperture plane. The
        # system from the aperture to the fiber face is free space, the lens,
        # then f + focus of free space; the mode has its waist on the face.
        if self.fiber.kind == "sm":
            self.w_fiber = self.fiber.mfd_um * 1e-3 / 2
            zr = math.pi * self.w_fiber ** 2 / lam
            (a, b), (c, d) = _abcd_mul(_space(p.lens_f_mm + p.focus_mm), _lens(p.lens_f_mm), _space(self.d_ap))
            q_f = 1j * zr
            q_ap = (d * q_f - b) / (a - c * q_f)
            self._c = 1j * self.k / (2 * np.conj(q_ap))    # conj(mode) = exp(c r^2)
            self.mode_radius_ap = math.sqrt(-lam / (math.pi * (1 / q_ap).imag))
            # the same mode at the lens, collimated: useful to compare with the beam
            self.mode_radius_lens = lam * p.lens_f_mm / (math.pi * self.w_fiber)

        # Quadrature over the aperture disk (polar Gauss-Legendre). Dense
        # enough for the fastest tilt fringe that still couples any light.
        self.aperture_radius = None if p.aperture_mm is None else p.aperture_mm / 2
        if self.aperture_radius is not None:
            r_ap = self.aperture_radius
            t_max = self._max_tilt()
            n_phi = max(48, int(math.ceil(2.5 * self.k * t_max * r_ap)) + 16)
            n_r = max(24, n_phi // 2)
            xg, wg = np.polynomial.legendre.leggauss(n_r)
            r = r_ap * (xg + 1) / 2
            wr = wg * r_ap / 2 * r
            phi = 2 * math.pi * (np.arange(n_phi) + 0.5) / n_phi
            rr, pp = np.meshgrid(r, phi)
            ww = np.broadcast_to(wr * (2 * math.pi / n_phi), rr.shape)
            self._x = (rr * np.cos(pp)).ravel()
            self._y = (rr * np.sin(pp)).ravel()
            e = np.exp(-self._x ** 2 / wx ** 2 - self._y ** 2 / wy ** 2)
            w = ww.ravel()
            self._we = w * e
            self._p_in = float(np.sum(w * e * e))
            self.throughput = self._p_in / (math.pi * wx * wy / 2)
            self.beam_radius_eq = (2 * math.sqrt(np.sum(w * e * e * self._x ** 2) / self._p_in),
                                   2 * math.sqrt(np.sum(w * e * e * self._y ** 2) / self._p_in))
        else:
            self.throughput = 1.0
            self.beam_radius_eq = (wx, wy)

        self.peak = float(self.coupling(np.zeros(4)))

    # ── geometry ─────────────────────────────────────────────────────────────
    def _max_tilt(self):
        """Beam angle past which single-mode coupling is below e^-64."""
        if self.fiber.kind == "sm":
            return 8 * self.w_fiber / self.p.lens_f_mm
        return 0.0

    def at_fiber(self, s):
        """Centroid offset (dx, dy) on the fiber face and angle (ax, ay) into it."""
        s = np.asarray(s, float)
        f, dz = self.p.lens_f_mm, self.p.focus_mm
        x, tx, y, ty = s[..., 0], s[..., 1], s[..., 2], s[..., 3]
        return ((f + dz) * tx - dz * x / f, (f + dz) * ty - dz * y / f, tx - x / f, ty - y / f)

    def spot(self):
        """1/e^2 radii (x, y) of the focused spot on the fiber face, mm."""
        lam, f, dz = self.p.wavelength_mm, self.p.lens_f_mm, self.p.focus_mm
        return tuple(math.hypot(lam * f / (math.pi * w), w * dz / f) for w in self.beam_radius_eq)

    # ── coupling ─────────────────────────────────────────────────────────────
    def coupling(self, s):
        """Share of the power leaving the aperture that is guided by the fiber
        (plus cladding light), before path losses. s: beam state(s) at the lens."""
        s = np.asarray(s, float)
        if self.fiber.kind == "sm":
            core = self._single_mode(s)
        else:
            core = self._geometric(s)
        return self._stops(s) * (core + self.p.halo * self._halo(s))

    def _single_mode(self, s):
        x, tx, y, ty = s[..., 0], s[..., 1], s[..., 2], s[..., 3]
        # The fiber mode as seen from the aperture plane: offset p, tilted by -theta
        px = -x + self.d_ap * tx
        py = -y + self.d_ap * ty
        if self.aperture_radius is None:
            return self._sm_analytic(px, tx, self.p.beam_radius_mm[0]) * \
                   self._sm_analytic(py, ty, self.p.beam_radius_mm[1])
        shape = px.shape
        px, py, tx, ty = (np.ravel(v)[:, None] for v in (px, py, tx, ty))
        arg = self._c * ((self._x - px) ** 2 + (self._y - py) ** 2) + 1j * self.k * (tx * self._x + ty * self._y)
        overlap = np.exp(arg) @ self._we
        eta = np.abs(overlap) ** 2 / (self._p_in * math.pi * self.mode_radius_ap ** 2 / 2)
        # Past the fastest fringe the grid resolves, the true value is < e^-64
        too_steep = np.hypot(tx, ty)[:, 0] > self._max_tilt()
        eta = np.where(too_steep, 0.0, eta)
        return eta.reshape(shape)

    def _sm_analytic(self, p, t, w):
        """1-D overlap of exp(-x^2/w^2) with the shifted, tilted mode."""
        c = self._c
        a = 1 / w ** 2 - c
        b = -2 * c * p + 1j * self.k * t
        g = b * b / (4 * a) + c * p * p
        return 2 / (np.abs(a) * w * self.mode_radius_ap) * np.exp(2 * g.real)

    def _geometric(self, s):
        dx, dy, ax, ay = self.at_fiber(s)
        a = self.fiber.core_um * 1e-3 / 2
        na = self.fiber.na
        sx, sy = (w / 2 for w in self.spot())
        f = self.p.lens_f_mm
        tx, ty = (w / (2 * f) for w in self.beam_radius_eq)
        pos = np.stack([dx / a, dy / a], -1)
        ang = np.stack([ax / na, ay / na], -1)
        if self.fiber.kind == "gi":
            # Graded index: a ray is guided when (r/a)^2 + (angle/NA)^2 < 1
            return _inside_ball(np.concatenate([pos, ang], -1), [sx / a, sy / a, tx / na, ty / na])
        return _inside_ball(pos, [sx / a, sy / a]) * _inside_ball(ang, [tx / na, ty / na])

    def _halo(self, s):
        dx, dy, _, _ = self.at_fiber(s)
        rc = self.fiber.clad_um * 1e-3 / 2
        sx, sy = (w / 2 for w in self.spot())
        return _inside_ball(np.stack([dx / rc, dy / rc], -1), [sx / rc, sy / rc])

    def _stops(self, s):
        """Transmission of the iris and the lens rim for the (equivalent Gaussian) beam."""
        x, tx, y, ty = s[..., 0], s[..., 1], s[..., 2], s[..., 3]
        sx, sy = (w / 2 for w in self.beam_radius_eq)
        t = np.ones(np.shape(x))
        stops = [(self.l2 - after_m2, dia) for after_m2, dia in self.p.irises]
        if self.p.lens_ca_mm:
            stops.append((0.0, self.p.lens_ca_mm))
        for back, dia in stops:
            r = dia / 2
            t = t * _inside_ball(np.stack([(x - back * tx) / r, (y - back * ty) / r], -1), [sx / r, sy / r])
        return t
