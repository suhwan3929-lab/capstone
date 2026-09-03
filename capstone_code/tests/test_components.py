"""
구성요소 테스트 — UDP 링크 / 파싱 / 경보 등급 / 알림 스풀.
"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import config  # noqa: E402


def wait_for(predicate, timeout=3.0, interval=0.02):
    """조건이 참이 될 때까지 기다린다. 고정 sleep은 CI에서 반드시 깨진다."""
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ══════════════════════════════════════════════════════════
# UDP 프로세스 간 링크
# ══════════════════════════════════════════════════════════
def test_status_link_roundtrip():
    from schema import GpsFix, ImuSample, HealthReport, SystemStatus
    from states import TIPOVER_ASKING
    from status_link import StatusPublisher, StatusSubscriber

    sub = StatusSubscriber(port=19101)
    sub.start()
    pub = StatusPublisher(addr=("127.0.0.1", 19101))
    time.sleep(0.3)

    def publish():
        pub.publish(SystemStatus(
            tipover_state=TIPOVER_ASKING, ask_deadline=time.time() + 9,
            imu=ImuSample(accel_g=3.3, roll_deg=70.0, valid=True),
            gps=GpsFix(lat=35.1, lon=126.8, fix_quality=4, valid=True),
            health=HealthReport(battery_pct=42.0, ntrip_healthy=True)))

    publish()
    wait_for(lambda: sub.latest()[0] is not None)
    got, alive = sub.latest()
    sub.stop()
    pub.close()

    assert alive
    assert got.tipover_state == TIPOVER_ASKING
    assert got.imu.accel_g == 3.3
    assert got.gps.fix_quality == 4
    assert got.health.battery_pct == 42.0
    assert got.health.ntrip_healthy is True


def test_command_link_dedupes_burst():
    """
    취소 명령은 UDP 손실 대비로 3연발 전송된다.
    수신 측이 이를 3번의 명령으로 처리하면 안 된다.
    """
    from states import CMD_USER_NO
    from status_link import CommandListener, CommandSender

    got = []
    lis = CommandListener(got.append, port=19102)
    lis.start()
    time.sleep(0.3)
    CommandSender(addr=("127.0.0.1", 19102)).send(CMD_USER_NO)
    wait_for(lambda: len(got) > 0)
    time.sleep(0.3)          # 중복이 뒤늦게 오는지도 확인
    lis.stop()
    assert got == [CMD_USER_NO], got


def test_lidar_udp_rejects_stale_and_accepts_restart():
    """
    seq 역전은 버리되, Jetson 재시작(seq 리셋)은 받아들여야 한다.
    이 예외가 없으면 Jetson 재부팅 후 모든 패킷을 영구히 거부한다.
    """
    import json
    import socket

    from sensors import lidar_udp

    port = 19100
    config.UDP_LIDAR_PORT = port
    lidar_udp.start(lambda *a, **k: None)
    time.sleep(0.3)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send(seq, d):
        sock.sendto(json.dumps({
            "v": config.SCHEMA_VERSION, "seq": seq, "t": time.time(),
            "left": {"d": d, "ok": True}, "right": {"d": d, "ok": True},
        }).encode(), ("127.0.0.1", port))

    send(5000, 1.5)
    assert wait_for(lambda: lidar_udp.snapshot().left_m == 1.5), "패킷 미수신"

    send(4999, 9.9)            # 순서 역전 → 무시되어야 한다
    time.sleep(0.3)
    assert lidar_udp.snapshot().left_m == 1.5, "순서 역전 패킷이 반영되었다"

    send(1, 0.7)               # Jetson 재시작(seq 리셋) → 수용되어야 한다
    assert wait_for(lambda: lidar_udp.snapshot().left_m == 0.7),         "Jetson 재시작 후 패킷이 영구히 거부되었다"

    lidar_udp.stop()
    sock.close()


def test_lidar_link_loss_hides_stale_distance():
    """링크가 끊기면 낡은 거리값을 절대 내보내지 않는다."""
    from sensors import lidar_udp

    lidar_udp._state.update(left=1.2, right=1.4, left_ok=True, right_ok=True,
                            arrived=time.monotonic() - 10.0)
    r = lidar_udp.snapshot()
    assert r.link_ok is False
    assert r.left_m is None and r.right_m is None


# ══════════════════════════════════════════════════════════
# NMEA 파싱
# ══════════════════════════════════════════════════════════
def test_nmea_checksum_and_fix_quality():
    from sensors import gps_sensor

    line = ("$GPGGA,123519,4807.038,N,01131.000,E,4,18,0.8,545.4,M,"
            "46.9,M,,*4D")
    # 체크섬을 실제로 계산해 맞춰 넣는다
    body = line[1:line.rfind("*")]
    cs = 0
    for ch in body:
        cs ^= ord(ch)
    line = f"${body}*{cs:02X}"

    assert gps_sensor._checksum_ok(line)
    gps_sensor._parse_gga(line.split(","))
    f = gps_sensor.snapshot()
    assert f.fix_quality == 4            # RTK 고정
    assert f.satellites == 18
    assert abs(f.lat - 48.1173) < 0.001
    assert abs(f.lon - 11.51667) < 0.001


def test_nmea_rejects_missing_checksum():
    """체크섬 없는 문장을 유효로 처리하면 깨진 좌표가 들어온다."""
    from sensors import gps_sensor
    assert not gps_sensor._checksum_ok("$GPGGA,123519,4807.038,N")


def test_gps_keeps_position_when_fix_lost():
    """
    fix를 잃으면 좌표를 갱신하지 않되, 마지막 좌표는 보존한다.
    사고 신고에 '몇 초 전 좌표'로 쓸 수 있어야 하기 때문.
    단 신선도(position_age)로 반드시 함께 보고한다.
    """
    from sensors import gps_sensor

    gps_sensor._parse_gga("$GPGGA,1,3730.00,N,12701.00,E,4,18,0.8,50,M,,M,,".split(","))
    before = gps_sensor.snapshot()
    assert before.lat is not None

    # fix 상실: 위경도 필드가 비어서 온다
    gps_sensor._parse_gga("$GPGGA,2,,,,,0,03,9.9,,M,,M,,".split(","))
    after = gps_sensor.snapshot()
    assert after.fix_quality == 0
    assert after.lat == before.lat           # 좌표는 유지
    assert gps_sensor.position_age() >= 0


# ══════════════════════════════════════════════════════════
# LiDAR 언패킹
# ══════════════════════════════════════════════════════════
def test_lidar_unpack_u16le():
    from sensors import lidar_serial
    config.LIDAR_PACKING = "u16le"
    out = lidar_serial._unpack(bytes([0xE8, 0x03, 0xD0, 0x07]))   # 1000, 2000
    assert list(out) == [1000.0, 2000.0]


def test_lidar_unpack_u12():
    from sensors import lidar_serial
    config.LIDAR_PACKING = "u12"
    # 바이트 23 41 45 → a=((0x41&0x0F)<<8)|0x23=0x123, c=(0x45<<4)|(0x41>>4)=0x454
    out = lidar_serial._unpack(bytes([0x23, 0x41, 0x45]))
    assert list(out) == [0x123, 0x454]
    config.LIDAR_PACKING = "u16le"


def test_lidar_checksum_modes():
    from sensors import lidar_serial
    payload = bytes([1, 2, 3, 4])
    config.LIDAR_CHECKSUM = "xor"
    assert lidar_serial._checksum_ok(payload, 1 ^ 2 ^ 3 ^ 4)
    assert not lidar_serial._checksum_ok(payload, 0xFF)
    config.LIDAR_CHECKSUM = "sum8"
    assert lidar_serial._checksum_ok(payload, 10)
    config.LIDAR_CHECKSUM = "none"
    assert lidar_serial._checksum_ok(payload, 0xAB)   # 검증 안 함


# ══════════════════════════════════════════════════════════
# 경보 등급 · 히스테리시스
# ══════════════════════════════════════════════════════════
def test_alert_priority_and_hysteresis():
    import alerting
    from alerting import Alerter

    a = Alerter(log_callback=lambda *x, **k: None)

    # 장애물 위험 → 히스테리시스 여유 안에서는 등급이 안 내려간다
    assert a._obstacle_grade(0.4, moving=True) == alerting.OBSTACLE_DANGER
    assert a._obstacle_grade(config.DIST_DANGER_M + 0.05,
                             moving=True) == alerting.OBSTACLE_DANGER
    assert a._obstacle_grade(config.DIST_DANGER_M + config.DIST_HYSTERESIS_M + 0.05,
                             moving=True) == alerting.OBSTACLE_WARN

    # 정지 중에는 장애물 경고를 울리지 않는다 (경보 피로 방지)
    assert a._obstacle_grade(0.3, moving=False) == alerting.SILENT


def test_alert_level_mapping():
    import alerting
    from states import TIPOVER_ASKING, TIPOVER_CONFIRMED, TIPOVER_NORMAL

    assert alerting.tipover_state_to_level(TIPOVER_NORMAL) == alerting.SILENT
    assert alerting.tipover_state_to_level(TIPOVER_ASKING) == alerting.TIPOVER_ASK
    assert (alerting.tipover_state_to_level(TIPOVER_CONFIRMED)
            == alerting.TIPOVER_CONFIRMED)
    # 사고 확정이 장애물 위험보다 우선해야 한다
    assert alerting.TIPOVER_CONFIRMED > alerting.OBSTACLE_DANGER


# ══════════════════════════════════════════════════════════
# 알림
# ══════════════════════════════════════════════════════════
def test_webhook_validation_rejects_placeholder():
    """
    회귀 테스트 — 예전 `if not URL:` 은 플레이스홀더가 truthy라
    절대 발동하지 않았고, 잘못된 URL로 POST를 시도했다.
    """
    import notifier

    saved = config.WEBHOOK_URL
    for bad in ("", "https://discord.com/api/webhooks/...",
                "http://example.com", "YOUR_WEBHOOK_HERE"):
        config.WEBHOOK_URL = bad
        assert not notifier.is_configured(), bad
    config.WEBHOOK_URL = saved


def test_notify_spool_survives_restart(tmpdir=None):
    """
    사고 알림은 프로세스가 죽어도 사라지면 안 된다.
    LTE가 끊긴 순간에 사고가 나고 프로세스가 죽는 상황이 최악의 시나리오다.
    """
    import json
    import os
    import tempfile

    import notifier

    saved = config.NOTIFY_SPOOL
    d = tempfile.mkdtemp()
    config.NOTIFY_SPOOL = os.path.join(d, "spool.jsonl")
    try:
        item = {"id": "test-1", "kind": "confirmed", "utc": "2026-01-01T00:00:00"}
        notifier._spool_add(item)
        raw = open(config.NOTIFY_SPOOL, encoding="utf-8").read()
        assert "test-1" in raw

        notifier._spool_remove("test-1")
        rest = open(config.NOTIFY_SPOOL, encoding="utf-8").read().strip()
        assert "test-1" not in rest
    finally:
        config.NOTIFY_SPOOL = saved


# ══════════════════════════════════════════════════════════
# 배터리
# ══════════════════════════════════════════════════════════
def test_battery_curve_monotonic():
    import battery

    prev = -1
    for v in [c * config.BATTERY_CELLS for c in (3.2, 3.5, 3.7, 3.9, 4.1, 4.2)]:
        pct = battery.volts_to_percent(v)
        assert pct >= prev, f"{v}V 에서 잔량이 역전됨"
        prev = pct
    assert battery.volts_to_percent(4.2 * config.BATTERY_CELLS) == 100.0
    assert battery.volts_to_percent(3.0 * config.BATTERY_CELLS) == 0.0


def test_battery_reports_none_when_unmeasurable():
    """
    회귀 테스트 — 예전에는 BAT0가 없어도 항상 100%를 반환했다.
    틀린 계기판은 없는 계기판보다 나쁘다.
    """
    import battery

    b = battery._NullBackend()
    pct, volts, amps, charging = b.read()
    assert pct is None


# ══════════════════════════════════════════════════════════
# 시뮬레이터 · 스키마
# ══════════════════════════════════════════════════════════
def test_all_sim_scenarios_run():
    from sensors import sim

    for name, fn in sim.SCENARIOS.items():
        for t in (0.0, 5.0, 6.1, 12.0, 25.0):
            a, r, p, g, o, alive = fn(t)
            assert 0.0 <= a < 50.0, f"{name}@{t}: 비현실적 가속도 {a}"
            assert -180 <= r <= 180 and -180 <= p <= 180
            assert o is None or 0.0 < o < 20.0
            assert isinstance(alive, bool)


def test_schema_roundtrip_preserves_everything():
    import json

    from schema import GpsFix, HealthReport, ImuSample, ObstacleReport, SystemStatus

    orig = SystemStatus(
        tipover_state="사고 확정", alert_sent=True,
        imu=ImuSample(accel_g=4.2, roll_deg=-70.5, valid=True),
        gps=GpsFix(lat=35.1, lon=126.8, fix_quality=4, hdop=0.7, valid=True),
        obstacle=ObstacleReport(left_m=0.42, curb_m=0.9, curb_type="drop",
                                link_ok=True),
        health=HealthReport(battery_pct=17.5, ntrip_healthy=True))
    back = SystemStatus.from_dict(json.loads(json.dumps(orig.to_dict())))

    assert back.tipover_state == orig.tipover_state
    assert back.imu.accel_g == orig.imu.accel_g
    assert back.imu.tilt_deg == orig.imu.tilt_deg
    assert back.obstacle.curb_type == "drop"
    assert back.health.battery_pct == 17.5


def test_imu_tilt_uses_max_of_roll_pitch():
    from schema import ImuSample
    assert ImuSample(roll_deg=-75.0, pitch_deg=10.0).tilt_deg == 75.0
    assert ImuSample(roll_deg=5.0, pitch_deg=-88.0).tilt_deg == 88.0
