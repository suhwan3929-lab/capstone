#!/usr/bin/env python3
"""
Jetson: ROS 2 LiDAR 브리지 노드

역할
    Cygbot 공식 ROS 2 드라이버가 발행하는 토픽을 구독해서
    관심영역(ROI) 안의 최근접 거리만 뽑아 Pi로 UDP 전송한다.

왜 이렇게 하는가
    * 프레임 파싱은 **벤더 드라이버에게 맡긴다.** 직접 파싱하면
      payload 오프셋·비트폭을 추측하게 되고, 틀려도 '그럴듯한 숫자'가 나와
      틀린 줄 모른다. (코드_리뷰.md §1.4)
    * Pi로 넘기는 데이터는 float 2개뿐이므로 DDS를 Pi까지 끌고 갈 이유가 없다.
    * 이 노드가 죽어도 Pi의 전도 감지는 계속 동작한다.

실행
    ros2 run walker_lidar lidar_bridge_node --ros-args \
        -p pi_host:=192.168.10.2 -p left_topic:=/cygbot_left/scan

⚠ 토픽 이름과 메시지 타입은 벤더 드라이버 버전에 따라 다르다.
  `ros2 topic list` / `ros2 topic info <topic>` 으로 확인해 파라미터로 넘길 것.
  LaserScan과 PointCloud2를 모두 지원한다.
"""
import json
import socket
import time

import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.qos import (QoSDurabilityPolicy, QoSHistoryPolicy, QoSProfile,
                       QoSReliabilityPolicy)
from sensor_msgs.msg import LaserScan, PointCloud2
from sensor_msgs_py import point_cloud2

SCHEMA_VERSION = 1

#: 점군은 최신 프레임만 의미가 있다 → BEST_EFFORT / depth 1
SENSOR_QOS = QoSProfile(
    reliability=QoSReliabilityPolicy.BEST_EFFORT,
    history=QoSHistoryPolicy.KEEP_LAST,
    durability=QoSDurabilityPolicy.VOLATILE,
    depth=1,
)


class LidarBridge(Node):
    def __init__(self):
        super().__init__("lidar_bridge")

        p = self.declare_parameter
        p("pi_host", "192.168.10.2")
        p("pi_port", 9100)
        p("send_hz", 20.0)
        p("left_topic", "/cygbot_left/scan")
        p("right_topic", "/cygbot_right/scan")
        p("msg_type", "LaserScan")          # LaserScan | PointCloud2
        # ROI — 바닥과 보행기 자체 프레임을 걸러낸다 (코드_리뷰.md §2.4)
        p("roi_fov_deg", 80.0)              # 정면 ±40°
        p("roi_z_min", -0.30)               # 지면 평면 아래는 무시
        p("roi_z_max", 1.20)
        p("min_valid_m", 0.10)
        p("max_valid_m", 8.00)
        p("percentile", 5.0)                # 최솟값 대신 하위 N퍼센타일
        p("stale_sec", 0.5)
        # 단차(턱) 감지 — 지면 평면 기준 편차
        p("curb_drop_m", 0.05)              # 이만큼 낮으면 '내려가는 턱'
        p("curb_rise_m", 0.04)              # 이만큼 높으면 '올라가는 턱'
        p("curb_warn_m", 1.20)

        g = lambda k: self.get_parameter(k).value      # noqa: E731
        self.addr = (g("pi_host"), int(g("pi_port")))
        self.roi_fov = float(g("roi_fov_deg"))
        self.z_min, self.z_max = float(g("roi_z_min")), float(g("roi_z_max"))
        self.d_min, self.d_max = float(g("min_valid_m")), float(g("max_valid_m"))
        self.pct = float(g("percentile"))
        self.stale = float(g("stale_sec"))
        self.curb_drop = float(g("curb_drop_m"))
        self.curb_rise = float(g("curb_rise_m"))
        self.curb_warn = float(g("curb_warn_m"))

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.seq = 0
        self.side = {"left": (None, 0.0), "right": (None, 0.0)}
        self.curb = {"left": (None, "", 0.0), "right": (None, "", 0.0)}

        msg_cls = PointCloud2 if g("msg_type") == "PointCloud2" else LaserScan
        cb = self._on_cloud if msg_cls is PointCloud2 else self._on_scan
        for name, topic in (("left", g("left_topic")), ("right", g("right_topic"))):
            self.create_subscription(
                msg_cls, topic,
                (lambda s: lambda m: cb(s, m))(name), SENSOR_QOS)
            self.get_logger().info(f"구독: {topic} ({msg_cls.__name__}) → {name}")

        self.create_timer(1.0 / float(g("send_hz")), self._send)
        self.get_logger().info(f"UDP 송신 대상: {self.addr[0]}:{self.addr[1]}")

    # ────────────────────────────────────── 콜백
    def _on_scan(self, side, msg: LaserScan):
        r = np.asarray(msg.ranges, dtype=np.float32)
        if r.size == 0:
            return
        ang = msg.angle_min + np.arange(r.size, dtype=np.float32) * msg.angle_increment
        half = np.deg2rad(self.roi_fov / 2.0)
        keep = (np.abs(ang) <= half) & np.isfinite(r) & \
               (r >= self.d_min) & (r <= self.d_max)
        self._store(side, r[keep])

    def _on_cloud(self, side, msg: PointCloud2):
        pts = point_cloud2.read_points_numpy(
            msg, field_names=("x", "y", "z"), skip_nans=True)
        if pts.size == 0:
            return
        x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
        d = np.hypot(x, y)                       # 수평 거리
        ang = np.arctan2(y, x)
        half = np.deg2rad(self.roi_fov / 2.0)
        in_fov = (np.abs(ang) <= half) & (d >= self.d_min) & (d <= self.d_max)

        # 장애물: 지면보다 위에 있는 것들
        keep = in_fov & (z >= self.z_min) & (z <= self.z_max)
        self._store(side, d[keep])

        # 단차: 지면 자체를 본다
        self._detect_curb(side, d[in_fov], z[in_fov])

    def _store(self, side, valid):
        dist = float(np.percentile(valid, self.pct)) if valid.size else None
        self.side[side] = (dist, time.time())

    # ────────────────────────────────────── 단차(턱) 감지
    def _detect_curb(self, side, d, z):
        """
        기획 배경의 "턱 걸림"에 대응한다.

        전방을 수평으로 보는 LiDAR는 바닥 단차를 볼 수 없다.
        센서를 아래로 틸트해서 전방 바닥면이 화각에 들어오게 한 뒤,
        **가까운 구간의 바닥 높이를 기준 평면으로 삼고**
        먼 구간이 그 평면에서 얼마나 벗어나는지를 본다.

            평면보다 낮다  → 내려가는 턱 (drop) — 가장 위험하다
            평면보다 높다  → 올라가는 턱 (rise) — 걸려 넘어진다

        ⚠ 이 방식은 센서가 아래로 10~20° 틸트되어 있고
          바닥이 화각에 충분히 들어와야 동작한다. 장착 각도가 전제다.
        ⚠ 지면이 젖어 있거나 검은 아스팔트면 ToF 반사가 약해 점이 사라진다.
          '점이 없는 것'과 '낭떠러지'를 구분하지 못한다는 한계를 명시할 것.
        """
        if d.size < 60:
            self.curb[side] = (None, "", time.time())
            return

        near = z[d < 0.6]                    # 발 앞 — 기준 평면
        if near.size < 20:
            self.curb[side] = (None, "", time.time())
            return
        ground = float(np.median(near))

        far_mask = (d >= 0.6) & (d <= self.curb_warn)
        if far_mask.sum() < 20:
            self.curb[side] = (None, "", time.time())
            return

        dz = z[far_mask] - ground
        dd = d[far_mask]

        drop = dz < -self.curb_drop
        rise = dz > self.curb_rise

        # 산발적인 점 몇 개는 노이즈다. 일정 비율 이상 뭉쳐 있어야 인정한다.
        best = (None, "")
        if drop.sum() >= 12:
            best = (float(np.percentile(dd[drop], 10)), "drop")
        if rise.sum() >= 12:
            r = float(np.percentile(dd[rise], 10))
            # 더 가까운 쪽을 보고한다. 내려가는 턱이 더 위험하므로 동률이면 drop.
            if best[0] is None or r < best[0] - 0.05:
                best = (r, "rise")
        self.curb[side] = (best[0], best[1], time.time())

    # ────────────────────────────────────── 송신
    def _send(self):
        """데이터가 없어도 매 주기 보낸다 — 패킷 자체가 하트비트다."""
        self.seq += 1
        now = time.time()
        body = {}
        for name in ("left", "right"):
            dist, t = self.side[name]
            fresh = bool(t) and (now - t) <= self.stale
            body[name] = {"d": dist if fresh else None, "ok": fresh}

        # 좌우 중 더 가까운 단차를 보고한다
        curb_m, curb_type = None, ""
        for name in ("left", "right"):
            cm, ct, ct_t = self.curb[name]
            if cm is None or not ct_t or (now - ct_t) > self.stale:
                continue
            if curb_m is None or cm < curb_m:
                curb_m, curb_type = cm, ct

        pkt = {"v": SCHEMA_VERSION, "seq": self.seq, "t": now,
               "curb_m": curb_m, "curb_type": curb_type, **body}
        try:
            self.sock.sendto(json.dumps(pkt).encode("utf-8"), self.addr)
        except OSError:
            pass          # 네트워크 일시 장애로 노드가 죽지 않는다


def main():
    rclpy.init()
    node = LidarBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
