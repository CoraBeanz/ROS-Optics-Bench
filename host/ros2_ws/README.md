# ROS 2 workspace (Jetson)

ROS 2 Humble packages that run the bench from the Jetson. The ESP32 keeps the real-time work (stepping, soft limits, photodiode sampling); the Jetson talks to it over USB serial with the same text protocol as `tools/test_gui.py`, and adds the camera and the alignment routine.

| Package | What it does |
| --- | --- |
| `optics_bench_interfaces` | Messages, services and actions below |
| `optics_bench_driver` | `bench_driver` node: the ESP32 (or the simulator) as ROS topics, services and actions, including auto-align |
| `optics_bench_camera` | `beam_spot` node: where the laser spot is on the OV9281, for phase 1 |
| `optics_bench_bringup` | Launch files, parameters and a udev rule for the Feather |

The driver doesn't copy the bench code: it imports `tools/bench_link.py` (serial and simulator links) and `tools/bench_twin` (the auto-align routine and the simulator) from this repo, so the GUI and ROS always run the same alignment. Build the workspace where it is, inside the repo.

## Setting up the Jetson

JetPack 6 is Ubuntu 22.04, which is what ROS 2 Humble targets. (JetPack 5 is Ubuntu 20.04, which Humble doesn't support from apt; ask before going that way.)

1. Install ROS 2 Humble (`ros-humble-ros-base` is enough) by following the [Humble install guide](https://docs.ros.org/en/humble/Installation/Ubuntu-Install-Debs.html), then:
   ```
   sudo apt install python3-colcon-common-extensions python3-rosdep ros-humble-v4l2-camera python3-serial python3-numpy
   sudo rosdep init && rosdep update      # once
   ```
2. Let your user open the serial port and give the Feather a fixed name:
   ```
   sudo usermod -aG dialout $USER        # log out and back in
   sudo cp host/ros2_ws/src/optics_bench_bringup/udev/99-optics-bench.rules /etc/udev/rules.d/
   sudo udevadm control --reload && sudo udevadm trigger
   ```
   The Feather then shows up as `/dev/optics_bench`.
3. Build:
   ```
   cd host/ros2_ws
   source /opt/ros/humble/setup.bash
   rosdep install --from-paths src --ignore-src -y
   colcon build --symlink-install
   source install/setup.bash
   ```

## Running

```
ros2 launch optics_bench_bringup bench.launch.py                          # the simulator (bench twin)
ros2 launch optics_bench_bringup bench.launch.py port:=/dev/optics_bench  # the ESP32
ros2 launch optics_bench_bringup bench.launch.py port:=/dev/optics_bench camera:=true
```

Everything is under `/bench`:

| Name | Type | |
| --- | --- | --- |
| `/bench/status` | topic, `BenchStatus` | motor positions and targets, laser, coils, drivers (5 Hz) |
| `/bench/photodiodes` | topic, `Photodiodes` | reference and output volts and the out/ref ratio (10 Hz, more often while aligning) |
| `/bench/rx` | topic, `std_msgs/String` | every line the ESP32 sends |
| `/bench/command` | service, `Command` | any protocol line, e.g. `ZERO ALL`, `PD RANGE AUTO`, `SIM KNOCK M1 1` |
| `/bench/laser` | service, `std_srvs/SetBool` | laser on or off |
| `/bench/stop` | service, `std_srvs/Trigger` | stops every motor and any alignment |
| `/bench/pd_dark` | service, `std_srvs/Trigger` | measure and subtract the photodiode dark offsets |
| `/bench/move_to` | action, `MoveTo` | absolute or relative moves in microsteps |
| `/bench/align` | action, `Align` | find the light and peak the ratio |

Try it on the simulator:

```
ros2 service call /bench/laser std_srvs/srv/SetBool "{data: true}"
ros2 action send_goal /bench/move_to optics_bench_interfaces/action/MoveTo "{axes: [M2X], position: [300]}"
ros2 action send_goal --feedback /bench/align optics_bench_interfaces/action/Align "{fiber: mm50}"
ros2 service call /bench/command optics_bench_interfaces/srv/Command "{line: 'SIM KNOCK M2 1.5'}"
ros2 action send_goal /bench/align optics_bench_interfaces/action/Align "{}"
ros2 topic echo /bench/photodiodes
```

The first Align for a fiber finds light, measures the walk directions and records the peak ratio; that calibration is saved to `~/.ros/optics_bench/align_calibration.json`, so after a restart Align goes straight to recovering. Set `recalibrate: true` in the goal after changing the optics. While Align runs, the other services refuse to move anything; `/bench/stop` or cancelling the goal ends it.

## Camera

`beam_spot` takes `/camera/image_raw` from `v4l2_camera` and publishes `/camera/beam_spot` (`BeamSpot`): the spot's centroid and widths in pixels, its peak brightness, and whether it is saturated. Its settings and the camera's are in `optics_bench_bringup/config/camera.yaml`. It has only been run on synthetic frames so far. With the OV9281 plugged in, check what it offers with `v4l2-ctl --list-formats-ext -d /dev/video0` and set `image_size` and `pixel_format` to match.

## Tests

```
colcon test && colcon test-result --verbose
```

They run the driver against the simulator through its services and actions (about a minute), and the spot finder on synthetic frames. `tools/tests` covers the bench twin and the aligner on their own.
