#!/usr/bin/env python3
"""Bench test panel for the optics bench: laser on/off and the four mirror motors.

Talks to firmware/optics_bench over USB serial (protocol in
firmware/optics_bench/src/comms/protocol.h).

    pip install -r requirements.txt    # PySide6, pyserial
    python test_gui.py                 # pick the ESP32's COM port and Connect
    python test_gui.py --sim           # no hardware: a simulated controller

Keyboard (when no text box or the console has focus, and not while Align
runs), one step of the selected size per press:
    Left/Right  M1X -/+      Down/Up  M1Y -/+
    A/D         M2X -/+      S/W      M2Y -/+
    L           laser on/off Esc      stop all motors
Holding a key repeats only the 1 microstep and 1 full step sizes.

The photodiode panel shows the reference and output photodiode voltages from
the ADS1115, the output/reference ratio, and a rolling plot of both.
"""

import argparse
import csv
import html
import math
import queue
import sys
import threading
import time

from collections import deque

from PySide6.QtCore import QEvent, QPointF, QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen, QPolygonF, QTextCursor
from PySide6.QtWidgets import (
    QAbstractScrollArea, QAbstractSpinBox, QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPushButton, QSpinBox, QStatusBar, QTextEdit,
    QVBoxLayout, QWidget,
)

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # the simulator still works without pyserial
    serial = None

from bench_link import AXES, SerialLink, SimLink, ints, parse_fields  # noqa: E402

UM_PER_TURN = 254.0          # 100 TPI adjuster screw
POLL_MS = 150                # STATUS poll period
JOG_REPEAT_MS = 150          # JOG keep-alive period (firmware times out at 400 ms)

FEATHER_USB = (0x1A86, 0x55D4)   # the Feather ESP32 V2's CH9102 USB serial chip

K = Qt.Key
KEYS = {
    K.Key_Left: (0, -1), K.Key_Right: (0, 1), K.Key_Down: (1, -1), K.Key_Up: (1, 1),
    K.Key_A: (2, -1), K.Key_D: (2, 1), K.Key_S: (3, -1), K.Key_W: (3, 1),
}


# ─────────────────────────────────────────────────────────────────────────────
# GUI
# ─────────────────────────────────────────────────────────────────────────────

STEP_SIZES = [  # label, turns
    ("1 microstep", None),
    ("1 full step (1.3 um)", 1 / 200),   # this one and smaller repeat while a key is held
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
        b = QPushButton("Reset to 0")
        b.setToolTip("ZERO: call wherever the motor is now position 0 and save it to flash.\n"
                     "Use it after turning an adjuster by hand. Nothing moves; the soft limits\n"
                     "are relative to 0, so they re-centre on the new zero.")
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
        self.en_chk.setToolTip("Coils powered. Moves power a motor and release it 0.5 s after it stops;\n"
                               "ticking this (ENABLE) holds it powered until you untick it (DISABLE).")
        self.en_chk.clicked.connect(self.toggle_enable)
        grid.addWidget(self.en_chk, row, 7, alignment=Qt.AlignmentFlag.AlignCenter)
        b = QPushButton("Diag")
        b.setToolTip("DRV: TMC2209 status (current, StealthChop, overtemperature, short, open load)")
        b.clicked.connect(lambda: app.send(f"DRV {self.name}"))
        grid.addWidget(b, row, 8)

    def goto(self):
        self.app.send(f"GOTO {self.name} {round(self.goto_box.value() * self.app.usteps_per_rev)}")

    def zero(self):
        answer = QMessageBox.question(self.app, "Reset position", f"Call the current {self.name} position 0?\n"
                                      "The motor doesn't move, and the soft limits re-centre on the new zero.")
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


PD_RATES = [5, 10, 20, 50]           # PD STREAM choices, Hz
# Replies the aligner's commands produce; kept out of the console while it runs
ALIGN_TRAFFIC = ("PD ", "EVT DONE", "STATUS", "OK GOTO", "OK SPEED", "OK ACCEL", "OK ENABLE", "OK DISABLE",
                 "OK PD STREAM")
PD_SPANS = [("10 s", 10), ("30 s", 30), ("2 min", 120), ("10 min", 600)]
PD_RANGES = ["AUTO", "4.096", "2.048", "1.024", "0.512", "0.256"]
PD_HISTORY = 50 * 600                # samples kept: 10 minutes at the top rate
REF_COLOR, OUT_COLOR, RATIO_COLOR = "#4a9eff", "#2ecc40", "#ff851b"


def si(v, unit):
    """1.23e-6, 'W' -> '1.230 uW'"""
    for scale, prefix in ((1, ""), (1e-3, "m"), (1e-6, "u"), (1e-9, "n")):
        if abs(v) >= scale or scale == 1e-9:
            return f"{v / scale:.3f} {prefix}{unit}"


class PlotWidget(QWidget):
    """Rolling strip chart over the shared photodiode history, drawn with
    QPainter so the panel needs nothing beyond PySide6. Each series is
    (index into the history tuples, colour, label)."""

    def __init__(self, history, series, title, unit="", zero_based=True):
        super().__init__()
        self.history, self.series, self.title, self.unit = history, series, title, unit
        self.zero_based = zero_based
        self.span = 30.0
        self.log = False
        self.setMinimumHeight(130)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(30, 30, 30))
        left, top, right, bottom = 62, 20, r.width() - 10, r.height() - 20
        plot = QRectF(left, top, max(1, right - left), max(1, bottom - top))
        p.setPen(QColor(85, 85, 85))
        p.drawRect(plot)
        p.setFont(QFont(MONO, 8))

        now = self.history[-1][0] if self.history else 0.0
        t0 = now - self.span
        pts = [h for h in self.history if h[0] >= t0]
        vals = [h[k] for h in pts for k, _c, _l in self.series if h[k] is not None]
        if self.log:
            vals = [v for v in vals if v > 0]
        if vals:
            lo, hi = min(vals), max(vals)
        else:
            lo, hi = 0.0, 1.0
        if self.log:
            lo, hi = math.log10(max(lo, 1e-6)), math.log10(max(hi, 1e-6))
            lo, hi = math.floor(lo), math.ceil(hi) if hi > lo else math.floor(lo) + 1
        else:
            if self.zero_based:
                lo = min(lo, 0.0)
            pad = (hi - lo) * 0.08 or max(abs(hi) * 0.1, 1e-3)
            hi += pad
            if not self.zero_based or lo < 0:
                lo -= pad

        def y_of(v):
            if self.log:
                v = math.log10(max(v, 10 ** lo))
            return plot.bottom() - (v - lo) / (hi - lo) * plot.height()

        def x_of(t):
            return plot.left() + (t - t0) / self.span * plot.width()

        # grid and labels
        ticks = range(int(lo), int(hi) + 1) if self.log else [lo + (hi - lo) * k / 4 for k in range(5)]
        for tv in ticks:
            y = plot.bottom() - (tv - lo) / (hi - lo) * plot.height()
            p.setPen(QColor(55, 55, 58))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(QColor(150, 150, 150))
            label = f"1e{tv}" if self.log else f"{tv:.4g}"
            p.drawText(QRectF(0, y - 8, left - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                       label)
        for k in range(1, 5):
            x = plot.left() + plot.width() * k / 5
            p.setPen(QColor(55, 55, 58))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(QColor(150, 150, 150))
            p.drawText(QRectF(x - 30, plot.bottom() + 2, 60, 16), Qt.AlignmentFlag.AlignHCenter,
                       f"-{self.span * (5 - k) / 5:g}s")

        # traces
        p.setClipRect(plot)
        for k, color, _label in self.series:
            poly = QPolygonF()
            for h in pts:
                v = h[k]
                if v is None or (self.log and v <= 0):
                    continue
                poly.append(QPointF(x_of(h[0]), y_of(v)))
            p.setPen(QPen(QColor(color), 1.6))
            p.drawPolyline(poly)
        p.setClipping(False)

        # title and legend
        p.setFont(QFont(MONO, 9, QFont.Weight.Bold))
        p.setPen(QColor(220, 220, 220))
        x = left
        p.drawText(QPointF(x, 14), self.title + (f" ({self.unit})" if self.unit else ""))
        x += p.fontMetrics().horizontalAdvance(self.title + (f" ({self.unit})" if self.unit else "")) + 16
        for _k, color, label in self.series:
            p.setPen(QColor(color))
            p.drawText(QPointF(x, 14), "━ " + label)
            x += p.fontMetrics().horizontalAdvance("━ " + label) + 14


class TestApp(QMainWindow):
    def __init__(self, sim=False):
        super().__init__()
        self.link = None
        self.sim = sim
        self.usteps_per_rev = 3200
        self.laser_on = False
        self.jog_timers = {}
        self.pd_rf = [47000.0, 47000.0]      # TIA feedback resistors, from INFO
        self.pd_resp = 0.40                  # A/W, from INFO
        self.pd_hist = deque(maxlen=PD_HISTORY)   # (t, ref V, out V, ratio or None, laser, fsr ref, fsr out)
        self.pd_t0 = None
        self.pd_peak = None
        self.align = None                    # the running auto-align, if any
        self.align_cal = None                # walk directions measured by the last first run
        self.settings = QSettings("ROS-Optics-Bench", "test_gui")   # fiber, port, step and search, kept
        self.setWindowTitle("Optics bench test panel")
        self.resize(1180, 960)

        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.addLayout(self._build_connection_bar())
        outer.addLayout(self._build_controls())
        outer.addWidget(self._build_axes())
        outer.addWidget(self._build_photodiodes(), stretch=2)
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

    def saved_index(self, key, default, count):
        """A combo box index kept from the last session, or default if it no longer fits."""
        try:
            i = int(self.settings.value(key, default))
        except (TypeError, ValueError):
            return default
        return i if 0 <= i < count else default

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

        s = self.motors_box = QGroupBox("All motors")
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
        b = QPushButton("Reset all to 0")
        b.setToolTip("ZERO ALL: call wherever every motor is now position 0 and save it to flash.\n"
                     "Nothing moves; the soft limits re-centre on the new zeros.")
        b.clicked.connect(self.zero_all)
        g.addWidget(b, 0, 5, 2, 1)
        row.addWidget(s)

        st = QGroupBox("Step size (◀ ▶ and keys)")
        v = QVBoxLayout(st)
        self.step_box = QComboBox()
        self.step_box.addItems([label for label, _ in STEP_SIZES])
        self.step_box.setCurrentIndex(self.saved_index("step", 2, self.step_box.count()))
        self.step_box.currentIndexChanged.connect(lambda i: self.settings.setValue("step", i))
        v.addWidget(self.step_box)
        row.addWidget(st)

        self.align_box = QGroupBox("Auto-align")
        g = QGridLayout(self.align_box)
        self.fiber_box = QComboBox()
        self.fiber_box.addItems(["mm50: 50 um multimode", "smf28: SMF-28 / OS2 single-mode patch cable",
                                 "sm630: single-mode for 630 nm"])
        self.fiber_box.setCurrentIndex(self.saved_index("fiber", 0, self.fiber_box.count()))
        self.fiber_box.setToolTip("The fiber on the bench. Align sizes its steps for it, and the simulator\n"
                                  "couples into it (SIM FIBER). Single-mode is the real target: its peak\n"
                                  "is only a couple of full steps wide.")
        self.fiber_box.currentIndexChanged.connect(self.fiber_changed)
        g.addWidget(self.fiber_box, 0, 0, 1, 3)
        self.align_btn = colored_button("Align", "#2e7d32", "#388e3c")
        self.align_btn.setToolTip("Find the light and peak the out/ref ratio (tools/bench_twin/align.py):\n"
                                  "steer with M2, walk with M1 and M2 together. The first run for a fiber\n"
                                  "also measures the walk directions, so start it near the peak; later\n"
                                  "runs recover from a knock. Needs the photodiodes. Stop or Esc ends it.")
        self.align_btn.clicked.connect(self.toggle_align)
        g.addWidget(self.align_btn, 0, 3)
        g.addWidget(QLabel("Search (turns)"), 2, 0, 1, 2)
        self.search_box = QDoubleSpinBox()
        self.search_box.setRange(0.1, 3.0)
        self.search_box.setDecimals(1)
        self.search_box.setSingleStep(0.1)
        self.search_box.setValue(self.settings.value("search", 0.4, type=float))
        self.search_box.valueChanged.connect(lambda v: self.settings.setValue("search", v))
        self.search_box.setToolTip("How far Align searches with M2, either way from where M2 is when you\n"
                                   "press Align, when the output photodiode sees no light. One turn moves\n"
                                   "the focused spot about 230 um on the fiber face. The search covers a\n"
                                   "square, so the time grows with the square of this: the log says how\n"
                                   "many points it will visit. Soft limits still stop any move that\n"
                                   "would pass them.")
        g.addWidget(self.search_box, 2, 2, 1, 2)
        self.sim_widgets = []
        for col, m in enumerate(("M1", "M2")):
            b = QPushButton(f"Knock {m}")
            b.setToolTip(f"SIM KNOCK {m}: tilt mirror {m} by 0.5-2 mrad in a random direction, as if bumped")
            b.clicked.connect(lambda _c=False, m=m: self.send(f"SIM KNOCK {m}"))
            g.addWidget(b, 1, col)
            self.sim_widgets.append(b)
        b = QPushButton("Unknock")
        b.setToolTip("SIM RESET: take the knocks back out")
        b.clicked.connect(lambda: self.send("SIM RESET"))
        g.addWidget(b, 1, 2)
        self.sim_widgets.append(b)
        b = QPushButton("Peak?")
        b.setToolTip("SIM PEAK: where the simulator's best position is, and how close the coupling is to it")
        b.clicked.connect(lambda: self.send("SIM PEAK"))
        g.addWidget(b, 1, 3)
        self.sim_widgets.append(b)
        row.addWidget(self.align_box)

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
        self.axes_box = box
        return box

    def _build_photodiodes(self):
        box = QGroupBox("Photodiodes (ADS1115: A0 reference, A1 output)")
        h = QHBoxLayout(box)

        g = QGridLayout()
        g.setVerticalSpacing(4)
        self.adc_dot = StatusDot("ADC: -")
        self.adc_dot.setToolTip("ADS1115 at 0x48 on SDA 22 / SCL 20, from INFO (ADC=1) or a PD reply")
        g.addWidget(self.adc_dot, 0, 0)
        self.dark_dot = StatusDot("DARK: off")
        self.dark_dot.setToolTip("Laser-off offsets from Measure dark are being subtracted")
        g.addWidget(self.dark_dot, 0, 1)

        big = QFont(MONO, 16, QFont.Weight.Bold)
        self.pd_val, self.pd_sub = [], []
        for row, (name, color) in enumerate((("Reference", REF_COLOR), ("Output", OUT_COLOR)), start=1):
            lbl = QLabel(name)
            lbl.setStyleSheet(f"color: {color}; font-weight: bold;")
            g.addWidget(lbl, 2 * row - 1, 0)
            v = QLabel("-")
            v.setFont(big)
            v.setStyleSheet(f"color: {color};")
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            v.setMinimumWidth(150)
            g.addWidget(v, 2 * row - 1, 1)
            s = QLabel("")
            s.setFont(QFont(MONO, 9))
            s.setStyleSheet("color: #999;")
            s.setAlignment(Qt.AlignmentFlag.AlignRight)
            g.addWidget(s, 2 * row, 0, 1, 2)
            self.pd_val.append(v)
            self.pd_sub.append(s)
        lbl = QLabel("Ratio out/ref")
        lbl.setStyleSheet(f"color: {RATIO_COLOR}; font-weight: bold;")
        g.addWidget(lbl, 5, 0)
        self.ratio_val = QLabel("-")
        self.ratio_val.setFont(big)
        self.ratio_val.setStyleSheet(f"color: {RATIO_COLOR};")
        self.ratio_val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        g.addWidget(self.ratio_val, 5, 1)
        self.peak_lbl = QLabel("peak -")
        self.peak_lbl.setFont(QFont(MONO, 9))
        self.peak_lbl.setStyleSheet("color: #999;")
        self.peak_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        g.addWidget(self.peak_lbl, 6, 0, 1, 2)

        ctl = QGridLayout()
        self.pd_controls = []                # off while Align owns the photodiodes
        self.live_chk = QCheckBox("Live")
        self.live_chk.setToolTip("PD STREAM: the firmware sends averaged readings at this rate")
        self.live_chk.toggled.connect(self.pd_stream_changed)
        ctl.addWidget(self.live_chk, 0, 0)
        self.rate_box = QComboBox()
        self.rate_box.addItems([f"{r} Hz" for r in PD_RATES])
        self.rate_box.setCurrentIndex(2)
        self.rate_box.currentIndexChanged.connect(lambda _i: self.pd_stream_changed())
        ctl.addWidget(self.rate_box, 0, 1)
        b = QPushButton("Read once")
        b.clicked.connect(lambda: self.send("PD"))
        ctl.addWidget(b, 0, 2)
        self.pd_controls.append(b)
        b = QPushButton("Measure dark")
        b.setToolTip("PD DARK: laser off, average both channels, laser back as it was.\n"
                     "The offsets (TIA offset + room light) are then subtracted from every reading.")
        b.clicked.connect(lambda: self.send("PD DARK"))
        ctl.addWidget(b, 1, 0, 1, 2)
        self.pd_controls.append(b)
        b = QPushButton("Clear dark")
        b.clicked.connect(lambda: self.send("PD DARK CLEAR"))
        ctl.addWidget(b, 1, 2)
        self.pd_controls.append(b)
        ctl.addWidget(QLabel("ADC range"), 2, 0)
        self.range_box = QComboBox()
        self.range_box.addItems([r if r == "AUTO" else f"±{r} V" for r in PD_RANGES])
        self.range_box.setToolTip("ADS1115 gain range. Auto picks the finest range per channel;\n"
                                  "a fixed range avoids range switches during a scan.")
        self.range_box.currentIndexChanged.connect(lambda i: self.send(f"PD RANGE {PD_RANGES[i]}"))
        ctl.addWidget(self.range_box, 2, 1, 1, 2)
        self.pd_controls += [self.live_chk, self.rate_box, self.range_box]
        b = QPushButton("Reset peak")
        b.clicked.connect(self.reset_peak)
        ctl.addWidget(b, 3, 0)
        b = QPushButton("Clear plot")
        b.clicked.connect(self.clear_pd_history)
        ctl.addWidget(b, 3, 1)
        b = QPushButton("Save CSV...")
        b.setToolTip("Save the recorded readings (up to the last 10 minutes)")
        b.clicked.connect(self.save_pd_csv)
        ctl.addWidget(b, 3, 2)
        ctl.addWidget(QLabel("Plot span"), 4, 0)
        self.span_box = QComboBox()
        self.span_box.addItems([s for s, _ in PD_SPANS])
        self.span_box.setCurrentIndex(1)
        self.span_box.currentIndexChanged.connect(self.set_plot_span)
        ctl.addWidget(self.span_box, 4, 1)
        self.log_chk = QCheckBox("Log volts")
        self.log_chk.toggled.connect(self.set_plot_log)
        ctl.addWidget(self.log_chk, 4, 2)

        left = QVBoxLayout()
        left.addLayout(g)
        left.addSpacing(6)
        left.addLayout(ctl)
        left.addStretch()
        h.addLayout(left)

        plots = QVBoxLayout()
        self.volt_plot = PlotWidget(self.pd_hist, [(1, REF_COLOR, "reference"), (2, OUT_COLOR, "output")],
                                    "Photodiode voltage", "V")
        self.ratio_plot = PlotWidget(self.pd_hist, [(3, RATIO_COLOR, "out/ref")], "Ratio", zero_based=False)
        plots.addWidget(self.volt_plot, stretch=3)
        plots.addWidget(self.ratio_plot, stretch=2)
        h.addLayout(plots, stretch=1)
        self.plot_timer = QTimer(self)
        self.plot_timer.setInterval(100)
        self.plot_timer.timeout.connect(self._repaint_plots)
        self.plot_timer.start()
        self._plots_dirty = False
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
        self.cmd_widgets = [self.cmd_edit, b]
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
        mods = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.MetaModifier
        if event.modifiers() & mods:         # Ctrl+A, Ctrl+C, ... belong to the widget
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, (QLineEdit, QAbstractSpinBox, QComboBox, QAbstractScrollArea)) or \
                (focus is not None and isinstance(focus.parent(), QAbstractScrollArea)):
            return False                     # text boxes, and the console (arrows scroll it)
        if key in KEYS or key == Qt.Key.Key_L:
            if self.align:                   # Align owns the motors and the laser until it ends
                return True
        if key in KEYS:
            # A held key repeats only the small steps; a big step per repeat
            # would queue turns of travel behind the key
            if event.isAutoRepeat() and STEP_SIZES[self.step_box.currentIndex()][1] not in (None, 1 / 200):
                return True
            i, d = KEYS[key]
            self.nudge(i, d)
            return True
        if key == Qt.Key.Key_L and not event.isAutoRepeat():
            self.toggle_laser()
            return True
        return False

    # ── connection ──────────────────────────────────────────────────────────
    def refresh_ports(self):
        current = self.port_box.currentText() or self.settings.value("port", "", type=str)
        ports, feather = ["Simulator"], None
        if serial is not None:
            found = serial.tools.list_ports.comports()
            ports = [f"{p.device} - {p.description}" for p in found] + ports
            feather = next((f"{p.device} - {p.description}" for p in found
                            if (p.vid, p.pid) == FEATHER_USB), None)
        self.port_box.clear()
        self.port_box.addItems(ports)
        if self.sim:
            self.port_box.setCurrentText("Simulator")
        elif current in ports:
            self.port_box.setCurrentText(current)
        elif feather:                        # nothing chosen yet: the Feather, not whatever is first
            self.port_box.setCurrentText(feather)

    def toggle_connection(self):
        if self.link:
            self.disconnect()
            return
        choice = self.port_box.currentText()
        try:
            if choice == "Simulator":
                self.link = SimLink(fiber=SimLink.FIBERS[self.fiber_box.currentIndex()])
            else:
                if serial is None:
                    raise RuntimeError("pyserial is not installed: pip install pyserial")
                self.link = SerialLink(choice.split(" - ")[0])
        except Exception as e:
            self.link = None
            QMessageBox.critical(self, "Connect", str(e))
            return
        self.settings.setValue("port", choice)
        self.set_connected(True)
        self.log(f"connected to {choice}", "info")
        self.send("INFO")
        self.pd_resync()
        self.poll_timer.start()

    def disconnect(self):
        if self.align:
            self.align["bench"].abort.set()
            self.align = None
            self.set_aligning(False)
        self.align_cal = None
        self.poll_timer.stop()
        for i in list(self.jog_timers):
            self.stop_jog(i, send_stop=False)
        if self.link:
            try:
                self.link.send("STOP ALL")
                self.link.send("LASER OFF")
                self.link.send("PD STREAM OFF")
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
        self.align_box.setVisible(on)
        for w in self.sim_widgets:
            w.setVisible(on and isinstance(self.link, SimLink))
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
            self.adc_dot.set_state("off", "ADC: -")

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
        if line and not self.align:
            self.send(line)
            self.cmd_edit.clear()

    def step_usteps(self):
        turns = STEP_SIZES[self.step_box.currentIndex()][1]
        return 1 if turns is None else max(1, round(turns * self.usteps_per_rev))

    def nudge(self, i, direction):
        if not self.align:
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
        if self.align:
            self.align["bench"].abort.set()
        for i in list(self.jog_timers):
            self.stop_jog(i, send_stop=False)
        self.send("STOP ALL")

    def zero_all(self):
        answer = QMessageBox.question(self, "Reset all positions",
                                      "Call the current position of all four motors 0?\n"
                                      "Nothing moves, and the soft limits re-centre on the new zeros.")
        if answer == QMessageBox.StandardButton.Yes:
            for i in list(self.jog_timers):
                self.stop_jog(i, send_stop=False)
            self.send("HALT ALL")            # ZERO is refused while a motor is still ramping
            self.send("ZERO ALL")
            self.send("INFO")

    def toggle_laser(self):
        if not self.align:
            self.send(f"LASER {'OFF' if self.laser_on else 'ON'}")

    def apply_settings(self):
        self.send(f"SPEED ALL {self.rpm_box.value():g}")
        self.send(f"ACCEL ALL {self.acc_box.value():g}")
        self.send(f"CURRENT ALL {self.ma_box.value()}")
        self.send("INFO")

    # ── photodiodes ─────────────────────────────────────────────────────────
    def pd_stream_changed(self, *_):
        if self.live_chk.isChecked():
            self.send(f"PD STREAM {PD_RATES[self.rate_box.currentIndex()]}")
        else:
            self.send("PD STREAM OFF")

    def pd_resync(self):
        """After a connect or a board reboot: put streaming and range back."""
        if self.range_box.currentIndex():
            self.send(f"PD RANGE {PD_RANGES[self.range_box.currentIndex()]}")
        if self.live_chk.isChecked():
            self.pd_stream_changed()

    def reset_peak(self):
        self.pd_peak = None
        self.peak_lbl.setText("peak -")

    def clear_pd_history(self):
        self.pd_hist.clear()
        self.pd_t0 = None
        self._plots_dirty = True

    def set_plot_span(self, i):
        for plot in (self.volt_plot, self.ratio_plot):
            plot.span = float(PD_SPANS[i][1])
        self._plots_dirty = True

    def set_plot_log(self, on):
        self.volt_plot.log = on
        self._plots_dirty = True

    def _repaint_plots(self):
        if self._plots_dirty:
            self._plots_dirty = False
            self.volt_plot.update()
            self.ratio_plot.update()

    def save_pd_csv(self):
        if not self.pd_hist:
            return self.log("no photodiode readings recorded yet", "warn")
        path, _ = QFileDialog.getSaveFileName(self, "Save photodiode readings",
                                              time.strftime("pd_%Y%m%d_%H%M%S.csv"), "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["t_s", "ref_V", "out_V", "ratio", "laser", "fsr_ref_V", "fsr_out_V",
                            "ref_uW", "out_uW"])
                for t, ref, out, ratio, laser, fr, fo in self.pd_hist:
                    w.writerow([f"{t:.3f}", f"{ref:.6f}", f"{out:.6f}", "" if ratio is None else f"{ratio:.6f}",
                                laser, fr, fo, f"{self.pd_watts(0, ref) * 1e6:.4f}",
                                f"{self.pd_watts(1, out) * 1e6:.4f}"])
        except OSError as e:
            return self.log(f"could not save {path}: {e}", "err")
        self.log(f"saved {len(self.pd_hist)} readings to {path}", "info")

    def pd_watts(self, ch, volts):
        return volts / self.pd_rf[ch] / self.pd_resp

    def show_adc(self, present):
        self.adc_dot.set_state("ok" if present else "bad", "ADC: ok" if present else "ADC: not found")

    def handle_pd(self, line):
        f = parse_fields(line)
        try:
            ref, out = float(f["REF"]), float(f["OUT"])
            fsr = f.get("FSR", "0,0").split(",")
        except (KeyError, ValueError):
            return
        ratio = None if f.get("RATIO", "-") == "-" else float(f["RATIO"])
        now = time.monotonic()
        if self.pd_t0 is None:
            self.pd_t0 = now
        self.pd_hist.append((now - self.pd_t0, ref, out, ratio, int(f.get("LASER", "0")), fsr[0], fsr[-1]))
        self._plots_dirty = True
        self.show_adc(True)
        dark = f.get("DARK") == "1"
        self.dark_dot.set_state("ok" if dark else "off", "DARK: subtracted" if dark else "DARK: off")
        for ch, v in enumerate((ref, out)):
            self.pd_val[ch].setText(f"{v:.5f} V")
            amps = v / self.pd_rf[ch]
            self.pd_sub[ch].setText(f"{si(amps, 'A')}  {si(self.pd_watts(ch, v), 'W')}  ±{fsr[ch]} V")
        if ratio is None:
            self.ratio_val.setText("-")
        else:
            self.ratio_val.setText(f"{ratio:.5f}")
            if self.pd_peak is None or ratio > self.pd_peak[0]:
                self.pd_peak = (ratio, [r.pos_lbl.text() for r in self.rows])
            self.peak_lbl.setText(f"peak {self.pd_peak[0]:.5f} at {', '.join(self.pd_peak[1])}")

    # ── receiving ───────────────────────────────────────────────────────────
    def drain(self):
        while self.link:
            try:
                line = self.link.rx.get_nowait()
            except queue.Empty:
                break
            self.handle(line)
        if self.align:
            self.poll_align()

    def handle(self, line):
        if not line:
            return
        head = line.split()[0]
        quiet = self.align is not None and line.startswith(ALIGN_TRAFFIC)
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
        if head == "PD":
            self.handle_pd(line)
            if not self.live_chk.isChecked() and not quiet:
                self.log(line)
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
            try:
                rf = [float(x) for x in f["PD_RF"].split(",")]
                self.pd_rf = (rf * 2)[:2]
                self.pd_resp = float(f["PD_RESP"])
            except (KeyError, ValueError):
                pass
            if "ADC" in f:
                self.show_adc(f["ADC"] == "1")
            if f.get("TRUSTED") == "0":
                trust = f.get("TRUST", "").split(",")
                lost = [ax for ax, t in zip(AXES, trust) if t == "0"]
                which = ", ".join(lost) if lost and len(trust) == len(AXES) else "some motors"
                text = (f"Positions may be off on {which}: power was lost mid-move, or a driver had no "
                        "power while it moved. Reset to 0 clears it once the position is right again.")
                self.log(text, "warn")
                self.statusBar().showMessage("⚠ " + text)
        elif head == "READY":                  # the board rebooted
            if self.align:                     # its positions and settings are gone: Align can't go on
                self.log("align: the controller rebooted, stopping", "err")
                self.align["bench"].abort.set()
            else:
                self.pd_resync()
            self.send("INFO")
        elif head == "LINK_ERROR":
            self.log(line, "err")
            self.disconnect()
            return
        if head == "OK" and "LASER=" in line:
            self.show_laser(line.rstrip().endswith("LASER=1"))
        if line.startswith("OK PD DARK REF="):
            self.dark_dot.set_state("ok", "DARK: subtracted")
        elif line.startswith("OK PD DARK CLEARED"):
            self.dark_dot.set_state("off", "DARK: off")
        elif head == "ERR" and "ADS1115" in line:
            self.show_adc(False)
            self.live_chk.setChecked(False)
        tag = "err" if head == "ERR" else "warn" if head == "WARN" else None
        if not quiet:
            self.log(line, tag)

    # ── auto-align ──────────────────────────────────────────────────────────
    def fiber_changed(self, i):
        self.settings.setValue("fiber", i)
        self.align_cal = None               # walk directions are per fiber
        if isinstance(self.link, SimLink):
            self.send(f"SIM FIBER {SimLink.FIBERS[i]}")

    def set_aligning(self, on):
        """Align owns the motors, the laser and the photodiodes while it runs: a
        stray PD, MOVE or LASER would shift its readings or positions."""
        self.align_btn.setText("Stop" if on else "Align")
        for w in [self.axes_box, self.motors_box, self.fiber_box, self.search_box, self.laser_btn,
                  *self.pd_controls, *self.cmd_widgets]:
            w.setEnabled(not on)

    def toggle_align(self):
        if self.align:
            self.align["bench"].abort.set()
            return
        if not self.link:
            return
        try:
            from bench_twin import Aligner, Bench, Optics, Settings, make_plan
            from bench_twin.protocol_bench import Aborted, ProtocolBench
        except ImportError as e:
            return self.log(f"Align needs numpy ({e}): py -3 -m pip install -r tools/requirements.txt", "err")
        fiber = SimLink.FIBERS[self.fiber_box.currentIndex()]
        cal = self.align_cal
        plan = cal["plan"] if cal else make_plan(Bench(Optics(fiber=fiber)))
        bench = ProtocolBench(self.link.send)
        msgs = queue.Queue()
        restore = [f"SPEED ALL {self.rpm_box.value():g}", f"ACCEL ALL {self.acc_box.value():g}", "DISABLE ALL"]
        link = self.link
        search = self.search_box.value()
        self.align = {"bench": bench, "msgs": msgs, "fiber": fiber}
        # Replies go straight from the link's reader thread to the aligner;
        # going through the 30 ms drain timer would add up to 30 ms per reply
        link.listeners.append(bench.feed)
        self.set_aligning(True)
        if not self.laser_on:
            self.send("LASER ON")
        self.log(f"align: {'recovering' if cal else 'first run for ' + fiber + ': finding light, then calibrating'}",
                 "info")

        def work():
            try:
                bench.start()
                bench.command("ENABLE ALL", "OK ENABLE")      # no enable settle between steps
                al = Aligner(bench, plan, Settings(search_turns=search),
                             say=lambda t: msgs.put(("info", "align: " + t, None)))
                if cal:
                    al.good = cal["good"]
                    res = al.recover()
                else:
                    res = al.first_align()
                start = al.trace[0][2] if al.trace else None
                # Only a first run that ends ok measured a calibration worth keeping
                new_cal = {"plan": al.plan, "good": al.good} if res.ok and not cal else None
                msgs.put(("done", (res, start, not cal), new_cal))
            except Aborted:
                msgs.put(("stopped", None, None))
            except Exception as e:           # a timeout or an ERR from the controller
                msgs.put(("error", str(e), None))
            finally:
                if bench.feed in link.listeners:
                    link.listeners.remove(bench.feed)
                try:
                    for line in restore:
                        link.send(line)
                except Exception:
                    pass

        threading.Thread(target=work, daemon=True).start()

    def poll_align(self):
        while True:
            try:
                kind, value, cal = self.align["msgs"].get_nowait()
            except queue.Empty:
                return
            if kind == "info":
                self.log(value, "info")
                continue
            if kind == "done":
                res, start, first = value
                if not res.found:
                    self.log("align: no light found within the search range. Get some light on the output "
                             "photodiode by hand, or raise Search (turns), and try again.", "warn")
                elif res.note:                  # light, but not a calibration to keep
                    self.log(f"align: found a signal but not a usable calibration, so it isn't kept: "
                             f"{res.note}", "warn")
                else:
                    if cal:
                        self.align_cal = cal
                    good = self.align_cal["good"] if self.align_cal else res.ratio
                    began = "" if start is None else f" from {start:.4f}"
                    self.log(f"align: done in {res.seconds:.1f} s ({res.moves} moves, {res.reads} readings): "
                             f"ratio{began} to {res.ratio:.4f}, " +
                             ("this is now the calibrated peak" if first else f"{res.ratio / good:.1%} of the "
                              "calibrated peak"), None if res.ok else "warn")
                    if start is not None and res.ratio < start:
                        self.log("align: it ended lower than it started: is the right fiber selected?", "warn")
            elif kind == "stopped":
                self.log("align: stopped", "warn")
            else:
                self.log(f"align: {value}", "err")
            self.align = None
            self.set_aligning(False)
            self.send("INFO")
            self.pd_resync()
            return

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
