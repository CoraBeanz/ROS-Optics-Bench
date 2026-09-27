#!/usr/bin/env python3
"""Bench test panel for the optics bench: laser on/off and the four mirror motors.

Talks to firmware/optics_bench over USB serial (protocol in
firmware/optics_bench/src/comms/protocol.h).

    pip install pyserial
    python bench_gui.py            # pick the ESP32's COM port and Connect
    python bench_gui.py --sim      # no hardware: a simulated controller

Keyboard (when no text box has focus), one step of the selected size per press:
    Left/Right  M1X -/+      Down/Up  M1Y -/+
    A/D         M2X -/+      S/W      M2Y -/+
    L           laser on/off Esc      stop all motors
"""

import argparse
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk
from tkinter.scrolledtext import ScrolledText

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # the simulator still works without pyserial
    serial = None

AXES = ["M1X", "M1Y", "M2X", "M2Y"]
UM_PER_TURN = 254.0          # 100 TPI adjuster screw
POLL_MS = 150                # STATUS poll period
JOG_REPEAT_MS = 150          # JOG keep-alive period (firmware times out at 400 ms)

KEYS = {
    "Left": (0, -1), "Right": (0, 1), "Down": (1, -1), "Up": (1, 1),
    "a": (2, -1), "d": (2, 1), "s": (3, -1), "w": (3, 1),
}


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


# ─────────────────────────────────────────────────────────────────────────────
# Links: something with send(line), close(), and a queue of received lines.
# ─────────────────────────────────────────────────────────────────────────────

class SerialLink:
    def __init__(self, port, baud=115200):
        self.rx = queue.Queue()
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
                chunk = self.ser.read(256)
            except Exception as e:  # unplugged
                self.rx.put(f"LINK_ERROR {e}")
                self.alive = False
                return
            if not chunk:
                continue
            buf += chunk
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                self.rx.put(raw.decode(errors="replace").strip())

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
    """Rough stand-in for the firmware so the GUI can be tried without hardware.
    Constant-speed moves, no ramps, drivers always answer."""

    USTEPS_PER_REV = 3200

    def __init__(self):
        self.rx = queue.Queue()
        self.lock = threading.Lock()
        n = len(AXES)
        self.pos = [0.0] * n
        self.tgt = [0] * n
        self.lo = [-3 * self.USTEPS_PER_REV] * n
        self.hi = [3 * self.USTEPS_PER_REV] * n
        self.rpm = [30.0] * n
        self.acc = [120.0] * n
        self.ma = [350] * n
        self.en = [False] * n
        self.jog_deadline = [None] * n
        self.limited = [False] * n
        self.laser = False
        self.alive = True
        self.rx.put("BOOT optics_bench sim")
        self.rx.put("READY")
        threading.Thread(target=self._tick, daemon=True).start()

    def _tick(self):
        last = time.monotonic()
        while self.alive:
            time.sleep(0.02)
            now = time.monotonic()
            dt, last = now - last, now
            with self.lock:
                for i in range(len(AXES)):
                    if self.jog_deadline[i] and now > self.jog_deadline[i]:
                        self.jog_deadline[i] = None
                        self.tgt[i] = round(self.pos[i])
                    d = self.tgt[i] - self.pos[i]
                    if d == 0:
                        continue
                    step = self.rpm[i] / 60 * self.USTEPS_PER_REV * dt
                    self.pos[i] = self.tgt[i] if abs(d) <= step else self.pos[i] + step * (1 if d > 0 else -1)
                    if self.pos[i] == self.tgt[i]:
                        p = self.tgt[i]
                        at = self.limited[i] and (p <= self.lo[i] or p >= self.hi[i])
                        self.limited[i] = False
                        self.jog_deadline[i] = None
                        self.rx.put(f"EVT DONE {AXES[i]} POS={p}" + (" LIMIT" if at else ""))

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
        self.tgt[i] = c
        return c != target

    def send(self, line):
        with self.lock:
            try:
                reply = self._handle(line.split())
            except (ValueError, IndexError) as e:
                reply = f"ERR {e}"
        if reply:
            self.rx.put(reply)

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
                    f"ABS_LIMIT={8 * self.USTEPS_PER_REV} TRUSTED=1 slots=sim")
        if c == "LASER":
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
                self.tgt[i] = round(self.pos[i])
                self.pos[i] = self.tgt[i]
                self.jog_deadline[i] = None
            return f"OK {c}"
        if c == "ZERO":
            for i in self._axis(a[0], True):
                self.pos[i] = self.tgt[i] = 0
            return "OK ZERO"
        if c == "SETPOS":
            i = self._axis(a[0])[0]
            self.pos[i] = self.tgt[i] = int(a[1])
            return f"OK SETPOS {AXES[i]} POS={a[1]}"
        if c == "LIMITS":
            lo, hi = int(a[1]), int(a[2])
            if lo > hi or lo < -8 * self.USTEPS_PER_REV or hi > 8 * self.USTEPS_PER_REV:
                return "ERR limits out of range"
            for i in self._axis(a[0], True):
                self.lo[i], self.hi[i] = lo, hi
            return f"OK LIMITS MIN={lo} MAX={hi}"
        if c in ("SPEED", "ACCEL", "CURRENT"):
            v = float(a[1])
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
                self.en[i] = c == "ENABLE"
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

    def close(self):
        self.alive = False


# ─────────────────────────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────────────────────────

STEP_SIZES = [  # label, turns
    ("1 microstep", None),
    ("1 full step (1.3 um)", 1 / 200),
    ("10 steps (12.7 um)", 10 / 200),
    ("1/10 turn (25 um)", 0.1),
    ("1/4 turn (64 um)", 0.25),
    ("1 turn (254 um)", 1.0),
]


class AxisRow:
    def __init__(self, app, parent, i, row):
        self.app, self.i, self.name = app, i, AXES[i]
        pad = dict(padx=3, pady=2)

        self.name_lbl = ttk.Label(parent, text=self.name, font=("TkDefaultFont", 11, "bold"))
        self.name_lbl.grid(row=row, column=0, **pad)
        self.drv_lbl = tk.Label(parent, text="●", fg="grey", font=("TkDefaultFont", 12))
        self.drv_lbl.grid(row=row, column=1, **pad)
        self.pos_lbl = ttk.Label(parent, text="-", width=9, anchor="e", font=("TkFixedFont", 11))
        self.pos_lbl.grid(row=row, column=2, **pad)
        self.turn_lbl = ttk.Label(parent, text="-", width=19, anchor="e", font=("TkFixedFont", 10))
        self.turn_lbl.grid(row=row, column=3, **pad)

        jog = ttk.Frame(parent)
        jog.grid(row=row, column=4, **pad)
        self._hold_button(jog, "◀◀", -1).pack(side="left")
        ttk.Button(jog, text="◀", width=3, command=lambda: app.nudge(i, -1)).pack(side="left")
        ttk.Button(jog, text="▶", width=3, command=lambda: app.nudge(i, 1)).pack(side="left")
        self._hold_button(jog, "▶▶", 1).pack(side="left")

        go = ttk.Frame(parent)
        go.grid(row=row, column=5, **pad)
        self.goto_var = tk.StringVar(value="0")
        ttk.Entry(go, textvariable=self.goto_var, width=7).pack(side="left")
        ttk.Button(go, text="Go (turns)", command=self.goto).pack(side="left")
        ttk.Button(go, text="To 0", width=5, command=lambda: app.send(f"GOTO {self.name} 0")).pack(side="left")
        ttk.Button(go, text="Set 0", width=5, command=self.zero).pack(side="left")

        lim = ttk.Frame(parent)
        lim.grid(row=row, column=6, **pad)
        self.lo_var = tk.StringVar()
        self.hi_var = tk.StringVar()
        ttk.Entry(lim, textvariable=self.lo_var, width=5).pack(side="left")
        ttk.Label(lim, text="to").pack(side="left")
        ttk.Entry(lim, textvariable=self.hi_var, width=5).pack(side="left")
        ttk.Button(lim, text="Set", width=4, command=self.set_limits).pack(side="left")

        self.en_var = tk.BooleanVar()
        ttk.Checkbutton(parent, variable=self.en_var, command=self.toggle_enable).grid(row=row, column=7, **pad)
        ttk.Button(parent, text="Diag", width=5, command=lambda: app.send(f"DRV {self.name}")).grid(
            row=row, column=8, **pad)

    def _hold_button(self, parent, text, direction):
        b = ttk.Button(parent, text=text, width=3)
        b.bind("<ButtonPress-1>", lambda e: self.app.start_jog(self.i, direction))
        b.bind("<ButtonRelease-1>", lambda e: self.app.stop_jog(self.i))
        return b

    def goto(self):
        try:
            turns = float(self.goto_var.get())
        except ValueError:
            return self.app.log(f"{self.name}: target must be a number of turns", "err")
        self.app.send(f"GOTO {self.name} {round(turns * self.app.usteps_per_rev)}")

    def zero(self):
        if messagebox.askyesno("Set zero", f"Call the current {self.name} position 0?\n"
                               "The soft limits move with it."):
            self.app.send(f"ZERO {self.name}")
            self.app.send("INFO")

    def set_limits(self):
        try:
            lo, hi = float(self.lo_var.get()), float(self.hi_var.get())
        except ValueError:
            return self.app.log(f"{self.name}: limits must be numbers of turns", "err")
        u = self.app.usteps_per_rev
        self.app.send(f"LIMITS {self.name} {round(lo * u)} {round(hi * u)}")
        self.app.send("INFO")

    def toggle_enable(self):
        self.app.send(f"{'ENABLE' if self.en_var.get() else 'DISABLE'} {self.name}")

    def show(self, pos, tgt, moving, en, drv):
        u = self.app.usteps_per_rev
        self.pos_lbl.config(text=str(pos))
        self.turn_lbl.config(text=f"{pos / u:+.4f} t {pos / u * UM_PER_TURN:+7.1f}um")
        self.name_lbl.config(foreground="#0a7" if moving else "")
        self.drv_lbl.config(fg="#0a0" if drv else "#d00")
        if self.en_var.get() != bool(en):
            self.en_var.set(bool(en))

    def show_limits(self, lo, hi):
        u = self.app.usteps_per_rev
        self.lo_var.set(f"{lo / u:g}")
        self.hi_var.set(f"{hi / u:g}")


class BenchApp:
    def __init__(self, root, sim=False):
        self.root = root
        self.link = None
        self.sim = sim
        self.usteps_per_rev = 3200
        self.laser_on = False
        self.jog_timers = {}
        root.title("Optics bench test panel")
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_connection_bar()
        self._build_controls()
        self._build_axes()
        self._build_log()
        self._bind_keys()
        self.set_connected(False)
        self.root.after(50, self.drain)

    # ── layout ──────────────────────────────────────────────────────────────
    def _build_connection_bar(self):
        bar = ttk.Frame(self.root, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="Port").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_box = ttk.Combobox(bar, textvariable=self.port_var, width=28)
        self.port_box.pack(side="left", padx=4)
        ttk.Button(bar, text="Refresh", command=self.refresh_ports).pack(side="left")
        self.conn_btn = ttk.Button(bar, text="Connect", command=self.toggle_connection)
        self.conn_btn.pack(side="left", padx=4)
        self.info_lbl = ttk.Label(bar, text="")
        self.info_lbl.pack(side="left", padx=10)
        self.refresh_ports()

    def _build_controls(self):
        f = ttk.Frame(self.root, padding=(6, 0))
        f.pack(fill="x")

        self.laser_btn = tk.Button(f, text="LASER OFF", width=12, height=2, font=("TkDefaultFont", 11, "bold"),
                                   command=self.toggle_laser)
        self.laser_btn.pack(side="left", padx=(0, 10))

        s = ttk.LabelFrame(f, text="All motors", padding=4)
        s.pack(side="left", fill="y")
        self.rpm_var = tk.StringVar(value="30")
        self.acc_var = tk.StringVar(value="120")
        self.ma_var = tk.StringVar(value="350")
        for col, (label, var) in enumerate([("Speed RPM", self.rpm_var), ("Accel RPM/s", self.acc_var),
                                            ("Current mA", self.ma_var)]):
            ttk.Label(s, text=label).grid(row=0, column=col, padx=3)
            ttk.Entry(s, textvariable=var, width=7).grid(row=1, column=col, padx=3)
        ttk.Button(s, text="Apply", command=self.apply_settings).grid(row=1, column=3, padx=3)
        ttk.Button(s, text="Enable all", command=lambda: self.send("ENABLE ALL")).grid(row=0, column=4, padx=3)
        ttk.Button(s, text="Disable all", command=lambda: self.send("DISABLE ALL")).grid(row=1, column=4, padx=3)

        st = ttk.LabelFrame(f, text="Step size (◀ ▶ and keys)", padding=4)
        st.pack(side="left", fill="y", padx=10)
        self.step_var = tk.StringVar(value=STEP_SIZES[2][0])
        ttk.Combobox(st, textvariable=self.step_var, values=[s[0] for s in STEP_SIZES],
                     state="readonly", width=20).pack()

        self.stop_btn = tk.Button(f, text="STOP ALL (Esc)", bg="#c62828", fg="white", activebackground="#e53935",
                                  font=("TkDefaultFont", 12, "bold"), height=2, command=self.stop_all)
        self.stop_btn.pack(side="right")

    def _build_axes(self):
        f = ttk.LabelFrame(self.root, text="Mirror motors (positive = firmware + direction)", padding=6)
        f.pack(fill="x", padx=6, pady=6)
        for col, h in enumerate(["Axis", "Drv", "Microsteps", "Turns / screw travel", "Jog  (◀◀ ▶▶ hold)",
                                 "Go to", "Soft limits (turns)", "On", ""]):
            ttk.Label(f, text=h, foreground="#555").grid(row=0, column=col, padx=3)
        self.rows = [AxisRow(self, f, i, i + 1) for i in range(len(AXES))]

    def _build_log(self):
        f = ttk.Frame(self.root, padding=6)
        f.pack(fill="both", expand=True)
        self.log_box = ScrolledText(f, height=12, font=("TkFixedFont", 9), state="disabled")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("err", foreground="#c62828")
        self.log_box.tag_config("warn", foreground="#b26a00")
        self.log_box.tag_config("tx", foreground="#1565c0")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="Command").pack(side="left")
        self.cmd_var = tk.StringVar()
        e = ttk.Entry(row, textvariable=self.cmd_var)
        e.pack(side="left", fill="x", expand=True, padx=4)
        e.bind("<Return>", lambda ev: self.send_raw())
        ttk.Button(row, text="Send", command=self.send_raw).pack(side="left")

    def _bind_keys(self):
        for key, (i, d) in KEYS.items():
            self.root.bind(f"<KeyPress-{key}>", lambda e, i=i, d=d: self._key(e, lambda: self.nudge(i, d)))
        self.root.bind("<KeyPress-l>", lambda e: self._key(e, self.toggle_laser))
        self.root.bind("<Escape>", lambda e: self.stop_all())

    def _key(self, event, action):
        if isinstance(event.widget, (tk.Entry, ttk.Entry, ttk.Combobox)):
            return
        action()

    # ── connection ──────────────────────────────────────────────────────────
    def refresh_ports(self):
        ports = ["Simulator"]
        if serial is not None:
            ports = [f"{p.device} - {p.description}" for p in serial.tools.list_ports.comports()] + ports
        self.port_box["values"] = ports
        if self.sim:
            self.port_var.set("Simulator")
        elif not self.port_var.get() or self.port_var.get() not in ports:
            self.port_var.set(ports[0])

    def toggle_connection(self):
        if self.link:
            self.disconnect()
            return
        choice = self.port_var.get()
        try:
            if choice == "Simulator":
                self.link = SimLink()
            else:
                if serial is None:
                    raise RuntimeError("pyserial is not installed: pip install pyserial")
                self.link = SerialLink(choice.split(" - ")[0])
        except Exception as e:
            self.link = None
            messagebox.showerror("Connect", str(e))
            return
        self.set_connected(True)
        self.log(f"connected to {choice}")
        self.send("INFO")
        self.poll()

    def disconnect(self):
        if self.link:
            try:
                self.link.send("STOP ALL")
                self.link.send("LASER OFF")
                time.sleep(0.05)
            except Exception:
                pass
            self.link.close()
            self.link = None
            self.log("disconnected")
        self.set_connected(False)

    def set_connected(self, on):
        self.conn_btn.config(text="Disconnect" if on else "Connect")
        state = "normal" if on else "disabled"
        self.laser_btn.config(state=state)
        self.stop_btn.config(state=state)
        if not on:
            self.info_lbl.config(text="not connected")
            self.show_laser(False)

    def on_close(self):
        self.disconnect()
        self.root.destroy()

    # ── sending ─────────────────────────────────────────────────────────────
    def send(self, line, quiet=False):
        if not self.link:
            return
        try:
            self.link.send(line)
        except Exception as e:
            self.log(f"send failed: {e}", "err")
            self.disconnect()
            return
        if not quiet:
            self.log(f"> {line}", "tx")

    def send_raw(self):
        line = self.cmd_var.get().strip()
        if line:
            self.send(line)
            self.cmd_var.set("")

    def poll(self):
        if not self.link:
            return
        self.send("STATUS", quiet=True)
        self.root.after(POLL_MS, self.poll)

    def step_usteps(self):
        for label, turns in STEP_SIZES:
            if label == self.step_var.get():
                return 1 if turns is None else max(1, round(turns * self.usteps_per_rev))
        return 1

    def nudge(self, i, direction):
        self.send(f"MOVE {AXES[i]} {direction * self.step_usteps()}")

    def start_jog(self, i, direction):
        self.stop_jog(i, send_stop=False)
        self.log(f"> JOG {AXES[i]} {'+' if direction > 0 else '-'} (held)", "tx")

        def repeat():
            self.send(f"JOG {AXES[i]} {'+' if direction > 0 else '-'}", quiet=True)
            self.jog_timers[i] = self.root.after(JOG_REPEAT_MS, repeat)
        repeat()

    def stop_jog(self, i, send_stop=True):
        t = self.jog_timers.pop(i, None)
        if t:
            self.root.after_cancel(t)
            if send_stop:
                self.send(f"STOP {AXES[i]}")

    def stop_all(self):
        for i in list(self.jog_timers):
            self.stop_jog(i, send_stop=False)
        self.send("STOP ALL")

    def toggle_laser(self):
        self.send(f"LASER {'OFF' if self.laser_on else 'ON'}")

    def apply_settings(self):
        try:
            rpm, acc, ma = float(self.rpm_var.get()), float(self.acc_var.get()), int(self.ma_var.get())
        except ValueError:
            return self.log("speed, accel and current must be numbers", "err")
        self.send(f"SPEED ALL {rpm:g}")
        self.send(f"ACCEL ALL {acc:g}")
        self.send(f"CURRENT ALL {ma}")
        self.send("INFO")

    # ── receiving ───────────────────────────────────────────────────────────
    def drain(self):
        if self.link:
            try:
                while True:
                    self.handle(self.link.rx.get_nowait())
            except queue.Empty:
                pass
        self.root.after(30, self.drain)

    def handle(self, line):
        if not line:
            return
        head = line.split()[0]
        if head == "STATUS":
            f = parse_fields(line)
            try:
                pos, tgt, mov, en, drv = (ints(f[k]) for k in ("POS", "TGT", "MOV", "EN", "DRV"))
            except (KeyError, ValueError):
                return
            for i, r in enumerate(self.rows):
                r.show(pos[i], tgt[i], mov[i], en[i], drv[i])
            self.show_laser(f.get("LASER") == "1")
            return
        if head == "INFO":
            f = parse_fields(line)
            try:
                self.usteps_per_rev = int(f["USTEPS_PER_REV"])
                for r, lo, hi in zip(self.rows, ints(f["MIN"]), ints(f["MAX"])):
                    r.show_limits(lo, hi)
                self.rpm_var.set(f["RPM"].split(",")[0])
                self.acc_var.set(f["ACCEL"].split(",")[0])
                self.ma_var.set(f["MA"].split(",")[0])
                self.info_lbl.config(text=f"firmware {f.get('FW', '?')}   {self.usteps_per_rev} microsteps/turn   "
                                          f"{f.get('slots', '')}")
            except (KeyError, ValueError):
                pass
            if f.get("TRUSTED") == "0":
                self.log("positions may be off: power was lost during a move", "warn")
        elif head == "READY":
            self.send("INFO")  # the board rebooted
        elif head == "LINK_ERROR":
            self.log(line, "err")
            self.disconnect()
            return
        if head == "OK" and "LASER=" in line:
            self.show_laser(line.rstrip().endswith("LASER=1"))
        tag = "err" if head == "ERR" else "warn" if head == "WARN" else None
        self.log(line, tag)

    def show_laser(self, on):
        self.laser_on = on
        self.laser_btn.config(text="LASER ON" if on else "LASER OFF",
                              bg="#d32f2f" if on else "#e0e0e0", fg="white" if on else "black",
                              activebackground="#e53935" if on else "#eeeeee")

    def log(self, text, tag=None):
        self.log_box.config(state="normal")
        self.log_box.insert("end", text + "\n", tag or ())
        if int(self.log_box.index("end-1c").split(".")[0]) > 2000:
            self.log_box.delete("1.0", "500.0")
        self.log_box.see("end")
        self.log_box.config(state="disabled")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", action="store_true", help="select the simulated controller")
    args = ap.parse_args()
    root = tk.Tk()
    BenchApp(root, sim=args.sim)
    root.mainloop()


if __name__ == "__main__":
    main()
