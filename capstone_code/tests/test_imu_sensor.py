"""무선 수신기 프레임, 센서 선택, 설정 응답과 유선 호환을 검증한다."""
import math
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

import config
from schema import ImuSample
from sensors import imu_sensor as imu
from states import CONN_OK

VALUES = "-0.68,-11.11,-151.58,0.0,0.0,0.0,-0.195,-0.012,0.981"
FRAME = "100-0," + VALUES + "\r\n"


@contextmanager
def protocol(name="wireless", **kwargs):
    with patch.multiple(config, IMU_PROTOCOL=name, IMU_CONFIGURE_ON_CONNECT=True, IMU_CHANNEL=100,
                        IMU_SENSOR_ID=0, **kwargs):
        yield


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Receiver:
    """응답을 조각으로 내보내고, 읽지 않은 응답은 reset에서 실제로 버린다."""
    def __init__(self, clock, replies=None, lines=None):
        self.clock = clock
        self.replies = replies or {}
        self.lines = list(lines or [])
        self.pending = []
        self.writes = []
        self.timeout = 1.0

    @property
    def in_waiting(self):
        return len(self.pending[0]) if self.pending else 0

    def reset_input_buffer(self):
        self.pending.clear()

    def write(self, command):
        self.writes.append(command.decode("ascii"))
        # ACK 조각과 텔레메트리가 섞여 도착하는 실제 수신 조건.
        self.pending.extend(self.replies.get(command, [FRAME.encode(), b"<o", b"k>"]))

    def flush(self):
        pass

    def read(self, size):
        self.clock.now += 0.02
        if not self.pending:
            return b""
        data = self.pending[0][:size]
        self.pending[0] = self.pending[0][size:]
        if not self.pending[0]:
            self.pending.pop(0)
        return data

    def readline(self):
        self.clock.now += 0.02
        if self.lines:
            return self.lines.pop(0)
        imu._running = False
        return b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


@contextmanager
def simulated_time(clock):
    with patch.object(imu.time, "monotonic", clock.monotonic), \
            patch.object(imu.time, "sleep", clock.sleep):
        yield


def test_wireless_observed_frame():
    with protocol():
        assert imu._parse(FRAME) == [float(v) for v in VALUES.split(",")]


def test_v6_observed_frame():
    frame = "100-0,0.10,0.29,-125.71,0.0,0.0,0.0,0.005,0.001,1.005\r\n"
    with protocol():
        assert imu._parse(frame) == [0.10, 0.29, -125.71, 0, 0, 0, 0.005, 0.001, 1.005]


def test_wireless_only_selected_channel_and_sensor():
    with protocol():
        for prefix in ("100-1", "101-0", "garbage", "-100-0", "100-0-extra"):
            assert imu._parse(prefix + "," + VALUES) == []
        assert imu._parse(VALUES) == []
    with patch.multiple(config, IMU_PROTOCOL="wireless", IMU_CHANNEL=101, IMU_SENSOR_ID=2):
        assert len(imu._parse("101-2," + VALUES)) == 9
        assert imu._parse(FRAME) == []


def test_wired_frames_still_supported():
    with protocol("wired"):
        assert len(imu._parse("*" + VALUES + "\r\n")) == 9
        assert len(imu._parse(VALUES)) == 9
        assert imu._parse(FRAME) == []


def test_ack_attached_to_sample():
    with protocol():
        assert len(imu._parse("<ok><ok>" + FRAME)) == 9
        for line in ("<ok>", "<er>" + FRAME, "<to>" + FRAME, "<os>" + FRAME):
            assert imu._parse(line) == []


def test_reject_shifted_empty_extra_and_default_quaternion_fields():
    with protocol():
        for values in (VALUES + ",99", VALUES + ",", VALUES.replace("0.0,", ",", 1),
                       "0.9556,0.0363,0.1305,-0.2615,99", "-0.71,-11.11,-151.58"):
            assert imu._parse("100-0," + values) == []


def test_reject_nonfinite_or_corrupted_values():
    with protocol():
        for value in ("nan", "inf", "-inf", "1e999", "broken", "\ufffd"):
            assert imu._parse("100-0," + VALUES.replace("-0.68", value, 1)) == []


def test_wireless_setup_acknowledges_each_command_and_restores_timeout():
    clock = Clock()
    receiver = Receiver(clock)
    with protocol(), simulated_time(clock):
        imu._setup_sensor(receiver)
    assert receiver.writes == ["<soc1>", "<sof1>", "<sog1>", "<soa1>",
                               "<som0>", "<sod0>", "<sot0>", "<sob0>", "<sots0>"]
    assert receiver.timeout == 1.0


def test_wireless_setup_stops_on_receiver_error():
    for error in (b"<er>", b"<to>", b"<os>"):
        clock = Clock()
        receiver = Receiver(clock, {b"<sog1>": [error]})
        with protocol(), simulated_time(clock):
            try:
                imu._setup_sensor(receiver)
            except RuntimeError as exc:
                assert "<sog1>" in str(exc) and error.decode() in str(exc)
            else:
                raise AssertionError("오류 응답을 성공으로 처리함")
        assert receiver.writes == ["<soc1>", "<sof1>", "<sog1>"]
        assert receiver.timeout == 1.0


def test_wireless_setup_missing_ack_is_bounded_and_restores_timeout():
    clock = Clock()
    receiver = Receiver(clock, {b"<soc1>": [FRAME.encode()]})
    with protocol(), simulated_time(clock):
        try:
            imu._setup_sensor(receiver)
        except TimeoutError as exc:
            assert "<soc1>" in str(exc)
        else:
            raise AssertionError("데이터 수신을 설정 ACK로 오인함")
    assert 2 <= clock.now < 2.2
    assert receiver.writes == ["<soc1>"]
    assert receiver.timeout == 1.0


def test_invalid_configuration_fails_before_sending_commands():
    for setting, value in (("IMU_CHANNEL", 126), ("IMU_SENSOR_ID", -1),
                           ("IMU_SENSOR_ID", "0"), ("IMU_PROTOCOL", "typo"),
                           ("IMU_CONFIGURE_ON_CONNECT", "False")):
        receiver = Receiver(Clock())
        with protocol(), patch.object(config, setting, value):
            try:
                imu._setup_sensor(receiver)
            except ValueError:
                pass
            else:
                raise AssertionError("잘못된 설정을 허용함")
        assert receiver.writes == []


def test_passive_integrity_check_reads_without_configuration_writes():
    clock = Clock()
    receiver = Receiver(clock, lines=[FRAME.replace("100-0", "100-1").encode(), FRAME.encode()])
    with protocol(), patch.object(config, "IMU_CONFIGURE_ON_CONNECT", False), \
            simulated_time(clock), patch.object(imu, "SERIAL_AVAILABLE", True), \
            patch.object(imu, "serial", SimpleNamespace(Serial=Mock(return_value=receiver)), create=True), \
            patch.object(imu, "_log", None):
        assert imu.run_integrity_check()
    assert receiver.writes == []


def test_passive_setup_still_validates_sensor_identity():
    receiver = Receiver(Clock())
    with protocol(), patch.object(config, "IMU_CONFIGURE_ON_CONNECT", False), \
            patch.object(config, "IMU_SENSOR_ID", 100):
        try:
            imu._setup_sensor(receiver)
        except ValueError:
            pass
        else:
            raise AssertionError("수신 전용 모드에서 잘못된 센서 ID를 허용함")
    assert receiver.writes == []


def test_wired_setup_keeps_legacy_commands():
    clock = Clock()
    receiver = Receiver(clock)
    with protocol("wired"), simulated_time(clock):
        imu._setup_sensor(receiver)
    assert receiver.writes == imu.SETUP_COMMANDS


def test_read_loop_builds_sample_without_mixing_other_sensor():
    clock = Clock()
    receiver = Receiver(clock, lines=[FRAME.encode(), FRAME.replace("100-0", "100-1").encode(),
                                      b"100-0,1,2,3,4,5,6,7,8,9",  # 미완성 줄
                                      FRAME.replace("-0.68", "\ufffd").encode("utf-8")])
    with protocol(MOUNT_ROLL_OFFSET_DEG=1.0, MOUNT_PITCH_OFFSET_DEG=2.0), \
            patch.object(imu, "_running", True), patch.object(imu, "_sample", ImuSample()), \
            patch.object(imu, "_self_check", Mock()):
        imu._read_loop(receiver)
        sample = imu.snapshot()
        assert sample.valid and sample.status == CONN_OK
        assert math.isclose(sample.roll_deg, -1.68)
        assert math.isclose(sample.pitch_deg, -13.11)
        assert sample.yaw_deg == -151.58
        assert math.isclose(sample.accel_g, math.sqrt(0.195**2 + 0.012**2 + 0.981**2))
        assert sample.gyro_dps == 0
        imu._self_check.assert_called_once()


def test_integrity_check_requires_selected_sensor_frame():
    clock = Clock()
    receiver = Receiver(clock, lines=[FRAME.replace("100-0", "100-1").encode(),
                                      FRAME.encode()])
    factory = Mock(return_value=receiver)
    with protocol(), simulated_time(clock), patch.object(imu, "SERIAL_AVAILABLE", True), \
            patch.object(imu, "serial", SimpleNamespace(Serial=factory), create=True), \
            patch.object(imu, "_log", None):
        assert imu.run_integrity_check()
        assert factory.call_count == 1


def test_integrity_check_does_not_pass_with_only_other_sensor():
    clock = Clock()
    receiver = Receiver(clock, lines=[FRAME.replace("100-0", "100-1").encode()])
    factory = Mock(return_value=receiver)
    with protocol(), simulated_time(clock), patch.object(imu, "SERIAL_AVAILABLE", True), \
            patch.object(imu, "serial", SimpleNamespace(Serial=factory), create=True), \
            patch.object(imu, "_running", False), patch.object(imu, "_log", None):
        assert not imu.run_integrity_check()
        assert factory.call_count == 3
