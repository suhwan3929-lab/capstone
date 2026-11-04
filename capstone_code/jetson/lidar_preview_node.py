#!/usr/bin/env python3
"""Separate ROS process for display-only 3D. The distance bridge stays on LaserScan."""
import secrets
import socket
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSDurabilityPolicy
from sensor_msgs.msg import PointCloud2
from sensor_msgs_py import point_cloud2

from walker_preview.protocol import PORT, encode_frame_chunks
from walker_preview.sampling import full_xyz

SENSOR_QOS = QoSProfile(depth=1, reliability=QoSReliabilityPolicy.BEST_EFFORT,
                        durability=QoSDurabilityPolicy.VOLATILE)


class LidarPreviewNode(Node):
    def __init__(self):
        super().__init__("lidar_preview_3d")
        p = self.declare_parameter
        p("pi_host", "192.168.10.2")
        p("preview_port", PORT)
        p("preview_hz", 10.0)
        p("left_cloud_topic", "/cygbot_left/scan_3D")
        p("right_cloud_topic", "/cygbot_right/scan_3D")
        p("coordinate_profile", "cyglidar_d2")
        g = lambda key: self.get_parameter(key).value
        self.profile = g("coordinate_profile")
        if self.profile not in ("cyglidar_d2", "ros_optical"):
            raise ValueError("Unsupported coordinate_profile")
        hz = float(g("preview_hz"))
        if not 0 < hz <= 10:
            raise ValueError("preview_hz must be in (0, 10]")
        self.addr = (g("pi_host"), int(g("preview_port")))
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.session = secrets.randbits(64)
        self.pending = {}
        self.last_capture = {}
        self.sequence = {"left": 0, "right": 0}
        self._last_error = 0.0
        for side, key in (("left", "left_cloud_topic"), ("right", "right_cloud_topic")):
            topic = g(key)
            self.create_subscription(PointCloud2, topic,
                lambda msg, side=side: self._receive(side, msg), SENSOR_QOS)
            self.get_logger().info(f"3D display: {topic} -> {side}, axes={self.profile}")
        self.create_timer(1.0 / hz, self._send_latest)

    def _receive(self, side, msg):
        # ROS's single-threaded executor replaces any waiting cloud with the latest one.
        self.pending[side] = (msg, time.monotonic())

    def _send_latest(self):
        for side in ("left", "right"):
            item = self.pending.pop(side, None)
            if item is None or time.monotonic() - item[1] >= 0.5:
                continue
            msg = item[0]
            capture = int(msg.header.stamp.sec) * 1_000_000_000 + int(msg.header.stamp.nanosec)
            if capture < 0 or (capture != 0 and self.last_capture.get(side) == capture):
                continue
            try:
                points = point_cloud2.read_points_numpy(msg, field_names=("x", "y", "z"),
                                                       skip_nans=True)
                points_mm = full_xyz(points, self.profile)
                sequence = (self.sequence[side] + 1) & 0xffffffff
                # Never reuse an identifier after a partially sent frame.
                self.sequence[side] = sequence
                packets = encode_frame_chunks(side, self.session, sequence, capture, points_mm)
                for packet in packets:
                    self.sock.sendto(packet, self.addr)
                self.last_capture[side] = capture
            except (OSError, ValueError, TypeError, OverflowError, AssertionError) as exc:
                # An optional display failure must not stop either sensor's safety stream.
                now = time.monotonic()
                if now - self._last_error >= 2:
                    self.get_logger().warning(f"3D display frame skipped: {exc}")
                    self._last_error = now

    def destroy_node(self):
        self.sock.close()
        return super().destroy_node()


def main():
    rclpy.init()
    node = None
    try:
        node = LidarPreviewNode()
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
