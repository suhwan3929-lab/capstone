"""D2 vendor-format bytes -> XYZ -> independent display snapshots, no USB hardware."""
from functools import reduce
import operator
import struct
from unittest.mock import Mock, patch

import numpy as np

from jetson.walker_preview.d2_usb import (
    AMPLITUDE, DEPTH, DEPTH_ONLY, DEVICE_INFO, PIXELS, START_3D, STOP, StreamParser, decode_depth, depth_to_xyz, display_depth_xyz, frequency_channel_command, unit_rays)
from tools.usb_lidar_3d import UsbReceiver, create_dashboard


def payload(values=None, amplitude=False):
    values = np.full(PIXELS, 1000, dtype=np.uint16) if values is None else np.asarray(values, dtype=np.uint16)
    pairs = values.reshape(-1, 2)
    packed = np.zeros((PIXELS // 2, 5 if amplitude else 3), dtype=np.uint8)
    packed[:, 0] = pairs[:, 0] >> 4
    packed[:, 1] = ((pairs[:, 0] & 15) << 4) | (pairs[:, 1] >> 8)
    packed[:, 2] = pairs[:, 1] & 255
    return bytes((AMPLITUDE if amplitude else DEPTH,)) + struct.pack("<HH", 123, 2500) + packed.tobytes()


def frame(data, device_id=255):
    raw = b"\x5a\x77" + bytes((device_id,)) + len(data).to_bytes(2, "little") + data
    return raw + bytes((reduce(operator.xor, raw[3:], 0),))


def test_sdk_run_and_stop_commands_use_correct_type_and_xor():
    assert START_3D == bytes.fromhex("5a77ff020008000a")
    assert STOP == bytes.fromhex("5a77ff0200020000")


def test_frequency_channel_command_bytes_and_input_validation():
    assert frequency_channel_command(0) == bytes.fromhex("5a77ff02000f000d")
    assert frequency_channel_command(1) == bytes.fromhex("5a77ff02000f010c")
    for value in (-1, 16, "1", True):
        try:
            frequency_channel_command(value)
        except ValueError:
            continue
        raise AssertionError("Invalid frequency channel accepted")
    try:
        UsbReceiver({"left": "COM20"}, passive=True, channels={"left": 0})
    except ValueError:
        pass
    else:
        raise AssertionError("Passive mode allowed a channel write")


def test_worker_sends_independent_channel_overrides_after_start_on_each_connection():
    for side, channel in (("left", 0), ("right", 1)):
        receiver = UsbReceiver({side: "COM20"}, channels={side: channel})
        serial = Mock()
        serial.write.side_effect = lambda packet: len(packet)
        raw = frame(payload())
        serial.in_waiting = len(raw)
        def read(_size):
            receiver._stop.set()
            return raw
        serial.read.side_effect = read
        receiver.serial_factory = Mock(return_value=serial)
        with patch.object(receiver._stop, "wait", return_value=False):
            receiver._loop(side, "COM20")
        assert [call.args[0] for call in serial.write.call_args_list] == [
            DEVICE_INFO, DEPTH_ONLY, START_3D, frequency_channel_command(channel), STOP]
        assert receiver.stats(side)["requested_channel"] == channel
        assert receiver.stats(side)["channel_command_sent"] == channel
        assert receiver.snapshot(side).status == "live"


def test_incomplete_channel_write_is_not_reported_as_sent():
    receiver = UsbReceiver({"left": "COM20"}, channels={"left": 0})
    serial = Mock()
    def write(packet):
        if packet == frequency_channel_command(0):
            receiver._stop.set()
            return len(packet) - 1
        return len(packet)
    serial.write.side_effect = write
    receiver.serial_factory = Mock(return_value=serial)
    with patch.object(receiver._stop, "wait", return_value=False):
        receiver._loop("left", "COM20")
    assert receiver.stats("left")["channel_command_sent"] is None
    assert receiver.stats("left")["error"] == "OSError"
    assert receiver.snapshot("left").status == "unavailable"
    serial.close.assert_called_once()


def test_cli_channel_defaults_and_read_only_opt_outs():
    from types import SimpleNamespace
    import tools.usb_lidar_3d as usb
    ports = [SimpleNamespace(device="COM20"), SimpleNamespace(device="COM21")]
    for flags, expected in (([], {"left": 0, "right": 1}),
                            (["--passive"], {}), (["--keep-channels"], {}),
                            (["--left-channel", "3", "--right-channel", "8"], {"left": 3, "right": 8})):
        args = ["usb_lidar_3d.py", "--left", "COM20", "--right", "COM21", *flags]
        with patch.object(usb.sys, "argv", args), patch("serial.tools.list_ports.comports", return_value=ports), \
                patch("tkinter.Tk"), patch.object(usb, "create_dashboard"), \
                patch.object(usb, "UsbReceiver") as receiver, patch("builtins.print"):
            assert usb.main() == 0
            assert receiver.call_args.kwargs["channels"] == expected
            receiver.return_value.stop.assert_called_once()


def test_3d_payload_offset_12bit_order_and_amplitude_layout():
    depth = np.full(PIXELS, 1000, dtype=np.uint16)
    depth[1] = 1200
    for amplitude in (False, True):
        data = payload(depth, amplitude)
        assert data[5:8] == bytes.fromhex("3e84b0")
        assert np.array_equal(decode_depth(data), depth)
    for data in (b"", b"\x01" + bytes(14404), payload()[:-1], payload() + b"x"):
        try:
            decode_depth(data)
        except ValueError:
            continue
        raise AssertionError("Malformed payload accepted")


def test_stream_accepts_split_frames_variable_id_and_full_3d_packet():
    parser = StreamParser()
    data = payload()
    raw = frame(data, device_id=7)
    assert len(raw) == 14411  # The old 4096-byte payload limit cannot receive this.
    got = []
    for start in range(0, len(raw), 137):
        got.extend(parser.feed(raw[start:start+137]))
    assert got == [data]


def test_stream_rejects_bad_checksum_and_resynchronizes_after_noise():
    data = payload()
    broken = bytearray(frame(data))
    broken[-1] ^= 1
    parser = StreamParser()
    got = parser.feed(b"noise\x5a\x77\xff\xff\xff" + broken + frame(data))
    assert got == [data]
    assert parser.bad_checksum >= 1 and parser.bad_length >= 1
    parser.feed(b"garbage" * 30000)
    assert len(parser.buffer) <= 48010


def test_lens_rays_preserve_vendor_axes_pixel_order_and_metric_radius():
    rays = unit_rays()
    assert rays.shape == (9600, 3)
    assert np.allclose(np.linalg.norm(rays, axis=1), 1, atol=2e-6)
    assert np.all(rays[:, 0] > 0)
    assert rays[0, 1] > 0 and rays[0, 2] > 0  # top-left = left/up
    assert rays[-1, 1] < 0 and rays[-1, 2] < 0
    assert np.allclose(rays[0], rays[-1] * [1, -1, -1], atol=2e-6)
    xyz = depth_to_xyz(np.full(PIXELS, 1500, dtype=np.uint16))
    assert np.allclose(np.linalg.norm(xyz, axis=1), 1.5, atol=3e-6)


def test_invalid_depth_codes_never_become_real_3d_points():
    values = np.full(PIXELS, 4080, dtype=np.uint16)
    values[:4] = [0, 3999, 4000, 4086]
    xyz = depth_to_xyz(values)
    assert xyz.shape == (1, 3)
    assert np.isclose(np.linalg.norm(xyz[0]), 3.999, atol=3e-6)


def test_receiver_10hz_staleness_empty_and_independent_sides():
    now = [10.0]
    receiver = UsbReceiver({}, clock=lambda: now[0])
    assert receiver.ingest("left", payload())
    assert receiver.snapshot("left").status == "live"
    assert len(receiver.snapshot("left").points) == 2400
    assert receiver.snapshot("left").simulated is False
    assert receiver.snapshot("right").status == "missing"
    now[0] += .02
    assert not receiver.ingest("left", payload())
    assert receiver.stats("left")["received"] == 2
    now[0] += .5
    assert receiver.snapshot("left").status == "stale"
    assert receiver.snapshot("left").points == ()
    assert receiver.ingest("left", payload(np.full(PIXELS, 4080)))
    assert receiver.snapshot("left").status == "empty"
    now[0] += .3
    assert not receiver.ingest("left", b"\x08broken")
    now[0] += .3
    assert receiver.snapshot("left").status == "stale"


def test_usb_display_retains_fixed_pixel_grid_and_valid_range_without_udp_sampling():
    depth = np.full(PIXELS, 1000, dtype=np.uint16)
    expected_rays = unit_rays().reshape(60, 160, 3)[::2, ::2].reshape(-1, 3)
    assert np.allclose(display_depth_xyz(depth), expected_rays)
    # An unselected pixel must not replace a selected ray when its distance changes.
    depth[1] = 200
    assert np.allclose(display_depth_xyz(depth), expected_rays)
    depth[0], depth[2], depth[4], depth[6] = 0, 49, 50, 2000
    depth[8], depth[10] = 2001, 4080
    points = display_depth_xyz(depth)
    assert len(points) == 2396
    assert np.isclose(np.linalg.norm(points[0]), .05, atol=1e-6)
    assert np.isclose(np.linalg.norm(points[1]), 2.0, atol=1e-6)


def test_full_resolution_keeps_all_valid_pixels_including_unsampled_columns():
    depth = np.full(PIXELS, 1000, dtype=np.uint16)
    assert len(display_depth_xyz(depth, True)) == 9600
    depth[:6] = [0, 49, 50, 2000, 2001, 4080]
    points = display_depth_xyz(depth, True)
    assert len(points) == 9596
    assert np.allclose(points[0], unit_rays()[2] * .05)
    assert np.allclose(points[1], unit_rays()[3] * 2)


def test_receiver_full_resolution_toggle_clears_old_selection_and_blocks_racing_update():
    receiver = UsbReceiver({})
    assert receiver.ingest("left", payload())
    assert len(receiver.snapshot("left").points) == 2400
    receiver.set_full_resolution(True)
    assert receiver.snapshot("left").status == "missing"
    assert receiver.ingest("left", payload())
    assert len(receiver.snapshot("left").points) == 9600
    assert receiver.stats("left")["points"] == receiver.stats("left")["in_range"] == 9600
    receiver.set_full_resolution(False)
    original = display_depth_xyz
    def switch_while_decoding(depth, full_resolution):
        receiver.set_full_resolution(True)
        return original(depth, full_resolution)
    with patch("tools.usb_lidar_3d.display_depth_xyz", side_effect=switch_while_decoding):
        assert not receiver.ingest("left", payload())
    assert receiver.snapshot("left").status == "missing"


def test_worker_uses_only_start_stop_and_passive_mode_writes_nothing():
    for passive in (False, True):
        receiver = UsbReceiver({}, passive=passive)
        serial = Mock()
        raw = frame(payload())
        serial.in_waiting = len(raw)

        def read(_size):
            receiver._stop.set()
            return raw

        serial.read.side_effect = read
        receiver.serial_factory = Mock(return_value=serial)
        with patch.object(receiver._stop, "wait", return_value=False):
            receiver._loop("left", "COM20")
        assert receiver.snapshot("left").status == "live"
        serial.close.assert_called_once()
        assert [call.args[0] for call in serial.write.call_args_list] == ([] if passive else [DEVICE_INFO, DEPTH_ONLY, START_3D, STOP])


def test_usb_test_dashboard_disables_safety_commands_and_never_claims_distance():
    import ui

    def build(d, root, **kwargs):
        d.root, d.preview_sub, d.cmd, d.sub = root, kwargs["preview_receiver"], kwargs["command_sender"], kwargs["status_subscriber"]
        d.display_mode_buttons = {"3D": Mock(), "2D": Mock()}
        for name in ("term", "clock", "lidar_l", "lidar_r", "overall", "health_lbl", "batt", "status_banner", "header_controls",
                     "curb_lbl", "summary_imu", "summary_gps", "sos_status", "sos_button"):
            setattr(d, name, Mock())

    receiver = UsbReceiver({"left": "COM20", "right": "COM21"})
    with patch.object(ui.Dashboard, "__init__", autospec=True, side_effect=build), \
            patch.object(ui.tk, "Frame"), patch.object(ui.tk, "Button", side_effect=lambda *a, **kw: Mock()):
        d = create_dashboard(Mock(), receiver)
    d._refresh()
    d.overall.grid_remove.assert_called_once()
    assert "비활성" in d.sos_status.config.call_args.kwargs["text"]
    assert d.lidar_l._flat.call_args.args[2] == "판정 미실행"
    assert d.sos_button.config.call_args.kwargs["state"] == ui.tk.DISABLED
    d.display_mode_buttons["2D"].config.assert_called_with(state=ui.tk.DISABLED)
    assert d.sub.latest() == (None, False)
    assert receiver.full_resolution
    d._toggle_full_points()
    assert not receiver.full_resolution
    d.lidar_l.preview_3d.set_full_view.assert_called_with(False)
    d._toggle_full_points()
    assert receiver.full_resolution
    d.lidar_l.preview_3d.set_full_view.assert_called_with(True)
    d.lidar_r.preview_3d.set_full_view.assert_called_with(True)
    assert d.full_points_button.config.call_args.kwargs["text"] == "전체 점군: 켬"
    d._toggle_full_points()
    assert not receiver.full_resolution
    d.lidar_l.preview_3d.set_full_view.assert_called_with(False)
    try:
        d.cmd.send("sos")
    except RuntimeError:
        pass
    else:
        raise AssertionError("USB test allowed a safety command")
