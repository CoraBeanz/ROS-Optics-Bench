#!/usr/bin/env python3
"""Bench test panel for the optics bench: laser on/off and the four mirror motors.

Talks to firmware/optics_bench over USB serial (protocol in
firmware/optics_bench/src/comms/protocol.h).

    pip install -r requirements.txt    # PySide6, pyserial
    python test_gui.py                 # pick the ESP32's COM port and Connect
    python test_gui.py --sim           # no hardware: a simulated controller

Keyboard (when no text box has focus), one step of the selected size per press:
    Left/Right  M1X -/+      Down/Up  M1Y -/+
    A/D         M2X -/+      S/W      M2Y -/+
    L           laser on/off Esc      stop all motors
"""

import argparse
import html
import queue
import sys
import threading
import time

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPalette, QTextCursor
from PySide6.QtWidgets import (
    QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPushButton, QSpinBox, QStatusBar, QTextEdit, QVBoxLayout,
    QWidget,
)

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # the simulator still works without pyserial
    serial = None

AXES = ["M1X", "M1Y", "M2X", "M2Y"]
UM_PER_TURN = 254.0          # 100 TPI adjuster screw
POLL_MS = 150                # STATUS poll period
JOG_REPEAT_MS = 150          # JOG keep-alive period (firmware times out at 400 ms)

K = Qt.Key
KEYS = {
    K.Key_Left: (0, -1), K.Key_Right: (0, 1), K.Key_Down: (1, -1), K.Key_Up: (1, 1),
    K.Key_A: (2, -1), K.Key_D: (2, 1), K.Key_S: (3, -1), K.Key_W: (3, 1),
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

# Console colours, same set as the KineoLabs hardware test panel
LOG_COLORS = {None: "#ddd", "err": "#ff4136", "warn": "#ff851b", "tx": "#4a9eff", "info": "#888"}

MONO = "Consolas"


class StatusDot(QLabel):
    """Small rounded badge: green / red / orange / grey."""
    COLORS = {"ok": "#2ecc40", "bad": "#ff4136", "warn": "#ff851b", "off": "#555"}

    def __init__(self, text="-"):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.set_state("off", text)

    def set_state(self, state, text=None):
        if text is not None:
            self.setText(text)
        self.setStyleSheet(
            f"QLabel {{ background: {self.COLORS.get(state, '#555')}; color: black; font-weight: bold;"
            f" border-radius: 8px; padding: 2px 10px; }}")


def colored_button(text, bg, hover, pad="6px 18px"):
    b = QPushButton(text)
    b.setStyleSheet(
        f"QPushButton {{ background: {bg}; color: white; font-weight: bold;"
        f" padding: {pad}; border-radius: 4px; }}"
        f"QPushButton:hover {{ background: {hover}; }}"
        "QPushButton:disabled { background: #444; color: #888; }")
    return b


def turns_box(lo=-8.0, hi=8.0, decimals=4, step=0.1):
    b = QDoubleSpinBox()
    b.setRange(lo, hi)
    b.setDecimals(decimals)
    b.setSingleStep(step)
    b.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    b.setAlignment(Qt.AlignmentFlag.AlignRight)
    return b


class AxisRow:
    def __init__(self, app, grid, i, row):
        self.app, self.i, self.name = app, i, AXES[i]

        self.name_lbl = QLabel(self.name)
        self.name_lbl.setFont(QFont(MONO, 11, QFont.Weight.Bold))
        grid.addWidget(self.name_lbl, row, 0)
        self.drv_dot = StatusDot("DRV")
        self.drv_dot.setToolTip("TMC2209 answered on the UART (green) or not (red: moves refused)")
        grid.addWidget(self.drv_dot, row, 1)
        self.pos_lbl = QLabel("-")
        self.pos_lbl.setFont(QFont(MONO, 11, QFont.Weight.Bold))
        self.pos_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.pos_lbl.setMinimumWidth(80)
        grid.addWidget(self.pos_lbl, row, 2)
        self.turn_lbl = QLabel("-")
        self.turn_lbl.setFont(QFont(MONO, 10))
        self.turn_lbl.setStyleSheet("color: #999;")
        self.turn_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.turn_lbl.setMinimumWidth(170)
        grid.addWidget(self.turn_lbl, row, 3)

        jog = QHBoxLayout()
        jog.setSpacing(2)
        for text, tip, direction, hold in (
            ("◀◀", "Hold: jog -", -1, True),
            ("◀", "Nudge - by the selected step", -1, False),
            ("▶", "Nudge + by the selected step", 1, False),
            ("▶▶", "Hold: jog +", 1, True),
        ):
            b = QPushButton(text)
            b.setFixedWidth(40)
            b.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            if hold:
                b.pressed.connect(lambda d=direction: app.start_jog(i, d))
                b.released.connect(lambda: app.stop_jog(i))
            else:
                b.clicked.connect(lambda _c=False, d=direction: app.nudge(i, d))
            jog.addWidget(b)
        grid.addLayout(jog, row, 4)

        go = QHBoxLayout()
        go.setSpacing(4)
        self.goto_box = turns_box()
        self.goto_box.setFixedWidth(70)
        self.goto_box.lineEdit().returnPressed.connect(self.goto)
        go.addWidget(self.goto_box)
        b = QPushButton("Go (turns)")
        b.clicked.connect(self.goto)
        go.addWidget(b)
        b = QPushButton("To 0")
        b.clicked.connect(lambda: app.send(f"GOTO {self.name} 0"))
        go.addWidget(b)
        b = QPushButton("Set 0")
        b.setToolTip("Call the current position 0; the soft limits move with it")
        b.clicked.connect(self.zero)
        go.addWidget(b)
        grid.addLayout(go, row, 5)

        lim = QHBoxLayout()
        lim.setSpacing(4)
        self.lo_box = turns_box(decimals=3)
        self.hi_box = turns_box(decimals=3)
        for box in (self.lo_box, self.hi_box):
            box.setFixedWidth(60)
        lim.addWidget(self.lo_box)
        lim.addWidget(QLabel("to"))
        lim.addWidget(self.hi_box)
        b = QPushButton("Set")
        b.clicked.connect(self.set_limits)
        lim.addWidget(b)
        grid.addLayout(lim, row, 6)

        self.en_chk = QCheckBox()
        self.en_chk.setToolTip("Driver enabled (coils powered)")
        self.en_chk.clicked.connect(self.toggle_enable)
        grid.addWidget(self.en_chk, row, 7, alignment=Qt.AlignmentFlag.AlignCenter)
        b = QPushButton("Diag")
        b.setToolTip("DRV: TMC2209 status (current, StealthChop, overtemperature, short, open load)")
        b.clicked.connect(lambda: app.send(f"DRV {self.name}"))
        grid.addWidget(b, row, 8)

    def goto(self):
        self.app.send(f"GOTO {self.name} {round(self.goto_box.value() * self.app.usteps_per_rev)}")

    def zero(self):
        answer = QMessageBox.question(self.app, "Set zero", f"Call the current {self.name} position 0?\n"
                                      "The soft limits move with it.")
        if answer == QMessageBox.StandardButton.Yes:
            self.app.send(f"ZERO {self.name}")
            self.app.send("INFO")

    def set_limits(self):
        lo, hi = self.lo_box.value(), self.hi_box.value()
        if lo > hi:
            return self.app.log(f"{self.name}: the lower limit is above the upper one", "err")
        u = self.app.usteps_per_rev
        self.app.send(f"LIMITS {self.name} {round(lo * u)} {round(hi * u)}")
        self.app.send("INFO")

    def toggle_enable(self):
        self.app.send(f"{'ENABLE' if self.en_chk.isChecked() else 'DISABLE'} {self.name}")

    def show(self, pos, tgt, moving, en, drv):
        u = self.app.usteps_per_rev
        self.pos_lbl.setText(str(pos))
        self.turn_lbl.setText(f"{pos / u:+.4f} t {pos / u * UM_PER_TURN:+7.1f} um")
        self.name_lbl.setStyleSheet("color: #2ecc40;" if moving else "")
        self.drv_dot.set_state("ok" if drv else "bad")
        if self.en_chk.isChecked() != bool(en):
            self.en_chk.setChecked(bool(en))

    def show_limits(self, lo, hi):
        u = self.app.usteps_per_rev
        self.lo_box.setValue(lo / u)
        self.hi_box.setValue(hi / u)

    def clear(self):
        self.pos_lbl.setText("-")
        self.turn_lbl.setText("-")
        self.name_lbl.setStyleSheet("")
        self.drv_dot.set_state("off")


class TestApp(QMainWindow):
    def __init__(self, sim=False):
        super().__init__()
        self.link = None
        self.sim = sim
        self.usteps_per_rev = 3200
        self.laser_on = False
        self.jog_timers = {}
        self.setWindowTitle("Optics bench test panel")
        self.resize(1180, 720)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.addLayout(self._build_connection_bar())
        outer.addLayout(self._build_controls())
        outer.addWidget(self._build_axes())
        outer.addWidget(self._build_console(), stretch=1)
        self.setStatusBar(QStatusBar())

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_MS)
        self.poll_timer.timeout.connect(lambda: self.send("STATUS", quiet=True))
        self.drain_timer = QTimer(self)
        self.drain_timer.setInterval(30)
        self.drain_timer.timeout.connect(self.drain)
        self.drain_timer.start()

        QApplication.instance().installEventFilter(self)
        self.set_connected(False)

    # ── layout ──────────────────────────────────────────────────────────────
    def _build_connection_bar(self):
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Port:</b>"))
        self.port_box = QComboBox()
        self.port_box.setMinimumWidth(280)
        bar.addWidget(self.port_box)
        b = QPushButton("↻")
        b.setFixedWidth(34)
        b.setToolTip("Rescan serial ports")
        b.clicked.connect(self.refresh_ports)
        bar.addWidget(b)
        self.conn_btn = QPushButton("Connect")
        self.conn_btn.clicked.connect(self.toggle_connection)
        bar.addWidget(self.conn_btn)
        self.conn_dot = StatusDot("DISCONNECTED")
        bar.addWidget(self.conn_dot)
        self.info_lbl = QLabel("")
        self.info_lbl.setStyleSheet("color: #999;")
        bar.addWidget(self.info_lbl)
        bar.addStretch()
        self.refresh_ports()
        return bar

    def _build_controls(self):
        row = QHBoxLayout()

        self.laser_btn = QPushButton("LASER OFF")
        self.laser_btn.setMinimumSize(140, 52)
        self.laser_btn.setToolTip("Laser on/off (L)")
        self.laser_btn.clicked.connect(self.toggle_laser)
        row.addWidget(self.laser_btn)

        s = QGroupBox("All motors")
        g = QGridLayout(s)
        self.rpm_box = QDoubleSpinBox()
        self.rpm_box.setRange(0.1, 1000)
        self.rpm_box.setDecimals(1)
        self.rpm_box.setValue(30)
        self.acc_box = QDoubleSpinBox()
        self.acc_box.setRange(0.1, 100000)
        self.acc_box.setDecimals(1)
        self.acc_box.setValue(120)
        self.ma_box = QSpinBox()
        self.ma_box.setRange(0, 2000)
        self.ma_box.setSingleStep(10)
        self.ma_box.setValue(350)
        for col, (label, box) in enumerate([("Speed RPM", self.rpm_box), ("Accel RPM/s", self.acc_box),
                                            ("Current mA", self.ma_box)]):
            g.addWidget(QLabel(label), 0, col)
            g.addWidget(box, 1, col)
        b = QPushButton("Apply")
        b.setToolTip("SPEED, ACCEL and CURRENT for all four motors (the firmware clamps to its maxima)")
        b.clicked.connect(self.apply_settings)
        g.addWidget(b, 1, 3)
        b = QPushButton("Enable all")
        b.clicked.connect(lambda: self.send("ENABLE ALL"))
        g.addWidget(b, 0, 4)
        b = QPushButton("Disable all")
        b.clicked.connect(lambda: self.send("DISABLE ALL"))
        g.addWidget(b, 1, 4)
        row.addWidget(s)

        st = QGroupBox("Step size (◀ ▶ and keys)")
        v = QVBoxLayout(st)
        self.step_box = QComboBox()
        self.step_box.addItems([label for label, _ in STEP_SIZES])
        self.step_box.setCurrentIndex(2)
        v.addWidget(self.step_box)
        row.addWidget(st)

        row.addStretch()
        self.stop_btn = colored_button("STOP ALL  (Esc)", "#c0392b", "#e74c3c", pad="14px 24px")
        self.stop_btn.clicked.connect(self.stop_all)
        row.addWidget(self.stop_btn)
        return row

    def _build_axes(self):
        box = QGroupBox("Mirror motors (positive = firmware + direction)")
        g = QGridLayout(box)
        g.setVerticalSpacing(6)
        g.setHorizontalSpacing(10)
        for col, h in enumerate(["Axis", "Driver", "Microsteps", "Turns / screw travel", "Jog (◀◀ ▶▶ hold)",
                                 "Go to", "Soft limits (turns)", "On", ""]):
            lbl = QLabel(h)
            lbl.setStyleSheet("color: #999;")
            g.addWidget(lbl, 0, col)
        self.rows = [AxisRow(self, g, i, i + 1) for i in range(len(AXES))]
        return box

    def _build_console(self):
        box = QGroupBox("Serial console")
        v = QVBoxLayout(box)
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont(MONO, 9))
        self.console.document().setMaximumBlockCount(2000)
        v.addWidget(self.console)
        row = QHBoxLayout()
        row.addWidget(QLabel("Command:"))
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setFont(QFont(MONO, 9))
        self.cmd_edit.setPlaceholderText("any protocol command, e.g. INFO, DRV M1X, SAVE")
        self.cmd_edit.returnPressed.connect(self.send_raw)
        row.addWidget(self.cmd_edit)
        b = QPushButton("Send")
        b.clicked.connect(self.send_raw)
        row.addWidget(b)
        v.addLayout(row)
        return box

    # ── keyboard ────────────────────────────────────────────────────────────
    def eventFilter(self, obj, event):
        if event.type() != QEvent.Type.KeyPress or QApplication.activeWindow() is not self:
            return False
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.stop_all()
            return True
        if isinstance(QApplication.focusWidget(), (QLineEdit, QAbstractSpinBox, QComboBox)):
            return False
        if key in KEYS:
            i, d = KEYS[key]
            self.nudge(i, d)
            return True
        if key == Qt.Key.Key_L and not event.isAutoRepeat():
            self.toggle_laser()
            return True
        return False

    # ── connection ──────────────────────────────────────────────────────────
    def refresh_ports(self):
        current = self.port_box.currentText()
        ports = ["Simulator"]
        if serial is not None:
            ports = [f"{p.device} - {p.description}" for p in serial.tools.list_ports.comports()] + ports
        self.port_box.clear()
        self.port_box.addItems(ports)
        if self.sim:
            self.port_box.setCurrentText("Simulator")
        elif current in ports:
            self.port_box.setCurrentText(current)

    def toggle_connection(self):
        if self.link:
            self.disconnect()
            return
        choice = self.port_box.currentText()
        try:
            if choice == "Simulator":
                self.link = SimLink()
            else:
                if serial is None:
                    raise RuntimeError("pyserial is not installed: pip install pyserial")
                self.link = SerialLink(choice.split(" - ")[0])
        except Exception as e:
            self.link = None
            QMessageBox.critical(self, "Connect", str(e))
            return
        self.set_connected(True)
        self.log(f"connected to {choice}", "info")
        self.send("INFO")
        self.poll_timer.start()

    def disconnect(self):
        self.poll_timer.stop()
        for i in list(self.jog_timers):
            self.stop_jog(i, send_stop=False)
        if self.link:
            try:
                self.link.send("STOP ALL")
                self.link.send("LASER OFF")
                time.sleep(0.05)
            except Exception:
                pass
            self.link.close()
            self.link = None
            self.log("disconnected", "info")
        self.set_connected(False)

    def set_connected(self, on):
        self.conn_btn.setText("Disconnect" if on else "Connect")
        self.port_box.setEnabled(not on)
        self.laser_btn.setEnabled(on)
        self.stop_btn.setEnabled(on)
        if on:
            self.conn_dot.set_state("ok", "SIMULATOR" if isinstance(self.link, SimLink) else "CONNECTED")
            self.statusBar().showMessage("Connected")
        else:
            self.conn_dot.set_state("off", "DISCONNECTED")
            self.info_lbl.setText("not connected")
            self.statusBar().showMessage("Not connected: pick a port (or Simulator) and hit Connect")
            self.show_laser(False)
            for r in self.rows:
                r.clear()

    def closeEvent(self, event):
        self.disconnect()
        event.accept()

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
        line = self.cmd_edit.text().strip()
        if line:
            self.send(line)
            self.cmd_edit.clear()

    def step_usteps(self):
        turns = STEP_SIZES[self.step_box.currentIndex()][1]
        return 1 if turns is None else max(1, round(turns * self.usteps_per_rev))

    def nudge(self, i, direction):
        self.send(f"MOVE {AXES[i]} {direction * self.step_usteps()}")

    def start_jog(self, i, direction):
        if not self.link:
            return
        self.stop_jog(i, send_stop=False)
        sign = "+" if direction > 0 else "-"
        self.log(f"> JOG {AXES[i]} {sign} (held)", "tx")
        self.send(f"JOG {AXES[i]} {sign}", quiet=True)
        t = QTimer(self)
        t.setInterval(JOG_REPEAT_MS)
        t.timeout.connect(lambda: self.send(f"JOG {AXES[i]} {sign}", quiet=True))
        t.start()
        self.jog_timers[i] = t

    def stop_jog(self, i, send_stop=True):
        t = self.jog_timers.pop(i, None)
        if t:
            t.stop()
            t.deleteLater()
            if send_stop:
                self.send(f"STOP {AXES[i]}")

    def stop_all(self):
        for i in list(self.jog_timers):
            self.stop_jog(i, send_stop=False)
        self.send("STOP ALL")

    def toggle_laser(self):
        self.send(f"LASER {'OFF' if self.laser_on else 'ON'}")

    def apply_settings(self):
        self.send(f"SPEED ALL {self.rpm_box.value():g}")
        self.send(f"ACCEL ALL {self.acc_box.value():g}")
        self.send(f"CURRENT ALL {self.ma_box.value()}")
        self.send("INFO")

    # ── receiving ───────────────────────────────────────────────────────────
    def drain(self):
        while self.link:
            try:
                line = self.link.rx.get_nowait()
            except queue.Empty:
                break
            self.handle(line)

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
                self.rpm_box.setValue(float(f["RPM"].split(",")[0]))
                self.acc_box.setValue(float(f["ACCEL"].split(",")[0]))
                self.ma_box.setValue(int(float(f["MA"].split(",")[0])))
                self.info_lbl.setText(f"firmware {f.get('FW', '?')}   {self.usteps_per_rev} microsteps/turn   "
                                      f"{f.get('slots', '')}")
            except (KeyError, ValueError):
                pass
            if f.get("TRUSTED") == "0":
                self.log("positions may be off: power was lost during a move", "warn")
                self.statusBar().showMessage("⚠ Positions may be off: power was lost during a move")
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
        self.laser_btn.setText("LASER ON" if on else "LASER OFF")
        if on:
            style = ("QPushButton { background: #d32f2f; color: white; font-weight: bold; font-size: 11pt;"
                     " border-radius: 4px; } QPushButton:hover { background: #e53935; }")
        else:
            style = ("QPushButton { background: #3c3c40; color: #ddd; font-weight: bold; font-size: 11pt;"
                     " border: 1px solid #555; border-radius: 4px; } QPushButton:hover { background: #4a4a50; }"
                     " QPushButton:disabled { color: #777; }")
        self.laser_btn.setStyleSheet(style)

    def log(self, text, tag=None):
        stamp = time.strftime("%H:%M:%S")
        self.console.append(f'<span style="color:#666">{stamp}</span> '
                            f'<span style="color:{LOG_COLORS.get(tag, "#ddd")}">{html.escape(text)}</span>')
        self.console.moveCursor(QTextCursor.MoveOperation.End)


def dark_palette():
    """Fusion + the dark palette of the KineoLabs GUIs."""
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(37, 37, 38))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Base, QColor(30, 30, 30))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(45, 45, 48))
    pal.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Button, QColor(60, 60, 64))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(74, 158, 255))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(0, 0, 0))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(45, 45, 48))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(220, 220, 220))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(120, 120, 120))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        pal.setColor(QPalette.ColorGroup.Disabled, role, QColor(120, 120, 120))
    return pal


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", action="store_true", help="select the simulated controller")
    args = ap.parse_args()
    app = QApplication(sys.argv[:1])
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    win = TestApp(sim=args.sim)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
