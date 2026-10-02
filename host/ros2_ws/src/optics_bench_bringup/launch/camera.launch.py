"""The OV9281 through v4l2_camera, and the beam_spot node on its images.

    ros2 launch optics_bench_bringup camera.launch.py [video_device:=/dev/video1]
"""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    params = os.path.join(get_package_share_directory("optics_bench_bringup"), "config", "camera.yaml")
    return LaunchDescription([
        DeclareLaunchArgument("video_device", default_value="/dev/video0"),
        Node(
            package="v4l2_camera",
            executable="v4l2_camera_node",
            namespace="camera",
            name="v4l2_camera",
            output="screen",
            parameters=[params, {"video_device": LaunchConfiguration("video_device")}],
        ),
        Node(
            package="optics_bench_camera",
            executable="beam_spot",
            namespace="camera",
            name="beam_spot",
            output="screen",
            parameters=[params],
        ),
    ])
