"""The driver node on the simulator, through its ROS services and actions."""

import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy")

from rclpy.action import ActionClient  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from std_srvs.srv import SetBool, Trigger  # noqa: E402

from optics_bench_interfaces.action import Align, MoveTo  # noqa: E402
from optics_bench_interfaces.msg import BenchStatus  # noqa: E402
from optics_bench_interfaces.srv import Command  # noqa: E402


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    from optics_bench_driver.driver_node import BenchDriver

    rclpy.init()
    cal = tmp_path_factory.mktemp("cal") / "cal.json"
    driver = BenchDriver(parameter_overrides=[Parameter("sim_seed", value=5),
                                              Parameter("calibration_file", value=str(cal))])
    client = rclpy.create_node("test_client")
    ex = MultiThreadedExecutor(num_threads=6)
    ex.add_node(driver)
    ex.add_node(client)
    threading.Thread(target=ex.spin, daemon=True).start()
    yield driver, client
    ex.shutdown()
    driver.destroy_node()
    client.destroy_node()
    rclpy.try_shutdown()


def call(node, srv_type, name, req, timeout=10.0):
    cli = node.create_client(srv_type, name)
    assert cli.wait_for_service(timeout_sec=5.0)
    fut = cli.call_async(req)
    deadline = time.monotonic() + timeout
    while not fut.done() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert fut.done(), f"{name} didn't answer"
    return fut.result()


def run_goal(node, action_type, name, goal, timeout=120.0, cancel_after=None):
    ac = ActionClient(node, action_type, name)
    assert ac.wait_for_server(timeout_sec=5.0)
    gf = ac.send_goal_async(goal)
    while not gf.done():
        time.sleep(0.02)
    handle = gf.result()
    assert handle.accepted
    if cancel_after is not None:
        time.sleep(cancel_after)
        handle.cancel_goal_async()
    rf = handle.get_result_async()
    deadline = time.monotonic() + timeout
    while not rf.done() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rf.done(), f"{name} didn't finish"
    return rf.result()


def test_status_topic(bench):
    _, client = bench
    got = []
    client.create_subscription(BenchStatus, "/status", got.append, 10)   # node runs without a namespace here
    deadline = time.monotonic() + 5
    while not got and time.monotonic() < deadline:
        time.sleep(0.05)
    assert got and got[-1].connected and list(got[-1].axes) == ["M1X", "M1Y", "M2X", "M2Y"]


def test_laser_and_command(bench):
    _, client = bench
    assert call(client, SetBool, "/laser", SetBool.Request(data=True)).success
    r = call(client, Command, "/command", Command.Request(line="SPEED ALL 120"))
    assert r.success and r.reply.startswith("OK SPEED")
    r = call(client, Command, "/command", Command.Request(line="GOTO M7X 1"))
    assert not r.success and "unknown axis" in r.reply


def test_move_to(bench):
    _, client = bench
    r = run_goal(client, MoveTo, "/move_to", MoveTo.Goal(axes=["M2X", "M1Y"], position=[300, -200]))
    assert r.status == 4                       # SUCCEEDED
    assert r.result.position[2] == 300 and r.result.position[1] == -200
    r = run_goal(client, MoveTo, "/move_to", MoveTo.Goal(axes=["M2X"], position=[-50], relative=True))
    assert r.result.position[2] == 250


def test_align_cancel_then_calibrate_and_recover(bench):
    driver, client = bench
    r = run_goal(client, Align, "/align", Align.Goal(fiber="mm50"), cancel_after=1.0)
    assert r.status == 5                       # CANCELED
    assert not driver.ctl.aligning
    # Back to where the simulated bench started, near the peak, for the full run
    assert run_goal(client, MoveTo, "/move_to", MoveTo.Goal(position=[0, 0, 0, 0])).status == 4
    r = run_goal(client, Align, "/align", Align.Goal(fiber="mm50"), timeout=180)
    assert r.status == 4 and r.result.success and r.result.found_light, r.result.message
    with driver.ctl.link.lock:
        driver.ctl.link.twin.knock(2, 1.0)
    r = run_goal(client, Align, "/align", Align.Goal(), timeout=180)
    assert r.result.success and r.result.fraction_of_peak > 0.9, r.result.message
    assert call(client, Trigger, "/stop", Trigger.Request()).success
