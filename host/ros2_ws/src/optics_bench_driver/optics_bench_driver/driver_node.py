"""ROS 2 node for the bench controller (the ESP32 over USB serial, or the simulator).

Topics (relative, so they land under the launch file's /bench namespace):
    status        optics_bench_interfaces/BenchStatus   motor positions, laser, drivers
    photodiodes   optics_bench_interfaces/Photodiodes   reference and output photodiodes, ratio
    rx            std_msgs/String                       every line the controller sends
Services:
    command       optics_bench_interfaces/Command       any protocol line, e.g. "SIM KNOCK M1 1"
    laser         std_srvs/SetBool
    stop          std_srvs/Trigger                      stops every motor and any alignment
    pd_dark       std_srvs/Trigger                      measure and subtract the dark offsets
Actions:
    move_to       optics_bench_interfaces/MoveTo
    align         optics_bench_interfaces/Align

Parameters: port ("sim" for the bench twin, else e.g. /dev/optics_bench),
baud, sim_fiber, sim_seed (-1 random), status_hz, pd_hz, calibration_file,
tools_dir.
"""

from __future__ import annotations

import os
import threading

import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import SetBool, Trigger

from optics_bench_interfaces.action import Align, MoveTo
from optics_bench_interfaces.msg import BenchStatus, Photodiodes
from optics_bench_interfaces.srv import Command

from .tools_path import add_tools_to_path

# Commands that are safe while the aligner owns the motors and photodiodes
READ_ONLY_WHILE_ALIGNING = ("PING", "STATUS", "INFO", "STOP", "HALT")


class BenchDriver(Node):
    def __init__(self, **kwargs):
        super().__init__("bench_driver", **kwargs)
        self.declare_parameter("port", "sim")
        self.declare_parameter("baud", 115200)
        self.declare_parameter("sim_fiber", "mm50")
        self.declare_parameter("sim_seed", -1)
        self.declare_parameter("status_hz", 5.0)
        self.declare_parameter("pd_hz", 10.0)
        self.declare_parameter("calibration_file", "~/.ros/optics_bench/align_calibration.json")
        self.declare_parameter("tools_dir", "")
        p = lambda name: self.get_parameter(name).value

        tools = add_tools_to_path(p("tools_dir"))
        from .controller import FIBERS, CalibrationStore, Controller, ControllerError, Busy, parse_pd, parse_status
        self._parse_pd, self._parse_status = parse_pd, parse_status
        self.ControllerError, self.Busy, self.FIBERS = ControllerError, Busy, FIBERS
        self.get_logger().info(f"bench code from {tools}")

        self.port = p("port")
        self.pd_hz = float(p("pd_hz"))
        self.fiber = p("sim_fiber") if p("sim_fiber") in FIBERS else "mm50"
        self.calibration = CalibrationStore(p("calibration_file"))
        self._Controller = Controller
        self.ctl = None
        self._connect_lock = threading.Lock()
        self._align_abort = None
        self._move_aborts = set()            # one per MoveTo goal in progress; /stop sets them
        self._last_status = None
        self._last_ratio = 0.0

        cb = ReentrantCallbackGroup()
        self.status_pub = self.create_publisher(BenchStatus, "status", 10)
        self.pd_pub = self.create_publisher(Photodiodes, "photodiodes", 50)
        self.rx_pub = self.create_publisher(String, "rx", 100)
        self.create_service(Command, "command", self.on_command, callback_group=cb)
        self.create_service(SetBool, "laser", self.on_laser, callback_group=cb)
        self.create_service(Trigger, "stop", self.on_stop, callback_group=cb)
        self.create_service(Trigger, "pd_dark", self.on_pd_dark, callback_group=cb)
        ActionServer(self, MoveTo, "move_to", self.run_move, goal_callback=self.accept_move,
                     cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=cb)
        ActionServer(self, Align, "align", self.run_align, goal_callback=self.accept_align,
                     cancel_callback=lambda _: CancelResponse.ACCEPT, callback_group=cb)
        self.create_timer(1.0 / max(0.5, float(p("status_hz"))), self.poll_status, callback_group=cb)
        self.create_timer(2.0, self.ensure_connected, callback_group=cb)
        self.ensure_connected()

    # ── connection ──────────────────────────────────────────────────────────
    def ensure_connected(self):
        if self.ctl is not None and self.ctl.alive:
            return
        if not self._connect_lock.acquire(blocking=False):
            return
        try:
            if self.ctl is not None:
                self.get_logger().warn("lost the controller link, reconnecting")
                self.ctl.close()
                self.ctl = None
            from bench_link import SerialLink, SimLink
            try:
                if self.port == "sim":
                    seed = self.get_parameter("sim_seed").value
                    link = SimLink(fiber=self.fiber, seed=None if seed < 0 else seed)
                else:
                    link = SerialLink(self.port, self.get_parameter("baud").value)
            except Exception as e:
                self.get_logger().warn(f"can't open {self.port}: {e}", throttle_duration_sec=30.0)
                return
            ctl = self._Controller(link, log=lambda t: self.get_logger().warn(t))
            ctl.add_listener(self.on_line)
            try:
                info = ctl.info()
                if self.pd_hz > 0:
                    try:
                        ctl.request(f"PD STREAM {self.pd_hz:g}")
                    except self.ControllerError as e:
                        self.get_logger().warn(f"photodiodes: {e}")
            except self.ControllerError as e:
                self.get_logger().warn(f"{self.port} opened but the controller doesn't answer: {e}",
                                       throttle_duration_sec=30.0)
                ctl.close()
                return
            self.ctl = ctl
            self.get_logger().info(f"connected to {self.port}: FW={info.get('FW')} "
                                   f"USTEPS_PER_REV={info.get('USTEPS_PER_REV')} ADC={info.get('ADC')}")
        finally:
            self._connect_lock.release()

    def _need(self):
        if self.ctl is None or not self.ctl.alive:
            raise self.ControllerError(f"not connected to the controller on {self.port}")
        return self.ctl

    # ── lines from the controller ───────────────────────────────────────────
    def on_line(self, line):
        self.rx_pub.publish(String(data=line))
        try:
            if line.startswith("STATUS "):
                self._last_status = self._parse_status(line)
                self.publish_status(self._last_status)
            elif line.startswith("PD "):
                r = self._parse_pd(line)
                self._last_ratio = r.ratio or 0.0
                self.publish_pd(r)
            elif line.startswith("WARN"):
                self.get_logger().warn(f"controller: {line[5:]}")
        except (KeyError, ValueError, IndexError) as e:
            self.get_logger().warn(f"can't parse {line!r}: {e}")

    def publish_status(self, s):
        from bench_link import AXES

        m = BenchStatus()
        m.header.stamp = self.get_clock().now().to_msg()
        m.connected = True
        m.aligning = bool(self.ctl and self.ctl.aligning)
        m.laser = s.laser
        m.axes = list(AXES)
        m.position, m.target = list(s.position), list(s.target)
        m.moving, m.enabled, m.driver_ok = list(s.moving), list(s.enabled), list(s.driver_ok)
        self.status_pub.publish(m)

    def publish_pd(self, r):
        m = Photodiodes()
        m.header.stamp = self.get_clock().now().to_msg()
        m.ref_v, m.out_v = r.ref_v, r.out_v
        m.has_ratio = r.ratio is not None
        m.ratio = r.ratio if r.ratio is not None else 0.0
        m.ref_range_v, m.out_range_v = r.ref_range_v, r.out_range_v
        m.ref_samples, m.out_samples = r.ref_samples, r.out_samples
        m.dark_subtracted, m.laser = r.dark_subtracted, r.laser
        self.pd_pub.publish(m)

    def poll_status(self):
        ctl = self.ctl
        if ctl is None or not ctl.alive:
            m = BenchStatus()
            m.header.stamp = self.get_clock().now().to_msg()
            self.status_pub.publish(m)          # connected = false
            return
        try:
            ctl.request("STATUS", timeout=1.0)   # published by on_line
        except self.ControllerError:
            pass

    # ── services ────────────────────────────────────────────────────────────
    def on_command(self, req, res):
        try:
            ctl = self._need()
            line = req.line.strip()
            cmd = line.split()[0].upper() if line else ""
            if cmd in ("STOP", "HALT"):
                self._stop_goals()
            if ctl.aligning and cmd not in READ_ONLY_WHILE_ALIGNING:
                raise self.Busy("aligning: only STATUS, INFO, PING, STOP and HALT until it finishes")
            timeout = 1.0 if cmd == "PD" and line.upper().split()[1:2] == ["DARK"] else 0.0
            res.reply = ctl.request(line, timeout=2.0 + timeout)
            res.success = True
        except self.ControllerError as e:
            res.success, res.reply = False, str(e)
        return res

    def on_laser(self, req, res):
        try:
            ctl = self._need()
            if ctl.aligning:
                raise self.Busy("aligning: the laser stays on until it finishes")
            res.message = ctl.request(f"LASER {'ON' if req.data else 'OFF'}")
            res.success = True
        except self.ControllerError as e:
            res.success, res.message = False, str(e)
        return res

    def _stop_goals(self):
        """End the running Align and MoveTo goals (they abort; the motors are
        stopped by the STOP that comes with this)."""
        if self._align_abort:
            self._align_abort.set()
        for ev in list(self._move_aborts):
            ev.set()

    def on_stop(self, req, res):
        self._stop_goals()
        try:
            res.message = self._need().request("STOP ALL")
            res.success = True
        except self.ControllerError as e:
            res.success, res.message = False, str(e)
        return res

    def on_pd_dark(self, req, res):
        try:
            ctl = self._need()
            if ctl.aligning:
                raise self.Busy("aligning")
            res.message = ctl.request("PD DARK", timeout=3.0)
            res.success = True
        except self.ControllerError as e:
            res.success, res.message = False, str(e)
        return res

    # ── actions ─────────────────────────────────────────────────────────────
    def accept_move(self, goal):
        if goal.axes and len(goal.axes) != len(goal.position):
            self.get_logger().warn("move_to: axes and position need the same length")
            return GoalResponse.REJECT
        if not goal.axes and len(goal.position) != 4:
            self.get_logger().warn("move_to: with no axes, give four positions (M1X, M1Y, M2X, M2Y)")
            return GoalResponse.REJECT
        if self.ctl is None or self.ctl.aligning:
            return GoalResponse.REJECT
        return GoalResponse.ACCEPT

    def run_move(self, handle):
        from bench_link import AXES

        g = handle.request
        axes = list(g.axes) or list(AXES)
        abort = threading.Event()
        self._move_aborts.add(abort)
        result = MoveTo.Result()

        def progress(pos):
            if handle.is_cancel_requested:
                abort.set()
            fb = MoveTo.Feedback()
            fb.position = list(pos)
            handle.publish_feedback(fb)

        try:
            pos, limited = self._need().move_to(dict(zip(axes, g.position)), relative=g.relative,
                                                speed_rpm=g.speed_rpm, abort=abort, on_progress=progress)
            result.position = list(pos)
            result.hit_limit = [bool(limited.get(a.upper(), False)) for a in axes]
            handle.succeed()
        except self.ControllerError as e:
            self.get_logger().warn(f"move_to: {e}")
            if self._last_status:
                result.position = list(self._last_status.position)
            self._end(handle, abort.is_set() and handle.is_cancel_requested)
        finally:
            self._move_aborts.discard(abort)
        return result

    def accept_align(self, goal):
        if goal.fiber and goal.fiber not in self.FIBERS:
            self.get_logger().warn(f"align: fiber must be one of {', '.join(self.FIBERS)}")
            return GoalResponse.REJECT
        if self.ctl is None or self.ctl.aligning or self._move_aborts:
            return GoalResponse.REJECT       # one goal at a time owns the motors
        return GoalResponse.ACCEPT

    def run_align(self, handle):
        g = handle.request
        result = Align.Result()
        if g.fiber and g.fiber != self.fiber:
            self.fiber = g.fiber
            if self.port == "sim":
                self._need().request(f"SIM FIBER {g.fiber}")
        abort = threading.Event()
        self._align_abort = abort
        stop_watch = threading.Event()

        def watch_cancel():
            while not stop_watch.wait(0.1):
                if handle.is_cancel_requested:
                    abort.set()
                    return

        threading.Thread(target=watch_cancel, daemon=True).start()

        def say(text):
            self.get_logger().info(f"align: {text}")
            fb = Align.Feedback()
            fb.stage = text
            fb.ratio = float(self._last_ratio)
            if self._last_status:
                fb.position = list(self._last_status.position)
            handle.publish_feedback(fb)

        try:
            res, frac = self._need().align(self.fiber, self.calibration, recalibrate=g.recalibrate, say=say,
                                           abort=abort, pd_stream_hz=self.pd_hz)
            result.success = bool(res.ok)
            result.found_light = bool(res.found)
            result.ratio, result.fraction_of_peak = float(res.ratio), float(frac)
            result.seconds, result.moves, result.reads = float(res.seconds), int(res.moves), int(res.reads)
            result.message = ("no light found within the search range: get some light on the output "
                              "photodiode by hand and try again" if not res.found else
                              f"ratio {res.ratio:.4f}, {frac:.1%} of the calibrated peak, {res.seconds:.1f} s")
            say(result.message)
            handle.succeed()
        except self.ControllerError as e:
            result.message = str(e)
            self.get_logger().warn(f"align: {e}")
            self._end(handle, abort.is_set() and handle.is_cancel_requested)
        finally:
            stop_watch.set()
            self._align_abort = None
        return result

    def _end(self, handle, cancelled):
        try:
            handle.canceled() if cancelled else handle.abort()
        except Exception as e:          # shutting down: the action server is already gone
            self.get_logger().debug(f"goal end: {e}")

    def destroy_node(self):
        if self.ctl is not None:
            self.ctl.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = BenchDriver()
    executor = MultiThreadedExecutor(num_threads=max(4, (os.cpu_count() or 4)))
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
