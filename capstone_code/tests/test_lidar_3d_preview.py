"""Wire, sensor sampling and GUI isolation checks without ROS or physical hardware."""
import ast
import math
from pathlib import Path
import socket
import struct
from types import SimpleNamespace
from unittest.mock import Mock
from unittest.mock import patch
import time

import numpy as np

from jetson.walker_preview import protocol as wire
from jetson.walker_preview.sampling import sample_xyz, normalize_xyz, full_xyz
from lidar_preview import PreviewReceiver, PreviewSnapshot
from lidar_preview_view import Lidar3DPreview, height_color, project_xyz
from tools.preview_lidar_3d import scene_points


def packet(sequence=1, session=10, side="left", points=((1000, 200, -450),)):
    return wire.encode_frame(side, session, sequence, 123456789, points)


def rejects(data):
    try:
        wire.decode_frame(data)
    except ValueError:
        return True
    return False


def test_preview_binary_roundtrip_bounds_and_empty():
    payload = packet(points=((1000, 200, -450),) * 192)
    assert len(payload) == 1182 and len(payload) <= 1200
    frame = wire.decode_frame(payload)
    assert frame.side == "left" and frame.points_mm[0] == (1000, 200, -450)
    assert frame.capture_ns == 123456789
    empty = wire.decode_frame(packet(points=()))
    assert empty.points_mm == ()
    simulated = wire.decode_frame(wire.encode_frame("right", 11, 2, 0, [], True))
    assert simulated.simulated and simulated.side == "right"


def test_preview_wire_rejects_truncated_oversized_unknown_and_inconsistent_frames():
    original = packet()
    assert rejects(original[:-1]) and rejects(original + b"x") and rejects(original * 100)
    for offset, value in ((0, 0), (4, 99), (5, 2), (6, 8), (7, 1)):
        data = bytearray(original)
        data[offset] = value
        assert rejects(data)
    data = bytearray(original)
    data[6] = wire.EMPTY  # Empty flag with a non-empty payload.
    assert rejects(data)
    data = bytearray(original)
    struct.pack_into("<h", data, wire.HEADER.size, -1000)
    assert rejects(data)
    assert rejects(original[:wire.HEADER.size] + wire.POINT.pack(3000, 0, 0))


def test_preview_sampler_retains_floor_and_rejects_bad_ranges():
    raw = [[1, .2, -.4], [1, -.2, .4], [0, 0, 0], [float("nan"), 0, 0],
           [float("inf"), 0, 0], [-1, 0, 0], [2.01, 0, 0], [.01, 0, 0]]
    sampled = sample_xyz(raw)
    assert sorted(sampled) == sorted([[1000, 200, -400], [1000, -200, 400]])
    assert sample_xyz([]) == []
    assert sample_xyz([[2, 0, 0], [.05, 0, 0]]) == [[50, 0, 0]]


def test_preview_sampler_preserves_vertical_cells_and_packet_budget():
    raw = []
    for elevation in np.linspace(-31, 31, 12):
        for azimuth in np.linspace(-58, 58, 16):
            a, e = np.deg2rad(azimuth), np.deg2rad(elevation)
            ray = [math.cos(e) * math.cos(a), math.cos(e) * math.sin(a), math.sin(e)]
            raw += [ray, [2 * v for v in ray]]
    sampled = sample_xyz(raw)
    assert len(sampled) == 192
    assert any(p[2] < -400 for p in sampled) and any(p[2] > 400 for p in sampled)
    assert len(packet(points=sampled)) <= wire.MAX_PACKET


def test_preview_coordinate_profiles_match_forward_left_up():
    assert np.array_equal(normalize_xyz([[1, .2, -.4]]), [[1, .2, -.4]])
    assert np.array_equal(normalize_xyz([[-.2, .4, 1]], "ros_optical"), [[1, .2, -.4]])
    assert project_xyz((1, .5, .2), "top")[:2] == (-.5, -1)
    assert project_xyz((1, .5, .2), "side")[:2] == (1, -.2)
    assert project_xyz((1, .5, .2), "front") == (.5, -.2, 1)
    assert project_xyz((1.8, .5, .2), "front")[:2] == (.5, -.2)
    assert height_color(-.5) != height_color(.5)


def test_front_canvas_mirrors_horizontal_movement_and_keeps_height():
    view = Lidar3DPreview.__new__(Lidar3DPreview)
    for name in ("delete", "create_text", "create_line", "create_oval"):
        setattr(view, name, Mock())
    view.winfo_width, view.winfo_height = lambda: 480, lambda: 330
    view.view = "front"
    positions = []
    for point in ((1, 0, 0), (1, .15, .1), (1, -.15, -.1)):
        view._snapshot = PreviewSnapshot((point,), "live", False)
        view._draw()
        x1, y1, x2, y2 = view.create_oval.call_args.args
        positions.append(((x1 + x2) / 2, (y1 + y2) / 2))
    center, positive_y, negative_y = positions
    assert positive_y[0] > center[0] > negative_y[0]
    assert positive_y[1] < center[1] < negative_y[1]


def test_preview_receiver_stale_empty_and_independent_sensors():
    now = [5.0]
    receiver = PreviewReceiver(clock=lambda: now[0])
    assert receiver.snapshot("left").status == "missing"
    assert receiver.ingest(packet())
    assert receiver.snapshot("left").points == ((1, .2, -.45),)
    assert receiver.snapshot("right").status == "missing"
    now[0] += .5
    assert receiver.snapshot("left").status == "stale"
    assert receiver.snapshot("left").points == ()
    assert receiver.ingest(packet(sequence=2, points=()))
    assert receiver.snapshot("left").status == "empty"


def test_preview_receiver_rejects_replay_and_recovers_after_restart():
    receiver = PreviewReceiver()
    assert receiver.ingest(packet(sequence=100))
    assert not receiver.ingest(packet(sequence=100))
    assert not receiver.ingest(packet(sequence=99))
    assert receiver.ingest(packet(sequence=1, session=11))
    assert not receiver.ingest(packet(sequence=101, session=10))
    assert receiver.ingest(packet(sequence=2, session=11))
    assert receiver.ingest(packet(sequence=1, side="right"))
    assert not receiver.ingest(b"bad")


def test_preview_sequence_wrap_is_not_a_restart():
    receiver = PreviewReceiver()
    assert receiver.ingest(packet(sequence=0xffffffff))
    assert receiver.ingest(packet(sequence=0))
    assert not receiver.ingest(packet(sequence=0xfffffffe))


def test_preview_port_failure_is_optional_and_closes_socket():
    sock = Mock()
    sock.bind.side_effect = OSError("port occupied")
    with patch("lidar_preview.socket.socket", return_value=sock):
        receiver = PreviewReceiver()
        assert not receiver.start(retry=False)
        assert receiver.snapshot("left").status == "unavailable"
        assert receiver._thread is None
        sock.close.assert_called_once()


def test_bad_preview_port_does_not_crash_dashboard_receiver():
    for port in ("not-a-port", -1, 65536):
        receiver = PreviewReceiver(port=port)
        assert not receiver.start()
        assert receiver.snapshot("left").status == "unavailable"


def test_preview_binds_only_explicit_ipv4_and_rejects_wildcard_before_binding():
    sock = Mock()
    sock.getsockname.return_value = ("192.168.10.2", 9103)
    with patch("lidar_preview.socket.socket", return_value=sock), patch("lidar_preview.threading.Thread"):
        receiver = PreviewReceiver(bind_host="192.168.10.2")
        assert receiver.start()
        sock.bind.assert_called_once_with(("192.168.10.2", 9103))
    for address in ("0.0.0.0", "", "::", "255.255.255.255", "224.0.0.1", "not-an-ip"):
        sock = Mock()
        with patch("lidar_preview.socket.socket", return_value=sock):
            receiver = PreviewReceiver(bind_host=address)
            assert not receiver.start()
            assert receiver.snapshot("left").status == "unavailable"
            sock.bind.assert_not_called()
            sock.close.assert_not_called()


def test_corrupt_preview_does_not_refresh_stale_time():
    now = [5.0]
    receiver = PreviewReceiver(clock=lambda: now[0])
    assert receiver.ingest(packet())
    now[0] += .4
    assert not receiver.ingest(packet() + b"bad")
    now[0] += .11
    assert receiver.snapshot("left").status == "stale"


def test_preview_udp_thread_receives_and_releases_port():
    receiver = PreviewReceiver(port=0)
    assert receiver.start()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sender.sendto(packet(), ("127.0.0.1", receiver.port))
        deadline = time.monotonic() + 2
        while receiver.snapshot("left").status != "live" and time.monotonic() < deadline:
            time.sleep(.01)
        assert receiver.snapshot("left").status == "live"
    finally:
        sender.close()
        receiver.stop()
    assert not receiver._thread.is_alive()


def preview_node():
    path = Path(__file__).resolve().parents[1] / "jetson" / "lidar_preview_node.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))]
    def read_points(msg, **kwargs):
        if msg.points.dtype.names:
            return msg.points[list(kwargs["field_names"])]
        return np.rec.fromarrays(msg.points.reshape(-1, 3).T, names="x,y,z")

    ns = dict(Node=object, np=np, time=time, full_xyz=full_xyz,
              encode_frame_chunks=wire.encode_frame_chunks,
              point_cloud2=SimpleNamespace(read_points=read_points,
                                          read_points_numpy=lambda msg, **kw: msg.points))
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(path), "exec"), ns)
    node = ns["LidarPreviewNode"].__new__(ns["LidarPreviewNode"])
    node.pending, node.last_capture = {}, {}
    node.sequence = {"left": 0, "right": 0}
    node.profile, node.session = "cyglidar_d2", 123
    node.sock, node.addr = Mock(), ("127.0.0.1", 9103)
    node._last_error = 0
    node.get_logger = Mock()
    return node


def cloud(points, sec=1):
    return SimpleNamespace(points=np.array(points),
                           header=SimpleNamespace(stamp=SimpleNamespace(sec=sec, nanosec=0)))


def test_3d_node_only_sends_new_frames_and_does_not_call_safety_bridge():
    node = preview_node()
    node._receive("left", cloud([[1, .1, -.4]]))
    node._receive("right", cloud([[1.5, -.1, .3]]))
    node._send_latest()
    packets = [wire.decode_chunk(call.args[0]) for call in node.sock.sendto.call_args_list]
    assert [p.side for p in packets] == ["left", "right"]
    assert packets[0].points_mm == ((1000, 100, -400),)
    node._send_latest()
    node._receive("left", cloud([[1, .1, -.4]]))  # Same capture stamp is a duplicate.
    node._send_latest()
    assert node.sock.sendto.call_count == 2
    assert not hasattr(node, "curb") and not hasattr(node, "side")


def test_3d_node_latest_cloud_replaces_backlog_and_empty_clears_frame():
    node = preview_node()
    node._receive("left", cloud([[1, 0, -.3]]))
    node._receive("left", cloud([[1.5, 0, -.5]], sec=2))
    node._send_latest()
    assert wire.decode_chunk(node.sock.sendto.call_args.args[0]).points_mm == ((1500, 0, -500),)
    node._receive("left", cloud([], sec=3))
    node._send_latest()
    assert wire.decode_chunk(node.sock.sendto.call_args.args[0]).points_mm == ()
    node.pending["right"] = (cloud([[1, 0, 0]]), time.monotonic() - 1)
    node._send_latest()
    assert node.sock.sendto.call_count == 2


def test_3d_node_bad_cloud_does_not_prevent_other_sensor():
    node = preview_node()
    node._receive("left", cloud([[1, 0]], sec=1))
    node._receive("right", cloud([[1, 0, .2]], sec=1))
    node._send_latest()
    assert node.sock.sendto.call_count == 1
    assert wire.decode_chunk(node.sock.sendto.call_args.args[0]).side == "right"


def full_packets(sequence=1, session=10, side="left", count=9600):
    points = tuple((1000, (index % 160) - 80, (index // 160) - 30) for index in range(count))
    return wire.encode_frame_chunks(side, session, sequence, 123, points)


def test_full_frame_wire_budget_empty_and_strict_headers():
    packets = full_packets()
    assert len(packets) == 50
    assert all(len(data) == 1192 <= wire.MAX_PACKET for data in packets)
    chunks = [wire.decode_chunk(data) for data in packets]
    assert sum(len(chunk.points_mm) for chunk in chunks) == 9600
    assert all(chunk.total_points == 9600 and chunk.count == 50 for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(50))
    empty = wire.decode_chunk(full_packets(count=0)[0])
    assert empty.points_mm == () and empty.count == 1 and empty.crc32 == 0
    for field, value in ((1, 99), (2, 2), (3, 8), (4, 1), (8, 191),
                         (9, 50), (10, 51), (11, 9601)):
        fields = list(wire.CHUNK_HEADER.unpack_from(packets[0]))
        fields[field] = value
        bad = wire.CHUNK_HEADER.pack(*fields) + packets[0][wire.CHUNK_HEADER.size:]
        try:
            wire.decode_chunk(bad)
        except ValueError:
            continue
        raise AssertionError(f"Accepted invalid chunk field {field}")
    for bad in (packets[0][:-1], packets[0] + b"x", packets[0] * 2):
        try:
            wire.decode_chunk(bad)
        except ValueError:
            continue
        raise AssertionError("Accepted incorrect datagram size")
    try:
        full_packets(count=9601)
    except ValueError:
        return
    raise AssertionError("Accepted oversized frame")


def test_full_xyz_retains_all_pixels_without_angular_reduction():
    points = np.array([[1, (index % 160 - 80) / 1000, (index // 160 - 30) / 1000]
                       for index in range(9600)])
    selected = full_xyz(points)
    assert len(selected) == len({tuple(point) for point in selected}) == 9600
    assert selected == np.rint(points * 1000).astype(int).tolist()
    assert len(sample_xyz(points)) < 192
    invalid = [[0, 0, 0], [-1, 0, 0], [float("nan"), 0, 0], [2.1, 0, 0]]
    assert full_xyz(invalid) == [] and full_xyz([]) == []
    assert len(full_xyz(np.vstack([points, points]))) == 9600
    assert full_xyz([[-.2, .4, 1]], "ros_optical") == [[1000, 200, -400]]
    assert full_xyz([[.05, 0, 0], [2, 0, 0]]) == [[50, 0, 0], [2000, 0, 0]]


def test_full_xyz_keeps_all_float32_d2_rays_at_both_range_boundaries():
    from jetson.walker_preview.d2_usb import display_depth_xyz
    for depth in (50, 2000):
        xyz = display_depth_xyz(np.full(9600, depth), True).astype(np.float32)
        selected = full_xyz(xyz)
        assert len(selected) == 9600
        receiver = PreviewReceiver()
        for data in wire.encode_frame_chunks("left", 10, depth, 123, selected):
            receiver.ingest(data)
        assert len(receiver.snapshot("left").points) == 9600
    assert full_xyz([[.04999, 0, 0], [2.00001, 0, 0]]) == []


def test_full_receiver_reorders_chunks_and_publishes_only_complete_frames():
    receiver = PreviewReceiver()
    packets = full_packets()
    for data in reversed(packets[1:]):
        assert not receiver.ingest(data)
        assert receiver.snapshot("left").status == "missing"
    assert not receiver.ingest(packets[1])  # Duplicate does not complete a frame.
    assert receiver.ingest(packets[0])
    snapshot = receiver.snapshot("left")
    assert snapshot.status == "live" and len(snapshot.points) == 9600
    expected = tuple(point for data in packets for point in wire.decode_chunk(data).points_mm)
    assert snapshot.points == tuple(tuple(value / 1000 for value in point) for point in expected)
    assert not receiver.ingest(packets[0])
    assert receiver.ingest(full_packets(sequence=2, count=0)[0])
    assert receiver.snapshot("left").status == "empty"


def test_full_receiver_timeout_late_chunks_and_stale_old_frame():
    now = [5.0]
    receiver = PreviewReceiver(clock=lambda: now[0])
    assert receiver.ingest(packet())  # Legacy senders still work during rollout.
    packets = full_packets(sequence=2, count=384)
    now[0] += .1
    assert not receiver.ingest(packets[0])
    now[0] += .2
    assert not receiver.ingest(packets[0])
    now[0] += .06  # First-chunk deadline, not last duplicate.
    assert not receiver.ingest(packets[1])
    assert not receiver._pending
    assert not receiver.ingest(packets[0])
    now[0] += .15
    assert receiver.snapshot("left").status == "stale"
    for data in full_packets(sequence=3):
        receiver.ingest(data)
    assert len(receiver.snapshot("left").points) == 9600


def test_full_receiver_crc_conflicts_and_bounded_newer_pending_frames():
    receiver = PreviewReceiver()
    packets = full_packets(count=384)
    corrupt = bytearray(packets[0])
    struct.pack_into("<h", corrupt, wire.CHUNK_HEADER.size, 1001)
    assert not receiver.ingest(corrupt)
    assert not receiver.ingest(packets[1])  # Valid coordinates but wrong full CRC.
    assert receiver.snapshot("left").status == "missing" and not receiver._pending
    packets = full_packets(sequence=2, count=384)
    assert not receiver.ingest(packets[0])
    fields = list(wire.CHUNK_HEADER.unpack_from(packets[1]))
    fields[7] += 1  # Inconsistent capture time.
    assert not receiver.ingest(wire.CHUNK_HEADER.pack(*fields) + packets[1][wire.CHUNK_HEADER.size:])
    assert not receiver._pending
    packets = full_packets(sequence=3, count=384)
    assert not receiver.ingest(packets[0])
    conflict = bytearray(packets[0])
    struct.pack_into("<h", conflict, wire.CHUNK_HEADER.size, 1001)
    assert not receiver.ingest(conflict) and not receiver._pending
    for sequence in range(4, 100):
        receiver.ingest(full_packets(sequence=sequence, count=384)[0])
        receiver.ingest(full_packets(sequence=sequence, side="right", count=384)[0])
    assert len(receiver._pending) == 2
    assert all(len(pending["chunks"]) == 1 for pending in receiver._pending.values())
    assert all(len(dropped) <= 64 for dropped in receiver._dropped.values())
    assert not receiver.ingest(full_packets(sequence=98, count=384)[1])
    assert receiver.ingest(full_packets(sequence=99, count=384)[1])
    assert receiver.snapshot("right").status == "missing"


def test_full_receiver_wrap_restart_and_retired_session():
    receiver = PreviewReceiver()
    assert receiver.ingest(full_packets(sequence=0xffffffff, count=1)[0])
    assert receiver.ingest(full_packets(sequence=0, count=1)[0])
    assert not receiver.ingest(full_packets(sequence=0xfffffffe, count=1)[0])
    restarting = full_packets(sequence=1, session=11, count=384)
    assert not receiver.ingest(restarting[0])
    assert not receiver.ingest(full_packets(sequence=1, count=384)[0])
    assert receiver.ingest(restarting[1])
    assert not receiver.ingest(full_packets(sequence=2, count=1)[0])


def test_full_node_sends_9600_and_consumes_sequence_after_partial_send_failure():
    node = preview_node()
    points = np.tile([[1, .1, -.2]], (9600, 1))
    node._receive("left", cloud(points))
    node._send_latest()
    packets = [call.args[0] for call in node.sock.sendto.call_args_list]
    assert len(packets) == 50
    receiver = PreviewReceiver()
    for data in packets:
        receiver.ingest(data)
    assert len(receiver.snapshot("left").points) == 9600
    node.sock.sendto.reset_mock()
    node.sock.sendto.side_effect = [None, OSError("send failed"), None]
    node._receive("left", cloud(points, sec=2))
    node._receive("right", cloud([[1, 0, 0]], sec=2))
    node._send_latest()
    assert node.sequence == {"left": 2, "right": 1}
    assert node.last_capture["left"] == 1000000000
    assert node.last_capture["right"] == 2000000000
    node.sock.sendto.side_effect = None
    node._receive("left", cloud(points, sec=2))
    node._send_latest()
    assert node.sequence["left"] == 3


def test_mixed_type_cloud_preserves_xyz_order_and_all_9600_points_per_sensor():
    # Match padded ROS records with differently typed color/intensity fields.
    records = np.zeros(9600, dtype={
        "names": ["rgba", "z", "x", "intensity", "y"],
        "formats": ["u4", "f4", "f4", "u2", "f8"],
        "offsets": [12, 8, 0, 16, 24], "itemsize": 32,
    })
    records["x"], records["rgba"], records["intensity"] = 1.0, 0xffabcdef, 65535
    records["y"] = (np.arange(9600) % 160 - 80) / 1000
    records["z"] = (np.arange(9600) // 160 - 30) / 1000
    node = preview_node()
    for side in ("left", "right"):
        node._receive(side, cloud(records))
    node._send_latest()
    assert node.sock.sendto.call_count == 100
    node.get_logger.return_value.warning.assert_not_called()
    receiver = PreviewReceiver()
    for call in node.sock.sendto.call_args_list:
        receiver.ingest(call.args[0])
    expected = [(1.0, (i % 160 - 80) / 1000, (i // 160 - 30) / 1000)
                for i in range(9600)]
    for side in ("left", "right"):
        assert receiver.snapshot(side).status == "live"
        assert receiver.snapshot(side).points == tuple(expected)


def test_full_udp_loopback_transports_two_9600_point_frames():
    receiver = PreviewReceiver(port=0)
    assert receiver.start()
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for side in ("left", "right"):
            for data in full_packets(side=side):
                sender.sendto(data, ("127.0.0.1", receiver.port))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if all(len(receiver.snapshot(side).points) == 9600 for side in ("left", "right")):
                break
            time.sleep(.005)
        assert all(len(receiver.snapshot(side).points) == 9600 for side in ("left", "right"))
    finally:
        sender.close()
        receiver.stop()


def test_3d_canvas_clears_stale_points_and_does_not_draw_a_floor_surface():
    view = Lidar3DPreview.__new__(Lidar3DPreview)
    for name in ("delete", "create_text", "create_line", "create_oval", "create_polygon", "create_rectangle"):
        setattr(view, name, Mock())
    view.winfo_width, view.winfo_height = lambda: 320, lambda: 172
    view.view = "oblique"
    view._snapshot = PreviewSnapshot(((1, .3, 0), (1.1, -.1, 0)), "live", True)
    view._draw()
    assert view.create_oval.call_count == 2
    view.create_polygon.assert_not_called()
    view.create_rectangle.assert_not_called()
    view.create_oval.reset_mock()
    view.update_snapshot(PreviewSnapshot(status="stale"))
    view.create_oval.assert_not_called()
    assert "3D 수신 중단" == view.create_text.call_args.kwargs["text"]


def test_3d_canvas_keeps_shared_points_and_metric_guides_fixed_when_cloud_changes():
    for camera in ("front", "oblique", "top", "side"):
        view = Lidar3DPreview.__new__(Lidar3DPreview)
        for name in ("delete", "create_text", "create_line", "create_oval"):
            setattr(view, name, Mock())
        view.winfo_width, view.winfo_height = lambda: 480, lambda: 330
        view.view = camera
        point = (.8, .2, .15)
        view._snapshot = PreviewSnapshot((point,), "live", False)
        view._draw()
        coordinates = view.create_oval.call_args.args
        guides = list(view.create_line.call_args_list)
        assert coordinates[2] - coordinates[0] == 2.0
        assert coordinates[3] - coordinates[1] == 2.0
        assert all("arrow" not in call.kwargs for call in guides)
        view.create_oval.reset_mock()
        view.create_line.reset_mock()
        view.update_snapshot(PreviewSnapshot((point, (1.9, -1.1, -.7)), "live", False))
        assert coordinates in [call.args for call in view.create_oval.call_args_list]
        assert guides == view.create_line.call_args_list
        view.create_line.reset_mock()
        view.update_snapshot(PreviewSnapshot(status="empty"))
        assert guides == view.create_line.call_args_list


def test_dense_cloud_raster_contains_only_small_measured_points_and_clears_on_loss():
    import lidar_preview_view as rendering
    if rendering.Image is None:
        return  # Minimal Pi installs retain the sparse Canvas fallback.
    view = Lidar3DPreview.__new__(Lidar3DPreview)
    for name in ("delete", "create_text", "create_line", "create_oval", "create_image"):
        setattr(view, name, Mock())
    view.winfo_width, view.winfo_height = lambda: 480, lambda: 330
    view.view = "front"
    view._snapshot = PreviewSnapshot(((1, 0, 0),) * 300, "live", False)
    with patch.object(rendering.ImageTk, "PhotoImage", return_value=object()) as photo:
        view._draw()
        bitmap = photo.call_args.args[0]
        assert bitmap.size == (480, 330)
        assert bitmap.getbbox() == (239, 164, 241, 166)
        assert sum(pixel[3] > 0 for pixel in bitmap.getdata()) == 4
        view.create_oval.assert_not_called()
        view.create_image.assert_called_once()
        view.update_snapshot(PreviewSnapshot(status="stale"))
        assert view._cloud_image is None
        assert photo.call_count == 1


def test_full_view_submits_every_valid_d2_ray_in_all_four_views_without_clipping():
    import lidar_preview_view as rendering
    from jetson.walker_preview.d2_usb import display_depth_xyz
    if rendering.Image is None:
        return
    points = tuple(map(tuple, display_depth_xyz(np.full(9600, 2000), True).tolist()))
    for camera in rendering.VIEWS:
        view = Lidar3DPreview.__new__(Lidar3DPreview)
        for name in ("delete", "create_text", "create_line", "create_oval", "create_image"):
            setattr(view, name, Mock())
        view.winfo_width, view.winfo_height = lambda: 471, lambda: 229
        view.view, view.full_view = camera, True
        view._snapshot = PreviewSnapshot(points, "live", False)
        with patch.object(rendering.ImageTk, "PhotoImage", return_value=object()):
            view._draw()
        assert view.drawn_points == view.total_points == 9600


def test_distance_palette_separates_nearby_depths_and_is_fixed_across_frames():
    from lidar_preview_view import distance_color
    colors = [distance_color(value) for value in (.1, .2, .35, .6, 1, 2)]
    assert len(set(colors)) == 6
    for first, second in zip(colors[:3], colors[1:4]):
        a = tuple(int(first[i:i+2], 16) for i in (1, 3, 5))
        b = tuple(int(second[i:i+2], 16) for i in (1, 3, 5))
        assert sum(abs(x-y) for x, y in zip(a, b)) >= 100
    assert distance_color(.2) == distance_color(.20001)
    assert distance_color(-1) == distance_color(0)
    assert distance_color(3) == distance_color(2)


def test_grid_size_changes_zoom_with_constant_on_screen_cell_spacing():
    from lidar_preview_view import fixed_projection
    base, cx, cy = fixed_projection(471, 303, "front")
    snapshot = PreviewSnapshot(((.5, .01, .01),), "live", False)
    canvas = Lidar3DPreview.__new__(Lidar3DPreview)
    canvas._snapshot, canvas._draw = snapshot, Mock()
    for centimeters, magnification in ((1, 10), (5, 2), (10, 1)):
        canvas.full_view = True
        canvas.set_grid_size_cm(centimeters)
        scale, center_x, center_y = fixed_projection(471, 303, "front", False, canvas.grid_step_m)
        assert math.isclose(scale, base * magnification)
        assert math.isclose(scale * canvas.grid_step_m, base * .1)
        assert (center_x, center_y) == (cx, cy)
        assert canvas._snapshot is snapshot and not canvas.full_view
    for invalid in (0, 2, 50, "5"):
        try:
            canvas.set_grid_size_cm(invalid)
        except ValueError:
            continue
        raise AssertionError("Unsupported grid size accepted")


def test_offline_scenes_keep_measured_height_change():
    flat, rise, drop = (scene_points(scene) for scene in ("flat", "rise", "drop"))
    assert all(p[2] == -.45 for p in flat)
    assert any(p[0] > 1.1 and p[2] == -.25 for p in rise)
    assert any(p[0] > 1.1 and p[2] == -.65 for p in drop)
    assert scene_points("empty") == ()
