"""Publishes where the laser spot is on the camera (phase 1: steering the beam
onto a known axis by spot position).

Subscribes to image_raw (sensor_msgs/Image from any camera driver; the launch
file starts v4l2_camera for the OV9281) and publishes
optics_bench_interfaces/BeamSpot on beam_spot.

Parameters: threshold (0-1 of the way from background to peak, default 0.25),
min_peak (0-1 of full scale above background, default 0.05), every_nth (only
look at every n-th frame, default 1).
"""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image

from optics_bench_interfaces.msg import BeamSpot

from .spot import find_spot, image_to_array


class BeamSpotNode(Node):
    def __init__(self):
        super().__init__("beam_spot")
        self.declare_parameter("threshold", 0.25)
        self.declare_parameter("min_peak", 0.05)
        self.declare_parameter("every_nth", 1)
        self.n = 0
        self.pub = self.create_publisher(BeamSpot, "beam_spot", 10)
        self.create_subscription(Image, "image_raw", self.on_image, qos_profile_sensor_data)

    def on_image(self, msg):
        self.n += 1
        if self.n % max(1, self.get_parameter("every_nth").value):
            return
        try:
            img, full = image_to_array(msg)
        except ValueError as e:
            self.get_logger().error(str(e), throttle_duration_sec=10.0)
            return
        s = find_spot(img, full, self.get_parameter("threshold").value, self.get_parameter("min_peak").value)
        out = BeamSpot()
        out.header = msg.header
        out.found = s.found
        out.x, out.y, out.sigma_x, out.sigma_y, out.angle = s.x, s.y, s.sigma_x, s.sigma_y, s.angle
        out.peak, out.pixels, out.saturated = s.peak, s.pixels, s.saturated
        self.pub.publish(out)
        if s.saturated:
            self.get_logger().warn("spot is saturated: lower the exposure or the laser", throttle_duration_sec=10.0)


def main(args=None):
    rclpy.init(args=args)
    node = BeamSpotNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == "__main__":
    main()
