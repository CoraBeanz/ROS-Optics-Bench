"""Checks for the bench twin and the aligner.

    py -3 -m unittest discover tools/tests

The optics checks compare against textbook results; the alignment checks run
knock-and-recover trials on simulated benches. The last test drives the
simulated controller (bench_link.SimLink, the one behind test_gui.py --sim) over
the serial protocol in real time (about 30 s).
"""

import dataclasses
import math
import os
import queue
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))

import numpy as np  # noqa: E402

from bench_twin import Aligner, Bench, Mechanics, OpticalModel, Optics, make_plan  # noqa: E402
from bench_twin.trials import run_trials  # noqa: E402

LAM = 635e-6


def matched(f=8.0, w_fiber=2.1e-3, **kw):
    """Optics whose laser beam is exactly the fiber mode seen from the lens,
    with the aperture plane at the lens's front focal point."""
    w = LAM * f / (math.pi * w_fiber)
    kw.setdefault("aperture_mm", None)
    return Optics(beam_radius_mm=(w, w), aperture_to_m1_mm=f - 460.0, irises=(), lens_ca_mm=0, halo=0,
                  lens_f_mm=f, **kw), w


class OpticsTest(unittest.TestCase):
    def test_matched_gaussian_couples_fully(self):
        o, _ = matched()
        self.assertAlmostEqual(OpticalModel(o).peak, 1.0, places=6)

    def test_spot_one_mode_radius_off_gives_one_over_e(self):
        o, _ = matched()
        m = OpticalModel(o)
        theta = 2.1e-3 / 8.0              # moves the focus by one mode radius
        self.assertAlmostEqual(float(m.coupling([0, theta, 0, 0])), math.exp(-1), places=4)

    def test_uniform_disk_matches_textbook(self):
        # A flat beam cut by a circular aperture into a Gaussian mode:
        # 2 (1 - exp(-b^2))^2 / b^2, best (81.5 %) at b = 1.12
        _, w = matched()
        for b in (0.8, 1.12, 1.5):
            o, _ = matched(aperture_mm=2 * b * w)
            o = dataclasses.replace(o, beam_radius_mm=(1e3, 1e3))
            expect = 2 * (1 - math.exp(-b * b)) ** 2 / (b * b)
            self.assertAlmostEqual(OpticalModel(o).peak, expect, places=5)

    def test_aperture_quadrature_matches_analytic(self):
        big = OpticalModel(Optics(beam_radius_mm=(1.2, 0.9), aperture_mm=12, irises=(), halo=0))
        none = OpticalModel(Optics(beam_radius_mm=(1.2, 0.9), aperture_mm=None, irises=(), halo=0))
        rng = np.random.default_rng(1)
        s = np.column_stack([rng.normal(0, 0.5, 20), rng.normal(0, 2e-4, 20),
                             rng.normal(0, 0.5, 20), rng.normal(0, 2e-4, 20)])
        np.testing.assert_allclose(big.coupling(s), none.coupling(s), atol=1e-9)

    def test_two_mm_aperture_is_near_the_best_choice(self):
        with_ap = OpticalModel(Optics()).peak
        without = OpticalModel(Optics(aperture_mm=None)).peak
        self.assertGreater(with_ap, 0.8)
        self.assertLess(without, 0.4)


class BenchTest(unittest.TestCase):
    def test_single_mode_valley(self):
        b = Bench(Optics())
        plan = make_plan(b)
        self.assertLess(plan.narrow[0], 40)                   # a couple of full steps
        self.assertGreater(plan.walk[0] / plan.narrow[0], 15)  # long thin valley
        self.assertAlmostEqual(plan.slope[0], -1.0, places=6)

    def test_play_holds_the_adjuster_on_a_short_reversal(self):
        b = Bench(Optics(), Mechanics(backlash_deg=(2.0,) * 4))
        b.set_motor([100, 0, 0, 0])
        before = b.adjuster.copy()
        b.set_motor([95, 0, 0, 0])                           # play is 2 deg = 17.8 microsteps
        np.testing.assert_array_equal(b.adjuster, before)
        b.set_motor([70, 0, 0, 0])
        self.assertLess(b.adjuster[0], before[0])

    def test_reading_at_the_peak(self):
        b = Bench(Optics(), seed=3)
        b.jump_to_peak()
        r = b.read(0.05)
        self.assertAlmostEqual(r.ratio, b.peak_ratio(), delta=0.01 * b.peak_ratio())
        b.laser = False
        self.assertIsNone(b.read().ratio)

    def test_knock_moves_the_peak(self):
        b = Bench(Optics(), seed=3)
        b.jump_to_peak()
        b.knock(1, 1.0)
        self.assertLess(float(b.coupling() / b.best_coupling()), 0.01)
        b.jump_to_peak()
        self.assertAlmostEqual(float(b.coupling() / b.best_coupling()), 1.0, places=6)


class AlignTest(unittest.TestCase):
    def test_single_mode_recovers(self):
        rs = run_trials(15, "sm630", seed=2)
        self.assertEqual(sum(r.ok for r in rs), len(rs))
        self.assertGreater(min(r.coupling for r in rs), 0.95)

    def test_multimode_recovers(self):
        rs = run_trials(10, "mm50", seed=2)
        self.assertEqual(sum(r.ok for r in rs), len(rs))

    def test_walking_beats_one_motor_at_a_time(self):
        walk = run_trials(15, "sm630", seed=4)
        naive = run_trials(15, "sm630", naive=True, seed=4)
        self.assertGreater(np.mean([r.coupling for r in walk]), np.mean([r.coupling for r in naive]))

    def test_calibration_finds_the_walk_direction(self):
        from bench_twin.trials import make_bench
        bench = make_bench("sm630", seed=6)
        bench.jump_to_peak()
        al = Aligner(bench, make_plan(Bench(Optics())))
        al.calibrate()
        # true slope: the M2 move that cancels an M1 move's beam angle
        k = bench._tilt_per_ustep * bench._gain
        for plane in (0, 1):
            true = -k[plane] / k[2 + plane]
            self.assertAlmostEqual(al.plan.slope[plane], true, delta=0.03 * abs(true))


class ProtocolTest(unittest.TestCase):
    def test_align_through_the_gui_simulator(self):
        from bench_link import AXES, SimLink
        from bench_twin.protocol_bench import ProtocolBench
        link = SimLink(fiber="mm50", seed=4)
        pb = ProtocolBench(link.send)
        alive = True

        def pump():
            while alive:
                try:
                    pb.feed(link.rx.get(timeout=0.05))
                except queue.Empty:
                    pass

        threading.Thread(target=pump, daemon=True).start()
        try:
            link.send("LASER ON")
            link.send("SPEED ALL 120")
            near = link.twin.peak_motor() + np.array([120, -90, -100, 140])
            for ax, p in zip(AXES, near):
                link.send(f"GOTO {ax} {round(p)}")
            time.sleep(0.5)
            pb.start()
            al = Aligner(pb, make_plan(Bench(Optics(fiber="mm50"))))
            self.assertTrue(al.first_align().ok)
            with link.lock:
                link.twin.knock(1, 0.8)
            res = al.recover()
            self.assertTrue(res.ok)
            self.assertGreater(float(link.twin.coupling() / link.twin.best_coupling()), 0.95)
        finally:
            alive = False
            link.close()


if __name__ == "__main__":
    unittest.main()
