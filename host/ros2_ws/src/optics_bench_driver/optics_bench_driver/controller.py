"""The bench controller (the ESP32, or the simulator) as Python calls, without ROS.

The driver node wraps this; keeping it free of rclpy lets it be tested and
used on its own. It owns one link (tools/bench_link.py): a thread hands every
received line to the listeners, and request() sends a line and waits for the
reply that belongs to it. The protocol is in
firmware/optics_bench/src/comms/protocol.h.

Requests are sent one at a time, so an ERR line answers the request that is
waiting. Auto-align (tools/bench_twin/align.py) runs over the same link
through bench_twin.protocol_bench.ProtocolBench, which sees every line too.
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import threading
import time
from typing import Callable, NamedTuple, Optional

from bench_link import AXES, ints, parse_fields

FIBERS = ("mm50", "smf28", "sm630")


class ControllerError(RuntimeError):
    pass


class Busy(ControllerError):
    pass


class Status(NamedTuple):
    laser: bool
    position: list
    target: list
    moving: list
    enabled: list
    driver_ok: list


class PdReading(NamedTuple):
    ref_v: float
    out_v: float
    ratio: Optional[float]
    ref_range_v: float
    out_range_v: float
    ref_samples: int
    out_samples: int
    dark_subtracted: bool
    laser: bool


def parse_status(line) -> Status:
    f = parse_fields(line)
    pos, tgt, mov, en, drv = (ints(f[k]) for k in ("POS", "TGT", "MOV", "EN", "DRV"))
    return Status(f["LASER"] == "1", pos, tgt, [bool(v) for v in mov], [bool(v) for v in en],
                  [bool(v) for v in drv])


def parse_pd(line) -> PdReading:
    f = parse_fields(line)
    fsr = [float(v) for v in f.get("FSR", "0,0").split(",")]
    n = ints(f.get("N", "0,0"))
    ratio = None if f.get("RATIO", "-") == "-" else float(f["RATIO"])
    return PdReading(float(f["REF"]), float(f["OUT"]), ratio, fsr[0], fsr[1], n[0], n[1],
                     f.get("DARK") == "1", f.get("LASER") == "1")


def reply_matcher(line):
    """What the reply to a command line starts with, or None for a command the
    firmware answers only on error (JOG, a keep-alive)."""
    t = line.split()
    if not t:
        raise ControllerError("empty command")
    c = t[0].upper()
    sub = t[1].upper() if len(t) > 1 else ""
    if c == "JOG":
        return None
    if c == "PING":
        return "OK PONG"
    if c in ("STATUS", "INFO"):
        return c + " "
    if c == "PD":
        if not sub:
            return "PD "
        return "OK PD"          # STREAM, RANGE, DARK CLEAR, and PD DARK's reply when it finishes
    return "OK " + c


class Controller:
    def __init__(self, link, log: Callable[[str], None] = None):
        self.link = link
        self.log = log or (lambda text: None)
        self._listeners = []
        self._listeners_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._align_lock = threading.Lock()
        self._moves = 0                      # move_to calls in progress
        self._moves_lock = threading.Lock()
        self.aligning = False
        self.align_abort = None
        self.alive = True
        self.connected = False
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    # ── lines in ────────────────────────────────────────────────────────────
    def _pump(self):
        while self.alive:
            try:
                line = self.link.rx.get(timeout=0.1)
            except queue.Empty:
                continue
            if not line:
                continue
            if line.startswith("LINK_ERROR"):
                self.connected = False
                self.alive = False
            with self._listeners_lock:
                listeners = list(self._listeners)
            for fn in listeners:
                try:
                    fn(line)
                except Exception as e:          # a listener's bug must not stop the pump
                    self.log(f"listener error on {line!r}: {e}")

    def add_listener(self, fn):
        with self._listeners_lock:
            self._listeners.append(fn)
        return fn

    def remove_listener(self, fn):
        with self._listeners_lock:
            if fn in self._listeners:
                self._listeners.remove(fn)

    def close(self):
        self.alive = False
        if self.align_abort:
            self.align_abort.set()
        self.link.close()

    # ── requests ────────────────────────────────────────────────────────────
    def request(self, line, timeout=2.0):
        """Send one command line and return its reply. Raises ControllerError
        for an ERR reply or no reply within timeout."""
        prefix = reply_matcher(line)
        # The firmware answers JOG only on error. A PING right behind it fences
        # that error off: an ERR before OK PONG is the JOG's, not the next request's
        fence = prefix is None
        if fence:
            prefix = "OK PONG"
        got = queue.Queue()

        def listen(l):
            if l.startswith(prefix) or l.startswith("ERR"):
                got.put(l)

        with self._request_lock:
            self.add_listener(listen)
            try:
                self.link.send(line)
                if fence:
                    self.link.send("PING")
                try:
                    reply = got.get(timeout=timeout)
                    if fence and reply.startswith("ERR"):
                        got.get(timeout=timeout)     # its PONG, so a later PING doesn't take it
                except queue.Empty:
                    raise ControllerError(f"no reply to {line!r} within {timeout:g} s")
            finally:
                self.remove_listener(listen)
        self.connected = True
        if reply.startswith("ERR"):
            raise ControllerError(reply[4:])
        return "" if fence else reply

    def status(self) -> Status:
        return parse_status(self.request("STATUS"))

    def info(self) -> dict:
        return parse_fields(self.request("INFO"))

    def move_to(self, targets: dict, relative=False, speed_rpm=0.0, abort: threading.Event = None,
                timeout=300.0, on_progress=None):
        """Move axes ({'M2X': 100, ...}) and wait until they stop. Returns
        (positions of all four axes, {axis: stopped at a soft limit})."""
        targets = {self._axis(a): int(v) for a, v in targets.items()}
        with self._moves_lock:               # counted before the check, so align() sees it
            self._moves += 1
        try:
            if self.aligning:
                raise Busy("aligning: stop the alignment first")
            return self._move_to(targets, relative, speed_rpm, abort, timeout, on_progress)
        finally:
            with self._moves_lock:
                self._moves -= 1

    def _move_to(self, targets, relative, speed_rpm, abort, timeout, on_progress):
        if speed_rpm and speed_rpm > 0:
            self.request(f"SPEED ALL {speed_rpm:g}")
        done = queue.Queue()

        def listen(l):
            if l.startswith("EVT DONE"):
                done.put(l)

        self.add_listener(listen)
        try:
            pos = self.status().position
            pending, limited = set(), {}
            for ax, v in targets.items():
                i = AXES.index(ax)
                reply = self.request(f"{'MOVE' if relative else 'GOTO'} {ax} {v}")
                tgt = int(parse_fields(reply)["TGT"])
                limited[ax] = "CLAMPED" in reply.split()
                if tgt != pos[i]:
                    pending.add(ax)
            deadline = time.monotonic() + timeout
            last_progress = 0.0
            while pending:
                if abort is not None and abort.is_set():
                    for ax in pending:
                        self.request(f"STOP {ax}")
                    raise ControllerError("move cancelled")
                if time.monotonic() > deadline:
                    raise ControllerError(f"{', '.join(sorted(pending))} still moving after {timeout:g} s")
                try:
                    l = done.get(timeout=0.1)
                except queue.Empty:
                    if on_progress and time.monotonic() - last_progress > 0.2:
                        last_progress = time.monotonic()
                        on_progress(self.status().position)
                    continue
                ax = l.split()[2]
                if ax in pending:
                    pending.discard(ax)
                    limited[ax] = limited[ax] or l.split()[-1] == "LIMIT"
            return self.status().position, limited
        finally:
            self.remove_listener(listen)

    @staticmethod
    def _axis(a):
        a = str(a).upper()
        if a in AXES:
            return a
        if a.isdigit() and 1 <= int(a) <= len(AXES):
            return AXES[int(a) - 1]
        raise ControllerError(f"unknown axis {a}")

    # ── auto-align ──────────────────────────────────────────────────────────
    def align(self, fiber, calibration: "CalibrationStore", recalibrate=False, say=None, abort=None,
              pd_stream_hz=0.0):
        """Run bench_twin's aligner over the link. The first run for a fiber finds
        light and calibrates; later runs recover. Returns (Result, fraction of
        the calibrated peak)."""
        from bench_twin import Aligner, Bench, Optics, make_plan
        from bench_twin.protocol_bench import Aborted, ProtocolBench

        if fiber not in FIBERS:
            raise ControllerError(f"fiber must be one of {', '.join(FIBERS)}")
        if not self._align_lock.acquire(blocking=False):
            raise Busy("already aligning")
        self.aligning = True                 # set before the check, so move_to() sees it
        with self._moves_lock:
            moving = self._moves > 0
        if moving:
            self.aligning = False
            self._align_lock.release()
            raise Busy("a move is in progress: wait for it to finish or stop it")
        say = say or (lambda text: None)
        bench = ProtocolBench(self.link.send)
        if abort is not None:
            bench.abort = abort
        self.align_abort = bench.abort
        self.add_listener(bench.feed)
        restore = ["DISABLE ALL"]
        try:
            info = self.info()
            if any(self.status().moving):    # the aligner would start from a position mid-move
                restore = []                 # and DISABLE would halt whatever is moving them
                raise Busy("motors are moving: wait for them to stop")
            restore = [f"SPEED ALL {info['RPM'].split(',')[0]}", f"ACCEL ALL {info['ACCEL'].split(',')[0]}",
                       "DISABLE ALL"]
            # The simulator's calibration says nothing about the real bench (and
            # the other way round), so each keeps its own
            key = f"sim/{fiber}" if info.get("FW") == "sim" else fiber
            if recalibrate:
                calibration.forget(key)
            cal = calibration.get(key)
            plan = cal[0] if cal else make_plan(Bench(Optics(fiber=fiber)))
            bench.command("LASER ON", "OK LASER")
            bench.start()
            bench.command("ENABLE ALL", "OK ENABLE")     # stay energised between steps
            al = Aligner(bench, plan, say=say)
            if cal:
                al.good = cal[1]
                say(f"recovering ({fiber})")
                res = al.recover()
            else:
                say(f"first run for {fiber}: finding light, then calibrating")
                res = al.first_align()
                if res.ok:                   # light that calibrated plausibly; res.note says why not
                    calibration.put(key, al.plan, al.good)
                elif res.found:
                    say(f"not keeping this calibration: {res.note}")
            return res, (res.ratio / al.good if al.good > 0 else 0.0)
        except Aborted:
            raise ControllerError("alignment stopped")
        except (TimeoutError, RuntimeError) as e:
            raise ControllerError(f"alignment failed: {e}")
        finally:
            self.remove_listener(bench.feed)
            self.aligning = False
            self.align_abort = None
            self._align_lock.release()
            for line in restore + ([f"PD STREAM {pd_stream_hz:g}"] if pd_stream_hz else []):
                try:
                    self.request(line)
                except ControllerError as e:
                    self.log(f"after align, {line}: {e}")


class CalibrationStore:
    """The aligner's walk directions and peak ratio per fiber, kept in a JSON
    file so a restart doesn't need a new calibration."""

    def __init__(self, path=""):
        self.path = os.path.expanduser(path) if path else ""
        self._data = {}
        if self.path and os.path.isfile(self.path):
            try:
                with open(self.path) as f:
                    self._data = json.load(f)
            except (OSError, ValueError):    # a damaged file means no calibration, not a crash
                self._data = {}
            if not isinstance(self._data, dict):
                self._data = {}

    def get(self, fiber):
        from bench_twin import Plan

        d = self._data.get(fiber)
        if not d:
            return None
        try:
            plan = Plan(**{k: tuple(v) if isinstance(v, list) else v for k, v in d["plan"].items()})
            return plan, float(d["good"])
        except (KeyError, TypeError, ValueError, AttributeError):   # written by another version
            return None

    def put(self, fiber, plan, good):
        self._data[fiber] = {"plan": dataclasses.asdict(plan), "good": float(good),
                             "when": time.strftime("%Y-%m-%dT%H:%M:%S")}
        self._save()

    def forget(self, fiber):
        if self._data.pop(fiber, None) is not None:
            self._save()

    def _save(self):
        if not self.path:
            return
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self._data, f, indent=2)
        os.replace(tmp, self.path)
