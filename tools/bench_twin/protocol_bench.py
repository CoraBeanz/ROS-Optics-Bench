"""The bench interface align.py needs, over the firmware's serial protocol.

Works with anything that takes command lines and hands back reply lines: the
real ESP32 (bench_link.SerialLink) or the simulator (bench_link.SimLink).
The caller passes every received line to feed(); the aligner runs in its own
thread and blocks here until the replies it needs arrive.

    move_to: GOTO for each axis whose target changed, then wait for EVT DONE
    read:    PD (starts a fresh average), wait, PD again (the average since)

start() turns PD STREAM off, so every PD line after it is a reply.
"""

from __future__ import annotations

import queue
import threading
import time

import numpy as np

from .bench import AXES, Reading


class Aborted(Exception):
    pass


def _fields(line):
    return dict(tok.split("=", 1) for tok in line.split()[1:] if "=" in tok)


class ProtocolBench:
    def __init__(self, send, timeout_s=20.0):
        self.send = send
        self.timeout_s = timeout_s
        self.lines = queue.Queue()
        self.abort = threading.Event()
        self.t0 = time.monotonic()
        self.motor = None
        self.n_moves = 0
        self.n_reads = 0
        self._motion = None

    def feed(self, line):
        self.lines.put(line)

    @property
    def clock(self):
        return time.monotonic() - self.t0

    @property
    def position(self):
        return self.motor.copy()

    def _wait(self, match, what):
        """Next received line for which match(line) is not None."""
        deadline = time.monotonic() + self.timeout_s
        while True:
            if self.abort.is_set():
                raise Aborted()
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no {what} from the controller")
            try:
                line = self.lines.get(timeout=min(0.05, left))
            except queue.Empty:
                continue
            if line.startswith("ERR"):
                raise RuntimeError(line)
            got = match(line)
            if got is not None:
                return got

    def _sleep(self, s):
        if self.abort.wait(s):
            raise Aborted()

    def command(self, line, reply_prefix):
        """Send a command and wait for the reply that starts with reply_prefix."""
        self.send(line)
        return self._wait(lambda l: l if l.startswith(reply_prefix) else None, reply_prefix)

    def start(self):
        """Stop PD streaming, drop old lines and learn where the motors are,
        once any move still running (a nudge just before Align) has ended."""
        self.command("PD STREAM OFF", "OK PD STREAM")     # streamed lines sent before it are gone now
        while not self.lines.empty():
            self.lines.get_nowait()
        deadline = time.monotonic() + self.timeout_s
        while True:
            f = _fields(self.command("STATUS", "STATUS"))
            if "1" not in f.get("MOV", "").split(","):
                break
            if time.monotonic() > deadline:
                raise TimeoutError("the motors are still moving")
            self._sleep(0.05)
        self.motor = np.array([float(v) for v in f["POS"].split(",")])

    def move_to(self, target, speed_rpm=None, accel_rpm_s=None):
        if speed_rpm and (speed_rpm, accel_rpm_s) != self._motion:
            self.command(f"SPEED ALL {speed_rpm:g}", "OK SPEED")
            if accel_rpm_s:
                self.command(f"ACCEL ALL {accel_rpm_s:g}", "OK ACCEL")
            self._motion = (speed_rpm, accel_rpm_s)
        target = np.round(np.asarray(target, float)).astype(int)
        pending = set()
        for i, ax in enumerate(AXES):
            if target[i] != int(self.motor[i]):
                self.send(f"GOTO {ax} {target[i]}")
                pending.add(ax)
        while pending:
            line = self._wait(lambda l: l if l.startswith(("EVT DONE", "OK GOTO")) else None, "EVT DONE")
            ax = line.split()[2]
            if ax not in pending:
                continue
            i = AXES.index(ax)
            if line.startswith("EVT DONE"):
                self.motor[i] = float(_fields(line)["POS"])
                pending.discard(ax)
            elif float(_fields(line)["TGT"]) == self.motor[i]:
                pending.discard(ax)          # clamped to where it already is: no move, no EVT DONE
        self.n_moves += 1

    def read(self, seconds=0.02):
        is_pd = lambda l: l if l.startswith("PD ") else None
        self.send("PD")
        self._wait(is_pd, "PD reading")
        self._sleep(seconds)
        self.send("PD")
        f = _fields(self._wait(is_pd, "PD reading"))
        self.n_reads += 1
        ratio = None if f.get("RATIO", "-") == "-" else float(f["RATIO"])
        return Reading(float(f["REF"]), float(f["OUT"]), ratio)
