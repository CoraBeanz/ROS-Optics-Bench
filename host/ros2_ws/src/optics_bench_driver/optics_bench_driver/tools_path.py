"""Find the repo's tools/ folder, which holds the serial and simulator links
(bench_link.py) and the bench twin with the auto-align routine (bench_twin/).

The ROS packages use that code as it is rather than keeping a copy. The
workspace lives in the repo (host/ros2_ws), so the folder is found by walking
up from this file, which works for both `colcon build` and
`colcon build --symlink-install`. Set the OPTICS_BENCH_TOOLS environment
variable (or the driver's tools_dir parameter) to use another checkout.
"""

import os
import sys


def _looks_right(d):
    return os.path.isfile(os.path.join(d, "bench_link.py")) and os.path.isdir(os.path.join(d, "bench_twin"))


def find_tools(override=""):
    candidates = [override, os.environ.get("OPTICS_BENCH_TOOLS", "")]
    d = os.path.dirname(os.path.realpath(__file__))
    while True:
        candidates.append(os.path.join(d, "tools"))
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    for c in candidates:
        if c and _looks_right(c):
            return os.path.abspath(c)
    raise RuntimeError("can't find the repo's tools/ folder (bench_link.py, bench_twin/): build the workspace "
                       "inside the repo, or set OPTICS_BENCH_TOOLS to the tools folder")


def add_tools_to_path(override=""):
    d = find_tools(override)
    if d not in sys.path:
        sys.path.insert(0, d)
    return d
