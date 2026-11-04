"""Restart, replay and network recovery checks without physical devices."""
import json
import socket
import time
from unittest.mock import Mock, patch

import config
from lidar_preview import PreviewReceiver
from schema import SystemStatus
from sensors import lidar_udp
from status_link import StatusPublisher, StatusSubscriber
from stream_order import StreamOrder


def test_identified_restart_accepts_small_sequence_and_rejects_retired_packets():
    now = [5.0]
    order = StreamOrder(.5, clock=lambda: now[0])
    assert order.accept(500, "old")
    assert order.accept(1, "new")
    assert not order.accept(501, "old")
    assert order.accept(2, "new")
    now[0] += 10
    assert not order.accept(2, "new") and not order.accept(1, "new")
    assert not order.accept(9999)  # Old sessionless senders cannot take over.
    assert order.arrived == 5.0
    for index in range(100):
        assert order.accept(1, str(index))
    assert len(order.retired) == 64


def test_legacy_restart_recovers_after_stale_boundary_without_replaying_duplicates():
    for timeout in (.5, 2.0):
        now = [5.0]
        order = StreamOrder(timeout, clock=lambda: now[0])
        assert order.accept(500)
        now[0] += timeout / 2
        assert not order.accept(1)
        now[0] += timeout / 2
        assert order.accept(2)
        now[0] += timeout
        assert not order.accept(2)
        assert order.accept(1, "upgraded")
        assert not order.accept(9999)


def test_invalid_order_metadata_never_changes_freshness():
    order = StreamOrder(.5)
    assert order.accept(1, "valid")
    for sequence, session in ((True, "valid"), (-1, "valid"), (1.1, "valid"),
                              (2**64, "valid"), (2, ""), (2, []), (2, "a" * 65)):
        assert not order.accept(sequence, session)
    assert order.sequence == 1 and order.session == "valid"
    assert order.accept(2, "valid")


def test_status_publishers_identify_each_process_without_changing_schema_version():
    with patch("status_link.socket.socket", return_value=Mock()):
        first, second = StatusPublisher(), StatusPublisher()
        assert first._session != second._session
        first.publish(SystemStatus())
        data = json.loads(first._sock.sendto.call_args.args[0])
        assert data["session"] == first._session and data["seq"] == 1
        assert data["v"] == config.SCHEMA_VERSION
        assert SystemStatus.from_dict(data).session == first._session
        assert SystemStatus.from_dict({}).session is None


def feed_status(packets):
    subscriber = StatusSubscriber()
    subscriber._running = True
    sock = Mock()
    def receive(_size):
        data = packets.pop(0)
        if not packets:
            subscriber._running = False
        return json.dumps(data).encode(), ("127.0.0.1", 9101)
    sock.recvfrom.side_effect = receive
    with patch("status_link.socket.socket", return_value=sock):
        subscriber._loop()
    return subscriber


def test_status_receiver_recovers_immediately_and_does_not_roll_back_to_old_process():
    def packet(session, seq, notice):
        return {"v": config.SCHEMA_VERSION, "session": session, "seq": seq, "notice": notice}
    subscriber = feed_status([packet("old", 500, "old"), packet("new", 1, "new"),
                              packet("old", 501, "late old")])
    assert subscriber.latest()[0].notice == "new"
    assert subscriber.latest()[1] and subscriber._seq == 1
    subscriber = feed_status([packet("new", 1, "first"),
        {**packet("new", 999, "bad"), "imu": {"invalid_field": 1}}, packet("new", 2, "second")])
    assert subscriber.latest()[0].notice == "second"


def test_distance_receiver_recovers_immediately_and_rejects_invalid_new_sequence():
    def packet(session, seq, distance):
        return {"v": config.SCHEMA_VERSION, "session": session, "seq": seq, "t": time.time(),
                "left": {"d": distance, "ok": True}, "right": {"d": distance, "ok": True}}
    packets = [packet("old", 500, 1.5), packet("new", 1, .4),
               {**packet("new", 999, 9), "left": None}, packet("new", 2, .6),
               packet("old", 501, 9), packet("new", 1, 9)]
    sock = Mock()
    def receive(_size):
        data = packets.pop(0)
        if not packets:
            lidar_udp._running = False
        return json.dumps(data).encode(), ("127.0.0.1", 9100)
    sock.recvfrom.side_effect = receive
    state = dict(lidar_udp._state)
    with patch.object(lidar_udp, "_state", state), patch.object(lidar_udp, "_running", True), \
            patch.object(lidar_udp.socket, "socket", return_value=sock):
        lidar_udp._rx_loop()
        assert lidar_udp.snapshot().left_m == .6
        assert state["seq"] == 2 and lidar_udp.snapshot().link_ok


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(.01)
    return False


def assert_live_udp(receiver):
    from jetson.walker_preview.protocol import encode_frame_chunks
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        data = encode_frame_chunks("left", 123, 1, 0, [(500, 0, 0)])[0]
        sender.sendto(data, ("127.0.0.1", receiver.port))
        assert wait_for(lambda: receiver.snapshot("left").status == "live")
    finally:
        sender.close()


def test_preview_automatically_recovers_when_bind_fails_at_start():
    broken = Mock()
    broken.bind.side_effect = OSError("interface not ready")
    receiver = PreviewReceiver(port=0)
    try:
        with patch("lidar_preview.socket.socket", return_value=broken):
            assert not receiver.start()
            assert receiver.snapshot("left").status == "unavailable"
        assert wait_for(lambda: receiver.error is None and receiver.port > 0)
        assert_live_udp(receiver)
    finally:
        receiver.stop()
    assert not receiver._thread.is_alive()


def test_preview_automatically_rebinds_after_runtime_socket_failure():
    broken = Mock()
    broken.getsockname.return_value = ("127.0.0.1", 0)
    broken.recvfrom.side_effect = OSError("interface disappeared")
    receiver = PreviewReceiver(port=0)
    try:
        with patch("lidar_preview.socket.socket", return_value=broken):
            receiver.start()
            assert wait_for(lambda: receiver.error is not None)
        assert wait_for(lambda: receiver.error is None and receiver.port > 0)
        assert_live_udp(receiver)
    finally:
        receiver.stop()
    assert not receiver._thread.is_alive()


def test_preview_stop_cancels_retry_without_opening_another_socket():
    broken = Mock()
    broken.bind.side_effect = OSError("interface not ready")
    receiver = PreviewReceiver(port=0)
    with patch("lidar_preview.socket.socket", return_value=broken) as factory:
        assert not receiver.start()
        receiver.stop()
        assert not receiver._thread.is_alive()
        assert factory.call_count == 1
