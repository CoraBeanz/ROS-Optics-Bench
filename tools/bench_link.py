"""Links to the bench controller: the ESP32 over USB serial, or a simulator.

A link has send(line), close(), and a queue `rx` of received lines. Callables
in `listeners` also get every line as it arrives, on the link's own thread
(the GUI feeds the aligner this way, without waiting for its UI timer). The
firmware's protocol is documented in firmware/optics_bench/src/comms/protocol.h.
Used by tools/test_gui.py and the ROS 2 driver in host/ros2_ws.

SerialLink needs pyserial and SimLink needs numpy (it runs the bench twin in
tools/bench_twin); each imports what it needs when it is opened.
"""

from __future__ import annotations

import dataclasses
import math
import queue
import random
import threading
import time

AXES = ["M1X", "M1Y", "M2X", "M2Y"]


def parse_fields(line):
    """'STATUS LASER=0 POS=1,2' -> {'LASER': '0', 'POS': '1,2'}"""
    out = {}
    for tok in line.split()[1:]:
        if "=" in tok:
            k, v = tok.split("=", 1)
            out[k] = v
    return out


def ints(csv):
    return [int(float(x)) for x in csv.split(",")]


def _emit(link, line):
    """Queue a received line and hand it to the link's listeners."""
    link.rx.put(line)
    for fn in list(link.listeners):
        fn(line)


class SerialLink:
    def __init__(self, port, baud=115200):
        self.rx = queue.Queue()
        self.listeners = []
        import serial

        self.ser = serial.Serial()
        self.ser.port = port
        self.ser.baudrate = baud
        self.ser.timeout = 0.1
        # Keep DTR/RTS low so opening the port doesn't reset the ESP32 on
        # boards with the auto-reset circuit.
        self.ser.dtr = False
        self.ser.rts = False
        self.ser.open()
        self.lock = threading.Lock()
        self.alive = True
        self.thread = threading.Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        buf = b""
        while self.alive:
            try:
                # Wait (up to the 0.1 s timeout) for the first byte only, then take
                # whatever has arrived: read(256) would hold every reply until 256
                # bytes or the timeout.
                chunk = self.ser.read(self.ser.in_waiting or 1)
            except Exception as e:  # unplugged
                _emit(self, f"LINK_ERROR {e}")
                self.alive = False
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                _emit(self, raw.decode(errors="replace").strip())

    def send(self, line):
        with self.lock:
            self.ser.write((line + "\n").encode())

    def close(self):
        self.alive = False
        try:
            self.ser.close()
        except Exception:
            pass


class SimLink:
    """Stand-in for the firmware so the GUI can be tried without hardware.
    Constant-speed moves, no ramps, drivers always answer. The light comes
    from the bench twin (tools/bench_twin): the adjusters follow the motors
    through a little play, the mirrors steer the beam into the chosen fiber,
    and the photodiodes read what couples. The best position is hidden a
    little way from zero; SIM commands knock a mirror, switch fiber or show
    where the peak is."""

    USTEPS_PER_REV = 3200
    FSRS = (4.096, 2.048, 1.024, 0.512, 0.256)
    FIBERS = ("mm50", "smf28", "sm630")
    SIM_HELP = "OK SIM KNOCK <M1|M2> [mrad] | PEAK | FIBER <mm50|smf28|sm630> | RESET"

    def __init__(self, fiber="mm50", seed=None):
        try:
            import numpy as np
            from bench_twin import Bench, Mechanics, Optics, randomized
        except ImportError as e:
            raise RuntimeError(f"the simulator needs numpy ({e}): py -3 -m pip install -r tools/requirements.txt")
        # An as-built bench: lever arms, distances, play and motor directions a
        # little off the design values, as Align will find the real one
        mech, optics = randomized(Mechanics(), Optics(), np.random.default_rng(seed))
        self._twin_parts = (Bench, mech, optics)
        rng = random.Random(seed)
        # hidden best position: within 0.05 turn on M1 and 0.08 turn on M2
        self.peak = [rng.uniform(-160, 160), rng.uniform(-160, 160), rng.uniform(-250, 250), rng.uniform(-250, 250)]
        self.fiber = None
        self.twin = None
        self._set_fiber(fiber, seed)
        self.stream_hz = 0.0
        self.next_stream = 0.0
        self.last_pd = time.monotonic()      # a PD line reports the mean of the samples since the last one
        self.dark = (0.0, 0.0)
        self.have_dark = False
        self.dark_done_at = None
        self.dark_laser = False
        self.fixed_fsr = None
        self.rx = queue.Queue()
        self.listeners = []
        self._events = []                    # lines a command causes after its reply (EVT DONE on STOP)
        self.lock = threading.Lock()
        n = len(AXES)
        self.pos = [0.0] * n
        self.zero = [0.0] * n                # physical position of each reported 0 (ZERO, SETPOS)
        self.tgt = [0] * n
        self.lo = [-3 * self.USTEPS_PER_REV] * n
        self.hi = [3 * self.USTEPS_PER_REV] * n
        self.rpm = [30.0] * n
        self.acc = [120.0] * n
        self.ma = [350] * n
        self.en = [False] * n
        self.held = [False] * n              # ENABLE: no auto-release until DISABLE
        self.still_since = [0.0] * n
        self.jog_deadline = [None] * n
        self.limited = [False] * n
        self.laser = False
        self.alive = True
        _emit(self, "BOOT optics_bench sim")
        _emit(self, "READY")
        threading.Thread(target=self._tick, daemon=True).start()

    def _set_fiber(self, fiber, seed=None):
        bench_cls, mech, optics = self._twin_parts
        old = self.twin
        self.twin = bench_cls(dataclasses.replace(optics, fiber=fiber), mech, peak_usteps=self.peak, seed=seed)
        if old is not None:            # keep the motors, the play and any knocks
            self.twin.offset[:] = old.offset
            self.twin.motor, self.twin.adjuster = old.motor.copy(), old.adjuster.copy()
        self.fiber = fiber

    def _tick(self):
        last = time.monotonic()
        while self.alive:
            time.sleep(0.02)
            now = time.monotonic()
            dt, last = now - last, now
            out = []                         # sent after the lock is released
            with self.lock:
                for i in range(len(AXES)):
                    if self.jog_deadline[i] and now > self.jog_deadline[i]:
                        self.jog_deadline[i] = None
                        self.tgt[i] = round(self.pos[i])
                    d = self.tgt[i] - self.pos[i]
                    if d == 0:
                        if self.en[i] and not self.held[i] and now - self.still_since[i] >= 0.5:
                            self.en[i] = False      # firmware AUTO_RELEASE after RELEASE_DELAY_MS
                        continue
                    self.still_since[i] = now
                    step = self.rpm[i] / 60 * self.USTEPS_PER_REV * dt
                    self.pos[i] = self.tgt[i] if abs(d) <= step else self.pos[i] + step * (1 if d > 0 else -1)
                    self._sync_twin()
                    if self.pos[i] == self.tgt[i]:
                        p = self.tgt[i]
                        at = self.limited[i] and (p <= self.lo[i] or p >= self.hi[i])
                        self.limited[i] = False
                        self.jog_deadline[i] = None
                        out.append(f"EVT DONE {AXES[i]} POS={p}" + (" LIMIT" if at else ""))
                if self.dark_done_at and now >= self.dark_done_at:
                    self.dark_done_at = None
                    self.dark = self._pd_raw()
                    self.have_dark = True
                    self.laser = self.dark_laser
                    out.append(f"OK PD DARK REF={self.dark[0]:.6f} OUT={self.dark[1]:.6f}")
                if self.stream_hz and now >= self.next_stream and not self.dark_done_at:
                    self.next_stream = now + 1 / self.stream_hz
                    out.append(self._pd_line())
            for line in out:
                _emit(self, line)

    def _sync_twin(self):
        self.twin.set_motor([p + z for p, z in zip(self.pos, self.zero)])

    def _pd_raw(self, n=32):
        """TIA voltages (ref, out) averaged over n ADC samples per channel,
        dark offsets and noise included."""
        self.twin.laser = self.laser
        return self.twin.raw_volts(n)

    def _fsr(self, v):
        if self.fixed_fsr:
            return self.fixed_fsr
        return next((f for f in reversed(self.FSRS) if v < 0.9 * f), self.FSRS[0])

    def _pd_line(self):
        now = time.monotonic()
        n = max(1, round((now - self.last_pd) * self.twin.sens.samples_per_s))
        self.last_pd = now
        raw = self._pd_raw(n)
        ref, out = (raw[k] - self.dark[k] if self.have_dark else raw[k] for k in (0, 1))
        ratio = f"{out / ref:.6f}" if self.laser and ref > 0.010 else "-"
        return (f"PD REF={ref:.6f} OUT={out:.6f} RATIO={ratio} FSR={self._fsr(raw[0]):.3f},{self._fsr(raw[1]):.3f} "
                f"N={n},{n} DARK={int(self.have_dark)} LASER={int(self.laser)}")

    def _pd(self, a):
        sub = (a[0] or "").upper()
        if not sub:
            return self._pd_line()
        if sub == "STREAM":
            hz = 0.0 if (a[1] or "").upper() == "OFF" else float(a[1])
            if not 0 <= hz <= 50:
                return "ERR PD STREAM takes OFF or 0-50 Hz"
            self.stream_hz, self.next_stream = hz, time.monotonic()
            return f"OK PD STREAM={hz:.1f}"
        if sub == "DARK":
            if (a[1] or "").upper() == "CLEAR":
                self.have_dark, self.dark = False, (0.0, 0.0)
                return "OK PD DARK CLEARED"
            if self.dark_done_at:
                return "ERR PD DARK is already running"
            self.dark_laser, self.laser = self.laser, False
            self.dark_done_at = time.monotonic() + 0.12
            return None
        if sub == "RANGE":
            v = (a[1] or "").upper()
            if v == "AUTO":
                self.fixed_fsr = None
                return "OK PD RANGE=AUTO"
            if v and float(v) in self.FSRS:
                self.fixed_fsr = float(v)
                return f"OK PD RANGE={self.fixed_fsr:.3f}"
            return "ERR PD RANGE takes AUTO, 4.096, 2.048, 1.024, 0.512 or 0.256"
        return "ERR PD takes no argument, STREAM, DARK or RANGE"

    def _axis(self, tok, allow_all=False):
        if tok is None:
            raise ValueError("missing axis")
        t = tok.upper()
        if allow_all and t == "ALL":
            return list(range(len(AXES)))
        if t in AXES:
            return [AXES.index(t)]
        if t.isdigit() and 1 <= int(t) <= len(AXES):
            return [int(t) - 1]
        raise ValueError(f"unknown axis {tok}")

    def _start(self, i, target, jog=False):
        c = max(self.lo[i], min(self.hi[i], target))
        self.limited[i] = c != target or jog
        self.en[i] = True
        self.still_since[i] = time.monotonic()
        self.tgt[i] = c
        return c != target

    def send(self, line):
        with self.lock:
            self._events = []
            try:
                reply = self._handle(line.split())
            except (ValueError, IndexError) as e:
                reply = f"ERR {e}"
            events, self._events = self._events, []
        for l in ([reply] if reply else []) + events:
            _emit(self, l)

    def _handle(self, t):
        if not t:
            return None
        c = t[0].upper()
        a = t[1:] + [None, None, None]
        csv = lambda f: ",".join(str(f(i)) for i in range(len(AXES)))
        moving = lambda i: round(self.pos[i]) != self.tgt[i]
        if c == "PING":
            return "OK PONG"
        if c == "STATUS":
            return (f"STATUS LASER={int(self.laser)} POS={csv(lambda i: round(self.pos[i]))} "
                    f"TGT={csv(lambda i: self.tgt[i])} MOV={csv(lambda i: int(moving(i)))} "
                    f"EN={csv(lambda i: int(self.en[i]))} DRV={csv(lambda i: 1)}")
        if c == "INFO":
            return (f"INFO FW=sim AXES={','.join(AXES)} USTEPS_PER_REV={self.USTEPS_PER_REV} "
                    f"MIN={csv(lambda i: self.lo[i])} MAX={csv(lambda i: self.hi[i])} "
                    f"RPM={csv(lambda i: self.rpm[i])} ACCEL={csv(lambda i: self.acc[i])} "
                    f"MA={csv(lambda i: self.ma[i])} MAX_RPM=120.0 MAX_MA=420 "
                    f"ABS_LIMIT={8 * self.USTEPS_PER_REV} TRUSTED=1 TRUST=1,1,1,1 ADC=1 PD_RF=47000,47000 "
                    f"PD_RESP=0.40 slots=sim")
        if c == "PD":
            return self._pd(a)
        if c == "LASER":
            if a[0] and self.dark_done_at:
                return "ERR PD DARK is switching the laser, try again"
            if a[0]:
                self.laser = a[0].upper() == "ON"
            return f"OK LASER={int(self.laser)}"
        if c in ("MOVE", "GOTO"):
            i = self._axis(a[0])[0]
            v = int(a[1])
            clamped = self._start(i, self.tgt[i] + v if c == "MOVE" else v)
            return f"OK {c} {AXES[i]} TGT={self.tgt[i]}" + (" CLAMPED" if clamped else "")
        if c == "JOG":
            i = self._axis(a[0])[0]
            d = 1 if a[1] == "+" else -1
            if self.jog_deadline[i] is None or (self.tgt[i] >= self.pos[i]) != (d > 0):
                self._start(i, self.hi[i] if d > 0 else self.lo[i], jog=True)
            self.jog_deadline[i] = time.monotonic() + 0.4
            return None
        if c in ("STOP", "HALT"):
            for i in self._axis(a[0] or "ALL", True):
                was_moving = self.pos[i] != self.tgt[i]
                self.tgt[i] = round(self.pos[i])
                self.pos[i] = self.tgt[i]
                self.jog_deadline[i] = None
                if was_moving:              # the firmware reports where a stopped move ended
                    p = self.tgt[i]
                    at = self.limited[i] and (p <= self.lo[i] or p >= self.hi[i])
                    self.limited[i] = False
                    self._events.append(f"EVT DONE {AXES[i]} POS={p}" + (" LIMIT" if at else ""))
            self._sync_twin()
            return f"OK {c}"
        if c == "ZERO":             # renames the position; nothing moves
            for i in self._axis(a[0], True):
                self.zero[i] += self.pos[i]
                self.pos[i] = self.tgt[i] = 0
            return "OK ZERO"
        if c == "SETPOS":
            i = self._axis(a[0])[0]
            self.zero[i] += self.pos[i] - int(a[1])
            self.pos[i] = self.tgt[i] = int(a[1])
            return f"OK SETPOS {AXES[i]} POS={a[1]}"
        if c == "SIM":
            return self._sim(a)
        if c == "LIMITS":
            lo, hi = int(a[1]), int(a[2])
            if lo > hi or lo < -8 * self.USTEPS_PER_REV or hi > 8 * self.USTEPS_PER_REV:
                return "ERR limits out of range"
            for i in self._axis(a[0], True):
                self.lo[i], self.hi[i] = lo, hi
            return f"OK LIMITS MIN={lo} MAX={hi}"
        if c in ("SPEED", "ACCEL", "CURRENT"):
            v = float(a[1])
            if not math.isfinite(v) or v <= 0:      # the firmware refuses nan and inf too
                return "ERR CURRENT needs mA" if c == "CURRENT" else f"ERR {c} needs a positive number"
            for i in self._axis(a[0], True):
                if c == "SPEED":
                    self.rpm[i] = min(v, 120.0)
                elif c == "ACCEL":
                    self.acc[i] = v
                else:
                    self.ma[i] = int(min(v, 420))
            return f"OK {c}={v}"
        if c in ("ENABLE", "DISABLE"):
            for i in self._axis(a[0], True):
                self.en[i] = self.held[i] = c == "ENABLE"
                self.still_since[i] = time.monotonic()
                if c == "DISABLE":
                    self.tgt[i] = round(self.pos[i])
            return f"OK {c}"
        if c == "DRV":
            i = self._axis(a[0])[0]
            return f"OK DRV {AXES[i]} (simulator: no driver)"
        if c == "REPROBE":
            return "OK REPROBE DRV=1,1,1,1 slots=sim"
        if c == "SAVE":
            return "OK SAVE"
        return f"ERR unknown command {c}"

    def _sim(self, a):
        """Simulator-only commands (the firmware answers ERR unknown command)."""
        sub = (a[0] or "").upper()
        if sub == "KNOCK":
            mirror = {"M1": 1, "1": 1, "M2": 2, "2": 2}.get((a[1] or "").upper())
            if mirror is None:
                return "ERR SIM KNOCK takes M1 or M2 and an optional size in mrad"
            m, dx, dy = self.twin.knock(mirror, float(a[2]) if a[2] else random.uniform(0.5, 2.0))
            return f"OK SIM KNOCK M{m} tilt X={dx:+.2f} Y={dy:+.2f} mrad"
        if sub == "PEAK":
            best = self.twin.peak_motor()
            pos = ",".join(str(round(best[i] - self.zero[i])) for i in range(len(AXES)))
            now = float(self.twin.coupling() / self.twin.best_coupling())
            return (f"OK SIM PEAK POS={pos} (each axis arriving moving +) NOW={now:.1%} of best, "
                    f"best ratio {self.twin.peak_ratio():.3f} ({self.fiber})")
        if sub == "FIBER":
            f = (a[1] or "").lower()
            if f not in self.FIBERS:
                return "ERR SIM FIBER takes " + ", ".join(self.FIBERS)
            self._set_fiber(f)
            return f"OK SIM FIBER={f}"
        if sub == "RESET":
            self.twin.clear_knocks()
            return "OK SIM RESET (knocks cleared)"
        return self.SIM_HELP

    def close(self):
        self.alive = False
