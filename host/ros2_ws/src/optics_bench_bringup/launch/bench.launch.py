"""The bench: the controller driver, and optionally the camera.

    ros2 launch optics_bench_bringup bench.launch.py                         # simulator
    ros2 launch optics_bench_bringup bench.launch.py port:=/dev/optics_bench # the ESP32
    ros2 launch optics_bench_bringup bench.launch.py camera:=true
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory("optics_bench_bringup")
    return LaunchDescription([
        DeclareLaunchArgument("port", default_value="sim",
                              description="sim for the bench twin, or the ESP32's serial port, e.g. /dev/optics_bench"),
        DeclareLaunchArgument("sim_fiber", default_value="mm50", description="mm50, smf28 or sm630"),
        DeclareLaunchArgument("calibration_file", default_value="~/.ros/optics_bench/align_calibration.json",
                              description="where the aligner keeps its per-fiber calibration"),
        DeclareLaunchArgument("camera", default_value="false", description="also start the OV9281 and beam_spot"),
        Node(
            package="optics_bench_driver",
            executable="bench_driver",
            namespace="bench",
            name="bench_driver",
            output="screen",
            parameters=[os.path.join(share, "config", "bench.yaml"), {
                "port": LaunchConfiguration("port"),
                "sim_fiber": LaunchConfiguration("sim_fiber"),
                "calibration_file": LaunchConfiguration("calibration_file"),
            }],
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(share, "launch", "camera.launch.py")),
            condition=IfCondition(LaunchConfiguration("camera")),
        ),
    ])
