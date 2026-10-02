"""The controller layer against the simulated controller (no ROS needed)."""

import time

import pytest

from optics_bench_driver.tools_path import add_tools_to_path

add_tools_to_path()

from bench_link import SimLink  # noqa: E402

from optics_bench_driver.controller import (  # noqa: E402
    CalibrationStore, Controller, ControllerError, parse_pd, reply_matcher,
)


def test_reply_matcher():
    assert reply_matcher("ping") == "OK PONG"
    assert reply_matcher("STATUS") == "STATUS "
    assert reply_matcher("PD") == "PD "
    assert reply_matcher("PD DARK") == "OK PD"
    assert reply_matcher("goto M1X 5") == "OK GOTO"
    assert reply_matcher("JOG M1X +") is None


def test_parse_pd():
    r = parse_pd("PD REF=1.200000 OUT=0.300000 RATIO=0.250000 FSR=2.048,0.512 N=12,12 DARK=1 LASER=1")
    assert r.ratio == 0.25 and r.ref_range_v == 2.048 and r.out_samples == 12 and r.dark_subtracted
    assert parse_pd("PD REF=0 OUT=0 RATIO=- FSR=4.096,4.096 N=1,1 DARK=0 LASER=0").ratio is None


@pytest.fixture
def ctl():
    c = Controller(SimLink(fiber="mm50", seed=3))
    yield c
    c.close()


def test_requests_and_errors(ctl):
    assert ctl.request("PING") == "OK PONG"
    assert ctl.request("LASER ON") == "OK LASER=1"
    assert ctl.status().laser
    with pytest.raises(ControllerError):
        ctl.request("GOTO M9X 3")


def test_move_to(ctl):
    ctl.request("SPEED ALL 120")
    pos, limited = ctl.move_to({"M1X": 400, "M2Y": -300})
    assert pos[0] == 400 and pos[3] == -300 and not any(limited.values())
    pos, _ = ctl.move_to({"M1X": -100}, relative=True)
    assert pos[0] == 300
    pos, limited = ctl.move_to({"M2X": 10 ** 6})          # clamped to the +3 turn soft limit
    assert pos[2] == 9600 and limited["M2X"]


def test_align_then_recover(ctl, tmp_path):
    store = CalibrationStore(str(tmp_path / "cal.json"))
    peak = ctl.link.twin.peak_motor()
    ctl.request("SPEED ALL 120")
    ctl.move_to({ax: round(p) + d for ax, p, d in zip(("M1X", "M1Y", "M2X", "M2Y"), peak, (120, -90, -100, 140))})
    t0 = time.monotonic()
    res, frac = ctl.align("mm50", store)
    assert res.found and res.ok, res
    assert store.get("mm50") is not None
    assert CalibrationStore(str(tmp_path / "cal.json")).get("mm50")[0] == store.get("mm50")[0]
    with ctl.link.lock:
        ctl.link.twin.knock(1, 0.8)
    res, frac = ctl.align("mm50", store)
    assert res.ok and frac > 0.9, (res, frac)
    assert float(ctl.link.twin.coupling() / ctl.link.twin.best_coupling()) > 0.95
    assert time.monotonic() - t0 < 300
