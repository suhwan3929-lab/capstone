"""
전도 판정 FSM + 사고 신고.

이 모듈이 시스템의 **안전 필수 경로**다. GUI와 완전히 분리되어 있으며,
GUI가 죽어도 여기는 계속 동작한다. (예전에는 판정 로직이 GUI의 _refresh() 안에
들어 있어서, tkinter가 멈추면 전도 감지도 같이 죽었다)

상태 전이
    평상시 ──충격 ≥ 2.8g──> 충격 감지 ──[기울기 < 60°]──> 평상시 (방지턱/내려놓기)
                                    └──[기울기 ≥ 60°]──> 움직임 분석중
    움직임 분석중 ──의미 있는 움직임 2회──> 평상시 (의식 있음)
                └──5초간 정지──────────> 응답 대기
    응답 대기 ──"아니오"──> 평상시
            └──"예" 또는 10초 무응답──> 사고 확정 → 신고 완료

이전 버전 대비 수정:
  [C1] 상태 문자열을 states.py에서 import — 문자열 불일치로 신고가 누락되던 문제
  [C5] '쓰러진 자세' 조건 추가 — 예전에는 충격 후 정지만으로 사고를 확정해서,
       횡단보도에서 턱 넘고 5초 서 있으면 보호자에게 신고가 갔다
  [H2] 충격 감지 즉시 예비 알림 발송
  [H6] 움직임 이벤트에 최소 시간 간격 요구 + 기준점을 구간 평균으로
       (예전에는 연속된 노이즈 2샘플로 실제 전도 판정이 취소될 수 있었다)

ROS 2 이행 시: 이 모듈이 tipover_detector_node가 된다.
              imu.snapshot() 폴링 → /imu/data 구독으로 바뀌는 것이 전부다.
"""
import threading
import time
from collections import deque

import config
import notifier
from buttons import CMD_SOS
from schema import GpsFix, ImuSample
from sensors import gps_source, imu_source
from states import (CMD_RESET, CMD_USER_NO, CMD_USER_YES, TIPOVER_ASKING,
                    TIPOVER_CHECKING, TIPOVER_CONFIRMED, TIPOVER_NORMAL, TIPOVER_REPORTED,
                    TIPOVER_STABILIZING)

TICK_HZ = 100


class TipoverMonitor:
    def __init__(self, log_callback=None, clock=time.time):
        self._log = log_callback
        #: 시간 소스를 주입 가능하게 둔다. tools/replay.py 가 가상 시계를 넣어
        #: 기록된 CSV를 실시간보다 수백 배 빠르게 재생하며 임계값을 탐색한다.
        #: 재생과 실주행이 **완전히 같은 판정 코드**를 쓰게 하려는 것이다.
        self._now = clock
        self._lock = threading.Lock()
        self._running = False

        self.state = TIPOVER_NORMAL
        self.ask_deadline = None
        self.alert_sent = False

        self._t_state = 0.0          # 현재 상태 진입 시각
        self._peak_g = 0.0
        self._pending_cmd = None
        self._pending_t = 0.0

        # [H6] 기준점을 한 샘플이 아니라 구간 평균으로 잡는다
        self._hist = deque(maxlen=int(TICK_HZ * config.BASELINE_AVG_SEC))
        self._base = None            # (accel_g, roll, pitch)
        self._move_count = 0
        self._last_move_t = 0.0
        self._rearm_at = 0.0         # 이 시각 전까지는 충격 감지를 하지 않는다

    # ────────────────────────────────────────── 공개 API
    def start(self):
        self._running = True
        notifier.start(self._log)
        threading.Thread(target=self._loop, daemon=True, name="Tipover").start()

    def stop(self):
        self._running = False

    def submit(self, cmd: str):
        """UI에서 온 사용자 명령. 스레드 어디서 불러도 안전하다."""
        with self._lock:
            self._pending_cmd = cmd
            self._pending_t = self._now()

    def snapshot(self):
        with self._lock:
            return self.state, self.ask_deadline, self.alert_sent

    # ────────────────────────────────────────── 내부
    def _emit(self, msg, level="INFO"):
        if self._log:
            self._log(msg, level)

    def _goto(self, state):
        with self._lock:
            self.state = state
        self._t_state = self._now()

    #: 사용자 명령 유효기간(초).
    #  매 틱마다 무조건 비우면, 명령이 상태 전이와 같은 틱에 도착했을 때
    #  그 상태가 처리하지 못하고 그대로 버려진다.
    #  "아니오(취소)"가 이렇게 유실되면 오신고가 그대로 나간다.
    CMD_TTL = 3.0

    def _peek_cmd(self):
        with self._lock:
            if self._pending_cmd and (self._now() - self._pending_t) > self.CMD_TTL:
                self._pending_cmd = None      # 오래된 명령은 폐기
            return self._pending_cmd

    def _consume_cmd(self):
        with self._lock:
            self._pending_cmd = None

    def _loop(self):
        period = 1.0 / TICK_HZ
        next_t = time.monotonic()
        while self._running:
            try:
                self._tick(imu_source.snapshot(), gps_source.snapshot())
            except Exception as e:
                self._emit(f"[판정] 예외: {type(e).__name__}: {e}", "ERROR")
            next_t += period
            time.sleep(max(0.0, next_t - time.monotonic()))

    def step(self, imu: ImuSample, gps: GpsFix):
        """한 틱 실행. 오프라인 재생(tools/replay.py)에서 직접 호출한다."""
        self._tick(imu, gps)

    def _tick(self, imu: ImuSample, gps: GpsFix):
        now = self._now()
        cmd = self._peek_cmd()

        if cmd == CMD_RESET and self.state == TIPOVER_REPORTED:
            self._consume_cmd()
            self._reset("사용자 리셋")
            return

        # ── SOS: 사용자가 직접 부르는 긴급 호출 ──────────
        #   판정 단계를 전부 건너뛴다. 몸을 못 움직이지만 의식은 있는 경우,
        #   또는 전도가 아닌 다른 응급 상황(현기증, 흉통 등)을 위한 경로다.
        #   자동 감지만으로는 이런 상황을 절대 잡을 수 없다.
        if cmd == CMD_SOS and self.state != TIPOVER_REPORTED:
            self._consume_cmd()
            self._emit("🆘 SOS — 사용자 요청으로 즉시 신고합니다", "ERROR")
            self._peak_g = max(self._peak_g, imu.accel_g if imu.valid else 0.0)
            self._goto(TIPOVER_CONFIRMED)
            return

        # "아니오(취소)"는 판정이 진행 중인 어느 단계에서든 받아들인다.
        # 팝업이 뜨기 직전에 눌러도, 상태 전이와 같은 틱에 도착해도 유실되지 않는다.
        if cmd == CMD_USER_NO and self.state in (TIPOVER_STABILIZING, TIPOVER_CHECKING,
                                                 TIPOVER_ASKING):
            self._consume_cmd()
            self._emit("사용자 취소 — 신고하지 않습니다", "INFO")
            notifier.send_cancelled("사용자가 '괜찮음'을 선택했습니다")
            self._reset()
            return

        # IMU가 죽었으면 판정을 진행할 수 없다. 진행 중이던 판정은 유지한다.
        if not imu.valid:
            return

        self._hist.append((imu.accel_g, imu.roll_deg, imu.pitch_deg))
        st = self.state

        # ── 평상시 ────────────────────────────────────
        if st == TIPOVER_NORMAL:
            if now < self._rearm_at:
                return          # 해제 직후 재트리거 방지 (반복 통보 차단)
            if imu.accel_g >= config.IMPACT_THRESHOLD_G:
                self._peak_g = imu.accel_g
                self._goto(TIPOVER_STABILIZING)
                self._emit(f"충격 감지 {imu.accel_g:.2f}g — 안정화 대기", "WARN")
                # [H2] 즉시 예비 알림. 보호자가 지금부터 움직일 수 있다.
                notifier.send_preliminary(imu, gps, gps_source.position_age())

        # ── 충격 감지 (안정화 대기) ───────────────────
        elif st == TIPOVER_STABILIZING:
            self._peak_g = max(self._peak_g, imu.accel_g)
            if now - self._t_state >= config.STABILIZE_TIME:
                tilt = imu.tilt_deg
                # [C5] ★ 핵심 관문: 쓰러져 있지 않으면 사고가 아니다
                if tilt < config.TIPOVER_TILT_DEG:
                    self._emit(f"기울기 {tilt:.0f}° — 서 있는 상태. "
                               f"단순 충격으로 판단하여 해제합니다.", "INFO")
                    notifier.send_cancelled(
                        f"기울기 {tilt:.0f}°로 정상 자세 확인 (충격 {self._peak_g:.2f}g)")
                    self._reset()
                    return
                self._base = self._avg()
                self._move_count = 0
                self._last_move_t = 0.0
                self._goto(TIPOVER_CHECKING)
                self._emit(f"기울기 {tilt:.0f}° — 쓰러짐 자세. 움직임 관찰 시작", "WARN")

        # ── 움직임 분석중 ─────────────────────────────
        elif st == TIPOVER_CHECKING:
            if self._is_moving(imu, now):
                self._move_count += 1
                self._last_move_t = now
                self._base = self._avg()
                self._emit(f"움직임 감지 ({self._move_count}/"
                           f"{config.REQUIRED_MOVE_COUNT})", "INFO")
                if self._move_count >= config.REQUIRED_MOVE_COUNT:
                    self._emit("의식 있는 움직임 확인 — 해제", "INFO")
                    notifier.send_cancelled("스스로 움직이는 것이 확인되었습니다")
                    self._reset()
                    return
            # 자세가 정상으로 돌아왔으면 일어난 것이다
            if imu.tilt_deg < config.TIPOVER_TILT_DEG * 0.6:
                self._emit("정상 자세로 복귀 — 해제", "INFO")
                notifier.send_cancelled("정상 자세로 복귀했습니다")
                self._reset()
                return
            if now - self._t_state >= config.CHECK_TIME:
                with self._lock:
                    self.ask_deadline = now + config.ASK_TIMEOUT
                self._goto(TIPOVER_ASKING)
                self._emit(f"움직임 없음 — 사용자 확인 요청 "
                           f"({config.ASK_TIMEOUT:.0f}초)", "WARN")

        # ── 응답 대기 ─────────────────────────────────
        elif st == TIPOVER_ASKING:
            if cmd == CMD_USER_YES or now >= (self.ask_deadline or now):
                why = "사용자 확인" if cmd == CMD_USER_YES else "무응답"
                self._consume_cmd()
                self._emit(f"사고 확정 ({why}) — 보호자에게 신고합니다", "ERROR")
                self._goto(TIPOVER_CONFIRMED)

        # ── 사고 확정 → 신고 ──────────────────────────
        elif st == TIPOVER_CONFIRMED:
            if not self.alert_sent:
                notifier.send_confirmed(imu, gps, gps_source.position_age(),
                                        self._peak_g)
                with self._lock:
                    self.alert_sent = True
                    self.ask_deadline = None
            self._goto(TIPOVER_REPORTED)

        # ── 신고 완료 (사용자 리셋 대기) ──────────────
        elif st == TIPOVER_REPORTED:
            pass

    # ────────────────────────────────────────── 보조
    def _avg(self):
        """[H6] 한 샘플이 아니라 최근 구간 평균을 기준점으로 쓴다."""
        if not self._hist:
            return (1.0, 0.0, 0.0)
        n = len(self._hist)
        a = sum(h[0] for h in self._hist) / n
        r = sum(h[1] for h in self._hist) / n
        p = sum(h[2] for h in self._hist) / n
        return (a, r, p)

    def _is_moving(self, imu: ImuSample, now: float) -> bool:
        # [H6] 이벤트 사이 최소 간격을 요구한다.
        #      이게 없으면 100 Hz에서 연속된 노이즈 2샘플로 전도 판정이 취소된다.
        if now - self._last_move_t < config.MOVE_MIN_INTERVAL:
            return False
        if self._base is None:
            return False
        ba, br, bp = self._base
        return (abs(imu.accel_g - ba) > config.MOVE_ACCEL_TOL_G
                or _angle_diff(imu.roll_deg, br) > config.MOVE_ANGLE_TOL_DEG
                or _angle_diff(imu.pitch_deg, bp) > config.MOVE_ANGLE_TOL_DEG
                or imu.gyro_dps > config.MOVE_GYRO_TOL_DPS)

    def _reset(self, note=None, cooldown=True):
        with self._lock:
            self.state = TIPOVER_NORMAL
            self.ask_deadline = None
            self.alert_sent = False
        now = self._now()
        self._t_state = now
        self._peak_g = 0.0
        self._move_count = 0
        self._base = None
        self._rearm_at = now + config.REARM_COOLDOWN if cooldown else 0.0
        if note:
            self._emit(f"상태 초기화 ({note})", "INFO")


def _angle_diff(a, b) -> float:
    d = abs(a - b) % 360.0
    return 360.0 - d if d > 180.0 else d
