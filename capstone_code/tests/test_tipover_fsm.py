"""
전도 판정 FSM 테스트.

pytest 없이도 돌아간다:
    python tests/run_all.py
pytest가 있으면:
    pytest tests/

가상 시계를 주입해 실시간을 기다리지 않는다 — 전체가 1초 안에 끝난다.
그래서 코드를 고칠 때마다 부담 없이 돌릴 수 있다.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import config  # noqa: E402
import notifier  # noqa: E402
from schema import GpsFix, ImuSample  # noqa: E402
from states import (CMD_RESET, CMD_USER_NO, CMD_USER_YES, TIPOVER_ASKING,  # noqa: E402
                    TIPOVER_CHECKING, TIPOVER_NORMAL, TIPOVER_REPORTED,
                    TIPOVER_STABILIZING)

SENT = []
notifier.start = lambda *a, **k: None
notifier.send_preliminary = lambda *a, **k: SENT.append("PRELIM")
notifier.send_confirmed = lambda i, g, a, p: SENT.append(f"CONFIRM:{p:.2f}")
notifier.send_cancelled = lambda r: SENT.append(f"CANCEL:{r}")

from tipover_monitor import TipoverMonitor  # noqa: E402
from buttons import CMD_SOS  # noqa: E402


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class Rig:
    """FSM을 가상 시계로 구동하는 테스트 지그."""

    def __init__(self):
        self.clock = Clock()
        self.logs = []
        self.mon = TipoverMonitor(
            log_callback=lambda m, l="INFO": self.logs.append(m),
            clock=self.clock)
        self.gps = GpsFix(valid=True, lat=35.0, lon=127.0, fix_quality=4)
        SENT.clear()

    def feed(self, seconds, accel=1.0, roll=0.0, pitch=0.0, gyro=0.0,
             valid=True, hz=100):
        n = max(1, int(seconds * hz))
        for _ in range(n):
            self.clock.t += 1.0 / hz
            self.mon.step(ImuSample(t_capture=self.clock.t, accel_g=accel,
                                    roll_deg=roll, pitch_deg=pitch,
                                    gyro_dps=gyro, valid=valid), self.gps)

    def impact(self, g=4.0):
        self.feed(0.05, accel=g)

    @property
    def state(self):
        return self.mon.state

    def sent(self, prefix):
        return any(s.startswith(prefix) for s in SENT)


# ══════════════════════════════════════════════════════════
# 테스트
# ══════════════════════════════════════════════════════════
def test_normal_walking_never_triggers():
    """정상 보행에서는 아무 일도 일어나지 않아야 한다."""
    r = Rig()
    r.feed(20, accel=1.05, pitch=2.0)
    assert r.state == TIPOVER_NORMAL
    assert not SENT


def test_impact_while_upright_is_released():
    """
    [C5] 회귀 테스트 — 이 조건이 없으면 횡단보도에서 턱 넘고 5초 서 있을 때
    보호자에게 사고 신고가 간다. 이 프로젝트에서 가장 중요한 오탐 방지 조건이다.
    """
    r = Rig()
    r.impact(3.5)
    r.feed(config.STABILIZE_TIME + 0.5, accel=1.0, pitch=8.0)   # 서 있는 자세
    assert r.state == TIPOVER_NORMAL
    assert r.sent("PRELIM")          # 예비 알림은 나가고
    assert r.sent("CANCEL")          # 곧바로 해제 알림이 나가야 한다
    assert not r.sent("CONFIRM")     # 확정 신고는 절대 나가면 안 된다


def test_fall_confirmed_when_motionless():
    """충격 + 쓰러진 자세 + 무응답 → 사고 확정."""
    r = Rig()
    r.impact(4.6)
    r.feed(config.STABILIZE_TIME + 0.1, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_CHECKING
    r.feed(config.CHECK_TIME + 0.1, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_ASKING
    r.feed(config.ASK_TIMEOUT + 0.2, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_REPORTED
    assert r.sent("CONFIRM")


def test_user_cancel_during_asking():
    """응답 대기 중 '아니오' → 신고하지 않는다."""
    r = Rig()
    r.impact(4.6)
    r.feed(config.STABILIZE_TIME + config.CHECK_TIME + 0.3, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_ASKING
    r.mon.submit(CMD_USER_NO)
    r.feed(0.2, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_NORMAL
    assert not r.sent("CONFIRM")


def test_user_cancel_before_popup_is_not_lost():
    """
    회귀 테스트 — 명령이 상태 전이와 같은 틱에 도착하면 그대로 버려지던 버그.
    취소가 유실되면 오신고가 그대로 나간다.
    """
    r = Rig()
    r.impact(4.6)
    r.feed(0.5, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_STABILIZING
    r.mon.submit(CMD_USER_NO)                  # 팝업이 뜨기 전에 눌렀다
    r.feed(0.2, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_NORMAL
    assert not r.sent("CONFIRM")


def test_movement_releases_but_needs_time_separation():
    """
    [H6] 회귀 테스트 — 100 Hz에서 연속된 노이즈 2샘플로 실제 전도가
    취소되던 문제. 움직임 이벤트에는 최소 시간 간격이 필요하다.
    """
    r = Rig()
    r.impact(4.6)
    r.feed(config.STABILIZE_TIME + 0.1, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_CHECKING

    # 연속 2샘플의 스파이크로는 취소되면 안 된다
    r.feed(0.02, accel=3.0, pitch=82.0, gyro=300)
    assert r.state == TIPOVER_CHECKING, "노이즈 2샘플로 전도 판정이 취소되었다"

    # 시간 간격을 둔 움직임 2회면 취소되어야 한다
    r.feed(config.MOVE_MIN_INTERVAL + 0.05, accel=1.0, pitch=82.0)
    r.feed(0.02, accel=3.0, pitch=82.0, gyro=300)
    r.feed(0.1, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_NORMAL
    assert not r.sent("CONFIRM")


def test_posture_recovery_releases():
    """쓰러졌다가 스스로 일어나면 해제된다."""
    r = Rig()
    r.impact(4.6)
    r.feed(config.STABILIZE_TIME + 0.1, accel=1.0, pitch=82.0)
    r.feed(0.3, accel=1.0, pitch=10.0)         # 일어났다
    assert r.state == TIPOVER_NORMAL
    assert not r.sent("CONFIRM")


def test_rearm_cooldown_prevents_repeat_alerts():
    """
    회귀 테스트 — 해제 직후에도 보행기가 기울어 있으면
    작은 충격 하나로 즉시 재확정되어 같은 상황을 반복 통보하던 문제.
    """
    r = Rig()
    r.impact(3.5)
    r.feed(config.STABILIZE_TIME + 0.3, accel=1.0, pitch=5.0)
    assert r.state == TIPOVER_NORMAL
    SENT.clear()
    r.impact(4.0)                              # 쿨다운 중 재충격
    r.feed(0.2, accel=1.0, pitch=85.0)
    assert r.state == TIPOVER_NORMAL, "쿨다운 중인데 재트리거되었다"
    assert not SENT


def test_sos_bypasses_fsm():
    """
    SOS는 판정 단계를 전부 건너뛴다.
    몸을 못 움직이지만 의식은 있는 경우, 또는 전도가 아닌 응급 상황
    (현기증·흉통 등)은 자동 감지로 절대 잡을 수 없다.
    """
    r = Rig()
    r.feed(1.0, accel=1.0)
    r.mon.submit(CMD_SOS)
    r.feed(0.2, accel=1.0)
    assert r.state == TIPOVER_REPORTED
    assert r.sent("CONFIRM")


def test_dead_imu_does_not_advance_fsm():
    """IMU가 죽으면 판정을 진행하지 않는다 (엉뚱한 확정 방지)."""
    r = Rig()
    r.impact(4.6)
    r.feed(1.0, accel=1.0, pitch=82.0)
    assert r.state == TIPOVER_STABILIZING
    r.feed(30.0, valid=False)                  # 센서 사망
    assert r.state == TIPOVER_STABILIZING, "죽은 센서로 상태가 진행되었다"


def test_reset_after_report():
    """신고 완료 후 리셋하면 평상시로 돌아간다."""
    r = Rig()
    r.mon.submit(CMD_SOS)
    r.feed(0.2)
    assert r.state == TIPOVER_REPORTED
    r.mon.submit(CMD_RESET)
    r.feed(0.2)
    assert r.state == TIPOVER_NORMAL


def test_confirm_sends_exactly_once():
    """같은 사고로 신고가 두 번 나가지 않는다."""
    r = Rig()
    r.mon.submit(CMD_USER_YES)
    r.impact(4.6)
    r.feed(config.STABILIZE_TIME + config.CHECK_TIME + config.ASK_TIMEOUT + 1.0,
           accel=1.0, pitch=82.0)
    r.feed(10.0, accel=1.0, pitch=82.0)
    assert sum(1 for s in SENT if s.startswith("CONFIRM")) == 1
