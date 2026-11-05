"""ROS 없이 실제 브리지 콜백과 그림 데이터의 신선도/호환성을 검증한다."""
import ast
import json
import math
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import time

import numpy as np
import config
import ui
from schema import ObstacleReport, SystemStatus
from sensors import lidar_udp, sim


def bridge():
    # ROS import/Node 초기화만 생략하고 실제 함수/클래스 본문을 실행한다.
    path = Path(__file__).resolve().parents[1] / "jetson" / "lidar_bridge_node.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    def read_points(msg, **kwargs):
        if msg.points.dtype.names:
            return msg.points[list(kwargs["field_names"])]
        return np.rec.fromarrays(msg.points.reshape(-1, 3).T, names="x,y,z")

    ns = dict(np=np, time=time, json=json, socket=SimpleNamespace(), Node=object,
              LaserScan=object, PointCloud2=object, PREVIEW_BINS=32, SCHEMA_VERSION=1,
              point_cloud2=SimpleNamespace(read_points=read_points,
                                          read_points_numpy=lambda msg, **kw: msg.points))
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), ns)
    node = ns["LidarBridge"].__new__(ns["LidarBridge"])
    node.roi_fov, node.d_min, node.d_max = 80, 0.1, 8.0
    node.z_min, node.z_max, node.pct, node.stale = -0.3, 1.2, 5, 0.5
    node.side = {"left": (None, 0.0), "right": (None, 0.0)}
    node.preview = {"left": None, "right": None}
    node.curb = {"left": (None, "", 0.0), "right": (None, "", 0.0)}
    node.sock, node.addr, node.seq = Mock(), ("127.0.0.1", 9100), 0
    node.session = "bridge-a"
    return node, ns["preview_xy"]


def test_scan_projects_real_angles_and_keeps_scalar_distance():
    node, _ = bridge()
    node._on_scan("left", SimpleNamespace(ranges=[2, 1, float("inf"), 0.05, 3],
                                          angle_min=-0.4, angle_increment=0.2))
    points = node.preview["left"]
    assert len(points) == 3
    assert any(abs(x - math.cos(-0.2)) < 0.001 and y < 0 for x, y in points)
    assert abs(node.side["left"][0] - 1.1) < 1e-5


def test_cloud_preview_uses_existing_roi_and_height_filter():
    node, _ = bridge()
    node._on_cloud("left", SimpleNamespace(points=np.array(
        [[1, 0.2, 0.5], [2, -0.3, 0], [1, 0, 2], [-1, 0, 0], [9, 0, 0]])))
    assert node.preview["left"] == [[2.0, -0.3], [1.0, 0.2]]


def test_cloud_bridge_accepts_mixed_records_without_changing_roi_or_distance():
    records = np.zeros(3, dtype=[("rgba", "u4"), ("z", "f4"),
                                 ("x", "f4"), ("y", "f4")])
    records["rgba"] = 0xffabcdef
    records["x"], records["z"] = [1, 2, 3], [0, 2, -2]
    node, _ = bridge()
    node._on_cloud("left", SimpleNamespace(points=records))
    assert node.preview["left"] == [[1.0, 0.0]]
    assert node.side["left"][0] == 1.0
    node._on_cloud("left", SimpleNamespace(points=records[:0]))
    assert node.preview["left"] == [] and node.side["left"][0] is None


def test_empty_scan_clears_previous_contour_without_reporting_sensor_failure():
    node, _ = bridge()
    node._store("left", np.array([1]), [[1, 0]])
    node._on_scan("left", SimpleNamespace(ranges=[]))
    node._send()
    packet = json.loads(node.sock.sendto.call_args.args[0])
    assert packet["left"] == {"d": None, "ok": True, "points_xy": []}


def test_preview_preserves_nearest_point_in_each_bin_and_bounds_payload():
    node, sample = bridge()
    angles = np.linspace(-math.radians(40), math.radians(40), 5000)
    distance = np.full(angles.shape, 8.0)
    distance[2500] = 0.25
    points = sample(distance * np.cos(angles), distance * np.sin(angles), math.radians(40))
    assert len(points) == 32 and [0.25, 0.0] in points
    for side in ("left", "right"):
        node._store(side, np.array([0.25]), points)
    node._send()
    assert len(node.sock.sendto.call_args.args[0]) < 1400


def test_stale_bridge_hides_distance_and_points_together():
    node, _ = bridge()
    node._store("left", np.array([1.0]), [[1, 0]])
    node.side["left"] = (1.0, time.time() - 10)
    node._send()
    assert json.loads(node.sock.sendto.call_args.args[0])["left"] == {
        "d": None, "ok": False, "points_xy": None}


def test_receiver_clears_link_and_failed_sensor_preview():
    saved = dict(lidar_udp._state)
    try:
        lidar_udp._state.update(arrived=time.monotonic(), left_ok=False, right_ok=True,
                                left_points_xy=[[1, 0]], right_points_xy=[[2, 0]])
        report = lidar_udp.snapshot()
        assert report.left_points_xy is None and report.right_points_xy == [[2, 0]]
        lidar_udp._state["arrived"] = time.monotonic() - 10
        report = lidar_udp.snapshot()
        assert report.left_points_xy is None and report.right_points_xy is None
    finally:
        lidar_udp._state.clear()
        lidar_udp._state.update(saved)


def test_optional_preview_rejects_malformed_points_without_touching_distances():
    assert lidar_udp.clean_preview(None) is None
    assert lidar_udp.clean_preview([]) == []
    assert lidar_udp.clean_preview([[float("nan"), 0], [1], ["bad", 1], [-1, 0]]) is None
    assert lidar_udp.clean_preview([[1, -0.2], [float("inf"), 1]]) == [[1, -0.2]]
    assert len(lidar_udp.clean_preview([[1, 0]] * 100)) == 32


def test_old_and_new_status_packets_roundtrip():
    assert SystemStatus.from_dict({"obstacle": {"left_m": 1.2}}).obstacle.left_points_xy is None
    report = ObstacleReport(left_m=1.2, left_points_xy=[[1.2, 0.1]],
                            right_points_xy=[], preview_simulated=True)
    back = SystemStatus.from_dict(json.loads(json.dumps(SystemStatus(obstacle=report).to_dict())))
    assert back.obstacle == report


def test_udp_optional_field_handles_old_bridge_and_corrupt_preview():
    saved = dict(lidar_udp._state)
    running = lidar_udp._running
    packets = []
    socket = Mock()

    def receive(_size):
        packet = packets.pop(0)
        lidar_udp._running = False
        return json.dumps(packet).encode(), ("127.0.0.1", 9100)

    socket.recvfrom.side_effect = receive
    try:
        with patch.object(lidar_udp.socket, "socket", return_value=socket):
            for preview in ([[1.2, 0.3]], [["bad", 0]], "missing"):
                side = {"d": 1.2, "ok": True}
                if preview != "missing":
                    side["points_xy"] = preview
                packets.append({"v": config.SCHEMA_VERSION, "seq": lidar_udp._state["seq"] + 1,
                                "t": time.time(), "left": side, "right": side})
                lidar_udp._running = True
                lidar_udp._rx_loop()
                report = lidar_udp.snapshot()
                assert report.left_m == 1.2 and report.link_ok
                assert report.left_points_xy == (preview if preview == [[1.2, 0.3]] else None)
    finally:
        lidar_udp._running = running
        lidar_udp._state.clear()
        lidar_udp._state.update(saved)


def test_canvas_places_sensor_left_to_screen_left_and_clears_lost_scan():
    view = ui.LidarPreview.__new__(ui.LidarPreview)
    for name in ("delete", "create_text", "create_arc", "create_line", "create_polygon",
                 "create_oval", "create_rectangle"):
        setattr(view, name, Mock())
    view.winfo_width = lambda: 300
    view.winfo_height = lambda: 172
    view._data = ([[1, 0.5]], True, True, False)
    view._draw()
    assert view.create_oval.call_args.args[0] < 150
    view.create_oval.reset_mock()
    view.update_scan([[1, 0.5]], True, False)
    view.delete.assert_called_with("all")
    view.create_oval.assert_not_called()
    assert "연결 끊김" in view.create_text.call_args.kwargs["text"]


def test_monitor_link_loss_clears_cards_and_curb_notice():
    dashboard = ui.Dashboard.__new__(ui.Dashboard)
    for name in ("clock", "sub", "lidar_l", "lidar_r", "curb_lbl", "overall", "batt",
                 "health_lbl", "root", "term", "imu_card", "gps_card",
                 "sos_button", "sos_status", "summary_imu", "summary_gps",
                 "_update_recovery", "_set_flash"):
        setattr(dashboard, name, Mock())
    dashboard._popup = None
    dashboard.sub.latest.return_value = (SystemStatus(), False)
    dashboard._link_warned = False
    dashboard._refresh()
    dashboard.lidar_l.update_card.assert_called_once_with(None, False, False)
    dashboard.lidar_r.update_card.assert_called_once_with(None, False, False)
    dashboard.curb_lbl.config.assert_called_once_with(text="")


def test_simulated_preview_is_explicit_and_no_returns_stays_empty():
    assert sim.preview_points(None) == []
    assert min(x for x, y in sim.preview_points(0.7)) == 0.7
